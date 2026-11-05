"""Deterministic wrapper/ownership tests; no network or package mutation."""
from __future__ import annotations

import hashlib
from http.client import IncompleteRead
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.request import Request

import pytest
import yaml

from flow_of_work_mcp import release_upgrade as upgrade
from flow_of_work_mcp import installation_fence
from flow_of_work_mcp.cli import main
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


_VERSION = '0.9.2'
_INSTALLER = b'print("verified installer fixture, never executed")\n'
_BASE = f'{upgrade._REPOSITORY}/releases/download/v{_VERSION}'


def _checksum(payload=_INSTALLER):
    return (f'{hashlib.sha256(payload).hexdigest()}  install_flower.py\n'
            f'{"1" * 64} *{upgrade._wheel(_VERSION)}\n').encode()


def _expect(code, call):
    with pytest.raises(upgrade.ReleaseUpgradeError) as error:
        call()
    assert error.value.code == code
    return error.value


@pytest.fixture
def selected(tmp_path, monkeypatch):
    if os.name == 'posix' and os.geteuid() == 0:
        pytest.skip('Official owned profiles require a normal local account.')
    root = tmp_path.resolve() / 'state'
    config = root / 'profiles' / 'owned' / 'flower.yaml'
    config.parent.mkdir(parents=True)
    database = root / 'separate-ledger.sqlite3'
    database.write_bytes(b'opaque ledger data: wrapper must never open SQLite')
    config.write_text(yaml.safe_dump({
        'schema_version': 1,
        'runtime': {'database_path': str(database), 'import_root': 'external-imports'},
        'logging': {'logs_path': 'retained-logs'},
    }))
    installed = upgrade._Installation(tmp_path / 'owned environment', tmp_path / 'base python',
                                      '0.9.1', 'a' * 64)
    monkeypatch.setattr(upgrade, '_installation', lambda: installed)
    requests = []

    def asset(url):
        requests.append(url)
        return {_BASE + '/SHA256SUMS': _checksum(), _BASE + '/install_flower.py': _INSTALLER}[url]

    monkeypatch.setattr(upgrade, '_asset', asset)
    return root, config, database, installed, requests


def _run(root, *, dry_run=False, version=_VERSION, backup=None):
    return upgrade.run_release_upgrade(version=version, profile='owned', profile_root=root,
                                       backup_root=backup, dry_run=dry_run)


def test_dry_run_uses_official_script_and_never_acquires_the_selected_lease(selected, monkeypatch):
    root, config, database, installed, requests = selected
    before = config.read_bytes(), database.read_bytes()
    workspaces = []

    def execute(args, *, cwd):
        workspaces.append(cwd)
        assert args == [str(installed.base_python), '-I', '-B', str(cwd / 'install_flower.py'),
                        '--upgrade', '--venv', str(installed.target), '--version', _VERSION,
                        '--profile', 'owned', '--profile-root', str(root), '--dry-run']
        assert Path(args[3]).read_bytes() == _INSTALLER
        assert not (cwd / 'SHA256SUMS').exists()
        return 17

    monkeypatch.setattr(upgrade, '_execute', execute)
    monkeypatch.setattr(upgrade, 'acquire_runtime_ownership', lambda path: pytest.fail('dry run took a lease'))
    assert _run(root, dry_run=True) == 17
    assert requests == [_BASE + '/SHA256SUMS', _BASE + '/install_flower.py']
    assert before == (config.read_bytes(), database.read_bytes())
    assert workspaces and not workspaces[0].exists()


def test_apply_refuses_active_owner_before_network_and_releases_probe_before_handoff(selected, monkeypatch):
    root, config, database, installed, requests = selected
    backup = root.parent / 'explicit backups'
    before = config.read_bytes(), database.read_bytes()

    def execute(args, *, cwd):
        assert '--dry-run' not in args and '--platform' not in args
        assert args[-2:] == ['--backup-root', str(backup)]
        # The official backend is allowed to reacquire immediately.
        with acquire_runtime_ownership(database):
            pass
        return 9

    monkeypatch.setattr(upgrade, '_execute', execute)
    with acquire_runtime_ownership(database):
        _expect('upgrade_ledger_active', lambda: _run(root, backup=backup))
    assert requests == []
    assert _run(root, backup=backup) == 9
    assert not backup.exists()
    assert before == (config.read_bytes(), database.read_bytes())


def test_manual_upgrade_refuses_dedicated_installation_before_network(selected, monkeypatch):
    root, _, _, _, requests = selected
    monkeypatch.setattr(installation_fence, 'read_enrollment', lambda: object())
    _expect('upgrade_managed_installation', lambda: _run(root))
    assert requests == []


