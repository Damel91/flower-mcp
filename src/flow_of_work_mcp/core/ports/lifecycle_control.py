"""Persistence port for milestones, phase audits and validation audit state."""
from __future__ import annotations

from typing import ContextManager, Mapping, Protocol

from flow_of_work_mcp.core.domain.lifecycle_control import (
    MilestoneDraft,
    PhaseAudit,
    ValidationAuditRecord,
)


class LifecycleControlRepository(Protocol):
    def atomic(self) -> ContextManager[object]: ...

    def promote_milestone(
        self,
        project_id: str,
        draft: MilestoneDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def accept_milestone(
        self,
        project_id: str,
        milestone_id: str,
        *,
        acceptance_evidence: tuple[str, ...],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def milestones(self, project_id: str) -> list[Mapping[str, object]]: ...

    def record_phase_audit(
        self,
        audit: PhaseAudit,
        *,
        actor: str,
        request_id: str = "",
    ) -> PhaseAudit: ...

    def latest_phase_audit(
        self, project_id: str, scope_id: str
    ) -> Mapping[str, object] | None: ...

    def phase_audits(self, project_id: str, scope_id: str) -> list[Mapping[str, object]]: ...

    def all_phase_audits(self, project_id: str) -> list[Mapping[str, object]]: ...

    def record_validation_audit(
        self,
        project_id: str,
        audit: ValidationAuditRecord,
        *,
        actor: str,
        request_id: str = "",
    ) -> ValidationAuditRecord: ...

    def validation_audits(self, project_id: str) -> list[Mapping[str, object]]: ...
