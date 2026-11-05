"""Prepared handoff from a managed operation to Flower's standalone release installer."""
from __future__ import annotations

import ast
from contextlib import closing
from dataclasses import dataclass
from email.parser import BytesParser
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
from zipfile import BadZipFile, ZipFile

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp import release_upgrade as release
from flow_of_work_mcp.ledger_archive import assert_private_archive_directory


MANAGED_UPGRADE_PROTOCOL = 1
_WHEEL_LIMIT = 128 * 1024 * 1024
_INSTALLER_LIMIT = 1024 * 1024
_MANIFEST_LIMIT = 1024 * 1024

# This program runs in the independent base interpreter. The public installer
# still owns the backup lease, package changes and installation receipt. Its
# download hook receives the exact bytes verified before the service stopped.
_BRIDGE = r'''
import hashlib
import json
import os
from pathlib import Path
import sys
from types import ModuleType

request = json.loads(sys.argv[1])
assets = Path(request['assets'])
result_path = Path(request['result'])
installer_path = assets / 'install_flower.py'
with installer_path.open('rb') as source:
    payload = source.read(1024 * 1024 + 1)
if len(payload) > 1024 * 1024 or hashlib.sha256(payload).hexdigest() != request['digests'][installer_path.name]:
    raise ValueError('staged installer changed')
backend = ModuleType('_flower_verified_release_installer')
backend.__file__ = str(installer_path)
sys.modules[backend.__name__] = backend
exec(compile(payload, str(installer_path), 'exec'), backend.__dict__)

def prepared_download(url, destination, *, max_bytes):
    name = url.rsplit('/', 1)[-1]
    if url != request['url'] + '/' + name or name not in request['downloads']:
        raise ValueError('the verified installer requested an unexpected asset')
    digest = hashlib.sha256()
    total = 0
    with (assets / name).open('rb') as source, destination.open('xb') as output:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError('staged asset exceeded its bound')
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != request['digests'][name]:
        raise ValueError('staged asset changed')
    return digest.hexdigest()

original_plan = backend.upgrade_plan
def checked_plan(args, target, version, *, cwd):
    plan, discovered = original_plan(args, target, version, cwd=cwd)
    if any(plan.get(key) != value for key, value in request['expected'].items()):
        raise ValueError('the installer selected a different profile, version or backup location')
    return plan, discovered

backend.download_asset = prepared_download
backend.upgrade_plan = checked_plan
args = backend.build_parser().parse_args(request['arguments'])
result = backend.installation(args)
descriptor = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
    json.dump(result, output)
    output.flush()
    os.fsync(output.fileno())
'''


@dataclass(frozen=True)
class PreparedUpgrade:
    previous_version: str
    version: str
    backup_root: Path
    wheel_sha256: str
    operation_dir: Path
    assets: Path
    digests: dict[str, str]
    installation: release._Installation
    selection: release._Profile
    profile: str

    @property
    def url(self) -> str:
        return f'{release._REPOSITORY}/releases/download/v{self.version}'

    def expected(self) -> dict:
        return {
            'previous_version': self.previous_version,
            'requested_version': self.version,
            'environment': str(self.installation.target),
            'profile': self.profile,
            'profile_root': str(self.selection.root),
            'profile_config': str(self.selection.config),
            'profile_sha256': self.selection.revision,
            'database_path': str(self.selection.database),
            'backup_root': str(self.backup_root),
            'registration_changed': False,
        }


def _failure(code: str, message: str) -> release.ReleaseUpgradeError:
    return release.ReleaseUpgradeError(code, message)


def _fetch_asset(url: str, limit: int) -> bytes:
    return release._asset(url, limit=limit)


