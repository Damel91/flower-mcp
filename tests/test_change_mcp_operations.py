from flow_of_work_mcp import RequirementDraft, RequirementService
from flow_of_work_mcp.application.operation_contracts import lens_operation_membership
from flow_of_work_mcp.mcp_runtime import McpRuntime, build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import (
    handle_assurance,
    handle_campaign_author,
    handle_change,
    handle_handover,
    handle_packet_author,
    handle_packet_inspect,
    handle_promote_milestone,
    handle_what_next,
)
from tests.support_packet_factory import make_documental_packet_ready_fixture


def _runtime(tmp_path) -> McpRuntime:
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)
    requirements = RequirementService(runtime.ledger)
    requirements.create_project("alpha", "Alpha", actor="operator")
    requirements.register(
        "alpha",
        RequirementDraft(
            title="Track packets",
            statement="The server shall track governed implementation packets.",
            category="functional",
            rationale="Lifecycle control.",
        ),
        actor="operator",
    )
    return runtime


def test_next_bounded_change_and_packet_link_the_cause_to_real_routes(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        project = "alpha"
        milestone = handle_promote_milestone(
            runtime, project_id=project, name="Packet tracking",
            requirement_ids=["REQ-000001"], prerequisite_requirement_ids=[],
            entry_policy={}, exit_policy={}, risk_disposition="none", actor="operator",
        )["result"]["milestone_id"]
        before = handle_what_next(runtime, project_id=project)
        primary = before["result"]["primary_action"]
        assert (primary["tool"], primary["operation"]) == ("fow_change", "create_change")
        assert primary["arguments"] == {
            "project_id": project, "operation": "create_change", "milestone_id": milestone,
        }
        assert "requirement_ids" in primary["required_inputs"]
        assert primary["automatic_eligible"] is False
        markdown = project_markdown("fow_what_next", before)
        assert "requirements not covered" in markdown
        assert "REQ-000001" in markdown and milestone in markdown
        assert "Next step" in markdown and "create_change" in markdown
        assert "```json" not in markdown

        lens = next(
            lens for lens in lens_operation_membership()["lenses"] if lens["area"] == "requirements"
        )
        assert {"tool": "fow_change", "operation": "create_change"} not in (
            *lens["primary_operations"], *lens["companion_operations"],
        )
        runtime.interaction_projection.execute(
            "select_project", interaction_session_ref="test-client", project_id=project, actor="operator",
        )
        runtime.interaction_projection.execute("select", interaction_session_ref="test-client", area=2, actor="operator")
        frame = runtime.interaction_projection.frame("test-client")
        assert frame["actions"][0]["tool"] == "fow_interaction"
        assert frame["actions"][0]["operation"] == "select"

        change = handle_change(
            runtime, **primary["arguments"], title="Track packets",
            rationale="Deliver the selected milestone result.", requirement_ids=["REQ-000001"],
            actor="operator", request_id="change",
        )["result"]["change"]["change_id"]
        after = handle_what_next(runtime, project_id=project)
        primary = after["result"]["primary_action"]
        assert (primary["tool"], primary["operation"]) == ("fow_packet_author", "start_packet")
        assert primary["arguments"] == {
            "project_id": project, "operation": "start_packet", "change_id": change,
        }
        assert "completion_criteria" in primary["required_inputs"]
        markdown = project_markdown("fow_what_next", after)
        assert "has no implementation packets" in markdown and change in markdown
        assert "start_packet" in markdown and "```json" not in markdown
        assert "Acceptance prerequisites" in markdown and "inspect_change_acceptance" in markdown

        snapshot = handle_handover(runtime, project_id=project, operation="project_state_snapshot")
        gate = snapshot["result"]["project_state_snapshot"]["next_gate"]
        assert gate["kind"] == "packet_construction"
        assert gate["route"]["arguments"] == primary["arguments"]
        assert "Next Bounded Increment" in project_markdown(
            "fow_handover", snapshot, arguments={"operation": "project_state_snapshot"},
        )

        second_requirement = runtime.requirements.register(
            project, RequirementDraft(title="List packets", statement="List the packets.", category="functional"),
            actor="operator",
        )["requirement_id"]
        second_milestone = handle_promote_milestone(
            runtime, project_id=project, name="Packet listing", requirement_ids=[second_requirement],
            prerequisite_requirement_ids=[], entry_policy={}, exit_policy={}, risk_disposition="none",
            actor="operator",
        )["result"]["milestone_id"]
        selected = handle_what_next(runtime, project_id=project, milestone_id=second_milestone)
        assert selected["result"]["primary_action"]["arguments"]["milestone_id"] == second_milestone
        assert selected["result"]["primary_action"]["requirement_ids"] == (second_requirement,)
    finally:
        runtime.close()


def test_change_acceptance_markdown_explains_campaign_and_finding_blockers(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        project = "alpha"
        change = handle_change(
            runtime, project_id=project, operation="create_change", actor="operator",
            title="Review packet tracking", rationale="Bound the result.", requirement_ids=["REQ-000001"],
        )["result"]["change"]["change_id"]
        finding = handle_assurance(
            runtime, project_id=project, operation="record_finding", actor="operator",
            change_id=change, title="Missing result", rationale="A result is missing.",
            severity="medium", expected_correction="Show the result.", scope_kind="change", scope_ref=change,
            source_anchor="test:missing-result",
        )["result"]["assurance"]["finding_id"]
        args = {"project_id": project, "operation": "request_change_acceptance", "actor": "operator",
                "change_id": change, "acceptance_reference": "pending-test"}
        preflight_args = {"project_id": project, "operation": "inspect_change_acceptance",
                          "actor": "operator", "change_id": change}
        before = runtime.ledger.ledger_version(project)
        preflight = handle_assurance(runtime, **preflight_args)
        assert runtime.ledger.ledger_version(project) == before
        blocked = handle_assurance(runtime, **args)
        assert blocked["reason"] == "change_acceptance_blocked"
        assert preflight["result"]["assurance"]["blockers"] == blocked["result"]["blockers"]
        assert {blocker["kind"] for blocker in blocked["result"]["blockers"]} == {
            "campaign_missing", "finding_unresolved",
        }
        markdown = project_markdown("fow_assurance", blocked, arguments=args)
        assert "No campaign is linked to this change" in markdown and change in markdown
        assert "fow_campaign_author" in markdown and "scope.change_id" in markdown
        assert finding in markdown and "get_finding" in markdown
        assert "Effect state" in markdown and "unknown" in markdown and "Before retrying" in markdown
        assert blocked["result"]["next_tool_call"]["arguments"] == preflight_args
        assert "```json" not in markdown
        assert "No campaign is linked" in project_markdown(
            "fow_assurance", preflight, arguments=preflight_args,
        )

        campaign = handle_campaign_author(
            runtime, project_id=project, operation="start", actor="operator", request_id="campaign",
            title="Verify packet tracking", scope={"change_id": change},
        )["result"]["campaign"]["campaign_id"]
        preflight = handle_assurance(runtime, **preflight_args)
        assert not any(item["kind"] == "campaign_missing" for item in preflight["result"]["assurance"]["blockers"])
        markdown = project_markdown("fow_assurance", preflight, arguments=preflight_args)
        assert campaign in markdown and "fow_campaign_inspect" in markdown
    finally:
        runtime.close()


def test_fow_change_creates_packets_and_blocks_false_closure(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        change = handle_change(
            runtime,
            project_id="alpha",
            operation="create_change",
            actor="operator",
            title="MCP change",
            rationale="Expose packet control.",
            requirement_ids=["REQ-000001"],
            request_id="change",
        )
        assert change["status"] == "success"
        assert change["result"]["change"]["change_id"] == "CHANGE-000001"

        packet = handle_packet_author(
            runtime,
            project_id="alpha",
            operation="start_packet",
            actor="operator",
            change_id="CHANGE-000001",
            title="MCP packet",
            intent="Expose packet control through the canonical lifecycle.",
            rationale="Bound the canonical MCP packet lifecycle.",
            in_scope=["packet lifecycle control"],
            invariants=["completion evidence remains mandatory"],
            completion_criteria=["tests pass"],
            target_policy="documental_only",
            request_id="packet",
        )
        assert packet["status"] == "success"
        assert packet["result"]["packet"]["packet_id"] == "PACKET-000001"
        make_documental_packet_ready_fixture(
            runtime,
            project_id="alpha",
            change_id="CHANGE-000001",
            packet_id="PACKET-000001",
            request_id="packet",
        )

        blocked = handle_change(
            runtime,
            project_id="alpha",
            operation="transition_packet",
            actor="operator",
            change_id="CHANGE-000001",
            packet_id="PACKET-000001",
            packet_status="implemented",
        )
        assert blocked["status"] == "blocked"
        assert blocked["reason"] == "packet_completion_criteria_missing"
        assert blocked["result"]["missing_criteria"] == ["tests pass"]

        closed = handle_change(
            runtime,
            project_id="alpha",
            operation="transition_packet",
            actor="operator",
            change_id="CHANGE-000001",
            packet_id="PACKET-000001",
            packet_status="implemented",
            criterion_results={"tests pass": "pytest tests/test_change_mcp_operations.py"},
            request_id="close",
        )
        assert closed["status"] == "success"
        assert closed["result"]["change"]["status"] == "implemented"
    finally:
        runtime.close()


def test_fow_what_next_exposes_ready_packet_action(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        handle_change(
            runtime,
            project_id="alpha",
            operation="create_change",
            actor="operator",
            title="Next packet",
            rationale="Expose packet next work.",
            requirement_ids=["REQ-000001"],
        )
        handle_packet_author(
            runtime,
            project_id="alpha",
            operation="start_packet",
            actor="operator",
            change_id="CHANGE-000001",
            title="Ready packet",
            intent="Expose the next authoring action for a ready packet.",
            completion_criteria=["done"],
            request_id="ready-packet",
        )
        packet = runtime.changes.get_change("alpha", "CHANGE-000001")["packets"][0]
        assert packet["navigation_audit_ids"] == ["NAV-000001"]
        assert runtime.packet_construction.audit_for_packet(
            "alpha", "CHANGE-000001", "PACKET-000001"
        ) is not None
        assert runtime.packet_reconciliation.get(
            "alpha", change_id="CHANGE-000001", packet_id="PACKET-000001"
        ) is not None
        result = handle_what_next(runtime, project_id="alpha")
        assert result["status"] == "success"
        primary = result["result"]["primary_action"]
        assert primary["tool"] == "fow_packet_author"
        assert primary["operation"] == "add_unit"
        assert primary["scope"] == {
            "change_id": "CHANGE-000001",
            "packet_id": "PACKET-000001",
        }
    finally:
        runtime.close()


def test_packet_requirement_view_is_paged_and_target_mutation_is_bounded(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        requirements = RequirementService(runtime.ledger)
        for index in range(2, 9):
            requirements.register(
                "alpha",
                RequirementDraft(
                    title=f"Requirement {index}",
                    statement=f"The server shall satisfy behavior {index}.",
                    category="functional",
                    rationale="Bounded packet projection coverage.",
                ),
                actor="operator",
            )
        requirement_ids = [f"REQ-{index:06d}" for index in range(1, 9)]
        handle_change(
            runtime,
            project_id="alpha",
            operation="create_change",
            actor="operator",
            title="Bounded packet",
            rationale="Exercise packet projections.",
            requirement_ids=requirement_ids,
        )
        handle_packet_author(
            runtime,
            project_id="alpha",
            operation="start_packet",
            actor="operator",
            change_id="CHANGE-000001",
            title="Bounded packet",
            intent="Exercise bounded packet projections and target mutation.",
            completion_criteria=["projection verified"],
            requirement_ids=requirement_ids,
            request_id="bounded-packet",
        )

        summary = handle_packet_inspect(
            runtime,
            project_id="alpha",
            packet_id="PACKET-000001",
        )["result"]["packet"]
        page = handle_packet_inspect(
            runtime,
            project_id="alpha",
            packet_id="PACKET-000001",
            view="requirements",
            offset=5,
            limit=2,
        )["result"]["packet"]
        mutation = handle_change(
            runtime,
            project_id="alpha",
            operation="set_packet_target_state",
            actor="operator",
            change_id="CHANGE-000001",
            packet_id="PACKET-000001",
            target_policy="documental_only",
            target_state="refined",
            request_id="bounded-target-mutation",
        )

        assert summary["packet"]["requirement_scope"] == {
            "count": 8,
            "sample": requirement_ids[:5],
            "truncated": True,
        }
        assert "requirement_ids" not in summary["packet"]
        assert page["requirements"] == requirement_ids[5:7]
        assert page["pagination"] == {
            "total": 8,
            "returned": 2,
            "offset": 5,
            "limit": 2,
            "has_more": True,
            "next_offset": 7,
        }
        assert mutation["status"] == "success"
        assert "change" not in mutation["result"]
        assert mutation["result"]["packet_delta"]["readiness_state"] == "refined"
        assert mutation["result"]["packet_delta"]["targets"][
            "target_binding_ids"
        ]["count"] == 0
    finally:
        runtime.close()
