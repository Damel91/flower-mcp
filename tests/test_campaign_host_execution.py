from dataclasses import replace

from flow_of_work_mcp import (
    GoalGraphService, GroundingAudit, GroundingDisposition, GroundingDivergence,
    GroundingItem, ImplementationAnchor, SequenceDraft, UseCaseDraft,
)
from flow_of_work_mcp.core.domain.campaign_authority import CampaignScopeDraft
from flow_of_work_mcp.server import handle_campaign_advance, handle_campaign_author, handle_campaign_inspect
from tests.test_campaign_authority import _case, _complete_fields, _runtime


ACTOR = "engineer"
PROJECT = "alpha"
SOURCE = "git:feature-verified"


def _ready(tmp_path, *, live=False, independent=False, provider=False):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    goals = []
    if live:
        graph = GoalGraphService(runtime.ledger)
        use_case = graph.add_use_case(
            PROJECT, UseCaseDraft(title="Public use case", actor=ACTOR, objective="Run the flow",
                                  observable_outcome="The result is visible."), actor=ACTOR,
        )
        sequence = graph.add_sequence(
            PROJECT, SequenceDraft(title="Runtime sequence", participants=(ACTOR, "server"),
                                   normal_steps=("invoke", "observe"), expected_effects=("result",)), actor=ACTOR,
        )
        goals = [use_case["goal_node_id"], sequence["goal_node_id"]]
        graph.link(PROJECT, source_goal_id=goals[0], target_goal_id=goals[1], relation="realized_by", actor=ACTOR)
    scope = CampaignScopeDraft(
        change_id=change_id, requirement_ids=(requirement_id,), goal_ids=tuple(goals),
        execution_lane="provider" if provider else "host",
        independent_proof_refs=(requirement_id,) if independent else (),
    )
    state = runtime.ledger.start_campaign_authority(
        PROJECT, title="Campaign", scope=scope,
        first_case=replace(_case(), case_kind="deterministic_regression"), actor=ACTOR,
    )
    campaign = state["campaign_id"]
    if live:
        runtime.ledger.add_campaign_authority_case(
            PROJECT, campaign, replace(_case("Live sequence"), case_kind="live_sequence", execution_class="live"),
            actor=ACTOR,
        )
    state = runtime.ledger.derive_campaign_obligations(PROJECT, campaign, actor=ACTOR)
    decisions = []
    bindings = []
    for item in state["obligations"]:
        obligation = item["obligation_id"]
        decisions.append({"obligation_id": obligation, "decision": "required", "rationale": "Current scope."})
        if item["source_kind"] == "requirement":
            bindings.append({"obligation_id": obligation, "case_id": "CASE-000001", "coverage_intent": "Observe output."})
        if live:
            bindings.append({"obligation_id": obligation, "case_id": "CASE-000002", "coverage_intent": "Observe live sequence."})
    _author(runtime, campaign, "author_obligations", "group", expected_fingerprint=state["fingerprint"],
            obligation_batch={"decisions": decisions, "bindings": bindings})
    for index in range(1, 3 if live else 2):
        fields = _complete_fields() | {"execution_class": "live" if index == 2 else "deterministic"}
        _author(
            runtime, campaign, "author_oracle", f"oracle-{index}", case_id=f"CASE-{index:06d}",
            oracle={"oracle_kind": "behavior", "subject_bindings": [requirement_id],
                    "goal_bindings": goals if index == 2 else [],
                    "authority_reference": "confirmed campaign scope", "semantic_fields": fields},
        )
    return runtime, campaign, change_id, requirement_id, goals


def _author(runtime, campaign, operation, request, *, expected="success", **fields):
    response = handle_campaign_author(
        runtime, project_id=PROJECT, campaign_id=campaign, operation=operation,
        request_id=request, actor=ACTOR, **fields,
    )
    assert response["status"] == expected, response
    return response["result"]


def _issue(runtime, campaign, case_id, request, *, source=SOURCE, check="verify_public_behavior", expected="success"):
    return _author(runtime, campaign, "issue_host_check", request, case_id=case_id, expected=expected, host_check={
        "source_revision": source, "execution_profile": "local test fixture", "check_reference": check,
    })


def _report(runtime, campaign, attempt, request, *, outcome="passed", source=SOURCE, expected="success"):
    return _author(runtime, campaign, "report_host_result", request, expected=expected, host_result={
        "attempt_id": attempt["attempt_id"], "source_revision": source, "outcome": outcome,
        "evidence_reference": "fixture:public-observation", "observation": "Observed result for this test case.",
    })


def _inspect(runtime, campaign, view="summary"):
    return handle_campaign_inspect(runtime, project_id=PROJECT, campaign_id=campaign, view=view)["result"]


def _advance(runtime, campaign, request, *, source=""):
    return handle_campaign_advance(
        runtime, project_id=PROJECT, campaign_id=campaign, actor=ACTOR, request_id=request, source_revision=source,
    )


