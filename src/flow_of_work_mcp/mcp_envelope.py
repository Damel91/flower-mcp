"""Structured MCP response envelopes with no raw exception exposure."""
from __future__ import annotations

from typing import Mapping


def envelope(
    *,
    tool: str,
    status: str,
    result: Mapping[str, object] | None = None,
    reason: str = "",
    audit_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "tool": tool,
        "status": status,
        "reason": reason,
        "result": dict(result or {}),
        "audit_reference": dict(audit_reference or {}),
    }
