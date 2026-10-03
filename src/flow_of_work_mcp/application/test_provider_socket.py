"""Durable provider socket for test materialization and technical evidence."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.campaign_authority import (
    TestProviderCommand,
    TestProviderMaterializationMode,
    TestProviderOperation,
    TestProviderReceipt,
    canonical_materializer_capability,
    semantic_fingerprint,
)
from flow_of_work_mcp.core.errors import (
    AssuranceBlockedError,
    ImplementationProviderError,
    ImplementationProviderUnavailableError,
    PacketProviderRejectedError,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.ports.test_provider import TestProvider


class TestProviderSocketRepository(Protocol):
    def campaign_provider_context(
        self, project_id: str, campaign_id: str, case_id: str
    ) -> Mapping[str, object]: ...

    def enqueue_test_provider_command(
        self,
        project_id: str,
        *,
        provider_kind: str,
        command: TestProviderCommand,
        actor: str,
        request_id: str = "",
        retry_of_command_id: str = "",
        retry_rationale: str = "",
    ) -> Mapping[str, object]: ...

    def test_provider_outbox_entry(
        self, project_id: str, command_id: str
    ) -> Mapping[str, object]: ...

    def test_provider_recoverable_commands(
        self, project_id: str, *, campaign_id: str = "", limit: int = 64
    ) -> list[Mapping[str, object]]: ...

    def latest_test_provider_command(
        self, project_id: str, *, campaign_id: str
    ) -> Mapping[str, object] | None: ...

    def next_unresolved_test_provider_rejection(
        self, project_id: str, *, campaign_id: str
    ) -> Mapping[str, object] | None: ...

    def claim_test_provider_command(
        self, project_id: str, command_id: str
    ) -> Mapping[str, object]: ...

    def mark_test_provider_command_unknown(
        self, project_id: str, command_id: str, *, reason: str
    ) -> Mapping[str, object]: ...

    def reject_test_provider_command(
        self, project_id: str, command_id: str, *, reason: str
    ) -> Mapping[str, object]: ...

    def record_test_provider_receipt(
        self,
        project_id: str,
        *,
        provider_kind: str,
        receipt: TestProviderReceipt,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]: ...


class TestProviderSocketService:
    """Persist before delivery and make response loss safely retryable."""

    def __init__(
        self,
        repository: TestProviderSocketRepository,
        *,
        mode: str,
        provider: TestProvider | None,
    ) -> None:
        normalized_mode = str(mode or "agnostic").strip()
        if normalized_mode not in {"agnostic", "auto", "required"}:
            raise ValueError("test provider mode must be agnostic, auto or required")
        self._repository = repository
        self._mode = normalized_mode
        self._provider = provider

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def provider_kind(self) -> str:
        return self._provider.kind if self._provider is not None else ""

    def require_materialization_capability(
        self,
        project_id: str,
        mode: TestProviderMaterializationMode,
        capability: Mapping[str, object],
    ) -> None:
        provider = self._require_provider()
        provider.session_for_project(project_id)
        supports = getattr(provider, "supports_materialization_mode", None)
        supported = (
            bool(supports(mode, capability))
            if callable(supports)
            else mode == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
        )
        if not supported:
            raise AssuranceBlockedError(
                "test_provider_materialization_capability_unsupported",
                details={
                    "materialization_mode": mode.value,
                    "next_action": "use attest_source or configure a compatible provider",
                },
            )

    def resolve_materialization_capability(
        self,
        project_id: str,
        capability: Mapping[str, object],
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        provider.session_for_project(project_id)
        requested = canonical_materializer_capability(capability)
        supports = getattr(provider, "supports_materialization_mode", None)
        if not callable(supports) or not supports(
            TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR,
            requested,
        ):
            raise AssuranceBlockedError(
                "test_provider_materialization_capability_unsupported"
            )
        resolver = getattr(provider, "resolve_materialization_capability", None)
        if not callable(resolver):
            raise AssuranceBlockedError(
                "test_provider_exact_materialization_capability_unavailable"
            )
        resolved = resolver(project_id, requested)
        if not isinstance(resolved, Mapping):
            raise AssuranceBlockedError(
                "test_provider_exact_materialization_capability_invalid"
            )
        return canonical_materializer_capability(
            resolved,
            require_versions=True,
        )

    def queue_materialization(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        source_files: Mapping[str, str],
        actor: str,
        request_id: str,
        deliver: bool = False,
    ) -> Mapping[str, object]:
        context = self._repository.campaign_provider_context(
            project_id, campaign_id, case_id
        )
        operation = (
            TestProviderOperation.EDIT
            if str(context.get("provider_test_ref") or "")
            else TestProviderOperation.MATERIALIZE
        )
        return self._queue_command(
            project_id,
            campaign_id,
            case_id,
            operation=operation,
            source_files=source_files,
            actor=actor,
            request_id=request_id,
            deliver=deliver,
            context=context,
        )

    def queue_deterministic_materialization(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        actor: str,
        request_id: str,
        deliver: bool = False,
    ) -> Mapping[str, object]:
        context = self._repository.campaign_provider_context(
            project_id, campaign_id, case_id
        )
        attestation = context.get("attestation")
        if (
            not isinstance(attestation, Mapping)
            or str(attestation.get("materialization_mode") or "")
            != TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value
        ):
            raise AssuranceBlockedError("deterministic_materialization_intent_missing")
        capability = attestation.get("requested_capability")
        if not isinstance(capability, Mapping):
            raise AssuranceBlockedError(
                "deterministic_materialization_capability_missing"
            )
        self.require_materialization_capability(
            project_id,
            TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR,
            capability,
        )
        return self._queue_command(
            project_id,
            campaign_id,
            case_id,
            operation=TestProviderOperation.MATERIALIZE,
            source_files=None,
            actor=actor,
            request_id=request_id,
            deliver=deliver,
            context=context,
        )

    def queue_operation(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        operation: TestProviderOperation,
        actor: str,
        request_id: str,
        deliver: bool = False,
        reason: str = "",
        regression_obligation: bool = False,
        promotion_evidence_id: str = "",
    ) -> Mapping[str, object]:
        operation = TestProviderOperation(operation)
        if operation in {
            TestProviderOperation.MATERIALIZE,
            TestProviderOperation.EDIT,
        }:
            raise ValueError("source operations require queue_materialization")
        return self._queue_command(
            project_id,
            campaign_id,
            case_id,
            operation=operation,
            source_files=None,
            actor=actor,
            request_id=request_id,
            deliver=deliver,
            reason=reason,
            regression_obligation=regression_obligation,
            promotion_evidence_id=promotion_evidence_id,
        )

    def _queue_command(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        operation: TestProviderOperation,
        source_files: Mapping[str, str] | None,
        actor: str,
        request_id: str,
        deliver: bool,
        reason: str = "",
        regression_obligation: bool = False,
        promotion_evidence_id: str = "",
        context: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        if self._provider is None:
            if self._mode == "required":
                raise ImplementationProviderUnavailableError(
                    "test_provider_required_but_unavailable"
                )
            return {
                "state": "provider_pending",
                "next_action": "configure a test provider or materialize directly",
            }
        context = context or self._repository.campaign_provider_context(
            project_id, campaign_id, case_id
        )
        oracle = context.get("oracle")
        attestation = context.get("attestation")
        case = context.get("case")
        if not all(isinstance(item, Mapping) for item in (oracle, attestation, case)):
            raise ValueError("campaign provider context is incomplete")
        provider_test_ref = str(context.get("provider_test_ref") or "").strip()
        if (
            operation
            not in {
                TestProviderOperation.MATERIALIZE,
                TestProviderOperation.EDIT,
            }
            and not provider_test_ref
        ):
            raise ValueError("campaign provider test reference is missing")
        if (
            operation
            in {
                TestProviderOperation.RUN,
                TestProviderOperation.PROMOTE,
            }
            and str(attestation.get("state") or "") != "attested_current"
        ):
            raise ValueError("campaign provider operation requires current attestation")
        current_run_evidence = context.get("current_run_evidence")
        if operation == TestProviderOperation.PROMOTE:
            promotion_evidence_id = str(promotion_evidence_id or "").strip()
            if (
                not promotion_evidence_id
                or not isinstance(current_run_evidence, Mapping)
                or str(current_run_evidence.get("evidence_id") or "")
                != promotion_evidence_id
                or not bool(current_run_evidence.get("authoritative"))
                or str(current_run_evidence.get("acceptance_disposition") or "")
                != "passed"
                or str(current_run_evidence.get("operation") or "") != "run"
            ):
                raise ValueError(
                    "test promotion requires the exact current authoritative passed run"
                )
        semantic_input: dict[str, object] = {
            "case": dict(case),
            "oracle_snapshot": dict(oracle["payload"]),
            "harness": dict(attestation.get("harness") or {}),
        }
        if source_files is not None:
            semantic_input.update(
                {
                    "source_files": dict(source_files),
                    "allowed_materialization_scope": sorted(source_files),
                }
            )
        if provider_test_ref and operation != TestProviderOperation.MATERIALIZE:
            semantic_input["provider_test_ref"] = provider_test_ref
        if operation == TestProviderOperation.PROMOTE:
            semantic_input["regression_obligation"] = bool(regression_obligation)
            semantic_input["promotion_evidence_id"] = promotion_evidence_id
        if operation == TestProviderOperation.DISCARD:
            semantic_input["reason"] = str(reason or "campaign test discarded")
        mode = TestProviderMaterializationMode(
            str(
                attestation.get("materialization_mode")
                or TestProviderMaterializationMode.ORCHESTRATOR_SOURCE.value
            )
        )
        oracle_ir: Mapping[str, object] = {}
        requested_capability: Mapping[str, object] = {}
        if mode == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR:
            semantic_input.pop("case", None)
            semantic_input.pop("oracle_snapshot", None)
            oracle_ir_value = attestation.get("oracle_ir")
            capability_value = attestation.get("requested_capability")
            if not isinstance(oracle_ir_value, Mapping) or not isinstance(
                capability_value, Mapping
            ):
                raise AssuranceBlockedError(
                    "deterministic_materialization_authority_incomplete"
                )
            oracle_ir = oracle_ir_value
            requested_capability = capability_value
            self.require_materialization_capability(
                project_id, mode, requested_capability
            )
        else:
            capability_value = attestation.get("requested_capability")
            if isinstance(capability_value, Mapping) and capability_value:
                source_route = canonical_materializer_capability(capability_value)
                if set(source_route).difference({"language", "framework"}):
                    raise AssuranceBlockedError(
                        "source_materialization_route_invalid"
                    )
                semantic_input.update(
                    {
                        "language": source_route["language"],
                        "framework": source_route["framework"],
                    }
                )
        materialization_revision = int(context.get("materialization_revision") or 0)
        retry_of_command_id = ""
        retry_rationale = ""
        basis = attestation.get("basis")
        technical_retry = (
            basis.get("technical_retry") if isinstance(basis, Mapping) else None
        )
        replay_boundary = (
            request_id
            if operation
            in {
                TestProviderOperation.RUN,
                TestProviderOperation.PROMOTE,
                TestProviderOperation.REPORT,
            }
            else ""
        )
        if (
            operation == TestProviderOperation.MATERIALIZE
            and isinstance(technical_retry, Mapping)
        ):
            retry_of_command_id = required_text(
                str(technical_retry.get("predecessor_command_id") or ""),
                "predecessor_command_id",
            )
            retry_rationale = "explicit deterministic materialization successor"
            replay_boundary = f"technical-retry:{retry_of_command_id}"
        command = TestProviderCommand(
            flow_session_ref=project_id,
            campaign_id=campaign_id,
            case_id=case_id,
            operation=operation,
            oracle_id=str(oracle["oracle_id"]),
            oracle_revision=int(oracle["revision"]),
            oracle_fingerprint=str(oracle["fingerprint"]),
            attestation_intent_ref=str(attestation["attestation_id"]),
            source_manifest_digest=str(attestation["source_manifest_digest"]),
            semantic_input=semantic_input,
            delivery_fingerprint=_delivery_fingerprint(
                project_id,
                campaign_id,
                case_id,
                operation.value,
                str(oracle["fingerprint"]),
                str(attestation["authority_input_fingerprint"]),
                str(attestation.get("requested_capability_fingerprint") or ""),
                provider_test_ref,
                str(materialization_revision),
                semantic_fingerprint(
                    {
                        key: value
                        for key, value in semantic_input.items()
                        if key != "source_files"
                    }
                ),
                replay_boundary,
            ),
            materialization_mode=mode,
            authority_input_fingerprint=str(attestation["authority_input_fingerprint"]),
            oracle_ir=oracle_ir,
            requested_capability=requested_capability,
        )
        entry = self._repository.enqueue_test_provider_command(
            project_id,
            provider_kind=self._provider.kind,
            command=command,
            actor=actor,
            request_id=request_id,
            retry_of_command_id=retry_of_command_id,
            retry_rationale=retry_rationale,
        )
        if deliver:
            return self.deliver(
                project_id,
                str(entry["command_id"]),
                actor=actor,
                request_id=request_id,
            )
        return {
            "state": str(entry["state"]),
            "outbox": entry,
            "next_action": "deliver the durable test provider command",
        }

    def deliver(
        self,
        project_id: str,
        command_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        provider = self._require_provider()
        entry = self._repository.claim_test_provider_command(project_id, command_id)
        state = str(entry["state"])
        if state == "delivered":
            return {
                "state": "provider_delivered",
                "outbox": entry,
                "next_action": "inspect current campaign evidence",
            }
        if state == "rejected":
            return {
                "state": "provider_rejected",
                "outbox": entry,
                "reason": str(entry.get("last_error") or "provider_rejected"),
                "next_action": _rejection_next_action(entry),
            }
        payload = entry.get("command")
        if not isinstance(payload, Mapping):
            raise ValueError("stored test provider command is invalid")
        command = TestProviderCommand.from_payload(payload)
        try:
            receipt = provider.execute(command)
        except PacketProviderRejectedError as exc:
            rejected = self._repository.reject_test_provider_command(
                project_id, command_id, reason=exc.reason
            )
            return {
                "state": "provider_rejected",
                "outbox": rejected,
                "reason": exc.reason,
                "next_action": _rejection_next_action(rejected),
            }
        except ImplementationProviderError as exc:
            reason = str(
                getattr(exc, "terminal_reason", "test_provider_response_unknown")
            )
            unknown = self._repository.mark_test_provider_command_unknown(
                project_id, command_id, reason=reason
            )
            return {
                "state": "provider_unknown",
                "outbox": unknown,
                "reason": reason,
                "next_action": "retry this same durable command",
            }
        try:
            recorded = self._repository.record_test_provider_receipt(
                project_id,
                provider_kind=provider.kind,
                receipt=receipt,
                actor=actor,
                request_id=request_id,
            )
        except AssuranceBlockedError as exc:
            rejected = self._repository.reject_test_provider_command(
                project_id, command_id, reason=exc.reason
            )
            return {
                "state": "provider_rejected",
                "outbox": rejected,
                "reason": exc.reason,
                "next_action": _rejection_next_action(rejected),
            }
        return {
            "state": "provider_delivered",
            **dict(recorded),
            "next_action": receipt.next_action,
        }

    def retry_rejected(
        self,
        project_id: str,
        campaign_id: str,
        command_id: str,
        *,
        actor: str,
        rationale: str,
        request_id: str,
        deliver: bool = True,
    ) -> Mapping[str, object]:
        """Append one explicit successor for a terminal provider rejection."""

        provider = self._require_provider()
        rationale = required_text(rationale, "rationale")
        entry = self._repository.test_provider_outbox_entry(project_id, command_id)
        if str(entry.get("campaign_id") or "") != campaign_id:
            raise ValueError("test provider retry campaign does not match command")
        if str(entry.get("state") or "") != "rejected":
            raise ValueError("test provider retry requires a rejected command")
        if str(entry.get("provider_kind") or "") != provider.kind:
            raise ValueError("test provider retry kind does not match active provider")
        payload = entry.get("command")
        if not isinstance(payload, Mapping):
            raise ValueError("stored test provider command is invalid")
        command = TestProviderCommand.from_payload(payload)
        retry = TestProviderCommand(
            flow_session_ref=command.flow_session_ref,
            campaign_id=command.campaign_id,
            case_id=command.case_id,
            operation=command.operation,
            oracle_id=command.oracle_id,
            oracle_revision=command.oracle_revision,
            oracle_fingerprint=command.oracle_fingerprint,
            attestation_intent_ref=command.attestation_intent_ref,
            source_manifest_digest=command.source_manifest_digest,
            semantic_input=command.semantic_input,
            delivery_fingerprint=_rejection_retry_fingerprint(
                command.delivery_fingerprint,
                str(entry.get("command_id") or command_id),
            ),
            materialization_mode=command.materialization_mode,
            authority_input_fingerprint=command.authority_input_fingerprint,
            oracle_ir=command.oracle_ir,
            requested_capability=command.requested_capability,
        )
        queued = self._repository.enqueue_test_provider_command(
            project_id,
            provider_kind=provider.kind,
            command=retry,
            actor=actor,
            request_id=request_id,
            retry_of_command_id=str(entry.get("command_id") or command_id),
            retry_rationale=rationale,
        )
        queued_predecessor = str(queued.get("retry_of_command_id") or "")
        queued_rationale = str(queued.get("retry_rationale") or "")
        if deliver:
            delivered = self.deliver(
                project_id,
                str(queued["command_id"]),
                actor=actor,
                request_id=f"{request_id}:delivery",
            )
            return {
                **dict(delivered),
                "retries_command_id": queued_predecessor,
                "rationale": queued_rationale,
            }
        return {
            "state": "provider_retry_pending",
            "outbox": queued,
            "retries_command_id": queued_predecessor,
            "rationale": queued_rationale,
            "next_action": "deliver the durable test provider successor command",
        }

    def recover(
        self,
        project_id: str,
        *,
        campaign_id: str,
        actor: str,
        request_id: str,
        limit: int = 16,
    ) -> Mapping[str, object]:
        entries = self._repository.test_provider_recoverable_commands(
            project_id, campaign_id=campaign_id, limit=limit
        )
        deliveries = []
        for entry in entries:
            delivery = self.deliver(
                project_id,
                str(entry["command_id"]),
                actor=actor,
                request_id=f"{request_id}:{entry['command_id']}",
            )
            deliveries.append(delivery)
            if delivery["state"] == "provider_unknown":
                break
            if delivery["state"] == "provider_rejected" and not _is_superseded_rejection(
                delivery.get("outbox")
            ):
                break
        if not deliveries:
            rejected = self._repository.next_unresolved_test_provider_rejection(
                project_id, campaign_id=campaign_id
            )
            if rejected is not None:
                if _is_superseded_rejection(rejected):
                    return {
                        "state": "provider_idle",
                        "deliveries": [],
                        "next_action": "inspect current campaign",
                    }
                return {
                    "state": "provider_rejected",
                    "outbox": rejected,
                    "reason": str(rejected.get("last_error") or "provider_rejected"),
                    "next_action": _rejection_next_action(rejected),
                }
        last = deliveries[-1] if deliveries else None
        superseded_only = bool(
            last
            and last["state"] == "provider_rejected"
            and _is_superseded_rejection(last.get("outbox"))
        )
        return {
            "state": (
                "provider_idle"
                if superseded_only or last is None
                else str(last["state"])
            ),
            "deliveries": deliveries,
            "next_action": (
                "inspect current campaign"
                if superseded_only or last is None
                else last.get("next_action")
            ),
        }

    def _require_provider(self) -> TestProvider:
        if self._provider is None:
            raise ImplementationProviderUnavailableError("test_provider_not_configured")
        return self._provider


def _delivery_fingerprint(*parts: str) -> str:
    return sha256(
        json.dumps(list(parts), separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _rejection_retry_fingerprint(delivery_fingerprint: str, command_id: str) -> str:
    return _delivery_fingerprint(
        "flow.test_provider.rejection-retry.v1",
        delivery_fingerprint,
        command_id,
    )


_SUPERSEDED_REJECTION_REASONS = frozenset(
    {
        "test_provider_command_stale",
        "test_provider_attestation_not_current",
        "test_provider_command_oracle_ir_stale",
    }
)


def _is_superseded_rejection(entry: object) -> bool:
    return isinstance(entry, Mapping) and str(entry.get("last_error") or "") in (
        _SUPERSEDED_REJECTION_REASONS
    )


def _rejection_next_action(entry: Mapping[str, object]) -> dict[str, object]:
    if _is_superseded_rejection(entry):
        return {
            "tool": "fow_campaign_advance",
            "operation": "advance",
            "arguments": {
                "campaign_id": str(entry.get("campaign_id") or ""),
            },
            "required_inputs": ["request_id"],
        }
    return {
        "tool": "fow_campaign_author",
        "operation": "retry_provider_rejection",
        "arguments": {
            "campaign_id": str(entry.get("campaign_id") or ""),
            "provider_command_id": str(entry.get("command_id") or ""),
        },
        "required_inputs": ["rationale", "request_id"],
    }


__all__ = ["TestProviderSocketRepository", "TestProviderSocketService"]
