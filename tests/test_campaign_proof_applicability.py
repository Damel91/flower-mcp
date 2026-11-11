"""Current campaign authority preserves the history of old proof decisions."""

import pytest

from flow_of_work_mcp import ChangeControlService, GovernedChangeDraft, RequirementDraft, RequirementService
from flow_of_work_mcp.application.campaign_authority import qualified_campaign_is_accepted
from flow_of_work_mcp.core.domain.campaign_authority import (
    CampaignCaseSemanticDraft, CampaignObligationDecision, CampaignScopeDraft,
)
from flow_of_work_mcp.core.errors import AssuranceBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime


@pytest.fixture
def campaign(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite", import_root=tmp_path)
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Owned campaign", actor="operator")
    requirement_ids = tuple(requirements.register("alpha", RequirementDraft(
        title=f"Proof {index}", statement=f"Observe state {index}.", category="functional",
    ), actor="operator")["requirement_id"] for index in (1, 2))
    change = ChangeControlService(runtime.ledger).create_change("alpha", GovernedChangeDraft(
        title="Bounded campaign", rationale="Qualify the two states.", requirement_ids=requirement_ids,
    ), actor="engineer")
    scope = CampaignScopeDraft(change_id=change["change_id"], requirement_ids=requirement_ids[:1],
                               invariants=("Keep one active owner.", "Keep the same profile."))
    first_case = CampaignCaseSemanticDraft(
        title="Observe the state", purpose="Check the original obligations.", case_kind="regression",
        action="Read the state.", expected_outcome="The expected state is returned.",
        prohibited_outcome="No state is returned.", observation_point="The response.",
    )
    start = runtime.ledger.start_campaign_authority(
        "alpha", title="Campaign", scope=scope, first_case=first_case, actor="engineer",
    )
    state = runtime.ledger.derive_campaign_obligations("alpha", start["campaign_id"], actor="engineer")
    try:
        yield runtime, state, requirement_ids
    finally:
        runtime.close()


def test_scope_edit_refreshes_only_affected_obligations(campaign):
    runtime, state, requirement_ids = campaign
    campaign_id = state["campaign_id"]
    original = {item["statement"]: item["obligation_id"] for item in state["obligations"]}
    changed = original["Keep one active owner."]
    state = runtime.ledger.decide_campaign_obligation(
        "alpha", campaign_id, changed, decision=CampaignObligationDecision.OUT_OF_SCOPE,
        rationale="Original scope excluded the case.", actor="engineer",
    )
    scope = CampaignScopeDraft(change_id=state["change_id"], requirement_ids=requirement_ids,
                               invariants=("Keep the same profile.", "Keep two active owners."))
    state = runtime.ledger.edit_campaign_authority_scope(
        "alpha", campaign_id, title="Expanded campaign", scope=scope, actor="engineer",
        expected_fingerprint=state["fingerprint"],
    )
    assert state["obligation_applicability"] == {"current": False, "candidates_pending": 2, "stale_active": 1}
    assert {item["obligation_id"] for item in state["obligations"]} == set(original.values()) - {changed}
    historical = state["obligation_history"][0]
    assert historical["obligation_id"] == changed and not historical["fresh"]
    assert historical["decision"] == "out_of_scope"
    gate = runtime.campaign_authority.inspect("alpha", campaign_id=campaign_id)["lifecycle_gate"]
    assert gate["next_action"]["operation"] == "derive_obligations"
    with pytest.raises(AssuranceBlockedError, match="campaign_obligation_stale"):
        runtime.ledger.decide_campaign_obligation(
            "alpha", campaign_id, changed, decision=CampaignObligationDecision.REQUIRED,
            rationale="A stale decision cannot be edited.", actor="engineer",
        )
    state = runtime.ledger.derive_campaign_obligations("alpha", campaign_id, actor="engineer")
    assert state["obligation_applicability"]["current"]
    refreshed = {item["statement"]: item["obligation_id"] for item in state["obligations"]}
    assert refreshed["Keep the same profile."] == original["Keep the same profile."]
    assert refreshed["Keep two active owners."] != changed
    assert state["obligation_history"] == [historical]


def test_exception_preserves_terminal_history_after_upstream_revision(campaign):
    runtime, state, requirement_ids = campaign
    campaign_id = state["campaign_id"]
    obligation = next(item for item in state["obligations"] if item["source_ref"] == requirement_ids[0])
    runtime.ledger.bind_campaign_case_obligation(
        "alpha", campaign_id, "CASE-000001", obligation["obligation_id"],
        coverage_intent="Observe the original requirement.", actor="engineer",
    )

    def traceability_row():
        rows = runtime.milestone_traceability.projection("alpha")["rows"]
        return next(row for row in rows if row["requirement_id"] == requirement_ids[0])

    accepted = runtime.campaign_authority.accept_exception(
        "alpha", campaign_id, obligation_ids=[item["obligation_id"] for item in state["obligations"]],
        evidence_gaps=["Proof remains pending."], risk_authority="stakeholder:owner",
        disposition_reference="decision:original-scope", actor="operator", request_id="accept-exception",
    )
    original = accepted["campaign"]["exception"]
    assert original["current"] and qualified_campaign_is_accepted(accepted)
    assert traceability_row()["accepted_campaign_ids"] == [campaign_id]
    RequirementService(runtime.ledger).revise("alpha", requirement_ids[0], RequirementDraft(
        title="Revised proof", statement="Observe the changed state.", category="functional",
    ), actor="operator", rationale="The intended outcome changed.")
    projection = runtime.campaign_authority.inspect("alpha", campaign_id=campaign_id)
    exception = projection["campaign"]["exception"]
    assert projection["campaign"]["status"] == "accepted_exception"
    assert projection["lifecycle_gate"]["state"] == "inactive"
    assert not qualified_campaign_is_accepted(projection)
    assert exception == {**original, "current": False, "applicability": "historical_on_original_basis"}
    traceability = traceability_row()
    assert traceability["accepted_campaign_ids"] == []
    assert "campaign_missing" in traceability["acceptance_blockers"]
    assert traceability["campaigns"][0]["acceptance_applicability"] == "historical_on_original_basis"
    assert traceability["campaigns"][0]["cases"][0]["case_id"] == "CASE-000001"
    with pytest.raises(AssuranceBlockedError, match="campaign_inactive"):
        runtime.ledger.derive_campaign_obligations("alpha", campaign_id, actor="engineer")
