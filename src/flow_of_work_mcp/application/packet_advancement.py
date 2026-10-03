"""Deterministic packet advancement across semantic and provider boundaries."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping

from flow_of_work_mcp.application.packet_guards import (
    PacketGuardDecision,
    PacketGuardService,
)
from flow_of_work_mcp.application.packet_next_action import (
    PacketNextActionProjectionService,
)
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_construction import (
    PacketConstructionAuditDraft,
)
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    ReconciliationItemDisposition,
    ReconciliationItemDispositionDraft,
)
from flow_of_work_mcp.core.domain.packet_review import (
    ProviderReviewFindingDraft,
    WorkspaceReviewReceiptDraft,
)
from flow_of_work_mcp.core.domain.change_control import PacketStatus, PacketTransition
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
)


_PACKET_PROVIDER_OPERATIONS = frozenset(
    {
        "configure_packet_provider",
        "provider_pending",
        "deliver_provider_command",
        "ensure_provider_draft",
        "choose_provider_targets",
        "synchronize_provider_unit",
        "remove_provider_unit",
        "start_provider_packet",
        "stop_provider_packet",
        "observe_provider_packet",
        "provider_complete",
        "provider_failed",
        "provider_stopped",
        "retry_provider_rejection",
    }
)
_MECHANICAL_OPERATIONS = frozenset(
    {
        "derive_engineering_questions",
        "evaluate_packet_readiness",
        "derive_packet_pressure",
        "collect_packet_evidence",
        "reconcile_packet_evidence",
        "consume_verification",
    }
)


class PacketAdvancementCoordinator:
    def __init__(
        self,
        *,
        ledger,
        guards: PacketGuardService,
        changes,
        construction,
        pressure,
        work_plans: PacketWorkPlanService,
        reviews,
        reconciliation,
        campaigns,
        next_actions: PacketNextActionProjectionService,
        packet_provider_overlay,
        max_steps: int = 12,
    ) -> None:
        self._ledger = ledger
        self._guards = guards
        self._changes = changes
        self._construction = construction
        self._pressure = pressure
        self._work_plans = work_plans
        self._reviews = reviews
        self._reconciliation = reconciliation
        self._campaigns = campaigns
        self._next_actions = next_actions
        self._packet_provider_overlay = packet_provider_overlay
        self._max_steps = max(1, int(max_steps))

    def advance(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str,
        decision: Mapping[str, object] | None = None,
        expected_spec_revision: int | None = None,
        expected_plan_revision: int | None = None,
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        decision = dict(decision or {})
        history: list[Mapping[str, object]] = []
        decision_consumed = False
        self._assert_expected_revisions(
            project_id,
            change_id,
            packet_id,
            expected_spec_revision=expected_spec_revision,
            expected_plan_revision=expected_plan_revision,
        )
        if decision:
            guard = self._guards.evaluate(project_id, change_id, packet_id)
            if self._provider_decision_applies(guard, decision):
                return self._advance_packet_provider(
                    project_id,
                    change_id,
                    packet_id,
                    actor=actor,
                    request_id=request_id,
                    decision=decision,
                )
            try:
                operation, outcome = self._consume_decision(
                    project_id,
                    change_id,
                    packet_id,
                    guard=guard,
                    decision=decision,
                    actor=actor,
                    request_id=request_id,
                    expected_spec_revision=expected_spec_revision,
                    expected_plan_revision=expected_plan_revision,
                )
            except (
                ChangeControlBlockedError,
                ImplementationProviderContractError,
                ImplementationProviderUnavailableError,
            ) as exc:
                if str(decision.get("disposition") or "").strip().lower() != (
                    "investigate"
                ):
                    raise
                return self._provider_boundary(
                    project_id,
                    change_id,
                    packet_id,
                    guard,
                    history,
                    exc,
                    decision_consumed=False,
                )
            history.append(
                {
                    "step_kind": operation,
                    "semantic": True,
                    "outcome": _bounded_outcome(outcome),
                }
            )
            decision_consumed = True

        for _ in range(self._max_steps):
            self._assert_expected_revisions(
                project_id,
                change_id,
                packet_id,
                expected_spec_revision=expected_spec_revision,
                expected_plan_revision=expected_plan_revision,
            )
            guard = self._guards.evaluate(project_id, change_id, packet_id)
            if guard.next_operation in _PACKET_PROVIDER_OPERATIONS:
                return self._advance_packet_provider(
                    project_id,
                    change_id,
                    packet_id,
                    actor=actor,
                    request_id=request_id,
                    decision={},
                )
            if guard.next_operation not in _MECHANICAL_OPERATIONS:
                return self._result(
                    project_id,
                    change_id,
                    packet_id,
                    guard,
                    history,
                    decision_consumed=decision_consumed,
                )

            spec_revision = self._spec_revision(project_id, change_id, packet_id)
            fingerprint_inputs: dict[str, object] = {
                "spec_revision": spec_revision,
                "step": guard.next_operation,
            }
            if guard.next_operation in {
                "collect_packet_evidence",
                "reconcile_packet_evidence",
            }:
                state = self._reconciliation.get(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                ) or {}
                fingerprint_inputs["evidence_snapshot_id"] = (
                    _latest_reconciliation_snapshot_id(state)
                )
            fingerprint = _fingerprint(fingerprint_inputs)
            replay = (
                None
                if guard.next_operation == "collect_packet_evidence"
                else self._receipt(
                    project_id,
                    change_id,
                    packet_id,
                    spec_revision,
                    guard.next_operation,
                    fingerprint,
                )
            )
            if replay is not None:
                history.append({**replay, "replayed": True})
                current = self._guards.evaluate(project_id, change_id, packet_id)
                if current.next_operation == guard.next_operation:
                    return self._result(
                        project_id,
                        change_id,
                        packet_id,
                        PacketGuardDecision(
                            **{
                                **current.__dict__,
                                "state": "blocked",
                                "blockers": current.blockers,
                            }
                        ),
                        history,
                        decision_consumed=decision_consumed,
                        invariant_violation=True,
                    )
                continue

            try:
                outcome = self._run_mechanical_operation(
                    project_id,
                    change_id,
                    packet_id,
                    guard.next_operation,
                    actor=actor,
                    request_id=request_id,
                )
            except (
                ChangeControlBlockedError,
                ImplementationProviderContractError,
                ImplementationProviderUnavailableError,
            ) as exc:
                return self._provider_boundary(
                    project_id,
                    change_id,
                    packet_id,
                    guard,
                    history,
                    exc,
                    decision_consumed=decision_consumed,
                )
            receipt = {
                "step_kind": guard.next_operation,
                "spec_revision": spec_revision,
                "outcome": _bounded_outcome(outcome),
            }
            if guard.next_operation != "collect_packet_evidence":
                self._store_receipt(
                    project_id,
                    change_id,
                    packet_id,
                    spec_revision,
                    guard.next_operation,
                    fingerprint,
                    receipt,
                    actor,
                    request_id,
                )
            history.append(receipt)

        guard = self._guards.evaluate(project_id, change_id, packet_id)
        return self._result(
            project_id,
            change_id,
            packet_id,
            guard,
            history,
            decision_consumed=decision_consumed,
            invariant_violation=True,
        )

    def _run_mechanical_operation(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        operation: str,
        *,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        if operation == "consume_verification":
            campaign = self._campaigns.completed_campaign_for_packet(
                project_id, change_id, packet_id
            )
            if not campaign:
                raise ChangeControlBlockedError(
                    "packet_verification_campaign_not_current"
                )
            state = self._ledger.change_state(project_id, change_id)
            packet = next(
                item
                for item in state.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("packet_id") or "") == packet_id
            )
            campaign_id = str(campaign.get("campaign_id") or "")
            criteria = {
                str(criterion): f"verified_by:{campaign_id}"
                for criterion in packet.get("completion_criteria", [])
                if str(criterion)
            }
            return self._changes.transition_packet(
                project_id,
                change_id,
                packet_id,
                PacketTransition(
                    status=PacketStatus.IMPLEMENTED,
                    criterion_results=criteria,
                ),
                actor=actor,
                request_id=f"{request_id}:consume-verification:{campaign_id}",
            )
        if operation == "derive_engineering_questions":
            return self._construction.start_audit(
                project_id,
                PacketConstructionAuditDraft(
                    change_id=change_id,
                    packet_id=packet_id,
                ),
                actor=actor,
                request_id=f"{request_id}:questions",
            )
        if operation == "derive_packet_pressure":
            return self._pressure.derive(
                project_id,
                change_id,
                packet_id,
                actor=actor,
                request_id=f"{request_id}:pressure",
            )
        if operation in {"collect_packet_evidence", "reconcile_packet_evidence"}:
            scope = self._reconciliation.get(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
            )
            if scope is None:
                raise ChangeControlBlockedError("packet_reconciliation_scope_missing")
            if operation == "collect_packet_evidence":
                return self._reconciliation.collect_provider_snapshot(
                    project_id,
                    str(scope["reconciliation_scope_id"]),
                    actor=actor,
                    request_id=f"{request_id}:evidence",
                )
            return self._reconciliation.reconcile(
                project_id,
                str(scope["reconciliation_scope_id"]),
                actor=actor,
                request_id=f"{request_id}:reconcile-evidence",
            )
        return self._changes.evaluate_packet_readiness(
            project_id,
            change_id,
            packet_id,
            actor=actor,
            request_id=f"{request_id}:readiness",
        )

    def _provider_decision_applies(
        self,
        guard: PacketGuardDecision,
        decision: Mapping[str, object],
    ) -> bool:
        operation = str(
            decision.get("operation") or decision.get("decision") or ""
        ).strip()
        return (
            guard.next_operation in _PACKET_PROVIDER_OPERATIONS
            or operation == "stop_provider_packet"
        )

    def _advance_packet_provider(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str,
        decision: Mapping[str, object],
    ) -> Mapping[str, object]:
        change = self._ledger.change_state(project_id, change_id)
        packet = next(
            item
            for item in change.get("packets", [])
            if isinstance(item, Mapping)
            and str(item.get("packet_id") or "") == packet_id
        )
        plan = self._ledger.packet_work_plan_state(
            project_id, change_id, packet_id
        )
        if not isinstance(plan, Mapping):
            raise ChangeControlBlockedError("packet_work_plan_missing")
        requested = dict(decision)
        requested_operation = str(requested.get("operation") or "")
        if requested_operation == "stop_provider_packet":
            requested["_force_provider_stop"] = True
        elif requested_operation == "start_provider_packet":
            requested["_force_provider_start"] = True
        return self._packet_provider_overlay.advance(
            project_id,
            change_id,
            packet_id,
            packet=packet,
            work_plan=plan,
            actor=actor,
            request_id=request_id,
            decision=requested,
        )

    def _provider_boundary(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        guard: PacketGuardDecision,
        history: list[Mapping[str, object]],
        error: Exception,
        *,
        decision_consumed: bool,
    ) -> Mapping[str, object]:
        reason = str(
            getattr(error, "reason", "")
            or getattr(error, "terminal_reason", "")
            or error.__class__.__name__
        )
        return {
            "decision": {
                **guard.as_payload(),
                "state": "provider_boundary",
                "blockers": [
                    {
                        "code": reason,
                        "domain": "reconciliation_provider",
                        "correction": "retry_packet_advance",
                    }
                ],
            },
            "next_action": {
                "contract": "flow.lifecycle_action.v1",
                "tool": "fow_packet_advance",
                "operation": "advance",
                "arguments": {
                    "project_id": project_id,
                    "packet_id": packet_id,
                },
                "required_inputs": ["actor", "request_id"],
                "reason": reason,
                "retryable": True,
            },
            "mechanical_steps": history,
            "decision_response_consumed": decision_consumed,
            "async_boundary": True,
        }

    def _consume_decision(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        guard: PacketGuardDecision,
        decision: Mapping[str, object],
        actor: str,
        request_id: str,
        expected_spec_revision: int | None,
        expected_plan_revision: int | None,
    ) -> tuple[str, Mapping[str, object]]:
        operation = str(
            decision.get("operation") or decision.get("decision") or ""
        ).strip()
        if operation in {"accept_work_plan", "reject_work_plan"}:
            if guard.next_operation != "accept_work_plan":
                raise _decision_not_current(operation, guard.next_operation)
            state = self._ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            if not state or not state.get("work_plan_id"):
                raise ChangeControlBlockedError("packet_work_plan_missing")
            transition = (
                self._work_plans.accept
                if operation == "accept_work_plan"
                else self._work_plans.reject
            )
            packet_revision = (
                int(expected_spec_revision)
                if expected_spec_revision is not None
                else int(state["packet_revision"])
            )
            plan_revision = (
                int(expected_plan_revision)
                if expected_plan_revision is not None
                else int(state["plan_revision"])
            )
            outcome = transition(
                project_id,
                change_id,
                packet_id,
                plan_revision=plan_revision,
                expected_packet_revision=packet_revision,
                expected_current_plan_revision=plan_revision,
                rationale=required_text(decision.get("rationale"), "rationale"),
                actor=actor,
                request_id=f"{request_id}:{operation}",
            )
            if operation == "accept_work_plan":
                applicability = self._reconciliation.derive_applicability(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    actor=actor,
                    request_id=f"{request_id}:applicability",
                )
                outcome = {
                    **dict(outcome),
                    "reconciliation_applicability": dict(applicability or {}),
                }
            return operation, outcome
        if operation == "accept_residual_risk":
            if guard.next_operation != "decide_residual_risk":
                raise _decision_not_current(operation, guard.next_operation)
            pressure = self._pressure.latest(project_id, change_id, packet_id)
            if not pressure:
                raise ChangeControlBlockedError("packet_pressure_missing")
            return operation, self._pressure.accept_risk(
                project_id,
                str(pressure["pressure_id"]),
                accepted_risk_ref=required_text(
                    decision.get("accepted_risk_ref"), "accepted_risk_ref"
                ),
                actor=actor,
                request_id=f"{request_id}:{operation}",
            )
        if operation == "record_workspace_review":
            if guard.next_operation != "review_workspace":
                raise _decision_not_current(operation, guard.next_operation)
            review = decision.get("review")
            if not isinstance(review, Mapping):
                raise ValueError("decision.review must be an object")
            findings = review.get("findings") or []
            if not isinstance(findings, list):
                raise ValueError("decision.review.findings must be a list")
            return operation, self._reviews.record(
                project_id,
                change_id,
                packet_id,
                WorkspaceReviewReceiptDraft(
                    provider_revision=str(review.get("provider_revision") or ""),
                    disposition=str(review.get("disposition") or ""),
                    reviewed_target_refs=_string_tuple(
                        review.get("reviewed_target_refs"),
                        "decision.review.reviewed_target_refs",
                    ),
                    evidence_refs=_string_tuple(
                        review.get("evidence_refs"),
                        "decision.review.evidence_refs",
                    ),
                    workspace_candidate_id=str(
                        review.get("workspace_candidate_id") or ""
                    ),
                    candidate_revision=str(review.get("candidate_revision") or ""),
                    provider_review_ref=str(review.get("provider_review_ref") or ""),
                    completeness=str(review.get("completeness") or ""),
                    findings=tuple(
                        _provider_review_finding(item, index)
                        for index, item in enumerate(findings, start=1)
                    ),
                    existing_finding_ids=_string_tuple(
                        review.get("existing_finding_ids") or [],
                        "decision.review.existing_finding_ids",
                    ),
                ),
                actor=actor,
                request_id=f"{request_id}:{operation}",
            )
        if guard.next_operation == "resolve_reconciliation_residual" and operation in {
            "",
            "resolve_reconciliation_residual",
        }:
            return self._resolve_reconciliation_decision(
                project_id,
                change_id,
                packet_id,
                decision,
                actor=actor,
                request_id=request_id,
            )
        raise ChangeControlBlockedError(
            "unsupported_packet_decision",
            details={
                "received_operation": operation,
                "expected_operation": guard.next_operation,
            },
        )

    def _resolve_reconciliation_decision(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        decision: Mapping[str, object],
        *,
        actor: str,
        request_id: str,
    ) -> tuple[str, Mapping[str, object]]:
        disposition = str(decision.get("disposition") or "").strip().lower()
        scope = self._reconciliation.get(
            project_id, change_id=change_id, packet_id=packet_id
        )
        if scope is None:
            raise ChangeControlBlockedError("packet_reconciliation_scope_missing")
        if disposition == "investigate":
            snapshots = [
                value
                for value in scope.get("snapshots", [])
                if isinstance(value, Mapping)
            ]
            previous = str(snapshots[-1].get("snapshot_id") if snapshots else "")
            refreshed = self._reconciliation.collect_provider_snapshot(
                project_id,
                str(scope["reconciliation_scope_id"]),
                actor=actor,
                request_id=f"{request_id}:investigate-refresh",
            )
            refreshed_id = str(refreshed.get("snapshot_id") or "")
            if refreshed_id != previous:
                return "resolve_reconciliation_residual", {
                    "state": "successor_evidence_collected",
                    "snapshot_id": refreshed_id,
                }
            return "resolve_reconciliation_residual", {
                "state": "investigation_required",
                "action": dict(
                    self._reconciliation.current_residual_action(
                        project_id, change_id=change_id, packet_id=packet_id
                    )
                ),
            }
        if disposition not in {"accepted", "rejected", "waived", "escalated"}:
            raise ValueError(
                "decision.disposition must be accepted, rejected, waived, "
                "escalated or investigate"
            )
        latest_run = scope.get("latest_run")
        if not isinstance(latest_run, Mapping):
            raise ChangeControlBlockedError("packet_reconciliation_residual_missing")
        item = next(
            (
                value
                for value in latest_run.get("items", [])
                if isinstance(value, Mapping)
                and bool(value.get("blocking"))
                and str(value.get("disposition") or "")
                in {"open", "rejected", "escalated"}
            ),
            None,
        )
        if item is None:
            raise ChangeControlBlockedError("packet_reconciliation_residual_missing")
        if disposition == "accepted":
            return "resolve_reconciliation_residual", (
                self._reconciliation.accept_current_proposal(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    rationale=required_text(decision.get("rationale"), "rationale"),
                    actor=actor,
                    request_id=f"{request_id}:reconciliation-accept",
                )
            )
        return "resolve_reconciliation_residual", self._reconciliation.disposition_item(
            project_id,
            ReconciliationItemDispositionDraft(
                item_id=str(item["item_id"]),
                disposition=ReconciliationItemDisposition(disposition),
                rationale=required_text(decision.get("rationale"), "rationale"),
                policy_ref=str(decision.get("policy_ref") or ""),
            ),
            actor=actor,
            request_id=f"{request_id}:reconciliation-residual",
        )

    def _assert_expected_revisions(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        expected_spec_revision: int | None,
        expected_plan_revision: int | None,
    ) -> None:
        if expected_spec_revision is None and expected_plan_revision is None:
            return
        current_spec_revision, current_plan_revision = self._revisions(
            project_id, change_id, packet_id
        )
        if (
            expected_spec_revision is not None
            and int(expected_spec_revision) != current_spec_revision
        ) or (
            expected_plan_revision is not None
            and int(expected_plan_revision) != current_plan_revision
        ):
            raise ChangeControlBlockedError(
                "stale_packet_revision",
                details={
                    "expected_spec_revision": current_spec_revision,
                    "received_spec_revision": expected_spec_revision,
                    "expected_plan_revision": current_plan_revision,
                    "received_plan_revision": expected_plan_revision,
                },
            )

    def _result(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        guard: PacketGuardDecision,
        history: list[Mapping[str, object]],
        *,
        decision_consumed: bool,
        invariant_violation: bool = False,
    ) -> Mapping[str, object]:
        decision = guard.as_payload()
        if invariant_violation:
            decision = {
                **decision,
                "state": "blocked",
                "blockers": [
                    {
                        "code": "mechanical_progress_stalled",
                        "domain": "advancement",
                        "correction": "inspect_advancement_history",
                    }
                ],
            }
        return {
            "decision": decision,
            "next_action": self._next_action(
                project_id, change_id, packet_id, guard
            ),
            "mechanical_steps": history,
            "decision_response_consumed": decision_consumed,
            **({"invariant_violation": True} if invariant_violation else {}),
        }

    def _next_action(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        guard: PacketGuardDecision,
    ) -> Mapping[str, object]:
        spec_revision, plan_revision = self._revisions(
            project_id, change_id, packet_id
        )
        return self._next_actions.project(
            guard,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            spec_revision=spec_revision,
            plan_revision=plan_revision,
        )

    def _revisions(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[int, int]:
        spec_revision = self._spec_revision(project_id, change_id, packet_id)
        plan = self._ledger.packet_work_plan_state(
            project_id, change_id, packet_id
        )
        return spec_revision, int(plan.get("plan_revision") or 0) if plan else 0

    def _spec_revision(
        self, project_id: str, change_id: str, packet_id: str
    ) -> int:
        change = self._ledger.change_state(project_id, change_id)
        packet = next(
            item for item in change["packets"] if item["packet_id"] == packet_id
        )
        return int(packet.get("spec_revision") or packet["current_revision"])

    def _receipt(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        step: str,
        fingerprint: str,
    ) -> Mapping[str, object] | None:
        with self._ledger._read_connection() as connection:
            row = connection.execute(
                """
                SELECT outcome_json FROM packet_advancement_receipts
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND spec_revision = ? AND step_kind = ?
                  AND input_fingerprint = ?
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    spec_revision,
                    step,
                    fingerprint,
                ),
            ).fetchone()
        return None if row is None else json.loads(str(row["outcome_json"]))

    def _store_receipt(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        step: str,
        fingerprint: str,
        outcome: Mapping[str, object],
        actor: str,
        request_id: str,
    ) -> None:
        from flow_of_work_mcp.adapters.sqlite.common import _utc_now

        with self._ledger._transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO packet_advancement_receipts(
                    project_id, change_id, packet_id, spec_revision,
                    step_kind, input_fingerprint, outcome_json, created_at,
                    actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    spec_revision,
                    step,
                    fingerprint,
                    json.dumps(outcome, sort_keys=True, separators=(",", ":")),
                    _utc_now(),
                    actor,
                    request_id,
                ),
            )


