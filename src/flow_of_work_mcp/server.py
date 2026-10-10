"""Bounded MCP transport for the Flow of Work lifecycle control plane."""

from __future__ import annotations

import argparse
from pathlib import Path
from dataclasses import asdict
from typing import Annotated, Any, Callable, Literal, Mapping

from mcp.server.fastmcp import FastMCP
from pydantic import WithJsonSchema
from flow_of_work_mcp.application.bootstrap_input_contracts import bootstrap_input_schema

from flow_of_work_mcp.application.jobs import JobBlockedError
from flow_of_work_mcp.application.operation_contracts import (
    InteractionOperation,
    accepted_values_for_error,
    change_operation_ownership,
    operation_contract,
    operation_contract_index,
    operation_names,
    operation_tools,
    public_tool_catalog,
    public_tool_names,
    registry_version,
    render_tool_reference,
    work_area_catalog,
)
from flow_of_work_mcp.application.lifecycle_recipes import (
    all_recipes,
    get_recipe,
    list_recipes,
    recipe_names,
)
from flow_of_work_mcp.config import FlowConfigError, load_config
from flow_of_work_mcp.core.domain import (
    BehavioralExpectationDraft,
    BehavioralOracleDraft,
    CampaignCaseSemanticDraft,
    CampaignObligationDecision,
    CampaignScopeDraft,
    FindingDisposition,
    FindingDispositionDraft,
    FixingPacketLinkDraft,
    HandoverDraft,
    LifecycleStatus,
    MilestoneDraft,
    PacketConstructionAuditDraft,
    PacketAnswerTemporalAuthority,
    PacketQuestionResolutionDraft,
    PACKET_INACTIVE_STATUS_VALUES,
    PACKET_EVIDENCE_CONTRACT_VERSION,
    PacketEvidenceClaimDraft,
    PacketEvidenceClaimType,
    PacketEvidenceSnapshotDraft,
    ReconciliationItemDisposition,
    ReconciliationItemDispositionDraft,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    PhaseAuditScope,
    PacketStatus,
    PacketPurpose,
    PacketTransition,
    OracleAnswerAuthority,
    RequirementDraft,
    ReviewFindingDraft,
    ReviewFindingSeverity,
    RunCompletionDraft,
    RunDraft,
    RunStepDraft,
    SequenceDraft,
    SourceAnchor,
    UseCaseDraft,
    ValidationAuditRecord,
    VerificationDraft,
    VerificationKind,
    VerificationOutcome,
)
from flow_of_work_mcp.core.errors import (
    AssuranceBlockedError,
    BootstrapBlockedError,
    BootstrapStartConflictError,
    ChangeControlBlockedError,
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
    InputValidationError,
    LifecycleError,
    ProjectNotFoundError,
    RequirementConflictError,
    RequirementMutationBlockedError,
    RunControlBlockedError,
)
from flow_of_work_mcp.mcp_envelope import envelope
from flow_of_work_mcp.logger import LoggerManager, get_logger, log_bootstrap_error
from flow_of_work_mcp.mcp_runtime import McpRuntime
from flow_of_work_mcp.model_facing import (
    assert_projector_registry,
    model_facing_tool,
)
from flow_of_work_mcp.runtime_factory import RuntimeCompositionCleanupError, build_runtime_from_config


_CHANGE_OPERATION_OWNERSHIP = change_operation_ownership()

SERVER_INSTRUCTIONS = (
    "Flower MCP is a durable software-engineering lifecycle plane for any coding agent. "
    "The agent owns repository investigation, coding, builds and tests; Flower owns lifecycle authority. "
    "Call fow_interaction first with the host-provided interaction session "
    "reference; select one project and work area, then use its bounded frame. "
    "Use fow_capabilities only for expert contract or recipe inspection. "
    "Use fow_packet_author/inspect/advance for packet work and "
    "fow_campaign_author/inspect/advance for verification campaigns. "
    "Read content as model-facing Markdown; machine and provider integrations "
    "must consume structuredContent directly and never parse Markdown as JSON. "
    "Use fow_get_job only after "
    "an asynchronous operation has returned a durable job_id. "
    "Use fow_external_work for explicit external-agent mode, standalone plan validation, complete offline Markdown export and outcome reconciliation. "
    "Use fow_bindings for portable associations and fow_semantic for explicit bounded assignments; internal models and implementation providers are optional. "
    "Core operations never invoke inference automatically. Agent completion, verification and human acceptance are separate."
)


def _job_view(job) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "kind": job.kind,
        "status": job.status.value,
        "progress": job.progress,
        "terminal_reason": job.terminal_reason,
        "result": dict(job.result),
        "request_id": job.request_id,
    }


def _action_view(action) -> dict[str, object]:
    value = asdict(action)
    value["kind"] = action.kind.value
    value["execution_class"] = action.execution_class.value
    return value


_RECOVERY_DETAIL_LEVELS = frozenset({"standard", "audit"})
_RECOVERY_DEFAULT_LIMIT = 10
_RECOVERY_MAX_LIMIT = 100


def _recovery_page_args(
    detail_level: str,
    offset: int,
    limit: int,
) -> tuple[str, int, int]:
    detail = str(detail_level or "standard").strip().lower()
    if detail not in _RECOVERY_DETAIL_LEVELS:
        raise ValueError("detail_level must be standard or audit")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= _RECOVERY_MAX_LIMIT
    ):
        raise ValueError(f"limit must be between 1 and {_RECOVERY_MAX_LIMIT}")
    return detail, offset, limit


def _page(
    items: list[object], *, offset: int, limit: int
) -> tuple[list[object], dict[str, object]]:
    total = len(items)
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < total
    return page, {
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _standard_requirement_view(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "requirement_id": str(row.get("requirement_id") or ""),
        "title": str(row.get("title") or ""),
        "category": str(row.get("category") or ""),
        "lifecycle_status": str(row.get("lifecycle_status") or ""),
        "current_revision": int(row.get("current_revision") or 0),
        "verification": dict(row.get("verification") or {}),
    }


def _standard_traceability_row(row: Mapping[str, object]) -> dict[str, object]:
    live_readiness = dict(row.get("live_campaign_readiness") or {})
    return {
        "requirement_id": str(row.get("requirement_id") or ""),
        "lifecycle_status": str(row.get("lifecycle_status") or ""),
        "milestone_id": str(row.get("milestone_id") or ""),
        "verification": dict(row.get("verification") or {}),
        "milestone_acceptance": dict(row.get("milestone_acceptance") or {}),
        "tested_deterministically": str(row.get("tested_deterministically") or ""),
        "tested_live": str(row.get("tested_live") or ""),
        "coverage_state": str(row.get("coverage_state") or ""),
        "coverage_gaps": [str(item) for item in row.get("coverage_gaps", [])],
        "live_campaign_readiness": {
            "ready": bool(live_readiness.get("ready")),
            "state": str(live_readiness.get("state") or ""),
        },
        "acceptance_blockers": [
            str(item) for item in row.get("acceptance_blockers", [])
        ],
        "readiness_projection": dict(row.get("readiness_projection") or {}),
    }


def _standard_milestone_view(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "milestone_id": str(row.get("milestone_id") or ""),
        "name": str(row.get("name") or ""),
        "status": str(row.get("status") or ""),
        "requirement_count": len(row.get("requirement_ids", [])),
    }


def _standard_gap_view(row: Mapping[str, object]) -> dict[str, object]:
    requirement_ids = [str(item) for item in row.get("requirement_ids", [])]
    return {
        "reason": str(row.get("reason") or ""),
        "requirement_count": len(requirement_ids),
        "sample_requirement_ids": requirement_ids[:5],
        "truncated": len(requirement_ids) > 5,
    }


def _guard(
    tool: str,
    operation: Callable[[], dict[str, object]],
    *,
    recovery: Callable[[], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    try:
        return operation()
    except ProjectNotFoundError:
        return envelope(tool=tool, status="blocked", reason="project_not_found")
    except BootstrapStartConflictError as exc:
        return envelope(
            tool=tool, status="rejected", reason=exc.reason,
            result=_recovery_result(recovery, _bootstrap_start_conflict_result(exc)),
        )
    except RequirementConflictError:
        return envelope(
            tool=tool,
            status="rejected",
            reason="state_conflict",
            result=_recovery_result(recovery),
        )
    except RequirementMutationBlockedError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.reason,
            result=_recovery_result(recovery),
        )
    except BootstrapBlockedError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.reason,
            result=_recovery_result(recovery),
        )
    except ChangeControlBlockedError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.reason,
            result=_recovery_result(recovery, exc.details),
        )
    except AssuranceBlockedError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.reason,
            result=_recovery_result(recovery, exc.details),
        )
    except RunControlBlockedError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.reason,
            result=_recovery_result(recovery, exc.details),
        )
    except ImplementationProviderUnavailableError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.terminal_reason,
            result=_recovery_result(recovery),
        )
    except ImplementationProviderContractError as exc:
        return envelope(
            tool=tool,
            status="blocked",
            reason=exc.terminal_reason,
            result=_recovery_result(recovery, {"detail": str(exc)}),
        )
    except InputValidationError as exc:
        diagnostic: dict[str, object] = {
            "code": "invalid_input",
            "message": str(exc)[:500],
            "field": exc.field,
            "received_value": exc.received_value,
        }
        if exc.accepted_values:
            diagnostic["accepted_values"] = list(exc.accepted_values)
        return envelope(
            tool=tool,
            status="rejected",
            reason="invalid_input",
            result=_recovery_result(recovery, {"diagnostics": [diagnostic]}),
        )
    except (ValueError, TypeError) as exc:
        message = str(exc).strip() or "input validation failed"
        accepted_values = accepted_values_for_error(message)
        diagnostic: dict[str, object] = {
            "code": "invalid_input",
            "message": message[:500],
        }
        if accepted_values:
            diagnostic["accepted_values"] = list(accepted_values)
        if "operation is invalid" in message and operation_names(tool):
            diagnostic["accepted_values"] = list(operation_names(tool))
        return envelope(
            tool=tool,
            status="rejected",
            reason="invalid_input",
            result=_recovery_result(recovery, {"diagnostics": [diagnostic]}),
        )
    except LifecycleError:
        return envelope(
            tool=tool,
            status="blocked",
            reason="lifecycle_state_error",
            result=_recovery_result(recovery),
        )
    except Exception:
        return envelope(tool=tool, status="failed", reason="internal_error")


def _bootstrap_start_conflict_result(exc: BootstrapStartConflictError) -> dict[str, object]:
    context = exc.context
    arguments = {"project_id": context["project_id"], "actor": context["actor"]}
    if exc.reason == "bootstrap_project_name_conflict":
        if "bootstrap_id" in context:
            arguments.update(operation="state", bootstrap_id=context["bootstrap_id"])
            resolution = "The project name differs and a bootstrap is already active. Inspect that bootstrap; the registered name is shown in conflict context."
        else:
            arguments.update(operation="start", project_name=context["registered_project_name"],
                             path=context["path"], request_id=context["request_id"])
            resolution = "Use the registered project name. This does not rename the project; retry is explicit."
    else:
        arguments.update(operation="state", bootstrap_id=context["bootstrap_id"])
        resolution = {
            "bootstrap_already_active": "Inspect the existing bootstrap, then resume its current gate instead of starting another.",
            "guided_bootstrap_start_request_conflict": "Inspect the original request owner. Preserve its payload for replay; use a new request only for an explicitly new intent.",
        }[exc.reason]
    return {
        "conflict": {key: value for key, value in context.items() if key not in {"actor", "request_id"}},
        "diagnostics": [{"code": exc.reason, "message": str(exc), "resolution": resolution}],
        "next_tool_call": {"tool": "fow_bootstrap", "arguments": arguments},
    }


