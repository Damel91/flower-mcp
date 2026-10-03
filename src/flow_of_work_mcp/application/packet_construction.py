"""Application boundary for packet-construction audits."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_construction import (
    PacketConstructionAuditDraft,
    PacketQuestionResolutionDraft,
)
from flow_of_work_mcp.core.ports import PacketConstructionRepository


class PacketConstructionService:
    """Coordinates packet-construction question plans and evidence state."""

    def __init__(self, repository: PacketConstructionRepository) -> None:
        self._repository = repository

    def start_audit(
        self,
        project_id: str,
        draft: PacketConstructionAuditDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.start_packet_construction_audit(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_audit(self, project_id: str, construction_audit_id: str) -> Mapping[str, object]:
        return self._repository.packet_construction_audit_state(project_id, construction_audit_id)

    def audit_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None:
        return self._repository.packet_construction_audit_for_packet(
            project_id, change_id, packet_id
        )

    def answer_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.answer_packet_question(
            project_id,
            construction_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def waive_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.waive_packet_question(
            project_id,
            construction_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def block_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.block_packet_question(
            project_id,
            construction_audit_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def readiness_blockers(self, project_id: str, change_id: str, packet_id: str) -> tuple[str, ...]:
        return self._repository.construction_readiness_blockers(project_id, change_id, packet_id)

    def resolve_questions_batch(
        self,
        project_id: str,
        construction_audit_id: str,
        drafts: tuple[PacketQuestionResolutionDraft, ...],
        *,
        expected_spec_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        if not drafts:
            raise ValueError("question answer batch must not be empty")
        return self._repository.resolve_packet_questions_batch(
            project_id,
            construction_audit_id,
            drafts,
            expected_spec_revision=int(expected_spec_revision),
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )
