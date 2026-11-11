"""Owner-local SQLite archives. Callers authorize access to the ledger."""

from __future__ import annotations

from contextlib import closing, contextmanager
import errno
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import sys
import tempfile
from time import monotonic
import zipfile

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.adapters.sqlite.ledger_store import SQLiteRequirementLedger
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.native_project_purge import _Problem, _scope, _validate_schema
from flow_of_work_mcp.native_purge_schema import PROJECT_IMPORT_TABLE_HASHES, SUPPORTED_LEDGER_TABLE_HASHES

CONTRACT = "flower.ledger-archive.v1"
MAX_DATABASE_BYTES = 2_000_000_000
MAX_MANIFEST_BYTES = 16 * 1024
MAX_ARCHIVE_BYTES = MAX_DATABASE_BYTES + 64 * 1024
_MANIFEST_NAME = "manifest.json"
_DATABASE_NAME = "ledger.sqlite3"
_MANIFEST_FIELDS = {
    "contract", "kind", "project_id", "schema_version", "database_size", "database_sha256",
}
_SESSION_TABLES = {
    "interaction_project_contexts",
    "interaction_project_context_events",
    "interaction_capability_lenses",
    "interaction_capability_lens_events",
    "interaction_projection_continuations",
}
_CHUNK_BYTES = 1024 * 1024
_LOCAL_HEADER = struct.Struct("<4s5H3I2H")
_CENTRAL_END = struct.Struct("<4s4H2IH")


class ArchiveError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _invalid() -> ArchiveError:
    return ArchiveError("archive_invalid", "The archive does not match the supported format or its payload is damaged.")


def _scope_error() -> ArchiveError:
    return ArchiveError("archive_scope_invalid", "The archive does not contain a closed single-project ledger.", 409)


def _schema_error() -> ArchiveError:
    return ArchiveError("archive_schema_unsupported", "The ledger schema or its integrity does not match supported schema55 or schema56.", 409)


def _size_error() -> ArchiveError:
    return ArchiveError("archive_size_exceeded", "The ledger or archive exceeds the supported size.", 413)


def _project_id(value: object) -> str:
    if not isinstance(value, str):
        raise _scope_error()
    try:
        project_id = validate_project_id(value)
    except ValueError as exc:
        raise _scope_error() from exc
    if value != project_id:
        raise _scope_error()
    return project_id


def _normalized_path(path: Path) -> Path:
    path = path.expanduser()
    return path.parent.resolve(strict=True) / path.name


def assert_private_archive_directory(path: Path) -> None:
    secure._private(path, directory=True)
    if sys.platform == "darwin":
        # A directory can inherit a macOS ACL even with mode 0700. Refuse
        # before staging any ledger bytes under an extended ACL.
        import ctypes
        api = ctypes.CDLL(None, use_errno=True)
        api.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
        api.acl_get_file.restype = ctypes.c_void_p
        api.acl_free.argtypes = [ctypes.c_void_p]
        api.acl_free.restype = ctypes.c_int
        ctypes.set_errno(0)
        acl = api.acl_get_file(os.fsencode(path), 0x100)  # ACL_TYPE_EXTENDED
        error = ctypes.get_errno()
        if acl:
            api.acl_free(acl)
        if acl or error != errno.ENOENT:
            raise ArchiveError("archive_workspace_unsafe", "Choose a destination that permits private archive staging.", 409)


@contextmanager
def _workspace(destination: Path):
    with tempfile.TemporaryDirectory(prefix=".flower-archive-", dir=destination.parent) as temporary:
        path = Path(temporary)
        if os.name == "nt":
            secure._windows_protect(path, directory=True)
        assert_private_archive_directory(path)
        yield path


def _publish(staged: Path, destination: Path) -> None:
    if os.name == "nt":
        secure._windows_protect(staged, directory=False)
    else:
        staged.chmod(0o600)
    with staged.open("r+b") as output:
        os.fsync(output.fileno())
    try:
        os.link(staged, destination)
    except FileExistsError as exc:
        raise ArchiveError("archive_destination_exists", "The destination already exists.", 409) from exc


def _read_only(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    options = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    connection = sqlite3.connect(path.as_uri() + options, uri=True, timeout=1)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _schema(connection: sqlite3.Connection) -> tuple:
    return tuple(connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
    ))


@lru_cache(maxsize=2)
def _canonical_schema(version: int) -> tuple:
    # This constructor can only touch a new, empty database. Its startup
    # reconciliation therefore has no records to recover.
    with tempfile.TemporaryDirectory(prefix="flower-archive-schema-") as temporary:
        path = Path(temporary).resolve() / _DATABASE_NAME
        SQLiteRequirementLedger(path)
        with closing(_read_only(path, immutable=True)) as connection:
            return tuple(row for row in _schema(connection)
                         if version != 55 or row[2] not in PROJECT_IMPORT_TABLE_HASHES)


def _validate_ledger(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    try:
        columns = _validate_schema(connection)
        if tuple(connection.execute("PRAGMA integrity_check(1)")) != (("ok",),):
            raise _schema_error()
    except (_Problem, sqlite3.DatabaseError) as exc:
        raise _schema_error() from exc
    return columns


def _schema_version(columns: dict[str, tuple[str, ...]]) -> int:
    return 56 if "project_import_origins" in columns else 55


@contextmanager
def _source_snapshot(database: Path):
    try:
        info = database.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("The source is not an unaliased regular file.")
        source = _read_only(database)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise ArchiveError("archive_source_unavailable", "A consistent ledger snapshot could not be acquired.", 409) from exc
    with closing(source):
        try:
            source.execute("BEGIN")
            # Establish the snapshot before either a logical projection or a
            # multipage Online Backup reads the ledger.
            source.execute("PRAGMA schema_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ArchiveError("archive_source_unavailable", "A consistent ledger snapshot could not be acquired.", 409) from exc
        yield source


def _snapshot(database: Path, destination: Path) -> None:
    try:
        with _source_snapshot(database) as source, closing(sqlite3.connect(destination)) as target:
            pages = source.execute("PRAGMA page_count").fetchone()[0]
            page_size = source.execute("PRAGMA page_size").fetchone()[0]
            if pages * page_size > MAX_DATABASE_BYTES:
                raise _size_error()
            deadline = monotonic() + 30

            def progress(status: int, remaining: int, total: int) -> None:
                if total * page_size > MAX_DATABASE_BYTES:
                    raise _size_error()
                if status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} and monotonic() >= deadline:
                    raise ArchiveError("archive_source_unavailable", "A consistent ledger snapshot could not be acquired.", 409)

            source.backup(target, pages=128, progress=progress, sleep=0.05)
            if target.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
                raise ArchiveError("archive_source_unavailable", "The ledger snapshot could not be closed as a standalone image.", 409)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise ArchiveError("archive_source_unavailable", "A consistent ledger snapshot could not be acquired.", 409) from exc


def _copy_projection(
    source: sqlite3.Connection, destination: Path, columns: dict[str, tuple[str, ...]], project_id: str | None,
) -> None:
    SQLiteRequirementLedger(destination)
    legacy = _schema_version(columns) == 55
    with closing(sqlite3.connect(destination)) as target, target:
        target.execute("PRAGMA foreign_keys = ON")
        target.execute("BEGIN")
        target.execute("PRAGMA defer_foreign_keys = ON")
        if legacy:
            # This target is a fresh scratch image. Match the source archive's
            # exact schema without asking the running ledger to downgrade.
            for name in reversed(tuple(PROJECT_IMPORT_TABLE_HASHES)):
                target.execute(f'DROP TABLE "{name}"')
            target.execute("DELETE FROM schema_migrations WHERE version = 56")
        for name, column_names in columns.items():
            if project_id is not None and (name in _SESSION_TABLES or name == "schema_migrations"):
                continue
            names = ",".join(f'"{column}"' for column in column_names)
            placeholders = ",".join("?" for _ in column_names)
            selection = f'SELECT {names} FROM "{name}"'
            if project_id is None:
                parameters = ()
                if name == "schema_migrations":
                    target.execute("DELETE FROM schema_migrations")
            else:
                where, parameters = _scope(name, project_id)
                selection += f" WHERE {where}"
            target.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({placeholders})',
                               source.execute(selection, parameters))
        if project_id is None:
            target.execute("DELETE FROM sqlite_sequence")
            target.executemany("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                               source.execute("SELECT name, seq FROM sqlite_sequence"))
        if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise _scope_error() if project_id is not None else _schema_error()
        if legacy:
            # Removing the new tables leaves free pages in a scratch image.
            # A project archive must remain compact and contain no freelist.
            target.commit()
            target.execute("VACUUM")


def _validate_phase_evidence(connection: sqlite3.Connection, project_id: str) -> None:
    # These snapshots store integer local evidence IDs in JSON instead of a FK.
    for table, column in (("phase_audit_requirements", "evidence_ids_json"),
                          ("phase_audit_deltas", "evidence_added_ids_json")):
        for requirement_id, raw in connection.execute(f'SELECT requirement_id, "{column}" FROM "{table}"'):
            try:
                ids = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise _scope_error() from exc
            if not isinstance(ids, list) or any(type(value) is not int for value in ids):
                raise _scope_error()
            for evidence_id in ids:
                if not connection.execute(
                    "SELECT 1 FROM verification_evidence WHERE evidence_id = ? AND project_id = ? AND requirement_id = ?",
                    (evidence_id, project_id, requirement_id),
                ).fetchone():
                    raise _scope_error()


def _validate_project(connection: sqlite3.Connection, columns: dict, project_id: str) -> None:
    if tuple(connection.execute("SELECT project_id FROM projects LIMIT 2")) != ((project_id,),):
        raise _scope_error()
    for name in columns:
        if name == "schema_migrations":
            continue
        if name in _SESSION_TABLES:
            where, parameters = "1", ()
        else:
            scope, parameters = _scope(name, project_id)
            where = f"COALESCE(({scope}), 0) = 0"
        if connection.execute(f'SELECT 1 FROM "{name}" WHERE {where} LIMIT 1', parameters).fetchone():
            raise _scope_error()
    _validate_phase_evidence(connection, project_id)
    expected_counters = []
    for name, in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND upper(sql) LIKE '%AUTOINCREMENT%'"
    ):
        # Table identities were already verified against the trusted schema.
        maximum = connection.execute(f'SELECT max(rowid) FROM "{name}"').fetchone()[0]
        if maximum is not None:
            expected_counters.append((name, max(maximum, 0)))
    if (tuple(connection.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name")) != tuple(sorted(expected_counters))
            or connection.execute("PRAGMA freelist_count").fetchone()[0]):
        raise _scope_error()


def _validate_import_references(connection: sqlite3.Connection, columns: dict[str, tuple[str, ...]]) -> None:
    imported_tables = set(columns) - _SESSION_TABLES - {"schema_migrations"} - PROJECT_IMPORT_TABLE_HASHES.keys()
    id_columns = {}
    for table, in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' AND upper(sql) LIKE '%AUTOINCREMENT%'"
    ):
        if table in imported_tables:
            id_columns[table] = next(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")') if row[5])

    def scoped_row(table: str, predicates: dict, project_id: str) -> bool:
        where, params = _scope(table, project_id)
        keys = " AND ".join(f'"{key}" = ?' for key in predicates)
        return connection.execute(
            f'SELECT 1 FROM "{table}" WHERE {keys} AND ({where}) LIMIT 1',
            (*predicates.values(), *params),
        ).fetchone() is not None

    for digest, source_id, imported_at in connection.execute(
        "SELECT origin_digest, source_project_id, imported_at FROM project_import_origins"
    ):
        if (_project_id(source_id) != source_id or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(imported_at, str) or not imported_at):
            raise _scope_error()

    for project_id, table, source_id, local_id in connection.execute(
        "SELECT project_id, identity_kind, source_id, local_id FROM project_import_identities"
    ):
        if (table not in id_columns or type(source_id) is not int or source_id <= 0
                or type(local_id) is not int or local_id <= 0
                or not scoped_row(table, {id_columns[table]: local_id}, project_id)
                or (source_id != local_id and scoped_row(table, {id_columns[table]: source_id}, project_id))):
            raise _scope_error()
    if connection.execute(
        "SELECT 1 FROM project_import_identities GROUP BY project_id, origin_digest, identity_kind, local_id "
        "HAVING count(*) > 1 LIMIT 1"
    ).fetchone():
        raise _scope_error()
    if connection.execute(
        "SELECT 1 FROM project_import_identities GROUP BY project_id, identity_kind, source_id "
        "HAVING count(DISTINCT local_id) > 1 LIMIT 1"
    ).fetchone():
        raise _scope_error()

    keys_by_table: dict[str, tuple[tuple[str, str | None], ...]] = {}
    for project_id, digest, source_project, table, raw_key, column, original in connection.execute(
        "SELECT project_id, origin_digest, source_project_id, table_name, row_key, column_name, original_value "
        "FROM project_import_originals JOIN project_import_origins USING (project_id, origin_digest)"
    ):
        if table not in imported_tables or column not in columns[table] or not isinstance(original, str):
            raise _scope_error()
        if table not in keys_by_table:
            parents = {row[3]: row[2] for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
                       if row[2] in id_columns and id_columns[row[2]] == row[4]}
            if table in id_columns:
                parents[id_columns[table]] = table
            keys_by_table[table] = tuple((row[1], parents.get(row[1])) for row in sorted(
                (row for row in connection.execute(f'PRAGMA table_info("{table}")') if row[5]),
                key=lambda row: row[5],
            ))
        keys = keys_by_table[table]
        try:
            values = json.loads(raw_key)
        except (TypeError, ValueError) as exc:
            raise _scope_error() from exc
        if not keys or not isinstance(values, list) or len(values) != len(keys):
            raise _scope_error()
        predicates = {}
        source_key = {key: value for (key, _), value in zip(keys, values, strict=True)}
        for key, kind in keys:
            value = source_key[key]
            if type(value) not in {str, int} or (type(value) is int and not 0 <= value < 2**63):
                raise _scope_error()
            if key == "project_id":
                if value != source_project:
                    raise _scope_error()
                value = project_id
            textual_audit = (table == "artifact_mappings" and key == "canonical_id"
                             and source_key.get("canonical_kind") == "phase_audit")
            if textual_audit:
                if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
                    raise _scope_error()
                kind, value = "phase_audits", int(value)
            if kind is not None:
                if type(value) is not int or not 0 < value < 2**63:
                    raise _scope_error()
                mapped = connection.execute(
                    "SELECT local_id FROM project_import_identities WHERE project_id = ? AND origin_digest = ? "
                    "AND identity_kind = ? AND source_id = ?", (project_id, digest, kind, value),
                ).fetchone()
                if mapped is None:
                    raise _scope_error()
                value = str(mapped[0]) if textual_audit else mapped[0]
            predicates[key] = value
        if not scoped_row(table, predicates, project_id):
            raise _scope_error()


def _digest(source, output=None) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    while chunk := source.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_DATABASE_BYTES:
            raise _size_error()
        hasher.update(chunk)
        if output is not None:
            output.write(chunk)
    return size, hasher.hexdigest()


def _validate_image(path: Path, project_id: str | None, version: int) -> None:
    with closing(_read_only(path, immutable=True)) as connection:
        if _schema(connection) != _canonical_schema(version):
            raise _schema_error()
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        if page_count * page_size != path.stat().st_size:
            raise _schema_error()
        columns = _validate_ledger(connection)
        if _schema_version(columns) != version:
            raise _schema_error()
        if project_id is not None:
            _validate_project(connection, columns, project_id)
        if version == 56:
            _validate_import_references(connection, columns)


def _prepare_image(database: Path, workspace: Path, project_id: str | None) -> tuple[Path, int]:
    image = workspace / _DATABASE_NAME
    if project_id is not None:
        # Never stage an entire ledger while preparing a project archive.
        with _source_snapshot(database) as source:
            columns = _validate_ledger(source)
            if not source.execute("SELECT 1 FROM projects WHERE project_id = ?", (project_id,)).fetchone():
                raise ArchiveError("archive_project_not_found", "The selected project does not exist.", 404)
            _copy_projection(source, image, columns, project_id)
            version = _schema_version(columns)
    else:
        snapshot = workspace / "snapshot.sqlite3"
        _snapshot(database, snapshot)
        with closing(_read_only(snapshot, immutable=True)) as source:
            columns = _validate_ledger(source)
            version = _schema_version(columns)
            if _schema(source) == _canonical_schema(version):
                if version == 56:
                    _validate_import_references(source, columns)
                return snapshot, version
            _copy_projection(source, image, columns, None)
    _validate_image(image, project_id, version)
    return image, version


def create_archive(database: Path, destination: Path, *, project_id: str | None = None) -> dict:
    """Publish a new archive from the caller-authorized database."""
    if project_id is not None:
        project_id = _project_id(project_id)
    try:
        database = _normalized_path(database)
        destination = _normalized_path(destination)
        if destination.exists() or destination.is_symlink():
            raise ArchiveError("archive_destination_exists", "The destination already exists.", 409)
        with _workspace(destination) as workspace:
            image, version = _prepare_image(database, workspace, project_id)
            with image.open("rb") as source:
                size, sha256 = _digest(source)
            manifest = {
                "contract": CONTRACT,
                "kind": "backup" if project_id is None else "project",
                "project_id": project_id,
                "schema_version": version,
                "database_size": size,
                "database_sha256": sha256,
            }
            staged = workspace / "archive.zip"
            with zipfile.ZipFile(staged, "x", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                archive.writestr(_MANIFEST_NAME, json.dumps(manifest, sort_keys=True, separators=(",", ":")))
                archive.write(image, _DATABASE_NAME)
            _publish(staged, destination)
            return manifest
    except sqlite3.IntegrityError as exc:
        raise (_scope_error() if project_id is not None else _schema_error()) from exc
    except (OSError, sqlite3.DatabaseError, zipfile.LargeZipFile, secure.ServiceSecurityError) as exc:
        raise ArchiveError("archive_io_failure", "The ledger archive could not be created.", 500) from exc


@contextmanager
def _open_archive(path: Path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise _invalid()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        current = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or not stat.S_ISREG(current.st_mode):
            raise _invalid()
        if current.st_size > MAX_ARCHIVE_BYTES:
            raise _size_error()
        yield source, current.st_size


def _central_offset(source, size: int) -> int:
    directory_size = 92 + len(_MANIFEST_NAME) + len(_DATABASE_NAME)
    if size <= directory_size + _CENTRAL_END.size:
        raise _invalid()
    offset = size - directory_size - _CENTRAL_END.size
    source.seek(-_CENTRAL_END.size, os.SEEK_END)
    if _CENTRAL_END.unpack(source.read(_CENTRAL_END.size)) != (
        b"PK\x05\x06", 0, 0, 2, 2, directory_size, offset, 0,
    ):
        raise _invalid()
    return offset


def _archive_members(archive: zipfile.ZipFile, source, directory_offset: int) -> tuple[zipfile.ZipInfo, zipfile.ZipInfo]:
    members = archive.infolist()
    if archive.comment or [entry.filename for entry in members] != [_MANIFEST_NAME, _DATABASE_NAME]:
        raise _invalid()
    offset = 0
    for entry in members:
        if (entry.header_offset != offset or entry.flag_bits or entry.extra or entry.comment
                or entry.compress_type != zipfile.ZIP_STORED or entry.compress_size != entry.file_size):
            raise _invalid()
        source.seek(offset)
        header = source.read(_LOCAL_HEADER.size)
        if len(header) != _LOCAL_HEADER.size:
            raise _invalid()
        signature, _, flags, method, _, _, crc, packed, raw, name_size, extra_size = _LOCAL_HEADER.unpack(header)
        name = entry.filename.encode("ascii")
        if (signature != b"PK\x03\x04" or flags or method or extra_size or crc != entry.CRC
                or packed != entry.file_size or raw != entry.file_size
                or name_size != len(name) or source.read(name_size) != name):
            raise _invalid()
        offset += _LOCAL_HEADER.size + name_size + entry.file_size
    if offset != directory_offset:
        raise _invalid()
    return members[0], members[1]


def _unique_json_object(items: list[tuple[str, object]]) -> dict:
    value = dict(items)
    if len(items) != len(value):
        raise _invalid()
    return value


def _manifest(content: bytes) -> dict:
    value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    if (not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS or value["contract"] != CONTRACT
            or type(value["schema_version"]) is not int or value["schema_version"] not in SUPPORTED_LEDGER_TABLE_HASHES
            or type(value["database_size"]) is not int or not 0 < value["database_size"] <= MAX_DATABASE_BYTES
            or not isinstance(value["database_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["database_sha256"])):
        raise _invalid()
    if value["kind"] == "project":
        _project_id(value["project_id"])
    elif value["kind"] != "backup" or value["project_id"] is not None:
        raise _invalid()
    return value


def read_archive(archive: Path, extracted_database: Path) -> dict:
    """Validate the archive and publish its SQLite payload into a new file."""
    try:
        archive = _normalized_path(archive)
        destination = _normalized_path(extracted_database)
        if destination.exists() or destination.is_symlink():
            raise ArchiveError("archive_destination_exists", "The destination already exists.", 409)
        with _workspace(destination) as workspace:
            staged = workspace / _DATABASE_NAME
            with _open_archive(archive) as (raw, length):
                directory_offset = _central_offset(raw, length)
                with zipfile.ZipFile(raw) as content:
                    metadata, payload = _archive_members(content, raw, directory_offset)
                    if metadata.file_size > MAX_MANIFEST_BYTES or payload.file_size > MAX_DATABASE_BYTES:
                        raise _size_error()
                    manifest = _manifest(content.read(metadata))
                    if payload.file_size != manifest["database_size"]:
                        raise _invalid()
                    with content.open(payload) as source, staged.open("xb") as output:
                        size, sha256 = _digest(source, output)
                    if size != manifest["database_size"] or sha256 != manifest["database_sha256"]:
                        raise _invalid()
            _validate_image(staged, manifest["project_id"], manifest["schema_version"])
            _publish(staged, destination)
            return manifest
    except ArchiveError:
        raise
    except (OSError, ValueError, RecursionError, sqlite3.DatabaseError, zipfile.BadZipFile,
            struct.error, secure.ServiceSecurityError) as exc:
        raise _invalid() from exc
