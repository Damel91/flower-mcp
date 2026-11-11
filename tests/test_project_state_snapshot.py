from __future__ import annotations

import sqlite3
from threading import Event, Thread

import pytest

from flow_of_work_mcp import (
    AssuranceService,
    CampaignCaseDraft,
    CampaignCaseKind,
    CampaignCaseResult,
    CampaignDraft,
    CampaignEvidenceDraft,
    CampaignEvidenceKind,
    GroundingAudit,
    GroundingDisposition,
    GroundingDivergence,
    GroundingItem,
    GoalGraphService,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    MilestoneDraft,
    PhaseAuditScope,
    RequirementDraft,
    RequirementService,
    SequenceDraft,
    UseCaseDraft,
)
from flow_of_work_mcp.application import (
    ChangeControlService,
    CoveragePropagationService,
    LifecycleControlService,
)
from flow_of_work_mcp.application.project_state_snapshot import (
    _ordered_actions,
    _verification_dimension,
)
from flow_of_work_mcp.core.domain.lifecycle_control import ActionExecutionClass, NextActionKind
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_handover, handle_what_next



def _basic_project(runtime):
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Alpha", actor="operator")
    requirement = requirements.register(
        "alpha",
        RequirementDraft(
            title="Recover state",
            statement="The server shall expose current project state.",
            category="functional",
        ),
        actor="operator",
    )
    lifecycle = LifecycleControlService(
        requirements=runtime.ledger,
        goals=runtime.ledger,
        grounding_audits=runtime.ledger,
        control=runtime.ledger,
        change_control=runtime.ledger,
        assurance=runtime.ledger,
        execution_runs=runtime.ledger,
    )
    milestone = lifecycle.promote_milestone(
        "alpha",
        MilestoneDraft(
            name="Recovery",
            requirement_ids=(requirement["requirement_id"],),
            prerequisite_requirement_ids=(),
            entry_policy={},
            exit_policy={},
            risk_disposition="none",
        ),
        actor="operator",
    )
    return requirements, requirement, milestone


def test_snapshot_is_stable_read_only_and_invalidates_on_material_change(
    tmp_path, monkeypatch
):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        requirements, _requirement, _milestone = _basic_project(runtime)
        original_connect = runtime.ledger._connect
        opened_connections = 0

        def counted_connect():
            nonlocal opened_connections
            opened_connections += 1
            return original_connect()

        monkeypatch.setattr(runtime.ledger, "_connect", counted_connect)
        first = runtime.project_state_snapshot.snapshot("alpha")
        assert opened_connections == 1
        repeated = runtime.project_state_snapshot.snapshot("alpha")

        assert first["snapshot_fingerprint"] == repeated["snapshot_fingerprint"]
        assert first["project_revision"] == repeated["project_revision"]
        assert isinstance(first["generated_at"], str)
        assert first["completeness"]["coherent_read"] is True
        assert first["completeness"]["unavailable_sources"] == [
            "implementation_provider"
        ]
        assert first["next_gate"]["kind"] == "intent_work"

        requirements.register(
            "alpha",
            RequirementDraft(
                title="Detect stale state",
                statement="The snapshot shall detect a material mutation.",
                category="functional",
            ),
            actor="operator",
        )
        changed = runtime.project_state_snapshot.snapshot("alpha")
        assert changed["snapshot_fingerprint"] != first["snapshot_fingerprint"]
        assert changed["project_revision"] != first["project_revision"]

        with pytest.raises(sqlite3.OperationalError, match="readonly database"):
            with runtime.ledger.consistent_read():
                requirements.register(
                    "alpha",
                    RequirementDraft(
                        title="Forbidden nested write",
                        statement="This write shall be rejected in a read snapshot.",
                        category="functional",
                    ),
                    actor="operator",
                )
        assert len(runtime.ledger.traceability_matrix("alpha")) == 2
    finally:
        runtime.close()


