"""Known external-work conflicts preserve authority and public read recovery."""

import asyncio
import json
import re
import sqlite3

import pytest

from flow_of_work_mcp import (
    ChangeControlService,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    RequirementDraft,
    RequirementService,
    SQLiteRequirementLedger,
)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.lifecycle_recipes import get_recipe
from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.core.errors import RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app
from tests.test_external_work import fixture


def _rows(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return tuple(connection.iterdump())
    finally:
        connection.close()


def _arguments(ids, revisions, *, request_id="repeat-upgrade"):
    return {
        "project_id": ids[0], "change_id": ids[1], "packet_id": ids[2],
        "operation": "upgrade_validation", "actor": "host",
        "request_id": request_id, "payload": dict(revisions),
    }


def _public(runtime, tool, arguments):
    return asyncio.run(create_app(runtime).call_tool(tool, arguments))


def _current_revisions(ledger, ids):
    change = ledger.change_state(ids[0], ids[1])
    packet = next(item for item in change["packets"] if item["packet_id"] == ids[2])
    plan = ledger.packet_work_plan_state(*ids)
    return {
        "expected_spec_revision": packet["spec_revision"],
        "expected_plan_revision": (plan or {}).get("plan_revision", 0),
    }


def test_initial_upgrade_and_exact_replay_create_one_stable_criterion_history(tmp_path):
    path = tmp_path / "flower.sqlite"
    ledger = SQLiteRequirementLedger(path)
    requirements = RequirementService(ledger)
    requirements.create_project("alpha", "Upgrade trial", actor="human")
    requirement = requirements.register("alpha", RequirementDraft(
        title="Stable criterion identity", statement="The software shall preserve stable criterion identity.",
        category="functional", rationale="The upgrade must be explicit.",
    ), actor="human")
    changes = ChangeControlService(ledger)
    change = changes.create_change(
        "alpha", GovernedChangeDraft(title="One upgrade", rationale="Record stable identities.",
                                     requirement_ids=(requirement["requirement_id"],)), actor="human"
    )
    packet = changes.add_packet(
        "alpha", change["change_id"],
        ImplementationPacketDraft(
            title="Two criteria", objective="Preserve criterion identity.", rationale="Bounded upgrade.",
            completion_criteria=("First criterion", "Second criterion"),
        ), actor="human",
    )["packets"][0]
    ids = ("alpha", change["change_id"], packet["packet_id"])
    service = ExternalWorkService(ledger)
    revisions = {"expected_spec_revision": packet["spec_revision"], "expected_plan_revision": 0}
    first = service.call(*ids, "upgrade_validation", actor="host", request_id="initial", payload=revisions)
    assert first["validation_version"] == 1
    assert [item["number"] for item in first["criteria"]] == [1, 2]
    assert len(ledger.external_work_state(*ids)["criterion_history"]) == 2
    before = _rows(path)
    assert service.call(*ids, "upgrade_validation", actor="host", request_id="initial", payload=revisions) == first
    assert _rows(path) == before


def test_known_repeat_is_rejected_with_exact_public_read_recovery_and_no_writes(tmp_path):
    path = tmp_path / "flower.sqlite"
    ledger, _service, ids, revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=path, import_root=tmp_path, ledger=ledger)
    try:
        before = _rows(path)
        response = _public(runtime, "fow_external_work", _arguments(ids, revisions))
        assert not response.isError
        envelope = response.structuredContent["result"]
        assert envelope["status"] == "rejected"
        assert envelope["reason"] == "packet_validation_already_upgraded"
        details = envelope["result"]
        assert details["operation"] == "upgrade_validation"
        assert (details["project_id"], details["change_id"], details["packet_id"]) == ids
        assert details["validation_version"] == 1
        assert details["current_authority"] == revisions
        assert details["criterion_authority_stale"] is False
        assert details["next_tool_call"] == {
            "tool": "fow_external_work",
            "arguments": {"project_id": ids[0], "change_id": ids[1], "packet_id": ids[2],
                          "operation": "validation", "payload": {"detail": "full"}},
        }
        assert details["recovery_calls"]["criteria"] == {
            "tool": "fow_external_work",
            "arguments": {"project_id": ids[0], "change_id": ids[1], "packet_id": ids[2], "operation": "criteria"},
        }
        assert "reconcile_criteria_help" not in details["recovery_calls"]
        markdown = response.content[0].text
        assert "packet_validation_already_upgraded" in markdown
        json_blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", markdown, re.S)]
        assert details["next_tool_call"] in json_blocks
        assert details["recovery_calls"] in json_blocks
        for route in [details["next_tool_call"], *details["recovery_calls"].values()]:
            recovered = _public(runtime, route["tool"], route["arguments"])
            assert not recovered.isError
        assert _rows(path) == before
    finally:
        runtime.close()


@pytest.mark.parametrize("criterion_drift", [False, True])
def test_reconciliation_help_requires_actual_criterion_drift(tmp_path, criterion_drift):
    path = tmp_path / "flower.sqlite"
    ledger, service, ids, _revisions = fixture(tmp_path)
    patch = ({"completion_criteria": ("Changed producer criterion", "consumer calls increment")}
             if criterion_drift else {"invariants": ("A different implementation invariant.",)})
    ChangeControlService(ledger).refine_packet(*ids, actor="engineer", **patch)
    revisions = _current_revisions(ledger, ids)
    before = _rows(path)
    with pytest.raises(RequirementConflictError) as caught:
        service.call(*ids, "upgrade_validation", actor="host", request_id="new-upgrade", payload=revisions)
    error = caught.value
    assert type(error).__name__ == "PacketValidationAlreadyUpgradedError"
    assert error.reason == "packet_validation_already_upgraded"
    assert error.details["current_authority"] == revisions
    assert error.details["criterion_authority_stale"] is criterion_drift
    calls = error.details["recovery_calls"]
    assert ("reconcile_criteria_help" in calls) is criterion_drift
    if criterion_drift:
        assert calls["reconcile_criteria_help"] == {
            "tool": "fow_capabilities", "arguments": {
                "view": "operation", "operation_tool": "fow_external_work", "operation_name": "reconcile_criteria",
            },
        }
    assert all(route["tool"] == "fow_capabilities" or route["arguments"]["operation"] in {"validation", "criteria"}
               for route in calls.values())
    assert _rows(path) == before


def test_original_upgrade_replays_historical_result_after_revision_drift_and_restart(tmp_path):
    path = tmp_path / "flower.sqlite"
    ledger, service, ids, revisions = fixture(tmp_path)
    original_payload = {"expected_spec_revision": 1, "expected_plan_revision": 0}
    original = service.call(*ids, "upgrade_validation", actor="human", request_id="upgrade", payload=original_payload)
    service.call(*ids, "edit_criterion", actor="engineer", request_id="criterion-edit", payload={
        "expected_spec_revision": revisions["expected_spec_revision"], "number": 1,
        "statement": "A revised criterion retains identity one.",
    })
    assert ledger.external_work_state(*ids)["criteria"][0]["statement"] != original["criteria"][0]["statement"]
    before = _rows(path)
    reopened = SQLiteRequirementLedger(path)
    resumed = ExternalWorkService(reopened)
    assert resumed.call(*ids, "upgrade_validation", actor="human", request_id="upgrade", payload=original_payload) == original
    assert _rows(path) == before


@pytest.mark.parametrize("changed", ["actor", "payload", "operation"])
def test_changed_original_request_stays_generic_conflict_without_writes(tmp_path, changed):
    path = tmp_path / "flower.sqlite"
    ledger, service, ids, _revisions = fixture(tmp_path)
    arguments = {"actor": "human", "request_id": "upgrade", "payload": {
        "expected_spec_revision": 1, "expected_plan_revision": 0,
    }}
    operation = "upgrade_validation"
    if changed == "actor":
        arguments["actor"] = "different-host"
    elif changed == "payload":
        arguments["payload"]["expected_spec_revision"] = 99
    else:
        operation = "export_plan"
    before = _rows(path)
    with pytest.raises(RequirementConflictError, match="external_work_request_conflict") as caught:
        service.call(*ids, operation, **arguments)
    assert type(caught.value) is RequirementConflictError
    assert _rows(path) == before


