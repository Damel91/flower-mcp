"""IMPL-45.7: registry-backed guidance and semantic recipe cutover."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from flow_of_work_mcp.application.lifecycle_recipes import all_recipes
from flow_of_work_mcp.application.operation_contracts import (
    operation_contract,
    operation_contract_index,
    operation_descriptors_for_area,
    public_tool_catalog,
    public_tool_names,
    registry_version,
    work_area_catalog,
)
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app, handle_capabilities
from tests.probes.loip_surface_probe import FIXTURE_PATH, build_inventory


_APPLICATION = Path(__file__).parents[1] / "src" / "flow_of_work_mcp" / "application"


def test_fastmcp_registration_and_descriptions_come_from_registry(tmp_path) -> None:
    runtime = build_runtime(
        database_path=tmp_path / "flow.sqlite3", import_root=tmp_path
    )
    try:
        registered = {
            item.name: item.description or ""
            for item in asyncio.run(create_app(runtime).list_tools())
        }
    finally:
        runtime.close()

    catalog = {
        str(item["name"]): str(item["description"]) for item in public_tool_catalog()
    }
    assert registered == catalog
    assert tuple(catalog) == public_tool_names()


def test_areas_recipes_and_operations_share_one_registry_vocabulary() -> None:
    areas = {str(item["area"]) for item in work_area_catalog()}
    assert areas
    assert {str(item["area"]) for item in all_recipes()} <= areas
    for area in areas:
        assert operation_descriptors_for_area(area), area

    indexed_routes = {
        (str(item["tool"]), str(item["operation"]))
        for item in operation_contract_index()
    }
    assert indexed_routes
    assert {tool for tool, _operation in indexed_routes} == set(public_tool_names())


def test_recipes_retain_policy_and_remove_transport_choreography() -> None:
    forbidden_keys = {
        "steps",
        "tool",
        "operation",
        "arguments",
        "receipt",
        "workflow_version",
        "guide_version",
    }
    for recipe in all_recipes():
        assert recipe["contract_version"] == "flow.lifecycle-recipe.v2"
        assert recipe["intent"]
        assert recipe["authority"]["owner"]
        assert recipe["authority"]["boundary"]
        assert recipe["semantic_decisions"]
        assert recipe["required_evidence"]
        assert recipe["stop_conditions"]
        assert recipe["escalation_conditions"]
        assert not (forbidden_keys & set(recipe))
        assert recipe["action_source"].startswith("current interaction frame")


def test_recipe_callers_cannot_mutate_the_canonical_policy() -> None:
    recipes = all_recipes()
    recipes[0]["semantic_decisions"].append("caller mutation")

    assert "caller mutation" not in all_recipes()[0]["semantic_decisions"]


def test_capability_views_are_progressive_and_exact_help_retains_unit_shape(
    tmp_path,
) -> None:
    runtime = build_runtime(
        database_path=tmp_path / "flow.sqlite3", import_root=tmp_path
    )
    try:
        summary = handle_capabilities(runtime)
        docs = handle_capabilities(runtime, view="docs")
        operation = handle_capabilities(
            runtime,
            view="operation",
            operation_tool="fow_packet_author",
            operation_name="add_unit",
        )
        full = handle_capabilities(runtime, view="full")
    finally:
        runtime.close()

    assert summary["result"]["registry_version"] == registry_version()
    assert len(json.dumps(summary, sort_keys=True)) < 4_000
    assert not ({"tools", "areas", "operation_contracts"} & set(summary["result"]))
    assert docs["result"]["areas"] == list(work_area_catalog())
    assert "fow_packet_author" in docs["result"]["tool_reference"]
    exact = operation["result"]["operation_contract"]
    assert exact["guidance"]["unit"]["required_fields"] == (
        "client_unit_key",
        "operation_kind",
        "instructions",
        "unit_checks",
    )
    assert "example" in exact
    assert exact["example"]["unit"]["operation_kind"] == "new_file"
    assert exact["example"]["unit"]["instructions"]
    assert all("example" not in item for item in full["result"]["operation_contracts"])


def test_expanded_diagnostics_stay_opt_in_and_default_discovery_is_bounded(tmp_path) -> None:
    frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["measurements"]
    current = asyncio.run(build_inventory())["measurements"]

    assert current["public_tool_count"] >= frozen["public_tool_count"]
    assert (
        current["multiplexed_operation_count"] >= frozen["multiplexed_operation_count"]
    )
    assert current["recipe_count"] > frozen["recipe_count"]
    # The immutable 114-operation measurement is historical evidence. The exact
    # 0.6.5 predecessor already exceeds its whole-inventory ratio (reviewv1.47§6).
    # Models consume bounded orientation first; complete diagnostics are opt-in.
    runtime = build_runtime(database_path=tmp_path / "discovery.sqlite3", import_root=tmp_path)
    try:
        summary = handle_capabilities(runtime)
        assert len(json.dumps(summary, sort_keys=True)) < 4_000
        assert "operation_contracts" not in summary["result"]
        assert {"docs", "operation", "full"} <= set(summary["result"]["detail_views"])
        complete = handle_capabilities(runtime, view="full")
        assert len(complete["result"]["operation_contracts"]) == current["multiplexed_operation_count"]
    finally:
        runtime.close()


def test_superseded_recipe_modules_and_server_catalog_are_absent() -> None:
    package = _APPLICATION.parent
    server_source = (package / "server.py").read_text(encoding="utf-8")

    assert "_CATALOG" not in server_source
    assert "tools = (" not in server_source
    assert not (_APPLICATION / "work_plan_guidance.py").exists()
    assert not (_APPLICATION / "project_state_guidance.py").exists()


def test_registry_version_covers_exact_operation_help() -> None:
    exact = operation_contract("fow_packet_author", "add_unit")

    assert exact["required_fields"]
    assert exact["accepted_values"]
    assert exact["guidance"]
    assert registry_version().startswith("flow.operations.")
