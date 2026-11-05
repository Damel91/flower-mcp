"""Lazy OS owner verification boundary; no password attempts during discovery."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import re
import sys

CONTRACT = 'flow.dashboard.native_auth.v1'
CAPABILITY_CONTRACT = 'flow.dashboard.native_capability.v1'
MAX_REQUEST_BYTES = 20 * 1024
MAX_REPLY_BYTES = 8 * 1024
MAX_USERNAME_BYTES = 1024
MAX_PASSWORD_BYTES = 8192
OUTCOMES = frozenset({'verified', 'denied', 'unavailable', 'unsupported', 'error'})
REASONS = frozenset({
    'credentials_denied', 'native_library_unavailable', 'native_policy_unavailable',
    'native_policy_unsafe', 'native_identity_unavailable', 'native_authentication_unavailable',
    'native_verification_failed', 'native_account_restricted', 'native_input_unsupported',
    'unsupported_identity', 'unsupported_conversation', 'unsupported_platform',
    'owner_mismatch', 'execution_identity_unsupported', 'protocol_invalid', 'internal_error',
})


class NativeAuthFailure(Exception):
    """Only fixed, nonsecret public outcomes cross the native boundary."""

    def __init__(self, outcome: str, reason: str):
        if outcome not in OUTCOMES - {'verified'} or reason not in REASONS:
            raise ValueError('invalid native authentication failure')
        self.outcome = outcome
        self.reason = reason
        super().__init__(reason)


def platform_name() -> str:
    if sys.platform.startswith('linux'):
        return 'linux'
    if sys.platform == 'darwin':
        return 'macos'
    if sys.platform == 'win32':
        return 'windows'
    raise NativeAuthFailure('unsupported', 'unsupported_platform')


def canonical_identity(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {'kind', 'value'}:
        raise ValueError('invalid identity')
    kind, identity = value['kind'], value['value']
    if not isinstance(identity, str):
        raise ValueError('invalid identity')
    if kind == 'uid' and re.fullmatch(r'0|[1-9][0-9]{0,9}', identity):
        if int(identity) > 0xFFFFFFFF:
            raise ValueError('invalid identity')
    elif kind == 'sid' and len(identity) <= 184 and re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}', identity):
        if any(str(int(part)) != part for part in identity.split('-')[2:]):
            raise ValueError('invalid identity')
    else:
        raise ValueError('invalid identity')
    return {'kind': kind, 'value': identity}


def _backend():
    name = platform_name()
    return importlib.import_module('flow_of_work_mcp.adapters.native.dashboard_auth_' + name)


def current_identity() -> dict[str, str]:
    if platform_name() == 'windows':
        return canonical_identity(_backend().current_identity())
    uid = os.getuid()
    if uid == 0 or uid != os.geteuid():
        raise NativeAuthFailure('unsupported', 'execution_identity_unsupported')
    return {'kind': 'uid', 'value': str(uid)}


def file_owner(path: str | Path) -> dict[str, str]:
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(Path(path), flags)
    try:
        return file_owner_handle(descriptor)
    finally:
        os.close(descriptor)


def file_owner_handle(descriptor: int) -> dict[str, str]:
    if platform_name() == 'windows':
        return canonical_identity(_backend().file_owner_handle(descriptor))
    return {'kind': 'uid', 'value': str(os.fstat(descriptor).st_uid)}


def _owner(owner: object) -> dict[str, str]:
    identity = canonical_identity(owner)
    if identity != current_identity():
        raise NativeAuthFailure('denied', 'owner_mismatch')
    return identity


def capability(owner: object) -> dict:
    try:
        identity = _owner(owner)
        _backend().capability(identity)
        return {'availability': 'ready', 'reason': None}
    except NativeAuthFailure as exc:
        return {'availability': 'unavailable', 'reason': exc.reason}
    except (OSError, AttributeError, ImportError):
        return {'availability': 'unavailable', 'reason': 'native_library_unavailable'}
    except (ValueError, TypeError, OverflowError):
        return {'availability': 'unavailable', 'reason': 'unsupported_identity'}
    except Exception:
        return {'availability': 'unavailable', 'reason': 'internal_error'}


def validate_credentials(username: object, password: object) -> tuple[str, str]:
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        raise ValueError('invalid credentials')
    if '\x00' in username or '\x00' in password:
        raise ValueError('invalid credentials')
    if len(username.encode('utf-8')) > MAX_USERNAME_BYTES or len(password.encode('utf-8')) > MAX_PASSWORD_BYTES:
        raise ValueError('invalid credentials')
    return username, password


def verify(owner: object, username: object, password: object) -> dict:
    try:
        identity = _owner(owner)
        username, password = validate_credentials(username, password)
        result = _backend().verify(identity, username, password)
        if not isinstance(result, dict) or result != {**identity, 'local': True} or result.get('local') is not True:
            raise NativeAuthFailure('denied', 'owner_mismatch')
        return {'outcome': 'verified', 'identity': result, 'reason': None}
    except NativeAuthFailure as exc:
        return {'outcome': exc.outcome, 'identity': None, 'reason': exc.reason}
    except (OSError, AttributeError, ImportError):
        return {'outcome': 'unavailable', 'identity': None, 'reason': 'native_library_unavailable'}
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return {'outcome': 'denied', 'identity': None, 'reason': 'credentials_denied'}
    except Exception:
        return {'outcome': 'error', 'identity': None, 'reason': 'internal_error'}


def validate_request(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {'contract', 'platform', 'owner', 'username', 'password'}:
        raise ValueError('invalid request')
    if value['contract'] != CONTRACT or value['platform'] != platform_name():
        raise ValueError('invalid request')
    identity = canonical_identity(value['owner'])
    expected = 'sid' if value['platform'] == 'windows' else 'uid'
    if identity['kind'] != expected:
        raise ValueError('invalid request')
    validate_credentials(value['username'], value['password'])
    return value


def validate_reply(value: object, owner: object) -> dict:
    if not isinstance(value, dict) or set(value) != {'contract', 'outcome', 'identity', 'reason'}:
        raise ValueError('invalid reply')
    if value['contract'] != CONTRACT or not isinstance(value['outcome'], str) or value['outcome'] not in OUTCOMES:
        raise ValueError('invalid reply')
    if value['outcome'] == 'verified':
        if (value['identity'] != {**canonical_identity(owner), 'local': True}
                or value['identity'].get('local') is not True or value['reason'] is not None):
            raise ValueError('invalid reply')
    elif value['identity'] is not None or not isinstance(value['reason'], str) or value['reason'] not in REASONS:
        raise ValueError('invalid reply')
    return value


def validate_capability_request(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {'contract', 'platform', 'owner'}:
        raise ValueError('invalid capability request')
    if value['contract'] != CAPABILITY_CONTRACT or value['platform'] != platform_name():
        raise ValueError('invalid capability request')
    identity = canonical_identity(value['owner'])
    if identity['kind'] != ('sid' if value['platform'] == 'windows' else 'uid'):
        raise ValueError('invalid capability request')
    return value


def validate_capability_reply(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {'contract', 'availability', 'reason'}:
        raise ValueError('invalid capability reply')
    if value['contract'] != CAPABILITY_CONTRACT:
        raise ValueError('invalid capability reply')
    if value['availability'] == 'ready':
        if value['reason'] is not None:
            raise ValueError('invalid capability reply')
    elif value['availability'] != 'unavailable' or not isinstance(value['reason'], str) or value['reason'] not in REASONS:
        raise ValueError('invalid capability reply')
    return value
