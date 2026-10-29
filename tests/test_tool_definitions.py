"""Installed-wheel-safe metadata and actual SDK input-compatibility oracles."""

import asyncio
from copy import deepcopy
import inspect
import json

from mcp.server.fastmcp.tools import Tool
from pydantic import ValidationError
import pytest

from flow_of_work_mcp.application import operation_contracts as registry
from flow_of_work_mcp.application.tool_help import (
    FIELD_HELP, FIELD_OVERRIDES, TOOL_EFFECTS, TOOL_GUIDANCE,
)
from flow_of_work_mcp.model_facing import model_facing_tool
from flow_of_work_mcp.server import (
    _optional_source_anchor, _packet_evidence_claim_from_payload, create_app,
)


@pytest.fixture(scope="module")
def app():
    class NoRuntimeAccess:
        def __getattribute__(self, name):
            raise AssertionError("catalog discovery touched runtime: " + name)

    return create_app(NoRuntimeAccess())


@pytest.fixture(scope="module")
def tools(app):
    # Inspect FastMCP's actual registration, not a second schema generator.
    return {tool.name: tool for tool in app._tool_manager.list_tools()}


def _without_help(value):
    if isinstance(value, dict):
        return {key: _without_help(item) for key, item in value.items()
                if key not in {"description", "examples"}}
    if isinstance(value, list):
        return [_without_help(item) for item in value]
    return value


def _validation(model, value):
    try:
        return ("accepted", model.model_validate(value).model_dump())
    except ValidationError as error:
        return ("rejected", error.errors(include_url=False))


def test_actual_catalog_has_explicit_complete_bounded_help(app, tools):
    catalog = [item.model_dump(exclude_none=True, by_alias=True)
               for item in asyncio.run(app.list_tools())]
    assert len(catalog) == len(tools) == 37
    fields = [name for item in catalog for name in item["inputSchema"]["properties"]]
    assert len(fields) == 447
    assert set(fields) == set(FIELD_HELP) and len(FIELD_HELP) == 234
    assert set(TOOL_GUIDANCE) == set(TOOL_EFFECTS) == set(tools)
    for item in catalog:
        assert item["description"] == registry.tool_description(item["name"])
        assert "Prerequisites:" in item["description"]
        assert "Effects:" in item["description"] and "Exact help" in item["description"]
        assert item["annotations"] == registry.tool_annotations(item["name"])
        for name, schema in item["inputSchema"]["properties"].items():
            help_text = registry.parameter_help(item["name"], name)
            assert schema["description"] == help_text["description"]
            assert len(schema["description"]) >= 35
    encoded = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= 200_000


def test_missing_semantic_definition_fails_without_name_fallback():
    with pytest.raises(KeyError):
        registry.parameter_help("fow_architecture", "invented_parameter")
    with pytest.raises(TypeError):
        FIELD_HELP["project_id"] = "changed"
    with pytest.raises(TypeError):
        TOOL_EFFECTS["fow_capabilities"] = (False, False, False, False)
    assert registry.tool_description(" fow_capabilities ") == registry.tool_description("fow_capabilities")


def test_published_signature_and_schema_keep_raw_handler_validation(tools):
    contracts = registry.operation_contract_catalog()
    assert len(contracts) == 183
    checked_routes = set()
    for name, tool in tools.items():
        raw = tool.fn.__wrapped__
        unwrapped = Tool.from_function(raw, name=name)
        assert _without_help(tool.parameters) == _without_help(unwrapped.parameters)
        raw_signature = inspect.signature(raw)
        published = inspect.signature(tool.fn)
        assert tuple(raw_signature.parameters) == tuple(published.parameters)
        for key, parameter in raw_signature.parameters.items():
            assert published.parameters[key].default == parameter.default
            assert published.parameters[key].kind == parameter.kind
        inputs = [{}, {"project_id": "  project  ", "operation": " INSPECT "}]
        for contract in contracts:
            if contract["tool"] == name:
                inputs.append(deepcopy(contract["example"]))
                checked_routes.add((name, contract["operation"]))
        for value in inputs:
            assert _validation(tool.fn_metadata.arg_model, value) == _validation(
                unwrapped.fn_metadata.arg_model, value
            ), (name, value)
    assert len(checked_routes) == 183


