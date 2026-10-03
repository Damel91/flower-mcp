"""Validated initial-baseline import plan value objects."""
from __future__ import annotations

from dataclasses import dataclass

from flow_of_work_mcp.core.domain.goals import SequenceDraft, UseCaseDraft
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.requirements import RequirementDraft
from flow_of_work_mcp.core.domain.srs import SourceAnchor


@dataclass(frozen=True)
class ImportedRequirement:
    source_id: str
    draft: RequirementDraft
    source_anchor: SourceAnchor

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", required_text(self.source_id, "source_id"))


@dataclass(frozen=True)
class ImportedUseCase:
    source_id: str
    draft: UseCaseDraft

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", required_text(self.source_id, "source_id"))


@dataclass(frozen=True)
class ImportedSequence:
    source_id: str
    draft: SequenceDraft
    related_use_case_source_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", required_text(self.source_id, "source_id"))


@dataclass(frozen=True)
class BaselineImportPlan:
    project_id: str
    source_path: str
    content_sha256: str
    profile_id: str
    profile_version: str
    requirements: tuple[ImportedRequirement, ...]
    use_cases: tuple[ImportedUseCase, ...]
    sequences: tuple[ImportedSequence, ...]
    origin: str = "srs_import"

    def __post_init__(self) -> None:
        for field_name in (
            "project_id",
            "source_path",
            "content_sha256",
            "profile_id",
            "profile_version",
        ):
            object.__setattr__(self, field_name, required_text(getattr(self, field_name), field_name))
        origin = required_text(self.origin, "origin")
        if origin not in {"srs_import", "derived_from_code"}:
            raise ValueError("baseline import origin is invalid")
        object.__setattr__(self, "origin", origin)
        if not self.requirements:
            raise ValueError("baseline import requires at least one requirement")
        if not self.use_cases or not self.sequences:
            raise ValueError("baseline import requires at least one use case and sequence")
        source_ids = [
            *[item.source_id for item in self.requirements],
            *[item.source_id for item in self.use_cases],
            *[item.source_id for item in self.sequences],
        ]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("baseline source entity IDs must be globally unique")