def _decision_not_current(
    received: str, expected: str
) -> ChangeControlBlockedError:
    return ChangeControlBlockedError(
        "packet_decision_not_current",
        details={
            "received_operation": received,
            "expected_operation": expected,
        },
    )


def _fingerprint(value: Mapping[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_reconciliation_snapshot_id(state: Mapping[str, object]) -> str:
    snapshots = state.get("snapshots")
    if not isinstance(snapshots, (list, tuple)) or not snapshots:
        return ""
    latest = snapshots[-1]
    return str(latest.get("snapshot_id") or "") if isinstance(latest, Mapping) else ""


def _bounded_outcome(value: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: value[key]
        for key in (
            "construction_audit_id",
            "pressure_id",
            "state",
            "readiness_state",
            "spec_revision",
            "state_revision",
            "workspace_review_id",
            "disposition",
            "normalized_finding_ids",
            "workspace_candidate_id",
            "candidate_revision",
            "provider_review_ref",
            "provider_packet_ref",
            "provider_packet_revision",
            "completeness",
            "existing_finding_ids",
        )
        if key in value
    }


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return tuple(required_text(item, field) for item in value)


def _provider_review_finding(
    value: object, index: int
) -> ProviderReviewFindingDraft:
    if not isinstance(value, Mapping):
        raise ValueError(f"decision.review.findings[{index - 1}] must be an object")
    return ProviderReviewFindingDraft(
        provider_finding_ref=str(value.get("provider_finding_ref") or ""),
        severity=str(value.get("severity") or ""),
        title=str(value.get("title") or ""),
        rationale=str(value.get("rationale") or ""),
        expected_correction=str(value.get("expected_correction") or ""),
        scope_kind=str(value.get("scope_kind") or ""),
        scope_ref=str(value.get("scope_ref") or ""),
        source_anchor=str(value.get("source_anchor") or ""),
    )


__all__ = ["PacketAdvancementCoordinator"]
