"""Architecture admission applies to new decisions, preserving issued history."""
from copy import deepcopy
import json
import sqlite3

import pytest

from flow_of_work_mcp import (
    ChangeControlService, GovernedChangeDraft, ImplementationPacketDraft,
    PacketWorkPlanDraft, SQLiteRequirementLedger, WorkPlanUnit,
)
from flow_of_work_mcp.application.architecture import ArchitectureService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from tests.engineering_cycle_support import minimal_architecture


def prepare(tmp_path, *, architecture="valid", refs=True):
    ledger = SQLiteRequirementLedger(tmp_path / "cycle.sqlite")
    ledger.create_project("alpha", "Bounded architecture admission", actor="engineer")
    service = ArchitectureService(ledger)
    if architecture != "missing":
        value = (minimal_architecture() if architecture != "empty"
                 else {"components": [], "interfaces": [], "decisions": []})
        proposal = service.call("alpha", "propose", actor="engineer", request_id="propose",
                                payload={"expected_revision": 0, "definition": value})
        if architecture != "proposed":
            service.call("alpha", "adopt", actor="engineer", request_id="adopt",
                         payload={"expected_revision": 0, "revision": proposal["revision"],
                                  "rationale": "Investigated engineering boundary."})
    changes = ChangeControlService(ledger)
    requirement = ledger.add_requirement(
        "alpha", title="Preserve selected behavior", statement="The application shall preserve its selected behavior.",
        category="functional", rationale="Bound the engineering increment.", actor="engineer",
    )
    change = changes.create_change("alpha", GovernedChangeDraft(
        title="Bounded work", rationale="Keep architectural decisions recoverable.",
        requirement_ids=(requirement["requirement_id"],)), actor="engineer")
    selected = ({"revision": 1, "kind": "component", "entity_id": "Application"},) if refs and architecture == "valid" else ()
    packet = changes.add_packet("alpha", change["change_id"], ImplementationPacketDraft(
        title="Implement the selected behavior", completion_criteria=("Behavior is preserved.",),
        architecture_refs=selected), actor="engineer")["packets"][0]
    plan = ledger.create_packet_work_plan("alpha", PacketWorkPlanDraft(
        change["change_id"], packet["packet_id"], packet["spec_revision"],
        (WorkPlanUnit(client_unit_key="work", operation_kind="new_file", file_path="src/work.py",
                      instructions=("Implement the bounded behavior.",),
                      unit_checks=("Check the selected behavior.",)),)), actor="engineer", request_id="plan")
    return ledger, service, plan


def transition(ledger, plan, *, status="accepted", request_id="accept", **patch):
    values = dict(status=status, expected_packet_revision=plan["packet_revision"],
                  expected_current_plan_revision=plan["plan_revision"],
                  rationale="Reviewed bounded work and selected engineering authority.",
                  actor="engineer", request_id=request_id)
    values.update(patch)
    return ledger.transition_packet_work_plan("alpha", plan["work_plan_id"], plan["plan_revision"], **values)


def dump(ledger):
    with sqlite3.connect(ledger.database_path) as connection:
        return "\n".join(connection.iterdump())


@pytest.mark.parametrize(("architecture", "refs", "condition"), [
    ("missing", False, "architecture_not_adopted"),
    ("proposed", False, "architecture_not_adopted"),
    ("empty", False, "architecture_components_missing"),
    ("valid", False, "packet_architecture_refs_missing"),
])
def test_new_acceptance_requires_adopted_nonempty_selected_architecture(tmp_path, architecture, refs, condition):
    ledger, _, plan = prepare(tmp_path, architecture=architecture, refs=refs)
    before = dump(ledger)
    with pytest.raises(ChangeControlBlockedError) as caught:
        transition(ledger, plan)
    assert caught.value.reason == "architecture_required"
    assert caught.value.details["architecture_condition"] == condition
    assert caught.value.details["next_tool_call"] == {
        "tool": "fow_architecture", "arguments": {"project_id": "alpha", "operation": "inspect"},
    }
    assert dump(ledger) == before
    assert ledger.packet_work_plan_state("alpha", plan["change_id"], plan["packet_id"])["status"] == "proposed"


