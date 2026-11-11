from contextlib import closing
import json
import sqlite3

import pytest

from flow_of_work_mcp.adapters.sqlite import SQLiteRequirementLedger
from flow_of_work_mcp.core.domain.jobs import JobRecord
from flow_of_work_mcp.core.domain.lifecycle_control import PhaseAudit, PhaseAuditScope, PhaseRequirementSnapshot
from flow_of_work_mcp.core.domain.provider_binding import ProviderProjectBindingDraft
from flow_of_work_mcp.core.errors import RequirementConflictError
from flow_of_work_mcp.ledger_archive import ArchiveError, create_archive, read_archive
from flow_of_work_mcp.ledger_project_import import import_project_image


def _project(path, project_id):
    ledger = SQLiteRequirementLedger(path)
    ledger.create_project(project_id, "Test project", actor="archive-owner")
    requirement = ledger.add_requirement(
        project_id, title="History", statement="Keep project history.", category="functional", actor="archive-owner",
    )
    requirement_id = requirement["requirement_id"]
    evidence = ledger.record_verification(
        project_id, requirement_id, kind="tested_deterministically", outcome="passed", reference="check result",
        actor="archive-owner", request_id="check-1",
    )
    snapshot = PhaseRequirementSnapshot(requirement_id, 1, "active", {}, (evidence["evidence_id"],))
    ledger.record_phase_audit(
        PhaseAudit(project_id, PhaseAuditScope("scope", (requirement_id,)), None, (snapshot,), (), "policy"),
        actor="archive-owner", request_id="review-1",
    )


def _export(tmp_path, database, project_id, label):
    archive = tmp_path / f"{label}.flower.zip"
    extracted = tmp_path / f"{label}.sqlite3"
    create_archive(database, archive, project_id=project_id)
    return extracted, read_archive(archive, extracted)


def test_import_renames_duplicate_project_preserves_originals_and_composes_aliases(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    source_project = "a" * 64
    _project(source, source_project)
    _project(destination, source_project)
    with closing(sqlite3.connect(destination)) as connection, connection:
        connection.execute("UPDATE sqlite_sequence SET seq = 101 WHERE name = 'verification_evidence'")
    image, manifest = _export(tmp_path, source, source_project, "first")
    result = import_project_image(destination, image, manifest)
    renamed = "a" * 62 + "-2"
    assert result["project_id"] == renamed
    assert result["source_project_id"] == source_project
    assert result["counts"]["verification_evidence"] == 1
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT evidence_id, project_id FROM verification_evidence ORDER BY evidence_id").fetchall() == [
            (1, source_project), (102, renamed),
        ]
        assert connection.execute("SELECT evidence_ids_json FROM phase_audit_requirements ORDER BY phase_audit_id").fetchall() == [
            ("[1]",), ("[102]",),
        ]
        assert connection.execute("SELECT original_value FROM project_import_originals WHERE project_id = ? "
                                  "AND table_name = 'phase_audit_requirements'", (renamed,)).fetchone() == ("[1]",)
        current = connection.execute("SELECT payload_json FROM requirement_events WHERE project_id = ? "
                                     "AND event_type = 'verification_recorded'", (renamed,)).fetchone()[0]
        assert json.loads(current)["evidence_id"] == 102
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None

    second_destination = tmp_path / "second-destination.sqlite3"
    _project(second_destination, renamed)
    reexport, second_manifest = _export(tmp_path, destination, renamed, "second")
    second = import_project_image(second_destination, reexport, second_manifest)
    with closing(sqlite3.connect(second_destination)) as connection:
        assert connection.execute("SELECT origin_digest, source_id, local_id FROM project_import_identities "
                                  "WHERE project_id = ? AND identity_kind = 'verification_evidence' "
                                  "ORDER BY source_id", (second["project_id"],)).fetchall() == [
            (manifest["database_sha256"], 1, 103), (second_manifest["database_sha256"], 102, 103),
        ]
        assert connection.execute("SELECT original_value FROM project_import_originals WHERE project_id = ? "
                                  "AND origin_digest = ? AND table_name = 'phase_audit_requirements'",
                                  (second["project_id"], manifest["database_sha256"])).fetchone() == ("[1]",)


