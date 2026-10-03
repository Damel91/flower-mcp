"""Input value objects for requirement and evidence application services."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.enums import VerificationKind, VerificationOutcome
from flow_of_work_mcp.core.domain.identifiers import required_text


@dataclass(frozen=True)
class RequirementDraft:
    title: str
    statement: str
    category: str
    rationale: str = ""
    source_anchor: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "statement", required_text(self.statement, "statement"))
        object.__setattr__(self, "category", required_text(self.category, "category"))
        object.__setattr__(self, "rationale", str(self.rationale or "").strip())
        object.__setattr__(self, "source_anchor", str(self.source_anchor or "").strip())


@dataclass(frozen=True)
class VerificationDraft:
    kind: VerificationKind
    outcome: VerificationOutcome
    reference: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", VerificationKind(self.kind))
        object.__setattr__(self, "outcome", VerificationOutcome(self.outcome))
        object.__setattr__(self, "reference", required_text(self.reference, "reference"))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
