"""Cross-case questions, source/IR independence and truthful recovery."""
import asyncio
import json
import sqlite3

import pytest

from flow_of_work_mcp import GovernedChangeDraft, RequirementDraft
from flow_of_work_mcp.core.domain import (
    BehavioralOracleDraft, CampaignCaseSemanticDraft, CampaignObligationDecision,
    CampaignScopeDraft,
)
from flow_of_work_mcp.core.errors import RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import create_app, handle_campaign_author, handle_campaign_inspect


def fields(execution_class="deterministic"):
    return {
        "preconditions": ["one project exists"], "stimulus": "read current result",
        "input_domain": {"project": "current"},
        "expected_observations": ["current result"], "invariants": ["history is retained"],
        "forbidden_effects": ["unintended writes"], "tolerances": {"count": 0},
        "expected_failure_transitions": ["invalid input is rejected"],
        "oracle_violation_conditions": ["stale output"],
        "execution_class": execution_class, "verification_intent": "observe the public result",
    }


def case(title):
    return CampaignCaseSemanticDraft(title=title, purpose="Observe a current result",
        case_kind="positive", action="Invoke the public operation",
        expected_outcome="Current result", prohibited_outcome="Stale result",
        observation_point="Public response")


@pytest.fixture
def owned(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "owned.sqlite3", import_root=tmp_path)
    runtime.requirements.create_project("question-test", "Owned question regression", actor="test")
    req = runtime.requirements.register("question-test", RequirementDraft(
        title="Current result", statement="The software shall return a current result.",
        category="functional", rationale="Bounded regression"), actor="test")
    change = runtime.changes.create_change("question-test", GovernedChangeDraft(
        title="Question regression", rationale="Observe source/IR independence",
        requirement_ids=(req["requirement_id"],)), actor="test")
    state = runtime.ledger.start_campaign_authority("question-test", title="Owned campaign",
        scope=CampaignScopeDraft(change_id=change["change_id"],
            requirement_ids=(req["requirement_id"],)), first_case=case("First"),
        actor="test", request_id="start")
    campaign_id = state["campaign_id"]
    state = runtime.ledger.derive_campaign_obligations("question-test", campaign_id,
        actor="test", request_id="derive")
    for n, obligation in enumerate(state["obligations"]):
        runtime.ledger.decide_campaign_obligation("question-test", campaign_id,
            obligation["obligation_id"], decision=CampaignObligationDecision.REQUIRED,
            rationale="Required observation", actor="test", request_id=f"decide-{n}")
        runtime.ledger.bind_campaign_case_obligation("question-test", campaign_id,
            "CASE-000001", obligation["obligation_id"], coverage_intent="direct",
            actor="test", request_id=f"bind-{n}")
    yield runtime, campaign_id, req["requirement_id"]
    runtime.close()


def author(owned, case_id="CASE-000001", semantic_fields=None, request_id="oracle"):
    runtime, campaign_id, requirement_id = owned
    return runtime.ledger.author_behavioral_oracle("question-test", campaign_id, case_id,
        BehavioralOracleDraft(oracle_kind="behavior", subject_bindings=(requirement_id,),
            authority_reference="decision:owned-regression", semantic_fields=semantic_fields or {}),
        actor="test", request_id=request_id)


def read(owned, view="summary"):
    runtime, campaign_id, _ = owned
    return handle_campaign_inspect(runtime, project_id="question-test", campaign_id=campaign_id, view=view)


def answer(owned, oracle_id, question_id, **kwargs):
    runtime, campaign_id, _ = owned
    return handle_campaign_author(runtime, project_id="question-test", campaign_id=campaign_id,
        operation="answer_question", actor="test", oracle_id=oracle_id, question_id=question_id,
        **{"request_id": "answer", "answer": ["project exists"],
           "answer_authority": "grounded_fact", "provenance": ["source:owned"], **kwargs})


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


def second_oracle(owned):
    runtime, campaign_id, _ = owned
    runtime.ledger.add_campaign_authority_case("question-test", campaign_id, case("Second"),
        actor="test", request_id="second-case")
    return author(owned, "CASE-000002", request_id="second-oracle")