def _recovery_result(
    recovery: Callable[[], Mapping[str, object]] | None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = dict(details or {})
    if recovery is None:
        return result
    try:
        projection = recovery()
    except Exception:
        return result
    for key, value in projection.items():
        result.setdefault(str(key), value)
    return result


def _campaign_recovery_projection(
    runtime: McpRuntime,
    project_id: str,
    *,
    campaign_id: str = "",
    change_id: str = "",
) -> Mapping[str, object]:
    return runtime.campaign_authority.inspect(
        project_id,
        campaign_id=campaign_id,
        change_id=change_id,
        view="summary",
    )


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _require_mapping_fields(
    value: object, field: str, allowed: set[str]
) -> Mapping[str, object]:
    payload = _require_mapping(value, field)
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ValueError(f"{field} field is invalid: {unknown[0]}")
    return payload


def _require_boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _question_resolution_drafts(
    answers: list[Mapping[str, object]],
) -> tuple[PacketQuestionResolutionDraft, ...]:
    return tuple(
        PacketQuestionResolutionDraft(
            question_id=str(item.get("question_id") or ""),
            answer_summary=str(item.get("answer_summary") or ""),
            evidence_refs=tuple(
                _require_string_list(item.get("evidence_refs") or [], "evidence_refs")
            ),
            linked_navigation_refs=tuple(
                _require_string_list(
                    item.get("linked_navigation_refs") or [],
                    "linked_navigation_refs",
                )
            ),
            waiver_rationale=str(item.get("waiver_rationale") or ""),
            policy_ref=str(item.get("policy_ref") or ""),
            blocker_reason=str(item.get("blocker_reason") or ""),
            answer_source=str(item.get("answer_source") or "explicit"),
        )
        for item in answers[:64]
    )


def _optional_source_anchor(value: object) -> SourceAnchor | None:
    if value in (None, ""):
        return None
    source_anchor = _require_mapping(value, "source_anchor")
    source_path = str(source_anchor.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("source_anchor.source_path is required")
    try:
        line_start = int(source_anchor.get("line_start"))
        line_end = int(source_anchor.get("line_end"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "source_anchor line_start and line_end are required integers"
        ) from exc
    label = str(source_anchor.get("label") or "")
    return SourceAnchor(
        source_path=source_path,
        line_start=line_start,
        line_end=line_end,
        label=label,
    )


def handle_capabilities(
    runtime: McpRuntime,
    *,
    view: str = "summary",
    recipe_name: str = "",
    operation_tool: str = "",
    operation_name: str = "",
) -> dict[str, object]:
    selected_view = str(view or "summary").strip().lower()
    allowed_views = {"summary", "recipe", "operation", "docs", "full"}
    if selected_view not in allowed_views:
        raise ValueError("view must be summary, recipe, operation, docs, or full")

    optional_capabilities = [
        {
            "name": "internal_srs_semantic_execution",
            "reason": "explicit internal mode requires a configured ModelGateway; host SRS assignments are available through fow_semantic",
            "available": runtime.semantic_validation is not None,
        },
        {
            "name": "internal_intention_grounding",
            "reason": "requires both ModelGateway and ImplementationGraphProvider",
            "available": bool(runtime.grounding is not None and runtime.grounding.internal_available),
        },
        {
            "name": "internal_bootstrap_behavior_derivation",
            "reason": "requires both ModelGateway and BootstrapBehaviorProvider",
            "available": (
                runtime.semantic_validation is not None
                and runtime.bootstrap_behavior_provider is not None
            ),
        },
    ]
    version = registry_version()
    result_channels = {
        "model_facing": "content[].text contains operation-specific Markdown",
        "machine_facing": (
            "structuredContent.result contains the unchanged application envelope"
        ),
        "provider_rule": (
            "cross-server consumers use structuredContent directly and fail closed "
            "when it is absent; Markdown is never parsed as protocol JSON"
        ),
    }

    if selected_view == "operation":
        return envelope(
            tool="fow_capabilities",
            status="success",
            result={
                "view": "operation",
                "registry_version": version,
                "operation_contract": dict(
                    operation_contract(operation_tool, operation_name)
                ),
                "available_operation_tools": list(operation_tools()),
                "result_channels": result_channels,
            },
        )
    if selected_view == "recipe":
        selected_recipe = get_recipe(recipe_name)
        if selected_recipe is None:
            raise ValueError(
                "recipe_name must identify one of: " + ", ".join(recipe_names())
            )
        return envelope(
            tool="fow_capabilities",
            status="success",
            result={
                "view": "recipe",
                "registry_version": version,
                "recipe": selected_recipe,
                "available_recipe_names": list(recipe_names()),
                "result_channels": result_channels,
            },
        )
    if selected_view == "docs":
        return envelope(
            tool="fow_capabilities",
            status="success",
            result={
                "view": "docs",
                "registry_version": version,
                "areas": list(work_area_catalog()),
                "tool_reference": render_tool_reference(),
                "operation_detail": {
                    "view": "operation",
                    "required_inputs": ["operation_tool", "operation_name"],
                },
                "result_channels": result_channels,
            },
        )
    if selected_view == "full":
        return envelope(
            tool="fow_capabilities",
            status="success",
            result={
                "view": "full",
                "registry_version": version,
                "tools": list(public_tool_catalog()),
                "areas": list(work_area_catalog()),
                "recipes": all_recipes(),
                "change_operation_ownership": [
                    {
                        "operation": operation,
                        "owner": owner,
                        "classification": "distinct_live_operation",
                    }
                    for operation, owner in _CHANGE_OPERATION_OWNERSHIP.items()
                ],
                "operation_contracts": operation_contract_index(),
                "provider_configuration": {
                    "packet_provider": runtime.packet_provider_mode,
                    "test_provider": runtime.test_provider_mode,
                    "available_provider_kinds": list(
                        runtime.provider_bindings.available_provider_kinds()
                    ),
                },
                "unavailable_capabilities": optional_capabilities,
                "result_channels": result_channels,
            },
        )

    return envelope(
        tool="fow_capabilities",
        status="success",
        result={
            "view": "summary",
            "registry_version": version,
            "preferred_entrypoint": "fow_interaction",
            "interaction_contract": "flow.interaction-frame.v1",
            "orientation": (
                "Flower MCP supports standalone lifecycle planning for external coding agents. "
                "Select one explicit project and work area, then follow the current frame or exact operation help. "
                "Use standalone-external-plan, portable-associations and host-semantic-assignment recipes for independent operation."
            ),
            "standalone": {
                "core_requires_inference": False,
                "core_requires_provider": False,
                "external_work_tool": "fow_external_work",
                "association_tool": "fow_bindings",
                "semantic_assignment_tool": "fow_semantic",
                "host_semantic_roles": ["srs_semantic_validation", "intention_grounding"],
                "unsupported_host_roles": ["observed_behavior_drafting"],
                "cross_server_pvp": "deferred; standalone handoff only",
                "guided_bootstrap_policy": "approved progressive scenarios; engineering-bootstrap recipe",
            },
            "recipes": [{k:v for k,v in recipe.items() if k != "intent"} for recipe in list_recipes()],
            "provider_status": [
                {
                    "name": str(item["name"]),
                    "available": bool(item["available"]),
                }
                for item in optional_capabilities
            ],
            "detail_views": {
                "recipe": "one named semantic lifecycle policy",
                "operation": "one exact executable operation contract",
                "docs": "registry-derived tool and area reference",
                "full": "complete diagnostic indexes and policies",
            },
            "result_channels": result_channels,
        },
    )


def handle_packet_author(
    runtime: McpRuntime,
    *,
    project_id: str = "",
    change_id: str = "",
    packet_id: str = "",
    operation: str = "add_unit",
    title: str = "",
    intent: str = "",
    rationale: str = "",
    completion_criteria: list[str] | None = None,
    purpose: str = "implementation",
    milestone_id: str = "",
    requirement_ids: list[str] | None = None,
    goal_ids: list[str] | None = None,
    in_scope: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    invariants: list[str] | None = None,
    unresolved_questions: list[str] | None = None,
    target_policy: str = "code_targets_required",
    active_provider: str = "",
    source_revision: str = "",
    finding_ids: list[str] | None = None,
    predecessor_packet_id: str = "",
    predecessor_dependency_policy: str = "materialized",
    required_regression_evidence: str = "",
    required_campaign_ids: list[str] | None = None,
    work_plan: Mapping[str, object] | None = None,
    unit: Mapping[str, object] | None = None,
    target_selection: Mapping[str, object] | None = None,
    unit_patch: Mapping[str, object] | None = None,
    client_unit_key: str = "",
    depends_on: list[str] | None = None,
    actor: str,
    answers: list[Mapping[str, object]] | None = None,
    response: Mapping[str, object] | None = None,
    gate_fingerprint: str = "",
    expected_spec_revision: int = 0,
    expected_plan_revision: int | None = None,
    request_id: str = "",
) -> dict[str, object]:
    operation = str(operation or "add_unit").strip().lower()
    if not request_id:
        raise ValueError("request_id is required")
    if operation == "start_packet":
        if not project_id:
            raise ValueError("project_id is required")
        if not change_id:
            raise ValueError("change_id is required")
        with runtime.ledger.atomic():
            created = runtime.packet_factory.create_packet(
                project_id,
                change_id=change_id,
                packet=ImplementationPacketDraft(
                    title=title,
                    objective=intent,
                    rationale=rationale,
                    completion_criteria=_require_string_list(
                        completion_criteria or [], "completion_criteria"
                    ),
                    requirement_ids=_require_string_list(
                        requirement_ids or [], "requirement_ids"
                    ),
                    goal_ids=_require_string_list(goal_ids or [], "goal_ids"),
                    in_scope=_require_string_list(in_scope or [], "in_scope"),
                    out_of_scope=_require_string_list(
                        out_of_scope or [], "out_of_scope"
                    ),
                    invariants=_require_string_list(invariants or [], "invariants"),
                    unresolved_questions=_require_string_list(
                        unresolved_questions or [], "unresolved_questions"
                    ),
                    target_policy=target_policy,
                ),
                purpose=PacketPurpose(purpose),
                actor=actor,
                request_id=request_id,
                milestone_id=milestone_id,
                active_provider=active_provider,
                source_revision=source_revision,
                finding_ids=_require_string_list(finding_ids or [], "finding_ids"),
                predecessor_packet_id=predecessor_packet_id,
                predecessor_dependency_policy=predecessor_dependency_policy,
                required_regression_evidence=required_regression_evidence,
                required_campaign_ids=_require_string_list(
                    required_campaign_ids or [], "required_campaign_ids"
                ),
            )
            created_packet_id = str(created["packet_id"])
            created_spec_revision, _ = _current_packet_revisions(
                runtime, project_id, change_id, created_packet_id
            )
            provider_queue = runtime.packet_provider_overlay.queue_plan_delta(
                project_id,
                change_id,
                created_packet_id,
                flow_spec_revision=created_spec_revision,
                before=None,
                after=None,
                actor=actor,
                request_id=request_id,
            )
        lifecycle = runtime.packet_lifecycle.get_packet(
            project_id,
            change_id,
            created_packet_id,
            view="gates",
        )
        return envelope(
            tool="fow_packet_author",
            status="success",
            result={
                "packet": dict(created),
                "semantic_delta": {
                    "operation": "start_packet",
                    "purpose": str(created["purpose"]),
                },
                "provider_queue": dict(provider_queue),
                "gate": lifecycle.get("gate", {}),
                "next_action": lifecycle.get("next_action", {}),
            },
            audit_reference={
                "change_id": change_id,
                "packet_id": created_packet_id,
            },
        )

    project_id, change_id, packet_id = _resolve_packet_address(
        runtime,
        project_id=project_id,
        change_id=change_id,
        packet_id=packet_id,
    )
    runtime.packet_factory.ensure_packet_lifecycle(
        project_id,
        change_id,
        packet_id,
        actor=actor,
        request_id=f"{request_id}:repair",
    )
    change = runtime.changes.get_change(project_id, change_id)
    packet = next(
        (
            item
            for item in change.get("packets", [])
            if isinstance(item, Mapping)
            and str(item.get("packet_id") or "") == packet_id
        ),
        None,
    )
    if packet is None:
        raise ValueError(f"unknown packet in change: {packet_id}")
    current_plan = runtime.ledger.packet_work_plan_state(
        project_id,
        change_id,
        packet_id,
    )
    current_plan_revision = (
        int(current_plan.get("plan_revision") or 0) if current_plan else 0
    )
    expected_plan_revision = (
        expected_plan_revision
        if expected_plan_revision is not None
        else current_plan_revision
    )
    spec_revision = int(
        expected_spec_revision
        or packet.get("spec_revision")
        or packet.get("current_revision")
        or 0
    )
    answer_result: Mapping[str, object] | None = None
    audit_id = ""
    if operation == "add_unit":
        with runtime.ledger.atomic():
            authored = runtime.packet_unit_authoring.add_unit(
                project_id,
                change_id,
                packet_id,
                unit=unit,
                client_unit_key=client_unit_key,
                target_selection=target_selection,
                expected_spec_revision=(
                    expected_spec_revision if expected_spec_revision else None
                ),
                expected_plan_revision=expected_plan_revision,
                actor=actor,
                request_id=request_id,
            )
            after_plan = runtime.ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            current_spec_revision, _ = _current_packet_revisions(
                runtime, project_id, change_id, packet_id
            )
            provider_queue = runtime.packet_provider_overlay.queue_plan_delta(
                project_id,
                change_id,
                packet_id,
                flow_spec_revision=current_spec_revision,
                before=current_plan,
                after=after_plan,
                actor=actor,
                request_id=request_id,
            )
        lifecycle = runtime.packet_lifecycle.get_packet(
            project_id, change_id, packet_id, view="gates"
        )
        return envelope(
            tool="fow_packet_author",
            status="success",
            result={
                "unit_authoring": dict(authored),
                "current_authority": dict(zip(("expected_spec_revision", "expected_plan_revision"),
                    _current_packet_revisions(runtime, project_id, change_id, packet_id))),
                "provider_queue": dict(provider_queue),
                "semantic_delta": dict(authored.get("semantic_delta") or {}),
                "gate": dict(lifecycle.get("gate") or {}),
                "next_action": dict(lifecycle.get("next_action") or {}),
            },
            audit_reference={
                "change_id": change_id,
                "packet_id": packet_id,
                "client_unit_key": str(
                    (unit or {}).get("client_unit_key") or client_unit_key
                ),
            },
        )
    if operation == "revise_packet":
        semantic_fields_present = any(
            (
                bool(str(title or "").strip()),
                bool(str(intent or "").strip()),
                bool(str(rationale or "").strip()),
                completion_criteria is not None,
                requirement_ids is not None,
                goal_ids is not None,
                in_scope is not None,
                out_of_scope is not None,
                invariants is not None,
                unresolved_questions is not None,
            )
        )
        if not semantic_fields_present:
            raise ValueError("revise_packet requires at least one packet field")

        current_spec_revision = int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        )
        replayed = any(
            isinstance(event, Mapping)
            and str(event.get("event_type") or "") == "packet_revised"
            and str(event.get("packet_id") or "") == packet_id
            and str(event.get("request_id") or "") == request_id
            for event in change.get("events", [])
        )
        if not replayed:
            if (
                expected_spec_revision
                and expected_spec_revision != current_spec_revision
            ):
                raise ChangeControlBlockedError(
                    "stale_packet_revision",
                    details={
                        "expected_spec_revision": current_spec_revision,
                        "received_spec_revision": expected_spec_revision,
                    },
                )
            if (
                expected_plan_revision is not None
                and int(expected_plan_revision) != current_plan_revision
            ):
                raise ChangeControlBlockedError(
                    "stale_current_work_plan_revision",
                    details={
                        "expected_plan_revision": current_plan_revision,
                        "received_plan_revision": int(expected_plan_revision),
                    },
                )

        plan_result: Mapping[str, object] | None = None
        with runtime.ledger.atomic():
            refined = runtime.changes.refine_packet(
                project_id,
                change_id,
                packet_id,
                title=title,
                objective=intent,
                rationale=rationale,
                requirement_ids=(
                    tuple(_require_string_list(requirement_ids, "requirement_ids"))
                    if requirement_ids is not None
                    else None
                ),
                goal_ids=(
                    tuple(_require_string_list(goal_ids, "goal_ids"))
                    if goal_ids is not None
                    else None
                ),
                in_scope=(
                    tuple(_require_string_list(in_scope, "in_scope"))
                    if in_scope is not None
                    else None
                ),
                out_of_scope=(
                    tuple(_require_string_list(out_of_scope, "out_of_scope"))
                    if out_of_scope is not None
                    else None
                ),
                invariants=(
                    tuple(_require_string_list(invariants, "invariants"))
                    if invariants is not None
                    else None
                ),
                unresolved_questions=(
                    tuple(
                        _require_string_list(
                            unresolved_questions, "unresolved_questions"
                        )
                    )
                    if unresolved_questions is not None
                    else None
                ),
                completion_criteria=(
                    tuple(
                        _require_string_list(completion_criteria, "completion_criteria")
                    )
                    if completion_criteria is not None
                    else None
                ),
                readiness_state="draft",
                readiness_blockers=(),
                actor=actor,
                request_id=request_id,
            )
            refined_packet = next(
                item
                for item in refined.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("packet_id") or "") == packet_id
            )
            refined_spec_revision = int(
                refined_packet.get("spec_revision")
                or refined_packet.get("current_revision")
                or 0
            )
            if current_plan is not None and not replayed:
                plan_result = runtime.packet_work_plan.set_plan(
                    project_id,
                    change_id,
                    packet_id,
                    {"units": list(current_plan.get("units") or [])},
                    expected_packet_revision=refined_spec_revision,
                    expected_current_plan_revision=current_plan_revision,
                    actor=actor,
                    request_id=f"{request_id}:plan",
                )
                plan_result = runtime.ledger.finalize_packet_authoring_revision(
                    project_id,
                    str(plan_result["work_plan_id"]),
                    int(plan_result["plan_revision"]),
                )
            elif current_plan is not None:
                plan_result = runtime.ledger.packet_work_plan_state(
                    project_id, change_id, packet_id
                )

            final_change = runtime.changes.get_change(project_id, change_id)
            final_packet = next(
                item
                for item in final_change.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("packet_id") or "") == packet_id
            )
            final_spec_revision = int(
                final_packet.get("spec_revision")
                or final_packet.get("current_revision")
                or 0
            )

        lifecycle = runtime.packet_lifecycle.get_packet(
            project_id, change_id, packet_id, view="gates"
        )
        return envelope(
            tool="fow_packet_author",
            status="success",
            result={
                "packet": {
                    "project_id": project_id,
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "spec_revision": final_spec_revision,
                    "plan_revision": int((plan_result or {}).get("plan_revision") or 0),
                    "plan_status": str((plan_result or {}).get("status") or ""),
                },
                "semantic_delta": {
                    "operation": "revise_packet",
                    "semantic_revision": final_spec_revision,
                    "plan_revision": int((plan_result or {}).get("plan_revision") or 0),
                    "replayed": replayed,
                },
                "gate": dict(lifecycle.get("gate") or {}),
                "next_action": dict(lifecycle.get("next_action") or {}),
            },
            audit_reference={"change_id": change_id, "packet_id": packet_id},
        )
    if operation == "answer_gate":
        current = runtime.packet_lifecycle.get_packet(
            project_id, change_id, packet_id, view="gates"
        )
        gate = _require_mapping(current.get("gate"), "gate")
        received_fingerprint = str(gate_fingerprint or "").strip()
        if not received_fingerprint:
            raise ValueError("answer_gate requires gate_fingerprint")
        if received_fingerprint != str(gate.get("dependency_fingerprint") or ""):
            raise ChangeControlBlockedError(
                "stale_packet_gate",
                details={"refreshed_gate": dict(gate)},
            )
        gate_response = _require_mapping(response, "response")
        decision = _require_mapping(
            gate.get("decision_required"), "gate.decision_required"
        )
        if str(decision.get("kind") or "") != "engineering_question":
            raise ChangeControlBlockedError(
                "packet_gate_response_not_current",
                details={"current_gate": dict(gate)},
            )
        audit = runtime.packet_construction.audit_for_packet(
            project_id, change_id, packet_id
        )
        if audit is None:
            raise ChangeControlBlockedError("packet_construction_audit_missing")
        open_questions = [
            item
            for item in audit.get("questions", [])
            if isinstance(item, Mapping)
            and bool(item.get("required"))
            and str(item.get("status") or "") in {"open", "blocked"}
        ]
        if not open_questions:
            raise ChangeControlBlockedError("packet_engineering_question_missing")
        question = open_questions[0]
        question_category = str(question.get("category") or "")
        reconciliation = runtime.packet_reconciliation.get(
            project_id,
            change_id=change_id,
            packet_id=packet_id,
        )
        claim_translation_available = (
            reconciliation is not None
            and question_category in {"target_selection", "impact"}
        )
        claim_fields = (
            "classification",
            "subject_ref",
            "predicate",
            "object_ref",
            "assertion",
        )
        supplied_claim_fields = [
            field for field in claim_fields if gate_response.get(field)
        ]
        temporal_authority = str(gate_response.get("temporal_authority") or "").strip()
        if supplied_claim_fields and not claim_translation_available:
            spec_revision, plan_revision = _current_packet_revisions(
                runtime, project_id, change_id, packet_id
            )
            return envelope(
                tool="fow_packet_author",
                status="blocked",
                reason="packet_reconciliation_fields_not_applicable",
                result={
                    "invalid_fields": supplied_claim_fields,
                    "preserved_state": {
                        "project_id": project_id,
                        "change_id": change_id,
                        "packet_id": packet_id,
                        "spec_revision": spec_revision,
                        "plan_revision": plan_revision,
                    },
                    "gate": dict(gate),
                    "next_action": dict(current.get("next_action") or {}),
                },
                audit_reference={"change_id": change_id, "packet_id": packet_id},
            )
        if claim_translation_available:
            try:
                answer_authority = PacketAnswerTemporalAuthority(temporal_authority)
            except ValueError as exc:
                raise ValueError(
                    "PacketAnswerTemporalAuthority is required for target/impact "
                    "answers"
                ) from exc
            if answer_authority == PacketAnswerTemporalAuthority.CURRENT_FACT:
                if supplied_claim_fields and not gate_response.get("classification"):
                    raise ValueError(
                        "a structured current_fact claim requires response.classification"
                    )
            elif supplied_claim_fields:
                raise ValueError(
                    f"{answer_authority.value} cannot carry current claim fields: "
                    + ", ".join(supplied_claim_fields)
                )
        elif temporal_authority:
            raise ValueError(
                "response.temporal_authority is only valid for target/impact answers"
            )
        audit_id = str(audit["construction_audit_id"])
        disposition = str(gate_response.get("disposition") or "answered").strip()
        answer_draft = PacketQuestionResolutionDraft(
            question_id=str(question["question_id"]),
            answer_summary=str(
                gate_response.get("answer_summary")
                or gate_response.get("rationale")
                or gate_response.get("classification")
                or ""
            ),
            evidence_refs=tuple(
                _require_string_list(
                    gate_response.get("evidence_refs") or [], "response.evidence_refs"
                )
            ),
            waiver_rationale=(
                str(gate_response.get("rationale") or "")
                if disposition == "waived"
                else ""
            ),
            policy_ref=str(gate_response.get("policy_ref") or ""),
            blocker_reason=(
                str(gate_response.get("rationale") or "")
                if disposition == "blocked"
                else ""
            ),
            answer_source="explicit",
        )
        with runtime.ledger.atomic():
            if (
                claim_translation_available
                and answer_authority == PacketAnswerTemporalAuthority.CURRENT_FACT
                and bool(gate_response.get("classification"))
            ):
                category = question_category
                runtime.packet_reconciliation.answer_gate(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    gate_kind=(
                        "target" if category == "target_selection" else "impact"
                    ),
                    subject_ref=str(gate_response.get("subject_ref") or ""),
                    predicate=str(
                        gate_response.get("predicate")
                        or (
                            "selected_target"
                            if category == "target_selection"
                            else "impact_classification"
                        )
                    ),
                    object_ref=str(
                        gate_response.get("object_ref")
                        or gate_response.get("classification")
                        or ""
                    ),
                    assertion={
                        **dict(gate_response.get("assertion") or {}),
                        "classification": str(
                            gate_response.get("classification") or ""
                        ),
                    },
                    evidence_refs=answer_draft.evidence_refs,
                    actor=actor,
                    request_id=f"{request_id}:claim",
                )
            if disposition == "waived":
                answer_result = runtime.packet_construction.waive_question(
                    project_id,
                    audit_id,
                    answer_draft,
                    actor=actor,
                    request_id=request_id,
                )
            elif disposition == "blocked":
                answer_result = runtime.packet_construction.block_question(
                    project_id,
                    audit_id,
                    answer_draft,
                    actor=actor,
                    request_id=request_id,
                )
            elif disposition == "answered":
                answer_result = runtime.packet_construction.answer_question(
                    project_id,
                    audit_id,
                    answer_draft,
                    actor=actor,
                    request_id=request_id,
                )
            else:
                raise ValueError(
                    "response.disposition must be answered, waived or blocked"
                )
            current_plan = runtime.ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            if current_plan is not None:
                runtime.ledger.finalize_packet_authoring_revision(
                    project_id,
                    str(current_plan["work_plan_id"]),
                    int(current_plan["plan_revision"]),
                    construction_audit_id=audit_id,
                )
        lifecycle = runtime.packet_lifecycle.get_packet(
            project_id, change_id, packet_id, view="gates"
        )
        return envelope(
            tool="fow_packet_author",
            status="success",
            result={
                "semantic_delta": {
                    "operation": "answer_gate",
                    "decision_kind": "engineering_question",
                    "category": str(question.get("category") or ""),
                    "disposition": disposition,
                    **(
                        {"temporal_authority": answer_authority.value}
                        if claim_translation_available
                        else {}
                    ),
                },
                "gate": dict(lifecycle.get("gate") or {}),
                "next_action": dict(lifecycle.get("next_action") or {}),
            },
            audit_reference={"change_id": change_id, "packet_id": packet_id},
        )
    with runtime.ledger.atomic():
        if operation == "resolve_questions":
            if not answers:
                raise ValueError("resolve_questions requires answers")
            audit = runtime.packet_construction.audit_for_packet(
                project_id, change_id, packet_id
            )
            if audit is None:
                raise ChangeControlBlockedError("packet_construction_audit_missing")
            audit_id = str(audit["construction_audit_id"])
            answer_result = runtime.packet_construction.resolve_questions_batch(
                project_id,
                audit_id,
                _question_resolution_drafts(answers),
                expected_spec_revision=spec_revision,
                actor=actor,
                request_id=request_id,
            )
            result = runtime.ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            if result is None:
                raise ChangeControlBlockedError("packet_work_plan_missing")
        elif operation == "replace_plan":
            result = runtime.packet_work_plan.set_plan(
                project_id,
                change_id,
                packet_id,
                _require_mapping(work_plan, "work_plan"),
                expected_packet_revision=spec_revision,
                expected_current_plan_revision=expected_plan_revision,
                actor=actor,
                request_id=request_id,
            )
        else:
            if answers:
                raise ValueError(
                    "answers are only valid with replace_plan or resolve_questions"
                )
            result = runtime.packet_work_plan.mutate_plan(
                project_id,
                change_id,
                packet_id,
                operation=operation,
                expected_packet_revision=spec_revision,
                expected_current_plan_revision=int(expected_plan_revision),
                actor=actor,
                request_id=request_id,
                client_unit_key=client_unit_key,
                unit=unit,
                unit_patch=unit_patch,
                depends_on=depends_on,
            )
        if answers and operation == "replace_plan":
            audit = runtime.packet_construction.audit_for_packet(
                project_id, change_id, packet_id
            )
            if audit is None:
                audit = runtime.packet_construction.start_audit(
                    project_id,
                    PacketConstructionAuditDraft(
                        change_id=change_id, packet_id=packet_id
                    ),
                    actor=actor,
                    request_id=f"{request_id}:questions" if request_id else "",
                )
            audit_id = str(audit["construction_audit_id"])
            answer_result = runtime.packet_construction.resolve_questions_batch(
                project_id,
                audit_id,
                _question_resolution_drafts(answers),
                expected_spec_revision=int(result["packet_revision"]),
                actor=actor,
                request_id=f"{request_id}:answers" if request_id else "",
            )
        result = runtime.ledger.finalize_packet_authoring_revision(
            project_id,
            str(result["work_plan_id"]),
            int(result["plan_revision"]),
            construction_audit_id=audit_id,
        )
        provider_queue: Mapping[str, object] | None = None
        if operation in {
            "replace_plan",
            "revise_unit",
            "remove_unit",
            "rebind_unit",
            "set_dependencies",
        }:
            current_spec_revision, _ = _current_packet_revisions(
                runtime, project_id, change_id, packet_id
            )
            provider_queue = runtime.packet_provider_overlay.queue_plan_delta(
                project_id,
                change_id,
                packet_id,
                flow_spec_revision=current_spec_revision,
                before=current_plan,
                after=result,
                actor=actor,
                request_id=request_id,
            )
    guard = runtime.packet_guards.evaluate(project_id, change_id, packet_id)
    current_spec_revision, current_plan_revision = _current_packet_revisions(
        runtime,
        project_id,
        change_id,
        packet_id,
    )
    next_action = runtime.packet_next_action.project(
        guard,
        project_id=project_id,
        change_id=change_id,
        packet_id=packet_id,
        spec_revision=current_spec_revision,
        plan_revision=current_plan_revision,
    )
    preview = runtime.packet_work_plan.preview(
        project_id,
        change_id,
        packet_id,
        plan_revision=int(result["plan_revision"]),
        detail_level="standard",
    )
    lifecycle = runtime.packet_lifecycle.get_packet(
        project_id, change_id, packet_id, view="gates"
    )
    return envelope(
        tool="fow_packet_author",
        status="success",
        result={
            "packet": {
                "project_id": project_id,
                "change_id": change_id,
                "packet_id": packet_id,
                "spec_revision": result["packet_revision"],
                "plan_revision": result["plan_revision"],
                "plan_status": result["status"],
            },
            "mutation": {
                "operation": operation,
                "affected_unit_key": str(result.get("affected_unit_key") or ""),
            },
            "engineering_questions": answer_result or {},
            "provider_queue": dict(provider_queue or {}),
            "warnings": list(preview.get("warnings") or []),
            "semantic_delta": {
                "operation": operation,
                "affected_unit_key": str(result.get("affected_unit_key") or ""),
                "plan_revision": int(result.get("plan_revision") or 0),
                "semantic_revision": current_spec_revision,
            },
            "gate": dict(lifecycle.get("gate") or {}),
            "next_action": dict(lifecycle.get("next_action") or next_action),
        },
        audit_reference={
            "change_id": change_id,
            "packet_id": packet_id,
            "work_plan_id": result["work_plan_id"],
        },
    )


