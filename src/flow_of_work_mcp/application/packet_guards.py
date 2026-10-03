"""Canonical, side-effect-free packet guard evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain import PACKET_INACTIVE_STATUS_VALUES


PACKET_WORKFLOW_VERSION = "packet-provider-socket-v2"

_PACKET_METADATA_BLOCKERS = {
    "packet_objective_missing",
    "packet_rationale_missing",
    "packet_scope_missing",
    "packet_invariants_missing",
    "packet_completion_criteria_missing",
    "packet_unresolved_authority_questions",
}
_REVIEWABLE_PROVIDER_STATES = frozenset(
    {"provider_technically_complete", "provider_complete"}
)


@dataclass(frozen=True)
class PacketGuardBlocker:
    code: str
    domain: str
    correction: str

    def as_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "domain": self.domain,
            "correction": self.correction,
        }


@dataclass(frozen=True)
class PacketGuardDecision:
    state: str
    authoring_ready: bool
    provider_ready: bool
    execution_ready: bool
    blockers: tuple[PacketGuardBlocker, ...]
    semantic_decisions: tuple[str, ...]
    residual_risks: tuple[str, ...]
    next_operation: str
    required_provider_capability: str = ""
    workflow_version: str = PACKET_WORKFLOW_VERSION

    def as_payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "authoring_ready": self.authoring_ready,
            "provider_ready": self.provider_ready,
            "execution_ready": self.execution_ready,
            "blockers": [item.as_payload() for item in self.blockers],
            "semantic_decisions": list(self.semantic_decisions),
            "residual_risks": list(self.residual_risks),
            "next_operation": self.next_operation,
            "required_provider_capability": self.required_provider_capability,
            "workflow_version": self.workflow_version,
        }


class _ChangeReader(Protocol):
    def change_state(self, project_id: str, change_id: str) -> Mapping[str, object]: ...


class PacketGuardEvaluator:
    """Pure precedence evaluator over one coherent packet snapshot."""

    @staticmethod
    def evaluate(snapshot: Mapping[str, object]) -> PacketGuardDecision:
        packet = _mapping(snapshot.get("packet"))
        plan = _mapping(snapshot.get("work_plan"))
        construction = _mapping(snapshot.get("construction"))
        pressure = _mapping(snapshot.get("pressure"))
        workspace_review = _mapping(snapshot.get("workspace_review"))
        reconciliation = _mapping(snapshot.get("reconciliation"))
        packet_socket = _mapping(snapshot.get("packet_socket"))
        verification_campaign = _mapping(snapshot.get("verification_campaign"))

        packet_revision = int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        )
        pressure_revision = pressure.get("packet_revision")
        if (
            pressure
            and pressure_revision is not None
            and int(pressure_revision) != packet_revision
        ):
            pressure = {}

        risks = tuple(
            str(item) for item in pressure.get("residual_risks", []) if str(item)
        )
        packet_status = str(packet.get("status") or "")
        if packet_status in PACKET_INACTIVE_STATUS_VALUES:
            return PacketGuardDecision(
                state=packet_status,
                authoring_ready=False,
                provider_ready=False,
                execution_ready=False,
                blockers=(),
                semantic_decisions=(),
                residual_risks=risks,
                next_operation="packet_inactive",
            )
        if not str(packet.get("objective") or "").strip() or not packet.get(
            "completion_criteria"
        ):
            return _decision(
                "needs_instructions",
                (_blocker("packet_instructions_missing", "packet", "packet_author"),),
                (),
                risks,
                "packet_author",
            )

        plan_status = str(plan.get("status") or "missing")
        if not plan or plan_status in {
            "missing",
            "legacy_non_executable",
            "rejected",
            "superseded",
        }:
            return _decision(
                "needs_instructions",
                (_blocker("work_plan_missing", "work_plan", "packet_author"),),
                (),
                risks,
                "packet_author",
            )
        spec_revision = packet_revision
        if int(plan.get("packet_revision") or 0) != spec_revision:
            return _decision(
                "needs_instructions",
                (_blocker("work_plan_stale", "work_plan", "reauthor_packet"),),
                (),
                risks,
                "packet_author",
            )
        if plan_status == "proposed":
            return _decision(
                "needs_instructions",
                (),
                ("accept_work_plan",),
                risks,
                "accept_work_plan",
            )

        if not construction:
            return _decision(
                "needs_engineering_answers",
                (
                    _blocker(
                        "engineering_question_plan_missing",
                        "engineering_questions",
                        "derive_engineering_questions",
                    ),
                ),
                (),
                risks,
                "derive_engineering_questions",
            )
        construction_revision = int(construction.get("packet_revision") or 0)
        if construction_revision and construction_revision != spec_revision:
            return _decision(
                "needs_engineering_answers",
                (
                    _blocker(
                        "packet_construction_audit_stale",
                        "engineering_questions",
                        "derive_engineering_questions",
                    ),
                ),
                (),
                risks,
                "derive_engineering_questions",
            )
        open_questions = tuple(
            str(item)
            for item in construction.get("open_required_question_ids", [])
            if str(item)
        )
        if open_questions:
            return _decision(
                "needs_engineering_answers",
                (
                    _blocker(
                        "engineering_answers_required",
                        "engineering_questions",
                        "answer_engineering_questions",
                    ),
                ),
                open_questions,
                risks,
                "answer_engineering_questions",
            )

        reconciliation_decision = _reconciliation_decision(reconciliation, risks)
        if reconciliation_decision is not None:
            return reconciliation_decision

        readiness_blockers = tuple(
            str(item) for item in packet.get("readiness_blockers", []) if str(item)
        )
        metadata_blockers = tuple(
            item for item in readiness_blockers if item in _PACKET_METADATA_BLOCKERS
        )
        if metadata_blockers:
            return PacketGuardDecision(
                state="needs_instructions",
                authoring_ready=False,
                provider_ready=False,
                execution_ready=False,
                blockers=tuple(
                    _blocker(item, "packet", "revise_packet")
                    for item in metadata_blockers
                ),
                semantic_decisions=(),
                residual_risks=risks,
                next_operation="revise_packet",
            )
        if not pressure:
            return PacketGuardDecision(
                state="provider_ready",
                authoring_ready=True,
                provider_ready=False,
                execution_ready=False,
                blockers=(),
                semantic_decisions=(),
                residual_risks=(),
                next_operation="derive_packet_pressure",
            )
        if risks and not bool(pressure.get("accepted_risk_refs")):
            return PacketGuardDecision(
                state="needs_risk_decision",
                authoring_ready=True,
                provider_ready=False,
                execution_ready=False,
                blockers=(),
                semantic_decisions=("accept_or_reject_residual_risk",),
                residual_risks=risks,
                next_operation="decide_residual_risk",
            )

        if not bool(packet_socket.get("enabled")):
            return PacketGuardDecision(
                state="provider_pending",
                authoring_ready=True,
                provider_ready=False,
                execution_ready=False,
                blockers=(
                    _blocker(
                        "packet_provider_socket_unavailable",
                        "provider",
                        "configure_packet_provider",
                    ),
                ),
                semantic_decisions=(),
                residual_risks=risks,
                next_operation="provider_pending",
                required_provider_capability="packet_provider",
            )

        socket_operation = str(
            packet_socket.get("next_operation") or "provider_pending"
        )
        socket_state = str(packet_socket.get("state") or "provider_pending")
        if (
            socket_operation == "provider_complete"
            or socket_state in _REVIEWABLE_PROVIDER_STATES
        ):
            return _workspace_review_decision(
                workspace_review, risks, verification_campaign
            )
        if socket_operation == "retry_provider_rejection":
            return PacketGuardDecision(
                state="provider_failed",
                authoring_ready=True,
                provider_ready=False,
                execution_ready=False,
                blockers=(
                    _blocker(
                        "packet_provider_command_rejected",
                        "provider",
                        "retry_provider_rejection",
                    ),
                ),
                semantic_decisions=("retry_provider_rejection",),
                residual_risks=risks,
                next_operation="retry_provider_rejection",
                required_provider_capability="packet_provider",
            )
        if socket_operation == "provider_failed" or socket_state == "provider_failed":
            return PacketGuardDecision(
                state="provider_failed",
                authoring_ready=True,
                provider_ready=False,
                execution_ready=False,
                blockers=(
                    _blocker(
                        "packet_provider_failed",
                        "provider",
                        "start_provider_packet",
                    ),
                ),
                semantic_decisions=("start_provider_packet",),
                residual_risks=risks,
                next_operation="provider_failed",
                required_provider_capability="packet_provider",
            )
        provider_ready = socket_operation in {
            "start_provider_packet",
            "observe_provider_packet",
        }
        return PacketGuardDecision(
            state=socket_state,
            authoring_ready=True,
            provider_ready=provider_ready,
            execution_ready=socket_operation == "start_provider_packet",
            blockers=(),
            semantic_decisions=(),
            residual_risks=risks,
            next_operation=socket_operation,
            required_provider_capability="packet_provider",
        )


class PacketGuardService:
    """Load one packet snapshot and delegate the decision to the pure evaluator."""

    def __init__(
        self,
        *,
        changes,
        work_plans,
        construction,
        pressure,
        reviews,
        reconciliation,
        campaigns,
        packet_provider_overlay,
        external_work=None,
        consistent_reads=None,
    ) -> None:
        self._changes = changes
        self._work_plans = work_plans
        self._construction = construction
        self._pressure = pressure
        self._reviews = reviews
        self._reconciliation = reconciliation
        self._campaigns = campaigns
        self._packet_provider_overlay = packet_provider_overlay
        self._external_work = external_work
        self._consistent_reads = consistent_reads

    def evaluate(
        self, project_id: str, change_id: str, packet_id: str
    ) -> PacketGuardDecision:
        context = self._consistent_reads.consistent_read() if self._consistent_reads is not None else nullcontext()
        with context:
            return self._evaluate(project_id, change_id, packet_id)

    def _evaluate(self, project_id: str, change_id: str, packet_id: str) -> PacketGuardDecision:
        change = self._changes.change_state(project_id, change_id)
        packet = next(
            (
                item
                for item in change.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("packet_id") or "") == packet_id
            ),
            None,
        )
        if packet is None:
            raise ValueError(f"unknown packet in change: {packet_id}")
        plan = self._work_plans.packet_work_plan_state(
            project_id, change_id, packet_id
        )
        spec_revision = int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        )
        context_reader = getattr(self._changes, "remediation_context", None)
        remediation = context_reader(project_id, change_id, packet_id) if callable(context_reader) else None
        context_only = isinstance(remediation, Mapping) and remediation.get("predecessor_dependency_policy") == "context_only"
        if context_only and (self._external_work is None or self._external_work.mode_for_packet(project_id, packet_id) != "external_agent"):
            return _decision("external_mode_required", (
                _blocker("context_only_requires_external_mode", "packet_validation", "external_select_mode"),
            ), (), (), "external_select_mode")
        if self._external_work is not None and plan and any(
            unit.get(field) for unit in plan.get("units", [])
            for field in ("implements", "provides", "requires", "verifies")
        ) and self._external_work.mode_for_packet(project_id, packet_id) != "external_agent":
            return _decision("external_mode_required", (
                _blocker("standalone_validation_requires_external_mode", "packet_validation", "external_select_mode"),
            ), (), (), "external_select_mode")
        if self._external_work is not None and self._external_work.mode_for_packet(
            project_id, packet_id
        ) == "external_agent":
            if str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES:
                return PacketGuardDecision(str(packet["status"]), False, False, False,
                                           (), (), (), "packet_inactive")
            validation = self._external_work.validation(project_id, change_id, packet_id)
            if not validation.get("plan_executable"):
                structural_gap = _mapping(_mapping(validation.get("validation")).get("next_gap"))
                reason = str(structural_gap.get("code") or validation.get("reason") or "external_validation_open")
                if reason == "work_plan_not_accepted" and plan and plan.get("status") == "proposed":
                    return _decision("needs_instructions", (), ("accept_work_plan",), (), "accept_work_plan")
                return _decision("external_validation_open", (
                    _blocker(reason, "packet_validation", "external_validation"),
                ), (), (), "external_validation")
            frontier = self._external_work.todo(project_id, change_id, packet_id)
            if frontier.get("status") == "blocked":
                reason = str(frontier.get("reason") or "external_frontier_blocked")
                gate = _mapping(frontier.get("next_gate"))
                obligation = str(gate.get("external_operation") or "")
                return _decision("external_frontier_blocked", (
                    _blocker(reason, "external_work", "external_todo"),
                ), (obligation,) if obligation else (), (), "external_todo")
            unit = _mapping(frontier.get("current_unit"))
            state = str(unit.get("status") or "")
            if state == "conflict":
                return PacketGuardDecision("external_outcome_conflict", True, False, False,
                                           (), (), (), "external_reconcile")
            if unit:
                return PacketGuardDecision("external_" + state, True, False,
                                           state == "actionable", (), (), (), "external_todo")
            return PacketGuardDecision("external_work_complete", True, False, False,
                                       (), (), (), "external_verification" if frontier.get("deferred_verification")
                                       else "external_acceptance")
        overlay = self._packet_provider_overlay.projection(
            project_id,
            change_id,
            packet_id,
            packet=packet,
            work_plan=plan,
        )
        technical = _mapping(overlay.get("technical"))
        binding = _mapping(technical.get("binding"))
        return PacketGuardEvaluator.evaluate(
            {
                "packet": packet,
                "work_plan": plan or {},
                "construction": self._construction.packet_construction_audit_for_packet(
                    project_id, change_id, packet_id
                )
                or {},
                "pressure": self._pressure.latest_packet_pressure(
                    project_id, change_id, packet_id
                )
                or {},
                "workspace_review": self._reviews.latest_workspace_review(
                    project_id,
                    change_id,
                    packet_id,
                    spec_revision,
                    provider_kind=str(binding.get("provider_kind") or ""),
                    provider_packet_ref=str(
                        binding.get("provider_packet_ref") or ""
                    ),
                    provider_packet_revision=int(
                        binding.get("provider_packet_revision") or 0
                    ),
                    binding_epoch=int(binding.get("binding_epoch") or 0),
                    event_seq=int(binding.get("event_seq") or 0),
                    provider_job_ref=str(binding.get("provider_job_ref") or ""),
                )
                or {},
                "reconciliation": self._reconciliation.packet_reconciliation_for_packet(
                    project_id, change_id, packet_id
                )
                or {},
                "verification_campaign": self._campaigns.completed_campaign_for_packet(
                    project_id, change_id, packet_id
                )
                or {},
                "packet_socket": {
                    "enabled": True,
                    "state": str(technical.get("state") or "provider_pending"),
                    "next_operation": str(
                        overlay.get("next_operation") or "provider_pending"
                    ),
                },
            }
        )


def _reconciliation_decision(
    reconciliation: Mapping[str, object], risks: tuple[str, ...]
) -> PacketGuardDecision | None:
    if str(reconciliation.get("applicability") or "not_applicable") != "applicable":
        return None
    blockers = tuple(
        str(item)
        for item in reconciliation.get("readiness_blockers", [])
        if str(item)
    )
    if "packet_evidence_snapshot_missing" in blockers:
        return PacketGuardDecision(
            "reconciliation_pending",
            True,
            False,
            False,
            (
                _blocker(
                    "packet_evidence_snapshot_missing",
                    "reconciliation",
                    "collect_packet_evidence",
                ),
            ),
            (),
            risks,
            "collect_packet_evidence",
            "packet_evidence_snapshot",
        )
    if any(
        item in blockers
        for item in (
            "packet_evidence_reconciliation_missing",
            "packet_evidence_reconciliation_stale",
        )
    ):
        return PacketGuardDecision(
            "reconciliation_pending",
            True,
            False,
            False,
            (
                _blocker(
                    "packet_evidence_reconciliation_required",
                    "reconciliation",
                    "reconcile_packet_evidence",
                ),
            ),
            (),
            risks,
            "reconcile_packet_evidence",
        )
    if "packet_evidence_residuals_open" not in blockers:
        return None
    latest_run = _mapping(reconciliation.get("latest_run"))
    open_items = [
        item
        for item in latest_run.get("items", [])
        if isinstance(item, Mapping)
        and bool(item.get("blocking"))
        and str(item.get("disposition") or "")
        in {"open", "rejected", "escalated"}
    ]
    return PacketGuardDecision(
        "needs_reconciliation_decision",
        True,
        False,
        False,
        (
            _blocker(
                "packet_evidence_residuals_open",
                "reconciliation",
                "resolve_reconciliation_residual",
            ),
        ),
        tuple(
            str(item.get("item_id") or "")
            for item in open_items[:1]
            if str(item.get("item_id") or "")
        ),
        risks,
        "resolve_reconciliation_residual",
    )


def _workspace_review_decision(
    workspace_review: Mapping[str, object],
    risks: tuple[str, ...],
    verification_campaign: Mapping[str, object] | None = None,
) -> PacketGuardDecision:
    disposition = str(workspace_review.get("disposition") or "")
    finding_ids = tuple(
        str(item)
        for item in workspace_review.get("normalized_finding_ids", [])
        if str(item)
    )
    if disposition == "approved":
        if str(workspace_review.get("completeness") or "partial") != "complete":
            return PacketGuardDecision(
                "blocked",
                True,
                True,
                False,
                (
                    _blocker(
                        "workspace_review_evidence_partial",
                        "assurance",
                        "retry_or_remediate",
                    ),
                ),
                (),
                risks,
                "retry_or_remediate",
            )
        if verification_campaign:
            return PacketGuardDecision(
                "verification_satisfied",
                True,
                True,
                False,
                (),
                (),
                risks,
                "consume_verification",
            )
        return PacketGuardDecision(
            "needs_verification",
            True,
            True,
            False,
            (),
            (),
            risks,
            "record_verification",
        )
    if disposition == "findings":
        return PacketGuardDecision(
            "needs_remediation",
            True,
            True,
            False,
            (
                _blocker(
                    "workspace_review_findings_open",
                    "assurance",
                    "retry_or_remediate",
                ),
            ),
            finding_ids,
            risks,
            "retry_or_remediate",
        )
    if disposition == "rejected":
        return PacketGuardDecision(
            "blocked",
            True,
            True,
            False,
            (
                _blocker(
                    "workspace_review_rejected",
                    "assurance",
                    "retry_or_remediate",
                ),
            ),
            finding_ids,
            risks,
            "retry_or_remediate",
        )
    return PacketGuardDecision(
        "needs_workspace_review",
        True,
        True,
        False,
        (),
        (),
        risks,
        "review_workspace",
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _blocker(code: str, domain: str, correction: str) -> PacketGuardBlocker:
    return PacketGuardBlocker(code=code, domain=domain, correction=correction)


def _decision(
    state: str,
    blockers: tuple[PacketGuardBlocker, ...],
    semantic: tuple[str, ...],
    risks: tuple[str, ...],
    next_operation: str,
) -> PacketGuardDecision:
    return PacketGuardDecision(
        state=state,
        authoring_ready=False,
        provider_ready=False,
        execution_ready=False,
        blockers=blockers,
        semantic_decisions=semantic,
        residual_risks=risks,
        next_operation=next_operation,
    )


__all__ = [
    "PACKET_WORKFLOW_VERSION",
    "PacketGuardBlocker",
    "PacketGuardDecision",
    "PacketGuardEvaluator",
    "PacketGuardService",
]