def test_selector_help_does_not_add_constraints_to_permissive_strings(tools):
    for name in ("fow_bootstrap", "fow_goal", "fow_change"):
        schema = tools[name].parameters["properties"]["operation"]
        assert schema["type"] == "string" and "enum" not in schema
        assert " INSPECT " == tools[name].fn_metadata.arg_model.model_validate({
            "project_id": "project", "operation": " INSPECT ", "actor": "engineer",
        }).operation
    # Existing Literal validation remains authoritative and still rejects it.
    with pytest.raises(ValidationError):
        tools["fow_architecture"].fn_metadata.arg_model.model_validate({
            "project_id": "project", "operation": " INSPECT ",
        })


def test_routing_is_derived_from_real_selectors_and_exact_help():
    for name in registry.public_tool_names():
        for operation in registry.operation_names(name):
            contract = registry.operation_contract(name, operation)
            example = contract["example"]
            description = registry.tool_description(name)
            assert operation in description or operation == "call"
            if name in {"fow_packet_inspect", "fow_campaign_inspect"}:
                assert example["view"] == operation
                assert operation in registry.parameter_help(name, "view")["description"]
            elif name == "fow_packet_advance":
                assert "change_id" in contract["optional_fields"]
                if operation != "advance":
                    assert example["decision"]["operation"] == operation
                assert "decision.operation" in description
            elif "operation" in example:
                assert example["operation"] == operation
                assert operation in registry.parameter_help(name, "operation")["description"]
            assert contract["field_descriptions"]


def test_required_selector_and_inspect_examples_are_actionable():
    for name in ("fow_bindings", "fow_semantic"):
        for operation in registry.operation_names(name):
            contract = registry.operation_contract(name, operation)
            assert "operation" in contract["required_fields"]
            assert contract["example"]["operation"] == operation
    for name in ("fow_packet_inspect", "fow_campaign_inspect"):
        for operation in registry.operation_names(name):
            assert registry.operation_contract(name, operation)["example"]["view"] == operation
    assert "change_id" in registry.operation_contract(
        "fow_packet_inspect", "summary"
    )["optional_fields"]


def test_all_canonical_examples_match_unchanged_sdk_input_shapes(tools):
    contracts = registry.operation_contract_catalog()
    assert len(contracts) == 183
    for contract in contracts:
        tool = tools[contract["tool"]]
        # This checks shape/selector compatibility only. Example identities and
        # evidence references are explicit placeholders, never authority claims.
        parsed = tool.fn_metadata.arg_model.model_validate(contract["example"])
        assert parsed is not None, (contract["tool"], contract["operation"])
    answers = registry.operation_contract("fow_packet_author", "resolve_questions")["example"]["answers"]
    assert isinstance(answers[0], dict)
    assert answers[0]["question_id"].startswith("replace-with-")
    response = registry.operation_contract("fow_packet_author", "answer_gate")["example"]["response"]
    assert isinstance(response, dict) and response["disposition"] == "answered"
    assert "current gate" in response["answer_summary"]
    snapshot = registry.operation_contract("fow_change", "import_packet_evidence_snapshot")["example"]
    claim = _packet_evidence_claim_from_payload(snapshot["claims"][0])
    assert claim.claim_type.value == "target"
    assert claim.claim_key.startswith("replace-with-")
    milestone = registry.operation_contract("fow_promote_milestone", "call")["example"]
    assert milestone["entry_policy"]["requires_milestone"] == []
    assert milestone["prerequisite_requirement_ids"] == []
    assert milestone["exit_policy"]["verification"].startswith("Replace with")


def test_actual_change_compatibility_aliases_are_discoverable_and_truthful():
    aliases = {"navigation_audit_id", "candidate_set_id", "context_snapshot_id"}
    for operation in ("revise_packet", "set_packet_target_state"):
        optional = registry.operation_contract("fow_change", operation)["optional_fields"]
        assert aliases | {"active_provider"} <= set(optional)
    assert "provider" in registry.operation_contract(
        "fow_change", "import_packet_evidence_snapshot"
    )["optional_fields"]
    assert "does not consume" in registry.parameter_help(
        "fow_change", "active_provider"
    )["description"]
    assert "not a structured object" in registry.parameter_help(
        "fow_register_requirement", "source_anchor"
    )["description"]
    assert "mapping" in registry.parameter_help("fow_goal", "source_anchor")["description"]