def test_snapshot_excludes_a_concurrent_mutation_until_the_next_read(
    tmp_path, monkeypatch
):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        requirements, _requirement, _milestone = _basic_project(runtime)
        initial_version = runtime.ledger.ledger_version("alpha")
        first_read_complete = Event()
        writer_attempted = Event()
        writer_errors: list[BaseException] = []
        original_goal_graph = runtime.ledger.goal_graph

        def delayed_goal_graph(project_id: str):
            result = original_goal_graph(project_id)
            first_read_complete.set()
            assert writer_attempted.wait(timeout=2)
            return result

        def mutate() -> None:
            try:
                assert first_read_complete.wait(timeout=2)
                writer_attempted.set()
                requirements.register(
                    "alpha",
                    RequirementDraft(
                        title="Concurrent requirement",
                        statement=(
                            "The next snapshot shall include this mutation."
                        ),
                        category="functional",
                    ),
                    actor="writer",
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                writer_errors.append(exc)

        monkeypatch.setattr(runtime.ledger, "goal_graph", delayed_goal_graph)
        writer = Thread(target=mutate, daemon=True)
        writer.start()
        during_write = runtime.project_state_snapshot.snapshot("alpha")
        writer.join(timeout=5)
        assert not writer.is_alive()
        assert writer_errors == []

        monkeypatch.setattr(runtime.ledger, "goal_graph", original_goal_graph)
        after_write = runtime.project_state_snapshot.snapshot("alpha")
        assert during_write["source_ledger_version"] == initial_version
        assert after_write["source_ledger_version"] == initial_version + 1
        assert during_write["project_revision"] != after_write["project_revision"]
    finally:
        runtime.close()


def test_snapshot_projects_goal_dimensions_without_collapsing_acceptance(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        requirements, requirement, milestone = _basic_project(runtime)
        changes = ChangeControlService(runtime.ledger)
        change = changes.create_change(
            "alpha",
            GovernedChangeDraft(
                title="Recovery change",
                rationale="Implement the state projection.",
                requirement_ids=(requirement["requirement_id"],),
                milestone_id=milestone["milestone_id"],
            ),
            actor="operator",
        )
        changes.add_packet(
            "alpha",
            change["change_id"],
            ImplementationPacketDraft(
                title="Recovery packet",
                objective="Implement the project state projection.",
                rationale="A local model needs bounded recovery.",
                completion_criteria=("the snapshot is available",),
                requirement_ids=(requirement["requirement_id"],),
                invariants=("acceptance remains evidence-derived",),
            ),
            actor="operator",
        )
        goals = GoalGraphService(runtime.ledger)
        use_case = goals.add_use_case(
            "alpha",
            UseCaseDraft(
                title="Resume work",
                actor="orchestrator",
                objective="recover current direction",
                observable_outcome="one next gate is visible",
            ),
            actor="operator",
        )
        sequence = goals.add_sequence(
            "alpha",
            SequenceDraft(
                title="Recovery sequence",
                participants=("orchestrator", "flow"),
                normal_steps=("read snapshot", "follow gate"),
                expected_effects=("work resumes without chat history",),
            ),
            actor="operator",
        )
        goals.link(
            "alpha",
            source_goal_id=use_case["goal_node_id"],
            target_goal_id=sequence["goal_node_id"],
            relation="realized_by",
            actor="operator",
        )
        runtime.ledger.record_grounding_audit(
            GroundingAudit(
                project_id="alpha",
                provider_id="fixture-provider",
                source_revision="fixture:1",
                selected_goal_ids=(
                    use_case["goal_node_id"],
                    sequence["goal_node_id"],
                ),
                disposition=GroundingDisposition.COMPLETED,
                items=(
                    GroundingItem(
                        divergence=GroundingDivergence.CONVERGED,
                        goal_node_id=use_case["goal_node_id"],
                        origin="deterministic",
                    ),
                    GroundingItem(
                        divergence=GroundingDivergence.CONVERGED,
                        goal_node_id=sequence["goal_node_id"],
                        origin="deterministic",
                    ),
                ),
                prompt_version="fixture-v1",
            ),
            actor="tester",
        )
        assurance = AssuranceService(
            assurance=runtime.ledger, changes=runtime.ledger
        )
        assurance.create_campaign(
            "alpha",
            CampaignDraft(
                change_id=change["change_id"],
                title="Recovery campaign",
                target_requirement_ids=(requirement["requirement_id"],),
            ),
            actor="tester",
        )
        assurance.add_campaign_case(
            "alpha",
            CampaignCaseDraft(
                campaign_id="CAMP-000001",
                title="Deterministic recovery",
                purpose="Verify the projection deterministically.",
                case_kind=CampaignCaseKind.DETERMINISTIC_REGRESSION,
                evidence_kind=CampaignEvidenceKind.DETERMINISTIC_TEST,
                covered_requirement_ids=(requirement["requirement_id"],),
                covered_use_case_goal_node_ids=(use_case["goal_node_id"],),
                covered_sequence_goal_node_ids=(sequence["goal_node_id"],),
            ),
            actor="tester",
        )
        assurance.record_campaign_evidence(
            "alpha",
            CampaignEvidenceDraft(
                campaign_id="CAMP-000001",
                case_id="CASE-000001",
                result=CampaignCaseResult.PASSED,
                evidence_kind=CampaignEvidenceKind.DETERMINISTIC_TEST,
                reference="pytest:project-state",
            ),
            actor="tester",
        )
        CoveragePropagationService(
            assurance=runtime.ledger,
            requirements=runtime.ledger,
            grounding_audits=runtime.ledger,
        ).propagate_campaign(
            "alpha", "CAMP-000001", actor="tester", request_id="propagate"
        )

        snapshot = runtime.project_state_snapshot.snapshot(
            "alpha",
            focus_kind="use_case",
            focus_ref=use_case["goal_node_id"],
        )
        by_id = {
            item["goal_node_id"]: item for item in snapshot["goal_reach"]["items"]
        }
        assert set(by_id) == {
            use_case["goal_node_id"],
            sequence["goal_node_id"],
        }
        assert by_id[use_case["goal_node_id"]]["implementation_grounding"][
            "state"
        ] == "grounded"
        assert by_id[use_case["goal_node_id"]]["deterministic_verification"][
            "state"
        ] == "passed"
        assert by_id[use_case["goal_node_id"]]["live_verification"][
            "state"
        ] == "not_verified"
        assert snapshot["active_work"]["milestone"]["status"] != "accepted"

        packet_snapshot = runtime.project_state_snapshot.snapshot(
            "alpha",
            focus_kind="packet",
            focus_ref="PACKET-000001",
        )
        assert packet_snapshot["active_work"]["packet"]["packet_id"] == (
            "PACKET-000001"
        )
        assert packet_snapshot["next_gate"]["kind"] == "packet_construction"
        assert packet_snapshot["project_revision"] == snapshot["project_revision"]
        assert packet_snapshot["snapshot_fingerprint"] != (
            snapshot["snapshot_fingerprint"]
        )
        assert packet_snapshot["active_work"]["provider_execution"]["state"] == (
            "unavailable"
        )
    finally:
        runtime.close()


def test_snapshot_focus_is_validated_and_default_output_is_bounded(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        _basic_project(runtime)
        goals = GoalGraphService(runtime.ledger)
        for ordinal in range(6):
            goals.add_use_case(
                "alpha",
                UseCaseDraft(
                    title=f"Use case {ordinal}",
                    actor="operator",
                    objective=f"exercise branch {ordinal}",
                    observable_outcome=f"branch {ordinal} is observable",
                ),
                actor="operator",
            )
        snapshot = runtime.project_state_snapshot.snapshot("alpha", limit=2)
        assert len(snapshot["goal_reach"]["items"]) == 2
        assert snapshot["goal_reach"]["truncated"] is True
        assert snapshot["completeness"]["omitted"]["goal_reach_items"] == 4

        with pytest.raises(ValueError, match="unknown packet focus"):
            runtime.project_state_snapshot.snapshot(
                "alpha", focus_kind="packet", focus_ref="PACKET-999999"
            )
        with pytest.raises(ValueError, match="focus_kind"):
            runtime.project_state_snapshot.snapshot(
                "alpha", focus_kind="source_file", focus_ref="src/main.py"
            )
    finally:
        runtime.close()


def test_idle_gate_can_be_reopened_as_an_explicit_focus(tmp_path):
    runtime = build_runtime(
        database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path
    )
    try:
        requirements = RequirementService(runtime.ledger)
        requirements.create_project("alpha", "Alpha", actor="operator")
        runtime.lifecycle.audit_phase(
            "alpha",
            PhaseAuditScope("project-default"),
            actor="operator",
        )

        snapshot = runtime.project_state_snapshot.snapshot(
            "alpha", focus_kind="gate", focus_ref="idle"
        )

        assert snapshot["focus"] == {"kind": "gate", "ref": "idle"}
        assert snapshot["next_gate"]["kind"] == "idle"
    finally:
        runtime.close()


def test_accepted_change_projection_is_advice_even_when_it_is_the_only_action(tmp_path, monkeypatch):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        _basic_project(runtime)
        advisory = runtime.lifecycle._action(
            action_id="projection:CHANGE-000001", kind=NextActionKind.CREATE_LIFECYCLE_PROJECTION,
            execution_class=ActionExecutionClass.DETERMINISTIC, priority=60,
            rationale="accepted change can be summarized through a ledger projection",
            state="advisory", decision_class="informational",
        )
        monkeypatch.setattr(runtime.lifecycle, "what_next", lambda *args, **kwargs: (advisory,))
        snapshot = runtime.project_state_snapshot.snapshot("alpha")
        assert snapshot["next_gate"]["kind"] == "idle"
        assert snapshot["secondary_actions"][0]["advisory"]
        assert snapshot["secondary_actions"][0]["route"] is None
        assert not any(item["source"] == "next_gate" for item in snapshot["blockers"])
        focused = runtime.project_state_snapshot.snapshot("alpha", focus_kind="gate", focus_ref=advisory.action_id)
        assert focused["next_gate"]["kind"] == "advisory"
        result = handle_what_next(runtime, project_id="alpha", detail_level="audit")["result"]
        assert result["primary_action"]["state"] == "idle"
        assert advisory.action_id in str(result)
    finally:
        runtime.close()


def test_handover_operation_recovers_same_state_after_restart(tmp_path):
    database_path = tmp_path / "ledger.sqlite3"
    runtime = build_runtime(database_path=database_path, import_root=tmp_path)
    _basic_project(runtime)
    first = handle_handover(
        runtime,
        project_id="alpha",
        operation="project_state_snapshot",
    )["result"]["project_state_snapshot"]
    runtime.close()

    restarted = build_runtime(database_path=database_path, import_root=tmp_path)
    try:
        second = handle_handover(
            restarted,
            project_id="alpha",
            operation="project_state_snapshot",
        )["result"]["project_state_snapshot"]
        assert second["snapshot_fingerprint"] == first["snapshot_fingerprint"]
        assert second["next_gate"] == first["next_gate"]
    finally:
        restarted.close()


def test_snapshot_preserves_global_priority_and_partial_goal_coverage():
    lifecycle_actions = [
        {
            "action_id": "repair-verification:FR-001",
            "kind": "repair_failed_verification",
            "priority": 10,
            "requirement_ids": ["FR-001"],
        },
        {
            "action_id": "implement-packet:CHANGE-000001:PACKET-000001",
            "kind": "implement_packet",
            "priority": 40,
            "packet_ids": ["PACKET-000001"],
        },
    ]
    packet_actions = [
        {
            "state": "needs_instructions",
            "tool": "fow_packet_author",
            "operation": "replace_plan",
            "scope": {
                "change_id": "CHANGE-000001",
                "packet_id": "PACKET-000001",
            },
        }
    ]

    ordered = _ordered_actions(lifecycle_actions, packet_actions)

    assert ordered[0]["action_id"] == "repair-verification:FR-001"
    assert ordered[1]["operation"] == "replace_plan"
    assert ordered[1]["lifecycle_kind"] == "implement_packet"
    assert _verification_dimension(
        [
            {"tested_deterministically": "passed"},
            {"tested_deterministically": ""},
        ],
        "tested_deterministically",
    )["state"] == "partial"
