"""Conservative provider-target filters used during packet authoring."""
from __future__ import annotations

from typing import Mapping


def candidate_can_be_deleted(candidate: Mapping[str, object]) -> bool:
    """Conservatively admit only symbol-like candidates for deletion."""

    kind = str(candidate.get("kind") or "").strip().lower()
    symbol_name = str(candidate.get("symbol_name") or "").strip()
    return bool(symbol_name) and not _obvious_non_symbol_kind(kind)


def _obvious_non_symbol_kind(kind: str) -> bool:
    return kind in {
        "artifact",
        "directory",
        "document",
        "file",
        "folder",
        "package",
        "path",
        "repo",
        "repository",
        "workspace",
    }