def _verify_wheel(wheel: Path, version: str) -> None:
    try:
        with ZipFile(wheel) as archive:
            files = archive.namelist()
            if len(files) != len(set(files)):
                raise ValueError('duplicate wheel members')
            for path in ('managed_service.py', 'installation_fence.py', 'server.py'):
                archive.getinfo('flow_of_work_mcp/' + path)
            metadata_path = f'flow_of_work_mcp-{version}.dist-info/METADATA'
            marker_path = 'flow_of_work_mcp/managed_upgrade_install.py'
            if archive.getinfo(metadata_path).file_size > 65536 or archive.getinfo(marker_path).file_size > 262144:
                raise ValueError('invalid capability metadata size')
            metadata = BytesParser().parsebytes(archive.read(metadata_path))
            if metadata.get_all('Version') != [version] or metadata.get_all('Name') != ['flow-of-work-mcp']:
                raise ValueError('wrong distribution or version')
            syntax = ast.parse(archive.read(marker_path))
            markers = [
                node.value for node in syntax.body
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'MANAGED_UPGRADE_PROTOCOL'
                    for target in node.targets
                )
            ]
            if len(markers) != 1 or not isinstance(markers[0], ast.Constant) or (
                type(markers[0].value) is not int or markers[0].value != MANAGED_UPGRADE_PROTOCOL
            ):
                raise ValueError('incompatible managed restart')
    except (BadZipFile, KeyError, OSError, RuntimeError, SyntaxError, ValueError) as exc:
        raise _failure('upgrade_target_incompatible', 'The selected wheel does not support this managed upgrade protocol.') from exc


def _matching_profile(config: Path, database: Path) -> tuple[str, release._Profile]:
    if config.name != 'flower.yaml' or config.parent.parent.name != 'profiles':
        raise _failure('upgrade_profile_unproved', 'The service must use a standard Flower profile.')
    profile = config.parent.name
    selected = release._selected_profile(profile, config.parent.parent.parent)
    if selected.config != config or selected.database != database:
        raise _failure('upgrade_profile_unproved', 'The service profile and ledger could not be bound to the selected installation.')
    return profile, selected


def _invoke(prepared: PreparedUpgrade, *, dry_run: bool) -> dict:
    stage = 'preflight' if dry_run else 'installation'
    result_path = prepared.operation_dir / (stage + '.json')
    if os.path.lexists(result_path):
        raise _failure('upgrade_stage_already_recorded', 'Inspect the recorded upgrade stage before retrying.')
    arguments = [
        '--upgrade', '--venv', str(prepared.installation.target), '--version', prepared.version,
        '--profile', prepared.profile, '--profile-root', str(prepared.selection.root),
        '--backup-root', str(prepared.backup_root),
    ]
    if dry_run:
        arguments.append('--dry-run')
    request = {
        'assets': str(prepared.assets), 'result': str(result_path), 'url': prepared.url,
        'digests': prepared.digests, 'downloads': ['SHA256SUMS', release._wheel(prepared.version)],
        'expected': prepared.expected(), 'arguments': arguments,
    }
    command = [str(prepared.installation.base_python), '-I', '-B', '-c', _BRIDGE, json.dumps(request)]
    if release._execute(command, cwd=prepared.operation_dir) != 0:
        raise _failure('upgrade_installer_failed', 'The release installer failed. Inspect this operation and its backup before taking further action.')
    try:
        result = json.loads(secure.read_owned(result_path, limit=65536), object_pairs_hook=release._unique_object)
        if not isinstance(result, dict):
            raise ValueError('unexpected installer result')
        return result
    except (OSError, ValueError) as exc:
        raise _failure('upgrade_result_unproved', 'The installer outcome could not be verified.') from exc


