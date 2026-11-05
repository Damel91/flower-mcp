"""Explicit native backup and recovery without taking over an existing profile."""
from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from flow_of_work_mcp.config import load_config_with_revision
from flow_of_work_mcp.ledger_archive import (
    ArchiveError, assert_private_archive_directory, create_archive, read_archive,
)
from flow_of_work_mcp.managed_service_security import (
    _windows_protect, check_data_file, ensure_directory,
)
from flow_of_work_mcp.native_project_purge import _Problem, pending_project_purges
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


def _absolute(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute() or path.resolve() != path:
        raise ArchiveError("archive_path_unsafe", "Use an absolute path without symbolic links.")
    return path


def backup_profile(config_path: Path, destination: Path, *, project_id: str | None = None) -> dict:
    config_path, destination = _absolute(config_path), _absolute(destination)
    check_data_file(config_path)
    assert_private_archive_directory(destination.parent)
    config, revision = load_config_with_revision(config_path)
    database = config.runtime.database_path
    check_data_file(database)
    with acquire_runtime_ownership(database) as lease:
        current, current_revision = load_config_with_revision(config_path)
        if current_revision != revision or current.runtime.database_path != database:
            raise ArchiveError("archive_profile_changed", "The selected profile changed. Inspect it and try again.")
        try:
            pending = pending_project_purges(config_path, lease)
        except (_Problem, ValueError, OSError) as exc:
            raise ArchiveError("archive_maintenance_pending", "The deletion journal cannot be verified. Inspect it before backing up.") from exc
        if pending:
            raise ArchiveError("archive_maintenance_pending", "Reconcile the unfinished deletion before making a backup.")
        return {**create_archive(database, destination, project_id=project_id), "archive": str(destination)}


def _sync_directory(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish_profile(database: Path, directory: Path) -> Path:
    """Reserve the new directory and publish the launchable config last."""
    ensure_directory(directory.parent, private=False)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ArchiveError("archive_destination_exists", "Choose a new destination directory.") from exc
    if os.name == "nt":
        _windows_protect(directory, directory=True)
    assert_private_archive_directory(directory)
    config_path = directory / "flower.yaml"
    try:
        # The backup scratch is on the same filesystem, so this publication
        # cannot replace a file that appeared after the directory reservation.
        os.link(database, directory / "ledger.sqlite3")
        database.unlink()
        (directory / "imports").mkdir(mode=0o700)
        template = files("flow_of_work_mcp").joinpath("resources/standalone.yaml").read_bytes()
        draft = database.parent / "flower.yaml"
        fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            if os.name == "nt":
                _windows_protect(draft, directory=False)
            stream.write(template)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(directory)
        os.link(draft, config_path)
        draft.unlink()
        _sync_directory(directory)
        _sync_directory(directory.parent)
    except OSError as exc:
        raise ArchiveError("archive_restore_incomplete", "Restore did not finish. Inspect the new directory and use a different destination for a retry.") from exc
    return config_path


def inspect_or_restore(archive: Path, *, restore_dir: Path | None = None) -> dict:
    archive = _absolute(archive)
    if restore_dir is not None:
        restore_dir = _absolute(restore_dir)
        if os.path.lexists(restore_dir):
            raise ArchiveError("archive_destination_exists", "Choose a new destination directory.")
        if not restore_dir.parent.is_dir():
            raise ArchiveError("archive_parent_missing", "Select an existing parent directory for the new profile.")
        ensure_directory(restore_dir.parent, private=False)
    scratch_parent = None if restore_dir is None else restore_dir.parent
    with TemporaryDirectory(prefix=".flower-restore-", dir=scratch_parent) as temporary:
        scratch = Path(temporary).resolve()
        if os.name == "nt":
            _windows_protect(scratch, directory=True)
        assert_private_archive_directory(scratch)
        database = scratch / "ledger.sqlite3"
        manifest = read_archive(archive, database)
        if restore_dir is None:
            return {**manifest, "verified": True}
        config_path = _publish_profile(database, restore_dir)
        return {
            **manifest, "verified": True, "profile_config": str(config_path),
            "database_path": str(restore_dir / "ledger.sqlite3"),
            "server_started": False, "client_registration_changed": False,
        }
