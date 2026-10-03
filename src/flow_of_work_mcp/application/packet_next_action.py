"""Canonical local-model-facing projection of one packet guard decision."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.application.operation_contracts import (
    operation_contract,
    operation_names,
)
from flow_of_work_mcp.application.packet_guards import PacketGuardDecision


_WORKSPACE_REVIEW_REQUIRED_INPUTS = tuple(
    field
    for field in operation_contract(
        "fow_packet_advance", "record_workspace_review"
    )["required_fields"]
    if field not in {"project_id", "packet_id"}
)


_ROUTES: Mapping[str, tuple[str, str, str, tuple[str, ...]]] = {
    "external_select_mode": ("fow_external_work", "set_mode", "semantic", ("actor", "request_id")),
    "external_validation": ("fow_external_work", "validation", "semantic", ()),
    "external_todo": ("fow_external_work", "todo", "semantic", ()),
    "external_reconcile": ("fow_external_work", "reconcile_outcome", "semantic",
                           ("payload.report_key", "payload.rationale", "actor", "request_id")),
    "external_verification": ("fow_campaign_author", "start", "semantic",
                              ("title", "scope.change_id", "actor", "request_id")),
    "external_acceptance": ("fow_packet_inspect", "summary", "semantic", ()),
    "packet_inactive": (
        "fow_packet_inspect",
        "summary",
        "mechanical",
        (),
    ),
    "packet_author": (
        "fow_packet_author",
        "add_unit",
        "semantic",
        ("unit", "actor", "request_id"),
    ),
    "accept_work_plan": (
        "fow_packet_advance",
        "advance",
        "semantic",
        ("decision.operation", "decision.rationale", "actor", "request_id"),
    ),
    "derive_engineering_questions": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "answer_engineering_questions": (
        "fow_packet_author",
        "answer_gate",
        "semantic",
        ("response", "gate_fingerprint", "actor", "request_id"),
    ),
    "revise_packet": (
        "fow_packet_author",
        "revise_packet",
        "semantic",
        ("actor", "request_id"),
    ),
    "evaluate_packet_readiness": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "derive_packet_pressure": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "decide_residual_risk": (
        "fow_packet_advance",
        "advance",
        "semantic",
        (
            "decision.operation",
            "decision.accepted_risk_ref",
            "actor",
            "request_id",
        ),
    ),
    "review_workspace": (
        "fow_packet_advance",
        "advance",
        "semantic",
        _WORKSPACE_REVIEW_REQUIRED_INPUTS,
    ),
    "record_verification": (
        "fow_campaign_author",
        "start",
        "semantic",
        ("title", "scope.change_id", "actor", "request_id"),
    ),
    "consume_verification": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "retry_or_remediate": (
        "fow_packet_author",
        "start_packet",
        "semantic",
        (
            "title",
            "intent",
            "rationale",
            "completion_criteria",
            "required_regression_evidence",
            "actor",
            "request_id",
        ),
    ),
    "inspect_provider_state": (
        "fow_packet_inspect",
        "history",
        "mechanical",
        (),
    ),
    "collect_packet_evidence": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "reconcile_packet_evidence": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "resolve_reconciliation_residual": (
        "fow_packet_advance",
        "advance",
        "semantic",
        (
            "decision.operation",
            "decision.disposition",
            "decision.rationale",
            "actor",
            "request_id",
        ),
    ),
    "configure_packet_provider": (
        "external_provider",
        "configure_packet_provider",
        "semantic",
        (),
    ),
    "provider_pending": (
        "fow_packet_inspect",
        "summary",
        "mechanical",
        (),
    ),
    "deliver_provider_command": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "ensure_provider_draft": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "choose_provider_targets": (
        "fow_packet_advance",
        "advance",
        "semantic",
        ("decision.target", "actor", "request_id"),
    ),
    "synchronize_provider_unit": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "remove_provider_unit": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "start_provider_packet": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "stop_provider_packet": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "observe_provider_packet": (
        "fow_packet_advance",
        "advance",
        "mechanical",
        ("actor", "request_id"),
    ),
    "provider_complete": (
        "fow_packet_inspect",
        "summary",
        "mechanical",
        (),
    ),
    "provider_failed": (
        "fow_packet_advance",
        "start_provider_packet",
        "semantic",
        ("decision.operation", "decision.rationale", "actor", "request_id"),
    ),
    "retry_provider_rejection": (
        "fow_packet_advance",
        "retry_provider_rejection",
        "semantic",
        ("decision.operation", "decision.rationale", "actor", "request_id"),
    ),
    "provider_stopped": (
        "fow_packet_advance",
        "advance",
        "semantic",
        ("decision.operation", "actor", "request_id"),
    ),
}


class PacketNextActionProjectionService:
    """Maps one guard authority to one stable public operation."""

    def project(
        self,
        decision: PacketGuardDecision,
        *,
        project_id: str,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        plan_revision: int,
    ) -> Mapping[str, object]:
        try:
            tool, operation, decision_class, required_inputs = _ROUTES[
                decision.next_operation
            ]
        except KeyError as exc:
            raise ValueError(
                f"unsupported packet next operation: {decision.next_operation!r}"
            ) from exc
        if decision.next_operation == "revise_packet":
            required_inputs = _packet_metadata_inputs(decision)
        blocker = decision.blockers[0] if decision.blockers else None
        reason = (
            blocker.code
            if blocker is not None
            else decision.semantic_decisions[0]
            if decision.semantic_decisions
            else decision.state
        )
        continuation_policy = str(
            operation_contract(
                tool, _registered_operation(tool, operation)
            ).get("continuation_policy")
            or "return_to_model"
        )
        if decision.next_operation == "observe_provider_packet":
            continuation_policy = "host_observe"
        return {
            "state": decision.state,
            "lifecycle_operation": decision.next_operation,
            "tool": tool,
            "operation": operation,
            "decision_class": decision_class,
            "continuation_policy": continuation_policy,
            "reason": reason,
            "arguments": _fixed_arguments(
                tool,
                operation,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                spec_revision=spec_revision,
                plan_revision=plan_revision,
                decision_class=decision_class,
            ),
            "required_inputs": list(required_inputs),
            "alternatives": [],
        }


def _registered_operation(tool: str, operation: str) -> str:
    names = operation_names(tool)
    if operation in names:
        return operation
    for fallback in ("advance", "call"):
        if fallback in names:
            return fallback
    raise ValueError(f"packet next-action route is not registered: {tool}:{operation}")


def _packet_metadata_inputs(
    decision: PacketGuardDecision,
) -> tuple[str, ...]:
    fields_by_blocker = {
        "packet_objective_missing": "intent",
        "packet_rationale_missing": "rationale",
        "packet_scope_missing": "in_scope",
        "packet_invariants_missing": "invariants",
        "packet_completion_criteria_missing": "completion_criteria",
        "packet_unresolved_authority_questions": "unresolved_questions",
    }
    fields: list[str] = []
    for blocker in decision.blockers:
        field = fields_by_blocker.get(blocker.code)
        if field and field not in fields:
            fields.append(field)
    return (*fields, "actor", "request_id")


def _fixed_arguments(
    tool: str,
    operation: str,
    *,
    project_id: str,
    change_id: str,
    packet_id: str,
    spec_revision: int,
    plan_revision: int,
    decision_class: str,
) -> dict[str, object]:
    if tool == "fow_packet_author":
        arguments: dict[str, object] = {
            "project_id": project_id,
            "packet_id": packet_id,
            "operation": operation,
            "expected_spec_revision": spec_revision,
            "expected_plan_revision": plan_revision,
        }
        if operation == "start_packet":
            arguments = {
                "project_id": project_id,
                "change_id": change_id,
                "operation": operation,
                "purpose": "remediation",
                "predecessor_packet_id": packet_id,
            }
        return arguments
    if tool == "fow_external_work":
        arguments = {"project_id": project_id, "change_id": change_id,
                     "packet_id": packet_id, "operation": operation}
        if operation == "reconcile_outcome":
            arguments["payload"] = {"expected_spec_revision": spec_revision,
                                    "expected_plan_revision": plan_revision}
        elif operation == "set_mode":
            arguments["payload"] = {"mode": "external_agent", "expected_spec_revision": spec_revision,
                                    "expected_plan_revision": plan_revision}
        return arguments
    if tool == "fow_packet_advance":
        arguments: dict[str, object] = {
            "project_id": project_id,
            "packet_id": packet_id,
            "expected_spec_revision": spec_revision,
            "expected_plan_revision": plan_revision,
        }
        if decision_class == "semantic" and operation != "advance":
            arguments["decision"] = {"operation": operation}
        return arguments
    if tool == "fow_packet_inspect":
        return {
            "project_id": project_id,
            "packet_id": packet_id,
            "view": operation,
        }
    if tool == "fow_bootstrap":
        return {
            "project_id": project_id,
            "operation": operation,
        }
    if tool == "fow_assurance":
        return {
            "project_id": project_id,
            "change_id": change_id,
            "operation": operation,
        }
    return {}
