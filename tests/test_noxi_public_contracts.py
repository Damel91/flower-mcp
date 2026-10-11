"""Public Noxi discovery must preserve execution and semantic authority boundaries."""

from copy import deepcopy

from flow_of_work_mcp.core.domain.architecture import normalize_definition, normalize_link
from flow_of_work_mcp.application.lifecycle_recipes import get_recipe, recipe_names
from flow_of_work_mcp.application.operation_contracts import (
    operation_contract,
    operation_names,
    public_tool_catalog,
    public_tool_names,
)
from flow_of_work_mcp.model_facing import (
    assert_projector_registry,
    model_facing_tool,
    project_markdown,
)


def test_architecture_is_discoverable_as_ordinary_project_authority():
    descriptor = next(item for item in public_tool_catalog() if item["name"] == "fow_architecture")
    assert descriptor["area"] == "project_bootstrap"
    assert operation_names("fow_architecture") == ("inspect", "propose", "adopt")
    assert_projector_registry(public_tool_names())

    inspect = operation_contract("fow_architecture", "inspect")
    assert inspect["risk"] == "read"
    assert inspect["effect_class"] == "none"
    assert inspect["paging_owner"] == "ledger"
    assert "actor" not in inspect["required_fields"]
    assert inspect["example"]["payload"] == {"revision": 0, "kind": "all", "offset": 0, "limit": 20}
    assert inspect["accepted_values"]["payload.kind"] == ["all", "component", "interface", "decision", "history"]


def test_architecture_mutation_help_closes_revision_replay_and_definition_shape():
    proposal = operation_contract("fow_architecture", "propose")
    adoption = operation_contract("fow_architecture", "adopt")
    for contract in (proposal, adoption):
        assert contract["risk"] == "write"
        assert contract["effect_class"] == "ledger_mutation"
        assert {"actor", "request_id", "payload.expected_revision"} <= set(contract["required_fields"])
        assert "historical receipt" in contract["guidance"]["replay"]
        assert "not product acceptance" in contract["guidance"]["authority"]
    assert proposal["example"]["payload"]["expected_revision"] == 0
    definition = proposal["example"]["payload"]["definition"]
    normalized = normalize_definition(definition)
    assert len(normalized["interfaces"]) == len(normalized["decisions"]) == 1
    for link in proposal["guidance"]["links"]:
        assert normalize_link(link) == link
    assert set(definition) == {"components", "interfaces", "decisions"}
    assert set(definition["components"][0]) == {"id", "name", "responsibility", "boundaries", "invariants", "links"}
    assert adoption["example"]["payload"]["revision"] == 1
    assert adoption["example"]["payload"]["expected_revision"] == 0
    assert adoption["example"]["payload"]["rationale"]

    # A caller editing a proposed example must not alter future operation help.
    definition["components"][0]["responsibility"] = "mutated client copy"
    assert operation_contract("fow_architecture", "propose")["example"]["payload"]["definition"]["components"][0]["responsibility"] != "mutated client copy"


def test_executor_help_distinguishes_pure_reads_from_explicit_provider_probe():
    provider = operation_contract("fow_external_work", "provider_validation")
    assert provider["risk"] == "read" and provider["effect_class"] == "none"
    assert provider["accepted_values"]["payload.detail"] == ["standard", "full"]
    assert "actor" not in provider["required_fields"]
    assert "request_id" not in provider["required_fields"]
    assert provider["example"]["payload"] == {"detail": "full"}

    negotiate = operation_contract("fow_external_work", "negotiate_provider")
    assert negotiate["risk"] == "process"
    assert negotiate["effect_class"] == "provider_probe_and_ledger_mutation"
    assert {"actor", "request_id", "payload.expected_spec_revision", "payload.expected_plan_revision"} <= set(negotiate["required_fields"])
    assert "No ordinary read probes a provider" in negotiate["guidance"]["provider_negotiation"]


def test_executor_help_does_not_imply_transfer_or_provider_fallback():
    contract = operation_contract("fow_external_work", "select_executor")
    assert contract["risk"] == "write"
    assert contract["accepted_values"]["payload.executor"] == ["external_agent", "provider"]
    assert "payload.provider_kind" in contract["optional_fields"]
    assert contract["example"]["payload"]["executor"] == "external_agent"
    assert "provider_kind" not in contract["example"]["payload"]
    ownership = contract["guidance"]["execution_ownership"]
    assert "external_agent forbids provider_kind" in ownership
    assert "unselected legacy provider default is not explicit selection" in ownership
    assert "no timeout fallback or second writer" in ownership


