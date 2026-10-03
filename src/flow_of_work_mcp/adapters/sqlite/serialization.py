"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.srs import SourceAnchor
from flow_of_work_mcp.core.errors import (
    RequirementConflictError,
)




class SerializationMixin:
    @staticmethod
    def _anchor_to_json(anchor: SourceAnchor | None) -> str:
        if anchor is None:
            return "{}"
        return json.dumps(
            {
                "source_path": anchor.source_path,
                "line_start": anchor.line_start,
                "line_end": anchor.line_end,
                "label": anchor.label,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _anchor_to_text(anchor: SourceAnchor | None) -> str:
        if anchor is None:
            return ""
        return f"{anchor.source_path}:{anchor.line_start}-{anchor.line_end}"

    @staticmethod
    def _anchor_from_json(value: str) -> Mapping[str, Any] | None:
        data = json.loads(value or "{}")
        return data or None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _json_object(value: object) -> dict[str, object]:
        try:
            decoded = json.loads(str(value or "{}"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError("bootstrap stored object is invalid") from exc
        if not isinstance(decoded, dict):
            raise RequirementConflictError("bootstrap stored object is invalid")
        return dict(decoded)

    @staticmethod
    def _json_list(value: object) -> list[dict[str, object]]:
        try:
            decoded = json.loads(str(value or "[]"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError("bootstrap stored list is invalid") from exc
        if not isinstance(decoded, list) or any(not isinstance(item, dict) for item in decoded):
            raise RequirementConflictError("bootstrap stored list is invalid")
        return [dict(item) for item in decoded]
