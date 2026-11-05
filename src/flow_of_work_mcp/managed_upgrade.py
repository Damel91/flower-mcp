"""Owner-scoped macOS upgrade control and independent launchd worker."""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
import os
from pathlib import Path
import plistlib
import re
import secrets
import sys
from threading import Lock
import time

from flow_of_work_mcp import managed_service as service
from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.installation_fence import (
    InstallationFenceError, enroll_installation, environment_lease, load_installation, read_enrollment, read_upgrade,
)
from flow_of_work_mcp.release_upgrade import _installation, _version
from flow_of_work_mcp.config import load_config_with_revision
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_file_ownership

CONTRACT = "flower.managed-upgrade.v1"
_ACTIVE = {"queued", "stopping", "installing", "restarting", "failed"}
_KEYS = {"contract", "id", "service_key", "version", "previous_version", "phase",
         "generation", "config_revision", "backup_directory", "reason"}
_HEX = re.compile(r"[a-f0-9]{32}")
_DIGEST = re.compile(r"[a-f0-9]{64}")


def _fail(code, message):
    raise service.ServiceError(code, message)


def _domain(selection):
    return "gui/" + selection.owner["value"]


def _native_pid(selection, label):
    result = service._call(selection, ["print", f"{_domain(selection)}/{label}"], allow_failure=True)
    if result.returncode:
        return None
    # launchd's root job properties are indented by one tab. Ignore nested
    # properties such as a responsible or parent process.
    matches = re.findall(r"^\tpid = ([1-9][0-9]*)$", result.stdout, re.M)
    return int(matches[0]) if len(matches) == 1 else None


def _binding(selection):
    if selection.platform != "macos":
        _fail("upgrade_platform_unsupported", "Automatic service upgrade is available on macOS.")
    binding = load_installation(selection.config, selection.database)
    if (binding.host, binding.port, binding.service_key) != (selection.host, selection.port, selection.key):
        _fail("upgrade_service_mismatch", "Use the service bound to this dedicated Flower installation.")
    return binding


def _journal(binding):
    value = read_upgrade(binding)
    if value is None:
        return None
    if (set(value) != _KEYS or not isinstance(value["generation"], str)
            or not _DIGEST.fullmatch(value["generation"])
            or not isinstance(value["config_revision"], str) or not _DIGEST.fullmatch(value["config_revision"])
            or not isinstance(value["reason"], str) or len(value["reason"]) > 96
            or not isinstance(value["backup_directory"], str) or len(value["backup_directory"]) > 4096):
        _fail("upgrade_receipt_invalid", "The retained upgrade receipt needs local inspection.")
    _version(value["version"])
    _version(value["previous_version"])
    return value


def _receipt(value):
    if value is None:
        return None
    return {key: value[key] for key in ("id", "version", "previous_version", "phase",
                                         "backup_directory", "reason")}


def _observed_receipt(selection, binding, value):
    receipt = _receipt(value)
    if (value is not None and value["phase"] in _ACTIVE - {"failed"}
            and time.time() - binding.journal.stat().st_mtime > 5
            and _native_pid(selection, _worker_label(selection, value["id"])) is None):
        return {**receipt, "reason": "upgrade_worker_unconfirmed"}
    return receipt


def _write(binding, value, **changes):
    value = {**value, **changes}
    secure.write_owned(binding.journal, service._json_bytes(value))
    return value


def _worker_label(selection, operation_id):
    if not isinstance(operation_id, str) or not _HEX.fullmatch(operation_id):
        _fail("upgrade_receipt_invalid", "The upgrade operation identifier is invalid.")
    return selection.key + ".upgrade-" + operation_id


def _stage_directory(binding, operation_id):
    return binding.journal.parent / "operations" / operation_id


