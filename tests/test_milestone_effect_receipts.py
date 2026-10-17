"""Effect knowledge at the actual milestone validation/commit boundary."""

import asyncio
from collections.abc import Mapping
import sqlite3

import pytest

from flow_of_work_mcp.core.domain import RequirementDraft
from flow_of_work_mcp.core.errors import (
    InputValidationError, MilestonePreEffectError, ProjectNotFoundError, RequirementConflictError,
)
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import _guard, create_app, handle_promote_milestone


@pytest.fixture
def owned_runtime(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "owned.sqlite3", import_root=tmp_path)
    runtime.requirements.create_project("effect-test", "Owned effect test", actor="tester")
    requirement = runtime.requirements.register("effect-test", RequirementDraft(
        title="Observable work", statement="The software shall retain observable work.",
        category="functional", rationale="Owned regression state.",
    ), actor="tester")
    yield runtime, requirement["requirement_id"]
    runtime.close()


def request(requirement_id):
    return {
        "project_id": "effect-test", "name": "First milestone",
        "requirement_ids": [requirement_id], "prerequisite_requirement_ids": [],
        "entry_policy": {"intent": "Defined"}, "exit_policy": {"check": "Observable"},
        "risk_disposition": "bounded", "actor": "tester", "request_id": "original-request",
    }


def snapshot(runtime):
    # Deterministic invariant evidence includes all tables, events and sequences.
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


def assert_none(response, arguments):
    result = response["result"]
    correlation = {"tool": "fow_promote_milestone", "operation": "call",
                   "project_id": arguments["project_id"], "request_id": arguments["request_id"]}
    assert response["status"] == "rejected"
    assert result["operation_state"] == "rejected"
    assert result["effect_state"] == "none"
    assert result["effect_receipt"] == {
        "contract_version": "flow.operation-effect.v1", **correlation,
        "basis": "pre_effect_validation", "mutation_started": False,
    }
    assert response["audit_reference"] == correlation
    diagnostic = result["diagnostics"][0]
    assert diagnostic["effect_state"] == "none"
    assert all(diagnostic.get(field) for field in ("code", "message", "field", "rule", "resolution"))
    assert result["next_tool_call"]["tool"] in {"fow_capabilities", "fow_handover"}


@pytest.mark.parametrize("field,value", [
    ("actor", ""), ("actor", 12), ("project_id", "Bad Project"),
    ("requirement_ids", "REQ-000001"), ("requirement_ids", []),
    ("requirement_ids", ["not-a-requirement"]),
    ("prerequisite_requirement_ids", None), ("entry_policy", []), ("exit_policy", None),
    ("acceptance_evidence", {}), ("acceptance_evidence", [""]),
    ("name", ""), ("risk_disposition", ""),
])
def test_known_input_rejection_has_correlated_none_before_service(owned_runtime, monkeypatch, field, value):
    runtime, requirement_id = owned_runtime
    arguments = {**request(requirement_id), field: value}
    before = snapshot(runtime)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid draft dispatched a mutating service")
    monkeypatch.setattr(runtime.lifecycle, "promote_milestone", forbidden)
    response = handle_promote_milestone(runtime, **arguments)
    assert_none(response, arguments)
    assert snapshot(runtime) == before


@pytest.mark.parametrize("case", ["overlap", "duplicate", "unassigned", "missing", "missing_project"])
def test_known_ledger_rejection_consumes_no_rows_events_or_sequences(owned_runtime, case):
    runtime, requirement_id = owned_runtime
    arguments = request(requirement_id)
    if case == "overlap":
        arguments["prerequisite_requirement_ids"] = [requirement_id]
    elif case == "duplicate":
        arguments["requirement_ids"] = [requirement_id, requirement_id]
    elif case == "unassigned":
        extra = runtime.requirements.register("effect-test", RequirementDraft(
            title="Unassigned prerequisite", statement="The software shall expose a prerequisite.",
            category="functional", rationale="No producer milestone exists yet.",
        ), actor="tester")
        arguments["prerequisite_requirement_ids"] = [extra["requirement_id"]]
    elif case == "missing":
        arguments["requirement_ids"] = ["REQ-999999"]
    else:
        arguments["project_id"] = "absent-project"
    before = snapshot(runtime)
    assert_none(handle_promote_milestone(runtime, **arguments), arguments)
    assert snapshot(runtime) == before


