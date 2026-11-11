"""Scoped acceptance readback preserves report, proof and decision boundaries."""
import asyncio

import pytest

from flow_of_work_mcp import (
    GoalGraphService, GovernedChangeDraft, ImplementationPacketDraft, LifecycleControlService,
    LifecycleStatus, MilestoneDraft, PacketWorkPlanDraft, RequirementDraft, RequirementService,
    UseCaseDraft, VerificationDraft, VerificationKind, VerificationOutcome, WorkPlanUnit,
)
from flow_of_work_mcp.core.domain.change_control import PacketStatus, PacketTransition
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import (
    create_app, handle_assurance, handle_change, handle_external_work,
    handle_handover, handle_packet_advance, handle_packet_inspect, handle_traceability,
)
from tests.engineering_cycle_support import adopt_minimal_architecture, record_test_repository_review
from tests.test_external_work import report


@pytest.fixture
def scoped_work(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        requirements = RequirementService(runtime.ledger)
        requirements.create_project("alpha", "Acceptance scope", actor="stakeholder")
        requirement_id, unrelated_requirement = (
            requirements.register("alpha", RequirementDraft(
                title=title, statement=f"The product shall {title}.", category="functional",
            ), actor="stakeholder")["requirement_id"] for title in ("publish the selected artifact", "run the unrelated workflow")
        )
        goals = GoalGraphService(runtime.ledger)
        goal_id, unrelated_goal = (goals.add_use_case("alpha", UseCaseDraft(
            title=title, actor="operator", objective=title, observable_outcome="The result is visible.",
        ), actor="stakeholder")["goal_node_id"] for title in ("Publish artifact", "Unrelated workflow"))
        milestone = runtime.lifecycle.promote_milestone("alpha", MilestoneDraft(
            name="Artifact publication", requirement_ids=(requirement_id,), prerequisite_requirement_ids=(),
            entry_policy={}, exit_policy={}, risk_disposition="none",
        ), actor="stakeholder")
        change = runtime.changes.create_change("alpha", GovernedChangeDraft(
            title="Publish artifact", rationale="The operator authorized this scope.",
            requirement_ids=(requirement_id,), milestone_id=milestone["milestone_id"],
        ), actor="stakeholder")
        packet = runtime.changes.add_packet("alpha", change["change_id"], ImplementationPacketDraft(
            title="Artifact release", objective="Publish the pinned artifact.",
            rationale="The operator must be able to install the verified release.",
            completion_criteria=("Published artifact matches the verified build",), requirement_ids=(requirement_id,),
            goal_ids=(goal_id,), in_scope=("Release artifact",), out_of_scope=("Other workflows",),
            invariants=("The checksum identifies the same artifact.",),
            architecture_refs=adopt_minimal_architecture(runtime.ledger),
        ), actor="stakeholder")["packets"][0]
        yield runtime, requirements, ("alpha", change["change_id"], packet["packet_id"]), milestone["milestone_id"], (
            requirement_id, unrelated_requirement, goal_id, unrelated_goal,
        )
    finally:
        runtime.close()


def _complete_external(runtime, ids, *, deferred=False, record_review=True):
    packet = runtime.ledger.change_state(*ids[:2])["packets"][0]
    spec_revision = packet["spec_revision"]
    external = runtime.external_work
    runtime.ledger.upgrade_external_criteria(*ids, packet["completion_criteria"], spec_revision=spec_revision, actor="agent")
    check = "Compare the public artifact checksum to the verified local build."
    verifies = [{"criterion": 1, "kind": "unit_check", "statement": check}]
    if deferred:
        verifies.append({"criterion": 1, "kind": "live_campaign", "statement": "Exercise the installed release. " * 20})
    plan = runtime.ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], spec_revision, (
        WorkPlanUnit(client_unit_key="publish", operation_kind="new_file", file_path="release.txt",
                     instructions=("Publish the pinned artifact.",), unit_checks=(check,), implements=(1,),
                     verifies=tuple(verifies)),
    )), actor="agent", request_id="plan")
    runtime.ledger.transition_packet_work_plan(ids[0], plan["work_plan_id"], plan["plan_revision"], status="accepted",
        expected_packet_revision=plan["packet_revision"], expected_current_plan_revision=plan["plan_revision"],
        rationale="Bounded test plan.", actor="agent", request_id="accept-plan")
    revisions = {"expected_spec_revision": plan["packet_revision"], "expected_plan_revision": plan["plan_revision"]}
    external.call(*ids, "set_mode", actor="agent", request_id="mode", payload={"mode": "external_agent", **revisions})
    external.call(*ids, "report_outcome", actor="agent", request_id="report",
                  payload=report(external, ids, revisions, "publish", report_key="release-report"))
    return record_test_repository_review(runtime.ledger, ids).audit_id if record_review else None


