"""Immutable value objects for bounded goal-to-implementation reconciliation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text


class GroundingDivergence(StrEnum):
    """Convergence state or a classified gap between intent and implementation."""

    CONVERGED = "converged"
    GOAL_UNIMPLEMENTED = "goal_unimplemented"
    IMPLEMENTATION_UNTRACED = "implementation_untraced"
    GOAL_PARTIALLY_REALIZED = "goal_partially_realized"
    EVIDENCE_MISSING = "evidence_missing"
    BEHAVIOR_CONFLICT = "behavior_conflict"
    REQUIREMENT_STALE_CANDIDATE = "requirement_stale_candidate"


class GroundingDisposition(StrEnum):
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ImplementationAnchor:
    """One identity in a closed provider or explicitly host-declared evidence set."""

    anchor_id: str
    kind: str
    label: str
    summary: str
    source_path: str = ""
    evidence_ids: tuple[str, ...] = ()
    dependency_anchor_ids: tuple[str, ...] = ()
    test_evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    source_excerpt: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_id", required_text(self.anchor_id, "anchor_id"))
        object.__setattr__(self, "kind", required_text(self.kind, "kind"))
        object.__setattr__(self, "label", required_text(self.label, "label"))
        object.__setattr__(self, "summary", required_text(self.summary, "summary"))
        if len(self.label) > 1_000:
            raise ValueError("implementation anchor label exceeds 1000 characters")
        if len(self.summary) > 4_000:
            raise ValueError("implementation anchor summary exceeds 4000 characters")
        if len(self.source_path) > 2_048:
            raise ValueError("implementation anchor source path exceeds 2048 characters")
        if not isinstance(self.source_excerpt, str) or len(self.source_excerpt) > 4096:
            raise ValueError("implementation anchor source excerpt exceeds 4096 characters")
        if (
            len(set(self.evidence_ids)) != len(self.evidence_ids)
            or any(not str(value or "").strip() or len(str(value)) > 2_048 for value in self.evidence_ids)
        ):
            raise ValueError("implementation anchor evidence IDs must be unique")
        if len(self.evidence_ids) > 128:
            raise ValueError("implementation anchor evidence IDs exceed 128 entries")
        if (
            len(set(self.dependency_anchor_ids)) != len(self.dependency_anchor_ids)
            or any(
                not str(value or "").strip() or len(str(value)) > 2_048
                for value in self.dependency_anchor_ids
            )
        ):
            raise ValueError("implementation anchor dependency IDs must be unique")
        if len(self.dependency_anchor_ids) > 128:
            raise ValueError("implementation anchor dependencies exceed 128 entries")
        if self.anchor_id in self.dependency_anchor_ids:
            raise ValueError("implementation anchor cannot depend on itself")
        if (
            len(set(self.test_evidence_ids)) != len(self.test_evidence_ids)
            or any(not str(value or "").strip() or len(str(value)) > 2_048 for value in self.test_evidence_ids)
        ):
            raise ValueError("implementation anchor test evidence IDs must be unique")
        if len(self.test_evidence_ids) > 128:
            raise ValueError("implementation anchor test evidence IDs exceed 128 entries")
        metadata = {str(key): str(value) for key, value in self.metadata.items()}
        if any(not key for key in metadata):
            raise ValueError("implementation anchor metadata keys must be non-empty")
        if len(metadata) > 32 or any(len(key) > 128 or len(value) > 512 for key, value in metadata.items()):
            raise ValueError("implementation anchor metadata exceeds bounded limits")
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class ImplementationGoalScope:
    """One canonical goal projection supplied to an external graph provider."""

    goal_node_id: str
    node_type: str
    title: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal_node_id", required_text(self.goal_node_id, "goal_node_id"))
        object.__setattr__(self, "node_type", required_text(self.node_type, "node_type"))
        object.__setattr__(self, "title", required_text(self.title, "title"))
        if len(self.title) > 1_000:
            raise ValueError("implementation goal scope title exceeds 1000 characters")
        payload = dict(self.payload)
        try:
            payload_size = len(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            raise ValueError("implementation goal scope payload must be JSON serializable") from exc
        if payload_size > 4_000:
            raise ValueError("implementation goal scope payload exceeds 4000 characters")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True)
class ImplementationSnapshotRequest:
    """Closed, bounded request passed from grounding to an external provider."""

    project_id: str
    goals: tuple[ImplementationGoalScope, ...]
    max_anchors: int
    source_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        if not self.goals:
            raise ValueError("implementation snapshot request requires at least one goal")
        goal_ids = [goal.goal_node_id for goal in self.goals]
        if len(goal_ids) != len(set(goal_ids)):
            raise ValueError("implementation snapshot request goal IDs must be unique")
        if self.max_anchors <= 0:
            raise ValueError("implementation snapshot request max_anchors must be positive")
        source_revision = str(self.source_revision or "").strip()
        if len(source_revision) > 512:
            raise ValueError("implementation snapshot request source_revision exceeds 512 characters")
        object.__setattr__(self, "source_revision", source_revision)


@dataclass(frozen=True)
class ImplementationGraphSnapshot:
    """A project-scoped, versioned implementation projection from a provider."""

    project_id: str
    provider_id: str
    source_revision: str
    anchors: tuple[ImplementationAnchor, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        object.__setattr__(self, "provider_id", required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "source_revision", required_text(self.source_revision, "source_revision"))
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("implementation snapshot anchor IDs must be unique")
        known_anchor_ids = set(anchor_ids)
        for anchor in self.anchors:
            if not set(anchor.dependency_anchor_ids).issubset(known_anchor_ids):
                raise ValueError("implementation anchor dependencies must remain within the snapshot")
        if not isinstance(self.truncated, bool):
            raise ValueError("implementation snapshot truncated must be boolean")


@dataclass(frozen=True)
class GroundingItem:
    """One bounded, auditable reconciliation classification."""

    divergence: GroundingDivergence
    goal_node_id: str = ""
    anchor_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    confidence: float | None = None
    rationale: str = ""
    origin: str = "model"

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("grounding confidence must be within [0, 1]")
        if len(set(self.anchor_ids)) != len(self.anchor_ids):
            raise ValueError("grounding item anchor IDs must be unique")
        if len(set(self.requirement_ids)) != len(self.requirement_ids):
            raise ValueError("grounding item requirement IDs must be unique")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("grounding item candidate IDs must be unique")
        if len(self.rationale) > 1_000:
            raise ValueError("grounding rationale exceeds 1000 characters")
        if self.origin not in {"model", "deterministic"}:
            raise ValueError("grounding origin must be model or deterministic")


@dataclass(frozen=True)
class GroundingAudit:
    """Persistable result of an intention-grounding run."""

    project_id: str
    provider_id: str
    source_revision: str
    selected_goal_ids: tuple[str, ...]
    disposition: GroundingDisposition
    items: tuple[GroundingItem, ...]
    anchors: tuple[ImplementationAnchor, ...] = ()
    model: str = ""
    terminal_reason: str = ""
    prompt_version: str = ""
    input_truncated: bool = False
    diagnostics: tuple[str, ...] = ()
    audit_id: int | None = None
    evidence_authority: str = "provider_snapshot"
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        if self.evidence_authority not in {"provider_snapshot", "host_declared"}:
            raise ValueError("unknown grounding evidence authority")
        provider_id = str(self.provider_id or "").strip()
        if not provider_id and self.evidence_authority != "host_declared":
            raise ValueError("provider_id is required for provider snapshot grounding")
        if provider_id and self.evidence_authority == "host_declared":
            raise ValueError("host-declared grounding cannot claim a provider identity")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "source_revision", required_text(self.source_revision, "source_revision"))
        if not self.selected_goal_ids:
            raise ValueError("grounding audit requires at least one selected goal")
        if len(set(self.selected_goal_ids)) != len(self.selected_goal_ids):
            raise ValueError("grounding audit selected goal IDs must be unique")
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("grounding audit anchor IDs must be unique")
        known_anchor_ids = set(anchor_ids)
        if any(not set(item.anchor_ids).issubset(known_anchor_ids) for item in self.items):
            raise ValueError("grounding items must reference audit snapshot anchors")
        if self.audit_id is not None and self.audit_id <= 0:
            raise ValueError("grounding audit ID must be positive")
        provenance = dict(self.provenance)
        if len(json.dumps(provenance, sort_keys=True, allow_nan=False).encode("utf-8")) > 16000:
            raise ValueError("grounding provenance exceeds its bounded contract")
        object.__setattr__(self, "provenance", provenance)