def test_corrected_request_after_no_effect_allocates_once_and_replays_after_acceptance(owned_runtime):
    runtime, requirement_id = owned_runtime
    arguments = {**request(requirement_id), "acceptance_evidence": ["initial:reference"]}
    invalid = {**arguments, "prerequisite_requirement_ids": [requirement_id]}
    assert_none(handle_promote_milestone(runtime, **invalid), invalid)
    created = handle_promote_milestone(runtime, **arguments)
    assert created["status"] == "success"
    assert created["result"]["milestone_id"] == "MILE-000001"
    # Storage-level deterministic setup represents later governed evidence;
    # this test does not qualify the acceptance policy or assert human approval.
    runtime.ledger.accept_milestone("effect-test", "MILE-000001",
        acceptance_evidence=("later:acceptance",), actor="tester")
    before = snapshot(runtime)
    replay = handle_promote_milestone(runtime, **arguments)
    assert replay["status"] == "success"
    assert replay["result"]["milestone_id"] == "MILE-000001"
    changed = {**arguments, "acceptance_evidence": ["different:initial"]}
    conflict = handle_promote_milestone(runtime, **changed)
    assert_none(conflict, changed)
    assert conflict["reason"] == "milestone_request_conflict"
    assert snapshot(runtime) == before


@pytest.mark.parametrize("error", [ValueError("private-token-never-return"),
    InputValidationError("private-token-never-return", field="secret", received_value="private-token-never-return"),
    RequirementConflictError("private-token-never-return"), RuntimeError("private-token-never-return")])
@pytest.mark.parametrize("commit_first", [False, True])
def test_unexpected_service_failure_never_certifies_none_or_exposes_exception(owned_runtime, monkeypatch, error, commit_first):
    runtime, requirement_id = owned_runtime
    original = runtime.lifecycle.promote_milestone
    def uncertain(*args, **kwargs):
        if commit_first:
            original(*args, **kwargs)
        raise error
    monkeypatch.setattr(runtime.lifecycle, "promote_milestone", uncertain)
    arguments = request(requirement_id)
    response = handle_promote_milestone(runtime, **arguments)
    assert response["status"] == "failed"
    assert response["result"]["effect_state"] == "unknown"
    assert "effect_receipt" not in response["result"]
    assert "private-token-never-return" not in str(response)
    assert response["result"]["original_request"] == response["audit_reference"]
    assert response["result"]["next_tool_call"] == {"tool": "fow_handover", "arguments": {
        "project_id": "effect-test", "operation": "project_state_snapshot"}}
    assert len(runtime.ledger.milestones("effect-test")) == int(commit_first)


def test_mcp_receipt_has_readable_markdown_correlation_and_no_legacy_input(owned_runtime):
    runtime, requirement_id = owned_runtime
    async def run():
        app = create_app(runtime)
        catalog = {tool.name: tool for tool in await app.list_tools()}
        assert len(catalog) == 37
        schema = catalog["fow_promote_milestone"].inputSchema
        assert "prerequisite_requirement_ids" in schema["required"]
        assert "dependency_closure_ids" not in schema["properties"]
        arguments = {**request(requirement_id), "prerequisite_requirement_ids": [requirement_id]}
        receipt = await app.call_tool("fow_promote_milestone", arguments)
        envelope = receipt.structuredContent["result"]
        assert_none(envelope, arguments)
        markdown = receipt.content[0].text
        for value in ("none", "original-request", "pre_effect_validation", "prerequisite_requirement_ids", "fow_capabilities"):
            assert value in markdown
        assert "## Continue" in markdown and '"operation_name": "call"' in markdown
    asyncio.run(run())


def test_render_failure_after_commit_remains_unqualified(owned_runtime, monkeypatch):
    runtime, requirement_id = owned_runtime
    import flow_of_work_mcp.model_facing as projection
    def fail_projection(*args, **kwargs):
        raise RuntimeError("projection-unavailable")
    monkeypatch.setattr(projection, "project_markdown", fail_projection)
    async def run():
        app = create_app(runtime)
        with pytest.raises(Exception, match="projection-unavailable"):
            await app.call_tool("fow_promote_milestone", request(requirement_id))
    asyncio.run(run())
    assert len(runtime.ledger.milestones("effect-test")) == 1


def test_output_failure_cannot_reuse_a_pre_effect_error_type(owned_runtime, monkeypatch):
    runtime, requirement_id = owned_runtime
    original = runtime.lifecycle.promote_milestone
    class InvalidOutput(Mapping):
        def __getitem__(self, key):
            raise KeyError(key)
        def __len__(self):
            return 1
        def __iter__(self):
            raise MilestonePreEffectError("validation_shaped_output_failure", "Not pre-effect here.",
                field="output", received_value=None, rule="Output must be readable.", resolution="Inspect state.")
    def invalid_output(*args, **kwargs):
        original(*args, **kwargs)
        return InvalidOutput()
    monkeypatch.setattr(runtime.lifecycle, "promote_milestone", invalid_output)
    response = handle_promote_milestone(runtime, **request(requirement_id))
    assert response["result"]["effect_state"] == "unknown"
    assert "effect_receipt" not in response["result"]
    assert len(runtime.ledger.milestones("effect-test")) == 1


