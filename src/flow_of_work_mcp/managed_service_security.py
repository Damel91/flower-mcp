"""Owner-only local files for the optional user service control protocol."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import stat
import tempfile


class ServiceSecurityError(ValueError):
    code = "service_control_unsafe"


def _unsafe() -> ServiceSecurityError:
    return ServiceSecurityError("The selected service files cannot be trusted; inspect ownership and aliases.")


def _identity():
    from flow_of_work_mcp.dashboard_auth_native import current_identity
    return current_identity()


def _owner(path: Path):
    from flow_of_work_mcp.dashboard_auth_native import file_owner
    return file_owner(path)


def _metadata(path: Path, *, directory: bool):
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise _unsafe()
        info = path.lstat()
        wanted = stat.S_ISDIR if directory else stat.S_ISREG
        if not wanted(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise _unsafe()
        if not directory and info.st_nlink != 1:
            raise _unsafe()
        owned = _windows_directory_owner(path) if os.name == "nt" and directory else _owner(path) == _identity()
        if not owned:
            raise _unsafe()
        return info
    except OSError as exc:
        raise _unsafe() from exc


def check_data_file(path: Path):
    """Prove an existing selected file's owner without changing its permissions."""
    _metadata(path, directory=False)
    return _owner(path)


def _windows_api():
    from ctypes import wintypes as w
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ptr = ctypes.c_void_p
    api.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, ctypes.c_int, w.DWORD,
        ctypes.POINTER(ptr), ctypes.POINTER(ptr), ctypes.POINTER(ptr), ctypes.POINTER(ptr), ctypes.POINTER(ptr)]
    api.GetNamedSecurityInfoW.restype = w.DWORD
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ptr), ctypes.POINTER(w.DWORD)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    api.GetSecurityDescriptorDacl.argtypes = [ptr, ctypes.POINTER(w.BOOL), ctypes.POINTER(ptr), ctypes.POINTER(w.BOOL)]
    api.GetSecurityDescriptorDacl.restype = w.BOOL
    api.GetSecurityDescriptorControl.argtypes = [ptr, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)]
    api.GetSecurityDescriptorControl.restype = w.BOOL
    api.SetNamedSecurityInfoW.argtypes = [w.LPWSTR, ctypes.c_int, w.DWORD, ptr, ptr, ptr, ptr]
    api.SetNamedSecurityInfoW.restype = w.DWORD
    api.GetAclInformation.argtypes = [ptr, ptr, w.DWORD, ctypes.c_int]
    api.GetAclInformation.restype = w.BOOL
    api.GetAce.argtypes = [ptr, w.DWORD, ctypes.POINTER(ptr)]
    api.GetAce.restype = w.BOOL
    api.EqualSid.argtypes = [ptr, ptr]
    api.EqualSid.restype = w.BOOL
    api.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, ctypes.POINTER(ptr)]
    api.ConvertStringSidToSidW.restype = w.BOOL
    api.IsValidSid.argtypes = [ptr]
    api.IsValidSid.restype = w.BOOL
    kernel.LocalFree.argtypes = [ptr]
    kernel.LocalFree.restype = ptr
    return api, kernel, w


def _windows_directory_owner(path: Path):
    # CRT file_owner cannot portably open directories. Query the directory's
    # native descriptor; lstat/resolve already reject reparse aliases.
    api, kernel, _ = _windows_api()
    owner, descriptor, expected = (ctypes.c_void_p() for _ in range(3))
    try:
        if api.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)):
            raise _unsafe()
        if not owner or not api.ConvertStringSidToSidW(_identity()["value"], ctypes.byref(expected)):
            raise _unsafe()
        return bool(api.EqualSid(owner, expected))
    finally:
        if expected:
            kernel.LocalFree(expected)
        if descriptor:
            kernel.LocalFree(descriptor)


def _windows_protect(path: Path, *, directory: bool):
    """Use a protected owner-only inheritable DACL, never chmod as a Windows ACL."""
    api, kernel, w = _windows_api()
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    present, defaulted = w.BOOL(), w.BOOL()
    flags = "OICI" if directory else ""
    sid = _identity()
    if sid.get("kind") != "sid":
        raise _unsafe()
    sddl = f"D:P(A;{flags};FA;;;{sid['value']})"
    try:
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise _unsafe()
        if not api.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present or not dacl:
            raise _unsafe()
        if api.SetNamedSecurityInfoW(str(path), 1, 0x00000004 | 0x80000000, None, None, dacl, None):
            raise _unsafe()
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)


