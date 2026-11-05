"""Local SAM/password owner verification; no domain discovery or impersonation."""
from __future__ import annotations

import ctypes as c
import os
from pathlib import Path

from flow_of_work_mcp.dashboard_auth_native import NativeAuthFailure

_DWORD = c.c_uint32
_BOOL = c.c_int32


class _User23(c.Structure):
    _fields_ = [('name', c.c_wchar_p), ('full_name', c.c_wchar_p), ('comment', c.c_wchar_p),
                ('flags', _DWORD), ('sid', c.c_void_p)]


class _User24(c.Structure):
    _fields_ = [('internet_identity', _BOOL), ('flags', _DWORD), ('provider', c.c_wchar_p),
                ('principal', c.c_wchar_p), ('sid', c.c_void_p)]


class _SidAttributes(c.Structure):
    _fields_ = [('sid', c.c_void_p), ('attributes', _DWORD)]


def _error(code: int):
    if code in {1330, 1907}:
        raise NativeAuthFailure('unsupported', 'unsupported_conversation')
    if code in {1326, 1327, 1328, 1329, 1331, 1385, 1793, 1909, 2221}:
        raise NativeAuthFailure('denied', 'credentials_denied')
    raise NativeAuthFailure('unavailable', 'native_authentication_unavailable')


