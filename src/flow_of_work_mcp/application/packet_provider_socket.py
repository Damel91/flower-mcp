"""Durable application service for the provider-neutral packet socket."""

from __future__ import annotations

from hashlib import sha256
from contextlib import nullcontext
from dataclasses import replace
from typing import Mapping, Protocol

from flow_of_work_mcp.application.packet_provider_delivery import (
    rejection_retry_fingerprint,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_provider import (
    PacketProviderCommand,
    PacketProviderMode,
    PacketProviderOperation,
    PacketProviderOutboxState,
    PacketProviderReceipt,
)
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    ImplementationProviderContractError,
    ImplementationProviderError,
    ImplementationProviderUnavailableError,
    PacketProviderRejectedError,
)
from flow_of_work_mcp.core.domain.provider_validation import COMMAND_VERSION
from flow_of_work_mcp.core.ports.packet_provider import PacketProvider


class PacketProviderSocketRepository(Protocol):
    def enqueue_packet_provider_command(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
        command: PacketProviderCommand,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_provider_outbox_entry(
        self, project_id: str, outbox_id: str
    ) -> Mapping[str, object]: ...

    def packet_provider_recoverable_commands(
        self,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        flow_binding_generation: int | None = None,
        limit: int = 64,
    ) -> list[Mapping[str, object]]: ...

    def packet_provider_outbox_entries(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_unit_ref: str = "",
        flow_binding_generation: int | None = None,
        limit: int = 256,
    ) -> list[Mapping[str, object]]: ...

    def claim_packet_provider_command(
        self, project_id: str, outbox_id: str
    ) -> Mapping[str, object]: ...

    def mark_packet_provider_command_unknown(
        self,
        project_id: str,
        outbox_id: str,
        *,
        reason: str,
    ) -> Mapping[str, object]: ...

    def reject_packet_provider_command(
        self,
        project_id: str,
        outbox_id: str,
        *,
        reason: str,
    ) -> Mapping[str, object]: ...

    def record_packet_provider_receipt(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        receipt: PacketProviderReceipt,
        actor: str,
        outbox_id: str = "",
        observation_kind: str = "command",
        allow_terminal_replacement: bool = False,
        request_id: str = "",
    ) -> Mapping[str, object]: ...

    def packet_provider_binding(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
    ) -> Mapping[str, object] | None: ...


class PacketProviderSocketService:
    """Deliver packet commands with durable, replay-safe provider correlation."""

    def __init__(
        self,
        repository: PacketProviderSocketRepository,
        *,
        mode: PacketProviderMode | str,
        provider: PacketProvider | None,
        executor=None,
    ) -> None:
        self._repository = repository
        self._mode = PacketProviderMode(mode)
        self._provider = provider
        self._executor = executor

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def provider_kind(self) -> str:
        return self._provider.kind if self._provider is not None else ""

    def validation_fields(self, project_id, change_id, packet_id, *, operation, unit_key=''):
        """Construct the negotiated envelope; leave the legacy wire unchanged."""
        if self._executor is None or not self._executor.requires_validation(project_id, change_id, packet_id):
            return {}
        context = (self._executor.frozen_context(project_id, change_id, packet_id, unit_key=unit_key)
                   if str(operation) in {'stop', 'status'} else
                   self._executor.validation_context(project_id, change_id, packet_id, unit_key=unit_key))
        return {'contract_version': COMMAND_VERSION, 'validation_context': context}

    def _admit(self, project_id, change_id, packet_id, command, *, recovering=False):
        context_reader = getattr(self._repository, 'remediation_context', None)
        context = context_reader(project_id, change_id, packet_id) if callable(context_reader) else None
        if isinstance(context, Mapping) and context.get('predecessor_dependency_policy') == 'context_only':
            raise ChangeControlBlockedError('context_only_provider_execution_prohibited')
        if self._executor is not None:
            if command.contract_version == COMMAND_VERSION and not callable(getattr(self._require_provider(), 'execute_bound', None)):
                raise ChangeControlBlockedError('provider_validation_bound_transport_required')
            capability = self._executor.admit_command(project_id, change_id, packet_id, command, recovering=recovering)
            if capability is not None and capability['provider_kind'] != self.provider_kind:
                raise ChangeControlBlockedError('provider_executor_kind_mismatch')
            return capability
        elif command.contract_version == COMMAND_VERSION:
            raise ChangeControlBlockedError('provider_executor_service_required')
        else:
            # Keep direct application callers from bypassing the same ownership
            # boundary when they omit the composed executor service.
            external_reader = getattr(self._repository, 'external_work_state', None)
            if callable(external_reader) and external_reader(project_id, change_id, packet_id)['consumption_mode'] == 'external_agent':
                raise ChangeControlBlockedError('external_agent_mode_provider_execution_prohibited')
            executor_reader = getattr(self._repository, 'packet_executor_state', None)
            if callable(executor_reader) and executor_reader(project_id, change_id, packet_id).get('selection'):
                raise ChangeControlBlockedError('provider_executor_service_required')
            plan_reader = getattr(self._repository, 'packet_work_plan_state', None)
            state_reader = getattr(self._repository, 'change_state', None)
            plan = plan_reader(project_id, change_id, packet_id) or {} if callable(plan_reader) else {}
            packets = state_reader(project_id, change_id)['packets'] if callable(state_reader) else []
            packet = next((p for p in packets if p['packet_id'] == packet_id), {})
            if packet.get('architecture_refs') or any(u.get(f) for u in plan.get('units', []) for f in ('implements', 'provides', 'requires', 'verifies')):
                raise ChangeControlBlockedError('provider_executor_not_selected')

    @staticmethod
    def _validate_receipt(command, receipt):
        from flow_of_work_mcp.application.packet_executor import PacketExecutorService
        try:
            PacketExecutorService.validate_receipt(command, receipt)
        except ValueError as exc:
            raise ImplementationProviderContractError(str(exc)) from exc

    def _atomic(self):
        transaction = getattr(self._repository, 'atomic', None)
        return transaction() if callable(transaction) else nullcontext()

    def _execute(self, command, *, capability=None):
        provider = self._require_provider()
        if command.contract_version == COMMAND_VERSION:
            if capability is None:
                raise ChangeControlBlockedError('provider_admission_receipt_missing')
            receipt = provider.execute_bound(command, binding_identity=dict(capability['binding_identity']))
        else:
            receipt = provider.execute(command)
        self._validate_receipt(command, receipt)
        return receipt

    def ensure_draft(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        actor: str,
        request_id: str = "",
        deliver: bool = True,
    ) -> Mapping[str, object]:
        provider_kind = self._provider.kind if self._provider is not None else ""
        if provider_kind:
            binding = self._repository.packet_provider_binding(
                project_id,
                change_id,
                packet_id,
                provider_kind=provider_kind,
            )
            if binding is not None:
                return {
                    "state": "provider_bound",
                    "binding": binding,
                    "next_action": "continue packet authoring",
                }
        if self._provider is None:
            if self._mode == PacketProviderMode.REQUIRED:
                raise ImplementationProviderUnavailableError(
                    "packet_provider_required_but_unavailable"
                )
            return {
                "state": "provider_pending",
                "binding": None,
                "next_action": "continue provider-agnostic packet authoring",
            }
        del deliver  # Draft scaffolding is an observation, never an outbox mutation.
        self._provider.session_for_project(project_id)
        command = PacketProviderCommand(
            flow_session_ref=project_id,
            flow_packet_ref=packet_id,
            flow_spec_revision=flow_spec_revision,
            operation=PacketProviderOperation.ADD,
            semantic_input={},
            **self.validation_fields(project_id, change_id, packet_id, operation='add'),
            delivery_fingerprint=_stable_delivery_fingerprint(
                project_id,
                change_id,
                packet_id,
                "draft",
                str(flow_spec_revision),
            ),
        )
        return self._observe_semantic_scaffolding(
            project_id,
            change_id,
            packet_id,
            command=command,
            actor=actor,
            request_id=request_id,
        )

    def preview_targets(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        flow_unit_ref: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        provider.session_for_project(project_id)
        command = PacketProviderCommand(
            flow_session_ref=project_id,
            flow_packet_ref=packet_id,
            flow_spec_revision=flow_spec_revision,
            flow_unit_ref="",
            operation=PacketProviderOperation.ADD,
            semantic_input={},
            **self.validation_fields(project_id, change_id, packet_id, operation='add'),
            delivery_fingerprint=_stable_delivery_fingerprint(
                project_id,
                change_id,
                packet_id,
                "target-preview",
                flow_unit_ref,
                str(flow_spec_revision),
            ),
        )
        return self._observe_semantic_scaffolding(
            project_id,
            change_id,
            packet_id,
            command=command,
            actor=actor,
            request_id=request_id,
        )

    def _observe_semantic_scaffolding(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        command: PacketProviderCommand,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        if command.contract_version == COMMAND_VERSION:
            # Even draft/target scaffolding can have effects. Retain its exact
            # admitted context in the existing outbox for honest recovery.
            command = replace(command, delivery_fingerprint=_stable_delivery_fingerprint(
                command.delivery_fingerprint, str(command.validation_context['context_sha256'])))
            result = self.submit(project_id, change_id, packet_id, command=command,
                                 actor=actor, request_id=request_id)
            return {**result, 'state': 'provider_observed' if result['state'] == 'provider_delivered' else result['state']}
        self._admit(project_id, change_id, packet_id, command)
        try:
            receipt = provider.execute(command)
            self._validate_receipt(command, receipt)
        except PacketProviderRejectedError as exc:
            return {
                "state": "provider_rejected",
                "reason": exc.reason,
                "binding": None,
                "next_action": "inspect provider rejection and retry scaffolding",
            }
        except ImplementationProviderError as exc:
            return {
                "state": "provider_unavailable",
                "reason": str(
                    getattr(exc, "terminal_reason", "packet_provider_unavailable")
                ),
                "binding": None,
                "next_action": "restore provider availability and retry scaffolding",
            }
        recorded = self._repository.record_packet_provider_receipt(
            project_id,
            change_id,
            packet_id,
            flow_spec_revision=command.flow_spec_revision,
            receipt=receipt,
            actor=actor,
            observation_kind="status",
            request_id=request_id,
        )
        return {
            "state": "provider_observed",
            **dict(recorded),
            "provider_decision": dict(receipt.decision),
            "next_action": receipt.current_step or "continue packet authoring",
        }

    def submit(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        command: PacketProviderCommand,
        actor: str,
        request_id: str = "",
        deliver: bool = True,
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        with self._atomic():
            capability = self._admit(project_id, change_id, packet_id, command)
            entry = self._repository.enqueue_packet_provider_command(
                project_id, change_id, packet_id, provider_kind=provider.kind,
                command=command, actor=actor, request_id=request_id,
            )
            if command.contract_version == COMMAND_VERSION:
                self._executor.record_admission(project_id, change_id, packet_id,
                    entry=entry, capability=capability, command=command, actor=actor)
        if not deliver:
            return {
                "state": str(entry["state"]),
                "outbox": entry,
                "next_action": "deliver the durable provider command",
            }
        return self.deliver(
            project_id,
            str(entry["outbox_id"]),
            actor=actor,
            request_id=request_id,
        )

    def deliver(
        self,
        project_id: str,
        outbox_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        entry = self._repository.packet_provider_outbox_entry(project_id, outbox_id)
        state = str(entry["state"])
        if state == PacketProviderOutboxState.DELIVERED.value:
            return self._terminal_delivery_projection(entry, "provider_delivered")
        if state == PacketProviderOutboxState.REJECTED.value:
            return self._terminal_delivery_projection(entry, "provider_rejected")
        command_payload = entry.get("command")
        if not isinstance(command_payload, Mapping):
            raise ValueError("stored packet provider command is invalid")
        command = PacketProviderCommand.from_payload(command_payload)
        with self._atomic():
            entry = self._repository.packet_provider_outbox_entry(project_id, outbox_id)
            state = str(entry['state'])
            if state == PacketProviderOutboxState.DELIVERED.value:
                return self._terminal_delivery_projection(entry, 'provider_delivered')
            if state == PacketProviderOutboxState.REJECTED.value:
                return self._terminal_delivery_projection(entry, 'provider_rejected')
            capability = self._admit(project_id, str(entry['change_id']), str(entry['packet_id']), command,
                        recovering=state in {'unknown', 'delivering'})
            entry = self._repository.claim_packet_provider_command(project_id, outbox_id)
        if str(entry['state']) == PacketProviderOutboxState.DELIVERED.value:
            return self._terminal_delivery_projection(entry, 'provider_delivered')
        if str(entry['state']) == PacketProviderOutboxState.REJECTED.value:
            return self._terminal_delivery_projection(entry, 'provider_rejected')
        try:
            receipt = self._execute(command, capability=capability)
        except PacketProviderRejectedError as exc:
            if command.contract_version == COMMAND_VERSION and state in {'unknown', 'delivering'}:
                # A later rejection cannot prove that an earlier uncertain
                # dispatch had no effect. Keep its original ambiguity durable.
                unknown = self._repository.mark_packet_provider_command_unknown(project_id, outbox_id, reason=exc.reason)
                return {'state': 'provider_unknown', 'outbox': unknown, 'reason': exc.reason,
                        'next_action': 'reconcile the original uncertain provider effect'}
            rejected = self._repository.reject_packet_provider_command(
                project_id, outbox_id, reason=exc.reason
            )
            return {
                "state": "provider_rejected",
                "outbox": rejected,
                "reason": exc.reason,
                "next_action": "inspect provider rejection and reconcile explicitly",
            }
        except ImplementationProviderError as exc:
            reason = str(
                getattr(exc, "terminal_reason", "packet_provider_response_unknown")
            )
            unknown = self._repository.mark_packet_provider_command_unknown(
                project_id, outbox_id, reason=reason
            )
            return {
                "state": "provider_unknown",
                "outbox": unknown,
                "reason": reason,
                "next_action": "retry the same durable command, then observe status",
            }
        try:
            recorded = self._repository.record_packet_provider_receipt(
                project_id,
                str(entry["change_id"]),
                str(entry["packet_id"]),
                flow_spec_revision=int(entry["flow_spec_revision"]),
                receipt=receipt,
                actor=actor,
                outbox_id=outbox_id,
                observation_kind="command",
                request_id=request_id,
            )
        except ImplementationProviderError as exc:
            reason = str(
                getattr(exc, "terminal_reason", "packet_provider_response_unknown")
            )
            unknown = self._repository.mark_packet_provider_command_unknown(
                project_id, outbox_id, reason=reason
            )
            return {
                "state": "provider_unknown",
                "outbox": unknown,
                "reason": reason,
                "next_action": "retry the same durable command, then observe status",
            }
        return {
            "state": "provider_delivered",
            **dict(recorded),
            "provider_decision": dict(receipt.decision),
            "next_action": receipt.current_step or "inspect current packet status",
        }

    def retry_rejected(
        self,
        project_id: str,
        outbox_id: str,
        *,
        actor: str,
        rationale: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Append one explicit retry attempt for a terminal provider rejection."""

        provider = self._require_provider()
        rationale = required_text(rationale, "rationale")
        entry = self._repository.packet_provider_outbox_entry(project_id, outbox_id)
        if str(entry.get("state") or "") != PacketProviderOutboxState.REJECTED.value:
            raise ValueError("packet provider retry requires a rejected command")
        if str(entry.get("provider_kind") or "") != provider.kind:
            raise ValueError(
                "packet provider retry kind does not match the active provider"
            )
        command_payload = entry.get("command")
        if not isinstance(command_payload, Mapping):
            raise ValueError("stored packet provider command is invalid")
        command = PacketProviderCommand.from_payload(command_payload)
        retry = PacketProviderCommand(
            flow_session_ref=command.flow_session_ref,
            flow_packet_ref=command.flow_packet_ref,
            flow_spec_revision=command.flow_spec_revision,
            operation=command.operation,
            semantic_input=command.semantic_input,
            flow_unit_ref=command.flow_unit_ref,
            delivery_fingerprint=rejection_retry_fingerprint(
                command.delivery_fingerprint,
                str(entry.get("outbox_id") or outbox_id),
            ),
            contract_version=command.contract_version,
            validation_context=command.validation_context,
        )
        queued = self.submit(project_id, str(entry['change_id']), str(entry['packet_id']),
                             command=retry, actor=actor, request_id=request_id, deliver=False)['outbox']
        return {
            "state": "provider_retry_pending",
            "outbox": queued,
            "retries_outbox_id": str(entry.get("outbox_id") or outbox_id),
            "rationale": rationale,
            "next_action": "deliver the durable provider retry command",
        }

    def observe_status(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        actor: str,
        allow_terminal_replacement: bool = False,
        request_id: str = "",
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        binding = self._repository.packet_provider_binding(
            project_id,
            change_id,
            packet_id,
            provider_kind=provider.kind,
        )
        if binding is None:
            return {
                "state": "provider_pending",
                "binding": None,
                "next_action": "create the provider packet draft",
            }
        command = PacketProviderCommand(
            flow_session_ref=project_id,
            flow_packet_ref=packet_id,
            flow_spec_revision=flow_spec_revision,
            operation=PacketProviderOperation.STATUS,
            **self.validation_fields(project_id, change_id, packet_id, operation='status'),
        )
        reader = getattr(self._repository, 'consistent_read', None)
        with reader() if callable(reader) else nullcontext():
            capability = self._admit(project_id, change_id, packet_id, command)
        try:
            receipt = self._execute(command, capability=capability)
        except PacketProviderRejectedError as exc:
            return {
                "state": "provider_rejected",
                "reason": exc.reason,
                "binding": binding,
                "next_action": "inspect provider rejection and reconcile explicitly",
            }
        except ImplementationProviderError as exc:
            return {
                "state": "provider_unavailable",
                "reason": str(
                    getattr(exc, "terminal_reason", "packet_provider_unavailable")
                ),
                "binding": binding,
                "next_action": "restore provider availability and retry status",
            }
        try:
            recorded = self._repository.record_packet_provider_receipt(
                project_id,
                change_id,
                packet_id,
                flow_spec_revision=flow_spec_revision,
                receipt=receipt,
                actor=actor,
                observation_kind="status",
                allow_terminal_replacement=allow_terminal_replacement,
                request_id=request_id,
            )
        except ImplementationProviderError as exc:
            return {
                "state": "provider_rejected",
                "reason": str(exc)
                or str(
                    getattr(
                        exc,
                        "terminal_reason",
                        "implementation_provider_contract_invalid",
                    )
                ),
                "binding": binding,
                "next_action": "inspect provider status conflict and reconcile explicitly",
            }
        recorded_row = recorded.get("receipt")
        recorded_payload = (
            recorded_row.get("receipt")
            if isinstance(recorded_row, Mapping)
            else None
        )
        recorded_technical = (
            recorded_payload.get("technical")
            if isinstance(recorded_payload, Mapping)
            else None
        )
        continuation_policy = (
            str(recorded_technical.get("continuation_policy") or "")
            if isinstance(recorded_technical, Mapping)
            else ""
        ) or receipt.continuation_policy
        terminal = (
            bool(recorded_technical.get("terminal"))
            if isinstance(recorded_technical, Mapping)
            else receipt.terminal
        )
        stale = str(recorded.get("observation_disposition") or "") == "stale"
        if stale and isinstance(recorded_payload, Mapping):
            provider_decision = {
                "current_step": str(recorded_payload.get("current_step") or ""),
                "question": recorded_payload.get("question"),
                "choices": [],
                "choices_truncated": bool(
                    recorded_payload.get("choices_truncated")
                ),
                "required_input": dict(recorded_payload.get("required_input") or {}),
                "available_actions": list(
                    recorded_payload.get("available_actions") or []
                ),
            }
            next_action = (
                str(recorded_payload.get("current_step") or "")
                or "continue semantic lifecycle"
            )
        else:
            provider_decision = dict(receipt.decision)
            next_action = receipt.current_step or "continue semantic lifecycle"
        return {
            "state": "provider_observed",
            **dict(recorded),
            "provider_decision": provider_decision,
            "continuation_policy": continuation_policy,
            "terminal": terminal,
            "next_action": next_action,
        }

    def reconcile(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        recoverable = self._repository.packet_provider_recoverable_commands(
            project_id,
            change_id=change_id,
            packet_id=packet_id,
        )
        deliveries: list[Mapping[str, object]] = []
        for entry in recoverable:
            result = self.deliver(
                project_id,
                str(entry["outbox_id"]),
                actor=actor,
                request_id=request_id,
            )
            deliveries.append(result)
            if result["state"] in {"provider_unknown", "provider_rejected"}:
                return {
                    "state": str(result["state"]),
                    "deliveries": deliveries,
                    "next_action": str(result["next_action"]),
                }
        observation = self.observe_status(
            project_id,
            change_id,
            packet_id,
            flow_spec_revision=flow_spec_revision,
            actor=actor,
            request_id=request_id,
        )
        return {
            "state": str(observation["state"]),
            "deliveries": deliveries,
            "observation": observation,
            "next_action": str(observation["next_action"]),
        }

    def _require_provider(self) -> PacketProvider:
        if self._provider is None:
            raise ImplementationProviderUnavailableError(
                "packet_provider_not_configured"
            )
        return self._provider

    @staticmethod
    def _terminal_delivery_projection(
        entry: Mapping[str, object], state: str
    ) -> Mapping[str, object]:
        return {
            "state": state,
            "outbox": entry,
            "next_action": (
                "observe current provider status"
                if state == "provider_delivered"
                else "inspect provider rejection and reconcile explicitly"
            ),
        }


def _stable_delivery_fingerprint(*parts: str) -> str:
    material = "\x1f".join(str(part or "").strip() for part in parts)
    return "flow-semantic:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = ["PacketProviderSocketRepository", "PacketProviderSocketService"]
