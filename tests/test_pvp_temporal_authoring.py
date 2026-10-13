"""Canonical deferred-only boundaries preserve semantic and temporal authority."""
from copy import deepcopy

import pytest

from flow_of_work_mcp import ChangeControlService, MilestoneDraft, SQLiteRequirementLedger, WorkPlanUnit
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.milestone_traceability import MilestoneTraceabilityProjectionService
from flow_of_work_mcp.application.navigation_audit import NavigationAuditService
from flow_of_work_mcp.application.packet_unit_authoring import PacketUnitAuthoringService
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.domain.external_work import fingerprint, normalize_declarations
from flow_of_work_mcp.core.domain.provider_validation import build_context, validate_context
from tests.test_external_work import fixture, report


def deferred_unit(*, key="deferred", kind="live_campaign", criterion=1):
    intent = {"criterion": criterion, "kind": kind, "statement": "Verify the installed behavior in its governed campaign."}
    if kind == "explicit_authority":
        intent["authority_ref"] = "decision:governed-verification"
    return {"client_unit_key": key, "operation_kind": "new_file", "file_path": "src/" + key + ".py",
            "instructions": ["Implement the declared behavior without running deferred verification."],
            "unit_checks": [], "implements": [criterion], "verifies": [intent]}


def services(ledger):
    plans = PacketWorkPlanService(ledger, changes=ledger, navigation=ledger)
    author = PacketUnitAuthoringService(ledger=ledger, repository=ledger, changes=ledger,
        navigation=NavigationAuditService(ledger, work_plans=ledger), work_plans=plans)
    return plans, author


def accept(plans, ids, proposed, *, request_id="accept-deferred-plan"):
    plans.accept(*ids, plan_revision=proposed["plan_revision"],
        expected_packet_revision=proposed["packet_revision"],
        expected_current_plan_revision=proposed["plan_revision"],
        rationale="The complete authored plan keeps deferred verification outside the unit boundary.",
        actor="engineer", request_id=request_id)
    return {"expected_spec_revision": proposed["packet_revision"],
            "expected_plan_revision": proposed["plan_revision"]}


def replace_with_deferred(ledger, ids, *, semantic_kind="api"):
    plans, _author = services(ledger)
    previous = ledger.packet_work_plan_state(*ids)
    units = deepcopy(previous["units"])
    for index, unit in enumerate(units):
        unit["unit_checks"] = []
        unit["verifies"] = [{"criterion": index + 1, "kind": "live_campaign" if index == 0 else "oracle",
                            "statement": "Deferred verification of criterion " + str(index + 1) + "."}]
    units[0]["provides"][0]["kind"] = semantic_kind
    proposed = plans.set_plan(*ids, {"units": units}, expected_packet_revision=previous["packet_revision"],
        expected_current_plan_revision=previous["plan_revision"], actor="engineer", request_id="deferred-bulk")
    return accept(plans, ids, proposed), units


@pytest.mark.parametrize("kind", ["deterministic_campaign", "live_campaign", "oracle", "explicit_authority"])
def test_domain_allows_only_explicit_deferred_only_empty_checks(kind):
    payload = deferred_unit(kind=kind)
    unit = WorkPlanUnit(**payload)
    assert unit.unit_checks == ()
    assert list(unit.verifies) == payload["verifies"]


@pytest.mark.parametrize("verifies", [
    [],
    [{"criterion": 1, "kind": "unit_check", "statement": "Local check."}],
    [{"criterion": 1, "kind": "unit_check", "statement": "Local check."},
     {"criterion": 1, "kind": "oracle", "statement": "Deferred check."}],
    [{"criterion": 1, "kind": "unknown", "statement": "Invented intent."}],
    [{"criterion": True, "kind": "oracle", "statement": "Invalid criterion identity."}],
    [{"criterion": 1, "kind": "explicit_authority", "statement": "Missing authority reference."}],
    [{"criterion": 1, "kind": "oracle", "statement": "Unknown field.", "approved": True}],
])
def test_domain_empty_checks_never_bypass_verification_validation(verifies):
    with pytest.raises(ValueError):
        WorkPlanUnit(**{**deferred_unit(), "verifies": verifies})


def test_deferred_verification_never_relaxes_ordered_instructions_or_legacy_checks():
    with pytest.raises(ValueError, match="instructions"):
        WorkPlanUnit(**{**deferred_unit(), "instructions": []})
    legacy = {**deferred_unit(), "verifies": [], "unit_checks": ["Import the new module."]}
    assert WorkPlanUnit(**legacy).unit_checks == ("Import the new module.",)


