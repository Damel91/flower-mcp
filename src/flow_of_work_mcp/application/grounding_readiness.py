"""Grounding-backed live readiness for application projections."""

from flow_of_work_mcp.core.domain.grounding_readiness import (
    goal_scope_from_case,
    live_grounding_readiness,
)

__all__ = ["goal_scope_from_case", "live_grounding_readiness"]
