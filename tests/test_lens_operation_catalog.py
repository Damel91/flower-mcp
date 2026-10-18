"""IMPL-79: complete lens membership and a pure coherent interaction read.

These deterministic fixtures do not qualify the separately exercised live MCP
transport or a consumer installation. Deliberately malformed rows stay in each
test's owned SQLite database.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import re
import sqlite3
from threading import Event

import pytest

from flow_of_work_mcp.application import operation_contracts as registry
from flow_of_work_mcp.application.interaction_projection import _GATE_AREAS
from flow_of_work_mcp.application.packet_next_action import _ROUTES
from flow_of_work_mcp.application.project_state_snapshot import _gate_kind
from flow_of_work_mcp.core.domain import RequirementDraft
from flow_of_work_mcp.core.domain.interaction_projection import CapabilityLensBinding
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app


SESSION = "private-host-chat-79-catalog"
CATALOG_KEYS = {
    "contract", "scope", "complete", "registry_version", "catalog_revision",
    "interaction_session_ref", "interaction_revision", "revisions",
    "project_context", "capability_lens", "selection_state", "selection_reason",
    "operation_count", "lens_count", "operations", "core_operations", "lenses",
    "execution_admission", "selection_contract",
}
OPERATION_KEYS = {
    "tool", "operation", "area", "owner", "risk", "effect_class",
    "continuation_policy", "availability", "reason", "execution_admission",
}
LENS_KEYS = {
    "provider", "area", "label", "purpose", "selected", "availability", "reason",
    "prerequisites", "primary_operations", "companion_operations",
}


@pytest.fixture
def runtime(tmp_path):
    value = build_runtime(database_path=tmp_path / "flow.sqlite3", import_root=tmp_path)
    try:
        yield value
    finally:
        value.close()


def _catalog(runtime, session=SESSION):
    return runtime.interaction_projection.execute(
        "catalog", interaction_session_ref=session
    )


def _public_catalog(runtime, session=SESSION):
    return asyncio.run(create_app(runtime).call_tool(
        "fow_interaction", {"operation": "catalog", "interaction_session_ref": session}
    ))


def _bind(runtime, *, project="alpha", area="requirements", provider="flow"):
    known = {row["project_id"] for row in runtime.ledger.list_projects_for_interaction()}
    if project not in known:
        runtime.requirements.create_project(project, project.title(), actor="test")
    context = runtime.ledger.set_interaction_project_context(
        SESSION, project, actor="test", provider_context_id="private-provider-context"
    )
    if area is not None:
        runtime.ledger.set_interaction_capability_lens(
            SESSION, project_id=project, project_context_revision=context.revision,
            producing_provider=provider, selected_area=area, actor="test"
        )
    return context


def _sql(runtime, statement, parameters=()):
    # Raw mutation is intentional adversarial fixture setup, never a product
    # recovery operation or a claimed public mutation.
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(statement, parameters)


def _logical_database(runtime):
    """Include every schema object and table, including sequence/audit rows."""
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        schema = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        tables = [row[1] for row in schema if row[0] == "table"]
        rows = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows[table] = sorted(connection.execute("SELECT * FROM " + quoted).fetchall(), key=repr)
        return {
            "schema": schema, "rows": rows,
            "user_version": connection.execute("PRAGMA user_version").fetchone(),
            "application_id": connection.execute("PRAGMA application_id").fetchone(),
        }


def _pairs(values):
    assert all(set(value) == {"tool", "operation"} for value in values)
    pairs = [(value["tool"], value["operation"]) for value in values]
    assert len(pairs) == len(set(pairs))
    return set(pairs)


def _lens(catalog, area):
    return next(value for value in catalog["lenses"] if value["area"] == area)


def test_catalog_exact_wire_complete_registry_and_unique_membership(runtime):
    catalog = _catalog(runtime)
    assert set(catalog) == CATALOG_KEYS
    assert catalog["contract"] == "flow.lens-operation-catalog.v1"
    assert catalog["scope"] == "flower_public_operations"
    assert catalog["complete"] is True
    assert catalog["interaction_session_ref"] == SESSION
    assert catalog["catalog_revision"] == catalog["registry_version"] == registry.registry_version()
    assert re.fullmatch(r"flow\.operations\.[0-9a-f]{16}", catalog["registry_version"])
    assert re.fullmatch(r"flow\.interaction-catalog\.[0-9a-f]{64}", catalog["interaction_revision"])
    assert catalog["execution_admission"] == "not_evaluated"
    assert catalog["selection_contract"] == {
        "tool": "fow_interaction", "discover": "discover", "select": "select", "switch": "switch"
    }
    source = {(item["tool"], item["operation"]): item for item in registry.operation_contract_index()}
    operations = {(item["tool"], item["operation"]): item for item in catalog["operations"]}
    assert len(catalog["operations"]) == len(operations) == catalog["operation_count"] == 182
    assert set(operations) == set(source)
    assert len({tool for tool, _operation in operations}) == 37
    for pair, item in operations.items():
        assert set(item) == OPERATION_KEYS
        assert item["availability"] == "declared"
        assert item["reason"] == "operation_admission_not_evaluated"
        assert item["execution_admission"] == "not_evaluated"
        for field in ("area", "risk", "effect_class", "continuation_policy"):
            assert item[field] == source[pair][field]
        assert item["owner"] == source[pair].get("owner", "flow")
    core = _pairs(catalog["core_operations"])
    expected_core = {("fow_interaction", operation) for operation in registry.operation_names("fow_interaction")}
    expected_core |= {
        ("fow_capabilities", "call"), ("fow_create_project", "call"),
        ("fow_handover", "project_state_snapshot"), ("fow_what_next", "call")
    }
    assert core == expected_core
    assert len(core) == 17
    areas = {item["area"]: item for item in registry.work_area_catalog()}
    assert catalog["lens_count"] == len(catalog["lenses"]) == len(areas) == 9
    assert {lens["area"] for lens in catalog["lenses"]} == set(areas)
    primary_union = set()
    for lens in catalog["lenses"]:
        assert set(lens) == LENS_KEYS
        assert lens["provider"] == "flow"
        assert lens["label"] == areas[lens["area"]]["label"]
        assert lens["purpose"] == areas[lens["area"]]["purpose"]
        primary, companions = _pairs(lens["primary_operations"]), _pairs(lens["companion_operations"])
        assert not (core & primary or core & companions or primary & companions)
        assert primary <= set(operations) and companions <= set(operations)
        assert primary == {pair for pair, op in operations.items() if op["area"] == lens["area"]} - core
        assert not primary_union & primary
        primary_union |= primary
    assert primary_union | core == set(operations)
    # A membership catalog never becomes a recommendation or executable call.
    assert not ({"choices", "actions", "next_gate", "next_tool_call", "frame_ref"} & set(catalog))
    assert all("arguments" not in op and "required_fields" not in op and "example" not in op for op in catalog["operations"])


def test_public_schema_help_and_markdown_keep_machine_catalog_separate(runtime):
    async def inspect():
        app = create_app(runtime)
        tools = await app.list_tools()
        result = await app.call_tool("fow_interaction", {
            "operation": "catalog", "interaction_session_ref": "  " + SESSION + "  "
        })
        help_result = await app.call_tool("fow_capabilities", {
            "view": "operation", "operation_tool": "fow_interaction", "operation_name": "catalog"
        })
        return tools, result, help_result
    tools, response, help_response = asyncio.run(inspect())
    assert len(tools) == 37
    assert sum(len(tool.inputSchema["properties"]) for tool in tools) == 445
    interaction = next(tool for tool in tools if tool.name == "fow_interaction")
    operation_schema = interaction.inputSchema["properties"]["operation"]
    if "$ref" in operation_schema:
        operation_schema = interaction.inputSchema["$defs"][operation_schema["$ref"].rsplit("/", 1)[1]]
    assert set(operation_schema["enum"]) == set(registry.operation_names("fow_interaction"))
    assert "catalog" in operation_schema["enum"]
    exact = help_response.structuredContent["result"]["result"]["operation_contract"]
    assert set(exact["required_fields"]) == {"operation", "interaction_session_ref"}
    assert exact["optional_fields"] == []
    assert exact["risk"] == "read" and exact["effect_class"] == "none"
    assert response.isError is False
    envelope = response.structuredContent["result"]
    assert envelope["tool"] == "fow_interaction" and envelope["status"] == "success"
    assert envelope["reason"] == "" and envelope["audit_reference"] == {}
    catalog = envelope["result"]
    assert catalog["interaction_session_ref"] == SESSION
    markdown = "\n".join(item.text for item in response.content if item.type == "text")
    assert markdown.startswith("# Flower Interaction: catalog\n")
    assert "\n\n" in markdown and len(markdown) < 12_000
    assert SESSION not in markdown and "interaction_session_ref" not in markdown
    assert catalog["registry_version"] in markdown
    assert "complete" in markdown.lower() and "summar" in markdown.lower()
    for lens in catalog["lenses"]:
        assert lens["label"] in markdown or lens["area"] in markdown
    assert "required_fields" not in markdown and "accepted_values" not in markdown


def test_no_context_catalog_has_explicit_coarse_prerequisites(runtime):
    catalog = _catalog(runtime)
    assert catalog["project_context"] is None and catalog["capability_lens"] is None
    assert catalog["selection_state"] == "project_unselected"
    assert catalog["selection_reason"] == "project_context_required"
    assert catalog["revisions"] == {"project_context": 0, "capability_lens": 0}
    for lens in catalog["lenses"]:
        assert lens["selected"] is False
        assert lens["availability"] == "available_with_prerequisites"
        assert lens["reason"] == "project_context_required"
        assert lens["prerequisites"] == ["project_context"]


@pytest.mark.parametrize("case,state,reason", [
    ("orphan", "stale", "project_context_changed"),
    ("missing_project", "stale", "project_not_found"),
    ("no_lens", "lens_unselected", "work_area_required"),
    ("context_mismatch", "stale", "project_context_changed"),
    ("foreign_mismatch", "stale", "project_context_changed"),
    ("foreign", "foreign_provider", "provider_catalog_not_in_scope"),
    ("unknown_area", "stale", "area_not_registered"),
    ("current", "current", ""),
])
def test_selection_precedence_preserves_raw_binding(runtime, case, state, reason):
    _bind(runtime, area=None if case == "no_lens" else "requirements",
          provider="foreign-test" if case.startswith("foreign") else "flow")
    if case == "orphan":
        _sql(runtime, "DELETE FROM interaction_project_contexts WHERE interaction_session_ref=?", (SESSION,))
    elif case == "missing_project":
        _sql(runtime, "UPDATE interaction_project_contexts SET project_id='missing' WHERE interaction_session_ref=?", (SESSION,))
    elif case in {"context_mismatch", "foreign_mismatch"}:
        _sql(runtime, "UPDATE interaction_capability_lenses SET project_context_revision=2 WHERE interaction_session_ref=?", (SESSION,))
    elif case == "unknown_area":
        _sql(runtime, "UPDATE interaction_capability_lenses SET selected_area='unregistered-test' WHERE interaction_session_ref=?", (SESSION,))
    before = _logical_database(runtime)
    catalog = _catalog(runtime)
    assert catalog["selection_state"] == state
    assert catalog["selection_reason"] == reason
    assert [lens["area"] for lens in catalog["lenses"] if lens["selected"]] == (["requirements"] if state == "current" else [])
    if case != "no_lens":
        assert catalog["capability_lens"] is not None
        assert set(catalog["capability_lens"]) == {
            "provider", "area", "revision", "project_id", "project_context_revision"
        }
    if case == "missing_project":
        assert all(lens["availability"] == "blocked" and lens["reason"] == "project_not_found" for lens in catalog["lenses"])
    if case in {"foreign", "foreign_mismatch"}:
        assert catalog["capability_lens"]["provider"] == "foreign-test"
        assert all(lens["provider"] == "flow" for lens in catalog["lenses"])
    assert _logical_database(runtime) == before


def test_selected_flag_does_not_hide_prerequisite_or_claim_admission(runtime):
    _bind(runtime, area="milestones")
    first = _catalog(runtime)
    milestone = _lens(first, "milestones")
    assert milestone["selected"] is True
    assert milestone["availability"] == "available_with_prerequisites"
    assert milestone["reason"] == "requirements_required"
    runtime.requirements.register("alpha", RequirementDraft(
        title="Required behavior", statement="The product shall retain explicit obligations.", category="functional"
    ), actor="test")
    second = _catalog(runtime)
    assert _lens(second, "milestones")["availability"] == "available"
    assert _lens(second, "milestones")["selected"] is True
    assert _lens(second, "changes")["reason"] == "milestone_required"
    assert _lens(second, "packet_lifecycle")["reason"] == "change_required"
    assert _lens(second, "campaigns")["reason"] == "packet_required"
    assert second["interaction_revision"] != first["interaction_revision"]
    assert second["revisions"] == first["revisions"]
    assert all(op["execution_admission"] == "not_evaluated" for op in second["operations"])


def test_read_is_whole_database_pure_with_provider_model_and_repairs_poisoned(runtime, monkeypatch):
    _bind(runtime)
    runtime.ledger.set_interaction_continuation(SESSION, project_id="alpha",
        project_context_revision=1, owner="sentinel", query="must-survive", offset=2,
        source_fingerprint="retained")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("catalog invoked a provider/model/projection mutation path")
    class PoisonProvider:
        kind = "poison-provider"
        discover = forbidden
        frame = forbidden
        resolve = forbidden
        invoke = forbidden
    monkeypatch.setattr(runtime.interaction_projection, "_interaction_provider", PoisonProvider())
    for name in ("frame", "discover", "_area_inventory", "_current_lens"):
        monkeypatch.setattr(runtime.interaction_projection, name, forbidden)
    monkeypatch.setattr(runtime.project_state_snapshot, "snapshot", forbidden)
    for name in ("traceability_matrix", "milestones", "list_changes"):
        monkeypatch.setattr(runtime.ledger, name, forbidden)
    # Core catalog cannot start either optional semantic service or any job.
    monkeypatch.setattr(runtime.jobs, "submit", forbidden)
    for service in (runtime.semantic_validation, runtime.grounding):
        if service is not None:
            monkeypatch.setattr(service, "_gateway", PoisonProvider())
            for name in ("validate", "ground", "prepare"):
                if hasattr(service, name):
                    monkeypatch.setattr(service, name, forbidden)
    before = _logical_database(runtime)
    first = _catalog(runtime)
    assert _catalog(runtime) == first
    response = _public_catalog(runtime)
    assert response.structuredContent["result"]["result"] == first
    assert first["project_context"]["provider_configured"] is True
    assert "private-provider-context" not in json.dumps(first)
    assert _logical_database(runtime) == before


def test_clear_revision_heads_and_restart_are_stable(runtime, tmp_path):
    initial = _catalog(runtime)
    _bind(runtime)
    selected = _catalog(runtime)
    assert selected["revisions"] == {"project_context": 1, "capability_lens": 1}
    runtime.ledger.clear_interaction_capability_lens(SESSION, actor="test")
    cleared_lens = _catalog(runtime)
    assert cleared_lens["selection_state"] == "lens_unselected"
    assert cleared_lens["revisions"]["capability_lens"] > selected["revisions"]["capability_lens"]
    runtime.ledger.clear_interaction_project_context(SESSION, actor="test")
    cleared = _catalog(runtime)
    assert cleared["selection_state"] == initial["selection_state"]
    assert cleared["revisions"]["project_context"] > selected["revisions"]["project_context"]
    assert cleared["interaction_revision"] != initial["interaction_revision"]
    before = _logical_database(runtime)
    restarted = build_runtime(database_path=runtime.ledger.database_path, import_root=tmp_path)
    try:
        assert _catalog(restarted) == cleared
        assert _logical_database(runtime) == before
    finally:
        restarted.close()


@pytest.mark.parametrize("table,column,value", [
    ("interaction_project_contexts", "revision", 0),
    ("interaction_project_contexts", "revision", "corrupt"),
    ("interaction_project_contexts", "revision", 1.5),
    ("interaction_capability_lenses", "revision", -1),
    ("interaction_capability_lenses", "project_context_revision", "corrupt"),
    ("interaction_project_context_events", "revision", -1),
    ("interaction_capability_lens_events", "revision", "corrupt"),
])
def test_corrupt_state_returns_non_success_without_partial_catalog(runtime, table, column, value):
    _bind(runtime)
    _sql(runtime, f"UPDATE {table} SET {column}=? WHERE interaction_session_ref=?", (value, SESSION))
    before = _logical_database(runtime)
    response = _public_catalog(runtime)
    envelope = response.structuredContent["result"]
    assert envelope["status"] != "success"
    assert envelope["reason"]
    assert envelope.get("result", {}).get("complete") is not True
    assert _logical_database(runtime) == before


@pytest.mark.parametrize("table", ["interaction_project_context_events", "interaction_capability_lens_events"])
def test_binding_without_its_event_revision_head_fails_closed(runtime, table):
    _bind(runtime)
    _sql(runtime, f"DELETE FROM {table} WHERE interaction_session_ref=?", (SESSION,))
    before = _logical_database(runtime)
    response = _public_catalog(runtime)
    assert response.structuredContent["result"]["status"] != "success"
    assert _logical_database(runtime) == before


def test_snapshot_remains_coherent_when_writer_commits_between_queries(runtime, monkeypatch):
    _bind(runtime)
    runtime.requirements.create_project("beta", "Beta", actor="test")
    runtime.requirements.register("beta", RequirementDraft(
        title="Beta prerequisite", statement="Beta shall have a requirement.", category="functional"
    ), actor="test")
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    original = runtime.ledger._connect
    committed = Event()

    def switch_atomically():
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE interaction_project_contexts SET project_id='beta',revision=2 WHERE interaction_session_ref=?", (SESSION,))
            connection.execute("UPDATE interaction_capability_lenses SET project_id='beta',project_context_revision=2,revision=2,selected_area='goal_graph' WHERE interaction_session_ref=?", (SESSION,))
            for table in ("interaction_project_context_events", "interaction_capability_lens_events"):
                connection.execute(f"UPDATE {table} SET revision=2,project_id='beta' WHERE interaction_session_ref=?", (SESSION,))
        committed.set()

    class Connection:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *args):
            cursor = self.connection.execute(sql, *args)
            if (not committed.is_set() and sql.lstrip().upper().startswith("SELECT")
                    and "interaction_project_contexts" in sql):
                # The SELECT has established the snapshot. WAL permits a writer
                # commit now without releasing that reader's transaction.
                switch_atomically()
            return cursor

    monkeypatch.setattr(runtime.ledger, "_connect", lambda: Connection(original()))
    first = _catalog(runtime)
    assert committed.is_set(), "fixture did not intercept the context read"
    assert first["selection_state"] == "current"
    assert first["project_context"]["project_id"] == first["capability_lens"]["project_id"] == "alpha"
    assert first["revisions"] == {"project_context": 1, "capability_lens": 1}
    assert _lens(first, "milestones")["availability"] == "available_with_prerequisites"
    second = _catalog(runtime)
    assert second["selection_state"] == "current"
    assert second["project_context"]["project_id"] == second["capability_lens"]["project_id"] == "beta"
    assert second["revisions"] == {"project_context": 2, "capability_lens": 2}
    assert _lens(second, "milestones")["availability"] == "available"
    assert first["interaction_revision"] != second["interaction_revision"]


def test_membership_covers_actual_default_and_normalized_packet_frame_routes(runtime, monkeypatch):
    context = _bind(runtime)
    catalog = _catalog(runtime)
    core = _pairs(catalog["core_operations"])
    scopes = {lens["area"]: core | _pairs(lens["primary_operations"]) | _pairs(lens["companion_operations"])
              for lens in catalog["lenses"]}
    current_snapshot = {"next_gate": {"kind": "idle"}, "active_work": {}}
    monkeypatch.setattr(runtime.project_state_snapshot, "snapshot", lambda *_args, **_kwargs: current_snapshot)
    service = runtime.interaction_projection
    for area in scopes:
        binding = CapabilityLensBinding(SESSION, "alpha", 1, "flow", area, 1)
        frame = service._flow_frame(context, binding, {}, {})
        assert all((action["tool"], action["operation"]) in scopes[area] for action in frame["actions"]), area
    checked = set()
    for action_kind, (tool, operation, _class, required) in _ROUTES.items():
        gate_kind = _gate_kind(action_kind, "", {"rows": []})
        for area in _GATE_AREAS.get(gate_kind, ()):
            if tool not in registry.public_tool_names():
                continue  # External-provider configuration is not a Flower verb.
            current_snapshot = {"next_gate": {"kind": gate_kind, "reason": action_kind,
                "route": {"tool": tool, "operation": operation, "required_inputs": required}}, "active_work": {}}
            binding = CapabilityLensBinding(SESSION, "alpha", 1, "flow", area, 1)
            frame = service._flow_frame(context, binding, {}, {})
            for action in frame["actions"]:
                pair = (action["tool"], action["operation"])
                assert pair in scopes[area], (area, action_kind, pair)
                checked.add((area, pair))
    assert ("changes", ("fow_external_work", "todo")) in checked
    assert ("assurance", ("fow_campaign_author", "start")) in checked
    for area, scope in scopes.items():
        for tool in ("fow_packet_inspect", "fow_campaign_inspect"):
            assert {(tool, op) for op in registry.operation_names(tool)} <= scope, area
        assert ("fow_handover", "create_handover") not in _pairs(_lens(catalog, area)["companion_operations"])
    for area in ("changes", "campaigns"):
        assert {("fow_external_work", op) for op in ("todo", "report_outcome", "reconcile_outcome", "validation", "provider_validation", "export_plan")} <= scopes[area]


def test_registry_membership_is_defensive_and_hash_covers_membership_and_help(monkeypatch):
    first = registry.lens_operation_membership()
    preserved = deepcopy(first)
    first["core_operations"].clear()
    first["lenses"][0]["companion_operations"].clear()
    assert registry.lens_operation_membership() == preserved
    registry.registry_version.cache_clear()
    before = registry.registry_version()
    try:
        changed_policy = dict(registry._LENS_COMPANION_PAIRS)
        changed_policy["project_bootstrap"] = (*changed_policy.get("project_bootstrap", ()),
                                               ("fow_external_work", "todo"))
        monkeypatch.setattr(registry, "_LENS_COMPANION_PAIRS", changed_policy)
        registry.registry_version.cache_clear()
        assert registry.registry_version() != before
        monkeypatch.undo()
        registry.registry_version.cache_clear()
        assert registry.registry_version() == before
        changed = dict(registry.FIELD_HELP)
        changed["interaction_session_ref"] += " Changed exact help."
        monkeypatch.setattr(registry, "FIELD_HELP", changed)
        registry.registry_version.cache_clear()
        assert registry.registry_version() != before
    finally:
        monkeypatch.undo()
        registry.registry_version.cache_clear()


def test_invalid_canonical_membership_fails_closed_without_writes(runtime, monkeypatch):
    # The canonical policy validation must reject invalid refs at construction;
    # poisoning its declaration seam exercises that validation rather than a
    # consumer fallback. The service still owes an ordinary non-success reply.
    poisoned = dict(registry._LENS_COMPANION_PAIRS)
    poisoned["project_bootstrap"] = (*poisoned.get("project_bootstrap", ()), ("fow_nonexistent", "call"))
    monkeypatch.setattr(registry, "_LENS_COMPANION_PAIRS", poisoned)
    registry.registry_version.cache_clear()
    before = _logical_database(runtime)
    try:
        response = _public_catalog(runtime)
        envelope = response.structuredContent["result"]
        assert envelope["status"] != "success"
        assert envelope.get("result", {}).get("complete") is not True
        assert _logical_database(runtime) == before
    finally:
        registry.registry_version.cache_clear()


def test_unreadable_catalog_state_is_ordinary_failure_without_repair(runtime):
    _bind(runtime)
    app = create_app(runtime)
    _sql(runtime, "DROP TABLE interaction_capability_lens_events")
    before = _logical_database(runtime)
    response = asyncio.run(app.call_tool("fow_interaction", {
        "operation": "catalog", "interaction_session_ref": SESSION
    }))
    assert response.isError is False
    envelope = response.structuredContent["result"]
    assert envelope["status"] != "success" and envelope["reason"]
    assert envelope.get("result", {}).get("complete") is not True
    assert _logical_database(runtime) == before


@pytest.mark.parametrize("corruption", ["outer_tool", "inner_operation", "missing_tool"])
def test_registry_identity_corruption_returns_ordinary_failure(runtime, monkeypatch, corruption):
    app = create_app(runtime)
    changed = {tool: dict(operations) for tool, operations in registry._BY_TOOL.items()}
    tool = "fow_interaction"
    if corruption == "outer_tool":
        changed[tool]["catalog"] = replace(changed[tool]["catalog"], tool="fow_what_next")
    elif corruption == "inner_operation":
        changed[tool]["catalog"] = replace(changed[tool]["catalog"], operation="frame")
    else:
        del changed["fow_what_next"]
    monkeypatch.setattr(registry, "_BY_TOOL", changed)
    registry.registry_version.cache_clear()
    before = _logical_database(runtime)
    try:
        response = asyncio.run(app.call_tool("fow_interaction", {
            "operation": "catalog", "interaction_session_ref": SESSION
        }))
        assert response.isError is False
        envelope = response.structuredContent["result"]
        assert envelope["status"] != "success" and envelope["reason"]
        assert envelope.get("result", {}).get("complete") is not True
        assert _logical_database(runtime) == before
    finally:
        registry.registry_version.cache_clear()
