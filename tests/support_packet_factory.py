"""Test-only adapter for fixtures that predate the canonical packet factory."""
from __future__ import annotations

import hashlib

from flow_of_work_mcp.application import (
    AssuranceService,
    ChangeControlService,
    NavigationAuditService,
    PacketConstructionService,
    PacketLifecycleService,
    PacketPressureService,
    PacketReconciliationService,
    RequirementService,
)
from flow_of_work_mcp import SQLiteRequirementLedger
from flow_of_work_mcp.core.domain.change_control import (
    GovernedChangeDraft,
    ImplementationPacketDraft,
)
from flow_of_work_mcp.core.domain.navigation_audit import (
    CandidateTarget,
    CandidateTargetSetDraft,
    ContextSnapshotRefDraft,
    NavigationAuditState,
    TargetBindingDraft,
)
from flow_of_work_mcp.core.domain.packet_construction import (
    PacketConstructionAuditDraft,
    PacketQuestionResolutionDraft,
)
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    PacketEvidenceClaimDraft,
    PacketEvidenceClaimType,
    PacketEvidenceSnapshotDraft,
)
from flow_of_work_mcp.core.domain.requirements import RequirementDraft
from flow_of_work_mcp.server import handle_packet_author
from tests.engineering_cycle_support import adopt_minimal_architecture


def create_packet_fixture(
    changes,
    *,
    project_id: str,
    change_id: str,
    title: str,
    completion_criteria: tuple[str, ...],
    intent: str,
    actor: str,
    request_id: str = "fixture-packet",
    milestone_id: str = "",
    rationale: str = "",
    requirement_ids: tuple[str, ...] = (),
    goal_ids: tuple[str, ...] = (),
    target_policy: str = "code_targets_required",
    active_provider: str = "",
    source_revision: str = "",
    architecture_refs: tuple[dict[str, object], ...] = (),
):
    """Create canonical state while retaining the compact legacy fixture shape."""

    ledger = changes._repository
    factory = PacketLifecycleService(
        ledger=ledger,
        changes=changes,
        assurance=AssuranceService(assurance=ledger, changes=ledger),
        navigation=NavigationAuditService(ledger),
        construction=PacketConstructionService(ledger),
        reconciliation=PacketReconciliationService(ledger),
    )
    result = factory.create_packet(
        project_id,
        change_id=change_id,
        packet=ImplementationPacketDraft(
            title=title,
            objective=intent,
            rationale=rationale,
            completion_criteria=completion_criteria,
            requirement_ids=requirement_ids,
            goal_ids=goal_ids,
            target_policy=target_policy,
            architecture_refs=architecture_refs,
        ),
        actor=actor,
        request_id=request_id,
        milestone_id=milestone_id,
        active_provider=active_provider,
        source_revision=source_revision,
    )
    return {
        **dict(result),
        "intent": intent,
        "change": dict(changes.get_change(project_id, change_id)),
    }


