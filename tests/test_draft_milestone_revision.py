import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from threading import Barrier, Event

import pytest

from flow_of_work_mcp import MilestoneDraft, RequirementDraft, UseCaseDraft
from flow_of_work_mcp.core.errors import BootstrapBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app, handle_bootstrap
from tests.test_guided_bootstrap import prepared


PROJECT = "draft-test"
ACTOR = "fixture-author"


def definition(name, realized, prerequisites=()):
    return MilestoneDraft(name=name, requirement_ids=tuple(realized),
        prerequisite_requirement_ids=tuple(prerequisites), entry_policy={"requires_milestone": []},
        exit_policy={"verification": "Exercise the selected scenario"}, risk_disposition="Local fixture")


@pytest.fixture
def draft(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "draft.sqlite", import_root=tmp_path)
    try:
        boot = runtime.bootstrap.start(PROJECT, project_name="Draft test", path="guided_engineering", actor=ACTOR)
        requirements = [runtime.requirements.register(PROJECT, RequirementDraft(
            title=f"Fixture requirement {index}", statement=f"Provide result {index}",
            category="functional", rationale="Roadmap revision fixture"), actor=ACTOR)["requirement_id"]
            for index in range(1, 4)]
        original = definition("Original scope", requirements[:1])
        milestone = runtime.ledger.promote_milestone(PROJECT, original, actor=ACTOR, request_id="promote")
        yield runtime, boot["bootstrap_id"], requirements, original, milestone
    finally:
        runtime.close()


def roadmap(runtime, boot, *milestones):
    return runtime.guided_bootstrap.roadmap(PROJECT, boot, milestone_ids=list(milestones))


def revision_arguments(view, milestone, *, request_id="edit", **replacements):
    return {"project_id": PROJECT, "bootstrap_id": view["bootstrap_id"],
            "milestone_ids": view["milestone_ids"], "roadmap_fingerprint": view["roadmap_fingerprint"],
            "milestone_revision": {"milestone_id": milestone,
                                   "expected_revision": view["milestone_revisions"][milestone], **replacements},
            "operation": "revise_draft_milestone", "actor": ACTOR, "request_id": request_id}


def map_scenario(runtime, boot, requirement, milestone, *, request_id="mapping"):
    goal = runtime.goals.add_use_case(PROJECT, UseCaseDraft(title="Observe result", actor="Operator",
        objective="Observe a result", observable_outcome="A distinct result is visible"), actor=ACTOR)
    runtime.guided_bootstrap.record_answer(PROJECT, boot, answer={"answer_key": "intent", "question": "What result?",
        "answer": "A distinct result", "kind": "intent", "source_reference": "fixture"}, actor=ACTOR, request_id="answer")
    mapping = {"answer_key": "intent", "answer_revision": 1, "disposition": "consistent", "rationale": "Fixture",
               "canonical_references": {"requirement_ids": [requirement], "goal_node_ids": [goal["goal_node_id"]],
                                        "milestone_ids": [milestone]}}
    runtime.guided_bootstrap.record_correspondence(PROJECT, boot, correspondence=mapping, actor=ACTOR, request_id=request_id)
    return mapping


def confirm(runtime, view):
    return runtime.guided_bootstrap.confirm_roadmap(PROJECT, view["bootstrap_id"], milestone_ids=view["milestone_ids"],
        roadmap_fingerprint=view["roadmap_fingerprint"], confirmation_reference="fixture consent", actor=ACTOR, request_id="confirm")


def audit_events(runtime, boot):
    return runtime.ledger.bootstrap_state(PROJECT, boot)["audit_events"]


def assert_refused(response, reason):
    assert response["status"] == "rejected"
    assert response["reason"] == reason
    assert response["result"]["effect_state"] == "none"
    assert response["result"]["diagnostics"][0]["resolution"]
    assert response["result"]["next_tool_call"]


