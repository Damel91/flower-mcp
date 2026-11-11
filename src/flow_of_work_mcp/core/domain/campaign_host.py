"""Host campaign input and eligibility rules shared by the gate and ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from flow_of_work_mcp.core.domain.assurance import normalize_campaign_case_kind
from flow_of_work_mcp.core.errors import OperationPreEffectError


HOST_CAMPAIGN_OUTCOMES = ("passed", "product_failed", "test_invalid", "environment_failed")


def host_rejection(field: str, value: object, message: str) -> OperationPreEffectError:
    return OperationPreEffectError(
        "campaign_host_action_rejected",
        message,
        field=field,
        received_value=value,
        rule="Host campaign evidence must use the current issued check and its recorded basis.",
        resolution="Inspect the campaign's current action and use its check or attempt reference.",
    )


def _parse_host_fields(value: object, name: str, limits: Mapping[str, int]) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(limits):
        raise host_rejection(name, "", f"Supply these fields: {', '.join(limits)}.")
    fields: dict[str, str] = {}
    for field, maximum in limits.items():
        raw = value[field]
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > maximum:
            raise host_rejection(f"{name}.{field}", raw, f"Supply 1 to {maximum} characters.")
        fields[field] = raw.strip()
    return fields


@dataclass(frozen=True)
class HostCampaignCheck:
    source_revision: str
    execution_profile: str
    check_reference: str

    @classmethod
    def parse(cls, value: object) -> HostCampaignCheck:
        return cls(**_parse_host_fields(value, "host_check", {
            "source_revision": 512, "execution_profile": 512, "check_reference": 1024,
        }))


@dataclass(frozen=True)
class HostCampaignResult:
    attempt_id: str
    source_revision: str
    outcome: str
    evidence_reference: str
    observation: str

    @classmethod
    def parse(cls, value: object) -> HostCampaignResult:
        fields = _parse_host_fields(value, "host_result", {
            "attempt_id": 64, "source_revision": 512, "outcome": 32,
            "evidence_reference": 1024, "observation": 2000,
        })
        if fields["outcome"] not in HOST_CAMPAIGN_OUTCOMES:
            raise host_rejection("host_result.outcome", fields["outcome"], f"Use {', '.join(HOST_CAMPAIGN_OUTCOMES)}.")
        return cls(**fields)


def campaign_case_lane(scope: Mapping[str, object], case: Mapping[str, object]) -> str:
    return str(case.get("execution_lane") or scope.get("execution_lane") or "provider")


def host_case_supported(case: Mapping[str, object]) -> bool:
    if case["execution_class"] not in {"deterministic", "live", "integration"}:
        return False
    evidence_kind = case["evidence_kind"]
    case_kind = normalize_campaign_case_kind(
        case["case_kind"], evidence_kind,
        has_sequence_coverage=bool(case.get("covered_sequence_goal_node_ids")),
    )
    if case_kind in {"negative_case", "boundary_case"}:
        return True
    return ((case_kind, evidence_kind) in {
        ("deterministic_regression", "deterministic_test"), ("live_sequence", "live_test"),
    })


def required_host_cases(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    by_id = {
        item["case_id"]: item for item in state.get("cases", ())
        if item.get("required") and campaign_case_lane(state.get("scope", {}), item) == "host"
    }
    return [by_id[case_id] for case_id in state.get("case_order", ()) if case_id in by_id]


def independent_host_obligations(state: Mapping[str, object], case_id: str) -> list[str]:
    refs = set(state.get("scope", {}).get("independent_proof_refs", ()))
    linked = {
        item["obligation_id"] for item in state.get("obligation_bindings", ())
        if item["case_id"] == case_id
    }
    return [
        str(item["obligation_id"]) for item in state.get("obligations", ())
        if item["obligation_id"] in linked and item["decision"] == "required"
        and (item["source_ref"] in refs or item["subject_ref"] in refs)
    ]


def next_host_case(
    state: Mapping[str, object], observed_source_revision: str = "",
) -> Mapping[str, object] | None:
    execution = state.get("host_execution", {})
    current_source = execution.get("declared_source_revision")
    receipts = execution.get("current_receipts", {})
    for case in required_host_cases(state):
        receipt = receipts.get(case["case_id"], {})
        if (receipt.get("outcome") != "passed"
                or (observed_source_revision and observed_source_revision != current_source)):
            return case
    return None
