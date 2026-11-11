from flow_of_work_mcp import (
    AssuranceService,
    CampaignCaseDraft,
    CampaignCaseKind,
    CampaignDraft,
    CampaignEvidenceDraft,
    CampaignEvidenceKind,
    CampaignCaseResult,
    CandidateTarget,
    CandidateTargetSetDraft,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    MilestoneDraft,
    NavigationAuditBlockDraft,
    PacketStatus,
    PacketTransition,
    PacketTargetPolicy,
    RequirementDraft,
    RequirementService,
)
from flow_of_work_mcp.application import ChangeControlService, LifecycleControlService
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import handle_traceability


def _setup_runtime(tmp_path, *, split_packet_scope=False):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Alpha", actor="operator")
    first = requirements.register(
        "alpha",
        RequirementDraft(
            title="Milestone projection",
            statement="The server shall expose milestone traceability.",
            category="functional",
            rationale="Traceability must be derived from canonical state.",
        ),
        actor="operator",
    )
    second = requirements.register(
        "alpha",
        RequirementDraft(
            title="Unscoped requirement",
            statement="The server shall expose requirements missing milestone scope.",
            category="functional",
            rationale="Project projections must expose planning gaps.",
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
            name="Projection milestone",
            requirement_ids=(
                (first["requirement_id"], second["requirement_id"])
                if split_packet_scope else (first["requirement_id"],)
            ),
            prerequisite_requirement_ids=(),
            entry_policy={"ready": True},
            exit_policy={"accepted": True},
            risk_disposition="standard",
        ),
        actor="operator",
    )
    changes = ChangeControlService(runtime.ledger)
    change = changes.create_change(
        "alpha",
        GovernedChangeDraft(
            title="Projection change",
            rationale="Cover milestone requirement.",
            requirement_ids=(first["requirement_id"],),
            milestone_id=milestone["milestone_id"],
        ),
        actor="operator",
    )
    changes.add_packet(
        "alpha",
        change["change_id"],
        ImplementationPacketDraft(
            title="Projection packet",
            completion_criteria=("traceability projection includes packet",),
            objective="Implement milestone traceability projection.",
            rationale="Projection must expose unresolved packet state.",
            requirement_ids=((second if split_packet_scope else first)["requirement_id"],),
            in_scope=("traceability projection",),
            invariants=("projection is read-only",),
            target_policy=PacketTargetPolicy.CODE_TARGETS_REQUIRED,
        ),
        actor="operator",
    )
    return runtime, first, second, milestone, change


def test_milestone_traceability_projection_classifies_blockers(tmp_path):
    runtime, first, _second, milestone, change = _setup_runtime(tmp_path)
    try:
        projection = runtime.milestone_traceability.projection(
            "alpha", milestone_id=milestone["milestone_id"]
        )
        assert projection["profile_version"] == "milestone-traceability-v1"
        assert projection["source_ledger_version"] >= 1
        assert projection["rows"][0]["requirement_id"] == first["requirement_id"]
        assert projection["rows"][0]["change_ids"] == [change["change_id"]]
        assert projection["rows"][0]["packets"][0]["packet_id"] == "PACKET-000001"
        assert set(projection["rows"][0]["acceptance_blockers"]) == {
            "packet_not_execution_ready",
            "navigation_audit_unresolved",
            "campaign_missing",
            "acceptance_evidence_missing",
        }
    finally:
        runtime.close()


def test_milestone_traceability_projects_provider_candidate_ids_and_readiness(tmp_path):
    runtime, first, _second, milestone, change = _setup_runtime(tmp_path)
    try:
        packet_id = "PACKET-000001"
        nav = runtime.navigation.open_block(
            "alpha",
            NavigationAuditBlockDraft(
                change_id=change["change_id"],
                packet_id=packet_id,
                active_provider="codingcastle",
                source_revision="graph:target:1",
            ),
            actor="operator",
        )
        runtime.navigation.append_candidate_set(
            "alpha",
            nav["navigation_audit_id"],
            CandidateTargetSetDraft(
                provider="codingcastle",
                provider_capability_version="packet-target-discovery-v1",
                semantic_seeds=("projection",),
                source_revision="graph:target:1",
                metadata={"provider_candidate_set_id": "cc-cset-42"},
                candidates=(
                    CandidateTarget(
                        candidate_id="cand-1",
                        target_handle="code:symbol:ProjectionService",
                        target_kind="symbol",
                        surface_id="repo",
                    ),
                ),
            ),
            actor="operator",
        )

        projection = runtime.milestone_traceability.projection(
            "alpha", milestone_id=milestone["milestone_id"]
        )
        row = projection["rows"][0]
        assert row["requirement_id"] == first["requirement_id"]
        assert row["navigation_audits"][0]["provider_candidate_set_ids"] == ["cc-cset-42"]
        assert row["readiness_projection"]["execution_ready_packet_ids"] == []
        assert row["readiness_projection"]["packet_readiness_blockers"] == [
            "navigation_audit_unresolved",
            "packet_not_execution_ready",
        ]
        assert row["readiness_projection"]["acceptance_blockers"] == [
            "acceptance_evidence_missing",
            "campaign_missing",
        ]
    finally:
        runtime.close()