def test_failed_reference_import_rolls_back_project_rows_and_sequences(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    _project(source, "incoming")
    _project(destination, "existing")
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("UPDATE requirement_events SET payload_json = '{\"evidence_id\":9999}' "
                           "WHERE event_type = 'verification_recorded'")
    image, manifest = _export(tmp_path, source, "incoming", "invalid")
    with closing(sqlite3.connect(destination)) as connection:
        sequences = connection.execute("SELECT * FROM sqlite_sequence").fetchall()
        with pytest.raises(ArchiveError, match="does not resolve") as rejected:
            import_project_image(destination, image, manifest)
        assert rejected.value.code == "archive_import_unsupported"
        assert connection.execute("SELECT project_id FROM projects").fetchall() == [("existing",)]
        assert connection.execute("SELECT * FROM project_import_origins").fetchall() == []
        assert connection.execute("SELECT * FROM sqlite_sequence").fetchall() == sequences


def test_import_refuses_unfinished_job_without_recovering_or_copying_it(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    ledger = SQLiteRequirementLedger(source)
    ledger.create_project("incoming", "Incoming project", actor="archive-owner")
    ledger.create_job(JobRecord("incoming", "test-work", "archive-owner"))
    _project(destination, "existing")
    image, manifest = _export(tmp_path, source, "incoming", "pending")
    with pytest.raises(ArchiveError, match="unfinished execution") as rejected:
        import_project_image(destination, image, manifest)
    assert rejected.value.code == "archive_import_unsupported"
    with closing(sqlite3.connect(destination)) as target, closing(sqlite3.connect(source)) as original:
        assert target.execute("SELECT project_id FROM projects").fetchall() == [("existing",)]
        assert original.execute("SELECT status FROM jobs").fetchall() == [("queued",)]


def test_import_retains_provider_binding_history_without_granting_authority(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    ledger = SQLiteRequirementLedger(source)
    ledger.create_project("incoming", "Incoming project", actor="archive-owner")
    ledger.bind_provider_project(
        "incoming", ProviderProjectBindingDraft("implementation_graph", "provider", "scope", ("graph",)),
        actor="archive-owner",
    )
    _project(destination, "existing")
    image, manifest = _export(tmp_path, source, "incoming", "provider")
    import_project_image(destination, image, manifest)
    restored = SQLiteRequirementLedger(destination)
    assert restored.resolve_provider_binding("incoming", "implementation_graph") is None
    assert restored.list_provider_bindings("incoming")[0]["status"] == "imported_inactive"
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT original_value FROM project_import_originals WHERE project_id='incoming' "
                                  "AND table_name='provider_project_bindings' AND column_name='status'").fetchone() == ("active",)
        assert connection.execute("SELECT event_type FROM provider_project_binding_events WHERE project_id='incoming'").fetchall() == [
            ("provider_binding_created",),
        ]
    _export(tmp_path, destination, "incoming", "detached")


def test_renamed_import_replays_the_exact_project_scoped_semantic_preparation(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    _project(source, "incoming")
    _project(destination, "incoming")
    source_ledger = SQLiteRequirementLedger(source)
    kwargs = dict(role="intention_grounding", execution_mode="host", actor="archive-owner",
                  request_id="prepare-1")
    original = source_ledger.prepare_semantic_assignment(
        "incoming", preparation={"project_id": "incoming", "scope": "original"}, **kwargs,
    )
    image, manifest = _export(tmp_path, source, "incoming", "semantic")
    import_project_image(destination, image, manifest)
    local = SQLiteRequirementLedger(destination)
    replay = local.prepare_semantic_assignment(
        "incoming-2", preparation={"project_id": "incoming-2", "scope": "original"}, **kwargs,
    )
    assert replay["assignment_id"] == original["assignment_id"]
    assert replay["preparation_fingerprint"] == original["preparation_fingerprint"]
    with pytest.raises(RequirementConflictError):
        local.prepare_semantic_assignment(
            "incoming-2", preparation={"project_id": "incoming-2", "scope": "changed"}, **kwargs,
        )
