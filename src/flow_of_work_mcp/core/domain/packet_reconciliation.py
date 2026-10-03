"""Packet evidence reconciliation value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text


PACKET_EVIDENCE_CONTRACT_VERSION = "packet-evidence-snapshot-v1"

_SCOPE_ID_RE = re.compile(r"^PRECON-[0-9]{6}$")
_CLAIM_ID_RE = re.compile(r"^PECLAIM-[0-9]{6}$")
_SNAPSHOT_ID_RE = re.compile(r"^PESNAP-[0-9]{6}$")
_RUN_ID_RE = re.compile(r"^RCRUN-[0-9]{6}$")
_ITEM_ID_RE = re.compile(r"^RCITEM-[0-9]{6}$")


class PacketEvidenceClaimType(StrEnum):
    TARGET = "target"
    SYMBOL_CONTRACT = "symbol_contract"
    IMPACT = "impact"
    CLEANUP = "cleanup"
    TEST_OBLIGATION = "test_obligation"


class PacketEvidenceClaimOrigin(StrEnum):
    DECLARED = "declared"
    OBSERVED = "observed"


class EvidenceCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ReconciliationClassification(StrEnum):
    CONFIRMED = "confirmed"
    PROPOSED = "proposed"
    CONTRADICTED = "contradicted"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    UNRESOLVED_DYNAMIC = "unresolved_dynamic"
    WAIVED = "waived"
    SUPERSEDED = "superseded"


class ReconciliationScopeState(StrEnum):
    COLLECTING = "collecting"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"
    SUPERSEDED = "superseded"


class ReconciliationItemDisposition(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    WAIVED = "waived"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class PacketEvidenceSnapshotRequest:
    """Closed Flow request passed to a configured evidence provider."""

    reconciliation_scope_id: str
    project_id: str
    packet_id: str
    provider_id: str
    provider_scope_id: str
    selection_ref: str
    source_revision: str
    surfaces: tuple[str, ...]
    selection_refs: tuple[str, ...] = ()
    target_handles: tuple[str, ...] = ()
    workspace_revision: str = ""
    claim_types: tuple[PacketEvidenceClaimType, ...] = tuple(PacketEvidenceClaimType)
    max_claims: int = 512
    max_depth: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_scope_id",
            validate_reconciliation_scope_id(self.reconciliation_scope_id),
        )
        object.__setattr__(self, "project_id", _bounded_text(self.project_id, "project_id", 512))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        for field_name in ("provider_id", "provider_scope_id"):
            object.__setattr__(
                self,
                field_name,
                _bounded_text(getattr(self, field_name), field_name, 1_024),
            )
        selection_ref = str(self.selection_ref or "").strip()
        source_revision = str(self.source_revision or "").strip()
        selection_refs = _unique_bounded_values(
            self.selection_refs, "selection_refs", 128
        )
        target_handles = _unique_bounded_values(
            self.target_handles, "target_handles", 2_048
        )
        if selection_refs:
            if selection_ref or source_revision or not target_handles:
                raise ValueError(
                    "selection-set rehydration requires only selection_refs and target_handles"
                )
        else:
            selection_ref = _bounded_text(
                selection_ref, "selection_ref", 1_024
            )
            source_revision = _bounded_text(
                source_revision, "source_revision", 1_024
            )
        object.__setattr__(self, "selection_ref", selection_ref)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "selection_refs", selection_refs)
        object.__setattr__(self, "target_handles", target_handles)
        surfaces = _unique_bounded_values(self.surfaces, "surfaces", 8)
        if len(surfaces) != 1:
            raise ValueError("packet evidence request requires exactly one surface")
        object.__setattr__(self, "surfaces", surfaces)
        workspace_revision = str(self.workspace_revision or "").strip()
        if len(workspace_revision) > 1_024:
            raise ValueError("workspace_revision exceeds 1024 characters")
        object.__setattr__(self, "workspace_revision", workspace_revision)
        claim_types = tuple(PacketEvidenceClaimType(value) for value in self.claim_types)
        if not claim_types or len(set(claim_types)) != len(claim_types):
            raise ValueError("claim_types must be a non-empty unique tuple")
        object.__setattr__(self, "claim_types", claim_types)
        if not 1 <= self.max_claims <= 2_048:
            raise ValueError("max_claims must be within 1..2048")
        if not 1 <= self.max_depth <= 8:
            raise ValueError("max_depth must be within 1..8")


@dataclass(frozen=True)
class PacketReconciliationScopeDraft:
    change_id: str
    packet_id: str
    profile: str = "target-impact-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        profile = str(self.profile or "target-impact-v1").strip()
        if profile not in {"target-impact-v1"}:
            raise ValueError("unsupported packet reconciliation profile")
        object.__setattr__(self, "profile", profile)


@dataclass(frozen=True)
class PacketEvidenceClaimDraft:
    claim_type: PacketEvidenceClaimType
    claim_key: str
    subject_ref: str
    predicate: str
    object_ref: str = ""
    assertion: Mapping[str, object] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    required: bool = True
    dynamic: bool = False
    contradicted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_type", PacketEvidenceClaimType(self.claim_type))
        object.__setattr__(self, "claim_key", _bounded_text(self.claim_key, "claim_key", 512))
        object.__setattr__(self, "subject_ref", _bounded_text(self.subject_ref, "subject_ref", 1024))
        object.__setattr__(self, "predicate", _bounded_text(self.predicate, "predicate", 256))
        object.__setattr__(self, "object_ref", str(self.object_ref or "").strip())
        if len(self.object_ref) > 1024:
            raise ValueError("object_ref exceeds 1024 characters")
        object.__setattr__(self, "assertion", _bounded_mapping(self.assertion, "assertion"))
        object.__setattr__(self, "evidence_refs", _unique_refs(self.evidence_refs))
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")
        if not isinstance(self.dynamic, bool):
            raise ValueError("dynamic must be boolean")
        if not isinstance(self.contradicted, bool):
            raise ValueError("contradicted must be boolean")


@dataclass(frozen=True)
class PacketEvidenceSnapshotDraft:
    reconciliation_scope_id: str
    packet_id: str
    provider_id: str
    provider_scope_id: str
    provider_snapshot_id: str
    selection_ref: str
    source_revision: str
    surfaces: tuple[str, ...]
    fingerprint: str
    completeness: Mapping[str, str]
    claims: tuple[PacketEvidenceClaimDraft, ...]
    workspace_revision: str = ""
    contract_version: str = PACKET_EVIDENCE_CONTRACT_VERSION
    truncated: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_scope_id",
            validate_reconciliation_scope_id(self.reconciliation_scope_id),
        )
        object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        if self.contract_version != PACKET_EVIDENCE_CONTRACT_VERSION:
            raise ValueError("packet evidence contract version mismatch")
        for field_name in (
            "provider_id",
            "provider_scope_id",
            "provider_snapshot_id",
            "selection_ref",
            "source_revision",
            "fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_text(getattr(self, field_name), field_name, 1024),
            )
        workspace_revision = str(self.workspace_revision or "").strip()
        if len(workspace_revision) > 1024:
            raise ValueError("workspace_revision exceeds 1024 characters")
        object.__setattr__(self, "workspace_revision", workspace_revision)
        surfaces = tuple(_bounded_text(value, "surface", 128) for value in self.surfaces)
        if not surfaces or len(set(surfaces)) != len(surfaces):
            raise ValueError("surfaces must be a non-empty unique tuple")
        object.__setattr__(self, "surfaces", surfaces)
        completeness: dict[str, str] = {}
        for key, value in dict(self.completeness or {}).items():
            claim_type = PacketEvidenceClaimType(str(key)).value
            completeness[claim_type] = EvidenceCompleteness(str(value)).value
        if not completeness:
            raise ValueError("completeness must contain at least one claim family")
        object.__setattr__(self, "completeness", completeness)
        claim_keys = [claim.claim_key for claim in self.claims]
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("snapshot claim keys must be unique")
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be boolean")
        object.__setattr__(self, "diagnostics", _unique_refs(self.diagnostics))


@dataclass(frozen=True)
class ReconciliationItemDraft:
    claim_type: PacketEvidenceClaimType
    claim_key: str
    classification: ReconciliationClassification
    declared_claim_ids: tuple[str, ...] = ()
    observed_claim_ids: tuple[str, ...] = ()
    blocking: bool = True
    severity: str = "medium"
    closure_condition: str = ""
    next_action: Mapping[str, object] = field(default_factory=dict)
    max_attempts: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_type", PacketEvidenceClaimType(self.claim_type))
        object.__setattr__(self, "claim_key", _bounded_text(self.claim_key, "claim_key", 512))
        object.__setattr__(
            self, "classification", ReconciliationClassification(self.classification)
        )
        object.__setattr__(self, "declared_claim_ids", _unique_refs(self.declared_claim_ids))
        object.__setattr__(self, "observed_claim_ids", _unique_refs(self.observed_claim_ids))
        if not isinstance(self.blocking, bool):
            raise ValueError("blocking must be boolean")
        severity = str(self.severity or "medium").strip()
        if severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid reconciliation severity")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(
            self,
            "closure_condition",
            _bounded_text(self.closure_condition, "closure_condition", 2000),
        )
        object.__setattr__(self, "next_action", _bounded_mapping(self.next_action, "next_action"))
        if self.max_attempts <= 0 or self.max_attempts > 100:
            raise ValueError("max_attempts must be within 1..100")


@dataclass(frozen=True)
class ReconciliationItemDispositionDraft:
    item_id: str
    disposition: ReconciliationItemDisposition
    rationale: str
    policy_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", validate_reconciliation_item_id(self.item_id))
        object.__setattr__(
            self, "disposition", ReconciliationItemDisposition(self.disposition)
        )
        if self.disposition == ReconciliationItemDisposition.OPEN:
            raise ValueError("open is not a terminal disposition operation")
        object.__setattr__(self, "rationale", _bounded_text(self.rationale, "rationale", 2000))
        policy_ref = str(self.policy_ref or "").strip()
        if self.disposition == ReconciliationItemDisposition.WAIVED and not policy_ref:
            raise ValueError("waiver requires policy_ref")
        if len(policy_ref) > 512:
            raise ValueError("policy_ref exceeds 512 characters")
        object.__setattr__(self, "policy_ref", policy_ref)


def validate_reconciliation_scope_id(value: str) -> str:
    return _validate_id(value, "reconciliation_scope_id", _SCOPE_ID_RE, "PRECON-000000")


def validate_evidence_claim_id(value: str) -> str:
    return _validate_id(value, "claim_id", _CLAIM_ID_RE, "PECLAIM-000000")


def validate_evidence_snapshot_id(value: str) -> str:
    return _validate_id(value, "snapshot_id", _SNAPSHOT_ID_RE, "PESNAP-000000")


def validate_reconciliation_run_id(value: str) -> str:
    return _validate_id(value, "run_id", _RUN_ID_RE, "RCRUN-000000")


def validate_reconciliation_item_id(value: str) -> str:
    return _validate_id(value, "item_id", _ITEM_ID_RE, "RCITEM-000000")


def _validate_id(value: str, field: str, pattern: re.Pattern[str], example: str) -> str:
    normalized = required_text(value, field)
    if not pattern.fullmatch(normalized):
        raise ValueError(f"{field} must match {example}")
    return normalized


def _bounded_text(value: object, field: str, maximum: int) -> str:
    normalized = required_text(str(value), field)
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _bounded_mapping(value: Mapping[str, object], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    normalized = dict(value)
    try:
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 32768:
        raise ValueError(f"{field} exceeds 32768 bytes")
    return normalized


def _unique_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_bounded_text(value, "reference", 1024) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("references must be unique")
    return normalized


def _unique_bounded_values(
    values: tuple[str, ...], field: str, maximum_items: int
) -> tuple[str, ...]:
    normalized = tuple(
        _bounded_text(value, field, 2_048) for value in tuple(values or ())
    )
    if len(normalized) > maximum_items or len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must be unique and bounded")
    return normalized