@pytest.mark.parametrize("revision_field,reason", [
    ("expected_spec_revision", "stale_packet_revision"),
    ("expected_plan_revision", "stale_work_plan_revision"),
])
def test_fresh_stale_request_precedes_already_upgraded_and_remains_blocked(tmp_path, revision_field, reason):
    path = tmp_path / "flower.sqlite"
    ledger, _service, ids, revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=path, import_root=tmp_path, ledger=ledger)
    try:
        stale = {**revisions, revision_field: revisions[revision_field] + 1}
        before = _rows(path)
        response = _public(runtime, "fow_external_work", _arguments(ids, stale))
        envelope = response.structuredContent["result"]
        assert envelope["status"] == "blocked"
        assert envelope["reason"] == reason
        assert "packet_validation_already_upgraded" not in response.content[0].text
        assert _rows(path) == before
    finally:
        runtime.close()


def test_unrelated_sensitive_conflict_remains_generic_in_both_public_channels(tmp_path, monkeypatch):
    path = tmp_path / "flower.sqlite"
    ledger, _service, ids, revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=path, import_root=tmp_path, ledger=ledger)
    secret = "private-path-and-credential-sentinel"
    def fail(*args, **kwargs):
        raise RequirementConflictError(secret)
    monkeypatch.setattr(runtime.external_work, "call", fail)
    try:
        before = _rows(path)
        response = _public(runtime, "fow_external_work", _arguments(ids, revisions))
        envelope = response.structuredContent["result"]
        assert envelope["status"] == "rejected"
        assert envelope["reason"] == "state_conflict"
        assert envelope["result"] == {}
        assert secret not in json.dumps(response.structuredContent)
        assert secret not in response.content[0].text
        assert _rows(path) == before
    finally:
        runtime.close()


@pytest.mark.parametrize("missing", ["actor", "request_id"])
def test_export_without_durable_identity_creates_no_artifact_or_receipt(tmp_path, missing):
    path = tmp_path / "flower.sqlite"
    ledger, _service, ids, revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=path, import_root=tmp_path, ledger=ledger)
    try:
        arguments = _arguments(ids, revisions, request_id="missing-export-identity")
        arguments["operation"] = "export_plan"
        arguments.pop(missing)
        before = _rows(path)
        response = _public(runtime, "fow_external_work", arguments)
        envelope = response.structuredContent["result"]
        assert envelope["status"] == "rejected"
        assert envelope["reason"] == "invalid_input"
        assert missing in envelope["result"]["diagnostics"][0]["message"]
        assert _rows(path) == before
    finally:
        runtime.close()


def test_export_help_explains_durable_identity_while_aggregate_schema_keeps_reads_optional(tmp_path):
    path = tmp_path / "flower.sqlite"
    ledger, _service, _ids, _revisions = fixture(tmp_path)
    runtime = build_runtime(database_path=path, import_root=tmp_path, ledger=ledger)
    try:
        app = create_app(runtime)
        tool = next(item for item in asyncio.run(app.list_tools()) if item.name == "fow_external_work")
        assert "actor" not in tool.inputSchema["required"]
        assert "request_id" not in tool.inputSchema["required"]
        before = _rows(path)
        response = _public(runtime, "fow_capabilities", {
            "view": "operation", "operation_tool": "fow_external_work", "operation_name": "export_plan",
        })
        contract = response.structuredContent["result"]["result"]["operation_contract"]
        assert {"actor", "request_id"} <= set(contract["required_fields"])
        guidance = " ".join(str(value) for value in contract["guidance"].values()).lower()
        for phrase in ("immutable artifact generation", "durable receipt", "actor", "request_id", "same request_id", "conflict"):
            assert phrase in guidance
            assert phrase in response.content[0].text.lower()
        recipe = " ".join(get_recipe("standalone-external-plan")["safety_notes"]).lower()
        for phrase in ("immutable artifact generation", "durable receipt", "actor", "request_id", "conflict"):
            assert phrase in recipe
        for operation in ("criteria", "validation", "provider_validation", "todo"):
            read = operation_contract("fow_external_work", operation)
            assert "actor" not in read["required_fields"]
            assert "request_id" in read["optional_fields"]
        assert _rows(path) == before
    finally:
        runtime.close()
