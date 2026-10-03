"""Closed, provider-neutral Oracle IR value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from typing import Mapping, Sequence

from flow_of_work_mcp.core.domain.identifiers import required_text


ORACLE_IR_CONTRACT_VERSION = "flow.oracle.ir.v1"
ORACLE_IR_OPERATOR_PROFILE = "flow.oracle.unit-contract.v1"

_MAX_DEPTH = 8
_MAX_COLLECTION_ITEMS = 128
_MAX_STRING_CHARS = 8_192
_MAX_CANONICAL_BYTES = 256_000
_NODE_ID_PREFIX = "IRN"


class OracleIRReferenceKind(StrEnum):
    FIXTURE = "fixture_ref"
    SUBJECT = "subject_ref"
    PRIOR_RESULT = "prior_result_ref"


class OracleIRStimulusOperator(StrEnum):
    CALL = "call"
    CONSTRUCT = "construct"
    GET = "get"
    SET = "set"


class OracleIRObservationSource(StrEnum):
    RETURN = "return"
    EXCEPTION = "exception"
    STATE = "state"
    EFFECT = "effect"


class OracleIRMatcher(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    TRUTHY = "truthy"
    FALSEY = "falsey"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"
    CONTAINS = "contains"
    MATCHES = "matches"
    WITHIN = "within"
    IN_RANGE = "in_range"
    RAISES = "raises"


_MATCHERS_REQUIRING_EXPECTED = {
    OracleIRMatcher.EQUALS,
    OracleIRMatcher.NOT_EQUALS,
    OracleIRMatcher.CONTAINS,
    OracleIRMatcher.MATCHES,
    OracleIRMatcher.WITHIN,
    OracleIRMatcher.IN_RANGE,
    OracleIRMatcher.RAISES,
}
_MATCHERS_FORBIDDING_EXPECTED = set(OracleIRMatcher) - _MATCHERS_REQUIRING_EXPECTED


@dataclass(frozen=True)
class OracleIRReference:
    kind: OracleIRReferenceKind
    ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", OracleIRReferenceKind(self.kind))
        object.__setattr__(self, "ref", required_text(self.ref, "reference.ref"))

    def as_payload(self) -> dict[str, str]:
        return {"ref_kind": self.kind.value, "ref": self.ref}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "OracleIRReference":
        _require_exact_fields(payload, {"ref_kind", "ref"}, "reference")
        return cls(
            kind=OracleIRReferenceKind(str(payload.get("ref_kind") or "")),
            ref=str(payload.get("ref") or ""),
        )


@dataclass(frozen=True)
class OracleIRStimulus:
    operator: OracleIRStimulusOperator
    subject_ref: str
    arguments: tuple[object, ...] = ()
    keyword_arguments: Mapping[str, object] | None = None
    value: object | None = None
    has_value: bool = False

    def __post_init__(self) -> None:
        operator = OracleIRStimulusOperator(self.operator)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(
            self, "subject_ref", required_text(self.subject_ref, "stimulus.subject_ref")
        )
        arguments = tuple(canonical_typed_value(item) for item in self.arguments)
        keyword_arguments = canonical_typed_value(dict(self.keyword_arguments or {}))
        if not isinstance(keyword_arguments, dict):  # pragma: no cover
            raise ValueError("stimulus.keyword_arguments must be an object")
        value = canonical_typed_value(self.value) if self.has_value else None
        if operator in {OracleIRStimulusOperator.GET, OracleIRStimulusOperator.SET}:
            if arguments or keyword_arguments:
                raise ValueError(f"stimulus {operator.value} forbids arguments")
        if operator == OracleIRStimulusOperator.SET and not self.has_value:
            raise ValueError("stimulus set requires value")
        if operator != OracleIRStimulusOperator.SET and self.has_value:
            raise ValueError(f"stimulus {operator.value} forbids value")
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "keyword_arguments", keyword_arguments)
        object.__setattr__(self, "value", value)

    @property
    def node_id(self) -> str:
        return _semantic_node_id("stimulus", self._semantic_payload())

    def _semantic_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "operator": self.operator.value,
            "subject_ref": self.subject_ref,
        }
        if self.arguments:
            payload["arguments"] = list(self.arguments)
        if self.keyword_arguments:
            payload["keyword_arguments"] = dict(self.keyword_arguments)
        if self.has_value:
            payload["value"] = self.value
        return payload

    def as_payload(self) -> dict[str, object]:
        return {"node_id": self.node_id, **self._semantic_payload()}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "OracleIRStimulus":
        _require_allowed_fields(
            payload,
            {"node_id", "operator", "subject_ref", "arguments", "keyword_arguments", "value"},
            "stimulus",
        )
        arguments = payload.get("arguments") or []
        keyword_arguments = payload.get("keyword_arguments") or {}
        if not isinstance(arguments, list):
            raise ValueError("stimulus.arguments must be a list")
        if not isinstance(keyword_arguments, Mapping):
            raise ValueError("stimulus.keyword_arguments must be an object")
        value = cls(
            operator=OracleIRStimulusOperator(str(payload.get("operator") or "")),
            subject_ref=str(payload.get("subject_ref") or ""),
            arguments=tuple(arguments),
            keyword_arguments=dict(keyword_arguments),
            value=payload.get("value"),
            has_value="value" in payload,
        )
        _validate_node_id(payload, value.node_id, "stimulus")
        return value


@dataclass(frozen=True)
class OracleIRObservation:
    source: OracleIRObservationSource
    matcher: OracleIRMatcher
    expected: object | None = None
    has_expected: bool = False
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        source = OracleIRObservationSource(self.source)
        matcher = OracleIRMatcher(self.matcher)
        path = tuple(required_text(item, "observation.path") for item in self.path)
        if len(path) > 32:
            raise ValueError("observation.path exceeds 32 segments")
        if matcher in _MATCHERS_REQUIRING_EXPECTED and not self.has_expected:
            raise ValueError(f"matcher {matcher.value} requires expected")
        if matcher in _MATCHERS_FORBIDDING_EXPECTED and self.has_expected:
            raise ValueError(f"matcher {matcher.value} forbids expected")
        if matcher == OracleIRMatcher.RAISES and source != OracleIRObservationSource.EXCEPTION:
            raise ValueError("matcher raises requires exception source")
        expected = canonical_typed_value(self.expected) if self.has_expected else None
        if matcher in {OracleIRMatcher.MATCHES, OracleIRMatcher.RAISES} and not isinstance(
            expected, str
        ):
            raise ValueError(f"matcher {matcher.value} requires a string expected value")
        if matcher == OracleIRMatcher.IN_RANGE and not (
            isinstance(expected, list) and len(expected) == 2
        ):
            raise ValueError("matcher in_range requires a two-item expected list")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "matcher", matcher)
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "path", path)

    @property
    def node_id(self) -> str:
        return _semantic_node_id("observation", self._semantic_payload())

    def _semantic_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": self.source.value,
            "matcher": self.matcher.value,
        }
        if self.path:
            payload["path"] = list(self.path)
        if self.has_expected:
            payload["expected"] = self.expected
        return payload

    def as_payload(self) -> dict[str, object]:
        return {"node_id": self.node_id, **self._semantic_payload()}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "OracleIRObservation":
        _require_allowed_fields(
            payload, {"node_id", "source", "matcher", "path", "expected"}, "observation"
        )
        path = payload.get("path") or []
        if not isinstance(path, list) or not all(isinstance(item, str) for item in path):
            raise ValueError("observation.path must be a list of strings")
        value = cls(
            source=OracleIRObservationSource(str(payload.get("source") or "")),
            matcher=OracleIRMatcher(str(payload.get("matcher") or "")),
            expected=payload.get("expected"),
            has_expected="expected" in payload,
            path=tuple(path),
        )
        _validate_node_id(payload, value.node_id, "observation")
        return value


@dataclass(frozen=True)
class OracleIRCase:
    preconditions: tuple[OracleIRObservation, ...]
    stimulus: OracleIRStimulus
    input_domain: object
    observations: tuple[OracleIRObservation, ...]
    invariants: tuple[OracleIRObservation, ...]
    forbidden_effects: tuple[OracleIRObservation, ...]
    tolerances: object
    expected_failure_transitions: tuple[OracleIRObservation, ...]
    oracle_violation_conditions: tuple[OracleIRObservation, ...]
    execution_class: str
    verification_intent: str

    def __post_init__(self) -> None:
        if self.execution_class != "deterministic":
            raise ValueError("unit-contract IR requires deterministic execution_class")
        object.__setattr__(
            self,
            "verification_intent",
            required_text(self.verification_intent, "verification_intent"),
        )
        object.__setattr__(self, "input_domain", canonical_typed_value(self.input_domain))
        object.__setattr__(self, "tolerances", canonical_typed_value(self.tolerances))
        for field_name in (
            "preconditions",
            "observations",
            "invariants",
            "forbidden_effects",
            "expected_failure_transitions",
            "oracle_violation_conditions",
        ):
            values = tuple(getattr(self, field_name))
            if not all(isinstance(item, OracleIRObservation) for item in values):
                raise ValueError(f"{field_name} must contain observations")
            object.__setattr__(self, field_name, values)
        if not self.observations:
            raise ValueError("unit-contract IR requires at least one observation")

    @property
    def node_id(self) -> str:
        return _semantic_node_id("case", self._semantic_payload())

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "preconditions": [item.as_payload() for item in self.preconditions],
            "stimulus": self.stimulus.as_payload(),
            "input_domain": self.input_domain,
            "observations": [item.as_payload() for item in self.observations],
            "invariants": [item.as_payload() for item in self.invariants],
            "forbidden_effects": [item.as_payload() for item in self.forbidden_effects],
            "tolerances": self.tolerances,
            "expected_failure_transitions": [
                item.as_payload() for item in self.expected_failure_transitions
            ],
            "oracle_violation_conditions": [
                item.as_payload() for item in self.oracle_violation_conditions
            ],
            "execution_class": self.execution_class,
            "verification_intent": self.verification_intent,
        }

    def as_payload(self) -> dict[str, object]:
        return {"node_id": self.node_id, **self._semantic_payload()}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "OracleIRCase":
        _require_exact_fields(
            payload,
            {
                "node_id",
                "preconditions",
                "stimulus",
                "input_domain",
                "observations",
                "invariants",
                "forbidden_effects",
                "tolerances",
                "expected_failure_transitions",
                "oracle_violation_conditions",
                "execution_class",
                "verification_intent",
            },
            "case",
        )
        value = cls(
            preconditions=_observation_sequence(payload["preconditions"], "preconditions"),
            stimulus=OracleIRStimulus.from_payload(
                _mapping(payload["stimulus"], "stimulus")
            ),
            input_domain=payload["input_domain"],
            observations=_observation_sequence(payload["observations"], "observations"),
            invariants=_observation_sequence(payload["invariants"], "invariants"),
            forbidden_effects=_observation_sequence(
                payload["forbidden_effects"], "forbidden_effects"
            ),
            tolerances=payload["tolerances"],
            expected_failure_transitions=_observation_sequence(
                payload["expected_failure_transitions"], "expected_failure_transitions"
            ),
            oracle_violation_conditions=_observation_sequence(
                payload["oracle_violation_conditions"], "oracle_violation_conditions"
            ),
            execution_class=str(payload["execution_class"]),
            verification_intent=str(payload["verification_intent"]),
        )
        _validate_node_id(payload, value.node_id, "case")
        return value


@dataclass(frozen=True)
class OracleIRSnapshot:
    oracle_id: str
    oracle_revision: int
    oracle_fingerprint: str
    dependency_fingerprint: str
    authority_reference: str
    subject_bindings: tuple[str, ...]
    fixture_bindings: tuple[str, ...]
    goal_bindings: tuple[str, ...]
    cases: tuple[OracleIRCase, ...]
    contract_version: str = ORACLE_IR_CONTRACT_VERSION
    operator_profile: str = ORACLE_IR_OPERATOR_PROFILE

    def __post_init__(self) -> None:
        for field_name in (
            "oracle_id",
            "oracle_fingerprint",
            "dependency_fingerprint",
            "authority_reference",
        ):
            object.__setattr__(self, field_name, required_text(getattr(self, field_name), field_name))
        if isinstance(self.oracle_revision, bool) or self.oracle_revision <= 0:
            raise ValueError("oracle_revision must be positive")
        if self.contract_version != ORACLE_IR_CONTRACT_VERSION:
            raise ValueError("unsupported Oracle IR contract version")
        if self.operator_profile != ORACLE_IR_OPERATOR_PROFILE:
            raise ValueError("unsupported Oracle IR operator profile")
        subjects = _unique_texts(self.subject_bindings, "subject_bindings")
        fixtures = _unique_texts(self.fixture_bindings, "fixture_bindings")
        goals = _unique_texts(self.goal_bindings, "goal_bindings")
        cases = tuple(self.cases)
        if not subjects or not cases:
            raise ValueError("Oracle IR requires subject bindings and cases")
        if not all(isinstance(item, OracleIRCase) for item in cases):
            raise ValueError("Oracle IR cases are invalid")
        object.__setattr__(self, "subject_bindings", subjects)
        object.__setattr__(self, "fixture_bindings", fixtures)
        object.__setattr__(self, "goal_bindings", goals)
        object.__setattr__(self, "cases", cases)
        if len(self.canonical_bytes) > _MAX_CANONICAL_BYTES:
            raise ValueError("Oracle IR exceeds 256000 bytes")

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "operator_profile": self.operator_profile,
            "oracle": {
                "oracle_ref": self.oracle_id,
                "revision": self.oracle_revision,
                "fingerprint": self.oracle_fingerprint,
                "dependency_fingerprint": self.dependency_fingerprint,
            },
            "authority": {
                "reference": self.authority_reference,
                "goal_bindings": list(self.goal_bindings),
            },
            "subject_bindings": list(self.subject_bindings),
            "fixture_bindings": list(self.fixture_bindings),
            "cases": [item.as_payload() for item in self.cases],
        }

    @property
    def fingerprint(self) -> str:
        return sha256(self.canonical_bytes).hexdigest()

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json(self._semantic_payload()).encode("utf-8")

    def as_payload(self) -> dict[str, object]:
        return {**self._semantic_payload(), "canonical_ir_fingerprint": self.fingerprint}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "OracleIRSnapshot":
        _require_exact_fields(
            payload,
            {
                "contract_version",
                "operator_profile",
                "oracle",
                "authority",
                "subject_bindings",
                "fixture_bindings",
                "cases",
                "canonical_ir_fingerprint",
            },
            "oracle_ir",
        )
        oracle = _mapping(payload["oracle"], "oracle")
        authority = _mapping(payload["authority"], "authority")
        _require_exact_fields(
            oracle, {"oracle_ref", "revision", "fingerprint", "dependency_fingerprint"}, "oracle"
        )
        _require_exact_fields(authority, {"reference", "goal_bindings"}, "authority")
        subjects = _string_sequence(payload["subject_bindings"], "subject_bindings")
        fixtures = _string_sequence(payload["fixture_bindings"], "fixture_bindings")
        goals = _string_sequence(authority["goal_bindings"], "authority.goal_bindings")
        cases_payload = payload["cases"]
        if not isinstance(cases_payload, list):
            raise ValueError("oracle_ir.cases must be a list")
        value = cls(
            oracle_id=str(oracle["oracle_ref"]),
            oracle_revision=_positive_int(oracle["revision"], "oracle.revision"),
            oracle_fingerprint=str(oracle["fingerprint"]),
            dependency_fingerprint=str(oracle["dependency_fingerprint"]),
            authority_reference=str(authority["reference"]),
            subject_bindings=subjects,
            fixture_bindings=fixtures,
            goal_bindings=goals,
            cases=tuple(OracleIRCase.from_payload(_mapping(item, "case")) for item in cases_payload),
            contract_version=str(payload["contract_version"]),
            operator_profile=str(payload["operator_profile"]),
        )
        if str(payload["canonical_ir_fingerprint"]) != value.fingerprint:
            raise ValueError("Oracle IR fingerprint mismatch")
        return value


def canonical_typed_value(value: object, *, _depth: int = 0) -> object:
    if _depth > _MAX_DEPTH:
        raise ValueError("typed value exceeds maximum depth")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        raise ValueError("typed values require finite decimal strings, not floats")
    if isinstance(value, str):
        if len(value) > _MAX_STRING_CHARS:
            raise ValueError("typed value string exceeds 8192 characters")
        return value
    if isinstance(value, tuple | list):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError("typed value list exceeds 128 items")
        return [canonical_typed_value(item, _depth=_depth + 1) for item in value]
    if isinstance(value, Mapping):
        if set(value) == {"ref_kind", "ref"}:
            return OracleIRReference.from_payload(value).as_payload()
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ValueError("typed value object exceeds 128 keys")
        result: dict[str, object] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str) or not key or len(key) > 256:
                raise ValueError("typed value object keys must be bounded strings")
            if key.startswith("$") or key in {"expression", "source_code", "raw_source"}:
                raise ValueError("typed value contains an executable or reserved field")
            result[key] = canonical_typed_value(value[key], _depth=_depth + 1)
        return result
    raise ValueError(f"unsupported typed value: {type(value).__name__}")


def _observation_sequence(value: object, field_name: str) -> tuple[OracleIRObservation, ...]:
    if not isinstance(value, list) or len(value) > _MAX_COLLECTION_ITEMS:
        raise ValueError(f"{field_name} must be a bounded list")
    return tuple(
        OracleIRObservation.from_payload(_mapping(item, field_name)) for item in value
    )


def _semantic_node_id(kind: str, payload: Mapping[str, object]) -> str:
    digest = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:20]
    return f"{_NODE_ID_PREFIX}-{kind.upper()}-{digest}"


def _validate_node_id(payload: Mapping[str, object], expected: str, field_name: str) -> None:
    supplied = str(payload.get("node_id") or "")
    if supplied != expected:
        raise ValueError(f"{field_name}.node_id does not match semantic content")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_exact_fields(
    value: Mapping[str, object], fields: set[str], field_name: str
) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        detail = missing[0] if missing else unknown[0]
        kind = "missing" if missing else "unknown"
        raise ValueError(f"{field_name} field is {kind}: {detail}")


def _require_allowed_fields(
    value: Mapping[str, object], fields: set[str], field_name: str
) -> None:
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ValueError(f"{field_name} field is unknown: {unknown[0]}")


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return tuple(value)


def _unique_texts(value: Sequence[str], field_name: str) -> tuple[str, ...]:
    result = tuple(required_text(item, field_name) for item in value)
    if len(result) > _MAX_COLLECTION_ITEMS or len(set(result)) != len(result):
        raise ValueError(f"{field_name} must be bounded and unique")
    return result


__all__ = [
    "ORACLE_IR_CONTRACT_VERSION",
    "ORACLE_IR_OPERATOR_PROFILE",
    "OracleIRCase",
    "OracleIRMatcher",
    "OracleIRObservation",
    "OracleIRObservationSource",
    "OracleIRReference",
    "OracleIRReferenceKind",
    "OracleIRSnapshot",
    "OracleIRStimulus",
    "OracleIRStimulusOperator",
    "canonical_typed_value",
]
