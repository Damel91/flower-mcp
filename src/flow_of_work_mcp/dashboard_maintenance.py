"""Local operator maintenance under the running Flower ledger lease."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from pathlib import Path
from threading import Condition, Lock
from types import SimpleNamespace
from uuid import UUID

from mcp.types import CallToolResult, TextContent

from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.native_project_purge import pending_project_purges, run_project_purge


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
        self._result = None
        self._message = ''
        self._recover_existing()

    def status(self) -> dict:
        with self._condition:
            return {'state': self._state, 'project_id': self._intent[0] if self._intent else None,
                    'deletion_id': self._intent[1] if self._intent else None,
                    'result': deepcopy(self._result), 'message': self._message}

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
                self._message = 'An unfinished deletion requires inspection of the original intent.'
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

    def _resume(self):
        # Another unfinished journal must never be hidden by completing this one.
        pending = pending_project_purges(self.config_path, self.runtime.runtime_ownership)
        if pending:
            first = pending[0]
            with self._condition:
                self._intent = (first['project_id'], first['deletion_id'])
                self._state = 'recovery_required'
                self._message = 'Another unfinished deletion requires inspection.'
            return
        self.runtime.jobs.resume()
        with self._condition:
            self._state = 'ready'
            self._intent = None
            self._message = ''

    def operate(self, project_id: str, operation: str, body: dict, *,
                authorize_delete: Callable[[], None] | None = None) -> dict:
        project_id = validate_project_id(project_id)
        common = {'deletion_id'}
        extra = {'delete': {'expected_fingerprint', 'confirm_project_id', 'host_quiescence_ref', 'host_stopped_run_ids'},
                 'reconcile': {'expected_fingerprint'}}
        if operation not in {'prepare', 'inspect', 'delete', 'reconcile', 'cancel'}:
            raise ValueError('dashboard_deletion_operation_invalid')
        if set(body) - (common | extra.get(operation, set())):
            raise ValueError('dashboard_deletion_fields_invalid')
        deletion_id = body.get('deletion_id')
        if not isinstance(deletion_id, str) or str(UUID(deletion_id)) != deletion_id:
            raise ValueError('dashboard_deletion_id_invalid')
        for key in ('expected_fingerprint', 'confirm_project_id', 'host_quiescence_ref'):
            if key in body and (not isinstance(body[key], str) or len(body[key]) > 256):
                raise ValueError('dashboard_deletion_field_invalid')
        runs = body.get('host_stopped_run_ids', [])
        if not isinstance(runs, list) or len(runs) > 64 or any(not isinstance(run, str) for run in runs):
            raise ValueError('dashboard_host_runs_invalid')
        identity = (project_id, deletion_id)
        with self._administration:
            if self._state != 'ready' and self._intent != identity:
                raise MaintenanceUnavailable('maintenance_other_intent_or_journal_recovery')
            if operation == 'delete':
                if authorize_delete is None:
                    raise ValueError('dashboard_delete_authorization_required')
                authorize_delete()
            if self._state == 'ready':
                self._begin()
                with self._condition:
                    self._intent = identity
            # A controller may be composed over a runtime with an existing job.
            # Recovery never substitutes a journal for actual local quiescence.
            if not self.runtime.jobs.pause_if_idle():
                raise MaintenanceUnavailable('maintenance_jobs_busy')
            args = SimpleNamespace(config=self.config_path, profile=None, profile_root=None,
                project_id=project_id, deletion_id=deletion_id,
                purge_operation='inspect' if operation == 'cancel' else operation,
                expected_fingerprint=body.get('expected_fingerprint', ''),
                confirm_project_id=body.get('confirm_project_id', ''),
                host_quiescence_ref=body.get('host_quiescence_ref', ''),
                host_stopped_run_id=runs, acknowledge_host_cleanup=False)
            result, _ = run_project_purge(args, ownership=self.runtime.runtime_ownership)
            with self._condition:
                self._result = result
            stage = result['deletion_state']
            if operation == 'cancel':
                if result['status'] == 'success' and stage in {'prepared', 'unprepared'} and result['project_effect_state'] == 'none':
                    self._resume()
                else:
                    with self._condition:
                        self._state = 'recovery_required'
                        self._message = 'Deletion may have started. Inspect or reconcile the same intent before normal service resumes.'
            elif result['status'] == 'success' and stage == 'scrubbed':
                self._resume()
            elif stage in {'deleting', 'ledger_deleted', 'unknown'}:
                with self._condition:
                    self._state = 'recovery_required'
                    self._message = 'Inspect or reconcile this same deletion intent.'
            return {'maintenance': self.status(), 'deletion': result}
