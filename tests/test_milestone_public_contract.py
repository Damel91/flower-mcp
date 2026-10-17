"""The public milestone instructions must describe executable planning semantics."""

import asyncio
import json

from flow_of_work_mcp.application.operation_contracts import (
    operation_contract,
    public_tool_names,
    tool_description,
)
from flow_of_work_mcp.core.domain.lifecycle_control import MilestoneDraft
from flow_of_work_mcp.server import create_app


def test_actual_mcp_schema_has_explicit_prerequisites_without_legacy_alias():
    class NoRuntimeAccess:
        def __getattribute__(self, name):
            raise AssertionError("metadata discovery accessed runtime: " + name)

    app = create_app(NoRuntimeAccess())
    tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}
    assert len(tools) == len(public_tool_names()) == 37
    schema = tools["fow_promote_milestone"].inputSchema
    assert "prerequisite_requirement_ids" in schema["required"]
    assert "dependency_closure_ids" not in schema["properties"]
    help_text = schema["properties"]["prerequisite_requirement_ids"]["description"]
    assert "earlier" in help_text and "disjoint" in help_text and "[]" in help_text
    assert "realized" in schema["properties"]["requirement_ids"]["description"]


def test_first_and_successor_examples_define_disjoint_executable_drafts():
    contract = operation_contract("fow_promote_milestone", "call")
    first = contract["example"]
    assert first["prerequisite_requirement_ids"] == []
    successor = contract["guidance"]["successor_example"]["arguments"]
    assert set(successor["requirement_ids"]).isdisjoint(
        successor["prerequisite_requirement_ids"]
    )
    for example in (first, successor):
        draft = MilestoneDraft(
            name=example["name"],
            requirement_ids=tuple(example["requirement_ids"]),
            prerequisite_requirement_ids=tuple(example["prerequisite_requirement_ids"]),
            entry_policy=example["entry_policy"],
            exit_policy=example["exit_policy"],
            risk_disposition=example["risk_disposition"],
        )
        assert draft.requirement_ids
    assert "dependency_closure_ids" not in json.dumps(contract)


def test_help_retains_effect_uncertainty_and_actual_acceptance_boundary():
    contract = operation_contract("fow_promote_milestone", "call")
    guidance = contract["guidance"]
    assert "timeout" in guidance["effect_receipt"]
    assert "not no-effect proof" in guidance["effect_receipt"]
    assert "initial evidence" in guidance["retry"]
    assert "milestone_request_replay_unverifiable" in guidance["retry"]
    assert "never accepts" in tool_description("fow_promote_milestone")
    assert "rejects nonempty" not in contract["field_descriptions"]["acceptance_evidence"]