def test_project_traceability_projection_keeps_unscoped_requirement_gap(tmp_path):
    runtime, _first, second, _milestone, _change = _setup_runtime(tmp_path)
    try:
        result = handle_traceability(runtime, project_id="alpha")
        projection = result["result"]["projection"]
        rows = {row["requirement_id"]: row for row in projection["rows"]}
        assert rows[second["requirement_id"]]["acceptance_blockers"] == [
            "no_milestone_scope",
            "no_packet_for_requirement",
        ]
        assert any(gap["reason"] == "no_milestone_scope" for gap in projection["gaps"])
    finally:
        runtime.close()


def test_explicit_packet_scope_governs_milestone_links_and_progress(tmp_path):
    runtime, first, second, milestone, _change = _setup_runtime(tmp_path, split_packet_scope=True)
    try:
        milestone_id = milestone["milestone_id"]
        projection = runtime.milestone_traceability.projection("alpha", milestone_id=milestone_id)
        rows = {row["requirement_id"]: row for row in projection["rows"]}
        assert rows[second["requirement_id"]]["packets"][0]["packet_id"] == "PACKET-000001"
        assert "no_packet_for_requirement" not in rows[second["requirement_id"]]["acceptance_blockers"]
        assert rows[first["requirement_id"]]["packets"] == []
        assert {
            "reason": "no_packet_for_requirement", "relation": "current_packet_requirement_scope",
            "scope_kind": "milestone", "milestone_id": milestone_id,
            "requirement_ids": [first["requirement_id"]],
        } in projection["gaps"]
        progress = runtime.milestone_traceability.progress("alpha", milestone_ids=(milestone_id,))
        assert [gap["requirement_id"] for gap in progress["gaps"]
                if gap["code"] == "milestone_requirement_unplanned"] == [first["requirement_id"]]
    finally:
        runtime.close()


