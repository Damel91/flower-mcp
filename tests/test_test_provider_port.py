from __future__ import annotations

from typing import Mapping
from dataclasses import replace

import pytest

from flow_of_work_mcp.adapters.implementation_intelligence.test_provider import (
    FLOW_TEST_PROVIDER_METADATA_KEY,
    CodingCastleTestProjectBinding,
    McpCodingCastleTestProvider,
)
from flow_of_work_mcp.core.domain.campaign_authority import (
    TestProviderMaterializationMode as ProviderMaterializationMode,
    TestProviderCommand as ProviderCommand,
    exact_fingerprint,
)
from flow_of_work_mcp.core.domain.oracle_ir import (
    OracleIRCase,
    OracleIRMatcher,
    OracleIRObservation,
    OracleIRObservationSource,
    OracleIRSnapshot,
    OracleIRStimulus,
    OracleIRStimulusOperator,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    PacketProviderRejectedError,
)


class _Client:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = dict(response)
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.metas: list[Mapping[str, object] | None] = []

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        meta: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        self.calls.append((tool_name, dict(arguments)))
        self.metas.append(dict(meta) if meta is not None else None)
        if tool_name == "codingcastle_tests" and arguments.get("detail_level") not in {
            "minimal", "standard", "verbose"
        }:
            raise ValueError("unknown CodingCastle detail_level")
        return self.response


def _command(*, operation: str = "materialize") -> ProviderCommand:
    return ProviderCommand(
        command_id="TCMD-000001",
        flow_session_ref="flow-project",
        campaign_id="CAMP-000001",
        case_id="CASE-000001",
        operation=operation,
        oracle_id="ORACLE-000001",
        oracle_revision=2,
        oracle_fingerprint="oracle-fingerprint",
        attestation_intent_ref="ATTEST-000001",
        source_manifest_digest="source-manifest",
        semantic_input={
            "oracle_snapshot": {
                "oracle_kind": "unit_contract",
                "subject_bindings": ["Service.run"],
                "goal_bindings": ["GOAL-000001"],
                "semantic_fields": {
                    "preconditions": ["service is initialized"],
                    "stimulus": "invoke run",
                    "input_domain": {"value": [0, 1]},
                    "expected_observations": ["returns the normalized value"],
                    "invariants": ["state remains valid"],
                    "tolerances": {"absolute": 0},
                    "forbidden_effects": ["no filesystem write"],
                    "expected_failure_transitions": [],
                    "oracle_violation_conditions": ["unexpected exception"],
                },
            },
            "source_files": {"tests/service.test.ts": "export const value = 1;\n"},
            "allowed_materialization_scope": ["tests/service.test.ts"],
            "language": "typescript",
            "framework": "vitest",
        },
        delivery_fingerprint="delivery-fingerprint",
    )


def _response(*, command_ref: str = "TCMD-000001") -> dict[str, object]:
    return {
        "status": "ok",
        "result": {
            "test": {"ref": "TEST-000001"},
            "provider_receipt": {
                "contract_version": "flow.test_provider.receipt.v2",
                "command_ref": command_ref,
                "provider_event_seq": 3,
                "technical_state": "technically_valid",
                "evidence_disposition": "diagnostic_only",
                "attestation_state": "pending_technical_validation",
                "oracle": {
                    "oracle_ref": "ORACLE-000001",
                    "revision": 2,
                    "fingerprint": "oracle-fingerprint",
                },
                "materialization_mode": "orchestrator_source",
                "authority_input_fingerprint": "source-manifest",
                "produced_source_manifest_digest": "source-manifest",
                "materialization": {
                    "ref": "TEST-000001",
                    "revision": 1,
                    "representation_fingerprint": "representation-fingerprint",
                    "representation_lineage": [],
                },
                "evidence_reference": "EVIDENCE-000001",
                "provider_test_ref": "TEST-000001",
                "current": True,
                "complete": True,
                "integrity_preserved": True,
                "diagnostics": [],
                "materialization_evidence": {},
                "next_action": "attest the current materialization",
            },
        },
    }


