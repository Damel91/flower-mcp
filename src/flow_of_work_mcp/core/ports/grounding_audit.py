"""Persistence port for immutable intention-grounding audits."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.grounding import GroundingAudit


class GroundingAuditRepository(Protocol):
    def record_grounding_audit(
        self,
        audit: GroundingAudit,
        *,
        actor: str,
        request_id: str = "",
    ) -> GroundingAudit: ...

    def grounding_audits(self, project_id: str) -> list[Mapping[str, object]]: ...
