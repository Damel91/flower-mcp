from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import sqlite3
import stat
import zipfile

import pytest

from flow_of_work_mcp.adapters.sqlite import SQLiteRequirementLedger
from flow_of_work_mcp import ledger_archive
from flow_of_work_mcp.native_project_purge import _scope
from tests.test_native_project_purge import _seed_all_tables


def _ledger(tmp_path, *, rich=False):
    path = tmp_path / "source.sqlite3"
    if rich:
        SQLiteRequirementLedger(path)
        _seed_all_tables(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            for table, column in (("phase_audit_requirements", "evidence_ids_json"),
                                  ("phase_audit_deltas", "evidence_added_ids_json")):
                connection.execute(
                    f'UPDATE "{table}" SET "{column}" = "[" || phase_audit_id || "]"'
                )
    else:
        ledger = SQLiteRequirementLedger(path)
        ledger.create_project("project-a", "Project A", actor="archive-test")
        ledger.create_project("project-b", "Project B", actor="archive-test")
    return path


def _rows(connection, table, suffix="", params=()):
    return sorted(connection.execute(f'SELECT * FROM "{table}" {suffix}', params), key=repr)


def _repack(path, manifest, database):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("ledger.sqlite3", database)


def _repack_image(path, manifest, image):
    database = image.read_bytes()
    _repack(path, dict(manifest, database_size=len(database),
                       database_sha256=hashlib.sha256(database).hexdigest()), database)


def test_backup_captures_committed_wal_and_all_logical_rows(tmp_path):
    source = _ledger(tmp_path, rich=True)
    output = tmp_path / "full.zip"
    restored = tmp_path / "restored.sqlite3"
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("UPDATE projects SET name = 'Only in WAL' WHERE project_id = 'project-a'")
        writer.execute("UPDATE sqlite_sequence SET seq = 5000 WHERE name = 'verification_evidence'")
        writer.commit()
        assert source.with_name(source.name + "-wal").stat().st_size > 0

        manifest = ledger_archive.create_archive(source, output)
        assert ledger_archive.read_archive(output, restored) == manifest
        assert manifest["kind"] == "backup"
        assert manifest["project_id"] is None
        assert manifest["schema_version"] == 55
        assert manifest["database_sha256"] == hashlib.sha256(restored.read_bytes()).hexdigest()
        with closing(sqlite3.connect(restored)) as target:
            for name, in writer.execute("SELECT name FROM sqlite_schema WHERE type = 'table'"):
                assert _rows(writer, name) == _rows(target, name), name
            assert target.execute("PRAGMA journal_mode").fetchone() == ("delete",)
            assert target.execute("SELECT name FROM projects WHERE project_id = 'project-a'").fetchone() == ("Only in WAL",)
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert stat.S_IMODE(restored.stat().st_mode) == 0o600


def test_project_roundtrip_preserves_owned_rows_and_excludes_other_projects(tmp_path):
    source = _ledger(tmp_path, rich=True)
    output = tmp_path / "project.zip"
    restored = tmp_path / "restored.sqlite3"
    with closing(sqlite3.connect(source)) as original, original:
        assert original.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        original.execute("PRAGMA wal_autocheckpoint = 0")
        original.execute("UPDATE projects SET name = 'Project A from WAL' WHERE project_id = 'project-a'")
        original.execute("UPDATE projects SET name = 'only-in-other-project' WHERE project_id = 'project-b'")
        original.execute("UPDATE sqlite_sequence SET seq = 5000 WHERE name = 'verification_evidence'")
        original.commit()
        manifest = ledger_archive.create_archive(source, output, project_id="project-a")
    assert manifest["kind"] == "project"
    assert manifest["project_id"] == "project-a"
    assert ledger_archive.read_archive(output, restored) == manifest

    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(restored)) as target:
        for name, in original.execute("SELECT name FROM sqlite_schema WHERE type = 'table'"):
            if name in {"schema_migrations", "sqlite_sequence"}:
                continue
            if name.startswith("interaction_"):
                assert not _rows(target, name), name
            else:
                where, params = _scope(name, "project-a")
                expected = _rows(original, name, f"WHERE {where}", params)
                assert len(expected) == 1, name
                assert expected == _rows(target, name), name
        assert target.execute("SELECT seq FROM sqlite_sequence WHERE name = 'verification_evidence'").fetchone() == (1,)
        assert target.execute("PRAGMA foreign_key_check").fetchone() is None
        assert original.execute("SELECT count(*) FROM projects").fetchone() == (2,)
    assert b"only-in-other-project" not in restored.read_bytes()
    assert b"interaction_session_ref-project-a" not in restored.read_bytes()


