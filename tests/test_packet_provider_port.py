from __future__ import annotations

import json
from copy import deepcopy
from typing import Mapping

import pytest

from flow_of_work_mcp.adapters.implementation_intelligence.packet_provider import (
    CodingCastlePacketProjectBinding,
    McpCodingCastlePacketProvider,
)
from flow_of_work_mcp.application.packet_provider_projection import (
    PacketProviderProjectionService,
)
from flow_of_work_mcp.core.domain.packet_provider import (
    PACKET_PROVIDER_COMMAND_VERSION,
    PacketProviderCommand,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    PacketProviderRejectedError,
)


class _Client:
    def __init__(
        self, responses: Mapping[str, object] | list[Mapping[str, object]]
    ) -> None:
        self.responses = (
            [dict(item) for item in responses]
            if isinstance(responses, list)
            else [dict(responses)]
        )
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
        if tool_name == "codingcastle_packet" and arguments.get("detail_level") not in {
            "minimal", "standard", "verbose"
        }:
            raise ValueError("unknown CodingCastle detail_level")
        if not self.responses:
            raise AssertionError("unexpected provider call")
        response = self.responses.pop(0)
        if tool_name == "codingcastle_packet" and arguments["detail_level"] != "verbose":
            # CC's canonical packet projection omits machine audit at lower levels.
            response = deepcopy(response)
            if isinstance(response.get("result"), dict):
                response["result"].pop("audit", None)
        return response


