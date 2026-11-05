"""The managed worker owns the stop/install/restart sequence and its receipt."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from flow_of_work_mcp import managed_upgrade as upgrade
from flow_of_work_mcp import managed_upgrade_install as backend


@pytest.fixture
def context(tmp_path, monkeypatch):
    selection = SimpleNamespace(manifest=tmp_path / "service.json", key="service", config=tmp_path / "flower.yaml",
                                database=tmp_path / "ledger.sqlite3")
    binding = SimpleNamespace(journal=tmp_path / "upgrade.json")
    initial = {"contract": upgrade.CONTRACT, "id": "a" * 32, "service_key": selection.key,
               "version": "1.0.1", "previous_version": "1.0.0", "phase": "queued",
               "generation": "b" * 64, "config_revision": "c" * 64,
               "backup_directory": "", "reason": ""}
    current = initial.copy()
    events = []
    record = {"registration": "installed"}
    generations = iter([{"generation": "b" * 64}, {"generation": "d" * 64}])
    prepared = SimpleNamespace(backup_root=tmp_path / "backups")

    def write(_binding, value, **changes):
        assert current == value
        current.update(changes)
        events.append(current["phase"])
        return current.copy()

    def change(name):
        events.append(name)

    @contextmanager
    def env(_binding):
        change("lease")
        yield
        change("lease-released")

    monkeypatch.setattr(upgrade, "_journal", lambda _: current.copy())
    monkeypatch.setattr(upgrade, "_write", write)
    monkeypatch.setattr(upgrade, "_current", lambda _: (record, next(generations)))
    monkeypatch.setattr(upgrade, "_verify_basis", lambda *args, **kw: None)
    monkeypatch.setattr(upgrade, "environment_lease", env)
    monkeypatch.setattr(upgrade.service, "_stop", lambda *args: change("stop"))
    monkeypatch.setattr(upgrade.service, "_start", lambda *args: change("start"))
    monkeypatch.setattr(upgrade.service, "_load", lambda *args: record)
    monkeypatch.setattr(backend, "prepare", lambda *args: (change("prepare"), prepared)[1])
    monkeypatch.setattr(backend, "apply", lambda _: (change("apply"), {"backup": {"backup_directory": "/backup/proved"}})[1])
    return selection, binding, current, events


def test_worker_pins_preflight_stops_holds_fence_and_requires_a_new_generation(context):
    selection, binding, current, events = context
    upgrade._work(selection, binding, current["id"])
    assert events == ["prepare", "stopping", "stop", "lease", "installing", "apply",
                      "restarting", "lease-released", "start", "complete"]
    assert current["backup_directory"] == "/backup/proved"


def test_preflight_failure_does_not_stop_a_service(context, monkeypatch):
    selection, binding, current, events = context
    def fail(*_):
        raise upgrade.service.ServiceError("upgrade_checksum_mismatch", "fixture")
    monkeypatch.setattr(backend, "prepare", fail)
    upgrade._work(selection, binding, current["id"])
    assert events == ["preflight_failed"]
    assert current["reason"] == "upgrade_checksum_mismatch"


def test_install_failure_keeps_the_fence_and_does_not_claim_a_backup(context, monkeypatch):
    selection, binding, current, events = context
    def fail(*_):
        raise upgrade.service.ServiceError("upgrade_installer_failed", "fixture")
    monkeypatch.setattr(backend, "apply", fail)
    upgrade._work(selection, binding, current["id"])
    assert current["phase"] == "failed"
    assert "start" not in events and not current["backup_directory"]


def test_only_the_native_service_pid_can_receive_the_restart_token(context, monkeypatch):
    selection, binding, current, _ = context
    current["phase"] = "restarting"
    monkeypatch.setattr(upgrade, "read_enrollment", lambda: binding)
    monkeypatch.setattr(upgrade, "_binding", lambda _: binding)
    monkeypatch.setattr(upgrade, "_native_pid", lambda *args: upgrade.os.getpid() + 1)
    with pytest.raises(upgrade.service.ServiceError, match="selected launchd service"):
        upgrade.runner_token(selection)
    monkeypatch.setattr(upgrade, "_native_pid", lambda *args: upgrade.os.getpid())
    assert upgrade.runner_token(selection) == current["id"]


def test_old_generation_does_not_count_as_a_restart(context, monkeypatch):
    selection, binding, current, events = context
    monkeypatch.setattr(upgrade, "_current", lambda _: ({}, {"generation": current["generation"]}))
    upgrade._work(selection, binding, current["id"])
    assert events[-3:] == ["start", "stop", "failed"]
    assert current["reason"] == "upgrade_restart_unconfirmed"
    assert current["backup_directory"] == "/backup/proved"
