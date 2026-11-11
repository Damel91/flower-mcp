import json
import sqlite3
from hashlib import sha256

import pytest

from flow_of_work_mcp.application import ChangeControlService, RequirementService
from flow_of_work_mcp.core.domain import (
    ORACLE_IR_OPERATOR_PROFILE,
    BehavioralOracleDraft,
    CampaignCaseSemanticDraft,
    CampaignObligationDecision,
    CampaignScopeDraft,
    GovernedChangeDraft,
    OracleAnswerAuthority,
    RequirementDraft,
    canonical_json,
    compile_oracle_ir,
    semantic_fingerprint,
)
from flow_of_work_mcp.core.errors import AssuranceBlockedError, RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import (
    handle_campaign_advance,
    handle_campaign_author,
    handle_campaign_inspect,
)


def _runtime(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "campaign.sqlite3", import_root=tmp_path
    )
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Alpha", actor="orchestrator")
    requirement = requirements.register(
        "alpha",
        RequirementDraft(
            title="Bounded lifecycle",
            statement="The service shall return one bounded lifecycle result.",
            category="functional",
            rationale="The campaign needs one current behavioral source.",
        ),
        actor="orchestrator",
    )
    change = ChangeControlService(runtime.ledger).create_change(
        "alpha",
        GovernedChangeDraft(
            title="Campaign authority",
            rationale="Qualify the current behavior.",
            requirement_ids=(str(requirement["requirement_id"]),),
        ),
        actor="orchestrator",
    )
    return runtime, str(change["change_id"]), str(requirement["requirement_id"])


def _case(title: str = "Nominal behavior") -> CampaignCaseSemanticDraft:
    return CampaignCaseSemanticDraft(
        title=title,
        purpose="Prove the current requirement.",
        case_kind="positive",
        action="Invoke the bounded lifecycle operation.",
        expected_outcome="One current result is returned.",
        prohibited_outcome="No stale result is returned.",
        observation_point="The public operation receipt.",
    )


def _complete_fields():
    return {
        "preconditions": ["one current project exists"],
        "stimulus": "invoke the lifecycle operation",
        "input_domain": {"project": "current"},
        "expected_observations": ["one bounded result"],
        "invariants": ["history remains immutable"],
        "forbidden_effects": ["stale authority is promoted"],
        "tolerances": {"count": 0},
        "expected_failure_transitions": ["invalid input is rejected"],
        "oracle_violation_conditions": ["the result is stale"],
        "execution_class": "deterministic",
        "verification_intent": "prove current bounded behavior",
    }


def _complete_typed_ir_fields():
    return {
        "operator_profile": ORACLE_IR_OPERATOR_PROFILE,
        "preconditions": [{"source": "state", "matcher": "truthy", "path": ["ready"]}],
        "stimulus": {
            "operator": "call",
            "subject_ref": "REQ-000001",
            "arguments": [],
        },
        "input_domain": {"project": "current"},
        "expected_observations": [{"source": "return", "matcher": "truthy"}],
        "invariants": [],
        "forbidden_effects": [],
        "tolerances": {"count": 0},
        "expected_failure_transitions": [],
        "oracle_violation_conditions": [],
        "execution_class": "deterministic",
        "verification_intent": "prove current bounded behavior",
    }


def _start(runtime, change_id, requirement_id, request_id="start-1"):
    return runtime.ledger.start_campaign_authority(
        "alpha",
        title="Qualified campaign",
        scope=CampaignScopeDraft(
            change_id=change_id,
            requirement_ids=(requirement_id,),
            invariants=("history remains immutable",),
        ),
        first_case=_case(),
        actor="orchestrator",
        request_id=request_id,
    )


def test_canonical_semantic_fingerprint_ignores_mapping_and_whitespace_order():
    left = {"b": ["two   words", {"z": 1, "a": True}], "a": " value "}
    right = {"a": "value", "b": ["two words", {"a": True, "z": 1}]}

    assert canonical_json(left) == canonical_json(right)
    assert semantic_fingerprint(left) == semantic_fingerprint(right)


