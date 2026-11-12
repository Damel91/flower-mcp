"""Scoped acceptance readback preserves report, proof and decision boundaries."""
import asyncio
from dataclasses import replace

import pytest

from flow_of_work_mcp import (
    GoalGraphService, GovernedChangeDraft, GroundingAudit, GroundingDisposition, GroundingDivergence,
    GroundingItem, ImplementationAnchor, ImplementationPacketDraft, LifecycleControlService,
    LifecycleStatus, MilestoneDraft, PacketWorkPlanDraft, RequirementDraft, RequirementService, SequenceDraft,
    UseCaseDraft, VerificationDraft, VerificationKind, VerificationOutcome, WorkPlanUnit,
)
from flow_of_work_mcp.core.domain.campaign_authority import CampaignScopeDraft
from flow_of_work_mcp.core.domain.change_control import PacketStatus, PacketTransition
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import (
    create_app, handle_assurance, handle_change, handle_external_work,
    handle_handover, handle_packet_advance, handle_packet_inspect, handle_traceability,
)
from tests.engineering_cycle_support import adopt_minimal_architecture, record_test_repository_review
from tests.test_campaign_authority import _case, _complete_fields
from tests.test_campaign_host_execution import _advance, _author, _issue, _report
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


def _prepare_external(runtime, ids, *, deferred=False, authority_ref="", deferred_kind="live_campaign"):
    packet = runtime.ledger.change_state(*ids[:2])["packets"][0]
    spec_revision = packet["spec_revision"]
    external = runtime.external_work
    runtime.ledger.upgrade_external_criteria(*ids, packet["completion_criteria"], spec_revision=spec_revision, actor="agent")
    check = "Compare the public artifact checksum to the verified local build."
    verifies = [{"criterion": 1, "kind": "unit_check", "statement": check}]
    if deferred:
        verification = {"criterion": 1, "kind": deferred_kind, "statement": "Exercise the installed release. " * 20}
        if authority_ref:
            verification["authority_ref"] = authority_ref
        verifies.append(verification)
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
    return revisions


def _complete_external(runtime, ids, *, deferred=False, record_review=True):
    revisions = _prepare_external(runtime, ids, deferred=deferred)
    runtime.external_work.call(*ids, "report_outcome", actor="agent", request_id="report",
                               payload=report(runtime.external_work, ids, revisions, "publish", report_key="release-report"))
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


def test_public_milestone_snapshot_renders_without_a_packet_checkpoint(scoped_work):
    runtime, _requirements, ids, milestone_id, _identities = scoped_work

    async def run():
        reply = await create_app(runtime).call_tool("fow_handover", {
            "project_id": ids[0], "operation": "project_state_snapshot",
            "focus_kind": "milestone", "focus_ref": milestone_id,
        })
        assert reply.isError is False
        body = reply.structuredContent["result"]["result"]["project_state_snapshot"]
        assert body["acceptance_context"]["packet_checkpoint"] is None
        assert "**Milestone Acceptance:**" in reply.content[0].text
        assert "**Packet Checkpoint:**" not in reply.content[0].text

    asyncio.run(run())


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


