"""Real macOS admission leases and socket handoff for manual dashboard updates."""
from __future__ import annotations

import socket
import sys
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from flow_of_work_mcp import installation_fence as fence
from flow_of_work_mcp import manual_dashboard_upgrade as upgrade
from flow_of_work_mcp import managed_upgrade_install as installer
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS manual update admission')


@pytest.fixture
def operation(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    installation = root / 'venv'
    installation.mkdir()
    config = root / 'flower.yaml'
    config.touch()
    database = root / 'ledger.sqlite3'
    database.touch()
    installed = SimpleNamespace(target=installation, version='1.0.0', receipt_digest='b' * 64)
    profile = SimpleNamespace(config=config, revision='c' * 64, config_identity=(1, 2, 3, 4, 5, 6),
                              database=database, database_identity=(1, 2))
    monkeypatch.setattr(fence, '_environment', lambda: installation)
    monkeypatch.setattr(upgrade, '_basis', lambda *_: (installed, profile))
    control = fence._private_control(installation, create=True)
    operation_id = 'a' * 32
    value = {'contract': fence.MANUAL_UPGRADE_CONTRACT, 'id': operation_id,
             'version': '1.0.1', 'phase': 'queued', 'backup_directory': '', 'reason': '',
             **upgrade._pin(installed, profile)}
    upgrade._write(control, value)
    prepared = SimpleNamespace(profile='test', installation=installed, selection=profile,
                               backup_root=root / 'backups')
    monkeypatch.setattr(installer, 'prepare', lambda *_: prepared)
    monkeypatch.setattr(upgrade.release, '_verify_selection', lambda *_: None)
    return installed, profile, value


def _launch_worker(operation_id):
    owner, worker = socket.socketpair()
    owner.settimeout(5)

    def run():
        with worker:
            upgrade.run_manual_upgrade(operation_id, worker)

    thread = Thread(target=run)
    thread.start()
    return owner, thread


def test_worker_waits_for_shutdown_and_preserves_installation_exclusion(operation, monkeypatch):
    installed, profile, value = operation
    apply_started = Event()

    def apply(_):
        apply_started.set()
        with pytest.raises(fence.InstallationFenceError) as denied:
            fence.startup_lease(transport='streamable-http')
        assert denied.value.code == 'installation_in_use'
        return {'backup': {'backup_directory': '/proved-backup'}}

    monkeypatch.setattr(installer, 'apply', apply)
    # The test owns the real prior instance's two leases before queueing the
    # worker. New starts use the normal admission function and must refuse.
    with fence._lease(installed.target, shared=True), acquire_runtime_ownership(profile.database):
        owner, worker = _launch_worker(value['id'])
        with owner:
            assert owner.recv(1) == b'R'
            with pytest.raises(fence.InstallationFenceError) as denied:
                fence.startup_lease(transport='stdio')
            assert denied.value.code == 'installation_manual_upgrade_pending'
            with pytest.raises(fence.InstallationFenceError):
                fence.manual_upgrade_lease()
            owner.sendall(b'S')
            assert not apply_started.wait(0.15)
    worker.join(5)
    assert not worker.is_alive() and apply_started.is_set()
    receipt = upgrade.manual_upgrade_status()['operation']
    assert receipt['phase'] == 'complete'
    assert receipt['backup_directory'] == '/proved-backup'
    with fence.startup_lease(transport='streamable-http').lease:
        pass


def test_missing_grant_records_preflight_failure_and_allows_start(operation, monkeypatch):
    _, _, value = operation
    monkeypatch.setattr(installer, 'apply', lambda *_: pytest.fail('install ran without shutdown grant'))
    owner, worker = _launch_worker(value['id'])
    with owner:
        assert owner.recv(1) == b'R'
    worker.join(5)
    assert not worker.is_alive()
    receipt = upgrade.manual_upgrade_status()['operation']
    assert receipt['phase'] == 'preflight_failed'
    assert receipt['reason'] == 'upgrade_stop_not_authorized'
    with fence.startup_lease(transport='stdio').lease:
        pass


def test_package_failure_retains_unresolved_fence(operation, monkeypatch):
    _, _, value = operation

    def fail(_):
        raise upgrade.service.ServiceError('upgrade_installer_failed', 'fixture')

    monkeypatch.setattr(installer, 'apply', fail)
    owner, worker = _launch_worker(value['id'])
    with owner:
        assert owner.recv(1) == b'R'
        owner.sendall(b'S')
    worker.join(5)
    assert not worker.is_alive()
    receipt = upgrade.manual_upgrade_status()['operation']
    assert receipt['phase'] == 'failed'
    assert receipt['reason'] == 'upgrade_installer_failed'
    with pytest.raises(fence.InstallationFenceError) as denied:
        fence.startup_lease(transport='streamable-http')
    assert denied.value.code == 'installation_manual_upgrade_pending'
