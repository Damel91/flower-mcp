"""Explicit model-facing Markdown projection for Flower MCP tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
import inspect
from typing import Annotated, Any, TypeVar, cast, get_type_hints

from mcp.types import CallToolResult, TextContent
from pydantic import Field

from flow_of_work_mcp.application.operation_contracts import (
    operation_names,
    parameter_help,
    public_tool_names,
)
from flow_of_work_mcp.application.external_plan_markdown import REVIEW_ACCEPTANCE_MEANING, render_assurance_result, render_external_result, repository_review_summary
from flow_of_work_mcp.application.roadmap_markdown import render_roadmap
from flow_of_work_mcp.core.domain.artifacts import ArtifactKind
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
    complete_evidence = tool_name == "fow_traceability" and bool(arguments.get("evidence_id")) and payload.get("status") == "success"
    explicit_review_detail = (
        tool_name == "fow_external_work" and operation == "validation"
        and isinstance(arguments.get("payload"), Mapping)
        and arguments["payload"].get("detail") == "full"
    )
    title = spec.title + (f": {operation}" if operation else "")
    full_review = (
        explicit_review_detail
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
        exact_call_keys=spec.exact_call_keys,
        preserve_multiline=complete_evidence or payload.get("status") in {"rejected", "blocked", "failed"},
    )
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
    if complete_evidence or (
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