def test_acceptance_issues_version_once_and_restart_replays_before_new_architecture_checks(tmp_path):
    ledger, service, plan = prepare(tmp_path)
    accepted = transition(ledger, plan)
    assert accepted["engineering_cycle_version"] == 1
    event = next(e for e in accepted["events"] if e["event_type"] == "work_plan_accepted")
    assert event["payload"]["engineering_cycle_version"] == 1
    proposal = service.call("alpha", "propose", actor="engineer", request_id="remove-components",
        payload={"expected_revision": 1, "definition": {"components": [], "interfaces": [], "decisions": []}})
    service.call("alpha", "adopt", actor="engineer", request_id="adopt-removal",
        payload={"expected_revision": 1, "revision": proposal["revision"], "rationale": "A later explicit authority revision."})
    reopened = SQLiteRequirementLedger(ledger.database_path)
    before = dump(reopened)
    assert transition(reopened, plan) == accepted
    assert dump(reopened) == before


@pytest.mark.parametrize("relevant", [False, True])
def test_selected_currentness_ignores_unrelated_adoption_but_rejects_relevant_drift(tmp_path, relevant):
    ledger, service, plan = prepare(tmp_path)
    changed = deepcopy(minimal_architecture())
    if relevant:
        changed["components"][0]["responsibility"] = "A different governing responsibility."
    else:
        extra = {**changed["components"][0], "id": "Unrelated", "name": "Unrelated"}
        changed["components"].append(extra)
    proposal = service.call("alpha", "propose", actor="engineer", request_id="change",
                           payload={"expected_revision": 1, "definition": changed})
    service.call("alpha", "adopt", actor="engineer", request_id="adopt-change",
                 payload={"expected_revision": 1, "revision": proposal["revision"], "rationale": "Investigated changed architecture."})
    before = dump(ledger)
    if relevant:
        with pytest.raises(ChangeControlBlockedError) as caught:
            transition(ledger, plan)
        assert caught.value.details["architecture_condition"] == "architecture_authority_stale"
        assert dump(ledger) == before
    else:
        assert transition(ledger, plan)["engineering_cycle_version"] == 1


def test_reject_and_stale_precedence_do_not_require_architecture(tmp_path):
    ledger, _, plan = prepare(tmp_path, architecture="missing")
    before = dump(ledger)
    with pytest.raises(RequirementConflictError, match="stale current work-plan"):
        transition(ledger, plan, expected_current_plan_revision=0)
    assert dump(ledger) == before
    rejected = transition(ledger, plan, status="rejected", request_id="reject")
    assert rejected["engineering_cycle_version"] is None
    assert rejected["events"][-1]["payload"] == {"rationale": "Reviewed bounded work and selected engineering authority."}


def test_historical_accepted_event_remains_unenrolled_on_read_and_exact_replay(tmp_path):
    ledger, _, plan = prepare(tmp_path)
    accepted = transition(ledger, plan)
    # Model an already-issued pre-policy database fixture, never a runtime migration.
    with sqlite3.connect(ledger.database_path) as connection:
        event = next(e for e in accepted["events"] if e["event_type"] == "work_plan_accepted")
        payload = {key: value for key, value in event["payload"].items() if key != "engineering_cycle_version"}
        connection.execute("UPDATE packet_work_plan_events SET payload_json=? WHERE event_id=?", (json.dumps(payload), event["event_id"]))
    reopened = SQLiteRequirementLedger(ledger.database_path)
    before = dump(reopened)
    historical = reopened.packet_work_plan_state("alpha", plan["change_id"], plan["packet_id"])
    assert historical["engineering_cycle_version"] is None
    assert transition(reopened, plan) == historical
    assert dump(reopened) == before
