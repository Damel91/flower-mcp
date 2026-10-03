"""Navigation-audit lifecycle value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text


_NAVIGATION_AUDIT_ID_RE = re.compile(r"^NAV-[0-9]{6}$")
_CANDIDATE_SET_ID_RE = re.compile(r"^CSET-[0-9]{6}$")
_TARGET_BINDING_ID_RE = re.compile(r"^TBIND-[0-9]{6}$")


class NavigationAuditState(StrEnum):
    OPENED = "opened"
    COLLECTING = "collecting"
    NEEDS_ORCHESTRATOR_REVIEW = "needs_orchestrator_review"
    ACCEPTED_FOR_PACKET = "accepted_for_packet"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"
    CLOSED = "closed"


class ProviderAuditWindowState(StrEnum):
    INACTIVE = "inactive"
    RECORDING = "recording"
    SNAPSHOT_READY = "snapshot_ready"
    IMPORTED_BY_FLOW = "imported_by_flow"
    FINALIZED = "finalized"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class NavigationAuditBlockDraft:
    milestone_id: str = ""
    change_id: str = ""
    packet_id: str = ""
    related_campaign_id: str = ""
    active_provider: str = ""
    source_revision: str = ""

    def __post_init__(self) -> None:
        if self.change_id:
            object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        if self.packet_id:
            object.__setattr__(self, "packet_id", validate_packet_id(self.packet_id))
        object.__setattr__(self, "milestone_id", str(self.milestone_id or "").strip())
        object.__setattr__(
            self,
            "related_campaign_id",
            str(self.related_campaign_id or "").strip(),
        )
        object.__setattr__(self, "active_provider", str(self.active_provider or "").strip())
        object.__setattr__(self, "source_revision", str(self.source_revision or "").strip())


@dataclass(frozen=True)
class ProviderAuditWindowDraft:
    provider: str
    provider_capability_version: str
    target_scope: Mapping[str, object] = field(default_factory=dict)
    source_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", required_text(self.provider, "provider"))
        object.__setattr__(
            self,
            "provider_capability_version",
            required_text(self.provider_capability_version, "provider_capability_version"),
        )
        object.__setattr__(self, "target_scope", dict(self.target_scope or {}))
        object.__setattr__(self, "source_revision", str(self.source_revision or "").strip())


@dataclass(frozen=True)
class ProviderNavigationAuditSnapshotDraft:
    provider: str
    provider_capability_version: str
    target_scope: Mapping[str, object] = field(default_factory=dict)
    source_revision: str = ""
    events_count: int = 0
    visited_files: tuple[str, ...] = ()
    visited_symbols: tuple[str, ...] = ()
    visited_chunks: tuple[str, ...] = ()
    selected_target_handles: tuple[str, ...] = ()
    rejected_target_handles: tuple[str, ...] = ()
    ambiguous_target_handles: tuple[str, ...] = ()
    traversal_evidence: Mapping[str, object] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    truncated: bool = False
    provider_snapshot_id: str = ""
    selection_ref: str = ""
    fingerprint: str = ""
    exact_identities: tuple[Mapping[str, object], ...] = ()
    page_refs: tuple[str, ...] = ()
    first_sequence: int = 0
    last_sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", required_text(self.provider, "provider"))
        object.__setattr__(
            self,
            "provider_capability_version",
            required_text(self.provider_capability_version, "provider_capability_version"),
        )
        object.__setattr__(self, "target_scope", dict(self.target_scope or {}))
        object.__setattr__(self, "source_revision", str(self.source_revision or "").strip())
        if self.events_count < 0:
            raise ValueError("events_count cannot be negative")
        object.__setattr__(self, "visited_files", _unique_texts(self.visited_files, "visited_files"))
        object.__setattr__(
            self, "visited_symbols", _unique_texts(self.visited_symbols, "visited_symbols")
        )
        object.__setattr__(self, "visited_chunks", _unique_texts(self.visited_chunks, "visited_chunks"))
        object.__setattr__(
            self,
            "selected_target_handles",
            _unique_texts(self.selected_target_handles, "selected_target_handles"),
        )
        object.__setattr__(
            self,
            "rejected_target_handles",
            _unique_texts(self.rejected_target_handles, "rejected_target_handles"),
        )
        object.__setattr__(
            self,
            "ambiguous_target_handles",
            _unique_texts(self.ambiguous_target_handles, "ambiguous_target_handles"),
        )
        object.__setattr__(self, "traversal_evidence", dict(self.traversal_evidence or {}))
        object.__setattr__(self, "diagnostics", _unique_texts(self.diagnostics, "diagnostics"))
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be boolean")
        identities = tuple(dict(value) for value in self.exact_identities)
        for identity in identities:
            required_text(str(identity.get("chunk_id") or ""), "exact_identities.chunk_id")
        object.__setattr__(self, "exact_identities", identities)
        object.__setattr__(self, "page_refs", _unique_texts(self.page_refs, "page_refs"))
        if self.first_sequence < 0 or self.last_sequence < 0:
            raise ValueError("provider snapshot sequence bounds cannot be negative")
        if self.last_sequence and self.first_sequence > self.last_sequence:
            raise ValueError("provider snapshot sequence bounds are inverted")
        selection_ref = str(self.selection_ref or "").strip()
        object.__setattr__(self, "selection_ref", selection_ref)
        canonical = {
            "provider": self.provider,
            "provider_capability_version": self.provider_capability_version,
            "target_scope": dict(self.target_scope),
            "source_revision": self.source_revision,
            "selection_ref": selection_ref,
            "exact_identities": identities,
            "selected_target_handles": self.selected_target_handles,
            "rejected_target_handles": self.rejected_target_handles,
            "ambiguous_target_handles": self.ambiguous_target_handles,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
        }
        derived_fingerprint = sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        fingerprint = str(self.fingerprint or derived_fingerprint).strip()
        provider_snapshot_id = str(
            self.provider_snapshot_id or f"provider-snapshot-{fingerprint[:24]}"
        ).strip()
        object.__setattr__(self, "fingerprint", required_text(fingerprint, "fingerprint"))
        object.__setattr__(
            self,
            "provider_snapshot_id",
            required_text(provider_snapshot_id, "provider_snapshot_id"),
        )


@dataclass(frozen=True)
class CandidateTarget:
    candidate_id: str
    target_handle: str
    target_kind: str
    surface_id: str
    repo_or_workspace_id: str = ""
    file_path: str = ""
    symbol_name: str = ""
    line_start: int | None = None
    line_end: int | None = None
    confidence: float | None = None
    selection_reason: str = ""
    semantic_seed: str = ""
    graph_evidence: Mapping[str, object] = field(default_factory=dict)
    traversal_path: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", required_text(self.candidate_id, "candidate_id"))
        object.__setattr__(
            self, "target_handle", required_text(self.target_handle, "target_handle")
        )
        object.__setattr__(self, "target_kind", required_text(self.target_kind, "target_kind"))
        object.__setattr__(self, "surface_id", required_text(self.surface_id, "surface_id"))
        if self.line_start is not None and self.line_start <= 0:
            raise ValueError("line_start must be positive")
        if self.line_end is not None and self.line_end <= 0:
            raise ValueError("line_end must be positive")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end cannot be before line_start")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("candidate confidence must be within [0, 1]")
        object.__setattr__(self, "graph_evidence", dict(self.graph_evidence or {}))
        object.__setattr__(
            self,
            "traversal_path",
            tuple(required_text(str(value), "traversal_path") for value in self.traversal_path),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(required_text(str(value), "diagnostics") for value in self.diagnostics),
        )


@dataclass(frozen=True)
class CandidateTargetSetDraft:
    provider: str
    provider_capability_version: str
    semantic_seeds: tuple[str, ...]
    candidates: tuple[CandidateTarget, ...]
    source_revision: str = ""
    truncated: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", required_text(self.provider, "provider"))
        object.__setattr__(
            self,
            "provider_capability_version",
            required_text(self.provider_capability_version, "provider_capability_version"),
        )
        object.__setattr__(
            self,
            "semantic_seeds",
            tuple(required_text(str(value), "semantic_seeds") for value in self.semantic_seeds),
        )
        if not self.candidates:
            raise ValueError("candidate target set requires at least one candidate")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate target IDs must be unique")
        object.__setattr__(self, "source_revision", str(self.source_revision or "").strip())
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be boolean")
        object.__setattr__(
            self,
            "metadata",
            _canonical_provider_handoff_metadata(dict(self.metadata or {}), self.candidates),
        )


@dataclass(frozen=True)
class CandidateRejectionDraft:
    candidate_set_id: str
    candidate_id: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_set_id",
            validate_candidate_set_id(self.candidate_set_id),
        )
        object.__setattr__(self, "candidate_id", required_text(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "rationale", required_text(self.rationale, "rationale"))


@dataclass(frozen=True)
class TargetBindingDraft:
    candidate_set_id: str
    candidate_id: str
    selection_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_set_id",
            validate_candidate_set_id(self.candidate_set_id),
        )
        object.__setattr__(self, "candidate_id", required_text(self.candidate_id, "candidate_id"))
        object.__setattr__(
            self,
            "selection_reason",
            required_text(self.selection_reason, "selection_reason"),
        )


@dataclass(frozen=True)
class ContextSnapshotRefDraft:
    provider: str
    context_snapshot_id: str
    source_revision: str
    summary: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", required_text(self.provider, "provider"))
        object.__setattr__(
            self,
            "context_snapshot_id",
            required_text(self.context_snapshot_id, "context_snapshot_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            required_text(self.source_revision, "source_revision"),
        )
        object.__setattr__(self, "summary", str(self.summary or "").strip())
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


def validate_navigation_audit_id(navigation_audit_id: str) -> str:
    value = required_text(navigation_audit_id, "navigation_audit_id")
    if not _NAVIGATION_AUDIT_ID_RE.fullmatch(value):
        raise ValueError("navigation_audit_id must match NAV-000000")
    return value


def validate_candidate_set_id(candidate_set_id: str) -> str:
    value = required_text(candidate_set_id, "candidate_set_id")
    if not _CANDIDATE_SET_ID_RE.fullmatch(value):
        raise ValueError("candidate_set_id must match CSET-000000")
    return value


def validate_target_binding_id(target_binding_id: str) -> str:
    value = required_text(target_binding_id, "target_binding_id")
    if not _TARGET_BINDING_ID_RE.fullmatch(value):
        raise ValueError("target_binding_id must match TBIND-000000")
    return value


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(required_text(str(value), field_name) for value in values)
    return tuple(dict.fromkeys(normalized))


def _canonical_provider_handoff_metadata(
    metadata: dict[str, object],
    candidates: tuple[CandidateTarget, ...],
) -> dict[str, object]:
    """Validate the typed provider handoff without reconstructing provider identities."""

    if "selection_ref" in metadata:
        raise ValueError(
            "metadata.selection_ref is retired; use metadata.provider_selection_ref"
        )
    provider_selection = str(metadata.get("provider_selection_ref") or "").strip()

    handoff_keys = {
        "provider_selection_ref",
        "provider_scope_id",
        "provider_surface_id",
        "provider_target_handles",
        "workspace_revision",
    }
    if not handoff_keys.intersection(metadata):
        return metadata

    provider_scope_id = required_text(
        str(metadata.get("provider_scope_id") or ""), "metadata.provider_scope_id"
    )
    provider_candidate_set_id = required_text(
        str(metadata.get("provider_candidate_set_id") or ""),
        "metadata.provider_candidate_set_id",
    )
    provider_selection = required_text(
        provider_selection, "metadata.provider_selection_ref"
    )
    provider_surface_id = required_text(
        str(metadata.get("provider_surface_id") or ""), "metadata.provider_surface_id"
    )
    raw_handles = metadata.get("provider_target_handles")
    if not isinstance(raw_handles, (list, tuple)):
        raise ValueError("metadata.provider_target_handles must be a list of strings")
    provider_target_handles = _unique_texts(
        tuple(str(value) for value in raw_handles), "metadata.provider_target_handles"
    )
    candidate_handles = tuple(candidate.target_handle for candidate in candidates)
    if set(provider_target_handles) != set(candidate_handles):
        raise ValueError(
            "metadata.provider_target_handles must exactly match candidate target handles"
        )
    return {
        "provider_scope_id": provider_scope_id,
        "provider_candidate_set_id": provider_candidate_set_id,
        "provider_selection_ref": provider_selection,
        "provider_surface_id": provider_surface_id,
        "provider_target_handles": list(provider_target_handles),
        "workspace_revision": str(metadata.get("workspace_revision") or "").strip(),
    }