def test_manual_apply_keeps_exclusive_installation_lease_through_installer(selected, monkeypatch):
    root, _, database, installed, _ = selected
    installed.target.mkdir()
    monkeypatch.setattr(installation_fence, '_environment', lambda: installed.target)

    def execute(args, *, cwd):
        with pytest.raises(installation_fence.InstallationFenceError) as busy:
            installation_fence._lease(installed.target, shared=True)
        assert busy.value.code == 'installation_in_use'
        with acquire_runtime_ownership(database):
            pass
        return 0

    monkeypatch.setattr(upgrade, '_execute', execute)
    assert _run(root) == 0
    with installation_fence._lease(installed.target, shared=True):
        pass


def test_revalidates_config_bytes_after_download_without_invoking_backend(selected, monkeypatch):
    root, config, _, _, _ = selected
    original = upgrade._asset

    def edited(url):
        result = original(url)
        if url.endswith('/install_flower.py'):
            config.write_bytes(config.read_bytes() + b'\n# intervening owner edit\n')
        return result

    monkeypatch.setattr(upgrade, '_asset', edited)
    monkeypatch.setattr(upgrade, '_execute', lambda *args, **kwargs: pytest.fail('started with changed profile'))
    _expect('upgrade_selection_changed', lambda: _run(root, dry_run=True))


@pytest.mark.parametrize(('target', 'code'), [('v0.9.2', 'upgrade_version_invalid'),
    ('0.9.2rc1', 'upgrade_version_invalid'), ('0.09.2', 'upgrade_version_invalid'),
    ('0.9.0', 'upgrade_version_not_newer'), ('0.9.1', 'upgrade_version_not_newer')])
def test_target_is_exact_stable_and_newer(selected, target, code):
    root, _, _, _, requests = selected
    _expect(code, lambda: _run(root, version=target))
    assert not requests


def test_profile_missing_or_aliased_is_rejected_before_download(selected):
    root, config, database, _, requests = selected
    original = config.read_bytes()
    config.unlink()
    _expect('upgrade_profile_unproved', lambda: _run(root, dry_run=True))
    alias = root / 'alias.sqlite3'
    try:
        alias.symlink_to(database)
    except OSError:
        pytest.skip('Symlink creation unavailable to this test account.')
    values = yaml.safe_load(original)
    values['runtime']['database_path'] = str(alias)
    config.write_text(yaml.safe_dump(values))
    _expect('upgrade_profile_unproved', lambda: _run(root, dry_run=True))
    assert not requests


@pytest.mark.parametrize('manifest', [b'invalid', b'\xff', _checksum() + _checksum(),
    f'{"1" * 64}  ../install_flower.py\n'.encode(), f'{"1" * 64}  install_flower.py\n'.encode()])
def test_manifest_requires_unique_valid_exact_release_assets(monkeypatch, manifest):
    def fetch(url):
        assert url == _BASE + '/SHA256SUMS'
        return manifest
    monkeypatch.setattr(upgrade, '_asset', fetch)
    _expect('upgrade_checksum_invalid', lambda: upgrade._installer(_VERSION))


def test_mismatched_installer_never_reaches_subprocess(selected, monkeypatch):
    root, _, _, _, _ = selected
    monkeypatch.setattr(upgrade, '_asset', lambda url: _checksum() if url.endswith('/SHA256SUMS') else b'changed')
    monkeypatch.setattr(upgrade, '_execute', lambda *args, **kwargs: pytest.fail('unverified code executed'))
    _expect('upgrade_checksum_mismatch', lambda: _run(root, dry_run=True))


@pytest.mark.parametrize('url', ['http://release-assets.githubusercontent.com/x',
    'https://release-assets.githubusercontent.com.evil.invalid/x', 'https://user@objects.githubusercontent.com/x',
    'https://objects.githubusercontent.com:8443/x', 'https://github.com/Damel91/other/releases/download/v0.9.2/x'])
def test_disallowed_redirects_are_refused_before_request(url):
    initial = _BASE + '/install_flower.py'
    redirect = upgrade._ReleaseRedirects(initial)
    _expect('upgrade_asset_origin_invalid', lambda: redirect.redirect_request(Request(initial), None, 302, '', {}, url))


