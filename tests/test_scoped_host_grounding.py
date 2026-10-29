"""Explicit host scope stays bounded and does not rebind historical evidence."""
import pytest

from flow_of_work_mcp import RequirementDraft
from tests.test_host_intention_grounding import _runtime, _receipt


def prepare(runtime, goal, ids, request="scope"):
    return runtime.semantic_assignments.prepare(
        "alpha", role="intention_grounding", execution_mode="host",
        goal_node_ids=(goal["goal_node_id"],), host_evidence=_receipt(),
        requirement_ids=ids, actor="engineer", request_id=request)


def test_explicit_scope_avoids_global_truncation_and_unrelated_drift(tmp_path):
    runtime, goal, requirement, _ = _runtime(tmp_path)
    try:
        for index in range(129):
            runtime.requirements.register("alpha", RequirementDraft(
                title=f"Other behavior {index}", statement=f"Other behavior {index} shall remain tracked.",
                category="functional"), actor="engineer")
        broad = runtime.semantic_assignments.prepare(
            "alpha", role="intention_grounding", execution_mode="host",
            goal_node_ids=(goal["goal_node_id"],), host_evidence=_receipt(),
            actor="engineer", request_id="broad")
        assert broad["preparation"]["input_truncated"] is True
        scoped = prepare(runtime, goal, [requirement["requirement_id"]])
        frozen = scoped["preparation"]
        assert frozen["selected_requirement_ids"] == [requirement["requirement_id"]]
        assert frozen["input_truncated"] is False
        assert len(frozen["scope"]["canonical_requirements"]) == 1
        assert frozen["scope"]["requirement_scope"]["project_count_as_of_preparation"] == 130
        runtime.requirements.register("alpha", RequirementDraft(
            title="Unrelated addition", statement="Unrelated behavior shall be retained.", category="functional"),
            actor="engineer")
        assert runtime.semantic_assignments.inspect("alpha", scoped["assignment_id"])["current"] is True
        assert runtime.semantic_assignments.inspect("alpha", broad["assignment_id"])["current"] is False
    finally:
        runtime.close()


def test_explicit_empty_is_not_omission_and_keeps_source_limitations(tmp_path):
    runtime, goal, _, _ = _runtime(tmp_path)
    try:
        receipt = _receipt()
        receipt["truncated"] = True
        value = runtime.semantic_assignments.prepare(
            "alpha", role="intention_grounding", execution_mode="host",
            goal_node_ids=(goal["goal_node_id"],), host_evidence=receipt,
            requirement_ids=[], actor="engineer", request_id="empty")
        frozen = value["preparation"]
        assert frozen["selected_requirement_ids"] == []
        assert frozen["scope"]["canonical_requirements"] == []
        assert frozen["input_truncated"] is True
        assert "not_whole_project" in frozen["scope"]["requirement_scope"]["completeness"]
    finally:
        runtime.close()


@pytest.mark.parametrize("ids", ["REQ-000001", [True], ["wrong"], ["REQ-000001"] * 2,
                                ["REQ-999999"], [f"REQ-{i:06}" for i in range(129)]])
def test_bad_scopes_create_no_assignment(tmp_path, ids):
    runtime, goal, _, _ = _runtime(tmp_path)
    try:
        before = runtime.ledger.ledger_version("alpha")
        with pytest.raises(ValueError):
            prepare(runtime, goal, ids)
        assert runtime.ledger.ledger_version("alpha") == before
    finally:
        runtime.close()


def test_scope_rejects_internal_and_srs_routes(tmp_path):
    runtime, goal, requirement, _ = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="only for host"):
            runtime.semantic_assignments.prepare(
                "alpha", role="intention_grounding", execution_mode="internal",
                goal_node_ids=(goal["goal_node_id"],), requirement_ids=[requirement["requirement_id"]],
                actor="engineer", request_id="internal")
        with pytest.raises(ValueError, match="grounding-only"):
            runtime.semantic_assignments.prepare(
                "alpha", role="srs_semantic_validation", execution_mode="host",
                requirement_ids=[], actor="engineer", request_id="srs")
    finally:
        runtime.close()
