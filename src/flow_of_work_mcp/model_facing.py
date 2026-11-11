"""Explicit model-facing Markdown projection for Flower MCP tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
import inspect
from typing import Annotated, Any, TypeVar, cast, get_type_hints

from mcp.types import CallToolResult, TextContent
from pydantic import Field

from flow_of_work_mcp.application.campaign_markdown import (
    campaign_check_lines,
    campaign_detail_lines,
    campaign_error_markdown,
    campaign_receipt_lines,
)
from flow_of_work_mcp.application.operation_contracts import (
    operation_names,
    parameter_help,
    public_tool_names,
)
from flow_of_work_mcp.application.external_plan_markdown import REVIEW_ACCEPTANCE_MEANING, render_assurance_result, render_external_result, repository_review_summary
from flow_of_work_mcp.application.roadmap_markdown import render_roadmap
from flow_of_work_mcp.core.domain.artifacts import ArtifactKind
from flow_of_work_mcp.core.domain.packet_validation_projection import CRITERION_RESPONSIBILITY_GAPS
from flow_of_work_mcp.markdown_adapter import (
    MarkdownArtifact,
    MarkdownJsonIsland,
    render_markdown,
    projection_boundary,
    safe_heading,
    safe_inline,
)

F = TypeVar("F", bound=Callable[..., Any])

_DEFAULT_OUTPUT_BUDGET = 512_000
_DEFAULT_EXACT_CALL_KEYS = frozenset(
    {
        "next_tool_call",
        "next_gate_call",
        "continuation",
        "continuations",
        "recovery_calls",
    }
)


@dataclass(frozen=True)
class ProjectionSpec:
    """One explicit public tool projection contract."""

    title: str
    result_heading: str
    artifact_keys: frozenset[str] = frozenset()
    exact_call_keys: frozenset[str] = _DEFAULT_EXACT_CALL_KEYS


_SPECS: dict[str, ProjectionSpec] = {
    "fow_architecture": ProjectionSpec("Flower Architecture", "Architecture Authority"),
    "fow_external_work": ProjectionSpec("Flower External Work", "Plan, Executor And Outcome", frozenset({"content", "markdown"})),
    "fow_bindings": ProjectionSpec("Flower Associations", "Association Receipt"),
    "fow_semantic": ProjectionSpec("Flower Semantic Assignment", "Assignment State", frozenset({"prompt", "content", "markdown", "task_markdown"})),
    "fow_capabilities": ProjectionSpec("Flower Capabilities", "Capability Catalog"),
    "fow_create_project": ProjectionSpec("Project Creation", "Project Receipt"),
    "fow_interaction": ProjectionSpec("Flower Interaction", "Interaction Frame"),
    "fow_register_requirement": ProjectionSpec(
        "Requirement Registration", "Requirement Receipt"
    ),
    "fow_get_requirement": ProjectionSpec("Requirement", "Requirement State"),
    "fow_revise_requirement": ProjectionSpec(
        "Requirement Revision", "Revision Receipt"
    ),
    "fow_set_requirement_lifecycle": ProjectionSpec(
        "Requirement Lifecycle", "Lifecycle Receipt"
    ),
    "fow_record_verification": ProjectionSpec(
        "Verification Evidence", "Verification Receipt"
    ),
    "fow_traceability": ProjectionSpec("Traceability", "Traceability Evidence"),
    "fow_goal": ProjectionSpec("Goal Graph", "Goal State"),
    "fow_validate_srs": ProjectionSpec("SRS Validation", "Validation Job"),
    "fow_import_srs": ProjectionSpec(
        "SRS Import",
        "Import Receipt",
        frozenset({"content", "source", "markdown"}),
    ),
    "fow_revise_srs_baseline": ProjectionSpec(
        "SRS Baseline Revision", "Baseline Receipt"
    ),
    "fow_promote_milestone": ProjectionSpec(
        "Milestone Promotion", "Promotion Receipt"
    ),
    "fow_accept_milestone": ProjectionSpec(
        "Milestone Acceptance", "Acceptance Receipt"
    ),
    "fow_audit_phase": ProjectionSpec("Phase Audit", "Audit Job"),
    "fow_what_next": ProjectionSpec("Prioritized Work", "Work Projection"),
    "fow_generate_artifacts": ProjectionSpec(
        "Artifact Generation", "Generation Job"
    ),
    "fow_get_artifacts": ProjectionSpec(
        "Generated Artifacts",
        "Artifact State",
        frozenset({"content", "markdown", "text", "source"}),
    ),
    "fow_ground_intent": ProjectionSpec("Intent Grounding", "Grounding Job"),
    "fow_get_job": ProjectionSpec(
        "Flower Job",
        "Job State",
        frozenset({"content", "stdout", "stderr", "logs"}),
    ),
    "fow_list_jobs": ProjectionSpec("Flower Jobs", "Jobs"),
    "fow_bootstrap": ProjectionSpec("Lifecycle Bootstrap", "Bootstrap State", frozenset({"markdown"})),
    "fow_change": ProjectionSpec("Change Control", "Change State"),
    "fow_assurance": ProjectionSpec("Assurance", "Assurance State"),
    "fow_run": ProjectionSpec("Implementation Run", "Run State"),
    "fow_handover": ProjectionSpec(
        "Lifecycle Handover",
        "Handover State",
        frozenset({"content", "markdown"}),
    ),
    "fow_packet_author": ProjectionSpec("Packet Authoring", "Packet Receipt"),
    "fow_packet_advance": ProjectionSpec("Packet Advancement", "Packet Gate"),
    "fow_packet_inspect": ProjectionSpec("Packet Inspection", "Packet State"),
    "fow_campaign_author": ProjectionSpec(
        "Campaign Authoring",
        "Campaign Receipt",
        frozenset({"content", "source", "markdown"}),
    ),
    "fow_campaign_advance": ProjectionSpec(
        "Campaign Advancement", "Campaign Gate"
    ),
    "fow_campaign_inspect": ProjectionSpec(
        "Campaign Inspection", "Campaign State"
    ),
}

_OPERATION_SPECS: dict[tuple[str, str], ProjectionSpec] = {
    (tool_name, operation): _SPECS[tool_name]
    for tool_name in public_tool_names()
    for operation in operation_names(tool_name)
}


class ModelFacingProjectionError(RuntimeError):
    """Raised when a public response cannot honor its projection contract."""


def projector_names() -> frozenset[str]:
    return frozenset(_SPECS)


def operation_projector_routes() -> frozenset[tuple[str, str]]:
    return frozenset(_OPERATION_SPECS)


def _has_semantic_recovery(value: object) -> bool:
    """Recognize selected architecture/provider context in current or frozen HAND."""
    if isinstance(value, Mapping):
        return bool({"architecture", "provider_validation"} & set(value)) or any(
            _has_semantic_recovery(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_semantic_recovery(item) for item in value)
    return False


def assert_projector_registry(tool_names: Iterable[str]) -> None:
    expected = {str(name) for name in tool_names}
    actual = set(_SPECS)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ModelFacingProjectionError(
            f"model_facing_registry_parity:missing={missing}:extra={extra}"
        )
    expected_operations = {
        (tool_name, operation)
        for tool_name in public_tool_names()
        for operation in operation_names(tool_name)
    }
    actual_operations = set(_OPERATION_SPECS)
    if expected_operations != actual_operations:
        missing_operations = sorted(expected_operations - actual_operations)
        extra_operations = sorted(actual_operations - expected_operations)
        raise ModelFacingProjectionError(
            "model_facing_operation_parity:"
            f"missing={missing_operations}:extra={extra_operations}"
        )


def model_facing_tool(
    fn: F,
    *,
    tool_name: str | None = None,
    output_budget: int = _DEFAULT_OUTPUT_BUDGET,
) -> F:
    """Project responses and describe inputs without changing input validation."""

    name = str(tool_name or getattr(fn, "__name__", "")).strip()
    if name not in _SPECS:
        raise ModelFacingProjectionError(f"missing_model_facing_projector:{name}")
    raw_signature = inspect.signature(fn)
    resolved_hints = get_type_hints(
        fn,
        globalns=getattr(fn, "__globals__", None),
        include_extras=True,
    )
    signature = raw_signature.replace(
        parameters=[
            parameter.replace(
                annotation=Annotated[
                    resolved_hints.get(parameter.name, parameter.annotation),
                    Field(**parameter_help(name, parameter.name)),
                ]
            )
            for parameter in raw_signature.parameters.values()
        ],
        return_annotation=resolved_hints.get(
            "return",
            raw_signature.return_annotation,
        ),
    )

    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> CallToolResult:
        bound = signature.bind_partial(*args, **kwargs)
        raw = fn(*args, **kwargs)
        if isinstance(raw, CallToolResult):
            raise ModelFacingProjectionError(
                f"nested_call_tool_result_not_allowed:{name}"
            )
        if not isinstance(raw, Mapping):
            raise ModelFacingProjectionError(
                f"model_facing_result_must_be_mapping:{name}"
            )
        payload = dict(raw)
        markdown = project_markdown(
            name,
            payload,
            arguments=bound.arguments,
            output_budget=output_budget,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=markdown)],
            structuredContent={"result": payload},
            isError=False,
        )

    wrapped.__annotations__ = {
        **resolved_hints,
        **{parameter.name: parameter.annotation for parameter in signature.parameters.values()},
    }
    wrapped.__signature__ = signature  # type: ignore[attr-defined]
    return cast(F, wrapped)


def _campaign_provider_boundary_lines(boundary: object) -> list[str]:
    if not isinstance(boundary, Mapping):
        return []
    state = boundary.get("state")
    if state not in {"provider_rejected", "provider_unknown"}:
        return []
    deliveries = boundary.get("deliveries") or []
    delivery = deliveries[-1] if deliveries else boundary
    outbox = delivery.get("outbox") or {}
    reason = delivery.get("reason") or outbox.get("last_error") or state
    lines = [f"- **Provider boundary:** {state}", f"- **Cause:** {safe_inline(str(reason)[:240])}"]
    for label, key in (("Case", "case_id"), ("Command", "command_id")):
        if identity := outbox.get(key):
            lines.append(f"- **{label}:** {safe_inline(str(identity)[:80])}")

    action = delivery.get("next_action") or boundary.get("next_action")
    if reason == "effective_project_cross_domain_collision":
        lines.append("- **Next step:** Inspect the provider test draft for this case and resolve its "
                     "overlap with the product checkout. Once the colliding draft is cleared, use "
                     "`fow_campaign_author` / `attest_source` to send the full source inline to an "
                     "unused provider destination. Leave the product checkout unchanged.")
    elif isinstance(action, Mapping) and action.get("tool") and action.get("operation"):
        lines.append(f"- **Next step:** Resolve the reported cause before using "
                     f"`{safe_inline(str(action['tool']))}` / `{safe_inline(str(action['operation']))}`.")
        arguments = action.get("arguments") or {}
        known = [f"`{key}={safe_inline(str(arguments[key])[:80])}`"
                 for key in ("campaign_id", "provider_command_id") if arguments.get(key)]
        if known:
            lines.append("- **Known inputs:** " + ", ".join(known))
        if required := action.get("required_inputs"):
            lines.append("- **Inputs to supply:** " + ", ".join(f"`{safe_inline(str(key))}`" for key in required))
    elif state == "provider_unknown":
        lines.append("- **Next step:** Use `fow_campaign_advance` on this campaign to reconcile "
                     "the same durable command before submitting another declaration.")
    else:
        lines.append("- **Next step:** Inspect the campaign and resolve the reported provider cause before retrying.")
    return lines


def _campaign_work_markdown(
    result: Mapping[str, Any], *, project_id: str, change_id: str, include_horizon: bool, view: str,
) -> str:
    gate = result["lifecycle_gate"]
    campaign = result.get("campaign") or {}
    campaign_id = str(campaign.get("campaign_id") or "")
    work = gate["work_remaining"]
    decision = gate.get("decision_required") or {}
    action = gate["next_action"]
    tool, operation = action["tool"], action["operation"]

    def plain(value: object) -> str:
        return safe_inline(str(value))

    lines = ["# Campaign work", "", f"- **Project:** {plain(project_id)}"]
    if campaign_id:
        lines.append(f"- **Campaign:** {plain(campaign_id)}")
    if change_id := campaign.get("change_id") or change_id:
        lines.append(f"- **Change:** {plain(change_id)}")
    if boundary_lines := _campaign_provider_boundary_lines(result.get("provider_boundary")):
        return "\n".join([*lines, *boundary_lines]) + "\n"
    lines.append(f"- **Current gate:** {plain(gate['lifecycle_state'])} ({plain(gate['state'])})")
    cause = decision.get("missing_fact") or decision.get("prompt") or decision.get("reason")
    if not cause and decision.get("kind") == "obligation_classification":
        cause = f"Classify {decision['obligation_id']}. {decision['statement']}"
    if not cause and decision.get("kind") in {"independent_proof_required", "case_not_host_eligible"}:
        cause = "The selected case needs proof outside the host execution lane."
    if not cause and decision.get("kind") == "product_failure_route":
        cause = decision.get("observation") or "The issued check observed a product failure."
    if gate["lifecycle_state"] == "missing":
        cause = "No current campaign is recorded for this selection."
    if not cause:
        cause = {
            "derive_obligations": "Proof obligations have not been derived for this scope.",
            "attest_source": "The selected case needs current attested test source.",
            "deliver_test_command": "The selected attestation is pending technical validation.",
            "run_test_case": "The selected case still needs current passed run evidence.",
            "authorize_promotion": "Current passed evidence still needs promotion authority.",
            "deliver_promotion": "Promotion is authorized and still needs accepted provider evidence.",
            "issue_host_check": "The selected case needs an issued check for the current source revision.",
            "report_host_result": "Flower is waiting for the observed outcome of the issued check.",
        }.get(operation)
    if cause:
        lines.append(f"- **Cause:** {plain(str(cause)[:360])}")
    elif work.get("current_phase_requirement"):
        lines.append(f"- **Current requirement:** {plain(work['current_phase_requirement'])}")
    if gate.get("semantic_effect"):
        lines.append(f"- **Expected action:** {plain(gate['semantic_effect'])}")

    known = dict(action.get("arguments") or {})
    known.pop("expected_fingerprint", None)
    known.pop("campaign_id", None)
    if operation == "report_host_result":
        lines.append("- **Next step:** Run the issued check with authorized host tools, then call "
                     "`fow_campaign_author` / `report_host_result` with the observed result.")
    elif tool == "fow_campaign_advance":
        lines.append(f"- **Next step:** Call `fow_campaign_advance` for this campaign with your actor and request ID. "
                     f"Its current transition is `{plain(operation)}`.")
    elif tool == "fow_campaign_inspect":
        lines.append(f"- **Next step:** Call `fow_campaign_inspect` for this campaign with `view={plain(operation)}`.")
    else:
        # The campaign gate uses the packet start action as a semantic route.
        # Packet authoring publishes start_packet as its actual selector.
        if tool == "fow_packet_author" and operation == "start":
            operation = "start_packet"
        lines.append(f"- **Next step:** Call `{plain(tool)}` / `{plain(operation)}` for this scope. "
                     "Use `fow_capabilities` for its exact inputs.")
    known_inputs = [f"`{key}={plain(value)}`" for key, value in known.items() if key.endswith("_id") and value]
    capability = known.get("requested_capability")
    if isinstance(capability, Mapping):
        known_inputs.extend(f"`requested_capability.{key}={plain(value)}`" for key, value in capability.items())
    if operation in {"issue_host_check", "report_host_result", "record_finding", "obligations", "advance"}:
        for key in ("attempt_id", "source_revision", "declared_source_revision", "observed_source_revision",
                    "check_reference", "execution_profile", "evidence_id", "last_outcome"):
            if value := decision.get(key):
                known_inputs.append(f"`{key}={plain(str(value)[:180])}`")
        if obligation_ids := decision.get("obligation_ids"):
            known_inputs.append("obligations " + ", ".join(plain(ref) for ref in obligation_ids[:6]))
    if known_inputs:
        label = "Transition context" if tool == "fow_campaign_advance" else "Known inputs"
        lines.append(f"- **{label}:** " + ", ".join(known_inputs))
    if operation == "answer_question":
        lines.append("- **Optional revision pin:** Use the current campaign fingerprint from `fow_campaign_inspect` with `view=oracles`.")
    elif operation == "author_obligations":
        lines.append("- **Required revision pin:** Read `view=obligations` and pass its current fingerprint as `expected_fingerprint`.")
    required_inputs = decision.get("required_inputs") or []
    if required_inputs:
        prefix = {"issue_host_check": "host_check.", "report_host_result": "host_result."}.get(operation, "")
        lines.append("- **Inputs to supply:** " + ", ".join(f"`{prefix}{plain(key)}`" for key in required_inputs))
    if operation == "report_host_result" and isinstance(check := decision.get("check"), Mapping):
        lines.extend(campaign_check_lines(check))
    allowed = gate.get("allowed_responses") or []
    if allowed and operation != "author_oracle":
        choices = [plain(row["value"]) for row in allowed]
        lines.append("- **Decision choices:** " + ", ".join(choices))
        if operation == "answer_question":
            lines.append("- **Decision inputs:** Supply `answer`, `answer_authority` and `provenance`. "
                         "Grounded facts and accepted decisions require nonempty provenance. "
                         "A waiver requires `waiver_scope`.")
        else:
            inputs = list(dict.fromkeys(plain(key) for row in allowed for key in row.get("requires", [])))
            if inputs:
                lines.append("- **Decision inputs:** " + ", ".join(inputs))
    questions = work.get("oracle_questions")
    if questions and questions["scope"] == "oracle_ir" and operation != "answer_question":
        lines.append("- **Optional deterministic IR:** Continue with the current gate above. "
                     "For the separate IR route, inspect `view=oracle_ir` before answering any optional question.")
    elif questions:
        label = "Required source fields" if questions["scope"] == "source" else "Optional deterministic IR fields"
        fields = [f"`{plain(row['field_name'])}` (`{plain(row['question_id'])}`)"
                  for row in questions["ordered_missing_fields"]]
        lines.extend(["", f"## {label} · {plain(questions['oracle_id'])} revision {questions['oracle_revision']} ({len(fields)} remaining)",
                      "", ", ".join(fields), "",
                      f"Current answer slot: `{plain(questions['current_question_id'])}`. "
                      "Record one answer at a time and refresh the gate."])
        if questions["other_pending_questions"]:
            lines.append(f"{questions['other_pending_questions']} additional current questions belong to other Oracles. "
                         "Use campaign inspection with `view=oracles` for details.")
    if include_horizon and work.get("conditional_phases"):
        lines.extend(["", "## Later phases if still applicable", ""])
        lines.extend(f"- {plain(phase['requirement'])}" for phase in work["conditional_phases"])
    if include_horizon and work.get("effort") == "undetermined":
        lines.extend(["", "The total remaining calls depend on decisions and observed evidence."])
    if result.get("transitions"):
        lines.append("- **Transitions applied:** " + ", ".join(plain(row["operation"]) for row in result["transitions"]))
    if (result.get("semantic_delta") or {}).get("replayed"):
        lines.append("- **Receipt:** Exact replay of a recorded request.")
    lines.extend(campaign_receipt_lines(result))
    lines.extend(campaign_detail_lines(result, view))
    return "\n".join(lines) + "\n"


def _requirements_export_markdown(
    result: Mapping[str, Any], *, project_id: str, generation_id: int
) -> str:
    """Present the pinned catalogue without repeating its machine-only mappings."""
    heading = (
        "# Flower Requirements Export\n\n"
        f"- **Project:** {safe_inline(project_id)}\n"
        f"- **Generation ID:** {generation_id}\n"
    )
    generations = result["generations"]
    if not generations:
        return (
            heading + "\nNo requirements catalogue matches this project and generation. "
            "Use `fow_get_artifacts` with `artifact_kind=requirements_catalogue` and omit "
            "`generation_id` and `include_content` to list available generations.\n"
        )
    generation = generations[0]
    artifact = generation["artifacts"][0]
    return (
        heading
        + f"- **Source ledger version:** {generation['source_ledger_version']}\n"
        + f"- **Content SHA-256:** `{artifact['content_sha256']}`\n\n"
        + artifact["content"]
    )


def _lens_catalog_markdown(result: Mapping[str, Any]) -> str:
    """Bounded model orientation; full route membership stays machine-facing."""
    context = result["project_context"]
    lines = ["# Flower Interaction: catalog", "", "## Current State", "",
             "- **Status:** success",
             f"- **Project:** {safe_inline(context['project_id']) if context else 'not selected'}",
             f"- **Selection:** {safe_inline(result['selection_state'])}",
             f"- **Reason:** {safe_inline(result['selection_reason']) or 'none'}",
             f"- **Catalog revision:** {safe_inline(result['catalog_revision'])}",
             f"- **Interaction revision:** {safe_inline(result['interaction_revision'])}",
             "- **Execution admission:** not evaluated", "", "## Work Lenses", "",
             "| Area | Selected | Availability | Prerequisites | Primary | Companions |",
             "| --- | --- | --- | --- | --- | --- |"]
    for lens in result["lenses"]:
        lines.append("| " + " | ".join(safe_inline(str(value)) for value in (
            lens["area"], "yes" if lens["selected"] else "no", lens["availability"],
            ", ".join(lens["prerequisites"]) or lens["reason"] or "none",
            len(lens["primary_operations"]), len(lens["companion_operations"]))) + " |")
    core_tools = sorted({item["tool"] for item in result["core_operations"]})
    lines += ["", "## Orientation And Selection", "",
              "Core controls: " + ", ".join(safe_inline(tool) for tool in core_tools) + ".",
              "Use fow_interaction discover for current issued choices; select/switch changes the durable lens.",
              "", f"The structured machine catalog is complete: {result['operation_count']} operations, "
              f"{result['lens_count']} lenses. This Markdown summarizes membership; it does not truncate the machine catalog.",
              "Declared membership grants no execution permission. Request exact inputs with fow_capabilities view=operation."]
    return "\n".join(lines) + "\n"


def _guided_bootstrap_markdown(payload: Mapping[str, Any], operation: str, output_budget: int) -> str:
    """Render only the issued operational view; never read runtime services."""
    view = payload['result']['operational_projection']
    title = f"Lifecycle Bootstrap: {operation}"
    note = ('Next gate is an action template. Supply its required inputs and prerequisites; '
            'request exact operation help when needed. It does not authorize coding or acceptance.')
    rendered = render_markdown(
        title=title, status=str(payload['status']), output_budget=None,
        document={'next_gate': view['next_gate'], 'next_gate_note': note,
                  'bootstrap': {key: value for key, value in view.items()
                                if key not in {'next_gate', 'detail_calls'}}},
        json_islands=tuple(MarkdownJsonIsland(f"Read full {name}", call)
                           for name, call in view['detail_calls'].items()),
    )
    budget = min(8192, output_budget) if output_budget is not None else 8192
    if len(rendered) <= budget:
        return rendered
    # Never byte-cut an issued action or its actor/identity. Unusually large
    # legacy identities can exceed even this boundary; the full read is exact.
    return render_markdown(
        title=title, status=str(payload['status']), output_budget=None,
        document={'status': view['status'], 'counts': view['counts'],
                  'presentation_boundary': 'Operational view exceeds the text budget. Read full guidance '
                    'for the complete next gate. Structured content retains the complete gate and state.'},
        json_islands=(MarkdownJsonIsland('Read full guidance', view['detail_calls']['guidance']),),
    )


def _present_repository_reviews(value: Any, *, full_review: bool = False) -> Any:
    """Explain review authority; preserve explicitly requested full coverage."""
    if isinstance(value, Mapping):
        if (value.get("contract_version") in (
                "flow.repository-review-projection.v1", "flow.repository-review.v1")
                and "coverage" in value):
            # An audit rejection can return this projection directly. Templates
            # share the raw contract name but have no observed coverage to trim.
            presentation = dict(value) if full_review else repository_review_summary(value)
            if "human_acceptance" in value:
                presentation["human_acceptance_meaning"] = REVIEW_ACCEPTANCE_MEANING
            return presentation
        return {
            key: _present_repository_reviews(item, full_review=full_review)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_present_repository_reviews(item, full_review=full_review) for item in value]
    return value


def _progress_totals(progress: Mapping[str, Any]) -> dict[str, str]:
    totals = {}
    for key in ("implementation", "local_verification"):
        count = progress[key]
        percent = count["percent"]
        proportion = "percentage unknown" if percent is None else f"{percent}%"
        totals[count["label"]] = (
            f"{count['completed']}/{count['total']} applicable criteria ({proportion}). "
            f"{count['not_applicable']} excluded as inapplicable. Current host reports against the recorded criterion scope."
        )
    milestones = progress["milestones"]
    accepted = sum(row["acceptance"]["state"] == "accepted" for row in milestones)
    totals["Recorded milestone acceptance"] = (
        f"{accepted}/{len(milestones)} selected milestones with accepted status and recorded evidence."
    )
    totals["Evidence boundary"] = "Ledger read. Repository state and test execution require separate evidence."
    return totals


_NEXT_WORK_OPERATIONS = {
    ("fow_change", "create_change"),
    ("fow_packet_author", "start_packet"),
}


def _next_work_lines(action: Mapping[str, Any]) -> list[str]:
    route = action.get("route", action)
    if not isinstance(route, Mapping):
        return []
    tool, operation = route.get("tool"), route.get("operation")
    if (tool, operation) not in _NEXT_WORK_OPERATIONS:
        return []
    scope = action.get("scope", action)
    scope_keys = ("milestone_ids", "change_ids", "requirement_ids")
    identities = [identity for key in scope_keys for identity in scope.get(key, ())]
    known = [
        f"{key}={value}" for key, value in route["arguments"].items()
        if key != "operation"
    ]
    return [
        "- **Cause** " + safe_inline(action.get("rationale") or action["reason"]),
        "- **Scope** " + safe_inline(", ".join(identities)),
        f"- **Next step** `{tool}` / `{operation}` for one bounded increment.",
        "- **Known inputs** " + safe_inline(", ".join(known)),
        "- **Inputs to supply** " + safe_inline(", ".join(route["required_inputs"])),
        f"- **Operation help** `fow_capabilities` with `view=operation`, "
        f"`operation_tool={tool}` and `operation_name={operation}`. Proceed within confirmed scope.",
    ]


def _compact_snapshot_markdown(snapshot: Mapping[str, Any], output_budget: int | None) -> str:
    gate = snapshot["next_gate"]
    route = gate.get("route")
    active = snapshot.get("active_work") or {}
    scope = {**snapshot["project"], "focus": snapshot["focus"]}
    for kind in ("milestone", "change", "packet", "campaign", "finding"):
        row = active.get(kind) or {}
        if identity := row.get(f"{kind}_id"):
            scope[f"{kind}_id"] = identity
    current = {"state": gate["state"], "cause": gate["reason"]}
    if isinstance(route, Mapping):
        current["next_bounded_increment"] = {
            "tool": route["tool"], "operation": route["operation"],
            "known_inputs": route["arguments"], "inputs_to_supply": route["required_inputs"],
        }
    if context := snapshot.get("acceptance_context"):
        current["packet_checkpoint"] = context["packet_checkpoint"]["state"]
        acceptance = context["milestone_acceptance"]
        current["milestone_acceptance"] = acceptance["state"]
        current["acceptance_prerequisites"] = [row["reason"] for row in acceptance["blockers"][:3]]
    blockers = snapshot["blockers"]
    return render_markdown(
        title="Flower Project State", status="success", output_budget=output_budget,
        document={
            "scope": scope, "next_gate": current, "blockers": blockers[:3],
            "completeness": {
                "coherent_read": snapshot["completeness"]["coherent_read"],
                "additional_blockers": max(0, len(blockers) - 3) + snapshot["completeness"]["omitted"]["blockers"],
                "audit_presentation": "Repeat this scope with projection_kind=audit for details and history.",
            },
        },
    )


def _acceptance_blocker_lines(
    blocker: Mapping[str, Any], *, change_id: str = "", milestone_id: str = "",
) -> list[str]:
    reason = blocker.get("reason") or blocker.get("kind") or "unknown"
    references = [str(blocker[key]) for key in ("scope", "change_id", "packet_id", "finding_id", "campaign_id")
                  if blocker.get(key)]
    for key in ("requirement_ids", "finding_ids", "campaign_ids"):
        references.extend(str(identity) for identity in blocker.get(key, ()))
    label = " · ".join([reason, *(references or [change_id or milestone_id])]).rstrip(" ·")
    lines = ["- **Prerequisite** " + safe_inline(label)]
    if reason == "campaign_missing":
        lines.extend([
            "  - **Cause** No campaign is linked to this change.",
            "  - **Next step** Read exact help for `fow_campaign_author` / `start`. "
            "Use the change above as `scope.change_id` and define the required verification before requesting acceptance.",
        ])
    elif reason == "campaign_not_complete":
        campaign_id = blocker.get("campaign_id")
        target = f"`campaign_id={safe_inline(campaign_id)}`" if campaign_id else "the affected `campaign_id`"
        lines.extend([
            "  - **Cause** The campaign has passing results and its current lifecycle has not completed.",
            f"  - **Next step** Call `fow_campaign_inspect` with {target} and "
            "`view=summary` in this project, then follow its current gate.",
        ])
    elif reason in {"campaign_not_green", "qualified_campaign_missing", "campaign_happy_path_only"}:
        if reason == "qualified_campaign_missing":
            cause = "No linked campaign has current, active qualification."
        elif reason == "campaign_happy_path_only":
            cause = "The campaign lacks required failure-oriented coverage and has no recorded exception."
        else:
            cause = "The linked campaign has no qualifying passing disposition."
        lines.extend([
            "  - **Cause** " + cause,
            "  - **Next step** Call `fow_campaign_inspect` with the project, the listed `campaign_id` "
            "and `view=summary` to read the current campaign gate.",
        ])
    elif reason in {"finding_unresolved", "finding_resolution_missing_evidence"}:
        cause = ("A linked finding still needs a disposition." if reason == "finding_unresolved"
                 else "A resolved finding has no evidence references.")
        lines.extend([
            "  - **Cause** " + cause,
            "  - **Next step** Read each listed `finding_id` with `fow_assurance` / `get_finding` "
            "in the selected project.",
        ])
    elif reason == "packet_missing":
        lines.extend([
            "  - **Cause** The linked change has no packet.",
            "  - **Next step** Read exact help for `fow_packet_author` / `start_packet` "
            "for the change above and define only the next bounded packet.",
        ])
    elif reason == "packet_unresolved":
        lines.extend([
            "  - **Cause** The packet still needs a terminal technical disposition.",
            "  - **Next step** Read `fow_packet_inspect` / `summary` for this packet. When its current "
            "route is `fow_change` / `transition_packet`, record `packet_status=implemented` with "
            "the observed criterion evidence. The change and milestone decisions are separate.",
        ])
    elif reason == "navigation_audit_blocker":
        lines.extend([
            "  - **Cause** The packet's required code targets are not ready.",
            "  - **Next step** Read `fow_packet_inspect` / `summary` for the listed change and packet, "
            "then follow its current gate.",
        ])
    elif reason == "required_change_unit_missing":
        lines.extend([
            "  - **Cause** The listed requirements have no change linked to this milestone.",
            "  - **Next step** Read exact help for `fow_change` / `create_change` "
            "and select the requirements for the next bounded result.",
        ])
    return lines


def _acceptance_gate_lines(
    gate: Mapping[str, Any], *, project_id: str = "",
) -> list[str]:
    change_id = gate.get("change_id", "")
    milestone_id = gate.get("milestone_id", "")
    lines = []
    if project_id:
        lines.append("- **Project** " + safe_inline(project_id))
    if change_id or milestone_id:
        lines.append("- **Scope** " + safe_inline(change_id or milestone_id))
    if gate.get("prerequisites_satisfied") is True:
        lines.append("- The current technical prerequisites are satisfied. Acceptance still requires an authorized decision and reference.")
    if gate.get("effect_state"):
        lines.append("- **Effect state** " + safe_inline(gate["effect_state"]))
    if guidance := gate.get("recovery_guidance"):
        lines.append("- **Before retrying** " + safe_inline(guidance["resolution"]))
    if call := gate.get("next_tool_call"):
        fields = ", ".join(f"{key}={value}" for key, value in call["arguments"].items())
        lines.append("- **Inspect** " + safe_inline(f"{call['tool']} with {fields}"))
    for blocker in gate["blockers"]:
        lines.extend(_acceptance_blocker_lines(blocker, change_id=change_id, milestone_id=milestone_id))
    return lines


def _acceptance_markdown(context: Mapping[str, Any]) -> str:
    scope = context["scope"]
    milestone = context["milestone_acceptance"]
    state = milestone["state"]
    explanations = {
        "blocked": "The current milestone has outstanding prerequisites. Inspect them before requesting acceptance.",
        "awaiting_human": "The checked prerequisites are satisfied. The stakeholder decision and its evidence are pending.",
        "ready": "The checked prerequisites are satisfied. Recorded references do not establish a stakeholder decision.",
        "accepted": "The selected milestone has a recorded acceptance and evidence.",
        "unavailable": "Milestone acceptance could not be evaluated for this selection.",
    }
    lines = [explanations[state], "", f"- **Acceptance disposition** {safe_inline(state)}"]
    identities = [str(scope[key]) for key in ("packet_id", "milestone_id") if scope.get(key)]
    if identities:
        lines.append("- **Selected scope** " + safe_inline(" · ".join(identities)))
    if milestone.get("recorded_status"):
        lines.append("- **Milestone recorded status** " + safe_inline(milestone["recorded_status"]))
    packet = context.get("packet_checkpoint")
    if packet:
        lines.append("- **Packet checkpoint** " + safe_inline(packet["state"]))
        units = packet.get("reported_units")
        if units is not None:
            lines.append(f"- **Host-reported units complete** {units['completed']}/{units['total']}")
        if review := packet.get("repository_review"):
            review_detail = [str(review.get("state") or "")]
            if review.get("latest_audit_id"):
                review_detail.append(f"audit {review['latest_audit_id']}")
            if source := review.get("source"):
                review_detail.extend(str(source[key]) for key in ("provenance", "revision") if source.get(key))
            lines.append("- **Repository review** " + safe_inline(" · ".join(review_detail)))
    if milestone.get("reason"):
        lines.append("- **Scope detail** " + safe_inline(milestone["reason"]))
    if milestone.get("awaited_inputs"):
        lines.append("- **Human input** " + safe_inline(", ".join(milestone["awaited_inputs"])))
    for reference in milestone.get("acceptance_evidence", []):
        lines.append("- **Recorded acceptance reference** " + safe_inline(reference))
    for blocker in milestone["blockers"]:
        lines.extend(_acceptance_blocker_lines(blocker, milestone_id=scope.get("milestone_id", "")))
    for requirement in context["requirements"]:
        lines.append("- **Requirement** " + safe_inline(" · ".join((requirement["requirement_id"],
            requirement["lifecycle_status"], requirement["direct_evidence_state"]))))
        for proof in requirement["direct_evidence"]:
            lines.append("  - " + safe_inline(" · ".join((f"evidence {proof['evidence_id']}",
                proof["verification_kind"], proof["outcome"], proof["currentness"], proof["reference"]))))
    for goal in context["goal_grounding"]:
        references = [goal["goal_node_id"], goal["state"], *goal["gaps"]]
        if goal.get("audit_id"):
            references.extend([f"audit {goal['audit_id']}", goal["evidence_authority"], goal["source_currentness"]])
            if goal.get("source_revision"):
                references.append(goal["source_revision"])
        lines.append("- **Goal grounding context** " + safe_inline(" · ".join(references)))
    for deferred in context["deferred_obligations"]:
        lines.append("- **Deferred verification** " + safe_inline(" · ".join(str(deferred.get(key) or "")
            for key in ("applicability", "state", "authority_ref", "statement"))))
    if context["truncated"]:
        lines.extend(["", "This view is bounded. Use the scoped read and the retained evidence references for details."])
    return "\n".join(lines)


def _architecture_proposal_help(contract: Mapping[str, Any]) -> str:
    guidance = contract["guidance"]
    fields = guidance["entity_fields"]
    kind_path = "payload.definition.interfaces[].kind"
    lines = [
        "# Flower Architecture: propose", "", "## Minimum definition shape", "",
        "Send `project_id`, `operation=propose`, `actor` and a caller-owned `request_id`.",
        "Set `payload.expected_revision` to the current adopted revision (0 before the first adoption).",
        "Set `payload.definition` to an object with all three arrays: `components`, `interfaces`, `decisions`.",
        "An unused array can be `[]`. Include a component before using the design for new plan admission.",
        "Each included entity must have every field in its row:", "",
    ]
    for kind, names in fields.items():
        lines.append(f"- **{kind.capitalize()}** " + ", ".join(f"`{name}`" for name in names))
    lines.extend([
        "",
        "A one-component example uses `id=Core`, `name=Core`, `responsibility=Own the project state`, "
        "`boundaries=[]`, `invariants=[]` and `links=[]`, with `interfaces=[]` and `decisions=[]`.",
        "",
        "Use `[]` for empty `links`, `boundaries`, `invariants`, `failure_contract`, "
        "`compatibility`, `component_ids` and `interface_ids`. Interface `clauses` and "
        "`consumer_component_ids` must be nonempty. Use `supersedes_decision_id` as an empty string for a first decision.",
        f"`{kind_path}` accepts " + ", ".join(contract["accepted_values"][kind_path]) + ".",
        "Use existing component IDs for endpoints, and existing component/interface IDs for decision subjects.",
        "", "## Typed links and narrative", "",
    ])
    for link in guidance["links"]:
        lines.append(f"- **{link['kind']} link** " + ", ".join(f"`{field}`" for field in link))
    lines.extend(["", guidance["markdown"], guidance["bounds"], "", "## Receipt and next gate", "",
                  guidance["replay"], guidance["authority"]])
    return "\n".join(lines) + "\n"


def _use_readable_recovery(tool: str, operation: str, payload: Mapping[str, Any]) -> bool:
    """Keep the new recovery paths readable without changing machine envelopes."""
    reason = str(payload.get("reason") or "")
    result = payload.get("result")
    diagnostics = result.get("diagnostics", []) if isinstance(result, Mapping) else []
    first = diagnostics[0] if isinstance(diagnostics, (list, tuple)) and diagnostics else {}
    first = first if isinstance(first, Mapping) else {}
    if tool == "fow_packet_advance":
        return reason == "packet_criterion_responsibility_unresolved" or (
            reason == "packet_decision_not_current"
            and first.get("expected_operation") == "external_validation"
        )
    if tool == "fow_architecture":
        field = str(first.get("field", ""))
        return reason == "architecture_input_invalid" and (
            field == "payload.definition.markdown" or field.startswith("payload.definition.interfaces[")
            or bool(first.get("missing_entity_fields"))
        )
    if tool == "fow_packet_author":
        if operation == "add_unit":
            return payload.get("status") != "success"
        return operation == "set_dependencies" and reason in {
            "stale_packet_revision", "stale_current_work_plan_revision",
        }
    return tool == "fow_external_work" and (
        operation == "classify_criteria" or reason in CRITERION_RESPONSIBILITY_GAPS
        or (operation == "select_executor" and first.get("field") == "payload.executor")
    )


def project_markdown(
    tool_name: str,
    payload: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any] | None = None,
    output_budget: int = _DEFAULT_OUTPUT_BUDGET,
) -> str:
    """Project one already-authorized Flower application envelope."""

    arguments = arguments or {}
    result = payload.get("result")
    if (tool_name == "fow_capabilities" and arguments.get("view") == "operation"
            and payload.get("status") == "success" and isinstance(result, Mapping)):
        contract = result.get("operation_contract")
        if isinstance(contract, Mapping) and (contract.get("tool"), contract.get("operation")) == ("fow_architecture", "propose"):
            rendered = _architecture_proposal_help(contract)
            if output_budget is not None and len(rendered) > output_budget:
                return projection_boundary(title="Flower Architecture: propose", status="success",
                                           required_chars=len(rendered), output_budget=output_budget)
            return rendered
    if tool_name in {"fow_campaign_author", "fow_campaign_advance", "fow_campaign_inspect"}:
        status = str(payload.get("status") or "failed")
        view = str(arguments.get("view") or "summary")
        if status == "success":
            rendered = _campaign_work_markdown(
                result, project_id=str(arguments.get("project_id") or "selected project"),
                change_id=str(arguments.get("change_id") or ""), view=view,
                include_horizon=(tool_name == "fow_campaign_inspect" and view == "summary")
                or arguments.get("operation") == "start",
            )
        else:
            rendered = campaign_error_markdown(tool_name, payload, arguments)
        if output_budget is not None and len(rendered) > output_budget:
            return projection_boundary(title="Campaign work", status=status,
                                       required_chars=len(rendered), output_budget=output_budget)
        return rendered
    if (
        tool_name == "fow_get_artifacts"
        and payload.get("status") == "success"
        and arguments.get("artifact_kind") == ArtifactKind.REQUIREMENTS_CATALOGUE.value
        and arguments.get("generation_id") is not None
        and arguments.get("include_content") is True
    ):
        return _requirements_export_markdown(
            result, project_id=arguments["project_id"], generation_id=arguments["generation_id"]
        )
    if (tool_name == "fow_bootstrap" and payload.get("status") == "success"
            and isinstance(result, Mapping) and "operational_projection" in result):
        return _guided_bootstrap_markdown(payload, str(arguments.get("operation") or ""), output_budget)
    if tool_name == "fow_interaction" and arguments.get("operation") == "catalog" and payload.get("status") == "success":
        rendered = _lens_catalog_markdown(result)
        if output_budget is not None and len(rendered) > output_budget:
            return projection_boundary(title="Flower Interaction: catalog", status="success",
                                       required_chars=len(rendered), output_budget=output_budget)
        return rendered
    spec = _projection_spec(tool_name, arguments)
    if spec is None:
        raise ModelFacingProjectionError(f"missing_model_facing_projector:{tool_name}")
    operation = str(arguments.get("operation") or "").strip()
    if tool_name == "fow_bootstrap" and operation == "revise_draft_milestone" and payload.get("status") == "success":
        milestone = result["milestone"]
        return render_markdown(
            title="Draft milestone revision", status="success", output_budget=output_budget,
            document={"milestone": milestone["milestone_id"], "ordinal": milestone["ordinal"],
                      "name": milestone["name"], "changed": result["changed"],
                      "previous_revision": result["previous_revision"], "current_revision": result["current_revision"],
                      "roadmap_fingerprint": result["roadmap_fingerprint"], "confirmable": result["confirmable"],
                      "unresolved_obligations": result["gaps"], "next_step": result["next_step"]},
            json_islands=(MarkdownJsonIsland("Read the current roadmap", result["next_tool_call"]),),
        )
    audit_snapshot = (
        tool_name == "fow_handover" and operation == "project_state_snapshot"
        and arguments.get("projection_kind") == "audit" and payload.get("status") == "success"
    )
    if (tool_name == "fow_handover" and operation == "project_state_snapshot"
            and payload.get("status") == "success" and not audit_snapshot
            and isinstance(result, Mapping) and isinstance(result.get("project_state_snapshot"), Mapping)):
        return _compact_snapshot_markdown(result["project_state_snapshot"], output_budget)
    if (payload.get("reason") in {"change_acceptance_blocked", "milestone_acceptance_blocked"}
            and isinstance(result, Mapping) and result.get("blockers")):
        lines = ["# Acceptance blocked", "", *_acceptance_gate_lines(
            result, project_id=str(arguments.get("project_id") or ""),
        )]
        rendered = "\n".join(lines) + "\n"
        if output_budget is not None and len(rendered) > output_budget:
            return projection_boundary(title="Acceptance blocked", status="blocked",
                                       required_chars=len(rendered), output_budget=output_budget)
        return rendered
    if (tool_name == "fow_assurance" and operation == "inspect_change_acceptance"
            and payload.get("status") == "success"):
        return "\n".join(["# Change acceptance preflight", "", *_acceptance_gate_lines(
            result["assurance"], project_id=str(arguments.get("project_id") or ""),
        )]) + "\n"
    if (tool_name == "fow_architecture" and operation == "export" and payload.get("status") == "success"
            and isinstance(result, Mapping) and isinstance(result.get("markdown"), str)):
        return result["markdown"]
    complete_evidence = tool_name == "fow_traceability" and bool(arguments.get("evidence_id")) and payload.get("status") == "success"
    explicit_review_detail = (
        tool_name == "fow_external_work" and operation == "validation"
        and isinstance(arguments.get("payload"), Mapping)
        and arguments["payload"].get("detail") == "full"
    )
    title = spec.title + (f": {operation}" if operation else "")
    full_review = (
        explicit_review_detail or audit_snapshot
    ) or (tool_name == "fow_packet_inspect" and arguments.get("detail_level") == "audit") or (
        tool_name == "fow_handover" and operation == "get_handover"
    )
    presentation_payload = (
        _present_repository_reviews(payload, full_review=full_review)
        if tool_name in {
            "fow_external_work", "fow_packet_inspect", "fow_interaction", "fow_handover", "fow_audit_phase", "fow_get_job"
        } else payload
    )
    document, artifacts, exact_calls = _presentation_parts(
        presentation_payload,
        result_heading=spec.result_heading,
        artifact_keys=spec.artifact_keys,
        exact_call_keys=(frozenset() if _use_readable_recovery(tool_name, operation, payload)
                         else spec.exact_call_keys),
        preserve_multiline=complete_evidence or payload.get("status") in {"rejected", "blocked", "failed"},
    )
    if tool_name == "fow_handover" and operation == "project_progress" and payload.get("status") == "success":
        section = document.pop(spec.result_heading)
        progress = section["project_progress"]
        document["recorded_progress_totals"] = _progress_totals(progress)
        progress.pop("implementation")
        progress.pop("local_verification")
        document[spec.result_heading] = section
    if tool_name == "fow_traceability" and isinstance(result, Mapping) and "pagination" in result:
        traceability = document.pop(spec.result_heading)
        pagination = traceability.pop("pagination")
        pages = [
            {"view": label, **pagination[key]}
            for key, label in (("requirements", "Requirements"), ("projection_rows", "Projection rows"))
        ]
        offsets = [page["next_offset"] for page in pages if page["has_more"]]
        projection = result["projection"]
        scope = f"project_id={projection['project_id']}"
        if projection["milestone_id"]:
            scope += f", milestone_id={projection['milestone_id']}"
        document["traceability_pagination"] = {
            "next_page": (
                f"Call fow_traceability with {scope}, detail_level={result['detail_level']}, "
                f"offset={min(offsets)}, limit={pages[0]['limit']}."
                if offsets else "End of both views."
            ),
            "pages": pages,
        }
        document[spec.result_heading] = traceability
    context_key = {"fow_handover": "project_state_snapshot", "fow_packet_inspect": "packet"}.get(tool_name)
    if tool_name == "fow_what_next" and isinstance(result, Mapping):
        shown_result = document[spec.result_heading]
        if next_lines := _next_work_lines(result.get("primary_action", {})):
            shown_result.pop("primary_action", None)
            artifacts.append(("Next bounded increment", "\n".join(next_lines), "markdown"))
        acceptance = result.get("acceptance_preflight") or result.get("milestone_closure")
        if acceptance and acceptance.get("blockers"):
            if "acceptance_preflight" in result:
                shown_result.pop("acceptance_preflight", None)
            else:
                shown_result["milestone_closure"].pop("blockers", None)
            lines = [
                "These are acceptance prerequisites. Continue the current work gate above when applicable.",
                "", *_acceptance_gate_lines(acceptance),
            ]
            if change_id := acceptance.get("change_id"):
                lines.append(
                    "- **Refresh this preflight** `fow_assurance` / `inspect_change_acceptance` "
                    f"with `change_id={change_id}`."
                )
            artifacts.append(("Acceptance prerequisites", "\n".join(lines), "markdown"))
    if context_key is not None:
        section = document.get(spec.result_heading)
        scoped = section.get(context_key) if isinstance(section, Mapping) else None
        if isinstance(scoped, dict) and not audit_snapshot and isinstance(scoped.get("acceptance_context"), Mapping):
            context = scoped.pop("acceptance_context")
            artifacts.append(("Scoped acceptance and evidence", _acceptance_markdown(context), "markdown"))
            exact_calls.append(("Read selected acceptance scope", context["detail_reference"]))
    if (
        tool_name == "fow_bootstrap" and operation == "roadmap"
        and payload.get("status") == "success" and isinstance(result, Mapping)
        and _complete_roadmap_reference(result.get("bootstrap"), artifacts)
    ):
        # The exact complete reference already carries these facts. Retain all
        # summary/gate fields and the raw envelope; remove only their second
        # human representation after the full artifact has been extracted.
        presented_result = document[spec.result_heading]
        document[spec.result_heading] = {
            **presented_result,
            "bootstrap": {
                **presented_result["bootstrap"],
                "canonical_scope": "Presented in the complete roadmap below.",
                "draft_context": "Presented in the complete roadmap below.",
            },
        }
    if complete_evidence or audit_snapshot or (
        tool_name == "fow_bootstrap" and operation == "state_details" and payload.get("status") == "success"
    ) or (
        explicit_review_detail and payload.get("status") in {"success", "blocked"}
    ):
        # An explicitly requested evidence/state body is a complete reference,
        # like an exported artifact. Never silently flatten or budget-cut it.
        output_budget = None
    status = str(payload.get("status") or "unknown")
    # Exported artifacts are the offline handoff. Return their complete bytes in
    # both channels; ordinary discovery projections keep the bounded budget.
    if status == "success" and artifacts and (
        (tool_name == "fow_external_work" and operation == "export_plan")
        or (tool_name == "fow_bootstrap" and operation in {"guidance", "roadmap"})
        or tool_name == "fow_get_artifacts"
        or (tool_name == "fow_semantic" and operation in {"prepare", "inspect"})
    ):
        output_budget = None
    result = payload.get("result", {})
    assurance_intent = tool_name == "fow_assurance" and operation in {"get_finding", "reassess_intent"}
    semantic_recovery = tool_name == "fow_handover" and _has_semantic_recovery(result)
    if assurance_intent or semantic_recovery or tool_name in {"fow_external_work", "fow_architecture"} or (
        tool_name == "fow_packet_inspect"
        and isinstance(result, Mapping)
        and (
            result.get("consumption_mode") == "external_agent" or "external_work" in result
            or (
                isinstance(result.get("packet"), Mapping)
                and (result["packet"].get("consumption_mode") == "external_agent" or "external_work" in result["packet"])
            )
        )
    ):
        # These are semantic work projections. Passing nested unit/evidence
        # records to the mechanical table converter hides their instructions.
        if output_budget is not None and output_budget < 1_024:
            raise ValueError("model-facing output budget must be at least 1024 chars")
        clean_result = document.get(spec.result_heading, {})
        if not isinstance(clean_result, Mapping):
            clean_result = {"result": clean_result}
        body = render_assurance_result(clean_result) if assurance_intent else render_external_result(clean_result, inspection=tool_name == "fow_packet_inspect", full_review=full_review)
        supplemental = render_markdown(
            title=title, document={},
            artifacts=[MarkdownArtifact(label=label, content=value, language=language) for label, value, language in artifacts],
            json_islands=[MarkdownJsonIsland(label=label, value=value) for label, value in exact_calls],
            status=status, output_budget=None,
        ).split("\n", 1)[1].strip()
        reason = payload.get("reason")
        current = f"- **Status:** {safe_inline(status)}\n"
        if reason:
            current += f"- **Reason:** {safe_inline(str(reason))}\n"
        rendered = f"# {safe_heading(title)}\n\n## Current State\n\n{current}\n{body}"
        if supplemental:
            rendered += "\n" + supplemental + "\n"
        if output_budget is not None and len(rendered) > output_budget:
            return projection_boundary(title=title, status=status, required_chars=len(rendered), output_budget=output_budget)
        return rendered
    return render_markdown(
        title=title,
        document=document,
        artifacts=[
            MarkdownArtifact(label=label, content=value, language=language)
            for label, value, language in artifacts
        ],
        json_islands=[
            MarkdownJsonIsland(label=label, value=value)
            for label, value in exact_calls
        ],
        status=status,
        output_budget=output_budget,
    )


def _complete_roadmap_reference(
    roadmap: Any, artifacts: list[tuple[str, str, str]],
) -> bool:
    """Eligibility for narrative deduplication, never lifecycle admission."""
    if not isinstance(roadmap, Mapping) or roadmap.get("contract_version") != "flow.guided_roadmap.v1":
        return False
    if not all(isinstance(roadmap.get(key), str) and roadmap[key].strip() for key in (
        "project_id", "bootstrap_id", "roadmap_fingerprint", "semantic_completeness", "markdown",
    )):
        return False
    if not all(isinstance(roadmap.get(key), bool) for key in ("confirmable", "confirmed", "human_acceptance")):
        return False
    if not isinstance(roadmap.get("milestone_ids"), list) or not all(
        isinstance(value, str) for value in roadmap["milestone_ids"]
    ):
        return False
    gaps = roadmap.get("gaps")
    if not isinstance(gaps, list) or not all(isinstance(value, Mapping) for value in gaps):
        return False
    scope, draft = roadmap.get("canonical_scope"), roadmap.get("draft_context")
    if not isinstance(scope, Mapping) or set(scope) != {
        "project_id", "bootstrap_id", "milestones", "requirements", "goals",
        "goal_edges", "answers", "correspondence",
    }:
        return False
    if any(scope[key] != roadmap[key] for key in ("project_id", "bootstrap_id")):
        return False
    if not all(isinstance(scope[key], list) and all(isinstance(value, Mapping) for value in scope[key])
               for key in ("milestones", "requirements", "goals", "goal_edges")):
        return False
    if not all(isinstance(scope[key], Mapping) for key in ("answers", "correspondence")):
        return False
    if not isinstance(draft, Mapping) or set(draft) != {
        "authority", "unassigned_answers", "outside_scope_answers", "outside_scope_correspondence",
    } or draft["authority"] != "outside_selected_scope" or not all(
        isinstance(draft[key], Mapping)
        for key in ("unassigned_answers", "outside_scope_answers", "outside_scope_correspondence")
    ):
        return False
    markdown = roadmap["markdown"]
    if not any(body == markdown and language == "markdown" for _label, body, language in artifacts):
        return False
    try:
        expected = render_roadmap(scope, fingerprint=roadmap["roadmap_fingerprint"], draft_context=draft, gaps=gaps)
    except (KeyError, TypeError, ValueError):
        # Malformed presentation input cannot justify hiding its original facts.
        return False
    return markdown == expected


def _projection_spec(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> ProjectionSpec:
    spec = _SPECS.get(tool_name)
    if spec is None:
        raise ModelFacingProjectionError(f"missing_model_facing_projector:{tool_name}")
    operation = str(arguments.get("operation") or "").strip()
    if not operation:
        return spec
    return _OPERATION_SPECS.get((tool_name, operation), spec)


def _presentation_parts(
    payload: Mapping[str, Any],
    *,
    result_heading: str,
    artifact_keys: frozenset[str],
    exact_call_keys: frozenset[str],
    preserve_multiline: bool = False,
) -> tuple[dict[str, Any], list[tuple[str, str, str]], list[tuple[str, Any]]]:
    current: dict[str, Any] = {
        "status": str(payload.get("status") or "unknown"),
    }
    reason = payload.get("reason")
    if reason not in (None, ""):
        current["reason"] = reason
    document: dict[str, Any] = {"current_state": current}
    result, artifacts, exact_calls = _extract_special_values(
        payload.get("result", {}),
        artifact_keys=artifact_keys,
        exact_call_keys=exact_call_keys,
        path=(),
        preserve_multiline=preserve_multiline,
    )
    for key in exact_call_keys:
        value = payload.get(key)
        if _is_exact_call_value(value):
            exact_calls.append((_label((key,)), value))
    if result not in (None, "", [], {}):
        document[result_heading] = result
    return document, artifacts, exact_calls


def _extract_special_values(
    value: Any,
    *,
    artifact_keys: frozenset[str],
    exact_call_keys: frozenset[str],
    path: tuple[str, ...],
    preserve_multiline: bool = False,
) -> tuple[Any, list[tuple[str, str, str]], list[tuple[str, Any]]]:
    artifacts: list[tuple[str, str, str]] = []
    exact_calls: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = (*path, key)
            if (
                (key in artifact_keys or (preserve_multiline and isinstance(item, str) and ("\n" in item or "\r" in item)))
                and isinstance(item, str)
                and item
                and _is_artifact_value(key, item)
            ):
                language = _artifact_language(key, value)
                if key not in artifact_keys and key not in {"source", "stdout", "stderr", "logs"}:
                    language = "markdown"
                artifacts.append((_label(item_path), item, language))
                continue
            if key in exact_call_keys and _is_exact_call_value(item):
                exact_calls.append((_label(item_path), item))
                continue
            cleaned, child_artifacts, child_calls = _extract_special_values(
                item,
                artifact_keys=artifact_keys,
                exact_call_keys=exact_call_keys,
                path=item_path,
                preserve_multiline=preserve_multiline,
            )
            output[key] = cleaned
            artifacts.extend(child_artifacts)
            exact_calls.extend(child_calls)
        return output, artifacts, exact_calls
    if isinstance(value, (list, tuple)):
        output_list: list[Any] = []
        for index, item in enumerate(value, start=1):
            cleaned, child_artifacts, child_calls = _extract_special_values(
                item,
                artifact_keys=artifact_keys,
                exact_call_keys=exact_call_keys,
                path=(*path, str(index)),
                preserve_multiline=preserve_multiline,
            )
            output_list.append(cleaned)
            artifacts.extend(child_artifacts)
            exact_calls.extend(child_calls)
        return output_list, artifacts, exact_calls
    if preserve_multiline and isinstance(value, str) and ("\n" in value or "\r" in value):
        return "Complete multiline content below.", [(_label(path), value, "markdown")], []
    return value, artifacts, exact_calls


def _is_artifact_value(key: str, value: str) -> bool:
    """Keep ordinary provenance labels inline instead of fencing by key alone."""

    if key in {"source", "excerpt"}:
        return "\n" in value or "\r" in value
    return True


def _is_exact_call_value(value: Any) -> bool:
    def call(item: Any) -> bool:
        return (
            isinstance(item, Mapping)
            and isinstance(item.get("tool"), str)
            and bool(item["tool"].strip())
            and isinstance(item.get("arguments"), Mapping)
        )

    if isinstance(value, Mapping):
        return call(value) or (bool(value) and all(call(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return bool(value) and all(call(item) for item in value)
    return False


def _artifact_language(key: str, owner: Mapping[str, Any]) -> str:
    if key in {"markdown", "task_markdown", "prompt"}:
        return "markdown"
    if key in {"stdout", "stderr", "logs"}:
        return "text"
    if key in {"content", "text"} and any(
        isinstance(owner.get(field), str)
        and owner[field] in {kind.value for kind in ArtifactKind}
        for field in ("artifact_kind", "kind")
    ):
        return "markdown"
    return str(owner.get("language") or owner.get("media_type") or "text").strip()


def _label(path: tuple[str, ...]) -> str:
    if not path:
        return "Artifact"
    return " / ".join(_display_label(part) for part in path)


def _display_label(value: str) -> str:
    label = safe_heading(value.replace("_", " "))
    return label[:1].upper() + label[1:]


__all__ = [
    "ModelFacingProjectionError",
    "assert_projector_registry",
    "model_facing_tool",
    "operation_projector_routes",
    "project_markdown",
    "projector_names",
]