@pytest.mark.parametrize("scenario", [
    "deterministic", "live", "integration", "wrong_class", "wrong_source", "no_link", "wrong_scope",
    "independent_exception", "stale_after_pass",
])
def test_linked_current_campaign_proof_reconciles_deferred_milestone(scoped_work, scenario):
    runtime, _requirements, ids, milestone_id, identities = scoped_work
    project_id, change_id, packet_id = ids
    requirement_id, _, goal_id, _ = identities
    ledger = runtime.ledger
    external = runtime.external_work
    report_source = "host-revision-1"
    independent = scenario == "independent_exception"
    case_source = "host-revision-other" if scenario == "wrong_source" else report_source
    case_class = scenario if scenario in {"live", "integration"} else "deterministic"
    deferred_kind = "live_campaign" if scenario in {"live", "integration", "wrong_class"} else "deterministic_campaign"
    goals = ()
    if case_class in {"live", "integration"}:
        graph = GoalGraphService(ledger)
        sequence = graph.add_sequence(project_id, SequenceDraft(
            title="Install artifact", participants=("operator", "runtime"),
            normal_steps=("Install the pinned artifact.", "Observe the running release."),
            expected_effects=("The verified release starts.",),
        ), actor="engineer")
        goals = (goal_id, sequence["goal_node_id"])
        graph.link(project_id, source_goal_id=goals[0], target_goal_id=goals[1],
                   relation="realized_by", actor="engineer")
        ledger.record_grounding_audit(GroundingAudit(
            project_id=project_id, provider_id="", source_revision=case_source,
            selected_goal_ids=goals, disposition=GroundingDisposition.COMPLETED,
            evidence_authority="host_declared",
            anchors=(ImplementationAnchor("fixture", "symbol", "installed release", "owned fixture"),),
            items=tuple(GroundingItem(GroundingDivergence.CONVERGED, goal, ("fixture",)) for goal in goals),
        ), actor="engineer")
    case = replace(_case("Verify the released artifact"), execution_class=case_class,
                   case_kind="live_sequence" if goals else "deterministic_regression")
    campaign = ledger.start_campaign_authority(
        project_id, title="Deferred milestone proof",
        scope=CampaignScopeDraft(
            change_id=change_id, milestone_id=milestone_id, requirement_ids=(requirement_id,),
            goal_ids=goals, packet_ids=() if scenario == "wrong_scope" else (packet_id,),
            execution_lane="host", independent_proof_refs=(packet_id,) if independent else (),
        ), first_case=case, actor="engineer",
    )["campaign_id"]
    if independent:
        ledger.add_campaign_authority_case(
            project_id, campaign, replace(case, title="Independent criterion proof", execution_lane="provider"),
            actor="engineer",
        )
    revisions = _prepare_external(
        runtime, ids, deferred=True, deferred_kind=deferred_kind,
        authority_ref="" if scenario == "no_link" else f"campaign:{campaign}",
    )
    state = ledger.derive_campaign_obligations(project_id, campaign, actor="engineer")
    case_id = state["cases"][0]["case_id"]
    criterion_obligation = next(
        (row for row in state["obligations"]
         if row["source_kind"] == "packet_criterion" and row["source_ref"] == f"{packet_id}:criterion:1"),
        None,
    )
    assert (criterion_obligation is not None) is (scenario != "wrong_scope")
    provider_case_id = state["cases"][1]["case_id"] if independent else ""
    _author(runtime, campaign, "author_obligations", "deferred-obligations", expected_fingerprint=state["fingerprint"],
            obligation_batch={
                "decisions": [{"obligation_id": row["obligation_id"], "decision": "required",
                               "rationale": "The declared obligation is in scope."} for row in state["obligations"]],
                "bindings": [{"obligation_id": row["obligation_id"],
                              "case_id": provider_case_id if independent and row == criterion_obligation else case_id,
                              "coverage_intent": row["statement"]} for row in state["obligations"]],
            })
    for current_case in state["cases"]:
        current_case_id = current_case["case_id"]
        _author(runtime, campaign, "author_oracle", f"deferred-oracle-{current_case_id}", case_id=current_case_id,
                oracle={"oracle_kind": "behavior", "subject_bindings": [requirement_id], "goal_bindings": list(goals),
                        "authority_reference": "confirmed campaign scope",
                        "semantic_fields": _complete_fields() | {"execution_class": case_class}})
    payload = report(external, ids, revisions, "publish", report_key="release-report")
    issued_receipt = external.call(*ids, "report_outcome", actor="agent", request_id="report", payload=payload)
    record_test_repository_review(ledger, ids, source_revision=payload["source_revision"])
    before = runtime.project_state_snapshot.acceptance_context(project_id, milestone_id=milestone_id)
    assert before["deferred_obligations"][0]["state"] == "verification_pending"
    assert "external_milestone_verification_pending" in {
        blocker["reason"] for blocker in before["milestone_acceptance"]["blockers"]
    }

    attempt = _issue(runtime, campaign, case_id, "deferred-issue", source=case_source)["host_attempt"]
    _report(runtime, campaign, attempt, "deferred-result", source=case_source)
    if independent:
        exception = _author(
            runtime, campaign, "accept_exception", "deferred-exception",
            exception_obligation_ids=[criterion_obligation["obligation_id"]],
            evidence_gaps=["Independent proof is unavailable in the fixture."],
            risk_authority="fixture:stakeholder-review", disposition_reference="fixture:independent-gap",
        )
        assert exception["campaign"]["status"] == "accepted_exception"
    else:
        advanced = _advance(runtime, campaign, "deferred-propagate", source=case_source)
        assert advanced["status"] == "success", advanced
        assert advanced["result"]["lifecycle_gate"]["state"] == "accepted"
        assert advanced["result"]["transitions"][0]["result"]["propagated"]
    after = runtime.project_state_snapshot.acceptance_context(project_id, milestone_id=milestone_id)
    obligation = after["deferred_obligations"][0]
    acceptance = after["milestone_acceptance"]
    expected_verified = scenario in {"deterministic", "live", "integration", "stale_after_pass"}
    expected_state = "verified" if expected_verified else "verification_pending"
    assert obligation["state"] == expected_state
    assert acceptance["recorded_acceptance"] is False
    assert acceptance["external_progress"]["implementation_complete"] is True
    assert acceptance["external_progress"]["local_verification_complete"] is True
    assert ("external_milestone_verification_pending" in {row["reason"] for row in acceptance["blockers"]}) is not expected_verified
    todo = external.todo(*ids)
    assert todo["authority_fingerprint"] == payload["authority_fingerprint"]
    assert todo["deferred_verification"][0]["state"] == expected_state
    assert todo["next_gate"]["external_operation"] == (
        "record_technical_disposition" if expected_verified else "obtain_deferred_verification"
    )
    replay = external.call(*ids, "report_outcome", actor="agent", request_id="report", payload=payload)
    assert replay.get("recorded_receipt", replay) == issued_receipt
    if scenario == "stale_after_pass":
        replacement = _issue(runtime, campaign, case_id, "deferred-source-changed", source="host-revision-new")
        assert replacement["host_attempt"]["attempt_id"] != attempt["attempt_id"]
        stale = runtime.project_state_snapshot.acceptance_context(project_id, milestone_id=milestone_id)
        stale_obligation = stale["deferred_obligations"][0]
        assert stale_obligation["state"] == "verification_pending"
        assert "campaign_proof" not in stale_obligation
        assert stale["milestone_acceptance"]["recorded_acceptance"] is False
        assert "external_milestone_verification_pending" in {
            row["reason"] for row in stale["milestone_acceptance"]["blockers"]
        }
        stale_todo = external.todo(*ids)
        assert stale_todo["authority_fingerprint"] == payload["authority_fingerprint"]
        assert stale_todo["next_gate"]["external_operation"] == "obtain_deferred_verification"
        replay = external.call(*ids, "report_outcome", actor="agent", request_id="report", payload=payload)
        assert replay.get("recorded_receipt", replay) == issued_receipt
    elif expected_verified:
        criterion = ledger.change_state(project_id, change_id)["packets"][0]["completion_criteria"][0]
        implemented = handle_change(
            runtime, project_id=project_id, change_id=change_id, packet_id=packet_id, operation="transition_packet",
            packet_status="implemented", actor="engineer", request_id="deferred-disposition",
            criterion_results={criterion: "Current report and linked campaign proof."},
        )
        assert implemented["status"] == "success", implemented
        human_gate = runtime.lifecycle.milestone_acceptance_context(project_id, milestone_id)
        assert human_gate["state"] == "awaiting_human"
        assert human_gate["awaited_inputs"] == ["acceptance_evidence"]
        if scenario != "deterministic":
            runtime.lifecycle.accept_milestone(project_id, milestone_id, acceptance_evidence=("operator:fixture",),
                                               actor="operator", request_id="deferred-human-decision")
            assert runtime.lifecycle.milestone_acceptance_context(project_id, milestone_id)["state"] == "accepted"
    elif scenario == "wrong_source":
        envelope = handle_packet_inspect(runtime, project_id=project_id, change_id=change_id, packet_id=packet_id,
                                         view="summary")
        structured = envelope["result"]["packet"]["acceptance_context"]["deferred_obligations"][0]
        assert structured["proof_reason"] == "Use campaign proof from the exact source of the current packet work."
        markdown = project_markdown("fow_packet_inspect", envelope, arguments={"view": "summary"})
        assert structured["proof_reason"] in markdown


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