def test_campaign_start_is_atomic_replay_safe_and_restart_safe(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    first = _start(runtime, change_id, requirement_id)
    replay = _start(runtime, change_id, requirement_id)

    assert first["campaign_id"] == "CAMP-000001"
    assert first["revision"] == 1
    assert replay["campaign_id"] == first["campaign_id"]
    assert replay["replayed"] is True
    runtime.close()

    restarted = build_runtime(
        database_path=tmp_path / "campaign.sqlite3", import_root=tmp_path
    )
    try:
        recovered = restarted.ledger.campaign_authority_state("alpha", "CAMP-000001")
        assert recovered["fingerprint"] == first["fingerprint"]
        assert recovered["cases"][0]["action"].startswith("Invoke")
    finally:
        restarted.close()


def test_campaign_obligations_require_decision_and_case_binding(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", state["campaign_id"], actor="orchestrator", request_id="derive"
        )
        assert state["constructibility"] == "needs_obligations"
        assert {item["kind"] for item in state["obligations"]} == {
            "primary_behavior",
            "invariant_preservation",
        }
        for index, obligation in enumerate(state["obligations"]):
            state = runtime.ledger.decide_campaign_obligation(
                "alpha",
                state["campaign_id"],
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="This is part of the accepted scope.",
                actor="orchestrator",
                request_id=f"decide-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                state["campaign_id"],
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="The case observes this exact obligation.",
                actor="orchestrator",
                request_id=f"bind-{index}",
            )
        assert state["constructibility"] == "needs_oracle"
    finally:
        runtime.close()


def test_grouped_campaign_authoring_replays_its_receipt_after_later_revision(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        campaign_id = state["campaign_id"]
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", campaign_id, actor="orchestrator", request_id="derive"
        )
        entries = state["obligations"]
        request = dict(
            project_id="alpha", operation="author_obligations", campaign_id=campaign_id,
            actor="orchestrator", request_id="group-1", expected_fingerprint=state["fingerprint"],
            obligation_batch={
                "decisions": [
                    dict(obligation_id=item["obligation_id"], decision="required", rationale="In scope.")
                    for item in entries
                ],
                "bindings": [
                    dict(case_id="CASE-000001", obligation_id=item["obligation_id"], coverage_intent="Observe case output.")
                    for item in entries
                ],
            },
        )
        result = handle_campaign_author(runtime, **request)["result"]
        receipt = result["authoring_receipt"]
        assert receipt["basis"]["revision"] == state["revision"]
        assert receipt["result"]["revision"] == state["revision"] + 1
        assert len({item["event_id"] for item in receipt["items"]}) == 4
        assert result["campaign"]["constructibility"] == "needs_oracle"
        later = runtime.ledger.add_campaign_authority_case(
            "alpha", campaign_id, _case("Another case"), actor="orchestrator", request_id="later",
        )
        replay = handle_campaign_author(runtime, **request)["result"]
        assert replay["replayed"] is True
        assert replay["authoring_receipt"] == receipt
        assert replay["campaign"]["revision"] == later["revision"]
        conflict = handle_campaign_author(runtime, **(request | {"actor": "other"}))
        assert conflict["status"] == "rejected"
        assert conflict["result"]["diagnostics"][0]["field"] == "request_id"
    finally:
        runtime.close()


def test_grouped_campaign_authoring_rejects_bad_final_entry_and_stale_basis(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        campaign_id = state["campaign_id"]
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", campaign_id, actor="orchestrator", request_id="derive"
        )
        obligation_id = state["obligations"][0]["obligation_id"]
        decision = dict(obligation_id=obligation_id, decision="required", rationale="In scope.")
        binding = dict(case_id="CASE-000999", obligation_id=obligation_id, coverage_intent="Observe result.")
        request = dict(
            project_id="alpha", operation="author_obligations", campaign_id=campaign_id,
            actor="orchestrator", request_id="group-1", expected_fingerprint=state["fingerprint"],
            obligation_batch={"decisions": [decision], "bindings": [binding]},
        )
        for changes, field in (
            ({}, "obligation_batch.bindings[0].case_id"),
            ({"obligation_batch": {"decisions": [decision, decision]}}, "obligation_batch.decisions[1]"),
            ({"expected_fingerprint": "stale"}, "expected_fingerprint"),
        ):
            rejected = handle_campaign_author(runtime, **(request | changes))
            assert rejected["status"] == "rejected"
            assert rejected["result"]["effect_state"] == "none"
            assert rejected["result"]["diagnostics"][0]["field"] == field
        assert runtime.ledger.campaign_authority_state("alpha", campaign_id) == state
    finally:
        runtime.close()


def test_oracle_question_answers_create_successor_semantic_revisions(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", state["campaign_id"], actor="o", request_id="derive"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                state["campaign_id"],
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                state["campaign_id"],
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:oracle-draft",
                semantic_fields={"preconditions": ["project exists"]},
            ),
            actor="o",
            request_id="oracle-draft",
        )
        oracle = state["oracles"][0]
        assert oracle["revision"] == 1
        assert oracle["status"] == "draft"
        first_question = oracle["questions"][0]

        state = runtime.ledger.answer_oracle_question(
            "alpha",
            state["campaign_id"],
            oracle["oracle_id"],
            first_question["question_id"],
            answer="invoke operation",
            authority=OracleAnswerAuthority.ACCEPTED_DECISION,
            provenance=("orchestrator-decision:stimulus",),
            waiver_scope="",
            actor="o",
            request_id="answer-1",
        )
        assert state["oracles"][0]["revision"] == 2
        assert (
            state["oracles"][0]["payload"]["semantic_fields"][
                first_question["field_name"]
            ]
            == "invoke operation"
        )
        revision = state["revision"]
        replay = runtime.ledger.answer_oracle_question(
            "alpha",
            state["campaign_id"],
            oracle["oracle_id"],
            first_question["question_id"],
            answer="invoke operation",
            authority=OracleAnswerAuthority.ACCEPTED_DECISION,
            provenance=("orchestrator-decision:stimulus",),
            waiver_scope="",
            actor="o",
            request_id="answer-1",
        )
        assert replay["replayed"] is True
        assert replay["revision"] == revision
        assert replay["oracles"][0]["revision"] == 2
    finally:
        runtime.close()


