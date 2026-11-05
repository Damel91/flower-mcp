"""Same-UID Linux-PAM owner authentication; no custom privileged helper."""
from __future__ import annotations

import ctypes as c
import ctypes.util
import hashlib
from pathlib import Path
import stat

from flow_of_work_mcp.dashboard_auth_native import NativeAuthFailure

POLICY = Path('/etc/pam.d/flower-mcp')
PASSWD = Path('/etc/passwd')
PAM_SUCCESS = 0
PAM_CONV_ERR = 19
PAM_DISALLOW_NULL_AUTHTOK = 1


def _execution_constraints() -> None:
    # The first supported policy uses pam_unix's distro-owned privilege helper.
    # Never alter a sandbox setting to make that helper work.
    library = c.CDLL(None, use_errno=True)
    function = library.prctl
    function.argtypes = [c.c_int, c.c_ulong, c.c_ulong, c.c_ulong, c.c_ulong]
    function.restype = c.c_int
    if function(39, 0, 0, 0, 0) != 0:  # PR_GET_NO_NEW_PRIVS
        raise NativeAuthFailure('unavailable', 'native_authentication_unavailable')


def _policy() -> tuple:
    try:
        for path, directory in ((POLICY.parent, True), (POLICY, False)):
            info = path.lstat()
            if (info.st_uid != 0 or info.st_mode & 0o022
                    or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
                raise NativeAuthFailure('unavailable', 'native_policy_unsafe')
        with POLICY.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536 or b'\x00' in raw:
            raise NativeAuthFailure('unavailable', 'native_policy_unsafe')
        categories = {line.split()[0].lstrip('-') for line in raw.decode('utf-8').splitlines()
                      if line.strip() and not line.lstrip().startswith('#')}
        if not {'auth', 'account'} <= categories:
            raise NativeAuthFailure('unavailable', 'native_policy_unsafe')
        return info.st_dev, info.st_ino, info.st_mtime_ns, hashlib.sha256(raw).digest()
    except (OSError, UnicodeError):
        raise NativeAuthFailure('unavailable', 'native_policy_unavailable') from None


def _local_user(owner: dict, username: str | None = None) -> str:
    try:
        with PASSWD.open('rb') as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError
        matches = []
        for line in raw.decode('utf-8').splitlines():
            fields = line.split(':')
            if len(fields) == 7 and fields[2] == owner['value']:
                matches.append(fields[0])
        if len(matches) != 1 or (username is not None and matches[0] != username):
            raise NativeAuthFailure('denied', 'credentials_denied')
        return matches[0]
    except (OSError, UnicodeError, ValueError):
        raise NativeAuthFailure('unavailable', 'native_identity_unavailable') from None


class _Message(c.Structure):
    _fields_ = [('style', c.c_int), ('message', c.c_char_p)]


class _Response(c.Structure):
    _fields_ = [('response', c.c_void_p), ('return_code', c.c_int)]


_ConversationFunction = c.CFUNCTYPE(c.c_int, c.c_int, c.POINTER(c.POINTER(_Message)),
                                   c.POINTER(c.POINTER(_Response)), c.c_void_p)


class _Conversation(c.Structure):
    _fields_ = [('function', _ConversationFunction), ('data', c.c_void_p)]


class _PAM:
    def __init__(self):
        library = ctypes.util.find_library('pam')
        if not library:
            raise NativeAuthFailure('unavailable', 'native_library_unavailable')
        self.lib = c.CDLL(library)
        self.lib.pam_start.argtypes = [c.c_char_p, c.c_char_p, c.POINTER(_Conversation), c.POINTER(c.c_void_p)]
        self.lib.pam_start.restype = c.c_int
        for name in ('pam_authenticate', 'pam_acct_mgmt', 'pam_end'):
            call = getattr(self.lib, name)
            call.argtypes = [c.c_void_p, c.c_int]
            call.restype = c.c_int
        self.lib.pam_get_item.argtypes = [c.c_void_p, c.c_int, c.POINTER(c.c_void_p)]
        self.lib.pam_get_item.restype = c.c_int
        self.memory = c.CDLL(None)
        self.memory.calloc.argtypes = [c.c_size_t, c.c_size_t]
        self.memory.calloc.restype = c.c_void_p
        self.memory.free.argtypes = [c.c_void_p]
        self.memory.free.restype = None

    def authenticate(self, username: str, password: str) -> str:
        secret = c.create_string_buffer(password.encode('utf-8'))
        supplied = False
        unsupported = False

        def converse(count, messages, responses, _):
            nonlocal supplied, unsupported
            allocated = []
            array = None
            try:
                if not 0 < count <= 32 or not messages or not responses:
                    unsupported = True
                    return PAM_CONV_ERR
                pointer = self.memory.calloc(count, c.sizeof(_Response))
                if not pointer:
                    return 5
                array = c.cast(pointer, c.POINTER(_Response))
                for index in range(count):
                    style = messages[index].contents.style
                    if style == 1 and not supplied:
                        answer = self.memory.calloc(c.sizeof(secret), 1)
                        if not answer:
                            raise MemoryError
                        allocated.append(answer)
                        c.memmove(answer, secret, c.sizeof(secret))
                        array[index].response = answer
                        supplied = True
                    elif style not in {3, 4}:
                        unsupported = True
                        raise ValueError
                responses[0] = array
                return PAM_SUCCESS
            except Exception:
                for answer in allocated:
                    c.memset(answer, 0, c.sizeof(secret))
                    self.memory.free(answer)
                if array is not None:
                    self.memory.free(c.cast(array, c.c_void_p))
                return PAM_CONV_ERR

        callback = _ConversationFunction(converse)
        conversation = _Conversation(callback, None)
        handle = c.c_void_p()
        status = 4
        started = False
        try:
            status = self.lib.pam_start(b'flower-mcp', username.encode('utf-8'), c.byref(conversation), c.byref(handle))
            started = status == PAM_SUCCESS
            if status == PAM_SUCCESS:
                status = self.lib.pam_authenticate(handle, PAM_DISALLOW_NULL_AUTHTOK)
            if status == PAM_SUCCESS:
                status = self.lib.pam_acct_mgmt(handle, PAM_DISALLOW_NULL_AUTHTOK)
            if unsupported:
                raise NativeAuthFailure('unsupported', 'unsupported_conversation')
            if status == PAM_SUCCESS and not supplied:
                raise NativeAuthFailure('unavailable', 'native_policy_unsafe')
            if status != PAM_SUCCESS:
                if status in {1, 2, 3, 4, 5, 8, 9, 15, 19, 26, 28}:
                    raise NativeAuthFailure('unavailable', 'native_authentication_unavailable')
                if status in {12, 27, 30, 31}:
                    raise NativeAuthFailure('unsupported', 'unsupported_conversation')
                raise NativeAuthFailure('denied', 'credentials_denied')
            actual = c.c_void_p()
            if self.lib.pam_get_item(handle, 2, c.byref(actual)) != PAM_SUCCESS or not actual:
                raise NativeAuthFailure('unavailable', 'native_identity_unavailable')
            return c.string_at(actual).decode('utf-8')
        finally:
            c.memset(secret, 0, c.sizeof(secret))
            if started:
                if self.lib.pam_end(handle, status) != PAM_SUCCESS:
                    raise NativeAuthFailure('unavailable', 'native_authentication_unavailable')


def capability(owner: dict) -> None:
    _policy()
    _local_user(owner)
    _execution_constraints()
    _PAM()


def verify(owner: dict, username: str, password: str) -> dict:
    policy = _policy()
    _local_user(owner, username)
    _execution_constraints()
    # Linux-PAM's documented response bound includes the terminating NUL.
    if len(password.encode('utf-8')) >= 512:
        raise NativeAuthFailure('unsupported', 'native_input_unsupported')
    actual = _PAM().authenticate(username, password)
    _local_user(owner, actual)
    if _policy() != policy:
        raise NativeAuthFailure('unavailable', 'native_policy_unsafe')
    return {**owner, 'local': True}
