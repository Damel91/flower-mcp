"""Scoped host declarations remain durable without becoming filesystem attestations."""
from copy import deepcopy
import json
import sqlite3

import pytest

from flow_of_work_mcp import (ChangeControlService, GovernedChangeDraft,
                             ImplementationPacketDraft, RequirementDraft, RequirementService)
from flow_of_work_mcp.application.engineering_cycle import (
    DIMENSIONS, RepositoryReviewService, engineering_cycle_version,
    normalize_repository_review, repository_review_projection,
)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.jobs import JobBlockedError
from flow_of_work_mcp.core.domain.jobs import JobRecord
from flow_of_work_mcp.core.domain.lifecycle_control import PhaseAuditScope
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, InputValidationError, RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_audit_phase


@pytest.fixture
def owned(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "review.sqlite3", import_root=tmp_path)
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Owned review", actor="human")
    requirement = requirements.register("alpha", RequirementDraft(title="Observed result",
        statement="The program shall return the agreed result.", category="functional", rationale="Confirmed intent."), actor="human")
    changes = ChangeControlService(runtime.ledger)
    change = changes.create_change("alpha", GovernedChangeDraft(title="Bounded work",
        rationale="An explicit historical context.", requirement_ids=(requirement["requirement_id"],)), actor="engineer")
    packet = changes.add_packet("alpha", change["change_id"], ImplementationPacketDraft(
        title="Observed implementation", objective="Inspect the existing implementation.",
        rationale="Missing ledger data is not missing code.", completion_criteria=("The result is documented.",),
        requirement_ids=(requirement["requirement_id"],)), actor="engineer")["packets"][0]
    yield runtime, ("alpha", change["change_id"], packet["packet_id"]), requirement["requirement_id"]
    runtime.close()


def declaration(owned, *, state="aligned"):
    runtime, ids, _requirement = owned
    context = RepositoryReviewService(runtime.ledger).context(*ids)
    value = {"contract_version": "flow.repository-review.v1", "change_id": ids[1], "packet_id": ids[2],
        "expected_basis_fingerprint": context["basis_fingerprint"], "source_identity": "host:owned-repository",
        "source_revision": "commit:observed-1", "coverage": [{"dimension": dimension,
            "state": state if dimension == "requirements" else "not_applicable",
            "rationale": "Investigated the exact selected scope.",
            "evidence_refs": ["host:inspection-log"] if dimension == "requirements" else []}
            for dimension in DIMENSIONS]}
    return PhaseAuditScope(context["scope_id"], tuple(context["requirement_ids"])), value


def submit(owned, *, value=None, scope=None, request_id="review-1", actor="engineer", jobs=None):
    runtime, ids, _requirement = owned
    default_scope, default_value = declaration(owned)
    return RepositoryReviewService(runtime.ledger).submit(ids[0], scope or default_scope,
        default_value if value is None else value, actor=actor, request_id=request_id,
        jobs=jobs or runtime.jobs, lifecycle=runtime.lifecycle)


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("patch", [
    {"unknown": True}, {"contract_version": "unsupported"}, {"expected_basis_fingerprint": True},
    {"source_revision": ""}, {"source_identity": "x" * 513}, {"coverage": []},
])
def test_strict_review_preflight_records_no_job_or_event(owned, patch):
    runtime, _ids, _requirement = owned
    _scope, value = declaration(owned)
    before = dump(runtime)
    with pytest.raises(InputValidationError):
        submit(owned, value={**value, **patch})
    assert dump(runtime) == before


def test_dimension_duplicates_unknown_fields_evidence_and_false_na_reject(owned):
    runtime, _ids, _requirement = owned
    _scope, original = declaration(owned)
    variants = []
    duplicate = deepcopy(original); duplicate["coverage"][1] = duplicate["coverage"][0]; variants.append(duplicate)
    extra = deepcopy(original); extra["coverage"][0]["extra"] = "invented"; variants.append(extra)
    no_evidence = deepcopy(original); no_evidence["coverage"][0]["evidence_refs"] = []; variants.append(no_evidence)
    false_na = deepcopy(original); false_na["coverage"][0]["state"] = "not_applicable"; variants.append(false_na)
    before = dump(runtime)
    for value in variants:
        with pytest.raises(InputValidationError):
            submit(owned, value=value)
        assert dump(runtime) == before


