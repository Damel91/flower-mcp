"""Explicit model-facing Markdown projection for Flower MCP tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
import inspect
from typing import Any, TypeVar, cast, get_type_hints

from mcp.types import CallToolResult, TextContent

from flow_of_work_mcp.application.operation_contracts import (
    operation_names,
    public_tool_names,
)
from flow_of_work_mcp.application.external_plan_markdown import render_assurance_result, render_external_result
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
    "fow_external_work": ProjectionSpec("Flower External Work", "Standalone Plan And Outcome", frozenset({"content", "markdown"})),
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
    """Wrap one public handler without changing its FastMCP input schema."""

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
                annotation=resolved_hints.get(parameter.name, parameter.annotation)
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

    wrapped.__annotations__ = resolved_hints
    wrapped.__signature__ = signature  # type: ignore[attr-defined]
    return cast(F, wrapped)


def project_markdown(
    tool_name: str,
    payload: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any] | None = None,
    output_budget: int = _DEFAULT_OUTPUT_BUDGET,
) -> str:
    """Project one already-authorized Flower application envelope."""

    arguments = arguments or {}
    spec = _projection_spec(tool_name, arguments)
    if spec is None:
        raise ModelFacingProjectionError(f"missing_model_facing_projector:{tool_name}")
    operation = str(arguments.get("operation") or "").strip()
    title = spec.title + (f": {operation}" if operation else "")
    document, artifacts, exact_calls = _presentation_parts(
        payload,
        result_heading=spec.result_heading,
        artifact_keys=spec.artifact_keys,
        exact_call_keys=spec.exact_call_keys,
    )
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
    if assurance_intent or tool_name == "fow_external_work" or (
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
        body = render_assurance_result(clean_result) if assurance_intent else render_external_result(clean_result, inspection=tool_name == "fow_packet_inspect")
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
) -> tuple[Any, list[tuple[str, str, str]], list[tuple[str, Any]]]:
    artifacts: list[tuple[str, str, str]] = []
    exact_calls: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = (*path, key)
            if (
                key in artifact_keys
                and isinstance(item, str)
                and item
                and _is_artifact_value(key, item)
            ):
                artifacts.append((_label(item_path), item, _artifact_language(key, value)))
                continue
            if key in exact_call_keys and _is_exact_call_value(item):
                exact_calls.append((_label(item_path), item))
                continue
            cleaned, child_artifacts, child_calls = _extract_special_values(
                item,
                artifact_keys=artifact_keys,
                exact_call_keys=exact_call_keys,
                path=item_path,
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
            )
            output_list.append(cleaned)
            artifacts.extend(child_artifacts)
            exact_calls.extend(child_calls)
        return output_list, artifacts, exact_calls
    return value, artifacts, exact_calls


def _is_artifact_value(key: str, value: str) -> bool:
    """Keep ordinary provenance labels inline instead of fencing by key alone."""

    if key in {"source", "excerpt"}:
        return "\n" in value or "\r" in value
    return True


def _is_exact_call_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, Mapping) for item in value)
    return False


def _artifact_language(key: str, owner: Mapping[str, Any]) -> str:
    if key in {"markdown", "task_markdown"}:
        return "markdown"
    if key in {"stdout", "stderr", "logs"}:
        return "text"
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
