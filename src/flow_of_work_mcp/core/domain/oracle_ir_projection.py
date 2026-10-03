"""Deterministic projection of current behavioral-oracle authority into Oracle IR."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Sequence

from flow_of_work_mcp.core.domain.campaign_authority import (
    ORACLE_SNAPSHOT_CONTRACT_VERSION,
    OracleAnswerAuthority,
)
from flow_of_work_mcp.core.domain.oracle_ir import (
    ORACLE_IR_OPERATOR_PROFILE,
    OracleIRCase,
    OracleIRMatcher,
    OracleIRObservation,
    OracleIRObservationSource,
    OracleIRReferenceKind,
    OracleIRSnapshot,
    OracleIRStimulus,
    OracleIRStimulusOperator,
    canonical_typed_value,
)


_MAX_RESIDUALS = 32
_AUTHORITATIVE_ANSWERS = {
    OracleAnswerAuthority.GROUNDED_FACT.value,
    OracleAnswerAuthority.ACCEPTED_DECISION.value,
}
_REQUIRED_FIELDS = (
    "operator_profile",
    "preconditions",
    "stimulus",
    "input_domain",
    "expected_observations",
    "invariants",
    "forbidden_effects",
    "tolerances",
    "expected_failure_transitions",
    "oracle_violation_conditions",
    "execution_class",
    "verification_intent",
)
_OBSERVATION_FIELDS = (
    "preconditions",
    "expected_observations",
    "invariants",
    "forbidden_effects",
    "expected_failure_transitions",
    "oracle_violation_conditions",
)


class OracleIRConstructibilityStatus(StrEnum):
    CONSTRUCTIBLE = "constructible"
    UNCONSTRUCTIBLE = "unconstructible"
    STALE = "stale"


class OracleIRResidualKind(StrEnum):
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    AUTHORITY_INCOMPLETE = "authority_incomplete"


@dataclass(frozen=True)
class OracleIRResidual:
    field_name: str
    kind: OracleIRResidualKind
    detail: str
    value_shape: str

    @property
    def question_id(self) -> str:
        return f"Q-{self.field_name.replace('_', '-')}"

    def as_payload(self) -> dict[str, object]:
        return {
            "question_id": self.question_id,
            "field_name": self.field_name,
            "kind": self.kind.value,
            "detail": self.detail,
            "value_shape": self.value_shape,
            "accepted_authorities": sorted(_AUTHORITATIVE_ANSWERS),
        }


@dataclass(frozen=True)
class OracleIRConstructibility:
    status: OracleIRConstructibilityStatus
    oracle_id: str
    oracle_revision: int
    oracle_fingerprint: str
    dependency_fingerprint: str
    residuals: tuple[OracleIRResidual, ...]
    snapshot: OracleIRSnapshot | None = None

    @property
    def constructible(self) -> bool:
        return self.status == OracleIRConstructibilityStatus.CONSTRUCTIBLE

    @property
    def next_residual(self) -> OracleIRResidual | None:
        return self.residuals[0] if self.residuals else None

    def as_payload(self, *, include_snapshot: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "constructible": self.constructible,
            "oracle_ref": self.oracle_id,
            "oracle_revision": self.oracle_revision,
            "oracle_fingerprint": self.oracle_fingerprint,
            "dependency_fingerprint": self.dependency_fingerprint,
            "operator_profile": ORACLE_IR_OPERATOR_PROFILE,
            "ir_fingerprint": self.snapshot.fingerprint if self.snapshot else "",
            "residuals": [item.as_payload() for item in self.residuals],
            "next_question": (
                self.next_residual.as_payload() if self.next_residual is not None else None
            ),
        }
        if include_snapshot and self.snapshot is not None:
            payload["oracle_ir"] = self.snapshot.as_payload()
        return payload


class _FieldError(ValueError):
    def __init__(self, kind: OracleIRResidualKind, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def compile_oracle_ir(
    source: Mapping[str, object],
    *,
    current_dependency_fingerprint: str = "",
) -> OracleIRConstructibility:
    """Compile one exact current oracle value or return bounded typed residuals."""

    oracle_id = str(source.get("oracle_id") or "")
    revision = _positive_int_or_zero(source.get("revision"))
    fingerprint = str(source.get("fingerprint") or "")
    dependency_fingerprint = str(source.get("dependency_fingerprint") or "")
    residuals: list[OracleIRResidual] = []

    def reject(
        field_name: str,
        kind: OracleIRResidualKind,
        detail: str,
    ) -> None:
        if len(residuals) < _MAX_RESIDUALS and not any(
            item.field_name == field_name for item in residuals
        ):
            residuals.append(
                OracleIRResidual(
                    field_name=field_name,
                    kind=kind,
                    detail=detail[:512],
                    value_shape=_value_shape(field_name),
                )
            )

    if not bool(source.get("current")) or str(source.get("status") or "") == "stale":
        reject(
            "oracle_revision",
            OracleIRResidualKind.STALE,
            "the selected oracle revision is not current",
        )
    expected_dependency = str(
        current_dependency_fingerprint
        or source.get("current_dependency_fingerprint")
        or ""
    )
    if expected_dependency and dependency_fingerprint != expected_dependency:
        reject(
            "dependency_fingerprint",
            OracleIRResidualKind.STALE,
            "the oracle dependency fingerprint no longer matches current authority",
        )
    if residuals:
        return _result(
            OracleIRConstructibilityStatus.STALE,
            oracle_id,
            revision,
            fingerprint,
            dependency_fingerprint,
            residuals,
        )

    payload = source.get("payload")
    if not isinstance(payload, Mapping):
        reject("oracle", OracleIRResidualKind.AMBIGUOUS, "oracle payload must be an object")
        return _result(
            OracleIRConstructibilityStatus.UNCONSTRUCTIBLE,
            oracle_id,
            revision,
            fingerprint,
            dependency_fingerprint,
            residuals,
        )
    if str(payload.get("contract_version") or "") != ORACLE_SNAPSHOT_CONTRACT_VERSION:
        reject(
            "contract_version",
            OracleIRResidualKind.UNSUPPORTED,
            "oracle snapshot contract version is unsupported",
        )
    if str(payload.get("oracle_kind") or "") != "behavior":
        reject(
            "oracle_kind",
            OracleIRResidualKind.UNSUPPORTED,
            "the initial Oracle IR profile supports behavior oracles only",
        )

    fields = payload.get("semantic_fields")
    if not isinstance(fields, Mapping):
        fields = {}
        reject(
            "semantic_fields",
            OracleIRResidualKind.AMBIGUOUS,
            "semantic_fields must be an object",
        )
    field_authority = source.get("field_authority")
    authorities = field_authority if isinstance(field_authority, Mapping) else {}

    parsed: dict[str, object] = {}
    for field_name in _REQUIRED_FIELDS:
        if field_name not in fields:
            reject(
                field_name,
                OracleIRResidualKind.MISSING,
                "an explicit typed value is required",
            )
            continue
        try:
            parsed[field_name] = _parse_field(field_name, fields[field_name])
        except _FieldError as exc:
            reject(field_name, exc.kind, exc.detail)
            continue
        if not _field_is_authoritative(authorities.get(field_name)):
            reject(
                field_name,
                OracleIRResidualKind.AUTHORITY_INCOMPLETE,
                "the typed value requires grounded-fact or accepted-decision provenance",
            )

    subjects = _string_bindings(
        payload.get("subject_bindings"), "subject_bindings", reject
    )
    goals = _string_bindings(
        payload.get("goal_bindings"), "goal_bindings", reject, allow_empty=True
    )
    fixtures = _fixture_bindings(fields, authorities, reject)

    if not residuals:
        stimulus = parsed["stimulus"]
        assert isinstance(stimulus, OracleIRStimulus)
        if stimulus.subject_ref not in subjects:
            reject(
                "stimulus",
                OracleIRResidualKind.STALE,
                "stimulus.subject_ref is not an exact current subject binding",
            )
        _validate_references(fields, subjects, fixtures, reject)

    if residuals:
        status = (
            OracleIRConstructibilityStatus.STALE
            if any(item.kind == OracleIRResidualKind.STALE for item in residuals)
            else OracleIRConstructibilityStatus.UNCONSTRUCTIBLE
        )
        return _result(
            status,
            oracle_id,
            revision,
            fingerprint,
            dependency_fingerprint,
            residuals,
        )

    try:
        case = OracleIRCase(
            preconditions=_observations(parsed["preconditions"]),
            stimulus=_stimulus(parsed["stimulus"]),
            input_domain=parsed["input_domain"],
            observations=_observations(parsed["expected_observations"]),
            invariants=_observations(parsed["invariants"]),
            forbidden_effects=_observations(parsed["forbidden_effects"]),
            tolerances=parsed["tolerances"],
            expected_failure_transitions=_observations(
                parsed["expected_failure_transitions"]
            ),
            oracle_violation_conditions=_observations(
                parsed["oracle_violation_conditions"]
            ),
            execution_class=str(parsed["execution_class"]),
            verification_intent=str(parsed["verification_intent"]),
        )
        snapshot = OracleIRSnapshot(
            oracle_id=oracle_id,
            oracle_revision=revision,
            oracle_fingerprint=fingerprint,
            dependency_fingerprint=dependency_fingerprint,
            authority_reference=str(payload.get("authority_reference") or ""),
            subject_bindings=subjects,
            fixture_bindings=fixtures,
            goal_bindings=goals,
            cases=(case,),
        )
    except (TypeError, ValueError) as exc:
        reject("oracle_ir", OracleIRResidualKind.AMBIGUOUS, str(exc))
        return _result(
            OracleIRConstructibilityStatus.UNCONSTRUCTIBLE,
            oracle_id,
            revision,
            fingerprint,
            dependency_fingerprint,
            residuals,
        )
    return OracleIRConstructibility(
        status=OracleIRConstructibilityStatus.CONSTRUCTIBLE,
        oracle_id=oracle_id,
        oracle_revision=revision,
        oracle_fingerprint=fingerprint,
        dependency_fingerprint=dependency_fingerprint,
        residuals=(),
        snapshot=snapshot,
    )


def _parse_field(field_name: str, value: object) -> object:
    if field_name == "operator_profile":
        if value != ORACLE_IR_OPERATOR_PROFILE:
            raise _FieldError(
                OracleIRResidualKind.UNSUPPORTED,
                f"operator_profile must be {ORACLE_IR_OPERATOR_PROFILE}",
            )
        return value
    if field_name == "stimulus":
        return _parse_stimulus(value)
    if field_name in _OBSERVATION_FIELDS:
        return _parse_observation_sequence(value, field_name)
    if field_name == "execution_class":
        if value != "deterministic":
            raise _FieldError(
                OracleIRResidualKind.UNSUPPORTED,
                "unit-contract IR requires deterministic execution_class",
            )
        return value
    if field_name == "verification_intent":
        if not isinstance(value, str) or not value.strip():
            raise _FieldError(
                OracleIRResidualKind.AMBIGUOUS,
                "verification_intent must be non-empty text",
            )
        return value.strip()
    try:
        return canonical_typed_value(value)
    except ValueError as exc:
        raise _FieldError(OracleIRResidualKind.UNSUPPORTED, str(exc)) from exc


def _parse_stimulus(value: object) -> OracleIRStimulus:
    if not isinstance(value, Mapping):
        raise _FieldError(OracleIRResidualKind.AMBIGUOUS, "stimulus must be an object")
    allowed = {"operator", "subject_ref", "arguments", "keyword_arguments", "value"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _FieldError(
            OracleIRResidualKind.AMBIGUOUS,
            f"stimulus field is unknown: {unknown[0]}",
        )
    arguments = value.get("arguments", [])
    keyword_arguments = value.get("keyword_arguments", {})
    if not isinstance(arguments, list):
        raise _FieldError(OracleIRResidualKind.AMBIGUOUS, "arguments must be a list")
    if not isinstance(keyword_arguments, Mapping):
        raise _FieldError(
            OracleIRResidualKind.AMBIGUOUS,
            "keyword_arguments must be an object",
        )
    try:
        operator = OracleIRStimulusOperator(str(value.get("operator") or ""))
    except ValueError as exc:
        raise _FieldError(
            OracleIRResidualKind.UNSUPPORTED,
            "stimulus operator is unsupported",
        ) from exc
    try:
        return OracleIRStimulus(
            operator=operator,
            subject_ref=str(value.get("subject_ref") or ""),
            arguments=tuple(arguments),
            keyword_arguments=dict(keyword_arguments),
            value=value.get("value"),
            has_value="value" in value,
        )
    except ValueError as exc:
        raise _FieldError(OracleIRResidualKind.AMBIGUOUS, str(exc)) from exc


def _parse_observation_sequence(
    value: object, field_name: str
) -> tuple[OracleIRObservation, ...]:
    if not isinstance(value, list) or len(value) > 128:
        raise _FieldError(
            OracleIRResidualKind.AMBIGUOUS,
            f"{field_name} must be a bounded list",
        )
    result: list[OracleIRObservation] = []
    allowed = {"source", "matcher", "path", "expected"}
    for item in value:
        if not isinstance(item, Mapping):
            raise _FieldError(
                OracleIRResidualKind.AMBIGUOUS,
                f"{field_name} entries must be objects",
            )
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise _FieldError(
                OracleIRResidualKind.AMBIGUOUS,
                f"{field_name} field is unknown: {unknown[0]}",
            )
        path = item.get("path", [])
        if not isinstance(path, list) or not all(isinstance(part, str) for part in path):
            raise _FieldError(
                OracleIRResidualKind.AMBIGUOUS,
                f"{field_name}.path must be a list of strings",
            )
        try:
            source = OracleIRObservationSource(str(item.get("source") or ""))
            matcher = OracleIRMatcher(str(item.get("matcher") or ""))
        except ValueError as exc:
            raise _FieldError(
                OracleIRResidualKind.UNSUPPORTED,
                f"{field_name} contains an unsupported source or matcher",
            ) from exc
        try:
            result.append(
                OracleIRObservation(
                    source=source,
                    matcher=matcher,
                    expected=item.get("expected"),
                    has_expected="expected" in item,
                    path=tuple(path),
                )
            )
        except ValueError as exc:
            raise _FieldError(OracleIRResidualKind.AMBIGUOUS, str(exc)) from exc
    return tuple(result)


def _field_is_authoritative(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    authority = str(value.get("authority") or "")
    provenance = value.get("provenance")
    return authority in _AUTHORITATIVE_ANSWERS and isinstance(provenance, list) and bool(
        provenance
    ) and all(isinstance(item, str) and item.strip() for item in provenance)


def _string_bindings(
    value: object,
    field_name: str,
    reject: Callable[[str, OracleIRResidualKind, str], None],
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        reject(
            field_name,
            OracleIRResidualKind.AMBIGUOUS,
            f"{field_name} must be a non-empty list of strings",
        )
        return ()
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        reject(
            field_name,
            OracleIRResidualKind.AMBIGUOUS,
            f"{field_name} must be unique",
        )
        return ()
    return normalized


def _fixture_bindings(
    fields: Mapping[str, object],
    authorities: Mapping[str, object],
    reject: Callable[[str, OracleIRResidualKind, str], None],
) -> tuple[str, ...]:
    if "fixture_bindings" not in fields:
        return ()
    value = fields["fixture_bindings"]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        reject(
            "fixture_bindings",
            OracleIRResidualKind.AMBIGUOUS,
            "fixture_bindings must be a list of strings",
        )
        return ()
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        reject(
            "fixture_bindings",
            OracleIRResidualKind.AMBIGUOUS,
            "fixture_bindings must be unique",
        )
        return ()
    if not _field_is_authoritative(authorities.get("fixture_bindings")):
        reject(
            "fixture_bindings",
            OracleIRResidualKind.AUTHORITY_INCOMPLETE,
            "fixture bindings require accepted provenance",
        )
    return result


def _validate_references(
    fields: Mapping[str, object],
    subjects: Sequence[str],
    fixtures: Sequence[str],
    reject: Callable[[str, OracleIRResidualKind, str], None],
) -> None:
    for field_name in _REQUIRED_FIELDS:
        for reference in _walk_references(fields.get(field_name)):
            kind = str(reference.get("ref_kind") or "")
            ref = str(reference.get("ref") or "")
            if kind == OracleIRReferenceKind.SUBJECT.value and ref not in subjects:
                reject(
                    field_name,
                    OracleIRResidualKind.STALE,
                    f"subject_ref {ref!r} is not a current subject binding",
                )
            elif kind == OracleIRReferenceKind.FIXTURE.value and ref not in fixtures:
                reject(
                    "fixture_bindings",
                    OracleIRResidualKind.MISSING,
                    f"fixture_ref {ref!r} has no accepted fixture binding",
                )
            elif kind == OracleIRReferenceKind.PRIOR_RESULT.value:
                reject(
                    field_name,
                    OracleIRResidualKind.UNSUPPORTED,
                    "prior_result_ref is unsupported by the initial single-case compiler",
                )


def _walk_references(value: object) -> Sequence[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        if set(value) == {"ref_kind", "ref"}:
            found.append(value)
        else:
            for child in value.values():
                found.extend(_walk_references(child))
    elif isinstance(value, list | tuple):
        for child in value:
            found.extend(_walk_references(child))
    return found


def _observations(value: object) -> tuple[OracleIRObservation, ...]:
    assert isinstance(value, tuple)
    return value


def _stimulus(value: object) -> OracleIRStimulus:
    assert isinstance(value, OracleIRStimulus)
    return value


def _positive_int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _value_shape(field_name: str) -> str:
    shapes = {
        "operator_profile": ORACLE_IR_OPERATOR_PROFILE,
        "stimulus": "{operator, subject_ref, arguments?, keyword_arguments?, value?}",
        "preconditions": "[{source, matcher, path?, expected?}]",
        "expected_observations": "[{source, matcher, path?, expected?}]",
        "invariants": "[{source, matcher, path?, expected?}]",
        "forbidden_effects": "[{source, matcher, path?, expected?}]",
        "expected_failure_transitions": "[{source, matcher, path?, expected?}]",
        "oracle_violation_conditions": "[{source, matcher, path?, expected?}]",
        "execution_class": "deterministic",
        "verification_intent": "non-empty text",
        "fixture_bindings": "[accepted fixture reference]",
    }
    return shapes.get(field_name, "canonical typed value")


def _result(
    status: OracleIRConstructibilityStatus,
    oracle_id: str,
    revision: int,
    fingerprint: str,
    dependency_fingerprint: str,
    residuals: Sequence[OracleIRResidual],
) -> OracleIRConstructibility:
    return OracleIRConstructibility(
        status=status,
        oracle_id=oracle_id,
        oracle_revision=revision,
        oracle_fingerprint=fingerprint,
        dependency_fingerprint=dependency_fingerprint,
        residuals=tuple(residuals[:_MAX_RESIDUALS]),
    )


__all__ = [
    "OracleIRConstructibility",
    "OracleIRConstructibilityStatus",
    "OracleIRResidual",
    "OracleIRResidualKind",
    "compile_oracle_ir",
]