def test_packet_authoring_help_exposes_ordinary_architecture_pins():
    for tool, operation in (
        ("fow_packet_author", "start_packet"),
        ("fow_packet_author", "revise_packet"),
        ("fow_change", "revise_packet"),
    ):
        contract = operation_contract(tool, operation)
        assert "architecture_refs" in contract["optional_fields"]
        shape = contract["guidance"]["architecture_refs"]["shape"]
        assert shape == [{"revision": 1, "kind": "decision", "entity_id": "loop-owner"}]
    guidance = operation_contract("fow_packet_author", "revise_packet")["guidance"]["architecture_refs"]["authority"]
    assert "Omission preserves" in guidance and "[] clears" in guidance


def test_architecture_model_channel_preserves_nested_multiline_authority():
    result = {
        "project_id": "isolated-project", "revision": 1, "state": "adopted",
        "definition": {
            "components": [{
                "id": "pi", "responsibility": "Own the loop.\nObserve execution before reporting cancellation.",
                "boundaries": ["Flower owns lifecycle authority.\nNoxi retains correlations."],
            }],
            "decisions": [{
                "id": "loop-owner", "statement": "Pi owns the loop.",
                "rationale": "Keep one execution owner.\nA timeout is not a transfer.",
                "links": [{"kind": "requirement", "requirement_id": "REQ-1", "statement": "Preserve the user's lifecycle authority."}],
            }],
        },
        "complete": True, "next_offset": None,
    }
    payload = {"status": "success", "result": result}
    untouched = deepcopy(payload)

    def handler(operation: str):
        return payload

    projected = model_facing_tool(handler, tool_name="fow_architecture")(operation="inspect")
    assert projected.structuredContent == {"result": untouched}
    assert payload == untouched
    markdown = projected.content[0].text
    assert "Flower Architecture: inspect" in markdown
    assert "Own the loop.\n  Observe execution before reporting cancellation." in markdown
    assert "Keep one execution owner.\n  A timeout is not a transfer." in markdown
    assert "Preserve the user's lifecycle authority." in markdown
    assert '| Responsibility |' not in markdown
    assert '"components"' not in markdown


def test_architecture_output_budget_reports_boundary_without_mutating_authority():
    payload = {"status": "success", "result": {"definition": {"decisions": [{"rationale": "x" * 5000}]}}}
    before = deepcopy(payload)
    markdown = project_markdown("fow_architecture", payload, arguments={"operation": "inspect"}, output_budget=1024)
    assert "model_facing_output_budget_exceeded" in markdown
    assert payload == before


def test_frozen_handover_preserves_architecture_and_provider_context_prose():
    payload = {
        "status": "success", "result": {"handover": {
            "handover_id": "HAND-1", "payload": {
                "architecture": {"decisions": [{
                    "statement": "Pi owns the loop.\nFlower owns lifecycle authority.",
                    "rationale": "Retain one canonical authority.",
                }]},
                "provider_validation": {
                    "authority_context": {"requirements": [{
                        "statement": "Preserve producer declarations.\nKeep deferred checks separate.",
                    }]},
                    "offline_boundary": "Provider ownership remains selected.\nNo external fallback is authorized.",
                },
            },
        }},
    }
    before = deepcopy(payload)
    markdown = project_markdown("fow_handover", payload, arguments={"operation": "get_handover"})
    assert "Pi owns the loop.\n  Flower owns lifecycle authority." in markdown
    assert "Preserve producer declarations.\n  Keep deferred checks separate." in markdown
    assert "Provider ownership remains selected.\n  No external fallback is authorized." in markdown
    assert '"architecture"' not in markdown
    assert payload == before


def test_current_handover_recognizes_provider_context_without_architecture():
    payload = {"status": "success", "result": {"resume_context": {
        "provider_validation": {"execution_admission": {
            "reason": "Capability support is stale.\nExplicit negotiation is required.",
        }},
    }}}
    markdown = project_markdown("fow_handover", payload, arguments={"operation": "resume_context"})
    assert "Capability support is stale.\n  Explicit negotiation is required." in markdown
    assert '| Reason |' not in markdown


def test_recipes_keep_standalone_and_negotiated_provider_boundaries_explicit():
    assert {"project-architecture-v1", "negotiated-provider-handoff-v1"} <= set(recipe_names())
    architecture = get_recipe("project-architecture-v1")
    provider = get_recipe("negotiated-provider-handoff-v1")
    standalone = get_recipe("standalone-external-plan")
    assert architecture and provider and standalone
    assert "not implementation evidence" in architecture["authority"]["boundary"]
    assert any("Pi owns the agent loop" in item for item in architecture["safety_notes"])
    assert "does not transfer an admitted run" in provider["authority"]["boundary"]
    assert any("provider_validation is a pure read" in item for item in provider["safety_notes"])
    assert any("deferred and never current coding tasks" in item for item in provider["safety_notes"])
    assert any("original" in item.lower() and "IMPL-67" in item and "deferred" in item for item in standalone["safety_notes"])
    assert any("After offline execution reconnect" in item for item in standalone["safety_notes"])
