"""Semantic Flow overlay on the durable packet-provider socket."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping, Protocol, Sequence

from flow_of_work_mcp.application.packet_provider_delivery import (
    rejection_retry_fingerprint,
    semantic_delivery_root,
)
from flow_of_work_mcp.application.packet_provider_projection import (
    PacketProviderProjectionService,
)
from flow_of_work_mcp.application.packet_provider_socket import (
    PacketProviderSocketService,
)
from flow_of_work_mcp.core.domain import PACKET_INACTIVE_STATUS_VALUES
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ImplementationProviderUnavailableError


_TERMINAL_UNIT_STATES = frozenset({"removed", "deleted", "abandoned"})
_TECHNICAL_FIELDS = (
    "instructions",
    "constraints",
    "out_of_scope",
    "unit_checks",
    "depends_on",
    "replaces",
)
_ACTIVE_PROVIDER_RUN_PHASES = frozenset(
    {"execution", "execution_recovery", "queued", "remediating", "running", "stopping"}
)
_COMPLETE_PROVIDER_RUN_PHASES = frozenset({"completed", "completion", "partial"})
_FAILED_PROVIDER_RUN_PHASES = frozenset(
    {
        "blocked",
        "execution_blocked",
        "execution_failed",
        "failed",
        "planning_reconciliation_blocked",
        "recovery_blocked",
    }
)
_REHYDRATABLE_UNIT_REJECTIONS = frozenset(
    {
        "packet_idempotency_conflict",
        "packet_provider_target_selection_required",
    }
)


def _has_standalone_declarations(plan: Mapping[str, object] | None) -> bool:
    return bool(plan and any(unit.get(field) for unit in plan.get("units", [])
                            for field in ("implements", "provides", "requires", "verifies")))


class PacketProviderOverlayRepository(Protocol):
    def remediation_context(self, *args, **kwargs): ...
    def packet_provider_binding(self, *args, **kwargs): ...
    def packet_provider_delivered_unit_entries(self, *args, **kwargs): ...
    def packet_provider_outbox_entries(self, *args, **kwargs): ...
    def packet_provider_recoverable_commands(self, *args, **kwargs): ...
    def packet_provider_receipts(self, *args, **kwargs): ...
    def recover_packet_provider_correlations(self, *args, **kwargs): ...
    def reject_packet_provider_command(self, *args, **kwargs): ...


class PacketProviderOverlayService:
    """Keep Flow semantics while delegating packet mechanics to the provider."""

    def __init__(
        self,
        repository: PacketProviderOverlayRepository,
        *,
        socket: PacketProviderSocketService,
        projection: PacketProviderProjectionService,
        external_work=None,
    ) -> None:
        self._repository = repository
        self._socket = socket
        self._projection = projection
        self._external_work = external_work

    @property
    def provider_managed_targets(self) -> bool:
        return self._projection.mode != "agnostic"

    @property
    def active(self) -> bool:
        return self._projection.mode != "agnostic" and self._socket.configured

    def _context_only_remediation(self, project_id, change_id, packet_id) -> bool:
        context_reader = getattr(self._repository, "remediation_context", None)
        context = context_reader(project_id, change_id, packet_id) if callable(context_reader) else None
        return isinstance(context, Mapping) and context.get("predecessor_dependency_policy") == "context_only"

    def queue_plan_delta(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        """Queue at most one complete semantic mutation in the Flow transaction."""

        if self._external_work is not None and self._external_work.mode_for_packet(project_id, packet_id) == "external_agent":
            return {"state": "not_applicable", "consumption_mode": "external_agent", "queued": False}
        if self._context_only_remediation(project_id, change_id, packet_id):
            return {"state": "blocked", "reason": "context_only_requires_external_mode", "queued": False}
        if _has_standalone_declarations(after):
            return {"state": "blocked", "reason": "standalone_validation_requires_external_mode", "queued": False}

        capability = self._projection.capability(project_id)
        if not self.active:
            return {
                "state": "provider_pending",
                "capability": capability,
                "queued": False,
            }
        try:
            binding = self._binding(project_id, change_id, packet_id)
            recoverable = self._repository.packet_provider_recoverable_commands(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                flow_binding_generation=_binding_generation(binding),
                limit=1,
            )
            if recoverable:
                state = str(recoverable[0].get("state") or "pending")
                return {
                    "state": "provider_degraded"
                    if state == "unknown"
                    else "provider_delivery_pending",
                    "capability": capability,
                    "queued": False,
                    **(
                        {
                            "reason": str(
                                recoverable[0].get("last_error")
                                or "packet_provider_response_unknown"
                            )
                        }
                        if state == "unknown"
                        else {}
                    ),
                }
            if binding is None:
                return {
                    "state": "provider_draft_pending",
                    "capability": capability,
                    "queued": False,
                }
            before_units = _units_by_key(before)
            after_units = _units_by_key(after)
            correlations = _correlations(binding)
            for key in before_units:
                if key in after_units or key not in correlations:
                    continue
                entry = self._enqueue_remove(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=flow_spec_revision,
                    unit=before_units[key],
                    correlation=correlations[key],
                    actor=actor,
                    request_id=request_id,
                )
                return _queued_projection(entry, capability)
            pending = self._first_unsynced_unit(
                project_id,
                change_id,
                packet_id,
                after_units,
                correlations,
                binding,
            )
            if pending is None:
                return {
                    "state": "provider_units_synchronized",
                    "capability": capability,
                    "queued": False,
                }
            key = str(pending["client_unit_key"])
            correlation = correlations.get(key)
            if self._requires_target_choice(
                project_id, change_id, packet_id, pending, correlation
            ):
                return {
                    "state": "provider_target_required",
                    "capability": capability,
                    "queued": False,
                    "flow_unit_ref": key,
                }
            entry = self._enqueue_semantic_unit(
                project_id,
                change_id,
                packet_id,
                flow_spec_revision=flow_spec_revision,
                unit=pending,
                correlation=correlation,
                target=None,
                actor=actor,
                request_id=request_id,
            )
            return _queued_projection(entry, capability)
        except ImplementationProviderUnavailableError as exc:
            return {
                "state": "provider_degraded",
                "capability": capability,
                "queued": False,
                "reason": str(getattr(exc, "terminal_reason", str(exc))),
            }

    def projection(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        packet: Mapping[str, object],
        work_plan: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        capability = self._projection.capability(project_id)
        portable = self._projection.portable_packet(
            project_id=project_id,
            change_id=change_id,
            packet=packet,
            work_plan=work_plan,
        )
        provider_kind = self._socket.provider_kind
        binding = (
            self._repository.packet_provider_binding(
                project_id, change_id, packet_id, provider_kind=provider_kind
            )
            if provider_kind
            else None
        )
        recoverable = (
            self._repository.packet_provider_recoverable_commands(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                flow_binding_generation=_binding_generation(binding),
                limit=16,
            )
            if provider_kind
            else []
        )
        units = _units_by_key(work_plan)
        correlations = _correlations(binding)
        unit_states = [
            self._unit_state(
                project_id,
                change_id,
                packet_id,
                unit,
                correlations.get(key),
                binding,
            )
            for key, unit in units.items()
        ]
        unit_states.extend(
            self._removed_unit_state(key, correlation)
            for key, correlation in correlations.items()
            if key not in units
            and str(correlation.get("unit_state") or "") not in _TERMINAL_UNIT_STATES
        )
        latest_outbox = self._repository.packet_provider_outbox_entries(
            project_id,
            change_id,
            packet_id,
            flow_binding_generation=_binding_generation(binding),
            limit=1,
        )
        technical_state, next_operation = self._technical_state(
            capability=capability,
            binding=binding,
            recoverable=recoverable,
            unit_states=unit_states,
            latest_delivery=latest_outbox[-1] if latest_outbox else None,
        )
        if str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES:
            next_operation = "packet_inactive"
        latest_receipt = self._latest_receipt(project_id, change_id, packet_id)
        return {
            "capability": capability,
            "portable_packet": portable,
            "technical": {
                "state": technical_state,
                "binding": _public_binding(binding),
                "unit_count": len(units),
                "correlated_unit_count": len(
                    [item for item in unit_states if item["correlated"]]
                ),
                "unit_states": unit_states,
                "recoverable_command_count": len(recoverable),
                "last_delivery": _public_delivery(
                    latest_outbox[-1] if latest_outbox else None
                ),
                "last_receipt": _public_receipt(latest_receipt),
                "technical_execution_claimed": bool(binding),
            },
            "next_operation": next_operation,
            "next_action": _next_action(next_operation, unit_states),
        }

    def advance(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        packet: Mapping[str, object],
        work_plan: Mapping[str, object],
        actor: str,
        request_id: str,
        decision: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        """Advance mechanical work and stop at at most one engineering question."""

        if self._context_only_remediation(project_id, change_id, packet_id):
            raise ChangeControlBlockedError("context_only_provider_execution_prohibited")
        if _has_standalone_declarations(work_plan):
            raise ChangeControlBlockedError("standalone_validation_requires_external_mode")
        if self._external_work is not None and self._external_work.mode_for_packet(project_id, packet_id) == "external_agent":
            raise ChangeControlBlockedError("external_agent_mode_provider_execution_prohibited")

        decision = dict(decision or {})
        forced_operation = ""
        refresh_before_forced_start = False
        retry_authorized = False
        if bool(decision.pop("_force_provider_stop", False)):
            forced_operation = "stop_provider_packet"
        elif bool(decision.pop("_force_provider_start", False)):
            forced_operation = "start_provider_packet"
            refresh_before_forced_start = True
        elif str(decision.get("operation") or "") == "retry_provider_rejection":
            forced_operation = "retry_provider_rejection"
            retry_authorized = True
        if self.active and self._socket.provider_kind:
            self._repository.recover_packet_provider_correlations(
                project_id,
                change_id,
                packet_id,
                provider_kind=self._socket.provider_kind,
            )
        history: list[Mapping[str, object]] = []
        terminal_status_observed = False
        max_steps = max(12, (2 * len(_units_by_key(work_plan))) + 6)
        for step in range(max_steps):
            current = self.projection(
                project_id,
                change_id,
                packet_id,
                packet=packet,
                work_plan=work_plan,
            )
            operation = forced_operation or str(current["next_operation"])
            forced_operation = ""
            if operation == "provider_failed" and not terminal_status_observed:
                binding = self._binding(project_id, change_id, packet_id)
                if binding is not None:
                    observed = self._socket.observe_status(
                        project_id,
                        change_id,
                        packet_id,
                        flow_spec_revision=_spec_revision(packet),
                        actor=actor,
                        request_id=f"{request_id}:terminal-status",
                    )
                    terminal_status_observed = True
                    history.append(_history("observe_provider_packet", observed))
                    if str(observed.get("state") or "") != "provider_observed":
                        return _advancement_result(current, history)
                    return _advancement_result(
                        self.projection(
                            project_id,
                            change_id,
                            packet_id,
                            packet=packet,
                            work_plan=work_plan,
                        ),
                        history,
                    )
            if operation in {
                "configure_packet_provider",
                "provider_pending",
                "provider_complete",
                "provider_failed",
                "provider_stopped",
            }:
                return _advancement_result(current, history)

            if operation == "retry_provider_rejection":
                if not retry_authorized:
                    return _advancement_result(current, history)
                rationale = required_text(decision.get("rationale"), "rationale")
                unit_state = _current_unit_state(current)
                rejected = self._current_rejected_entry(
                    project_id,
                    change_id,
                    packet_id,
                    unit_state=unit_state,
                )
                if self._requires_rejected_unit_rehydration(
                    project_id,
                    change_id,
                    packet_id,
                    rejected=rejected,
                    unit_state=unit_state,
                    work_plan=work_plan,
                ):
                    assert unit_state is not None
                    unit_key = str(unit_state["client_unit_key"])
                    target = decision.get("target")
                    if target is None:
                        preview = self._socket.preview_targets(
                            project_id,
                            change_id,
                            packet_id,
                            flow_spec_revision=_spec_revision(packet),
                            flow_unit_ref=unit_key,
                            actor=actor,
                            request_id=f"{request_id}:retry-target-preview",
                        )
                        history.append(
                            _history("preview_provider_retry_targets", preview)
                        )
                        boundary = self._decision_boundary(preview)
                        preview_state = str(preview.get("state") or "")
                        if boundary is None and preview_state != "provider_observed":
                            boundary = _retry_preview_failure_boundary(preview)
                        elif boundary is None or str(boundary.get("state") or "") in {
                            "needs_provider_navigation",
                            "needs_provider_target_selection",
                        }:
                            boundary = _retry_target_question_boundary(
                                boundary or _target_question_boundary([])
                            )
                        return _advancement_result(
                            current,
                            history,
                            boundary=boundary,
                        )
                    queued = self._enqueue_semantic_unit(
                        project_id,
                        change_id,
                        packet_id,
                        flow_spec_revision=_spec_revision(packet),
                        unit=_unit(work_plan, unit_key),
                        correlation=self._correlation(
                            project_id, change_id, packet_id, unit_key
                        ),
                        target=_target_decision(target),
                        actor=actor,
                        request_id=request_id,
                        retry_origin=rejected,
                    )
                    decision.pop("target", None)
                    history.append(
                        _history("rehydrate_rejected_provider_unit", queued)
                    )
                    retry_authorized = False
                    continue
                retry = self._socket.retry_rejected(
                    project_id,
                    str(rejected["outbox_id"]),
                    actor=actor,
                    rationale=rationale,
                    request_id=f"{request_id}:retry-rejection",
                )
                history.append(_history(operation, retry))
                retry_authorized = False
                continue

            if operation == "deliver_provider_command":
                binding = self._binding(project_id, change_id, packet_id)
                pending = self._repository.packet_provider_recoverable_commands(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    flow_binding_generation=_binding_generation(binding),
                    limit=1,
                )
                if not pending:
                    continue
                if not self._recoverable_command_is_current(pending[0], work_plan):
                    superseded = self._repository.reject_packet_provider_command(
                        project_id,
                        str(pending[0]["outbox_id"]),
                        reason="superseded_by_flow_semantic_revision",
                    )
                    history.append(_history("supersede_provider_command", superseded))
                    continue
                delivered = self._socket.deliver(
                    project_id,
                    str(pending[0]["outbox_id"]),
                    actor=actor,
                    request_id=f"{request_id}:deliver:{step}",
                )
                history.append(_history(operation, delivered))
                boundary = self._decision_boundary(delivered)
                if boundary is not None:
                    return _advancement_result(current, history, boundary=boundary)
                continue

            if operation == "ensure_provider_draft":
                observed = self._socket.ensure_draft(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    actor=actor,
                    request_id=f"{request_id}:draft",
                )
                history.append(_history(operation, observed))
                boundary = self._decision_boundary(observed)
                current_unit = _current_unit_state(current)
                if (
                    boundary is not None
                    and current_unit is not None
                    and str(current_unit.get("phase") or "") == "target_required"
                ):
                    return _advancement_result(current, history, boundary=boundary)
                continue

            unit_state = _current_unit_state(current)
            if operation == "choose_provider_targets":
                assert unit_state is not None
                unit_key = str(unit_state["client_unit_key"])
                target = decision.get("target")
                if target is None:
                    preview = self._socket.preview_targets(
                        project_id,
                        change_id,
                        packet_id,
                        flow_spec_revision=_spec_revision(packet),
                        flow_unit_ref=unit_key,
                        actor=actor,
                        request_id=f"{request_id}:target-preview",
                    )
                    history.append(_history("preview_provider_targets", preview))
                    return _advancement_result(
                        current,
                        history,
                        boundary=self._decision_boundary(preview)
                        or _target_question_boundary([]),
                    )
                normalized_target = _target_decision(target)
                queued = self._enqueue_semantic_unit(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    unit=_unit(work_plan, unit_key),
                    correlation=self._correlation(
                        project_id, change_id, packet_id, unit_key
                    ),
                    target=normalized_target,
                    actor=actor,
                    request_id=request_id,
                )
                decision.pop("target", None)
                history.append(_history("queue_provider_unit", queued))
                continue

            if operation == "synchronize_provider_unit":
                assert unit_state is not None
                unit_key = str(unit_state["client_unit_key"])
                queued = self._enqueue_semantic_unit(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    unit=_unit(work_plan, unit_key),
                    correlation=self._correlation(
                        project_id, change_id, packet_id, unit_key
                    ),
                    target=None,
                    actor=actor,
                    request_id=request_id,
                )
                history.append(_history(operation, queued))
                continue

            if operation == "remove_provider_unit":
                assert unit_state is not None
                unit_key = str(unit_state["client_unit_key"])
                correlation = self._correlation(
                    project_id, change_id, packet_id, unit_key
                )
                if correlation is None:
                    continue
                queued = self._enqueue_remove(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    unit=None,
                    correlation=correlation,
                    actor=actor,
                    request_id=request_id,
                )
                history.append(_history(operation, queued))
                continue

            if operation in {"start_provider_packet", "stop_provider_packet"}:
                if operation == "start_provider_packet" and refresh_before_forced_start:
                    binding_before_preflight = self._binding(
                        project_id, change_id, packet_id
                    )
                    observed = self._socket.observe_status(
                        project_id,
                        change_id,
                        packet_id,
                        flow_spec_revision=_spec_revision(packet),
                        actor=actor,
                        allow_terminal_replacement=True,
                        request_id=f"{request_id}:preflight-status",
                    )
                    terminal_status_observed = True
                    history.append(_history("observe_provider_packet", observed))
                    refresh_before_forced_start = False
                    refreshed = self.projection(
                        project_id,
                        change_id,
                        packet_id,
                        packet=packet,
                        work_plan=work_plan,
                    )
                    if str(observed.get("state") or "") != "provider_observed":
                        return _advancement_result(refreshed, history)
                    binding_after_preflight = self._binding(
                        project_id, change_id, packet_id
                    )
                    if _binding_generation(
                        binding_after_preflight
                    ) != _binding_generation(binding_before_preflight):
                        continue
                    if str(refreshed.get("next_operation") or "") not in {
                        "provider_failed",
                        "start_provider_packet",
                    }:
                        return _advancement_result(refreshed, history)
                binding = self._require_binding(project_id, change_id, packet_id)
                command_operation = (
                    "start" if operation == "start_provider_packet" else "stop"
                )
                command = PacketProviderCommand(
                    flow_session_ref=project_id,
                    flow_packet_ref=packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    operation=command_operation,
                    delivery_fingerprint=_control_fingerprint(
                        packet_id,
                        command_operation,
                        _spec_revision(packet),
                        binding,
                    ),
                )
                outcome = self._socket.submit(
                    project_id,
                    change_id,
                    packet_id,
                    command=command,
                    actor=actor,
                    request_id=f"{request_id}:{command_operation}",
                )
                history.append(_history(operation, outcome))
                if command_operation == "stop":
                    return _advancement_result(
                        self.projection(
                            project_id,
                            change_id,
                            packet_id,
                            packet=packet,
                            work_plan=work_plan,
                        ),
                        history,
                    )
                continue

            if operation == "observe_provider_packet":
                observed = self._socket.observe_status(
                    project_id,
                    change_id,
                    packet_id,
                    flow_spec_revision=_spec_revision(packet),
                    actor=actor,
                    request_id=f"{request_id}:status",
                )
                history.append(_history(operation, observed))
                return _advancement_result(
                    self.projection(
                        project_id,
                        change_id,
                        packet_id,
                        packet=packet,
                        work_plan=work_plan,
                    ),
                    history,
                )
            raise RuntimeError(
                f"unknown packet provider overlay operation: {operation}"
            )
        raise RuntimeError(
            "packet provider overlay exceeded its bounded advancement loop"
        )

    def _technical_state(
        self,
        *,
        capability: Mapping[str, object],
        binding: Mapping[str, object] | None,
        recoverable: Sequence[Mapping[str, object]],
        unit_states: Sequence[Mapping[str, object]],
        latest_delivery: Mapping[str, object] | None,
    ) -> tuple[str, str]:
        mode = str(capability.get("mode") or "agnostic")
        configured = bool(capability.get("configured"))
        project_bound = bool(capability.get("project_bound"))
        if mode == "agnostic" or (mode == "auto" and not configured):
            return "provider_pending", "provider_pending"
        if not configured or not project_bound:
            return "provider_pending", "configure_packet_provider"
        if recoverable:
            if str(recoverable[0].get("state") or "") == "unknown":
                return "provider_degraded", "deliver_provider_command"
            return "provider_delivery_pending", "deliver_provider_command"
        if binding is None:
            if _retryable_rejection(latest_delivery, unit_states):
                return "provider_failed", "retry_provider_rejection"
            return "provider_draft_pending", "ensure_provider_draft"
        pending = next((item for item in unit_states if not item["synchronized"]), None)
        if pending is not None:
            phase = str(pending["phase"])
            operation = {
                "target_required": "choose_provider_targets",
                "direct_required": "synchronize_provider_unit",
                "delivery_pending": "deliver_provider_command",
                "remove_required": "remove_provider_unit",
                "rejected": "retry_provider_rejection",
            }.get(phase, "synchronize_provider_unit")
            return (
                ("provider_failed", operation)
                if phase == "rejected"
                else ("provider_unit_pending", operation)
            )
        provider_state = str(binding.get("provider_state") or "draft")
        run_phase = str(binding.get("run_phase") or "idle")
        provider_job_ref = str(binding.get("provider_job_ref") or "")
        if run_phase in _COMPLETE_PROVIDER_RUN_PHASES or provider_state in {
            "completed",
            "partial",
        }:
            return "provider_technically_complete", "provider_complete"
        if run_phase in _FAILED_PROVIDER_RUN_PHASES or provider_state in {
            "failed",
            "blocked",
        }:
            return "provider_failed", "provider_failed"
        if (
            run_phase in _ACTIVE_PROVIDER_RUN_PHASES
            or provider_state in {"running", "stopping"}
            or (run_phase == "authoring" and bool(provider_job_ref))
        ):
            return "provider_running", "observe_provider_packet"
        if _retryable_rejection(latest_delivery, unit_states):
            return "provider_failed", "retry_provider_rejection"
        if run_phase == "stopped" or provider_state == "stopped":
            return "provider_stopped", "start_provider_packet"
        return "provider_ready", "start_provider_packet"

    def _unit_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        unit: Mapping[str, object],
        correlation: Mapping[str, object] | None,
        binding: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        key = str(unit["client_unit_key"])
        identity_hash = _identity_hash(unit)
        content_hash = _content_hash(unit)
        correlated = (
            bool(correlation)
            and str((correlation or {}).get("unit_state") or "")
            not in _TERMINAL_UNIT_STATES
        )
        entries = self._repository.packet_provider_outbox_entries(
            project_id,
            change_id,
            packet_id,
            flow_unit_ref=key,
            flow_binding_generation=_binding_generation(binding),
            limit=256,
        )
        current = [
            item
            for item in entries
            if _delivery_matches(
                str(item.get("delivery_fingerprint") or ""),
                unit_key=key,
                identity_hash=identity_hash,
                content_hash=content_hash,
            )
        ]
        delivered = any(
            _delivery_matches(
                str(item.get("delivery_fingerprint") or ""),
                unit_key=key,
                identity_hash=identity_hash,
                content_hash=content_hash,
            )
            for item in self._delivered_entries_for_current_packet(
                project_id,
                change_id,
                packet_id,
                unit_key=key,
                binding=binding,
            )
        )
        synchronized = correlated and delivered
        if synchronized:
            phase = "synchronized"
        elif current and str(current[-1].get("state") or "") == "rejected":
            phase = "rejected"
        elif current:
            phase = "delivery_pending"
        elif self._requires_target_choice(
            project_id, change_id, packet_id, unit, correlation
        ):
            phase = "target_required"
        else:
            phase = "direct_required"
        return {
            "client_unit_key": key,
            "operation_kind": str(unit.get("operation_kind") or ""),
            "correlated": correlated,
            "synchronized": synchronized,
            "phase": phase,
            "identity_hash": identity_hash,
            "content_hash": content_hash,
        }

    def _first_unsynced_unit(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        units: Mapping[str, Mapping[str, object]],
        correlations: Mapping[str, Mapping[str, object]],
        binding: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        for key, unit in units.items():
            if not self._unit_state(
                project_id,
                change_id,
                packet_id,
                unit,
                correlations.get(key),
                binding,
            )["synchronized"]:
                return unit
        return None

    @staticmethod
    def _removed_unit_state(
        key: str, correlation: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {
            "client_unit_key": key,
            "operation_kind": "remove",
            "correlated": True,
            "synchronized": False,
            "phase": "remove_required",
            "identity_hash": _fingerprint(
                {"provider_unit_ref": str(correlation.get("provider_unit_ref") or "")}
            )[:16],
            "content_hash": _fingerprint("removed")[:16],
        }

    def _requires_target_choice(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        unit: Mapping[str, object],
        correlation: Mapping[str, object] | None,
    ) -> bool:
        if str(unit.get("operation_kind") or "") == "new_file":
            return False
        if correlation is None:
            return True
        return self._latest_delivered_identity(
            project_id, change_id, packet_id, str(unit["client_unit_key"])
        ) != _identity_hash(unit)

    @staticmethod
    def _recoverable_command_is_current(
        entry: Mapping[str, object], work_plan: Mapping[str, object]
    ) -> bool:
        unit_key = str(entry.get("flow_unit_ref") or "")
        if not unit_key:
            return True
        unit = _units_by_key(work_plan).get(unit_key)
        operation = str(entry.get("operation") or "")
        if operation == "remove":
            return unit is None
        if unit is None:
            return False
        return _delivery_matches(
            str(entry.get("delivery_fingerprint") or ""),
            unit_key=unit_key,
            identity_hash=_identity_hash(unit),
            content_hash=_content_hash(unit),
        )

    def _enqueue_semantic_unit(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        unit: Mapping[str, object],
        correlation: Mapping[str, object] | None,
        target: Mapping[str, object] | None,
        actor: str,
        request_id: str,
        retry_origin: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        key = str(unit["client_unit_key"])
        identity_hash = _identity_hash(unit)
        content_hash = _content_hash(unit)
        current_correlation = (
            correlation
            if correlation
            and str(correlation.get("unit_state") or "") not in _TERMINAL_UNIT_STATES
            else None
        )
        operation_kind = str(unit.get("operation_kind") or "")
        if operation_kind == "new_file":
            if current_correlation is None:
                operation = "add"
                semantic_input: dict[str, object] = {
                    "unit": _provider_unit(unit, future=True)
                }
            else:
                operation = "edit"
                semantic_input = {
                    "changes": _provider_unit_changes(unit, include_future=True)
                }
        else:
            prior_identity = self._latest_delivered_identity(
                project_id, change_id, packet_id, key
            )
            if (
                current_correlation is not None
                and prior_identity == identity_hash
                and target is None
            ):
                operation = "edit"
                semantic_input = {"changes": _provider_unit_changes(unit)}
            else:
                if target is None:
                    raise ValueError("provider target decision is required")
                if current_correlation is None:
                    operation = "add"
                    semantic_input = {
                        "unit": _provider_unit(unit),
                        "target": dict(target),
                    }
                else:
                    operation = "edit"
                    semantic_input = {
                        "changes": _provider_unit_changes(unit),
                        "target": dict(target),
                    }
        delivery_fingerprint = _unit_delivery_fingerprint(
            operation,
            key,
            identity_hash,
            content_hash,
            _binding_generation(
                self._require_binding(project_id, change_id, packet_id)
            ),
        )
        if retry_origin is not None:
            delivery_fingerprint = rejection_retry_fingerprint(
                str(retry_origin.get("delivery_fingerprint") or ""),
                str(retry_origin.get("outbox_id") or ""),
            )
        command = PacketProviderCommand(
            flow_session_ref=project_id,
            flow_packet_ref=packet_id,
            flow_spec_revision=flow_spec_revision,
            operation=operation,
            flow_unit_ref=key,
            semantic_input=semantic_input,
            delivery_fingerprint=delivery_fingerprint,
        )
        return self._socket.submit(
            project_id,
            change_id,
            packet_id,
            command=command,
            actor=actor,
            request_id=f"{request_id}:semantic-unit",
            deliver=False,
        )["outbox"]

    def _requires_rejected_unit_rehydration(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        rejected: Mapping[str, object],
        unit_state: Mapping[str, object] | None,
        work_plan: Mapping[str, object],
    ) -> bool:
        if (
            unit_state is None
            or str(rejected.get("last_error") or "")
            not in _REHYDRATABLE_UNIT_REJECTIONS
        ):
            return False
        unit_key = str(unit_state.get("client_unit_key") or "")
        unit = _units_by_key(work_plan).get(unit_key)
        if unit is None or str(unit.get("operation_kind") or "") == "new_file":
            return False
        correlation = self._correlation(project_id, change_id, packet_id, unit_key)
        if (
            correlation is not None
            and str(correlation.get("unit_state") or "")
            not in _TERMINAL_UNIT_STATES
        ):
            return False
        return self._requires_target_choice(
            project_id,
            change_id,
            packet_id,
            unit,
            correlation,
        )

    def _enqueue_remove(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        unit: Mapping[str, object] | None,
        correlation: Mapping[str, object],
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        key = str(
            (unit or {}).get("client_unit_key")
            or correlation.get("flow_unit_ref")
            or ""
        )
        if not key:
            raise ValueError("provider removal correlation lacks flow_unit_ref")
        identity_hash = (
            _identity_hash(unit)
            if unit is not None
            else _fingerprint(
                {"provider_unit_ref": str(correlation["provider_unit_ref"])}
            )[:16]
        )
        content_hash = (
            _content_hash(unit) if unit is not None else _fingerprint("removed")[:16]
        )
        command = PacketProviderCommand(
            flow_session_ref=project_id,
            flow_packet_ref=packet_id,
            flow_spec_revision=flow_spec_revision,
            operation="remove",
            flow_unit_ref=key,
            semantic_input={},
            delivery_fingerprint=_unit_delivery_fingerprint(
                "remove",
                key,
                identity_hash,
                content_hash,
                _binding_generation(
                    self._require_binding(project_id, change_id, packet_id)
                ),
            ),
        )
        return self._socket.submit(
            project_id,
            change_id,
            packet_id,
            command=command,
            actor=actor,
            request_id=f"{request_id}:remove",
            deliver=False,
        )["outbox"]

    def _binding(self, project_id: str, change_id: str, packet_id: str):
        if not self._socket.provider_kind:
            return None
        return self._repository.packet_provider_binding(
            project_id,
            change_id,
            packet_id,
            provider_kind=self._socket.provider_kind,
        )

    def _require_binding(self, project_id: str, change_id: str, packet_id: str):
        binding = self._binding(project_id, change_id, packet_id)
        if binding is None:
            raise ValueError("provider packet binding is unavailable")
        return binding

    def _correlation(
        self, project_id: str, change_id: str, packet_id: str, unit_key: str
    ) -> Mapping[str, object] | None:
        return _correlations(self._binding(project_id, change_id, packet_id)).get(
            unit_key
        )

    def _latest_receipt(self, project_id: str, change_id: str, packet_id: str):
        receipts = self._repository.packet_provider_receipts(
            project_id, change_id, packet_id, limit=1
        )
        return receipts[0] if receipts else None

    def _latest_delivered_identity(
        self, project_id: str, change_id: str, packet_id: str, unit_key: str
    ) -> str:
        binding = self._require_binding(project_id, change_id, packet_id)
        entries = self._delivered_entries_for_current_packet(
            project_id,
            change_id,
            packet_id,
            unit_key=unit_key,
            binding=binding,
        )
        for item in reversed(entries):
            parts = _delivery_parts(str(item.get("delivery_fingerprint") or ""))
            if parts is not None and parts[1] == unit_key:
                return parts[2]
        return ""

    def _delivered_entries_for_current_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        unit_key: str,
        binding: Mapping[str, object] | None,
    ) -> Sequence[Mapping[str, object]]:
        if binding is None or not self._socket.provider_kind:
            return ()
        provider_packet_ref = str(binding.get("provider_packet_ref") or "")
        if not provider_packet_ref:
            return ()
        return self._repository.packet_provider_delivered_unit_entries(
            project_id,
            change_id,
            packet_id,
            provider_kind=self._socket.provider_kind,
            provider_packet_ref=provider_packet_ref,
            flow_unit_ref=unit_key,
            limit=256,
        )

    def _current_rejected_entry(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        unit_state: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        entries = self._repository.packet_provider_outbox_entries(
            project_id,
            change_id,
            packet_id,
            flow_unit_ref=str((unit_state or {}).get("client_unit_key") or ""),
            flow_binding_generation=_binding_generation(
                self._require_binding(project_id, change_id, packet_id)
            ),
            limit=256,
        )
        for entry in reversed(entries):
            if str(entry.get("state") or "") != "rejected":
                continue
            if unit_state is None or _delivery_matches(
                str(entry.get("delivery_fingerprint") or ""),
                unit_key=str(unit_state.get("client_unit_key") or ""),
                identity_hash=str(unit_state.get("identity_hash") or ""),
                content_hash=str(unit_state.get("content_hash") or ""),
            ):
                return entry
        raise ValueError("current provider rejection is unavailable")

    @staticmethod
    def _decision_boundary(result: Mapping[str, object]) -> Mapping[str, object] | None:
        state = str(result.get("state") or "")
        if state in {"provider_unknown", "provider_rejected"}:
            return {
                "state": state,
                "reason": str(result.get("reason") or state),
                "decision_required": {
                    "kind": "retry_provider_delivery"
                    if state == "provider_unknown"
                    else "retry_provider_rejection"
                },
                "next_operation": "deliver_provider_command"
                if state == "provider_unknown"
                else "retry_provider_rejection",
                "candidates": [],
            }
        decision = result.get("provider_decision")
        if not isinstance(decision, Mapping):
            return None
        choices = decision.get("choices")
        if not isinstance(choices, list):
            choices = []
        current_step = str(decision.get("current_step") or "")
        if current_step not in {"navigate", "choose_target"} and not choices:
            return None
        return _target_question_boundary(
            choices,
            question=str(decision.get("question") or ""),
            navigation_required=current_step == "navigate",
        )


def _units_by_key(plan: Mapping[str, object] | None) -> dict[str, Mapping[str, object]]:
    return {
        str(item["client_unit_key"]): item
        for item in (plan or {}).get("units", [])
        if isinstance(item, Mapping) and str(item.get("client_unit_key") or "")
    }


def _unit(plan: Mapping[str, object], key: str) -> Mapping[str, object]:
    try:
        return _units_by_key(plan)[key]
    except KeyError as exc:
        raise ValueError(f"unknown semantic packet unit: {key}") from exc


def _correlations(
    binding: Mapping[str, object] | None,
) -> dict[str, Mapping[str, object]]:
    return {
        str(item["flow_unit_ref"]): item
        for item in (binding or {}).get("unit_correlations", [])
        if isinstance(item, Mapping) and str(item.get("flow_unit_ref") or "")
    }


def _binding_generation(binding: Mapping[str, object] | None) -> int | None:
    if binding is None:
        return None
    generation = int(binding.get("flow_binding_generation") or 0)
    if generation <= 0:
        raise ValueError("provider binding generation is unavailable")
    return generation


def _provider_unit(
    unit: Mapping[str, object], *, future: bool = False
) -> dict[str, object]:
    kind = _provider_kind(str(unit.get("operation_kind") or ""))
    if not kind:
        raise ValueError(
            "semantic unit operation kind is unsupported by the packet provider"
        )
    result: dict[str, object] = {
        "kind": kind,
        "instructions": list(unit.get("instructions") or ()),
        "constraints": list(unit.get("constraints") or ()),
        "out_of_scope": list(unit.get("out_of_scope") or ()),
        "unit_checks": list(unit.get("unit_checks") or ()),
        "depends_on": list(unit.get("depends_on") or ()),
        "replaces": list(unit.get("replaces") or ()),
    }
    if future:
        result["future_target"] = _provider_future_target(unit)
    elif str(unit.get("operation_kind") or "") == "extract_move":
        result["produced_targets"] = [_provider_future_target(unit)]
    return result


def _provider_future_target(unit: Mapping[str, object]) -> dict[str, object]:
    return {
        "local_ref": "future:" + str(unit["client_unit_key"]),
        "member_label": str(unit.get("member_label") or ""),
        "surface": str(unit.get("surface") or "workspace"),
        "relative_path": str(unit.get("file_path") or ""),
    }


def _provider_unit_changes(
    unit: Mapping[str, object], *, include_future: bool = False
) -> dict[str, object]:
    return _provider_unit(unit, future=include_future)


def _provider_kind(operation_kind: str) -> str:
    return {
        "modify_existing": "modify_symbol",
        "new_file": "create_file",
        "delete_existing": "delete_symbol",
        "extract_move": "extract_move",
        "insert_in_file": "modify_file",
        "replace_region": "modify_file",
    }.get(operation_kind, "")


def _identity_hash(unit: Mapping[str, object]) -> str:
    return _fingerprint(
        {
            "operation_kind": str(unit.get("operation_kind") or ""),
            "target_description": str(unit.get("target_description") or ""),
            "member_label": str(unit.get("member_label") or ""),
            "file_path": str(unit.get("file_path") or ""),
            "surface": str(unit.get("surface") or "repo"),
        }
    )[:16]


def _content_hash(unit: Mapping[str, object]) -> str:
    return _fingerprint(
        {field: list(unit.get(field) or ()) for field in _TECHNICAL_FIELDS}
        | {"kind": _provider_kind(str(unit.get("operation_kind") or ""))}
    )[:16]


def _fingerprint(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _unit_delivery_fingerprint(
    operation: str,
    unit_key: str,
    identity_hash: str,
    content_hash: str,
    flow_binding_generation: int | None,
) -> str:
    if flow_binding_generation is None or flow_binding_generation <= 0:
        raise ValueError("provider binding generation is unavailable")
    return (
        f"flow-semantic:g{flow_binding_generation}:{operation}:"
        f"{unit_key}:{identity_hash}:{content_hash}"
    )


def _delivery_parts(value: str) -> tuple[str, str, str, str] | None:
    value = semantic_delivery_root(value)
    if not value.startswith("flow-semantic:"):
        return None
    body = value[len("flow-semantic:") :]
    if body.startswith("g"):
        try:
            generation, body = body.split(":", 1)
            if not generation[1:].isdigit() or int(generation[1:]) <= 0:
                return None
        except ValueError:
            return None
    try:
        head, identity_hash, content_hash = body.rsplit(":", 2)
        operation, unit_key = head.split(":", 1)
    except ValueError:
        return None
    return operation, unit_key, identity_hash, content_hash


def _delivery_matches(
    value: str,
    *,
    unit_key: str,
    identity_hash: str,
    content_hash: str,
) -> bool:
    parts = _delivery_parts(value)
    return bool(
        parts is not None
        and parts[1] == unit_key
        and parts[2] == identity_hash
        and parts[3] == content_hash
    )


def _control_fingerprint(
    packet_id: str,
    operation: str,
    spec_revision: int,
    binding: Mapping[str, object],
) -> str:
    boundary = {
        key: binding.get(key)
        for key in (
            "provider_packet_ref",
            "provider_packet_revision",
            "binding_epoch",
            "event_seq",
            "provider_state",
            "run_phase",
            "provider_job_ref",
            "current_step",
            "last_receipt_id",
        )
    }
    digest = _fingerprint(boundary)[:32]
    return f"flow-semantic-control:{operation}:{packet_id}:s{spec_revision}:b{digest}"


def _target_decision(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("decision.target must be an object")
    unknown = set(value) - {"mutation", "context"}
    if unknown:
        raise ValueError("decision.target contains unsupported field")
    mutation = value.get("mutation")
    if isinstance(mutation, bool) or not isinstance(mutation, int) or mutation <= 0:
        raise ValueError("decision.target.mutation must be a positive ordinal")
    context = _positive_ordinals(
        value.get("context") or (), "decision.target.context", required=False
    )
    if mutation in context:
        raise ValueError("decision target cannot use mutation as context")
    return {"mutation": mutation, "context": list(context)}


def _positive_ordinals(
    value: object, field: str, *, required: bool = True
) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"{field} must be a list of positive ordinals")
    try:
        result = tuple(int(item) for item in value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a list of positive ordinals") from exc
    if (
        (required and not result)
        or any(item <= 0 for item in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError(f"{field} must contain unique positive ordinals")
    return result


def _spec_revision(packet: Mapping[str, object]) -> int:
    return int(packet.get("spec_revision") or packet.get("current_revision") or 0)


def _public_binding(
    binding: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if binding is None:
        return None
    return {
        key: binding[key]
        for key in (
            "provider_kind",
            "provider_packet_ref",
            "provider_packet_revision",
            "flow_spec_revision",
            "binding_epoch",
            "event_seq",
            "provider_state",
            "run_phase",
            "provider_job_ref",
            "current_step",
            "last_receipt_id",
        )
        if key in binding
    }


def _public_receipt(
    receipt: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if receipt is None:
        return None
    value = receipt.get("receipt")
    if not isinstance(value, Mapping):
        return None
    return {
        "receipt_id": str(receipt.get("receipt_id") or ""),
        "flow_spec_revision": int(receipt.get("flow_spec_revision") or 0),
        "provider_packet_revision": int(value.get("provider_packet_revision") or 0),
        "provider_state": str(value.get("provider_state") or ""),
        "binding_epoch": int(value.get("binding_epoch") or 0),
        "event_seq": int(value.get("event_seq") or 0),
        "technical": dict(value.get("technical") or {}),
        "current_step": str(value.get("current_step") or ""),
    }


def _public_delivery(entry: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if entry is None:
        return None
    return {
        "outbox_id": str(entry.get("outbox_id") or ""),
        "operation": str(entry.get("operation") or ""),
        "flow_unit_ref": str(entry.get("flow_unit_ref") or ""),
        "state": str(entry.get("state") or ""),
        "attempts": int(entry.get("attempts") or 0),
        "reason": str(entry.get("last_error") or ""),
    }


def _next_action(
    operation: str, unit_states: Sequence[Mapping[str, object]]
) -> Mapping[str, object]:
    current = next((item for item in unit_states if not item["synchronized"]), None)
    exposed_operation = (
        "start_provider_packet" if operation == "provider_failed" else operation
    )
    required = ["actor", "request_id"]
    if operation == "choose_provider_targets":
        required.append("decision.target")
    elif operation in {"provider_failed", "retry_provider_rejection"}:
        required.extend(["decision.operation", "decision.rationale"])
    return {
        "tool": "fow_packet_advance",
        "operation": exposed_operation,
        "decision_class": "semantic"
        if operation
        in {"choose_provider_targets", "provider_failed", "retry_provider_rejection"}
        else "mechanical",
        "required_inputs": required,
        "client_unit_key": str((current or {}).get("client_unit_key") or ""),
    }


def _current_unit_state(
    projection: Mapping[str, object],
) -> Mapping[str, object] | None:
    technical = projection.get("technical")
    if not isinstance(technical, Mapping):
        return None
    return next(
        (
            item
            for item in technical.get("unit_states", [])
            if isinstance(item, Mapping) and not bool(item.get("synchronized"))
        ),
        None,
    )


def _retryable_rejection(
    delivery: Mapping[str, object] | None,
    unit_states: Sequence[Mapping[str, object]],
) -> bool:
    if delivery is None or str(delivery.get("state") or "") != "rejected":
        return False
    unit_ref = str(delivery.get("flow_unit_ref") or "")
    if not unit_ref:
        return True
    return any(
        str(item.get("client_unit_key") or "") == unit_ref
        and str(item.get("phase") or "") == "rejected"
        for item in unit_states
    )


def _history(operation: str, outcome: Mapping[str, object]) -> Mapping[str, object]:
    nested = outcome.get("outbox")
    return {
        "operation": operation,
        "state": str(outcome.get("state") or ""),
        "outbox_id": str(
            nested.get("outbox_id")
            if isinstance(nested, Mapping)
            else outcome.get("outbox_id") or ""
        ),
        **(
            {"reason": str(outcome.get("reason") or outcome.get("last_error"))}
            if outcome.get("reason") or outcome.get("last_error")
            else {}
        ),
    }


def _queued_projection(
    outcome: Mapping[str, object], capability: Mapping[str, object]
) -> Mapping[str, object]:
    nested = outcome.get("outbox")
    entry = nested if isinstance(nested, Mapping) else outcome
    return {
        "state": "provider_delivery_pending",
        "queued": True,
        "outbox_id": str(entry.get("outbox_id") or ""),
        "operation": str(entry.get("operation") or ""),
        "flow_unit_ref": str(entry.get("flow_unit_ref") or ""),
        "capability": dict(capability),
    }


def _target_question_boundary(
    choices: Sequence[Mapping[str, object]],
    *,
    question: str = "",
    navigation_required: bool = False,
) -> Mapping[str, object]:
    return {
        "state": "needs_provider_navigation"
        if navigation_required
        else "needs_provider_target_selection",
        "question": question
        or (
            "Read the intended implementation entry point before selecting a target."
            if navigation_required
            else "Which visited symbol should this unit modify?"
        ),
        "decision_required": {
            "kind": "provider_target_selection",
            "target": {"mutation": None, "context": []},
        },
        "candidates": [dict(item) for item in choices],
    }


def _retry_target_question_boundary(
    boundary: Mapping[str, object],
) -> Mapping[str, object]:
    result = dict(boundary)
    decision_required = result.get("decision_required")
    target = (
        dict(decision_required.get("target") or {})
        if isinstance(decision_required, Mapping)
        else {}
    )
    result["next_operation"] = "retry_provider_rejection"
    result["decision_required"] = {
        "kind": "provider_rejection_rehydration",
        "operation": "retry_provider_rejection",
        "rationale": None,
        "target": target or {"mutation": None, "context": []},
    }
    result["required_inputs"] = [
        "actor",
        "request_id",
        "decision.operation",
        "decision.rationale",
        "decision.target",
    ]
    return result


def _retry_preview_failure_boundary(
    preview: Mapping[str, object],
) -> Mapping[str, object]:
    state = str(preview.get("state") or "provider_unavailable")
    return {
        "state": state,
        "reason": str(preview.get("reason") or state),
        "decision_required": {"kind": "retry_provider_rejection"},
        "next_operation": "retry_provider_rejection",
        "required_inputs": [
            "actor",
            "request_id",
            "decision.operation",
            "decision.rationale",
        ],
        "candidates": [],
    }


def _advancement_result(
    projection: Mapping[str, object],
    history: Sequence[Mapping[str, object]],
    *,
    boundary: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    result: dict[str, object] = {
        "state": str(
            (boundary or projection.get("technical") or {}).get("state") or ""
        ),
        "provider": dict(projection.get("technical") or {}),
        "mechanical_steps": list(history),
        "next_action": dict(projection.get("next_action") or {}),
    }
    if boundary:
        result["decision"] = dict(boundary)
        result["next_action"] = {
            **dict(projection.get("next_action") or {}),
            "operation": str(
                boundary.get("next_operation") or "choose_provider_targets"
            ),
        }
        required_inputs = boundary.get("required_inputs")
        if isinstance(required_inputs, list):
            result["next_action"]["required_inputs"] = list(required_inputs)
    return result


__all__ = ["PacketProviderOverlayService"]
