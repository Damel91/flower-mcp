"""Application boundary for packet residual-risk pressure."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_pressure import PacketPressureDraft
from flow_of_work_mcp.core.ports import PacketPressureRepository


class PacketPressureService:
    """Coordinates semantic residual-risk pressure around packets."""

    def __init__(self, repository: PacketPressureRepository) -> None:
        self._repository = repository

    def derive(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        profile: str = "balanced",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.derive_packet_pressure(
            project_id,
            change_id,
            packet_id,
            profile=profile,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get(self, project_id: str, pressure_id: str) -> Mapping[str, object]:
        return self._repository.packet_pressure_state(project_id, pressure_id)

    def latest(self, project_id: str, change_id: str, packet_id: str) -> Mapping[str, object] | None:
        return self._repository.latest_packet_pressure(project_id, change_id, packet_id)

    def record(
        self,
        project_id: str,
        draft: PacketPressureDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.record_packet_pressure(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def accept_risk(
        self,
        project_id: str,
        pressure_id: str,
        *,
        accepted_risk_ref: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.accept_residual_risk(
            project_id,
            pressure_id,
            accepted_risk_ref=accepted_risk_ref,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )
