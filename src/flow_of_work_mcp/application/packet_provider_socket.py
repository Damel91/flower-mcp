"""Durable application service for the provider-neutral packet socket."""

from __future__ import annotations

from hashlib import sha256
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
    ImplementationProviderError,
    ImplementationProviderUnavailableError,
    PacketProviderRejectedError,
)
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
    ) -> None:
        self._repository = repository
        self._mode = PacketProviderMode(mode)
        self._provider = provider

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def provider_kind(self) -> str:
        return self._provider.kind if self._provider is not None else ""

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
        try:
            receipt = provider.execute(command)
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
        entry = self._repository.enqueue_packet_provider_command(
            project_id,
            change_id,
            packet_id,
            provider_kind=provider.kind,
            command=command,
            actor=actor,
            request_id=request_id,
        )
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
        entry = self._repository.claim_packet_provider_command(project_id, outbox_id)
        state = str(entry["state"])
        if state == PacketProviderOutboxState.DELIVERED.value:
            return self._terminal_delivery_projection(entry, "provider_delivered")
        if state == PacketProviderOutboxState.REJECTED.value:
            return self._terminal_delivery_projection(entry, "provider_rejected")
        command_payload = entry.get("command")
        if not isinstance(command_payload, Mapping):
            raise ValueError("stored packet provider command is invalid")
        command = PacketProviderCommand.from_payload(command_payload)
        try:
            receipt = provider.execute(command)
        except PacketProviderRejectedError as exc:
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
        )
        queued = self._repository.enqueue_packet_provider_command(
            project_id,
            str(entry["change_id"]),
            str(entry["packet_id"]),
            provider_kind=provider.kind,
            command=retry,
            actor=actor,
            request_id=request_id,
        )
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
        )
        try:
            receipt = provider.execute(command)
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