def test_oracle_questions_keep_field_identity_and_reject_noncurrent_answers(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", state["campaign_id"], actor="o", request_id="derive"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                state["campaign_id"],
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                state["campaign_id"],
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:stable-question-test",
                semantic_fields={"preconditions": ["project exists"]},
            ),
            actor="o",
            request_id="oracle",
        )
        oracle = state["oracles"][0]
        by_field = {item["field_name"]: item for item in oracle["questions"]}
        current = oracle["questions"][0]
        future = by_field["input_domain"]
        assert current["question_id"] == "Q-stimulus"
        assert future["question_id"] == "Q-input-domain"

        before = (state["revision"], state["fingerprint"], oracle["revision"])
        with pytest.raises(
            RequirementConflictError, match="oracle_question_not_current"
        ):
            runtime.ledger.answer_oracle_question(
                "alpha",
                state["campaign_id"],
                oracle["oracle_id"],
                future["question_id"],
                answer={"project": "current"},
                authority=OracleAnswerAuthority.ACCEPTED_DECISION,
                provenance=("decision:future",),
                waiver_scope="",
                actor="o",
                request_id="future-too-early",
            )
        unchanged = runtime.ledger.campaign_authority_state(
            "alpha", state["campaign_id"]
        )
        assert (
            unchanged["revision"],
            unchanged["fingerprint"],
            unchanged["oracles"][0]["revision"],
        ) == before

        state = runtime.ledger.answer_oracle_question(
            "alpha",
            state["campaign_id"],
            oracle["oracle_id"],
            current["question_id"],
            answer="invoke operation",
            authority=OracleAnswerAuthority.ACCEPTED_DECISION,
            provenance=("decision:stimulus",),
            waiver_scope="",
            actor="o",
            request_id="answer-current",
        )
        next_question = state["oracles"][0]["questions"][0]
        assert next_question["field_name"] == "input_domain"
        assert next_question["question_id"] == future["question_id"]

        before = (
            state["revision"],
            state["fingerprint"],
            state["oracles"][0]["revision"],
        )
        with pytest.raises(
            RequirementConflictError, match="oracle_question_not_current"
        ):
            runtime.ledger.answer_oracle_question(
                "alpha",
                state["campaign_id"],
                oracle["oracle_id"],
                current["question_id"],
                answer="duplicate stale answer",
                authority=OracleAnswerAuthority.ACCEPTED_DECISION,
                provenance=("decision:stale",),
                waiver_scope="",
                actor="o",
                request_id="stale-answer",
            )
        unchanged = runtime.ledger.campaign_authority_state(
            "alpha", state["campaign_id"]
        )
        assert (
            unchanged["revision"],
            unchanged["fingerprint"],
            unchanged["oracles"][0]["revision"],
        ) == before
    finally:
        runtime.close()


