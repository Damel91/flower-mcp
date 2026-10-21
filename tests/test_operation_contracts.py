from flow_of_work_mcp.application.operation_contracts import (
    change_operation_ownership,
    operation_contract,
    operation_contract_catalog,
    operation_names,
    operation_tools,
    public_tool_names,
)
from flow_of_work_mcp.application.packet_lifecycle_projection import (
    _gate_decision,
)
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import (
    _CHANGE_OPERATION_OWNERSHIP,
    handle_capabilities,
    handle_change,
)


EXPECTED_OPERATIONS = {
    "fow_architecture": {"inspect", "propose", "adopt"},
    "fow_external_work": {"provider_validation", "select_executor", "negotiate_provider", "set_mode", "criteria", "reconcile_criteria", "add_criterion", "edit_criterion", "remove_criterion", "upgrade_validation", "validation", "export_plan", "todo", "report_outcome", "reconcile_outcome"},
    "fow_bindings": {"inspect", "export", "import"},
    "fow_semantic": {"inventory", "prepare", "inspect", "submit", "adopt", "execute_internal"},
    "fow_bootstrap": {
        "guidance", "record_answer", "record_correspondence", "roadmap", "confirm_roadmap", "record_continuation",
        "bind_implementation_provider",
        "provider_binding_state",
        "list_provider_bindings",
        "start",
        "resume",
        "state",
        "state_details",
        "record_intake",
        "record_contradiction",
        "confirm_intake",
        "derive_behavior",
        "complete",
        "cancel",
    },
    "fow_assurance": {
        "record_finding",
        "get_finding",
        "reassess_intent",
        "set_finding_disposition",
        "link_fixing_packet",
        "request_change_acceptance",
    },
    "fow_run": {
        "create_run",
        "get_run",
        "add_step",
        "link_step_dependency",
        "start_step",
        "complete_step",
        "block_step",
        "cancel_step",
        "complete_run",
        "cancel_run",
        "task_view",
    },
    "fow_handover": {
        "project_progress",
        "create_handover",
        "get_handover",
        "resume_context",
        "ledger_projection",
        "project_state_snapshot",
    },
    "fow_goal": {
        "view",
        "add_use_case",
        "add_sequence",
        "add_behavioral_expectation",
        "link",
        "derive_requirement_candidates",
    },
    "fow_packet_author": {
        "start_packet",
        "revise_packet",
        "replace_plan",
        "resolve_questions",
        "answer_gate",
        "add_unit",
        "revise_unit",
        "remove_unit",
        "rebind_unit",
        "set_dependencies",
    },
    "fow_packet_advance": {
        "advance",
        "accept_work_plan",
        "reject_work_plan",
        "accept_residual_risk",
        "record_workspace_review",
        "resolve_reconciliation_residual",
        "retry_provider_rejection",
    },
    "fow_packet_inspect": {
        "summary",
        "units",
        "gates",
        "history",
        "requirements",
        "working_sheet",
    },
    "fow_campaign_author": {
        "start",
        "edit_scope",
        "add_case",
        "edit_case",
        "remove_case",
        "reorder_cases",
        "decide_obligation",
        "bind_obligation",
        "author_oracle",
        "answer_question",
        "attest_source",
        "authorize_materialization",
        "retry_provider_rejection",
        "authorize_promotion",
        "accept_exception",
        "cancel",
    },
    "fow_campaign_advance": {"advance"},
    "fow_campaign_inspect": {
        "summary",
        "working_sheet",
        "cases",
        "obligations",
        "oracles",
        "constructibility",
        "oracle_ir",
        "attestation",
        "evidence",
        "residuals",
        "history",
    },
}


def test_operation_registry_covers_every_retained_multiplexed_operation():
    expected = {
        **EXPECTED_OPERATIONS,
        "fow_change": set(_CHANGE_OPERATION_OWNERSHIP),
    }
    assert dict(change_operation_ownership()) == dict(_CHANGE_OPERATION_OWNERSHIP)
    for tool, operations in expected.items():
        assert set(operation_names(tool)) == operations

    catalog = operation_contract_catalog()
    assert len(catalog) > sum(len(values) for values in expected.values())
    for contract in catalog:
        assert contract["required_fields"] or contract["tool"] == "fow_capabilities"
        assert all(
            _has_path(contract["example"], field)
            for field in contract["required_fields"]
        )
        assert isinstance(contract["optional_fields"], list)
        assert isinstance(contract["accepted_values"], dict)
        assert contract["area"]
        assert contract["risk"] in {"read", "write", "destructive", "process"}
        assert contract["decision_class"] in {"inspection", "mechanical", "semantic"}
        assert contract["continuation_policy"] in {
            "internal_until_quiescent",
            "host_observe",
            "return_to_model",
        }


