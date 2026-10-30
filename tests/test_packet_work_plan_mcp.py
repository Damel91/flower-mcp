from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import (
    handle_capabilities,
    handle_external_work,
    handle_packet_advance,
    handle_packet_author,
    handle_packet_inspect,
    handle_what_next,
)

from tests.support_packet_factory import (
    ready_packet_state_fixture,
    reconcile_current_packet_fixture,
)


def _scope(ledger, change_id: str, packet_id: str):
    packet = next(
        item
        for item in ledger.change_state("alpha", change_id)["packets"]
        if item["packet_id"] == packet_id
    )
    binding = ledger.list_navigation_audits("alpha")[0]["target_bindings"][0]
    return int(packet["spec_revision"]), str(binding["binding_id"]), str(binding["target_handle"])


def _work_plan(binding_id: str):
    return {
        "units": [
            {
                "client_unit_key": "modify",
                "operation_kind": "modify_existing",
                "mutation_target_binding_id": binding_id,
                "instructions": [
                    "Add the bounded work-plan behavior at the selected target.",
                    "Preserve the existing public contract.",
                ],
                "unit_checks": ["The selected behavior is observable."],
                "implements": [1],
                "verifies": [{"criterion": 1, "kind": "unit_check", "statement": "The selected behavior is observable."}],
                "surface": "repo",
            },
            {
                "client_unit_key": "support",
                "operation_kind": "new_file",
                "file_path": "src/generated/work_plan_support.py",
                "instructions": ["Create the reusable supporting module."],
                "unit_checks": ["The supporting module can be imported."],
                "implements": [1],
                "verifies": [{"criterion": 1, "kind": "unit_check", "statement": "The supporting module can be imported."}],
                "depends_on": ["modify"],
                "surface": "repo",
            },
        ]
    }


def _select_provider(runtime, change_id: str, packet_id: str):
    packet_revision, _binding, _target = _scope(runtime.ledger, change_id, packet_id)
    plan = runtime.ledger.packet_work_plan_state("alpha", change_id, packet_id)
    selected = handle_external_work(
        runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
        operation="select_executor", actor="orchestrator", request_id="select-provider",
        payload={"executor": "provider", "provider_kind": "codingcastle",
                 "expected_spec_revision": packet_revision,
                 "expected_plan_revision": int((plan or {}).get("plan_revision") or 0)},
    )
    assert selected["status"] == "success"