def test_generic_guard_preserves_typed_diagnostic_and_explicit_recovery():
    diagnostic = InputValidationError("Known input rule", field="path", received_value="bad",
                                    accepted_values=("good",))
    def invalid():
        raise diagnostic
    recovery = {"next_tool_call": {"tool": "fow_traceability", "arguments": {"project_id": "owned"}}}
    result = _guard("fow_bootstrap", invalid, recovery=lambda: recovery)["result"]
    assert result["diagnostics"] == [{"code": "invalid_input", "message": "Known input rule",
        "field": "path", "received_value": "bad", "accepted_values": ["good"],
        "effect_state": "unknown", "resolution": result["recovery_guidance"]["resolution"]}]
    assert result["effect_state"] == "unknown"
    assert result["next_tool_call"] == recovery["next_tool_call"]
    assert "before retrying" in result["recovery_guidance"]["resolution"]


def test_unaudited_diagnostic_and_recovery_cannot_inject_no_effect_proof():
    diagnostic = InputValidationError("Known correction", field="path", received_value="bad",
        details={"effect_state": "none", "operation_state": "rejected",
                 "resolution": "Nothing changed; retry mutation.",
                 "effect_receipt": {"basis": "not-a-proof"}})
    def invalid():
        raise diagnostic
    result = _guard("fow_bootstrap", invalid, recovery=lambda: {
        "operation_state": "rejected", "effect_state": "none",
        "effect_receipt": {"basis": "not-a-proof"},
        "next_tool_call": {"tool": "fow_bootstrap", "arguments": {
            "operation": "start", "project_id": "owned", "actor": "agent"}},
    })["result"]
    assert result["operation_state"] == result["effect_state"] == "unknown"
    assert "effect_receipt" not in result
    assert result["diagnostics"][0]["effect_state"] == "unknown"
    assert result["diagnostics"][0]["operation_state"] == "unknown"
    assert "effect_receipt" not in result["diagnostics"][0]
    assert "before retrying" in result["diagnostics"][0]["resolution"]
    assert "Nothing changed" not in result["diagnostics"][0]["resolution"]
    assert result["diagnostics"][0]["input_guidance_is_effect_evidence"] is False
    assert result["next_tool_call"]["tool"] == "fow_capabilities"


@pytest.mark.parametrize("error", [ProjectNotFoundError(), RequirementConflictError()])
def test_early_generic_guard_failures_are_constructive_and_uncertain(error):
    def fail():
        raise error
    result = _guard("fow_register_requirement", fail)["result"]
    assert result["effect_state"] == "unknown"
    assert result["diagnostics"][0]["message"]
    assert result["diagnostics"][0]["resolution"]
    assert result["next_tool_call"] == {"tool": "fow_capabilities", "arguments": {
        "view": "operation", "operation_tool": "fow_register_requirement", "operation_name": "call"}}


@pytest.mark.parametrize("value", ["x" * 100_000, [[[["x" * 100_000]]]] * 1_000,
                                   float("nan"), {"secret": "x" * 100_000}])
def test_generic_guard_bounds_problem_value_after_details_merge(value):
    import json
    diagnostic = InputValidationError("Known rule", field="input", received_value="original",
                                      details={"received_value": value})
    def invalid():
        raise diagnostic
    result = _guard("fow_bootstrap", invalid)["result"]
    encoded = json.dumps(result["diagnostics"][0]["received_value"], allow_nan=False)
    assert len(encoded) < 2_000
    assert "secret" not in encoded


def test_bounded_generic_list_keeps_problematic_items_for_correction():
    def invalid():
        raise InputValidationError("Use a canonical identity", field="requirements",
                                   received_value=["bad-id", "REQ-000001"])
    value = _guard("fow_bootstrap", invalid)["result"]["diagnostics"][0]["received_value"]
    assert value == {"items": ["bad-id", "REQ-000001"], "count": 2, "truncated": False}


def test_error_guidance_preserves_physical_multiline_markdown():
    resolution = "Inspect the original request.\nCompare current durable state.\nDo not blindly retry."
    markdown = project_markdown("fow_promote_milestone", {
        "status": "failed", "reason": "operation_effect_unknown",
        "result": {"effect_state": "unknown", "diagnostics": [{"code": "operation_effect_unknown",
            "resolution": resolution}]},
    })
    assert resolution in markdown
    assert "Inspect the original request. / Compare" not in markdown