def test_ordered_remaining_source_fields_and_conditional_phases_in_both_channels(owned):
    runtime, campaign_id, _ = owned
    author(owned)

    async def run():
        app = create_app(runtime)
        scope = {"project_id": "question-test", "campaign_id": campaign_id}
        inspection = await app.call_tool("fow_campaign_inspect", scope)
        initial = inspection.structuredContent["result"]["result"]
        work = initial["lifecycle_gate"]["work_remaining"]
        questions = work["oracle_questions"]
        assert work["current_phase"] == "oracle" and work["effort"] == "undetermined"
        assert [row["phase"] for row in work["conditional_phases"]] == [
            "attestation", "evidence", "promotion", "coverage",
        ]
        assert questions["current_question_id"] == "Q-preconditions"
        assert questions["oracle_revision"] == 1 and questions["scope"] == "source"
        expected = [row["question_id"] for row in questions["ordered_missing_fields"]]
        exact = read(owned, "oracles")["result"]["oracles"][0]
        assert expected == [row["question_id"] for row in exact["questions"]]
        markdown = inspection.content[0].text
        assert "(11 remaining)" in markdown and "Later phases if still applicable" in markdown
        assert markdown.index("Q-preconditions") < markdown.index("Q-stimulus") < markdown.index("Q-input-domain")
        assert "answer_question" in markdown and "Optional revision pin" in markdown
        assert initial["campaign"]["fingerprint"] not in markdown

        answered = await app.call_tool("fow_campaign_author", {
            **scope, "operation": "answer_question", "oracle_id": questions["oracle_id"],
            "question_id": questions["current_question_id"], "actor": "test", "request_id": "public-answer",
            "answer": ["project exists"], "answer_authority": "grounded_fact", "provenance": ["source:owned"],
        })
        body = answered.structuredContent["result"]["result"]
        remaining = body["lifecycle_gate"]["work_remaining"]["oracle_questions"]
        assert remaining["oracle_revision"] == 2 and remaining["current_question_id"] == "Q-stimulus"
        assert [row["question_id"] for row in remaining["ordered_missing_fields"]] == expected[1:]
        assert body["campaign"]["fingerprint"] and body["semantic_delta"]["changed"] is True
        receipt = answered.content[0].text
        assert "(10 remaining)" in receipt and "Q-preconditions" not in receipt
        assert body["campaign"]["fingerprint"] not in receipt and "Semantic Delta" not in receipt
        assert "Later phases if still applicable" not in receipt

    asyncio.run(run())


def test_advancement_stops_at_the_current_question_and_names_its_author_route(owned):
    runtime, campaign_id, _ = owned
    author(owned)
    before = dump(runtime)

    async def run():
        app = create_app(runtime)
        result = await app.call_tool("fow_campaign_advance", {
            "project_id": "question-test", "campaign_id": campaign_id,
            "actor": "test", "request_id": "advance-at-question",
        })
        assert result.structuredContent["result"]["result"]["transitions"] == []
        markdown = result.content[0].text
        assert "Q-preconditions" in markdown and "fow_campaign_author" in markdown and "answer_question" in markdown
        assert "Semantic Delta" not in markdown and "Dependency Fingerprint" not in markdown

    asyncio.run(run())
    assert dump(runtime) == before


@pytest.mark.parametrize(("state", "reason", "next_step"), [
    ("provider_rejected", "effective_project_cross_domain_collision", "unused provider destination"),
    ("provider_rejected", "provider_route_unavailable", "retry_provider_rejection"),
    ("provider_unknown", "test_provider_response_unknown", "same durable command"),
])
def test_campaign_markdown_prioritizes_the_provider_delivery_failure(state, reason, next_step):
    next_action = (
        {
            "tool": "fow_campaign_author",
            "operation": "retry_provider_rejection",
            "arguments": {"campaign_id": "CAMP-000001", "provider_command_id": "TCMD-000001"},
            "required_inputs": ["rationale", "request_id"],
        }
        if state == "provider_rejected" else "retry this same durable command"
    )
    body = {
        "campaign": {"campaign_id": "CAMP-000001"},
        "lifecycle_gate": {
            "state": "provider_boundary", "lifecycle_state": "ready_to_run",
            "next_action": {"tool": "fow_campaign_advance", "operation": "deliver_test_command"},
            "work_remaining": {},
        },
        "provider_boundary": {
            "state": state,
            "next_action": next_action,
            "deliveries": [{
                "state": state, "reason": reason, "next_action": next_action,
                "outbox": {"command_id": "TCMD-000001", "case_id": "CASE-000001"},
            }],
        },
    }
    markdown = project_markdown("fow_campaign_advance", {"status": "success", "result": body})
    assert state in markdown and reason in markdown and next_step in markdown
    assert "CASE-000001" in markdown and "TCMD-000001" in markdown
    assert "pending technical validation" not in markdown
    if reason == "effective_project_cross_domain_collision":
        assert "colliding draft is cleared" in markdown
        assert "attest_source" in markdown and "retry_provider_rejection" not in markdown


