"""Validate bounded groups of campaign obligation decisions and bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from flow_of_work_mcp.core.domain.assurance import validate_case_id
from flow_of_work_mcp.core.domain.campaign_authority import (
    CampaignObligationDecision,
    validate_obligation_id,
)
from flow_of_work_mcp.core.errors import OperationPreEffectError


MAX_CAMPAIGN_AUTHORING_ENTRIES = 64


def batch_rejection(field: str, value: object, message: str) -> OperationPreEffectError:
    return OperationPreEffectError(
        "campaign_obligation_batch_rejected",
        message,
        field=field,
        received_value=value,
        rule="The bounded group must target the current campaign and contain valid, unique entries.",
        resolution="Inspect the campaign, correct this input and submit against its current fingerprint.",
    )


@dataclass(frozen=True)
class ObligationAuthoringBatch:
    decisions: tuple[dict[str, str], ...]
    bindings: tuple[dict[str, str], ...]

    @classmethod
    def parse(cls, value: object) -> ObligationAuthoringBatch:
        field = "obligation_batch"
        if not isinstance(value, Mapping) or value.keys() - {"decisions", "bindings"}:
            raise batch_rejection(field, "", "Use a group object with decisions and bindings arrays.")
        decisions = value.get("decisions", [])
        bindings = value.get("bindings", [])
        if not isinstance(decisions, list) or not isinstance(bindings, list):
            raise batch_rejection(field, "", "Each group collection must be an array.")
        count = len(decisions) + len(bindings)
        if not 1 <= count <= MAX_CAMPAIGN_AUTHORING_ENTRIES:
            raise batch_rejection(field, count, f"Supply 1 to {MAX_CAMPAIGN_AUTHORING_ENTRIES} total entries.")
        return cls(
            _entries("decisions", decisions, ("obligation_id", "decision", "rationale"), ("obligation_id",)),
            _entries("bindings", bindings, ("case_id", "obligation_id", "coverage_intent"), ("case_id", "obligation_id")),
        )


def _entries(
    collection: str, entries: list[object], fields: tuple[str, ...], identity: tuple[str, ...]
) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for index, entry in enumerate(entries):
        path = f"obligation_batch.{collection}[{index}]"
        if not isinstance(entry, Mapping) or set(entry) != set(fields):
            raise batch_rejection(path, "", f"Supply exactly these fields: {', '.join(fields)}.")
        item: dict[str, str] = {}
        for field in fields:
            raw = entry[field]
            if not isinstance(raw, str) or not raw.strip():
                raise batch_rejection(f"{path}.{field}", raw, f"{field} must be non-empty text.")
            value = raw.strip()
            try:
                if field == "obligation_id":
                    value = validate_obligation_id(value)
                elif field == "case_id":
                    value = validate_case_id(value)
                elif field == "decision":
                    decision = CampaignObligationDecision(value)
                    if decision is CampaignObligationDecision.UNCLASSIFIED:
                        raise ValueError("unclassified is not an authoring decision")
            except ValueError as exc:
                raise batch_rejection(f"{path}.{field}", raw, str(exc)) from exc
            item[field] = value
        key = tuple(item[field] for field in identity)
        if key in seen:
            raise batch_rejection(path, " / ".join(key), f"Duplicate {collection} entry.")
        seen.add(key)
        values.append(item)
    return tuple(values)
