"""Provider-neutral handover and ledger projection views."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain import HandoverDraft
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.ports import ExecutionRunRepository


class HandoverService:
    """Creates bounded resume contexts from canonical ledger state."""

    def __init__(self, repository: ExecutionRunRepository) -> None:
        self._repository = repository

    def create_handover(
        self,
        project_id: str,
        draft: HandoverDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.create_handover(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_handover(self, project_id: str, handover_id: str) -> Mapping[str, object]:
        return self._repository.handover_state(project_id, handover_id)

    def resume_context(
        self,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.resume_context(
            project_id, change_id=change_id, packet_id=packet_id, run_id=run_id
        )

    def ledger_projection(
        self,
        project_id: str,
        *,
        projection_kind: str = "lifecycle",
    ) -> Mapping[str, object]:
        return self._repository.ledger_projection(project_id, projection_kind=projection_kind)