class _Windows:
    def __init__(self):
        # Restrict all system DLL resolution to System32, independent of cwd.
        self.kernel = c.WinDLL('kernel32.dll', use_last_error=True, winmode=0x800)
        self.security = c.WinDLL('advapi32.dll', use_last_error=True, winmode=0x800)
        self.net = c.WinDLL('netapi32.dll', use_last_error=True, winmode=0x800)
        definitions = [
            (self.kernel, 'GetCurrentProcess', [], c.c_void_p),
            (self.kernel, 'CloseHandle', [c.c_void_p], _BOOL),
            (self.kernel, 'LocalFree', [c.c_void_p], c.c_void_p),
            (self.security, 'OpenProcessToken', [c.c_void_p, _DWORD, c.POINTER(c.c_void_p)], _BOOL),
            (self.security, 'GetTokenInformation', [c.c_void_p, c.c_int, c.c_void_p, _DWORD, c.POINTER(_DWORD)], _BOOL),
            (self.security, 'GetUserNameW', [c.c_void_p, c.POINTER(_DWORD)], _BOOL),
            (self.security, 'GetSecurityInfo', [c.c_void_p, c.c_int, _DWORD,
                c.POINTER(c.c_void_p), c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)], _DWORD),
            (self.security, 'IsValidSid', [c.c_void_p], _BOOL),
            (self.security, 'ConvertSidToStringSidW', [c.c_void_p, c.POINTER(c.c_void_p)], _BOOL),
            (self.security, 'ConvertStringSidToSidW', [c.c_wchar_p, c.POINTER(c.c_void_p)], _BOOL),
            (self.security, 'EqualSid', [c.c_void_p, c.c_void_p], _BOOL),
            (self.security, 'LogonUserW', [c.c_wchar_p, c.c_wchar_p, c.c_wchar_p,
                _DWORD, _DWORD, c.POINTER(c.c_void_p)], _BOOL),
            (self.net, 'NetUserGetInfo', [c.c_wchar_p, c.c_wchar_p, _DWORD, c.POINTER(c.c_void_p)], _DWORD),
            (self.net, 'NetApiBufferFree', [c.c_void_p], _DWORD),
            (self.net, 'DsRoleGetPrimaryDomainInformation', [c.c_wchar_p, c.c_int, c.POINTER(c.c_void_p)], _DWORD),
            (self.net, 'DsRoleFreeMemory', [c.c_void_p], None),
        ]
        for library, name, arguments, result in definitions:
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result

    def _free(self, pointer):
        if pointer and self.kernel.LocalFree(pointer):
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')

    def _close(self, handle):
        if handle and not self.kernel.CloseHandle(handle):
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')

    def sid(self, pointer) -> str:
        output = c.c_void_p()
        try:
            if not pointer or not self.security.IsValidSid(pointer):
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            if not self.security.ConvertSidToStringSidW(pointer, c.byref(output)) or not output:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            value = c.wstring_at(output)
            if not value.startswith('S-1-5-21-') or len(value) > 184:
                raise NativeAuthFailure('unsupported', 'unsupported_identity')
            return value
        finally:
            self._free(output)

    def token_sid(self, token, *, require_unprivileged=False) -> str:
        needed = _DWORD()
        if require_unprivileged:
            elevated = _DWORD()
            if not self.security.GetTokenInformation(token, 20, c.byref(elevated), c.sizeof(elevated), c.byref(needed)):
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            if elevated.value:
                raise NativeAuthFailure('unsupported', 'execution_identity_unsupported')
        self.security.GetTokenInformation(token, 1, None, 0, c.byref(needed))
        if not 0 < needed.value <= 65536:
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        buffer = c.create_string_buffer(needed.value)
        if not self.security.GetTokenInformation(token, 1, buffer, len(buffer), c.byref(needed)):
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        return self.sid(c.cast(buffer, c.POINTER(_SidAttributes)).contents.sid)

    def current_identity(self) -> dict:
        token = c.c_void_p()
        try:
            if not self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, c.byref(token)) or not token:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            return {'kind': 'sid', 'value': self.token_sid(token, require_unprivileged=True)}
        finally:
            self._close(token)

    def file_owner(self, path: Path) -> dict:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
        try:
            return self.file_owner_handle(descriptor)
        finally:
            os.close(descriptor)

    def file_owner_handle(self, descriptor_number: int) -> dict:
        import msvcrt
        owner, descriptor = c.c_void_p(), c.c_void_p()
        try:
            handle = msvcrt.get_osfhandle(descriptor_number)
            status = self.security.GetSecurityInfo(handle, 1, 1, c.byref(owner), None, None, None, c.byref(descriptor))
            if status or not descriptor or not owner:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            return {'kind': 'sid', 'value': self.sid(owner)}
        finally:
            self._free(descriptor)

    def current_username(self) -> str:
        buffer = c.create_unicode_buffer(1024)
        size = _DWORD(len(buffer))
        if not self.security.GetUserNameW(buffer, c.byref(size)):
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        return buffer.value

    def require_local_sam(self):
        # NULL server selects this computer. A DC has no qualifying local SAM;
        # NetUserGetInfo(NULL, ...) there could resolve Active Directory users.
        buffer = c.c_void_p()
        try:
            status = self.net.DsRoleGetPrimaryDomainInformation(None, 1, c.byref(buffer))
            if status or not buffer:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            role = c.cast(buffer, c.POINTER(c.c_int32)).contents.value
            if role in {4, 5}:
                raise NativeAuthFailure('unsupported', 'unsupported_identity')
            if role not in {0, 1, 2, 3}:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        finally:
            if buffer:
                self.net.DsRoleFreeMemory(buffer)

    def local_user(self, username: str) -> dict:
        self.require_local_sam()
        if any(character in username for character in '\\/@'):
            raise NativeAuthFailure('denied', 'credentials_denied')
        buffer = c.c_void_p()
        try:
            status = self.net.NetUserGetInfo(None, username, 23, c.byref(buffer))
            if status or not buffer:
                _error(int(status))
            user = c.cast(buffer, c.POINTER(_User23)).contents
            if not user.name:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            result = {'name': str(user.name), 'sid': self.sid(user.sid), 'flags': int(user.flags)}
        finally:
            if buffer and self.net.NetApiBufferFree(buffer):
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        buffer = c.c_void_p()
        try:
            status = self.net.NetUserGetInfo(None, result['name'], 24, c.byref(buffer))
            if status or not buffer:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            linked = c.cast(buffer, c.POINTER(_User24)).contents.internet_identity
            if linked:
                raise NativeAuthFailure('unsupported', 'unsupported_identity')
            # Microsoft requires all remaining USER_INFO_24 fields be ignored
            # when internet_identity is false. The SID is from level23 above.
        finally:
            if buffer and self.net.NetApiBufferFree(buffer):
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        if result['flags'] & (0x2 | 0x10):
            raise NativeAuthFailure('denied', 'native_account_restricted')
        if result['flags'] & (0x800000 | 0x40000):
            raise NativeAuthFailure('unsupported', 'unsupported_conversation')
        return result

    def authenticate(self, username: str, password: str, expected_sid: str) -> str:
        # Explicit UTF16 storage preserves non-BMP characters without truncation.
        secret = c.create_string_buffer(password.encode('utf-16-le') + b'\x00\x00')
        token, expected = c.c_void_p(), c.c_void_p()
        try:
            if not self.security.ConvertStringSidToSidW(expected_sid, c.byref(expected)) or not expected:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            if not self.security.LogonUserW(username, '.', c.cast(secret, c.c_wchar_p), 3, 0, c.byref(token)):
                _error(c.get_last_error())
            actual = self.token_sid(token)
            actual_pointer = c.c_void_p()
            try:
                if not self.security.ConvertStringSidToSidW(actual, c.byref(actual_pointer)):
                    raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
                if not self.security.EqualSid(actual_pointer, expected):
                    raise NativeAuthFailure('denied', 'owner_mismatch')
            finally:
                self._free(actual_pointer)
            return actual
        finally:
            c.memset(secret, 0, c.sizeof(secret))
            try:
                self._close(token)
            finally:
                self._free(expected)


def current_identity() -> dict:
    return _Windows().current_identity()


def file_owner(path: Path) -> dict:
    return _Windows().file_owner(path)


def file_owner_handle(descriptor: int) -> dict:
    return _Windows().file_owner_handle(descriptor)


def capability(owner: dict) -> None:
    native = _Windows()
    user = native.local_user(native.current_username())
    if user['sid'] != owner['value']:
        raise NativeAuthFailure('unsupported', 'unsupported_identity')


def verify(owner: dict, username: str, password: str) -> dict:
    native = _Windows()
    before = native.local_user(username)
    if before['sid'] != owner['value']:
        raise NativeAuthFailure('denied', 'credentials_denied')
    actual = native.authenticate(before['name'], password, owner['value'])
    after = native.local_user(before['name'])
    if actual != owner['value'] or after['sid'] != owner['value']:
        raise NativeAuthFailure('denied', 'owner_mismatch')
    return {**owner, 'local': True}