def _public_receipt(
    *,
    changed: bool = True,
    unit_ref: str = "provider-unit-9",
    unit_number: int = 1,
    choices: list[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    delta = (
        [
            {
                "number": unit_number,
                "state": "ready",
                "client_unit_key": "server-owned-key",
                "unit_ref": unit_ref,
            }
        ]
        if unit_ref
        else []
    )
    return {
        "status": "ok",
        "result": {
            "contract_version": "codingcastle.packet.receipt.v2",
            "packet_state": "ready" if unit_ref else "draft",
            "changed": changed,
            "units": [],
            "units_truncated": False,
            "readiness_gaps": [],
            "readiness_gaps_truncated": False,
            "technical_phase": "idle",
            "current_step": "start" if unit_ref else "add",
            "question": "Choose a target" if choices else None,
            "choices": [dict(item) for item in choices or []],
            "choices_truncated": False,
            "required_input": {"target": "ordinal"} if choices else {},
            "available_actions": ["add", "start", "status"],
            "audit": {
                "packet_ref": "provider-packet-1",
                "packet_revision": 2,
                "binding_epoch": 1,
                "event_seq": 7,
                "job_ref": None,
                "unit_delta": delta,
                "unit_delta_truncated": False,
                "recent_packets": [],
            },
        },
    }


def _provider(client: _Client, *, resolver=None) -> McpCodingCastlePacketProvider:
    return McpCodingCastlePacketProvider(
        client=client,
        bindings=(
            CodingCastlePacketProjectBinding("flow-project", "coding-session"),
        ),
        unit_correlation_resolver=resolver,
    )


def _future_unit() -> dict[str, object]:
    return {
        "kind": "create_file",
        "future_target": {
            "member_label": "app",
            "surface": "workspace",
            "relative_path": "src/config.py",
        },
        "instructions": ["Create the bounded configuration module."],
        "unit_checks": ["The module parses."],
    }


def test_codingcastle_adapter_adds_one_unit_through_public_semantic_tool() -> None:
    client = _Client(_public_receipt())
    provider = _provider(client)
    command = PacketProviderCommand(
        contract_version=PACKET_PROVIDER_COMMAND_VERSION,
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=3,
        flow_unit_ref="unit-1",
        operation="add",
        semantic_input={"unit": _future_unit()},
        delivery_fingerprint="flow:add:unit-1:v3",
    )

    receipt = provider.execute(command)

    assert client.calls == [
        (
            "codingcastle_packet",
            {
                "session_id": "coding-session",
                "operation": "add",
                "detail_level": "verbose",
                "unit": _future_unit(),
            },
        )
    ]
    assert receipt.provider_packet_ref == "provider-packet-1"
    assert receipt.unit_receipts[0].flow_unit_ref == "unit-1"
    assert receipt.unit_receipts[0].provider_unit_ref == "provider-unit-9"
    assert receipt.unit_receipts[0].unit_number == 1
    assert client.metas == [None]


@pytest.mark.parametrize("operation", ["add", "edit", "remove", "start", "stop", "status"])
def test_every_packet_operation_retains_required_machine_audit(operation: str) -> None:
    client = _Client(_public_receipt())
    provider = _provider(client, resolver=lambda *_: {
        "provider_unit_ref": "provider-unit-9", "unit_number": 1,
    })
    semantic = ({"unit": _future_unit()} if operation == "add" else
                {"changes": {"instructions": ["Keep the module typed."]}} if operation == "edit" else {})
    command = PacketProviderCommand(
        flow_session_ref="flow-project", flow_packet_ref="PACKET-000001",
        flow_spec_revision=3, operation=operation,
        flow_unit_ref="unit-1" if operation in {"add", "edit", "remove"} else "",
        semantic_input=semantic, delivery_fingerprint="profile-" + operation,
    )
    receipt = provider.execute(command)
    assert client.calls[0][1]["detail_level"] == "verbose"
    assert len(client.calls) == 1  # No invalid-profile retry or fallback.
    assert receipt.provider_packet_ref == "provider-packet-1"
    assert receipt.provider_packet_revision == 2
    assert receipt.event_seq == 7


def test_transient_target_choices_are_not_persisted_as_provider_authority() -> None:
    choice = {"ordinal": 1, "label": "Service.run", "kind": "function"}
    provider = _provider(_Client(_public_receipt(unit_ref="", choices=[choice])))
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=3,
        operation="add",
        semantic_input={},
        delivery_fingerprint="flow:preview:unit-1:v3",
    )

    receipt = provider.execute(command)

    assert receipt.decision["choices"] == [choice]
    persisted = receipt.persisted_payload()
    assert "choices" not in persisted
    assert "Service.run" not in json.dumps(persisted, sort_keys=True)


@pytest.mark.parametrize("current_step", ["navigate", "choose_target"])
def test_no_effect_target_scaffold_precedes_inventory_correlation(
    current_step: str,
) -> None:
    payload = _public_receipt(changed=False)
    result = payload["result"]
    assert isinstance(result, dict)
    result["current_step"] = current_step
    audit = result["audit"]
    assert isinstance(audit, dict)
    audit["unit_delta"] = [
        {
            "number": number,
            "state": "ready",
            "client_unit_key": f"server-owned-key-{number}",
            "unit_ref": f"provider-unit-{number}",
        }
        for number in range(1, 6)
    ]
    client = _Client(payload)
    provider = _provider(client)
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=3,
        flow_unit_ref="flow-unit-6",
        operation="add",
        semantic_input={
            "unit": {
                "kind": "modify_existing",
                "instructions": ["Update the bounded runtime behavior."],
                "unit_checks": ["The runtime behavior remains typed."],
            },
            "target": {"mutation": 1, "context": []},
        },
        delivery_fingerprint="flow:add:unit-6:v3",
    )

    with pytest.raises(PacketProviderRejectedError) as error:
        provider.execute(command)

    assert error.value.reason == "packet_provider_target_selection_required"
    assert len(client.calls) == 1


def test_edit_resolves_internal_provider_identity_to_human_unit_number() -> None:
    client = _Client(_public_receipt(unit_ref="provider-unit-9"))
    provider = _provider(
        client,
        resolver=lambda *_: {
            "provider_unit_ref": "provider-unit-9",
            "unit_number": 1,
        },
    )
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=4,
        flow_unit_ref="flow-unit-1",
        operation="edit",
        semantic_input={
            "changes": {"instructions": ["Keep the configuration typed."]}
        },
        delivery_fingerprint="flow:edit:unit-1:v4",
    )

    provider.execute(command)

    assert client.calls == [
        (
            "codingcastle_packet",
            {
                "session_id": "coding-session",
                "operation": "edit",
                "detail_level": "verbose",
                "unit_number": 1,
                "changes": {
                    "instructions": ["Keep the configuration typed."]
                },
            },
        ),
    ]
    assert client.metas == [
        {
            "codingcastle.packet.provider-correlation.v1": {
                "selected": {
                    "provider_unit_ref": "provider-unit-9",
                    "unit_number": 1,
                }
            }
        }
    ]


