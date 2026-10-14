"""Request-scoped packet advancement authority; never persisted as run state."""
from enum import StrEnum
from typing import Mapping

from flow_of_work_mcp.core.errors import ChangeControlBlockedError


class PacketAdvanceMode(StrEnum):
    ADVANCE = "advance"
    SYNC_ONLY = "sync_only"


def validate_advancement_mode(mode: str, decision: Mapping[str, object] | None = None) -> PacketAdvanceMode:
    try:
        selected = PacketAdvanceMode(mode)
    except (TypeError, ValueError) as exc:
        raise ValueError("packet advancement mode must be advance or sync_only") from exc
    if selected == PacketAdvanceMode.SYNC_ONLY:
        values = dict(decision or {})
        if any(key in values for key in ("_force_provider_start", "_force_provider_stop")):
            raise ChangeControlBlockedError("sync_only_control_decision_prohibited")
        if set(values) - {"operation", "decision", "target", "rationale"}:
            raise ChangeControlBlockedError("sync_only_semantic_decision_prohibited")
        for key in ("operation", "decision"):
            operation = str(values.get(key) or "").strip()
            if operation in {"start_provider_packet", "stop_provider_packet", "start", "stop"}:
                raise ChangeControlBlockedError("sync_only_control_decision_prohibited")
            if operation not in {"", "retry_provider_rejection"}:
                raise ChangeControlBlockedError("sync_only_semantic_decision_prohibited")
    return selected