def test_legacy_ordinal_question_transitions_to_stable_identity(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", state["campaign_id"], actor="o", request_id="derive"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                state["campaign_id"],
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                state["campaign_id"],
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:legacy-question-test",
                semantic_fields={"preconditions": ["project exists"]},
            ),
            actor="o",
            request_id="oracle",
        )
        oracle = state["oracles"][0]
        with sqlite3.connect(tmp_path / "campaign.sqlite3") as connection:
            rows = connection.execute(
                """
                SELECT question_id, ordinal FROM oracle_questions
                WHERE project_id = 'alpha' AND oracle_id = ? AND oracle_revision = 1
                ORDER BY ordinal
                """,
                (oracle["oracle_id"],),
            ).fetchall()
            for question_id, ordinal in rows:
                connection.execute(
                    """
                    UPDATE oracle_questions SET question_id = ?
                    WHERE project_id = 'alpha' AND oracle_id = ?
                      AND oracle_revision = 1 AND question_id = ?
                    """,
                    (f"LEGACY-{ordinal:03d}", oracle["oracle_id"], question_id),
                )
            for _, ordinal in rows:
                connection.execute(
                    """
                    UPDATE oracle_questions SET question_id = ?
                    WHERE project_id = 'alpha' AND oracle_id = ?
                      AND oracle_revision = 1 AND question_id = ?
                    """,
                    (f"Q-{ordinal:03d}", oracle["oracle_id"], f"LEGACY-{ordinal:03d}"),
                )

        state = runtime.ledger.answer_oracle_question(
            "alpha",
            state["campaign_id"],
            oracle["oracle_id"],
            "Q-001",
            answer="invoke operation",
            authority=OracleAnswerAuthority.ACCEPTED_DECISION,
            provenance=("decision:legacy-current",),
            waiver_scope="",
            actor="o",
            request_id="answer-legacy-current",
        )
        assert state["oracles"][0]["revision"] == 2
        assert state["oracles"][0]["questions"][0]["question_id"] == ("Q-input-domain")
        with pytest.raises(
            RequirementConflictError, match="oracle_question_not_current"
        ):
            runtime.ledger.answer_oracle_question(
                "alpha",
                state["campaign_id"],
                oracle["oracle_id"],
                "Q-002",
                answer={"project": "current"},
                authority=OracleAnswerAuthority.ACCEPTED_DECISION,
                provenance=("decision:legacy-stale",),
                waiver_scope="",
                actor="o",
                request_id="answer-legacy-stale",
            )
    finally:
        runtime.close()


def test_constructible_oracle_allows_exact_source_attestation_intent(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", state["campaign_id"], actor="o", request_id="derive"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                state["campaign_id"],
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                state["campaign_id"],
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:oracle",
                semantic_fields=_complete_fields(),
            ),
            actor="o",
            request_id="oracle",
        )
        assert state["constructibility"] == "ready_to_run"
        state = runtime.ledger.create_campaign_attestation_intent(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            source_files={
                "tests/test_contract.py": "def test_contract():\n    assert True\n"
            },
            authority_reference="decision:test-source",
            actor="o",
            request_id="attest",
        )
        attestation = state["attestations"][0]
        assert attestation["state"] == "pending_technical_validation"
        assert attestation["oracle_fingerprint"] == state["oracles"][0]["fingerprint"]
        assert attestation["source_manifest"] == {
            "tests/test_contract.py": sha256(
                b"def test_contract():\n    assert True\n"
            ).hexdigest()
        }
        working_sheet = handle_campaign_inspect(
            runtime,
            project_id="alpha",
            campaign_id=state["campaign_id"],
            view="working_sheet",
        )["result"]["campaign"]["attestations"][0]
        attestation_view = handle_campaign_inspect(
            runtime,
            project_id="alpha",
            campaign_id=state["campaign_id"],
            view="attestation",
        )["result"]["attestations"][0]
        assert working_sheet == attestation_view
        assert (
            working_sheet["source_manifest_digest"]
            == attestation["source_manifest_digest"]
        )
        assert "source_manifest" not in working_sheet
        assert "harness" not in working_sheet
        with sqlite3.connect(tmp_path / "campaign.sqlite3") as connection:
            row = connection.execute(
                """
                SELECT event_id, payload_json FROM campaign_authority_events
                WHERE project_id = 'alpha'
                  AND event_type = 'attestation_intent_created'
                  AND request_id = 'attest'
                """
            ).fetchone()
            payload = json.loads(row[1])
            legacy_input = {
                key: value
                for key, value in payload.items()
                if key != "input_fingerprint"
            }
            payload["input_fingerprint"] = semantic_fingerprint(legacy_input)
            connection.execute(
                """
                UPDATE campaign_authority_events SET payload_json = ?
                WHERE event_id = ?
                """,
                (json.dumps(payload, sort_keys=True, separators=(",", ":")), row[0]),
            )
        revision = state["revision"]
        replay = runtime.ledger.create_campaign_attestation_intent(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            source_files={
                "tests/test_contract.py": "def test_contract():\n    assert True\n"
            },
            authority_reference="decision:test-source",
            actor="o",
            request_id="attest",
        )
        assert replay["replayed"] is True
        assert replay["revision"] == revision
        assert len(replay["attestations"]) == 1
    finally:
        runtime.close()


def test_generated_case_and_oracle_ids_do_not_break_exact_replay(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        state = runtime.ledger.add_campaign_authority_case(
            "alpha",
            state["campaign_id"],
            _case("Generated identity case"),
            actor="o",
            request_id="add-generated-case",
        )
        case_revision = state["revision"]
        replay = runtime.ledger.add_campaign_authority_case(
            "alpha",
            state["campaign_id"],
            _case("Generated identity case"),
            actor="o",
            request_id="add-generated-case",
        )
        assert replay["replayed"] is True
        assert replay["revision"] == case_revision
        assert len(replay["cases"]) == 2

        draft = BehavioralOracleDraft(
            oracle_kind="behavior",
            subject_bindings=(requirement_id,),
            authority_reference="decision:generated-oracle",
            semantic_fields=_complete_fields(),
        )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            draft,
            actor="o",
            request_id="author-generated-oracle",
        )
        oracle_revision = state["revision"]
        oracle_id = state["oracles"][0]["oracle_id"]
        replay = runtime.ledger.author_behavioral_oracle(
            "alpha",
            state["campaign_id"],
            "CASE-000001",
            draft,
            actor="o",
            request_id="author-generated-oracle",
        )
        assert replay["replayed"] is True
        assert replay["revision"] == oracle_revision
        assert replay["oracles"][0]["oracle_id"] == oracle_id
        assert len(replay["oracles"]) == 1
    finally:
        runtime.close()