def test_unknown_packet_scope_and_missing_identity_reject_before_job(owned):
    runtime, _ids, _requirement = owned
    scope, value = declaration(owned)
    before = dump(runtime)
    with pytest.raises(InputValidationError):
        submit(owned, value={**value, "packet_id": "PACKET-999999"})
    with pytest.raises(InputValidationError):
        submit(owned, scope=PhaseAuditScope("caller-invented", scope.requirement_ids))
    for field in ("actor", "request_id"):
        with pytest.raises(InputValidationError):
            submit(owned, **{field: ""})
    assert dump(runtime) == before


def test_plain_audit_without_request_identity_creates_one_completed_job(owned):
    runtime, ids, _requirement = owned
    before = runtime.ledger.jobs(ids[0])
    response = handle_audit_phase(runtime, project_id=ids[0], scope_id="plain-without-request", actor="engineer")
    assert response["status"] == "success"
    job_id = response["result"]["job"]["job_id"]
    assert runtime.jobs.wait(ids[0], job_id, timeout=10).status.value == "completed"
    created = [job for job in runtime.ledger.jobs(ids[0]) if job.job_id not in {row.job_id for row in before}]
    assert len(created) == 1 and created[0].job_id == job_id
    assert created[0].request_id == "" and created[0].status.value == "completed"
    assert runtime.ledger.all_phase_audits(ids[0])[-1]["scope_id"] == "plain-without-request"


def test_legacy_and_review_audits_restart_without_new_tables_or_clock_staleness(owned):
    runtime, ids, _requirement = owned
    runtime.lifecycle.audit_phase(ids[0], PhaseAuditScope("historical"), actor="engineer", request_id="plain")
    legacy = runtime.ledger.all_phase_audits(ids[0])[0]
    assert legacy["repository_review"] is None
    scope, value = declaration(owned)
    job = submit(owned, scope=scope, value=value)
    result = runtime.jobs.wait(ids[0], job.job_id, timeout=10)
    assert result.status.value == "completed"
    before_basis = RepositoryReviewService(runtime.ledger).context(*ids)
    assert before_basis["state"] == "current" and before_basis["complete"]
    assert not before_basis["required"] and before_basis["engineering_cycle_version"] is None
    assert before_basis["source"]["provenance"] == "host_declared"
    assert not before_basis["semantic_truth_verified"] and not before_basis["human_acceptance"]
    RequirementService(runtime.ledger).register(ids[0], RequirementDraft(title="Unrelated",
        statement="Another feature exists.", category="functional", rationale="Different scope."), actor="human")
    assert RepositoryReviewService(runtime.ledger).context(*ids) == before_basis
    from flow_of_work_mcp import SQLiteRequirementLedger
    reopened = SQLiteRequirementLedger(runtime.ledger.database_path)
    assert RepositoryReviewService(reopened).context(*ids) == before_basis
    audit = reopened.all_phase_audits(ids[0])[-1]
    assert audit["repository_review"] == normalize_repository_review(value)
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        assert max(row[0] for row in connection.execute("SELECT version FROM schema_migrations")) == 55
        payload = json.loads(connection.execute("SELECT payload_json FROM requirement_events WHERE event_type='phase_audit_recorded' ORDER BY event_id DESC LIMIT 1").fetchone()[0])
        assert payload["repository_review"] == normalize_repository_review(value)


def test_currentness_changes_only_for_scoped_semantics_and_exact_replay_is_historical(owned):
    runtime, ids, requirement = owned
    scope, value = declaration(owned)
    first = submit(owned, scope=scope, value=value)
    runtime.jobs.wait(ids[0], first.job_id, timeout=10)
    RequirementService(runtime.ledger).revise(ids[0], requirement, RequirementDraft(title="Observed result",
        statement="The program shall return a different agreed result.", category="functional"),
        actor="human", rationale="Actual intent revision.")
    context = RepositoryReviewService(runtime.ledger).context(*ids)
    assert context["state"] == "stale" and not context["complete"]
    before = dump(runtime)
    assert submit(owned, scope=scope, value=value).job_id == first.job_id
    assert dump(runtime) == before
    with pytest.raises(RequirementConflictError):
        submit(owned, scope=scope, value={**value, "source_revision": "another-commit"})
    with pytest.raises(RequirementConflictError):
        submit(owned, scope=scope, value=value, actor="other-engineer")
    with pytest.raises(ChangeControlBlockedError, match="basis_stale"):
        submit(owned, scope=scope, value=value, request_id="new-stale")
    assert dump(runtime) == before


def test_historical_classification_records_review_but_never_current_closure(owned):
    runtime, ids, _requirement = owned
    _scope, value = declaration(owned, state="historical_on_pin")
    job = submit(owned, value=value)
    runtime.jobs.wait(ids[0], job.job_id, timeout=10)
    context = RepositoryReviewService(runtime.ledger).context(*ids)
    assert context["retrospective_recorded"] and not context["complete"] and context["state"] == "open"


class HeldJobs:
    """Control queue timing while persisting the ordinary job records."""
    def __init__(self, ledger):
        self.ledger, self.operation = ledger, None

    def submit(self, *, project_id, kind, actor, request_id, operation):
        self.operation = operation
        return self.ledger.create_job(JobRecord(project_id=project_id, kind=kind, created_by=actor, request_id=request_id))


def test_worker_rechecks_queued_basis_without_partial_audit(owned):
    runtime, ids, requirement = owned
    held = HeldJobs(runtime.ledger)
    job = submit(owned, jobs=held)
    RequirementService(runtime.ledger).revise(ids[0], requirement, RequirementDraft(title="Changed",
        statement="A changed semantic contract.", category="functional"), actor="human", rationale="Queue drift.")
    before = dump(runtime)
    with pytest.raises(JobBlockedError, match="repository_review_basis_stale"):
        held.operation()
    assert dump(runtime) == before
    assert not runtime.ledger.all_phase_audits(ids[0])
    recovery = RepositoryReviewService(runtime.ledger).job_recovery(ids[0], runtime.ledger.get_job(ids[0], job.job_id))
    assert recovery["next_tool_call"]["arguments"]["operation"] == "validation"


def test_atomic_worker_rollback_and_postcommit_job_failure_recovery(owned, monkeypatch):
    runtime, ids, _requirement = owned
    held = HeldJobs(runtime.ledger)
    job = submit(owned, jobs=held)
    original = runtime.ledger.record_phase_audit
    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after insert")
    monkeypatch.setattr(runtime.ledger, "record_phase_audit", failing)
    before = dump(runtime)
    with pytest.raises(RuntimeError, match="injected"):
        held.operation()
    assert dump(runtime) == before
    monkeypatch.setattr(runtime.ledger, "record_phase_audit", original)
    held.operation()
    # Committed audit remains authoritative when subsequent job completion fails.
    runtime.ledger.fail_job(ids[0], job.job_id, terminal_reason="job_execution_failed")
    failed = runtime.ledger.get_job(ids[0], job.job_id)
    recovery = RepositoryReviewService(runtime.ledger).job_recovery(ids[0], failed)
    assert recovery["repository_review"]["complete"]
    assert recovery["diagnostics"][0]["code"] == "job_execution_failed"
    assert submit(owned).job_id == job.job_id
    assert len(runtime.ledger.all_phase_audits(ids[0])) == 1


def test_failed_job_keeps_its_original_audit_after_a_later_review(owned, monkeypatch):
    runtime, ids, _requirement = owned
    held = HeldJobs(runtime.ledger)
    first_job = submit(owned, jobs=held)
    held.operation()
    runtime.ledger.fail_job(ids[0], first_job.job_id, terminal_reason="job_execution_failed")
    _scope, later = declaration(owned)
    later["source_revision"] = "commit:observed-2"
    second_job = submit(owned, value=later, request_id="review-2")
    assert runtime.jobs.wait(ids[0], second_job.job_id, timeout=10).status.value == "completed"
    service = RepositoryReviewService(runtime.ledger)
    failed = runtime.ledger.get_job(ids[0], first_job.job_id)
    recovery = service.job_recovery(ids[0], failed)
    assert recovery["original_audit"]["phase_audit_id"] == 1
    assert recovery["original_audit"]["repository_review"]["source_revision"] == "commit:observed-1"
    assert recovery["repository_review"]["latest_audit_id"] == 2
    assert recovery["repository_review"]["source"]["revision"] == "commit:observed-2"
    def authority_unavailable(*args):
        raise ChangeControlBlockedError("architecture_authority_stale")
    monkeypatch.setattr(service, "context", authority_unavailable)
    assert service.job_recovery(ids[0], failed)["original_audit"] == recovery["original_audit"]


def test_plain_job_request_cannot_be_reused_as_repository_proof(owned):
    runtime, ids, _requirement = owned
    runtime.ledger.create_job(JobRecord(project_id=ids[0], kind="audit_phase", created_by="engineer", request_id="review-1"))
    before = dump(runtime)
    with pytest.raises(RequirementConflictError):
        submit(owned)
    assert dump(runtime) == before