def _dispatch(selection, binding, operation_id):
    from flow_of_work_mcp.ledger_archive import assert_private_archive_directory
    stage = _stage_directory(binding, operation_id)
    secure.ensure_directory(stage.parent)
    stage.mkdir(mode=0o700)
    assert_private_archive_directory(stage)
    label = _worker_label(selection, operation_id)
    definition = stage / "worker.plist"
    secure.write_owned(definition, plistlib.dumps({
        "Label": label,
        "ProgramArguments": [selection.command[0], "-I", "-B", "-m", "flow_of_work_mcp.managed_upgrade",
                             "--manifest", str(selection.manifest), "--operation-id", operation_id],
        "WorkingDirectory": str(stage),
        "RunAtLoad": False,
        "KeepAlive": False,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(stage / "worker.stdout.log"),
        "StandardErrorPath": str(stage / "worker.stderr.log"),
    }))
    domain = _domain(selection)
    service._call(selection, ["bootstrap", domain, str(definition)])
    try:
        service._call(selection, ["kickstart", domain + "/" + label])
    except Exception:
        # The operation lock is still held by the submitter. No worker can
        # advance the receipt before it is marked as a preflight failure.
        service._call(selection, ["bootout", domain + "/" + label], allow_failure=True)
        raise


def _current(selection, instance_id=None):
    record = service._load(selection)
    state = service._state(selection)
    if (record["registration"] != "installed" or state is None
            or (instance_id is not None and state["instance_id"] != instance_id)
            or state["pid"] != _native_pid(selection, selection.key)
            or not service._ready(selection, state)):
        _fail("upgrade_service_not_ready", "Start the selected managed Flower service before upgrading.")
    return record, state


def _validate_target(version):
    target = _version(version)
    previous = _installation().version
    if target <= _version(previous):
        _fail("upgrade_version_not_newer", "Select a stable official version newer than the installed release.")
    return previous


def _intent(selection, binding, version, instance_id):
    current = _journal(binding)
    if current is not None and current["phase"] in _ACTIVE:
        _fail("upgrade_already_pending", "Inspect the retained upgrade before submitting another request.")
    _, state = _current(selection, instance_id)
    previous = _validate_target(version)
    config, revision = load_config_with_revision(selection.config)
    if config.runtime.database_path != selection.database:
        _fail("upgrade_selection_changed", "The selected service configuration changed.")
    return {"contract": CONTRACT, "id": secrets.token_hex(16), "service_key": selection.key,
            "version": version, "previous_version": previous, "phase": "queued",
            "generation": state["generation"], "config_revision": revision, "backup_directory": "", "reason": ""}


def _submit(selection, binding, reviewed, instance_id):
    with acquire_file_ownership(selection.manifest, suffix=".operation.lock"):
        current = _intent(selection, binding, reviewed["version"], instance_id)
        if {**current, "id": reviewed["id"]} != reviewed:
            _fail("upgrade_selection_changed", "The reviewed upgrade changed. Review the current version and service again.")
        _write(binding, reviewed)
        try:
            _dispatch(selection, binding, reviewed["id"])
        except Exception:
            failed = _write(binding, reviewed, phase="preflight_failed", reason="upgrade_dispatch_failed")
            return {"operation": _receipt(failed)}
        return {"operation": _receipt(reviewed)}


def _external_failure(error):
    code = getattr(error, "code", None)
    return service.ServiceError(code if isinstance(code, str) else "upgrade_control_unavailable",
                                "The selected service upgrade cannot proceed; inspect the local upgrade receipt.")


