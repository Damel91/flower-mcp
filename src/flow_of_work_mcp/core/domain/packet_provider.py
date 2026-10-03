"""Flow-owned semantic commands and provider evidence receipts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from typing import Mapping, Sequence

from flow_of_work_mcp.core.domain.identifiers import required_text


PACKET_PROVIDER_COMMAND_VERSION = "flow.packet_provider.semantic.v2"
PACKET_PROVIDER_RECEIPT_VERSION = "flow.packet_provider.receipt.v2"
PACKET_PROVIDER_OPERATIONS = frozenset(
    {"add", "edit", "remove", "start", "stop", "status"}
)
_MAX_COMMAND_BYTES = 131_072
_MAX_RECEIPT_BYTES = 262_144
_MAX_RECEIPT_UNITS = 64
_MAX_READINESS_GAPS = 16
_MAX_CHOICES = 64
_MAX_RETRY_COUNTER = (2**63) - 1
_RETRY_FIELDS = frozenset(
    {
        "state",
        "current_layer",
        "current_attempt",
        "current_cause",
        "current_result",
        "consumed",
        "residual",
        "blocker",
    }
)
_RETRY_CONSUMED_FIELDS = frozenset({"cycles", "model_calls", "processes"})
_RETRY_RESIDUAL_FIELDS = frozenset(
    {"cycles", "model_calls", "processes", "wall_time_ms"}
)
_ACTIVE_PROVIDER_STATES = frozenset({"queued", "running", "stopping"})
_ACTIVE_PROVIDER_PHASES = frozenset(
    {
        "execution",
        "execution_recovery",
        "queued",
        "remediating",
        "running",
        "stopping",
        "technical_remediation",
    }
)
_TERMINAL_PROVIDER_STATES = frozenset(
    {"abandoned", "blocked", "completed", "failed", "partial", "stopped"}
)
_TERMINAL_PROVIDER_PHASES = frozenset(
    {
        "blocked",
        "completed",
        "completion",
        "execution_blocked",
        "execution_failed",
        "failed",
        "partial",
        "planning_reconciliation_blocked",
        "recovery_blocked",
        "stopped",
    }
)
_FORBIDDEN_PROVIDER_INPUT_KEYS = frozenset(
    {
        "binding_epoch",
        "binding_ref",
        "chunk_id",
        "client_unit_key",
        "continuation_ref",
        "event_seq",
        "expected_packet_revision",
        "expected_provider_revision",
        "graph_revision",
        "idempotency_key",
        "packet_ref",
        "projection_fingerprint",
        "projection_ref",
        "provider_binding_ref",
        "provider_packet_ref",
        "provider_packet_revision",
        "provider_unit_ref",
        "revision_vector",
        "run_id",
        "selected_candidates",
        "selection_ref",
        "target_handle",
        "target_set_id",
        "unit_ref",
    }
)
_FLOW_BUREAUCRACY_KEYS = frozenset(
    {
        "acceptance",
        "campaign_ids",
        "change_id",
        "delivery_fingerprint",
        "flow_packet_ref",
        "flow_session_ref",
        "flow_spec_revision",
        "flow_unit_ref",
        "goal_ids",
        "milestone_id",
        "rationale",
        "requirement_ids",
    }
)


class PacketProviderMode(StrEnum):
    AGNOSTIC = "agnostic"
    AUTO = "auto"
    REQUIRED = "required"


class PacketProviderOperation(StrEnum):
    ADD = "add"
    EDIT = "edit"
    REMOVE = "remove"
    START = "start"
    STOP = "stop"
    STATUS = "status"


class PacketProviderOutboxState(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    UNKNOWN = "unknown"
    DELIVERED = "delivered"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PacketProviderCommand:
    """One durable Flow semantic delivery, free of provider mechanics."""

    flow_session_ref: str
    flow_packet_ref: str
    flow_spec_revision: int
    operation: PacketProviderOperation | str
    semantic_input: Mapping[str, object] = field(default_factory=dict)
    flow_unit_ref: str = ""
    delivery_fingerprint: str = ""
    contract_version: str = PACKET_PROVIDER_COMMAND_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PACKET_PROVIDER_COMMAND_VERSION:
            raise ValueError("packet provider command contract is unsupported")
        object.__setattr__(
            self,
            "flow_session_ref",
            required_text(self.flow_session_ref, "flow_session_ref"),
        )
        object.__setattr__(
            self,
            "flow_packet_ref",
            required_text(self.flow_packet_ref, "flow_packet_ref"),
        )
        if (
            isinstance(self.flow_spec_revision, bool)
            or not isinstance(self.flow_spec_revision, int)
            or self.flow_spec_revision <= 0
        ):
            raise ValueError("flow_spec_revision must be positive")
        operation = PacketProviderOperation(self.operation)
        object.__setattr__(self, "operation", operation)
        unit_ref = str(self.flow_unit_ref or "").strip()
        fingerprint = str(self.delivery_fingerprint or "").strip()
        if len(unit_ref) > 256 or len(fingerprint) > 256:
            raise ValueError("packet provider correlation exceeds the supported bound")
        if operation != PacketProviderOperation.STATUS and not fingerprint:
            raise ValueError("packet provider mutation requires delivery_fingerprint")
        if not isinstance(self.semantic_input, Mapping):
            raise ValueError("packet provider semantic input must be an object")
        semantic = _canonical_mapping(
            self.semantic_input, "packet provider semantic input"
        )
        if operation in {
            PacketProviderOperation.START,
            PacketProviderOperation.STOP,
            PacketProviderOperation.STATUS,
        } and semantic:
            raise ValueError(f"{operation.value} semantic input must be empty")
        forbidden = _forbidden_keys(semantic)
        if forbidden:
            raise ValueError(
                "packet provider semantic input contains forbidden authority: "
                + sorted(forbidden)[0]
            )
        encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_COMMAND_BYTES:
            raise ValueError("packet provider command exceeds the supported bound")
        object.__setattr__(self, "flow_unit_ref", unit_ref)
        object.__setattr__(self, "delivery_fingerprint", fingerprint)
        object.__setattr__(self, "semantic_input", semantic)

    def as_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "flow_session_ref": self.flow_session_ref,
            "flow_packet_ref": self.flow_packet_ref,
            "flow_spec_revision": self.flow_spec_revision,
            "flow_unit_ref": self.flow_unit_ref or None,
            "operation": self.operation.value,
            "semantic_input": dict(self.semantic_input),
            "delivery_fingerprint": self.delivery_fingerprint,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "PacketProviderCommand":
        if not isinstance(payload, Mapping):
            raise ValueError("packet provider command payload must be an object")
        semantic = payload.get("semantic_input", {})
        if not isinstance(semantic, Mapping):
            raise ValueError("packet provider semantic input must be an object")
        revision = payload.get("flow_spec_revision")
        return cls(
            contract_version=str(payload.get("contract_version") or ""),
            flow_session_ref=str(payload.get("flow_session_ref") or ""),
            flow_packet_ref=str(payload.get("flow_packet_ref") or ""),
            flow_spec_revision=revision if isinstance(revision, int) else 0,
            flow_unit_ref=str(payload.get("flow_unit_ref") or ""),
            operation=str(payload.get("operation") or ""),
            semantic_input=semantic,
            delivery_fingerprint=str(payload.get("delivery_fingerprint") or ""),
        )


@dataclass(frozen=True)
class PacketProviderUnitReceipt:
    flow_unit_ref: str
    provider_unit_ref: str
    state: str
    unit_number: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "flow_unit_ref", required_text(self.flow_unit_ref, "flow_unit_ref")
        )
        object.__setattr__(
            self,
            "provider_unit_ref",
            required_text(self.provider_unit_ref, "provider_unit_ref"),
        )
        object.__setattr__(self, "state", required_text(self.state, "state"))
        if len(self.flow_unit_ref) > 256 or len(self.provider_unit_ref) > 256:
            raise ValueError("packet provider unit identity exceeds the supported bound")
        if len(self.state) > 64:
            raise ValueError("packet provider unit state exceeds the supported bound")
        if self.unit_number is not None and (
            isinstance(self.unit_number, bool)
            or not isinstance(self.unit_number, int)
            or self.unit_number <= 0
        ):
            raise ValueError("packet provider unit number must be positive")

    def as_payload(self) -> dict[str, object]:
        return {
            "flow_unit_ref": self.flow_unit_ref,
            "provider_unit_ref": self.provider_unit_ref,
            "state": self.state,
            "unit_number": self.unit_number,
        }


@dataclass(frozen=True)
class PacketProviderReceipt:
    """Bounded provider truth retained by Flow as evidence, never input."""

    provider_kind: str
    provider_contract_version: str
    provider_packet_ref: str
    provider_packet_revision: int
    provider_state: str
    binding_epoch: int
    event_seq: int
    changed: bool
    unit_receipts: tuple[PacketProviderUnitReceipt, ...] = ()
    readiness_gaps: tuple[str, ...] = ()
    current_step: str = ""
    question: str = ""
    choices: tuple[Mapping[str, object], ...] = ()
    required_input: Mapping[str, object] = field(default_factory=dict)
    available_actions: tuple[str, ...] = ()
    run_phase: str = "idle"
    provider_job_ref: str = ""
    retry: Mapping[str, object] = field(default_factory=dict)
    unit_receipts_truncated: bool = False
    readiness_gaps_truncated: bool = False
    choices_truncated: bool = False
    contract_version: str = PACKET_PROVIDER_RECEIPT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PACKET_PROVIDER_RECEIPT_VERSION:
            raise ValueError("packet provider receipt contract is unsupported")
        for field_name in (
            "provider_kind",
            "provider_contract_version",
            "provider_packet_ref",
            "provider_state",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), field_name),
            )
        for field_name in ("provider_packet_revision", "binding_epoch", "event_seq"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if not isinstance(self.changed, bool):
            raise ValueError("changed must be boolean")
        for name in (
            "unit_receipts_truncated",
            "readiness_gaps_truncated",
            "choices_truncated",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("packet provider truncation flags must be boolean")
        units = tuple(self.unit_receipts)
        if len(units) > _MAX_RECEIPT_UNITS or any(
            not isinstance(item, PacketProviderUnitReceipt) for item in units
        ):
            raise ValueError("packet provider unit receipts are invalid")
        gaps = _bounded_text_sequence(
            self.readiness_gaps, _MAX_READINESS_GAPS, "readiness gaps"
        )
        actions = _bounded_text_sequence(
            self.available_actions, 16, "available actions"
        )
        choices = tuple(
            _canonical_mapping(item, "packet provider choice")
            for item in self.choices
        )
        if len(choices) > _MAX_CHOICES:
            raise ValueError("packet provider choices exceed the supported bound")
        required_input = _canonical_mapping(
            self.required_input, "packet provider required input"
        )
        retry = _retry_summary(self.retry)
        object.__setattr__(self, "unit_receipts", units)
        object.__setattr__(self, "readiness_gaps", gaps)
        object.__setattr__(self, "available_actions", actions)
        object.__setattr__(self, "choices", choices)
        object.__setattr__(self, "required_input", required_input)
        object.__setattr__(self, "retry", retry)
        for field_name, fallback in (
            ("current_step", ""),
            ("question", ""),
            ("run_phase", "idle"),
            ("provider_job_ref", ""),
        ):
            value = str(getattr(self, field_name) or fallback).strip()
            if len(value) > 512:
                raise ValueError("packet provider receipt text exceeds the supported bound")
            object.__setattr__(self, field_name, value)
        encoded = json.dumps(self.as_payload(), sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_RECEIPT_BYTES:
            raise ValueError("packet provider receipt exceeds the supported bound")

    @property
    def decision(self) -> Mapping[str, object]:
        """Human scaffolding projection retained for the Flow question gate."""

        return {
            "current_step": self.current_step,
            "question": self.question or None,
            "choices": [dict(item) for item in self.choices],
            "choices_truncated": self.choices_truncated,
            "required_input": dict(self.required_input),
            "available_actions": list(self.available_actions),
        }

    @property
    def continuation_policy(self) -> str:
        return provider_observation_continuation(
            provider_state=self.provider_state,
            run_phase=self.run_phase,
            provider_job_ref=self.provider_job_ref,
        )

    @property
    def terminal(self) -> bool:
        return provider_observation_terminal(
            provider_state=self.provider_state,
            run_phase=self.run_phase,
        )

    def as_payload(self, *, include_choices: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "provider_kind": self.provider_kind,
            "provider_contract_version": self.provider_contract_version,
            "provider_packet_ref": self.provider_packet_ref,
            "provider_packet_revision": self.provider_packet_revision,
            "provider_state": self.provider_state,
            "binding_epoch": self.binding_epoch,
            "event_seq": self.event_seq,
            "changed": self.changed,
            "unit_receipts": [item.as_payload() for item in self.unit_receipts],
            "unit_receipts_truncated": self.unit_receipts_truncated,
            "readiness_gaps": list(self.readiness_gaps),
            "readiness_gaps_truncated": self.readiness_gaps_truncated,
            "current_step": self.current_step,
            "question": self.question or None,
            "choices_truncated": self.choices_truncated,
            "required_input": dict(self.required_input),
            "available_actions": list(self.available_actions),
            "technical": {
                "phase": self.run_phase,
                "job_ref": self.provider_job_ref or None,
                "continuation_policy": self.continuation_policy,
                "terminal": self.terminal,
                "retry": dict(self.retry),
            },
        }
        if include_choices:
            payload["choices"] = [dict(item) for item in self.choices]
        return payload

    def persisted_payload(self) -> dict[str, object]:
        return self.as_payload(include_choices=False)


def _bounded_text_sequence(
    value: Sequence[object], limit: int, field_name: str
) -> tuple[str, ...]:
    values = tuple(str(item or "").strip() for item in value)
    if any(not item or len(item) > 512 for item in values) or len(values) > limit:
        raise ValueError(f"packet provider {field_name} are invalid")
    return values


def provider_observation_active(
    *, provider_state: str, run_phase: str, provider_job_ref: str = ""
) -> bool:
    state = str(provider_state or "").strip().lower()
    phase = str(run_phase or "").strip().lower()
    return (
        state in _ACTIVE_PROVIDER_STATES
        or phase in _ACTIVE_PROVIDER_PHASES
        or (phase == "authoring" and bool(str(provider_job_ref or "").strip()))
    )


def provider_observation_terminal(*, provider_state: str, run_phase: str) -> bool:
    return (
        str(provider_state or "").strip().lower() in _TERMINAL_PROVIDER_STATES
        or str(run_phase or "").strip().lower() in _TERMINAL_PROVIDER_PHASES
    )


def provider_observation_continuation(
    *, provider_state: str, run_phase: str, provider_job_ref: str = ""
) -> str:
    if provider_observation_terminal(
        provider_state=provider_state,
        run_phase=run_phase,
    ):
        return "return_to_model"
    return (
        "host_observe"
        if provider_observation_active(
            provider_state=provider_state,
            run_phase=run_phase,
            provider_job_ref=provider_job_ref,
        )
        else "return_to_model"
    )


def _retry_summary(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("packet provider retry summary must be an object")
    raw = dict(value)
    unknown = set(raw) - _RETRY_FIELDS
    if unknown:
        raise ValueError(
            "packet provider retry summary contains unsupported field: "
            + sorted(unknown)[0]
        )
    if not raw:
        return {}
    result: dict[str, object] = {}
    for field_name in (
        "state",
        "current_layer",
        "current_cause",
        "current_result",
        "blocker",
    ):
        raw_text = raw.get(field_name, "")
        if raw_text is not None and not isinstance(raw_text, str):
            raise ValueError(
                f"packet provider retry {field_name} must be text"
            )
        text = str(raw_text or "").strip()
        if len(text) > 512:
            raise ValueError("packet provider retry text exceeds the supported bound")
        result[field_name] = text
    result["current_attempt"] = _retry_counter(
        raw.get("current_attempt", 0), "current_attempt"
    )
    result["consumed"] = _retry_counters(
        raw.get("consumed", {}), _RETRY_CONSUMED_FIELDS, "consumed"
    )
    result["residual"] = _retry_counters(
        raw.get("residual", {}), _RETRY_RESIDUAL_FIELDS, "residual"
    )
    return result


def _retry_counters(
    value: object, fields: frozenset[str], section: str
) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"packet provider retry {section} must be an object")
    raw = dict(value)
    unknown = set(raw) - fields
    if unknown:
        raise ValueError(
            f"packet provider retry {section} contains unsupported field: "
            + sorted(unknown)[0]
        )
    return {field: _retry_counter(raw.get(field, 0), field) for field in sorted(fields)}


def _retry_counter(value: object, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_RETRY_COUNTER
    ):
        raise ValueError(f"packet provider retry {field_name} is invalid")
    return value


def _canonical_mapping(value: Mapping[str, object], field_name: str) -> dict[str, object]:
    try:
        encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON values") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be an object")
    return decoded


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if key in _FORBIDDEN_PROVIDER_INPUT_KEYS or key in _FLOW_BUREAUCRACY_KEYS:
                found.add(key)
            found.update(_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys(item))
    return found


__all__ = [
    "PACKET_PROVIDER_COMMAND_VERSION",
    "PACKET_PROVIDER_OPERATIONS",
    "PACKET_PROVIDER_RECEIPT_VERSION",
    "PacketProviderCommand",
    "PacketProviderMode",
    "PacketProviderOperation",
    "PacketProviderOutboxState",
    "PacketProviderReceipt",
    "PacketProviderUnitReceipt",
    "provider_observation_active",
    "provider_observation_continuation",
    "provider_observation_terminal",
]