def test_ordered_fields_reflect_conditional_source_oracle_schema(owned):
    runtime, campaign_id, requirement_id = owned
    runtime.ledger.author_behavioral_oracle("question-test", campaign_id, "CASE-000001",
        BehavioralOracleDraft(oracle_kind="integration", subject_bindings=(requirement_id,),
            authority_reference="decision:integration", semantic_fields=fields("integration")),
        actor="test", request_id="integration-oracle")
    questions = read(owned)["result"]["lifecycle_gate"]["work_remaining"]["oracle_questions"]
    assert questions["scope"] == "source"
    assert questions["ordered_missing_fields"] == [
        {"field_name": "participants", "question_id": "Q-participants"},
        {"field_name": "real_mock_boundaries", "question_id": "Q-real-mock-boundaries"},
    ]


@pytest.mark.parametrize("execution_class", ["live", "deterministic"])
def test_all_source_questions_precede_other_cases_optional_ir(owned, execution_class):
    author(owned, semantic_fields=fields(execution_class))
    state = second_oracle(owned)
    gate = read(owned)["result"]["lifecycle_gate"]
    selected = gate["decision_required"]
    assert selected["oracle_id"] == "ORACLE-000002"
    assert selected["case_id"] == "CASE-000002"
    assert selected["oracle_revision"] == 1 and selected["scope"] == "source"
    assert gate["next_action"]["arguments"]["question_id"] == "Q-preconditions"
    questions = gate["work_remaining"]["oracle_questions"]
    assert questions["oracle_id"] == "ORACLE-000002" and questions["scope"] == "source"
    assert "Q-operator-profile" not in [row["question_id"] for row in questions["ordered_missing_fields"]]
    ir = read(owned, "oracle_ir")["result"]["oracle_ir"]
    for item in ir:
        action = item["next_action"]
        if action["operation"] == "answer_question":
            assert action["arguments"]["oracle_id"] == "ORACLE-000002"
    result = answer(owned, "ORACLE-000002", "Q-preconditions")
    assert result["status"] == "success", result
    assert result["result"]["campaign"]["revision"] > state["revision"]
    assert result["result"]["campaign"]["completed"] is False
    assert result["result"]["campaign"]["attestation_count"] == 0
    assert result["result"]["campaign"]["evidence_count"] == 0


@pytest.mark.parametrize("execution_class", ["live", "integration", "manual"])
def test_non_deterministic_source_has_no_actionable_ir_or_semantic_rewrite(owned, execution_class):
    state = author(owned, semantic_fields=fields(execution_class))
    assert state["constructibility"] == "ready_to_run"
    assert state["oracles"][0]["oracle_ir_questions"] == []
    ir = read(owned, "oracle_ir")["result"]["oracle_ir"][0]
    assert ir["constructible"] is False
    assert any(r["kind"] == "unsupported" and r["field_name"] == "execution_class" for r in ir["residuals"])
    assert ir["next_question"] is None
    assert ir["next_action"]["operation"] == "attest_source"
    assert state["oracles"][0]["payload"]["semantic_fields"]["execution_class"] == execution_class


def test_historical_live_ir_rows_remain_stored_but_do_not_block_source(owned):
    runtime, campaign_id, _ = owned
    state = author(owned, semantic_fields=fields("live"))
    oracle = state["oracles"][0]
    with runtime.ledger._transaction() as connection:
        connection.execute("""INSERT OR IGNORE INTO oracle_questions
            (project_id,oracle_id,oracle_revision,question_id,ordinal,question_scope,
             field_name,prompt,choices_json,required)
            VALUES (?,?,?,?,1,'oracle_ir','operator_profile','Historical profile','[]',1)""",
            ("question-test", oracle["oracle_id"], oracle["revision"], "Q-operator-profile"))
    second_oracle(owned)
    assert answer(owned, "ORACLE-000002", "Q-preconditions")["status"] == "success"
    retained = runtime.ledger.campaign_authority_state("question-test", campaign_id)
    assert retained["oracles"][0]["oracle_ir_questions"][0]["question_id"] == "Q-operator-profile"


