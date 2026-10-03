"""Governed change-unit and implementation-packet value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_requirement_id


_CHANGE_ID_RE = re.compile(r"^CHANGE-[0-9]{6}$")
_PACKET_ID_RE = re.compile(r"^PACKET-[0-9]{6}$")
_MILESTONE_ID_RE = re.compile(r"^MILE-[0-9]{6}$")


class ChangeStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    PARTIAL = "partial"
    IMPLEMENTED = "implemented"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class PacketStatus(StrEnum):
    PLANNED = "planned"
    SCAFFOLDED = "scaffolded"
    PARTIAL = "partial"
    IDLE = "idle"
    IMPLEMENTED = "implemented"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


PACKET_TERMINAL_STATUS_VALUES = frozenset(
    {
        PacketStatus.IMPLEMENTED.value,
        PacketStatus.SUPERSEDED.value,
        PacketStatus.CANCELLED.value,
    }
)
PACKET_QUIESCENT_STATUS_VALUES = frozenset({PacketStatus.IDLE.value})
PACKET_INACTIVE_STATUS_VALUES = (
    PACKET_TERMINAL_STATUS_VALUES | PACKET_QUIESCENT_STATUS_VALUES
)


class PacketReadinessState(StrEnum):
    DRAFT = "draft"
    NEEDS_TARGETS = "needs_targets"
    NEEDS_AUTHORITY = "needs_authority"
    REFINED = "refined"
    EXECUTION_READY = "execution_ready"
    STALE = "stale"
    BLOCKED = "blocked"


class PacketTargetPolicy(StrEnum):
    CODE_TARGETS_REQUIRED = "code_targets_required"
    DOCUMENTAL_ONLY = "documental_only"


class PacketPurpose(StrEnum):
    IMPLEMENTATION = "implementation"
    REMEDIATION = "remediation"


@dataclass(frozen=True)
class GovernedChangeDraft:
    title: str
    rationale: str
    requirement_ids: tuple[str, ...]
    source_refs: tuple[str, ...] = ()
    baseline_refs: tuple[str, ...] = ()
    milestone_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "rationale", required_text(self.rationale, "rationale"))
        if not self.requirement_ids:
            raise ValueError("change unit requires at least one requirement")
        requirement_ids = tuple(validate_requirement_id(item) for item in self.requirement_ids)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("change unit requirement IDs must be unique")
        object.__setattr__(self, "requirement_ids", requirement_ids)
        object.__setattr__(self, "source_refs", _unique_texts(self.source_refs, "source_refs"))
        object.__setattr__(self, "baseline_refs", _unique_texts(self.baseline_refs, "baseline_refs"))
        if self.milestone_id:
            object.__setattr__(self, "milestone_id", validate_milestone_id(self.milestone_id))


@dataclass(frozen=True)
class ImplementationPacketDraft:
    title: str
    completion_criteria: tuple[str, ...]
    objective: str = ""
    rationale: str = ""
    requirement_ids: tuple[str, ...] = ()
    goal_ids: tuple[str, ...] = ()
    in_scope: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    navigation_audit_ids: tuple[str, ...] = ()
    target_binding_ids: tuple[str, ...] = ()
    candidate_set_ids: tuple[str, ...] = ()
    context_snapshot_ids: tuple[str, ...] = ()
    target_policy: PacketTargetPolicy = PacketTargetPolicy.DOCUMENTAL_ONLY
    readiness_state: PacketReadinessState | str = ""
    readiness_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", required_text(self.title, "title"))
        criteria = _unique_texts(self.completion_criteria, "completion_criteria")
        if not criteria:
            raise ValueError("packet requires at least one completion criterion")
        object.__setattr__(self, "completion_criteria", criteria)
        object.__setattr__(self, "objective", str(self.objective or "").strip())
        object.__setattr__(self, "rationale", str(self.rationale or "").strip())
        object.__setattr__(
            self,
            "requirement_ids",
            tuple(validate_requirement_id(item) for item in self.requirement_ids),
        )
        object.__setattr__(self, "goal_ids", _unique_texts(self.goal_ids, "goal_ids") if self.goal_ids else ())
        object.__setattr__(self, "in_scope", _unique_texts(self.in_scope, "in_scope") if self.in_scope else ())
        object.__setattr__(
            self,
            "out_of_scope",
            _unique_texts(self.out_of_scope, "out_of_scope") if self.out_of_scope else (),
        )
        object.__setattr__(
            self,
            "invariants",
            _unique_texts(self.invariants, "invariants") if self.invariants else (),
        )
        object.__setattr__(
            self,
            "unresolved_questions",
            _unique_texts(self.unresolved_questions, "unresolved_questions")
            if self.unresolved_questions
            else (),
        )
        object.__setattr__(
            self,
            "navigation_audit_ids",
            _unique_texts(self.navigation_audit_ids, "navigation_audit_ids")
            if self.navigation_audit_ids
            else (),
        )
        object.__setattr__(
            self,
            "target_binding_ids",
            _unique_texts(self.target_binding_ids, "target_binding_ids")
            if self.target_binding_ids
            else (),
        )
        object.__setattr__(
            self,
            "candidate_set_ids",
            _unique_texts(self.candidate_set_ids, "candidate_set_ids")
            if self.candidate_set_ids
            else (),
        )
        object.__setattr__(
            self,
            "context_snapshot_ids",
            _unique_texts(self.context_snapshot_ids, "context_snapshot_ids")
            if self.context_snapshot_ids
            else (),
        )
        target_policy = PacketTargetPolicy(self.target_policy)
        object.__setattr__(self, "target_policy", target_policy)
        readiness_state = (
            PacketReadinessState(self.readiness_state)
            if self.readiness_state
            else (
                PacketReadinessState.NEEDS_TARGETS
                if target_policy == PacketTargetPolicy.CODE_TARGETS_REQUIRED
                else PacketReadinessState.EXECUTION_READY
            )
        )
        object.__setattr__(self, "readiness_state", readiness_state)
        object.__setattr__(
            self,
            "readiness_blockers",
            _unique_texts(self.readiness_blockers, "readiness_blockers")
            if self.readiness_blockers
            else (),
        )


@dataclass(frozen=True)
class PacketTransition:
    status: PacketStatus
    criterion_results: Mapping[str, str] = None  # type: ignore[assignment]
    blocking_reasons: tuple[str, ...] = ()
    disposition: str = ""
    successor_packet_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PacketStatus(self.status))
        results = {
            required_text(str(key), "criterion_id"): required_text(str(value), "criterion_result")
            for key, value in dict(self.criterion_results or {}).items()
        }
        object.__setattr__(self, "criterion_results", results)
        object.__setattr__(
            self,
            "blocking_reasons",
            _unique_texts(self.blocking_reasons, "blocking_reasons"),
        )
        object.__setattr__(self, "disposition", str(self.disposition or "").strip())
        if self.successor_packet_id:
            object.__setattr__(
                self,
                "successor_packet_id",
                validate_packet_id(self.successor_packet_id),
            )


def validate_change_id(change_id: str) -> str:
    value = required_text(change_id, "change_id")
    if not _CHANGE_ID_RE.fullmatch(value):
        raise ValueError("change_id must match CHANGE-000000")
    return value


def validate_packet_id(packet_id: str) -> str:
    value = required_text(packet_id, "packet_id")
    if not _PACKET_ID_RE.fullmatch(value):
        raise ValueError("packet_id must match PACKET-000000")
    return value


def validate_milestone_id(milestone_id: str) -> str:
    value = required_text(milestone_id, "milestone_id")
    if not _MILESTONE_ID_RE.fullmatch(value):
        raise ValueError("milestone_id must match MILE-000000")
    return value


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(item), field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized
