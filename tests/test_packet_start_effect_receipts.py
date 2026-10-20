"""Packet start proof is knowledge at the pre-write boundary, not error wording."""
import asyncio
from contextlib import contextmanager
import sqlite3

import pytest

from flow_of_work_mcp.core.domain import RequirementDraft
from flow_of_work_mcp.core.errors import (
    ChangeNotFoundError, OperationPreEffectError, RequirementConflictError,
)
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app, handle_change, handle_packet_author


@pytest.fixture
def owned_runtime(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "owned.sqlite3", import_root=tmp_path)
    runtime.requirements.create_project("packet-effect", "Owned packet effect", actor="tester")
    requirement = runtime.requirements.register("packet-effect", RequirementDraft(
        title="Observable work", statement="The software shall retain observable work.",
        category="functional", rationale="Owned regression state."), actor="tester")
    scope = handle_change(runtime, project_id="packet-effect", operation="create_change",
        title="Owned scope", rationale="Regression scope.", requirement_ids=[requirement["requirement_id"]],
        actor="tester", request_id="scope")
    assert scope["status"] == "success"

    yield runtime
    runtime.close()


def request(**changes):
    return {"operation": "start_packet", "project_id": "packet-effect", "change_id": "CHANGE-000001",
            "title": "Owned packet", "intent": "Implement observable work.", "completion_criteria": ["Observable check"],
            "purpose": "implementation", "actor": "tester", "request_id": "original-packet", **changes}


def snapshot(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


def assert_none(response, arguments, field):
    result = response["result"]
    correlation = {key: arguments[key] for key in ("project_id", "request_id")}
    correlation.update(tool="fow_packet_author", operation="start_packet")
    assert response["status"] == "rejected"
    assert result["effect_state"] == "none" and result["operation_state"] == "rejected"
    assert result["effect_receipt"] == {"contract_version": "flow.operation-effect.v1", **correlation,
        "basis": "pre_effect_validation", "mutation_started": False}
    assert response["audit_reference"] == correlation
    diagnostic = result["diagnostics"][0]
    assert diagnostic["field"] == field
    assert all(diagnostic.get(key) for key in ("rule", "resolution", "message"))
    assert "received_value" in diagnostic
    assert result["next_tool_call"] == {"tool": "fow_capabilities", "arguments": {
        "view": "operation", "operation_tool": "fow_packet_author", "operation_name": "start_packet"}}


def assert_unknown(response):
    result = response["result"]
    assert result["effect_state"] == "unknown"
    assert "effect_receipt" not in result
    assert result["original_request"] == response["audit_reference"]
    assert result["next_tool_call"]["tool"] == "fow_handover"
    assert "private-exception" not in str(response)


@pytest.mark.parametrize("field,value,diagnostic", [
    ("change_id", "probe-nonexistent-000", "change_id"),
    ("project_id", "Bad Project", "project_id"), ("actor", "", "actor"),
    ("request_id", "", "request_id"), ("purpose", "unknown", "purpose"),
    ("title", "", "packet"), ("intent", "", "intent"),
    ("completion_criteria", [], "packet"), ("requirement_ids", "REQ-000001", "packet"),
])
def test_pure_validation_never_dispatches_or_changes_ledger(owned_runtime, monkeypatch, field, value, diagnostic):
    arguments = request(**{field: value})
    before = snapshot(owned_runtime)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid input reached service dispatch")
    monkeypatch.setattr(owned_runtime.packet_factory, "create_packet", forbidden)
    assert_none(handle_packet_author(owned_runtime, **arguments), arguments, diagnostic)
    assert snapshot(owned_runtime) == before


@pytest.mark.parametrize("field,value", [("change_id", "CHANGE-999999"), ("project_id", "absent-project")])
def test_exact_missing_scope_is_proven_before_creation(owned_runtime, monkeypatch, field, value):
    arguments = request(**{field: value})
    before = snapshot(owned_runtime)
    def forbidden(*args, **kwargs):
        pytest.fail("Missing scope reached creation")
    monkeypatch.setattr(owned_runtime.packet_factory, "create_packet", forbidden)
    assert_none(handle_packet_author(owned_runtime, **arguments), arguments, field)
    assert snapshot(owned_runtime) == before


def test_correlation_uses_original_supplied_identity(owned_runtime):
    arguments = request(project_id=" packet-effect ", request_id=" original-packet ", change_id="bad")
    assert_none(handle_packet_author(owned_runtime, **arguments), arguments, "change_id")


def test_corrected_creation_exact_replay_and_conflict_preserve_history(owned_runtime):
    arguments = request()
    assert_none(handle_packet_author(owned_runtime, **request(change_id="bad")), request(change_id="bad"), "change_id")
    created = handle_packet_author(owned_runtime, **arguments)
    assert created["status"] == "success"
    assert created["result"]["packet"]["packet_id"] == "PACKET-000001"
    before = snapshot(owned_runtime)
    replay = handle_packet_author(owned_runtime, **arguments)
    assert replay["result"]["packet"]["packet_id"] == "PACKET-000001"
    assert snapshot(owned_runtime) == before
    conflict = handle_packet_author(owned_runtime, **request(intent="Different work"))
    assert_unknown(conflict)
    assert snapshot(owned_runtime) == before
    # This invocation is none; it does not certify no earlier work under this ID.
    assert_none(handle_packet_author(owned_runtime, **request(change_id="bad")), request(change_id="bad"), "change_id")
    assert snapshot(owned_runtime) == before


@pytest.mark.parametrize("error", [ValueError("private-exception"), RequirementConflictError("private-exception"),
    ChangeNotFoundError("private-exception"), OperationPreEffectError("not-trusted-here", "private-exception",
        field="after_write", received_value=None, rule="Never trust late proof", resolution="Read state")])
def test_service_failures_cannot_claim_no_effect_even_with_rollback(owned_runtime, monkeypatch, error):
    original = owned_runtime.packet_factory.create_packet
    before = snapshot(owned_runtime)
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise error
    monkeypatch.setattr(owned_runtime.packet_factory, "create_packet", fail)
    assert_unknown(handle_packet_author(owned_runtime, **request()))
    assert snapshot(owned_runtime) == before  # rollback is not a pre-effect certificate


def test_queue_failure_and_commit_failure_remain_unknown(owned_runtime, monkeypatch):
    before = snapshot(owned_runtime)
    def fail(*args, **kwargs):
        raise RuntimeError("private-exception")
    with monkeypatch.context() as patch:
        patch.setattr(owned_runtime.packet_provider_overlay, "queue_plan_delta", fail)
        assert_unknown(handle_packet_author(owned_runtime, **request()))
    assert snapshot(owned_runtime) == before
    original = owned_runtime.ledger.atomic
    depth = 0
    @contextmanager
    def commit_then_fail():
        nonlocal depth
        is_outer = depth == 0
        depth += 1
        try:
            with original() as connection:
                yield connection
        finally:
            depth -= 1
        if is_outer:
            raise RuntimeError("private-exception")
    with monkeypatch.context() as patch:
        patch.setattr(owned_runtime.ledger, "atomic", commit_then_fail)
        assert_unknown(handle_packet_author(owned_runtime, **request()))
    assert len(owned_runtime.changes.get_change("packet-effect", "CHANGE-000001")["packets"]) == 1


def test_postcommit_continuation_failure_keeps_packet_and_unknown(owned_runtime, monkeypatch):
    import flow_of_work_mcp.server as server
    def fail(*args, **kwargs):
        raise OperationPreEffectError("not-trusted-here", "private-exception", field="output",
            received_value=None, rule="Output is not validation", resolution="Read state")
    monkeypatch.setattr(server, "_packet_author_continuation", fail)
    assert_unknown(handle_packet_author(owned_runtime, **request()))
    change = owned_runtime.changes.get_change("packet-effect", "CHANGE-000001")
    assert len(change["packets"]) == 1


def test_public_channels_and_lost_projection_do_not_invent_receipt(owned_runtime, monkeypatch):
    async def run():
        app = create_app(owned_runtime)
        tools = {item.name: item for item in await app.list_tools()}
        assert len(tools) == 37
        assert "change_id" in tools["fow_packet_author"].inputSchema["properties"]
        arguments = request(change_id="bad")
        response = await app.call_tool("fow_packet_author", arguments)
        assert_none(response.structuredContent["result"], arguments, "change_id")
        markdown = response.content[0].text
        for word in ("none", "pre_effect_validation", "original-packet", "change_id", "fow_capabilities"):
            assert word in markdown
        import flow_of_work_mcp.model_facing as projection
        def fail(*args, **kwargs):
            raise RuntimeError("projection-unavailable")
        monkeypatch.setattr(projection, "project_markdown", fail)
        with pytest.raises(Exception, match="projection-unavailable"):
            await app.call_tool("fow_packet_author", request())
    asyncio.run(run())
    assert len(owned_runtime.changes.get_change("packet-effect", "CHANGE-000001")["packets"]) == 1