def test_registry_covers_every_public_tool_and_simple_calls() -> None:
    registered = set(public_tool_names())
    assert set(operation_tools()) == registered
    for tool in registered.difference(EXPECTED_OPERATIONS).difference({"fow_change"}):
        if tool != "fow_interaction":
            assert operation_names(tool) == ("call",)


def test_capabilities_projects_one_operation_contract(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        result = handle_capabilities(
            runtime,
            view="operation",
            operation_tool="fow_packet_advance",
            operation_name="record_workspace_review",
        )["result"]
        contract = result["operation_contract"]
        assert contract["operation"] == "record_workspace_review"
        assert contract["accepted_values"]["decision.review.disposition"] == [
            "approved",
            "findings",
            "rejected",
        ]
        assert contract["accepted_values"]["decision.review.completeness"] == [
            "complete",
            "partial",
        ]
        assert contract["accepted_values"]["decision.review.findings[].severity"] == [
            "info",
            "low",
            "medium",
            "high",
            "critical",
        ]
        assert contract["example"]["decision"]["operation"] == (
            "record_workspace_review"
        )
        guidance = contract["guidance"]["workspace_review"]
        assert guidance["finding_item"]["example"]["provider_finding_ref"]
        assert "requires at least one" in guidance["disposition_rules"]["rejected"]
        assert "forbids findings" in guidance["disposition_rules"]["approved"]
    finally:
        runtime.close()


def test_source_attestation_help_projects_harness_and_route_grammar():
    contract = operation_contract("fow_campaign_author", "attest_source")

    assert contract["accepted_values"]["harness.disposition"] == [
        "repository",
        "project_integration",
    ]
    assert "requested_capability.language" in contract["optional_fields"]
    assert "requested_capability.framework" in contract["optional_fields"]
    guidance = contract["guidance"]["source_attestation"]
    assert guidance["harness"]["required_fields"] == (
        "disposition",
        "participants",
    )
    assert guidance["harness"]["participant"]["required_fields"] == (
        "participant_ref",
        "repository",
        "runtime_participant",
        "role",
    )
    assert guidance["harness"]["rules"]["repository"] == (
        "participants must be empty"
    )
    assert guidance["requested_capability"]["required_fields_when_present"] == (
        "language",
        "framework",
    )


def test_operation_contract_enums_are_domain_accurate():
    claim = operation_contract("fow_change", "declare_packet_evidence_claim")
    residual = operation_contract("fow_change", "disposition_packet_evidence_residual")
    obligation = operation_contract("fow_campaign_author", "decide_obligation")
    answer = operation_contract("fow_campaign_author", "answer_question")

    assert claim["accepted_values"]["claim_type"] == [
        "target",
        "symbol_contract",
        "impact",
        "cleanup",
        "test_obligation",
    ]
    assert residual["accepted_values"]["reconciliation_disposition"] == [
        "resolved",
        "waived",
        "rejected",
        "escalated",
        "superseded",
    ]
    assert obligation["accepted_values"]["decision"] == [
        "required",
        "out_of_scope",
        "duplicate",
        "investigate",
        "waived",
    ]
    assert answer["accepted_values"]["answer_authority"] == [
        "grounded_fact",
        "accepted_decision",
        "derived_hypothesis",
        "unknown",
        "waived",
    ]


def test_reconciliation_gate_offers_proposal_decisions_only_for_proposals():
    _question, proposed, _effect = _gate_decision(
        "resolve_reconciliation_residual",
        current_question={},
        residual={"classification": "proposed"},
        has_units=True,
        has_reconciliation_scope=True,
    )
    _question, dynamic, _effect = _gate_decision(
        "resolve_reconciliation_residual",
        current_question={},
        residual={"classification": "unresolved_dynamic"},
        has_units=True,
        has_reconciliation_scope=True,
    )

    assert proposed == [
        "accepted",
        "rejected",
        "waived",
        "escalated",
        "investigate",
    ]
    assert dynamic == ["waived", "escalated", "investigate"]


def _has_path(payload, path: str) -> bool:
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def test_invalid_operation_returns_actionable_bounded_diagnostic(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        result = handle_change(
            runtime,
            project_id="alpha",
            operation="not_an_operation",
            actor="operator",
        )
        assert result["status"] == "rejected"
        diagnostic = result["result"]["diagnostics"][0]
        assert diagnostic["code"] == "invalid_input"
        assert diagnostic["message"] == "change operation is invalid"
        assert diagnostic["accepted_values"] == list(operation_names("fow_change"))
    finally:
        runtime.close()


def test_public_packet_inspect_detail_values_do_not_expose_internal_verbose():
    from flow_of_work_mcp.application.operation_contracts import operation_contract
    for view in ("summary", "units", "gates", "working_sheet", "history", "requirements"):
        contract = operation_contract("fow_packet_inspect", view)
        assert contract["accepted_values"]["detail_level"] == ["standard", "audit"]
