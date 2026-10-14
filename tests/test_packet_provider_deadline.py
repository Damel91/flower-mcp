"""Actual RPC child deadlines preserve original durable packet authority.

The controlled stdlib worker models effect/ACK persistence and exact replay;
these deterministic tests do not qualify a real provider compiler or service.
"""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess

import pytest

from flow_of_work_mcp.adapters.implementation_intelligence import mcp_provider as provider_module
from flow_of_work_mcp.adapters.implementation_intelligence.packet_provider import McpCodingCastlePacketProvider
from flow_of_work_mcp.application.packet_provider_projection import PacketProviderProjectionService
from tests.test_mcp_provider_deadline import _assert_settled, _capture_children, _client, _install_worker
from tests.test_provider_sync_only import _advance, _restart, _tables
from tests.test_provider_validation_delivery import setup, unit_command


_EFFECT_WORKER = r'''
from pathlib import Path
from copy import deepcopy
import hashlib
STATE, MODE = Path(__STATE__), Path(__MODE__)
request = json.load(sys.stdin)
arguments, meta = request["arguments"], request["meta"]
context = meta["flow.packet_validation_context.v1"]
operation, key = arguments["operation"], context["unit_key"]
identity = hashlib.sha256(json.dumps({"arguments": arguments, "meta": meta}, sort_keys=True,
    separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
state = json.loads(STATE.read_text()) if STATE.exists() else {
    "sequence": 0, "units": {}, "state": "draft", "phase": "idle", "starts": 0, "effects": [], "cache": {}}
if operation != "status" and identity in state["cache"]:
    reply = deepcopy(state["cache"][identity])
else:
    state["sequence"] += 1
    delta = []
    if operation in {"add", "edit"} and key:
        state["units"].setdefault(key, len(state["units"]) + 1)
        state["state"] = "ready"
        delta = [{"number": state["units"][key], "unit_ref": "deadline-unit-" + key, "state": "ready"}]
    elif operation == "start":
        state["state"], state["phase"] = "running", "execution"
        state["starts"] += 1
    elif operation == "stop":
        state["state"], state["phase"] = "stopped", "stopped"
    elif operation == "status":
        delta = [{"number": number, "unit_ref": "deadline-unit-" + unit, "state": "ready"}
                 for unit, number in state["units"].items()]
    ack = {"contract_version": "codingcastle.packet_validation_ack.v1",
           "context_sha256": context["context_sha256"], "authority_fingerprint": context["authority_fingerprint"],
           "unit_key": key, "compiled_context_sha256": "a" * 64}
    reply = {"status": "ok", "result": {"contract_version": "codingcastle.packet.receipt.v3",
        "packet_state": state["state"], "changed": operation != "status", "units": [], "units_truncated": False,
        "readiness_gaps": [], "readiness_gaps_truncated": False, "technical_phase": state["phase"],
        "current_step": "status" if state["state"] == "running" else "start" if state["units"] else "add",
        "choices": [], "choices_truncated": False, "required_input": {},
        "available_actions": ["add", "edit", "remove", "start", "stop", "status"],
        "audit": {"packet_ref": "deadline-packet", "packet_revision": state["sequence"], "binding_epoch": 1,
            "event_seq": state["sequence"], "job_ref": "deadline-job" if state["starts"] else None,
            "unit_delta": delta, "unit_delta_truncated": False, "recent_packets": [], "validation_ack": ack}}}
    if operation != "status":
        state["cache"][identity] = deepcopy(reply)
        state["effects"].append({"identity": identity, "operation": operation, "unit_key": key,
            "context_sha256": context["context_sha256"], "arguments": arguments, "meta": meta})
    temporary = STATE.with_suffix(".new")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE)
mode = json.loads(MODE.read_text()) if MODE.exists() else {}
delayed = operation == mode.get("operation") and key == mode.get("unit_key")
frame = {"version": request["version"], "status": "ok", "result": reply}
if delayed and mode.get("emit_before_exit"):
    print(json.dumps(frame, ensure_ascii=False), flush=True)
if delayed:
    time.sleep(10)
if not delayed or not mode.get("emit_before_exit"):
    print(json.dumps(frame, ensure_ascii=False), flush=True)
'''


