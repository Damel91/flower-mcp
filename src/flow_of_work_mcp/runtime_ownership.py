"""Nonblocking, process-owned leases for selected host-local resources.

The stable sidecar names a lock, not its owner. Only the operating system's
held file lock proves ownership; a leftover file after a crash is harmless.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from types import TracebackType


class RuntimeOwnershipError(RuntimeError):
    """A selected resource could not be owned safely and exclusively."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class RuntimeOwnership:
    """One OS lease, transferred to its runtime or used as a context manager."""

    def __init__(self, resource_path: Path, lock_path: Path, descriptor: int) -> None:
        self.resource_path = resource_path
        self.lock_path = lock_path
        self._descriptor: int | None = descriptor

    def assert_resource(self, resource_path: str | Path) -> None:
        if self._descriptor is None:
            raise RuntimeOwnershipError(
                "resource_ownership_inactive", "The resource ownership lease is closed."
            )
        if _canonical_resource(resource_path) != self.resource_path:
            raise RuntimeOwnershipError(
                "resource_ownership_mismatch",
                "The ownership lease belongs to a different resource.",
            )
        _assert_sidecar_identity(self.lock_path, self._descriptor)

    def close(self) -> None:
        """Close the descriptor to release the OS lease; never unlink its path."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self) -> RuntimeOwnership:
        try:
            self.assert_resource(self.resource_path)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _unsafe(message: str) -> RuntimeOwnershipError:
    return RuntimeOwnershipError("resource_ownership_unsafe", message)


def _canonical_resource(resource_path: str | Path) -> Path:
    try:
        return Path(resource_path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise _unsafe("The selected resource path cannot be resolved safely.") from exc


def _assert_regular_sidecar(lock_path: Path, metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise _unsafe(f"Ownership lock must be a regular file without hard-link aliases: {lock_path}")


def _assert_sidecar_identity(lock_path: Path, descriptor: int) -> None:
    held = os.fstat(descriptor)
    _assert_regular_sidecar(lock_path, held)
    try:
        named = lock_path.lstat()
    except OSError as exc:
        raise _unsafe(f"Ownership lock path changed: {lock_path}") from exc
    _assert_regular_sidecar(lock_path, named)
    if not held.st_ino or not named.st_ino:
        raise RuntimeOwnershipError(
            "resource_ownership_unavailable",
            f"The filesystem cannot prove ownership lock identity: {lock_path}",
        )
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise _unsafe(f"Ownership lock path changed: {lock_path}")


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif os.name == "nt":
        import msvcrt

        # Windows permits a locked range beyond EOF. Do not write or truncate
        # the sidecar merely to obtain its one-byte lock.
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        raise RuntimeOwnershipError(
            "resource_ownership_unavailable",
            "This operating system has no supported exclusive ownership primitive.",
        )


def acquire_file_ownership(
    resource_path: str | Path, *, suffix: str = ".runtime.lock"
) -> RuntimeOwnership:
    """Own the canonical resource without waiting or using PID heuristics.

    Only the selected resource's parent is created. Native editors need not
    honor this advisory lock; callers still must recheck before replacing data.
    """
    if (
        not isinstance(suffix, str)
        or not suffix.startswith(".")
        or suffix in {".", ".."}
        or any(character in suffix for character in ("/", "\\", "\x00"))
    ):
        raise _unsafe("Ownership lock suffix must be a dot-prefixed filename suffix.")
    resource = _canonical_resource(resource_path)
    lock_path = resource.with_name(resource.name + suffix)
    descriptor: int | None = None
    try:
        resource.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = lock_path.lstat()
        except FileNotFoundError:
            pass
        else:
            _assert_regular_sidecar(lock_path, existing)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        os.set_inheritable(descriptor, False)
        _assert_sidecar_identity(lock_path, descriptor)
        try:
            _lock_descriptor(descriptor)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK}:
                raise RuntimeOwnershipError(
                    "resource_in_use",
                    f"Resource is already owned by another process: {resource}",
                ) from exc
            raise
        _assert_sidecar_identity(lock_path, descriptor)
        lease = RuntimeOwnership(resource, lock_path, descriptor)
        descriptor = None
        return lease
    except RuntimeOwnershipError:
        raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _unsafe(f"Ownership lock cannot be a symbolic link: {lock_path}") from exc
        raise RuntimeOwnershipError(
            "resource_ownership_unavailable",
            f"Cannot acquire exclusive ownership for resource: {resource}",
        ) from exc
    except ImportError as exc:
        raise RuntimeOwnershipError(
            "resource_ownership_unavailable",
            "The operating system's exclusive ownership primitive is unavailable.",
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def acquire_runtime_ownership(database_path: str | Path) -> RuntimeOwnership:
    """Own a canonical ledger before migrations or interrupted-work recovery."""
    try:
        database = _canonical_resource(database_path)
        try:
            metadata = database.stat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise _unsafe(
                    f"Ledger must be a regular file without hard-link aliases: {database}"
                )
        return acquire_file_ownership(database)
    except RuntimeOwnershipError as exc:
        code = {
            "resource_in_use": "ledger_runtime_in_use",
            "resource_ownership_unsafe": "ledger_runtime_ownership_unsafe",
            "resource_ownership_unavailable": "ledger_runtime_ownership_unavailable",
        }.get(exc.code, exc.code)
        message = exc.message
        if exc.code == "resource_in_use":
            message = (
                f"Another Flower runtime already owns this ledger: {database}. "
                "Use its explicit HTTP endpoint for shared access, or select a different profile."
            )
        raise RuntimeOwnershipError(code, message) from exc
    except OSError as exc:
        raise RuntimeOwnershipError(
            "ledger_runtime_ownership_unavailable",
            f"Cannot inspect the selected ledger safely: {database}",
        ) from exc
