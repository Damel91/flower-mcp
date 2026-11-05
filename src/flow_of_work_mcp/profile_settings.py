"""Owner-authorized, revision-bound profile drafts and offline application."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

import yaml

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.config import FlowConfig, FlowConfigError, parse_config_mapping
from flow_of_work_mcp.dashboard_auth import DashboardAuthError, OwnerBinding
from flow_of_work_mcp.runtime_ownership import (
    RuntimeOwnershipError, acquire_file_ownership, acquire_runtime_ownership,
)


_CONTRACT = 'flow.profile-settings-draft.v1'
_LIMIT = 65536
_SHA = re.compile(r'[0-9a-f]{64}')
_ID = re.compile(r'[0-9a-f]{32}')
_ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}')


class SettingsError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


@dataclass(frozen=True)
class _Field:
    key: str
    type: str
    section: str = 'advanced'
    options: tuple[str, ...] = ()
    nullable: bool = False
    readonly: bool = False


_SNAPSHOT_PROVIDERS = {
    'implementation_graph': 'implementation_graph_provider',
    'bootstrap_behavior': 'bootstrap_behavior_provider',
    'packet_evidence': 'packet_evidence_provider',
}
_FIELDS = (
    _Field('runtime.import_root', 'text', 'basic'),
    _Field('model.enabled', 'boolean', 'basic'),
    _Field('model.model', 'text', 'basic'),
    _Field('runtime.job_workers', 'integer'),
    _Field('logging.level', 'select', options=('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG')),
    _Field('logging.enable_console', 'boolean'),
    _Field('logging.logs_path', 'text'),
    _Field('model.backend', 'select', options=('llamacpp',), readonly=True),
    _Field('model.base_url', 'text'),
    _Field('model.context_length', 'integer', nullable=True),
    _Field('model.api_key_env', 'text', nullable=True),
    _Field('model.idle_timeout_sec', 'number'),
    _Field('model.verify_ssl', 'boolean'),
    _Field('model.temperature', 'number'),
    _Field('model.reasoning', 'select', options=('auto', 'off', 'on', 'low', 'medium', 'high')),
    *(_Field(f'providers.{provider}.{key}', kind, options=options)
      for provider in _SNAPSHOT_PROVIDERS for key, kind, options in (
          ('enabled', 'boolean', ()), ('url', 'text', ()), ('tool', 'text', ()),
          ('invocation', 'select', ('direct', 'advanced')), ('session_id', 'text', ()),
          ('domain', 'text', ()), ('operation', 'text', ()),
      )),
    *(_Field(f'{provider}.{key}', kind, options=options, readonly=key == 'kind')
      for provider, tool in (('packet_provider', 'codingcastle_packet'), ('test_provider', 'codingcastle_tests'))
      for key, kind, options in (
          ('mode', 'select', ('agnostic', 'auto', 'required')), ('kind', 'select', ('codingcastle',)),
          ('endpoint', 'text', ()), ('tool', 'select', (tool,)), ('timeout_seconds', 'number', ()),
      )),
)
_FIELD_BY_KEY = {field.key: field for field in _FIELDS}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _closed_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate mapping key')
        result[key] = value
    return result


class _ProfileLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        return _closed_pairs(self.construct_pairs(node, deep=deep))


def _parse(payload: bytes, path: Path) -> tuple[dict, FlowConfig]:
    try:
        raw = yaml.load(payload.decode('utf-8'), Loader=_ProfileLoader)
        return raw, parse_config_mapping(raw, source_path=path)
    except (FlowConfigError, UnicodeError, ValueError, TypeError, yaml.YAMLError, RecursionError):
        raise SettingsError('settings_configuration_invalid', 'The selected profile is not an unambiguous supported YAML configuration.') from None


def _is_url(key: str) -> bool:
    return key.rsplit('.', 1)[-1] in {'url', 'base_url', 'endpoint'}


def _safe_url(value: str, *, model: bool) -> bool:
    if not value:
        return not model
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        return False
    try:
        parts = urlsplit(value)
        # A custom path can encode a bearer secret just as a query can. The
        # structured editor only reflects and accepts standard literal routes.
        paths = {'', '/', '/v1', '/v1/'} if model else {'', '/', '/mcp', '/mcp/', '/sse', '/sse/'}
        return (parts.scheme in {'http', 'https'} and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and '@' not in parts.netloc and '?' not in value and '#' not in value
                and parts.path in paths
                and (parts.port is None or parts.port > 0))
    except ValueError:
        return False


def _valid_value(field: _Field, value: object) -> bool:
    if value is None:
        return field.nullable
    if field.type == 'boolean':
        return type(value) is bool
    if field.type == 'integer':
        return type(value) is int and 0 <= value <= 2**53 - 1
    if field.type == 'number':
        return type(value) in {int, float} and abs(value) <= 2**53 - 1 and math.isfinite(value)
    if field.type == 'select':
        return type(value) is str and value in field.options
    if not isinstance(value, str) or len(value) > 4096 or any(
        ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value
    ):
        return False
    if _is_url(field.key):
        return _safe_url(value, model=field.key == 'model.base_url')
    if field.key == 'model.api_key_env':
        return not value or _ENV.fullmatch(value) is not None
    return True


def _values(config: FlowConfig) -> list[dict]:
    result = []
    for field in _FIELDS:
        keys = field.key.split('.')
        source = (getattr(config, _SNAPSHOT_PROVIDERS[keys[1]]) if keys[0] == 'providers'
                  else getattr(config, keys[0]))
        value = getattr(source, keys[-1])
        if isinstance(value, Path):
            value = str(value)
        safe = _valid_value(field, value)
        row = {'key': field.key, 'section': field.section, 'type': field.type,
               'value': value if safe else None}
        if field.options:
            row['options'] = list(field.options)
        if field.nullable:
            row['nullable'] = True
        if field.readonly or not safe:
            row['readonly'] = True
        result.append(row)
    return result


def _changes(value: object) -> dict:
    if not isinstance(value, dict) or len(value) > len(_FIELDS):
        raise SettingsError('settings_input_invalid', 'Supply the supported typed settings fields.')
    for key, item in value.items():
        field = _FIELD_BY_KEY.get(key)
        if field is None or field.readonly or not _valid_value(field, item):
            raise SettingsError('settings_input_invalid', 'A setting is unsupported, read-only, or has an invalid value.')
    return dict(value)


def _merge(raw: dict, path: Path, changes: dict, current: FlowConfig) -> tuple[bytes, FlowConfig]:
    # Merge only leaves of the original mapping. Never reconstruct config from
    # public fields: legacy bindings, surfaces and other noneditable keys stay.
    merged = dict(raw)
    for key, value in changes.items():
        *parents, leaf = key.split('.')
        node = merged
        for parent in parents:
            # Copy the path being edited: YAML aliases can share submappings.
            child = dict(node.get(parent, {}))
            node[parent] = child
            node = child
        if value is None:
            node.pop(leaf, None)
        else:
            node[leaf] = value
    try:
        proposed = parse_config_mapping(merged, source_path=path)
        data = yaml.safe_dump(merged, allow_unicode=True, sort_keys=False).encode('utf-8')
    except (FlowConfigError, UnicodeError, ValueError, TypeError, yaml.YAMLError, RecursionError):
        raise SettingsError('settings_validation_failed', 'These settings do not form a valid profile. Check the selected model and provider fields.') from None
    if proposed.runtime.database_path != current.runtime.database_path:
        raise SettingsError('settings_selection_changed', 'The selected ledger may not change through settings.', 409)
    if len(data) > _LIMIT:
        raise SettingsError('settings_configuration_too_large', 'The proposed profile exceeds the settings size limit.', 413)
    return data, proposed


def _read_existing(path: Path) -> tuple[bytes, int]:
    """Bounded no-follow read, preserving the selected file's POSIX mode."""
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or getattr(before, 'st_file_attributes', 0) & 0x400):
        raise secure.ServiceSecurityError('The selected profile file is unsafe.')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    def stamp(info):
        return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    with os.fdopen(fd, 'rb') as source:
        opened = os.fstat(source.fileno())
        if not opened.st_ino or stamp(before) != stamp(opened):
            raise secure.ServiceSecurityError('The selected profile file changed before inspection.')
        data = source.read(_LIMIT + 1)
        after = path.lstat()
        if stamp(opened) != stamp(after):
            raise secure.ServiceSecurityError('The selected profile file changed during inspection.')
    if len(data) > _LIMIT:
        raise SettingsError('settings_configuration_too_large', 'The selected profile exceeds the settings size limit.', 413)
    return data, stat.S_IMODE(opened.st_mode)


def _owner_error() -> SettingsError:
    return SettingsError('settings_owner_unsafe', 'The selected profile and ledger must remain safe files owned by the local account.', 403)


def _changed() -> SettingsError:
    return SettingsError('settings_configuration_changed', 'The profile changed. Inspect the selected settings before retrying.', 409)


def _valid_stamp(value: object, path: Path) -> bool:
    return (isinstance(value, dict)
            and set(value) == {'path', 'device', 'inode', 'owner_kind', 'owner_value'}
            and value['path'] == str(path)
            and type(value['device']) is int and value['device'] >= 0
            and type(value['inode']) is int and value['inode'] > 0
            and value['owner_kind'] in ('uid', 'sid')
            and isinstance(value['owner_value'], str) and bool(value['owner_value']))


def _require_plain_posix_metadata(path: Path) -> None:
    """A new POSIX file must not silently lose a group or an extended ACL."""
    file_info, parent_info = path.lstat(), path.parent.lstat()
    message = 'The selected profile has group or ACL metadata that requires manual editing.'
    if (file_info.st_gid != parent_info.st_gid or file_info.st_gid != os.getegid()
            or file_info.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)):
        raise SettingsError('settings_metadata_unsupported', message, 409)
    if sys.platform == 'darwin':
        import ctypes
        api = ctypes.CDLL(None, use_errno=True)
        api.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
        api.acl_get_file.restype = ctypes.c_void_p
        api.acl_free.argtypes = [ctypes.c_void_p]
        api.acl_free.restype = ctypes.c_int
        for item, before in ((path, file_info), (path.parent, parent_info)):
            # Darwin's sys/acl.h ACL_TYPE_EXTENDED. ENOENT also represents
            # an absent ACL on an existing file, so recheck file identity.
            ctypes.set_errno(0)
            acl = api.acl_get_file(os.fsencode(item), 0x100)
            error = ctypes.get_errno()
            if acl:
                api.acl_free(acl)
                raise SettingsError('settings_metadata_unsupported', message, 409)
            after = item.lstat()
            if error != errno.ENOENT or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                raise SettingsError('settings_metadata_unsupported', message, 409)
    elif sys.platform == 'linux':
        for item, attributes in ((path, ('system.posix_acl_access', 'system.nfs4_acl')),
                                 (path.parent, ('system.posix_acl_default', 'system.nfs4_acl'))):
            for attribute in attributes:
                try:
                    os.getxattr(item, attribute, follow_symlinks=False)
                except OSError as exc:
                    if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
                        continue
                raise SettingsError('settings_metadata_unsupported', message, 409)
    else:
        raise SettingsError('settings_metadata_unsupported', message, 409)


