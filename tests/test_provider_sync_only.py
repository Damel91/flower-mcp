"""Explicit synchronization delivers provider deltas without crossing START."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import sqlite3
from types import SimpleNamespace

import pytest

from flow_of_work_mcp import SQLiteRequirementLedger
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.packet_executor import PacketExecutorService
from flow_of_work_mcp.application.packet_provider_overlay import PacketProviderOverlayService
from flow_of_work_mcp.application.packet_provider_projection import PacketProviderProjectionService
from flow_of_work_mcp.application.packet_provider_socket import PacketProviderSocketService
from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand, PacketProviderUnitReceipt
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ImplementationProviderUnavailableError
from flow_of_work_mcp.server import create_app, handle_packet_advance, handle_packet_author
from tests.test_packet_executor import fixture, select
from tests.test_provider_validation_delivery import (
    drift, setup, unit_command, upstream_coordinator,
)
from tests.provider_sync_fixtures import (
    _PacketProvider, _RejectUnitOnceProvider, _author_unit, _close_semantic_gates,
    _packet_and_plan, _seed_packet,
)


def _tables(ledger):
    """Capture every persisted table, including sequence and receipt metadata."""
    with sqlite3.connect(ledger.database_path) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )]
        return {name: sorted(connection.execute(
            'SELECT * FROM "' + name.replace('"', '""') + '"'
        ).fetchall(), key=repr) for name in names}


def _advance(ledger, overlay, ids, *, request="sync", mode="sync_only", decision=None):
    packet = next(p for p in ledger.change_state(*ids[:2])["packets"] if p["packet_id"] == ids[2])
    return overlay.advance(*ids, packet=packet, work_plan=ledger.packet_work_plan_state(*ids),
                           actor="engineer", request_id=request, mode=mode, decision=decision)


def _unreachable_runtime():
    def forbidden(*args, **kwargs):
        pytest.fail("request validation happened after address resolution or lifecycle repair")
    return SimpleNamespace(changes=SimpleNamespace(get_change=forbidden),
                           packet_factory=SimpleNamespace(ensure_packet_lifecycle=forbidden))


def _assert_start_boundary(result, *, provider_state="ready", public=False):
    assert result["mode"] == "sync_only"
    assert result["state"] == "provider_synchronized"
    assert result["reason"] == "sync_only_start_boundary"
    assert result["provider"]["binding"]["provider_state"] == provider_state
    if public:
        action = result["next_action"]
        assert action["tool"] == "fow_packet_advance"
        assert action["arguments"]["mode"] == "advance"
        assert action["continuation_policy"] == "return_to_model"
        assert action["decision_class"] == "semantic"


def _restart(ledger, provider):
    restarted = SQLiteRequirementLedger(ledger.database_path)
    executor = PacketExecutorService(restarted, provider=provider,
        semantic_projection=ExternalWorkService(restarted).provider_validation)
    external = ExternalWorkService(restarted, packet_executor=executor)
    socket = PacketProviderSocketService(restarted, mode="required", provider=provider, executor=executor)
    overlay = PacketProviderOverlayService(restarted, socket=socket,
        projection=PacketProviderProjectionService(mode="required", provider=provider),
        external_work=external, executor=executor)
    return restarted, external, executor, socket, overlay


def test_negotiated_sync_delivers_complete_context_and_stops_before_start(tmp_path):
    ledger, _external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    result = _advance(ledger, overlay, ids)
    _assert_start_boundary(result)
    assert [command.operation.value for command in provider.commands] == ["add", "add", "add"]
    assert all(row["state"] == "delivered" for row in ledger.packet_provider_outbox_entries(*ids))
    consumer = next(command for command in provider.commands if command.flow_unit_ref == "consumer")
    assert consumer.validation_context["units"][1]["resolved_requires"][0]["contract"]["symbol"] == "a"
    assert consumer.validation_context["units"][0]["deferred_verification"][0]["kind"] == "live_campaign"
    assert "Run the installed CLI." not in str(consumer.semantic_input)
    assert ledger.change_state(*ids[:2])["packets"][0]["status"] == "planned"


def test_repeated_and_restarted_sync_does_not_persist_an_execution_mode(tmp_path):
    ledger, _external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    _assert_start_boundary(_advance(ledger, overlay, ids))
    commands = list(provider.commands)
    before = _tables(ledger)
    _assert_start_boundary(_advance(ledger, overlay, ids, request="repeat-sync"))
    assert provider.commands == commands
    assert _tables(ledger) == before
    restarted, _external, _executor, _socket, resumed = _restart(ledger, provider)
    _assert_start_boundary(_advance(restarted, resumed, ids, request="restart-sync"))
    assert provider.commands == commands
    result = _advance(restarted, resumed, ids, request="explicit-advance", mode="advance")
    assert result["state"] == "provider_running"
    assert [command.operation.value for command in provider.commands[len(commands):]] == ["start", "status"]


def test_omitted_mode_preserves_existing_automatic_start(tmp_path):
    ledger, _external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    packet = ledger.change_state(*ids[:2])["packets"][0]
    result = overlay.advance(*ids, packet=packet, work_plan=ledger.packet_work_plan_state(*ids),
                            actor="engineer", request_id="existing-default")
    assert result["state"] == "provider_running"
    assert [command.operation.value for command in provider.commands] == ["add", "add", "add", "start", "status"]


def test_sync_coordinator_does_not_derive_or_consume_regular_lifecycle_gates(tmp_path, monkeypatch):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    def forbidden(*args, **kwargs):
        pytest.fail("sync_only entered the ordinary lifecycle advancement loop")
    monkeypatch.setattr(coordinator, "_run_mechanical_operation", forbidden)
    monkeypatch.setattr(coordinator, "_consume_decision", forbidden)
    before = _tables(ledger)
    audit = ledger.packet_construction_audit_for_packet(*ids)
    pressure = ledger.latest_packet_pressure(*ids)
    result = coordinator.advance(*ids, actor="engineer", request_id="coordinated-sync", mode="sync_only")
    assert result["mode"] == "sync_only"
    assert result["decision"]["next_operation"] == "derive_engineering_questions"
    assert result["next_action"]["arguments"]["mode"] == "advance"
    assert result["next_action"]["continuation_policy"] == "return_to_model"
    assert _tables(ledger) == before
    assert ledger.packet_construction_audit_for_packet(*ids) == audit
    assert ledger.latest_packet_pressure(*ids) == pressure
    assert provider.commands == []


@pytest.mark.parametrize("operation", ["start", "stop"])
@pytest.mark.parametrize("state", ["pending", "delivering", "unknown", "rejected"])
def test_sync_holds_existing_controls_without_replay_retry_or_any_ledger_write(tmp_path, operation, state):
    ledger, _external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    _advance(ledger, overlay, ids, request="synchronize-before-control")
    command = PacketProviderCommand(ids[0], ids[2], revs["expected_spec_revision"], operation,
        delivery_fingerprint="existing-control", **socket.validation_fields(*ids, operation=operation))
    entry = socket.submit(*ids, command=command, actor="engineer", deliver=False)["outbox"]
    outbox_id = entry["outbox_id"]
    if state in {"delivering", "unknown"}:
        ledger.claim_packet_provider_command(ids[0], outbox_id)
    if state == "unknown":
        ledger.mark_packet_provider_command_unknown(ids[0], outbox_id, reason="transport_state_unknown")
    elif state == "rejected":
        ledger.reject_packet_provider_command(ids[0], outbox_id, reason="provider_control_rejected")
    # A later queued delta cannot jump ahead of the unresolved control.
    ledger.enqueue_packet_provider_command(*ids, provider_kind=provider.kind,
        command=unit_command(executor, ids, revs, key="later-delta"), actor="engineer")
    expected = ledger.packet_provider_outbox_entry(ids[0], outbox_id)
    before = _tables(ledger)
    commands = list(provider.commands)
    decision = ({"operation": "retry_provider_rejection", "rationale": "An explicit retry remains forbidden for a control."}
                if state == "rejected" else None)
    result = _advance(ledger, overlay, ids, request="hold-control", decision=decision)
    assert result["mode"] == "sync_only"
    assert result["state"] == "provider_control_pending"
    assert result["reason"] == "sync_only_control_pending"
    assert result["pending_control"] == {key: expected[key] for key in (
        "outbox_id", "operation", "state", "delivery_fingerprint", "attempts", "last_error")}
    assert provider.commands == commands
    assert _tables(ledger) == before


def test_sync_returns_stopped_boundary_without_resuming_run(tmp_path):
    ledger, _external, _executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    _advance(ledger, overlay, ids)
    stop = PacketProviderCommand(ids[0], ids[2], revs["expected_spec_revision"], "stop",
        delivery_fingerprint="explicit-stop", **socket.validation_fields(*ids, operation="stop"))
    socket.submit(*ids, command=stop, actor="engineer")
    before = _tables(ledger)
    commands = list(provider.commands)
    _assert_start_boundary(_advance(ledger, overlay, ids, request="sync-stopped"), provider_state="stopped")
    assert provider.commands == commands
    assert _tables(ledger) == before


def test_sync_fresh_status_settles_running_to_stopped_without_restarting(tmp_path):
    ledger, _external, executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    _advance(ledger, overlay, ids, request="synchronize-before-run")
    assert _advance(ledger, overlay, ids, request="explicit-start", mode="advance")["state"] == "provider_running"
    frozen = executor.frozen_context(*ids)
    provider.state, provider.phase = "stopped", "stopped"
    before = len(provider.commands)
    authority = deepcopy(ledger.change_state(*ids[:2]))
    result = _advance(ledger, overlay, ids, request="observe-stopped-run")
    _assert_start_boundary(result, provider_state="stopped")
    assert len(provider.commands) == before + 1
    assert provider.commands[-1].operation.value == "status"
    assert provider.commands[-1].validation_context == frozen
    assert ledger.change_state(*ids[:2]) == authority


def test_sync_recovers_exact_unknown_delta_then_returns_current_gate_after_drift(tmp_path):
    ledger, _external, executor, provider, socket, _overlay, ids, revs = setup(tmp_path)
    original = unit_command(executor, ids, revs)
    provider.timeout_once = True
    result = socket.submit(*ids, command=original, actor="engineer")
    assert result["state"] == "provider_unknown"
    drift(ledger, ids)
    restarted, _external, _executor, _socket, resumed = _restart(ledger, provider)
    before = deepcopy(restarted.change_state(*ids[:2]))
    _guards, coordinator = upstream_coordinator(restarted, _external, resumed)
    result = coordinator.advance(*ids, actor="engineer", request_id="recover-old-draft", mode="sync_only")
    assert provider.commands == [original, original]
    assert restarted.packet_provider_outbox_entries(*ids)[0]["state"] == "delivered"
    assert result["mode"] == "sync_only"
    assert result["next_action"]["arguments"]["mode"] == "advance"
    assert result["next_action"]["continuation_policy"] == "return_to_model"
    assert restarted.change_state(*ids[:2]) == before


def test_sync_unknown_draft_returns_before_retry_and_next_explicit_sync_recovers(tmp_path):
    ledger, _external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    provider.timeout_once = True
    unknown = _advance(ledger, overlay, ids, request="first-unknown-draft")
    assert unknown["state"] == "provider_unknown"
    assert unknown["mode"] == "sync_only"
    assert len(provider.commands) == 1
    original = provider.commands[0]
    assert original.operation.value == "add" and not original.flow_unit_ref
    assert ledger.packet_provider_outbox_entries(*ids)[0]["state"] == "unknown"
    recovered = _advance(ledger, overlay, ids, request="explicit-recover-draft")
    _assert_start_boundary(recovered)
    assert provider.commands[:2] == [original, original]
    assert all(command.operation.value not in {"start", "stop"} for command in provider.commands)


@pytest.mark.parametrize("ack_mode", ["missing", "mismatch"])
def test_sync_bad_ack_remains_unknown_and_never_reaches_start(tmp_path, ack_mode):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    provider.ack_mode = ack_mode
    result = _advance(ledger, overlay, ids)
    assert result["state"] == "provider_unknown"
    assert len(provider.commands) == 1
    assert provider.commands[0].operation.value == "add"
    assert ledger.packet_provider_outbox_entries(*ids)[0]["state"] == "unknown"
    assert ledger.packet_provider_receipts(*ids) == []
    drift(ledger, ids)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    resumed = coordinator.advance(*ids, actor="engineer", request_id="bad-ack-continuation", mode="sync_only")
    assert resumed["mode"] == "sync_only"
    assert resumed["state"] == "provider_unknown"
    assert resumed["next_action"]["arguments"]["mode"] == "sync_only"
    assert all(command == provider.commands[0] for command in provider.commands)


@pytest.mark.parametrize("mode", ["", "SYNC_ONLY", "sync-only", None, True, "start"])
def test_invalid_mode_fails_before_any_provider_or_ledger_effect(tmp_path, mode):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    with pytest.raises(ValueError):
        coordinator.advance(*ids, actor="engineer", request_id="invalid-mode", mode=mode)
    with pytest.raises(ValueError):
        _advance(ledger, overlay, ids, mode=mode)
    # Validation precedes even address resolution and factory access.
    with pytest.raises(ValueError):
        handle_packet_advance(_unreachable_runtime(), project_id=ids[0], change_id=ids[1], packet_id=ids[2],
                              actor="engineer", request_id="invalid-public-mode", mode=mode)
    assert provider.commands == []
    assert _tables(ledger) == before


@pytest.mark.parametrize("decision", [
    {"operation": "start_provider_packet"}, {"operation": "stop_provider_packet"},
    {"_force_provider_start": True}, {"_force_provider_stop": False},
    {"operation": "accept_work_plan", "rationale": "No implicit acceptance."},
    {"operation": "accept_residual_risk", "accepted_risk_ref": "test:unrequested"},
    {"unexpected": True},
])
def test_sync_rejects_control_flags_and_non_provider_decisions_before_effects(tmp_path, decision):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    with pytest.raises((ValueError, ChangeControlBlockedError)):
        coordinator.advance(*ids, actor="engineer", request_id="invalid-decision", mode="sync_only", decision=decision)
    with pytest.raises((ValueError, ChangeControlBlockedError)):
        _advance(ledger, overlay, ids, decision=decision)
    with pytest.raises((ValueError, ChangeControlBlockedError)):
        handle_packet_advance(_unreachable_runtime(), project_id=ids[0], change_id=ids[1], packet_id=ids[2],
                              actor="engineer", request_id="invalid-public-decision", mode="sync_only", decision=decision)
    assert provider.commands == []
    assert _tables(ledger) == before


def test_sync_rejects_stale_expected_revision_before_any_effect(tmp_path):
    ledger, external, _executor, provider, _socket, overlay, ids, revs = setup(tmp_path)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    with pytest.raises(ChangeControlBlockedError, match="stale_packet_revision"):
        coordinator.advance(*ids, actor="engineer", request_id="stale-sync", mode="sync_only",
                            expected_spec_revision=revs["expected_spec_revision"] + 1,
                            expected_plan_revision=revs["expected_plan_revision"])
    assert provider.commands == []
    assert _tables(ledger) == before


def test_sync_unnegotiated_provider_does_not_autonegotiate_or_prepare_gates(tmp_path):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path, negotiated=False)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    result = coordinator.advance(*ids, actor="engineer", request_id="unnegotiated-sync", mode="sync_only")
    assert result["mode"] == "sync_only"
    assert result["next_action"]["tool"] in {"fow_external_work", "fow_packet_advance", "fow_packet_author"}
    assert provider.commands == []
    assert provider.capability_provider.calls == 0
    assert _tables(ledger) == before


def test_sync_does_not_transfer_external_agent_ownership(tmp_path):
    ledger, external, executor, capability, ids, revs = fixture(tmp_path)
    select(executor, ids, revs, executor="external_agent")
    socket = PacketProviderSocketService(ledger, mode="required", provider=capability, executor=executor)
    overlay = PacketProviderOverlayService(ledger, socket=socket,
        projection=PacketProviderProjectionService(mode="required", provider=capability),
        external_work=external, executor=executor)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    result = coordinator.advance(*ids, actor="engineer", request_id="external-sync", mode="sync_only")
    assert result["mode"] == "sync_only"
    with pytest.raises(ChangeControlBlockedError, match="external_agent_mode_provider_execution_prohibited"):
        _advance(ledger, overlay, ids, request="direct-external-sync")
    assert capability.calls == 0
    assert _tables(ledger) == before


def test_sync_completed_provider_remains_complete_and_never_freshly_mutates(tmp_path):
    ledger, _external, _executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    _advance(ledger, overlay, ids)
    provider.state, provider.phase = "completed", "completed"
    socket.observe_status(*ids, flow_spec_revision=revs["expected_spec_revision"], actor="engineer")
    before = _tables(ledger)
    commands = list(provider.commands)
    result = _advance(ledger, overlay, ids, request="completed-sync")
    assert result["state"] == "provider_technically_complete"
    assert provider.commands == commands
    assert _tables(ledger) == before


def test_public_sync_skips_lifecycle_repair_and_aligns_top_level_action(tmp_path, monkeypatch):
    provider = _PacketProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "created", "operation_kind": "new_file",
            "file_path": "src/created.py", "instructions": ["Create the bounded output."],
            "unit_checks": ["The output parses."]}, "author-created")
        _close_semantic_gates(runtime, change_id, packet_id)
        def forbidden(*args, **kwargs):
            pytest.fail("sync_only called lifecycle repair")
        monkeypatch.setattr(runtime.packet_factory, "ensure_packet_lifecycle", forbidden)
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="public-sync", mode="sync_only")["result"]
        _assert_start_boundary(result["advancement"], public=True)
        assert result["next_action"] == result["advancement"]["next_action"]
        assert all(command.operation.value != "start" for command in provider.commands)
    finally:
        runtime.close()


def test_public_tool_schema_exposes_explicit_mode_with_backward_compatible_default(tmp_path):
    runtime, _change_id, _packet_id, _started = _seed_packet(tmp_path, mode="agnostic")
    try:
        tool = next(tool for tool in asyncio.run(create_app(runtime).list_tools()) if tool.name == "fow_packet_advance")
        schema = tool.inputSchema
        assert schema["properties"]["mode"]["enum"] == ["advance", "sync_only"]
        assert schema["properties"]["mode"]["default"] == "advance"
        assert "mode" not in schema["required"]
    finally:
        runtime.close()


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_public_sync_control_hold_has_read_only_matching_continuations(tmp_path, operation):
    provider = _PacketProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "created", "operation_kind": "new_file",
            "file_path": "src/created.py", "instructions": ["Create the bounded output."],
            "unit_checks": ["The output parses."]}, "author-created")
        _close_semantic_gates(runtime, change_id, packet_id)
        handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-before-control", mode="sync_only")
        packet, _plan = _packet_and_plan(runtime, change_id, packet_id)
        command = PacketProviderCommand("alpha", packet_id, packet["spec_revision"], operation,
            delivery_fingerprint="public-held-control")
        runtime.packet_provider_socket.submit("alpha", change_id, packet_id,
            command=command, actor="engineer", deliver=False)
        commands = list(provider.commands)
        before = _tables(runtime.ledger)
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="hold-public-control", mode="sync_only")["result"]
        assert result["advancement"]["state"] == "provider_control_pending"
        assert result["next_action"] == result["advancement"]["next_action"]
        assert result["next_action"]["tool"] == "fow_packet_inspect"
        assert result["next_action"]["arguments"]["view"] == "gates"
        assert result["next_action"]["continuation_policy"] == "return_to_model"
        assert provider.commands == commands
        assert _tables(runtime.ledger) == before
    finally:
        runtime.close()


class _DeltaProvider(_PacketProvider):
    """Preserve the removed unit ordinal in this provider fixture's receipt."""

    def _execute(self, command):
        if command.operation.value != "remove":
            return super()._execute(command)
        key = command.flow_unit_ref
        ordinal = tuple(self.units).index(key) + 1
        provider_ref = self.units.pop(key)
        self.revision += 1
        self.event_seq += 1
        self.packet_state = "ready" if self.units else "draft"
        return replace(self._receipt(changed=True, include_all_units=True),
            unit_receipts=(PacketProviderUnitReceipt(key, provider_ref, "removed", ordinal),))


