"""Cycle policy and concise authority-bound actions preserve complete machine data."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from flow_of_work_mcp.application.external_plan_markdown import render_plan
from flow_of_work_mcp.application.goal_hook_projection import GoalHookProjectionService
from flow_of_work_mcp.application.interaction_projection import InteractionProjectionService
from flow_of_work_mcp.application.lifecycle_recipes import get_recipe
from flow_of_work_mcp.application.operation_contracts import operation_contract, work_area_catalog
from flow_of_work_mcp.application.packet_guards import PacketGuardDecision, PacketGuardEvaluator
from flow_of_work_mcp.application.packet_next_action import PacketNextActionProjectionService
from flow_of_work_mcp.application.project_state_snapshot import _next_gate
from flow_of_work_mcp.model_facing import model_facing_tool, project_markdown


def review_projection(*, state="pending", complete=False):
    gate = {"tool": "fow_audit_phase", "operation": "call",
            "arguments": {"project_id": "alpha", "scope_id": "repository:PACKET-000001:1234567890abcdef",
                          "requirement_ids": ["REQ-000001"]},
            "required_inputs": ["actor", "request_id", "repository_review.source_identity",
                                "repository_review.source_revision", "repository_review.coverage"],
            "repository_review_template": {"contract_version": "flow.repository-review.v1",
                "change_id": "CHANGE-000001", "packet_id": "PACKET-000001",
                "expected_basis_fingerprint": "basis-from-current-authority"}}
    return {"contract_version": "flow.repository-review-projection.v1",
            "engineering_cycle_version": 1, "required": True, "state": state,
            "scope_id": gate["arguments"]["scope_id"], "requirement_ids": ["REQ-000001"],
            "basis_fingerprint": "basis-from-current-authority", "latest_audit_id": 9,
            "source": {"identity": "repository-alpha", "revision": "actual-source-pin", "provenance": "host_declared"},
            "coverage": [{"dimension": dimension, "state": "unknown",
                          "rationale": "FIRST_PRIVATE_DETAIL\n" + "long retained rationale " * 150,
                          "evidence_refs": ["host:evidence-001"]}
                         for dimension in ("requirements", "architecture", "grounding", "verification", "outcomes")],
            "complete": complete, "retrospective_recorded": False,
            "semantic_truth_verified": False, "human_acceptance": False,
            "next_gate": None if complete else gate}


def test_cycle_recipe_composes_existing_authority_without_transport_or_acceptance():
    recipe = get_recipe("provider-agnostic-engineering-cycle")
    assert recipe["contract_version"] == "flow.lifecycle-recipe.v2"
    assert not ({"steps", "tool", "operation", "arguments", "receipt"} & set(recipe))
    notes = " ".join(recipe["safety_notes"])
    for phrase in ("project-architecture-v1", "standalone-external-plan", "Flower is canonical",
                   "historical_on_pin", "interrupted handover", "host owns the agent loop"):
        assert phrase.lower() in notes.lower()
    assert "missing current outcome does not prove absent code" in notes
    assert "human acceptance" in notes
    review_stops = [item for item in recipe["stop_conditions"] if "repository review" in item]
    assert review_stops and all("final closure" in item and "dependent admission" in item for item in review_stops)
    assert "not before the packet's own unit work" in notes


def test_exact_review_and_history_help_keep_conditional_shape_and_scope_explicit():
    audit = operation_contract("fow_audit_phase", "call")
    assert "repository_review" in audit["optional_fields"]
    example = audit["example"]["repository_review"]
    assert example["contract_version"] == "flow.repository-review.v1"
    assert len(example["coverage"]) == 5
    assert {row["state"] for row in example["coverage"]} == {"unknown"}
    validation = operation_contract("fow_external_work", "validation")
    assert "payload.history_offset" in validation["optional_fields"]
    assert "outside guided execution" in validation["guidance"]["history"]
    semantic = operation_contract("fow_semantic", "prepare")
    assert "requirement_ids" in semantic["optional_fields"]
    assert "explicit []" in semantic["guidance"]["requirement_scope"]


@pytest.mark.parametrize("tool,operation", [("fow_external_work", "todo"),
    ("fow_handover", "project_state_snapshot"), ("fow_interaction", "frame"),
    ("fow_get_job", "")])
def test_default_review_text_is_compact_and_complete_machine_rows_are_untouched(tool, operation):
    review = review_projection()
    value = {"status": "success", "result": {"repository_review": review}}
    if tool == "fow_get_job":
        value["result"] = {"job": {"result": {"repository_review": review}},
                           "recovery": {"repository_review": review}}
    untouched = deepcopy(value)
    def handler(operation: str = ""):
        return value
    wrapped = model_facing_tool(handler, tool_name=tool)
    returned = wrapped(operation=operation)
    text = returned.content[0].text
    assert "FIRST_PRIVATE_DETAIL" not in text
    assert len(text) < 10_000
    assert "pending" in text and "basis-from-current-authority" in text
    assert returned.structuredContent == {"result": untouched}
    assert value == untouched


def test_explicit_review_detail_preserves_full_multiline_coverage_and_original_history():
    review = review_projection(state="open")
    payload = {"status": "success", "result": {"repository_review": review,
        "report_history": [{"report_key": "old-report", "source_revision": "historical-source-pin",
                            "spec_revision": 2, "plan_revision": 3,
                            "authority_fingerprint": "original-authority", "currentness": "historical_on_pin"}]}}
    untouched = deepcopy(payload)
    rendered = project_markdown("fow_external_work", payload,
                               arguments={"operation": "validation", "payload": {"detail": "full"}})
    assert "FIRST_PRIVATE_DETAIL\n  long retained rationale" in rendered
    assert "historical-source-pin" in rendered and "original-authority" in rendered
    assert "does not authorize replay" in rendered
    assert payload == untouched


@pytest.mark.parametrize("status", ["success", "blocked"])
def test_explicit_review_detail_remains_complete_beyond_the_generic_text_budget(status):
    payload = {"status": status, "result": {"repository_review": review_projection(state="open"),
        "report_history": [{"report_key": "original-report", "source_revision": "original-source-pin"}]}}
    original = deepcopy(payload)
    rendered = project_markdown("fow_external_work", payload,
        arguments={"operation": "validation", "payload": {"detail": "full"}}, output_budget=1024)
    assert len(rendered) > 1024
    assert rendered.count("FIRST_PRIVATE_DETAIL") == 5
    assert "original-source-pin" in rendered
    assert "model_facing_output_budget_exceeded" not in rendered
    assert payload == original


def test_blocked_default_review_does_not_reintroduce_long_rows_as_error_artifacts():
    review = review_projection(state="stale")
    payload = {"status": "blocked", "reason": "repository_review_stale",
               "result": {"repository_review": review}}
    untouched = deepcopy(payload)
    rendered = project_markdown("fow_external_work", payload, arguments={"operation": "todo"})
    assert "FIRST_PRIVATE_DETAIL" not in rendered
    assert "repository_review_stale" in rendered and len(rendered) < 8192
    assert payload == untouched


def test_blocked_direct_audit_review_is_compact_without_changing_machine_data():
    review = review_projection(state="authority_blocked")
    review["basis_fingerprint"] = None
    review["diagnostic"] = {"reason": "repository_review_authority_blocked",
                            "architecture_gaps": [{"code": "architecture_authority_stale"}]}
    review["next_gate"] = {"tool": "fow_external_work", "operation": "validation",
        "arguments": {"project_id": "alpha", "change_id": "CHANGE-000001",
            "packet_id": "PACKET-000001", "operation": "validation", "payload": {"detail": "full"}},
        "required_inputs": []}
    payload = {"status": "blocked", "reason": "repository_review_authority_blocked", "result": review}
    original = deepcopy(payload)

    def handler():
        return payload

    returned = model_facing_tool(handler, tool_name="fow_audit_phase")()
    text = returned.content[0].text
    assert "FIRST_PRIVATE_DETAIL" not in text and len(text) < 8192
    assert "authority_blocked" in text and "architecture_authority_stale" in text
    assert "fow_external_work" in text and "validation" in text
    assert "Coverage Count" in text and "5" in text
    assert returned.structuredContent == {"result": original}
    assert payload == original


def test_current_review_next_action_retains_issued_template_without_repository_reads():
    review = review_projection()
    decision = PacketGuardDecision("repository_reconciliation_pending", True, False, False,
                                  (), (), (), "repository_reconciliation", repository_review=review)
    action = PacketNextActionProjectionService().project(decision, project_id="alpha",
        change_id="CHANGE-000001", packet_id="PACKET-000001", spec_revision=2, plan_revision=3)
    assert action["tool"] == "fow_audit_phase" and action["operation"] == "call"
    assert action["arguments"] == review["next_gate"]["arguments"]
    assert action["repository_review_template"] == review["next_gate"]["repository_review_template"]
    assert "repository_review.coverage" in action["required_inputs"]
    gate = _next_gate("alpha", action, {})
    assert gate["kind"] == "repository_reconciliation"
    assert gate["route"]["repository_review_template"] == action["repository_review_template"]
    legacy = PacketGuardDecision("external_work_complete", True, False, False, (), (), (), "external_acceptance")
    assert "repository_review" not in legacy.as_payload()
    assert PacketGuardDecision.from_payload(decision.as_payload()) == decision
    with pytest.raises(ValueError, match="repository_review guard payload"):
        PacketGuardDecision.from_payload({**decision.as_payload(), "repository_review": "invalid"})


def test_unresolved_review_authority_points_to_explicit_read_instead_of_inventing_a_basis():
    review = review_projection(state="authority_blocked")
    review["basis_fingerprint"] = None
    review["next_gate"] = {"tool": "fow_external_work", "operation": "validation",
                           "arguments": {"project_id": "alpha", "change_id": "CHANGE-000001",
                               "packet_id": "PACKET-000001", "operation": "validation", "payload": {"detail": "full"}},
                           "required_inputs": []}
    decision = PacketGuardDecision("repository_reconciliation_pending", True, False, False,
                                  (), (), (), "repository_reconciliation", repository_review=review)
    action = PacketNextActionProjectionService().project(decision, project_id="alpha",
        change_id="CHANGE-000001", packet_id="PACKET-000001", spec_revision=2, plan_revision=3)
    assert action["tool"] == "fow_external_work"
    assert action["arguments"]["payload"] == {"detail": "full"}
    assert "repository_review_template" not in action


def test_architecture_admission_orients_new_acceptance_without_reenrolling_historical_plan():
    snapshot = {"packet": {"objective": "Investigated software", "completion_criteria": ["Bounded behavior"],
                           "spec_revision": 1},
                "work_plan": {"status": "proposed", "packet_revision": 1}}
    decision = PacketGuardEvaluator.evaluate_upstream(snapshot)
    assert decision.next_operation == "architecture_required"
    action = PacketNextActionProjectionService().project(decision, project_id="alpha",
        change_id="CHANGE-000001", packet_id="PACKET-000001", spec_revision=1, plan_revision=1)
    assert action["tool"] == "fow_architecture" and action["operation"] == "inspect"
    snapshot["work_plan"]["status"] = "accepted"
    assert PacketGuardEvaluator.evaluate_upstream(snapshot).next_operation != "architecture_required"


@pytest.mark.parametrize("kind,target_area", [("repository_reconciliation", "assurance"),
                                             ("architecture_authority", "project_bootstrap")])
def test_frame_issues_one_explicit_lens_selection_then_one_gate(kind, target_area):
    review = review_projection()
    route = review["next_gate"] if kind == "repository_reconciliation" else {
        "tool": "fow_architecture", "operation": "inspect", "arguments": {"project_id": "alpha", "operation": "inspect"},
        "required_inputs": []}
    snapshot = {"project_revision": "flow:1", "focus": {"kind": "packet", "ref": "PACKET-000001"},
                "active_work": {}, "next_gate": {"kind": kind, "reason": "current engineering obligation", "route": route},
                "repository_review": review, "blockers": [], "open_decisions": []}
    projector = SimpleNamespace(snapshot=lambda *_args, **_kwargs: snapshot)
    service = InteractionProjectionService(repository=object(), project_context=object(), project_state_snapshot=projector)
    context = SimpleNamespace(project_id="alpha", revision=1, provider_context_id="")
    lens = SimpleNamespace(producing_provider="flow", selected_area="packet_lifecycle", revision=1)
    frame = service._flow_frame(context, lens, {}, {})
    assert len(frame["actions"]) == 1
    action = frame["actions"][0]
    expected = next(number for number, item in enumerate(work_area_catalog(), 1) if item["area"] == target_area)
    assert action["tool"] == "fow_interaction" and action["arguments"]["area"] == expected
    assert lens.selected_area == "packet_lifecycle"
    lens.selected_area = target_area
    next_frame = service._flow_frame(context, lens, {}, {})
    assert len(next_frame["actions"]) == 1 and next_frame["actions"][0]["tool"] == route["tool"]
    if kind == "repository_reconciliation":
        assert next_frame["actions"][0]["repository_review_template"] == route["repository_review_template"]


@pytest.mark.parametrize("selected_area", ["assurance", "campaigns"])
def test_authority_blocked_review_uses_actual_validation_membership(selected_area):
    route = {"tool": "fow_external_work", "operation": "validation", "arguments": {
        "project_id": "alpha", "change_id": "CHANGE-000001", "packet_id": "PACKET-000001",
        "operation": "validation", "payload": {"detail": "full"}}, "required_inputs": []}
    snapshot = {"project_revision": "flow:1", "focus": {}, "active_work": {},
        "next_gate": {"kind": "repository_reconciliation", "reason": "authority blocked", "route": route},
        "blockers": [], "open_decisions": []}
    service = InteractionProjectionService(repository=object(), project_context=object(),
        project_state_snapshot=SimpleNamespace(snapshot=lambda *_args, **_kwargs: snapshot))
    context = SimpleNamespace(project_id="alpha", revision=1, provider_context_id="")
    lens = SimpleNamespace(producing_provider="flow", selected_area=selected_area, revision=1)
    frame = service._flow_frame(context, lens, {}, {})
    assert len(frame["actions"]) == 1 and lens.selected_area == selected_area
    if selected_area == "assurance":
        action = frame["actions"][0]
        assert action["tool"] == "fow_interaction"
        target = next(item["area"] for number, item in enumerate(work_area_catalog(), 1)
                      if number == action["arguments"]["area"])
        assert target == "packet_lifecycle"
        lens.selected_area = target
        frame = service._flow_frame(context, lens, {}, {})
    assert frame["actions"][0]["tool"] == "fow_external_work"
    assert frame["actions"][0]["operation"] == "validation"


def test_resolve_keeps_known_review_fields_and_requests_only_missing_host_inputs():
    review = review_projection()
    snapshot = {"project_revision": "flow:1", "focus": {}, "active_work": {},
        "next_gate": {"kind": "repository_reconciliation", "reason": "review required", "route": review["next_gate"]},
        "blockers": [], "open_decisions": []}
    service = InteractionProjectionService(repository=object(), project_context=object(),
        project_state_snapshot=SimpleNamespace(snapshot=lambda *_args, **_kwargs: snapshot))
    context = SimpleNamespace(project_id="alpha", revision=1, provider_context_id="")
    lens = SimpleNamespace(producing_provider="flow", selected_area="assurance", revision=1)
    frame = {**service._flow_frame(context, lens, {}, {}), "frame_ref": "current-frame"}
    original = deepcopy(frame)
    service.frame = lambda _interaction: frame
    resolved = service.resolve("client", "current-frame", 1)
    arguments = resolved["next_tool_call"]["arguments"]
    assert arguments["repository_review"] == review["next_gate"]["repository_review_template"]
    assert arguments["scope_id"] == review["scope_id"]
    assert arguments["requirement_ids"] == review["requirement_ids"]
    assert resolved["repository_review_template"] == arguments["repository_review"]
    assert set(resolved["semantic_inputs"]) == {
        "repository_review.source_identity", "repository_review.source_revision", "repository_review.coverage"}
    assert "source_revision" not in arguments["repository_review"]
    assert frame == original


def test_goal_hook_keeps_current_review_obligation_without_echoing_rationales_or_granting_authority():
    review = review_projection()
    snapshot = {"repository_review": review, "next_gate": {"kind": "repository_reconciliation", "state": "pending"}}
    projected = GoalHookProjectionService().project(trigger="bounded_work_completed",
        snapshot=snapshot, goal_graph={}, interaction_frame={})
    contribution = projected["contribution"]
    assert contribution["repository_review"]["state"] == "pending"
    assert len(contribution["repository_review"]["coverage"]) == 5
    assert "FIRST_PRIVATE_DETAIL" not in json.dumps(contribution)
    assert contribution["unresolved_obligations"][0]["kind"] == "repository_reconciliation"
    assert contribution["repository_review"]["human_acceptance"] is False


@pytest.mark.parametrize("version", [None, 1])
def test_offline_export_contains_issued_cycle_policy_without_mutable_review_status(version):
    snapshot = {"project_id": "alpha", "change_id": "CHANGE-000001", "packet_id": "PACKET-000001",
                "packet": {"title": "Bounded work", "objective": "Preserve investigated authority", "rationale": "Resume offline"},
                "change": {}, "engineering_cycle_version": version,
                "repository_review": review_projection()}
    projection = {"spec_revision": 1, "plan_revision": 1, "authority_fingerprint": "issued-original",
                  "contract_version": "flow.packet-validation.v1", "consumer_scope": "external_agent",
                  "status": "closed", "units": [], "criteria": [], "gaps": []}
    text = render_plan(snapshot, projection, project_predecessor=lambda _snapshot: {})
    assert "Flower is canonical" in text and "historical evidence on its pin" in text
    assert "interruption handover" in text and "Retain this original authority fingerprint and revisions" in text
    assert "FIRST_PRIVATE_DETAIL" not in text and "basis-from-current-authority" not in text
    if version == 1:
        assert "current bounded repository review" in text and "flow.repository-review.v1" in text
        assert "exactly five unique dimensions" in text
    else:
        assert "not silently enrolled" in text


def test_real_packet_snapshot_retains_completed_work_and_issued_review_action(tmp_path):
    from flow_of_work_mcp.mcp_runtime import build_runtime
    from tests.test_external_work import fixture, report

    ledger, _service, ids, revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=ledger.database_path, import_root=tmp_path, ledger=ledger)
    try:
        service = runtime.external_work
        for key in ("producer", "consumer"):
            service.call(*ids, "report_outcome", actor="host", request_id="cycle-exposure-" + key,
                         payload=report(service, ids, revisions, key=key, report_key="cycle-exposure-" + key))
        frontier = service.todo(*ids)
        assert frontier["current_unit"] is None
        assert {row["status"] for row in frontier["todos"]} == {"complete"}
        before = ledger.ledger_version(ids[0])
        snapshot = runtime.project_state_snapshot.snapshot(ids[0], focus_kind="packet", focus_ref=ids[2])
        assert snapshot["repository_review"]["required"] is True
        assert snapshot["repository_review"]["complete"] is False
        assert snapshot["next_gate"]["kind"] == "repository_reconciliation"
        route = snapshot["next_gate"]["route"]
        assert route["tool"] == "fow_audit_phase"
        assert route["repository_review_template"]["expected_basis_fingerprint"] == snapshot["repository_review"]["basis_fingerprint"]
        assert ledger.ledger_version(ids[0]) == before
    finally:
        runtime.close()


def test_actual_job_original_audit_is_compact_without_altering_raw_review(tmp_path):
    from flow_of_work_mcp.mcp_runtime import build_runtime
    from flow_of_work_mcp.server import handle_audit_phase, handle_get_job
    from tests.test_external_work import fixture

    ledger, _service, ids, _revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=ledger.database_path, import_root=tmp_path, ledger=ledger)
    try:
        projection = runtime.external_work.validation(*ids, detail="full")["repository_review"]
        review = {**projection["next_gate"]["repository_review_template"],
                  "source_identity": "synthetic:repository", "source_revision": "inspected-source-pin",
                  "coverage": [{**row, "rationale": row["rationale"].strip()}
                               for row in review_projection()["coverage"]]}
        submitted = handle_audit_phase(runtime, project_id=ids[0], scope_id=projection["scope_id"],
            requirement_ids=projection["requirement_ids"], repository_review=review,
            actor="host", request_id="audit-raw-review-exposure")
        job_id = submitted["result"]["job"]["job_id"]
        assert runtime.jobs.wait(ids[0], job_id, timeout=5).status.value == "completed"
        result = handle_get_job(runtime, project_id=ids[0], job_id=job_id)
        original = deepcopy(result)
        assert result["result"]["original_audit"]["repository_review"] == review
        rendered = project_markdown("fow_get_job", result)
        assert "FIRST_PRIVATE_DETAIL" not in rendered and len(rendered) < 12_000
        assert "inspected-source-pin" in rendered and projection["basis_fingerprint"] in rendered
        assert "original_audit.repository_review body returned by fow_get_job" in rendered
        assert "may reference a newer audit" in rendered
        assert result == original
    finally:
        runtime.close()
