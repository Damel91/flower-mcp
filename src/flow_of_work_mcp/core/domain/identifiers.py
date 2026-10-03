"""Deterministic validation and normalization of lifecycle identities."""
from __future__ import annotations

import re


_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REQUIREMENT_ID_RE = re.compile(r"^REQ-[0-9]{6}$")


def required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be a non-empty string")
    return normalized


def validate_project_id(project_id: str) -> str:
    project_id = required_text(project_id, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(
            "project_id must contain lowercase letters, digits, '_' or '-' and be at most 64 characters"
        )
    return project_id


def validate_requirement_id(requirement_id: str) -> str:
    requirement_id = required_text(requirement_id, "requirement_id")
    if not _REQUIREMENT_ID_RE.fullmatch(requirement_id):
        raise ValueError("requirement_id must match REQ-000000")
    return requirement_id


def normalize_requirement_statement(statement: str) -> str:
    return " ".join(required_text(statement, "statement").casefold().split())