def test_same_id_wrong_oracle_has_bounded_identity_and_read_recovery(owned, monkeypatch):
    runtime, _, _ = owned
    author(owned)
    second_oracle(owned)
    before = dump(runtime)
    result = answer(owned, "ORACLE-000002", "Q-preconditions")
    assert result["status"] == "rejected" and result["reason"] == "oracle_question_not_current"
    body = result["result"]
    detail = body["diagnostics"][0]
    assert detail["expected"]["oracle_id"] == "ORACLE-000001"
    assert detail["expected"]["scope"] == "source"
    assert detail["expected"]["oracle_revision"] == 1
    assert detail["received"] == {"oracle_id": "ORACLE-000002", "question_id": "Q-preconditions"}
    assert body["next_tool_call"]["tool"] == "fow_campaign_inspect"
    assert body["next_tool_call"]["arguments"]["view"] == "oracles"
    assert body["effect_state"] == "unknown" and "effect_receipt" not in body
    assert body["original_request"]["request_id"] == "answer"
    assert dump(runtime) == before
    import flow_of_work_mcp.server as server
    monkeypatch.setattr(server, "_campaign_recovery_projection", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("recovery failed")))
    repeated = answer(owned, "ORACLE-000002", "Q-preconditions")
    assert repeated["result"]["diagnostics"][0]["expected"] == detail["expected"]
    assert dump(runtime) == before


def test_optional_fingerprint_rejects_new_stale_request_but_preserves_exact_replay(owned):
    runtime, _, _ = owned
    original = author(owned)
    fingerprint = original["fingerprint"]
    first = answer(owned, "ORACLE-000001", "Q-preconditions", expected_fingerprint=fingerprint)
    assert first["status"] == "success"
    before = dump(runtime)
    replay = answer(owned, "ORACLE-000001", "Q-preconditions", expected_fingerprint=fingerprint)
    assert replay["status"] == "success" and replay["result"]["semantic_delta"]["replayed"]
    assert dump(runtime) == before
    stale = answer(owned, "ORACLE-000001", "Q-stimulus", answer="observe", request_id="stale",
                   expected_fingerprint=fingerprint)
    assert stale["status"] == "blocked" and stale["reason"] == "campaign_revision_stale"
    assert dump(runtime) == before
    conflict = answer(owned, "ORACLE-000001", "Q-preconditions", answer=["different"])
    assert conflict["status"] == "rejected" and conflict["reason"] == "state_conflict"
    assert dump(runtime) == before


@pytest.mark.parametrize("authority", ["unknown", "derived_hypothesis", "waived"])
def test_non_authoritative_answer_never_closes_required_source(owned, authority):
    runtime, campaign_id, _ = owned
    author(owned)
    result = answer(owned, "ORACLE-000001", "Q-preconditions", answer_authority=authority,
                    waiver_scope="owned explicit scope" if authority == "waived" else "")
    assert result["status"] == "success"
    state = runtime.ledger.campaign_authority_state("question-test", campaign_id)
    assert state["oracles"][0]["revision"] == 1
    assert state["oracles"][0]["questions"][0]["field_name"] == "preconditions"
    assert state["constructibility"] == "needs_oracle"


def test_invalid_inspect_is_observation_error_with_valid_help_and_no_write(owned):
    runtime, _, _ = owned
    before = dump(runtime)
    response = read(owned, "nonexistent")
    body = response["result"]
    assert response["reason"] == "invalid_input" and body["read_only"] is True
    assert not {"effect_state", "operation_state", "effect_receipt"}.intersection(body)
    assert "oracles" in body["diagnostics"][0]["accepted_values"]
    assert body["next_tool_call"]["arguments"]["operation_name"] == "summary"
    assert dump(runtime) == before


def test_unexpected_inspection_failure_is_not_unknown_mutation(owned, monkeypatch):
    runtime, _, _ = owned
    before = dump(runtime)
    monkeypatch.setattr(runtime.campaign_authority, "inspect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private failure")))
    response = read(owned, "oracles")
    body = response["result"]
    assert response["reason"] == "internal_error" and body["read_only"] is True
    assert not {"effect_state", "operation_state", "effect_receipt"}.intersection(body)
    assert "private failure" not in json.dumps(response)
    assert dump(runtime) == before


