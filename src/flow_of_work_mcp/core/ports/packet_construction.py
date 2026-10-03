"""Persistence port for packet-construction audits."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.packet_construction import (
    PacketConstructionAuditDraft,
    PacketQuestionResolutionDraft,
)


class PacketConstructionRepository(Protocol):
    def start_packet_construction_audit(
        self,
        project_id: str,
        draft: PacketConstructionAuditDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_construction_audit_state(
        self, project_id: str, construction_audit_id: str
    ) -> Mapping[str, object]: ...

    def packet_construction_audit_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def answer_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def waive_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def block_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def resolve_packet_questions_batch(
        self,
        project_id: str,
        construction_audit_id: str,
        drafts: tuple[PacketQuestionResolutionDraft, ...],
        *,
        expected_spec_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def construction_readiness_blockers(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]: ...
