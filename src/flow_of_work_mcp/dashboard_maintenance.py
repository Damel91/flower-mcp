"""Local operator maintenance under the running Flower ledger lease."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import Condition, Lock

from mcp.types import CallToolResult, TextContent

from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.native_project_purge import pending_project_purges, run_dashboard_project_purge


class MaintenanceUnavailable(RuntimeError):
    pass


class DashboardMaintenance:
    """Fence calls and idle jobs, retaining the runtime and its exclusive lease."""

    def __init__(self, runtime, config_path: Path, *, drain_timeout: float = 5.0):
        self.runtime = runtime
        self.config_path = config_path.absolute()
        self.drain_timeout = drain_timeout
        self._condition = Condition()
        self._administration = Lock()
        self._active = 0
        self._state = 'ready'
        self._intent = None
        self._message = ''
        self._recover_existing()

    def status(self) -> dict:
        with self._condition:
            return {'state': self._state, 'project_id': self._intent[0] if self._intent else None,
                    'deletion_id': self._intent[1] if self._intent else None,
                    'message': self._message}

    @contextmanager
    def admission(self):
        with self._condition:
            if self._state != 'ready':
                raise MaintenanceUnavailable('server_maintenance')
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def read(self, operation, *args, **kwargs):
        # Count inside the actual worker, including HTTP cancellation settlement.
        with self.admission():
            return operation(*args, **kwargs)

    def wrap_tool(self, function, name):
        @wraps(function)
        def invoke(*args, **kwargs):
            try:
                with self.admission():
                    return function(*args, **kwargs)
            except MaintenanceUnavailable:
                envelope = {'tool': name, 'status': 'blocked', 'reason': 'server_maintenance',
                    'result': {'status': 'blocked', 'reason': 'server_maintenance',
                        'retry_after_seconds': 2,
                        'recovery_guidance': 'Flower is in operator maintenance. Retry the same request after service resumes. Inspect any previously uncertain mutation; this refusal does not establish its earlier outcome.'},
                    'audit_reference': {}}
                return CallToolResult(content=[TextContent(type='text', text=project_markdown(name, envelope, arguments=kwargs))],
                                      structuredContent={'result': envelope}, isError=False)
        return invoke

    def _recover_existing(self):
        lease = self.runtime.runtime_ownership
        if lease is None:
            self._state = 'recovery_required'
            self._message = 'The runtime has no verified ledger ownership. Use the owning Flower HTTP entry point.'
            return
        try:
            pending = pending_project_purges(self.config_path, lease)
            if pending:
                first = pending[0]
                self._intent = (first['project_id'], first['deletion_id'])
                self._state = 'recovery_required'
                self._message = 'An earlier native deletion needs recovery. Stop Flower and reconcile the original intent with project-purge.'
                self.runtime.jobs.pause_if_idle()
        except Exception:
            self._state = 'recovery_required'
            self._message = 'The native deletion journal cannot be validated. Stop Flower and inspect its owned project-purge journal with native tools; preserve the original records.'
            self.runtime.jobs.pause_if_idle()

    def _begin(self):
        with self._condition:
            self._state = 'maintenance'
            drained = self._condition.wait_for(lambda: self._active == 0, timeout=self.drain_timeout)
            if not drained:
                self._state = 'ready'
                raise MaintenanceUnavailable('maintenance_requests_busy')
        if not self.runtime.jobs.pause_if_idle():
            with self._condition:
                self._state = 'ready'
            raise MaintenanceUnavailable('maintenance_jobs_busy')

    @contextmanager
    def exclusive(self, *, authorize: Callable[[], None] | None = None, until_shutdown: bool = False):
        """Drain admitted requests and pause idle workers for an owner operation."""
        if not self._administration.acquire(blocking=False):
            raise MaintenanceUnavailable('server_maintenance')
        try:
            if self._state != 'ready':
                raise MaintenanceUnavailable('maintenance_native_recovery_required')
            if authorize is not None:
                authorize()
            self._begin()
            completed = False
            try:
                yield
                completed = True
            finally:
                if not (completed and until_shutdown):
                    self.runtime.jobs.resume()
                    with self._condition:
                        self._state = 'ready'
        finally:
            self._administration.release()

    def operate(self, project_id: str, operation: str, body: dict, *,
                authorize_delete: Callable[[], None] | None = None,
                recheck_session: Callable[[], None] | None = None) -> dict:
        project_id = validate_project_id(project_id)
        if operation != 'delete':
            raise ValueError('dashboard_deletion_operation_invalid')
        if set(body) != {'confirm_project_id'} or body['confirm_project_id'] != project_id:
            raise ValueError('dashboard_deletion_fields_invalid')
        if authorize_delete is None:
            raise ValueError('dashboard_delete_authorization_required')
        with self.exclusive(authorize=authorize_delete):
            if recheck_session is not None:
                recheck_session()
            result, _ = run_dashboard_project_purge(
                self.config_path, project_id, ownership=self.runtime.runtime_ownership,
            )
        return {'maintenance': self.status(), 'deletion': result}
