"""CodingCastle adapter for Flow's durable test-provider socket."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from flow_of_work_mcp.adapters.implementation_intelligence.mcp_provider import (
    McpToolClient,
    ProviderProjectBindingResolver,
)
from flow_of_work_mcp.core.domain.campaign_authority import (
    CampaignEvidenceDisposition,
    MaterializationAttestationState,
    TEST_PROVIDER_COMMAND_VERSION as FLOW_TEST_PROVIDER_COMMAND_VERSION,
    TEST_PROVIDER_RECEIPT_VERSION as FLOW_TEST_PROVIDER_RECEIPT_VERSION,
    TestProviderCommand,
    TestProviderMaterializationMode,
    TestProviderOperation,
    TestProviderReceipt,
    canonical_materializer_capability,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    ImplementationProviderUnavailableError,
    PacketProviderRejectedError,
)
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind


CODINGCASTLE_TEST_PROVIDER_COMMAND_VERSION = "codingcastle.test.provider-command.v1"
CODINGCASTLE_TEST_PROVIDER_RECEIPT_VERSION = "codingcastle.test.provider-receipt.v1"
FLOW_TEST_PROVIDER_METADATA_KEY = FLOW_TEST_PROVIDER_COMMAND_VERSION


@dataclass(frozen=True)
class CodingCastleTestProjectBinding:
    project_id: str
    provider_session_id: str
    repository: str | int | None = None

    def __post_init__(self) -> None:
        project_id = str(self.project_id or "").strip()
        session_id = str(self.provider_session_id or "").strip()
        if not project_id or not session_id:
            raise ValueError("test provider binding requires project and session")
        if len(session_id) > 256:
            raise ValueError("test provider session exceeds the supported bound")
        if isinstance(self.repository, bool) or (
            self.repository is not None and not isinstance(self.repository, (str, int))
        ):
            raise ValueError(
                "test provider repository must be a display name or number"
            )
        if isinstance(self.repository, str) and not self.repository.strip():
            raise ValueError("test provider repository cannot be blank")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "provider_session_id", session_id)


class McpCodingCastleTestProvider:
    """Map provider-neutral campaign commands to ``codingcastle_tests``."""

    def __init__(
        self,
        *,
        client: McpToolClient,
        bindings: tuple[CodingCastleTestProjectBinding, ...],
        tool_name: str = "codingcastle_tests",
        binding_resolver: ProviderProjectBindingResolver | None = None,
    ) -> None:
        if str(tool_name or "").strip() != "codingcastle_tests":
            raise ValueError("CodingCastle test provider requires codingcastle_tests")
        by_project = {item.project_id: item for item in bindings}
        if len(by_project) != len(bindings):
            raise ValueError("test provider project bindings must be unique")
        self._client = client
        self._bindings = by_project
        self._tool_name = "codingcastle_tests"
        self._binding_resolver = binding_resolver

    @property
    def kind(self) -> str:
        return "codingcastle"

    def session_for_project(self, project_id: str) -> str:
        return self._binding(project_id).provider_session_id

    def supports_materialization_mode(
        self,
        mode: TestProviderMaterializationMode,
        capability: Mapping[str, object],
    ) -> bool:
        if mode == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE:
            return True
        if mode != TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR:
            return False
        try:
            canonical_materializer_capability(capability)
        except ValueError:
            return False
        return True

    def resolve_materialization_capability(
        self,
        project_id: str,
        capability: Mapping[str, object],
    ) -> Mapping[str, object]:
        binding = self._binding(project_id)
        requested = canonical_materializer_capability(capability)
        payload = _unwrap_public_result(
            self._client.call_tool(
                "codingcastle_capabilities",
                {"group": "tests", "session_id": binding.provider_session_id},
            )
        )
        profiles = payload.get("deterministic_materializer_profiles")
        if not isinstance(profiles, list):
            raise ImplementationProviderContractError(
                "test_provider_materialization_capabilities_missing"
            )
        matches = [
            item
            for item in profiles
            if isinstance(item, Mapping)
            and item.get("language") == requested["language"]
            and item.get("framework") == requested["framework"]
        ]
        if len(matches) != 1:
            raise ImplementationProviderContractError(
                "test_provider_materialization_capability_not_exact"
            )
        selected = matches[0]
        resolved: dict[str, object] = dict(requested)
        for field_name in (
            "oracle_ir_contract_version",
            "operator_profile",
            "materializer_version",
            "adapter_version",
        ):
            value = selected.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ImplementationProviderContractError(
                    "test_provider_materialization_capability_incomplete"
                )
            resolved[field_name] = value
        return canonical_materializer_capability(
            resolved,
            require_versions=True,
        )

    def execute(self, command: TestProviderCommand) -> TestProviderReceipt:
        binding = self._binding(command.flow_session_ref)
        arguments = self._public_arguments(binding, command)
        metadata = (
            {FLOW_TEST_PROVIDER_METADATA_KEY: _flow_provider_metadata(command)}
            if command.contract_version == FLOW_TEST_PROVIDER_COMMAND_VERSION
            else {
                CODINGCASTLE_TEST_PROVIDER_COMMAND_VERSION: _provider_metadata(command)
            }
        )
        payload = _unwrap_public_result(
            self._client.call_tool(self._tool_name, arguments, meta=metadata)
        )
        provider_receipt = payload.get("provider_receipt")
        if not isinstance(provider_receipt, Mapping):
            raise ImplementationProviderContractError("test_provider_receipt_missing")
        test = payload.get("test")
        provider_test_ref = ""
        if isinstance(test, Mapping):
            provider_test_ref = str(test.get("ref") or "").strip()
        if not provider_test_ref:
            provider_test_ref = str(
                command.semantic_input.get("provider_test_ref") or ""
            ).strip()
        return _receipt_from_provider_payload(
            provider_receipt,
            command=command,
            provider_test_ref=provider_test_ref,
        )

    def _binding(self, project_id: str) -> CodingCastleTestProjectBinding:
        if self._binding_resolver is not None:
            durable = self._binding_resolver.resolve_provider_binding(
                project_id, ImplementationProviderKind.TEST_EXECUTION
            )
            if durable is not None:
                return CodingCastleTestProjectBinding(
                    project_id=durable.project_id,
                    provider_session_id=durable.provider_context_id,
                    repository=durable.repository,
                )
        binding = self._bindings.get(str(project_id or "").strip())
        if binding is None:
            raise ImplementationProviderUnavailableError(
                "test_provider_project_unbound"
            )
        return binding

    @staticmethod
    def _public_arguments(
        binding: CodingCastleTestProjectBinding,
        command: TestProviderCommand,
    ) -> dict[str, object]:
        semantic = dict(command.semantic_input)
        operation_map = {
            TestProviderOperation.MATERIALIZE: "create",
            TestProviderOperation.EDIT: "edit",
            TestProviderOperation.VALIDATE: "validate",
            TestProviderOperation.RUN: "run",
            TestProviderOperation.PROMOTE: "promote",
            TestProviderOperation.DISCARD: "discard",
            TestProviderOperation.REPORT: "report",
        }
        arguments: dict[str, object] = {
            "session_id": binding.provider_session_id,
            "operation": operation_map[command.operation],
            "detail_level": "audit",
        }
        harness = _harness_input(command.semantic_input)
        if harness["disposition"] == "repository" and binding.repository is not None:
            arguments["repository"] = binding.repository
        if command.operation == TestProviderOperation.MATERIALIZE:
            if (
                command.materialization_mode
                == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR
            ):
                arguments["operation"] = "materialize"
                return arguments
            files = _source_files(semantic)
            if len(files) != 1:
                raise ImplementationProviderContractError(
                    "test_provider_baseline_requires_one_source_file"
                )
            relative_path, source = next(iter(files.items()))
            arguments.update(
                {
                    "relative_path": relative_path,
                    "source": source,
                    "oracle": _codingcastle_oracle(command, semantic),
                }
            )
            _copy_optional_text(semantic, arguments, "language")
            _copy_optional_text(semantic, arguments, "framework")
        elif command.operation == TestProviderOperation.EDIT:
            arguments["test"] = _required_text(
                semantic.get("provider_test_ref"), "provider_test_ref"
            )
            files = _source_files(semantic)
            if len(files) != 1:
                raise ImplementationProviderContractError(
                    "test_provider_baseline_requires_one_source_file"
                )
            arguments["source"] = next(iter(files.values()))
            arguments["oracle"] = _codingcastle_oracle(command, semantic)
            _copy_optional_text(semantic, arguments, "language")
            _copy_optional_text(semantic, arguments, "framework")
        else:
            arguments["test"] = _required_text(
                semantic.get("provider_test_ref"), "provider_test_ref"
            )
            if command.operation == TestProviderOperation.PROMOTE:
                arguments["disposition"] = "accepted"
                arguments["regression_obligation"] = bool(
                    semantic.get("regression_obligation", False)
                )
            elif command.operation == TestProviderOperation.DISCARD:
                arguments["reason"] = _required_text(semantic.get("reason"), "reason")
        return arguments


def _provider_metadata(command: TestProviderCommand) -> dict[str, object]:
    harness = _harness_input(command.semantic_input)
    return {
        "contract_version": CODINGCASTLE_TEST_PROVIDER_COMMAND_VERSION,
        "command_ref": command.command_id,
        "delivery_fingerprint": command.delivery_fingerprint,
        "origin": {
            "session_ref": command.flow_session_ref,
            "campaign_ref": command.campaign_id,
            "case_ref": command.case_id,
        },
        "operation": command.operation.value,
        "oracle": {
            "oracle_ref": command.oracle_id,
            "revision": command.oracle_revision,
            "fingerprint": command.oracle_fingerprint,
        },
        "attestation_intent_ref": command.attestation_intent_ref,
        "source_manifest_digest": command.source_manifest_digest,
        "allowed_materialization_scope": list(
            command.semantic_input.get("allowed_materialization_scope") or []
        ),
        "harness": harness,
    }


def _flow_provider_metadata(command: TestProviderCommand) -> dict[str, object]:
    payload = command.as_payload()
    semantic_input = dict(_mapping(payload.get("semantic_input"), "semantic_input"))
    semantic_input["harness"] = _harness_input(command.semantic_input)
    payload["semantic_input"] = semantic_input
    return payload


def _codingcastle_oracle(
    command: TestProviderCommand, semantic: Mapping[str, object]
) -> dict[str, object]:
    snapshot = semantic.get("oracle_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ImplementationProviderContractError("test_provider_oracle_missing")
    fields = snapshot.get("semantic_fields")
    if not isinstance(fields, Mapping):
        raise ImplementationProviderContractError("test_provider_oracle_fields_missing")
    oracle_kind = _canonical_oracle_kind(
        str(snapshot.get("oracle_kind") or ""),
        semantic,
    )
    subject_bindings = snapshot.get("subject_bindings")
    if not isinstance(subject_bindings, list) or not subject_bindings:
        raise ImplementationProviderContractError(
            "test_provider_oracle_subject_missing"
        )
    return {
        "contract_version": "codingcastle.test_oracle.v1",
        "oracle_id": command.oracle_id,
        "oracle_revision": command.oracle_revision,
        "test_kind": oracle_kind,
        "probe_mode": str(fields.get("probe_mode") or "none"),
        "subject": {
            "bindings": list(subject_bindings),
            "goal_bindings": list(snapshot.get("goal_bindings") or []),
        },
        "preconditions": _as_list(fields.get("preconditions")),
        "stimuli": _as_list(fields.get("stimulus")),
        "input_domains": _as_list(fields.get("input_domain")),
        "expected_outputs": _as_list(fields.get("expected_observations")),
        "invariants": _as_list(fields.get("invariants")),
        "tolerances": _as_list(fields.get("tolerances")),
        "forbidden_effects": _as_list(fields.get("forbidden_effects")),
        "expected_failure_transitions": _as_list(
            fields.get("expected_failure_transitions")
        ),
        "oracle_violation_conditions": _as_list(
            fields.get("oracle_violation_conditions")
        ),
    }


def _receipt_from_provider_payload(
    payload: Mapping[str, object],
    *,
    command: TestProviderCommand,
    provider_test_ref: str,
) -> TestProviderReceipt:
    if command.contract_version == FLOW_TEST_PROVIDER_COMMAND_VERSION:
        try:
            if str(payload.get("contract_version") or "") != (
                FLOW_TEST_PROVIDER_RECEIPT_VERSION
            ):
                raise ImplementationProviderContractError(
                    "test_provider_receipt_version_mismatch"
                )
            receipt = TestProviderReceipt.from_payload(payload)
            if receipt.command_id != command.command_id:
                raise ImplementationProviderContractError(
                    "test_provider_receipt_command_mismatch"
                )
            if (
                receipt.materialization_mode != command.materialization_mode
                or receipt.authority_input_fingerprint
                != command.authority_input_fingerprint
            ):
                raise ImplementationProviderContractError(
                    "test_provider_receipt_authority_mismatch"
                )
            if not receipt.provider_test_ref and provider_test_ref:
                receipt = replace(receipt, provider_test_ref=provider_test_ref)
            return receipt
        except ImplementationProviderContractError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ImplementationProviderContractError(
                "test_provider_receipt_invalid"
            ) from exc
    try:
        if str(payload.get("contract_version") or "") != (
            CODINGCASTLE_TEST_PROVIDER_RECEIPT_VERSION
        ):
            raise ImplementationProviderContractError(
                "test_provider_receipt_version_mismatch"
            )
        oracle = _mapping(payload.get("oracle"), "oracle")
        materialization = _mapping(payload.get("materialization"), "materialization")
        if str(payload.get("command_ref") or "") != command.command_id:
            raise ImplementationProviderContractError(
                "test_provider_receipt_command_mismatch"
            )
        return TestProviderReceipt(
            command_id=command.command_id,
            provider_event_seq=_integer(
                payload.get("provider_event_seq"), "provider_event_seq", minimum=0
            ),
            technical_state=_required_text(
                payload.get("technical_state"), "technical_state"
            ),
            evidence_disposition=CampaignEvidenceDisposition(
                str(payload.get("evidence_disposition") or "")
            ),
            attestation_state=MaterializationAttestationState(
                str(payload.get("attestation_state") or "")
            ),
            oracle_id=str(oracle.get("oracle_ref") or ""),
            oracle_revision=_integer(
                oracle.get("revision"), "oracle.revision", minimum=1
            ),
            oracle_fingerprint=str(oracle.get("fingerprint") or ""),
            source_manifest_digest=str(payload.get("source_manifest_digest") or ""),
            materialization_ref=str(materialization.get("ref") or ""),
            materialization_revision=_integer(
                materialization.get("revision"),
                "materialization.revision",
                minimum=0,
            ),
            representation_fingerprint=str(
                materialization.get("representation_fingerprint") or ""
            ),
            representation_lineage=tuple(
                _mapping(item, "representation_lineage")
                for item in _sequence(
                    materialization.get("representation_lineage") or [],
                    "representation_lineage",
                )
            ),
            evidence_reference=_required_text(
                payload.get("evidence_reference"), "evidence_reference"
            ),
            provider_test_ref=provider_test_ref,
            current=_boolean(payload.get("current"), "current"),
            complete=_boolean(payload.get("complete"), "complete"),
            integrity_preserved=_boolean(
                payload.get("integrity_preserved"), "integrity_preserved"
            ),
            diagnostics=tuple(
                str(item)
                for item in _sequence(payload.get("diagnostics") or [], "diagnostics")
            ),
            next_action=_required_text(payload.get("next_action"), "next_action"),
            materialization_mode=command.materialization_mode,
            authority_input_fingerprint=command.authority_input_fingerprint,
            materialization_evidence={
                "provider_contract_version": str(payload.get("contract_version") or "")
            },
        )
    except ImplementationProviderContractError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ImplementationProviderContractError(
            "test_provider_receipt_invalid"
        ) from exc


def _harness_input(semantic: Mapping[str, object]) -> dict[str, object]:
    raw = semantic.get("harness")
    if raw is None:
        return {"disposition": "repository", "participants": []}
    if not isinstance(raw, Mapping):
        raise ImplementationProviderContractError("test_provider_harness_invalid")
    unknown = sorted(set(raw).difference({"disposition", "participants"}))
    if unknown:
        raise ImplementationProviderContractError("test_provider_harness_field_unknown")
    disposition = str(raw.get("disposition") or "").strip()
    if disposition not in {"repository", "project_integration"}:
        raise ImplementationProviderContractError(
            "test_provider_harness_disposition_invalid"
        )
    participants = raw.get("participants") or []
    if not isinstance(participants, list) or not all(
        isinstance(item, Mapping) for item in participants
    ):
        raise ImplementationProviderContractError(
            "test_provider_harness_participants_invalid"
        )
    if disposition == "repository" and participants:
        raise ImplementationProviderContractError(
            "test_provider_repository_participants_forbidden"
        )
    if disposition == "project_integration" and len(participants) < 2:
        raise ImplementationProviderContractError(
            "test_provider_integration_participants_insufficient"
        )
    return {
        "disposition": disposition,
        "participants": [dict(item) for item in participants],
    }


def _canonical_oracle_kind(
    value: str,
    semantic: Mapping[str, object],
) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "unit_contract": "unit_contract",
        "deterministic_contract": "unit_contract",
        "contract": "unit_contract",
        "behavior": "unit_contract",
        "deterministic": "unit_contract",
        "integration_behavior": "integration_behavior",
        "integration": "integration_behavior",
        "live": "integration_behavior",
        "probe_limit": "probe_limit",
        "probe": "probe_limit",
        "limit": "probe_limit",
        "boundary": "probe_limit",
    }
    selected = aliases.get(normalized)
    if selected is None:
        raise ImplementationProviderContractError("test_provider_oracle_kind_invalid")
    harness = _harness_input(semantic)
    if harness["disposition"] == "project_integration":
        return "integration_behavior"
    return selected


def _unwrap_public_result(payload: Mapping[str, object]) -> Mapping[str, object]:
    current: object = payload
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        status = str(current.get("status") or "").strip().lower()
        result = current.get("result")
        if status and status not in {"ok", "success", "accepted"}:
            detail = result if isinstance(result, Mapping) else current
            reason = str(
                detail.get("reason")
                or current.get("reason")
                or "test_provider_rejected"
            )
            raise PacketProviderRejectedError(reason)
        if isinstance(result, Mapping):
            current = result
            continue
        return current
    raise ImplementationProviderContractError("test_provider_result_invalid")


def _source_files(semantic: Mapping[str, object]) -> dict[str, str]:
    raw = semantic.get("source_files")
    if not isinstance(raw, Mapping) or not raw:
        raise ImplementationProviderContractError("test_provider_source_required")
    result: dict[str, str] = {}
    for path, source in raw.items():
        relative_path = str(path or "").strip().replace("\\", "/")
        if (
            not relative_path
            or relative_path.startswith("/")
            or ".." in relative_path.split("/")
            or not isinstance(source, str)
            or not source.strip()
        ):
            raise ImplementationProviderContractError("test_provider_source_invalid")
        result[relative_path] = source
    return dict(sorted(result.items()))


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _copy_optional_text(
    source: Mapping[str, object], target: dict[str, object], field: str
) -> None:
    value = source.get(field)
    if value is not None and str(value).strip():
        target[field] = str(value).strip()


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ImplementationProviderContractError(f"test_provider_{field}_required")
    return text


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ImplementationProviderContractError(f"test_provider_{field}_invalid")
    return value


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ImplementationProviderContractError(f"test_provider_{field}_invalid")
    return value


def _integer(value: object, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ImplementationProviderContractError(f"test_provider_{field}_invalid")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ImplementationProviderContractError(f"test_provider_{field}_invalid")
    return value


__all__ = [
    "CODINGCASTLE_TEST_PROVIDER_COMMAND_VERSION",
    "CODINGCASTLE_TEST_PROVIDER_RECEIPT_VERSION",
    "FLOW_TEST_PROVIDER_METADATA_KEY",
    "CodingCastleTestProjectBinding",
    "McpCodingCastleTestProvider",
]
