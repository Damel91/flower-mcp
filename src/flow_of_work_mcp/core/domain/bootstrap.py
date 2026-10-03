"""Bounded value objects for authority-gated project bootstrap."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.provider_surfaces import (
    codingcastle_provider_surfaces,
)


class BootstrapPath(StrEnum):
    REQUIREMENTS_IMPORT = "requirements_import"
    CODE_IMPORT = "code_import"
    REQUIREMENTS_CREATION = "requirements_creation"
    GUIDED_ENGINEERING = "guided_engineering"


class BootstrapStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BootstrapBehaviorSnapshotRequest:
    """Closed request for repository evidence before a Flow Goal Graph exists."""

    project_id: str
    scope_id: str
    source_revision: str
    surfaces: tuple[str, ...]
    max_anchors: int = 64

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        object.__setattr__(self, "scope_id", required_text(self.scope_id, "scope_id"))
        object.__setattr__(
            self, "source_revision", required_text(self.source_revision, "source_revision")
        )
        surfaces = codingcastle_provider_surfaces(
            self.surfaces,
            require_repo=True,
        )
        if not 1 <= self.max_anchors <= 128:
            raise ValueError("bootstrap behavior snapshot max_anchors must be 1..128")
        object.__setattr__(self, "surfaces", surfaces)


@dataclass(frozen=True)
class BootstrapBehaviorAnchor:
    """Provider-owned structural evidence used only during bootstrap derivation."""

    anchor_id: str
    kind: str
    label: str
    summary: str
    source_path: str = ""
    evidence_ids: tuple[str, ...] = ()
    dependency_anchor_ids: tuple[str, ...] = ()
    test_evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("anchor_id", "kind", "label", "summary"):
            object.__setattr__(self, field_name, required_text(getattr(self, field_name), field_name))
        if len(self.label) > 1_000 or len(self.summary) > 4_000:
            raise ValueError("bootstrap behavior anchor text exceeds bounds")
        if len(self.source_path) > 2_048:
            raise ValueError("bootstrap behavior anchor source path exceeds bounds")
        for field_name, values, maximum in (
            ("evidence_ids", self.evidence_ids, 128),
            ("dependency_anchor_ids", self.dependency_anchor_ids, 128),
            ("test_evidence_ids", self.test_evidence_ids, 128),
        ):
            normalized = tuple(str(item or "").strip() for item in values)
            if not all(normalized) or len(set(normalized)) != len(normalized) or len(normalized) > maximum:
                raise ValueError(f"bootstrap behavior anchor {field_name} are invalid")
            object.__setattr__(self, field_name, normalized)
        if self.anchor_id in self.dependency_anchor_ids:
            raise ValueError("bootstrap behavior anchor cannot depend on itself")
        metadata = {str(key): str(value) for key, value in self.metadata.items()}
        if any(not key for key in metadata) or len(metadata) > 32:
            raise ValueError("bootstrap behavior anchor metadata is invalid")
        if any(len(key) > 128 or len(value) > 512 for key, value in metadata.items()):
            raise ValueError("bootstrap behavior anchor metadata exceeds bounds")
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class BootstrapBehaviorSnapshot:
    """Revisioned provider evidence, never a canonical product interpretation."""

    project_id: str
    provider_id: str
    scope_id: str
    source_revision: str
    surfaces: tuple[str, ...]
    anchors: tuple[BootstrapBehaviorAnchor, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        for field_name in ("project_id", "provider_id", "scope_id", "source_revision"):
            object.__setattr__(self, field_name, required_text(getattr(self, field_name), field_name))
        surfaces = codingcastle_provider_surfaces(
            self.surfaces,
            require_repo=True,
        )
        if len(self.anchors) > 128 or len({anchor.anchor_id for anchor in self.anchors}) != len(self.anchors):
            raise ValueError("bootstrap behavior snapshot anchors are invalid")
        available = {anchor.anchor_id for anchor in self.anchors}
        if any(
            dependency not in available
            for anchor in self.anchors
            for dependency in anchor.dependency_anchor_ids
        ):
            raise ValueError("bootstrap behavior snapshot must be closed")
        object.__setattr__(self, "surfaces", surfaces)
