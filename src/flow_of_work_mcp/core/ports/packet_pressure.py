"""Persistence port for packet residual-risk pressure."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.packet_pressure import PacketPressureDraft


class PacketPressureRepository(Protocol):
    def derive_packet_pressure(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        profile: str = "balanced",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_pressure_state(
        self, project_id: str, pressure_id: str
    ) -> Mapping[str, object]: ...

    def latest_packet_pressure(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def record_packet_pressure(
        self,
        project_id: str,
        draft: PacketPressureDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def accept_residual_risk(
        self,
        project_id: str,
        pressure_id: str,
        *,
        accepted_risk_ref: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...