class UpgradeController:
    def __init__(self, config_path: Path, host: str, port: int, instance_id: str):
        self.config_path, self.host, self.port, self.instance_id = config_path, host, port, instance_id
        self._lock = Lock()
        self._preview = None

    def _select(self):
        selection = service._select(self.config_path, self.host, self.port)
        return selection, _binding(selection)

    def status(self):
        try:
            selection, binding = self._select()
            operation = _journal(binding)
            result = {"available": False, "operation": _observed_receipt(selection, binding, operation)}
            if operation is not None and operation["phase"] in _ACTIVE:
                return {**result, "reason": "upgrade_already_pending"}
            try:
                _current(selection, self.instance_id)
                return {**result, "available": True, "installed_version": _installation().version}
            except (OSError, ValueError, RuntimeOwnershipError) as exc:
                return {**result, "reason": _external_failure(exc).code}
        except (OSError, ValueError, RuntimeOwnershipError) as exc:
            return {"available": False, "reason": _external_failure(exc).code, "operation": None}

    def preview(self, version):
        with self._lock:
            try:
                selection, binding = self._select()
                value = _intent(selection, binding, version, self.instance_id)
                self._preview = (time.monotonic() + 300, value)
                return {"id": value["id"], "version": value["version"],
                        "installed_version": value["previous_version"]}
            except (OSError, ValueError, RuntimeOwnershipError) as exc:
                raise _external_failure(exc) from None

    def apply(self, operation_id):
        with self._lock:
            current, self._preview = self._preview, None
            if current is None or current[0] < time.monotonic() or operation_id != current[1]["id"]:
                _fail("upgrade_preview_expired", "Review the selected version again before applying it.")
            try:
                selection, binding = self._select()
                return _submit(selection, binding, current[1], self.instance_id)
            except (OSError, ValueError, RuntimeOwnershipError) as exc:
                raise _external_failure(exc) from None


def native_operation(action, config, host, port, version=None):
    try:
        selection = service._select(config, host, port)
        if action == "enroll-upgrade":
            if selection.platform != "macos":
                _fail("upgrade_platform_unsupported", "Automatic service upgrade is available on macOS.")
            if os.path.lexists(selection.manifest) or os.path.lexists(selection.definition):
                _fail("upgrade_enrollment_requires_new_service", "Enroll the dedicated installation before registering its service.")
            enroll_installation(selection.config, selection.database, host=host, port=port, service_key=selection.key)
            return {"enrolled": True, "service_id": selection.key}
        binding = _binding(selection)
        if action == "upgrade-status":
            return {"operation": _observed_receipt(selection, binding, _journal(binding))}
        value = _intent(selection, binding, version, None)
        return _submit(selection, binding, value, None)
    except (OSError, ValueError, RuntimeOwnershipError) as exc:
        raise _external_failure(exc) from None


def guard_operator(selection):
    binding = read_enrollment()
    if binding is None:
        return
    binding = _binding(selection)
    current = _journal(binding)
    if current is not None and current["phase"] in _ACTIVE:
        _fail("upgrade_already_pending", "The managed upgrade fences service changes. Inspect its receipt.")


def supervised_restart(binding):
    try:
        selection = service._select(binding.config, binding.host, binding.port)
        return (selection.platform == "macos" and selection.key == binding.service_key
                and _native_pid(selection, selection.key) == os.getpid())
    except (OSError, ValueError):
        return False


def runner_token(selection):
    binding = read_enrollment()
    if binding is None:
        return None
    binding = _binding(selection)
    current = _journal(binding)
    if current is None or current["phase"] not in _ACTIVE:
        return None
    if current["phase"] != "restarting" or _native_pid(selection, selection.key) != os.getpid():
        _fail("upgrade_already_pending", "Only the selected launchd service can restart during this upgrade.")
    return current["id"]


@contextmanager
def _operation_lock(selection):
    # The submitter holds the native-operation lock while launchd accepts the
    # worker. Wait only for this bounded admission handoff.
    deadline = time.monotonic() + 12
    while True:
        try:
            lease = acquire_file_ownership(selection.manifest, suffix=".operation.lock")
        except RuntimeOwnershipError as exc:
            if exc.code != "resource_in_use" or time.monotonic() >= deadline:
                raise
            time.sleep(.05)
        else:
            break
    with lease:
        yield


