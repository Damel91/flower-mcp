"""Tree-sitter backed Markdown parser for deterministic SRS validation."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from flow_of_work_mcp.core.domain.srs import ParsedSection, ParsedSrs, SourceAnchor


class MarkdownAstParserUnavailable(RuntimeError):
    """Raised when the runtime cannot load the Markdown tree-sitter parser."""


@lru_cache(maxsize=1)
def _markdown_parser():
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_markdown

        return Parser(Language(tree_sitter_markdown.language()))
    except Exception as exc:  # noqa: BLE001 - converted to explicit readiness error.
        raise MarkdownAstParserUnavailable(
            "tree-sitter markdown parser is unavailable; install "
            "the core tree-sitter and tree-sitter-markdown dependencies"
        ) from exc


def markdown_parser_status() -> dict[str, Any]:
    """Return runtime readiness for Markdown parsers without network access."""

    status: dict[str, Any] = {"available": True, "parsers": {}}
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_markdown
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "parsers": {},
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    for language, grammar in (
        ("markdown", tree_sitter_markdown.language),
        ("markdown_inline", tree_sitter_markdown.inline_language),
    ):
        try:
            Parser(Language(grammar()))
            status["parsers"][language] = {"available": True}
        except Exception as exc:  # noqa: BLE001
            status["available"] = False
            status["parsers"][language] = {
                "available": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    return status


class MarkdownSrsParser:
    """Parse SRS Markdown sections through the Markdown tree-sitter grammar."""

    def __init__(self, allowed_root: str | Path | None = None) -> None:
        self._allowed_root = (
            Path(allowed_root).expanduser().resolve() if allowed_root is not None else None
        )
        self._parser = _markdown_parser()

    def parse(self, source_path: str | Path) -> ParsedSrs:
        path = Path(source_path).expanduser().resolve()
        if path.suffix.lower() not in {".md", ".markdown"}:
            raise ValueError("structural SRS validation currently accepts Markdown files only")
        if self._allowed_root is not None:
            try:
                path.relative_to(self._allowed_root)
            except ValueError as exc:
                raise ValueError("source_path is outside the configured import root") from exc
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"unable to read SRS source: {path}") from exc

        return self.parse_text(content, source_path=path)

    def parse_text(self, content: str, *, source_path: str | Path) -> ParsedSrs:
        path = Path(source_path).expanduser().resolve()
        content_bytes = content.encode("utf-8")
        tree = self._parser.parse(content_bytes)
        headings = self._heading_nodes(tree.root_node, content_bytes)
        lines = content.splitlines()

        sections: list[ParsedSection] = []
        for index, heading in enumerate(headings):
            next_start_line = len(lines) + 1
            for candidate in headings[index + 1 :]:
                if candidate["level"] <= heading["level"]:
                    next_start_line = candidate["line_start"]
                    break

            body_start_index = heading["body_start_index"]
            body_end_index = max(body_start_index, next_start_line - 1)
            body = "\n".join(lines[body_start_index:body_end_index]).strip()
            line_end = max(heading["line_start"], body_end_index)
            sections.append(
                ParsedSection(
                    heading=heading["title"],
                    level=heading["level"],
                    body=body,
                    anchor=SourceAnchor(
                        source_path=str(path),
                        line_start=heading["line_start"],
                        line_end=line_end,
                        label=heading["title"],
                    ),
                )
            )

        return ParsedSrs(
            source_path=str(path),
            content_sha256=hashlib.sha256(content_bytes).hexdigest(),
            line_count=len(lines),
            sections=tuple(sections),
        )

    def _heading_nodes(self, root_node: Any, content_bytes: bytes) -> list[dict[str, Any]]:
        headings: list[dict[str, Any]] = []
        for node in self._walk(root_node):
            node_type = str(getattr(node, "type", "") or "")
            if node_type not in {"atx_heading", "setext_heading"} and "heading" not in node_type:
                continue
            raw_text = content_bytes[node.start_byte : node.end_byte].decode(
                "utf-8",
                errors="ignore",
            )
            level, title = self._heading_title(node_type, raw_text)
            if not title:
                continue
            end_point = getattr(node, "end_point")
            end_row, end_column = self._point_row_column(end_point)
            body_start_index = end_row if end_column == 0 else end_row + 1
            start_point = getattr(node, "start_point")
            start_row, _start_column = self._point_row_column(start_point)
            headings.append(
                {
                    "line_start": start_row + 1,
                    "body_start_index": body_start_index,
                    "level": level,
                    "title": title,
                    "start_byte": int(getattr(node, "start_byte")),
                }
            )
        headings.sort(key=lambda item: (item["line_start"], item["start_byte"]))
        return headings

    def _heading_title(self, node_type: str, text: str) -> tuple[int, str]:
        lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return 1, ""
        first = lines[0].strip()
        if node_type == "atx_heading" or first.startswith("#"):
            level = len(first) - len(first.lstrip("#"))
            title = first[level:].strip().strip("#").strip()
            return max(1, min(level or 1, 6)), title
        if node_type == "setext_heading" and len(lines) >= 2:
            underline = lines[1].strip()
            level = 1 if underline.startswith("=") else 2
            return level, first.strip()
        return 1, first.strip().strip("#").strip()

    def _point_row_column(self, point: Any) -> tuple[int, int]:
        row = getattr(point, "row", None)
        column = getattr(point, "column", None)
        if row is not None and column is not None:
            return int(row), int(column)
        return int(point[0]), int(point[1])

    def _walk(self, node: Any):
        yield node
        for child in getattr(node, "named_children", []) or []:
            yield from self._walk(child)
