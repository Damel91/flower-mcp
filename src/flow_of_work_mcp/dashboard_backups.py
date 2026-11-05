"""Retained private dashboard backups for one selected ledger."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from threading import Lock
from uuid import uuid4

from flow_of_work_mcp.ledger_archive import ArchiveError, assert_private_archive_directory, create_archive
from flow_of_work_mcp.managed_service_security import _private, ensure_directory


_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}")
_SUFFIX = ".flower.zip"
_MAX_BACKUPS = 256


class DashboardBackups:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.directory = database.with_name(database.name + ".backups")
        self._lock = Lock()

    def _path(self, backup_id: str) -> Path:
        if not isinstance(backup_id, str) or not _ID.fullmatch(backup_id):
            raise ArchiveError("archive_backup_id_invalid", "Select a valid backup identifier.")
        return self.directory / (backup_id + _SUFFIX)

    def _record(self, backup_id: str, path: Path) -> dict:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise ArchiveError("archive_backup_not_found", "The selected backup no longer exists.", status=404) from exc
        _private(path, directory=False)
        created = datetime.strptime(backup_id.split("-", 1)[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return {"id": backup_id, "created_at": created.isoformat(), "size": info.st_size}

    def _entries(self) -> list[dict]:
        if not os.path.lexists(self.directory):
            return []
        assert_private_archive_directory(self.directory)
        result = []
        for path in self.directory.iterdir():
            if path.name.endswith(_SUFFIX):
                backup_id = path.name.removesuffix(_SUFFIX)
                if _ID.fullmatch(backup_id):
                    result.append(self._record(backup_id, path))
                    if len(result) > _MAX_BACKUPS:
                        raise ArchiveError("archive_backup_inventory_limit", "The backup folder exceeds its supported inventory.")
        return sorted(result, key=lambda item: item["id"], reverse=True)

    def list(self) -> dict:
        with self._lock:
            return {"backups": self._entries()}

    def create(self) -> dict:
        with self._lock:
            if len(self._entries()) >= _MAX_BACKUPS:
                raise ArchiveError("archive_backup_limit", "Remove a retained backup before creating another.", status=409)
            ensure_directory(self.directory)
            assert_private_archive_directory(self.directory)
            backup_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}"
            path = self._path(backup_id)
            create_archive(self.database, path)
            return self._record(backup_id, path)

    def open(self, backup_id: str):
        with self._lock:
            path = self._path(backup_id)
            if not os.path.lexists(self.directory):
                raise ArchiveError("archive_backup_not_found", "The selected backup no longer exists.", status=404)
            assert_private_archive_directory(self.directory)
            self._record(backup_id, path)
            expected = _private(path, directory=False)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
            try:
                held = os.fstat(descriptor)
                if not held.st_ino or (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
                    raise ArchiveError("archive_backup_changed", "The selected backup changed. Refresh the list.")
                stream = os.fdopen(descriptor, "rb")
            except BaseException:
                os.close(descriptor)
                raise
            return stream

    def delete(self, backup_id: str) -> dict:
        with self._lock:
            path = self._path(backup_id)
            if not os.path.lexists(self.directory):
                raise ArchiveError("archive_backup_not_found", "The selected backup no longer exists.", status=404)
            assert_private_archive_directory(self.directory)
            self._record(backup_id, path)
            path.unlink()
            return {"deleted": True}
