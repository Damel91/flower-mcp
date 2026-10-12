"""Rejected SRS jobs retain every finding and never materialize a baseline."""
import sqlite3

import pytest

from flow_of_work_mcp.core.domain import ValidationAuditRecord, ValidationDisposition
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_import_srs, handle_revise_srs_baseline


VALID_SRS = """# Example SRS

## Scope
This document describes enough bounded behavior for the structural profile.

## Functional Requirements
- FR-EXAMPLE-001 The server shall validate the document.

## Non-Functional Requirements
- NFR-EXAMPLE-001 The server shall persist audit state.

## Use Cases
### UC-EXAMPLE-001 - Validate
Actor: operator
Objective: validate an SRS source
Observable Outcome: a structured validation audit is returned

## Sequences
### SQ-EXAMPLE-001 - Validation
Use Case: UC-EXAMPLE-001
Participants: operator; server
Normal Steps: submit the SRS; validate the SRS
Expected Effects: a structural audit is persisted

## Acceptance Criteria
- AC-EXAMPLE-001 Valid sources return an accepted audit.
"""

CASES = {
    "missing_sections": ("# Scope\nNot a supported requirements baseline.\n", 5),
    "mixed_codes": ("Not a supported requirements baseline.\n", 7),
    "single_error": (VALID_SRS.split("## Acceptance Criteria")[0], 1),
    "duplicate_identifiers": (VALID_SRS.replace(
        "- FR-EXAMPLE-001 The server shall validate the document.",
        "- FR-EXAMPLE-001 First declaration.\n"
        "- FR-EXAMPLE-001 Second declaration.\n"
        "- FR-EXAMPLE-001 Third declaration.",
    ), 2),
}


def _canonical_rows(database):
    # Audit/job events may append; imported authority must remain byte-for-byte.
    tables = (
        "requirements", "requirement_revisions", "goal_nodes", "goal_edges",
        "goal_requirement_candidates", "baseline_imports", "baseline_entity_mappings",
    )
    with sqlite3.connect(database) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in tables}


def _seed(runtime, source):
    source.write_text(VALID_SRS, encoding="utf-8")
    submission = handle_import_srs(
        runtime, project_id="alpha", source_path=str(source),
        standard_profile="fow-srs-markdown-v1", actor="test", request_id="seed",
    )
    job = runtime.jobs.wait("alpha", submission["result"]["job"]["job_id"], timeout=5)
    assert job.status.value == "completed"
    assert job.result["imported"] is True
    return job.result["baseline"]["baseline"]["baseline_id"]


def _submit(runtime, operation, source, previous="", request_id="reject"):
    kwargs = dict(project_id="alpha", source_path=str(source),
                  standard_profile="fow-srs-markdown-v1", actor="test", request_id=request_id)
    if operation == "revise":
        return handle_revise_srs_baseline(runtime, previous_baseline_id=previous, **kwargs)
    return handle_import_srs(runtime, **kwargs)


@pytest.mark.parametrize("operation", ["import", "revise"])
@pytest.mark.parametrize("case", list(CASES))
def test_rejected_source_completes_with_full_diagnostics_without_authority_changes(tmp_path, operation, case):
    database = tmp_path / "ledger.sqlite3"
    source = tmp_path / "source.md"
    runtime = build_runtime(database_path=database, import_root=tmp_path)
    try:
        runtime.requirements.create_project("alpha", "Alpha", actor="test")
        previous = _seed(runtime, source) if operation == "revise" else ""
        before = _canonical_rows(database)
        text, expected_findings = CASES[case]
        source.write_text(text, encoding="utf-8")
        # Use the real structural audit as the rich-data oracle, including anchors.
        structural = runtime.baseline_import.structural_validation.validate(
            str(source), standard_profile="fow-srs-markdown-v1",
        ).to_dict()
        assert structural["disposition"] == "rejected"
        assert len(structural["findings"]) == expected_findings
        submitted = _submit(runtime, operation, source, previous)
        job_id = submitted["result"]["job"]["job_id"]
        job = runtime.jobs.wait("alpha", job_id, timeout=5)
        assert job.status.value == "completed", (job.status, job.terminal_reason)
        result = job.result
        assert result["imported" if operation == "import" else "revised"] is False
        assert result["disposition"] == "rejected"
        assert result["reason"] == "validation_not_accepted"
        assert result["audit"] == structural
        assert _canonical_rows(database) == before
        audit = runtime.ledger.validation_audits("alpha")[-1]
        assert audit["validation_audit_id"] == result["validation_audit_id"]
        assert audit["finding_codes"] == sorted({f["code"] for f in structural["findings"]})
        assert audit["disposition"] == "rejected"
        replay = _submit(runtime, operation, source, previous)
        assert replay["result"]["job"]["job_id"] == job_id
        assert runtime.jobs.get("alpha", job_id).result == result
        assert _canonical_rows(database) == before
    finally:
        runtime.close()


@pytest.mark.parametrize("operation", ["import", "revise"])
def test_source_path_refusal_still_blocks_without_baseline_changes(tmp_path, operation):
    allowed = tmp_path / "imports"
    allowed.mkdir()
    database = tmp_path / "ledger.sqlite3"
    source = allowed / "valid.md"
    runtime = build_runtime(database_path=database, import_root=allowed)
    try:
        runtime.requirements.create_project("alpha", "Alpha", actor="test")
        previous = _seed(runtime, source) if operation == "revise" else ""
        outside = tmp_path / "outside.md"
        outside.write_text(VALID_SRS, encoding="utf-8")
        before = _canonical_rows(database)
        submission = _submit(runtime, operation, outside, previous)
        job = runtime.jobs.wait("alpha", submission["result"]["job"]["job_id"], timeout=5)
        assert job.status.value == "blocked"
        assert job.terminal_reason == "baseline_source_rejected"
        assert job.result == {}
        assert _canonical_rows(database) == before
    finally:
        runtime.close()


def test_validation_record_still_rejects_duplicate_summary_codes():
    with pytest.raises(ValueError, match="finding codes must be unique"):
        ValidationAuditRecord(source_ref="source.md", disposition=ValidationDisposition.REJECTED,
                              finding_codes=("SRS-SECTION-MISSING", "SRS-SECTION-MISSING"))