def test_late_projection_failure_retains_unknown_and_original_request(owned, monkeypatch):
    runtime, _, _ = owned
    author(owned)
    before = dump(runtime)
    monkeypatch.setattr(runtime.campaign_authority, "_mutation_projection", lambda *a, **k: (_ for _ in ()).throw(ValueError("late projection")))
    response = answer(owned, "ORACLE-000001", "Q-preconditions")
    assert response["result"]["effect_state"] == "unknown"
    assert "effect_receipt" not in response["result"]
    assert response["result"]["original_request"]["request_id"] == "answer"
    assert dump(runtime) != before


def test_generic_conflict_remains_redacted(owned, monkeypatch):
    runtime, _, _ = owned
    monkeypatch.setattr(runtime.campaign_authority, "answer_question", lambda *a, **k: (_ for _ in ()).throw(RequirementConflictError("secret arbitrary conflict")))
    response = answer(owned, "ORACLE-000001", "Q-preconditions")
    assert response["reason"] == "state_conflict"
    assert "secret arbitrary conflict" not in json.dumps(response)
    assert response["result"]["effect_state"] == "unknown"


def test_missing_source_oracle_precedes_optional_ir(owned):
    runtime, campaign_id, _ = owned
    author(owned, semantic_fields=fields())
    runtime.ledger.add_campaign_authority_case("question-test", campaign_id, case("Second"),
        actor="test", request_id="second-case")
    gate = read(owned)["result"]["lifecycle_gate"]
    assert gate["next_action"] == {"tool": "fow_campaign_author", "operation": "author_oracle",
                                    "arguments": {"case_id": "CASE-000002"}}
    assert "oracle_questions" not in gate["work_remaining"]
    assert read(owned, "oracle_ir")["result"]["oracle_ir"][0]["next_action"] == gate["next_action"]
    before = dump(runtime)
    assert answer(owned, "ORACLE-000001", "Q-operator-profile")["reason"] == "oracle_question_unavailable"
    assert dump(runtime) == before


def test_two_complete_sources_expose_one_admissible_optional_ir_question(owned):
    runtime, campaign_id, _ = owned
    author(owned, semantic_fields=fields())
    runtime.ledger.add_campaign_authority_case("question-test", campaign_id, case("Second"),
        actor="test", request_id="second-case")
    author(owned, "CASE-000002", fields(), "second-oracle")
    projections = read(owned, "oracle_ir")["result"]["oracle_ir"]
    work = read(owned)["result"]["lifecycle_gate"]["work_remaining"]
    assert work["oracle_questions"]["scope"] == "oracle_ir"
    assert work["oracle_questions"]["other_pending_questions"] >= 1
    for p in projections:
        arguments = p["next_action"]["arguments"]
        assert arguments["oracle_id"] == "ORACLE-000001"
        assert arguments["question_id"] == "Q-operator-profile"
        assert arguments["expected_fingerprint"]
    assert projections[0]["next_question"]["scope"] == "oracle_ir"
    assert projections[1]["next_question"] is None
    summary = asyncio.run(create_app(runtime).call_tool("fow_campaign_inspect", {
        "project_id": "question-test", "campaign_id": campaign_id, "view": "summary",
    }))
    markdown = summary.content[0].text
    assert "Optional deterministic IR" in markdown and "view=oracle_ir" in markdown
    assert "Current answer slot" not in markdown and "Q-operator-profile" not in markdown
    assert answer(owned, "ORACLE-000002", "Q-operator-profile")["reason"] == "oracle_question_not_current"
    from flow_of_work_mcp.core.domain import ORACLE_IR_OPERATOR_PROFILE
    assert answer(owned, "ORACLE-000001", "Q-operator-profile", answer=ORACLE_IR_OPERATOR_PROFILE)["status"] == "success"


def test_explicit_unsupported_profile_retains_source_route(owned):
    value = {**fields(), "operator_profile": "unsupported.profile.v999"}
    state = author(owned, semantic_fields=value)
    assert state["oracles"][0]["oracle_ir_questions"] == []
    ir = read(owned, "oracle_ir")["result"]["oracle_ir"][0]
    assert any(r["kind"] == "unsupported" and r["field_name"] == "operator_profile" for r in ir["residuals"])
    assert ir["next_question"] is None and ir["next_action"]["operation"] == "attest_source"


