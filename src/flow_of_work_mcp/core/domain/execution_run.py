"""Implementation-run continuity value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text


_RUN_ID_RE = re.compile(r"^RUN-[0-9]{6}$")
_STEP_ID_RE = re.compile(r"^STEP-[0-9]{6}$")
_HANDOVER_ID_RE = re.compile(r"^HAND-[0-9]{6}$")


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RunStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RunDraft:
    change_id: str
    packet_id: str
    objective: str
    orchestrator_ref: str = ""
    external_ref: str = ""
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(self, "objective", required_text(self.objective, "objective"))
        object.__setattr__(self, "orchestrator_ref", str(self.orchestrator_ref or "").strip())
        object.__setattr__(self, "external_ref", str(self.external_ref or "").strip())
        object.__setattr__(self, "source_ref", str(self.source_ref or "").strip())


@dataclass(frozen=True)
class RunStepDraft:
    run_id: str
    title: str
    action: str
    target_refs: Mapping[str, object] | None = None
    evidence_refs: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", validate_run_id(self.run_id))
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "action", required_text(self.action, "action"))
        object.__setattr__(self, "target_refs", dict(self.target_refs or {}))
        object.__setattr__(self, "evidence_refs", _unique_texts(self.evidence_refs, "evidence_refs"))


@dataclass(frozen=True)
class RunStepTransition:
    status: RunStepStatus
    evidence_refs: tuple[str, ...] = ()
    retry_rationale: str = ""
    blocking_reason: str = ""
    next_expected_action: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RunStepStatus(self.status))
        object.__setattr__(self, "evidence_refs", _unique_texts(self.evidence_refs, "evidence_refs"))
        object.__setattr__(self, "retry_rationale", str(self.retry_rationale or "").strip())
        object.__setattr__(self, "blocking_reason", str(self.blocking_reason or "").strip())
        object.__setattr__(
            self, "next_expected_action", str(self.next_expected_action or "").strip()
        )


@dataclass(frozen=True)
class RunCompletionDraft:
    completion_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "completion_reference",
            required_text(self.completion_reference, "completion_reference"),
        )


@dataclass(frozen=True)
class HandoverDraft:
    change_id: str = ""
    packet_id: str = ""
    run_id: str = ""
    profile_version: str = "handover-context-v1"

    def __post_init__(self) -> None:
        if self.change_id:
            object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        if self.packet_id:
            object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        if self.run_id:
            object.__setattr__(self, "run_id", validate_run_id(self.run_id))
        object.__setattr__(self, "profile_version", required_text(self.profile_version, "profile_version"))


def validate_run_id(run_id: str) -> str:
    value = required_text(run_id, "run_id")
    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError("run_id must match RUN-000000")
    return value


def validate_step_id(step_id: str) -> str:
    value = required_text(step_id, "step_id")
    if not _STEP_ID_RE.fullmatch(value):
        raise ValueError("step_id must match STEP-000000")
    return value


def validate_handover_id(handover_id: str) -> str:
    value = required_text(handover_id, "handover_id")
    if not _HANDOVER_ID_RE.fullmatch(value):
        raise ValueError("handover_id must match HAND-000000")
    return value


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(item), field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized
