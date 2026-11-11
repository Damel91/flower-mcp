"""Canonical campaign authoring, inspection and deterministic advancement."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from flow_of_work_mcp.core.domain.campaign_authoring import ObligationAuthoringBatch
from flow_of_work_mcp.core.domain.campaign_host import (
    OMITTED_CAMPAIGN_DECISIONS,
    HostCampaignCheck,
    HostCampaignResult,
    campaign_case_lane,
    host_case_supported,
    independent_host_obligations,
    next_host_case,
    obligation_requires_independent_proof,
    required_host_cases,
)
from flow_of_work_mcp.core.domain.campaign_authority import (
    BehavioralOracleDraft,
    CampaignCaseSemanticDraft,
    CampaignConstructibility,
    CampaignObligationDecision,
    CampaignScopeDraft,
    OracleAnswerAuthority,
    TestProviderOperation,
    deterministic_materialization_retry_eligible,
    semantic_fingerprint,
    source_attestation_retry_eligible,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.oracle_ir_projection import compile_oracle_ir
from flow_of_work_mcp.core.domain.oracle_questions import (
    applicable_oracle_questions, current_oracle_question, oracle_ir_refinement_applicable, oracle_source_repair,
)
from flow_of_work_mcp.core.errors import AssuranceBlockedError, InputValidationError
from flow_of_work_mcp.core.ports.campaign_authority import CampaignAuthorityRepository
from flow_of_work_mcp.application.test_provider_socket import TestProviderSocketService


class _CoveragePropagation(Protocol):
    def propagate_campaign(
        self,
        project_id: str,
        campaign_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...


class CampaignAuthorityService:
    """Keeps semantic decisions in Flow and provider mechanics outside it."""

    def __init__(
        self,
        repository: CampaignAuthorityRepository,
        *,
        test_provider_socket: TestProviderSocketService | None = None,
        coverage_propagation: _CoveragePropagation | None = None,
    ) -> None:
        self._repository = repository
        self._test_provider_socket = test_provider_socket
        self._coverage_propagation = coverage_propagation

    def start(
        self,
        project_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        first_case: CampaignCaseSemanticDraft | None,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        state = self._repository.start_campaign_authority(
            project_id,
            title=title,
            scope=scope,
            first_case=first_case,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("start", None, state)

    def edit_scope(
        self,
        project_id: str,
        campaign_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        actor: str,
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.edit_campaign_authority_scope(
            project_id,
            campaign_id,
            title=title,
            scope=scope,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("edit_scope", before, state)

    def add_case(
        self,
        project_id: str,
        campaign_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.add_campaign_authority_case(
            project_id,
            campaign_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("add_case", before, state)

    def edit_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.edit_campaign_authority_case(
            project_id,
            campaign_id,
            case_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("edit_case", before, state)

    def remove_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.remove_campaign_authority_case(
            project_id,
            campaign_id,
            case_id,
            rationale=rationale,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("remove_case", before, state)

    def reorder_cases(
        self,
        project_id: str,
        campaign_id: str,
        case_order: Sequence[str],
        *,
        actor: str,
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.reorder_campaign_authority_cases(
            project_id,
            campaign_id,
            case_order,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("reorder_cases", before, state)

    def author_obligations(
        self,
        project_id: str,
        campaign_id: str,
        batch: object,
        *,
        expected_fingerprint: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        state = self._repository.author_campaign_obligations(
            project_id, campaign_id, ObligationAuthoringBatch.parse(batch),
            expected_fingerprint=expected_fingerprint, actor=actor, request_id=request_id,
        )
        return {
            "campaign": _summary(state),
            "authoring_receipt": state["authoring_receipt"],
            "replayed": bool(state.get("replayed")),
            "lifecycle_gate": _campaign_gate(state),
        }

    def issue_host_check(
        self, project_id: str, campaign_id: str, case_id: str, check: object,
        *, actor: str, request_id: str, expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        state = self._repository.issue_campaign_host_check(
            project_id, campaign_id, case_id, HostCampaignCheck.parse(check),
            actor=actor, request_id=request_id, expected_fingerprint=expected_fingerprint,
        )
        return self._host_action_projection(state, "host_attempt")

    def report_host_result(
        self, project_id: str, campaign_id: str, result: object,
        *, actor: str, request_id: str,
    ) -> Mapping[str, object]:
        state = self._repository.report_campaign_host_result(
            project_id, campaign_id, HostCampaignResult.parse(result),
            actor=actor, request_id=request_id,
        )
        return self._host_action_projection(state, "host_receipt")

    @staticmethod
    def _host_action_projection(state: Mapping[str, object], field: str) -> Mapping[str, object]:
        return {
            "campaign": _summary(state),
            field: state[field],
            "replayed": bool(state.get("replayed")),
            "lifecycle_gate": _campaign_gate(state),
        }

    def decide_obligation(
        self,
        project_id: str,
        campaign_id: str,
        obligation_id: str,
        *,
        decision: CampaignObligationDecision,
        rationale: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.decide_campaign_obligation(
            project_id,
            campaign_id,
            obligation_id,
            decision=decision,
            rationale=rationale,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("decide_obligation", before, state)

    def bind_obligation(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        obligation_id: str,
        *,
        coverage_intent: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.bind_campaign_case_obligation(
            project_id,
            campaign_id,
            case_id,
            obligation_id,
            coverage_intent=coverage_intent,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("bind_obligation", before, state)

    def author_oracle(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: BehavioralOracleDraft,
        *,
        actor: str,
        request_id: str,
        oracle_id: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.author_behavioral_oracle(
            project_id,
            campaign_id,
            case_id,
            draft,
            actor=required_text(actor, "actor"),
            oracle_id=oracle_id,
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("author_oracle", before, state)

    def answer_question(
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
        request_id: str,
        expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.answer_oracle_question(
            project_id,
            campaign_id,
            oracle_id,
            question_id,
            answer=answer,
            authority=authority,
            provenance=provenance,
            waiver_scope=waiver_scope,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            expected_fingerprint=expected_fingerprint,
        )
        return self._mutation_projection("answer_question", before, state)

    def attest_source(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        source_files: Mapping[str, str],
        authority_reference: str,
        actor: str,
        request_id: str,
        harness: Mapping[str, object] | None = None,
        requested_capability: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        provider = None
        with self._repository.atomic():
            before = self._repository.campaign_authority_state(project_id, campaign_id)
            state = self._repository.create_campaign_attestation_intent(
                project_id,
                campaign_id,
                case_id,
                source_files=source_files,
                harness=harness,
                requested_capability=requested_capability,
                allow_pending_dispatch=bool(
                    self._test_provider_socket and self._test_provider_socket.configured
                ),
                authority_reference=authority_reference,
                actor=actor,
                request_id=request_id,
            )
            attestation_id = str(state["source_attestation_id"])
            if self._test_provider_socket is not None:
                if state.get("replayed"):
                    provider = self._test_provider_socket.replay_source_materialization(
                        project_id, campaign_id, case_id, attestation_id=attestation_id,
                        request_id=f"{request_id}:provider",
                    )
                else:
                    provider = self._test_provider_socket.queue_materialization(
                        project_id, campaign_id, case_id, source_files=source_files,
                        actor=actor, request_id=f"{request_id}:provider", deliver=False,
                    )
        projection = dict(self._mutation_projection("attest_source", before, state))
        projection["attestation_id"] = attestation_id
        if provider is not None:
            projection["provider"] = _provider_projection(provider)
        return projection

    def authorize_materialization(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        requested_capability: Mapping[str, object],
        authority_reference: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        if self._test_provider_socket is None:
            raise AssuranceBlockedError(
                "test_provider_not_configured",
                details={"next_action": "use attest_source or configure a provider"},
            )
        capability = self._test_provider_socket.resolve_materialization_capability(
            project_id,
            requested_capability,
        )
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        with self._repository.atomic():
            state = self._repository.create_campaign_materialization_intent(
                project_id,
                campaign_id,
                case_id,
                requested_capability=capability,
                authority_reference=authority_reference,
                actor=required_text(actor, "actor"),
                request_id=required_text(request_id, "request_id"),
            )
            provider = self._test_provider_socket.queue_deterministic_materialization(
                project_id,
                campaign_id,
                case_id,
                actor=actor,
                request_id=f"{request_id}:provider",
                deliver=False,
            )
        projection = dict(
            self._mutation_projection("authorize_materialization", before, state)
        )
        projection["provider"] = _provider_projection(provider)
        return projection

    def cancel(
        self,
        project_id: str,
        campaign_id: str,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.cancel_campaign_authority(
            project_id,
            campaign_id,
            disposition_reference=disposition_reference,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("cancel", before, state)

    def retry_provider_rejection(
        self,
        project_id: str,
        campaign_id: str,
        provider_command_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        if self._test_provider_socket is None:
            raise ValueError("test provider socket is unavailable")
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        provider = self._test_provider_socket.retry_rejected(
            project_id,
            campaign_id,
            provider_command_id,
            rationale=rationale,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
            deliver=True,
        )
        state = self._repository.campaign_authority_state(project_id, campaign_id)
        result = dict(
            self._mutation_projection("retry_provider_rejection", before, state)
        )
        result["provider"] = _provider_projection(provider)
        return result

    def accept_exception(
        self,
        project_id: str,
        campaign_id: str,
        *,
        obligation_ids: Sequence[str],
        evidence_gaps: Sequence[str],
        risk_authority: str,
        disposition_reference: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.accept_campaign_exception(
            project_id,
            campaign_id,
            obligation_ids=obligation_ids,
            evidence_gaps=evidence_gaps,
            risk_authority=risk_authority,
            disposition_reference=disposition_reference,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        return self._mutation_projection("accept_exception", before, state)

    def authorize_promotion(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        evidence_id: str,
        authority_reference: str,
        regression_obligation: bool,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.authorize_campaign_promotion(
            project_id,
            campaign_id,
            case_id,
            evidence_id=evidence_id,
            authority_reference=authority_reference,
            regression_obligation=regression_obligation,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        projection = dict(
            self._mutation_projection("authorize_promotion", before, state)
        )
        if self._test_provider_socket is not None:
            projection["provider"] = _provider_projection(
                self._test_provider_socket.queue_operation(
                    project_id,
                    campaign_id,
                    case_id,
                    operation=TestProviderOperation.PROMOTE,
                    actor=required_text(actor, "actor"),
                    request_id=f"{required_text(request_id, 'request_id')}:provider",
                    deliver=True,
                    regression_obligation=regression_obligation,
                    promotion_evidence_id=evidence_id,
                )
            )
            state = self._repository.campaign_authority_state(project_id, campaign_id)
            projection["campaign"] = _summary(state)
            projection["lifecycle_gate"] = _campaign_gate(state)
        return projection

    def inspect(
        self,
        project_id: str,
        *,
        campaign_id: str = "",
        change_id: str = "",
        view: str = "summary",
        offset: int = 0,
        limit: int = 20,
    ) -> Mapping[str, object]:
        selected_view = str(view or "summary").strip()
        if selected_view not in {
            "summary",
            "working_sheet",
            "cases",
            "obligations",
            "oracles",
            "constructibility",
            "oracle_ir",
            "attestation",
            "host_attempts",
            "evidence",
            "residuals",
            "history",
        }:
            raise InputValidationError("campaign inspect view is invalid", field="view",
                received_value=selected_view, accepted_values=("summary", "working_sheet", "cases",
                    "obligations", "oracles", "constructibility", "oracle_ir", "attestation",
                    "host_attempts", "evidence", "residuals", "history"))
        if not campaign_id:
            active = self._repository.active_campaign_authority(
                project_id, change_id=change_id
            )
            if active is None:
                return {
                    "campaign": None,
                    "lifecycle_gate": _empty_gate(project_id, change_id),
                }
            state = active
        else:
            state = self._repository.campaign_authority_state(
                project_id, campaign_id, history_limit=max(limit, 1)
            )
        gate = _campaign_gate(state)
        if selected_view == "oracle_ir":
            return {
                "campaign": _summary(state),
                "view": selected_view,
                "oracle_ir": _oracle_ir_projections(state),
                "lifecycle_gate": gate,
            }
        if selected_view in {"summary", "working_sheet", "constructibility"}:
            if selected_view == "constructibility":
                return {
                    "campaign": _summary(state),
                    "constructibility": {
                        "state": str(state.get("constructibility") or ""),
                        "residuals": list(state.get("residuals", []))[:20],
                    },
                    "lifecycle_gate": gate,
                }
            campaign = (
                _working_sheet(state)
                if selected_view == "working_sheet"
                else _summary(state)
            )
            return {"campaign": campaign, "lifecycle_gate": gate}
        key = {
            "cases": "cases",
            "obligations": "obligations",
            "oracles": "oracles",
            "attestation": "attestations",
            "host_attempts": "host_attempts",
            "evidence": "evidence",
            "residuals": "residuals",
            "history": "history",
        }[selected_view]
        values = list(
            state.get("host_execution", {}).get("attempts", []) if key == "host_attempts" else state.get(key, [])
        )
        if key == "obligations":
            values.extend(state.get("obligation_history", []))
        if key == "attestations":
            values = [
                _public_attestation_projection(item)
                for item in values
                if isinstance(item, Mapping)
            ]
        page = _page(values, offset=offset, limit=limit)
        return {
            "campaign": _summary(state),
            "view": selected_view,
            key: page["items"],
            "page": page["page"],
            "lifecycle_gate": gate,
        }

    def advance(
        self,
        project_id: str,
        *,
        campaign_id: str = "",
        change_id: str = "",
        actor: str,
        request_id: str,
        transition_budget: int = 8,
        source_revision: str = "",
    ) -> Mapping[str, object]:
        if isinstance(transition_budget, bool) or not 1 <= transition_budget <= 32:
            raise ValueError("transition_budget must be between 1 and 32")
        if not campaign_id:
            active = self._repository.active_campaign_authority(
                project_id, change_id=change_id
            )
            if active is None:
                return {
                    "campaign": None,
                    "transitions": [],
                    "lifecycle_gate": _empty_gate(project_id, change_id),
                }
            campaign_id = str(active["campaign_id"])
            state = active
        else:
            state = self._repository.campaign_authority_state(project_id, campaign_id)
        transitions: list[Mapping[str, object]] = []
        for index in range(transition_budget):
            gate = _campaign_gate(state, source_revision)
            action = gate["next_action"]
            if (
                gate["state"] == "mechanical_progress"
                and action.get("operation") == "derive_obligations"
            ):
                state = self._repository.derive_campaign_obligations(
                    project_id,
                    campaign_id,
                    actor=required_text(actor, "actor"),
                    request_id=f"{required_text(request_id, 'request_id')}:derive:{index}",
                )
                transitions.append(
                    {
                        "operation": "derive_obligations",
                        "revision": int(state["revision"]),
                    }
                )
                continue
            if (
                gate["state"] in {"execution_boundary", "environment_boundary"}
                and action.get("operation") in {"run_test_case", "rerun_test_case"}
                and self._test_provider_socket is not None
                and self._test_provider_socket.configured
            ):
                arguments = action.get("arguments")
                case_id = str(
                    (arguments.get("case_id") if isinstance(arguments, Mapping) else "")
                    or action.get("case_id")
                    or ""
                )
                provider = self._test_provider_socket.queue_operation(
                    project_id,
                    campaign_id,
                    case_id,
                    operation=TestProviderOperation.RUN,
                    actor=required_text(actor, "actor"),
                    request_id=(
                        f"{required_text(request_id, 'request_id')}:run:{case_id}:{index}"
                    ),
                    deliver=True,
                )
                transitions.append(
                    {
                        "operation": "run_test_case",
                        "case_id": case_id,
                        "provider": _provider_projection(provider),
                    }
                )
                state = self._repository.campaign_authority_state(
                    project_id, campaign_id
                )
                if provider["state"] != "provider_delivered":
                    return {
                        "campaign": _summary(state),
                        "transitions": transitions,
                        "lifecycle_gate": _campaign_gate(state),
                        "provider_boundary": _provider_projection(provider),
                    }
                next_gate = _campaign_gate(state)
                if not (
                    next_gate["state"] == "mechanical_progress"
                    and next_gate["next_action"].get("operation")
                    == "propagate_coverage"
                ):
                    return {
                        "campaign": _summary(state),
                        "transitions": transitions,
                        "lifecycle_gate": next_gate,
                    }
                continue
            if (
                gate["state"] == "mechanical_progress"
                and action.get("operation") == "propagate_coverage"
                and self._coverage_propagation is not None
            ):
                host_cases = required_host_cases(state)
                with self._repository.atomic():
                    if host_cases:
                        state = self._repository.campaign_authority_state(project_id, campaign_id)
                        current_gate = _campaign_gate(state, source_revision)
                        if current_gate["next_action"].get("operation") != "propagate_coverage":
                            return {
                                "campaign": _summary(state), "transitions": transitions,
                                "lifecycle_gate": current_gate,
                            }
                    propagation = self._coverage_propagation.propagate_campaign(
                        project_id, campaign_id, actor=required_text(actor, "actor"),
                        request_id=f"{required_text(request_id, 'request_id')}:coverage",
                    )
                    state = self._repository.record_campaign_completion(
                        project_id, campaign_id, propagation=propagation,
                        actor=required_text(actor, "actor"),
                        request_id=f"{required_text(request_id, 'request_id')}:completion",
                        observed_source_revision=source_revision if host_cases else "",
                    )
                transitions.append(
                    {"operation": "propagate_coverage", "result": propagation}
                )
                return {
                    "campaign": _summary(state),
                    "transitions": transitions,
                    "lifecycle_gate": _accepted_campaign_gate(state),
                }
            if (
                gate["state"] == "provider_boundary"
                and self._test_provider_socket is not None
                and self._test_provider_socket.configured
            ):
                provider = self._test_provider_socket.recover(
                    project_id,
                    campaign_id=campaign_id,
                    actor=required_text(actor, "actor"),
                    request_id=f"{required_text(request_id, 'request_id')}:provider:{index}",
                )
                transitions.append(
                    {
                        "operation": "deliver_test_command",
                        "provider": _provider_projection(provider),
                    }
                )
                if (
                    provider["state"] == "provider_idle"
                    and action.get("operation") == "deliver_promotion"
                ):
                    arguments = action.get("arguments")
                    if not isinstance(arguments, Mapping):
                        raise ValueError("promotion gate arguments are invalid")
                    provider = self._test_provider_socket.queue_operation(
                        project_id,
                        campaign_id,
                        str(arguments.get("case_id") or ""),
                        operation=TestProviderOperation.PROMOTE,
                        actor=required_text(actor, "actor"),
                        request_id=(
                            f"{required_text(request_id, 'request_id')}:"
                            f"promotion:{index}"
                        ),
                        deliver=True,
                        regression_obligation=bool(
                            arguments.get("regression_obligation", False)
                        ),
                        promotion_evidence_id=str(arguments.get("evidence_id") or ""),
                    )
                    transitions.append(
                        {
                            "operation": "recover_promotion",
                            "provider": _provider_projection(provider),
                        }
                    )
                state = self._repository.campaign_authority_state(
                    project_id, campaign_id
                )
                if provider["state"] != "provider_delivered":
                    return {
                        "campaign": _summary(state),
                        "transitions": transitions,
                        "lifecycle_gate": _campaign_gate(state),
                        "provider_boundary": _provider_projection(provider),
                    }
                continue
            return {
                "campaign": _summary(state),
                "transitions": transitions,
                "lifecycle_gate": gate,
            }
        return {
            "campaign": _summary(state),
            "transitions": transitions,
            "lifecycle_gate": _campaign_gate(state),
            "transition_budget_exhausted": True,
        }

    @staticmethod
    def _mutation_projection(
        operation: str,
        before: Mapping[str, object] | None,
        state: Mapping[str, object],
    ) -> Mapping[str, object]:
        before_revision = int(before.get("revision", 0)) if before else 0
        return {
            "campaign": _summary(state),
            "semantic_delta": {
                "operation": operation,
                "from_revision": before_revision,
                "to_revision": int(state.get("revision", 0)),
                "changed": before is None
                or str(before.get("fingerprint") or "")
                != str(state.get("fingerprint") or ""),
                "replayed": bool(state.get("replayed", False)),
            },
            "lifecycle_gate": _campaign_gate(state),
        }


def _summary(state: Mapping[str, object]) -> dict[str, object]:
    exception = state.get("exception")
    historical_exception = isinstance(exception, Mapping) and exception.get("current") is False
    return {
        "campaign_id": str(state.get("campaign_id") or ""),
        "change_id": str(state.get("change_id") or ""),
        "title": str(state.get("title") or ""),
        "status": str(state.get("status") or ""),
        "qualification": "historical_on_original_basis" if historical_exception else str(state.get("qualification") or ""),
        "constructibility": str(state.get("constructibility") or ""),
        "revision": int(state.get("revision") or 0),
        "fingerprint": str(state.get("fingerprint") or ""),
        "case_count": len(state.get("cases", [])),
        "obligation_count": len(state.get("obligations", [])),
        "oracle_count": len(state.get("oracles", [])),
        "attestation_count": len(state.get("attestations", [])),
        "evidence_count": len(state.get("evidence", [])),
        **({"execution_lane": state["scope"]["execution_lane"]}
           if state.get("scope", {}).get("execution_lane") else {}),
        **({"host_source_revision": state["host_execution"]["declared_source_revision"]}
           if state.get("host_execution") else {}),
        "promotion_authorization_count": len(state.get("promotion_authorizations", [])),
        "completed": bool(
            isinstance(state.get("completion"), Mapping)
            and state["completion"].get("current")
        ),
        "residual_count": len(state.get("residuals", [])),
        "exception": dict(exception) if isinstance(exception, Mapping) else None,
    }


def _working_sheet(state: Mapping[str, object]) -> dict[str, object]:
    return {
        **_summary(state),
        "scope": dict(state.get("scope") or {}),
        "cases": list(state.get("cases", []))[:20],
        "obligations": list(state.get("obligations", []))[:20],
        "oracles": list(state.get("oracles", []))[:10],
        "attestations": [
            _public_attestation_projection(item)
            for item in list(state.get("attestations", []))[:10]
            if isinstance(item, Mapping)
        ],
        "evidence": list(state.get("evidence", []))[:10],
        "promotion_authorizations": list(state.get("promotion_authorizations", []))[
            :10
        ],
        "completion": dict(state["completion"])
        if isinstance(state.get("completion"), Mapping)
        else None,
        "residuals": list(state.get("residuals", []))[:20],
    }


def _question_action(state: Mapping[str, object], question: Mapping[str, object]) -> dict[str, object]:
    return {"tool": "fow_campaign_author", "operation": "answer_question", "arguments": {
        "campaign_id": state["campaign_id"], "oracle_id": question["oracle_id"],
        "question_id": question["question_id"], "expected_fingerprint": state["fingerprint"],
    }}


def _oracle_ir_projections(state: Mapping[str, object]) -> list[dict[str, object]]:
    oracles = {item["oracle_id"]: item for item in state.get("oracles", [])}
    cases = {item["case_id"]: item for item in state.get("cases", [])}
    selected = current_oracle_question(state)
    source_pending = selected is not None and selected["scope"] == "source"
    gate = _campaign_gate(state)
    result = []
    for binding in state.get("oracle_bindings", []):
        oracle = oracles.get(binding["oracle_id"])
        if oracle is None:
            continue
        projection = compile_oracle_ir(oracle)
        value = dict(projection.as_payload())
        value["case_id"] = binding["case_id"]
        lane = campaign_case_lane(state.get("scope", {}), cases.get(binding["case_id"], {}))
        value["refinement_applicable"] = lane == "provider" and oracle_ir_refinement_applicable(oracle)
        # Residuals describe this Oracle; only the shared current selection is
        # actionable. Never suggest a different local question to a global writer.
        value["next_question"] = None
        exact_binding = (oracle.get("current") and oracle["revision"] == binding["oracle_revision"]
                         and oracle["fingerprint"] == binding["oracle_fingerprint"])
        if source_pending or oracle_source_repair(state) or not exact_binding or not value["refinement_applicable"]:
            value["next_action"] = dict(gate["next_action"])
        elif projection.constructible:
            value["next_action"] = {"tool": "fow_campaign_author", "operation": "authorize_materialization",
                "arguments": {"case_id": binding["case_id"]}}
        elif selected is not None and selected["scope"] == "oracle_ir":
            if selected["oracle_id"] == oracle["oracle_id"] and selected["case_id"] == binding["case_id"]:
                value["next_question"] = dict(selected)
            value["next_action"] = _question_action(state, selected)
        else:
            value["next_action"] = dict(gate["next_action"])
        result.append(value)
    return result[:20]


_CAMPAIGN_WORK_PHASES = (
    ("scope", "Select a current governed change and scope.", {"start", "edit_scope"}),
    ("obligations", "Derive and classify proof obligations for the selected scope.",
     {"derive_obligations", "decide_obligation"}),
    ("cases", "Author required cases and bind applicable obligations.", {"add_case", "bind_obligation"}),
    ("oracle", "Author and complete current source Oracles for the required cases.",
     {"author_oracle", "answer_question", "oracles"}),
    ("attestation", "Bind and validate exact test source or authorized materialization.",
     {"attest_source", "authorize_materialization", "deliver_test_command", "issue_host_check"}),
    ("evidence", "Run current attested cases and inspect their observed outcomes.",
     {"run_test_case", "rerun_test_case", "report_host_result"}),
    ("promotion", "Authorize and deliver promotion for current passed evidence.",
     {"authorize_promotion", "deliver_promotion"}),
    ("coverage", "Reconcile accepted coverage and record campaign completion.", {"propagate_coverage"}),
)


def _campaign_remaining_work(
    gate: Mapping[str, object], questions: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    action = gate["next_action"]
    phase = next((index for index, (_, _, operations) in enumerate(_CAMPAIGN_WORK_PHASES)
                  if action["operation"] in operations), None)
    remaining: dict[str, object] = {"conditional_phases": []}
    if gate["state"] in {"accepted", "inactive"}:
        return remaining
    remaining["effort"] = "undetermined"
    if action["tool"] == "fow_packet_author":
        remaining["current_phase"] = "product_correction"
    elif phase is not None:
        name, description, _ = _CAMPAIGN_WORK_PHASES[phase]
        remaining["current_phase"] = name
        remaining["current_phase_requirement"] = description
        remaining["conditional_phases"] = [
            {"phase": later_name, "requirement": later_description}
            for later_name, later_description, _ in _CAMPAIGN_WORK_PHASES[phase + 1:]
        ]
    if questions:
        selected = questions[0]
        same_oracle = [question for question in questions
                       if question["oracle_id"] == selected["oracle_id"]
                       and question["oracle_revision"] == selected["oracle_revision"]]
        remaining["oracle_questions"] = {
            **{key: selected[key] for key in ("case_id", "oracle_id", "oracle_revision", "scope")},
            "current_question_id": selected["question_id"],
            "ordered_missing_fields": [
                {key: question[key] for key in ("question_id", "field_name")} for question in same_oracle
            ],
            "other_pending_questions": len(questions) - len(same_oracle),
        }
    return remaining


def _campaign_gate(state: Mapping[str, object], source_revision: str = "") -> dict[str, object]:
    active = state.get("qualification") == "current" and state.get("status") not in {"cancelled", "accepted_exception"}
    questions = applicable_oracle_questions(state) if active else []
    gate = _campaign_lifecycle_gate(state, questions[0] if questions else None, source_revision)
    return {**gate, "work_remaining": _campaign_remaining_work(gate, questions)}


def _campaign_lifecycle_gate(
    state: Mapping[str, object], current_question: Mapping[str, object] | None,
    source_revision: str = "",
) -> dict[str, object]:
    campaign_id = str(state.get("campaign_id") or "")
    qualification = str(state.get("qualification") or "")
    if qualification != "current":
        return _legacy_campaign_gate(state)
    constructibility = str(state.get("constructibility") or "draft")
    obligations = list(state.get("obligations", []))
    cases = list(state.get("cases", []))
    attestations = list(state.get("attestations", []))
    decision_required: dict[str, object] | None = None
    allowed: list[Mapping[str, object]] = []
    effect = ""
    gate_state = "semantic_decision"
    next_action: dict[str, object]
    status = str(state.get("status") or "")
    applicability = state.get("obligation_applicability") or {}
    source_repair = oracle_source_repair(state)
    if status in {"cancelled", "accepted_exception"}:
        gate_state = "inactive"
        next_action = {"tool": "fow_campaign_inspect", "operation": "summary"}
        exception = state.get("exception")
        if isinstance(exception, Mapping) and exception.get("current") is False:
            effect = "The exception belongs to its original scope. Assess current scope through an ordinary campaign."
    elif constructibility == CampaignConstructibility.NEEDS_OBLIGATIONS.value:
        scope = state.get("scope", {})
        undecided = [
            item
            for item in obligations
            if item.get("decision") in {"unclassified", "investigate"}
            or (item.get("decision") in OMITTED_CAMPAIGN_DECISIONS
                and obligation_requires_independent_proof(scope, item))
        ]
        if not obligations or applicability.get("current") is False:
            gate_state = "mechanical_progress"
            next_action = {
                "tool": "fow_campaign_advance",
                "operation": "derive_obligations",
            }
            effect = ("refresh proof obligations for changed scope or sources"
                      if obligations else "derive current proof-obligation candidates without accepting them")
        else:
            item = undecided[0]
            decision_required = {
                "kind": "obligation_classification",
                "obligation_id": item["obligation_id"],
                "statement": item["statement"],
                "source": {
                    "kind": item["source_kind"],
                    "ref": item["source_ref"],
                    "revision": item["source_revision"],
                },
            }
            choices = (
                ("required", "investigate") if obligation_requires_independent_proof(scope, item)
                else ("required", "out_of_scope", "duplicate", "investigate", "waived")
            )
            allowed = [
                {"value": value, "requires": ["rationale"]}
                for value in choices
            ]
            effect = "persist one explicit obligation decision"
            next_action = {
                "tool": "fow_campaign_author",
                "operation": "decide_obligation",
                "arguments": {"obligation_id": item["obligation_id"]},
            }
    elif constructibility == CampaignConstructibility.NEEDS_CASES.value:
        residual = next(iter(state.get("residuals", [])), {})
        operation = str(
            (residual.get("next_action") or {}).get("operation") or "add_case"
        )
        next_action = {"tool": "fow_campaign_author", "operation": operation}
        decision_required = {
            "kind": operation,
            "subject_ref": str(residual.get("subject_ref") or ""),
            "missing_fact": str(residual.get("missing_fact") or ""),
        }
        effect = "add or bind one falsifiable required case"
    elif constructibility == CampaignConstructibility.NEEDS_ORACLE.value or source_repair:
        residual = next(iter(state.get("residuals", [])), {})
        operation = str(
            (residual.get("next_action") or {}).get("operation") or "author_oracle"
        )
        decision_required = (
            {"kind": "oracle_answer", **dict(current_question)}
            if current_question is not None
            else {
                "kind": operation,
                "subject_ref": str(residual.get("subject_ref") or ""),
                "missing_fact": str(residual.get("missing_fact") or ""),
            }
        )
        allowed = [
            {"value": value, "requires": ["answer", "provenance"]}
            for value in (
                "grounded_fact",
                "accepted_decision",
                "derived_hypothesis",
                "unknown",
                "waived",
            )
        ]
        effect = "author or complete one immutable behavioral-oracle revision"
        if current_question is not None:
            next_action = _question_action(state, current_question)
        elif source_repair:
            arguments = {key: source_repair[key] for key in ("case_id", "oracle_id") if key in source_repair}
            next_action = {"tool": "fow_campaign_author", "operation": "author_oracle", "arguments": arguments}
            decision_required = {"kind": "oracle_source_repair", **source_repair}
        else:
            next_action = {"tool": "fow_campaign_inspect", "operation": "oracles",
                "arguments": {"campaign_id": campaign_id, "view": "oracles"}}
    elif (host_case := next_host_case(state, source_revision)) is not None:
        gate_state, next_action, decision_required, effect = _host_execution_boundary(
            state, host_case, source_revision,
        )
    else:
        required_cases = [
            item for item in cases if bool(item.get("required"))
            and campaign_case_lane(state.get("scope", {}), item) == "provider"
        ]
        oracle_by_case = {
            str(binding.get("case_id") or ""): binding
            for binding in state.get("oracle_bindings", [])
            if isinstance(binding, Mapping)
        }
        latest_attestation: dict[str, Mapping[str, object]] = {}
        for item in attestations:
            if not isinstance(item, Mapping):
                continue
            case_ref = str(item.get("case_id") or "")
            current = latest_attestation.get(case_ref)
            if current is None or int(item.get("ordinal") or 0) > int(
                current.get("ordinal") or 0
            ):
                latest_attestation[case_ref] = item
        current_attestations: dict[str, Mapping[str, object]] = {}
        for case in required_cases:
            case_ref = str(case.get("case_id") or "")
            item = latest_attestation.get(case_ref)
            oracle_binding = oracle_by_case.get(case_ref)
            if (
                item is not None
                and oracle_binding is not None
                and str(item.get("oracle_id") or "")
                == str(oracle_binding.get("oracle_id") or "")
                and int(item.get("oracle_revision") or 0)
                == int(oracle_binding.get("oracle_revision") or 0)
            ):
                current_attestations[case_ref] = item
        missing_attestation = next(
            (
                case
                for case in required_cases
                if str(case.get("case_id") or "") not in current_attestations
                or str(
                    current_attestations[str(case.get("case_id") or "")].get("state")
                    or ""
                )
                in {"unattested", "invalidated", "rejected"}
            ),
            None,
        )
        pending_attestation = next(
            (
                item
                for item in current_attestations.values()
                if str(item.get("state") or "") == "pending_technical_validation"
            ),
            None,
        )
        if missing_attestation is not None:
            case_ref = str(missing_attestation.get("case_id") or "")
            next_action, decision_required, effect = _attestation_successor_gate(
                case_ref,
                current_attestations.get(case_ref),
                known_case_choices=[
                    str(item.get("case_id") or "") for item in required_cases
                ],
            )
        elif pending_attestation is not None:
            gate_state = "provider_boundary"
            next_action = {
                "tool": "fow_campaign_advance",
                "operation": "deliver_test_command",
                "arguments": {"case_id": pending_attestation.get("case_id")},
            }
            effect = "materialize and validate exact pre-authorized source through the provider"
        else:
            completion = state.get("completion")
            if isinstance(completion, Mapping) and bool(completion.get("current")):
                return _accepted_campaign_gate(state)
            run_evidence_by_case: dict[str, Mapping[str, object]] = {}
            promotion_evidence_by_case: dict[str, Mapping[str, object]] = {}
            for item in state.get("evidence", []):
                if not isinstance(item, Mapping) or not bool(item.get("current")):
                    continue
                case_ref = str(item.get("case_id") or "")
                operation = str(item.get("operation") or "")
                if operation == "run":
                    run_evidence_by_case.setdefault(case_ref, item)
                elif (
                    operation == "promote"
                    and bool(item.get("authoritative"))
                    and str(item.get("acceptance_disposition") or "") == "passed"
                ):
                    promotion_evidence_by_case.setdefault(case_ref, item)
            unresolved_case = next(
                (
                    case
                    for case in required_cases
                    if str(case.get("case_id") or "") not in run_evidence_by_case
                    or str(
                        run_evidence_by_case[str(case.get("case_id") or "")].get(
                            "acceptance_disposition"
                        )
                        or ""
                    )
                    != "passed"
                ),
                None,
            )
            if unresolved_case is not None:
                case_ref = str((unresolved_case or {}).get("case_id") or "")
                evidence = run_evidence_by_case.get(case_ref)
                disposition = str((evidence or {}).get("acceptance_disposition") or "")
                if disposition == "test_invalid":
                    next_action, decision_required, effect = (
                        _attestation_successor_gate(
                            case_ref,
                            current_attestations.get(case_ref),
                            known_case_choices=[
                                str(item.get("case_id") or "")
                                for item in required_cases
                            ],
                            evidence_id=str(
                                (evidence or {}).get("evidence_id") or ""
                            ),
                        )
                    )
                elif disposition == "product_failed":
                    decision_required = {
                        "kind": "product_failure_route",
                        "case_id": case_ref,
                        "evidence_id": (evidence or {}).get("evidence_id"),
                    }
                    allowed = [
                        {"value": "originating_packet", "requires": []},
                        {"value": "remediation_packet", "requires": []},
                        {"value": "successor_change", "requires": ["rationale"]},
                        {"value": "scope_decision", "requires": ["rationale"]},
                    ]
                    next_action = {
                        "tool": "fow_packet_author",
                        "operation": "start",
                    }
                    effect = "route the authoritative product failure without rewriting evidence"
                elif disposition == "environment_failed":
                    gate_state = "environment_boundary"
                    next_action = {
                        "tool": "fow_campaign_advance",
                        "operation": "rerun_test_case",
                        "arguments": {"case_id": case_ref},
                    }
                    effect = (
                        "restore the declared execution environment before retrying"
                    )
                else:
                    gate_state = "execution_boundary"
                    operation = (
                        "rerun_test_case"
                        if disposition in {"flaky", "incomplete"}
                        else "run_test_case"
                    )
                    next_action = {
                        "tool": "fow_campaign_advance",
                        "operation": operation,
                        "arguments": {"case_id": case_ref},
                    }
                    effect = "execute the current attested materialization"
            else:
                unpromoted_case = next(
                    (
                        case
                        for case in required_cases
                        if (
                            str(case.get("case_id") or "")
                            not in promotion_evidence_by_case
                            or str(
                                promotion_evidence_by_case[
                                    str(case.get("case_id") or "")
                                ].get("promotion_evidence_id")
                                or ""
                            )
                            != str(
                                run_evidence_by_case[
                                    str(case.get("case_id") or "")
                                ].get("evidence_id")
                                or ""
                            )
                        )
                    ),
                    None,
                )
                if unpromoted_case is None and required_host_cases(state) and not source_revision:
                    gate_state = "source_boundary"
                    next_action = {
                        "tool": "fow_campaign_advance", "operation": "advance",
                        "arguments": {"campaign_id": campaign_id},
                    }
                    decision_required = {"kind": "observe_host_source", "required_inputs": ["source_revision"]}
                    effect = "supply the repository source revision observed for coverage reconciliation"
                elif unpromoted_case is None:
                    gate_state = "mechanical_progress"
                    next_action = {
                        "tool": "fow_campaign_advance",
                        "operation": "propagate_coverage",
                    }
                    effect = "propagate only current accepted obligation coverage"
                else:
                    case_ref = str(unpromoted_case.get("case_id") or "")
                    evidence = run_evidence_by_case[case_ref]
                    authorization = next(
                        (
                            item
                            for item in state.get("promotion_authorizations", [])
                            if isinstance(item, Mapping)
                            and bool(item.get("current"))
                            and str(item.get("case_id") or "") == case_ref
                            and str(item.get("evidence_id") or "")
                            == str(evidence.get("evidence_id") or "")
                        ),
                        None,
                    )
                    if authorization is None:
                        decision_required = {
                            "kind": "test_promotion_authority",
                            "case_id": case_ref,
                            "evidence_id": evidence.get("evidence_id"),
                            "provider_test_ref": evidence.get("provider_test_ref"),
                        }
                        allowed = [
                            {
                                "value": "authorize_promotion",
                                "requires": ["authority_reference"],
                            }
                        ]
                        next_action = {
                            "tool": "fow_campaign_author",
                            "operation": "authorize_promotion",
                            "arguments": {
                                "case_id": case_ref,
                                "evidence_id": evidence.get("evidence_id"),
                            },
                        }
                        effect = "authorize promotion only from current attested passed evidence"
                    else:
                        gate_state = "provider_boundary"
                        next_action = {
                            "tool": "fow_campaign_advance",
                            "operation": "deliver_promotion",
                            "arguments": {
                                "case_id": case_ref,
                                "evidence_id": evidence.get("evidence_id"),
                                "regression_obligation": bool(
                                    authorization.get("regression_obligation", False)
                                ),
                            },
                        }
                        effect = "deliver the durable authorized promotion command"
    dependency = {
        "campaign_id": campaign_id,
        "revision": int(state.get("revision") or 0),
        "fingerprint": str(state.get("fingerprint") or ""),
        "constructibility": constructibility,
        "next_operation": next_action["operation"],
    }
    return {
        "contract": "flow.lifecycle_gate.v1",
        "subject": "campaign",
        "state": gate_state,
        "lifecycle_state": constructibility,
        "dependency_fingerprint": semantic_fingerprint(dependency),
        "known_facts": [
            {
                "label": "campaign scope",
                "fact": f"{len(state.get('scope', {}).get('requirement_ids', []))} requirements; "
                f"{len(cases)} cases; {len(obligations)} obligations",
                "source": "Flow campaign ledger",
                "freshness": "current",
            }
        ],
        "decision_required": decision_required,
        "allowed_responses": allowed,
        "semantic_effect": effect,
        "next_action": next_action,
    }


def _host_execution_boundary(state, case, observed_source_revision):
    case_id = case["case_id"]
    campaign_id = state["campaign_id"]
    execution = state.get("host_execution", {})
    declared_source = execution.get("declared_source_revision", "")
    source_changed = bool(observed_source_revision and declared_source and observed_source_revision != declared_source)
    attempt = execution.get("current_attempts", {}).get(case_id)
    receipt = execution.get("current_receipts", {}).get(case_id)
    blockers = independent_host_obligations(state, case_id)
    if blockers or not host_case_supported(case):
        cause = "independent_proof_required" if blockers else "case_not_host_eligible"
        return (
            "independent_proof_boundary",
            {"tool": "fow_campaign_author", "operation": "edit_case",
             "arguments": {"campaign_id": campaign_id, "case_id": case_id}},
            {"kind": cause, "case_id": case_id, "obligation_ids": blockers,
             "required_inputs": ["case"]},
            "supply an eligible case and select its required proof lane before execution",
        )
    if receipt and not source_changed and receipt["outcome"] == "product_failed":
        return (
            "product_failure_boundary",
            {"tool": "fow_assurance", "operation": "record_finding",
             "arguments": {"change_id": state["change_id"]}},
            {"kind": "product_failure_route", "case_id": case_id,
             "evidence_id": receipt["receipt_id"], "observation": receipt["observation"]},
            "record and route the observed product failure, then verify the corrected source",
        )
    if attempt and not source_changed and not receipt:
        return (
            "host_execution_boundary",
            {"tool": "fow_campaign_author", "operation": "report_host_result",
             "arguments": {"campaign_id": campaign_id, "host_result": {
                 "attempt_id": attempt["attempt_id"], "source_revision": attempt["source_revision"],
             }}},
            {"kind": "run_host_check", "case_id": case_id, "attempt_id": attempt["attempt_id"],
             "check_reference": attempt["check_reference"], "execution_profile": attempt["execution_profile"],
             "source_revision": attempt["source_revision"], "check": attempt["check"],
             "required_inputs": ["outcome", "evidence_reference", "observation"]},
            "run the issued check using authorized host tools and report its actual result",
        )
    last_outcome = receipt.get("outcome") if receipt and not source_changed else ""
    cause = {
        "test_invalid": "correct the invalid check, then issue its replacement",
        "environment_failed": "restore the declared execution environment before issuing a retry",
    }.get(last_outcome, "issue the current case check using the observed source and execution profile")
    decision = {
        "kind": "issue_host_check", "case_id": case_id,
        "required_inputs": ["source_revision", "execution_profile", "check_reference"],
    }
    if source_changed:
        decision |= {"declared_source_revision": declared_source, "observed_source_revision": observed_source_revision}
        cause = "source changed since the previous attempts; issue a check for the observed revision"
    if receipt:
        decision |= {"evidence_id": receipt["receipt_id"], "last_outcome": receipt["outcome"],
                     "observation": receipt["observation"]}
    return (
        "host_check_boundary",
        {"tool": "fow_campaign_author", "operation": "issue_host_check",
         "arguments": {"campaign_id": campaign_id, "case_id": case_id,
                       "expected_fingerprint": state["fingerprint"]}},
        decision, cause,
    )


def _attestation_successor_gate(
    case_id: str,
    attestation: Mapping[str, object] | None,
    *,
    known_case_choices: Sequence[str],
    evidence_id: str = "",
) -> tuple[dict[str, object], dict[str, object], str]:
    if not evidence_id and attestation is not None and source_attestation_retry_eligible(attestation):
        attestation_id = str(attestation["attestation_id"])
        capability = attestation.get("requested_capability") or {}
        arguments = {"case_id": case_id, "requested_capability": capability}
        return (
            {"tool": "fow_campaign_author", "operation": "attest_source", "arguments": arguments},
            {
                "kind": "source_attestation_technical_retry",
                "case_id": case_id,
                "attestation_id": attestation_id,
                "reason": f"A finished technical attempt invalidated {attestation_id}. The source authority is unchanged.",
                "known_case_choices": list(known_case_choices),
            },
            "submit one new request now with the exact same source_files, harness and capability. "
            "The new provider attempt checks readiness. Inspect its result before any further retry",
        )
    if deterministic_materialization_retry_eligible(attestation):
        raw_capability = attestation.get("requested_capability")
        capability = (
            {
                key: raw_capability[key]
                for key in (
                    "language",
                    "framework",
                    "artifact_scope_preference",
                )
                if key in raw_capability
            }
            if isinstance(raw_capability, Mapping)
            else {}
        )
        arguments: dict[str, object] = {
            "case_id": case_id,
            "requested_capability": capability,
        }
        decision: dict[str, object] = {
            "kind": "deterministic_materialization_retry_authorization",
            "case_id": case_id,
            "requested_capability": capability,
            "known_case_choices": list(known_case_choices),
        }
        if evidence_id:
            decision["evidence_id"] = evidence_id
        return (
            {
                "tool": "fow_campaign_author",
                "operation": "authorize_materialization",
                "arguments": arguments,
            },
            decision,
            "authorize one deterministic provider retry over the current oracle",
        )

    decision = {
        "kind": "test_source_correction"
        if evidence_id
        else "materialization_attestation_intent",
        "case_id": case_id,
        "known_case_choices": list(known_case_choices),
    }
    if evidence_id:
        decision["evidence_id"] = evidence_id
    return (
        {
            "tool": "fow_campaign_author",
            "operation": "attest_source",
            "arguments": {"case_id": case_id},
        },
        decision,
        "send corrected test source inline for the same Oracle and leave the product checkout unchanged"
        if evidence_id
        else "send test source inline to a distinct provider-managed destination and leave the product checkout unchanged",
    )


def _legacy_campaign_gate(state: Mapping[str, object]) -> dict[str, object]:
    campaign_id = str(state.get("campaign_id") or "")
    change_id = str(state.get("change_id") or "")
    return {
        "contract": "flow.lifecycle_gate.v1",
        "subject": "campaign",
        "state": "semantic_decision",
        "lifecycle_state": "legacy_unqualified",
        "dependency_fingerprint": semantic_fingerprint(
            {
                "campaign_id": campaign_id,
                "change_id": change_id,
                "qualification": "legacy_unqualified",
            }
        ),
        "known_facts": [
            {
                "label": "campaign qualification",
                "fact": "historical campaign facts do not prove current oracle and attestation authority",
                "source": "Flow campaign ledger",
                "freshness": "historical",
            }
        ],
        "decision_required": {
            "kind": "campaign_qualification",
            "change_id": change_id,
        },
        "allowed_responses": [
            {
                "value": "start_successor_campaign",
                "requires": ["title", "scope.change_id"],
            }
        ],
        "semantic_effect": "retain historical evidence without manufacturing current authority",
        "next_action": {
            "tool": "fow_campaign_author",
            "operation": "start",
            "arguments": {"scope": {"change_id": change_id}},
        },
    }


def _accepted_campaign_gate(state: Mapping[str, object]) -> dict[str, object]:
    campaign_id = str(state.get("campaign_id") or "")
    return {
        "contract": "flow.lifecycle_gate.v1",
        "subject": "campaign",
        "state": "accepted",
        "lifecycle_state": "passed",
        "dependency_fingerprint": semantic_fingerprint(
            {
                "campaign_id": campaign_id,
                "revision": int(state.get("revision") or 0),
                "status": "passed",
            }
        ),
        "known_facts": [
            {
                "label": "campaign evidence",
                "fact": (
                    "all required cases have eligible passed evidence; host receipts retain declared provenance"
                    if required_host_cases(state) else "all required cases have current attested passed evidence"
                ),
                "source": "Flow campaign ledger",
                "freshness": "current",
            }
        ],
        "decision_required": None,
        "allowed_responses": [],
        "semantic_effect": "campaign evidence is accepted and coverage was reconciled",
        "next_action": {"tool": "fow_campaign_inspect", "operation": "summary"},
        "work_remaining": {"conditional_phases": []},
    }


def _empty_gate(project_id: str, change_id: str) -> dict[str, object]:
    gate = {
        "contract": "flow.lifecycle_gate.v1",
        "subject": "campaign",
        "state": "semantic_decision",
        "lifecycle_state": "missing",
        "dependency_fingerprint": semantic_fingerprint(
            {"project_id": project_id, "change_id": change_id, "state": "missing"}
        ),
        "known_facts": [],
        "decision_required": {"kind": "campaign_scope"},
        "allowed_responses": [],
        "semantic_effect": "create one qualified campaign from current scope",
        "next_action": {"tool": "fow_campaign_author", "operation": "start"},
    }
    return {**gate, "work_remaining": _campaign_remaining_work(gate)}


def _page(values: Sequence[object], *, offset: int, limit: int) -> dict[str, object]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    total = len(values)
    end = min(total, offset + limit)
    return {
        "items": list(values[offset:end]),
        "page": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": end < total,
            "next_offset": end if end < total else None,
        },
    }


def _provider_projection(value: Mapping[str, object]) -> dict[str, object]:
    """Expose provider progress without echoing durable source or oracle payloads."""

    projection = {
        key: value[key] for key in ("state", "reason", "next_action") if key in value
    }
    outbox = value.get("outbox")
    if isinstance(outbox, Mapping):
        projection["outbox"] = {
            key: outbox[key]
            for key in (
                "command_id",
                "campaign_id",
                "case_id",
                "provider_kind",
                "operation",
                "delivery_fingerprint",
                "state",
                "attempts",
                "last_error",
                "receipt_id",
                "retry_of_command_id",
                "retry_rationale",
            )
            if key in outbox
        }
    receipt = value.get("receipt")
    if isinstance(receipt, Mapping):
        projection["receipt"] = {
            key: receipt[key]
            for key in (
                "receipt_id",
                "command_id",
                "campaign_id",
                "case_id",
                "provider_kind",
                "provider_event_seq",
                "fingerprint",
                "evidence_disposition",
                "attestation_state",
                "observed_at",
            )
            if key in receipt
        }
    attestation = value.get("attestation")
    if isinstance(attestation, Mapping):
        projection["attestation"] = _public_attestation_projection(attestation)
    deliveries = value.get("deliveries")
    if isinstance(deliveries, Sequence) and not isinstance(deliveries, str | bytes):
        projection["deliveries"] = [
            _provider_projection(item)
            for item in deliveries[:16]
            if isinstance(item, Mapping)
        ]
        projection["deliveries_truncated"] = len(deliveries) > 16
    return projection


def _public_attestation_projection(
    attestation: Mapping[str, object],
) -> dict[str, object]:
    """Project lifecycle state without exposing provider authority payloads."""

    return {
        key: attestation[key]
        for key in (
            "attestation_id",
            "campaign_id",
            "case_id",
            "oracle_id",
            "oracle_revision",
            "oracle_fingerprint",
            "materialization_mode",
            "authority_input_fingerprint",
            "source_manifest_digest",
            "oracle_ir_contract_version",
            "oracle_ir_operator_profile",
            "oracle_ir_fingerprint",
            "requested_capability",
            "state",
            "provider_materialization_ref",
            "representation_fingerprint",
            "basis",
        )
        if key in attestation
    }


def qualified_campaign_is_accepted(projection: Mapping[str, object]) -> bool:
    campaign = projection.get("campaign")
    gate = projection.get("lifecycle_gate")
    if not isinstance(campaign, Mapping) or not isinstance(gate, Mapping):
        return False
    status = str(campaign.get("status") or "")
    gate_state = str(gate.get("state") or "")
    return gate_state == "accepted" or (
        status == "accepted_exception" and gate_state == "inactive"
        and campaign.get("qualification") != "historical_on_original_basis"
    )


__all__ = ["CampaignAuthorityService", "qualified_campaign_is_accepted"]