def test_p55_shape_explains_current_review_and_missing_registration_without_accepting(scoped_work):
    runtime, _requirements, ids, milestone_id, identities = scoped_work
    requirement_id, unrelated_requirement, goal_id, unrelated_goal = identities
    goals = GoalGraphService(runtime.ledger)
    for index in range(6):
        goals.add_use_case(ids[0], UseCaseDraft(title=f"Other workflow {index}", actor="operator",
            objective="Handle another workflow", observable_outcome="A separate result is visible."), actor="stakeholder")
    audit_id = _complete_external(runtime, ids)
    version = runtime.ledger.ledger_version(ids[0])
    result = runtime.project_state_snapshot.acceptance_context(ids[0], packet_id=ids[2])
    assert result["scope"] == dict(project_id=ids[0], change_id=ids[1], packet_id=ids[2], milestone_id=milestone_id)
    assert result["packet_checkpoint"]["state"] == "record_technical_disposition"
    assert result["packet_checkpoint"]["reported_units"]["completed"] == 1
    assert result["packet_checkpoint"]["repository_review"]["latest_audit_id"] == audit_id
    assert result["packet_checkpoint"]["repository_review"]["complete"] is True
    acceptance = result["milestone_acceptance"]
    assert acceptance["state"] == "blocked"
    assert acceptance["awaited_inputs"] == []
    assert {row["reason"] for row in acceptance["blockers"]} == {"packet_unresolved", "campaign_missing"}
    assert result["requirements"][0]["requirement_id"] == requirement_id
    assert result["requirements"][0]["lifecycle_status"] == "planned"
    assert result["requirements"][0]["direct_evidence_state"] == "missing_registration"
    assert [(row["goal_node_id"], row["gaps"]) for row in result["goal_grounding"]] == [
        (goal_id, ["implementation_grounding_missing"])
    ]
    assert unrelated_requirement not in str(result) and unrelated_goal not in str(result)
    overall = runtime.project_state_snapshot.snapshot(ids[0], limit=3)["goal_reach"]
    assert overall["ledger_only"] is True
    assert overall["summary"]["unresolved"] == 8
    assert len(overall["items"]) == 3 and overall["omitted_count"] == 5
    envelope = handle_handover(runtime, project_id=ids[0], operation="project_state_snapshot",
                               focus_kind="packet", focus_ref=ids[2])
    assert envelope["result"]["project_state_snapshot"]["acceptance_context"] == result
    markdown = project_markdown("fow_handover", envelope, arguments={"operation": "project_state_snapshot"})
    assert "record_technical_disposition" in markdown and "campaign_missing" in markdown
    assert "implementation_grounding_missing" not in markdown
    audit = project_markdown("fow_handover", envelope, arguments={
        "operation": "project_state_snapshot", "projection_kind": "audit",
    })
    assert "implementation_grounding_missing" in audit
    assert len(markdown) < len(audit) // 3
    inspection = handle_packet_inspect(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2], view="summary")
    assert inspection["result"]["packet"]["acceptance_context"] == result
    packet_markdown = project_markdown("fow_packet_inspect", inspection, arguments={"view": "summary"})
    assert "Scoped acceptance and evidence" in packet_markdown
    assert "outstanding prerequisites" in packet_markdown
    assert runtime.ledger.ledger_version(ids[0]) == version
    assert runtime.lifecycle.milestone_closure_state(ids[0], milestone_id)["acceptance_state"] == "blocked"


def test_direct_proofs_keep_ids_outcomes_and_counts_without_claiming_live_or_acceptance(scoped_work):
    runtime, requirements, ids, milestone_id, identities = scoped_work
    requirement_id = identities[0]
    requirements.set_lifecycle(ids[0], requirement_id, LifecycleStatus.IMPLEMENTED, actor="agent",
                               reason="The bounded requirement is implemented.")
    evidence_ids = []
    for index in range(4):
        receipt = requirements.record_verification(ids[0], requirement_id, VerificationDraft(
            VerificationKind.DETERMINISTIC, VerificationOutcome.FAILED if index == 3 else VerificationOutcome.PASSED,
            f"report:test-proof-{index}",
        ), actor="agent")
        evidence_ids.append(receipt["evidence_id"])
    result = runtime.project_state_snapshot.acceptance_context(ids[0], milestone_id=milestone_id, limit=1)
    assert result["packet_checkpoint"] is None
    requirement = result["requirements"][0]
    assert requirement["lifecycle_status"] == "implemented"
    assert requirement["direct_evidence_count"] == 4
    assert [row["evidence_id"] for row in requirement["direct_evidence"]] == list(reversed(evidence_ids[-3:]))
    assert requirement["direct_evidence"][0]["outcome"] == "failed"
    reference = requirement["direct_evidence"][0]["detail_reference"]
    assert reference["tool"] == "fow_traceability"
    proof = handle_traceability(runtime, **reference["arguments"])
    assert proof["status"] == "success" and proof["result"]["evidence"]["evidence_id"] == evidence_ids[-1]
    assert all(row["verification_kind"] == "tested_deterministically" for row in requirement["direct_evidence"])
    assert requirement["direct_evidence_truncated"] is True and result["truncated"] is True
    assert result["milestone_acceptance"]["state"] == "blocked"