def test_typed_oracle_authority_and_ir_are_byte_stable_after_reopen(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    campaign_id = ""
    try:
        state = _start(runtime, change_id, requirement_id)
        campaign_id = state["campaign_id"]
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", campaign_id, actor="o", request_id="derive-ir"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                campaign_id,
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-ir-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                campaign_id,
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-ir-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            campaign_id,
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:typed-oracle",
                semantic_fields=_complete_typed_ir_fields(),
            ),
            actor="o",
            request_id="typed-oracle",
        )
        oracle = state["oracles"][0]
        before = compile_oracle_ir(oracle)
        assert before.constructible is True
        assert before.snapshot is not None
        assert set(oracle["field_authority"]) == set(_complete_typed_ir_fields())
        canonical_before = before.snapshot.canonical_bytes
    finally:
        runtime.close()

    reopened = build_runtime(
        database_path=tmp_path / "campaign.sqlite3", import_root=tmp_path
    )
    try:
        state = reopened.ledger.campaign_authority_state("alpha", campaign_id)
        after = compile_oracle_ir(state["oracles"][0])
        assert after.constructible is True
        assert after.snapshot is not None
        assert after.snapshot.canonical_bytes == canonical_before
        RequirementService(reopened.ledger).revise(
            "alpha",
            requirement_id,
            RequirementDraft(
                title="Bounded lifecycle revised",
                statement="The service shall return one revised bounded result.",
                category="functional",
                rationale="The dependency must invalidate the old oracle IR.",
            ),
            actor="o",
            rationale="exercise dependency currentness",
            request_id="revise-ir-dependency",
        )
        stale_state = reopened.ledger.campaign_authority_state("alpha", campaign_id)
        stale = compile_oracle_ir(stale_state["oracles"][0])
        assert stale.constructible is False
        assert stale.status.value == "stale"
        with sqlite3.connect(tmp_path / "campaign.sqlite3") as connection:
            from flow_of_work_mcp.adapters.sqlite.schema import CURRENT_SCHEMA_VERSION
            assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        reopened.close()


