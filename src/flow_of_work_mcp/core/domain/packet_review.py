"""Provider-neutral workspace review receipt value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from flow_of_work_mcp.core.domain.assurance import ReviewFindingSeverity
from flow_of_work_mcp.core.domain.identifiers import required_text


_WORKSPACE_REVIEW_ID_RE = re.compile(r"^WREV-[0-9]{6}$")
_OPAQUE_REFERENCE_LIMIT = 512


class WorkspaceReviewDisposition(StrEnum):
    APPROVED = "approved"
    FINDINGS = "findings"
    REJECTED = "rejected"


class WorkspaceReviewCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ProviderReviewFindingDraft:
    provider_finding_ref: str
    severity: ReviewFindingSeverity | str
    title: str
    rationale: str
    expected_correction: str
    scope_kind: str
    scope_ref: str
    source_anchor: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_finding_ref",
            required_text(self.provider_finding_ref, "provider_finding_ref"),
        )
        object.__setattr__(self, "severity", ReviewFindingSeverity(self.severity))
        for field in (
            "title",
            "rationale",
            "expected_correction",
            "scope_kind",
            "scope_ref",
        ):
            object.__setattr__(self, field, required_text(getattr(self, field), field))
        object.__setattr__(self, "source_anchor", str(self.source_anchor or "").strip())

    def as_payload(self) -> dict[str, object]:
        return {
            "provider_finding_ref": self.provider_finding_ref,
            "severity": self.severity.value,
            "title": self.title,
            "rationale": self.rationale,
            "expected_correction": self.expected_correction,
            "scope_kind": self.scope_kind,
            "scope_ref": self.scope_ref,
            "source_anchor": self.source_anchor,
        }


@dataclass(frozen=True)
class WorkspaceReviewReceiptDraft:
    provider_revision: str
    disposition: WorkspaceReviewDisposition | str
    reviewed_target_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    workspace_candidate_id: str
    candidate_revision: str
    provider_review_ref: str
    completeness: WorkspaceReviewCompleteness | str
    findings: tuple[ProviderReviewFindingDraft, ...] = ()
    existing_finding_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_revision",
            required_text(self.provider_revision, "provider_revision"),
        )
        object.__setattr__(self, "disposition", WorkspaceReviewDisposition(self.disposition))
        object.__setattr__(
            self,
            "reviewed_target_refs",
            _unique_texts(self.reviewed_target_refs, "reviewed_target_refs"),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _unique_texts(self.evidence_refs, "evidence_refs"),
        )
        object.__setattr__(
            self,
            "workspace_candidate_id",
            _optional_opaque_reference(self.workspace_candidate_id, "workspace_candidate_id"),
        )
        object.__setattr__(
            self,
            "candidate_revision",
            _optional_opaque_reference(self.candidate_revision, "candidate_revision"),
        )
        object.__setattr__(
            self,
            "provider_review_ref",
            _optional_opaque_reference(self.provider_review_ref, "provider_review_ref"),
        )
        object.__setattr__(
            self, "completeness", WorkspaceReviewCompleteness(self.completeness)
        )
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(
            self,
            "existing_finding_ids",
            _unique_texts(self.existing_finding_ids, "existing_finding_ids"),
        )
        if not self.reviewed_target_refs:
            raise ValueError("reviewed_target_refs requires at least one value")
        if not self.evidence_refs:
            raise ValueError("evidence_refs requires at least one value")
        candidate_identity = bool(self.workspace_candidate_id), bool(self.candidate_revision)
        if candidate_identity[0] != candidate_identity[1]:
            raise ValueError(
                "workspace_candidate_id and candidate_revision must be supplied together"
            )
        if self.completeness == WorkspaceReviewCompleteness.COMPLETE:
            for field in (
                "workspace_candidate_id",
                "candidate_revision",
                "provider_review_ref",
            ):
                required_text(getattr(self, field), field)
        if self.disposition == WorkspaceReviewDisposition.APPROVED:
            if self.completeness != WorkspaceReviewCompleteness.COMPLETE:
                raise ValueError("approved workspace review requires complete evidence")
            if self.findings or self.existing_finding_ids:
                raise ValueError("approved workspace review cannot contain findings")
        if self.disposition in {
            WorkspaceReviewDisposition.FINDINGS,
            WorkspaceReviewDisposition.REJECTED,
        } and not (self.findings or self.existing_finding_ids):
            raise ValueError(
                f"{self.disposition.value} workspace review requires at least one finding"
            )
        refs = [item.provider_finding_ref for item in self.findings]
        if len(set(refs)) != len(refs):
            raise ValueError("provider finding references must be unique")


def validate_workspace_review_id(value: str) -> str:
    review_id = required_text(value, "workspace_review_id")
    if not _WORKSPACE_REVIEW_ID_RE.fullmatch(review_id):
        raise ValueError("workspace_review_id must match WREV-000000")
    return review_id


def _unique_texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(required_text(item, field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} values must be unique")
    return normalized


def _optional_opaque_reference(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > _OPAQUE_REFERENCE_LIMIT:
        raise ValueError(f"{field} must be at most {_OPAQUE_REFERENCE_LIMIT} characters")
    return normalized