def test_reservation_failure_never_dispatches_an_uncommitted_job(owned, monkeypatch):
    runtime, _ids, _requirement = owned
    held = HeldJobs(runtime.ledger)
    def fail(*args, **kwargs):
        raise RuntimeError("reservation insert failed")
    monkeypatch.setattr(runtime.ledger, "reserve_phase_audit_request", fail)
    before = dump(runtime)
    with pytest.raises(RuntimeError, match="reservation"):
        submit(owned, jobs=held)
    assert held.operation is None
    assert dump(runtime) == before


def test_plain_audit_cannot_downgrade_a_reserved_review_request(owned):
    runtime, ids, _requirement = owned
    held = HeldJobs(runtime.ledger)
    submit(owned, jobs=held)
    scope, _value = declaration(owned)
    before = dump(runtime)
    result = handle_audit_phase(runtime, project_id=ids[0], scope_id=scope.scope_id,
        requirement_ids=list(scope.requirement_ids), actor="engineer", request_id="review-1")
    assert result["status"] == "rejected" and result["reason"] == "state_conflict"
    assert dump(runtime) == before


def test_only_original_plan_acceptance_enrolls_cycle_and_applicable_states_gate(owned):
    runtime, ids, _requirement = owned
    snapshot = ExternalWorkService(runtime.ledger)._snapshot(*ids)
    assert engineering_cycle_version(None) is None
    snapshot["plan"] = {"events": [{"event_type": "work_plan_accepted", "payload": {"engineering_cycle_version": 1}}], "units": []}
    snapshot["external"]["consumption_mode"] = "external_agent"
    pending = repository_review_projection(snapshot, [])
    assert pending["required"] and pending["state"] == "pending"
    assert pending["next_gate"]["operation"] == "call"
    assert set(pending["next_gate"]["repository_review_template"]) == {
        "contract_version", "change_id", "packet_id", "expected_basis_fingerprint"}
    _scope, value = declaration(owned)
    value["expected_basis_fingerprint"] = pending["basis_fingerprint"]
    audit = {"phase_audit_id": 1, "scope_id": pending["scope_id"], "repository_review": value}
    assert repository_review_projection(snapshot, [audit])["complete"]
    for state in ("authority_missing", "compatibility_review", "current_obligation", "unknown", "historical_on_pin"):
        changed = deepcopy(audit); changed["repository_review"]["coverage"][0]["state"] = state
        assert not repository_review_projection(snapshot, [changed])["complete"]


def test_public_rejection_is_scoped_and_has_read_only_recovery(owned):
    runtime, ids, _requirement = owned
    scope, value = declaration(owned)
    value["coverage"] = []
    response = handle_audit_phase(runtime, project_id=ids[0], scope_id=scope.scope_id,
        requirement_ids=list(scope.requirement_ids), repository_review=value, actor="engineer", request_id="bad")
    assert response["status"] == "rejected"
    assert response["result"]["diagnostics"][0]["field"] == "repository_review"
    assert response["result"]["next_tool_call"]["arguments"]["operation"] == "validation"
    assert not runtime.ledger.jobs(ids[0])


def test_relevant_predecessor_report_change_invalidates_review_basis(owned):
    runtime, ids, _requirement = owned
    snapshot = ExternalWorkService(runtime.ledger)._snapshot(*ids)
    predecessor = {"packet_id": "PACKET-000002", "external": {"reports": [
        {"report_key": "producer-1", "payload": {"source_revision": "old-source"}}], "selections": []}}
    snapshot["predecessor_packets"] = [predecessor]
    first = repository_review_projection(snapshot, [])
    predecessor["external"]["reports"][0]["payload"]["source_revision"] = "new-source"
    changed = repository_review_projection(snapshot, [])
    assert changed["basis_fingerprint"] != first["basis_fingerprint"]
    assert changed["scope_id"] == first["scope_id"]


@pytest.mark.parametrize("status,expected", [(None, "not_required"), ("proposed", "not_required"),
    ("rejected", "not_required"), ("accepted", "historical_authority"), ("superseded", "historical_authority")])
def test_unissued_plans_are_not_labelled_as_historical_authority(owned, status, expected):
    runtime, ids, _requirement = owned
    snapshot = ExternalWorkService(runtime.ledger)._snapshot(*ids)
    snapshot["plan"] = None if status is None else {"status": status, "events": [], "units": []}
    projection = repository_review_projection(snapshot, [])
    assert projection["engineering_cycle_version"] is None
    assert projection["state"] == expected and not projection["required"]