def ready_packet_state_fixture(
    tmp_path,
    *,
    accept_pressure: bool = True,
    candidate: CandidateTarget | None = None,
    provider_context_authoritative: bool = True,
):
    """Build an execution-ready semantic packet without a provider handoff."""

    ledger = SQLiteRequirementLedger(tmp_path / "ledger.sqlite3")
    requirements = RequirementService(ledger)
    requirements.create_project("alpha", "Alpha", actor="operator")
    architecture_refs = adopt_minimal_architecture(ledger)
    requirement = requirements.register(
        "alpha",
        RequirementDraft(
            title="Implement bounded packet work",
            statement="The server shall retain a complete bounded packet work plan.",
            category="functional",
            rationale="Exercise semantic packet state independently of a provider.",
        ),
        actor="operator",
    )
    changes = ChangeControlService(ledger)
    change = changes.create_change(
        "alpha",
        GovernedChangeDraft(
            title="Bounded packet work",
            rationale="Exercise packet lifecycle state.",
            requirement_ids=(requirement["requirement_id"],),
        ),
        actor="operator",
    )
    bootstrap = create_packet_fixture(
        changes,
        project_id="alpha",
        change_id=change["change_id"],
        title="Implement bounded packet work",
        completion_criteria=("bounded work validates",),
        intent="Implement one bounded packet change.",
        rationale="Keep semantic packet state provider-neutral.",
        requirement_ids=(requirement["requirement_id"],),
        milestone_id="MILE-000001",
        active_provider="codingcastle",
        source_revision="graph:alpha:1",
        actor="operator",
        request_id="ready-packet",
        architecture_refs=architecture_refs,
    )
    changes.refine_packet(
        "alpha",
        change["change_id"],
        bootstrap["packet_id"],
        in_scope=("bounded target",),
        out_of_scope=("unrelated modules",),
        invariants=("selected target identity remains stable",),
        actor="operator",
    )
    navigation = NavigationAuditService(ledger)
    selected = candidate or CandidateTarget(
        candidate_id="cand-1",
        target_handle="src/module.py::Target",
        target_kind="symbol",
        surface_id="repo",
        repo_or_workspace_id="repo-alpha",
        file_path="src/module.py",
        symbol_name="Target",
        line_start=1,
        line_end=40,
        graph_evidence={"chunk_id": "chunk-target"},
    )
    navigation.append_candidate_set(
        "alpha",
        bootstrap["navigation_audit_id"],
        CandidateTargetSetDraft(
            provider="codingcastle",
            provider_capability_version="implementation-graph-snapshot-v1",
            semantic_seeds=("bounded-work",),
            candidates=(selected,),
            source_revision="graph:alpha:2",
        ),
        actor="operator",
    )
    navigation.accept_candidate(
        "alpha",
        bootstrap["navigation_audit_id"],
        TargetBindingDraft(
            candidate_set_id="CSET-000001",
            candidate_id="cand-1",
            selection_reason="The target owns the bounded behavior.",
        ),
        actor="operator",
    )
    navigation.attach_context_snapshot(
        "alpha",
        bootstrap["navigation_audit_id"],
        ContextSnapshotRefDraft(
            provider="codingcastle",
            context_snapshot_id="ctx-ready-packet",
            source_revision="graph:alpha:2",
            metadata=(
                {
                    "revision_authority": "provider",
                    "target_handles": [selected.target_handle],
                }
                if provider_context_authoritative
                else {}
            ),
        ),
        actor="operator",
    )
    navigation.transition_block(
        "alpha",
        bootstrap["navigation_audit_id"],
        NavigationAuditState.ACCEPTED_FOR_PACKET,
        actor="operator",
        rationale="Target accepted.",
    )
    construction = PacketConstructionService(ledger)
    audit = construction.start_audit(
        "alpha",
        PacketConstructionAuditDraft(
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
        ),
        actor="operator",
    )
    for question in audit["questions"]:
        if question["required"]:
            construction.answer_question(
                "alpha",
                audit["construction_audit_id"],
                PacketQuestionResolutionDraft(
                    question_id=question["question_id"],
                    answer_summary=f"{question['category']} evidence is bounded.",
                    evidence_refs=(f"evidence:{question['question_key']}",),
                ),
                actor="operator",
            )
    changes.evaluate_packet_readiness(
        "alpha", change["change_id"], bootstrap["packet_id"], actor="operator"
    )
    pressure = PacketPressureService(ledger).derive(
        "alpha", change["change_id"], bootstrap["packet_id"], actor="operator"
    )
    if accept_pressure:
        PacketPressureService(ledger).accept_risk(
            "alpha",
            pressure["pressure_id"],
            accepted_risk_ref="operator-reviewed:semantic-risk",
            actor="operator",
        )
    return ledger, None, change, bootstrap


def make_documental_packet_ready_fixture(
    runtime,
    *,
    project_id: str,
    change_id: str,
    packet_id: str,
    actor: str = "operator",
    request_id: str = "fixture-documental-readiness",
):
    """Resolve the canonical construction gate for a documental fixture."""

    audit = runtime.packet_construction.audit_for_packet(
        project_id, change_id, packet_id
    )
    if audit is None:
        raise AssertionError("packet construction audit missing in test fixture")
    for index, question in enumerate(audit.get("questions", []), start=1):
        if not question.get("required") or question.get("status") not in {
            "open",
            "blocked",
        }:
            continue
        runtime.packet_construction.answer_question(
            project_id,
            str(audit["construction_audit_id"]),
            PacketQuestionResolutionDraft(
                question_id=str(question["question_id"]),
                answer_summary=(
                    f"{question['category']} is bounded by the documental fixture."
                ),
                evidence_refs=(f"fixture:{request_id}:{index}",),
            ),
            actor=actor,
            request_id=f"{request_id}:question:{index}",
        )
    return runtime.changes.evaluate_packet_readiness(
        project_id,
        change_id,
        packet_id,
        actor=actor,
        request_id=f"{request_id}:readiness",
    )