def test_oracle_ir_refinement_reuses_answer_gate_without_blocking_source(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        campaign_id = state["campaign_id"]
        state = runtime.ledger.derive_campaign_obligations(
            "alpha", campaign_id, actor="o", request_id="derive-ir-refinement"
        )
        for index, obligation in enumerate(state["obligations"]):
            runtime.ledger.decide_campaign_obligation(
                "alpha",
                campaign_id,
                obligation["obligation_id"],
                decision=CampaignObligationDecision.REQUIRED,
                rationale="required",
                actor="o",
                request_id=f"decision-ir-refinement-{index}",
            )
            state = runtime.ledger.bind_campaign_case_obligation(
                "alpha",
                campaign_id,
                "CASE-000001",
                obligation["obligation_id"],
                coverage_intent="direct observation",
                actor="o",
                request_id=f"binding-ir-refinement-{index}",
            )
        state = runtime.ledger.author_behavioral_oracle(
            "alpha",
            campaign_id,
            "CASE-000001",
            BehavioralOracleDraft(
                oracle_kind="behavior",
                subject_bindings=(requirement_id,),
                authority_reference="decision:legacy-source-oracle",
                semantic_fields=_complete_fields(),
            ),
            actor="o",
            request_id="legacy-source-oracle",
        )
        oracle = state["oracles"][0]
        assert state["constructibility"] == "ready_to_run"
        assert oracle["questions"] == []
        assert oracle["oracle_ir_questions"][0]["question_id"] == ("Q-operator-profile")

        inspected = handle_campaign_inspect(
            runtime,
            project_id="alpha",
            campaign_id=campaign_id,
            view="oracle_ir",
        )
        projection = inspected["result"]["oracle_ir"][0]
        assert projection["constructible"] is False
        assert projection["next_action"]["operation"] == "answer_question"
        assert projection["next_question"]["question_id"] == "Q-operator-profile"
        assert "oracle_ir" not in projection

        answered = handle_campaign_author(
            runtime,
            project_id="alpha",
            operation="answer_question",
            actor="o",
            request_id="answer-ir-profile",
            campaign_id=campaign_id,
            oracle_id=oracle["oracle_id"],
            question_id="Q-operator-profile",
            answer=ORACLE_IR_OPERATOR_PROFILE,
            answer_authority="accepted_decision",
            provenance=["decision:unit-contract-profile"],
        )
        assert answered["status"] == "success"
        current = runtime.ledger.campaign_authority_state("alpha", campaign_id)
        assert current["constructibility"] == "ready_to_run"
        assert current["oracles"][0]["questions"] == []
        assert current["oracles"][0]["revision"] == 2
        assert current["oracles"][0]["oracle_ir_questions"][0]["scope"] == ("oracle_ir")
    finally:
        runtime.close()


def test_stale_campaign_fingerprint_fails_without_partial_case(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)
        with pytest.raises(AssuranceBlockedError, match="campaign_revision_stale"):
            runtime.ledger.add_campaign_authority_case(
                "alpha",
                state["campaign_id"],
                _case("Second"),
                actor="o",
                request_id="stale-add",
                expected_fingerprint="0" * 64,
            )
        current = runtime.ledger.campaign_authority_state("alpha", state["campaign_id"])
        assert [item["title"] for item in current["cases"]] == ["Nominal behavior"]
    finally:
        runtime.close()


def test_public_campaign_facade_advances_and_projects_bounded_gate(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        started = handle_campaign_author(
            runtime,
            project_id="alpha",
            operation="start",
            actor="orchestrator",
            request_id="mcp-start",
            title="MCP campaign",
            scope={"change_id": change_id, "requirement_ids": [requirement_id]},
            case={
                "title": "MCP case",
                "purpose": "Prove the public facade.",
                "case_kind": "positive",
                "action": "Invoke campaign advance.",
                "expected_outcome": "A bounded gate is returned.",
                "observation_point": "MCP response",
            },
        )
        assert started["status"] == "success"
        campaign_id = started["result"]["campaign"]["campaign_id"]
        advanced = handle_campaign_advance(
            runtime,
            project_id="alpha",
            campaign_id=campaign_id,
            actor="orchestrator",
            request_id="mcp-advance",
        )
        assert advanced["status"] == "success"
        assert advanced["result"]["transitions"] == [
            {"operation": "derive_obligations", "revision": 2}
        ]
        gate = advanced["result"]["lifecycle_gate"]
        assert gate["contract"] == "flow.lifecycle_gate.v1"
        assert gate["subject"] == "campaign"
        assert gate["decision_required"]["kind"] == "obligation_classification"

        inspected = handle_campaign_inspect(
            runtime,
            project_id="alpha",
            campaign_id=campaign_id,
            view="working_sheet",
            limit=5,
        )
        assert inspected["status"] == "success"
        assert inspected["result"]["campaign"]["obligation_count"] == 1
    finally:
        runtime.close()


def test_public_campaign_nested_objects_reject_unknown_fields(tmp_path):
    runtime, change_id, _ = _runtime(tmp_path)
    try:
        response = handle_campaign_author(
            runtime,
            project_id="alpha",
            operation="start",
            actor="orchestrator",
            request_id="reject-unknown-case-field",
            title="Strict campaign input",
            scope={"change_id": change_id},
            case={
                "title": "Boundary behavior",
                "purpose": "Reject a misspelled semantic field.",
                "case_kind": "boundary",
                "action": "Exercise the boundary.",
                "expected_outcome": "The boundary remains observable.",
                "observation_point": "Public response",
                "prohibitted_outcome": "The typo must not be ignored.",
            },
        )

        assert response["status"] == "rejected"
        assert response["reason"] == "invalid_input"
        assert response["result"]["diagnostics"][0]["message"] == (
            "case field is invalid: prohibitted_outcome"
        )
        assert (
            runtime.ledger.active_campaign_authority("alpha", change_id=change_id)
            is None
        )
    finally:
        runtime.close()


def test_public_campaign_stale_mutation_returns_current_recovery_gate(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        state = _start(runtime, change_id, requirement_id)

        stale = handle_campaign_author(
            runtime,
            project_id="alpha",
            operation="add_case",
            actor="orchestrator",
            request_id="stale-public-add",
            campaign_id=str(state["campaign_id"]),
            expected_fingerprint="0" * 64,
            case={
                "title": "Stale case",
                "purpose": "Exercise recoverable stale input.",
                "case_kind": "positive",
                "action": "Invoke the operation.",
                "expected_outcome": "The current state remains unchanged.",
                "observation_point": "MCP response",
            },
        )

        assert stale["status"] == "blocked"
        assert stale["reason"] == "campaign_revision_stale"
        assert stale["result"]["campaign"]["campaign_id"] == state["campaign_id"]
        assert stale["result"]["campaign"]["case_count"] == 1
        gate = stale["result"]["lifecycle_gate"]
        assert gate["contract"] == "flow.lifecycle_gate.v1"
        assert gate["subject"] == "campaign"
        assert gate["next_action"]["operation"] == "derive_obligations"
    finally:
        runtime.close()


def test_legacy_campaign_never_acquires_qualified_authority(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        legacy = runtime.assurance.create_campaign(
            "alpha",
            __import__("flow_of_work_mcp").CampaignDraft(
                change_id=change_id,
                title="Legacy",
                target_requirement_ids=(requirement_id,),
            ),
            actor="legacy",
        )
        projected = runtime.ledger.campaign_authority_state(
            "alpha", str(legacy["campaign_id"])
        )
        assert projected["qualification"] == "legacy_unqualified"
        assert projected["revision"] == 0
        inspected = runtime.campaign_authority.inspect(
            "alpha", campaign_id=str(legacy["campaign_id"])
        )
        assert inspected["lifecycle_gate"]["lifecycle_state"] == ("legacy_unqualified")
        assert inspected["lifecycle_gate"]["next_action"] == {
            "tool": "fow_campaign_author",
            "operation": "start",
            "arguments": {"scope": {"change_id": change_id}},
        }
        with pytest.raises(AssuranceBlockedError, match="campaign_legacy_unqualified"):
            runtime.ledger.add_campaign_authority_case(
                "alpha",
                str(legacy["campaign_id"]),
                _case(),
                actor="o",
                request_id="cannot-upgrade",
            )
    finally:
        runtime.close()


def test_request_id_collision_rejects_different_semantic_input(tmp_path):
    runtime, change_id, requirement_id = _runtime(tmp_path)
    try:
        _start(runtime, change_id, requirement_id, request_id="same")
        with pytest.raises(RequirementConflictError, match="request_id conflicts"):
            runtime.ledger.start_campaign_authority(
                "alpha",
                title="Different",
                scope=CampaignScopeDraft(
                    change_id=change_id, requirement_ids=(requirement_id,)
                ),
                first_case=_case(),
                actor="orchestrator",
                request_id="same",
            )
    finally:
        runtime.close()