def test_revision_currentness_and_immutable_receipts_survive_reopen(draft, tmp_path):
    runtime, boot, requirements, original, milestone = draft
    identity = milestone["milestone_id"]
    with runtime.ledger.atomic() as connection:
        # Restore the exact schema-55 promotion event shape that predates revision support.
        connection.execute("UPDATE requirement_events SET payload_json=json_remove(payload_json, '$.milestone_snapshot') "
                           "WHERE project_id=? AND event_type='milestone_promoted'", (PROJECT,))
    mapping = map_scenario(runtime, boot, requirements[0], identity)
    legacy = roadmap(runtime, boot, identity)
    canonical = json.dumps(legacy["canonical_scope"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    assert sha256(canonical).hexdigest() == legacy["roadmap_fingerprint"]
    assert legacy["confirmable"] and legacy["milestone_revisions"] == {identity: 1}
    untouched = runtime.ledger.promote_milestone(PROJECT, definition("Unchanged", requirements[1:2]), actor=ACTOR)["milestone_id"]
    untouched_fingerprint = roadmap(runtime, boot, untouched)["roadmap_fingerprint"]
    edit = revision_arguments(legacy, identity, name="  Revised scope  ")
    before_version = runtime.ledger.ledger_version(PROJECT)
    response = handle_bootstrap(runtime, **edit)
    result = response["result"]
    assert response["status"] == "success" and result["changed"]
    assert result["milestone"]["milestone_id"] == identity
    assert result["milestone"]["ordinal"] == milestone["ordinal"]
    assert result["milestone"]["revision"] == 2
    assert result["previous_milestone"]["name"] == original.name
    assert not result["confirmable"] and result["gaps"][0]["reason"] == "answer_correspondence_stale"
    current = roadmap(runtime, boot, identity)
    assert current["roadmap_fingerprint"] == result["roadmap_fingerprint"]
    assert current["roadmap_fingerprint"] != legacy["roadmap_fingerprint"]
    assert roadmap(runtime, boot, untouched)["roadmap_fingerprint"] == untouched_fingerprint
    assert len(runtime.ledger.milestones(PROJECT)) == 2
    edited_version = runtime.ledger.ledger_version(PROJECT)
    assert edited_version > before_version
    assert runtime.ledger.promote_milestone(PROJECT, original, actor=ACTOR, request_id="promote") == milestone
    assert_refused(handle_bootstrap(runtime, **{**edit, "milestone_revision": {**edit["milestone_revision"], "name": "different"}}),
                   "milestone_draft_request_conflict")
    noop = revision_arguments(current, identity, request_id="noop", name="Revised scope")
    no_effect = handle_bootstrap(runtime, **noop)["result"]
    assert not no_effect["changed"] and no_effect["current_revision"] == 2
    assert no_effect["roadmap_fingerprint"] == current["roadmap_fingerprint"]
    assert runtime.ledger.ledger_version(PROJECT) == edited_version
    revert = handle_bootstrap(runtime, **revision_arguments(current, identity, request_id="revert", name=original.name))["result"]
    assert revert["current_revision"] == 3 and revert["roadmap_fingerprint"] != legacy["roadmap_fingerprint"]
    runtime.guided_bootstrap.record_correspondence(PROJECT, boot, correspondence=mapping, actor=ACTOR, request_id="repair")
    confirm(runtime, roadmap(runtime, boot, identity))
    reopened = build_runtime(database_path=tmp_path / "draft.sqlite", import_root=tmp_path)
    try:
        recorded = audit_events(reopened, boot)
        assert handle_bootstrap(reopened, **edit) == response
        assert handle_bootstrap(reopened, **noop)["result"] == no_effect
        assert roadmap(reopened, boot, identity)["confirmed"]
        assert audit_events(reopened, boot) == recorded
    finally:
        reopened.close()


def test_prerequisite_changes_protect_downstream_historical_scope(draft):
    runtime, boot, requirements, _original, milestone = draft
    identity = milestone["milestone_id"]
    consumer = runtime.ledger.promote_milestone(PROJECT, definition("Consumer", requirements[2:], requirements[:1]), actor=ACTOR)
    consumer_id = consumer["milestone_id"]
    prior = roadmap(runtime, boot, identity)
    assert_refused(handle_bootstrap(runtime, **revision_arguments(prior, identity, requirement_ids=requirements[1:2])),
                   "milestone_draft_orphans_prerequisite")
    assert roadmap(runtime, boot, identity) == prior
    # Introduce an additional producer before a new dependent, so its producer
    # mapping would still exist after the edit but its confirmed authority would change.
    runtime.ledger.promote_milestone(PROJECT, definition("Other producer", requirements[:1]), actor=ACTOR)
    second_consumer = runtime.ledger.promote_milestone(PROJECT,
        definition("Second consumer", requirements[2:], requirements[:1]), actor=ACTOR)["milestone_id"]
    map_scenario(runtime, boot, requirements[2], second_consumer)
    confirm(runtime, roadmap(runtime, boot, second_consumer))
    runtime.bootstrap.cancel(PROJECT, boot, reason="Complete the fixture history", actor=ACTOR)
    later = runtime.bootstrap.start(PROJECT, project_name="Draft test", path="guided_engineering", actor=ACTOR)["bootstrap_id"]
    historical = roadmap(runtime, later, second_consumer)
    assert not historical["confirmed"]
    assert_refused(handle_bootstrap(runtime, **revision_arguments(historical, second_consumer, name="Forbidden")),
                   "milestone_draft_authority_locked")
    # The earlier consumer still lacks any other producer. A different edit
    # can reach the historical dependent guard without orphaning it.
    later_producer = runtime.ledger.milestones(PROJECT)[2]["milestone_id"]
    assert_refused(handle_bootstrap(runtime, **revision_arguments(roadmap(runtime, later, later_producer),
        later_producer, requirement_ids=requirements[1:2])), "milestone_draft_authority_locked")
    assert roadmap(runtime, boot, consumer_id)["canonical_scope"]["milestones"][0]["prerequisite_producers"] == {requirements[0]: [identity]}


def test_incomplete_milestone_names_missing_field_and_routes_to_same_draft(draft):
    runtime, boot, requirements, _original, _milestone = draft
    incomplete = MilestoneDraft(name="Missing exit", requirement_ids=(requirements[0],),
        prerequisite_requirement_ids=(), entry_policy={"requires_milestone": []},
        exit_policy={}, risk_disposition="Local fixture")
    identity = runtime.ledger.promote_milestone(PROJECT, incomplete, actor=ACTOR)["milestone_id"]
    correspondence = map_scenario(runtime, boot, requirements[0], identity)
    view = roadmap(runtime, boot, identity)
    rejected = handle_bootstrap(runtime, project_id=PROJECT, bootstrap_id=boot,
        operation="confirm_roadmap", milestone_ids=[identity], roadmap_fingerprint=view["roadmap_fingerprint"],
        confirmation_reference="fixture consent", actor=ACTOR, request_id="confirm-incomplete")
    assert rejected["reason"] == "guided_roadmap_not_confirmable"
    problem = next(row for row in rejected["result"]["diagnostics"]
                   if row.get("reason") == "milestone_definition_incomplete")
    assert problem["missing_fields"] == ["exit_policy"]
    correction = problem["correction"]
    assert "milestone_revision.exit_policy" in correction["required_inputs"]
    args = correction["arguments"]
    args["milestone_revision"]["exit_policy"] = {"verification": "Exercise the selected scenario"}
    repaired = handle_bootstrap(runtime, **args, actor=ACTOR, request_id="complete-same-draft")
    assert repaired["status"] == "success"
    assert repaired["result"]["milestone"]["milestone_id"] == identity
    assert not any(gap["reason"] == "milestone_definition_incomplete"
                   for gap in roadmap(runtime, boot, identity)["gaps"])
    runtime.guided_bootstrap.record_correspondence(PROJECT, boot, correspondence=correspondence,
        actor=ACTOR, request_id="refresh-mapping")
    assert roadmap(runtime, boot, identity)["confirmable"]


def test_public_operation_discovers_schema_and_reports_known_causes(draft):
    runtime, boot, requirements, _original, milestone = draft
    identity = milestone["milestone_id"]
    view = roadmap(runtime, boot, identity)

    async def run():
        app = create_app(runtime)
        help_response = await app.call_tool("fow_capabilities", {"view": "operation", "operation_tool": "fow_bootstrap",
            "operation_name": "revise_draft_milestone"})
        assert not help_response.isError and "expected_revision" in help_response.content[0].text
        bad = await app.call_tool("fow_bootstrap", revision_arguments(view, identity, requirement_ids=["REQ-999999"]))
        rejected = bad.structuredContent["result"]
        assert_refused(rejected, "milestone_requirement_not_current")
        assert "Inspect this project's canonical requirements" in bad.content[0].text
        result = await app.call_tool("fow_bootstrap", revision_arguments(view, identity, name="Revised"))
        assert not result.isError
        assert "Draft milestone revision" in result.content[0].text and "Read the current roadmap" in result.content[0].text
        assert result.structuredContent["result"]["result"]["current_revision"] == 2

    asyncio.run(run())
    accepted = runtime.ledger.accept_milestone(PROJECT, identity, acceptance_evidence=("fixture evidence",), actor=ACTOR)
    assert accepted["status"] == "accepted"
    assert_refused(handle_bootstrap(runtime, **revision_arguments(roadmap(runtime, boot, identity), identity,
        request_id="after-acceptance", requirement_ids=requirements[1:2])), "milestone_draft_authority_locked")


def test_existing_accepted_work_plan_protects_linked_milestone(tmp_path):
    runtime, ids, _revs, boot, milestone, _answer, _mapping = prepared(tmp_path)
    try:
        view = runtime.guided_bootstrap.roadmap(ids[0], boot, milestone_ids=[milestone])
        assert_refused(handle_bootstrap(runtime, **{**revision_arguments(view, milestone, name="Blocked"), "project_id": ids[0]}),
                       "milestone_draft_linked_work_locked")
    finally:
        runtime.close()


@pytest.mark.parametrize("legacy_confirmation", [True, False])
def test_confirmed_correspondence_protects_its_milestone_without_freezing_disjoint_drafts(draft, legacy_confirmation):
    runtime, boot, requirements, _original, milestone = draft
    selected = milestone["milestone_id"]
    related = runtime.ledger.promote_milestone(PROJECT, definition("Related", requirements[1:2]), actor=ACTOR)["milestone_id"]
    disjoint = runtime.ledger.promote_milestone(PROJECT, definition("Disjoint", requirements[2:]), actor=ACTOR)["milestone_id"]
    mapping = map_scenario(runtime, boot, requirements[0], selected)
    mapping["canonical_references"]["milestone_ids"].append(related)
    runtime.guided_bootstrap.record_correspondence(PROJECT, boot, correspondence=mapping, actor=ACTOR, request_id="related")
    confirmed = roadmap(runtime, boot, selected)
    confirm(runtime, confirmed)
    if legacy_confirmation:
        with runtime.ledger.atomic() as connection:
            connection.execute("UPDATE bootstrap_events SET payload_json=json_remove(payload_json, '$.authority_milestone_ids') "
                               "WHERE project_id=? AND event_type='guided_confirm_roadmap'", (PROJECT,))
    related_view = roadmap(runtime, boot, related)
    assert_refused(handle_bootstrap(runtime, **revision_arguments(related_view, related, name="Protected")),
                   "milestone_draft_authority_locked")
    disjoint_view = roadmap(runtime, boot, disjoint)
    updated = handle_bootstrap(runtime, **revision_arguments(disjoint_view, disjoint, name="Revised disjoint"))
    assert updated["status"] == "success"
    still_confirmed = roadmap(runtime, boot, selected)
    assert still_confirmed["confirmed"] and still_confirmed["roadmap_fingerprint"] == confirmed["roadmap_fingerprint"]


@pytest.mark.parametrize("confirm_first", [True, False])
def test_edit_and_confirm_share_one_write_gate(draft, confirm_first):
    runtime, boot, requirements, _original, milestone = draft
    identity = milestone["milestone_id"]
    map_scenario(runtime, boot, requirements[0], identity)
    view = roadmap(runtime, boot, identity)
    edit = revision_arguments(view, identity, name="Revised")
    started = Event()

    def first():
        with runtime.ledger.atomic():
            assert started.wait(2)
            return confirm(runtime, view) if confirm_first else handle_bootstrap(runtime, **edit)

    def second():
        started.set()
        return handle_bootstrap(runtime, **edit) if confirm_first else confirm(runtime, view)

    def locked_first():
        with runtime.ledger.atomic():
            gate.wait()
            return first()

    gate = Barrier(2, timeout=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(locked_first)
        gate.wait()
        loser = pool.submit(second)
        first_result = winner.result(timeout=10)
        if confirm_first:
            assert first_result["intake"]["_guided"]["roadmap_confirmation"]
            assert_refused(loser.result(timeout=10), "milestone_draft_authority_locked")
        else:
            assert first_result["status"] == "success"
            with pytest.raises(BootstrapBlockedError, match="guided_roadmap_not_confirmable"):
                loser.result(timeout=10)
    effects = {event["event_type"] for event in audit_events(runtime, boot)}
    assert ("guided_confirm_roadmap" in effects) == confirm_first
    assert ("guided_revise_draft_milestone" in effects) != confirm_first


def test_competing_edits_leave_one_receipt(draft):
    runtime, boot, _requirements, _original, milestone = draft
    identity = milestone["milestone_id"]
    view = roadmap(runtime, boot, identity)
    start = Barrier(2, timeout=5)

    def change(name):
        start.wait()
        return handle_bootstrap(runtime, **revision_arguments(view, identity, request_id=name, name=name))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(change, ("First contender", "Second contender")))
    winner, loser = sorted(outcomes, key=lambda outcome: outcome["status"], reverse=True)
    assert winner["status"] == "success"
    assert_refused(loser, "milestone_draft_fingerprint_stale")
    assert roadmap(runtime, boot, identity)["milestone_revisions"] == {identity: 2}
    assert sum(event["event_type"] == "guided_revise_draft_milestone" for event in audit_events(runtime, boot)) == 1
