"""Deterministic assurance policy for findings, campaigns and acceptance."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.assurance import (
    CampaignCaseDraft,
    CampaignCaseKind,
    CampaignDraft,
    CampaignEvidenceDraft,
    CampaignStatus,
    normalize_campaign_case_kind,
    FindingDisposition,
    FindingDispositionDraft,
    FixingPacketLinkDraft,
    RemediationRelationshipsDraft,
    ReviewFindingDraft,
)
from flow_of_work_mcp.core.domain.change_control import PacketStatus
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import AssuranceBlockedError
from flow_of_work_mcp.core.ports import AssuranceRepository, ChangeControlRepository


_TERMINAL_FINDING_DISPOSITIONS = {
    FindingDisposition.RESOLVED.value,
    FindingDisposition.ACCEPTED_EXCEPTION.value,
    FindingDisposition.SUPERSEDED.value,
    FindingDisposition.CANCELLED.value,
}


class AssuranceService:
    """Applies evidence gates around findings, campaigns and change acceptance."""

    def __init__(
        self,
        *,
        assurance: AssuranceRepository,
        changes: ChangeControlRepository,
        engineer_gate=None,
    ) -> None:
        self._assurance = assurance
        self._changes = changes
        self._engineer_gate = engineer_gate

    def record_finding(
        self,
        project_id: str,
        draft: ReviewFindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.record_finding(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_finding(self, project_id: str, finding_id: str) -> Mapping[str, object]:
        if self._engineer_gate is not None:
            return self._engineer_gate.finding_context(project_id, finding_id)
        return self._assurance.finding_state(project_id, finding_id)

    def reassess_intent(self, project_id, finding_id, assessment, *, actor, request_id):
        if self._engineer_gate is None:
            raise AssuranceBlockedError("engineer_gate_unavailable")
        return self._engineer_gate.reassess_intent(project_id, finding_id, assessment, actor=actor, request_id=request_id)

    def set_finding_disposition(
        self,
        project_id: str,
        finding_id: str,
        draft: FindingDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        if draft.disposition == FindingDisposition.RESOLVED and not draft.evidence_refs:
            raise AssuranceBlockedError(
                "finding_resolution_requires_evidence",
                details={"finding_id": finding_id},
            )
        if draft.disposition in {
            FindingDisposition.ACCEPTED_EXCEPTION,
            FindingDisposition.DEFERRED,
            FindingDisposition.SUPERSEDED,
            FindingDisposition.CANCELLED,
        } and not draft.disposition_reference:
            raise AssuranceBlockedError(
                "finding_disposition_requires_reference",
                details={"finding_id": finding_id, "disposition": draft.disposition.value},
            )
        return self._assurance.set_finding_disposition(
            project_id,
            finding_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def link_fixing_packet(
        self,
        project_id: str,
        draft: FixingPacketLinkDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.link_fixing_packet(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def link_remediation_relationships(
        self,
        project_id: str,
        draft: RemediationRelationshipsDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.link_remediation_relationships(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def create_campaign(
        self,
        project_id: str,
        draft: CampaignDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.create_campaign(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def add_campaign_case(
        self,
        project_id: str,
        draft: CampaignCaseDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.add_campaign_case(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def record_campaign_evidence(
        self,
        project_id: str,
        draft: CampaignEvidenceDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._assurance.record_campaign_evidence(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def set_campaign_disposition(
        self,
        project_id: str,
        campaign_id: str,
        status: CampaignStatus,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        if status in {CampaignStatus.ACCEPTED_EXCEPTION, CampaignStatus.CANCELLED}:
            required_text(disposition_reference, "disposition_reference")
        return self._assurance.set_campaign_disposition(
            project_id,
            campaign_id,
            CampaignStatus(status),
            disposition_reference=disposition_reference,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def request_change_acceptance(
        self,
        project_id: str,
        change_id: str,
        *,
        acceptance_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        required_text(acceptance_reference, "acceptance_reference")
        blockers = self._acceptance_blockers(project_id, change_id)
        if blockers:
            raise AssuranceBlockedError(
                "change_acceptance_blocked",
                details={"change_id": change_id, "blockers": blockers},
            )
        return self._assurance.accept_change(
            project_id,
            change_id,
            acceptance_reference=acceptance_reference,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def _acceptance_blockers(self, project_id: str, change_id: str) -> list[Mapping[str, object]]:
        blockers: list[Mapping[str, object]] = []
        change = self._changes.change_state(project_id, change_id)
        for packet in change.get("packets", []):
            if not isinstance(packet, Mapping):
                continue
            status = str(packet["status"])
            if status == PacketStatus.IMPLEMENTED.value:
                continue
            if status == PacketStatus.SUPERSEDED.value and str(packet.get("successor_packet_id") or ""):
                continue
            if status == PacketStatus.CANCELLED.value and str(packet.get("disposition") or ""):
                continue
            blockers.append(
                {
                    "kind": "packet_unresolved",
                    "packet_id": str(packet["packet_id"]),
                    "status": status,
                }
            )
        findings = self._assurance.findings_for_change(project_id, change_id)
        for finding in findings:
            disposition = str(finding["disposition"])
            if disposition in _TERMINAL_FINDING_DISPOSITIONS:
                if disposition == FindingDisposition.RESOLVED.value and not finding.get("evidence_refs"):
                    blockers.append(
                        {
                            "kind": "finding_resolution_missing_evidence",
                            "finding_id": str(finding["finding_id"]),
                        }
                    )
                continue
            blockers.append(
                {
                    "kind": "finding_unresolved",
                    "finding_id": str(finding["finding_id"]),
                    "disposition": disposition,
                }
            )
        campaigns = self._assurance.campaigns_for_change(project_id, change_id)
        if not campaigns:
            blockers.append({"kind": "campaign_missing", "change_id": change_id})
        for campaign in campaigns:
            status = str(campaign["status"])
            if _happy_path_only(campaign) and not campaign.get("exception_reference"):
                blockers.append(
                    {
                        "kind": "campaign_happy_path_only",
                        "campaign_id": str(campaign["campaign_id"]),
                    }
                )
            if status in {CampaignStatus.PASSED.value, CampaignStatus.ACCEPTED_EXCEPTION.value}:
                continue
            blockers.append(
                {
                    "kind": "campaign_not_green",
                    "campaign_id": str(campaign["campaign_id"]),
                    "status": status,
                }
            )
        return blockers


def _happy_path_only(campaign: Mapping[str, object]) -> bool:
    cases = [case for case in campaign.get("cases", []) if isinstance(case, Mapping)]
    if not cases:
        return True
    required = [case for case in cases if bool(case.get("required", True))]
    if not required:
        return True
    failure_oriented = {
        CampaignCaseKind.NEGATIVE_CASE.value,
        CampaignCaseKind.BOUNDARY_CASE.value,
        CampaignCaseKind.DETERMINISTIC_REGRESSION.value,
    }
    return not any(
        normalize_campaign_case_kind(
            str(case.get("case_kind") or ""),
            str(case.get("evidence_kind") or ""),
            has_sequence_coverage=bool(case.get("covered_sequence_goal_node_ids") or []),
            milestone_scoped=str(case.get("case_kind") or "") == CampaignCaseKind.MILESTONE_ACCEPTANCE.value,
        )
        in failure_oriented
        for case in required
    )