@pytest.mark.parametrize("change", ["phase", "evidence"])
def test_project_export_refuses_references_outside_selected_project(tmp_path, change):
    source = _ledger(tmp_path, rich=True)
    output = tmp_path / "project.zip"
    with closing(sqlite3.connect(source)) as connection, connection:
        if change == "phase":
            connection.execute("UPDATE phase_audits SET previous_phase_audit_id = 2 WHERE project_id = 'project-a'")
        else:
            connection.execute("UPDATE phase_audit_requirements SET evidence_ids_json = '[2]' WHERE phase_audit_id = 1")
    with pytest.raises(ledger_archive.ArchiveError) as error:
        ledger_archive.create_archive(source, output, project_id="project-a")
    assert error.value.code == "archive_scope_invalid"
    assert not output.exists()
    assert not tuple(tmp_path.glob(".flower-archive-*"))


def test_create_refuses_missing_project_and_never_overwrites(tmp_path):
    source = _ledger(tmp_path)
    output = tmp_path / "existing.zip"
    output.write_text("keep")
    with pytest.raises(ledger_archive.ArchiveError) as error:
        ledger_archive.create_archive(source, output)
    assert error.value.code == "archive_destination_exists"
    assert output.read_text() == "keep"
    with pytest.raises(ledger_archive.ArchiveError) as error:
        ledger_archive.create_archive(source, tmp_path / "missing.zip", project_id="missing")
    assert error.value.code == "archive_project_not_found"


@pytest.mark.parametrize("tamper", ["digest", "kind", "extra_entry", "zip_tail", "noncanonical_sql", "project_scope"])
def test_read_refuses_tampered_or_inconsistent_archives(tmp_path, tamper):
    source = _ledger(tmp_path)
    archive = tmp_path / "full.zip"
    extracted = tmp_path / "extracted.sqlite3"
    manifest = ledger_archive.create_archive(source, archive)
    with zipfile.ZipFile(archive) as content:
        payload = content.read("ledger.sqlite3")
    if tamper == "digest":
        _repack(archive, dict(manifest, database_sha256="a" * 64), payload)
    elif tamper == "kind":
        _repack(archive, dict(manifest, kind="backup", project_id="project-a"), payload)
    elif tamper == "extra_entry":
        with zipfile.ZipFile(archive, "a") as content:
            content.writestr("unexpected", "stray payload")
    elif tamper == "zip_tail":
        with archive.open("ab") as output:
            output.write(b"undeclared bytes")
    elif tamper == "noncanonical_sql":
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("CREATE INDEX unexpected_expression ON projects (lower(name))")
        _repack_image(archive, manifest, source)
    else:
        _repack(archive, dict(manifest, kind="project", project_id="project-a"), payload)
    with pytest.raises(ledger_archive.ArchiveError):
        ledger_archive.read_archive(archive, extracted)
    assert not extracted.exists()
    assert not tuple(tmp_path.glob(".flower-archive-*"))


def test_read_does_not_replace_existing_database(tmp_path):
    source = _ledger(tmp_path)
    archive = tmp_path / "full.zip"
    ledger_archive.create_archive(source, archive)
    expected = source.read_bytes()
    with pytest.raises(ledger_archive.ArchiveError) as error:
        ledger_archive.read_archive(archive, source)
    assert error.value.code == "archive_destination_exists"
    assert source.read_bytes() == expected


def test_backup_canonicalizes_supported_source_index_without_changing_rows(tmp_path):
    source = _ledger(tmp_path)
    archive = tmp_path / "full.zip"
    target = tmp_path / "restored.sqlite3"
    with closing(sqlite3.connect(source)) as original, original:
        original.execute("CREATE INDEX extra_project_name_index ON projects (name)")
    manifest = ledger_archive.create_archive(source, archive)
    assert ledger_archive.read_archive(archive, target) == manifest
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(target)) as restored:
        assert _rows(original, "projects") == _rows(restored, "projects")
        assert original.execute("SELECT 1 FROM sqlite_schema WHERE name = 'extra_project_name_index'").fetchone()
        assert restored.execute("SELECT 1 FROM sqlite_schema WHERE name = 'extra_project_name_index'").fetchone() is None
