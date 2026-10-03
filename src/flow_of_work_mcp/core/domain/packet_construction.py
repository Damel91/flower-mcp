"""Packet-construction question and audit value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text


_CONSTRUCTION_AUDIT_ID_RE = re.compile(r"^PCAUD-[0-9]{6}$")
_PACKET_QUESTION_ID_RE = re.compile(r"^PQUESTION-[0-9]{6}$")


class PacketQuestionCategory(StrEnum):
    ENTRYPOINT_SURFACE = "entrypoint_surface"
    TARGET_SELECTION = "target_selection"
    SYMBOL_CONTRACT = "symbol_contract"
    IMPACT = "impact"
    CLEANUP = "cleanup"
    TEST_EVIDENCE = "test_evidence"
    AUTHORITY_BLOCKER = "authority_blocker"


class PacketQuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    WAIVED = "waived"
    BLOCKED = "blocked"


class PacketAnswerTemporalAuthority(StrEnum):
    """Time boundary for facts carried by one engineering-gate answer."""

    CURRENT_FACT = "current_fact"
    FUTURE_INSTRUCTION = "future_instruction"
    COMPLETION_EVIDENCE = "completion_evidence"


class PacketConstructionAuditState(StrEnum):
    OPEN = "open"
    READY_FOR_READINESS = "ready_for_readiness"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


@dataclass(frozen=True)
class PacketConstructionAuditDraft:
    change_id: str
    packet_id: str
    milestone_id: str = ""
    profile: str = "balanced"

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(self, "milestone_id", str(self.milestone_id or "").strip())
        object.__setattr__(self, "profile", _profile(self.profile))


@dataclass(frozen=True)
class PacketQuestionResolutionDraft:
    question_id: str
    answer_summary: str = ""
    evidence_refs: tuple[str, ...] = ()
    linked_navigation_refs: tuple[str, ...] = ()
    waiver_rationale: str = ""
    policy_ref: str = ""
    blocker_reason: str = ""
    answer_source: str = "explicit"

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_id", validate_packet_question_id(self.question_id))
        object.__setattr__(self, "answer_summary", str(self.answer_summary or "").strip())
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, "evidence_refs") if self.evidence_refs else (),
        )
        object.__setattr__(
            self,
            "linked_navigation_refs",
            _unique_texts(self.linked_navigation_refs, "linked_navigation_refs")
            if self.linked_navigation_refs
            else (),
        )
        object.__setattr__(self, "waiver_rationale", str(self.waiver_rationale or "").strip())
        object.__setattr__(self, "policy_ref", str(self.policy_ref or "").strip())
        object.__setattr__(self, "blocker_reason", str(self.blocker_reason or "").strip())
        source = str(self.answer_source or "explicit").strip()
        if source not in {"explicit", "deterministic_evidence", "model_proposal"}:
            raise ValueError(
                "answer_source must be explicit, deterministic_evidence or model_proposal"
            )
        object.__setattr__(self, "answer_source", source)


def validate_construction_audit_id(construction_audit_id: str) -> str:
    value = required_text(construction_audit_id, "construction_audit_id")
    if not _CONSTRUCTION_AUDIT_ID_RE.fullmatch(value):
        raise ValueError("construction_audit_id must match PCAUD-000000")
    return value


def validate_packet_question_id(question_id: str) -> str:
    value = required_text(question_id, "question_id")
    if not _PACKET_QUESTION_ID_RE.fullmatch(value):
        raise ValueError("question_id must match PQUESTION-000000")
    return value


def _profile(value: str) -> str:
    normalized = str(value or "balanced").strip()
    if normalized not in {"balanced", "strict_local_orchestrator", "minimal"}:
        raise ValueError("profile must be balanced, strict_local_orchestrator or minimal")
    return normalized


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(item), field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized
