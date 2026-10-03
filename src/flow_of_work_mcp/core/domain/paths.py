"""Shared path validation for provider-facing lifecycle artifacts."""
from __future__ import annotations

from pathlib import PurePosixPath
import re


def repo_relative_file_path(value: str, *, required: bool = False) -> str:
    """Normalize a portable repo-relative file path without filesystem access."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        if required:
            raise ValueError("file_path is required")
        return ""
    if len(raw) > 512 or "\x00" in raw:
        raise ValueError("file_path is invalid")
    if raw.startswith(("/", "~/")) or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("file_path must be repo-relative")
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("file_path must not contain empty or traversal segments")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError("file_path must name a repo-relative file")
    return path.as_posix()
