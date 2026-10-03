"""Application service for canonical use cases, sequences and expectations."""
from __future__ import annotations

from typing import Any, Mapping

from flow_of_work_mcp.core.domain.goals import (
    BehavioralExpectationDraft,
    GoalNodeType,
    SequenceDraft,
    UseCaseDraft,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.ports.goal_graph import GoalGraphRepository


class GoalGraphService:
    """Records product intent without turning inferred candidates into requirements."""

    def __init__(self, repository: GoalGraphRepository) -> None:
        self._repository = repository

    def add_use_case(
        self,
        project_id: str,
        draft: UseCaseDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._repository.create_goal_node(
            project_id,
            node_type=GoalNodeType.USE_CASE,
            title=draft.title,
            payload={
                "actor": draft.actor,
                "objective": draft.objective,
                "observable_outcome": draft.observable_outcome,
                "preconditions": list(draft.preconditions),
                "postconditions": list(draft.postconditions),
                "invariants": list(draft.invariants),
            },
            source_anchor=draft.source_anchor,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def add_sequence(
        self,
        project_id: str,
        draft: SequenceDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._repository.create_goal_node(
            project_id,
            node_type=GoalNodeType.SEQUENCE,
            title=draft.title,
            payload={
                "participants": list(draft.participants),
                "normal_steps": list(draft.normal_steps),
                "alternate_steps": list(draft.alternate_steps),
                "failure_steps": list(draft.failure_steps),
                "expected_effects": list(draft.expected_effects),
            },
            source_anchor=draft.source_anchor,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def add_behavioral_expectation(
        self,
        project_id: str,
        draft: BehavioralExpectationDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._repository.create_goal_node(
            project_id,
            node_type=GoalNodeType.BEHAVIORAL_EXPECTATION,
            title=draft.title,
            payload={
                "statement": draft.statement,
                "category": draft.category,
                "observable_outcome": draft.observable_outcome,
            },
            source_anchor=draft.source_anchor,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def link(
        self,
        project_id: str,
        *,
        source_goal_id: str,
        target_goal_id: str,
        relation: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._repository.link_goal_nodes(
            project_id,
            source_goal_id=source_goal_id,
            target_goal_id=target_goal_id,
            relation=required_text(relation, "relation"),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def derive_requirement_candidates(
        self,
        project_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> list[Mapping[str, Any]]:
        return self._repository.derive_requirement_candidates(
            project_id,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def view(self, project_id: str) -> Mapping[str, Any]:
        return self._repository.goal_graph(project_id)