def test_public_sync_delivers_authored_edit_and_remove_before_first_start(tmp_path):
    provider = _DeltaProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider)
    try:
        for key in ("kept", "removed"):
            _author_unit(runtime, packet_id, {"client_unit_key": key, "operation_kind": "new_file",
                "file_path": f"src/{key}.py", "instructions": [f"Create {key}."],
                "unit_checks": [f"The {key} module parses."]}, f"author-{key}")
        _close_semantic_gates(runtime, change_id, packet_id)
        first = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-original", mode="sync_only")["result"]
        _assert_start_boundary(first["advancement"], public=True)
        for operation, key, patch in (("revise_unit", "kept", {"instructions": ["Create the revised kept module."]}),
                                      ("remove_unit", "removed", None)):
            packet, plan = _packet_and_plan(runtime, change_id, packet_id)
            handle_packet_author(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
                operation=operation, client_unit_key=key, unit_patch=patch,
                expected_spec_revision=packet["spec_revision"], expected_plan_revision=plan["plan_revision"],
                actor="engineer", request_id="author-" + operation)
        packet, plan = _packet_and_plan(runtime, change_id, packet_id)
        runtime.packet_work_plan.accept("alpha", change_id, packet_id,
            plan_revision=plan["plan_revision"], expected_packet_revision=packet["spec_revision"],
            expected_current_plan_revision=plan["plan_revision"], rationale="Bounded delta plan reviewed.",
            actor="engineer", request_id="accept-delta-plan")
        pressure = runtime.packet_pressure.derive("alpha", change_id, packet_id,
            actor="engineer", request_id="derive-delta-pressure")
        if pressure.get("residual_risks"):
            runtime.packet_pressure.accept_risk("alpha", pressure["pressure_id"],
                accepted_risk_ref="test:accepted-delta-risk", actor="engineer", request_id="accept-delta-pressure")
        runtime.external_work.call("alpha", change_id, packet_id, "negotiate_provider",
            payload={"expected_spec_revision": packet["spec_revision"], "expected_plan_revision": plan["plan_revision"]},
            actor="engineer", request_id="negotiate-delta-plan")
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-deltas", mode="sync_only")["result"]
        _assert_start_boundary(result["advancement"], public=True)
        assert result["next_action"] == result["advancement"]["next_action"]
        operations = [command.operation.value for command in provider.commands]
        assert "edit" in operations and "remove" in operations
        assert "start" not in operations and "stop" not in operations
        assert set(provider.units) == {"kept"}
        edit = next(command for command in reversed(provider.commands) if command.operation.value == "edit")
        assert edit.semantic_input["changes"]["instructions"] == ["Create the revised kept module."]
        assert not runtime.ledger.packet_provider_recoverable_commands("alpha", change_id=change_id, packet_id=packet_id)
    finally:
        runtime.close()