def test_asset_accepts_signed_github_cdn_and_bounds_bytes_and_http_failures(monkeypatch):
    url = _BASE + '/install_flower.py'

    class Response(BytesIO):
        def geturl(self):
            return 'https://release-assets.githubusercontent.com/signed?signature=private-test-marker'

    def opener(response):
        return lambda *args: SimpleNamespace(open=lambda request, timeout: response)

    monkeypatch.setattr(upgrade, 'build_opener', opener(Response(b'asset')))
    assert upgrade._asset(url) == b'asset'
    monkeypatch.setattr(upgrade, '_ASSET_LIMIT', 3)
    monkeypatch.setattr(upgrade, 'build_opener', opener(Response(b'asset')))
    _expect('upgrade_asset_too_large', lambda: upgrade._asset(url))

    class Incomplete(Response):
        def read(self, *args):
            raise IncompleteRead(b'sensitive raw upstream error')

    monkeypatch.setattr(upgrade, 'build_opener', opener(Incomplete(b'')))
    error = _expect('upgrade_asset_unavailable', lambda: upgrade._asset(url))
    assert 'sensitive' not in str(error)


def test_installation_receipt_binds_running_venv_distribution_not_a_checkout(tmp_path, monkeypatch):
    if os.name == 'posix' and os.geteuid() == 0:
        pytest.skip('Official owned profiles require a normal local account.')
    root = tmp_path.resolve()
    target = root / 'venv'
    env_python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    env_python.parent.mkdir(parents=True)
    env_python.write_bytes(b'fixture executable')
    base_python = root / 'base' / 'python'
    base_python.parent.mkdir()
    base_python.write_bytes(b'independent fixture executable')
    base_python.chmod(0o700)
    (target / 'pyvenv.cfg').write_text('home = fixture\n')
    site = target / 'site-packages'
    module = site / 'flow_of_work_mcp/release_upgrade.py'
    module.parent.mkdir(parents=True)
    module.write_text('# installed module fixture\n')
    receipt = {'contract': upgrade._CONTRACT, 'repository': upgrade._REPOSITORY,
               'version': '0.9.1', 'wheel': upgrade._wheel('0.9.1'), 'sha256': 'a' * 64}
    (target / upgrade._RECEIPT).write_text(json.dumps(receipt))
    direct = {'url': (root / receipt['wheel']).as_uri(), 'archive_info': {'hashes': {'sha256': 'a' * 64}}}
    dist = SimpleNamespace(version='0.9.1', locate_file=lambda name: site / name,
                           files=[PurePosixPath('flow_of_work_mcp/release_upgrade.py')],
                           read_text=lambda name: json.dumps(direct))
    monkeypatch.setattr(upgrade.sys, 'prefix', str(target))
    monkeypatch.setattr(upgrade.sys, 'base_prefix', str(base_python.parent))
    monkeypatch.setattr(upgrade.sys, 'executable', str(env_python))
    monkeypatch.setattr(upgrade.sys, '_base_executable', str(base_python))
    monkeypatch.setattr(upgrade, '__file__', str(module))
    monkeypatch.setattr(upgrade.metadata, 'distribution', lambda name: dist)
    assert upgrade._installation().target == target
    direct['archive_info']['hashes']['sha256'] = 'b' * 64
    _expect('upgrade_installation_unproved', upgrade._installation)
    direct['archive_info']['hashes']['sha256'] = 'a' * 64
    checkout = root / 'checkout.py'
    checkout.write_text('# source checkout fixture\n')
    monkeypatch.setattr(upgrade, '__file__', str(checkout))
    _expect('upgrade_installation_unproved', upgrade._installation)


def test_native_subprocess_does_not_capture_output_or_force_kill_on_interrupt(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', 'should-not-be-inherited')
    observations = []

    class Process:
        def wait(self):
            observations.append('wait')
            if observations.count('wait') == 1:
                raise KeyboardInterrupt
            return 19

    def start(command, **kwargs):
        observations.append(command)
        assert kwargs['shell'] is False and kwargs['cwd'] == tmp_path
        assert 'PYTHONPATH' not in kwargs['env']
        assert 'stdout' not in kwargs and 'stderr' not in kwargs
        return Process()

    monkeypatch.setattr(upgrade.subprocess, 'Popen', start)
    assert upgrade._execute(['independent-python', '-I', 'verified-installer'], cwd=tmp_path) == 19
    assert observations[1:] == ['wait', 'wait']


def test_cli_passes_exact_manual_selection_and_preserves_status(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(upgrade, 'run_release_upgrade', lambda **kwargs: calls.append(kwargs) or 23)
    backup = tmp_path / 'backup'
    with pytest.raises(SystemExit) as error:
        main(['upgrade', '--version', _VERSION, '--profile', 'owned', '--profile-root', str(tmp_path),
              '--backup-root', str(backup), '--dry-run'])
    assert error.value.code == 23
    assert calls == [dict(version=_VERSION, profile='owned', profile_root=tmp_path,
                          backup_root=backup, dry_run=True)]