def test_mixed_tool_effects_are_conservative(tools):
    inert = {"fow_capabilities", "fow_get_requirement", "fow_traceability", "fow_what_next",
             "fow_get_artifacts", "fow_get_job", "fow_list_jobs", "fow_packet_inspect",
             "fow_campaign_inspect"}
    assert {name for name, tool in tools.items() if tool.annotations.readOnlyHint} == inert
    for name in inert:
        hints = tools[name].annotations
        assert hints.idempotentHint and not hints.destructiveHint and not hints.openWorldHint
    for name in {"fow_architecture", "fow_bindings", "fow_external_work", "fow_packet_author",
                 "fow_packet_advance", "fow_campaign_author", "fow_change", "fow_run"}:
        assert tools[name].annotations.destructiveHint
        assert not tools[name].annotations.readOnlyHint
        assert not tools[name].annotations.idempotentHint
    for name in {"fow_semantic", "fow_validate_srs", "fow_import_srs", "fow_revise_srs_baseline",
                 "fow_ground_intent", "fow_interaction", "fow_external_work"}:
        assert tools[name].annotations.openWorldHint
    assert not tools["fow_bindings"].annotations.openWorldHint
    assert not tools["fow_generate_artifacts"].annotations.openWorldHint
    assert not tools["fow_semantic"].annotations.destructiveHint
    assert not tools["fow_audit_phase"].annotations.openWorldHint


def test_structured_multiplexer_help_preserves_nested_contract_guidance():
    for name in ("fow_architecture", "fow_external_work"):
        help_text = registry.parameter_help(name, "payload")
        assert "operation_name=<selected route>" in help_text["description"]
        assert isinstance(help_text["examples"][0], dict)
    report = registry.operation_contract("fow_external_work", "report_outcome")
    assert report["guidance"]["report_schema"]["verification"][0]["provenance"] == "host-reported"
    assert report["guidance"]["verification_identity"]
    semantic = registry.operation_contract("fow_semantic", "submit")
    assert semantic["example"]["result"] == {"findings": []}
    assert "Submit validates only" in semantic["guidance"]["adoption"]


def test_metadata_participates_in_existing_registry_fingerprint(monkeypatch):
    registry.registry_version.cache_clear()
    before = registry.registry_version()
    changed = dict(FIELD_HELP)
    changed["project_id"] += " Changed semantic help."
    with monkeypatch.context() as patch:
        patch.setattr(registry, "FIELD_HELP", changed)
        registry.registry_version.cache_clear()
        assert registry.registry_version() != before
    registry.registry_version.cache_clear()
    assert registry.registry_version() == before


def test_metadata_enrichment_keeps_result_envelope_multiline_and_call_arguments():
    calls = []
    payload = {"tool": "fow_architecture", "status": "success", "result": {
        "note": "First line\nSecond line", "revision": 1,
    }}

    def handler(operation: str, payload: dict | None = None):
        calls.append((operation, payload))
        return deepcopy(response)

    response = deepcopy(payload)
    wrapped = model_facing_tool(handler, tool_name="fow_architecture")
    result = wrapped(operation="inspect", payload={"kind": "all"})
    assert calls == [("inspect", {"kind": "all"})]
    assert result.structuredContent == {"result": response}
    assert result.isError is False
    assert "First line\n  Second line" in result.content[0].text
    assert response == payload


def test_immutable_context_overrides_only_target_real_fields(tools):
    for name, field in FIELD_OVERRIDES:
        assert name in tools and field in tools[name].parameters["properties"]


def test_source_anchor_help_matches_distinct_existing_input_shapes(tools):
    for name in ("fow_register_requirement", "fow_revise_requirement", "fow_assurance"):
        assert tools[name].parameters["properties"]["source_anchor"]["type"] == "string"
    schema = tools["fow_goal"].parameters["properties"]["source_anchor"]
    assert {item["type"] for item in schema["anyOf"]} == {"object", "null"}
    example = {"source_path": "requirements.md", "line_start": 2, "line_end": 4, "label": "scenario"}
    anchor = _optional_source_anchor(example)
    assert (anchor.source_path, anchor.line_start, anchor.line_end, anchor.label) == (
        "requirements.md", 2, 4, "scenario",
    )
    with pytest.raises(ValueError, match="line_start and line_end"):
        _optional_source_anchor({"source_path": "requirements.md", "section_id": "scenario"})
    assert "SERVER filesystem" in registry.parameter_help("fow_validate_srs", "source_path")["description"]