def test_sync_target_choice_and_explicit_delta_retry_preserve_sync_mode(tmp_path):
    provider = _RejectUnitOnceProvider(reason="packet_provider_target_selection_required", offer_choices=True)
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "service", "operation_kind": "modify_existing",
            "target_description": "the public Service.run method", "instructions": ["Return the bounded service result."],
            "unit_checks": ["The public result remains typed."], "surface": "repo"}, "author-service")
        packet, plan = _packet_and_plan(runtime, change_id, packet_id)
        def call(request, decision=None):
            return runtime.packet_provider_overlay.advance("alpha", change_id, packet_id,
                packet=packet, work_plan=plan, actor="engineer", request_id=request,
                decision=decision, mode="sync_only")
        question = call("target-question")
        assert question["state"] == "needs_provider_target_selection"
        rejected = call("target-answer", {"target": {"mutation": 1, "context": [2]}})
        assert rejected["state"] == "provider_rejected"
        resolved = call("retry-delta", {"operation": "retry_provider_rejection",
            "rationale": "The current target has been confirmed.", "target": {"mutation": 1, "context": [2]}})
        _assert_start_boundary(resolved)
        assert all(command.operation.value not in {"start", "stop"} for command in provider.commands)
    finally:
        runtime.close()


def test_sync_current_authority_gap_does_not_investigate_or_fill_it_implicitly(tmp_path):
    ledger, external, _executor, provider, _socket, overlay, ids, _revs = setup(tmp_path)
    drift(ledger, ids)
    _guards, coordinator = upstream_coordinator(ledger, external, overlay)
    before = _tables(ledger)
    result = coordinator.advance(*ids, actor="engineer", request_id="stale-authority-sync", mode="sync_only")
    assert result["mode"] == "sync_only"
    assert result["next_action"]["arguments"]["mode"] == "advance"
    assert result["next_action"]["continuation_policy"] == "return_to_model"
    assert provider.commands == []
    assert _tables(ledger) == before