def _current_packet_revisions(
    runtime: McpRuntime,
    project_id: str,
    change_id: str,
    packet_id: str,
) -> tuple[int, int]:
    change = runtime.changes.get_change(project_id, change_id)
    packet = next(
        (
            item
            for item in change.get("packets", [])
            if isinstance(item, Mapping)
            and str(item.get("packet_id") or "") == packet_id
        ),
        None,
    )
    if packet is None:
        raise ValueError(f"unknown packet in change: {packet_id}")
    plan = runtime.ledger.packet_work_plan_state(
        project_id,
        change_id,
        packet_id,
    )
    return (
        int(packet.get("spec_revision") or packet.get("current_revision") or 0),
        int(plan.get("plan_revision") or 0) if plan else 0,
    )


def _resolve_packet_address(
    runtime: McpRuntime,
    *,
    project_id: str,
    packet_id: str,
    change_id: str = "",
) -> tuple[str, str, str]:
    project = str(project_id or "").strip()
    packet = str(packet_id or "").strip()
    requested_change = str(change_id or "").strip()
    if not project:
        raise ValueError("project_id is required")
    if not packet:
        raise ValueError("packet_id is required")
    if requested_change:
        change = runtime.changes.get_change(project, requested_change)
        if not any(
            isinstance(item, Mapping) and str(item.get("packet_id") or "") == packet
            for item in change.get("packets", [])
        ):
            raise ValueError(f"unknown packet in change: {packet}")
        return project, requested_change, packet
    return project, runtime.changes.packet_change_id(project, packet), packet


def handle_packet_inspect(
    runtime: McpRuntime,
    *,
    project_id: str = "",
    change_id: str = "",
    packet_id: str = "",
    detail_level: str = "standard",
    view: str = "summary",
    offset: int = 0,
    limit: int = _RECOVERY_DEFAULT_LIMIT,
) -> dict[str, object]:
    project_id, change_id, packet_id = _resolve_packet_address(
        runtime,
        project_id=project_id,
        change_id=change_id,
        packet_id=packet_id,
    )
    runtime.packet_factory.ensure_packet_lifecycle(
        project_id,
        change_id,
        packet_id,
        actor="system:packet-inspect",
        request_id=f"inspect-repair:{packet_id}",
    )
    detail = str(detail_level or "standard").strip().lower()
    if detail not in {"standard", "audit"}:
        raise ValueError("detail_level must be standard or audit")
    result = runtime.packet_lifecycle.get_packet(
        project_id,
        change_id,
        packet_id,
        detail_level="verbose" if detail == "audit" else "standard",
        view=view,
        offset=offset,
        limit=limit,
    )
    return envelope(
        tool="fow_packet_inspect",
        status="success",
        result={"packet": dict(result)},
        audit_reference={"change_id": change_id, "packet_id": packet_id},
    )


def handle_packet_advance(
    runtime: McpRuntime,
    *,
    project_id: str = "",
    change_id: str = "",
    packet_id: str = "",
    actor: str,
    request_id: str,
    decision: Mapping[str, object] | None = None,
    expected_spec_revision: int | None = None,
    expected_plan_revision: int | None = None,
) -> dict[str, object]:
    project_id, change_id, packet_id = _resolve_packet_address(
        runtime,
        project_id=project_id,
        change_id=change_id,
        packet_id=packet_id,
    )
    runtime.packet_factory.ensure_packet_lifecycle(
        project_id,
        change_id,
        packet_id,
        actor=actor,
        request_id=f"{request_id}:repair",
    )
    result = runtime.packet_advancement.advance(
        project_id,
        change_id,
        packet_id,
        actor=actor,
        request_id=request_id,
        decision=decision,
        expected_spec_revision=expected_spec_revision,
        expected_plan_revision=expected_plan_revision,
    )
    lifecycle = runtime.packet_lifecycle.get_packet(
        project_id, change_id, packet_id, view="gates"
    )
    return envelope(
        tool="fow_packet_advance",
        status="success",
        result={
            "advancement": dict(result),
            "gate": dict(lifecycle.get("gate") or {}),
            "next_action": dict(lifecycle.get("next_action") or {}),
        },
        audit_reference={"change_id": change_id, "packet_id": packet_id},
    )


def handle_create_project(
    runtime: McpRuntime, *, project_id: str, name: str, actor: str, request_id: str = ""
) -> dict[str, object]:
    return _guard(
        "fow_create_project",
        lambda: envelope(
            tool="fow_create_project",
            status="success",
            result=dict(
                runtime.requirements.create_project(project_id, name, actor=actor)
            ),
        ),
    )


