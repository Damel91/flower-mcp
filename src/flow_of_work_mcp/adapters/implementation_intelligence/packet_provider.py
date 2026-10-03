"""CodingCastle adapter for Flow's semantic session-packet socket."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from flow_of_work_mcp.adapters.implementation_intelligence.mcp_provider import (
    McpToolClient,
    ProviderProjectBindingResolver,
)
from flow_of_work_mcp.core.domain.packet_provider import (
    PacketProviderCommand,
    PacketProviderOperation,
    PacketProviderReceipt,
    PacketProviderUnitReceipt,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
    PacketProviderRejectedError,
)
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind


_CODINGCASTLE_RECEIPT_VERSION = "codingcastle.packet.receipt.v2"
_PROVIDER_CORRELATION_VERSION = "codingcastle.packet.provider-correlation.v1"


@dataclass(frozen=True)
class CodingCastleProviderUnitCorrelation:
    provider_unit_ref: str
    unit_number: int

    @classmethod
    def from_value(cls, value: object) -> "CodingCastleProviderUnitCorrelation":
        if not isinstance(value, Mapping):
            raise ImplementationProviderContractError(
                "packet_provider_unit_correlation_missing"
            )
        provider_unit_ref = str(value.get("provider_unit_ref") or "").strip()
        unit_number = value.get("unit_number")
        if not provider_unit_ref or len(provider_unit_ref) > 256:
            raise ImplementationProviderContractError(
                "packet_provider_unit_correlation_missing"
            )
        if (
            isinstance(unit_number, bool)
            or not isinstance(unit_number, int)
            or unit_number <= 0
        ):
            raise ImplementationProviderContractError(
                "packet_provider_unit_number_unresolved"
            )
        return cls(provider_unit_ref=provider_unit_ref, unit_number=unit_number)

    def as_payload(self) -> dict[str, object]:
        return {
            "provider_unit_ref": self.provider_unit_ref,
            "unit_number": self.unit_number,
        }


@dataclass(frozen=True)
class CodingCastlePacketProjectBinding:
    project_id: str
    provider_session_id: str

    def __post_init__(self) -> None:
        project_id = str(self.project_id or "").strip()
        session_id = str(self.provider_session_id or "").strip()
        if not project_id or not session_id:
            raise ValueError("packet provider binding requires project and session")
        if len(session_id) > 256:
            raise ValueError("packet provider session exceeds the supported bound")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "provider_session_id", session_id)


class McpCodingCastlePacketProvider:
    """Map Flow semantics to the same human-scale CodingCastle public tool."""

    def __init__(
        self,
        *,
        client: McpToolClient,
        bindings: tuple[CodingCastlePacketProjectBinding, ...],
        unit_correlation_resolver: Callable[
            [str, str, str], Mapping[str, object] | None
        ]
        | None = None,
        tool_name: str = "codingcastle_packet",
        binding_resolver: ProviderProjectBindingResolver | None = None,
    ) -> None:
        if str(tool_name or "").strip() != "codingcastle_packet":
            raise ValueError("CodingCastle packet provider requires codingcastle_packet")
        by_project = {item.project_id: item for item in bindings}
        if len(by_project) != len(bindings):
            raise ValueError("packet provider project bindings must be unique")
        self._client = client
        self._bindings = by_project
        self._unit_correlation_resolver = unit_correlation_resolver
        self._tool_name = "codingcastle_packet"
        self._binding_resolver = binding_resolver

    @property
    def kind(self) -> str:
        return "codingcastle"

    def session_for_project(self, project_id: str) -> str:
        if self._binding_resolver is not None:
            durable = self._binding_resolver.resolve_provider_binding(
                project_id, ImplementationProviderKind.PACKET_EXECUTION
            )
            if durable is not None:
                return durable.provider_context_id
        binding = self._bindings.get(str(project_id or "").strip())
        if binding is None:
            raise ImplementationProviderUnavailableError(
                "packet_provider_project_unbound"
            )
        return binding.provider_session_id

    def execute(self, command: PacketProviderCommand) -> PacketProviderReceipt:
        session_id = self.session_for_project(command.flow_session_ref)
        arguments: dict[str, object] = {
            "session_id": session_id,
            "operation": command.operation.value,
            "detail_level": "audit",
        }
        semantic = dict(command.semantic_input)
        selected_correlation: CodingCastleProviderUnitCorrelation | None = None
        dependency_correlations: tuple[CodingCastleProviderUnitCorrelation, ...] = ()
        packet_checks_edit = (
            command.operation == PacketProviderOperation.EDIT
            and "packet_checks" in semantic
        )
        if command.operation == PacketProviderOperation.REMOVE or (
            command.operation == PacketProviderOperation.EDIT
            and not packet_checks_edit
        ):
            selected_correlation = self._provider_unit_correlation(
                command, command.flow_unit_ref
            )
            arguments["unit_number"] = selected_correlation.unit_number
        if command.operation == PacketProviderOperation.ADD:
            if "unit" in semantic:
                arguments["unit"], dependency_correlations = self._translate_dependencies(
                    command,
                    semantic["unit"],
                )
            if "target" in semantic:
                arguments["target"] = semantic["target"]
        elif command.operation == PacketProviderOperation.EDIT:
            arguments["changes"], dependency_correlations = self._translate_dependencies(
                command,
                semantic.get("changes", {}),
            )
            if "target" in semantic:
                arguments["target"] = semantic["target"]
            if "packet_checks" in semantic:
                arguments.pop("unit_number", None)
                arguments.pop("changes", None)
                arguments["packet_checks"] = semantic["packet_checks"]
                selected_correlation = None
        elif command.operation == PacketProviderOperation.REMOVE:
            if "disposition" in semantic:
                arguments.pop("unit_number", None)
                arguments["disposition"] = semantic["disposition"]
                selected_correlation = None

        metadata_payload: dict[str, object] = {}
        if selected_correlation is not None:
            metadata_payload["selected"] = selected_correlation.as_payload()
        if dependency_correlations:
            metadata_payload["dependencies"] = [
                item.as_payload() for item in dependency_correlations
            ]
        metadata = (
            {_PROVIDER_CORRELATION_VERSION: metadata_payload}
            if metadata_payload
            else None
        )

        payload = _unwrap_public_result(
            self._client.call_tool(self._tool_name, arguments, meta=metadata)
        )
        return _receipt_from_public_payload(
            payload,
            flow_unit_ref=command.flow_unit_ref,
            operation=command.operation,
            fallback_provider_unit_ref=(
                selected_correlation.provider_unit_ref
                if selected_correlation is not None
                else ""
            ),
            fallback_unit_number=(
                selected_correlation.unit_number
                if selected_correlation is not None
                else None
            ),
        )

    def _provider_unit_correlation(
        self,
        command: PacketProviderCommand,
        flow_unit_ref: str,
    ) -> CodingCastleProviderUnitCorrelation:
        if not str(flow_unit_ref or "").strip():
            raise ImplementationProviderContractError(
                "packet_provider_flow_unit_required"
            )
        if self._unit_correlation_resolver is None:
            raise ImplementationProviderContractError(
                "packet_provider_unit_resolver_unavailable"
            )
        value = self._unit_correlation_resolver(
            command.flow_session_ref,
            command.flow_packet_ref,
            flow_unit_ref,
        )
        return CodingCastleProviderUnitCorrelation.from_value(value)

    def _translate_dependencies(
        self,
        command: PacketProviderCommand,
        value: object,
    ) -> tuple[Mapping[str, object], tuple[CodingCastleProviderUnitCorrelation, ...]]:
        if not isinstance(value, Mapping):
            raise ImplementationProviderContractError(
                "packet_provider_semantic_unit_invalid"
            )
        translated = dict(value)
        dependencies = translated.get("depends_on")
        if dependencies is None:
            return translated, ()
        if not isinstance(dependencies, list):
            raise ImplementationProviderContractError(
                "packet_provider_dependencies_invalid"
            )
        numbers: list[int] = []
        correlations: list[CodingCastleProviderUnitCorrelation] = []
        for flow_ref in dependencies:
            if not isinstance(flow_ref, str) or not flow_ref.strip():
                raise ImplementationProviderContractError(
                    "packet_provider_dependency_flow_ref_invalid"
                )
            correlation = self._provider_unit_correlation(command, flow_ref)
            correlations.append(correlation)
            numbers.append(correlation.unit_number)
        translated["depends_on"] = numbers
        return translated, tuple(correlations)


def _unwrap_public_result(payload: Mapping[str, object]) -> Mapping[str, object]:
    current: object = payload
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        status = str(current.get("status") or "").strip().lower()
        result = current.get("result")
        if status and status not in {"ok", "success", "accepted"}:
            detail = result if isinstance(result, Mapping) else current
            reason = str(
                detail.get("reason")
                or current.get("reason")
                or "packet_provider_rejected"
            )
            raise PacketProviderRejectedError(reason)
        if isinstance(result, Mapping):
            current = result
            continue
        return current
    raise ImplementationProviderContractError("packet_provider_result_invalid")


def _receipt_from_public_payload(
    payload: Mapping[str, object],
    *,
    flow_unit_ref: str,
    operation: PacketProviderOperation,
    fallback_provider_unit_ref: str,
    fallback_unit_number: int | None,
) -> PacketProviderReceipt:
    try:
        provider_contract = str(payload["contract_version"])
        if provider_contract != _CODINGCASTLE_RECEIPT_VERSION:
            raise ImplementationProviderContractError(
                "packet_provider_receipt_version_mismatch"
            )
        audit = payload.get("audit")
        if not isinstance(audit, Mapping):
            raise TypeError("audit")
        changed = _boolean(payload.get("changed"), "changed")
        current_step = str(payload.get("current_step") or "")
        if (
            flow_unit_ref
            and operation in {PacketProviderOperation.ADD, PacketProviderOperation.EDIT}
            and not changed
            and current_step in {"navigate", "choose_target"}
        ):
            raise PacketProviderRejectedError(
                "packet_provider_target_selection_required"
            )
        raw_delta = audit.get("unit_delta") or []
        if not isinstance(raw_delta, list):
            raise TypeError("unit_delta")
        units: tuple[PacketProviderUnitReceipt, ...] = ()
        if flow_unit_ref:
            if len(raw_delta) > 1:
                raise ImplementationProviderContractError(
                    "packet_provider_unit_correlation_ambiguous"
                )
            if raw_delta:
                item = raw_delta[0]
                if not isinstance(item, Mapping):
                    raise TypeError("unit_delta item")
                units = (
                    PacketProviderUnitReceipt(
                        flow_unit_ref=flow_unit_ref,
                        provider_unit_ref=str(item["unit_ref"]),
                        state=str(item["state"]),
                        unit_number=_positive_optional_integer(item.get("number")),
                    ),
                )
            elif operation == PacketProviderOperation.REMOVE:
                units = (
                    PacketProviderUnitReceipt(
                        flow_unit_ref=flow_unit_ref,
                        provider_unit_ref=fallback_provider_unit_ref,
                        state="removed",
                        unit_number=fallback_unit_number,
                    ),
                )
        gaps = payload.get("readiness_gaps") or []
        choices = payload.get("choices") or []
        required_input = payload.get("required_input") or {}
        actions = payload.get("available_actions") or []
        retry = payload.get("retry", {})
        if retry is None:
            retry = {}
        if not isinstance(gaps, list) or not isinstance(choices, list):
            raise TypeError("bounded lists")
        if (
            not isinstance(required_input, Mapping)
            or not isinstance(actions, list)
            or not isinstance(retry, Mapping)
        ):
            raise TypeError("scaffolding")
        return PacketProviderReceipt(
            provider_kind="codingcastle",
            provider_contract_version=provider_contract,
            provider_packet_ref=str(audit["packet_ref"]),
            provider_packet_revision=_nonnegative_integer(
                audit.get("packet_revision"), "packet_revision"
            ),
            provider_state=str(payload["packet_state"]),
            binding_epoch=_nonnegative_integer(
                audit.get("binding_epoch", 0), "binding_epoch"
            ),
            event_seq=_nonnegative_integer(audit.get("event_seq", 0), "event_seq"),
            changed=changed,
            unit_receipts=units,
            unit_receipts_truncated=_boolean(
                audit.get("unit_delta_truncated", False),
                "unit_delta_truncated",
            ),
            readiness_gaps=tuple(str(item) for item in gaps),
            readiness_gaps_truncated=_boolean(
                payload.get("readiness_gaps_truncated", False),
                "readiness_gaps_truncated",
            ),
            current_step=current_step,
            question=str(payload.get("question") or ""),
            choices=tuple(dict(item) for item in choices if isinstance(item, Mapping)),
            choices_truncated=_boolean(
                payload.get("choices_truncated", False), "choices_truncated"
            ),
            required_input=dict(required_input),
            available_actions=tuple(str(item) for item in actions),
            run_phase=str(payload.get("technical_phase") or "idle"),
            provider_job_ref=str(audit.get("job_ref") or ""),
            retry=dict(retry),
        )
    except PacketProviderRejectedError:
        raise
    except ImplementationProviderContractError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ImplementationProviderContractError(
            "packet_provider_receipt_invalid"
        ) from exc


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(field)
    return value


def _positive_optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypeError("unit_number")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(field)
    return value


__all__ = [
    "CodingCastlePacketProjectBinding",
    "McpCodingCastlePacketProvider",
]