class _UnavailableDraftProvider(_PacketProvider):
    def execute(self, command):
        if command.operation.value == "add" and not command.flow_unit_ref:
            self.commands.append(command)
            raise ImplementationProviderUnavailableError("implementation_provider_transport_unavailable")
        return super().execute(command)


def test_sync_legacy_unavailable_draft_returns_after_one_transport_attempt(tmp_path):
    provider = _UnavailableDraftProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "created", "operation_kind": "new_file",
            "file_path": "src/created.py", "instructions": ["Create the bounded output."],
            "unit_checks": ["The output parses."]}, "author-created")
        _close_semantic_gates(runtime, change_id, packet_id)
        before = _tables(runtime.ledger)
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="unavailable-draft", mode="sync_only")["result"]
        assert result["advancement"]["state"] == "provider_unavailable"
        assert result["advancement"]["mode"] == "sync_only"
        assert len(provider.commands) == 1
        assert provider.commands[0].operation.value == "add" and not provider.commands[0].flow_unit_ref
        assert result["next_action"]["arguments"]["mode"] == "sync_only"
        assert _tables(runtime.ledger) == before
    finally:
        runtime.close()


def test_public_sync_retry_target_boundary_preserves_required_target_input(tmp_path):
    provider = _RejectUnitOnceProvider(reason="packet_provider_target_selection_required", offer_choices=True)
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "service", "operation_kind": "modify_existing",
            "target_description": "the public Service.run method", "instructions": ["Return the bounded service result."],
            "unit_checks": ["The public result remains typed."], "surface": "repo"}, "author-service")
        _close_semantic_gates(runtime, change_id, packet_id)
        def call(request, decision=None):
            return handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
                actor="engineer", request_id=request, mode="sync_only", decision=decision)["result"]
        assert call("choose-target")["advancement"]["state"] == "needs_provider_target_selection"
        assert call("target-rejected", {"target": {"mutation": 1, "context": [2]}})["advancement"]["state"] == "provider_rejected"
        result = call("retry-needs-target", {"operation": "retry_provider_rejection",
            "rationale": "The rejected target needs a fresh current selection."})
        assert result["advancement"]["state"] == "needs_provider_target_selection"
        assert result["next_action"] == result["advancement"]["next_action"]
        assert result["next_action"]["arguments"]["mode"] == "sync_only"
        assert "decision.target" in result["next_action"]["required_inputs"]
        assert "decision.rationale" in result["next_action"]["required_inputs"]
        assert result["advancement"]["decision"]["decision_required"]["kind"] == "provider_rejection_rehydration"
        assert all(command.operation.value not in {"start", "stop"} for command in provider.commands)
    finally:
        runtime.close()


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_sync_fifo_does_not_jump_old_generation_control_to_current_delta(tmp_path, operation):
    provider = _PacketProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "created", "operation_kind": "new_file",
            "file_path": "src/created.py", "instructions": ["Create the bounded output."],
            "unit_checks": ["The output parses."]}, "author-created")
        _close_semantic_gates(runtime, change_id, packet_id)
        handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-before-history", mode="sync_only")
        packet, _plan = _packet_and_plan(runtime, change_id, packet_id)
        delta = PacketProviderCommand("alpha", packet_id, packet["spec_revision"], "edit", flow_unit_ref="created",
            semantic_input={"changes": {"instructions": ["An obsolete historical payload."]}},
            delivery_fingerprint="obsolete-generation-delta")
        control = PacketProviderCommand("alpha", packet_id, packet["spec_revision"], operation,
            delivery_fingerprint="old-generation-control")
        current = replace(delta, delivery_fingerprint="current-generation-delta")
        entries = [runtime.ledger.enqueue_packet_provider_command("alpha", change_id, packet_id,
            provider_kind=provider.kind, command=command, actor="engineer") for command in (delta, control, current)]
        # A precise historical persistence fixture, not a claim that current
        # public binding replacement permits outstanding deliveries.
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            connection.execute("UPDATE packet_provider_outbox SET flow_binding_generation = 0 WHERE outbox_id IN (?, ?)",
                (entries[0]["outbox_id"], entries[1]["outbox_id"]))
        expected_control = runtime.ledger.packet_provider_outbox_entry("alpha", entries[1]["outbox_id"])
        expected_current = runtime.ledger.packet_provider_outbox_entry("alpha", entries[2]["outbox_id"])
        commands = list(provider.commands)
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-historical-fifo", mode="sync_only")["result"]
        assert result["advancement"]["state"] == "provider_control_pending"
        assert result["advancement"]["pending_control"]["outbox_id"] == entries[1]["outbox_id"]
        assert runtime.ledger.packet_provider_outbox_entry("alpha", entries[0]["outbox_id"])["state"] == "rejected"
        assert runtime.ledger.packet_provider_outbox_entry("alpha", entries[1]["outbox_id"]) == expected_control
        assert runtime.ledger.packet_provider_outbox_entry("alpha", entries[2]["outbox_id"]) == expected_current
        assert provider.commands == commands
    finally:
        runtime.close()


