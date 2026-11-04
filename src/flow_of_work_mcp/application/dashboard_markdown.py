"""Bounded Markdown presentation as inert semantic nodes, never supplied HTML."""
from __future__ import annotations

from collections import Counter
import re
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


READER_CONTRACT = "flow.dashboard.markdown.v1"
MAXIMUM_SOURCE_BYTES = 256 * 1024
MAXIMUM_NODES = 25000
ALLOWED_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
    "pre", "code", "strong", "em", "s", "hr", "br", "a", "table", "thead", "tbody",
    "tr", "th", "td", "span",
})


class _NodeLimitReached(Exception):
    pass


def limited_reader(reason: str) -> dict[str, object]:
    return {"contract_version": READER_CONTRACT, "status": "limited", "reason": reason,
            "nodes": [], "outline": []}


def _inline_text(tokens) -> str:
    parts = []
    for token in tokens or ():
        if token.type == "image":
            parts.append(_inline_text(token.children) if token.children else token.content)
        elif token.type in {"text", "code_inline"}:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
    return "".join(parts)


def _heading_slug(text: str) -> str:
    # Match Flower's existing offline reader slugs, but never use them as DOM IDs.
    cleaned = "".join(character for character in text.lower().strip()
                      if character.isalnum() or character in "-_ ")
    return re.sub(r"\s+", "-", cleaned)


def _safe_href(value: object, anchors: dict[str, str]) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    if value.startswith("#"):
        target = anchors.get(unquote(value[1:]))
        return "#" + target if target else None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            return value
    except ValueError:
        pass
    return None


def markdown_reader(source: str) -> dict[str, object]:
    if not isinstance(source, str):
        raise TypeError("Markdown reader source must be text")
    if len(source.encode("utf-8")) > MAXIMUM_SOURCE_BYTES:
        return limited_reader("reader_source_limit")
    parser = MarkdownIt("js-default", {"html": False, "linkify": False, "maxNesting": 20})
    tokens = parser.parse(source)
    outline = []
    anchors = {}
    counts = Counter()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            text = _inline_text(tokens[index + 1].children)
            identity = "flower-md-heading-" + str(len(outline) + 1)
            slug = _heading_slug(text)
            duplicate = counts[slug]
            counts[slug] += 1
            if slug:
                anchors[slug + ("-" + str(duplicate) if duplicate else "")] = identity
            token.meta["flower_heading_id"] = identity
            outline.append({"id": identity, "text": text, "level": int(token.tag[1:])})

    count = 0

    def node(value):
        nonlocal count
        count += 1
        if count > MAXIMUM_NODES:
            raise _NodeLimitReached
        return value

    def render(sequence):
        result = []
        stack = [result]
        for token in sequence or ():
            target = stack[-1]
            if token.type == "inline":
                target.extend(render(token.children))
            elif token.nesting == -1:
                stack.pop()
            elif token.type in {"fence", "code_block"}:
                code = node({"tag": "code", "children": [node({"text": token.content})]})
                target.append(node({"tag": "pre", "children": [code]}))
            elif token.type == "code_inline":
                target.append(node({"tag": "code", "children": [node({"text": token.content})]}))
            elif token.type == "image":
                target.append(node({"text": _inline_text(token.children) if token.children else token.content}))
            elif token.type == "softbreak":
                target.append(node({"text": "\n"}))
            elif token.type == "hardbreak":
                target.append(node({"tag": "br", "children": []}))
            elif token.nesting == 1:
                tag = token.tag if token.tag in ALLOWED_TAGS else "span"
                attributes = {}
                if tag == "a":
                    href = _safe_href(token.attrGet("href"), anchors)
                    if href:
                        attributes["href"] = href
                    else:
                        tag = "span"
                if token.type == "heading_open":
                    attributes["id"] = token.meta["flower_heading_id"]
                if tag == "ol":
                    start = token.attrGet("start")
                    if start is not None and str(start).isascii() and str(start).isdecimal() and 0 <= int(start) <= 999999999:
                        attributes["start"] = int(start)
                if tag in {"th", "td"}:
                    align = {"text-align:left": "left", "text-align:center": "center", "text-align:right": "right"}.get(token.attrGet("style"))
                    if align:
                        attributes["align"] = align
                container = node({"tag": tag, "children": [], **attributes})
                target.append(container)
                stack.append(container["children"])
            elif token.type == "hr":
                target.append(node({"tag": "hr", "children": []}))
            elif token.content:
                target.append(node({"text": token.content}))
        return result

    try:
        nodes = render(tokens)
    except _NodeLimitReached:
        return limited_reader("reader_node_limit")
    return {"contract_version": READER_CONTRACT, "status": "ready", "nodes": nodes, "outline": outline}
