"""Exercise the prepared release boundary without reaching GitHub or changing an environment."""
from __future__ import annotations

from contextlib import closing
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile

import pytest
import yaml

from flow_of_work_mcp import managed_upgrade_install as managed
from flow_of_work_mcp import release_upgrade as release
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


_TARGET = '0.9.3'
_INSTALLER = b'''
import argparse
import hashlib
from pathlib import Path
import tempfile

def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upgrade', action='store_true')
    parser.add_argument('--venv', type=Path)
    parser.add_argument('--version')
    parser.add_argument('--profile')
    parser.add_argument('--profile-root', type=Path)
    parser.add_argument('--backup-root', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    return parser

def upgrade_plan(args, target, version, *, cwd):
    config = args.profile_root / 'profiles' / args.profile / 'flower.yaml'
    return {
        'contract': 'flower.release-upgrade-plan.v1', 'dry_run': args.dry_run,
        'previous_version': '0.9.2', 'requested_version': version, 'environment': str(target),
        'profile': args.profile, 'profile_root': str(args.profile_root), 'profile_config': str(config),
        'profile_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
        'database_path': str(args.profile_root / 'ledger.sqlite3'),
        'backup_root': str(args.backup_root), 'registration_changed': False,
    }, {}

def installation(args):
    plan, _ = upgrade_plan(args, args.venv, args.version, cwd=Path.cwd())
    if args.dry_run:
        return plan
    with tempfile.TemporaryDirectory() as temp:
        download_asset(
            'https://github.com/Damel91/flower-mcp/releases/download/v' + args.version + '/SHA256SUMS',
            Path(temp) / 'SHA256SUMS', max_bytes=1048576,
        )
    Path('installer-reached-mutation').touch()
    return plan
'''


def _wheel(marker='MANAGED_UPGRADE_PROTOCOL = 1\n'):
    data = BytesIO()
    with ZipFile(data, 'w') as wheel:
        for path in ('managed_service.py', 'installation_fence.py', 'server.py'):
            wheel.writestr('flow_of_work_mcp/' + path, '')
        wheel.writestr('flow_of_work_mcp/managed_upgrade_install.py', marker)
        wheel.writestr(f'flow_of_work_mcp-{_TARGET}.dist-info/METADATA',
                       f'Name: flow-of-work-mcp\nVersion: {_TARGET}\n')
    return data.getvalue()


@pytest.fixture
def selected(tmp_path, monkeypatch):
    state = tmp_path.resolve() / 'profile-root'
    config = state / 'profiles' / 'sandbox' / 'flower.yaml'
    config.parent.mkdir(parents=True)
    database = state / 'ledger.sqlite3'
    with closing(sqlite3.connect(database)) as ledger, ledger:
        ledger.execute('CREATE TABLE local_fixture (value TEXT NOT NULL)')
        ledger.execute("INSERT INTO local_fixture VALUES ('preserve this row')")
    config.write_text(yaml.safe_dump({
        'schema_version': 1,
        'runtime': {'database_path': str(database), 'import_root': 'imports'},
        'logging': {'logs_path': 'logs'},
    }))
    target = tmp_path.resolve() / 'old-environment'
    target.mkdir()
    old = release._Installation(target, Path(sys.executable).resolve(), '0.9.2', 'a' * 64)
    monkeypatch.setattr(release, '_installation', lambda: old)
    operation = tmp_path.resolve() / 'fixture-operation'
    operation.mkdir(mode=0o700)
    return config, database, operation, old


def _assets(monkeypatch, wheel):
    files = {'install_flower.py': _INSTALLER, release._wheel(_TARGET): wheel}
    files['SHA256SUMS'] = ''.join(
        f'{hashlib.sha256(payload).hexdigest()}  {name}\n' for name, payload in files.items()
    ).encode()
    calls = []

    def fetch(url, limit):
        prefix = f'{release._REPOSITORY}/releases/download/v{_TARGET}/'
        assert url.startswith(prefix)
        name = url.removeprefix(prefix)
        calls.append(name)
        assert len(files[name]) <= limit
        return files[name]

    monkeypatch.setattr(managed, '_fetch_asset', fetch)
    return calls


def test_pinned_preflight_reads_under_live_ledger_then_rejects_tampered_stage(selected, monkeypatch):
    config, database, operation, _ = selected
    calls = _assets(monkeypatch, _wheel())
    with acquire_runtime_ownership(database):
        prepared = managed.prepare(config, database, _TARGET, operation)
    assert calls == ['SHA256SUMS', 'install_flower.py', release._wheel(_TARGET)]
    assert prepared.backup_root.is_dir()
    assert not list(prepared.backup_root.iterdir())
    (prepared.assets / 'SHA256SUMS').write_text('changed after review')
    with pytest.raises(release.ReleaseUpgradeError, match='installer failed'):
        managed.apply(prepared)
    assert not (operation / 'installer-reached-mutation').exists()
    assert not (operation / 'installation.json').exists()
    assert len(calls) == 3


def test_wheel_without_compatible_restart_protocol_is_rejected_before_installer(selected, monkeypatch):
    config, database, operation, _ = selected
    _assets(monkeypatch, _wheel('MANAGED_UPGRADE_PROTOCOL = 2\n'))
    monkeypatch.setattr(release, '_execute', lambda *args, **kwargs: pytest.fail('ran incompatible installer'))
    with pytest.raises(release.ReleaseUpgradeError) as error:
        managed.prepare(config, database, _TARGET, operation)
    assert error.value.code == 'upgrade_target_incompatible'


def test_apply_checks_retained_receipt_yaml_bytes_and_sqlite_copy(selected, monkeypatch):
    config, database, operation, old = selected
    _assets(monkeypatch, _wheel())
    prepared = managed.prepare(config, database, _TARGET, operation)
    backup_dir = prepared.backup_root / 'fixture-backup'
    backup_dir.mkdir(mode=0o700)
    config_copy = backup_dir / 'flower.yaml'
    db_copy = backup_dir / 'ledger.sqlite3'
    config_copy.write_bytes(config.read_bytes())
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(db_copy)) as copied:
        source.backup(copied)
    backup = {
        'contract': 'flower.release-upgrade-backup.v1',
        'backup_directory': str(backup_dir),
        'profile_backup': str(config_copy),
        'database_backup': str(db_copy),
        'profile_sha256': prepared.selection.revision,
    }
    backup_receipt = backup_dir / 'upgrade.json'
    backup_receipt.write_text(json.dumps(backup))
    for path in (config_copy, db_copy, backup_receipt):
        path.chmod(0o600)
    result = {
        **prepared.expected(), 'contract': 'flower.release-upgrade-result.v1',
        'version': _TARGET, 'sha256': prepared.wheel_sha256, 'data_preserved': True, 'backup': backup,
    }
    def installer(prepared, *, dry_run):
        assert not dry_run
        (old.target / release._RECEIPT).write_text(json.dumps({
            'contract': release._CONTRACT, 'repository': release._REPOSITORY,
            'version': _TARGET, 'wheel': release._wheel(_TARGET), 'sha256': prepared.wheel_sha256,
        }))
        return result
    monkeypatch.setattr(managed, '_invoke', installer)
    assert managed.apply(prepared)['backup'] == backup
    config_copy.write_bytes(b'tampered backup')
    with pytest.raises(release.ReleaseUpgradeError) as error:
        managed.apply(prepared)
    assert error.value.code == 'upgrade_result_unproved'