def _fixture(monkeypatch, tmp_path):
    state, mode = tmp_path / "remote-effect.json", tmp_path / "remote-mode.json"
    body = _EFFECT_WORKER.replace("__STATE__", repr(str(state))).replace("__MODE__", repr(str(mode)))
    _install_worker(monkeypatch, tmp_path, body)
    ledger, external, executor, _provider, socket, overlay, ids, revs = setup(tmp_path)
    adapter = McpCodingCastlePacketProvider(client=_client(0.7), bindings=(),
        binding_resolver=ledger, unit_correlation_resolver=ledger.packet_provider_unit_correlation)
    executor._provider = adapter
    socket._provider = adapter
    overlay._projection = PacketProviderProjectionService(mode="required", provider=adapter)
    return ledger, external, executor, adapter, socket, overlay, ids, revs, state, mode


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", ["advance", "sync_only"])
@pytest.mark.parametrize("emit_before_exit", [False, True])
def test_deadline_after_persisted_delta_keeps_exact_unknown_then_original_ack_on_restart(monkeypatch, tmp_path, mode, emit_before_exit):
    ledger, _external, _executor, adapter, _socket, overlay, ids, _revs, state_path, mode_path = _fixture(monkeypatch, tmp_path)
    mode_path.write_text(json.dumps({"operation": "add", "unit_key": "producer", "emit_before_exit": emit_before_exit}))
    children, _launches = _capture_children(monkeypatch)
    outcome = _advance(ledger, overlay, ids, mode=mode)
    assert outcome["state"] == "provider_unknown"
    unknown = next(row for row in ledger.packet_provider_outbox_entries(*ids) if row["state"] == "unknown")
    assert unknown["last_error"] == "implementation_provider_timeout"
    assert unknown["flow_unit_ref"] == "producer"
    original = deepcopy(unknown)
    remote = _read(state_path)
    effect = remote["effects"][-1]
    assert effect["operation"] == "add" and effect["unit_key"] == "producer"
    original_ack = remote["cache"][effect["identity"]]["result"]["audit"]["validation_ack"]
    assert original_ack["context_sha256"] == original["command"]["validation_context"]["context_sha256"]
    assert remote["starts"] == 0
    assert not any(row["operation"] == "start" for row in ledger.packet_provider_outbox_entries(*ids))
    assert not any(row["outbox_id"] == original["outbox_id"] for row in ledger.packet_provider_receipts(*ids))
    _assert_settled(children)
    mode_path.write_text("{}")
    restarted, _external, _executor, _socket, resumed = _restart(ledger, adapter)
    recovered = _advance(restarted, resumed, ids, request="recover-original-delta")
    assert recovered["state"] == "provider_synchronized"
    entry = restarted.packet_provider_outbox_entry(ids[0], original["outbox_id"])
    assert entry["state"] == "delivered"
    for key in ("command", "command_fingerprint", "delivery_fingerprint", "flow_spec_revision", "flow_binding_generation"):
        assert entry[key] == original[key]
    receipt = next(row for row in restarted.packet_provider_receipts(*ids) if row["receipt_id"] == entry["receipt_id"])
    assert receipt["receipt"]["validation_ack"] == original_ack
    final = _read(state_path)
    assert sum(row["identity"] == effect["identity"] for row in final["effects"]) == 1
    assert final["starts"] == 0
    _assert_settled(children)