def _native_replace_windows(path: Path, staged: Path, recovery: Path) -> None:
    import ctypes
    from ctypes import wintypes

    replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    replace.restype = wintypes.BOOL
    # Microsoft ReplaceFileW preserves the destination DACL. No flags allow
    # the native operation to silently ignore an ACL or metadata merge error.
    # A recovery name also retains the original on documented partial failures.
    if not replace(str(path), str(staged), str(recovery), 0, None, None):
        raise OSError(ctypes.get_last_error(), 'The Windows profile replacement did not settle.')


def _replace_windows(path: Path, target: bytes, recovery: Path, verify) -> None:
    if recovery.exists() or recovery.is_symlink():
        raise SettingsError('settings_apply_unconfirmed', 'A native recovery file already exists for this draft. Inspect it and the retained backup before retrying.', 409)
    fd, name = tempfile.mkstemp(prefix='.profile-replace-', dir=recovery.parent)
    staged = Path(name)
    attempted = False
    try:
        with os.fdopen(fd, 'wb') as output:
            secure._windows_protect(staged, directory=False)
            output.write(target)
            output.flush()
            os.fsync(output.fileno())
        verify()
        attempted = True
        _native_replace_windows(path, staged, recovery)
    finally:
        # Once native publication begins, don't discard files that may be
        # needed to inspect its outcome. On success the stage has moved.
        if not attempted:
            staged.unlink(missing_ok=True)


