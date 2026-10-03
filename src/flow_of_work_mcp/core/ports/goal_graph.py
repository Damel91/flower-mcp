"""Persistence port for the canonical behavioral Goal Graph."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from flow_of_work_mcp.core.domain.goals import GoalNodeType
from flow_of_work_mcp.core.domain.srs import SourceAnchor


class GoalGraphRepository(Protocol):
    def create_goal_node(
        self,
        project_id: str,
        *,
        node_type: GoalNodeType,
        title: str,
        payload: Mapping[str, Any],
        source_anchor: SourceAnchor | None,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def link_goal_nodes(
        self,
        project_id: str,
        *,
        source_goal_id: str,
        target_goal_id: str,
        relation: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def derive_requirement_candidates(
        self,
        project_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> list[Mapping[str, Any]]: ...

    def goal_graph(self, project_id: str) -> Mapping[str, Any]: ...