def _deterministic_command() -> ProviderCommand:
    oracle_ir = OracleIRSnapshot(
        oracle_id="ORACLE-000002",
        oracle_revision=1,
        oracle_fingerprint="oracle-ir-fingerprint",
        dependency_fingerprint="dependency-fingerprint",
        authority_reference="ATTEST-000002",
        subject_bindings=("add",),
        fixture_bindings=(),
        goal_bindings=("REQ-001",),
        cases=(
            OracleIRCase(
                preconditions=(),
                stimulus=OracleIRStimulus(
                    operator=OracleIRStimulusOperator.CALL,
                    subject_ref="add",
                    arguments=(1, 2),
                ),
                input_domain={},
                observations=(
                    OracleIRObservation(
                        source=OracleIRObservationSource.RETURN,
                        matcher=OracleIRMatcher.EQUALS,
                        expected=3,
                        has_expected=True,
                    ),
                ),
                invariants=(),
                forbidden_effects=(),
                tolerances={},
                expected_failure_transitions=(),
                oracle_violation_conditions=(),
                execution_class="deterministic",
                verification_intent="prove exact addition",
            ),
        ),
    )
    return ProviderCommand(
        command_id="TCMD-000002",
        flow_session_ref="flow-project",
        campaign_id="CAMP-000001",
        case_id="CASE-000001",
        operation="materialize",
        oracle_id=oracle_ir.oracle_id,
        oracle_revision=oracle_ir.oracle_revision,
        oracle_fingerprint=oracle_ir.oracle_fingerprint,
        attestation_intent_ref="ATTEST-000002",
        source_manifest_digest="",
        semantic_input={"harness": {"disposition": "repository", "participants": []}},
        delivery_fingerprint="deterministic-delivery-fingerprint",
        materialization_mode=(ProviderMaterializationMode.DETERMINISTIC_ORACLE_IR),
        oracle_ir=oracle_ir.as_payload(),
        requested_capability={
            "language": "python",
            "framework": "pytest",
            "oracle_ir_contract_version": "flow.oracle.ir.v1",
            "operator_profile": "flow.oracle.unit-contract.v1",
            "materializer_version": "codingcastle.oracle-materializer.v1",
            "adapter_version": "codingcastle.oracle-emitter.python-pytest.v1",
        },
    )


def _deterministic_response(
    command: ProviderCommand,
) -> dict[str, object]:
    lineage = [
        {
            "ir_node_id": "IRN-CASE-0123456789abcdef0123",
            "semantic_ast_node_id": "AST-0123456789abcdef01234567",
            "source_region_fingerprint": "sha256:semantic-region",
        }
    ]
    return {
        "status": "ok",
        "result": {
            "test": {"ref": "TEST-000002"},
            "provider_receipt": {
                "contract_version": "flow.test_provider.receipt.v2",
                "command_ref": command.command_id,
                "provider_event_seq": 4,
                "technical_state": "technically_valid",
                "evidence_disposition": "passed",
                "attestation_state": "attested_current",
                "oracle": {
                    "oracle_ref": command.oracle_id,
                    "revision": command.oracle_revision,
                    "fingerprint": command.oracle_fingerprint,
                },
                "materialization_mode": "deterministic_oracle_ir",
                "authority_input_fingerprint": (command.authority_input_fingerprint),
                "produced_source_manifest_digest": "produced-source-manifest",
                "materialization": {
                    "ref": "TEST-MATERIALIZATION-000002",
                    "revision": 2,
                    "representation_fingerprint": "rendered-source-manifest",
                    "representation_lineage": [
                        {
                            "authority_input_fingerprint": (
                                command.authority_input_fingerprint
                            ),
                            "source_manifest_digest": "rendered-source-manifest",
                            "complete": True,
                            "integrity_preserved": True,
                            "from_materialization_ref": ("TEST-MATERIALIZATION-000001"),
                            "to_materialization_ref": ("TEST-MATERIALIZATION-000002"),
                            "integrity_proof_fingerprint": ("sha256:integrity-proof"),
                        }
                    ],
                },
                "evidence_reference": "EVIDENCE-000002",
                "provider_test_ref": "TEST-000002",
                "current": True,
                "complete": True,
                "integrity_preserved": True,
                "diagnostics": [],
                "materialization_evidence": {
                    "oracle_ir_contract_version": "flow.oracle.ir.v1",
                    "operator_profile": "flow.oracle.unit-contract.v1",
                    "materializer_version": "codingcastle.oracle-materializer.v1",
                    "adapter_version": "codingcastle.oracle-emitter.python-pytest.v1",
                    "semantic_ast_fingerprint": "sha256:semantic-ast",
                    "rendered_source_fingerprint": "rendered-source-manifest",
                    "ir_node_lineage": lineage,
                },
                "next_action": "run the current materialization",
            },
        },
    }


def _provider(client: _Client) -> McpCodingCastleTestProvider:
    return McpCodingCastleTestProvider(
        client=client,
        bindings=(
            CodingCastleTestProjectBinding(
                project_id="flow-project",
                provider_session_id="coding-session",
                repository="service-repo",
            ),
        ),
    )