@dataclass(frozen=True)
class _Profile:
    owner: OwnerBinding
    payload: bytes
    mode: int
    raw: dict
    config: FlowConfig

    @property
    def revision(self) -> str:
        return _digest(self.payload)


class DashboardSettings:
    def __init__(self, config_path: Path, database_path: Path, *, loaded_revision: str | None = None):
        self.config_path = Path(config_path).expanduser().absolute()
        self.database_path = Path(database_path).expanduser().absolute()
        self.loaded_revision = loaded_revision
        self._directory = self.config_path.parent / '.flower-settings'
        # Distinct explicit configurations in one directory never share drafts.
        self._draft_path = self._directory / (_digest(os.fsencode(self.config_path)) + '.json')

    def _read(self, *, enforce_loaded: bool = True) -> _Profile:
        try:
            if os.name == 'nt' and any(str(p).startswith('\\\\') for p in (self.config_path, self.database_path)):
                raise _owner_error()
            owner = OwnerBinding(self.config_path, self.database_path)
            if (tuple(item.path for item in owner.resources) != (str(self.config_path), str(self.database_path))
                    or not all(item.inode for item in owner.resources)):
                raise _owner_error()
            payload, mode = _read_existing(self.config_path)
            owner.check()
        except (DashboardAuthError, secure.ServiceSecurityError, OSError):
            raise _owner_error() from None
        raw, config = _parse(payload, self.config_path)
        profile = _Profile(owner, payload, mode, raw, config)
        if config.runtime.database_path != self.database_path:
            raise SettingsError('settings_selection_changed', 'The configuration no longer selects the current ledger.', 409)
        if enforce_loaded and self.loaded_revision is not None and profile.revision != self.loaded_revision:
            raise _changed()
        return profile

    def _draft(self) -> dict | None:
        if not (self._draft_path.exists() or self._draft_path.is_symlink()):
            return None
        try:
            secure._private(self._directory, directory=True)
            value = json.loads(secure.read_owned(self._draft_path), object_pairs_hook=_closed_pairs)
            if (not isinstance(value, dict) or set(value) != {
                'contract', 'id', 'base_revision', 'target_revision', 'config', 'database', 'changes',
            } or value['contract'] != _CONTRACT
                or not isinstance(value['id'], str) or not _ID.fullmatch(value['id'])
                or any(not isinstance(value[key], str) or not _SHA.fullmatch(value[key])
                       for key in ('base_revision', 'target_revision'))
                or not _valid_stamp(value['config'], self.config_path)
                or not _valid_stamp(value['database'], self.database_path)
                or not _changes(value['changes'])):
                raise ValueError('draft fields')
            return value
        except (ValueError, TypeError, OSError, RecursionError):
            raise SettingsError('settings_draft_invalid', 'The retained settings draft cannot be validated. Inspect it before replacing it.', 409) from None

    @staticmethod
    def _state(profile: _Profile, draft: dict) -> str:
        config, database = map(asdict, profile.owner.resources)
        if database != draft['database'] or any(
            config[k] != draft['config'].get(k) for k in ('path', 'owner_kind', 'owner_value')
        ):
            return 'stale'
        if profile.revision == draft['target_revision']:
            return 'applied'
        if profile.revision == draft['base_revision'] and config == draft['config']:
            return 'pending'
        return 'stale'

    def _view(self, profile: _Profile, draft: dict | None) -> dict:
        return {'config_path': str(self.config_path), 'database_path': str(self.database_path),
                'revision': profile.revision, 'loaded_revision': self.loaded_revision,
                'fields': _values(profile.config),
                'draft': None if draft is None else {
                    'id': draft['id'], 'state': self._state(profile, draft), 'changes': draft['changes'],
                }}

    def snapshot(self) -> dict:
        return self._view(self._read(), self._draft())

    def save(self, body: dict) -> dict:
        if (not isinstance(body, dict) or set(body) != {'revision', 'draft_id', 'changes'}
                or not isinstance(body['revision'], str) or not _SHA.fullmatch(body['revision'])
                or (body['draft_id'] is not None and (
                    not isinstance(body['draft_id'], str) or not _ID.fullmatch(body['draft_id'])
                ))):
            raise SettingsError('settings_input_invalid', 'Supply the current profile and draft revisions and the settings changes.')
        changes = _changes(body['changes'])
        profile = self._read()
        if body['revision'] != profile.revision:
            raise _changed()
        if not changes and body['draft_id'] is None and self._draft() is None:
            return self._view(profile, None)
        try:
            secure.ensure_directory(self._directory)
            with acquire_file_ownership(self._draft_path, suffix='.operation.lock') as lock:
                profile = self._read()
                if body['revision'] != profile.revision:
                    raise _changed()
                current = self._draft()
                if body['draft_id'] != (current['id'] if current else None):
                    raise SettingsError('settings_draft_changed', 'The settings draft changed. Reload it before saving or discarding.', 409)
                fields = {field['key']: field for field in _values(profile.config)}
                if any(fields[key].get('readonly') for key in changes):
                    raise SettingsError('settings_input_invalid', 'A selected setting is read-only.')
                changes = {key: value for key, value in changes.items() if value != fields[key]['value']}
                if changes:
                    target, proposed = _merge(profile.raw, self.config_path, changes, profile.config)
                    if proposed == profile.config:
                        changes = {}
                if changes:
                    secure.ensure_directory(self.config_path.parent, private=False)
                    if os.name == 'posix':
                        _require_plain_posix_metadata(self.config_path)
                profile.owner.check()
                lock.assert_resource(self._draft_path)
                if _read_existing(self.config_path)[0] != profile.payload:
                    raise _changed()
                if not changes:
                    secure.remove_owned(self._draft_path)
                    return self._view(profile, None)
                target_revision = _digest(target)
                if (current and self._state(profile, current) == 'pending'
                        and current['changes'] == changes and current['target_revision'] == target_revision):
                    return self._view(profile, current)
                config, database = map(asdict, profile.owner.resources)
                draft = {'contract': _CONTRACT, 'id': uuid4().hex, 'base_revision': profile.revision,
                         'target_revision': target_revision, 'config': config, 'database': database,
                         'changes': changes}
                data = json.dumps(draft, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                if len(data) > _LIMIT:
                    raise SettingsError('settings_draft_too_large', 'The settings draft exceeds its size limit.', 413)
                secure.write_owned(self._draft_path, data)
                return self._view(profile, draft)
        except RuntimeOwnershipError:
            raise SettingsError('settings_draft_busy', 'Another settings operation owns this draft. Inspect it before retrying.', 409) from None
        except (DashboardAuthError, secure.ServiceSecurityError, OSError):
            raise _owner_error() from None


def apply_profile_settings(config_path: Path, draft_id: str) -> dict:
    """Apply one exact draft without constructing a runtime or opening SQLite."""
    if not isinstance(draft_id, str) or not _ID.fullmatch(draft_id):
        raise SettingsError('settings_input_invalid', 'Select the exact retained draft ID.')
    path = Path(config_path).expanduser().absolute()
    try:
        secure.check_data_file(path)
        payload, _ = _read_existing(path)
        _, config = _parse(payload, path)
        service = DashboardSettings(path, config.runtime.database_path)
        service._read(enforce_loaded=False)
        with acquire_runtime_ownership(service.database_path) as lease:
            if service._draft() is None:
                raise SettingsError('settings_draft_missing', 'No retained settings draft matches this profile.', 409)
            with acquire_file_ownership(service._draft_path, suffix='.operation.lock') as lock:
                profile = service._read(enforce_loaded=False)
                draft = service._draft()
                if draft is None or draft['id'] != draft_id:
                    raise SettingsError('settings_draft_changed', 'The selected settings draft is no longer current.', 409)
                state = service._state(profile, draft)
                backup = service._directory / (draft_id + '.yaml.bak')
                if state == 'applied':
                    if _digest(secure.read_owned(backup)) != draft['base_revision']:
                        raise SettingsError('settings_backup_changed', 'Inspect the retained settings backup before continuing.', 409)
                    return {'draft_id': draft_id, 'state': 'applied', 'changed': False,
                            'revision': profile.revision, 'backup_path': str(backup)}
                if state != 'pending':
                    raise _changed()
                readonly = {field['key'] for field in _values(profile.config) if field.get('readonly')}
                if readonly.intersection(draft['changes']):
                    raise SettingsError('settings_draft_invalid', 'The draft attempts to change a read-only setting.', 409)
                target, _ = _merge(profile.raw, path, draft['changes'], profile.config)
                if _digest(target) != draft['target_revision']:
                    raise SettingsError('settings_draft_invalid', 'The exact validated draft no longer reproduces its target.', 409)
                # Never publish through an unsafe directory or silently drop
                # metadata the selected platform's replacement cannot preserve.
                secure.ensure_directory(path.parent, private=False)
                if os.name == 'posix':
                    _require_plain_posix_metadata(path)
                if backup.exists() or backup.is_symlink():
                    if secure.read_owned(backup) != profile.payload:
                        raise SettingsError('settings_backup_changed', 'Inspect the retained settings backup before continuing.', 409)
                else:
                    secure.write_owned(backup, profile.payload)
                def verify():
                    lease.assert_resource(service.database_path)
                    lock.assert_resource(service._draft_path)
                    profile.owner.check()
                    if os.name == 'posix':
                        _require_plain_posix_metadata(path)
                    if _read_existing(path) != (profile.payload, profile.mode):
                        raise _changed()

                try:
                    if os.name == 'nt':
                        _replace_windows(path, target, service._directory / (draft_id + '.windows-original'), verify)
                    else:
                        verify()
                        from flow_of_work_mcp.client_registration import ClientRegistrationError, _replace_config
                        try:
                            _replace_config(path, profile.payload, target, profile.mode)
                        except ClientRegistrationError:
                            raise _changed() from None
                except (secure.ServiceSecurityError, OSError):
                    raise SettingsError('settings_apply_unconfirmed', 'The settings write needs inspection. Preserve the draft and backup before retrying.', 409) from None
                settled = service._read(enforce_loaded=False)
                if service._state(settled, draft) != 'applied':
                    raise SettingsError('settings_apply_unconfirmed', 'The settings write needs inspection. Preserve the draft and backup before retrying.', 409)
                return {'draft_id': draft_id, 'state': 'applied', 'changed': True,
                        'revision': settled.revision, 'backup_path': str(backup)}
    except RuntimeOwnershipError as exc:
        if exc.code == 'ledger_runtime_in_use':
            raise SettingsError('settings_ledger_active', 'Stop the Flower owner of this ledger before applying settings.', 409) from None
        raise SettingsError('settings_ownership_unavailable', 'The selected settings operation could not obtain safe ownership.', 409) from None
    except (DashboardAuthError, secure.ServiceSecurityError, OSError):
        raise _owner_error() from None