def handle_bootstrap(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str,
    project_name: str = "",
    path: str = "",
    bootstrap_id: str = "",
    answer: Mapping[str, object] | None = None,
    correspondence: Mapping[str, object] | None = None,
    milestone_ids: list[str] | None = None,
    roadmap_fingerprint: str = "",
    continuation_choice: str = "",
    continuation_reference: str = "",
    progress_revision: str = "",
    intake: Mapping[str, object] | None = None,
    contradiction: Mapping[str, object] | None = None,
    confirmation_reference: str = "",
    completion_reference: str = "",
    reason: str = "",
    provider_kind: str = "",
    provider_scope_id: str = "",
    provider_context_id: str = "",
    surfaces: list[str] | None = None,
    replacement_reason: str = "",
    request_id: str = "",
) -> dict[str, object]:
    """Apply one bounded bootstrap transition and return its durable state."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "bind_implementation_provider":
            result = runtime.provider_bindings.bind(
                project_id,
                provider_kind=provider_kind,
                scope_id=provider_scope_id,
                provider_context_id=provider_context_id,
                surfaces=tuple(_require_string_list(surfaces or [], "surfaces")),
                actor=actor,
                replacement_reason=replacement_reason,
                request_id=request_id,
            )
            return envelope(
                tool="fow_bootstrap",
                status="success",
                result={"provider_binding": dict(result)},
                audit_reference={
                    "project_id": project_id,
                    "provider_kind": result.get("provider_kind", ""),
                    "binding_revision": result.get("revision", 0),
                },
            )
        if selected == "provider_binding_state":
            result = runtime.provider_bindings.get(project_id, provider_kind)
            return envelope(
                tool="fow_bootstrap",
                status="success",
                result={"provider_binding": dict(result)},
            )
        if selected == "list_provider_bindings":
            return envelope(
                tool="fow_bootstrap",
                status="success",
                result={
                    "provider_bindings": [
                        dict(item)
                        for item in runtime.provider_bindings.list(project_id)
                    ]
                },
            )
        if selected == "start":
            result = runtime.bootstrap.start(
                project_id,
                project_name=project_name,
                path=path,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "resume":
            result = runtime.bootstrap.resume(
                project_id, bootstrap_id, actor=actor, request_id=request_id
            )
        elif selected == "state":
            result = runtime.bootstrap.state(project_id, bootstrap_id)
        elif selected == "record_intake":
            result = runtime.bootstrap.record_intake(
                project_id,
                bootstrap_id,
                intake=_require_mapping(intake, "intake"),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "record_contradiction":
            result = runtime.bootstrap.record_contradiction(
                project_id,
                bootstrap_id,
                contradiction=_require_mapping(contradiction, "contradiction"),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "confirm_intake":
            result = runtime.bootstrap.confirm_intake(
                project_id,
                bootstrap_id,
                confirmation_reference=confirmation_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "derive_behavior":
            result = runtime.bootstrap.derive_behavior(
                project_id, bootstrap_id, actor=actor, request_id=request_id
            )
        elif selected == "guidance":
            result = runtime.guided_bootstrap.guidance(project_id, bootstrap_id)
        elif selected == "record_answer":
            result = runtime.guided_bootstrap.record_answer(project_id, bootstrap_id,
                answer=answer, actor=actor, request_id=request_id)
        elif selected == "record_correspondence":
            result = runtime.guided_bootstrap.record_correspondence(project_id, bootstrap_id,
                correspondence=correspondence, actor=actor, request_id=request_id)
        elif selected == "roadmap":
            result = runtime.guided_bootstrap.roadmap(project_id, bootstrap_id, milestone_ids=milestone_ids or [])
        elif selected == "confirm_roadmap":
            result = runtime.guided_bootstrap.confirm_roadmap(project_id, bootstrap_id,
                milestone_ids=milestone_ids or [], roadmap_fingerprint=roadmap_fingerprint,
                confirmation_reference=confirmation_reference, actor=actor, request_id=request_id)
        elif selected == "record_continuation":
            result = runtime.guided_bootstrap.record_continuation(project_id, bootstrap_id,
                continuation_choice=continuation_choice, continuation_reference=continuation_reference,
                roadmap_fingerprint=roadmap_fingerprint, progress_revision=progress_revision,
                reason=reason, actor=actor, request_id=request_id)
        elif selected == "complete":
            service = (runtime.guided_bootstrap if runtime.bootstrap.state(project_id, bootstrap_id)["path"] == "guided_engineering" else runtime.bootstrap)
            result = service.complete(
                project_id,
                bootstrap_id,
                completion_reference=completion_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "cancel":
            result = runtime.bootstrap.cancel(
                project_id,
                bootstrap_id,
                reason=reason,
                actor=actor,
                request_id=request_id,
            )
        else:
            raise ValueError("bootstrap operation is invalid")
        return envelope(
            tool="fow_bootstrap",
            status="success",
            result={"bootstrap": dict(result)},
            audit_reference={"bootstrap_id": result.get("bootstrap_id", "")},
        )

    return _guard("fow_bootstrap", operation_fn)


def handle_change(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str,
    change_id: str = "",
    packet_id: str = "",
    depends_on_packet_id: str = "",
    title: str = "",
    rationale: str = "",
    requirement_ids: list[str] | None = None,
    goal_ids: list[str] | None = None,
    in_scope: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    invariants: list[str] | None = None,
    unresolved_questions: list[str] | None = None,
    source_refs: list[str] | None = None,
    baseline_refs: list[str] | None = None,
    completion_criteria: list[str] | None = None,
    milestone_id: str = "",
    intent: str = "",
    target_policy: str = "",
    active_provider: str = "",
    source_revision: str = "",
    navigation_audit_id: str = "",
    navigation_audit_ids: list[str] | None = None,
    provider: str = "",
    candidate_set_id: str = "",
    candidate_set_ids: list[str] | None = None,
    target_binding_ids: list[str] | None = None,
    context_snapshot_id: str = "",
    context_snapshot_ids: list[str] | None = None,
    summary: str = "",
    diagnostics: list[str] | None = None,
    target_state: str = "",
    truncated: bool = False,
    packet_status: str = "",
    criterion_results: Mapping[str, object] | None = None,
    blocking_reasons: list[str] | None = None,
    disposition: str = "",
    successor_packet_id: str = "",
    construction_audit_id: str = "",
    question_id: str = "",
    evidence_refs: list[str] | None = None,
    linked_navigation_refs: list[str] | None = None,
    answer_summary: str = "",
    waiver_rationale: str = "",
    policy_ref: str = "",
    profile: str = "balanced",
    pressure_id: str = "",
    accepted_risk_ref: str = "",
    provider_id: str = "",
    reconciliation_scope_id: str = "",
    reconciliation_profile: str = "target-impact-v1",
    claim_id: str = "",
    claim_type: str = "",
    claim_key: str = "",
    subject_ref: str = "",
    predicate: str = "",
    object_ref: str = "",
    assertion: Mapping[str, object] | None = None,
    claim_required: bool = True,
    claim_dynamic: bool = False,
    claim_contradicted: bool = False,
    contract_version: str = PACKET_EVIDENCE_CONTRACT_VERSION,
    provider_scope_id: str = "",
    provider_snapshot_id: str = "",
    selection_ref: str = "",
    workspace_revision: str = "",
    surfaces: list[str] | None = None,
    fingerprint: str = "",
    completeness: Mapping[str, object] | None = None,
    claims: list[dict[str, object]] | None = None,
    snapshot_id: str = "",
    reconciliation_item_id: str = "",
    reconciliation_disposition: str = "",
    max_claims: int = 512,
    max_depth: int = 4,
    request_id: str = "",
) -> dict[str, object]:
    """Apply one bounded governed-change operation."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected not in _CHANGE_OPERATION_OWNERSHIP:
            raise ValueError("change operation is invalid")
        if selected == "create_change":
            result = runtime.changes.create_change(
                project_id,
                GovernedChangeDraft(
                    title=title,
                    rationale=rationale,
                    requirement_ids=_require_string_list(
                        requirement_ids or [], "requirement_ids"
                    ),
                    source_refs=_require_string_list(source_refs or [], "source_refs"),
                    baseline_refs=_require_string_list(
                        baseline_refs or [], "baseline_refs"
                    ),
                    milestone_id=milestone_id,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "get_change":
            result = runtime.changes.get_change(project_id, change_id)
        elif selected == "link_change_milestone":
            result = runtime.changes.link_change_milestone(
                project_id,
                change_id,
                milestone_id,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "set_packet_target_state":
            result = runtime.changes.set_packet_target_state(
                project_id,
                change_id,
                packet_id,
                target_policy=target_policy,
                readiness_state=target_state,
                navigation_audit_ids=_require_string_list(
                    navigation_audit_ids
                    or ([navigation_audit_id] if navigation_audit_id else []),
                    "navigation_audit_ids",
                ),
                target_binding_ids=_require_string_list(
                    target_binding_ids or [], "target_binding_ids"
                ),
                candidate_set_ids=_require_string_list(
                    candidate_set_ids
                    or ([candidate_set_id] if candidate_set_id else []),
                    "candidate_set_ids",
                ),
                context_snapshot_ids=_require_string_list(
                    context_snapshot_ids
                    or ([context_snapshot_id] if context_snapshot_id else []),
                    "context_snapshot_ids",
                ),
                readiness_blockers=_require_string_list(
                    blocking_reasons or [], "readiness_blockers"
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_delta": _packet_target_delta(result, packet_id)},
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                },
            )
        elif selected == "evaluate_packet_readiness":
            result = runtime.changes.evaluate_packet_readiness(
                project_id,
                change_id,
                packet_id,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "start_packet_construction_audit":
            result = runtime.packet_construction.start_audit(
                project_id,
                PacketConstructionAuditDraft(
                    milestone_id=milestone_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    profile=profile,
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_construction_audit": dict(result)},
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "construction_audit_id": result.get("construction_audit_id", ""),
                },
            )
        elif selected == "get_packet_construction_audit":
            result = (
                runtime.packet_construction.get_audit(project_id, construction_audit_id)
                if construction_audit_id
                else runtime.packet_construction.audit_for_packet(
                    project_id, change_id, packet_id
                )
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={
                    "packet_construction_audit": {} if result is None else dict(result)
                },
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "construction_audit_id": construction_audit_id,
                },
            )
        elif selected == "initialize_packet_reconciliation":
            result = runtime.packet_reconciliation.initialize(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                profile=reconciliation_profile,
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_reconciliation": dict(result)},
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "reconciliation_scope_id": result.get(
                        "reconciliation_scope_id", ""
                    ),
                },
            )
        elif selected == "get_packet_reconciliation":
            result = runtime.packet_reconciliation.get(
                project_id,
                reconciliation_scope_id=reconciliation_scope_id,
                change_id=change_id,
                packet_id=packet_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={
                    "packet_reconciliation": {} if result is None else dict(result)
                },
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "reconciliation_scope_id": reconciliation_scope_id,
                },
            )
        elif selected == "declare_packet_evidence_claim":
            result = runtime.packet_reconciliation.declare_claim(
                project_id,
                reconciliation_scope_id,
                PacketEvidenceClaimDraft(
                    claim_type=PacketEvidenceClaimType(claim_type),
                    claim_key=claim_key,
                    subject_ref=subject_ref,
                    predicate=predicate,
                    object_ref=object_ref,
                    assertion=_require_mapping(assertion or {}, "assertion"),
                    evidence_refs=_require_string_list(
                        evidence_refs or [], "evidence_refs"
                    ),
                    required=claim_required,
                    dynamic=claim_dynamic,
                    contradicted=claim_contradicted,
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_evidence_claim": dict(result)},
                audit_reference={
                    "reconciliation_scope_id": reconciliation_scope_id,
                    "claim_id": result.get("claim_id", ""),
                },
            )
        elif selected == "supersede_packet_evidence_claim":
            result = runtime.packet_reconciliation.supersede_claim(
                project_id,
                claim_id,
                rationale=rationale,
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_evidence_claim": dict(result)},
                audit_reference={"claim_id": claim_id},
            )
        elif selected == "import_packet_evidence_snapshot":
            result = runtime.packet_reconciliation.import_snapshot(
                project_id,
                PacketEvidenceSnapshotDraft(
                    reconciliation_scope_id=reconciliation_scope_id,
                    packet_id=packet_id,
                    provider_id=provider_id or provider,
                    provider_scope_id=provider_scope_id,
                    provider_snapshot_id=provider_snapshot_id,
                    selection_ref=selection_ref,
                    source_revision=source_revision,
                    workspace_revision=workspace_revision,
                    surfaces=_require_string_list(surfaces or [], "surfaces"),
                    fingerprint=fingerprint,
                    completeness={
                        str(key): str(value)
                        for key, value in _require_mapping(
                            completeness or {}, "completeness"
                        ).items()
                    },
                    claims=tuple(
                        _packet_evidence_claim_from_payload(item)
                        for item in (claims or [])
                    ),
                    contract_version=contract_version,
                    truncated=truncated,
                    diagnostics=_require_string_list(diagnostics or [], "diagnostics"),
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_evidence_snapshot": dict(result)},
                audit_reference={
                    "reconciliation_scope_id": reconciliation_scope_id,
                    "snapshot_id": result.get("snapshot_id", ""),
                },
            )
        elif selected == "collect_packet_evidence_snapshot":
            result = runtime.packet_reconciliation.collect_provider_snapshot(
                project_id,
                reconciliation_scope_id,
                actor=actor,
                request_id=request_id,
                max_claims=max_claims,
                max_depth=max_depth,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_evidence_snapshot": dict(result)},
                audit_reference={
                    "reconciliation_scope_id": reconciliation_scope_id,
                    "snapshot_id": result.get("snapshot_id", ""),
                },
            )
        elif selected == "reconcile_packet_evidence":
            result = runtime.packet_reconciliation.reconcile(
                project_id,
                reconciliation_scope_id,
                snapshot_id=snapshot_id,
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_reconciliation_run": dict(result)},
                audit_reference={
                    "reconciliation_scope_id": reconciliation_scope_id,
                    "run_id": result.get("run_id", ""),
                },
            )
        elif selected == "disposition_packet_evidence_residual":
            result = runtime.packet_reconciliation.disposition_item(
                project_id,
                ReconciliationItemDispositionDraft(
                    item_id=reconciliation_item_id,
                    disposition=ReconciliationItemDisposition(
                        reconciliation_disposition
                    ),
                    rationale=rationale,
                    policy_ref=policy_ref,
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_reconciliation": dict(result)},
                audit_reference={"item_id": reconciliation_item_id},
            )
        elif selected == "answer_packet_question":
            result = runtime.packet_construction.answer_question(
                project_id,
                construction_audit_id,
                PacketQuestionResolutionDraft(
                    question_id=question_id,
                    answer_summary=answer_summary or summary,
                    evidence_refs=_require_string_list(
                        evidence_refs or [], "evidence_refs"
                    ),
                    linked_navigation_refs=_require_string_list(
                        linked_navigation_refs or [], "linked_navigation_refs"
                    ),
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_construction_audit": dict(result)},
                audit_reference={
                    "construction_audit_id": construction_audit_id,
                    "question_id": question_id,
                },
            )
        elif selected == "waive_packet_question":
            result = runtime.packet_construction.waive_question(
                project_id,
                construction_audit_id,
                PacketQuestionResolutionDraft(
                    question_id=question_id,
                    waiver_rationale=waiver_rationale or rationale,
                    policy_ref=policy_ref,
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_construction_audit": dict(result)},
                audit_reference={
                    "construction_audit_id": construction_audit_id,
                    "question_id": question_id,
                },
            )
        elif selected == "block_packet_question":
            result = runtime.packet_construction.block_question(
                project_id,
                construction_audit_id,
                PacketQuestionResolutionDraft(
                    question_id=question_id,
                    blocker_reason=blocking_reasons[0]
                    if blocking_reasons
                    else rationale or answer_summary or summary,
                ),
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_construction_audit": dict(result)},
                audit_reference={
                    "construction_audit_id": construction_audit_id,
                    "question_id": question_id,
                },
            )
        elif selected == "derive_packet_pressure":
            result = runtime.packet_pressure.derive(
                project_id,
                change_id,
                packet_id,
                profile=profile,
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_pressure": dict(result)},
                audit_reference={
                    "change_id": change_id,
                    "packet_id": packet_id,
                    "pressure_id": result.get("pressure_id", ""),
                },
            )
        elif selected == "get_packet_pressure":
            result = (
                runtime.packet_pressure.get(project_id, pressure_id)
                if pressure_id
                else runtime.packet_pressure.latest(project_id, change_id, packet_id)
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_pressure": {} if result is None else dict(result)},
                audit_reference={"pressure_id": pressure_id, "packet_id": packet_id},
            )
        elif selected == "accept_residual_risk":
            result = runtime.packet_pressure.accept_risk(
                project_id,
                pressure_id,
                accepted_risk_ref=accepted_risk_ref,
                actor=actor,
                request_id=request_id,
            )
            return envelope(
                tool="fow_change",
                status="success",
                result={"packet_pressure": dict(result)},
                audit_reference={"pressure_id": pressure_id},
            )
        elif selected == "revise_packet":
            result = runtime.changes.refine_packet(
                project_id,
                change_id,
                packet_id,
                title=title,
                objective=intent,
                rationale=rationale,
                requirement_ids=(
                    _require_string_list(requirement_ids, "requirement_ids")
                    if requirement_ids is not None
                    else None
                ),
                goal_ids=(
                    _require_string_list(goal_ids, "goal_ids")
                    if goal_ids is not None
                    else None
                ),
                in_scope=(
                    _require_string_list(in_scope, "in_scope")
                    if in_scope is not None
                    else None
                ),
                out_of_scope=(
                    _require_string_list(out_of_scope, "out_of_scope")
                    if out_of_scope is not None
                    else None
                ),
                invariants=(
                    _require_string_list(invariants, "invariants")
                    if invariants is not None
                    else None
                ),
                unresolved_questions=(
                    _require_string_list(unresolved_questions, "unresolved_questions")
                    if unresolved_questions is not None
                    else None
                ),
                completion_criteria=(
                    _require_string_list(completion_criteria, "completion_criteria")
                    if completion_criteria is not None
                    else None
                ),
                target_policy=target_policy,
                readiness_state=target_state,
                navigation_audit_ids=(
                    _require_string_list(
                        navigation_audit_ids
                        or ([navigation_audit_id] if navigation_audit_id else []),
                        "navigation_audit_ids",
                    )
                    if navigation_audit_ids is not None or navigation_audit_id
                    else None
                ),
                target_binding_ids=(
                    _require_string_list(target_binding_ids, "target_binding_ids")
                    if target_binding_ids is not None
                    else None
                ),
                candidate_set_ids=(
                    _require_string_list(
                        candidate_set_ids
                        or ([candidate_set_id] if candidate_set_id else []),
                        "candidate_set_ids",
                    )
                    if candidate_set_ids is not None or candidate_set_id
                    else None
                ),
                context_snapshot_ids=(
                    _require_string_list(
                        context_snapshot_ids
                        or ([context_snapshot_id] if context_snapshot_id else []),
                        "context_snapshot_ids",
                    )
                    if context_snapshot_ids is not None or context_snapshot_id
                    else None
                ),
                readiness_blockers=(
                    _require_string_list(blocking_reasons, "readiness_blockers")
                    if blocking_reasons is not None
                    else None
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "link_dependency":
            result = runtime.changes.link_dependency(
                project_id,
                change_id,
                packet_id,
                depends_on_packet_id,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "transition_packet":
            result = runtime.changes.transition_packet(
                project_id,
                change_id,
                packet_id,
                PacketTransition(
                    status=PacketStatus(packet_status),
                    criterion_results={
                        str(key): str(value)
                        for key, value in _require_mapping(
                            criterion_results or {}, "criterion_results"
                        ).items()
                    },
                    blocking_reasons=_require_string_list(
                        blocking_reasons or [], "blocking_reasons"
                    ),
                    disposition=disposition,
                    successor_packet_id=successor_packet_id,
                ),
                actor=actor,
                request_id=request_id,
            )
        else:
            raise RuntimeError("change operation ownership and dispatch diverged")
        return envelope(
            tool="fow_change",
            status="success",
            result={"change": dict(result)},
            audit_reference={"change_id": result.get("change_id", change_id)},
        )

    return _guard("fow_change", operation_fn)


def _packet_target_delta(
    change: Mapping[str, object], packet_id: str
) -> Mapping[str, object]:
    packet = next(
        (
            item
            for item in change.get("packets", [])
            if isinstance(item, Mapping)
            and str(item.get("packet_id") or "") == packet_id
        ),
        None,
    )
    if packet is None:
        raise ValueError(f"unknown packet in change: {packet_id}")
    target_fields = (
        "navigation_audit_ids",
        "target_binding_ids",
        "candidate_set_ids",
        "context_snapshot_ids",
    )
    return {
        "change_id": str(change.get("change_id") or ""),
        "packet_id": packet_id,
        "current_revision": int(packet.get("current_revision") or 0),
        "spec_revision": int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        ),
        "state_revision": int(packet.get("state_revision") or 0),
        "target_policy": str(packet.get("target_policy") or ""),
        "readiness_state": str(packet.get("readiness_state") or ""),
        "readiness_blockers": list(packet.get("readiness_blockers", []))[:20],
        "targets": {
            field: {
                "count": len(packet.get(field, [])),
                "sample": [str(item) for item in packet.get(field, [])[:5]],
                "truncated": len(packet.get(field, [])) > 5,
            }
            for field in target_fields
        },
    }


def _packet_evidence_claim_from_payload(
    payload: Mapping[str, object],
) -> PacketEvidenceClaimDraft:
    value = _require_mapping(payload, "claim")
    return PacketEvidenceClaimDraft(
        claim_type=PacketEvidenceClaimType(str(value.get("claim_type") or "")),
        claim_key=str(value.get("claim_key") or ""),
        subject_ref=str(value.get("subject_ref") or ""),
        predicate=str(value.get("predicate") or ""),
        object_ref=str(value.get("object_ref") or ""),
        assertion=_require_mapping(value.get("assertion") or {}, "claim.assertion"),
        evidence_refs=_require_string_list(
            value.get("evidence_refs") or [], "claim.evidence_refs"
        ),
        required=_require_boolean(value.get("required", True), "claim.required"),
        dynamic=_require_boolean(value.get("dynamic", False), "claim.dynamic"),
        contradicted=_require_boolean(
            value.get("contradicted", False), "claim.contradicted"
        ),
    )


def handle_assurance(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str,
    change_id: str = "",
    packet_id: str = "",
    finding_id: str = "",
    title: str = "",
    rationale: str = "",
    severity: str = "",
    finding_kind: str = "unspecified",
    assessment: dict[str, object] | None = None,
    expected_correction: str = "",
    scope_kind: str = "",
    scope_ref: str = "",
    source_anchor: str = "",
    implementation_ref: str = "",
    disposition: str = "",
    disposition_reference: str = "",
    supersedes_finding_id: str = "",
    evidence_refs: list[str] | None = None,
    required_regression_evidence: str = "",
    required_campaign_ids: list[str] | None = None,
    acceptance_reference: str = "",
    request_id: str = "",
) -> dict[str, object]:
    """Apply one bounded assurance operation."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "record_finding":
            result = runtime.assurance.record_finding(
                project_id,
                ReviewFindingDraft(
                    change_id=change_id,
                    packet_id=packet_id,
                    severity=ReviewFindingSeverity(severity),
                    finding_kind=finding_kind,
                    title=title,
                    rationale=rationale,
                    expected_correction=expected_correction,
                    scope_kind=scope_kind,
                    scope_ref=scope_ref,
                    source_anchor=source_anchor,
                    implementation_ref=implementation_ref,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "get_finding":
            result = runtime.assurance.get_finding(project_id, finding_id)
        elif selected == "reassess_intent":
            result = runtime.assurance.reassess_intent(project_id, finding_id, assessment or {}, actor=actor, request_id=request_id)
        elif selected == "set_finding_disposition":
            result = runtime.assurance.set_finding_disposition(
                project_id,
                finding_id,
                FindingDispositionDraft(
                    disposition=FindingDisposition(disposition),
                    rationale=rationale,
                    evidence_refs=_require_string_list(
                        evidence_refs or [], "evidence_refs"
                    ),
                    disposition_reference=disposition_reference,
                    supersedes_finding_id=supersedes_finding_id,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "link_fixing_packet":
            result = runtime.assurance.link_fixing_packet(
                project_id,
                FixingPacketLinkDraft(
                    finding_id=finding_id,
                    packet_id=packet_id,
                    expected_correction=expected_correction,
                    required_regression_evidence=required_regression_evidence,
                    required_campaign_ids=_require_string_list(
                        required_campaign_ids or [], "required_campaign_ids"
                    ),
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "request_change_acceptance":
            result = runtime.assurance.request_change_acceptance(
                project_id,
                change_id,
                acceptance_reference=acceptance_reference,
                actor=actor,
                request_id=request_id,
            )
        else:
            raise ValueError("assurance operation is invalid")
        packet_result = result.get("packet")
        result_packet_id = (
            packet_result.get("packet_id", "")
            if isinstance(packet_result, Mapping)
            else packet_id
        )
        return envelope(
            tool="fow_assurance",
            status="success",
            result={"assurance": dict(result)},
            audit_reference={
                "change_id": result.get("change_id", change_id),
                "finding_id": result.get("finding_id", finding_id),
                "packet_id": result_packet_id,
            },
        )

    return _guard("fow_assurance", operation_fn)


def handle_campaign_author(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str,
    request_id: str,
    campaign_id: str = "",
    case_id: str = "",
    evidence_id: str = "",
    obligation_id: str = "",
    oracle_id: str = "",
    question_id: str = "",
    provider_command_id: str = "",
    title: str = "",
    scope: Mapping[str, object] | None = None,
    case: Mapping[str, object] | None = None,
    case_order: list[str] | None = None,
    decision: str = "",
    rationale: str = "",
    coverage_intent: str = "",
    oracle: Mapping[str, object] | None = None,
    answer: Any = None,
    answer_authority: str = "",
    provenance: list[str] | None = None,
    waiver_scope: str = "",
    source_files: Mapping[str, str] | None = None,
    harness: Mapping[str, object] | None = None,
    requested_capability: Mapping[str, object] | None = None,
    authority_reference: str = "",
    disposition_reference: str = "",
    exception_obligation_ids: list[str] | None = None,
    evidence_gaps: list[str] | None = None,
    risk_authority: str = "",
    regression_obligation: bool = False,
    expected_fingerprint: str = "",
) -> dict[str, object]:
    """Apply one semantic campaign mutation and return its successor gate."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "start":
            scope_draft = _campaign_scope_draft(scope)
            first_case = _campaign_case_draft(case) if case else None
            result = runtime.campaign_authority.start(
                project_id,
                title=title,
                scope=scope_draft,
                first_case=first_case,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "edit_scope":
            result = runtime.campaign_authority.edit_scope(
                project_id,
                campaign_id,
                title=title,
                scope=_campaign_scope_draft(scope),
                actor=actor,
                request_id=request_id,
                expected_fingerprint=expected_fingerprint,
            )
        elif selected == "add_case":
            result = runtime.campaign_authority.add_case(
                project_id,
                campaign_id,
                _campaign_case_draft(case),
                actor=actor,
                request_id=request_id,
                expected_fingerprint=expected_fingerprint,
            )
        elif selected == "edit_case":
            result = runtime.campaign_authority.edit_case(
                project_id,
                campaign_id,
                case_id,
                _campaign_case_draft(case),
                actor=actor,
                request_id=request_id,
                expected_fingerprint=expected_fingerprint,
            )
        elif selected == "remove_case":
            result = runtime.campaign_authority.remove_case(
                project_id,
                campaign_id,
                case_id,
                rationale=rationale,
                actor=actor,
                request_id=request_id,
                expected_fingerprint=expected_fingerprint,
            )
        elif selected == "reorder_cases":
            result = runtime.campaign_authority.reorder_cases(
                project_id,
                campaign_id,
                _require_string_list(case_order or [], "case_order"),
                actor=actor,
                request_id=request_id,
                expected_fingerprint=expected_fingerprint,
            )
        elif selected == "decide_obligation":
            result = runtime.campaign_authority.decide_obligation(
                project_id,
                campaign_id,
                obligation_id,
                decision=CampaignObligationDecision(decision),
                rationale=rationale,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "bind_obligation":
            result = runtime.campaign_authority.bind_obligation(
                project_id,
                campaign_id,
                case_id,
                obligation_id,
                coverage_intent=coverage_intent,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "author_oracle":
            result = runtime.campaign_authority.author_oracle(
                project_id,
                campaign_id,
                case_id,
                _behavioral_oracle_draft(oracle),
                actor=actor,
                request_id=request_id,
                oracle_id=oracle_id,
            )
        elif selected == "answer_question":
            result = runtime.campaign_authority.answer_question(
                project_id,
                campaign_id,
                oracle_id,
                question_id,
                answer=answer,
                authority=OracleAnswerAuthority(answer_authority),
                provenance=_require_string_list(provenance or [], "provenance"),
                waiver_scope=waiver_scope,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "attest_source":
            files = _require_mapping(source_files or {}, "source_files")
            if any(not isinstance(value, str) for value in files.values()):
                raise ValueError("source_files values must be strings")
            result = runtime.campaign_authority.attest_source(
                project_id,
                campaign_id,
                case_id,
                source_files={
                    str(path): str(content) for path, content in files.items()
                },
                harness=harness,
                requested_capability=requested_capability,
                authority_reference=authority_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "authorize_materialization":
            result = runtime.campaign_authority.authorize_materialization(
                project_id,
                campaign_id,
                case_id,
                requested_capability=_require_mapping(
                    requested_capability or {}, "requested_capability"
                ),
                authority_reference=authority_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "retry_provider_rejection":
            result = runtime.campaign_authority.retry_provider_rejection(
                project_id,
                campaign_id,
                provider_command_id,
                rationale=rationale,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "cancel":
            result = runtime.campaign_authority.cancel(
                project_id,
                campaign_id,
                disposition_reference=disposition_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "accept_exception":
            result = runtime.campaign_authority.accept_exception(
                project_id,
                campaign_id,
                obligation_ids=_require_string_list(
                    exception_obligation_ids or [], "exception_obligation_ids"
                ),
                evidence_gaps=_require_string_list(
                    evidence_gaps or [], "evidence_gaps"
                ),
                risk_authority=risk_authority,
                disposition_reference=disposition_reference,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "authorize_promotion":
            result = runtime.campaign_authority.authorize_promotion(
                project_id,
                campaign_id,
                case_id,
                evidence_id=evidence_id,
                authority_reference=authority_reference,
                regression_obligation=regression_obligation,
                actor=actor,
                request_id=request_id,
            )
        else:
            raise ValueError("campaign author operation is invalid")
        campaign = result.get("campaign")
        campaign_ref = (
            str(campaign.get("campaign_id") or "")
            if isinstance(campaign, Mapping)
            else campaign_id
        )
        return envelope(
            tool="fow_campaign_author",
            status="success",
            result=dict(result),
            audit_reference={"campaign_id": campaign_ref},
        )

    recovery_change_id = str((scope or {}).get("change_id") or "")
    return _guard(
        "fow_campaign_author",
        operation_fn,
        recovery=lambda: _campaign_recovery_projection(
            runtime,
            project_id,
            campaign_id=campaign_id,
            change_id=recovery_change_id,
        ),
    )


def handle_campaign_inspect(
    runtime: McpRuntime,
    *,
    project_id: str,
    campaign_id: str = "",
    change_id: str = "",
    view: str = "summary",
    offset: int = 0,
    limit: int = 20,
) -> dict[str, object]:
    def operation_fn() -> dict[str, object]:
        result = runtime.campaign_authority.inspect(
            project_id,
            campaign_id=campaign_id,
            change_id=change_id,
            view=view,
            offset=offset,
            limit=limit,
        )
        return envelope(
            tool="fow_campaign_inspect",
            status="success",
            result=dict(result),
            audit_reference={"campaign_id": campaign_id},
        )

    return _guard(
        "fow_campaign_inspect",
        operation_fn,
        recovery=lambda: _campaign_recovery_projection(
            runtime,
            project_id,
            campaign_id=campaign_id,
            change_id=change_id,
        ),
    )


def handle_campaign_advance(
    runtime: McpRuntime,
    *,
    project_id: str,
    actor: str,
    request_id: str,
    campaign_id: str = "",
    change_id: str = "",
    transition_budget: int = 8,
) -> dict[str, object]:
    def operation_fn() -> dict[str, object]:
        result = runtime.campaign_authority.advance(
            project_id,
            campaign_id=campaign_id,
            change_id=change_id,
            actor=actor,
            request_id=request_id,
            transition_budget=transition_budget,
        )
        campaign = result.get("campaign")
        campaign_ref = (
            str(campaign.get("campaign_id") or "")
            if isinstance(campaign, Mapping)
            else campaign_id
        )
        return envelope(
            tool="fow_campaign_advance",
            status="success",
            result=dict(result),
            audit_reference={"campaign_id": campaign_ref},
        )

    return _guard(
        "fow_campaign_advance",
        operation_fn,
        recovery=lambda: _campaign_recovery_projection(
            runtime,
            project_id,
            campaign_id=campaign_id,
            change_id=change_id,
        ),
    )


def _campaign_scope_draft(value: Mapping[str, object] | None) -> CampaignScopeDraft:
    payload = _require_mapping_fields(
        value or {},
        "scope",
        {
            "change_id",
            "milestone_id",
            "requirement_ids",
            "goal_ids",
            "packet_ids",
            "finding_ids",
            "invariants",
            "environment_assumptions",
        },
    )
    return CampaignScopeDraft(
        change_id=str(payload.get("change_id") or ""),
        milestone_id=str(payload.get("milestone_id") or ""),
        requirement_ids=_require_string_list(
            payload.get("requirement_ids") or [], "scope.requirement_ids"
        ),
        goal_ids=_require_string_list(payload.get("goal_ids") or [], "scope.goal_ids"),
        packet_ids=_require_string_list(
            payload.get("packet_ids") or [], "scope.packet_ids"
        ),
        finding_ids=_require_string_list(
            payload.get("finding_ids") or [], "scope.finding_ids"
        ),
        invariants=_require_string_list(
            payload.get("invariants") or [], "scope.invariants"
        ),
        environment_assumptions=_require_string_list(
            payload.get("environment_assumptions") or [],
            "scope.environment_assumptions",
        ),
    )


def _campaign_case_draft(
    value: Mapping[str, object] | None,
) -> CampaignCaseSemanticDraft:
    payload = _require_mapping_fields(
        value or {},
        "case",
        {
            "title",
            "purpose",
            "case_kind",
            "action",
            "expected_outcome",
            "prohibited_outcome",
            "observation_point",
            "setup",
            "cleanup",
            "execution_class",
            "required",
            "obligation_ids",
            "oracle_kind",
        },
    )
    return CampaignCaseSemanticDraft(
        title=str(payload.get("title") or ""),
        purpose=str(payload.get("purpose") or ""),
        case_kind=str(payload.get("case_kind") or ""),
        action=str(payload.get("action") or ""),
        expected_outcome=str(payload.get("expected_outcome") or ""),
        prohibited_outcome=str(payload.get("prohibited_outcome") or ""),
        observation_point=str(payload.get("observation_point") or ""),
        setup=str(payload.get("setup") or ""),
        cleanup=str(payload.get("cleanup") or ""),
        execution_class=str(payload.get("execution_class") or "deterministic"),
        required=_require_boolean(payload.get("required", True), "case.required"),
        obligation_ids=_require_string_list(
            payload.get("obligation_ids") or [], "case.obligation_ids"
        ),
        oracle_kind=str(payload.get("oracle_kind") or "behavior"),
    )


def _behavioral_oracle_draft(
    value: Mapping[str, object] | None,
) -> BehavioralOracleDraft:
    payload = _require_mapping_fields(
        value or {},
        "oracle",
        {
            "oracle_kind",
            "subject_bindings",
            "goal_bindings",
            "authority_reference",
            "semantic_fields",
        },
    )
    return BehavioralOracleDraft(
        oracle_kind=str(payload.get("oracle_kind") or ""),
        subject_bindings=_require_string_list(
            payload.get("subject_bindings") or [], "oracle.subject_bindings"
        ),
        goal_bindings=_require_string_list(
            payload.get("goal_bindings") or [], "oracle.goal_bindings"
        ),
        authority_reference=str(payload.get("authority_reference") or ""),
        semantic_fields=_require_mapping(
            payload.get("semantic_fields") or {}, "oracle.semantic_fields"
        ),
    )


def handle_run(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str,
    change_id: str = "",
    packet_id: str = "",
    run_id: str = "",
    step_id: str = "",
    depends_on_step_id: str = "",
    objective: str = "",
    orchestrator_ref: str = "",
    external_ref: str = "",
    source_ref: str = "",
    title: str = "",
    action: str = "",
    target_refs: Mapping[str, object] | None = None,
    evidence_refs: list[str] | None = None,
    step_required: bool = True,
    blocking_reason: str = "",
    next_expected_action: str = "",
    completion_reference: str = "",
    reason: str = "",
    request_id: str = "",
) -> dict[str, object]:
    """Apply one bounded implementation-run operation."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "create_run":
            result = runtime.execution_runs.create_run(
                project_id,
                RunDraft(
                    change_id=change_id,
                    packet_id=packet_id,
                    objective=objective,
                    orchestrator_ref=orchestrator_ref,
                    external_ref=external_ref,
                    source_ref=source_ref,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "get_run":
            result = runtime.execution_runs.get_run(project_id, run_id)
        elif selected == "add_step":
            result = runtime.execution_runs.add_step(
                project_id,
                RunStepDraft(
                    run_id=run_id,
                    title=title,
                    action=action,
                    target_refs=_require_mapping(target_refs or {}, "target_refs"),
                    evidence_refs=_require_string_list(
                        evidence_refs or [], "evidence_refs"
                    ),
                    required=step_required,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "link_step_dependency":
            result = runtime.execution_runs.link_step_dependency(
                project_id,
                run_id,
                step_id,
                depends_on_step_id,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "start_step":
            result = runtime.execution_runs.start_step(
                project_id, run_id, step_id, actor=actor, request_id=request_id
            )
        elif selected == "complete_step":
            result = runtime.execution_runs.complete_step(
                project_id,
                run_id,
                step_id,
                evidence_refs=_require_string_list(
                    evidence_refs or [], "evidence_refs"
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "block_step":
            result = runtime.execution_runs.block_step(
                project_id,
                run_id,
                step_id,
                blocking_reason=blocking_reason,
                next_expected_action=next_expected_action,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "cancel_step":
            result = runtime.execution_runs.cancel_step(
                project_id,
                run_id,
                step_id,
                reason=reason,
                actor=actor,
                request_id=request_id,
            )
        elif selected == "complete_run":
            result = runtime.execution_runs.complete_run(
                project_id,
                run_id,
                RunCompletionDraft(completion_reference=completion_reference),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "cancel_run":
            result = runtime.execution_runs.cancel_run(
                project_id, run_id, reason=reason, actor=actor, request_id=request_id
            )
        elif selected == "task_view":
            result = runtime.execution_runs.task_view(project_id, run_id)
        else:
            raise ValueError("run operation is invalid")
        return envelope(
            tool="fow_run",
            status="success",
            result={"run": dict(result)},
            audit_reference={
                "run_id": result.get("run_id", run_id),
                "step_id": step_id,
            },
        )

    return _guard("fow_run", operation_fn)


def handle_handover(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    actor: str = "",
    handover_id: str = "",
    change_id: str = "",
    packet_id: str = "",
    run_id: str = "",
    profile_version: str = "handover-context-v1",
    projection_kind: str = "lifecycle",
    focus_kind: str = "project",
    focus_ref: str = "",
    milestone_ids: list[str] | None = None,
    limit: int = 10,
    request_id: str = "",
) -> dict[str, object]:
    """Return or persist bounded handover/projection views."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "create_handover":
            result = runtime.handover.create_handover(
                project_id,
                HandoverDraft(
                    change_id=change_id,
                    packet_id=packet_id,
                    run_id=run_id,
                    profile_version=profile_version,
                ),
                actor=actor,
                request_id=request_id,
            )
        elif selected == "get_handover":
            result = runtime.handover.get_handover(project_id, handover_id)
        elif selected == "resume_context":
            result = runtime.handover.resume_context(
                project_id, change_id=change_id, packet_id=packet_id, run_id=run_id
            )
        elif selected == "ledger_projection":
            result = runtime.handover.ledger_projection(
                project_id, projection_kind=projection_kind
            )
        elif selected == "project_progress":
            result = runtime.milestone_traceability.progress(project_id, milestone_ids=tuple(milestone_ids or []))
        elif selected == "project_state_snapshot":
            result = runtime.project_state_snapshot.snapshot(
                project_id,
                focus_kind=focus_kind,
                focus_ref=focus_ref,
                limit=limit,
            )
        else:
            raise ValueError("handover operation is invalid")
        result_key = (
            "project_state_snapshot"
            if selected == "project_state_snapshot"
            else "project_progress" if selected == "project_progress" else "handover"
        )
        return envelope(
            tool="fow_handover",
            status="success",
            result={result_key: dict(result)},
            audit_reference={
                "handover_id": result.get("handover_id", handover_id),
                "run_id": run_id,
            },
        )

    return _guard("fow_handover", operation_fn)


def handle_register_requirement(
    runtime: McpRuntime,
    *,
    project_id: str,
    title: str,
    statement: str,
    category: str,
    rationale: str,
    actor: str,
    source_anchor: str = "",
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        result = dict(
            runtime.requirements.register(
                project_id,
                RequirementDraft(
                    title=title,
                    statement=statement,
                    category=category,
                    rationale=rationale,
                    source_anchor=source_anchor,
                ),
                actor=actor,
                request_id=request_id,
            )
        )
        return envelope(
            tool="fow_register_requirement",
            status="success",
            result=result,
            audit_reference={"event_id": result.get("audit_event_id", 0)},
        )

    return _guard(
        "fow_register_requirement",
        operation,
    )


def handle_get_requirement(
    runtime: McpRuntime,
    *,
    project_id: str,
    requirement_id: str,
) -> dict[str, object]:
    return _guard(
        "fow_get_requirement",
        lambda: envelope(
            tool="fow_get_requirement",
            status="success",
            result=dict(runtime.requirements.history(project_id, requirement_id)),
        ),
    )


def handle_revise_requirement(
    runtime: McpRuntime,
    *,
    project_id: str,
    requirement_id: str,
    title: str,
    statement: str,
    category: str,
    rationale: str,
    actor: str,
    source_anchor: str = "",
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        result = dict(
            runtime.requirements.revise(
                project_id,
                requirement_id,
                RequirementDraft(
                    title=title,
                    statement=statement,
                    category=category,
                    rationale=rationale,
                    source_anchor=source_anchor,
                ),
                actor=actor,
                rationale=rationale,
                request_id=request_id,
            )
        )
        return envelope(
            tool="fow_revise_requirement",
            status="success",
            result=result,
            audit_reference={"event_id": result.get("audit_event_id", 0)},
        )

    return _guard("fow_revise_requirement", operation)


def handle_set_requirement_lifecycle(
    runtime: McpRuntime,
    *,
    project_id: str,
    requirement_id: str,
    lifecycle_status: str,
    reason: str,
    actor: str,
    governed_approval_reference: str = "",
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        result = dict(
            runtime.requirements.set_lifecycle(
                project_id,
                requirement_id,
                LifecycleStatus(lifecycle_status),
                actor=actor,
                reason=reason,
                governed_approval_reference=governed_approval_reference,
                request_id=request_id,
            )
        )
        return envelope(
            tool="fow_set_requirement_lifecycle",
            status="success",
            result=result,
            audit_reference={"event_id": result.get("audit_event_id", 0)},
        )

    return _guard("fow_set_requirement_lifecycle", operation)


def handle_record_verification(
    runtime: McpRuntime,
    *,
    project_id: str,
    requirement_id: str,
    verification_kind: str,
    outcome: str,
    reference: str,
    actor: str,
    metadata: Mapping[str, object] | None = None,
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        result = dict(
            runtime.requirements.record_verification(
                project_id,
                requirement_id,
                VerificationDraft(
                    kind=VerificationKind(verification_kind),
                    outcome=VerificationOutcome(outcome),
                    reference=reference,
                    metadata=_require_mapping(metadata or {}, "metadata"),
                ),
                actor=actor,
                request_id=request_id,
            )
        )
        return envelope(
            tool="fow_record_verification",
            status="success",
            result=result,
            audit_reference={"event_id": result.get("audit_event_id", 0)},
        )

    return _guard("fow_record_verification", operation)


def handle_traceability(
    runtime: McpRuntime,
    *,
    project_id: str,
    milestone_id: str = "",
    detail_level: str = "standard",
    offset: int = 0,
    limit: int = _RECOVERY_DEFAULT_LIMIT,
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        detail, page_offset, page_limit = _recovery_page_args(
            detail_level,
            offset,
            limit,
        )
        requirements = [
            dict(item) for item in runtime.requirements.traceability(project_id)
        ]
        projection = dict(
            runtime.milestone_traceability.projection(
                project_id,
                milestone_id=milestone_id,
            )
        )
        rows = [
            dict(item)
            for item in projection.get("rows", [])
            if isinstance(item, Mapping)
        ]
        if milestone_id:
            scoped_ids = {str(item.get("requirement_id") or "") for item in rows}
            requirements = [
                item
                for item in requirements
                if str(item.get("requirement_id") or "") in scoped_ids
            ]

        requirement_page, requirement_pagination = _page(
            requirements,
            offset=page_offset,
            limit=page_limit,
        )
        row_page, row_pagination = _page(
            rows,
            offset=page_offset,
            limit=page_limit,
        )
        milestone_rows = [
            dict(item)
            for item in projection.get("milestones", [])
            if isinstance(item, Mapping)
        ]
        gap_rows = [
            dict(item)
            for item in projection.get("gaps", [])
            if isinstance(item, Mapping)
        ]
        projected = {
            "project_id": str(projection.get("project_id") or project_id),
            "projection_kind": str(projection.get("projection_kind") or ""),
            "profile_version": str(projection.get("profile_version") or ""),
            "scope": str(projection.get("scope") or ""),
            "milestone_id": str(projection.get("milestone_id") or ""),
            "source_ledger_version": int(projection.get("source_ledger_version") or 0),
            "milestones": (
                milestone_rows
                if detail == "audit"
                else [_standard_milestone_view(item) for item in milestone_rows]
            ),
            "rows": (
                row_page
                if detail == "audit"
                else [_standard_traceability_row(item) for item in row_page]
            ),
            "gaps": (
                gap_rows
                if detail == "audit"
                else [_standard_gap_view(item) for item in gap_rows]
            ),
        }
        return envelope(
            tool="fow_traceability",
            status="success",
            result={
                "detail_level": detail,
                "requirements": (
                    requirement_page
                    if detail == "audit"
                    else [_standard_requirement_view(item) for item in requirement_page]
                ),
                "projection": projected,
                "pagination": {
                    "requirements": requirement_pagination,
                    "projection_rows": row_pagination,
                },
            },
        )

    return _guard("fow_traceability", operation)


def handle_goal(
    runtime: McpRuntime,
    *,
    project_id: str,
    operation: str,
    view: str = "summary",
    detail_level: str = "standard",
    offset: int = 0,
    limit: int = _RECOVERY_DEFAULT_LIMIT,
    actor: str = "",
    title: str = "",
    use_case_actor: str = "",
    objective: str = "",
    observable_outcome: str = "",
    preconditions: list[str] | None = None,
    postconditions: list[str] | None = None,
    invariants: list[str] | None = None,
    participants: list[str] | None = None,
    normal_steps: list[str] | None = None,
    alternate_steps: list[str] | None = None,
    failure_steps: list[str] | None = None,
    expected_effects: list[str] | None = None,
    statement: str = "",
    category: str = "",
    source_goal_id: str = "",
    target_goal_id: str = "",
    relation: str = "",
    source_anchor: Mapping[str, object] | None = None,
    request_id: str = "",
) -> dict[str, object]:
    """Apply one bounded Goal Graph operation."""

    def operation_fn() -> dict[str, object]:
        selected = str(operation or "").strip()
        if selected == "view":
            result = _goal_graph_projection(
                runtime.goals.view(project_id),
                view=view,
                detail_level=detail_level,
                offset=offset,
                limit=limit,
            )
            return envelope(
                tool="fow_goal", status="success", result={"goal_graph": result}
            )
        if selected == "add_use_case":
            result = dict(
                runtime.goals.add_use_case(
                    project_id,
                    UseCaseDraft(
                        title=title,
                        actor=use_case_actor,
                        objective=objective,
                        observable_outcome=observable_outcome,
                        preconditions=_require_string_list(
                            preconditions or [], "preconditions"
                        ),
                        postconditions=_require_string_list(
                            postconditions or [], "postconditions"
                        ),
                        invariants=_require_string_list(invariants or [], "invariants"),
                        source_anchor=_optional_source_anchor(source_anchor),
                    ),
                    actor=actor,
                    request_id=request_id,
                )
            )
            return envelope(
                tool="fow_goal",
                status="success",
                result={"goal": result},
                audit_reference={"goal_node_id": result.get("goal_node_id", "")},
            )
        if selected == "add_sequence":
            result = dict(
                runtime.goals.add_sequence(
                    project_id,
                    SequenceDraft(
                        title=title,
                        participants=_require_string_list(
                            participants or [], "participants"
                        ),
                        normal_steps=_require_string_list(
                            normal_steps or [], "normal_steps"
                        ),
                        alternate_steps=_require_string_list(
                            alternate_steps or [], "alternate_steps"
                        ),
                        failure_steps=_require_string_list(
                            failure_steps or [], "failure_steps"
                        ),
                        expected_effects=_require_string_list(
                            expected_effects or [], "expected_effects"
                        ),
                        source_anchor=_optional_source_anchor(source_anchor),
                    ),
                    actor=actor,
                    request_id=request_id,
                )
            )
            return envelope(
                tool="fow_goal",
                status="success",
                result={"goal": result},
                audit_reference={"goal_node_id": result.get("goal_node_id", "")},
            )
        if selected == "add_behavioral_expectation":
            result = dict(
                runtime.goals.add_behavioral_expectation(
                    project_id,
                    BehavioralExpectationDraft(
                        title=title,
                        statement=statement,
                        category=category,
                        observable_outcome=observable_outcome,
                        source_anchor=_optional_source_anchor(source_anchor),
                    ),
                    actor=actor,
                    request_id=request_id,
                )
            )
            return envelope(
                tool="fow_goal",
                status="success",
                result={"goal": result},
                audit_reference={"goal_node_id": result.get("goal_node_id", "")},
            )
        if selected == "link":
            result = dict(
                runtime.goals.link(
                    project_id,
                    source_goal_id=source_goal_id,
                    target_goal_id=target_goal_id,
                    relation=relation,
                    actor=actor,
                    request_id=request_id,
                )
            )
            return envelope(
                tool="fow_goal",
                status="success",
                result={"edge": result},
                audit_reference={"edge_id": result.get("edge_id", 0)},
            )
        if selected == "derive_requirement_candidates":
            result = [
                dict(item)
                for item in runtime.goals.derive_requirement_candidates(
                    project_id,
                    actor=actor,
                    request_id=request_id,
                )
            ]
            return envelope(
                tool="fow_goal",
                status="success",
                result={"candidates": result},
            )
        raise ValueError("goal operation is invalid")

    return _guard("fow_goal", operation_fn)


def _goal_graph_projection(
    graph: Mapping[str, object],
    *,
    view: str,
    detail_level: str,
    offset: int,
    limit: int,
) -> Mapping[str, object]:
    selected_view = str(view or "summary").strip().lower()
    if selected_view not in {"summary", "nodes", "edges", "candidates"}:
        raise ValueError("view must be summary, nodes, edges or candidates")
    detail, page_offset, page_limit = _recovery_page_args(detail_level, offset, limit)
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, Mapping)]
    edges = [item for item in graph.get("edges", []) if isinstance(item, Mapping)]
    candidates = [
        item
        for item in graph.get("requirement_candidates", [])
        if isinstance(item, Mapping)
    ]
    result: dict[str, object] = {
        "project_id": str(graph.get("project_id") or ""),
        "view": selected_view,
        "detail_level": detail,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "candidate_count": len(candidates),
            "node_type_counts": {
                node_type: sum(
                    1 for item in nodes if str(item.get("node_type") or "") == node_type
                )
                for node_type in sorted(
                    {str(item.get("node_type") or "") for item in nodes}
                )
                if node_type
            },
        },
    }
    if selected_view == "summary":
        return result
    source = {
        "nodes": nodes,
        "edges": edges,
        "candidates": candidates,
    }[selected_view]
    projected = [_goal_graph_item(selected_view, item, detail) for item in source]
    page, pagination = _page(projected, offset=page_offset, limit=page_limit)
    result[selected_view] = page
    result["pagination"] = pagination
    return result


def _goal_graph_item(
    view: str, item: Mapping[str, object], detail: str
) -> Mapping[str, object]:
    if detail == "audit":
        return dict(item)
    if view == "nodes":
        return {
            "goal_node_id": str(item.get("goal_node_id") or ""),
            "node_type": str(item.get("node_type") or ""),
            "title": str(item.get("title") or ""),
        }
    if view == "edges":
        return {
            "edge_id": int(item.get("edge_id") or 0),
            "source_goal_id": str(item.get("source_goal_id") or ""),
            "target_goal_id": str(item.get("target_goal_id") or ""),
            "relation": str(item.get("relation") or ""),
        }
    return {
        "candidate_id": str(item.get("candidate_id") or ""),
        "source_goal_id": str(item.get("source_goal_id") or ""),
        "category": str(item.get("category") or ""),
        "statement": str(item.get("statement") or ""),
        "status": str(item.get("status") or ""),
    }


def handle_validate_srs(
    runtime: McpRuntime,
    *,
    project_id: str,
    source_path: str,
    standard_profile: str,
    actor: str,
    request_id: str = "",
) -> dict[str, object]:
    def submit() -> dict[str, object]:
        def operation() -> Mapping[str, object]:
            try:
                structural = runtime.structural_validation.validate(
                    source_path,
                    standard_profile=standard_profile,
                )
            except ValueError as exc:
                raise JobBlockedError("validation_source_rejected") from exc
            audit = structural
            recorded = runtime.lifecycle.record_validation(
                project_id,
                ValidationAuditRecord(
                    source_ref=str(source_path),
                    disposition=audit.disposition,
                    finding_codes=tuple(sorted({item.code for item in audit.findings})),
                    profile_id=standard_profile,
                ),
                actor=actor,
                request_id=f"{request_id}:validation" if request_id else "",
            )
            return {
                "validation_audit_id": recorded.audit_id or 0,
                "disposition": audit.disposition.value,
                "audit": audit.to_dict(),
                "validation_scope": "deterministic_structural",
                "semantic_continuation": {"tool": "fow_semantic", "operation": "prepare", "role": "srs_semantic_validation", "execution_modes": ["host", "internal"]},
            }

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="validate_srs",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_validate_srs",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_validate_srs", submit)


def handle_import_srs(
    runtime: McpRuntime,
    *,
    project_id: str,
    source_path: str,
    standard_profile: str,
    actor: str,
    request_id: str = "",
) -> dict[str, object]:
    """Queue the only supported baseline materialization path.

    A rejected or shape-incomplete SRS is a completed diagnostic result, not a
    partially imported database state. A pre-existing baseline is explicitly
    blocked because revision semantics are intentionally out of scope.
    """

    def submit() -> dict[str, object]:
        def operation() -> Mapping[str, object]:
            try:
                return runtime.baseline_import.import_srs(
                    project_id,
                    source_path=source_path,
                    standard_profile=standard_profile,
                    actor=actor,
                    request_id=request_id,
                )
            except RequirementConflictError as exc:
                raise JobBlockedError("baseline_already_imported") from exc
            except ValueError as exc:
                raise JobBlockedError("baseline_source_rejected") from exc

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="import_srs",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_import_srs",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_import_srs", submit)


def handle_revise_srs_baseline(
    runtime: McpRuntime,
    *,
    project_id: str,
    previous_baseline_id: str,
    source_path: str,
    standard_profile: str,
    actor: str,
    governed_approval_reference: str = "",
    request_id: str = "",
) -> dict[str, object]:
    """Queue a source-proven baseline successor without implicit artifact generation."""

    def submit() -> dict[str, object]:
        def operation() -> Mapping[str, object]:
            try:
                return runtime.baseline_import.revise_srs(
                    project_id,
                    previous_baseline_id=previous_baseline_id,
                    source_path=source_path,
                    standard_profile=standard_profile,
                    actor=actor,
                    governed_approval_reference=governed_approval_reference,
                    request_id=request_id,
                )
            except RequirementConflictError as exc:
                raise JobBlockedError("baseline_revision_rejected") from exc
            except ValueError as exc:
                raise JobBlockedError("baseline_source_rejected") from exc

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="revise_srs_baseline",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_revise_srs_baseline",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_revise_srs_baseline", submit)


def handle_promote_milestone(
    runtime: McpRuntime,
    *,
    project_id: str,
    name: str,
    requirement_ids: list[str],
    dependency_closure_ids: list[str],
    entry_policy: dict[str, object],
    exit_policy: dict[str, object],
    risk_disposition: str,
    actor: str,
    acceptance_evidence: list[str] | None = None,
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        milestone = runtime.lifecycle.promote_milestone(
            project_id,
            MilestoneDraft(
                name=name,
                requirement_ids=_require_string_list(
                    requirement_ids, "requirement_ids"
                ),
                dependency_closure_ids=_require_string_list(
                    dependency_closure_ids, "dependency_closure_ids"
                ),
                entry_policy=_require_mapping(entry_policy, "entry_policy"),
                exit_policy=_require_mapping(exit_policy, "exit_policy"),
                risk_disposition=risk_disposition,
                acceptance_evidence=_require_string_list(
                    acceptance_evidence or [], "acceptance_evidence"
                ),
            ),
            actor=actor,
            request_id=request_id,
        )
        return envelope(
            tool="fow_promote_milestone",
            status="success",
            result=dict(milestone),
            audit_reference={"milestone_id": milestone["milestone_id"]},
        )

    return _guard("fow_promote_milestone", operation)


def handle_accept_milestone(
    runtime: McpRuntime,
    *,
    project_id: str,
    milestone_id: str,
    acceptance_evidence: list[str],
    actor: str,
    request_id: str = "",
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        milestone = runtime.lifecycle.accept_milestone(
            project_id,
            milestone_id,
            acceptance_evidence=_require_string_list(
                acceptance_evidence, "acceptance_evidence"
            ),
            actor=actor,
            request_id=request_id,
        )
        return envelope(
            tool="fow_accept_milestone",
            status="success",
            result=dict(milestone),
            audit_reference={"milestone_id": milestone["milestone_id"]},
        )

    return _guard("fow_accept_milestone", operation)


def handle_audit_phase(
    runtime: McpRuntime,
    *,
    project_id: str,
    scope_id: str,
    actor: str,
    requirement_ids: list[str] | None = None,
    request_id: str = "",
) -> dict[str, object]:
    def submit() -> dict[str, object]:
        scope = PhaseAuditScope(
            scope_id, _require_string_list(requirement_ids or [], "requirement_ids")
        )

        def operation() -> Mapping[str, object]:
            try:
                audit = runtime.lifecycle.audit_phase(
                    project_id,
                    scope,
                    actor=actor,
                    request_id=f"{request_id}:phase" if request_id else "",
                )
            except ValueError as exc:
                raise JobBlockedError("phase_scope_rejected") from exc
            return {
                "phase_audit_id": audit.audit_id or 0,
                "scope_id": audit.scope.scope_id,
                "delta_count": len(audit.deltas),
            }

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="audit_phase",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_audit_phase",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_audit_phase", submit)


def handle_what_next(
    runtime: McpRuntime,
    *,
    project_id: str,
    scope_id: str = "project-default",
    milestone_id: str = "",
    detail_level: str = "standard",
    offset: int = 0,
    limit: int = _RECOVERY_DEFAULT_LIMIT,
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        detail, page_offset, page_limit = _recovery_page_args(
            detail_level,
            offset,
            limit,
        )
        lifecycle_actions = [
            _action_view(item)
            for item in runtime.lifecycle.what_next(project_id, scope_id=scope_id)
        ]
        audit_only_actions = [
            dict(item)
            for item in (runtime.packet_reconciliation.next_actions(project_id))
        ]
        audit_only_actions.sort(
            key=lambda item: (
                int(item.get("priority") or 100),
                str(item.get("action_id") or ""),
            )
        )
        lifecycle_audit_actions = lifecycle_actions + audit_only_actions
        packet_actions = _packet_next_actions(runtime, project_id)
        candidates = packet_actions or lifecycle_actions
        primary_action = (
            dict(candidates[0])
            if candidates
            else {
                "state": "idle",
                "tool": "fow_what_next",
                "operation": "none",
                "decision_class": "mechanical",
                "reason": "no_pending_action",
                "required_inputs": [],
                "alternatives": [],
            }
        )
        alternatives = list(primary_action.pop("alternatives", []))
        milestones = [
            _standard_milestone_view(item)
            for item in runtime.ledger.milestones(project_id)
            if isinstance(item, Mapping)
        ]
        milestone_entry_diagnostics = list(
            runtime.lifecycle.milestone_entry_policy_diagnostics(project_id)
        )
        result: dict[str, object] = {
            "detail_level": detail,
            "primary_action": primary_action,
            "alternatives": alternatives,
            "summary": {
                "packet_action_count": len(packet_actions),
                "lifecycle_action_count": len(lifecycle_audit_actions),
                "milestone_count": len(milestones),
                "blocked_milestone_entry_count": len(milestone_entry_diagnostics),
            },
        }
        if detail == "audit":
            packet_page, packet_pagination = _page(
                packet_actions, offset=page_offset, limit=page_limit
            )
            lifecycle_page, lifecycle_pagination = _page(
                lifecycle_audit_actions, offset=page_offset, limit=page_limit
            )
            milestone_page, milestone_pagination = _page(
                milestones, offset=page_offset, limit=page_limit
            )
            entry_page, entry_pagination = _page(
                milestone_entry_diagnostics,
                offset=page_offset,
                limit=page_limit,
            )
            result.update(
                {
                    "packet_actions": packet_page,
                    "lifecycle_actions": lifecycle_page,
                    "milestones": milestone_page,
                    "milestone_entry_diagnostics": entry_page,
                    "pagination": {
                        "packet_actions": packet_pagination,
                        "lifecycle_actions": lifecycle_pagination,
                        "milestones": milestone_pagination,
                        "milestone_entry_diagnostics": entry_pagination,
                    },
                }
            )
        if milestone_id:
            result["milestone_closure"] = dict(
                runtime.lifecycle.milestone_closure_state(project_id, milestone_id)
            )
            if detail == "audit":
                traceability = runtime.milestone_traceability.projection(
                    project_id,
                    milestone_id=milestone_id,
                )
                result["live_campaign_readiness"] = [
                    {
                        "requirement_id": str(row.get("requirement_id") or ""),
                        **dict(row.get("live_campaign_readiness") or {}),
                        "coverage_state": str(row.get("coverage_state") or ""),
                        "coverage_gaps": [
                            str(item) for item in row.get("coverage_gaps", [])
                        ],
                        "covered_use_case_goal_node_ids": [
                            str(item)
                            for item in row.get("covered_use_case_goal_node_ids", [])
                        ],
                        "covered_sequence_goal_node_ids": [
                            str(item)
                            for item in row.get("covered_sequence_goal_node_ids", [])
                        ],
                    }
                    for row in traceability.get("rows", [])
                    if isinstance(row, Mapping)
                ]
        return envelope(
            tool="fow_what_next",
            status="success",
            result=result,
        )

    return _guard("fow_what_next", operation)


def _packet_next_actions(
    runtime: McpRuntime, project_id: str
) -> list[Mapping[str, object]]:
    actions: list[Mapping[str, object]] = []
    for change in runtime.ledger.list_changes(project_id):
        change_id = str(change.get("change_id") or "")
        for packet in change.get("packets", []):
            if not isinstance(packet, Mapping):
                continue
            if str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES:
                continue
            packet_id = str(packet.get("packet_id") or "")
            guard = runtime.packet_guards.evaluate(project_id, change_id, packet_id)
            plan = runtime.ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            action = runtime.packet_next_action.project(
                guard,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                spec_revision=int(
                    packet.get("spec_revision") or packet.get("current_revision") or 0
                ),
                plan_revision=(int(plan.get("plan_revision") or 0) if plan else 0),
            )
            actions.append(
                {
                    **dict(action),
                    "scope": {
                        "change_id": change_id,
                        "packet_id": packet_id,
                    },
                }
            )
    return actions


def handle_generate_artifacts(
    runtime: McpRuntime,
    *,
    project_id: str,
    profile_id: str,
    actor: str,
    request_id: str = "",
) -> dict[str, object]:
    def submit() -> dict[str, object]:
        def operation() -> Mapping[str, object]:
            try:
                generation = runtime.artifacts.generate(
                    project_id,
                    profile_id=profile_id,
                    actor=actor,
                    request_id=f"{request_id}:artifacts" if request_id else "",
                )
            except ValueError as exc:
                raise JobBlockedError("artifact_profile_rejected") from exc
            return {
                "generation_id": generation.generation_id or 0,
                "artifact_kinds": [
                    artifact.kind.value for artifact in generation.artifacts
                ],
                "source_ledger_version": generation.source_ledger_version,
            }

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="generate_artifacts",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_generate_artifacts",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_generate_artifacts", submit)


def handle_get_artifacts(
    runtime: McpRuntime,
    *,
    project_id: str,
    generation_id: int | None = None,
    artifact_kind: str = "",
    include_content: bool = False,
) -> dict[str, object]:
    def operation() -> dict[str, object]:
        generations = runtime.ledger.artifact_generations(project_id)
        if generation_id is not None:
            generations = [
                item for item in generations if item["generation_id"] == generation_id
            ]
        views = []
        for generation in generations:
            artifacts = []
            for artifact in generation["artifacts"]:
                if artifact_kind and artifact["artifact_kind"] != artifact_kind:
                    continue
                view = {
                    key: value
                    for key, value in artifact.items()
                    if key != "content" or include_content
                }
                artifacts.append(view)
            if artifacts:
                views.append({**generation, "artifacts": artifacts})
        return envelope(
            tool="fow_get_artifacts",
            status="success",
            result={"generations": views},
        )

    return _guard("fow_get_artifacts", operation)


def handle_ground_intent(
    runtime: McpRuntime,
    *,
    project_id: str,
    goal_node_ids: list[str],
    actor: str,
    request_id: str = "",
    source_revision: str = "",
) -> dict[str, object]:
    def submit() -> dict[str, object]:
        goal_ids = _require_string_list(goal_node_ids, "goal_node_ids")

        def operation() -> Mapping[str, object]:
            if runtime.grounding is None or not runtime.grounding.internal_available:
                if runtime.semantic_validation is None:
                    raise JobBlockedError("model_gateway_unconfigured")
                raise JobBlockedError("implementation_provider_unconfigured")
            try:
                audit = runtime.grounding.ground(
                    project_id,
                    goal_node_ids=goal_ids,
                    actor=actor,
                    request_id=f"{request_id}:grounding" if request_id else "",
                    source_revision=source_revision,
                )
            except ValueError as exc:
                raise JobBlockedError("grounding_scope_rejected") from exc
            except ImplementationProviderUnavailableError as exc:
                raise JobBlockedError(exc.terminal_reason) from exc
            except ImplementationProviderContractError as exc:
                raise JobBlockedError(exc.terminal_reason) from exc
            return {
                "grounding_audit_id": audit.audit_id or 0,
                "disposition": audit.disposition.value,
                "item_count": len(audit.items),
            }

        job = runtime.jobs.submit(
            project_id=project_id,
            kind="ground_intent",
            actor=actor,
            request_id=request_id,
            operation=operation,
        )
        return envelope(
            tool="fow_ground_intent",
            status="success",
            result={"job": _job_view(job)},
            audit_reference={"job_id": job.job_id},
        )

    return _guard("fow_ground_intent", submit)


def handle_get_job(
    runtime: McpRuntime, *, project_id: str, job_id: str
) -> dict[str, object]:
    return _guard(
        "fow_get_job",
        lambda: envelope(
            tool="fow_get_job",
            status="success",
            result={"job": _job_view(runtime.jobs.get(project_id, job_id))},
        ),
    )


def handle_list_jobs(runtime: McpRuntime, *, project_id: str) -> dict[str, object]:
    return _guard(
        "fow_list_jobs",
        lambda: envelope(
            tool="fow_list_jobs",
            status="success",
            result={"jobs": [_job_view(job) for job in runtime.jobs.list(project_id)]},
        ),
    )


def _standalone_receipt(tool: str, value: Mapping[str, object]) -> dict[str, object]:
    status = str(value.get("status", "success"))
    if value.get("state") == "blocked":
        status = "blocked"
    elif value.get("state") in {"conflicting", "conflict"}:
        status = "rejected"
    if status == "conflict":
        status = "rejected"
    elif status == "historical":
        status = "partial"
    if status not in {"success", "partial", "blocked", "rejected", "failed"}:
        status = "success"
    reason = str(value.get("reason") or ("external_outcome_" + str(value["status"])
                 if value.get("status") in {"conflict", "historical"} else ""))
    return envelope(tool=tool, status=status, reason=reason, result=dict(value))


def handle_external_work(
    runtime: McpRuntime, *, project_id: str, change_id: str, packet_id: str,
    operation: str, payload: Mapping[str, object] | None = None,
    actor: str = "", request_id: str = "",
) -> dict[str, object]:
    return _guard("fow_external_work", lambda: _standalone_receipt(
        "fow_external_work", runtime.external_work.call(
            project_id, change_id, packet_id, operation,
            payload=payload, actor=actor, request_id=request_id,
        ),
    ))


def handle_bindings(
    runtime: McpRuntime, *, project_id: str, operation: str,
    association_kind: str = "", host_id: str = "", provider_kind: str = "",
    association_receipt: Mapping[str, object] | None = None,
    actor: str = "", replacement_reason: str = "", request_id: str = "",
) -> dict[str, object]:
    def run() -> dict[str, object]:
        service = runtime.association_receipts
        if operation == "inspect":
            value = service.inspect(project_id)
        elif operation == "export":
            value = service.export_association(project_id, association_kind=association_kind, host_id=host_id, provider_kind=provider_kind)
        elif operation == "import":
            if association_receipt is None:
                raise ValueError("association_receipt is required for import")
            value = service.import_association(project_id, association_receipt, actor=actor, replacement_reason=replacement_reason, request_id=request_id)
        else:
            raise ValueError("operation is invalid")
        return _standalone_receipt("fow_bindings", value)
    return _guard("fow_bindings", run)


def handle_semantic(
    runtime: McpRuntime, *, project_id: str, operation: str,
    role: str = "", execution_mode: str = "", source_path: str = "",
    standard_profile: str = "", assignment_id: str = "",
    result: Mapping[str, object] | None = None, executor_ref: str = "",
    goal_node_ids: list[str] | None = None, host_evidence: Mapping[str, object] | None = None,
    source_revision: str = "", actor: str = "", request_id: str = "",
) -> dict[str, object]:
    def run() -> dict[str, object]:
        service = runtime.semantic_assignments
        if operation == "inventory":
            value = service.inventory(project_id)
        elif operation == "prepare":
            value = service.prepare(project_id, role=role, execution_mode=execution_mode, source_path=source_path, standard_profile=standard_profile, goal_node_ids=tuple(goal_node_ids or []), host_evidence=host_evidence, source_revision=source_revision, actor=actor, request_id=request_id)
        elif operation == "inspect":
            value = service.inspect(project_id, assignment_id)
        elif operation == "submit":
            if result is None:
                raise ValueError("result is required for submit")
            value = service.submit(project_id, assignment_id, result=result, executor_ref=executor_ref, source_revision=source_revision, actor=actor, request_id=request_id)
        elif operation == "adopt":
            value = service.adopt(project_id, assignment_id, actor=actor, request_id=request_id)
        elif operation == "execute_internal":
            value = service.execute_internal(project_id, assignment_id, actor=actor, request_id=request_id)
        else:
            raise ValueError("operation is invalid")
        return _standalone_receipt("fow_semantic", value)
    return _guard("fow_semantic", run)


def create_app(
    runtime: McpRuntime,
    *,
    host: str = "127.0.0.1",
    port: int = 8010,
) -> FastMCP:
    """Build a compact MCP catalog over an already initialized runtime."""

    mcp = FastMCP(
        name="Flower MCP",
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
    )

    def fow_capabilities(
        view: str = "summary",
        recipe_name: str = "",
        operation_tool: str = "",
        operation_name: str = "",
    ) -> dict[str, object]:
        return handle_capabilities(
            runtime,
            view=view,
            recipe_name=recipe_name,
            operation_tool=operation_tool,
            operation_name=operation_name,
        )

    def fow_create_project(
        project_id: str, name: str, actor: str, request_id: str = ""
    ) -> dict[str, object]:
        return handle_create_project(
            runtime,
            project_id=project_id,
            name=name,
            actor=actor,
            request_id=request_id,
        )

    def fow_interaction(
        interaction_session_ref: str,
        operation: InteractionOperation = InteractionOperation.STATUS,
        project_id: str = "",
        project_selection: int = 0,
        area: int = 0,
        selection: int = 0,
        frame_ref: str = "",
        query: str = "",
        limit: int = 9,
        page_action: str = "refine",
        actor: str = "orchestrator",
        request_id: str = "",
        trigger: str = "",
        previous_anchor_fingerprint: str = "",
        trigger_ref: str = "",
        breath_available: bool = False,
    ) -> dict[str, object]:
        return _guard(
            "fow_interaction",
            lambda: envelope(
                tool="fow_interaction",
                status="success",
                result=dict(
                    runtime.interaction_projection.execute(
                        str(operation),
                        interaction_session_ref=interaction_session_ref,
                        project_id=project_id,
                        project_selection=project_selection,
                        area=area,
                        selection=selection,
                        frame_ref=frame_ref,
                        query=query,
                        limit=limit,
                        page_action=page_action,
                        actor=actor,
                        request_id=request_id,
                        trigger=trigger,
                        previous_anchor_fingerprint=previous_anchor_fingerprint,
                        trigger_ref=trigger_ref,
                        breath_available=breath_available,
                    )
                ),
            ),
        )

    def fow_bootstrap(
        project_id: str,
        operation: str,
        actor: str,
        project_name: str = "",
        path: str = "",
        bootstrap_id: str = "",
        answer: Annotated[dict[str, object] | None, WithJsonSchema(bootstrap_input_schema("answer", nullable=True))] = None,
        correspondence: Annotated[dict[str, object] | None, WithJsonSchema(bootstrap_input_schema("correspondence", nullable=True))] = None,
        milestone_ids: list[str] | None = None,
        roadmap_fingerprint: str = "",
        continuation_choice: str = "",
        continuation_reference: str = "",
        progress_revision: str = "",
        intake: dict[str, object] | None = None,
        contradiction: dict[str, object] | None = None,
        confirmation_reference: str = "",
        completion_reference: str = "",
        reason: str = "",
        provider_kind: str = "",
        provider_scope_id: str = "",
        provider_context_id: str = "",
        surfaces: list[str] | None = None,
        replacement_reason: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_bootstrap(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            project_name=project_name,
            path=path,
            bootstrap_id=bootstrap_id,
            answer=answer,
            correspondence=correspondence,
            milestone_ids=milestone_ids,
            roadmap_fingerprint=roadmap_fingerprint,
            continuation_choice=continuation_choice,
            continuation_reference=continuation_reference,
            progress_revision=progress_revision,
            intake=intake,
            contradiction=contradiction,
            confirmation_reference=confirmation_reference,
            completion_reference=completion_reference,
            reason=reason,
            provider_kind=provider_kind,
            provider_scope_id=provider_scope_id,
            provider_context_id=provider_context_id,
            surfaces=surfaces,
            replacement_reason=replacement_reason,
            request_id=request_id,
        )

    def fow_change(
        project_id: str,
        operation: str,
        actor: str,
        change_id: str = "",
        packet_id: str = "",
        depends_on_packet_id: str = "",
        title: str = "",
        rationale: str = "",
        requirement_ids: list[str] | None = None,
        goal_ids: list[str] | None = None,
        in_scope: list[str] | None = None,
        out_of_scope: list[str] | None = None,
        invariants: list[str] | None = None,
        unresolved_questions: list[str] | None = None,
        source_refs: list[str] | None = None,
        baseline_refs: list[str] | None = None,
        completion_criteria: list[str] | None = None,
        milestone_id: str = "",
        intent: str = "",
        target_policy: str = "",
        active_provider: str = "",
        source_revision: str = "",
        navigation_audit_id: str = "",
        navigation_audit_ids: list[str] | None = None,
        provider: str = "",
        candidate_set_id: str = "",
        candidate_set_ids: list[str] | None = None,
        target_binding_ids: list[str] | None = None,
        context_snapshot_id: str = "",
        context_snapshot_ids: list[str] | None = None,
        summary: str = "",
        diagnostics: list[str] | None = None,
        target_state: str = "",
        truncated: bool = False,
        packet_status: str = "",
        criterion_results: dict[str, object] | None = None,
        blocking_reasons: list[str] | None = None,
        disposition: str = "",
        successor_packet_id: str = "",
        construction_audit_id: str = "",
        question_id: str = "",
        evidence_refs: list[str] | None = None,
        linked_navigation_refs: list[str] | None = None,
        answer_summary: str = "",
        waiver_rationale: str = "",
        policy_ref: str = "",
        profile: str = "balanced",
        pressure_id: str = "",
        accepted_risk_ref: str = "",
        provider_id: str = "",
        reconciliation_scope_id: str = "",
        reconciliation_profile: str = "target-impact-v1",
        claim_id: str = "",
        claim_type: str = "",
        claim_key: str = "",
        subject_ref: str = "",
        predicate: str = "",
        object_ref: str = "",
        assertion: dict[str, object] | None = None,
        claim_required: bool = True,
        claim_dynamic: bool = False,
        claim_contradicted: bool = False,
        contract_version: str = PACKET_EVIDENCE_CONTRACT_VERSION,
        provider_scope_id: str = "",
        provider_snapshot_id: str = "",
        selection_ref: str = "",
        workspace_revision: str = "",
        surfaces: list[str] | None = None,
        fingerprint: str = "",
        completeness: dict[str, object] | None = None,
        claims: list[dict[str, object]] | None = None,
        snapshot_id: str = "",
        reconciliation_item_id: str = "",
        reconciliation_disposition: str = "",
        max_claims: int = 512,
        max_depth: int = 4,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_change(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            change_id=change_id,
            packet_id=packet_id,
            depends_on_packet_id=depends_on_packet_id,
            title=title,
            rationale=rationale,
            requirement_ids=requirement_ids,
            goal_ids=goal_ids,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            invariants=invariants,
            unresolved_questions=unresolved_questions,
            source_refs=source_refs,
            baseline_refs=baseline_refs,
            completion_criteria=completion_criteria,
            milestone_id=milestone_id,
            intent=intent,
            target_policy=target_policy,
            active_provider=active_provider,
            source_revision=source_revision,
            navigation_audit_id=navigation_audit_id,
            navigation_audit_ids=navigation_audit_ids,
            provider=provider,
            candidate_set_id=candidate_set_id,
            candidate_set_ids=candidate_set_ids,
            target_binding_ids=target_binding_ids,
            context_snapshot_id=context_snapshot_id,
            context_snapshot_ids=context_snapshot_ids,
            summary=summary,
            diagnostics=diagnostics,
            target_state=target_state,
            truncated=truncated,
            packet_status=packet_status,
            criterion_results=criterion_results,
            blocking_reasons=blocking_reasons,
            disposition=disposition,
            successor_packet_id=successor_packet_id,
            construction_audit_id=construction_audit_id,
            question_id=question_id,
            evidence_refs=evidence_refs,
            linked_navigation_refs=linked_navigation_refs,
            answer_summary=answer_summary,
            waiver_rationale=waiver_rationale,
            policy_ref=policy_ref,
            profile=profile,
            pressure_id=pressure_id,
            accepted_risk_ref=accepted_risk_ref,
            provider_id=provider_id,
            reconciliation_scope_id=reconciliation_scope_id,
            reconciliation_profile=reconciliation_profile,
            claim_id=claim_id,
            claim_type=claim_type,
            claim_key=claim_key,
            subject_ref=subject_ref,
            predicate=predicate,
            object_ref=object_ref,
            assertion=assertion,
            claim_required=claim_required,
            claim_dynamic=claim_dynamic,
            claim_contradicted=claim_contradicted,
            contract_version=contract_version,
            provider_scope_id=provider_scope_id,
            provider_snapshot_id=provider_snapshot_id,
            selection_ref=selection_ref,
            workspace_revision=workspace_revision,
            surfaces=surfaces,
            fingerprint=fingerprint,
            completeness=completeness,
            claims=claims,
            snapshot_id=snapshot_id,
            reconciliation_item_id=reconciliation_item_id,
            reconciliation_disposition=reconciliation_disposition,
            max_claims=max_claims,
            max_depth=max_depth,
            request_id=request_id,
        )

    def fow_assurance(
        project_id: str,
        operation: str,
        actor: str,
        change_id: str = "",
        packet_id: str = "",
        finding_id: str = "",
        title: str = "",
        rationale: str = "",
        severity: str = "",
        finding_kind: str = "unspecified",
        assessment: dict[str, object] | None = None,
        expected_correction: str = "",
        scope_kind: str = "",
        scope_ref: str = "",
        source_anchor: str = "",
        implementation_ref: str = "",
        disposition: str = "",
        disposition_reference: str = "",
        supersedes_finding_id: str = "",
        evidence_refs: list[str] | None = None,
        required_regression_evidence: str = "",
        required_campaign_ids: list[str] | None = None,
        acceptance_reference: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_assurance(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            change_id=change_id,
            packet_id=packet_id,
            finding_id=finding_id,
            title=title,
            rationale=rationale,
            severity=severity,
            finding_kind=finding_kind,
            assessment=assessment,
            expected_correction=expected_correction,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            source_anchor=source_anchor,
            implementation_ref=implementation_ref,
            disposition=disposition,
            disposition_reference=disposition_reference,
            supersedes_finding_id=supersedes_finding_id,
            evidence_refs=evidence_refs,
            required_regression_evidence=required_regression_evidence,
            required_campaign_ids=required_campaign_ids,
            acceptance_reference=acceptance_reference,
            request_id=request_id,
        )

    def fow_run(
        project_id: str,
        operation: str,
        actor: str,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
        step_id: str = "",
        depends_on_step_id: str = "",
        objective: str = "",
        orchestrator_ref: str = "",
        external_ref: str = "",
        source_ref: str = "",
        title: str = "",
        action: str = "",
        target_refs: dict[str, object] | None = None,
        evidence_refs: list[str] | None = None,
        step_required: bool = True,
        blocking_reason: str = "",
        next_expected_action: str = "",
        completion_reference: str = "",
        reason: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_run(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            change_id=change_id,
            packet_id=packet_id,
            run_id=run_id,
            step_id=step_id,
            depends_on_step_id=depends_on_step_id,
            objective=objective,
            orchestrator_ref=orchestrator_ref,
            external_ref=external_ref,
            source_ref=source_ref,
            title=title,
            action=action,
            target_refs=target_refs,
            evidence_refs=evidence_refs,
            step_required=step_required,
            blocking_reason=blocking_reason,
            next_expected_action=next_expected_action,
            completion_reference=completion_reference,
            reason=reason,
            request_id=request_id,
        )

    def fow_handover(
        project_id: str,
        operation: str,
        actor: str = "",
        handover_id: str = "",
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
        profile_version: str = "handover-context-v1",
        projection_kind: str = "lifecycle",
        focus_kind: str = "project",
        focus_ref: str = "",
        milestone_ids: list[str] | None = None,
        limit: int = 10,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_handover(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            handover_id=handover_id,
            change_id=change_id,
            packet_id=packet_id,
            run_id=run_id,
            profile_version=profile_version,
            projection_kind=projection_kind,
            focus_kind=focus_kind,
            focus_ref=focus_ref,
            milestone_ids=milestone_ids,
            limit=limit,
            request_id=request_id,
        )

    def fow_register_requirement(
        project_id: str,
        title: str,
        statement: str,
        category: str,
        rationale: str,
        actor: str,
        source_anchor: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_register_requirement(
            runtime,
            project_id=project_id,
            title=title,
            statement=statement,
            category=category,
            rationale=rationale,
            actor=actor,
            source_anchor=source_anchor,
            request_id=request_id,
        )

    def fow_get_requirement(project_id: str, requirement_id: str) -> dict[str, object]:
        return handle_get_requirement(
            runtime,
            project_id=project_id,
            requirement_id=requirement_id,
        )

    def fow_revise_requirement(
        project_id: str,
        requirement_id: str,
        title: str,
        statement: str,
        category: str,
        rationale: str,
        actor: str,
        source_anchor: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_revise_requirement(
            runtime,
            project_id=project_id,
            requirement_id=requirement_id,
            title=title,
            statement=statement,
            category=category,
            rationale=rationale,
            actor=actor,
            source_anchor=source_anchor,
            request_id=request_id,
        )

    def fow_set_requirement_lifecycle(
        project_id: str,
        requirement_id: str,
        lifecycle_status: str,
        reason: str,
        actor: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_set_requirement_lifecycle(
            runtime,
            project_id=project_id,
            requirement_id=requirement_id,
            lifecycle_status=lifecycle_status,
            reason=reason,
            actor=actor,
            governed_approval_reference=governed_approval_reference,
            request_id=request_id,
        )

    def fow_record_verification(
        project_id: str,
        requirement_id: str,
        verification_kind: str,
        outcome: str,
        reference: str,
        actor: str,
        metadata: dict[str, object] | None = None,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_record_verification(
            runtime,
            project_id=project_id,
            requirement_id=requirement_id,
            verification_kind=verification_kind,
            outcome=outcome,
            reference=reference,
            actor=actor,
            metadata=metadata,
            request_id=request_id,
        )

    def fow_traceability(
        project_id: str,
        milestone_id: str = "",
        detail_level: str = "standard",
        offset: int = 0,
        limit: int = _RECOVERY_DEFAULT_LIMIT,
    ) -> dict[str, object]:
        return handle_traceability(
            runtime,
            project_id=project_id,
            milestone_id=milestone_id,
            detail_level=detail_level,
            offset=offset,
            limit=limit,
        )

    def fow_goal(
        project_id: str,
        operation: str,
        view: str = "summary",
        detail_level: str = "standard",
        offset: int = 0,
        limit: int = _RECOVERY_DEFAULT_LIMIT,
        actor: str = "",
        title: str = "",
        use_case_actor: str = "",
        objective: str = "",
        observable_outcome: str = "",
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        invariants: list[str] | None = None,
        participants: list[str] | None = None,
        normal_steps: list[str] | None = None,
        alternate_steps: list[str] | None = None,
        failure_steps: list[str] | None = None,
        expected_effects: list[str] | None = None,
        statement: str = "",
        category: str = "",
        source_goal_id: str = "",
        target_goal_id: str = "",
        relation: str = "",
        source_anchor: dict[str, object] | None = None,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_goal(
            runtime,
            project_id=project_id,
            operation=operation,
            view=view,
            detail_level=detail_level,
            offset=offset,
            limit=limit,
            actor=actor,
            title=title,
            use_case_actor=use_case_actor,
            objective=objective,
            observable_outcome=observable_outcome,
            preconditions=preconditions,
            postconditions=postconditions,
            invariants=invariants,
            participants=participants,
            normal_steps=normal_steps,
            alternate_steps=alternate_steps,
            failure_steps=failure_steps,
            expected_effects=expected_effects,
            statement=statement,
            category=category,
            source_goal_id=source_goal_id,
            target_goal_id=target_goal_id,
            relation=relation,
            source_anchor=source_anchor,
            request_id=request_id,
        )

    def fow_validate_srs(
        project_id: str,
        source_path: str,
        standard_profile: str,
        actor: str,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_validate_srs(
            runtime,
            project_id=project_id,
            source_path=source_path,
            standard_profile=standard_profile,
            actor=actor,
            request_id=request_id,
        )

    def fow_import_srs(
        project_id: str,
        source_path: str,
        standard_profile: str,
        actor: str,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_import_srs(
            runtime,
            project_id=project_id,
            source_path=source_path,
            standard_profile=standard_profile,
            actor=actor,
            request_id=request_id,
        )

    def fow_revise_srs_baseline(
        project_id: str,
        previous_baseline_id: str,
        source_path: str,
        standard_profile: str,
        actor: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_revise_srs_baseline(
            runtime,
            project_id=project_id,
            previous_baseline_id=previous_baseline_id,
            source_path=source_path,
            standard_profile=standard_profile,
            actor=actor,
            governed_approval_reference=governed_approval_reference,
            request_id=request_id,
        )

    def fow_promote_milestone(
        project_id: str,
        name: str,
        requirement_ids: list[str],
        dependency_closure_ids: list[str],
        entry_policy: dict[str, object],
        exit_policy: dict[str, object],
        risk_disposition: str,
        actor: str,
        acceptance_evidence: list[str] | None = None,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_promote_milestone(
            runtime,
            project_id=project_id,
            name=name,
            requirement_ids=requirement_ids,
            dependency_closure_ids=dependency_closure_ids,
            entry_policy=entry_policy,
            exit_policy=exit_policy,
            risk_disposition=risk_disposition,
            actor=actor,
            acceptance_evidence=acceptance_evidence,
            request_id=request_id,
        )

    def fow_accept_milestone(
        project_id: str,
        milestone_id: str,
        acceptance_evidence: list[str],
        actor: str,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_accept_milestone(
            runtime,
            project_id=project_id,
            milestone_id=milestone_id,
            acceptance_evidence=acceptance_evidence,
            actor=actor,
            request_id=request_id,
        )

    def fow_audit_phase(
        project_id: str,
        scope_id: str,
        actor: str,
        requirement_ids: list[str] | None = None,
        request_id: str = "",
    ) -> dict[str, object]:
        return handle_audit_phase(
            runtime,
            project_id=project_id,
            scope_id=scope_id,
            actor=actor,
            requirement_ids=requirement_ids,
            request_id=request_id,
        )

    def fow_what_next(
        project_id: str,
        scope_id: str = "project-default",
        milestone_id: str = "",
        detail_level: str = "standard",
        offset: int = 0,
        limit: int = _RECOVERY_DEFAULT_LIMIT,
    ) -> dict[str, object]:
        return handle_what_next(
            runtime,
            project_id=project_id,
            scope_id=scope_id,
            milestone_id=milestone_id,
            detail_level=detail_level,
            offset=offset,
            limit=limit,
        )

    def fow_generate_artifacts(
        project_id: str, profile_id: str, actor: str, request_id: str = ""
    ) -> dict[str, object]:
        return handle_generate_artifacts(
            runtime,
            project_id=project_id,
            profile_id=profile_id,
            actor=actor,
            request_id=request_id,
        )

    def fow_get_artifacts(
        project_id: str,
        generation_id: int | None = None,
        artifact_kind: str = "",
        include_content: bool = False,
    ) -> dict[str, object]:
        return handle_get_artifacts(
            runtime,
            project_id=project_id,
            generation_id=generation_id,
            artifact_kind=artifact_kind,
            include_content=include_content,
        )

    def fow_ground_intent(
        project_id: str,
        goal_node_ids: list[str],
        actor: str,
        request_id: str = "",
        source_revision: str = "",
    ) -> dict[str, object]:
        return handle_ground_intent(
            runtime,
            project_id=project_id,
            goal_node_ids=goal_node_ids,
            actor=actor,
            request_id=request_id,
            source_revision=source_revision,
        )

    def fow_get_job(project_id: str, job_id: str) -> dict[str, object]:
        return handle_get_job(runtime, project_id=project_id, job_id=job_id)

    def fow_list_jobs(project_id: str) -> dict[str, object]:
        return handle_list_jobs(runtime, project_id=project_id)

    def fow_packet_author(
        actor: str,
        request_id: str,
        project_id: str,
        packet_id: str = "",
        change_id: str = "",
        operation: str = "add_unit",
        title: str = "",
        intent: str = "",
        rationale: str = "",
        completion_criteria: list[str] | None = None,
        purpose: str = "implementation",
        milestone_id: str = "",
        requirement_ids: list[str] | None = None,
        goal_ids: list[str] | None = None,
        in_scope: list[str] | None = None,
        out_of_scope: list[str] | None = None,
        invariants: list[str] | None = None,
        unresolved_questions: list[str] | None = None,
        target_policy: str = "code_targets_required",
        active_provider: str = "",
        source_revision: str = "",
        finding_ids: list[str] | None = None,
        predecessor_packet_id: str = "",
        predecessor_dependency_policy: str = "materialized",
        required_regression_evidence: str = "",
        required_campaign_ids: list[str] | None = None,
        work_plan: dict[str, object] | None = None,
        unit: dict[str, object] | None = None,
        target_selection: dict[str, object] | None = None,
        unit_patch: dict[str, object] | None = None,
        client_unit_key: str = "",
        depends_on: list[str] | None = None,
        answers: list[dict[str, object]] | None = None,
        response: dict[str, object] | None = None,
        gate_fingerprint: str = "",
        expected_spec_revision: int = 0,
        expected_plan_revision: int | None = None,
    ) -> dict[str, object]:
        return handle_packet_author(
            runtime,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            operation=operation,
            title=title,
            intent=intent,
            rationale=rationale,
            completion_criteria=completion_criteria,
            purpose=purpose,
            milestone_id=milestone_id,
            requirement_ids=requirement_ids,
            goal_ids=goal_ids,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            invariants=invariants,
            unresolved_questions=unresolved_questions,
            target_policy=target_policy,
            active_provider=active_provider,
            source_revision=source_revision,
            finding_ids=finding_ids,
            predecessor_packet_id=predecessor_packet_id,
            predecessor_dependency_policy=predecessor_dependency_policy,
            required_regression_evidence=required_regression_evidence,
            required_campaign_ids=required_campaign_ids,
            work_plan=work_plan,
            unit=unit,
            target_selection=target_selection,
            unit_patch=unit_patch,
            client_unit_key=client_unit_key,
            depends_on=depends_on,
            actor=actor,
            answers=answers,
            response=response,
            gate_fingerprint=gate_fingerprint,
            expected_spec_revision=expected_spec_revision,
            expected_plan_revision=expected_plan_revision,
            request_id=request_id,
        )

    def fow_packet_advance(
        actor: str,
        request_id: str,
        project_id: str,
        packet_id: str,
        change_id: str = "",
        decision: dict[str, object] | None = None,
        expected_spec_revision: int | None = None,
        expected_plan_revision: int | None = None,
    ) -> dict[str, object]:
        return handle_packet_advance(
            runtime,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            actor=actor,
            request_id=request_id,
            decision=decision,
            expected_spec_revision=expected_spec_revision,
            expected_plan_revision=expected_plan_revision,
        )

    def fow_packet_inspect(
        project_id: str,
        packet_id: str,
        change_id: str = "",
        detail_level: str = "standard",
        view: str = "summary",
        offset: int = 0,
        limit: int = _RECOVERY_DEFAULT_LIMIT,
    ) -> dict[str, object]:
        return handle_packet_inspect(
            runtime,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            detail_level=detail_level,
            view=view,
            offset=offset,
            limit=limit,
        )

    def fow_campaign_author(
        project_id: str,
        operation: str,
        actor: str,
        request_id: str,
        campaign_id: str = "",
        case_id: str = "",
        evidence_id: str = "",
        obligation_id: str = "",
        oracle_id: str = "",
        question_id: str = "",
        provider_command_id: str = "",
        title: str = "",
        scope: dict[str, object] | None = None,
        case: dict[str, object] | None = None,
        case_order: list[str] | None = None,
        decision: str = "",
        rationale: str = "",
        coverage_intent: str = "",
        oracle: dict[str, object] | None = None,
        answer: Any = None,
        answer_authority: str = "",
        provenance: list[str] | None = None,
        waiver_scope: str = "",
        source_files: dict[str, str] | None = None,
        harness: dict[str, object] | None = None,
        requested_capability: dict[str, object] | None = None,
        authority_reference: str = "",
        disposition_reference: str = "",
        exception_obligation_ids: list[str] | None = None,
        evidence_gaps: list[str] | None = None,
        risk_authority: str = "",
        regression_obligation: bool = False,
        expected_fingerprint: str = "",
    ) -> dict[str, object]:
        return handle_campaign_author(
            runtime,
            project_id=project_id,
            operation=operation,
            actor=actor,
            request_id=request_id,
            campaign_id=campaign_id,
            case_id=case_id,
            evidence_id=evidence_id,
            obligation_id=obligation_id,
            oracle_id=oracle_id,
            question_id=question_id,
            provider_command_id=provider_command_id,
            title=title,
            scope=scope,
            case=case,
            case_order=case_order,
            decision=decision,
            rationale=rationale,
            coverage_intent=coverage_intent,
            oracle=oracle,
            answer=answer,
            answer_authority=answer_authority,
            provenance=provenance,
            waiver_scope=waiver_scope,
            source_files=source_files,
            harness=harness,
            requested_capability=requested_capability,
            authority_reference=authority_reference,
            disposition_reference=disposition_reference,
            exception_obligation_ids=exception_obligation_ids,
            evidence_gaps=evidence_gaps,
            risk_authority=risk_authority,
            regression_obligation=regression_obligation,
            expected_fingerprint=expected_fingerprint,
        )

    def fow_campaign_advance(
        project_id: str,
        actor: str,
        request_id: str,
        campaign_id: str = "",
        change_id: str = "",
        transition_budget: int = 8,
    ) -> dict[str, object]:
        return handle_campaign_advance(
            runtime,
            project_id=project_id,
            actor=actor,
            request_id=request_id,
            campaign_id=campaign_id,
            change_id=change_id,
            transition_budget=transition_budget,
        )

    def fow_campaign_inspect(
        project_id: str,
        campaign_id: str = "",
        change_id: str = "",
        view: str = "summary",
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, object]:
        return handle_campaign_inspect(
            runtime,
            project_id=project_id,
            campaign_id=campaign_id,
            change_id=change_id,
            view=view,
            offset=offset,
            limit=limit,
        )

    def fow_external_work(
        project_id: str, change_id: str, packet_id: str,
        operation: Literal["set_mode", "criteria", "reconcile_criteria", "add_criterion", "edit_criterion", "remove_criterion", "upgrade_validation", "validation", "export_plan", "todo", "report_outcome", "reconcile_outcome"],
        payload: dict[str, Any] | None = None, actor: str = "", request_id: str = "",
    ) -> dict[str, object]:
        return handle_external_work(runtime, project_id=project_id, change_id=change_id, packet_id=packet_id, operation=operation, payload=payload, actor=actor, request_id=request_id)

    def fow_bindings(
        project_id: str, operation: Literal["inspect", "export", "import"],
        association_kind: str = "", host_id: str = "", provider_kind: str = "",
        association_receipt: dict[str, Any] | None = None,
        actor: str = "", replacement_reason: str = "", request_id: str = "",
    ) -> dict[str, object]:
        return handle_bindings(runtime, project_id=project_id, operation=operation, association_kind=association_kind, host_id=host_id, provider_kind=provider_kind, association_receipt=association_receipt, actor=actor, replacement_reason=replacement_reason, request_id=request_id)

    def fow_semantic(
        project_id: str, operation: Literal["inventory", "prepare", "inspect", "submit", "adopt", "execute_internal"],
        role: str = "", execution_mode: str = "", source_path: str = "",
        standard_profile: str = "", assignment_id: str = "",
        result: dict[str, Any] | None = None, executor_ref: str = "",
        goal_node_ids: list[str] | None = None, host_evidence: dict[str, Any] | None = None,
        source_revision: str = "", actor: str = "", request_id: str = "",
    ) -> dict[str, object]:
        return handle_semantic(runtime, project_id=project_id, operation=operation, role=role, execution_mode=execution_mode, source_path=source_path, standard_profile=standard_profile, assignment_id=assignment_id, result=result, executor_ref=executor_ref, goal_node_ids=goal_node_ids, host_evidence=host_evidence, source_revision=source_revision, actor=actor, request_id=request_id)

    handler_namespace = locals()
    assert_projector_registry(public_tool_names())
    tools_by_name = {
        name: handler_namespace[name]
        for name in public_tool_names()
        if callable(handler_namespace.get(name))
    }
    missing_handlers = set(public_tool_names()).difference(tools_by_name)
    if missing_handlers:
        raise RuntimeError(
            "public tool catalog has no callable handler: "
            + ", ".join(sorted(missing_handlers))
        )
    for descriptor in public_tool_catalog():
        name = str(descriptor["name"])
        mcp.add_tool(
            model_facing_tool(tools_by_name[name], tool_name=name),
            name=name,
            description=str(descriptor["description"]),
        )
    return mcp


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flower-mcp", description="Flower MCP standalone software-engineering lifecycle plane")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--config")
    selection.add_argument("--profile")
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    return parser


def main(argv: list[str] | None = None) -> None:
    from flow_of_work_mcp.profiles import ProfileError, prepare_profile
    from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership

    parser = build_cli_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in the range 1..65535")
    try:
        if args.config is not None and args.profile_root is not None:
            raise ProfileError("--config and --profile-root cannot be combined")
        config_path = args.config if args.config is not None else prepare_profile(args.profile_root, args.profile or "default")
        config = load_config(config_path)
    except (FlowConfigError, ProfileError, OSError) as exc:
        log_bootstrap_error(str(exc))
        parser.error(str(exc))
    try:
        ownership = acquire_runtime_ownership(config.runtime.database_path)
    except RuntimeOwnershipError as exc:
        parser.error(f"{exc.code}: {exc}")

    manager = LoggerManager()
    logger = None
    runtime: McpRuntime | None = None
    composition_cleanup_incomplete = False
    try:
        manager.setup(config.logging)
        logger = get_logger("server", session_id="server")
        summary = config.safe_summary()
        logger.info(
            "configuration loaded schema=%s config=%s database=%s import_root=%s logs=%s",
            summary["schema_version"], summary["config_path"], summary["database_path"],
            summary["import_root"], summary["logs_path"],
        )
        logger.info(
            "components model=%s implementation_provider=%s bootstrap_provider=%s",
            summary["model_backend"], summary["implementation_provider_enabled"],
            summary["bootstrap_provider_enabled"],
        )
        runtime = build_runtime_from_config(config, ownership=ownership)
        app = create_app(runtime, host=args.host, port=args.port)
        logger.info(
            "MCP server ready transport=%s host=%s port=%d",
            args.transport, args.host, args.port,
        )
        app.run(transport=args.transport)
    except RuntimeCompositionCleanupError:
        composition_cleanup_incomplete = True
        if logger is not None:
            logger.error("server composition cleanup incomplete; runtime ownership retained")
        raise
    except Exception as exc:
        if logger is not None:
            logger.error("server startup/runtime failure type=%s", type(exc).__name__)
        raise
    finally:
        runtime_stopped = False
        try:
            if runtime is not None:
                runtime.close()
                runtime_stopped = True
        finally:
            # Failed shutdown may leave live workers. Keep the OS lease until
            # successful close or process exit rather than admitting a rival.
            if (runtime is None and not composition_cleanup_incomplete) or runtime_stopped:
                ownership.close()
            if logger is not None:
                if (runtime is None and not composition_cleanup_incomplete) or runtime_stopped:
                    logger.info("MCP server stopped")
                else:
                    logger.error("MCP server shutdown incomplete; runtime ownership retained")
            manager.close()


if __name__ == "__main__":
    main()
