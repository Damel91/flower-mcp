import asyncio

import pytest

from flow_of_work_mcp.application.operation_contracts import operation_contract, parameter_help
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app


def test_exact_help_has_only_selected_applicability_and_explains_audit_modes():
    change = operation_contract("fow_change", "create_change")
    assert "Applies to" not in change["field_descriptions"]["title"]
    assert "Required by" not in change["field_descriptions"]["title"]
    assert "Applies to" in parameter_help("fow_change", "title")["description"]

    inspect = operation_contract("fow_campaign_inspect", "cases")
    assert "Canonical values: cases." in inspect["field_descriptions"]["view"]
    assert "summary" not in inspect["field_descriptions"]["view"]
    assert parameter_help("fow_campaign_inspect", "view", selected_operation="cases")["examples"] == ["cases"]

    export = operation_contract("fow_architecture", "export")["field_descriptions"]["payload"]
    assert all(route not in export for route in ("inspect", "propose", "adopt"))
    todo = operation_contract("fow_external_work", "todo")["field_descriptions"]["payload"]
    assert all(term not in todo for term in ("outcome", "PVP"))
    assert "propose" in parameter_help("fow_architecture", "payload")["description"]

    audit = operation_contract("fow_audit_phase", "call")["guidance"]
    assert "Omit repository_review" in audit["plain_scope"]
    assert "nonempty project-local scope_id" in audit["plain_scope"]
    assert "identical selection and order" in audit["plain_scope"]
    assert "expected_basis_fingerprint" in audit["review_scope"]


@pytest.mark.parametrize("unknown", [{"operation": "cases"}, {"unexpected": 42}])
def test_campaign_inspect_rejects_unknown_inputs_before_reading(unknown):
    class NoRuntimeAccess:
        def __getattribute__(self, name):
            raise AssertionError(f"Unexpected runtime access: {name}")

    app = create_app(NoRuntimeAccess())
    result = asyncio.run(app.call_tool("fow_campaign_inspect", {"project_id": "alpha", **unknown}))
    rejection = result.structuredContent["result"]
    assert rejection["status"] == "rejected" and rejection["reason"] == "unknown_arguments"
    assert rejection["result"]["unknown_fields"] == list(unknown)
    assert "view" in rejection["result"]["accepted_fields"]
    assert {"summary", "cases", "oracles"} <= set(rejection["result"]["diagnostics"][0]["accepted_values"])
    assert "view=cases" in result.content[0].text


@pytest.mark.parametrize(("tool", "arguments", "code", "continuation"), [
    ("fow_handover", {"project_id": "alpha"}, "operation_required", "operation=project_state_snapshot"),
    ("fow_packet_author", {"project_id": "alpha", "operation": "start_packet"},
     "packet_identity_inputs_missing", "operation_name=start_packet"),
])
def test_observed_missing_inputs_have_scoped_markdown_before_dispatch(tool, arguments, code, continuation):
    class NoRuntimeAccess:
        def __getattribute__(self, name):
            raise AssertionError(f"Unexpected runtime access: {name}")

    result = asyncio.run(create_app(NoRuntimeAccess()).call_tool(tool, arguments))
    envelope = result.structuredContent["result"]
    assert envelope["status"] == "rejected" and envelope["reason"] == code
    assert continuation in result.content[0].text
    assert "```json" not in result.content[0].text


