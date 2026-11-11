"""Owner-triggered update of an official Flower installation started by hand."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from threading import Event, Lock, Thread
import time

from flow_of_work_mcp import installation_fence as fence
from flow_of_work_mcp import managed_service as service
from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp import managed_upgrade_install as installer
from flow_of_work_mcp import release_upgrade as release
from flow_of_work_mcp.dashboard_maintenance import DashboardMaintenance
from flow_of_work_mcp.managed_upgrade import _verified_backup
from flow_of_work_mcp.runtime_ownership import acquire_file_ownership


_PREPARATION_SECONDS = 600
_HANDOFF_SECONDS = 30
_LOCK_SECONDS = 20


def _error(code: str, message: str) -> service.ServiceError:
    return service.ServiceError(code, message)


def _code(error: Exception) -> str:
    code = getattr(error, "code", None) or getattr(error, "reason", None)
    return code if isinstance(code, str) and len(code) <= 96 else "upgrade_manual_failed"


def _write(control: Path, value: dict, **changes) -> dict:
    result = {**value, **changes}
    secure.write_owned(control / "manual-upgrade.json", service._json_bytes(result))
    return result


def _public_receipt(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {key: value[key] for key in (
        "id", "version", "previous_version", "phase", "backup_directory", "reason",
    )}


def manual_upgrade_status() -> dict:
    environment = fence._environment()
    if environment is None:
        raise _error("upgrade_installation_unproved", "Use the official Flower installation to read its manual update receipt.")
    return {"operation": _public_receipt(fence.read_manual_upgrade(environment))}


def _basis(config: Path, database: Path) -> tuple[release._Installation, release._Profile]:
    if sys.platform != "darwin":
        raise _error("upgrade_platform_unsupported", "Dashboard updates for manual starts are available on macOS.")
    installed = release._installation()
    if fence.read_enrollment() is not None:
        raise _error("upgrade_managed_installation", "Use the managed service to update this dedicated installation.")
    _, profile = installer._matching_profile(config, database)
    return installed, profile


def _pin(installed: release._Installation, profile: release._Profile) -> dict:
    return {"previous_version": installed.version, "installed_receipt": installed.receipt_digest,
            "config": str(profile.config), "config_revision": profile.revision,
            "config_identity": list(profile.config_identity), "database": str(profile.database),
            "database_identity": list(profile.database_identity)}


def _verify_basis(value: dict) -> tuple[release._Installation, release._Profile]:
    installed, profile = _basis(Path(value["config"]), Path(value["database"]))
    if any(value[key] != expected for key, expected in _pin(installed, profile).items()):
        raise _error("upgrade_selection_changed", "The reviewed installation or profile changed.")
    return installed, profile


@dataclass
class _ShutdownHandoff:
    operation_id: str
    response_sent: Event = field(default_factory=Event)
    authorize: Callable[[], None] | None = None


class ManualUpgradeController:
    def __init__(self, config: Path, database: Path, maintenance: DashboardMaintenance,
                 request_shutdown: Callable[[], None]) -> None:
        self.config, self.database = config, database
        self.maintenance, self.request_shutdown = maintenance, request_shutdown
        self._lock = Lock()
        self._preview: tuple[float, dict] | None = None
        self._handoff: _ShutdownHandoff | None = None

    def status(self) -> dict:
        try:
            installed, profile = _basis(self.config, self.database)
            value = fence.read_manual_upgrade(installed.target)
            own = value is None or value["config"] == str(profile.config)
            pending = value is not None and value["phase"] not in {"complete", "preflight_failed"}
            return {"mode": "manual", "available": not pending, "installed_version": installed.version,
                    "operation": _public_receipt(value) if own else None,
                    **({"reason": "upgrade_already_pending"} if pending else {})}
        except (OSError, ValueError) as exc:
            return {"mode": "manual", "available": False, "operation": None, "reason": _code(exc)}

    def preview(self, version: str) -> dict:
        with self._lock:
            self._preview = None
            try:
                installed, profile = _basis(self.config, self.database)
                if release._version(version) <= release._version(installed.version):
                    raise _error("upgrade_version_not_newer", "Select a newer official Flower version.")
                fence._assert_manual_admitted(installed.target)
                value = {"contract": fence.MANUAL_UPGRADE_CONTRACT, "id": secrets.token_hex(16),
                         "version": version, "phase": "queued", "backup_directory": "", "reason": "",
                         **_pin(installed, profile)}
                self._preview = time.monotonic() + 300, value
                return {"id": value["id"], "version": version, "installed_version": installed.version,
                        "mode": "manual"}
            except (OSError, ValueError) as exc:
                raise _error(_code(exc), str(exc) if isinstance(exc, service.ServiceError) else
                             "Review the installed version and selected profile.") from None

    def apply(self, operation_id: str) -> dict:
        with self._lock:
            preview, self._preview = self._preview, None
            if preview is None or preview[0] < time.monotonic() or preview[1]["id"] != operation_id:
                raise _error("upgrade_preview_expired", "Review the selected version again before applying it.")
            value = preview[1]
            try:
                installed, _ = _verify_basis(value)
                control = fence._private_control(installed.target, create=True)
                with acquire_file_ownership(control / "manual-operation"):
                    fence._assert_manual_admitted(installed.target)
                    directory = control / "manual-operations" / operation_id
                    secure.ensure_directory(directory.parent)
                    directory.mkdir(mode=0o700)
                    installer.assert_private_archive_directory(directory)
                    _write(control, value)
                    try:
                        self._handoff = self._dispatch(directory, operation_id)
                    except OSError:
                        value = _write(control, value, phase="preflight_failed", reason="upgrade_dispatch_failed")
            except (OSError, ValueError) as exc:
                raise _error(_code(exc), "The reviewed manual update could not be started.") from None
            return {"operation": _public_receipt(value), "mode": "manual"}

    def after_response(self, operation_id: str, authorize: Callable[[], None]) -> None:
        """Only a sent HTTP acknowledgement may give the worker a shutdown grant."""
        handoff = self._handoff
        if handoff is not None and handoff.operation_id == operation_id:
            handoff.authorize = authorize
            handoff.response_sent.set()

    def _dispatch(self, directory: Path, operation_id: str) -> _ShutdownHandoff:
        parent, child = socket.socketpair()
        try:
            with child, os.fdopen(os.open(directory / "worker.log",
                                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as log:
                process = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-m", __name__, "--operation-id", operation_id,
                     "--channel", str(child.fileno())],
                    cwd=directory, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, pass_fds=(child.fileno(),),
                )
            handoff = _ShutdownHandoff(operation_id)
            Thread(target=self._watch, args=(parent, process, handoff), daemon=True,
                   name="flower-manual-upgrade-handoff").start()
            return handoff
        except BaseException:
            parent.close()
            raise

    def _watch(self, channel: socket.socket, process: subprocess.Popen, handoff: _ShutdownHandoff) -> None:
        try:
            with channel:
                channel.settimeout(_PREPARATION_SECONDS)
                if channel.recv(1) != b"R" or not handoff.response_sent.wait(_HANDOFF_SECONDS):
                    return
                if handoff.authorize is None:
                    return
                with self.maintenance.exclusive(until_shutdown=True):
                    handoff.authorize()
                    channel.sendall(b"S")
                    self.request_shutdown()
        except (OSError, RuntimeError, ValueError):
            # Closing the channel denies any ungranted stop. Once granted, a
            # still-running server retains the lease and prevents installation.
            pass
        finally:
            process.wait()


def _installation_lease(operation_id: str):
    deadline = time.monotonic() + _LOCK_SECONDS
    while True:
        try:
            lease = fence.manual_upgrade_lease(operation_id=operation_id)
        except fence.InstallationFenceError as exc:
            if exc.code != "installation_in_use":
                raise
            if time.monotonic() >= deadline:
                raise _error("upgrade_shutdown_unconfirmed", "Flower did not stop before installation.") from None
            time.sleep(0.05)
        else:
            if lease is None:
                raise _error("upgrade_control_unavailable", "The installation lease is unavailable.")
            return lease


def run_manual_upgrade(operation_id: str, channel: socket.socket) -> None:
    environment = fence._environment()
    if environment is None:
        raise _error("upgrade_control_unavailable", "The official installation is unavailable.")
    control = fence._private_control(environment)
    value = fence.read_manual_upgrade(environment)
    if value is None or value["id"] != operation_id or value["phase"] != "queued":
        raise _error("upgrade_preview_expired", "The approved update is unavailable.")
    prepared = None
    try:
        value = _write(control, value, phase="preparing")
        _verify_basis(value)
        prepared = installer.prepare(Path(value["config"]), Path(value["database"]), value["version"],
                                     control / "manual-operations" / operation_id)
        _verify_basis(value)
        value = _write(control, value, phase="stopping")
        channel.settimeout(_HANDOFF_SECONDS)
        channel.sendall(b"R")
        if channel.recv(1) != b"S":
            raise _error("upgrade_stop_not_authorized", "Flower could not enter the shutdown window.")
        with _installation_lease(operation_id):
            _verify_basis(value)
            release._check_stopped(prepared.profile, prepared.installation, prepared.selection)
            value = _write(control, value, phase="installing")
            outcome = installer.apply(prepared)
            _write(control, value, phase="complete", backup_directory=_verified_backup(prepared, outcome))
    except Exception as exc:
        _write(control, value, phase="failed" if value["phase"] == "installing" else "preflight_failed",
               backup_directory=_verified_backup(prepared), reason=_code(exc))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--channel", required=True, type=int)
    args = parser.parse_args(argv)
    with socket.socket(fileno=args.channel) as channel:
        run_manual_upgrade(args.operation_id, channel)


if __name__ == "__main__":
    main()
