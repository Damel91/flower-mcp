"""Value objects for host-owned Goal Hook projection receipts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GoalHookTrigger(str, Enum):
    GOAL_STARTED = "goal_started"
    GOAL_RESUMED = "goal_resumed"
    LENS_CHANGED = "lens_changed"
    BOUNDED_WORK_COMPLETED = "bounded_work_completed"
    ASYNCHRONOUS_WAKE = "asynchronous_wake"
    BREATH_RESUMED = "breath_resumed"
    CONTEXT_RECONSTRUCTED = "context_reconstructed"
    STRUCTURAL_NO_PROGRESS = "structural_no_progress"


class GoalHookDisposition(str, Enum):
    REANCHOR = "reanchor"
    UNCHANGED_ANCHOR = "unchanged_anchor"


def normalize_goal_hook_trigger(value: str | GoalHookTrigger) -> GoalHookTrigger:
    if isinstance(value, GoalHookTrigger):
        return value
    normalized = str(value or "").strip().lower()
    try:
        return GoalHookTrigger(normalized)
    except ValueError as exc:
        accepted = ", ".join(item.value for item in GoalHookTrigger)
        raise ValueError(f"goal_hook_trigger must identify one of: {accepted}") from exc


@dataclass(frozen=True)
class GoalHookEventReceipt:
    """A deterministic signal the host may use to re-anchor one inference."""

    trigger: GoalHookTrigger
    anchor_fingerprint: str
    receipt_fingerprint: str
    append_required: bool
    disposition: GoalHookDisposition
    trigger_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, GoalHookTrigger):
            raise ValueError("goal_hook_receipt_trigger_invalid")
        for field_name, prefix in (
            ("anchor_fingerprint", "goal-anchor:"),
            ("receipt_fingerprint", "goal-hook-event:"),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.startswith(prefix):
                raise ValueError(f"{field_name} is invalid")
            digest = value.removeprefix(prefix)
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"{field_name} is invalid")
        if not isinstance(self.append_required, bool):
            raise ValueError("append_required must be a boolean")
        expected = (
            GoalHookDisposition.REANCHOR
            if self.append_required
            else GoalHookDisposition.UNCHANGED_ANCHOR
        )
        if self.disposition is not expected:
            raise ValueError("goal_hook_receipt_disposition_inconsistent")
        if not isinstance(self.trigger_ref, str) or len(self.trigger_ref) > 256:
            raise ValueError("trigger_ref must be bounded text")

    def as_payload(self) -> dict[str, object]:
        return {
            "contract": "flow.goal-hook-event.v1",
            "trigger": self.trigger.value,
            "trigger_ref": self.trigger_ref,
            "anchor_fingerprint": self.anchor_fingerprint,
            "receipt_fingerprint": self.receipt_fingerprint,
            "append_required": self.append_required,
            "disposition": self.disposition.value,
        }


__all__ = [
    "GoalHookDisposition",
    "GoalHookEventReceipt",
    "GoalHookTrigger",
    "normalize_goal_hook_trigger",
]
