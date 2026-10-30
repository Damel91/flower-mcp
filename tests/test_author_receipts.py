"""Author effects stay historical while continuation names the current head."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_packet_author
from tests.test_external_work import fixture


@pytest.fixture
def authored(tmp_path):
    ledger, _external, ids, _revs = fixture(tmp_path)
    runtime = build_runtime(database_path=ledger.database_path, import_root=tmp_path, ledger=ledger)
    runtime.packet_factory.ensure_packet_lifecycle(*ids, actor="engineer", request_id="author-test-substrate")
    try:
        yield runtime, ids
    finally:
        runtime.close()


def current(runtime, ids):
    packet = next(row for row in runtime.ledger.change_state(*ids[:2])["packets"] if row["packet_id"] == ids[2])
    plan = runtime.ledger.packet_work_plan_state(*ids)
    return {"expected_spec_revision": packet["spec_revision"],
            "expected_plan_revision": plan["plan_revision"] if plan else 0}


def snapshot(runtime):
    """Compare every durable row, including author events and provider outbox."""
    with sqlite3.connect(f"file:{runtime.ledger.database_path}?mode=ro", uri=True) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: sorted(connection.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall(), key=repr)
                for table in tables}


def call(runtime, ids, operation, request_id, **arguments):
    return handle_packet_author(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2],
                                operation=operation, actor="engineer", request_id=request_id, **arguments)


def assert_current(runtime, ids, response):
    assert response["status"] == "success"
    result = response["result"]
    authority = current(runtime, ids)
    assert result["current_authority"] == authority
    for action in (result["next_action"], result["gate"].get("next_action", {})):
        for key, expected in authority.items():
            if key in action.get("arguments", {}):
                assert action["arguments"][key] == expected
    return result


def mutation_arguments(operation):
    if operation == "revise_unit":
        return {"client_unit_key": "consumer", "unit_patch": {"instructions": ["Call the canonical predecessor increment API."]}}
    if operation == "remove_unit":
        return {"client_unit_key": "consumer"}
    if operation == "rebind_unit":
        return {"client_unit_key": "consumer", "unit_patch": {"file_path": "src/relocated_client.py"}}
    if operation == "set_dependencies":
        return {"client_unit_key": "consumer", "depends_on": []}
    raise AssertionError(operation)


def extra_unit():
    return {"client_unit_key": "extra", "operation_kind": "new_file", "file_path": "src/extra.py",
            "instructions": ["Create a bounded supporting module."], "unit_checks": ["The module imports successfully."]}


@pytest.mark.parametrize("operation", ["revise_unit", "remove_unit", "rebind_unit", "set_dependencies"])
def test_service_mutation_identity_survives_fresh_and_exact_replay(authored, operation):
    runtime, ids = authored
    revs = current(runtime, ids)
    arguments = {"operation": operation, **mutation_arguments(operation),
                 "expected_packet_revision": revs["expected_spec_revision"],
                 "expected_current_plan_revision": revs["expected_plan_revision"],
                 "actor": "engineer", "request_id": "service-" + operation}
    fresh = runtime.packet_work_plan.mutate_plan(*ids, **arguments)
    before = snapshot(runtime)
    replay = runtime.packet_work_plan.mutate_plan(*ids, **arguments)
    assert fresh["affected_unit_key"] == replay["affected_unit_key"] == "consumer"
    assert fresh["mutation_operation"] == replay["mutation_operation"] == operation
    assert fresh["replayed"] is False and replay["replayed"] is True
    assert {key: value for key, value in replay.items() if key != "replayed"} == {
        key: value for key, value in fresh.items() if key != "replayed"}
    assert snapshot(runtime) == before


def test_set_plan_replay_flag_is_transient_and_state_history_stay_canonical(authored):
    runtime, ids = authored
    previous = runtime.ledger.packet_work_plan_state(*ids)
    arguments = {"work_plan": {"units": deepcopy(previous["units"])},
                 "expected_packet_revision": previous["packet_revision"],
                 "expected_current_plan_revision": previous["plan_revision"],
                 "actor": "engineer", "request_id": "service-replace"}
    fresh = runtime.packet_work_plan.set_plan(*ids, **arguments)
    before = snapshot(runtime)
    replay = runtime.packet_work_plan.set_plan(*ids, **arguments)
    assert fresh["replayed"] is False and replay["replayed"] is True
    assert "replayed" not in runtime.ledger.packet_work_plan_state(*ids)
    assert all("replayed" not in row for row in runtime.ledger.packet_work_plan_history(*ids))
    assert snapshot(runtime) == before


@pytest.mark.parametrize("operation", ["revise_unit", "remove_unit", "rebind_unit", "set_dependencies"])
def test_public_unit_receipt_retains_identity_through_finalization_and_replay(authored, operation):
    runtime, ids = authored
    arguments = {**mutation_arguments(operation), **current(runtime, ids)}
    fresh = call(runtime, ids, operation, "public-" + operation, **arguments)
    first = assert_current(runtime, ids, fresh)
    replay = call(runtime, ids, operation, "public-" + operation, **arguments)
    second = assert_current(runtime, ids, replay)
    for result in (first, second):
        assert result["mutation"]["operation"] == operation
        assert result["mutation"]["affected_unit_key"] == "consumer"
        assert result["semantic_delta"]["affected_unit_key"] == "consumer"
    assert first["packet"]["plan_revision"] == second["packet"]["plan_revision"]


@pytest.mark.parametrize("operation", ["replace_plan", "revise_unit", "remove_unit", "rebind_unit", "set_dependencies"])
def test_historical_author_replay_is_read_only_after_new_head_and_restart(authored, tmp_path, monkeypatch, operation):
    runtime, ids = authored
    old_plan = runtime.ledger.packet_work_plan_state(*ids)
    arguments = ({"work_plan": {"units": deepcopy(old_plan["units"])}} if operation == "replace_plan"
                 else mutation_arguments(operation))
    arguments.update(current(runtime, ids))
    first = call(runtime, ids, operation, "historical-" + operation, **arguments)
    historical = deepcopy(first["result"]["packet"])
    call(runtime, ids, "revise_packet", "advance-head-" + operation,
         unresolved_questions=["Which new customer decision closes the scenario?"], **current(runtime, ids))
    before = snapshot(runtime)
    head = current(runtime, ids)

    def no_queue(*args, **kwargs):
        raise AssertionError("An exact historical replay must not queue a provider delta")

    monkeypatch.setattr(runtime.packet_provider_overlay, "queue_plan_delta", no_queue)
    response = call(runtime, ids, operation, "historical-" + operation, **arguments)
    result = assert_current(runtime, ids, response)
    assert result["packet"]["spec_revision"] == historical["spec_revision"]
    assert result["packet"]["plan_revision"] == historical["plan_revision"]
    assert result["semantic_delta"]["semantic_revision"] == historical["spec_revision"]
    assert result["current_authority"] == head
    assert snapshot(runtime) == before
    runtime.close()
    reopened = build_runtime(database_path=tmp_path / "flower.sqlite", import_root=tmp_path)
    try:
        before_restart_replay = snapshot(reopened)
        monkeypatch.setattr(reopened.packet_provider_overlay, "queue_plan_delta", no_queue)
        replay = assert_current(reopened, ids, call(reopened, ids, operation, "historical-" + operation, **arguments))
        assert replay["packet"]["spec_revision"] == historical["spec_revision"]
        assert replay["current_authority"] == head
        assert snapshot(reopened) == before_restart_replay
    finally:
        reopened.close()


def test_storage_refuses_historical_finalize_without_rebinding_authority(authored):
    runtime, ids = authored
    original = runtime.ledger.packet_work_plan_state(*ids)
    call(runtime, ids, "revise_unit", "newer-before-finalize", **mutation_arguments("revise_unit"), **current(runtime, ids))
    before = snapshot(runtime)
    with pytest.raises((ChangeControlBlockedError, RequirementConflictError)):
        runtime.ledger.finalize_packet_authoring_revision(ids[0], original["work_plan_id"], original["plan_revision"])
    assert snapshot(runtime) == before


def test_committed_add_replay_accepts_original_stale_revisions_but_rejects_changed_intent(authored, monkeypatch):
    runtime, ids = authored
    arguments = {"unit": extra_unit(), **current(runtime, ids)}
    added = call(runtime, ids, "add_unit", "committed-add", **arguments)
    assert added["result"]["unit_authoring"]["replayed"] is False
    call(runtime, ids, "revise_packet", "head-after-add",
         unresolved_questions=["Which new customer decision closes the scenario?"], **current(runtime, ids))
    before = snapshot(runtime)

    def no_queue(*args, **kwargs):
        raise AssertionError("A committed add replay must not queue a provider delta")

    monkeypatch.setattr(runtime.packet_provider_overlay, "queue_plan_delta", no_queue)
    replay = assert_current(runtime, ids, call(runtime, ids, "add_unit", "committed-add", **arguments))
    assert replay["unit_authoring"]["replayed"] is True
    assert replay["semantic_delta"]["affected_unit_key"] == "extra"
    assert snapshot(runtime) == before
    with pytest.raises(RequirementConflictError, match="another authoring intent"):
        call(runtime, ids, "add_unit", "committed-add", **{**arguments, "unit": {**extra_unit(), "instructions": ["Different work."]}})
    assert snapshot(runtime) == before


def test_stale_uncommitted_add_creates_no_intent_or_partial_authority(authored):
    runtime, ids = authored
    revisions = current(runtime, ids)
    before = snapshot(runtime)
    with pytest.raises(ChangeControlBlockedError, match="stale_packet_revision"):
        call(runtime, ids, "add_unit", "stale-new-unit", unit=extra_unit(),
             expected_spec_revision=revisions["expected_spec_revision"] - 1,
             expected_plan_revision=revisions["expected_plan_revision"])
    assert runtime.ledger.packet_unit_authoring_intent(*ids, "extra") is None
    assert snapshot(runtime) == before


def test_committed_add_resume_by_key_is_read_only_with_a_new_request_id(authored, monkeypatch):
    runtime, ids = authored
    revisions = current(runtime, ids)
    added = call(runtime, ids, "add_unit", "original-add-intent", unit=extra_unit(), **revisions)
    call(runtime, ids, "revise_packet", "head-after-committed-intent",
         unresolved_questions=["Which new customer decision closes the scenario?"], **current(runtime, ids))
    before = snapshot(runtime)

    def no_queue(*args, **kwargs):
        raise AssertionError("A committed intent resume must not queue provider work")

    monkeypatch.setattr(runtime.packet_provider_overlay, "queue_plan_delta", no_queue)
    result = assert_current(runtime, ids, call(runtime, ids, "add_unit", "resume-committed-intent",
        client_unit_key="extra", **revisions))
    assert result["unit_authoring"]["replayed"] is True
    assert result["unit_authoring"]["plan_revision"] == added["result"]["unit_authoring"]["plan_revision"]
    assert snapshot(runtime) == before


@pytest.mark.parametrize("operation", ["replace_plan", "revise_packet", "resolve_questions", "add_unit"])
def test_current_authority_covers_author_result_branches(authored, operation):
    runtime, ids = authored
    if operation == "replace_plan":
        arguments = {"work_plan": {"units": runtime.ledger.packet_work_plan_state(*ids)["units"]}}
    elif operation == "revise_packet":
        arguments = {"invariants": ["Keep the successor contract and avoid I/O."]}
    elif operation == "resolve_questions":
        audit = runtime.packet_construction.audit_for_packet(*ids)
        arguments = {"answers": [{"question_id": audit["questions"][0]["question_id"],
                                  "answer_summary": "Use the recorded public entrypoint."}]}
    else:
        arguments = {"unit": extra_unit()}
    result = assert_current(runtime, ids, call(runtime, ids, operation, "branch-" + operation, **arguments, **current(runtime, ids)))
    if operation == "replace_plan":
        assert result["mutation"]["affected_unit_key"] == ""


def test_start_packet_reports_current_authority_without_unit_identity(authored):
    runtime, ids = authored
    response = handle_packet_author(runtime, project_id=ids[0], change_id=ids[1], operation="start_packet",
        title="A bounded correction", intent="Implement the recorded small correction.",
        completion_criteria=["The correction is observable."], in_scope=["A supporting module"],
        actor="engineer", request_id="start-author-receipt")
    created_ids = (ids[0], ids[1], response["result"]["packet"]["packet_id"])
    result = assert_current(runtime, created_ids, response)
    assert "affected_unit_key" not in result["semantic_delta"]


def test_pending_selection_reports_current_authority_without_claiming_unit_added(authored):
    runtime, ids = authored
    before_plan = runtime.ledger.packet_work_plan_state(*ids)
    pending = {"client_unit_key": "pending", "operation_kind": "modify_existing",
               "instructions": ["Preserve the selected behavior."], "unit_checks": ["The behavior remains observable."]}
    result = assert_current(runtime, ids, call(runtime, ids, "add_unit", "pending-selection", unit=pending, **current(runtime, ids)))
    assert result["unit_authoring"]["state"] == "navigation_audit_has_no_candidates"
    assert result["semantic_delta"] == {}
    assert runtime.ledger.packet_work_plan_state(*ids) == before_plan
    assert runtime.ledger.packet_unit_authoring_intent(*ids, "pending")["state"] == "pending"


def test_pending_selection_stale_resume_preserves_intent_and_plan(authored):
    runtime, ids = authored
    revisions = current(runtime, ids)
    pending = {"client_unit_key": "pending", "operation_kind": "modify_existing",
               "instructions": ["Preserve the selected behavior."], "unit_checks": ["The behavior remains observable."]}
    response = call(runtime, ids, "add_unit", "pending-before-change", unit=pending, **revisions)
    assert response["result"]["unit_authoring"]["state"] == "navigation_audit_has_no_candidates"
    call(runtime, ids, "revise_unit", "head-after-pending", **mutation_arguments("revise_unit"), **current(runtime, ids))
    before = snapshot(runtime)
    with pytest.raises(ChangeControlBlockedError, match="stale_packet_revision"):
        call(runtime, ids, "add_unit", "pending-resume", client_unit_key="pending", **revisions)
    assert snapshot(runtime) == before


def legacy_question_packet(runtime, ids):
    original = next(packet for packet in runtime.ledger.change_state(*ids[:2])["packets"]
                    if packet["packet_id"] == ids[2])
    architecture_refs = original["architecture_refs"]
    response = handle_packet_author(runtime, project_id=ids[0], change_id=ids[1], operation="start_packet",
        title="Bounded authority question", intent="Create a supporting module.",
        completion_criteria=["The module imports."], in_scope=["A supporting module"], invariants=["No I/O"],
        unresolved_questions=["Which customer approval closes the scenario?"], architecture_refs=architecture_refs,
        actor="engineer", request_id="start-question")
    scoped = (ids[0], ids[1], response["result"]["packet"]["packet_id"])
    call(runtime, scoped, "add_unit", "question-unit", unit=extra_unit(), **current(runtime, scoped))
    plan = runtime.ledger.packet_work_plan_state(*scoped)
    # Selected architecture makes executor ownership explicit. Select the
    # provider route locally; this fixture neither negotiates nor calls it.
    selected = runtime.external_work.call(*scoped, "select_executor", payload={
        "executor": "provider", "provider_kind": "codingcastle", **current(runtime, scoped)},
        actor="engineer", request_id="question-executor-select")
    assert selected["status"] == "success"
    runtime.packet_work_plan.accept(*scoped, plan_revision=plan["plan_revision"],
        expected_packet_revision=plan["packet_revision"], expected_current_plan_revision=plan["plan_revision"],
        rationale="The bounded plan is complete; customer authority remains separately open.", actor="engineer", request_id="question-plan-accept")
    gate = runtime.packet_lifecycle.get_packet(*scoped, view="gates")["gate"]
    assert gate["decision_required"]["kind"] == "engineering_question"
    return scoped, gate


def test_answer_gate_receipt_reports_current_authority_and_preserves_failed_gate(authored):
    runtime, ids = authored
    scoped, gate = legacy_question_packet(runtime, ids)
    before = snapshot(runtime)
    arguments = {"response": {"disposition": "answered", "answer_summary": "The stakeholder reviews the completed scenario."}}
    with pytest.raises(ChangeControlBlockedError, match="stale_packet_gate"):
        call(runtime, scoped, "answer_gate", "stale-answer", gate_fingerprint="obsolete-gate", **arguments)
    assert snapshot(runtime) == before
    blocked = call(runtime, scoped, "answer_gate", "inapplicable-answer-fields",
        gate_fingerprint=gate["dependency_fingerprint"], response={**arguments["response"], "classification": "selected"})
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "packet_reconciliation_fields_not_applicable"
    assert blocked["result"]["current_authority"] == current(runtime, scoped)
    assert blocked["result"]["gate"] == gate
    assert snapshot(runtime) == before
    result = assert_current(runtime, scoped, call(runtime, scoped, "answer_gate", "answer-current-gate",
        gate_fingerprint=gate["dependency_fingerprint"], **arguments))
    assert result["semantic_delta"]["operation"] == "answer_gate"
    assert "affected_unit_key" not in result["semantic_delta"]


def test_invalid_question_batch_does_not_resolve_earlier_answers_or_change_authority(authored):
    runtime, ids = authored
    audit = runtime.packet_construction.audit_for_packet(*ids)
    before = snapshot(runtime)
    response = call(runtime, ids, "resolve_questions", "invalid-question-batch", answers=[
        {"question_id": audit["questions"][0]["question_id"], "answer_summary": "This answer must roll back."},
        {"question_id": "PQUESTION-999999", "answer_summary": "Unknown question."}], **current(runtime, ids))
    assert response["status"] == "rejected"
    assert response["result"]["effect_state"] == "unknown"
    assert response["result"]["diagnostics"][0]["field"] == "answers.question_id"
    assert snapshot(runtime) == before


def test_changed_mutation_replay_is_rejected_without_partial_authority(authored):
    runtime, ids = authored
    revisions = current(runtime, ids)
    call(runtime, ids, "revise_unit", "changed-replay", **mutation_arguments("revise_unit"), **revisions)
    before = snapshot(runtime)
    rejected = call(runtime, ids, "revise_unit", "changed-replay", client_unit_key="consumer",
                    unit_patch={"instructions": ["Different work under the same request identity."]}, **revisions)
    assert_unknown_rejection(rejected, reason="state_conflict", request_id="changed-replay")
    assert snapshot(runtime) == before


def test_old_replace_with_answers_never_resolves_new_questions_or_rebinds_history(authored, monkeypatch):
    runtime, ids = authored
    audit = runtime.packet_construction.audit_for_packet(*ids)
    arguments = {"work_plan": {"units": deepcopy(runtime.ledger.packet_work_plan_state(*ids)["units"])},
                 "answers": [{"question_id": audit["questions"][0]["question_id"],
                              "answer_summary": "The original question has this recorded answer."}], **current(runtime, ids)}
    original = call(runtime, ids, "replace_plan", "replace-with-original-answers", **arguments)
    call(runtime, ids, "revise_packet", "new-authority-question", unresolved_questions=["Which new customer decision is required?"],
         **current(runtime, ids))
    before = snapshot(runtime)

    def no_queue(*args, **kwargs):
        raise AssertionError("An old replace-plan replay must not queue work")

    monkeypatch.setattr(runtime.packet_provider_overlay, "queue_plan_delta", no_queue)
    replay = assert_current(runtime, ids, call(runtime, ids, "replace_plan", "replace-with-original-answers", **arguments))
    assert replay["packet"]["spec_revision"] == original["result"]["packet"]["spec_revision"]
    assert replay["semantic_delta"]["replayed"] is True
    assert snapshot(runtime) == before
    remaining = runtime.packet_construction.audit_for_packet(*ids)
    assert any(question["question_key"] == "authority_blocker" and question["status"] == "open"
               for question in remaining["questions"])


def test_affected_unit_identity_is_normalized_in_fresh_and_replay(authored):
    runtime, ids = authored
    arguments = {"client_unit_key": " consumer ", "unit_patch": {"instructions": ["Call the canonical increment API."]},
                 **current(runtime, ids)}
    for _attempt in range(2):
        result = assert_current(runtime, ids, call(runtime, ids, "revise_unit", "normalized-key", **arguments))
        assert result["mutation"]["affected_unit_key"] == "consumer"


@pytest.mark.parametrize("operation,arguments", [
    ("revise_unit", {"client_unit_key": "consumer", "unit_patch": {"instructions": []}}),
    ("remove_unit", {"client_unit_key": "producer"}),
    ("add_unit", {"unit": extra_unit(), "target_selection": {"mutation_candidate": 1}}),
])
def test_failed_authoring_preserves_all_durable_authority(authored, operation, arguments):
    runtime, ids = authored
    before = snapshot(runtime)
    if operation == "revise_unit":
        rejected = call(runtime, ids, operation, "invalid-author-" + operation, **arguments, **current(runtime, ids))
        assert_unknown_rejection(rejected, reason="invalid_input", request_id="invalid-author-revise_unit")
    else:
        with pytest.raises((ValueError, ChangeControlBlockedError, RequirementConflictError)):
            call(runtime, ids, operation, "invalid-author-" + operation, **arguments, **current(runtime, ids))
    assert snapshot(runtime) == before


def test_cross_packet_request_reuse_rejects_before_ancillary_lifecycle_repair(authored):
    from flow_of_work_mcp import ImplementationPacketDraft

    runtime, ids = authored
    arguments = mutation_arguments("revise_unit")
    call(runtime, ids, "revise_unit", "project-scoped-author-request", **arguments, **current(runtime, ids))
    changed = runtime.changes.add_packet(
        ids[0], ids[1], ImplementationPacketDraft(
            title="Independent packet without author substrate",
            objective="Preserve this packet when a foreign request is rejected.",
            rationale="A project request belongs to exactly one canonical packet.",
            completion_criteria=("The producer retains its contract.", "The consumer uses the producer."),
        ), actor="engineer", request_id="second-packet",
    )
    packet = next(item for item in changed["packets"] if item["packet_id"] != ids[2])
    scoped = (ids[0], ids[1], packet["packet_id"])
    runtime.packet_work_plan.set_plan(
        *scoped, {"units": deepcopy(runtime.ledger.packet_work_plan_state(*ids)["units"])},
        expected_packet_revision=packet["spec_revision"], expected_current_plan_revision=0,
        actor="engineer", request_id="second-packet-plan",
    )
    assert runtime.packet_construction.audit_for_packet(*scoped) is None
    before = snapshot(runtime)
    blocked = call(runtime, scoped, "revise_unit", "project-scoped-author-request", **arguments, **current(runtime, scoped))
    assert_unknown_rejection(blocked, status="blocked", reason="packet_work_plan_request_scope_conflict",
                             request_id="project-scoped-author-request")
    assert snapshot(runtime) == before
    assert runtime.packet_construction.audit_for_packet(*scoped) is None


def assert_unknown_rejection(response, *, reason, request_id, status="rejected"):
    assert response["status"] == status and response["reason"] == reason
    result = response["result"]
    assert result["effect_state"] == "unknown" and result["operation_state"] == "unknown"
    assert "effect_receipt" not in result
    assert result["original_request"]["operation"] == "revise_unit"
    assert result["original_request"]["request_id"] == request_id
