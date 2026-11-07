from flow_of_work_mcp import (
    FindingDisposition,
    FindingDispositionDraft,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    RequirementDraft,
    ReviewFindingDraft,
    ReviewFindingSeverity,
    VerificationKind,
    VerificationOutcome,
)
from flow_of_work_mcp.application.dashboard import DashboardProjectionService
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import handle_handover, handle_traceability, handle_what_next


def _record(runtime, requirement_id, *, kind, outcome, reference, metadata=None):
    return runtime.ledger.record_verification(
        "alpha", requirement_id, kind=kind, outcome=outcome, reference=reference,
        metadata=metadata, actor="tester",
    )


def test_failed_evidence_and_publication_exception_keep_separate_scopes(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        runtime.requirements.create_project("alpha", "Alpha", actor="operator")
        producer = runtime.requirements.register(
            "alpha", RequirementDraft("Publish producer", "Publish the producer package.", "functional"),
            actor="operator",
        )["requirement_id"]
        current = runtime.requirements.register(
            "alpha", RequirementDraft("Qualify consumer", "Qualify numerical equivalence separately.", "functional"),
            actor="operator",
        )["requirement_id"]
        change = runtime.changes.create_change(
            "alpha", GovernedChangeDraft("Producer release", "Track producer publication.", (producer,)),
            actor="operator",
        )["change_id"]
        packet = runtime.changes.add_packet(
            "alpha", change, ImplementationPacketDraft("Package producer", ("package builds",)),
            actor="operator",
        )["packets"][0]["packet_id"]
        finding = runtime.assurance.record_finding(
            "alpha",
            ReviewFindingDraft(
                change_id=change, packet_id=packet, severity=ReviewFindingSeverity.HIGH,
                title="Numerical equivalence failed", rationale="Retain the measured failure.",
                expected_correction="Qualify the consumer separately.", scope_kind="packet",
                scope_ref=packet, source_anchor="producer:qualification",
            ),
            actor="reviewer",
        )["finding_id"]
        reason = "The exception permits producer publication only. Consumer and numerical qualification remain open."
        runtime.assurance.set_finding_disposition(
            "alpha", finding,
            FindingDispositionDraft(
                disposition=FindingDisposition.ACCEPTED_EXCEPTION, rationale=reason,
                evidence_refs=("retained:profile-A/failed",), disposition_reference="operator:producer-only",
            ),
            actor="operator",
        )
        old = _record(
            runtime, current, kind=VerificationKind.LIVE, outcome=VerificationOutcome.FAILED,
            reference="retained:older",
        )
        unlinked = _record(
            runtime, current, kind=VerificationKind.DETERMINISTIC, outcome=VerificationOutcome.FAILED,
            reference="retained:unlinked", metadata={"finding_id": finding},
        )
        failure = _record(
            runtime, current, kind=VerificationKind.LIVE, outcome=VerificationOutcome.FAILED,
            reference="retained:profile-A/failed",
            metadata={
                "finding_id": finding,
                "source_runtime_implementation": "source-abc",
                "model_profile": "profile-A",
                "provenance": "earlier actual candidate measurement",
                "numerical_thresholds": {"max_abs": 1e-5, "min_cosine": 0.999999},
            },
        )
        view = handle_what_next(runtime, project_id="alpha", detail_level="audit")
        action = next(
            action for action in view["result"]["lifecycle_actions"]
            if action["action_id"] == f"repair-verification:{current}"
        )
        recovery = action["verification_recovery"]
        rows = recovery["failed_evidence"]
        assert [row["evidence_id"] for row in rows] == [failure["evidence_id"], unlinked["evidence_id"]]
        assert old["evidence_id"] not in {row["evidence_id"] for row in rows}
        assert "linked_exception" not in rows[1]
        assert rows[0]["linked_exception"] == {
            "finding_id": finding, "disposition": "accepted_exception", "scope_kind": "packet",
            "scope_ref": packet, "change_id": change, "packet_id": packet,
            "disposition_reference": "operator:producer-only", "disposition_rationale": reason,
            "next_tool_call": {
                "tool": "fow_assurance",
                "arguments": {"project_id": "alpha", "operation": "get_finding", "finding_id": finding},
            },
        }
        assert rows[0]["requirement_id"] == current
        assert rows[0]["outcome"] == "failed"
        assert rows[0]["source_revision"] == "source-abc"
        assert rows[0]["profile"] == "profile-A"
        assert rows[0]["numerical_thresholds"] == {"max_abs": 1e-5, "min_cosine": 0.999999}
        assert action["requirement_ids"] == (current,)
        assert not action["packet_ids"]
        assert recovery["live_execution_authorized"] is False
        assert recovery["establishes_global_admission"] is False
        exact = handle_traceability(runtime, **action["arguments"])["result"]["evidence"]
        assert exact["evidence_id"] == failure["evidence_id"]
        assert exact["outcome"] == "failed"

        snapshot_response = handle_handover(runtime, project_id="alpha", operation="project_state_snapshot")
        gate = snapshot_response["result"]["project_state_snapshot"]["next_gate"]
        assert gate["verification_recovery"] == recovery
        assert gate["scope"]["requirement_ids"] == [current]
        assert not gate["scope"].get("packet_ids")
        assert gate["route"]["tool"] == "fow_traceability"
        assert gate["route"]["arguments"] == action["arguments"]
        dashboard = DashboardProjectionService(runtime).project("alpha")
        dashboard_recovery = dashboard["summary"]["next_gate"]["verification_recovery"]
        assert dashboard_recovery["failed_evidence_bounds"]["total"] == 2
        assert {key: dashboard_recovery[key] for key in recovery} == recovery
        for tool, response, arguments in (
            ("fow_what_next", view, {}),
            ("fow_handover", snapshot_response, {"operation": "project_state_snapshot"}),
        ):
            markdown = project_markdown(tool, response, arguments=arguments)
            assert "retained:profile-A/failed" in markdown
            assert "operator:producer-only" in markdown
            assert "fow_traceability" in markdown
            assert "Check the separate live execution authority" in markdown
    finally:
        runtime.close()


def test_new_passing_evidence_clears_failed_repair_without_removing_history(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        runtime.requirements.create_project("alpha", "Alpha", actor="operator")
        current = runtime.requirements.register(
            "alpha", RequirementDraft("Current", "Keep the verification record.", "functional"),
            actor="operator",
        )["requirement_id"]
        failure = _record(
            runtime, current, kind=VerificationKind.DETERMINISTIC, outcome=VerificationOutcome.FAILED,
            reference="test:failure", metadata={"finding_id": "FIND-000999"},
        )
        action_id = f"repair-verification:{current}"
        action = next(action for action in runtime.lifecycle.what_next("alpha") if action.action_id == action_id)
        assert "linked_exception" not in action.verification_recovery["failed_evidence"][0]
        assert action.tool == "fow_traceability"
        assert "plan remediation" in action.verification_recovery["next_step"]
        _record(
            runtime, current, kind=VerificationKind.DETERMINISTIC, outcome=VerificationOutcome.PASSED,
            reference="test:pass",
        )
        assert not any(action.action_id == action_id for action in runtime.lifecycle.what_next("alpha"))
        original = handle_traceability(
            runtime, project_id="alpha", detail_level="audit", evidence_id=failure["evidence_id"],
        )["result"]["evidence"]
        assert original["outcome"] == "failed"
    finally:
        runtime.close()
