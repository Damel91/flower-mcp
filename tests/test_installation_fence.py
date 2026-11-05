"""Installation-wide ownership and the durable managed restart handoff."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from flow_of_work_mcp import installation_fence as fence
from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp import release_upgrade, server
from flow_of_work_mcp.profiles import prepare_profile

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS managed upgrade admission")


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    environment = root / "venv"
    environment.mkdir()
    (environment / ".flower-release-install.json").write_text("{}")
    monkeypatch.setattr(fence.sys, "prefix", str(environment))
    monkeypatch.setattr(release_upgrade, "_installation", lambda: SimpleNamespace(target=environment))
    config = prepare_profile(root / "state")
    database = config.parent / "ledger.sqlite3"
    database.touch()
    return SimpleNamespace(environment=environment, config=config, database=database)


def _enroll(installed):
    host, port = "127.0.0.1", 8123
    return fence.enroll_installation(installed.config, installed.database, host=host, port=port,
                                    service_key=fence._service_key(installed.config, host, port))


def _publish(binding, phase):
    record = {"contract": fence.UPGRADE_CONTRACT, "phase": phase,
              "service_key": binding.service_key, "id": "ab" * 16}
    secure.write_owned(binding.journal, json.dumps(record).encode())
    return record["id"]


def test_shared_servers_exclude_offline_enrollment_and_package_replacement(installed):
    with fence.startup_lease(transport="stdio").lease:
        with fence.startup_lease(transport="streamable-http").lease:
            with pytest.raises(fence.InstallationFenceError) as denied:
                _enroll(installed)
            assert denied.value.code == "installation_in_use"
    binding = _enroll(installed)
    assert _enroll(installed) == binding
    assert fence.load_installation(installed.config, installed.database) == binding
    with fence.environment_lease(binding):
        for transport in ("stdio", "streamable-http"):
            with pytest.raises(fence.InstallationFenceError) as denied:
                fence.startup_lease(transport=transport)
            assert denied.value.code == "installation_in_use"


def test_unresolved_durable_journal_blocks_even_without_worker_or_ledger_owner(installed):
    binding = _enroll(installed)
    _publish(binding, "failed")
    with pytest.raises(fence.InstallationFenceError) as denied:
        fence.startup_lease(transport="stdio")
    assert denied.value.code == "installation_upgrade_pending"
    with fence.environment_lease(binding):
        _publish(binding, "preflight_failed")
    with fence.startup_lease(installed.config, installed.database, transport="stdio").lease:
        pass


def test_restart_only_admits_the_internal_operation_and_exact_http_endpoint(installed, monkeypatch):
    binding = _enroll(installed)
    operation = _publish(binding, "restarting")
    from flow_of_work_mcp import managed_upgrade
    monkeypatch.setattr(managed_upgrade, "supervised_restart", lambda _: False)
    with pytest.raises(fence.InstallationFenceError) as rejected:
        fence.startup_lease(transport="streamable-http", host=binding.host,
                            port=binding.port, managed_restart=operation)
    assert rejected.value.code == "installation_restart_unproved"
    monkeypatch.setattr(managed_upgrade, "supervised_restart", lambda _: True)
    for transport, host, port, token in (
        ("streamable-http", binding.host, binding.port, None),
        ("streamable-http", binding.host, binding.port, "12" * 16),
        ("streamable-http", "::1", binding.port, operation),
        ("streamable-http", binding.host, binding.port + 1, operation),
        ("stdio", binding.host, binding.port, operation),
    ):
        with pytest.raises(fence.InstallationFenceError) as denied:
            fence.startup_lease(transport=transport, host=host, port=port, managed_restart=token)
        assert denied.value.code == "installation_upgrade_pending"
    with fence.startup_lease(installed.config, installed.database, transport="streamable-http",
                             host=binding.host, port=binding.port, managed_restart=operation).lease:
        with pytest.raises(fence.InstallationFenceError) as denied:
            fence.environment_lease(binding)
        assert denied.value.code == "installation_in_use"
    with fence.environment_lease(binding):
        _publish(binding, "complete")
    with fence.startup_lease(installed.config, installed.database, transport="stdio").lease:
        pass


def test_server_rejects_another_profile_before_creating_it(installed, tmp_path, capsys):
    _enroll(installed)
    target = tmp_path / "other-profile"
    with pytest.raises(SystemExit) as denied:
        server.main(["--profile-root", str(target), "--profile", "other"])
    assert denied.value.code == 2
    assert "installation_profile_mismatch" in capsys.readouterr().err
    assert not target.exists()


def test_active_upgrade_blocks_direct_entry_before_loading_configuration(installed, monkeypatch, capsys):
    binding = _enroll(installed)
    _publish(binding, "installing")
    monkeypatch.setattr(server, "load_config", lambda *_: pytest.fail("fenced start opened configuration"))
    for transport in ("stdio", "streamable-http"):
        with pytest.raises(SystemExit) as denied:
            server.main(["--config", str(binding.config), "--transport", transport])
        assert denied.value.code == 2
        assert "installation_upgrade_pending" in capsys.readouterr().err


def test_unsafe_control_state_fails_closed(installed):
    binding = _enroll(installed)
    secure.write_owned(binding.journal, b'{"id":"ambiguous", "id":"duplicate"}')
    with pytest.raises(fence.InstallationFenceError) as denied:
        fence.startup_lease(transport="stdio")
    assert denied.value.code == "installation_fence_unsafe"
    with fence.environment_lease(binding):
        pass


def test_manual_apply_and_managed_enrollment_serialize(installed):
    with fence.manual_upgrade_lease():
        with pytest.raises(fence.InstallationFenceError) as denied:
            _enroll(installed)
        assert denied.value.code == "installation_in_use"
    _enroll(installed)
    with pytest.raises(fence.InstallationFenceError) as denied:
        fence.manual_upgrade_lease()
    assert denied.value.code == "installation_managed_upgrade_required"


def test_server_rechecks_queued_upgrade_after_obtaining_ledger(installed, monkeypatch, capsys):
    from flow_of_work_mcp import runtime_ownership

    binding = _enroll(installed)
    acquire = runtime_ownership.acquire_runtime_ownership

    def queue_while_opening(path):
        _publish(binding, "queued")
        return acquire(path)

    monkeypatch.setattr(runtime_ownership, "acquire_runtime_ownership", queue_while_opening)
    monkeypatch.setattr(server, "build_runtime_from_config", lambda **_: pytest.fail("fenced contender composed runtime"))
    with pytest.raises(SystemExit) as denied:
        server.main(["--config", str(binding.config)])
    assert denied.value.code == 2
    assert "installation_upgrade_pending" in capsys.readouterr().err
    with fence.environment_lease(binding), acquire(binding.database):
        pass
