"""Persistence port for review findings, campaigns and acceptance gates."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.assurance import (
    CampaignCaseDraft,
    CampaignEvidenceDraft,
    CampaignDraft,
    CampaignStatus,
    FindingDispositionDraft,
    FixingPacketLinkDraft,
    RemediationRelationshipsDraft,
    ReviewFindingDraft,
)


class AssuranceRepository(Protocol):
    def record_finding(
        self,
        project_id: str,
        draft: ReviewFindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def finding_state(self, project_id: str, finding_id: str) -> Mapping[str, object]: ...

    def intent_reassessment_replay(self, project_id: str, finding_id: str, assessment: Mapping[str, object], *, actor: str, request_id: str) -> Mapping[str, object] | None: ...

    def record_intent_reassessment(self, project_id: str, finding_id: str, assessment: Mapping[str, object], *, actor: str, request_id: str, intent_context: Mapping[str, object] | None = None) -> Mapping[str, object]: ...

    def remediation_context(self, project_id: str, change_id: str, packet_id: str) -> Mapping[str, object] | None: ...

    def findings_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, object]]: ...

    def set_finding_disposition(
        self,
        project_id: str,
        finding_id: str,
        draft: FindingDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def link_fixing_packet(
        self,
        project_id: str,
        draft: FixingPacketLinkDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def link_remediation_relationships(
        self,
        project_id: str,
        draft: RemediationRelationshipsDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def create_campaign(
        self,
        project_id: str,
        draft: CampaignDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def campaign_state(self, project_id: str, campaign_id: str) -> Mapping[str, object]: ...

    def campaigns_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, object]]: ...

    def add_campaign_case(
        self,
        project_id: str,
        draft: CampaignCaseDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def record_campaign_evidence(
        self,
        project_id: str,
        draft: CampaignEvidenceDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def set_campaign_disposition(
        self,
        project_id: str,
        campaign_id: str,
        status: CampaignStatus,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def record_coverage_diagnostic(
        self,
        project_id: str,
        *,
        change_id: str,
        campaign_id: str,
        case_id: str,
        diagnostic: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def accept_change(
        self,
        project_id: str,
        change_id: str,
        *,
        acceptance_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...
