"""Review findings, verification campaigns and acceptance value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_requirement_id


_FINDING_ID_RE = re.compile(r"^FIND-[0-9]{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^CAMP-[0-9]{6}$")
_CASE_ID_RE = re.compile(r"^CASE-[0-9]{6}$")


class ReviewFindingSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingDisposition(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    ACCEPTED_EXCEPTION = "accepted_exception"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class CampaignStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    PARTIAL = "partial"
    PASSED = "passed"
    FAILED = "failed"
    ACCEPTED_EXCEPTION = "accepted_exception"
    CANCELLED = "cancelled"


class CampaignCaseKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    REGRESSION = "regression"
    LIVE_PROBE = "live_probe"
    MANUAL_REVIEW = "manual_review"
    TOOL_SMOKE = "tool_smoke"
    DETERMINISTIC_REGRESSION = "deterministic_regression"
    LIVE_SEQUENCE = "live_sequence"
    NEGATIVE_CASE = "negative_case"
    BOUNDARY_CASE = "boundary_case"
    MILESTONE_ACCEPTANCE = "milestone_acceptance"
    INTEGRATION = "integration"


class CampaignEvidenceKind(StrEnum):
    DETERMINISTIC_TEST = "deterministic_test"
    LIVE_TEST = "live_test"
    MOCKED_PROBE = "mocked_probe"
    MANUAL_REVIEW = "manual_review"
    ACCEPTED_EXCEPTION = "accepted_exception"


class CampaignCaseResult(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    INVALID_EVIDENCE = "invalid_evidence"


def normalize_campaign_case_kind(
    case_kind: CampaignCaseKind | str,
    evidence_kind: CampaignEvidenceKind | str,
    *,
    has_sequence_coverage: bool,
    milestone_scoped: bool = False,
) -> str:
    """Return the v0.4 policy meaning for legacy and canonical case kinds."""
    try:
        kind = CampaignCaseKind(case_kind)
    except ValueError:
        return CampaignCaseKind.TOOL_SMOKE.value
    evidence = CampaignEvidenceKind(evidence_kind)
    if kind in {
        CampaignCaseKind.TOOL_SMOKE,
        CampaignCaseKind.DETERMINISTIC_REGRESSION,
        CampaignCaseKind.LIVE_SEQUENCE,
        CampaignCaseKind.NEGATIVE_CASE,
        CampaignCaseKind.BOUNDARY_CASE,
        CampaignCaseKind.MILESTONE_ACCEPTANCE,
    }:
        return kind.value
    if kind == CampaignCaseKind.NEGATIVE:
        return CampaignCaseKind.NEGATIVE_CASE.value
    if kind == CampaignCaseKind.BOUNDARY:
        return CampaignCaseKind.BOUNDARY_CASE.value
    if kind == CampaignCaseKind.REGRESSION:
        return CampaignCaseKind.DETERMINISTIC_REGRESSION.value
    if kind == CampaignCaseKind.LIVE_PROBE:
        if evidence == CampaignEvidenceKind.LIVE_TEST and has_sequence_coverage:
            return CampaignCaseKind.LIVE_SEQUENCE.value
        return CampaignCaseKind.TOOL_SMOKE.value
    if kind == CampaignCaseKind.INTEGRATION:
        if evidence == CampaignEvidenceKind.LIVE_TEST and has_sequence_coverage:
            return CampaignCaseKind.LIVE_SEQUENCE.value
        return CampaignCaseKind.TOOL_SMOKE.value
    if kind == CampaignCaseKind.MANUAL_REVIEW:
        if milestone_scoped:
            return CampaignCaseKind.MILESTONE_ACCEPTANCE.value
        return "manual_evidence"
    return CampaignCaseKind.TOOL_SMOKE.value


@dataclass(frozen=True)
class ReviewFindingDraft:
    change_id: str
    severity: ReviewFindingSeverity
    title: str
    rationale: str
    expected_correction: str
    scope_kind: str
    scope_ref: str
    packet_id: str = ""
    source_anchor: str = ""
    implementation_ref: str = ""
    finding_kind: str = "unspecified"

    def __post_init__(self) -> None:
        if self.finding_kind not in {"semantic", "engineering", "informational", "unspecified"}:
            raise ValueError("finding_kind is invalid")
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "severity", ReviewFindingSeverity(self.severity))
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "rationale", required_text(self.rationale, "rationale"))
        object.__setattr__(
            self,
            "expected_correction",
            required_text(self.expected_correction, "expected_correction"),
        )
        object.__setattr__(self, "scope_kind", required_text(self.scope_kind, "scope_kind"))
        object.__setattr__(self, "scope_ref", required_text(self.scope_ref, "scope_ref"))
        if self.packet_id:
            object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        if not self.source_anchor and not self.implementation_ref:
            raise ValueError("finding requires source_anchor or implementation_ref")


@dataclass(frozen=True)
class FindingDispositionDraft:
    disposition: FindingDisposition
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    disposition_reference: str = ""
    supersedes_finding_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "disposition", FindingDisposition(self.disposition))
        object.__setattr__(self, "rationale", required_text(self.rationale, "rationale"))
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, "evidence_refs"),
        )
        object.__setattr__(
            self,
            "disposition_reference",
            str(self.disposition_reference or "").strip(),
        )
        if self.supersedes_finding_id:
            object.__setattr__(
                self,
                "supersedes_finding_id",
                validate_finding_id(self.supersedes_finding_id),
            )


@dataclass(frozen=True)
class FixingPacketLinkDraft:
    finding_id: str
    packet_id: str
    expected_correction: str
    required_regression_evidence: str
    required_campaign_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "finding_id", validate_finding_id(self.finding_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(
            self,
            "expected_correction",
            required_text(self.expected_correction, "expected_correction"),
        )
        object.__setattr__(
            self,
            "required_regression_evidence",
            required_text(self.required_regression_evidence, "required_regression_evidence"),
        )
        object.__setattr__(
            self,
            "required_campaign_ids",
            tuple(validate_campaign_id(item) for item in self.required_campaign_ids),
        )


@dataclass(frozen=True)
class RemediationRelationshipsDraft:
    """Corrective relationships attached to an already-created packet."""

    change_id: str
    packet_id: str
    finding_ids: tuple[str, ...]
    required_regression_evidence: str
    predecessor_packet_id: str = ""
    required_campaign_ids: tuple[str, ...] = ()
    predecessor_dependency_policy: str = "materialized"

    def __post_init__(self) -> None:
        if self.predecessor_dependency_policy not in {"materialized", "context_only"}:
            raise ValueError("predecessor_dependency_policy is invalid")
        if self.predecessor_dependency_policy == "context_only" and not self.predecessor_packet_id:
            raise ValueError("context_only requires a predecessor_packet_id")
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        finding_ids = tuple(validate_finding_id(item) for item in self.finding_ids)
        if not finding_ids:
            raise ValueError("remediation packet requires at least one finding")
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("remediation finding IDs must be unique")
        object.__setattr__(self, "finding_ids", finding_ids)
        object.__setattr__(
            self,
            "required_regression_evidence",
            required_text(self.required_regression_evidence, "required_regression_evidence"),
        )
        if self.predecessor_packet_id:
            object.__setattr__(
                self,
                "predecessor_packet_id",
                validate_packet_id(self.predecessor_packet_id),
            )
        campaign_ids = tuple(validate_campaign_id(item) for item in self.required_campaign_ids)
        if len(set(campaign_ids)) != len(campaign_ids):
            raise ValueError("required campaign IDs must be unique")
        object.__setattr__(self, "required_campaign_ids", campaign_ids)


@dataclass(frozen=True)
class CampaignDraft:
    change_id: str
    title: str
    target_requirement_ids: tuple[str, ...] = ()
    target_packet_ids: tuple[str, ...] = ()
    target_finding_ids: tuple[str, ...] = ()
    environment_assumptions: tuple[str, ...] = ()
    exception_reference: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(
            self,
            "target_requirement_ids",
            tuple(validate_requirement_id(item) for item in self.target_requirement_ids),
        )
        object.__setattr__(
            self,
            "target_packet_ids",
            tuple(validate_packet_id(item) for item in self.target_packet_ids),
        )
        object.__setattr__(
            self,
            "target_finding_ids",
            tuple(validate_finding_id(item) for item in self.target_finding_ids),
        )
        object.__setattr__(
            self,
            "environment_assumptions",
            _unique_texts(self.environment_assumptions, "environment_assumptions"),
        )
        object.__setattr__(self, "exception_reference", str(self.exception_reference or "").strip())


@dataclass(frozen=True)
class CampaignCaseDraft:
    campaign_id: str
    title: str
    purpose: str
    case_kind: CampaignCaseKind
    evidence_kind: CampaignEvidenceKind
    required: bool = True
    covered_requirement_ids: tuple[str, ...] = ()
    covered_use_case_goal_node_ids: tuple[str, ...] = ()
    covered_sequence_goal_node_ids: tuple[str, ...] = ()
    coverage_notes: str = ""
    out_of_scope_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", validate_campaign_id(self.campaign_id))
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "purpose", required_text(self.purpose, "purpose"))
        object.__setattr__(self, "case_kind", CampaignCaseKind(self.case_kind))
        object.__setattr__(self, "evidence_kind", CampaignEvidenceKind(self.evidence_kind))
        object.__setattr__(
            self,
            "covered_requirement_ids",
            tuple(validate_requirement_id(item) for item in self.covered_requirement_ids),
        )
        object.__setattr__(
            self,
            "covered_use_case_goal_node_ids",
            _unique_texts(self.covered_use_case_goal_node_ids, "covered_use_case_goal_node_ids"),
        )
        object.__setattr__(
            self,
            "covered_sequence_goal_node_ids",
            _unique_texts(self.covered_sequence_goal_node_ids, "covered_sequence_goal_node_ids"),
        )
        object.__setattr__(self, "coverage_notes", str(self.coverage_notes or "").strip())
        object.__setattr__(self, "out_of_scope_reason", str(self.out_of_scope_reason or "").strip())


@dataclass(frozen=True)
class CampaignEvidenceDraft:
    campaign_id: str
    case_id: str
    result: CampaignCaseResult
    evidence_kind: CampaignEvidenceKind
    reference: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", validate_campaign_id(self.campaign_id))
        object.__setattr__(self, "case_id", validate_case_id(self.case_id))
        object.__setattr__(self, "result", CampaignCaseResult(self.result))
        object.__setattr__(self, "evidence_kind", CampaignEvidenceKind(self.evidence_kind))
        object.__setattr__(self, "reference", required_text(self.reference, "reference"))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


def validate_finding_id(finding_id: str) -> str:
    value = required_text(finding_id, "finding_id")
    if not _FINDING_ID_RE.fullmatch(value):
        raise ValueError("finding_id must match FIND-000000")
    return value


def validate_campaign_id(campaign_id: str) -> str:
    value = required_text(campaign_id, "campaign_id")
    if not _CAMPAIGN_ID_RE.fullmatch(value):
        raise ValueError("campaign_id must match CAMP-000000")
    return value


def validate_case_id(case_id: str) -> str:
    value = required_text(case_id, "case_id")
    if not _CASE_ID_RE.fullmatch(value):
        raise ValueError("case_id must match CASE-000000")
    return value


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(item), field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must be unique")
    return normalized
