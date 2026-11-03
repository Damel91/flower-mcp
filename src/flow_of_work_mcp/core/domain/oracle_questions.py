"""One current answer authority for campaign projections and transactional writes."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.campaign_authority import ORACLE_SNAPSHOT_CONTRACT_VERSION
from flow_of_work_mcp.core.domain.oracle_ir import ORACLE_IR_OPERATOR_PROFILE


def oracle_ir_refinement_applicable(oracle: Mapping[str, object]) -> bool:
    """Optional unit IR must not turn source/live semantics into deterministic ones."""
    payload = oracle.get("payload") or {}
    fields = payload.get("semantic_fields") or {}
    return (
        payload.get("contract_version") == ORACLE_SNAPSHOT_CONTRACT_VERSION
        and payload.get("oracle_kind") == "behavior"
        and fields.get("execution_class") == "deterministic"
        and fields.get("operator_profile", ORACLE_IR_OPERATOR_PROFILE) == ORACLE_IR_OPERATOR_PROFILE
    )


def _binding_current(binding: Mapping[str, object], oracle: Mapping[str, object]) -> bool:
    return bool(oracle.get("current")
        and oracle["revision"] == binding["oracle_revision"]
        and oracle["fingerprint"] == binding["oracle_fingerprint"]
        and oracle.get("dependency_fingerprint") == oracle.get("current_dependency_fingerprint"))


def oracle_source_repair(state: Mapping[str, object]) -> dict[str, object] | None:
    """Address missing/stale required source authority without guessing a case ID."""
    oracles = {o["oracle_id"]: o for o in state.get("oracles", [])}
    bindings = {b["case_id"]: b for b in state.get("oracle_bindings", [])}
    for case in sorted(state.get("cases", []), key=lambda c: c["case_id"]):
        if not case.get("required"):
            continue
        binding = bindings.get(case["case_id"])
        if binding is None:
            return {"case_id": case["case_id"], "reason": "oracle_missing"}
        oracle = oracles.get(binding["oracle_id"])
        if (not oracle or not _binding_current(binding, oracle)
                or (oracle.get("status") != "constructible" and not oracle.get("questions"))):
            return {"case_id": case["case_id"], "oracle_id": binding["oracle_id"],
                    "reason": "oracle_source_authority_not_current"}
    return None


def current_oracle_question(state: Mapping[str, object]) -> dict[str, object] | None:
    """Source questions globally precede optional IR; only exact bound heads qualify.

    Consume the full authority snapshot, never a paginated presentation. Retained
    questions from unsupported historical IR do not become execution authority.
    """
    oracles = {o["oracle_id"]: o for o in state.get("oracles", [])}
    source: list[dict[str, object]] = []
    ir: list[dict[str, object]] = []
    bindings = sorted(state.get("oracle_bindings", []),
                      key=lambda b: (b["case_id"], b["oracle_id"]))
    bound_cases = set()
    source_incomplete = False
    for binding in bindings:
        bound_cases.add(binding["case_id"])
        oracle = oracles.get(binding["oracle_id"])
        if not oracle or not _binding_current(binding, oracle):
            source_incomplete = True
            continue
        identity = {"case_id": binding["case_id"], "oracle_id": binding["oracle_id"],
                    "oracle_revision": binding["oracle_revision"]}
        source_questions = oracle.get("questions", [])
        source.extend({**question, **identity} for question in source_questions)
        if oracle.get("status") != "constructible":
            source_incomplete = True
        if not source_questions and oracle_ir_refinement_applicable(oracle):
            ir.extend({**question, **identity} for question in oracle.get("oracle_ir_questions", []))
    if source:
        return source[0]
    if source_incomplete or any(c.get("required") and c["case_id"] not in bound_cases
                                for c in state.get("cases", [])):
        return None
    return ir[0] if ir else None
