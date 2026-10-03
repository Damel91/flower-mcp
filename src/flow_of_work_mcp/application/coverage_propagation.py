"""Closed-set propagation from campaign coverage facts to requirement verification."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain import (
    CampaignCaseKind,
    CampaignEvidenceKind,
    CampaignStatus,
    VerificationKind,
    VerificationOutcome,
    normalize_campaign_case_kind,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import AssuranceBlockedError
from flow_of_work_mcp.core.ports import (
    AssuranceRepository,
    GroundingAuditRepository,
    RequirementLedger,
)
from flow_of_work_mcp.application.grounding_readiness import (
    goal_scope_from_case,
    live_grounding_readiness,
)


class CoveragePropagationService:
    """Derives verification evidence without broad campaign-status propagation."""

    def __init__(
        self,
        *,
        assurance: AssuranceRepository,
        requirements: RequirementLedger,
        grounding_audits: GroundingAuditRepository,
    ) -> None:
        self._assurance = assurance
        self._requirements = requirements
        self._grounding_audits = grounding_audits

    def propagate_campaign(
        self,
        project_id: str,
        campaign_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        campaign = self._assurance.campaign_state(project_id, campaign_id)
        status = str(campaign.get("status") or "")
        if status not in {CampaignStatus.PASSED.value, CampaignStatus.ACCEPTED_EXCEPTION.value}:
            raise AssuranceBlockedError(
                "coverage_propagation_requires_accepted_campaign",
                details={"campaign_id": campaign_id, "status": status},
            )
        propagated: list[Mapping[str, object]] = []
        diagnostics: list[Mapping[str, object]] = []
        change_id = str(campaign["change_id"])
        base_request_id = str(request_id or f"coverage:{campaign_id}")
        for case in campaign.get("cases", []):
            if not isinstance(case, Mapping):
                continue
            case_result = str(case.get("result") or "")
            if case_result != "passed":
                diagnostics.append(
                    self._diagnostic(
                        project_id,
                        change_id=change_id,
                        campaign_id=campaign_id,
                        case=case,
                        reason="case_not_passed",
                        actor=actor,
                        request_id=f"{base_request_id}:{case.get('case_id')}:case-not-passed",
                    )
                )
                continue
            covered_requirements = [str(item) for item in case.get("covered_requirement_ids", [])]
            normalized = str(case.get("normalized_case_kind") or "")
            if not normalized:
                normalized = normalize_campaign_case_kind(
                    str(case.get("case_kind") or ""),
                    str(case.get("evidence_kind") or ""),
                    has_sequence_coverage=bool(case.get("covered_sequence_goal_node_ids") or []),
                    milestone_scoped=str(case.get("case_kind") or "")
                    == CampaignCaseKind.MILESTONE_ACCEPTANCE.value,
                )
            effect = self._verification_effect(case, normalized)
            if effect is None:
                diagnostics.append(
                    self._diagnostic(
                        project_id,
                        change_id=change_id,
                        campaign_id=campaign_id,
                        case=case,
                        reason=f"{normalized}_does_not_propagate_requirement_verification",
                        actor=actor,
                        request_id=f"{base_request_id}:{case.get('case_id')}:no-effect",
                    )
                )
                continue
            if not covered_requirements:
                diagnostics.append(
                    self._diagnostic(
                        project_id,
                        change_id=change_id,
                        campaign_id=campaign_id,
                        case=case,
                        reason="coverage_requirements_missing",
                        actor=actor,
                        request_id=f"{base_request_id}:{case.get('case_id')}:requirements-missing",
                    )
                )
                continue
            if effect == VerificationKind.LIVE and (
                not case.get("covered_use_case_goal_node_ids")
                or not case.get("covered_sequence_goal_node_ids")
            ):
                diagnostics.append(
                    self._diagnostic(
                        project_id,
                        change_id=change_id,
                        campaign_id=campaign_id,
                        case=case,
                        reason="live_coverage_scope_incomplete",
                        actor=actor,
                        request_id=f"{base_request_id}:{case.get('case_id')}:live-scope-incomplete",
                    )
                )
                continue
            grounding_projection: Mapping[str, object] | None = None
            if effect == VerificationKind.LIVE:
                grounding_projection = live_grounding_readiness(
                    project_id=project_id,
                    goal_node_ids=goal_scope_from_case(case),
                    audits=self._grounding_audits.grounding_audits(project_id),
                )
                if not grounding_projection.get("ready"):
                    diagnostics.append(
                        self._diagnostic(
                            project_id,
                            change_id=change_id,
                            campaign_id=campaign_id,
                            case=case,
                            reason=f"live_grounding_{grounding_projection.get('state')}",
                            actor=actor,
                            request_id=f"{base_request_id}:{case.get('case_id')}:live-grounding",
                            extra={"grounding": grounding_projection},
                        )
                    )
                    continue
            for requirement_id in covered_requirements:
                evidence = self._requirements.record_verification(
                    project_id,
                    requirement_id,
                    kind=effect,
                    outcome=VerificationOutcome.PASSED,
                    reference=f"campaign:{campaign_id}:case:{case['case_id']}",
                    actor=actor,
                    metadata={
                        "campaign_id": campaign_id,
                        "case_id": str(case["case_id"]),
                        "normalized_case_kind": normalized,
                        "covered_use_case_goal_node_ids": [
                            str(item) for item in case.get("covered_use_case_goal_node_ids", [])
                        ],
                        "covered_sequence_goal_node_ids": [
                            str(item) for item in case.get("covered_sequence_goal_node_ids", [])
                        ],
                        "grounding": dict(grounding_projection or {}),
                    },
                    request_id=(
                        f"{base_request_id}:{case['case_id']}:{requirement_id}:{effect.value}"
                    ),
                )
                propagated.append(evidence)
        return {
            "project_id": project_id,
            "campaign_id": campaign_id,
            "change_id": change_id,
            "propagated": propagated,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _verification_effect(case: Mapping[str, object], normalized: str) -> VerificationKind | None:
        evidence_kind = str(case.get("evidence_kind") or "")
        if normalized == CampaignCaseKind.DETERMINISTIC_REGRESSION.value:
            return VerificationKind.DETERMINISTIC
        if normalized == CampaignCaseKind.LIVE_SEQUENCE.value:
            return VerificationKind.LIVE
        if normalized in {
            CampaignCaseKind.NEGATIVE_CASE.value,
            CampaignCaseKind.BOUNDARY_CASE.value,
        }:
            if evidence_kind == CampaignEvidenceKind.LIVE_TEST.value:
                return VerificationKind.LIVE
            return VerificationKind.DETERMINISTIC
        return None

    def _diagnostic(
        self,
        project_id: str,
        *,
        change_id: str,
        campaign_id: str,
        case: Mapping[str, object],
        reason: str,
        actor: str,
        request_id: str,
        extra: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        payload = {
            "reason": reason,
            "campaign_id": campaign_id,
            "case_id": str(case.get("case_id") or ""),
            "case_kind": str(case.get("case_kind") or ""),
            "normalized_case_kind": str(case.get("normalized_case_kind") or ""),
        }
        if extra:
            payload.update(dict(extra))
        self._assurance.record_coverage_diagnostic(
            project_id,
            change_id=change_id,
            campaign_id=campaign_id,
            case_id=str(case.get("case_id") or ""),
            diagnostic=payload,
            actor=actor,
            request_id=request_id,
        )
        return payload
