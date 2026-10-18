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
        body = render_structured(document).strip()
        if body:
            fragments.append(body)
    for artifact in artifacts:
        language = artifact.language.lower().split(";", 1)[0].strip()
        body = safe_text(artifact.content) if language in {
            "markdown", "md", "text/markdown", "text/x-markdown"
        } else fenced_text(artifact.content, language=artifact.language)
        fragments.append(f"## {safe_heading(artifact.label)}\n\n{body}")
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


def safe_text(value: str) -> str:
    """Keep physical Markdown lines; escape only non-printing controls."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_CHARACTER_RE.sub(
        lambda match: f"\\u{ord(match.group(0)):04x}", normalized
    )


def _scalar(value: Any) -> str:
    if value is None:
        return "Not provided (null)."
    if value == "":
        return "Empty text."
    if isinstance(value, bool):
        return "yes" if value else "no"
    return safe_text(str(value))


def _container(value: Any) -> bool:
    return isinstance(value, (Mapping, list, tuple))


def _label(value: Any) -> str:
    return safe_heading(str(value).replace("_", " ")).title()


def _table_label(value: Any) -> str:
    # Give the scalar-table emitter final, idempotently formatted headings.
    text = safe_inline(str(value)).replace("_", " ").replace("-", " ")
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", text).strip().title() or text


def render_structured(value: Any, *, level: int = 2) -> str:
    """Render records without serializing containers or flattening prose.

    Tables are an optimization for uniform, single-line scalar records only.
    Everything else keeps explicit parent/item structure and all supplied facts.
    """
    lines: list[str] = []

    def heading(label: str, depth: int, path: tuple[str, ...]) -> None:
        title = " / ".join((*path, label)) if depth > 6 else label
        lines.extend(["", "#" * min(max(depth, 1), 6) + " " + title, ""])

    def text_line(text: str, prefix: str = "") -> None:
        physical = text.split("\n")
        if prefix and len(physical) > 1:
            lines.extend([prefix.rstrip(), ""])
            lines.extend("  " + part if part else "" for part in physical)
            lines.append("")
            return
        lines.append(prefix + physical[0])
        indent = "  " if prefix else ""
        lines.extend(indent + part for part in physical[1:])

    def walk(item: Any, depth: int, path: tuple[str, ...]) -> None:
        if isinstance(item, Mapping):
            if not item:
                lines.append("No fields recorded (empty object).")
            mixed = any(_container(child) for child in item.values()) and any(
                not _container(child) for child in item.values()
            )
            labels = [_label(key) for key in item]
            def record_label(key: Any) -> str:
                label = _label(key)
                if labels.count(label) > 1:
                    identity = safe_text(str(key)).replace("\n", "\\n")
                    return f"{label} (field name: {identity})"
                return label
            for key, child in item.items():
                if not _container(child):
                    text_line(_scalar(child), f"- **{record_label(key)}:** ")
                elif mixed:
                    # A nested list item has a real Markdown boundary. A later
                    # parent field cannot accidentally belong to the child.
                    label = record_label(key)
                    lines.extend([f"- **{label}:**", ""])
                    start = len(lines)
                    walk(child, depth + 1, (*path, label))
                    lines[start:] = ["  " + line if line else "" for line in lines[start:]]
                    lines.append("")
                else:
                    label = record_label(key)
                    heading(label, depth, path)
                    walk(child, depth + 1, (*path, label))
        elif isinstance(item, (list, tuple)):
            if not item:
                lines.append("No items recorded (empty list).")
                return
            if all(isinstance(row, Mapping) and row for row in item):
                keys = tuple(item[0])
                headers = [_table_label(key) for key in keys]
                table_headers = len(set(headers)) == len(headers) and all(
                    "\n" not in safe_text(str(key)) for key in keys
                )
                if table_headers and all(tuple(row) == keys and all(
                    not _container(cell) and "\n" not in _scalar(cell)
                    for cell in row.values()
                ) for row in item):
                    # The external emitter never receives recursive values.
                    from md_generator.text.md_emit_json import json_to_markdown

                    rows = [{header.replace("\\", "\\\\"): _scalar(row[key]).replace("\\", "\\\\")
                             for key, header in zip(keys, headers)} for row in item]
                    table = json_to_markdown(rows, "", include_source_block=False,
                                             generate_toc=False).strip()
                    lines.extend(table.splitlines())
                    return
            if all(not _container(child) for child in item):
                for child in item:
                    text_line(_scalar(child), "- ")
            else:
                for index, child in enumerate(item, 1):
                    label = f"Item {index}"
                    heading(label, depth, path)
                    walk(child, depth + 1, (*path, label))
        else:
            text_line(_scalar(item))

    walk(value, level, ())
    return "\n".join(lines).strip() + "\n"


def safe_inline(value: str) -> str:
    return " / ".join(safe_text(value).split("\n"))


def safe_heading(value: str) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _CONTROL_CHARACTER_RE.sub("", text).replace("\n", " ").strip()
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
    "render_structured",
    "safe_heading",
    "safe_inline",
    "safe_text",
]