def test_traceability_markdown_identifies_scoped_pages_and_their_continuation(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        requirements = RequirementService(runtime.ledger)
        requirements.create_project("alpha", "Alpha", actor="operator")
        ids = [
            requirements.register(
                "alpha", RequirementDraft(title=f"Behavior {ordinal}",
                    statement=f"The project exposes behavior {ordinal}.", category="functional"),
                actor="operator",
            )["requirement_id"]
            for ordinal in range(20)
        ]
        milestone = runtime.lifecycle.promote_milestone(
            "alpha", MilestoneDraft(name="Scoped release", requirement_ids=tuple(ids[:19]),
                prerequisite_requirement_ids=(), entry_policy={}, exit_policy={}, risk_disposition="none"),
            actor="operator",
        )["milestone_id"]
        args = {"project_id": "alpha", "milestone_id": milestone}
        seen = set()
        for offset, count, next_offset in ((0, 10, 10), (10, 9, None)):
            call = {**args, "offset": offset}
            result = handle_traceability(runtime, **call)
            page = result["result"]["pagination"]["projection_rows"]
            assert page == {"offset": offset, "limit": 10, "returned": count, "total": 19,
                            "has_more": next_offset is not None, "next_offset": next_offset}
            rows = result["result"]["projection"]["rows"]
            assert len(rows) == count
            seen.update(row["requirement_id"] for row in rows)
            markdown = project_markdown("fow_traceability", result, arguments=call)
            assert markdown.index("Traceability Pagination") < markdown.index("Traceability Evidence")
            table_rows = [line.split("|")[1:-1] for line in markdown.splitlines()
                          if "| Projection rows" in line]
            assert [[value.strip() for value in row] for row in table_rows] == [[
                "Projection rows", str(offset), "10", str(count), "19",
                "yes" if next_offset is not None else "no",
                str(next_offset) if next_offset is not None else "Not provided (null).",
            ]]
            continuation = (f"fow_traceability with project_id=alpha, milestone_id={milestone}, "
                            "detail_level=standard, offset=10, limit=10.")
            assert (continuation if next_offset is not None else "End of both views.") in markdown
        assert seen == set(ids[:19])
    finally:
        runtime.close()


def test_accepting_milestone_appends_evidence_and_clears_projection_gap(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    try:
        requirements = RequirementService(runtime.ledger)
        requirements.create_project("alpha", "Alpha", actor="operator")
        requirement = requirements.register(
            "alpha",
            RequirementDraft(
                title="Milestone acceptance projection",
                statement="The server shall derive milestone acceptance from canonical evidence.",
                category="functional",
                rationale="Traceability must not require manual matrix edits.",
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
                name="Acceptance milestone",
                requirement_ids=(requirement["requirement_id"],),
                prerequisite_requirement_ids=(),
                entry_policy={"requires": ["packet"]},
                exit_policy={"requires": ["accepted_campaign"]},
                risk_disposition="standard",
            ),
            actor="operator",
        )
        changes = ChangeControlService(runtime.ledger)
        change = changes.create_change(
            "alpha",
            GovernedChangeDraft(
                title="Acceptance change",
                rationale="Cover the milestone requirement.",
                requirement_ids=(requirement["requirement_id"],),
                milestone_id=milestone["milestone_id"],
            ),
            actor="operator",
        )
        changes.add_packet(
            "alpha",
            change["change_id"],
            ImplementationPacketDraft(
                title="Acceptance packet",
                completion_criteria=("projection gap is cleared",),
                requirement_ids=(requirement["requirement_id"],),
            ),
            actor="operator",
        )
        changes.transition_packet(
            "alpha",
            change["change_id"],
            "PACKET-000001",
            PacketTransition(
                status=PacketStatus.IMPLEMENTED,
                criterion_results={"projection gap is cleared": "covered"},
            ),
            actor="operator",
        )
        assurance = AssuranceService(
            assurance=runtime.ledger,
            changes=runtime.ledger,
        )
        assurance.create_campaign(
            "alpha",
            CampaignDraft(
                change_id=change["change_id"],
                title="Acceptance campaign",
                target_requirement_ids=(requirement["requirement_id"],),
                target_packet_ids=("PACKET-000001",),
            ),
            actor="tester",
        )
        assurance.add_campaign_case(
            "alpha",
            CampaignCaseDraft(
                campaign_id="CAMP-000001",
                title="Regression",
                purpose="Prove milestone acceptance evidence can be projected.",
                case_kind=CampaignCaseKind.REGRESSION,
                evidence_kind=CampaignEvidenceKind.DETERMINISTIC_TEST,
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
                reference="pytest:milestone-acceptance",
            ),
            actor="tester",
        )
        assurance.request_change_acceptance(
            "alpha",
            change["change_id"],
            acceptance_reference="accepted:CAMP-000001",
            actor="authority",
        )

        before = runtime.milestone_traceability.projection(
            "alpha", milestone_id=milestone["milestone_id"]
        )
        assert before["rows"][0]["acceptance_blockers"] == ["acceptance_evidence_missing"]

        accepted = lifecycle.accept_milestone(
            "alpha",
            milestone["milestone_id"],
            acceptance_evidence=("accepted:CAMP-000001",),
            actor="authority",
            request_id="accept-milestone",
        )
        repeated = lifecycle.accept_milestone(
            "alpha",
            milestone["milestone_id"],
            acceptance_evidence=("ignored:on-idempotent-retry",),
            actor="authority",
            request_id="accept-milestone",
        )

        assert accepted["status"] == "accepted"
        assert repeated["acceptance_evidence"] == ["accepted:CAMP-000001"]
        after = runtime.milestone_traceability.projection(
            "alpha", milestone_id=milestone["milestone_id"]
        )
        assert after["rows"][0]["acceptance_blockers"] == []
        assert after["gaps"] == []
    finally:
        runtime.close()