def test_materialization_uses_public_tool_and_private_provider_correlation() -> None:
    client = _Client(_response())
    receipt = _provider(client).execute(_command())

    tool, arguments = client.calls[0]
    assert tool == "codingcastle_tests"
    assert arguments["session_id"] == "coding-session"
    assert arguments["repository"] == "service-repo"
    assert arguments["operation"] == "create"
    assert arguments["detail_level"] == "verbose"
    assert arguments["relative_path"] == "tests/service.test.ts"
    assert arguments["source"] == "export const value = 1;\n"
    assert arguments["language"] == "typescript"
    assert arguments["framework"] == "vitest"
    assert arguments["oracle"]["test_kind"] == "unit_contract"
    assert "campaign_ref" not in arguments

    metadata = client.metas[0][FLOW_TEST_PROVIDER_METADATA_KEY]
    assert metadata["command_ref"] == "TCMD-000001"
    assert metadata["flow_session_ref"] == "flow-project"
    assert metadata["campaign_ref"] == "CAMP-000001"
    assert metadata["case_ref"] == "CASE-000001"
    assert metadata["oracle"]["fingerprint"] == "oracle-fingerprint"
    assert metadata["semantic_input"]["harness"] == {
        "disposition": "repository",
        "participants": [],
    }
    assert receipt.command_id == "TCMD-000001"
    assert receipt.materialization_ref == "TEST-000001"
    assert receipt.provider_test_ref == "TEST-000001"


@pytest.mark.parametrize("operation", ["materialize", "edit", "validate", "run", "promote", "discard", "report"])
def test_every_test_operation_uses_canonical_complete_profile(operation: str) -> None:
    original = _command()
    command = replace(original, operation=operation, semantic_input={
        **original.semantic_input, "provider_test_ref": "TEST-000001",
        "reason": "Discard the isolated diagnostic fixture.",
    })
    client = _Client(_response())
    receipt = _provider(client).execute(command)
    assert client.calls[0][1]["detail_level"] == "verbose"
    assert len(client.calls) == 1
    assert receipt.command_id == command.command_id
    assert receipt.provider_test_ref == "TEST-000001"
    assert receipt.attestation_state.value == "pending_technical_validation"


def test_provider_receipt_must_bind_the_exact_durable_command() -> None:
    provider = _provider(_Client(_response(command_ref="TCMD-000002")))

    with pytest.raises(
        ImplementationProviderContractError,
        match="test_provider_receipt_command_mismatch",
    ):
        provider.execute(_command())


def test_provider_rejection_remains_typed_and_bounded() -> None:
    provider = _provider(
        _Client(
            {
                "status": "blocked",
                "result": {"reason": "source_manifest_mismatch"},
            }
        )
    )

    with pytest.raises(PacketProviderRejectedError) as error:
        provider.execute(_command())
    assert error.value.reason == "source_manifest_mismatch"


def test_flow_behavior_oracle_maps_to_provider_unit_contract() -> None:
    client = _Client(_response())
    command = _command()
    semantic = dict(command.semantic_input)
    oracle = dict(semantic["oracle_snapshot"])
    oracle["oracle_kind"] = "behavior"
    semantic["oracle_snapshot"] = oracle
    command = ProviderCommand(
        **{
            **command.__dict__,
            "semantic_input": semantic,
        }
    )

    _provider(client).execute(command)

    assert client.calls[0][1]["oracle"]["test_kind"] == "unit_contract"


@pytest.mark.parametrize(
    ("flow_kind", "provider_kind"),
    (
        ("deterministic_contract", "unit_contract"),
        ("unit_contract", "unit_contract"),
        ("integration_behavior", "integration_behavior"),
    ),
)
def test_current_flow_oracle_kinds_map_to_closed_provider_kinds(
    flow_kind: str,
    provider_kind: str,
) -> None:
    client = _Client(_response())
    command = _command()
    semantic = dict(command.semantic_input)
    oracle = dict(semantic["oracle_snapshot"])
    oracle["oracle_kind"] = flow_kind
    semantic["oracle_snapshot"] = oracle
    command = ProviderCommand(**{**command.__dict__, "semantic_input": semantic})

    _provider(client).execute(command)

    assert client.calls[0][1]["oracle"]["test_kind"] == provider_kind


def test_unknown_oracle_kind_fails_before_provider_side_effect() -> None:
    client = _Client(_response())
    command = _command()
    semantic = dict(command.semantic_input)
    oracle = dict(semantic["oracle_snapshot"])
    oracle["oracle_kind"] = "unsupported-kind"
    semantic["oracle_snapshot"] = oracle
    command = ProviderCommand(**{**command.__dict__, "semantic_input": semantic})

    with pytest.raises(
        ImplementationProviderContractError,
        match="test_provider_oracle_kind_invalid",
    ):
        _provider(client).execute(command)
    assert client.calls == []


