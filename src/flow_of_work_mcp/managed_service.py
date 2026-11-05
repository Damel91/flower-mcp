"""Optional owner-session service management with same-process graceful stop.

The protected control directory is local process-control state, not lifecycle
authority. No operation adds a user account, stores passwords, or modifies data.
"""
from __future__ import annotations

import _thread
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import plistlib
import secrets
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.config import load_config
from flow_of_work_mcp.dashboard_auth_native import NativeAuthFailure
from flow_of_work_mcp.runtime_ownership import acquire_file_ownership, acquire_runtime_ownership, RuntimeOwnershipError

CONTRACT = "flower.user-service.v1"
_BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('flow_of_work_mcp.managed_service',run_name='__main__')"
_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


class ServiceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _blocked(code, message):
    raise ServiceError(code, message)


def _native_identity():
    from flow_of_work_mcp.dashboard_auth_native import current_identity, platform_name
    return current_identity(), platform_name()


@dataclass(frozen=True)
class Selection:
    config: Path
    database: Path
    owner: dict
    platform: str
    host: str
    port: int
    key: str
    root: Path
    definition: Path

    @property
    def manifest(self):
        return self.root / "service.json"

    @property
    def command(self):
        package_root = str(Path(__file__).resolve().parents[1])
        return [str(Path(sys.executable).absolute()), "-I", "-c", _BOOTSTRAP,
                package_root, "run", "--manifest", str(self.manifest)]


def _select(config_path: Path, host: str, port: int) -> Selection:
    if host not in {"127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535:
        _blocked("service_endpoint_invalid", "Select an explicit loopback host and valid port.")
    config = Path(config_path).expanduser().absolute()
    if any(c in str(config) for c in "\x00\r\n"):
        _blocked("service_config_invalid", "Select a regular absolute configuration file.")
    owner, platform = _native_identity()
    if platform not in {"linux", "macos", "windows"} or owner.get("value") in {"0", "S-1-5-18", "S-1-5-19", "S-1-5-20"}:
        _blocked("service_owner_unsupported", "Managed startup requires the normal local data owner's account.")
    if platform == "windows" and str(config).startswith("\\\\"):
        _blocked("service_config_invalid", "Managed startup requires a host-local data path.")
    if secure.check_data_file(config) != owner:
        _blocked("service_owner_mismatch", "The selected data must belong to the execution account.")
    loaded = load_config(config)
    database = Path(loaded.runtime.database_path).absolute()
    if secure.check_data_file(database) != owner:
        _blocked("service_owner_mismatch", "The selected data must belong to the execution account.")
    fingerprint = hashlib.sha256((str(config) + "\0" + host + "\0" + str(port)).encode()).hexdigest()[:20]
    key = "ai.flower-mcp." + fingerprint
    root = config.parent / ".flower-service" / fingerprint
    if platform == "macos":
        home = Path.home().resolve()
        definition = home / "Library/LaunchAgents" / (key + ".plist")
    elif platform == "linux":
        home = Path.home().resolve()
        config_home = os.environ.get("XDG_CONFIG_HOME")
        directory = Path(config_home) if config_home else home / ".config"
        if not directory.is_absolute():
            _blocked("service_manager_unavailable", "The user service configuration directory must be absolute.")
        if any(c in str(directory) for c in "\x00\r\n"):
            _blocked("service_config_invalid", "The user service configuration directory is invalid.")
        definition = directory / "systemd/user" / (key + ".service")
    else:
        definition = root / "task.xml"
    return Selection(config, database, owner, platform, host, port, key, root, definition)


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _read_json(path):
    try:
        value = json.loads(secure.read_owned(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ServiceError("service_control_invalid", "Inspect the retained service control files.") from exc
    if not isinstance(value, dict):
        _blocked("service_control_invalid", "Inspect the retained service control files.")
    return value


def _definition(selection, enabled):
    if selection.platform == "macos":
        return plistlib.dumps({"Label": selection.key, "ProgramArguments": selection.command, "Umask": 0o077,
            "RunAtLoad": enabled, "KeepAlive": False, "ProcessType": "Background",
            "WorkingDirectory": str(selection.config.parent),
            "StandardOutPath": str(selection.root / "stdout.log"),
            "StandardErrorPath": str(selection.root / "stderr.log")}, sort_keys=True)
    if selection.platform == "linux":
        def quote(value, *, variable_expansion=True):
            quoted = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
            return '"' + (quoted.replace('$', '$$') if variable_expansion else quoted) + '"'
        return ("[Unit]\nDescription=Flower MCP owner service\n\n[Service]\nType=simple\nExecStart="
                + " ".join(quote(v) for v in selection.command)
                + "\nEnvironment=" + quote("XDG_CONFIG_HOME=" + str(selection.definition.parents[2]), variable_expansion=False)
                + "\nUMask=0077\nRestart=no\nKillSignal=SIGINT\nSendSIGKILL=no\nTimeoutStopSec=35\n"
                  "\n[Install]\nWantedBy=default.target\n").encode()
    task = ET.Element("Task", {"version": "1.2", "xmlns": _TASK_NS})
    registration = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(registration, "URI").text = "\\" + selection.key
    # The existing Task Scheduler needs SYSTEM access to its own registered
    # task object. This does not change the action's owner-only execution token
    # or the owner-only DACL on our control directory and manifest.
    ET.SubElement(registration, "SecurityDescriptor").text = f"D:P(A;;FA;;;SY)(A;;FA;;;{selection.owner['value']})"
    triggers = ET.SubElement(task, "Triggers")
    trigger = ET.SubElement(triggers, "LogonTrigger")
    ET.SubElement(trigger, "Enabled").text = str(enabled).lower()
    ET.SubElement(trigger, "UserId").text = selection.owner["value"]
    principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal", {"id": "Owner"})
    ET.SubElement(principal, "UserId").text = selection.owner["value"]
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(task, "Settings")
    for key, value in [("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                       ("StopIfGoingOnBatteries", "false"), ("AllowHardTerminate", "false"),
                       ("AllowStartOnDemand", "true"), ("Enabled", "true"), ("ExecutionTimeLimit", "PT0S")]:
        ET.SubElement(settings, key).text = value
    action = ET.SubElement(ET.SubElement(task, "Actions", {"Context": "Owner"}), "Exec")
    ET.SubElement(action, "Command").text = selection.command[0]
    ET.SubElement(action, "Arguments").text = subprocess.list2cmdline(selection.command[1:])
    ET.SubElement(action, "WorkingDirectory").text = str(selection.config.parent)
    # No RestartOnFailure element means RestartCount=0; trigger disabled at
    # install still permits an explicitly requested Run in the owner's session.
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def _tool(platform):
    if platform == "macos":
        path = Path("/bin/launchctl")
    elif platform == "linux":
        path = Path("/usr/bin/systemctl")
    else:
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
        kernel.GetSystemDirectoryW.restype = w.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not length or length >= len(buffer):
            _blocked("service_manager_unavailable", "The native user service manager is unavailable.")
        path = Path(buffer.value) / "schtasks.exe"
    if not path.is_file():
        _blocked("service_manager_unavailable", "The native user service manager is unavailable.")
    return str(path)


def _call(selection, arguments, *, allow_failure=False, timeout=10):
    try:
        result = subprocess.run([_tool(selection.platform), *arguments], capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError("service_manager_unavailable", "The native service-manager operation did not complete; inspect its existing registration.") from exc
    if result.returncode and not allow_failure:
        _blocked("service_manager_refused", "The native user service manager refused this operation; inspect the owned registration.")
    return result


def _record(selection, enabled, *, registration="prepared", native_digest=None):
    definition = _definition(selection, enabled)
    return {"contract": CONTRACT, "config": str(selection.config), "database": str(selection.database),
        "owner": selection.owner, "platform": selection.platform, "host": selection.host, "port": selection.port,
        "key": selection.key, "command": selection.command, "definition": str(selection.definition),
        "definition_sha256": hashlib.sha256(definition).hexdigest(), "autostart_enabled": enabled,
        "registration": registration, "native_definition_sha256": native_digest}


def _load(selection, *, inspect_definition=True):
    secure.ensure_directory(selection.root)
    record = _read_json(selection.manifest)
    expected = _record(selection, record.get("autostart_enabled"), registration=record.get("registration"),
                       native_digest=record.get("native_definition_sha256"))
    if (type(record.get("autostart_enabled")) is not bool or record != expected
        or record.get("registration") not in {"prepared", "installed"}):
        _blocked("service_registration_changed", "Service selection or its trusted manifest changed; inspect the existing registration.")
    if inspect_definition and hashlib.sha256(secure.read_owned(selection.definition)).hexdigest() != record["definition_sha256"]:
        _blocked("service_definition_changed", "The service definition was edited; it was not overwritten.")
    return record


def _task_digest(selection):
    result = _call(selection, ["/Query", "/TN", selection.key, "/XML"], allow_failure=True)
    if result.returncode:
        return None
    try:
        # Scheduler adds native defaults. Pin its canonical registered output,
        # not a byte comparison with our smaller input XML.
        root = ET.fromstring(result.stdout.lstrip("\ufeff"))
    except ET.ParseError as exc:
        raise ServiceError("service_definition_changed", "The existing task definition cannot be verified.") from exc
    return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()


def _launchd_loaded(selection, domain):
    result = _call(selection, ["print", domain], allow_failure=True)
    if not result.returncode:
        return True
    if "could not find service" in result.stderr.lower():
        return False
    _blocked("service_manager_unavailable", "The selected launchd registration could not be inspected.")


def _write_definition(selection, enabled):
    secure.ensure_directory(selection.definition.parent, private=selection.platform == "windows")
    secure.write_owned(selection.definition, _definition(selection, enabled), private_parent=selection.platform == "windows")


def _install(selection):
    secure.ensure_directory(selection.root)
    if selection.manifest.exists():
        record = _load(selection, inspect_definition=False)
        if record["registration"] == "installed":
            _load(selection)
            return record
        if selection.definition.exists() and hashlib.sha256(secure.read_owned(selection.definition)).hexdigest() != record["definition_sha256"]:
            _blocked("service_definition_changed", "The prepared service definition was edited; it was not overwritten.")
        if selection.platform == "windows" and _task_digest(selection) is not None:
            _blocked("service_installation_pending", "The task creation outcome is uncertain. Inspect the retained task before repair; it was not overwritten.")
    else:
        if selection.definition.exists() or selection.definition.is_symlink():
            _blocked("service_definition_conflict", "An unrecognized service definition already exists; it was not overwritten.")
        if selection.platform == "windows" and _task_digest(selection) is not None:
            _blocked("service_definition_conflict", "An unrecognized scheduled task already exists; it was not overwritten.")
        record = _record(selection, False)
        secure.write_owned(selection.manifest, _json_bytes(record))
    secure.write_owned(selection.root / "paused.json", _json_bytes({"contract": CONTRACT, "paused": True}))
    if not selection.definition.exists():
        _write_definition(selection, False)
    if selection.platform == "linux":
        _call(selection, ["--user", "daemon-reload"])
    elif selection.platform == "windows":
        _call(selection, ["/Create", "/TN", selection.key, "/XML", str(selection.definition)])
    digest = _task_digest(selection) if selection.platform == "windows" else None
    if selection.platform == "windows" and digest is None:
        _blocked("service_installation_pending", "The scheduled task registration needs inspection.")
    record = _record(selection, False, registration="installed", native_digest=digest)
    secure.write_owned(selection.manifest, _json_bytes(record))
    return record


def _set_enabled(selection, record, enabled):
    if record["registration"] != "installed":
        _blocked("service_installation_pending", "Complete inspection of the retained installation first.")
    if selection.platform == "windows":
        if _task_digest(selection) != record["native_definition_sha256"]:
            _blocked("service_definition_changed", "The scheduled task was edited; it was not overwritten.")
    _write_definition(selection, enabled)
    if selection.platform == "linux":
        _call(selection, ["--user", "enable" if enabled else "disable", selection.key + ".service"])
    elif selection.platform == "windows":
        _call(selection, ["/Create", "/TN", selection.key, "/XML", str(selection.definition), "/F"])
    digest = _task_digest(selection) if selection.platform == "windows" else None
    updated = _record(selection, enabled, registration="installed", native_digest=digest)
    secure.write_owned(selection.manifest, _json_bytes(updated))
    return updated


def _state(selection):
    path = selection.root / "running.json"
    if not path.exists():
        return None
    value = _read_json(path)
    if (set(value) != {"contract", "generation", "pid", "instance_id"} or value.get("contract") != CONTRACT
        or type(value.get("pid")) is not int or value["pid"] <= 0
        or not isinstance(value.get("generation"), str) or len(value["generation"]) != 64
        or any(c not in "0123456789abcdef" for c in value["generation"])
        or (value["instance_id"] is not None and not isinstance(value["instance_id"], str))):
        _blocked("service_control_invalid", "The service run identity needs inspection.")
    return value


def _process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.GetExitCodeProcess.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = w.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _lease_free(selection):
    try:
        lease = acquire_runtime_ownership(selection.database)
    except RuntimeOwnershipError as exc:
        if exc.code == "ledger_runtime_in_use":
            return False
        raise
    lease.close()
    return True


def _runner_free(selection):
    """Admission can precede running.json and the runtime's ledger lease."""
    try:
        lease = acquire_file_ownership(selection.manifest, suffix=".runner.lock")
    except RuntimeOwnershipError as exc:
        if exc.code == "resource_in_use":
            return False
        raise
    lease.close()
    return True


@contextmanager
def _open_local(host, port, *, timeout):
    # HTTPConnection never applies ambient proxy variables or follows redirects.
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", "/dashboard/api/auth", headers={"Accept": "application/json", "Connection": "close"})
        yield connection.getresponse()
    finally:
        connection.close()


def _ready(selection, state):
    if not state or not state["instance_id"] or not _process_alive(state["pid"]) or _lease_free(selection):
        return False
    try:
        with _open_local(selection.host, selection.port, timeout=0.5) as response:
            if response.status != 200:
                return False
            payload = response.read(16385)
            if len(payload) > 16384:
                return False
            envelope = json.loads(payload)
        result = envelope.get("result") if isinstance(envelope, dict) else None
        return isinstance(result, dict) and result.get("instance_id") == state["instance_id"]
    except (OSError, ValueError, http.client.HTTPException):
        return False


def _start(selection, record):
    state = _state(selection)
    if state and _process_alive(state["pid"]):
        if _ready(selection, state):
            return
        _blocked("service_start_pending", "The owned process exists but readiness is not yet proved.")
    if not _lease_free(selection):
        _blocked("service_ledger_busy", "Another runtime owns this ledger; it was not stopped or replaced.")
    secure.remove_owned(selection.root / "paused.json")
    if selection.platform == "linux":
        _call(selection, ["--user", "start", selection.key + ".service"])
    elif selection.platform == "macos":
        domain = "gui/" + selection.owner["value"]
        if not _launchd_loaded(selection, domain + "/" + selection.key):
            _call(selection, ["bootstrap", domain, str(selection.definition)])
        _call(selection, ["kickstart", domain + "/" + selection.key])
    else:
        if _task_digest(selection) != record["native_definition_sha256"]:
            _blocked("service_definition_changed", "The scheduled task was edited; it was not overwritten.")
        _call(selection, ["/Run", "/TN", selection.key])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _ready(selection, _state(selection)):
            return
        time.sleep(0.1)
    _blocked("service_start_unconfirmed", "Start was requested but the owned HTTP instance is not ready; inspect its state before retrying.")


def _stop(selection, record):
    # Persistent suppression is first, before manager changes or signalling.
    secure.write_owned(selection.root / "paused.json", _json_bytes({"contract": CONTRACT, "paused": True}))
    deadline = time.monotonic() + 30
    observed_pids = set()
    signalled_generation = None
    while time.monotonic() < deadline:
        # Refresh after persistent pause: an admitted runner may not have
        # published its generation or acquired the ledger on the first read.
        state = _state(selection)
        if state is not None:
            observed_pids.add(state["pid"])
            if _process_alive(state["pid"]) and signalled_generation != state["generation"]:
                secure.write_owned(selection.root / "stop.json", _json_bytes({"contract": CONTRACT, "generation": state["generation"]}))
                signalled_generation = state["generation"]
        alive = any(_process_alive(pid) for pid in observed_pids)
        if not alive and _runner_free(selection) and _lease_free(selection):
            return record
        time.sleep(0.1)
    _blocked("service_stop_unconfirmed", "Graceful stop did not settle within its bound. The service remains paused; no forced termination was used.")


def _run(selection):
    record = _load(selection)
    if record["registration"] != "installed":
        _blocked("service_installation_pending", "The registration has not completed.")
    with acquire_file_ownership(selection.manifest, suffix=".runner.lock"):
        if (selection.root / "paused.json").exists():
            if _read_json(selection.root / "paused.json") != {"contract": CONTRACT, "paused": True}:
                _blocked("service_control_invalid", "Inspect the retained service pause marker.")
            _blocked("service_paused", "The managed service is paused; use explicit start when ready.")
        from flow_of_work_mcp.managed_upgrade import runner_token
        restart = runner_token(selection)
        generation = secrets.token_hex(32)
        state = {"contract": CONTRACT, "generation": generation, "pid": os.getpid(), "instance_id": None}
        secure.write_owned(selection.root / "running.json", _json_bytes(state))
        finished = threading.Event()

        def created(instance_id):
            if not isinstance(instance_id, str) or not instance_id:
                _blocked("service_instance_invalid", "The server instance identity is unavailable.")
            state["instance_id"] = instance_id
            secure.write_owned(selection.root / "running.json", _json_bytes(state))

        def watch():
            while not finished.wait(0.1):
                marker = selection.root / "stop.json"
                if marker.exists():
                    try:
                        stop = _read_json(marker)
                    except (ValueError, OSError):
                        continue
                    if stop == {"contract": CONTRACT, "generation": generation}:
                        _thread.interrupt_main(signal.SIGINT)
                        return

        watcher = threading.Thread(target=watch, name="flower-owner-stop", daemon=True)
        watcher.start()
        try:
            from flow_of_work_mcp.server import main
            options = {"dashboard_created": created}
            if restart is not None:
                options["managed_restart"] = restart
            main(["--config", str(selection.config), "--transport", "streamable-http",
                  "--host", selection.host, "--port", str(selection.port)], **options)
        except KeyboardInterrupt:
            pass
        finally:
            finished.set()
            watcher.join(timeout=0.5)
            current = _state(selection)
            if current and current["generation"] == generation:
                secure.remove_owned(selection.root / "running.json")


def _result(selection, operation, record=None, *, observe_readiness=True):
    state = _state(selection) if selection.root.exists() else None
    return {"contract": CONTRACT, "status": "success", "operation": operation,
        "service_id": selection.key, "platform": selection.platform,
        "autostart_enabled": bool(record and record["autostart_enabled"]),
        "registration": record["registration"] if record else "absent",
        "paused": (selection.root / "paused.json").exists(),
        "running": bool(state and _process_alive(state["pid"])),
        "ready": (_ready(selection, state) if state else False) if observe_readiness else None,
        "readiness_checked": observe_readiness,
        "config": str(selection.config), "database": str(selection.database),
        "definition": str(selection.definition), "control_root": str(selection.root)}


def _run_service(operation: str, config_path: Path, host="127.0.0.1", port=8010) -> dict:
    if operation not in {"plan", "install", "enable", "disable", "start", "stop", "status", "remove", "run"}:
        _blocked("service_operation_invalid", "Select a supported service operation.")
    selection = _select(config_path, host, port)
    if operation == "plan":
        return {**_result(selection, operation, observe_readiness=False), "command": selection.command,
                "install_starts_server": False, "enable_starts_server": False,
                "scope": "owner session at sign-in; manual startup remains available"}
    if operation == "run":
        _run(selection)
        return _result(selection, operation)
    if operation == "status" and not selection.manifest.exists():
        return {**_result(selection, operation), "installed": False}
    secure.ensure_directory(selection.root)
    with acquire_file_ownership(selection.manifest, suffix=".operation.lock"):
        if operation != "status":
            from flow_of_work_mcp.managed_upgrade import guard_operator
            guard_operator(selection)
        if operation == "install":
            record = _install(selection)
        else:
            record = _load(selection, inspect_definition=operation != "status")
            if operation == "status" and record["registration"] == "prepared":
                return {**_result(selection, operation, record), "status": "blocked", "code": "service_installation_pending",
                        "installed": False, "message": "Inspect the retained installation intent and native registration before repair."}
            if record["registration"] != "installed":
                _blocked("service_installation_pending", "The installation outcome needs inspection; it was not removed or replaced.")
            if operation == "status":
                _load(selection)
            if operation in {"enable", "disable"}:
                record = _set_enabled(selection, record, operation == "enable")
                if operation == "enable":
                    secure.remove_owned(selection.root / "paused.json")
            elif operation == "start":
                _start(selection, record)
            elif operation in {"stop", "remove"}:
                record = _stop(selection, record)
                if operation == "remove":
                    if selection.platform == "linux":
                        record = _set_enabled(selection, record, False)
                        secure.remove_owned(selection.definition)
                        _call(selection, ["--user", "daemon-reload"])
                    elif selection.platform == "macos":
                        domain = "gui/" + selection.owner["value"] + "/" + selection.key
                        if _launchd_loaded(selection, domain):
                            _call(selection, ["bootout", domain])
                        secure.remove_owned(selection.definition)
                    else:
                        if _task_digest(selection) != record["native_definition_sha256"]:
                            _blocked("service_definition_changed", "The scheduled task was edited; it was not removed.")
                        _call(selection, ["/Delete", "/TN", selection.key, "/F"])
                        secure.remove_owned(selection.definition)
                    secure.remove_owned(selection.manifest)
                    return {**_result(selection, operation), "installed": False}
        return {**_result(selection, operation, record), "installed": True}


def run_service(operation: str, config_path: Path, host="127.0.0.1", port=8010) -> dict:
    """Run one selected operation; errors carry fixed safe codes/messages."""
    try:
        return _run_service(operation, config_path, host, port)
    except RuntimeOwnershipError as exc:
        code = "service_resource_busy" if exc.code in {"resource_in_use", "ledger_runtime_in_use"} else "service_ownership_unavailable"
        raise ServiceError(code, "The selected runtime or service ownership cannot be proved; inspect its state.") from exc
    except OSError as exc:
        raise ServiceError("service_control_unavailable", "The selected owned service files or native manager could not be accessed.") from exc
    except NativeAuthFailure as exc:
        raise ServiceError("service_owner_unavailable", "The local execution and data-owner identity could not be verified.") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["run"])
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    record = _read_json(args.manifest)
    selection = _select(Path(record["config"]), record["host"], record["port"])
    if selection.manifest != args.manifest:
        _blocked("service_control_invalid", "The selected service control path does not match its owner binding.")
    run_service("run", selection.config, selection.host, selection.port)


if __name__ == "__main__":
    main()