def test_canonical_add_and_revise_preserve_empty_checks_and_exact_replay(tmp_path):
    ledger, _external, ids, _revs = fixture(tmp_path)
    plans, author = services(ledger)
    unit = deferred_unit()
    added = author.add_unit(*ids, unit=unit, actor="engineer", request_id="add-deferred")
    assert added["state"] == "unit_added"
    state = ledger.packet_work_plan_state(*ids)
    assert state["units"][-1]["unit_checks"] == []
    assert state["units"][-1]["verifies"] == unit["verifies"]
    before_replay = ledger.ledger_version(ids[0])
    replay = author.add_unit(*ids, unit=unit, actor="engineer", request_id="add-deferred")
    assert replay["plan_revision"] == added["plan_revision"]
    assert replay["replayed"] is True
    assert ledger.ledger_version(ids[0]) == before_replay
    patch = {"verifies": [{"criterion": 1, "kind": "oracle", "statement": "Observe the complete governed scenario."}]}
    arguments = dict(operation="revise_unit", client_unit_key="deferred", unit_patch=patch,
        expected_packet_revision=state["packet_revision"], expected_current_plan_revision=state["plan_revision"],
        actor="engineer", request_id="revise-deferred")
    revised = plans.mutate_plan(*ids, **arguments)
    before_replay = ledger.ledger_version(ids[0])
    replay = plans.mutate_plan(*ids, **arguments)
    assert revised["replayed"] is False and replay["replayed"] is True
    assert {key: value for key, value in replay.items() if key != "replayed"} == {
        key: value for key, value in revised.items() if key != "replayed"}
    assert ledger.ledger_version(ids[0]) == before_replay
    accept(plans, ids, revised)
    current = ledger.packet_work_plan_state(*ids)
    assert current["status"] == "accepted"
    assert current["units"][-1]["unit_checks"] == []
    assert current["units"][-1]["verifies"] == patch["verifies"]
    reopened = SQLiteRequirementLedger(ledger.database_path)
    assert reopened.packet_work_plan_state(*ids) == current


@pytest.mark.parametrize("patch", [
    {"verifies": []},
    {"verifies": [{"criterion": 1, "kind": "unit_check", "statement": "Local check."}]},
    {"verifies": [{"criterion": 1, "kind": "oracle", "statement": "Deferred check."},
                  {"criterion": 1, "kind": "unit_check", "statement": "Local check."}]},
    {"verifies": [{"criterion": 1, "kind": "invented", "statement": "Invalid deferred intent."}]},
    {"instructions": []},
])
def test_invalid_add_creates_no_intent_or_partial_authority(tmp_path, patch):
    ledger, _external, ids, _revs = fixture(tmp_path)
    _plans, author = services(ledger)
    before = deepcopy(ledger.packet_work_plan_state(*ids))
    version = ledger.ledger_version(ids[0])
    with pytest.raises(ValueError):
        author.add_unit(*ids, unit={**deferred_unit(), **patch}, actor="engineer", request_id="invalid-add")
    assert ledger.packet_work_plan_state(*ids) == before
    assert ledger.ledger_version(ids[0]) == version
    assert ledger.packet_unit_authoring_intent(*ids, "deferred") is None


@pytest.mark.parametrize("operation", ["bulk", "revise"])
def test_invalid_later_unit_or_removal_of_deferred_intent_is_atomic(tmp_path, operation):
    ledger, _external, ids, _revs = fixture(tmp_path)
    plans, _author = services(ledger)
    if operation == "revise":
        replace_with_deferred(ledger, ids)
    before = deepcopy(ledger.packet_work_plan_state(*ids))
    version = ledger.ledger_version(ids[0])
    with pytest.raises(ValueError):
        if operation == "bulk":
            units = deepcopy(before["units"])
            units[0]["unit_checks"] = []
            units[0]["verifies"] = deferred_unit()["verifies"]
            units[1]["unit_checks"] = []
            units[1]["verifies"] = []
            plans.set_plan(*ids, {"units": units}, expected_packet_revision=before["packet_revision"],
                expected_current_plan_revision=before["plan_revision"], actor="engineer", request_id="invalid-bulk")
        else:
            plans.mutate_plan(*ids, operation="revise_unit", client_unit_key="producer", unit_patch={"verifies": []},
                expected_packet_revision=before["packet_revision"], expected_current_plan_revision=before["plan_revision"],
                actor="engineer", request_id="invalid-revise")
    assert ledger.packet_work_plan_state(*ids) == before
    assert ledger.ledger_version(ids[0]) == version


@pytest.mark.parametrize("kind", ["symbol", "api", "data_shape", "protocol", "behavioral_boundary"])
def test_accepted_semantic_kinds_preserve_exact_future_shape_without_ast_inference(tmp_path, kind):
    ledger, external, ids, _revs = fixture(tmp_path)
    replace_with_deferred(ledger, ids, semantic_kind=kind)
    projection = external.provider_validation(*ids)
    assert projection["status"] == "closed"
    context = build_context(projection, unit_key="consumer")
    canonical = context["units"][0]["provides"][0]
    assert canonical == {"name": "increment-api", "kind": kind,
        "clauses": ["One integer argument named value.", "Return value + 1.", "No I/O side effects."],
        "file_path": "src/increment.py", "symbol": "increment", "signature": "(value: int) -> int"}
    consumed = context["units"][1]["resolved_requires"][0]
    assert consumed["contract"] == canonical
    assert consumed["temporal_state"] == "planned"
    assert all(unit["local_verification"] == [] for unit in context["units"])
    assert [unit["deferred_verification"] for unit in context["units"]] == [unit["verifies"] for unit in projection["units"]]
    assert "expected_kind" not in str(context) and "symbol_kind" not in str(context)