def test_project_integration_omits_repository_and_transports_participants() -> None:
    client = _Client(_response())
    command = _command()
    semantic = dict(command.semantic_input)
    semantic["harness"] = {
        "disposition": "project_integration",
        "participants": [
            {
                "participant_ref": "api",
                "repository": "service-repo",
                "runtime_participant": "python-api",
                "role": "real",
            },
            {
                "participant_ref": "ui",
                "repository": "ui-repo",
                "runtime_participant": "web-client",
                "role": "mock",
            },
        ],
    }
    command = ProviderCommand(**{**command.__dict__, "semantic_input": semantic})

    _provider(client).execute(command)

    arguments = client.calls[0][1]
    assert "repository" not in arguments
    assert arguments["oracle"]["test_kind"] == "integration_behavior"
    metadata = client.metas[0][FLOW_TEST_PROVIDER_METADATA_KEY]
    assert metadata["semantic_input"]["harness"] == semantic["harness"]


def test_provider_command_preserves_source_bytes_in_transport_identity() -> None:
    first = _command()
    first_source = first.semantic_input["source_files"]["tests/service.test.ts"]
    assert first_source == "export const value = 1;\n"

    semantic = dict(first.semantic_input)
    semantic["source_files"] = {"tests/service.test.ts": "export  const value = 1;\n"}
    second = ProviderCommand(**{**first.__dict__, "semantic_input": semantic})

    assert exact_fingerprint(first.as_payload()) != exact_fingerprint(
        second.as_payload()
    )


def test_materialization_capability_is_resolved_from_live_provider_projection() -> None:
    client = _Client(
        {
            "group": "tests",
            "deterministic_materializer_profiles": [
                {
                    "language": "python",
                    "framework": "pytest",
                    "oracle_ir_contract_version": "flow.oracle.ir.v1",
                    "operator_profile": "flow.oracle.unit-contract.v1",
                    "materializer_version": "codingcastle.oracle-materializer.v1",
                    "adapter_version": ("codingcastle.oracle-emitter.python-pytest.v1"),
                }
            ],
        }
    )

    resolved = _provider(client).resolve_materialization_capability(
        "flow-project",
        {
            "language": "python",
            "framework": "pytest",
            "artifact_scope_preference": "tests/unit",
        },
    )

    assert client.calls == [
        (
            "codingcastle_capabilities",
            {"group": "tests", "session_id": "coding-session"},
        )
    ]
    assert resolved == {
        "language": "python",
        "framework": "pytest",
        "artifact_scope_preference": "tests/unit",
        "oracle_ir_contract_version": "flow.oracle.ir.v1",
        "operator_profile": "flow.oracle.unit-contract.v1",
        "materializer_version": "codingcastle.oracle-materializer.v1",
        "adapter_version": "codingcastle.oracle-emitter.python-pytest.v1",
    }


def test_materialization_mode_support_does_not_duplicate_provider_profile_registry() -> (
    None
):
    provider = _provider(_Client({}))

    assert provider.supports_materialization_mode(
        ProviderMaterializationMode.DETERMINISTIC_ORACLE_IR,
        {"language": "ruby", "framework": "rspec"},
    )
    assert not provider.supports_materialization_mode(
        ProviderMaterializationMode.DETERMINISTIC_ORACLE_IR,
        {"language": "", "framework": "rspec"},
    )


def test_deterministic_oracle_ir_uses_private_v2_authority_and_closed_receipt() -> None:
    command = _deterministic_command()
    client = _Client(_deterministic_response(command))

    receipt = _provider(client).execute(command)

    tool, arguments = client.calls[0]
    assert tool == "codingcastle_tests"
    assert arguments == {
        "session_id": "coding-session",
        "repository": "service-repo",
        "operation": "materialize",
        "detail_level": "verbose",
    }
    metadata = client.metas[0]
    assert metadata is not None
    assert set(metadata) == {FLOW_TEST_PROVIDER_METADATA_KEY}
    command_payload = metadata[FLOW_TEST_PROVIDER_METADATA_KEY]
    assert command_payload["contract_version"] == "flow.test_provider.command.v2"
    assert command_payload["authority_input"]["oracle_ir"] == command.oracle_ir
    assert command_payload["authority_input_fingerprint"] == (
        command.authority_input_fingerprint
    )
    assert "oracle_ir" not in arguments
    assert "source" not in arguments
    assert receipt.materialization_mode == (
        ProviderMaterializationMode.DETERMINISTIC_ORACLE_IR
    )
    assert receipt.attestation_state.value == "attested_current"
    assert receipt.representation_lineage[0]["source_manifest_digest"] == (
        "rendered-source-manifest"
    )
    assert set(receipt.materialization_evidence) == {
        "oracle_ir_contract_version",
        "operator_profile",
        "materializer_version",
        "adapter_version",
        "semantic_ast_fingerprint",
        "rendered_source_fingerprint",
        "ir_node_lineage",
    }
