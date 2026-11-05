"""Local-node Open Directory owner verification through system C APIs."""
from __future__ import annotations

import ctypes as c
import pwd
from uuid import UUID

from flow_of_work_mcp.dashboard_auth_native import NativeAuthFailure

_UTF8 = 0x08000100
_LOCAL_NODE = 0x2200


def _failure(code: int) -> NativeAuthFailure:
    if code in {5000, 5101, 5300, 5301, 5302, 5303, 5304, 5305, 5500, 5501}:
        return NativeAuthFailure('denied', 'credentials_denied')
    if code in {5100, 5400, 5401}:
        return NativeAuthFailure('unsupported', 'unsupported_conversation')
    return NativeAuthFailure('unavailable', 'native_authentication_unavailable')


class _OD:
    def __init__(self):
        self.cf = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.od = c.CDLL('/System/Library/Frameworks/OpenDirectory.framework/OpenDirectory')
        self.objects: list[int] = []
        specifications = [
            (self.cf, 'CFRelease', [c.c_void_p], None),
            (self.cf, 'CFStringCreateWithBytes', [c.c_void_p, c.c_void_p, c.c_long, c.c_uint32, c.c_ubyte], c.c_void_p),
            (self.cf, 'CFStringGetCString', [c.c_void_p, c.c_void_p, c.c_long, c.c_uint32], c.c_ubyte),
            (self.cf, 'CFStringGetLength', [c.c_void_p], c.c_long),
            (self.cf, 'CFStringGetMaximumSizeForEncoding', [c.c_long, c.c_uint32], c.c_long),
            (self.cf, 'CFStringGetTypeID', [], c.c_ulong),
            (self.cf, 'CFArrayGetTypeID', [], c.c_ulong),
            (self.cf, 'CFGetTypeID', [c.c_void_p], c.c_ulong),
            (self.cf, 'CFArrayGetCount', [c.c_void_p], c.c_long),
            (self.cf, 'CFArrayGetValueAtIndex', [c.c_void_p, c.c_long], c.c_void_p),
            (self.cf, 'CFErrorGetCode', [c.c_void_p], c.c_long),
            (self.od, 'ODNodeCreateWithNodeType', [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_void_p)], c.c_void_p),
            (self.od, 'ODNodeCopyRecord', [c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)], c.c_void_p),
            (self.od, 'ODRecordCopyValues', [c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)], c.c_void_p),
            (self.od, 'ODRecordAuthenticationAllowed', [c.c_void_p, c.POINTER(c.c_void_p)], c.c_bool),
            (self.od, 'ODRecordVerifyPassword', [c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)], c.c_bool),
        ]
        for library, name, args, result in specifications:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result
        self.session = c.c_void_p.in_dll(self.od, 'kODSessionDefault').value
        self.users = c.c_void_p.in_dll(self.od, 'kODRecordTypeUsers').value
        self.attributes = {name: c.c_void_p.in_dll(self.od, symbol).value for name, symbol in (
            ('uid', 'kODAttributeTypeUniqueID'), ('guid', 'kODAttributeTypeGUID'),
            ('node', 'kODAttributeTypeMetaNodeLocation'), ('original', 'kODAttributeTypeOriginalNodeName'))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for value in reversed(self.objects):
            self.cf.CFRelease(value)
        self.objects.clear()

    def _owned(self, value):
        if value:
            self.objects.append(value)
        return value

    def _error(self, error) -> int:
        if not error.value:
            return 0
        try:
            return int(self.cf.CFErrorGetCode(error))
        finally:
            self.cf.CFRelease(error)

    def string(self, text: str):
        raw = c.create_string_buffer(text.encode('utf-8'))
        try:
            value = self._owned(self.cf.CFStringCreateWithBytes(None, raw, c.sizeof(raw) - 1, _UTF8, False))
            if not value:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            return value
        finally:
            c.memset(raw, 0, c.sizeof(raw))

    def text(self, value) -> str:
        if self.cf.CFGetTypeID(value) != self.cf.CFStringGetTypeID():
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        size = self.cf.CFStringGetMaximumSizeForEncoding(self.cf.CFStringGetLength(value), _UTF8) + 1
        if not 0 < size <= 8192:
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        buffer = c.create_string_buffer(size)
        if not self.cf.CFStringGetCString(value, buffer, size, _UTF8):
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
        return buffer.value.decode('utf-8')

    def node(self):
        error = c.c_void_p()
        value = self._owned(self.od.ODNodeCreateWithNodeType(None, self.session, _LOCAL_NODE, c.byref(error)))
        code = self._error(error)
        if not value or code:
            raise _failure(code)
        return value

    def record(self, node, username: str):
        error = c.c_void_p()
        value = self._owned(self.od.ODNodeCopyRecord(node, self.users, self.string(username), None, c.byref(error)))
        code = self._error(error)
        if not value or code:
            if not value and code in {0, 4104, 5300}:
                raise NativeAuthFailure('denied', 'credentials_denied')
            raise _failure(code)
        return value

    def values(self, record, name: str, *, optional=False) -> list[str]:
        error = c.c_void_p()
        array = self.od.ODRecordCopyValues(record, self.attributes[name], c.byref(error))
        code = self._error(error)
        try:
            if optional and not array and code in {0, 4201}:
                return []
            if not array or code or self.cf.CFGetTypeID(array) != self.cf.CFArrayGetTypeID():
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            count = self.cf.CFArrayGetCount(array)
            if not 0 <= count <= 16:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            return [self.text(self.cf.CFArrayGetValueAtIndex(array, index)) for index in range(count)]
        finally:
            if array:
                self.cf.CFRelease(array)

    def identity(self, record, owner: dict) -> tuple[str, str]:
        uid, guid, node = (self.values(record, name) for name in ('uid', 'guid', 'node'))
        original = self.values(record, 'original', optional=True)
        if (uid != [owner['value']] or len(guid) != 1 or node != ['/Local/Default']
                or any(value and value != '/Local/Default' for value in original)):
            raise NativeAuthFailure('denied', 'credentials_denied')
        try:
            normalized_guid = str(UUID(guid[0]))
        except ValueError:
            raise NativeAuthFailure('unavailable', 'native_identity_unavailable') from None
        return uid[0], normalized_guid

    def allowed(self, record):
        error = c.c_void_p()
        allowed = self.od.ODRecordAuthenticationAllowed(record, c.byref(error))
        code = self._error(error)
        if not allowed or code:
            if not code:
                raise NativeAuthFailure('denied', 'native_account_restricted')
            raise _failure(code)

    def password(self, record, password: str):
        error = c.c_void_p()
        accepted = self.od.ODRecordVerifyPassword(record, self.string(password), c.byref(error))
        code = self._error(error)
        if not accepted or code:
            raise _failure(code or 5000)


def capability(owner: dict) -> None:
    try:
        username = pwd.getpwuid(int(owner['value'])).pw_name
    except (KeyError, ValueError):
        raise NativeAuthFailure('unavailable', 'native_identity_unavailable') from None
    with _OD() as native:
        record = native.record(native.node(), username)
        native.identity(record, owner)
        native.allowed(record)


def verify(owner: dict, username: str, password: str) -> dict:
    with _OD() as native:
        node = native.node()
        record = native.record(node, username)
        before = native.identity(record, owner)
        native.allowed(record)
        native.password(record, password)
        fresh = native.record(node, username)
        if native.identity(fresh, owner) != before:
            raise NativeAuthFailure('denied', 'owner_mismatch')
        native.allowed(fresh)
    return {**owner, 'local': True}
