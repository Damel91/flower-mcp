"""Manual handoff to the verified standalone Flower release installer."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import hmac
from http.client import HTTPException
from importlib import metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.config import parse_config_mapping
from flow_of_work_mcp.ledger_archive import ArchiveError, assert_private_archive_directory
from flow_of_work_mcp.profiles import profile_config_path, profile_root as resolve_profile_root
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership


_REPOSITORY = 'https://github.com/Damel91/flower-mcp'
_RECEIPT = '.flower-release-install.json'
_CONTRACT = 'flower.release-installation.v1'
_DISTRIBUTION = 'flow-of-work-mcp'
_RELEASE_HOSTS = {'github.com', 'release-assets.githubusercontent.com',
                  'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}
_STABLE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
_CHECKSUM = re.compile(r'([A-Fa-f0-9]{64}) [ *]([A-Za-z0-9_.-]+)')
_METADATA_LIMIT = 64 * 1024
_CONFIG_LIMIT = 4 * 1024 * 1024
_ASSET_LIMIT = 1024 * 1024
_DOWNLOAD_TIMEOUT = 30


class ReleaseUpgradeError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _unsupported() -> ReleaseUpgradeError:
    return ReleaseUpgradeError('upgrade_installation_unproved',
        'Run this command from the existing official installer-owned Flower environment.')


def _version(value: str) -> tuple[int, int, int]:
    match = _STABLE.fullmatch(value) if isinstance(value, str) and len(value) <= 64 else None
    if match is None:
        raise ReleaseUpgradeError('upgrade_version_invalid', 'Select an exact stable MAJOR.MINOR.PATCH release.')
    major, minor, patch = map(int, match.groups())
    return major, minor, patch


def _wheel(version: str) -> str:
    return f'flow_of_work_mcp-{version}-py3-none-any.whl'


def _unalias(path: Path) -> Path:
    selected = Path(path).expanduser().absolute()
    if selected.resolve() != selected or any(c in str(selected) for c in '\0\r\n'):
        raise ValueError('unsafe path')
    return selected


def _stamp(info) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _owned_file(path: Path, *, limit: int | None = None):
    secure.check_data_file(path)
    info = path.lstat()
    if not info.st_ino or (limit is not None and info.st_size > limit):
        raise ValueError('unsupported file identity')
    return info


def _read_owned(path: Path, *, limit: int) -> tuple[bytes, tuple[int, ...]]:
    before = _owned_file(path, limit=limit)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags), 'rb') as source:
        held = os.fstat(source.fileno())
        if _stamp(held) != _stamp(before):
            raise ValueError('changed file')
        content = source.read(limit + 1)
        if len(content) > limit or _stamp(_owned_file(path)) != _stamp(held):
            raise ValueError('changed file')
    return content, _stamp(held)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _prove_distribution(target: Path, receipt: dict) -> None:
    dist = metadata.distribution(_DISTRIBUTION)
    installed = Path(dist.locate_file('')).resolve(strict=True)
    running = Path(__file__).resolve(strict=True)
    module = 'flow_of_work_mcp/release_upgrade.py'
    recorded = {item.as_posix() for item in dist.files or ()}
    if (dist.version != receipt['version'] or not installed.is_relative_to(target)
            or module not in recorded or running != installed / module):
        raise ValueError('package is not the selected installed distribution')
    # An official installer receipt is the installation contract; additional
    # pip direct-url provenance, when present, must not contradict it.
    text = dist.read_text('direct_url.json')
    if text is not None:
        if len(text) > _METADATA_LIMIT:
            raise ValueError('oversized package metadata')
        origin = json.loads(text, object_pairs_hook=_unique_object)
        url = urlsplit(origin['url'])
        archive = origin['archive_info']
        hashes = archive.get('hashes', {})
        supplied = []
        if 'hash' in archive:
            supplied.append(archive['hash'])
        if 'sha256' in hashes:
            supplied.append('sha256=' + hashes['sha256'])
        if (set(origin) != {'url', 'archive_info'} or url.scheme != 'file'
                or url.query or url.fragment or url.username is not None or url.password is not None
                or Path(unquote(url.path)).name != receipt['wheel']
                or not supplied or any(item != 'sha256=' + receipt['sha256'] for item in supplied)):
            raise ValueError('package metadata does not match the wheel receipt')


@dataclass(frozen=True)
class _Installation:
    target: Path
    base_python: Path
    version: str
    receipt_digest: str


def _installation() -> _Installation:
    try:
        target = _unalias(Path(sys.prefix))
        base_prefix = Path(sys.base_prefix).resolve(strict=True)
        secure._metadata(target, directory=True)
        if target == base_prefix:
            raise ValueError('not a venv')
        _owned_file(target / 'pyvenv.cfg', limit=_METADATA_LIMIT)
        expected = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        invoked = Path(sys.executable).absolute()
        if invoked.parent != expected.parent or not expected.is_file() or not invoked.samefile(expected):
            raise ValueError('interpreter does not select this venv')
        base_python = Path(sys._base_executable).resolve(strict=True)
        if (not stat.S_ISREG(base_python.stat().st_mode) or base_python.is_relative_to(target)
                or (os.name == 'posix' and not os.access(base_python, os.X_OK))):
            raise ValueError('no independent base interpreter')
        path = target / _RECEIPT
        owner = secure.check_data_file(path)
        if owner.get('value') in {'0', 'S-1-5-18', 'S-1-5-19', 'S-1-5-20'}:
            raise ValueError('not a normal local owner')
        payload, _ = _read_owned(path, limit=_METADATA_LIMIT)
        receipt = json.loads(payload, object_pairs_hook=_unique_object)
        if (not isinstance(receipt, dict) or set(receipt) != {'contract', 'repository', 'version', 'wheel', 'sha256'}
                or receipt['contract'] != _CONTRACT or receipt['repository'] != _REPOSITORY
                or receipt['wheel'] != _wheel(receipt['version']) or not isinstance(receipt['sha256'], str)
                or re.fullmatch(r'[a-f0-9]{64}', receipt['sha256']) is None):
            raise ValueError('invalid receipt')
        _version(receipt['version'])
        _prove_distribution(target, receipt)
        return _Installation(target, base_python, receipt['version'], hashlib.sha256(payload).hexdigest())
    except (OSError, ValueError, KeyError, TypeError, AttributeError, metadata.PackageNotFoundError):
        raise _unsupported() from None


@dataclass(frozen=True)
class _Profile:
    root: Path
    config: Path
    config_identity: tuple[int, ...]
    revision: str
    database: Path
    database_identity: tuple[int, int]


def _selected_profile(profile: str, root: Path | None) -> _Profile:
    try:
        if root is not None:
            # Unlike .resolve(), this check doesn't erase an operator alias.
            if not Path(root).expanduser().is_absolute():
                raise ValueError('profile root must be absolute')
            root = _unalias(root)
        selected_root = _unalias(resolve_profile_root(root))
        path = _unalias(profile_config_path(selected_root, profile))
        payload, identity = _read_owned(path, limit=_CONFIG_LIMIT)
        raw = yaml.safe_load(payload.decode('utf-8'))
        config = parse_config_mapping(raw, source_path=path)
        configured = Path(raw['runtime']['database_path']).expanduser()
        if not configured.is_absolute():
            configured = path.parent / configured
        database = _unalias(Path(os.path.abspath(configured)))
        if database != config.runtime.database_path:
            raise ValueError('configured ledger path is aliased')
        db = _owned_file(database)
        return _Profile(selected_root, path, identity, hashlib.sha256(payload).hexdigest(),
                        database, (db.st_dev, db.st_ino))
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        raise ReleaseUpgradeError('upgrade_profile_unproved',
            'Select an existing owned Flower profile and ledger using the standard profile arguments.') from None


def _release_url(url: str, expected: str) -> None:
    try:
        parts = urlsplit(url)
        allowed = (parts.scheme == 'https' and parts.hostname in _RELEASE_HOSTS
                   and parts.port in {None, 443} and parts.username is None and parts.password is None
                   and '#' not in url and '\\' not in url and url == url.strip()
                   and not any(ord(ch) < 32 or ord(ch) == 127 for ch in url)
                   and (parts.hostname != 'github.com' or url == expected))
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        raise ReleaseUpgradeError('upgrade_asset_origin_invalid', 'The release asset left its authorized GitHub HTTPS origins.')


class _ReleaseRedirects(HTTPRedirectHandler):
    def __init__(self, expected: str):
        self.expected = expected

    def redirect_request(self, request, response, code, message, headers, new_url):
        _release_url(new_url, self.expected)
        return super().redirect_request(request, response, code, message, headers, new_url)


def _asset(url: str, *, limit: int | None = None) -> bytes:
    limit = _ASSET_LIMIT if limit is None else limit
    _release_url(url, url)
    request = Request(url, headers={'User-Agent': 'Flower-MCP-Release-Installer', 'Accept-Encoding': 'identity'})
    try:
        with build_opener(_ReleaseRedirects(url)).open(request, timeout=_DOWNLOAD_TIMEOUT) as response:
            _release_url(response.geturl(), url)
            result = bytearray()
            while chunk := response.read(64 * 1024):
                if len(result) + len(chunk) > limit:
                    raise ReleaseUpgradeError('upgrade_asset_too_large', 'A release asset exceeds the download limit.')
                result.extend(chunk)
        return bytes(result)
    except ReleaseUpgradeError:
        raise
    except (OSError, HTTPException, ValueError):
        raise ReleaseUpgradeError('upgrade_asset_unavailable', 'The selected official release assets could not be downloaded.') from None


def _checksums(payload: bytes) -> dict[str, str]:
    try:
        entries = {}
        for line in payload.decode('ascii').splitlines():
            if not line.strip():
                continue
            match = _CHECKSUM.fullmatch(line)
            if match is None or match[2] in {'.', '..'} or match[2] in entries:
                raise ValueError('invalid manifest')
            entries[match[2]] = match[1].lower()
        return entries
    except ValueError:
        raise ReleaseUpgradeError('upgrade_checksum_invalid', 'The official release checksum manifest is invalid.') from None


def _installer(version: str) -> bytes:
    base = f'{_REPOSITORY}/releases/download/v{version}'
    checksums = _checksums(_asset(base + '/SHA256SUMS'))
    expected = checksums.get('install_flower.py')
    if expected is None or _wheel(version) not in checksums:
        raise ReleaseUpgradeError('upgrade_checksum_invalid', 'The official manifest does not identify the selected installer and wheel.')
    payload = _asset(base + '/install_flower.py')
    if not payload or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected):
        raise ReleaseUpgradeError('upgrade_checksum_mismatch', 'The installer SHA256 differs from the official manifest.')
    return payload


def _verify_selection(profile: str, installed: _Installation, selected: _Profile) -> None:
    if _installation() != installed or _selected_profile(profile, selected.root) != selected:
        raise ReleaseUpgradeError('upgrade_selection_changed', 'The selected installation or profile changed. Inspect it before retrying.')


def _check_stopped(profile: str, installed: _Installation, selected: _Profile) -> None:
    try:
        with acquire_runtime_ownership(selected.database) as lease:
            lease.assert_resource(selected.database)
            _verify_selection(profile, installed, selected)
    except RuntimeOwnershipError as exc:
        if exc.code == 'ledger_runtime_in_use':
            raise ReleaseUpgradeError('upgrade_ledger_active', 'Stop Flower and its owning clients before applying this upgrade.') from None
        raise ReleaseUpgradeError('upgrade_ownership_unavailable', 'Cannot prove safe ownership of the selected ledger.') from None


def _execute(command: list[str], *, cwd: Path) -> int:
    environment = dict(os.environ)
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__', 'VIRTUAL_ENV',
                 'PIP_TARGET', 'PIP_PREFIX', 'PIP_USER'):
        environment.pop(name, None)
    try:
        process = subprocess.Popen(command, cwd=cwd, env=environment, shell=False)
    except OSError:
        raise ReleaseUpgradeError('upgrade_installer_unavailable', 'The verified installer could not be started.') from None
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # The foreground installer receives the terminal interrupt itself.
            # Never kill a child that may be settling pip or its backup lease.
            continue


def run_release_upgrade(*, version: str, profile: str, profile_root: Path | None,
                        backup_root: Path | None, dry_run: bool) -> int:
    """Validate an explicit manual request and delegate without starting Flower."""
    from flow_of_work_mcp import installation_fence

    def require_manual_environment():
        if installation_fence.read_enrollment() is not None:
            raise ReleaseUpgradeError('upgrade_managed_installation',
                'Use the managed service upgrade for this dedicated Flower installation.')

    requested = _version(version)
    installed = _installation()
    require_manual_environment()
    if requested <= _version(installed.version):
        raise ReleaseUpgradeError('upgrade_version_not_newer', 'Select an official version newer than the installed release.')
    selected = _selected_profile(profile, profile_root)
    try:
        backup = _unalias(backup_root) if backup_root is not None else None
    except (OSError, ValueError, TypeError):
        raise ReleaseUpgradeError('upgrade_backup_path_invalid', 'Select a safe explicit backup directory.') from None
    if not dry_run:
        _check_stopped(profile, installed, selected)
    payload = _installer(version)
    status = None
    try:
        with tempfile.TemporaryDirectory(prefix='flower-upgrade-installer-') as folder:
            scratch = Path(folder).resolve()
            if os.name == 'nt':
                secure._windows_protect(scratch, directory=True)
            try:
                assert_private_archive_directory(scratch)
            except ArchiveError:
                raise ReleaseUpgradeError('upgrade_workspace_unavailable',
                    'A private installer workspace could not be established.') from None
            script = scratch / 'install_flower.py'
            secure.write_owned(script, payload)
            command = [str(installed.base_python), '-I', '-B', str(script), '--upgrade',
                       '--venv', str(installed.target), '--version', version, '--profile', profile,
                       '--profile-root', str(selected.root)]
            if backup is not None:
                command.extend(('--backup-root', str(backup)))
            if dry_run:
                command.append('--dry-run')
                require_manual_environment()
                _verify_selection(profile, installed, selected)
                status = _execute(command, cwd=scratch)
            else:
                ownership = installation_fence.manual_upgrade_lease()
                with ownership if ownership is not None else nullcontext():
                    # The installer takes its own ledger lease. Retain only the
                    # installation fence across the independent process.
                    _check_stopped(profile, installed, selected)
                    status = _execute(command, cwd=scratch)
    except ReleaseUpgradeError:
        raise
    except (OSError, secure.ServiceSecurityError):
        if status is not None:
            # Workspace cleanup cannot overwrite the already observed result.
            print('The temporary installer workspace could not be removed.', file=sys.stderr)
            return status
        raise ReleaseUpgradeError('upgrade_workspace_unavailable', 'The verified installer workspace could not be prepared or settled.') from None
    return status