def test_deadline_after_start_is_held_purely_by_sync_then_explicit_advance_replays_once(monkeypatch, tmp_path):
    ledger, _external, _executor, adapter, _socket, overlay, ids, _revs, state_path, mode_path = _fixture(monkeypatch, tmp_path)
    children, _launches = _capture_children(monkeypatch)
    assert _advance(ledger, overlay, ids)["state"] == "provider_synchronized"
    mode_path.write_text(json.dumps({"operation": "start", "unit_key": ""}))
    outcome = _advance(ledger, overlay, ids, request="start-with-deadline", mode="advance")
    assert outcome["state"] == "provider_unknown"
    original = next(row for row in ledger.packet_provider_outbox_entries(*ids) if row["operation"] == "start")
    assert original["state"] == "unknown" and original["last_error"] == "implementation_provider_timeout"
    remote = _read(state_path)
    assert remote["starts"] == 1
    effect = next(row for row in remote["effects"] if row["operation"] == "start")
    original_ack = remote["cache"][effect["identity"]]["result"]["audit"]["validation_ack"]
    before = _tables(ledger)
    launched = len(children)
    for request in ("hold-uncertain-start", "repeat-hold"):
        held = _advance(ledger, overlay, ids, request=request)
        assert held["state"] == "provider_control_pending"
        assert held["pending_control"]["outbox_id"] == original["outbox_id"]
        assert _tables(ledger) == before
    restarted, _external, _executor, _socket, resumed = _restart(ledger, adapter)
    assert _advance(restarted, resumed, ids, request="hold-after-restart")["state"] == "provider_control_pending"
    assert len(children) == launched
    assert restarted.packet_provider_outbox_entry(ids[0], original["outbox_id"]) == original
    mode_path.write_text("{}")
    recovered = _advance(restarted, resumed, ids, request="explicit-original-start-recovery", mode="advance")
    assert recovered["state"] == "provider_running"
    entry = restarted.packet_provider_outbox_entry(ids[0], original["outbox_id"])
    assert entry["state"] == "delivered" and entry["command"] == original["command"]
    receipt = next(row for row in restarted.packet_provider_receipts(*ids) if row["receipt_id"] == entry["receipt_id"])
    assert receipt["receipt"]["validation_ack"] == original_ack
    final = _read(state_path)
    assert final["starts"] == 1
    assert sum(row["identity"] == effect["identity"] for row in final["effects"]) == 1
    _assert_settled(children)


def test_external_cancellation_after_effect_preserves_crash_recovery_and_original_ack(monkeypatch, tmp_path):
    ledger, _external, executor, adapter, socket, _overlay, ids, revs, state_path, mode_path = _fixture(monkeypatch, tmp_path)
    mode_path.write_text(json.dumps({"operation": "add", "unit_key": "producer"}))
    original_spawn = subprocess.Popen
    children = []
    interrupt = KeyboardInterrupt("caller canceled after remote effect")
    def spawn(*args, **kwargs):
        child = original_spawn(*args, **kwargs)
        children.append(child)
        communicate = child.communicate
        first = True
        def canceled(*positional, **named):
            nonlocal first
            if first:
                first = False
                named["timeout"] = 0.25
                try:
                    communicate(*positional, **named)
                except subprocess.TimeoutExpired:
                    assert state_path.is_file(), "The fixture must persist its effect before caller cancellation"
                    raise interrupt
            return communicate(*positional, **named)
        child.communicate = canceled
        return child
    monkeypatch.setattr(provider_module.subprocess, "Popen", spawn)
    command = unit_command(executor, ids, revs)
    with pytest.raises(KeyboardInterrupt) as error:
        socket.submit(*ids, command=command, actor="engineer")
    assert error.value is interrupt
    entry = ledger.packet_provider_outbox_entries(*ids)[0]
    assert entry["state"] == "delivering"
    remote = _read(state_path)
    effect = remote["effects"][0]
    original_ack = remote["cache"][effect["identity"]]["result"]["audit"]["validation_ack"]
    _assert_settled(children)
    # Restore only the parent test hook; keep the same real adapter/child path.
    monkeypatch.setattr(subprocess, "Popen", original_spawn)
    mode_path.write_text("{}")
    restarted, _external, _executor, resumed_socket, _resumed = _restart(ledger, adapter)
    assert restarted.packet_provider_outbox_entry(ids[0], entry["outbox_id"])["state"] == "unknown"
    recovered = resumed_socket.deliver(ids[0], entry["outbox_id"], actor="engineer")
    assert recovered["state"] == "provider_delivered"
    final_entry = restarted.packet_provider_outbox_entry(ids[0], entry["outbox_id"])
    assert final_entry["command"] == entry["command"]
    receipt = next(row for row in restarted.packet_provider_receipts(*ids) if row["receipt_id"] == final_entry["receipt_id"])
    assert receipt["receipt"]["validation_ack"] == original_ack
    assert len(_read(state_path)["effects"]) == 1
