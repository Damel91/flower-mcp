"""Immutable generated lifecycle-artifact value objects."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from flow_of_work_mcp.core.domain.identifiers import required_text


class ArtifactKind(StrEnum):
    IMPLEMENTATION_PLAN = "implementation_plan"
    SRS = "srs"
    REQUIREMENTS_CATALOGUE = "requirements_catalogue"
    USE_CASE_SPECIFICATION = "use_case_specification"
    SEQUENCE_SPECIFICATION = "sequence_specification"
    TRACEABILITY_MATRIX = "traceability_matrix"
    MILESTONE_AUDIT = "milestone_audit"
    PHASE_AUDIT = "phase_audit"


@dataclass(frozen=True)
class ArtifactMapping:
    canonical_kind: str
    canonical_id: str
    source_anchor: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_kind", required_text(self.canonical_kind, "canonical_kind"))
        object.__setattr__(self, "canonical_id", required_text(self.canonical_id, "canonical_id"))


@dataclass(frozen=True)
class ArtifactDraft:
    kind: ArtifactKind
    content: str
    mappings: tuple[ArtifactMapping, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", required_text(self.content, "content"))
        pairs = [(item.canonical_kind, item.canonical_id) for item in self.mappings]
        if len(set(pairs)) != len(pairs):
            raise ValueError("artifact canonical mappings must be unique")

    @property
    def content_sha256(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactGeneration:
    project_id: str
    profile_id: str
    profile_version: str
    source_ledger_version: int
    generated_at: str
    artifacts: tuple[ArtifactDraft, ...]
    generation_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        object.__setattr__(self, "profile_id", required_text(self.profile_id, "profile_id"))
        object.__setattr__(self, "profile_version", required_text(self.profile_version, "profile_version"))
        object.__setattr__(self, "generated_at", required_text(self.generated_at, "generated_at"))
        if self.source_ledger_version < 0:
            raise ValueError("artifact source ledger version cannot be negative")
        if not self.artifacts:
            raise ValueError("artifact generation requires at least one artifact")
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(set(kinds)) != len(kinds):
            raise ValueError("artifact generation kinds must be unique")
        if self.generation_id is not None and self.generation_id <= 0:
            raise ValueError("artifact generation ID must be positive")
