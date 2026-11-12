"""Evaluate linked host campaign proof independently of packet execution authority."""
from typing import Mapping

from flow_of_work_mcp.application.grounding_readiness import (
    goal_scope_from_case, live_grounding_readiness,
)
from flow_of_work_mcp.core.domain.campaign_host import (
    independent_host_obligations, required_host_cases,
)


CAMPAIGN_VERIFICATION_KINDS = {
    "deterministic_campaign": ({"deterministic"}, "deterministic_test"),
    "live_campaign": ({"live", "integration"}, "live_test"),
}


def campaign_plan_basis(semantic: Mapping[str, object]) -> dict:
    """Use the campaign's ordinary pre-execution shape for its issued plan pin."""
    return {
        **semantic,
        "status": "planned",
        "cases": [
            {**case, "result": "pending", "evidence_reference": "", "evidence_metadata": {}}
            for case in semantic["cases"]
        ],
    }


def deferred_campaign_proof(snapshot, criterion, intent, report, grounding_audits):
    if intent["kind"] not in CAMPAIGN_VERIFICATION_KINDS:
        return {}

    ref = intent.get("authority_ref", "")
    state = snapshot["deferred_campaigns"].get(ref)
    if state is None:
        return {"proof_reason": "Inspect the accepted plan for an explicit link to a host campaign for this criterion."}

    campaign_id = state["campaign_id"]
    pending = {
        "proof_route": {"tool": "fow_campaign_inspect", "arguments": {
            "project_id": snapshot["project_id"], "campaign_id": campaign_id, "view": "working_sheet",
        }},
    }
    packet = snapshot["packet"]
    packet_id = snapshot["packet_id"]
    same_binding = [item for item in criterion["verification"]
                    if item["kind"] == intent["kind"] and item.get("authority_ref") == ref]
    if len(same_binding) != 1:
        return pending | {"proof_reason": "Resolve multiple declarations sharing this criterion, proof class and campaign."}
    scope = state["scope"]
    obligation_ids = {
        item["obligation_id"] for item in state["obligations"]
        if item["source_kind"] == "packet_criterion"
        and item["source_ref"] == f"{packet_id}:criterion:{intent['criterion']}"
        and item["source_revision"] == str(packet["spec_revision"])
        and item["statement"] == criterion["statement"]
        and item["decision"] == "required" and item["fresh"]
    }
    bound_cases = {
        link["case_id"] for link in state["obligation_bindings"]
        if link["obligation_id"] in obligation_ids
    }
    if (state["change_id"] != snapshot["change_id"]
            or scope.get("milestone_id") not in (None, "", snapshot["change"]["milestone_id"])
            or packet_id not in scope.get("packet_ids", ()) or not bound_cases):
        return pending | {"proof_reason": "Bind a required campaign case to this packet criterion on its current revision."}

    execution_classes, evidence_kind = CAMPAIGN_VERIFICATION_KINDS[intent["kind"]]
    cases = [case for case in required_host_cases(state) if case["case_id"] in bound_cases
             and case["execution_class"] in execution_classes and case["evidence_kind"] == evidence_kind]
    if not cases:
        return pending | {"proof_reason": f"Use a required case with {evidence_kind} evidence in the declared class."}

    completion = state.get("completion") or {}
    if (state["status"] != "passed" or state["qualification"] != "current"
            or not state["obligation_applicability"]["current"] or not completion.get("current")):
        return pending | {"proof_reason": "Complete the linked campaign with proof applicable to its current scope."}

    review = snapshot["repository_review"]
    source = (review.get("source") or {}).get("revision") if review["complete"] else None
    if not source:
        source = report["payload"]["source_revision"] if report else None
    if not source or completion.get("observed_source_revision") != source:
        return pending | {"proof_reason": "Use campaign proof from the exact source of the current packet work."}

    receipts = state["host_execution"]["current_receipts"]
    accepted_receipts = set(completion.get("host_receipt_ids", ()))
    proof = []
    for case in cases:
        case_id = case["case_id"]
        receipt = receipts.get(case_id, {})
        if (independent_host_obligations(state, case_id) or receipt.get("receipt_id") not in accepted_receipts
                or receipt.get("outcome") != "passed" or receipt.get("source_revision") != source):
            continue
        if evidence_kind == "live_test":
            grounding = live_grounding_readiness(
                project_id=snapshot["project_id"], goal_node_ids=goal_scope_from_case(case),
                audits=grounding_audits(snapshot["project_id"]),
            )
            if not grounding["ready"] or grounding.get("source_revision") != source:
                continue
        proof.append({"case_id": case_id, "receipt_id": receipt["receipt_id"]})
    if len(proof) != len(cases):
        return pending | {"proof_reason": "Supply current eligible receipts for the required cases and their proof policy."}
    return {
        "state": "verified",
        "campaign_proof": {"campaign_id": campaign_id, "source_revision": source, "cases": proof,
                           "provenance": "host_reported"},
    }
