"""Explicit canonical architecture prerequisites for engineering test projects."""
from flow_of_work_mcp.application.architecture import ArchitectureService


def minimal_architecture():
    return {
        "components": [{
            "id": "Application", "name": "Application",
            "responsibility": "Implement the bounded behavior governed by this project.",
            "boundaries": ["Preserve the selected requirement and packet authority."],
            "invariants": [], "links": [],
        }],
        "interfaces": [], "decisions": [],
    }


def adopt_minimal_architecture(ledger, project_id="alpha"):
    """Use ordinary immutable proposal/adoption, never a test policy bypass."""
    service = ArchitectureService(ledger)
    proposal = service.call(
        project_id, "propose", actor="engineer", request_id="fixture-architecture-propose",
        payload={"expected_revision": 0, "definition": minimal_architecture()},
    )
    adopted = service.call(
        project_id, "adopt", actor="engineer", request_id="fixture-architecture-adopt",
        payload={"expected_revision": 0, "revision": proposal["revision"],
                 "rationale": "Record the investigated technical boundary for this test project."},
    )
    return ({"revision": adopted["revision"], "kind": "component", "entity_id": "Application"},)


def record_test_repository_review(ledger, ids, *, state="aligned"):
    """Record explicitly synthetic host inspection for a test's current scope."""
    from flow_of_work_mcp.application.engineering_cycle import DIMENSIONS, RepositoryReviewService
    from flow_of_work_mcp.application.external_work import ExternalWorkService
    from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
    from flow_of_work_mcp.core.domain.external_work import fingerprint
    from flow_of_work_mcp.core.domain.lifecycle_control import PhaseAuditScope
    snapshot = ExternalWorkService(ledger)._snapshot(*ids)
    context = RepositoryReviewService(ledger).context(*ids)
    absent = {"requirements": not snapshot["requirements"], "architecture": not snapshot["packet"].get("architecture_refs"),
              "grounding": not snapshot["goals"],
              "verification": not any(unit.get("verifies") for unit in (snapshot["plan"] or {}).get("units", [])),
              "outcomes": not (snapshot["plan"] or {}).get("units") and not snapshot["external"]["reports"]}
    review = {"contract_version": "flow.repository-review.v1", "change_id": ids[1], "packet_id": ids[2],
              "expected_basis_fingerprint": context["basis_fingerprint"], "source_identity": "synthetic:test-repository",
              "source_revision": "test-reviewed-source", "coverage": [
                  {"dimension": dimension, "state": "not_applicable" if absent[dimension] else state,
                   "rationale": "Synthetic scoped inspection retains original reports and deferred verification obligations.",
                   "evidence_refs": [] if absent[dimension] else ["synthetic:inspection-and-original-report-log"]}
                  for dimension in DIMENSIONS]}
    scope = PhaseAuditScope(context["scope_id"], tuple(context["requirement_ids"]))
    actor = "test-engineer"
    request_fp = fingerprint({"operation": "fow_audit_phase", "actor": actor, "scope_id": scope.scope_id,
                              "requirement_ids": list(scope.requirement_ids), "repository_review": review})
    service = LifecycleControlService(requirements=ledger, goals=ledger, grounding_audits=ledger, control=ledger)
    return service.audit_phase(ids[0], scope, actor=actor,
        request_id="synthetic-review-" + request_fp, repository_review=review, request_fingerprint=request_fp)
