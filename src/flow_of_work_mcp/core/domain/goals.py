"""Structured Goal Graph nodes derived from use cases and sequences."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.srs import SourceAnchor


class GoalNodeType(StrEnum):
    USE_CASE = "use_case"
    SEQUENCE = "sequence"
    BEHAVIORAL_EXPECTATION = "behavioral_expectation"


def _text_tuple(values: Iterable[str], field: str, *, required: bool = False) -> tuple[str, ...]:
    normalized = tuple(str(value or "").strip() for value in values if str(value or "").strip())
    if required and not normalized:
        raise ValueError(f"{field} must contain at least one value")
    return normalized


@dataclass(frozen=True)
class UseCaseDraft:
    title: str
    actor: str
    objective: str
    observable_outcome: str
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    source_anchor: SourceAnchor | None = None

    def __post_init__(self) -> None:
        for field_name in ("title", "actor", "objective", "observable_outcome"):
            object.__setattr__(self, field_name, required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "preconditions", _text_tuple(self.preconditions, "preconditions"))
        object.__setattr__(self, "postconditions", _text_tuple(self.postconditions, "postconditions"))
        object.__setattr__(self, "invariants", _text_tuple(self.invariants, "invariants"))


@dataclass(frozen=True)
class SequenceDraft:
    title: str
    participants: tuple[str, ...]
    normal_steps: tuple[str, ...]
    expected_effects: tuple[str, ...]
    alternate_steps: tuple[str, ...] = ()
    failure_steps: tuple[str, ...] = ()
    source_anchor: SourceAnchor | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "participants", _text_tuple(self.participants, "participants", required=True))
        object.__setattr__(self, "normal_steps", _text_tuple(self.normal_steps, "normal_steps", required=True))
        object.__setattr__(self, "expected_effects", _text_tuple(self.expected_effects, "expected_effects", required=True))
        object.__setattr__(self, "alternate_steps", _text_tuple(self.alternate_steps, "alternate_steps"))
        object.__setattr__(self, "failure_steps", _text_tuple(self.failure_steps, "failure_steps"))


@dataclass(frozen=True)
class BehavioralExpectationDraft:
    title: str
    statement: str
    category: str
    observable_outcome: str
    source_anchor: SourceAnchor | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", required_text(self.title, "title"))
        object.__setattr__(self, "statement", required_text(self.statement, "statement"))
        category = required_text(self.category, "category")
        if category not in {"functional", "non_functional"}:
            raise ValueError("category must be functional or non_functional")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "observable_outcome", required_text(self.observable_outcome, "observable_outcome"))