def test_other_campaign_oracle_revision_requires_exact_binding_repair(owned):
    runtime, campaign_id, requirement_id = owned
    state = author(owned)
    other = runtime.ledger.start_campaign_authority("question-test", title="Other owned campaign",
        scope=CampaignScopeDraft(change_id=state["change_id"], requirement_ids=(requirement_id,)),
        first_case=case("Other"), actor="test", request_id="other-start")
    runtime.ledger.author_behavioral_oracle("question-test", other["campaign_id"], "CASE-000001",
        BehavioralOracleDraft(oracle_kind="behavior", subject_bindings=(requirement_id,),
            authority_reference="decision:other", semantic_fields=fields()),
        oracle_id="ORACLE-000001", actor="test", request_id="other-oracle")
    gate = read(owned)["result"]["lifecycle_gate"]
    assert gate["next_action"] == {"tool": "fow_campaign_author", "operation": "author_oracle",
        "arguments": {"case_id": "CASE-000001", "oracle_id": "ORACLE-000001"}}
    assert read(owned, "oracle_ir")["result"]["oracle_ir"][0]["next_action"] == gate["next_action"]
    before = dump(runtime)
    assert answer(owned, "ORACLE-000001", "Q-preconditions")["reason"] == "oracle_question_unavailable"
    assert dump(runtime) == before


def test_invalid_view_is_rejected_even_when_project_has_no_campaign(owned):
    runtime, _, _ = owned
    runtime.requirements.create_project("empty-test", "Empty owned project", actor="test")
    before = dump(runtime)
    response = handle_campaign_inspect(runtime, project_id="empty-test", view="nonexistent")
    assert response["status"] == "rejected" and response["reason"] == "invalid_input"
    assert response["result"]["read_only"] is True
    assert dump(runtime) == before


def test_campaign_working_views_preserve_the_gate_and_separate_the_typed_data(owned):
    runtime, campaign_id, _ = owned
    author(owned)

    async def inspect():
        app = create_app(runtime)
        scope = {"project_id": "question-test", "campaign_id": campaign_id}
        for view in ("working_sheet", "cases", "obligations", "oracles", "constructibility",
                     "oracle_ir", "attestation", "evidence", "residuals", "history"):
            reply = await app.call_tool("fow_campaign_inspect", {**scope, "view": view})
            body = reply.structuredContent["result"]["result"]
            markdown = reply.content[0].text
            assert body["campaign"]["campaign_id"] == campaign_id
            assert "Current gate" in markdown and "Next step" in markdown and "```json" not in markdown
            if view in {"oracles", "obligations"}:
                assert body["campaign"]["fingerprint"] in markdown
        rejected = await app.call_tool("fow_campaign_inspect", {**scope, "view": "wrong-view"})
        assert "Cause" in rejected.content[0].text and "Input to correct" in rejected.content[0].text
        assert "Next step" in rejected.content[0].text and "```json" not in rejected.content[0].text

    asyncio.run(inspect())


def test_received_identity_is_bounded_without_changing_admission(owned):
    author(owned)
    response = answer(owned, "ORACLE-000001", "Q-" + "x" * 20_000, request_id="r" * 10_000)
    body = response["result"]
    received = body["diagnostics"][0]["received"]
    assert len(received["question_id"]) == 160
    assert received["question_id_length"] == 20_002 and received["question_id_truncated"] is True
    assert len(body["original_request"]["request_id"]) == 160
    assert body["original_request"]["request_id_length"] == 10_000


def test_newer_recovery_does_not_replace_conflict_snapshot(owned, monkeypatch):
    runtime, campaign_id, _ = owned
    original = author(owned)
    import flow_of_work_mcp.server as server
    real_recovery = server._campaign_recovery_projection
    def recovery(*args, **kwargs):
        runtime.ledger.add_campaign_authority_case("question-test", campaign_id, case("Recovery advancement"),
            actor="test", request_id="recovery-observed-newer")
        return real_recovery(*args, **kwargs)
    monkeypatch.setattr(server, "_campaign_recovery_projection", recovery)
    response = answer(owned, "ORACLE-000001", "Q-stimulus")
    result = response["result"]
    assert result["diagnostics"][0]["current_authority"]["revision"] == original["revision"]
    assert result["campaign"]["revision"] > original["revision"]
    assert result["effect_state"] == "unknown"
