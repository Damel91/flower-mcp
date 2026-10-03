"""Provider-neutral operation kinds used by packet work-plan units."""
from __future__ import annotations

from enum import StrEnum


class PacketTaskOperationKind(StrEnum):
    MODIFY_EXISTING = "modify_existing"
    DELETE_EXISTING = "delete_existing"
    NEW_FILE = "new_file"
    EXTRACT_MOVE = "extract_move"
    INSERT_IN_FILE = "insert_in_file"
    REPLACE_REGION = "replace_region"
    REVIEW_ONLY = "review_only"


__all__ = ["PacketTaskOperationKind"]