def _windows_private(path: Path, *, directory: bool):
    api, kernel, w = _windows_api()
    descriptor, owner, dacl, expected = (ctypes.c_void_p() for _ in range(4))
    control, revision = w.WORD(), w.DWORD()

    class ACLSize(ctypes.Structure):
        _fields_ = [("count", w.DWORD), ("used", w.DWORD), ("free", w.DWORD)]

    try:
        if api.GetNamedSecurityInfoW(str(path), 1, 1 | 4, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor)):
            raise _unsafe()
        if not descriptor or not owner or not dacl:
            raise _unsafe()
        if not api.ConvertStringSidToSidW(_identity()["value"], ctypes.byref(expected)) or not api.EqualSid(owner, expected):
            raise _unsafe()
        if not api.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)) or not control.value & 0x1000:
            raise _unsafe()
        size = ACLSize()
        if not api.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2) or size.count != 1:
            raise _unsafe()
        ace = ctypes.c_void_p()
        if not api.GetAce(dacl, 0, ctypes.byref(ace)) or not ace:
            raise _unsafe()
        header = ctypes.string_at(ace, 8)
        ace_size = int.from_bytes(header[2:4], "little")
        expected_flags = 3 if directory else 0
        if (header[0] != 0 or header[1] != expected_flags or ace_size < 16
            or int.from_bytes(header[4:8], "little") != 0x1F01FF
            or ace.value < dacl.value + 8 or ace.value + ace_size > dacl.value + size.used):
            raise _unsafe()
        candidate = ctypes.c_void_p(ace.value + 8)
        sid_header = ctypes.string_at(candidate, 8)
        if (sid_header[1] > 15 or 8 + sid_header[1] * 4 > ace_size - 8
            or not api.IsValidSid(candidate) or not api.EqualSid(candidate, expected)):
            raise _unsafe()
    finally:
        if expected:
            kernel.LocalFree(expected)
        if descriptor:
            kernel.LocalFree(descriptor)


def _private(path: Path, *, directory: bool):
    info = _metadata(path, directory=directory)
    if os.name == "nt":
        _windows_private(path, directory=directory)
    elif info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise _unsafe()
    return info


def ensure_directory(path: Path, *, private: bool = True):
    """Create only missing directories; never chmod an existing foreign definition."""
    if not path.is_absolute() or path.resolve() != path:
        raise _unsafe()
    if not path.exists():
        ensure_directory(path.parent, private=False)
        try:
            path.mkdir(mode=0o700)
        except OSError as exc:
            raise _unsafe() from exc
        if os.name == "nt":
            _windows_protect(path, directory=True)
    info = _metadata(path, directory=True)
    if private:
        _private(path, directory=True)
    elif os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o022:
        raise _unsafe()


def read_owned(path: Path, *, limit: int = 65536) -> bytes:
    before = _private(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        held = os.fstat(fd)
        if not held.st_ino or (held.st_dev, held.st_ino) != (before.st_dev, before.st_ino):
            raise _unsafe()
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(limit + 1)
        after = _private(path, directory=False)
        if len(data) > limit or (held.st_dev, held.st_ino) != (after.st_dev, after.st_ino):
            raise _unsafe()
        return data
    finally:
        os.close(fd)


def write_owned(path: Path, data: bytes, *, private_parent: bool = True):
    ensure_directory(path.parent, private=private_parent)
    before = _private(path, directory=False) if path.exists() or path.is_symlink() else None
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    name = Path(temporary)
    opened = True
    try:
        if os.name == "nt":
            _windows_protect(name, directory=False)
        with os.fdopen(fd, "wb") as output:
            opened = False
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if before is not None:
            current = _private(path, directory=False)
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise _unsafe()
        if os.name == "nt":
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.MoveFileExW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
            kernel.MoveFileExW.restype = w.BOOL
            if not kernel.MoveFileExW(str(name), str(path), 0x1 | 0x8):
                raise _unsafe()
        else:
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        _private(path, directory=False)
    finally:
        if opened:
            os.close(fd)
        if name.exists():
            name.unlink()


def remove_owned(path: Path):
    if path.exists() or path.is_symlink():
        _private(path, directory=False)
        path.unlink()