def test_bulk_work_plan_mcp_lifecycle_is_bounded_idempotent_and_restart_safe(tmp_path):
    initial = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    initial.close()
    ledger, _handoff, change, bootstrap = ready_packet_state_fixture(tmp_path)
    packet_revision, binding_id, target_handle = _scope(
        ledger, change["change_id"], bootstrap["packet_id"]
    )
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        upgraded = handle_external_work(
            runtime, project_id="alpha", change_id=change["change_id"], packet_id=bootstrap["packet_id"],
            operation="upgrade_validation", actor="orchestrator", request_id="upgrade-validation",
            payload={"expected_spec_revision": packet_revision, "expected_plan_revision": 0},
        )
        assert upgraded["status"] == "success"
        proposed = handle_packet_author(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
            operation="replace_plan",
            work_plan=_work_plan(binding_id),
            expected_spec_revision=packet_revision,
            expected_plan_revision=0,
            actor="orchestrator",
            request_id="set-plan-v1",
        )
        replay = handle_packet_author(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
            operation="replace_plan",
            work_plan=_work_plan(binding_id),
            expected_spec_revision=packet_revision,
            expected_plan_revision=0,
            actor="orchestrator",
            request_id="set-plan-v1",
        )
        assert replay["status"] == "success"
        assert replay["result"]["semantic_delta"]["replayed"] is True
        assert replay["result"]["engineering_questions"] == proposed["result"]["engineering_questions"]
        before_changed_replay = runtime.ledger.packet_work_plan_state(
            "alpha", change["change_id"], bootstrap["packet_id"]
        )
        changed_replay = handle_packet_author(
            runtime, project_id="alpha", change_id=change["change_id"],
            packet_id=bootstrap["packet_id"], operation="replace_plan",
            work_plan=_work_plan(binding_id),
            expected_spec_revision=proposed["result"]["packet"]["spec_revision"],
            expected_plan_revision=0, actor="orchestrator", request_id="set-plan-v1",
        )
        assert changed_replay["status"] == "rejected"
        assert changed_replay["reason"] == "state_conflict"
        assert changed_replay["result"]["effect_state"] == "unknown"
        assert runtime.ledger.packet_work_plan_state(
            "alpha", change["change_id"], bootstrap["packet_id"]
        ) == before_changed_replay
        _select_provider(runtime, change["change_id"], bootstrap["packet_id"])
        standard = handle_packet_inspect(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
            view="units",
        )
        accepted = handle_packet_advance(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
            actor="orchestrator",
            decision={
                "operation": "accept_work_plan",
                "rationale": "The complete plan has been reviewed.",
            },
            request_id="accept-plan-v1",
        )
        reconcile_current_packet_fixture(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
            request_id="work-plan-current-evidence",
        )
        # Authoring and impact reconciliation establish new semantic authority;
        # an earlier accepted risk record does not govern that current revision.
        pressure = runtime.packet_pressure.derive(
            "alpha", change["change_id"], bootstrap["packet_id"],
            actor="orchestrator", request_id="work-plan-current-pressure",
        )
        if pressure["residual_risks"]:
            runtime.packet_pressure.accept_risk(
                "alpha", pressure["pressure_id"],
                accepted_risk_ref="fixture:reviewed-current-work-plan-risk",
                actor="orchestrator", request_id="work-plan-current-risk",
            )
        provider_preview = handle_packet_inspect(
            runtime,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
        )["result"]["packet"]["packet_provider"]["portable_packet"]

        packet_view = standard["result"]["packet"]
        assert proposed["result"]["packet"]["plan_revision"] == 1
        assert replay["result"]["packet"]["plan_revision"] == 1
        assert packet_view["units"][0]["target"] == target_handle
        # The concise unit view hides mutation handles. The enriched provider
        # proof is a separate machine contract and retains exact canonical IDs.
        assert binding_id not in str(packet_view["units"])
        assert "work_plan_id" not in packet_view
        assert accepted["status"] == "success"
        assert runtime.ledger.packet_work_plan_state(
            "alpha", change["change_id"], bootstrap["packet_id"]
        )["status"] == "accepted"
        assert [unit["instructions"] for unit in provider_preview["units"]] == [
            [
                "Add the bounded work-plan behavior at the selected target.",
                "Preserve the existing public contract.",
            ],
            ["Create the reusable supporting module."],
        ]
        assert provider_preview["completion_criteria"] == [
            "bounded work validates"
        ]
        assert provider_preview["contract_version"] == "flow.portable_packet.v2"
        assert provider_preview["packet_validation"]["status"] == "closed"
        assert provider_preview["packet_validation"]["units"][0]["mutation_target_binding_id"] == binding_id
        assert all(
            "completion_criteria" not in unit for unit in provider_preview["units"]
        )
    finally:
        runtime.close()

    reopened = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        verbose = reopened.ledger.packet_work_plan_state(
            "alpha", change["change_id"], bootstrap["packet_id"]
        )
        actions = handle_what_next(reopened, project_id="alpha")["result"]
        restarted_provider_preview = handle_packet_inspect(
            reopened,
            project_id="alpha",
            change_id=change["change_id"],
            packet_id=bootstrap["packet_id"],
        )["result"]["packet"]["packet_provider"]["portable_packet"]

        assert verbose["work_plan_id"] == "WPLAN-000001"
        assert verbose["units"][0]["mutation_target_binding_id"] == binding_id
        assert verbose["events"][-1]["event_type"] == "work_plan_accepted"
        # The enriched plan stays on its explicit provider route. Negotiation is
        # still required; this fixture does not contact or fabricate a provider.
        assert actions["primary_action"]["operation"] == "negotiate_provider"
        assert actions["primary_action"]["tool"] == "fow_external_work"
        assert "packet_actions" not in actions
        assert restarted_provider_preview == provider_preview
    finally:
        reopened.close()


def test_work_plan_policy_is_single_source_and_what_next_is_bounded(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        capabilities = handle_capabilities(runtime, view="full")["result"]
        recipes = [
            item for item in capabilities["recipes"]
            if item.get("name") == "packet-work-plan-v2"
        ]

        assert len(recipes) == 1
        recipe = recipes[0]
        assert recipe["contract_version"] == "flow.lifecycle-recipe.v2"
        assert len(recipe["semantic_decisions"]) == 7
        assert "steps" not in recipe
        add_unit = operation_contract("fow_packet_author", "add_unit")
        unit_guidance = add_unit["guidance"]["unit"]
        assert "member_label" in unit_guidance["optional_fields"]
        assert "operation_kind" in unit_guidance["required_fields"]
        assert "delete_existing" in add_unit["accepted_values"]["unit.operation_kind"]
        assert add_unit["accepted_values"]["unit.surface"] == [
            "repo",
            "workspace",
            "docs",
            "test_repo",
            "cc_test",
        ]
        assert "CodingCastle-managed harness tests" in unit_guidance["surface_rule"]
        assert all(item.get("name") != "packet-fast-path" for item in capabilities["recipes"])
        assert "propose_packet_units" not in str(recipe)
    finally:
        runtime.close()

    ledger, _handoff, change, bootstrap = ready_packet_state_fixture(tmp_path)
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        _select_provider(runtime, change["change_id"], bootstrap["packet_id"])
        action = handle_what_next(runtime, project_id="alpha")["result"][
            "primary_action"
        ]

        assert action["scope"]["change_id"] == change["change_id"]
        assert action["scope"]["packet_id"] == bootstrap["packet_id"]
        assert action["operation"] == "add_unit"
        assert action["tool"] == "fow_packet_author"
        assert action["arguments"]["project_id"] == "alpha"
        assert action["arguments"]["packet_id"] == bootstrap["packet_id"]
        assert action["arguments"]["expected_spec_revision"] >= 1
        assert action["arguments"]["expected_plan_revision"] == 0
        assert "continuation_ref" not in action
        assert "valid_example" not in action
        assert "navigation" not in str(action).lower()
        assert "proposal" not in str(action).lower()
    finally:
        runtime.close()
