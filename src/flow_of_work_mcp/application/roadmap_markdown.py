"""Complete presentation of an already-selected engineering roadmap.

These helpers do not select authority, query state, or decide readiness. Their
inputs are the coherent values supplied by the existing application services.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flow_of_work_mcp.markdown_adapter import render_structured, safe_heading, safe_text


_ORDERED_STEP_FIELDS = frozenset({"normal_steps", "alternate_steps", "failure_steps"})


def _section(title: str, *, level: int = 2) -> str:
    return "#" * min(max(level, 1), 6) + " " + safe_heading(title)


def render_requirement(requirement: Mapping[str, Any], *, level: int = 3) -> str:
    """Keep a requirement's complete supplied fields beside its identity."""
    title = f"{requirement['requirement_id']}: {requirement['title']}"
    fields = {key: value for key, value in requirement.items() if key != "requirement_id"}
    return _section(title, level=level) + "\n\n" + render_structured(fields, level=level + 1)


def _ordered_steps(steps: list[str] | tuple[str, ...]) -> str:
    ordered = []
    for index, step in enumerate(steps, 1):
        physical = safe_text(step).split("\n")
        prefix = f"{index}. "
        # A label supplies a real list-item boundary. A heading, fence or
        # nested list at the start of the authored step stays in its ordinal.
        ordered.extend([prefix + f"**Step {index}**", ""])
        ordered.extend(" " * len(prefix) + line if line else "" for line in physical)
        ordered.append("")
    return "\n".join(ordered)


def render_goal(goal: Mapping[str, Any], *, level: int = 3) -> str:
    """Render scenario facts and preserve sequence ordering and physical lines."""
    parts = [_section(f"{goal['goal_node_id']}: {goal['title']}", level=level)]
    metadata = {key: value for key, value in goal.items()
                if key not in {"goal_node_id", "payload"}}
    if metadata:
        parts.append(render_structured(metadata, level=level + 1))
    if "payload" in goal:
        parts.append(_section("Scenario details", level=level + 1))
        payload = goal["payload"]
        if not isinstance(payload, Mapping) or not payload:
            parts.append(render_structured(payload, level=level + 2))
        else:
            prepared = {
                key: _ordered_steps(value)
                if (key in _ORDERED_STEP_FIELDS and isinstance(value, (list, tuple))
                    and value and all(isinstance(step, str) for step in value))
                else value
                for key, value in payload.items()
            }
            # One record preserves the sibling boundaries between scalar facts
            # and containers, including the sorted payload order from SQLite.
            parts.append(render_structured(prepared, level=level + 2))
    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def render_roadmap(
    basis: Mapping[str, Any], *, fingerprint: str,
    draft_context: Mapping[str, Any], gaps: list[Mapping[str, Any]],
) -> str:
    """Present the existing roadmap basis without changing its semantic scope."""
    parts = [
        "# Flower engineering roadmap",
        render_structured({"project": basis["project_id"], "bootstrap": basis["bootstrap_id"],
                           "semantic_roadmap_fingerprint": fingerprint}),
        "This describes the entire selected milestone spectrum. Human scope confirmation "
        "authorizes planning/execution; it does not accept implemented software.",
        "## Scenarios and intent",
    ]
    goals = basis["goals"]
    parts.extend(render_goal(goal) for goal in goals)
    if not goals:
        parts.append("No scenarios recorded; absence is not semantic completeness.")
    parts.extend(["## Scenario relations", render_structured(basis["goal_edges"], level=3),
                  "## Requirements",
                  "The milestone sections distinguish requirements realized by current work "
                  "from prerequisite requirements supplied by earlier work."])
    parts.extend(render_requirement(requirement) for requirement in basis["requirements"])
    if not basis["requirements"]:
        parts.append("No requirements recorded; absence is not semantic completeness.")
    parts.append("## Milestones in selected order")
    for milestone in basis["milestones"]:
        parts.append(_section(f"{milestone['milestone_id']}: {milestone['name']}", level=3))
        fields = {}
        for key, value in milestone.items():
            if key != "milestone_id":
                label = {"requirement_ids": "realized_requirement_ids"}.get(key, key)
                fields[label] = value
        parts.append(render_structured(fields, level=4))
    if not basis["milestones"]:
        parts.append("No milestones recorded.")
    parts.extend([
        "## Selected stakeholder answers and correspondence",
        render_structured({"answers": basis["answers"], "correspondence": basis["correspondence"]}, level=3),
        "## Draft intake outside the selected scope",
        "Unassigned or unrelated answers remain draft context. They do not govern this "
        "roadmap or authorize additional work; explicit correspondence and ordinary "
        "canonical authority are required to include them.",
        render_structured(draft_context, level=3),
        "## Unresolved obligations", render_structured(gaps, level=3),
        "I have gathered enough information to define this roadmap. Does it represent "
        "what you want, or is there anything else I need to know?",
    ])
    return "\n\n".join(part.rstrip() for part in parts) + "\n"
