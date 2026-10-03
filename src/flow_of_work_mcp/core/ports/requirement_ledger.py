"""Persistence port for the canonical requirement lifecycle ledger."""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from flow_of_work_mcp.core.domain import (
    LifecycleStatus,
    VerificationKind,
    VerificationOutcome,
)


class RequirementLedger(Protocol):
    def create_project(self, project_id: str, name: str, *, actor: str) -> Mapping[str, Any]: ...

    def add_requirement(
        self,
        project_id: str,
        *,
        title: str,
        statement: str,
        category: str,
        actor: str,
        rationale: str = "",
        source_anchor: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def revise_requirement(
        self,
        project_id: str,
        requirement_id: str,
        *,
        title: str,
        statement: str,
        category: str,
        actor: str,
        rationale: str,
        source_anchor: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def set_lifecycle_status(
        self,
        project_id: str,
        requirement_id: str,
        *,
        status: LifecycleStatus,
        actor: str,
        reason: str,
        governance_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def record_verification(
        self,
        project_id: str,
        requirement_id: str,
        *,
        kind: VerificationKind,
        outcome: VerificationOutcome,
        reference: str,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
        request_id: str = "",
    ) -> Mapping[str, Any]: ...

    def traceability_matrix(self, project_id: str) -> list[Mapping[str, Any]]: ...

    def requirement_history(self, project_id: str, requirement_id: str) -> Mapping[str, Any]: ...
