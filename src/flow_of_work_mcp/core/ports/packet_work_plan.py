"""Persistence port for revisioned packet work plans."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.packet_work_plan import PacketWorkPlanDraft


class PacketWorkPlanRepository(Protocol):
    def save_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        intent_fingerprint: str,
        unit: Mapping[str, object],
        candidate_window: list[Mapping[str, object]],
        spec_revision: int,
        plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
    ) -> Mapping[str, object] | None: ...

    def rebase_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        intent_fingerprint: str,
        unit: Mapping[str, object],
        spec_revision: int,
        plan_revision: int,
        actor: str,
    ) -> Mapping[str, object]: ...

    def mark_packet_unit_targets_committed(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        unit: Mapping[str, object],
        candidate_window: list[Mapping[str, object]],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def commit_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        committed_plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def create_packet_work_plan(
        self,
        project_id: str,
        draft: PacketWorkPlanDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_current_plan_revision: int | None = None,
        request_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def packet_work_plan_request_replay(
        self,
        project_id: str,
        request_id: str,
        *,
        request_fingerprint: str,
    ) -> Mapping[str, object] | None: ...

    def packet_work_plan_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int | None = None,
    ) -> Mapping[str, object] | None: ...

    def accepted_packet_work_plan(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def packet_work_plan_history(
        self, project_id: str, change_id: str, packet_id: str
    ) -> list[Mapping[str, object]]: ...

    def transition_packet_work_plan(
        self,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        *,
        status: str,
        expected_packet_revision: int,
        expected_current_plan_revision: int,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...