def test_providerless_host_campaign_reconciles_deterministic_and_live_with_current_grounding(tmp_path):
    runtime, campaign, _, _, goals = _ready(tmp_path, live=True)
    try:
        assert _inspect(runtime, campaign)["lifecycle_gate"]["next_action"]["operation"] == "issue_host_check"
        first = _issue(runtime, campaign, "CASE-000001", "issue-1")["host_attempt"]
        assert first["basis"]["oracle"]["oracle_revision"] == 1
        assert _issue(runtime, campaign, "CASE-000001", "issue-1")["host_attempt"] == first
        wrong = _report(runtime, campaign, first, "wrong", source="git:drift", expected="rejected")
        assert wrong["effect_state"] == "none"
        report = _report(runtime, campaign, first, "report-1")
        assert report["host_receipt"]["provenance"] == "host_reported"
        assert report["lifecycle_gate"]["next_action"]["arguments"]["case_id"] == "CASE-000002"
        second = _issue(runtime, campaign, "CASE-000002", "issue-2")["host_attempt"]
        _report(runtime, campaign, second, "report-2")
        assert _advance(runtime, campaign, "no-source")["result"]["lifecycle_gate"]["state"] == "source_boundary"
        denied = _advance(runtime, campaign, "missing-grounding", source=SOURCE)
        assert denied["reason"] == "campaign_host_live_coverage_blocked"
        assert not _inspect(runtime, campaign)["campaign"]["completed"]
        runtime.ledger.record_grounding_audit(
            GroundingAudit(
                project_id=PROJECT, provider_id="", source_revision=SOURCE, selected_goal_ids=tuple(goals),
                disposition=GroundingDisposition.COMPLETED, evidence_authority="host_declared",
                anchors=(ImplementationAnchor("fixture", "symbol", "public call", "owned live fixture"),),
                items=tuple(GroundingItem(GroundingDivergence.CONVERGED, goal, ("fixture",)) for goal in goals),
            ),
            actor=ACTOR,
        )
        advanced = _advance(runtime, campaign, "coverage", source=SOURCE)
        assert advanced["status"] == "success", advanced
        assert advanced["result"]["lifecycle_gate"]["state"] == "accepted"
        evidence = advanced["result"]["transitions"][0]["result"]["propagated"]
        assert {item["kind"] for item in evidence} == {"tested_deterministically", "tested_live"}
        assert all(
            runtime.ledger.verification_evidence(PROJECT, item["evidence_id"])["metadata"]["provenance"] == "host_reported"
            for item in evidence
        )
        assert len(_inspect(runtime, campaign, "host_attempts")["host_attempts"]) == 2
        assert _report(runtime, campaign, first, "report-1")["host_receipt"] == report["host_receipt"]
        refreshed = _advance(runtime, campaign, "new-source", source="git:new")["result"]["lifecycle_gate"]
        assert refreshed["next_action"]["operation"] == "issue_host_check"
        replacement = _issue(runtime, campaign, "CASE-000001", "issue-new", source="git:new")["host_attempt"]
        assert replacement["attempt_id"] != first["attempt_id"]
        assert not _inspect(runtime, campaign)["campaign"]["completed"]
        assert all(not item["current"] for item in _inspect(runtime, campaign, "evidence")["evidence"])
    finally:
        runtime.close()


def test_independent_proof_is_a_named_hold_and_provider_lane_is_unchanged(tmp_path):
    runtime, campaign, _, _, _ = _ready(tmp_path / "host", independent=True)
    try:
        gate = _inspect(runtime, campaign)["lifecycle_gate"]
        assert gate["state"] == "independent_proof_boundary"
        assert gate["decision_required"]["obligation_ids"] == ["OBL-000001"]
        rejected = _issue(runtime, campaign, "CASE-000001", "held", expected="rejected")
        assert rejected["effect_state"] == "none"
        assert not _inspect(runtime, campaign, "evidence")["evidence"]
    finally:
        runtime.close()
    runtime, campaign, _, _, _ = _ready(tmp_path / "provider", provider=True)
    try:
        gate = _inspect(runtime, campaign)["lifecycle_gate"]
        assert gate["next_action"]["operation"] == "attest_source"
        _issue(runtime, campaign, "CASE-000001", "wrong-lane", expected="rejected")
    finally:
        runtime.close()


def test_host_failure_routes_preserve_the_attempt_and_require_corrected_basis(tmp_path):
    runtime, campaign, change_id, requirement_id, _ = _ready(tmp_path)
    try:
        attempt = _issue(runtime, campaign, "CASE-000001", "issue")["host_attempt"]
        blocked = _report(runtime, campaign, attempt, "environment", outcome="environment_failed")
        assert "restore the declared execution environment" in blocked["lifecycle_gate"]["semantic_effect"]
        retry = _issue(runtime, campaign, "CASE-000001", "issue-again")["host_attempt"]
        failed = _report(runtime, campaign, retry, "invalid", outcome="test_invalid")
        assert failed["lifecycle_gate"]["next_action"]["operation"] == "issue_host_check"
        _issue(runtime, campaign, "CASE-000001", "same-invalid-check", expected="rejected")
        corrected = _issue(runtime, campaign, "CASE-000001", "new-check", check="corrected check")["host_attempt"]
        failure = _report(runtime, campaign, corrected, "product", outcome="product_failed")
        assert failure["lifecycle_gate"]["next_action"]["operation"] == "record_finding"
        _issue(runtime, campaign, "CASE-000001", "same-source", expected="rejected")
        new = _issue(runtime, campaign, "CASE-000001", "corrected-source", source="git:corrected")["host_attempt"]
        _author(runtime, campaign, "edit_scope", "new-profile", title="Campaign", scope={
            "change_id": change_id, "requirement_ids": [requirement_id], "environment_assumptions": ["New profile"],
        })
        stale = _report(runtime, campaign, new, "stale", source="git:corrected", expected="rejected")
        assert stale["effect_state"] == "none"
        assert _inspect(runtime, campaign)["lifecycle_gate"]["next_action"]["operation"] == "issue_host_check"
    finally:
        runtime.close()