@contextmanager
def _exclusive_for_install(binding):
    # A start admitted just before the request may still be draining its
    # now-rejected startup. Do not install until the exclusive lease is held.
    deadline = time.monotonic() + 4
    while True:
        try:
            lease = environment_lease(binding)
        except InstallationFenceError as exc:
            if exc.code != "installation_in_use" or time.monotonic() >= deadline:
                raise
            time.sleep(.05)
        else:
            break
    with lease:
        yield


def _verify_basis(selection, value, *, installed_version=None):
    config, revision = load_config_with_revision(selection.config)
    if (revision != value["config_revision"] or config.runtime.database_path != selection.database
            or _installation().version != (installed_version or value["previous_version"])):
        _fail("upgrade_selection_changed", "The selected profile or installed version changed after review.")


def _verified_backup(prepared, outcome=None):
    if outcome is not None:
        return outcome["backup"]["backup_directory"]
    if prepared is None:
        return ""
    # A failed pip run can still leave a complete installer backup. Report
    # only a verified copy, never an empty staging directory as a backup.
    from flow_of_work_mcp.managed_upgrade_install import _verify_backup
    try:
        entries = list(prepared.backup_root.iterdir())
        if len(entries) == 1:
            backup = json.loads(secure.read_owned(entries[0] / "upgrade.json"))
            _verify_backup(prepared, backup)
            return str(entries[0])
    except Exception:
        pass
    return ""


def _work(selection, binding, operation_id):
    from flow_of_work_mcp.managed_upgrade_install import apply, prepare
    with _operation_lock(selection):
        value = _journal(binding)
        if value is None or value["id"] != operation_id or value["phase"] != "queued":
            return
        stopped = False
        prepared = None
        backup = ""
        try:
            _verify_basis(selection, value)
            prepared = prepare(selection.config, selection.database, value["version"],
                               _stage_directory(binding, operation_id))
            _verify_basis(selection, value)
            record, state = _current(selection)
            if state["generation"] != value["generation"]:
                _fail("upgrade_selection_changed", "The admitted service generation changed.")
            value = _write(binding, value, phase="stopping")
            stopped = True  # Once stop is requested its failure is uncertain.
            service._stop(selection, record)
            with _exclusive_for_install(binding):
                _verify_basis(selection, value)
                value = _write(binding, value, phase="installing")
                outcome = apply(prepared)
                backup = _verified_backup(prepared, outcome)
                value = _write(binding, value, phase="restarting", backup_directory=backup)
            _verify_basis(selection, value, installed_version=value["version"])
            service._start(selection, record)
            _, state = _current(selection)
            _verify_basis(selection, value, installed_version=value["version"])
            if state["generation"] == value["generation"]:
                _fail("upgrade_restart_unconfirmed", "The updated managed service identity could not be confirmed.")
            _write(binding, value, phase="complete")
        except Exception as error:
            if value["phase"] == "restarting":
                try:
                    service._stop(selection, service._load(selection))
                except Exception:
                    error = service.ServiceError("upgrade_restart_unsettled", "Inspect the retained service and upgrade state.")
            _write(binding, value, phase="failed" if stopped else "preflight_failed",
                   backup_directory=backup or _verified_backup(prepared),
                   reason=_external_failure(error).code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--operation-id", required=True)
    args = parser.parse_args(argv)
    record = service._read_json(args.manifest)
    selection = service._select(Path(record["config"]), record["host"], record["port"])
    if selection.manifest != args.manifest:
        _fail("upgrade_service_mismatch", "The upgrade worker's managed service binding does not match.")
    binding = _binding(selection)
    label = _worker_label(selection, args.operation_id)
    if _native_pid(selection, label) != os.getpid():
        _fail("upgrade_worker_unproved", "The upgrade must run in the owned launchd worker.")
    try:
        _work(selection, binding, args.operation_id)
    finally:
        service._call(selection, ["bootout", _domain(selection) + "/" + label], allow_failure=True)


if __name__ == "__main__":
    main()
