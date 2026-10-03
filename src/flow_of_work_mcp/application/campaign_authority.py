"""Canonical campaign authoring, inspection and deterministic advancement."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

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
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.oracle_ir_projection import compile_oracle_ir
from flow_of_work_mcp.core.errors import AssuranceBlockedError
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
        before = self._repository.campaign_authority_state(project_id, campaign_id)
        state = self._repository.create_campaign_attestation_intent(
            project_id,
            campaign_id,
            case_id,
            source_files=source_files,
            harness=harness,
            requested_capability=requested_capability,
            authority_reference=authority_reference,
            actor=required_text(actor, "actor"),
            request_id=required_text(request_id, "request_id"),
        )
        projection = dict(self._mutation_projection("attest_source", before, state))
        if self._test_provider_socket is not None:
            projection["provider"] = _provider_projection(
                self._test_provider_socket.queue_materialization(
                    project_id,
                    campaign_id,
                    case_id,
                    source_files=source_files,
                    actor=actor,
                    request_id=f"{request_id}:provider",
                    deliver=False,
                )
            )
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
            "evidence",
            "residuals",
            "history",
        }:
            raise ValueError("campaign inspect view is invalid")
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
            "evidence": "evidence",
            "residuals": "residuals",
            "history": "history",
        }[selected_view]
        values = list(state.get(key, []))
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
            gate = _campaign_gate(state)
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
                propagation = self._coverage_propagation.propagate_campaign(
                    project_id,
                    campaign_id,
                    actor=required_text(actor, "actor"),
                    request_id=(f"{required_text(request_id, 'request_id')}:coverage"),
                )
                transitions.append(
                    {"operation": "propagate_coverage", "result": propagation}
                )
                state = self._repository.record_campaign_completion(
                    project_id,
                    campaign_id,
                    propagation=propagation,
                    actor=required_text(actor, "actor"),
                    request_id=(
                        f"{required_text(request_id, 'request_id')}:completion"
                    ),
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
    return {
        "campaign_id": str(state.get("campaign_id") or ""),
        "change_id": str(state.get("change_id") or ""),
        "title": str(state.get("title") or ""),
        "status": str(state.get("status") or ""),
        "qualification": str(state.get("qualification") or ""),
        "constructibility": str(state.get("constructibility") or ""),
        "revision": int(state.get("revision") or 0),
        "fingerprint": str(state.get("fingerprint") or ""),
        "case_count": len(state.get("cases", [])),
        "obligation_count": len(state.get("obligations", [])),
        "oracle_count": len(state.get("oracles", [])),
        "attestation_count": len(state.get("attestations", [])),
        "evidence_count": len(state.get("evidence", [])),
        "promotion_authorization_count": len(state.get("promotion_authorizations", [])),
        "completed": bool(
            isinstance(state.get("completion"), Mapping)
            and state["completion"].get("current")
        ),
        "residual_count": len(state.get("residuals", [])),
        "exception": dict(state["exception"])
        if isinstance(state.get("exception"), Mapping)
        else None,
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


def _oracle_ir_projections(state: Mapping[str, object]) -> list[dict[str, object]]:
    oracles = {
        str(item.get("oracle_id") or ""): item
        for item in state.get("oracles", [])
        if isinstance(item, Mapping)
    }
    result: list[dict[str, object]] = []
    for binding in state.get("oracle_bindings", []):
        if not isinstance(binding, Mapping):
            continue
        oracle = oracles.get(str(binding.get("oracle_id") or ""))
        if oracle is None:
            continue
        projection = compile_oracle_ir(oracle)
        value = dict(projection.as_payload())
        value["case_id"] = str(binding.get("case_id") or "")
        current_question = projection.next_residual
        ir_questions = {
            str(item.get("question_id") or ""): item
            for item in oracle.get("oracle_ir_questions", [])
            if isinstance(item, Mapping)
        }
        if projection.constructible:
            value["next_action"] = {
                "tool": "fow_campaign_author",
                "operation": "authorize_materialization",
                "arguments": {"case_id": value["case_id"]},
            }
        elif (
            current_question is not None
            and current_question.question_id in ir_questions
        ):
            value["next_action"] = {
                "tool": "fow_campaign_author",
                "operation": "answer_question",
                "arguments": {
                    "oracle_id": projection.oracle_id,
                    "question_id": current_question.question_id,
                },
            }
        else:
            value["next_action"] = {
                "tool": "fow_campaign_author",
                "operation": "author_oracle",
                "arguments": {
                    "case_id": value["case_id"],
                    "oracle_id": projection.oracle_id,
                },
            }
        result.append(value)
    return result[:20]


def _campaign_gate(state: Mapping[str, object]) -> dict[str, object]:
    campaign_id = str(state.get("campaign_id") or "")
    qualification = str(state.get("qualification") or "")
    if qualification != "current":
        return _legacy_campaign_gate(state)
    constructibility = str(state.get("constructibility") or "draft")
    obligations = list(state.get("obligations", []))
    cases = list(state.get("cases", []))
    oracles = list(state.get("oracles", []))
    attestations = list(state.get("attestations", []))
    decision_required: dict[str, object] | None = None
    allowed: list[Mapping[str, object]] = []
    effect = ""
    gate_state = "semantic_decision"
    next_action: dict[str, object]
    status = str(state.get("status") or "")
    if status in {"cancelled", "accepted_exception"}:
        gate_state = "inactive"
        next_action = {"tool": "fow_campaign_inspect", "operation": "summary"}
    elif constructibility == CampaignConstructibility.NEEDS_OBLIGATIONS.value:
        undecided = [
            item
            for item in obligations
            if item.get("decision") in {"unclassified", "investigate"}
        ]
        if not obligations:
            gate_state = "mechanical_progress"
            next_action = {
                "tool": "fow_campaign_advance",
                "operation": "derive_obligations",
            }
            effect = "derive current proof-obligation candidates without accepting them"
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
            allowed = [
                {"value": value, "requires": ["rationale"]}
                for value in (
                    "required",
                    "out_of_scope",
                    "duplicate",
                    "investigate",
                    "waived",
                )
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
    elif constructibility == CampaignConstructibility.NEEDS_ORACLE.value:
        residual = next(iter(state.get("residuals", [])), {})
        operation = str(
            (residual.get("next_action") or {}).get("operation") or "author_oracle"
        )
        current_question = None
        for oracle in oracles:
            questions = list(oracle.get("questions", []))
            if questions:
                current_question = questions[0]
                break
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
        next_action = {"tool": "fow_campaign_author", "operation": operation}
    else:
        required_cases = [item for item in cases if bool(item.get("required"))]
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
                if unpromoted_case is None:
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


def _attestation_successor_gate(
    case_id: str,
    attestation: Mapping[str, object] | None,
    *,
    known_case_choices: Sequence[str],
    evidence_id: str = "",
) -> tuple[dict[str, object], dict[str, object], str]:
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
        "author a corrected source revision without changing the oracle"
        if evidence_id
        else "bind exact orchestrator-authored test source to the current oracle",
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
                "fact": "all required cases have current attested passed evidence",
                "source": "Flow campaign ledger",
                "freshness": "current",
            }
        ],
        "decision_required": None,
        "allowed_responses": [],
        "semantic_effect": "campaign evidence is accepted and coverage was reconciled",
        "next_action": {"tool": "fow_campaign_inspect", "operation": "summary"},
    }


def _empty_gate(project_id: str, change_id: str) -> dict[str, object]:
    return {
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


__all__ = ["CampaignAuthorityService"]
