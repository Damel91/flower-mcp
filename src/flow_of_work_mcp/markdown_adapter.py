"""Mechanical Markdown assembly for model-facing Flow MCP content.

This module owns converter safety only. Lifecycle projectors select and order
authorized facts before invoking it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any

from md_generator.text.md_emit_json import json_to_markdown

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INFO_STRING_RE = re.compile(r"[^A-Za-z0-9_+.-]+")


@dataclass(frozen=True)
class MarkdownArtifact:
    label: str
    content: str
    language: str = "text"


@dataclass(frozen=True)
class MarkdownJsonIsland:
    label: str
    value: Any


def render_markdown(
    *,
    title: str,
    document: Mapping[str, Any],
    artifacts: Sequence[MarkdownArtifact] = (),
    json_islands: Sequence[MarkdownJsonIsland] = (),
    status: str = "unknown",
    output_budget: int | None,
) -> str:
    """Render one already-shaped presentation model into bounded Markdown."""

    if output_budget is not None and output_budget < 1_024:
        raise ValueError("model-facing output budget must be at least 1024 chars")
    fragments = [f"# {safe_heading(title)}"]
    if document:
        body = json_to_markdown(
            safe_structured_value(document),
            "",
            include_source_block=False,
            generate_toc=False,
        ).strip()
        if body:
            fragments.append(body)
    for artifact in artifacts:
        fragments.append(
            f"## {safe_heading(artifact.label)}\n\n"
            f"{fenced_text(artifact.content, language=artifact.language)}"
        )
    if json_islands:
        fragments.append("## Continue")
        for island in json_islands:
            fragments.append(f"### {safe_heading(island.label)}")
            fragments.append(
                fenced_text(
                    json.dumps(island.value, ensure_ascii=False, indent=2),
                    language="json",
                )
            )
    rendered = "\n\n".join(
        fragment.rstrip() for fragment in fragments if fragment
    ).rstrip() + "\n"
    if output_budget is None or len(rendered) <= output_budget:
        return rendered
    return projection_boundary(
        title=title,
        status=status,
        required_chars=len(rendered),
        output_budget=output_budget,
    )


def safe_structured_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            safe_inline(str(key)): safe_structured_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [safe_structured_value(item) for item in value]
    if isinstance(value, str):
        return safe_inline(value)
    return value


def safe_inline(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARACTER_RE.sub(
        lambda match: f"\\u{ord(match.group(0)):04x}",
        normalized,
    )
    return " / ".join(normalized.split("\n"))


def safe_heading(value: str) -> str:
    cleaned = _CONTROL_CHARACTER_RE.sub("", str(value)).replace("\n", " ").strip()
    return cleaned or "Artifact"


def fenced_text(value: str, *, language: str = "") -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARACTER_RE.sub(
        lambda match: f"\\u{ord(match.group(0)):04x}",
        text,
    )
    backticks = _longest_run(text, "`")
    tildes = _longest_run(text, "~")
    delimiter = "`" if backticks <= tildes else "~"
    fence = delimiter * max(3, min(backticks, tildes) + 1)
    info = _INFO_STRING_RE.sub("", str(language))[:32]
    return f"{fence}{info}\n{text}\n{fence}"


def projection_boundary(
    *,
    title: str,
    status: str,
    required_chars: int,
    output_budget: int,
) -> str:
    return (
        f"# {safe_heading(title)}\n\n"
        "## Current State\n\n"
        f"- **Status:** {safe_inline(status)}\n\n"
        "## Projection Boundary\n\n"
        "- **Complete:** false\n"
        f"- **Required Characters:** {required_chars}\n"
        f"- **Output Budget:** {output_budget}\n"
        "- **Reason:** model_facing_output_budget_exceeded\n"
        "- **Structured Contract:** preserved for machine consumers\n"
    )


def _longest_run(value: str, character: str) -> int:
    longest = current = 0
    for item in value:
        if item == character:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


__all__ = [
    "MarkdownArtifact",
    "MarkdownJsonIsland",
    "fenced_text",
    "projection_boundary",
    "render_markdown",
    "safe_heading",
    "safe_inline",
    "safe_structured_value",
]