class _StableStatusProvider(_PacketProvider):
    def execute(self, command):
        if command.operation.value == "status":
            self.commands.append(command)
            return self._receipt(changed=False, include_all_units=True)
        return super().execute(command)


def test_sync_status_settle_checks_historical_fifo_before_claiming_synchronized(tmp_path):
    provider = _StableStatusProvider()
    runtime, change_id, packet_id, _started = _seed_packet(tmp_path, mode="required", provider=provider, legacy_wire=True)
    try:
        _author_unit(runtime, packet_id, {"client_unit_key": "created", "operation_kind": "new_file",
            "file_path": "src/created.py", "instructions": ["Create the bounded output."],
            "unit_checks": ["The output parses."]}, "author-created")
        _close_semantic_gates(runtime, change_id, packet_id)
        handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="sync-before-run", mode="sync_only")
        running = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="explicit-run", mode="advance")["result"]["advancement"]
        assert running["state"] == "provider_running"
        packet, plan = _packet_and_plan(runtime, change_id, packet_id)
        delta = PacketProviderCommand("alpha", packet_id, packet["spec_revision"], "edit", flow_unit_ref="created",
            semantic_input={"changes": {"instructions": ["An obsolete historical payload."]}},
            delivery_fingerprint="historical-delta-before-status")
        control = PacketProviderCommand("alpha", packet_id, packet["spec_revision"], "start",
            delivery_fingerprint="historical-control-before-status")
        entries = [runtime.ledger.enqueue_packet_provider_command("alpha", change_id, packet_id,
            provider_kind=provider.kind, command=command, actor="engineer") for command in (delta, control)]
        # Both entries are hidden from the current generation's projection.
        # The real projection must first observe the running provider, then
        # honor global historical FIFO before claiming synchronization.
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            connection.execute("UPDATE packet_provider_outbox SET flow_binding_generation = 0 WHERE outbox_id IN (?, ?)",
                (entries[0]["outbox_id"], entries[1]["outbox_id"]))
        expected_control = runtime.ledger.packet_provider_outbox_entry("alpha", entries[1]["outbox_id"])
        authority = deepcopy(runtime.ledger.change_state("alpha", change_id))
        current_plan = deepcopy(plan)
        current_units = dict(provider.units)
        before = len(provider.commands)
        provider.packet_state, provider.run_phase = "stopped", "stopped"
        provider.event_seq += 1
        result = handle_packet_advance(runtime, project_id="alpha", change_id=change_id, packet_id=packet_id,
            actor="engineer", request_id="observe-stop-with-historical-fifo", mode="sync_only")["result"]
        assert result["advancement"]["state"] == "provider_control_pending"
        assert result["advancement"]["reason"] == "sync_only_control_pending"
        assert result["advancement"]["provider"]["binding"]["provider_state"] == "stopped"
        assert result["advancement"]["pending_control"]["outbox_id"] == entries[1]["outbox_id"]
        assert runtime.ledger.packet_provider_outbox_entry("alpha", entries[0]["outbox_id"])["state"] == "rejected"
        assert runtime.ledger.packet_provider_outbox_entry("alpha", entries[1]["outbox_id"]) == expected_control
        assert runtime.ledger.change_state("alpha", change_id) == authority
        assert runtime.ledger.packet_work_plan_state("alpha", change_id, packet_id) == current_plan
        assert provider.units == current_units
        assert [command.operation.value for command in provider.commands[before:]] == ["status"]
    finally:
        runtime.close()
