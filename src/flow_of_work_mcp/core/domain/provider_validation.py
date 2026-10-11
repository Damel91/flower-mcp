"""Typed, lossless validation context negotiated separately from coding input."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import (
    ContractUse, PlannedContract, VerificationIntent, canonical_json,
    fingerprint, normalize_declarations, number, objects, text,
)

CAPABILITY_VERSION = "codingcastle.packet_validation_capability.v1"
CONTEXT_VERSION = "flow.packet_validation_context.v1"
ACK_VERSION = "codingcastle.packet_validation_ack.v1"
COMMAND_VERSION = "flow.packet_provider.semantic.v3"
RECEIPT_VERSION = "flow.packet_provider.receipt.v3"
CONSUMER_RECEIPT_VERSION = "codingcastle.packet.receipt.v3"
MAX_CONTEXT_BYTES = 131_072
CONTEXT_FIELDS = {
    "contract_version", "authority_fingerprint", "spec_revision", "plan_revision",
    "unit_key", "authority_context", "criteria", "units", "context_sha256",
}
UNIT_FIELDS = {"unit_key", "implements", "provides", "resolved_requires",
               "local_verification", "deferred_verification"}


def sha256(value: object, field: str) -> str:
    result = text(value, field)
    if result != value or len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
        raise ValueError(f"{field} must be a lowercase SHA256")
    return result


def validate_capability(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("provider packet_validation capability must be an object")
    expected = {"contract_version", "command_versions", "context_versions",
                "receipt_versions", "acknowledgement", "materialization"}
    if set(value) != expected:
        raise ValueError("provider packet_validation capability fields are invalid")
    if value["contract_version"] != CAPABILITY_VERSION:
        raise ValueError("provider packet_validation capability version unsupported")
    for field, required in (("command_versions", COMMAND_VERSION),
                            ("context_versions", CONTEXT_VERSION),
                            ("receipt_versions", CONSUMER_RECEIPT_VERSION)):
        versions = value[field]
        if not isinstance(versions, list) or not versions or len(versions) > 8:
            raise ValueError(f"{field} must be a bounded version list")
        normalized = [text(v, field) for v in versions]
        if normalized != versions:
            raise ValueError(f'{field} requires exact wire versions')
        if len(set(versions)) != len(versions) or required not in versions:
            raise ValueError(f"{field} does not support the required contract")
    if value["acknowledgement"] != "exact_context_sha256" or value["materialization"] != "producer_contracts_before_consumers":
        raise ValueError("provider validation acknowledgement/materialization unsupported")
    return dict(value)


def validate_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != CONTEXT_FIELDS:
        raise ValueError("validation context fields are invalid")
    if value["contract_version"] != CONTEXT_VERSION:
        raise ValueError("validation context version unsupported")
    sha256(value["authority_fingerprint"], "authority_fingerprint")
    number(value["spec_revision"], "spec_revision")
    number(value["plan_revision"], "plan_revision")
    text(value["unit_key"], "unit_key", required=False)
    if not isinstance(value["authority_context"], Mapping):
        raise ValueError("authority_context must be an object")
    criteria = objects(value["criteria"], "criteria")
    criterion_numbers = {number(c.get("number")) for c in criteria}
    if len(criterion_numbers) != len(criteria):
        raise ValueError("validation criteria must have unique identities")
    for criterion in criteria:
        text(criterion.get("statement"), "criterion statement")
    units = objects(value["units"], "units")
    by_key = {}
    for unit in units:
        if set(unit) != UNIT_FIELDS:
            raise ValueError("validation unit fields are invalid")
        key = text(unit["unit_key"], "unit_key")
        if key in by_key:
            raise ValueError("validation unit identities must be unique")
        declarations = normalize_declarations({"implements": unit["implements"], "provides": unit["provides"]})
        if not set(declarations["implements"]).issubset(criterion_numbers):
            raise ValueError("validation unit implements an unknown criterion")
        for field, local in (("local_verification", True), ("deferred_verification", False)):
            seen = set()
            for raw in objects(unit[field], field):
                intent = VerificationIntent.from_payload(raw)
                identity = (intent.criterion, intent.kind, intent.statement)
                if identity in seen or (intent.kind == "unit_check") != local or intent.criterion not in criterion_numbers:
                    raise ValueError("verification context is duplicated, unknown or temporally misplaced")
                seen.add(identity)
        by_key[key] = unit
    for unit in units:
        seen = set()
        for use in objects(unit["resolved_requires"], "resolved_requires"):
            if set(use) != {"producer_unit_key", "contract_name", "use", "contract", "temporal_state"}:
                raise ValueError("resolved contract fields are invalid")
            reference = ContractUse.from_payload({k: use[k] for k in ("producer_unit_key", "contract_name", "use")})
            identity = (reference.producer_unit_key, reference.contract_name)
            producer = by_key.get(reference.producer_unit_key)
            contract = PlannedContract.from_payload(use["contract"]).as_payload()
            canonical = next((c for c in (producer or {}).get("provides", []) if c["name"] == reference.contract_name), None)
            if identity in seen or canonical != contract or use["temporal_state"] != "planned":
                raise ValueError("resolved contract must retain its canonical planned producer")
            seen.add(identity)
    body = {k: v for k, v in value.items() if k != "context_sha256"}
    if sha256(value["context_sha256"], "context_sha256") != fingerprint(body):
        raise ValueError("validation context digest mismatch")
    if len(canonical_json(value).encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("validation context exceeds the supported bound")
    return dict(value)


def build_context(projection: Mapping[str, object], *, unit_key: str = "") -> dict[str, object]:
    if projection.get("status") != "closed":
        raise ValueError("validation context requires closed semantic authority")
    pending = list(projection["units"])
    ordered = []
    while pending:
        ready = next((u for u in pending if set(u.get("depends_on", [])).issubset({v["client_unit_key"] for v in ordered})), None)
        if ready is None:
            raise ValueError("validation units have no dependency frontier")
        ordered.append(ready)
        pending.remove(ready)
    context = {
        "contract_version": CONTEXT_VERSION,
        "authority_fingerprint": projection["authority_fingerprint"],
        "spec_revision": projection["spec_revision"], "plan_revision": projection["plan_revision"],
        "unit_key": unit_key, "authority_context": projection["authority_context"],
        "criteria": projection["criteria"],
        "units": [{"unit_key": u["client_unit_key"], "implements": u["implements"], "provides": u["provides"],
                   "resolved_requires": u["resolved_requires"],
                   "local_verification": [v for v in u["verifies"] if v["kind"] == "unit_check"],
                   "deferred_verification": [v for v in u["verifies"] if v["kind"] != "unit_check"]}
                  for u in ordered],
    }
    context["context_sha256"] = fingerprint(context)
    return validate_context(context)


def context_for_unit(context: Mapping[str, object], unit_key: str) -> dict[str, object]:
    body = {k: v for k, v in context.items() if k != "context_sha256"}
    body["unit_key"] = unit_key
    return validate_context({**body, "context_sha256": fingerprint(body)})


def validate_ack(value: object, context: Mapping[str, object] | None = None) -> dict[str, object]:
    expected = {"contract_version", "context_sha256", "authority_fingerprint", "unit_key", "compiled_context_sha256"}
    if not isinstance(value, Mapping) or set(value) != expected or value.get("contract_version") != ACK_VERSION:
        raise ValueError("provider validation acknowledgement fields/version invalid")
    for field in ("context_sha256", "authority_fingerprint", "compiled_context_sha256"):
        sha256(value[field], field)
    text(value["unit_key"], "unit_key", required=False)
    if context is not None and any(value[field] != context[field] for field in ("context_sha256", "authority_fingerprint", "unit_key")):
        raise ValueError("provider validation acknowledgement does not match delivered context")
    return dict(value)