def test_finding_and_campaign_exact_help_matches_public_conditions_and_labels(tmp_path):
    runtime = build_runtime(database_path=tmp_path / "ledger.sqlite3", import_root=tmp_path)

    async def run():
        app = create_app(runtime)

        async def call(tool, expected="success", **arguments):
            response = await app.call_tool(tool, arguments)
            envelope = response.structuredContent["result"]
            assert envelope["status"] == expected, envelope
            return envelope

        await call("fow_create_project", project_id="alpha", name="Alpha", actor="engineer")
        requirement = await call(
            "fow_register_requirement", project_id="alpha", title="Covered behavior",
            statement="The covered call returns a result.", category="functional",
            rationale="The call has a public observable effect.", actor="engineer",
        )
        requirement_id = requirement["result"]["requirement_id"]
        change = await call(
            "fow_change", project_id="alpha", operation="create_change", actor="engineer",
            title="Cover behavior", rationale="Verify the documented call.", requirement_ids=[requirement_id],
        )
        change_id = change["result"]["change"]["change_id"]

        finding_help = operation_contract("fow_assurance", "record_finding")
        assert finding_help["guidance"]["require_any_of"] == ["source_anchor", "implementation_ref"]
        assert finding_help["example"]["source_anchor"]
        finding_args = {
            "project_id": "alpha", "operation": "record_finding", "actor": "engineer",
            "change_id": change_id, "severity": "medium", "title": "Missing verification",
            "rationale": "The observation was not recorded.", "expected_correction": "Record it.",
            "scope_kind": "change", "scope_ref": change_id,
        }
        await call("fow_assurance", expected="rejected", **finding_args)
        anchored = await call("fow_assurance", source_anchor="src/example.py:5", **finding_args)
        await call("fow_assurance", implementation_ref="source:example.py", **finding_args)
        finding_id = anchored["result"]["assurance"]["finding_id"]

        disposition_help = operation_contract("fow_assurance", "set_finding_disposition")
        conditional = disposition_help["guidance"]["requires_if"]
        disposition = {
            "project_id": "alpha", "operation": "set_finding_disposition",
            "actor": "engineer", "finding_id": finding_id, "rationale": "Reviewed disposition.",
        }
        for value in conditional["disposition_reference"]["disposition"]:
            denied = await call("fow_assurance", expected="blocked", disposition=value, **disposition)
            assert denied["reason"] == "finding_disposition_requires_reference"
        assert conditional["evidence_refs"] == {"disposition": ["resolved"]}
        denied = await call("fow_assurance", expected="blocked", disposition="resolved", **disposition)
        assert denied["reason"] == "finding_resolution_requires_evidence"
        await call(
            "fow_assurance", disposition="deferred", disposition_reference="decision:defer", **disposition,
        )

        campaign = await call(
            "fow_campaign_author", project_id="alpha", operation="start", actor="engineer",
            request_id="campaign", title="Verify behavior", scope={"change_id": change_id},
        )
        campaign_id = campaign["result"]["campaign"]["campaign_id"]
        add = operation_contract("fow_campaign_author", "add_case")
        assert "regression" in add["guidance"]["case_kind"]["recognized_labels"]
        assert "automated" in add["guidance"]["case_kind"]["compatibility"]
        assert "case.case_kind" not in add["accepted_values"]
        assert "case.case_kind" in add["field_descriptions"] and "case.oracle_kind" in add["field_descriptions"]

        await call(
            "fow_campaign_author", project_id="alpha", operation="add_case", actor="engineer",
            campaign_id=campaign_id, request_id="case", case={
                "title": "Check call", "purpose": "Observe the public return value.",
                "case_kind": "automated", "action": "Invoke the call.", "expected_outcome": "A result returns.",
                "observation_point": "Call response", "oracle_kind": "fixture-oracle",
            },
        )
        cases = await call("fow_campaign_inspect", project_id="alpha", campaign_id=campaign_id, view="cases")
        case = cases["result"]["cases"][0]
        assert case["case_kind"] == "automated" and case["oracle_kind"] == "fixture-oracle"
        oracle_help = operation_contract("fow_campaign_author", "author_oracle")
        assert "oracle.oracle_kind" in oracle_help["required_fields"]
        assert "explicitly" in oracle_help["guidance"]["oracle_kind"]
        assert "default" not in oracle_help["guidance"]["oracle_kind"]
        semantic_help = oracle_help["guidance"]["semantic_fields"]
        oracle_example = oracle_help["example"]["oracle"]
        assert set(semantic_help["required_keys"]) == oracle_example["semantic_fields"].keys()
        assert set(semantic_help["nonempty_values"]) == {
            "stimulus", "expected_observations", "execution_class", "verification_intent",
        }
        await call(
            "fow_campaign_author", expected="rejected", project_id="alpha", operation="author_oracle",
            actor="engineer", campaign_id=campaign_id, case_id=case["case_id"], request_id="oracle-kind",
            oracle={"subject_bindings": [requirement_id], "authority_reference": "decision:oracle", "semantic_fields": {}},
        )
        await call(
            "fow_campaign_author", project_id="alpha", operation="author_oracle",
            actor="engineer", campaign_id=campaign_id, case_id=case["case_id"], request_id="oracle-example",
            oracle={**oracle_example, "subject_bindings": [requirement_id], "authority_reference": "decision:oracle"},
        )
        oracles = await call("fow_campaign_inspect", project_id="alpha", campaign_id=campaign_id, view="oracles")
        oracle = oracles["result"]["oracles"][0]
        assert oracle["status"] == "constructible" and oracle["questions"] == []

        attestation_help = await app.call_tool("fow_capabilities", {
            "view": "operation", "operation_tool": "fow_campaign_author", "operation_name": "attest_source",
        })
        source_help = attestation_help.content[0].text
        assert "reserved for this case" in source_help and "source bytes and paths unchanged" in source_help
        assert "Reuse the original request_id only to read back that exact recorded request" in source_help
        transition_help = operation_contract("fow_change", "transition_packet")
        assert "including punctuation" in transition_help["guidance"]["criterion_results"]
        assert transition_help["example"]["packet_status"] == "implemented"
        await call("fow_campaign_inspect", project_id="alpha", campaign_id=campaign_id)

        # This selector fix remains confined to campaign inspection.
        await call("fow_get_requirement", project_id="alpha", requirement_id=requirement_id, unrelated=True)

        audit = await call(
            "fow_audit_phase", project_id="alpha", scope_id="owned-label", actor="engineer",
            requirement_ids=[requirement_id], request_id="plain-audit",
        )
        job_id = audit["result"]["job"]["job_id"]
        assert runtime.jobs.wait("alpha", job_id, timeout=5).status.value == "completed"

    try:
        asyncio.run(run())
    finally:
        runtime.close()
