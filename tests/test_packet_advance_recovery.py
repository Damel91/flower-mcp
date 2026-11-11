"""Public packet conflict recovery keeps comparison facts separate from effects."""

import asyncio
import sqlite3

import pytest

from flow_of_work_mcp.core.domain import GovernedChangeDraft, ImplementationPacketDraft, RequirementDraft
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app


@pytest.fixture
def packet(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "packet.sqlite3", import_root=tmp_path)
    try:
        project = "advance-recovery"
        runtime.requirements.create_project(project, "Packet recovery", actor="tester")
        requirement = runtime.requirements.register(project, RequirementDraft(
            title="Observable output", statement="The software shall show the current output.",
            category="functional", rationale="The output distinguishes a current result.",
        ), actor="tester")
        requirement_ids = (requirement["requirement_id"],)
        change = runtime.changes.create_change(project, GovernedChangeDraft(
            title="Show output", rationale="Realize the requirement.", requirement_ids=requirement_ids,
        ), actor="tester")
        state = runtime.changes.add_packet(project, change["change_id"], ImplementationPacketDraft(
            title="Render output", objective="Show the current output.",
            rationale="Complete the bounded output behavior.", requirement_ids=requirement_ids,
            in_scope=("output display",), invariants=("No unrelated state changes.",),
            completion_criteria=("The current output is visible.",),
        ), actor="tester")
        item = state["packets"][0]
        yield runtime, {
            "project_id": project, "change_id": change["change_id"], "packet_id": item["packet_id"],
        }, item["spec_revision"]
    finally:
        runtime.close()


def _call(runtime, tool, arguments):
    return asyncio.run(create_app(runtime).call_tool(tool, arguments))


def _snapshot(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


def _request(scope, spec_revision):
    return {
        "project_id": scope["project_id"], "packet_id": scope["packet_id"],
        "actor": "tester", "request_id": "test-advance-original-request",
        "expected_spec_revision": spec_revision, "expected_plan_revision": 0,
        "decision": {"operation": "accept_work_plan", "rationale": "The supplied plan is complete."},
    }


def _conflict(response, scope, request, reason):
    assert response.isError is False
    value = response.structuredContent["result"]
    result = value["result"]
    assert (value["status"], value["reason"]) == ("blocked", reason)
    assert result["operation_state"] == result["effect_state"] == "unknown"
    assert "effect_receipt" not in result
    correlation = {"tool": "fow_packet_advance", "operation": "advance", **scope,
                   "request_id": request["request_id"]}
    assert value["audit_reference"] == result["original_request"] == correlation
    assert result["next_tool_call"] == {"tool": "fow_packet_inspect", "arguments": {**scope, "view": "gates"}}
    assert result["diagnostics"][0]["code"] == reason
    assert result["diagnostics"][0]["effect_state"] == "unknown"
    assert "effect_receipt" not in result["diagnostics"][0]
    markdown = response.content[0].text
    for fact in (reason, "unknown", "fow_packet_inspect", scope["change_id"], scope["packet_id"], request["request_id"]):
        assert fact in markdown
    assert "before retrying" in markdown
    return result, markdown


def test_current_revisions_wrong_decision_has_scoped_recovery_even_after_real_repair(packet):
    runtime, scope, revision = packet
    address = tuple(scope.values())
    assert runtime.packet_construction.audit_for_packet(*address) is None
    request = _request(scope, revision)
    response = _call(runtime, "fow_packet_advance", request)
    result, markdown = _conflict(response, scope, request, "packet_decision_not_current")
    diagnostic = result["diagnostics"][0]
    assert diagnostic["received_operation"] == "accept_work_plan"
    assert diagnostic["decision_consumed"] is False
    assert runtime.packet_construction.audit_for_packet(*address) is not None
    assert runtime.ledger.packet_work_plan_state(*address) is None
    # The next read is callable as issued, and sees the current gate on this fixture.
    call = result["next_tool_call"]
    before_read = _snapshot(runtime)
    observed = _call(runtime, call["tool"], call["arguments"]).structuredContent["result"]
    assert _snapshot(runtime) == before_read
    assert observed["status"] == "success"
    current = observed["result"]["packet"]["next_action"]["lifecycle_operation"]
    assert diagnostic["expected_operation"] == current != "accept_work_plan"
    assert current in markdown and "accept_work_plan" in markdown


@pytest.mark.parametrize("field", ["expected_spec_revision", "expected_plan_revision"])
def test_stale_revision_preserves_expected_and_received_pair(packet, field):
    runtime, scope, revision = packet
    request = _request(scope, revision)
    request[field] += 1
    result, markdown = _conflict(_call(runtime, "fow_packet_advance", request), scope, request, "stale_packet_revision")
    diagnostic = result["diagnostics"][0]
    assert {name: diagnostic[name] for name in (
        "expected_spec_revision", "received_spec_revision", "expected_plan_revision", "received_plan_revision",
    )} == {
        "expected_spec_revision": revision, "received_spec_revision": request["expected_spec_revision"],
        "expected_plan_revision": 0, "received_plan_revision": request["expected_plan_revision"],
    }
    assert "decision_consumed" not in diagnostic
    assert "Received Spec Revision" in markdown and "Expected Plan Revision" in markdown


@pytest.mark.parametrize("error", [
    ValueError("late validation-shaped failure"),
    ChangeControlBlockedError("packet_decision_not_current"),
])
def test_unrecognized_failure_after_real_repair_keeps_native_error(packet, monkeypatch, error):
    runtime, scope, revision = packet

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(runtime.packet_advancement, "advance", fail)
    with pytest.raises(Exception, match=str(error)):
        _call(runtime, "fow_packet_advance", _request(scope, revision))
    assert runtime.packet_construction.audit_for_packet(*scope.values()) is not None


def test_success_and_sync_only_keep_existing_public_boundary(packet):
    runtime, scope, revision = packet
    request = _request(scope, revision)
    request.pop("decision")
    stale_sync = _call(runtime, "fow_packet_advance", {
        **request, "mode": "sync_only", "expected_spec_revision": revision + 1,
    }).structuredContent["result"]
    assert (stale_sync["status"], stale_sync["reason"]) == ("blocked", "stale_packet_revision")
    assert stale_sync["result"]["next_tool_call"] == {"tool": "fow_capabilities", "arguments": {"view": "summary"}}
    assert "original_request" not in stale_sync["result"]
    assert runtime.packet_construction.audit_for_packet(*scope.values()) is None
    ordinary = _call(runtime, "fow_packet_advance", {
        **request, "request_id": "test-ordinary-advance",
    }).structuredContent["result"]
    assert ordinary["status"] == "success"
    assert set(ordinary["result"]) == {"advancement", "gate", "next_action"}
    assert ordinary["audit_reference"] == {name: scope[name] for name in ("change_id", "packet_id")}
