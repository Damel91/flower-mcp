"""Persistence port for governed change units and implementation packets."""
from __future__ import annotations

from typing import ContextManager, Mapping, Protocol

from flow_of_work_mcp.core.domain.change_control import (
    GovernedChangeDraft,
    ImplementationPacketDraft,
    PacketTransition,
)


class ChangeControlRepository(Protocol):
    def atomic(self) -> ContextManager[object]: ...

    def create_change(
        self,
        project_id: str,
        draft: GovernedChangeDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def change_state(self, project_id: str, change_id: str) -> Mapping[str, object]: ...

    def list_changes(self, project_id: str) -> list[Mapping[str, object]]: ...

    def packet_change_id(self, project_id: str, packet_id: str) -> str: ...

    def link_change_milestone(
        self,
        project_id: str,
        change_id: str,
        milestone_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def add_packet(
        self,
        project_id: str,
        change_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def revise_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def link_packet_dependency(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        depends_on_packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def set_packet_target_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        target_policy: str = "",
        readiness_state: str = "",
        navigation_audit_ids: tuple[str, ...] = (),
        target_binding_ids: tuple[str, ...] = (),
        candidate_set_ids: tuple[str, ...] = (),
        context_snapshot_ids: tuple[str, ...] = (),
        readiness_blockers: tuple[str, ...] = (),
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def evaluate_packet_readiness(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def transition_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        transition: PacketTransition,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...