def prepare(config: Path, database: Path, version: str, operation_dir: Path) -> PreparedUpgrade:
    """Verify the entire exact release and the installer's read-only plan before stop."""
    requested = release._version(version)
    installed = release._installation()
    if requested <= release._version(installed.version):
        raise _failure('upgrade_version_not_newer', 'Select an official version newer than the installed release.')
    profile, selected = _matching_profile(config, database)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,63}', operation_dir.name):
        raise _failure('upgrade_operation_invalid', 'The upgrade operation identifier is invalid.')
    try:
        assert_private_archive_directory(operation_dir)
        assets = operation_dir / 'release'
        assets.mkdir(mode=0o700)
        assert_private_archive_directory(assets)
        backup_root = selected.root / 'upgrade-backups' / operation_dir.name
        secure.ensure_directory(backup_root.parent)
        backup_root.mkdir(mode=0o700)
        assert_private_archive_directory(backup_root)
    except (OSError, ValueError) as exc:
        raise _failure('upgrade_workspace_unavailable', 'Private release and backup directories could not be established.') from exc
    base = f'{release._REPOSITORY}/releases/download/v{version}'
    manifest = _fetch_asset(base + '/SHA256SUMS', _MANIFEST_LIMIT)
    checksums = release._checksums(manifest)
    wheel_name = release._wheel(version)
    digests = {'SHA256SUMS': hashlib.sha256(manifest).hexdigest()}
    secure.write_owned(assets / 'SHA256SUMS', manifest)
    for name, limit in (('install_flower.py', _INSTALLER_LIMIT), (wheel_name, _WHEEL_LIMIT)):
        expected = checksums.get(name)
        if expected is None:
            raise _failure('upgrade_checksum_invalid', 'The official manifest does not identify the selected installer and wheel.')
        payload = _fetch_asset(base + '/' + name, limit)
        if not payload or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected):
            raise _failure('upgrade_checksum_mismatch', 'A prepared release asset differs from the official manifest.')
        secure.write_owned(assets / name, payload)
        digests[name] = expected
    _verify_wheel(assets / wheel_name, version)
    prepared = PreparedUpgrade(installed.version, version, backup_root, digests[wheel_name],
                               operation_dir, assets, digests, installed, selected, profile)
    plan = _invoke(prepared, dry_run=True)
    if plan.get('contract') != 'flower.release-upgrade-plan.v1' or plan.get('dry_run') is not True:
        raise _failure('upgrade_target_incompatible', 'The verified installer did not produce the supported read-only upgrade plan.')
    release._verify_selection(profile, installed, selected)
    return prepared


def _verify_backup(prepared: PreparedUpgrade, backup: dict) -> None:
    if backup.get('contract') != 'flower.release-upgrade-backup.v1':
        raise ValueError('unexpected backup receipt')
    directory = Path(backup['backup_directory'])
    if directory.parent != prepared.backup_root:
        raise ValueError('unexpected backup directory')
    assert_private_archive_directory(directory)
    config = directory / 'flower.yaml'
    database = directory / 'ledger.sqlite3'
    if backup.get('profile_backup') != str(config) or backup.get('database_backup') != str(database):
        raise ValueError('unexpected backup paths')
    receipt_path = directory / 'upgrade.json'
    saved = json.loads(secure.read_owned(receipt_path, limit=65536), object_pairs_hook=release._unique_object)
    if saved != backup or backup.get('profile_sha256') != prepared.selection.revision:
        raise ValueError('backup receipt changed')
    config_bytes = secure.read_owned(config, limit=release._CONFIG_LIMIT)
    if hashlib.sha256(config_bytes).hexdigest() != prepared.selection.revision:
        raise ValueError('configuration backup does not match')
    secure._private(database, directory=False)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as copied:
        if copied.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('backup did not pass integrity verification')


def apply(prepared: PreparedUpgrade) -> dict:
    """Install while the caller holds the dedicated installation fence."""
    if (release._installation() != prepared.installation or
        release._selected_profile(prepared.profile, prepared.selection.root) != prepared.selection):
        raise _failure('upgrade_selection_changed', 'The installation or profile changed after preflight.')
    result = _invoke(prepared, dry_run=False)
    try:
        expected = prepared.expected()
        for key in ('backup_root', 'profile_sha256'):
            del expected[key]
        if (result.get('contract') != 'flower.release-upgrade-result.v1'
                or result.get('data_preserved') is not True
                or any(result.get(key) != value for key, value in expected.items())
                or result.get('version') != prepared.version or result.get('sha256') != prepared.wheel_sha256):
            raise ValueError('unexpected upgrade receipt')
        receipt, _ = release._read_owned(prepared.installation.target / release._RECEIPT, limit=release._METADATA_LIMIT)
        installed = json.loads(receipt, object_pairs_hook=release._unique_object)
        if installed != {
            'contract': release._CONTRACT, 'repository': release._REPOSITORY, 'version': prepared.version,
            'wheel': release._wheel(prepared.version), 'sha256': prepared.wheel_sha256,
        }:
            raise ValueError('installed receipt does not identify the prepared wheel')
        if release._selected_profile(prepared.profile, prepared.selection.root) != prepared.selection:
            raise ValueError('the profile or ledger changed during installation')
        _verify_backup(prepared, result['backup'])
    except (OSError, ValueError, AttributeError, KeyError, TypeError, sqlite3.Error) as exc:
        raise _failure('upgrade_result_unproved', 'The installed release or backup could not be verified.') from exc
    return result