def test_public_snapshot_audit_only_expands_markdown_and_progress_names_its_basis(scoped_work):
    runtime, _requirements, ids, milestone_id, _identities = scoped_work

    async def run():
        app = create_app(runtime)
        progress_args = {"project_id": ids[0], "operation": "project_progress", "milestone_ids": [milestone_id]}
        before = await app.call_tool("fow_handover", progress_args)
        assert "percentage unknown" in before.content[0].text
        assert "0/1 selected milestones with accepted status and recorded evidence" in before.content[0].text

        _complete_external(runtime, ids)
        args = {"project_id": ids[0], "operation": "project_state_snapshot", "focus_kind": "packet", "focus_ref": ids[2]}
        ordinary = await app.call_tool("fow_handover", args)
        audit = await app.call_tool("fow_handover", {**args, "projection_kind": "audit"})
        assert not ordinary.isError and not audit.isError
        ordinary_state = dict(ordinary.structuredContent["result"]["result"]["project_state_snapshot"])
        audit_state = dict(audit.structuredContent["result"]["result"]["project_state_snapshot"])
        ordinary_state.pop("generated_at")
        audit_state.pop("generated_at")
        assert ordinary_state == audit_state
        ordinary_text, audit_text = ordinary.content[0].text, audit.content[0].text
        for field in ("project_revision", "snapshot_fingerprint", "source_ledger_version_namespace"):
            assert ordinary_state[field] in audit_text and ordinary_state[field] not in ordinary_text
        assert "Source Ledger Version" in audit_text and "Source Ledger Version" not in ordinary_text
        assert "Generated At" in audit_text and "Generated At" not in ordinary_text
        for text in (ordinary_text, audit_text):
            assert "Next Gate" in text and "Completeness" in text
            assert "campaign_missing" in text and "record_technical_disposition" in text
        assert "projection_kind=audit" in ordinary_text

        progress = await app.call_tool("fow_handover", progress_args)
        state = progress.structuredContent["result"]["result"]["project_progress"]
        assert state == runtime.milestone_traceability.progress(ids[0], milestone_ids=(milestone_id,))
        assert state["implementation"]["completed"] == state["local_verification"]["completed"] == 1
        text = progress.content[0].text
        assert "1/1 applicable criteria" in text
        assert "Current host reports against the recorded criterion scope" in text
        assert "0/1 selected milestones with accepted status and recorded evidence" in text
        assert "Repository state and test execution require separate evidence" in text
        assert state["progress_revision"] in text  # A guided continuation consumes this revision.

        help_args = {"view": "operation", "operation_tool": "fow_handover", "operation_name": "project_state_snapshot"}
        help_reply = await app.call_tool("fow_capabilities", help_args)
        contract = help_reply.structuredContent["result"]["result"]["operation_contract"]
        assert "projection_kind" in contract["optional_fields"]
        assert "projection_kind=audit" in contract["guidance"]["presentation"]

    asyncio.run(run())


def test_external_packet_disposition_routes_exact_evidence_after_current_review(scoped_work):
    runtime, _requirements, ids, milestone_id, _identities = scoped_work
    project_id, change_id, packet_id = ids
    scope = {"project_id": project_id, "change_id": change_id, "packet_id": packet_id}
    read_args = {"project_id": project_id, "change_id": change_id,
                 "operation": "inspect_change_acceptance", "actor": "agent"}
    todo_args = {**scope, "operation": "todo"}
    _complete_external(runtime, ids, record_review=False)
    pending_review = handle_external_work(runtime, **todo_args)
    assert pending_review["result"]["next_gate"]["reason"] == "repository_review_required"
    assert pending_review["result"]["next_gate"]["tool"] == "fow_audit_phase"
    record_test_repository_review(runtime.ledger, ids)

    route = {"tool": "fow_change", "operation": "transition_packet",
             "arguments": {**scope, "operation": "transition_packet", "packet_status": "implemented"},
             "required_inputs": ["criterion_results", "actor", "request_id"],
             "criterion_result_keys": ["Published artifact matches the verified build"]}
    todo = handle_external_work(runtime, **todo_args)
    packet = handle_packet_inspect(runtime, **scope)["result"]["packet"]
    advanced = handle_packet_advance(runtime, **scope, actor="agent",
                                     request_id="next-disposition", mode="sync_only")["result"]
    snapshot = runtime.project_state_snapshot.snapshot(
        project_id, focus_kind="packet", focus_ref=packet_id,
    )
    assert snapshot["next_gate"]["kind"] == "packet_disposition"
    for actual in (todo["result"]["next_gate"], packet["next_action"], advanced["next_action"],
                   packet["acceptance_context"]["packet_checkpoint"]["next_gate"], snapshot["next_gate"]["route"]):
        assert {key: actual[key] for key in route} == route
    markdown = project_markdown("fow_external_work", todo, arguments=todo_args)
    assert "transition_packet" in markdown and "Published artifact matches the verified build" in markdown

    before = handle_assurance(runtime, **read_args)["result"]["assurance"]
    assert {blocker["kind"] for blocker in before["blockers"]} == {"packet_unresolved", "campaign_missing"}
    rejected = handle_change(runtime, **route["arguments"], actor="agent", request_id="missing-evidence")
    assert rejected["reason"] == "packet_completion_criteria_missing"
    implemented = handle_change(
        runtime, **route["arguments"], actor="agent", request_id="record-disposition",
        criterion_results={route["criterion_result_keys"][0]: "release-report and current repository review"},
    )
    assert implemented["status"] == "success"
    after = handle_assurance(runtime, **read_args)["result"]["assurance"]
    assert [blocker["kind"] for blocker in after["blockers"]] == ["campaign_missing"]
    assert runtime.lifecycle.milestone_closure_state(project_id, milestone_id)["acceptance_state"] == "blocked"
    assert handle_packet_inspect(runtime, **scope)["result"]["packet"]["next_action"]["lifecycle_operation"] == "packet_inactive"


def test_external_deferred_requirement_uses_same_check_and_mixed_mode_preserves_existing_branch(scoped_work):
    runtime, _requirements, ids, milestone_id, identities = scoped_work
    _complete_external(runtime, ids, deferred=True)
    result = runtime.project_state_snapshot.acceptance_context(ids[0], packet_id=ids[2])
    assert result["packet_checkpoint"]["state"] == "obtain_deferred_verification"
    assert result["milestone_acceptance"]["external_progress_applies"] is True
    assert result["milestone_acceptance"]["blockers"][0]["reason"] == "external_milestone_verification_pending"
    assert result["deferred_obligations"][0]["applicability"] == "acceptance_prerequisite"
    assert result["deferred_obligations"][0]["statement_truncated"] and result["truncated"]
    with pytest.raises(ChangeControlBlockedError, match="external_milestone_verification_pending"):
        runtime.lifecycle.accept_milestone(ids[0], milestone_id, acceptance_evidence=("operator:decision",), actor="operator")
    runtime.changes.add_packet(*ids[:2], ImplementationPacketDraft(
        title="Provider sibling", completion_criteria=("Existing scope is preserved",), requirement_ids=(identities[0],),
    ), actor="operator")
    mixed = runtime.project_state_snapshot.acceptance_context(ids[0], packet_id=ids[2])
    assert mixed["milestone_acceptance"]["external_progress_applies"] is False
    assert mixed["deferred_obligations"][0]["applicability"] == "packet_context"
    with pytest.raises(ChangeControlBlockedError, match="milestone_acceptance_blocked"):
        runtime.lifecycle.accept_milestone(ids[0], milestone_id, acceptance_evidence=("operator:decision",), actor="operator")


def test_existing_closure_distinguishes_missing_human_input_from_a_prerequisite(scoped_work):
    runtime, _requirements, ids, milestone_id, _identities = scoped_work
    ledger = runtime.ledger
    # The isolated authority has no campaign service. Seed a historical terminal
    # packet to isolate acceptance evidence from technical prerequisites.
    ledger.transition_packet(*ids, PacketTransition(status=PacketStatus.IMPLEMENTED), actor="fixture")
    service = LifecycleControlService(requirements=ledger, goals=ledger, grounding_audits=ledger,
                                      control=ledger, change_control=ledger)
    context = service.milestone_acceptance_context(ids[0], milestone_id)
    assert context["state"] == "awaiting_human"
    assert context["blockers"] == []
    assert context["awaited_inputs"] == ["acceptance_evidence"]
    with pytest.raises(ValueError, match="requires acceptance evidence"):
        service.accept_milestone(ids[0], milestone_id, acceptance_evidence=(), actor="operator")
    service.accept_milestone(ids[0], milestone_id, acceptance_evidence=("operator:observed-acceptance",), actor="operator")
    accepted = service.milestone_acceptance_context(ids[0], milestone_id)
    assert accepted["state"] == "accepted"
    assert accepted["recorded_acceptance"] is True
    assert accepted["awaited_inputs"] == []
