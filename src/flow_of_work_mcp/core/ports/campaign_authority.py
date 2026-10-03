"""Persistence port for the qualified campaign authority."""
from __future__ import annotations

from typing import ContextManager, Mapping, Protocol, Sequence

from flow_of_work_mcp.core.domain.campaign_authority import (
    BehavioralOracleDraft,
    CampaignCaseSemanticDraft,
    CampaignObligationDecision,
    CampaignScopeDraft,
    OracleAnswerAuthority,
)


class CampaignAuthorityRepository(Protocol):
    def atomic(self) -> ContextManager[object]: ...

    def start_campaign_authority(
        self,
        project_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        first_case: CampaignCaseSemanticDraft | None,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def campaign_authority_state(
        self, project_id: str, campaign_id: str, *, history_limit: int = 20
    ) -> Mapping[str, object]: ...

    def active_campaign_authority(
        self, project_id: str, *, change_id: str = ""
    ) -> Mapping[str, object] | None: ...

    def completed_campaign_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None: ...

    def add_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def edit_campaign_authority_scope(
        self,
        project_id: str,
        campaign_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def cancel_campaign_authority(
        self,
        project_id: str,
        campaign_id: str,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def accept_campaign_exception(
        self,
        project_id: str,
        campaign_id: str,
        *,
        obligation_ids: Sequence[str],
        evidence_gaps: Sequence[str],
        risk_authority: str,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def authorize_campaign_promotion(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        evidence_id: str,
        authority_reference: str,
        regression_obligation: bool,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def record_campaign_completion(
        self,
        project_id: str,
        campaign_id: str,
        *,
        propagation: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def edit_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def remove_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def reorder_campaign_authority_cases(
        self,
        project_id: str,
        campaign_id: str,
        case_order: Sequence[str],
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]: ...

    def derive_campaign_obligations(
        self,
        project_id: str,
        campaign_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def decide_campaign_obligation(
        self,
        project_id: str,
        campaign_id: str,
        obligation_id: str,
        *,
        decision: CampaignObligationDecision,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def bind_campaign_case_obligation(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        obligation_id: str,
        *,
        coverage_intent: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def author_behavioral_oracle(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: BehavioralOracleDraft,
        *,
        actor: str,
        oracle_id: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def answer_oracle_question(
        self,
        project_id: str,
        campaign_id: str,
        oracle_id: str,
        question_id: str,
        *,
        answer: object,
        authority: OracleAnswerAuthority,
        provenance: Sequence[str],
        waiver_scope: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def create_campaign_attestation_intent(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        source_files: Mapping[str, str],
        harness: Mapping[str, object] | None,
        requested_capability: Mapping[str, object] | None = None,
        authority_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def create_campaign_materialization_intent(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        requested_capability: Mapping[str, object],
        authority_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def campaign_provider_context(
        self, project_id: str, campaign_id: str, case_id: str
    ) -> Mapping[str, object]: ...


__all__ = ["CampaignAuthorityRepository"]