def reconcile_current_packet_fixture(
    runtime,
    *,
    project_id: str,
    change_id: str,
    packet_id: str,
    actor: str = "operator",
    request_id: str = "fixture-reconciliation",
):
    """Close current impact facts with a deterministic provider-equivalent snapshot."""

    state = runtime.packet_reconciliation.get(
        project_id,
        change_id=change_id,
        packet_id=packet_id,
    )
    if state is None:
        raise AssertionError("packet reconciliation scope missing in test fixture")
    target_handles = [
        str(binding.get("target_handle") or "")
        for block in runtime.ledger.list_navigation_audits(project_id)
        if str(block.get("packet_id") or "") == packet_id
        for binding in block.get("target_bindings", [])
        if str(binding.get("target_handle") or "")
    ]
    if not target_handles:
        raise AssertionError("test fixture requires one accepted target")
    target_handle = target_handles[0]
    runtime.packet_reconciliation.answer_gate(
        project_id,
        change_id=change_id,
        packet_id=packet_id,
        gate_kind="target",
        subject_ref=target_handle,
        predicate="selected_target",
        actor=actor,
        request_id=f"{request_id}:target",
    )

    current_gate = runtime.packet_lifecycle.get_packet(
        project_id,
        change_id,
        packet_id,
        view="gates",
    )["gate"]
    decision = dict(current_gate.get("decision_required") or {})
    if decision.get("kind") == "engineering_question":
        current = runtime.packet_reconciliation.get(
            project_id,
            change_id=change_id,
            packet_id=packet_id,
        )
        active_impact = [
            claim
            for claim in current.get("claims", [])
            if claim.get("origin") == "declared"
            and claim.get("status") == "active"
            and claim.get("claim_type") == "impact"
        ]
        response = {
            "answer_summary": "The selected target and its bounded consumers are affected.",
            "temporal_authority": "current_fact",
            "evidence_refs": [f"fixture:{request_id}:impact"],
        }
        if not active_impact:
            response.update(
                {
                    "classification": "affected",
                    "subject_ref": target_handle,
                    "predicate": "impact_classification",
                    "object_ref": "affected",
                }
            )
        handle_packet_author(
            runtime,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            operation="answer_gate",
            response=response,
            gate_fingerprint=str(current_gate["dependency_fingerprint"]),
            actor=actor,
            request_id=f"{request_id}:impact",
        )

    scope = runtime.packet_reconciliation.get(
        project_id,
        change_id=change_id,
        packet_id=packet_id,
    )
    declared = [
        claim
        for claim in scope.get("claims", [])
        if claim.get("origin") == "declared" and claim.get("status") == "active"
    ]
    expected = runtime.ledger.packet_reconciliation_expected_evidence_context(
        project_id,
        change_id,
        packet_id,
    )
    contexts = list(expected.get("contexts", []))
    if len(contexts) != 1:
        raise AssertionError("test fixture requires one provider evidence context")
    context = contexts[0]
    fingerprint = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    snapshot = runtime.packet_reconciliation.import_snapshot(
        project_id,
        PacketEvidenceSnapshotDraft(
            reconciliation_scope_id=str(scope["reconciliation_scope_id"]),
            packet_id=packet_id,
            provider_id=str(context.get("provider_id") or "codingcastle"),
            provider_scope_id=str(
                context.get("provider_scope_id") or "fixture-scope"
            ),
            provider_snapshot_id=f"snapshot-{fingerprint[:16]}",
            selection_ref=str(
                context.get("selection_ref") or "fixture-selection"
            ),
            source_revision=str(
                context.get("source_revision") or "fixture-revision"
            ),
            workspace_revision=str(context.get("workspace_revision") or ""),
            surfaces=(str(context.get("surface") or "repo"),),
            fingerprint=fingerprint,
            completeness={
                PacketEvidenceClaimType.TARGET.value: "complete",
                PacketEvidenceClaimType.IMPACT.value: "complete",
            },
            claims=tuple(
                PacketEvidenceClaimDraft(
                    claim_type=PacketEvidenceClaimType(str(claim["claim_type"])),
                    claim_key=str(claim["claim_key"]),
                    subject_ref=str(claim["subject_ref"]),
                    predicate=str(claim["predicate"]),
                    object_ref=str(claim.get("object_ref") or ""),
                    assertion=dict(claim.get("assertion") or {}),
                    evidence_refs=(f"fixture:{request_id}:observed",),
                    required=bool(claim.get("required", True)),
                    dynamic=False,
                    contradicted=False,
                )
                for claim in declared
            ),
        ),
        actor=actor,
        request_id=f"{request_id}:snapshot",
    )
    run = runtime.packet_reconciliation.reconcile(
        project_id,
        str(scope["reconciliation_scope_id"]),
        snapshot_id=str(snapshot["snapshot_id"]),
        actor=actor,
        request_id=f"{request_id}:run",
    )
    runtime.changes.evaluate_packet_readiness(
        project_id,
        change_id,
        packet_id,
        actor=actor,
        request_id=f"{request_id}:readiness",
    )
    return run
