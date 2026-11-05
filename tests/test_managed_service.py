"""Managed startup mechanics on owned files; native managers are never installed."""
from __future__ import annotations

import io
from dataclasses import replace
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from flow_of_work_mcp import managed_service as service
from flow_of_work_mcp import managed_service_security as secure


@pytest.fixture
def owned(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    config, database = root / "flower.yaml", root / "ledger.sqlite3"
    config.write_text("owned test configuration\n")
    database.write_bytes(b"unchanged owned ledger fixture")
    owner = {"kind": "uid", "value": str(os.geteuid() or 1001)}
    monkeypatch.setattr(service, "_native_identity", lambda: (owner, "macos"))
    monkeypatch.setattr(secure, "_identity", lambda: owner)
    monkeypatch.setattr(secure, "_owner", lambda path: owner)
    monkeypatch.setattr(service, "load_config", lambda path: SimpleNamespace(runtime=SimpleNamespace(database_path=database)))
    monkeypatch.setattr(Path, "home", lambda: root / "home")
    (root / "home").mkdir(mode=0o700)
    commands = []

    def native(selection, args, **kwargs):
        commands.append(args)
        missing = args[0] == "print"
        return subprocess.CompletedProcess(args, 1 if missing else 0, "", "Could not find service" if missing else "")

    monkeypatch.setattr(service, "_call", native)
    selection = service._select(config, "127.0.0.1", 18788)
    return selection, commands


def test_plan_is_non_mutating_and_preserves_exact_source_entry(owned):
    selection, commands = owned
    before = set(selection.config.parent.rglob("*"))
    result = service.run_service("plan", selection.config, port=18788)
    assert result["install_starts_server"] is False
    assert result["enable_starts_server"] is False
    assert result["command"][1:3] == ["-I", "-c"]
    assert result["command"][4] == str(Path(service.__file__).resolve().parents[1])
    assert result["command"][-1] == str(selection.manifest)
    assert set(selection.config.parent.rglob("*")) == before
    assert commands == []


def test_launchagent_install_and_enable_never_start_runtime(owned):
    selection, commands = owned
    before = selection.database.read_bytes()
    result = service.run_service("install", selection.config, port=18788)
    definition = plistlib.loads(selection.definition.read_bytes())
    assert definition["ProgramArguments"] == selection.command
    assert definition["KeepAlive"] is False and definition["RunAtLoad"] is False
    assert result["paused"] is True and result["autostart_enabled"] is False
    assert commands == []
    enabled = service.run_service("enable", selection.config, port=18788)
    assert enabled["autostart_enabled"] is True and enabled["paused"] is False
    assert plistlib.loads(selection.definition.read_bytes())["RunAtLoad"] is True
    assert commands == []
    assert selection.database.read_bytes() == before


def test_edited_native_definition_is_not_overwritten(owned):
    selection, commands = owned
    service.run_service("install", selection.config, port=18788)
    selection.definition.write_bytes(b"user edited definition")
    with pytest.raises(service.ServiceError) as error:
        service.run_service("enable", selection.config, port=18788)
    assert error.value.code == "service_definition_changed"
    assert selection.definition.read_bytes() == b"user edited definition"
    assert commands == []


def test_unrecognized_definition_is_not_adopted(owned):
    selection, commands = owned
    selection.definition.parent.mkdir(parents=True)
    selection.definition.write_bytes(b"unrecognized")
    with pytest.raises(service.ServiceError) as error:
        service.run_service("install", selection.config, port=18788)
    assert error.value.code == "service_definition_conflict"
    assert commands == []


def test_stop_pauses_before_marker_and_preserves_registration(owned, monkeypatch):
    selection, commands = owned
    service.run_service("install", selection.config, port=18788)
    service.run_service("enable", selection.config, port=18788)
    generation = "a" * 64
    secure.write_owned(selection.root / "running.json", service._json_bytes({"contract": service.CONTRACT,
        "generation": generation, "pid": 12345, "instance_id": "known-instance"}))
    calls = []

    def alive(pid):
        assert (selection.root / "paused.json").exists()
        calls.append(pid)
        return len(calls) == 1

    monkeypatch.setattr(service, "_process_alive", alive)
    monkeypatch.setattr(service, "_lease_free", lambda value: True)
    result = service.run_service("stop", selection.config, port=18788)
    assert result["paused"] and not result["running"]
    assert result["autostart_enabled"] is True  # Original next-login setting retained, admission paused.
    assert json.loads(secure.read_owned(selection.root / "stop.json"))["generation"] == generation
    assert selection.manifest.exists() and selection.definition.exists()
    assert commands == []  # No forced manager Stop or definition replacement.


def test_stop_timeout_is_blocked_without_forced_manager_action(owned, monkeypatch):
    selection, commands = owned
    record = service._install(selection)
    moments = iter([0, 15, 30])
    monkeypatch.setattr(service.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(service.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(service, "_lease_free", lambda value: False)
    with pytest.raises(service.ServiceError) as error:
        service._stop(selection, record)
    assert error.value.code == "service_stop_unconfirmed"
    assert (selection.root / "paused.json").exists()
    assert commands == []


def test_runner_ignores_old_stop_generation_and_removes_own_state(owned, monkeypatch):
    selection, _ = owned
    service._install(selection)
    secure.remove_owned(selection.root / "paused.json")
    secure.write_owned(selection.root / "stop.json", service._json_bytes({"contract": service.CONTRACT, "generation": "b" * 64}))
    monkeypatch.setattr(service.secrets, "token_hex", lambda count: "a" * 64)
    signals = []
    monkeypatch.setattr(service._thread, "interrupt_main", lambda sig: signals.append(sig))
    from flow_of_work_mcp import server

    def fake_server(argv, *, dashboard_created):
        assert argv[-1] == "18788"
        dashboard_created("owned-instance")
        time.sleep(0.25)

    monkeypatch.setattr(server, "main", fake_server)
    service._run(selection)
    assert signals == []
    assert not (selection.root / "running.json").exists()


def test_runner_matching_generation_requests_same_process_sigint(owned, monkeypatch):
    selection, _ = owned
    service._install(selection)
    secure.remove_owned(selection.root / "paused.json")
    requested = threading.Event()
    signals = []

    def interrupt(sig):
        signals.append(sig)
        requested.set()

    monkeypatch.setattr(service._thread, "interrupt_main", interrupt)
    from flow_of_work_mcp import server

    def fake_server(argv, *, dashboard_created):
        dashboard_created("same-process")
        state = service._state(selection)
        assert state["pid"] == os.getpid()
        secure.write_owned(selection.root / "stop.json", service._json_bytes({"contract": service.CONTRACT, "generation": state["generation"]}))
        assert requested.wait(1)

    monkeypatch.setattr(server, "main", fake_server)
    service._run(selection)
    assert signals == [signal.SIGINT]
    assert not (selection.root / "running.json").exists()


def test_paused_runner_does_not_invoke_server(owned, monkeypatch):
    selection, _ = owned
    service._install(selection)
    from flow_of_work_mcp import server
    monkeypatch.setattr(server, "main", lambda *args, **kwargs: pytest.fail("server started while paused"))
    with pytest.raises(service.ServiceError) as error:
        service._run(selection)
    assert error.value.code == "service_paused"
    assert not (selection.root / "running.json").exists()


def test_readiness_rejects_other_http_instance(owned, monkeypatch):
    selection, _ = owned
    state = {"pid": 12345, "generation": "a" * 64, "instance_id": "expected"}
    monkeypatch.setattr(service, "_process_alive", lambda pid: True)
    monkeypatch.setattr(service, "_lease_free", lambda value: False)

    class Response(io.BytesIO):
        status = 200

    monkeypatch.setattr(service, "_open_local", lambda *a, **kw: Response(b'{"result":{"instance_id":"other"}}'))
    assert service._ready(selection, state) is False
    monkeypatch.setattr(service, "_open_local", lambda *a, **kw: Response(b'{"result":{"instance_id":"expected"}}'))
    assert service._ready(selection, state) is True


def test_windows_definition_is_nonprivileged_and_autostart_disabled(owned):
    selection, _ = owned
    selection = replace(selection, platform="windows", owner={"kind": "sid", "value": "S-1-5-21-1-2-3-1001"})
    root = ET.fromstring(service._definition(selection, False))
    ns = {"t": service._TASK_NS}
    assert root.findtext("t:Triggers/t:LogonTrigger/t:Enabled", namespaces=ns) == "false"
    assert root.findtext("t:Settings/t:Enabled", namespaces=ns) == "true"
    assert root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    assert root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns) == "LeastPrivilege"
    assert root.findtext("t:Settings/t:AllowHardTerminate", namespaces=ns) == "false"
    assert root.find("t:Settings/t:RestartOnFailure", ns) is None
    assert "D:P(A;;FA;;;SY)(A;;FA;;;S-1-5-21-1-2-3-1001)" == root.findtext("t:RegistrationInfo/t:SecurityDescriptor", namespaces=ns)


def test_linux_definition_quotes_manager_expansion_and_has_no_restart(owned):
    selection, _ = owned
    selection = replace(selection, platform="linux", root=selection.root / "space % $ test")
    unit = service._definition(selection, False).decode()
    assert "Restart=no\n" in unit and "SendSIGKILL=no\n" in unit
    assert "%%" in unit and "$$" in unit
    assert "PYTHONPATH=" not in unit


def test_private_control_rejects_alias_broad_mode_hardlinks_and_oversize(owned):
    selection, _ = owned
    secure.ensure_directory(selection.root)
    path = selection.root / "record.json"
    secure.write_owned(path, b"12345")
    with pytest.raises(secure.ServiceSecurityError):
        secure.read_owned(path, limit=4)
    link = selection.root / "linked.json"
    link.symlink_to(path)
    with pytest.raises(secure.ServiceSecurityError):
        secure.read_owned(link)
    hard = selection.root / "hard.json"
    os.link(path, hard)
    with pytest.raises(secure.ServiceSecurityError):
        secure.read_owned(path)
    hard.unlink()
    path.chmod(0o644)
    with pytest.raises(secure.ServiceSecurityError):
        secure.read_owned(path)


def test_prepared_install_status_is_not_false_success_and_exact_retry_is_bounded(owned, monkeypatch):
    selection, _ = owned
    selection = replace(selection, platform="linux", definition=selection.config.parent / "home/.config/systemd/user" / (selection.key + ".service"))
    monkeypatch.setattr(service, "_select", lambda *args: selection)
    def unavailable(*args, **kwargs):
        raise service.ServiceError("service_manager_unavailable", "Native operation unavailable")
    monkeypatch.setattr(service, "_call", unavailable)
    with pytest.raises(service.ServiceError):
        service.run_service("install", selection.config, port=18788)
    assert service.run_service("status", selection.config, port=18788)["status"] == "blocked"
    with pytest.raises(service.ServiceError) as error:
        service.run_service("remove", selection.config, port=18788)
    assert error.value.code == "service_installation_pending"
    monkeypatch.setattr(service, "_call", lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""))
    assert service.run_service("install", selection.config, port=18788)["installed"] is True


def test_stop_waits_for_admitted_runner_before_generation_publication(owned, monkeypatch):
    selection, _ = owned
    record = service._install(selection)
    secure.remove_owned(selection.root / "paused.json")
    admitted, publish, marker_seen = threading.Event(), threading.Event(), threading.Event()
    alive = threading.Event()
    alive.set()
    generation = "c" * 64
    errors = []

    def runner():
        try:
            with service.acquire_file_ownership(selection.manifest, suffix=".runner.lock"):
                assert not (selection.root / "paused.json").exists()
                admitted.set()
                assert publish.wait(2)
                secure.write_owned(selection.root / "running.json", service._json_bytes({
                    "contract": service.CONTRACT, "pid": 12345, "generation": generation, "instance_id": None}))
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    marker = selection.root / "stop.json"
                    if marker.exists() and service._read_json(marker).get("generation") == generation:
                        marker_seen.set()
                        break
                    time.sleep(0.01)
                assert marker_seen.is_set()
                alive.clear()
        except BaseException as exc:
            errors.append(exc)

    original_proof = service._runner_free

    def admission_proof(value):
        free = original_proof(value)
        if not free:
            assert (selection.root / "paused.json").exists()
            publish.set()
        return free

    monkeypatch.setattr(service, "_runner_free", admission_proof)
    monkeypatch.setattr(service, "_process_alive", lambda pid: alive.is_set())
    monkeypatch.setattr(service, "_lease_free", lambda value: True)
    thread = threading.Thread(target=runner)
    thread.start()
    assert admitted.wait(1)
    try:
        service._stop(selection, record)
    finally:
        publish.set()
        thread.join(timeout=3)
    assert not errors
    assert marker_seen.is_set() and not alive.is_set()


def test_readiness_ignores_proxy_environment_and_never_follows_redirects(owned, monkeypatch):
    selection, _ = owned
    monkeypatch.setenv("HTTP_PROXY", "http://must-not-be-contacted.invalid:9")
    monkeypatch.setenv("ALL_PROXY", "http://must-not-be-contacted.invalid:9")
    monkeypatch.setattr(service, "_process_alive", lambda pid: True)
    monkeypatch.setattr(service, "_lease_free", lambda value: False)
    requests = []

    class Connection:
        def __init__(self, host, port, *, timeout):
            assert (host, port) == ("127.0.0.1", 18788)
        def request(self, method, path, headers):
            requests.append((method, path))
        def getresponse(self):
            return SimpleNamespace(status=302)
        def close(self):
            requests.append("closed")

    monkeypatch.setattr(service.http.client, "HTTPConnection", Connection)
    assert not service._ready(selection, {"pid": 12345, "instance_id": "owned"})
    assert requests == [("GET", "/dashboard/api/auth"), "closed"]


def test_control_read_fifo_swap_remains_nonblocking(owned, monkeypatch):
    selection, _ = owned
    secure.ensure_directory(selection.root)
    path = selection.root / "swapped.json"
    secure.write_owned(path, b"original")
    original_open = os.open

    def replaced(name, flags, *args, **kwargs):
        if Path(name) == path:
            assert flags & os.O_NONBLOCK
            path.unlink()
            os.mkfifo(path)
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(secure.os, "open", replaced)
    with pytest.raises(secure.ServiceSecurityError):
        secure.read_owned(path)