def test_flow_dependency_refs_are_translated_to_packet_local_numbers() -> None:
    client = _Client(_public_receipt(unit_ref="provider-unit-10", unit_number=3))
    provider = _provider(
        client,
        resolver=lambda *_: {
            "provider_unit_ref": "provider-dependency",
            "unit_number": 2,
        },
    )
    unit = _future_unit()
    unit["depends_on"] = ["flow-dependency"]
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=4,
        flow_unit_ref="flow-unit-2",
        operation="add",
        semantic_input={"unit": unit},
        delivery_fingerprint="flow:add:unit-2:v4",
    )

    provider.execute(command)

    assert client.calls == [
        (
            "codingcastle_packet",
            {
                "session_id": "coding-session",
                "operation": "add",
                "detail_level": "verbose",
                "unit": {**unit, "depends_on": [2]},
            },
        )
    ]
    assert client.metas == [
        {
            "codingcastle.packet.provider-correlation.v1": {
                "dependencies": [
                    {
                        "provider_unit_ref": "provider-dependency",
                        "unit_number": 2,
                    }
                ]
            }
        }
    ]


def test_missing_persisted_unit_number_fails_before_provider_call() -> None:
    client = _Client(_public_receipt())
    provider = _provider(
        client,
        resolver=lambda *_: {
            "provider_unit_ref": "provider-unit-9",
            "unit_number": None,
        },
    )
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=4,
        flow_unit_ref="flow-unit-1",
        operation="remove",
        delivery_fingerprint="flow:remove:unit-1:v4",
    )

    with pytest.raises(
        ImplementationProviderContractError,
        match="packet_provider_unit_number_unresolved",
    ):
        provider.execute(command)

    assert client.calls == []


def test_command_rejects_graph_identity_and_flow_bureaucracy() -> None:
    for forbidden in ("chunk_id", "graph_revision", "requirement_ids", "rationale"):
        with pytest.raises(ValueError, match="forbidden authority"):
            PacketProviderCommand(
                flow_session_ref="flow-project",
                flow_packet_ref="PACKET-000001",
                flow_spec_revision=1,
                operation="add",
                semantic_input={"unit": {forbidden: "not-authorized"}},
                delivery_fingerprint="flow:forbidden:test",
            )


def test_provider_rejection_preserves_bounded_reason() -> None:
    provider = _provider(
        _Client(
            {
                "status": "blocked",
                "result": {"reason": "packet_state_conflict"},
            }
        )
    )
    command = PacketProviderCommand(
        flow_session_ref="flow-project",
        flow_packet_ref="PACKET-000001",
        flow_spec_revision=1,
        operation="start",
        delivery_fingerprint="flow:start:v1",
    )

    with pytest.raises(PacketProviderRejectedError) as error:
        provider.execute(command)
    assert error.value.reason == "packet_state_conflict"


def test_agnostic_projection_is_complete_without_fabricated_provider_truth() -> None:
    service = PacketProviderProjectionService(mode="agnostic")

    capability = service.capability("flow-project")
    assert capability["state"] == "agnostic"
    assert capability["health"] == "not_applicable"

    projection = service.portable_packet(
        project_id="flow-project",
        change_id="CHANGE-000001",
        packet={
            "packet_id": "PACKET-000001",
            "spec_revision": 3,
            "purpose": "implementation",
            "title": "Add configuration",
            "objective": "Create the configuration boundary.",
            "rationale": "Keep process control deterministic.",
            "completion_criteria": ["The module parses."],
            "in_scope": ["configuration"],
            "out_of_scope": ["UI"],
            "invariants": ["No process side effects."],
            "requirement_ids": ["REQ-000001"],
            "goal_ids": ["GOAL-000001"],
        },
        work_plan={
            "units": [
                {
                    "client_unit_key": "create-config",
                    "operation_kind": "new_file",
                    "file_path": "src/config.py",
                    "surface": "workspace",
                    "instructions": ["Create the typed configuration module."],
                    "unit_checks": ["The module parses."],
                }
            ]
        },
    )

    assert projection["execution_disposition"] == "provider_pending"
    assert projection["technical_execution_claimed"] is False
    assert projection["units"][0]["target"] == {
        "kind": "future_path",
        "relative_path": "src/config.py",
        "member_label": "",
        "surface": "workspace",
    }
    encoded = json.dumps(projection, sort_keys=True)
    for forbidden in (
        "provider_packet_ref",
        "graph_revision",
        "chunk_id",
        "target_set_id",
    ):
        assert forbidden not in encoded