@pytest.mark.parametrize("field", ["expected_kind", "symbol_kind"])
def test_unknown_ast_fields_are_rejected_even_in_a_consistently_rehashed_context(tmp_path, field):
    ledger, external, ids, _revs = fixture(tmp_path)
    context = build_context(external.provider_validation(*ids), unit_key="consumer")
    context["units"][0]["provides"][0][field] = "function"
    context["units"][1]["resolved_requires"][0]["contract"][field] = "function"
    body = {key: value for key, value in context.items() if key != "context_sha256"}
    context["context_sha256"] = fingerprint(body)
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_context(context)
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_declarations({"provides": context["units"][0]["provides"]})


def test_deferred_only_export_frontier_report_restart_and_progress_stay_truthful(tmp_path):
    ledger, external, ids, _revs = fixture(tmp_path)
    revs, units = replace_with_deferred(ledger, ids)
    requirement_id = ledger.change_state(*ids[:2])["requirement_ids"][0]
    milestone = ledger.promote_milestone(ids[0], MilestoneDraft(name="Deferred verification boundary",
        requirement_ids=(requirement_id,), dependency_closure_ids=(requirement_id,),
        entry_policy={"scope": "declared"}, exit_policy={"acceptance": "human"}, risk_disposition="bounded"), actor="human")
    ChangeControlService(ledger).link_change_milestone(*ids[:2], milestone["milestone_id"], actor="human")
    exported = external.call(*ids, "export_plan", payload=revs, actor="agent", request_id="export-deferred")
    content = exported["content"]
    assert exported["draft"] is False
    assert content.index("Unit 1: producer") < content.index("Unit 2: consumer")
    assert "deferred control-plane verification; not a current coding instruction" in content
    for unit in units:
        section = content.split(": " + unit["client_unit_key"], 1)[1]
        local_section = section.split("#### Unit-local checks", 1)[1].split("#### ", 1)[0]
        assert unit["verifies"][0]["statement"] not in local_section
        assert unit["verifies"][0]["statement"] in content
    version = ledger.ledger_version(ids[0])
    initial = external.todo(*ids)
    assert initial["current_unit"]["unit_key"] == "producer"
    assert initial["todos"][1]["dependencies_pending"] == ["producer"]
    assert ledger.ledger_version(ids[0]) == version
    producer = report(external, ids, revs)
    assert producer["verification"] == []
    receipt = external.call(*ids, "report_outcome", payload=producer, actor="agent", request_id="producer-deferred")
    reopened = SQLiteRequirementLedger(ledger.database_path)
    resumed = ExternalWorkService(reopened)
    assert resumed.call(*ids, "report_outcome", payload=producer, actor="agent", request_id="producer-deferred") == receipt
    assert resumed.todo(*ids)["current_unit"]["unit_key"] == "consumer"
    consumer = report(resumed, ids, revs, "consumer", report_key="consumer-deferred")
    assert consumer["verification"] == []
    resumed.call(*ids, "report_outcome", payload=consumer, actor="agent", request_id="consumer-deferred")
    final = resumed.todo(*ids)
    assert final["current_unit"] is None
    assert final["next_gate"]["external_operation"] == "obtain_deferred_verification"
    assert final["acceptance"] == "not_inferred"
    assert all(obligation["state"] == "verification_pending" for obligation in final["deferred_verification"])
    progress_service = MilestoneTraceabilityProjectionService(requirements=reopened, lifecycle=reopened, changes=reopened,
        navigation=reopened, assurance=reopened, execution_runs=reopened, ledger_versions=reopened,
        grounding_audits=reopened, external_work=resumed)
    progress = progress_service.progress(ids[0], milestone_ids=(milestone["milestone_id"],))
    assert progress["implementation"]["percent"] == 100
    assert progress["local_verification"]["total"] == 0
    assert progress["local_verification"]["not_applicable"] == 2
    assert progress["local_verification"]["percent"] is None
    assert all(criterion["local_verification_state"] == "not_applicable" for criterion in progress["criteria"])
    assert all(obligation["state"] == "verification_pending" for obligation in progress["deferred_obligations"])
    assert progress["fully_completed"] is False
    assert progress["acceptance"] == "not_inferred"
    assert reopened.change_state(*ids[:2])["packets"][0]["status"] == "planned"
