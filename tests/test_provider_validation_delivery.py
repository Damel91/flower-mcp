"""Negotiated provider handoff preserves authority and recovers exact effects."""
from copy import deepcopy
from dataclasses import replace

import pytest

from flow_of_work_mcp import (
    RequirementDraft, RequirementService, SQLiteRequirementLedger, ChangeControlService,
    GovernedChangeDraft, ImplementationPacketDraft,
)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.packet_executor import PacketExecutorService
from flow_of_work_mcp.application.packet_provider_overlay import PacketProviderOverlayService, _provider_unit
from flow_of_work_mcp.application.packet_provider_projection import PacketProviderProjectionService
from flow_of_work_mcp.application.packet_provider_socket import PacketProviderSocketService
from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand, PacketProviderReceipt, PacketProviderUnitReceipt
from flow_of_work_mcp.core.domain.provider_validation import COMMAND_VERSION, RECEIPT_VERSION, ACK_VERSION, CONTEXT_VERSION
from flow_of_work_mcp.core.domain.provider_binding import ProviderProjectBindingDraft, ImplementationProviderKind
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ImplementationProviderUnavailableError, PacketProviderRejectedError
from tests.test_packet_executor import fixture, select, negotiate
from tests.test_packet_provider_port import _Client, _public_receipt
from flow_of_work_mcp.adapters.implementation_intelligence.packet_provider import McpCodingCastlePacketProvider


class ConformingProvider:
    kind = 'codingcastle'

    def __init__(self, capability_provider):
        self.capability_provider = capability_provider
        self.commands = []
        self.receipts = {}
        self.units = {}
        self.seq = 0
        self.state = 'draft'
        self.phase = 'idle'
        self.timeout_once = False
        self.ack_mode = ''
        self.bound_routes = []

    def execute_bound(self, command, *, binding_identity):
        self.bound_routes.append(deepcopy(binding_identity))
        return self.execute(command)

    def binding_identity(self, project_id):
        return self.capability_provider.binding_identity(project_id)

    def validation_capabilities(self, project_id):
        return self.capability_provider.validation_capabilities(project_id)

    def session_for_project(self, project_id):
        return self.binding_identity(project_id)['provider_context_id']

    def execute(self, command):
        self.commands.append(command)
        key = command.delivery_fingerprint
        if key and key in self.receipts:
            return self.receipts[key]
        self.seq += 1
        if command.flow_unit_ref:
            self.units.setdefault(command.flow_unit_ref, len(self.units) + 1)
            self.state = 'ready'
        if command.operation == 'start':
            self.state, self.phase = 'running', 'execution'
        elif command.operation == 'stop':
            self.state, self.phase = 'stopped', 'stopped'
        context = command.validation_context
        ack = {'contract_version': ACK_VERSION, 'context_sha256': context['context_sha256'],
               'authority_fingerprint': context['authority_fingerprint'], 'unit_key': context['unit_key'],
               'compiled_context_sha256': 'a' * 64}
        if self.ack_mode == 'mismatch':
            ack['context_sha256'] = 'b' * 64
        receipt = PacketProviderReceipt(provider_kind=self.kind,
            provider_contract_version='codingcastle.packet.receipt.v3', provider_packet_ref='provider-packet',
            provider_packet_revision=self.seq, provider_state=self.state, binding_epoch=1,
            event_seq=self.seq, changed=command.operation != 'status', run_phase=self.phase,
            unit_receipts=tuple(PacketProviderUnitReceipt(k, 'provider-' + k, 'ready', n) for k, n in self.units.items()),
            contract_version=RECEIPT_VERSION, validation_ack=ack)
        if self.ack_mode == 'missing':
            receipt = replace(receipt, contract_version='flow.packet_provider.receipt.v2', validation_ack={})
        if key:
            self.receipts[key] = receipt
        if self.timeout_once:
            self.timeout_once = False
            raise ImplementationProviderUnavailableError('implementation_provider_transport_unavailable')
        return receipt


def setup(tmp_path, *, negotiated=True, fixture_options=None):
    ledger, external, _executor, capability, ids, revs = fixture(tmp_path, **(fixture_options or {}))
    provider = ConformingProvider(capability)
    executor = PacketExecutorService(ledger, provider=provider,
        semantic_projection=lambda *identity: external.provider_validation(*identity))
    external = ExternalWorkService(ledger, packet_executor=executor)
    socket = PacketProviderSocketService(ledger, mode='required', provider=provider, executor=executor)
    overlay = PacketProviderOverlayService(ledger, socket=socket,
        projection=PacketProviderProjectionService(mode='required', provider=provider),
        external_work=external, executor=executor)
    select(executor, ids, revs)
    if negotiated:
        negotiate(executor, ids, revs)
    return ledger, external, executor, provider, socket, overlay, ids, revs


def upstream_coordinator(ledger, external, overlay):
    from flow_of_work_mcp.application.packet_advancement import PacketAdvancementCoordinator
    from flow_of_work_mcp.application.packet_construction import PacketConstructionService
    from flow_of_work_mcp.application.packet_guards import PacketGuardService
    from flow_of_work_mcp.application.packet_next_action import PacketNextActionProjectionService
    from flow_of_work_mcp.application.packet_pressure import PacketPressureService
    from flow_of_work_mcp.application.packet_reconciliation import PacketReconciliationService
    guards = PacketGuardService(changes=ledger, work_plans=ledger, construction=ledger, pressure=ledger,
        reviews=ledger, reconciliation=ledger, campaigns=ledger, packet_provider_overlay=overlay,
        external_work=external, consistent_reads=ledger)
    return guards, PacketAdvancementCoordinator(ledger=ledger, guards=guards,
        changes=ChangeControlService(ledger), construction=PacketConstructionService(ledger),
        pressure=PacketPressureService(ledger), work_plans=None, reviews=None,
        reconciliation=PacketReconciliationService(ledger), campaigns=ledger,
        next_actions=PacketNextActionProjectionService(), packet_provider_overlay=overlay)


def unit_command(executor, ids, revs, unit='producer', *, key='unit-command'):
    context = executor.validation_context(*ids, unit_key=unit)
    canonical = next(u for u in executor._ledger.packet_work_plan_state(*ids)['units'] if u['client_unit_key'] == unit)
    return PacketProviderCommand(*[ids[0], ids[2], revs['expected_spec_revision']],
        operation='add', flow_unit_ref=unit, semantic_input={'unit': _provider_unit(canonical, future=True)},
        delivery_fingerprint=key, contract_version=COMMAND_VERSION, validation_context=context)


def drift(ledger, ids):
    requirement = ledger.traceability_matrix(ids[0])[0]
    RequirementService(ledger).revise(ids[0], requirement['requirement_id'], RequirementDraft(
        title='Revised protocol', statement='a returns one and b calls a without I/O.', category='functional',
        rationale='Clarify intent.'), actor='human', rationale='Clarify intent.')


def test_no_unnegotiated_or_legacy_enriched_delivery(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path, negotiated=False)
    with pytest.raises(ChangeControlBlockedError, match='negotiation_required'):
        socket.ensure_draft(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')
    legacy = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'add', delivery_fingerprint='legacy')
    with pytest.raises(ChangeControlBlockedError, match='validation_context_required'):
        socket.submit(*ids, command=legacy, actor='engineer')
    assert provider.commands == []
    assert ledger.packet_provider_outbox_entries(*ids) == []


def test_complete_overlay_context_ack_and_start_order(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    packet = ledger.change_state(ids[0], ids[1])['packets'][0]
    plan = ledger.packet_work_plan_state(*ids)
    outcome = overlay.advance(*ids, packet=packet, work_plan=plan, actor='engineer', request_id='advance')
    assert outcome['state'] == 'provider_running'
    commands = provider.commands
    assert [c.operation.value for c in commands] == ['add', 'add', 'add', 'start', 'status']
    assert all(c.contract_version == COMMAND_VERSION for c in commands)
    consumer = next(c for c in commands if c.flow_unit_ref == 'consumer')
    assert consumer.validation_context['units'][1]['resolved_requires'][0]['contract']['symbol'] == 'a'
    assert consumer.validation_context['units'][0]['deferred_verification'][0]['kind'] == 'live_campaign'
    assert 'Run the installed CLI.' not in str(consumer.semantic_input)
    assert 'authority_context' in consumer.validation_context
    assert all(e['state'] == 'delivered' for e in ledger.packet_provider_outbox_entries(*ids))
    assert overlay.projection(*ids, packet=packet, work_plan=plan)['portable_packet']['contract_version'] == 'flow.portable_packet.v2'


@pytest.mark.parametrize('mode', ['missing', 'mismatch'])
def test_bad_ack_after_write_is_unknown(tmp_path, mode):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    provider.ack_mode = mode
    result = socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    assert result['state'] == 'provider_unknown'
    assert result['outbox']['state'] == 'unknown'
    assert len(provider.commands) == 1
    assert ledger.packet_provider_receipts(*ids) == []


def test_unknown_retry_rejection_preserves_prior_possible_effect(tmp_path, monkeypatch):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    provider.timeout_once = True
    unknown = socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    def reject(command):
        raise PacketProviderRejectedError('provider_unit_completed')
    monkeypatch.setattr(provider, 'execute', reject)
    result = socket.deliver(ids[0], unknown['outbox']['outbox_id'], actor='engineer')
    assert result['state'] == 'provider_unknown'
    assert ledger.packet_provider_outbox_entry(ids[0], unknown['outbox']['outbox_id'])['state'] == 'unknown'


def test_start_requires_current_unit_acknowledgements(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    context = executor.validation_context(*ids)
    start = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'start',
        delivery_fingerprint='start', contract_version=COMMAND_VERSION, validation_context=context)
    with pytest.raises(ChangeControlBlockedError, match='unit_acknowledgement_required'):
        socket.submit(*ids, command=start, actor='engineer')
    assert provider.commands == []


def test_unknown_restart_replays_exact_old_context_after_authority_drift(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    provider.timeout_once = True
    unknown = socket.submit(*ids, command=command, actor='engineer')
    drift(ledger, ids)
    restarted = SQLiteRequirementLedger(ledger.database_path)
    resumed = PacketExecutorService(restarted, provider=provider, semantic_projection=ExternalWorkService(restarted).provider_validation)
    transport = PacketProviderSocketService(restarted, mode='required', provider=provider, executor=resumed)
    with pytest.raises(ChangeControlBlockedError, match='existing_delivery_unresolved'):
        transport.submit(*ids, command=replace(command, delivery_fingerprint='rewritten'), actor='engineer')
    delivered = transport.deliver(ids[0], unknown['outbox']['outbox_id'], actor='engineer')
    assert delivered['state'] == 'provider_delivered'
    assert provider.commands == [command, command]
    assert resumed.admission(*ids)['allowed'] is False


def test_frozen_stop_and_status_after_drift_do_not_admit_new_work(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    original = executor.frozen_context(*ids)
    drift(ledger, ids)
    stopped = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'stop',
        delivery_fingerprint='stop-admitted', **socket.validation_fields(*ids, operation='stop'))
    assert socket.submit(*ids, command=stopped, actor='engineer')['state'] == 'provider_delivered'
    assert socket.observe_status(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')['state'] == 'provider_observed'
    assert provider.commands[-1].validation_context == original
    assert executor.admission(*ids)['allowed'] is False


def test_stale_replay_keeps_exact_unit_ack_and_current_binding(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    provider.timeout_once = True
    unknown = socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    # A status discovers the committed effect, with a later control ack.
    receipt = provider.execute(PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'status',
        **socket.validation_fields(*ids, operation='status')))
    current = ledger.record_packet_provider_receipt(*ids, flow_spec_revision=revs['expected_spec_revision'],
        receipt=receipt, actor='engineer', observation_kind='status')
    delivered = socket.deliver(ids[0], unknown['outbox']['outbox_id'], actor='engineer')
    entry = ledger.packet_provider_outbox_entry(ids[0], unknown['outbox']['outbox_id'])
    assert delivered['state'] == 'provider_delivered'
    by_id = {r['receipt_id']: r for r in ledger.packet_provider_receipts(*ids)}
    assert by_id[entry['receipt_id']]['receipt']['validation_ack']['unit_key'] == 'producer'
    binding = ledger.packet_provider_binding(*ids, provider_kind='codingcastle')
    assert binding['last_receipt_id'] == current['receipt']['receipt_id']
    assert binding['event_seq'] == receipt.event_seq


def test_adapter_carries_typed_context_and_exact_ack_without_compiling(tmp_path):
    ledger, external, executor, capability, ids, revs = fixture(tmp_path)
    select(executor, ids, revs)
    negotiate(executor, ids, revs)
    command = unit_command(executor, ids, revs)
    response = _public_receipt()
    response['result']['contract_version'] = 'codingcastle.packet.receipt.v3'
    response['result']['audit']['validation_ack'] = {
        'contract_version': ACK_VERSION, 'context_sha256': command.validation_context['context_sha256'],
        'authority_fingerprint': command.validation_context['authority_fingerprint'], 'unit_key': 'producer',
        'compiled_context_sha256': 'c' * 64}
    client = _Client(response)
    adapter = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    receipt = adapter.execute_bound(command, binding_identity=adapter.binding_identity(ids[0]))
    assert receipt.contract_version == RECEIPT_VERSION
    assert client.metas[0][CONTEXT_VERSION] == command.validation_context
    assert client.calls[0][1]['unit'] == command.semantic_input['unit']
    assert 'deferred_verification' not in str(client.calls[0][1])
    assert receipt.validation_ack['compiled_context_sha256'] == 'c' * 64


def test_adapter_discovers_only_explicit_capability_route(tmp_path):
    ledger, external, executor, capability, ids, revs = fixture(tmp_path)
    client = _Client({'status': 'success', 'result': {'packet_validation': capability.capability}})
    adapter = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    assert adapter.validation_capabilities(ids[0]) == capability.capability
    assert client.calls == [('codingcastle_capabilities', {})]


def rebind(ledger, ids):
    ledger.bind_provider_project(ids[0], ProviderProjectBindingDraft(ImplementationProviderKind.PACKET_EXECUTION,
        'fixture-provider', '', (), provider_context_id='different-session',
        replacement_reason='Separate explicit association.'), actor='human')


def test_admitted_route_cannot_be_rebound_by_new_negotiation(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    original = executor.inspect(*ids)['admitted_route']
    rebind(ledger, ids)
    with pytest.raises(ChangeControlBlockedError, match='execution_route_changed'):
        negotiate(executor, ids, revs, 'new-route')
    assert provider.capability_provider.calls == 1
    assert executor.admission(*ids)['reason'] == 'provider_execution_route_changed'
    with pytest.raises(ChangeControlBlockedError, match='execution_route_changed'):
        socket.validation_fields(*ids, operation='stop')
    assert executor.inspect(*ids)['admitted_route'] == original


def test_negative_renegotiation_blocks_fresh_work_but_not_original_unknown(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    provider.timeout_once = True
    unknown = socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    provider.capability_provider.capability['command_versions'] = ['incompatible.v1']
    assert negotiate(executor, ids, revs, 'negative-after-admission')['status'] == 'blocked'
    assert executor.admission(*ids)['allowed'] is False
    assert socket.deliver(ids[0], unknown['outbox']['outbox_id'], actor='engineer')['state'] == 'provider_delivered'
    assert socket.observe_status(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')['state'] == 'provider_observed'
    assert executor.admission(*ids)['allowed'] is False


def test_exact_unit_ack_survives_more_than_recent_receipt_window(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    for unit in ('producer', 'consumer'):
        socket.submit(*ids, command=unit_command(executor, ids, revs, unit, key=unit), actor='engineer')
    for _ in range(65):
        socket.observe_status(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')
    start = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'start',
        delivery_fingerprint='start-after-observations', **socket.validation_fields(*ids, operation='start'))
    assert socket.submit(*ids, command=start, actor='engineer')['state'] == 'provider_delivered'
    provider.state, provider.phase = 'completed', 'completed'
    socket.observe_status(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')
    assert executor.implementation_closure(*ids)['complete'] is True


def v3_response(command, *, changed=True, status='ok'):
    response = _public_receipt(changed=changed)
    response['status'] = status
    response['result']['contract_version'] = 'codingcastle.packet.receipt.v3'
    response['result']['audit']['validation_ack'] = {
        'contract_version': ACK_VERSION, 'context_sha256': command.validation_context['context_sha256'],
        'authority_fingerprint': command.validation_context['authority_fingerprint'], 'unit_key': command.flow_unit_ref,
        'compiled_context_sha256': 'c' * 64}
    return response


def test_bound_transport_keeps_captured_session_outside_database_locks(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    client = _Client(v3_response(command))
    adapter = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    alternate = SQLiteRequirementLedger(ledger.database_path)
    class RaceProvider:
        kind = 'codingcastle'
        def execute_bound(self, command, *, binding_identity):
            assert ledger._transaction_connection.get() is None
            rebind(alternate, ids)  # Commits before transport; no SQLite lock spans MCP.
            return adapter.execute_bound(command, binding_identity=binding_identity)
    socket._provider = RaceProvider()
    assert socket.submit(*ids, command=command, actor='engineer')['state'] == 'provider_delivered'
    assert client.calls[0][1]['session_id'] == 'fixture-session'
    assert executor.inspect(*ids)['admitted_route']['binding_identity']['provider_context_id'] == 'fixture-session'
    assert executor.admission(*ids)['reason'] == 'provider_execution_route_changed'


@pytest.mark.parametrize('changed', [False, True])
def test_outer_error_needs_exact_ack_and_explicit_no_effect_for_rejection(tmp_path, changed):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    client = _Client(v3_response(command, changed=changed, status='blocked'))
    socket._provider = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    outcome = socket.submit(*ids, command=command, actor='engineer')
    assert outcome['state'] == ('provider_unknown' if changed else 'provider_rejected')


def test_wire_scalars_require_exact_hash_and_version_strings(tmp_path):
    from flow_of_work_mcp.core.domain.provider_validation import validate_ack, validate_capability
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    ack = v3_response(unit_command(executor, ids, revs))['result']['audit']['validation_ack']
    ack['compiled_context_sha256'] = ' ' + 'c' * 64 + ' '
    with pytest.raises(ValueError, match='lowercase SHA256'):
        validate_ack(ack)
    capability = deepcopy(provider.capability_provider.capability)
    capability['command_versions'] = [' ' * 200_000 + COMMAND_VERSION]
    with pytest.raises(ValueError, match='exact wire versions'):
        validate_capability(capability)


@pytest.mark.parametrize('changed', [True, None, False])
def test_outer_error_cannot_claim_effect_free_rejection_without_v3_ack(tmp_path, changed):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    response = _public_receipt(changed=bool(changed))
    response['status'] = 'blocked'
    response['reason'] = 'provider_postcondition_failed'
    response['result']['contract_version'] = 'codingcastle.packet.receipt.v3'
    if changed is None:
        del response['result']['changed']
    client = _Client(response)
    socket._provider = McpCodingCastlePacketProvider(client=client, bindings=(), binding_resolver=ledger)
    outcome = socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    assert outcome['state'] == 'provider_unknown'
    assert outcome['outbox']['state'] == 'unknown'
    assert len(client.calls) == 1


def test_guard_and_overlay_recover_unknown_then_return_current_gate(tmp_path):
    from flow_of_work_mcp.application.packet_guards import PacketGuardService
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    provider.timeout_once = True
    command = unit_command(executor, ids, revs)
    socket.submit(*ids, command=command, actor='engineer')
    drift(ledger, ids)
    guards = PacketGuardService(changes=ledger, work_plans=ledger, construction=None, pressure=None,
        reviews=None, reconciliation=None, campaigns=None, packet_provider_overlay=overlay,
        external_work=external, consistent_reads=ledger)
    guard = guards.evaluate(*ids)
    assert guard.state == 'provider_recovery_pending'
    assert guard.next_operation == 'deliver_provider_command'
    assert guard.execution_ready is False
    packet = ledger.change_state(ids[0], ids[1])['packets'][0]
    outcome = overlay.advance(*ids, packet=packet, work_plan=ledger.packet_work_plan_state(*ids),
        actor='engineer', request_id='recover-via-overlay')
    assert outcome['next_action']['tool'] == 'fow_packet_advance'
    assert outcome['next_action']['operation'] == 'advance'
    assert outcome['next_action']['lifecycle_operation'] == 'derive_engineering_questions'
    assert provider.commands == [command, command]
    assert guards.evaluate(*ids).execution_ready is False


def test_coordinator_exposes_and_consumes_existing_risk_gate_then_renegotiates(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path, negotiated=False)
    guards, coordinator = upstream_coordinator(ledger, external, overlay)
    result = coordinator.advance(*ids, actor='engineer', request_id='prepare-upstream')
    assert result['decision']['state'] == 'needs_risk_decision'
    assert result['decision']['next_operation'] == 'decide_residual_risk'
    assert result['next_action']['tool'] == 'fow_packet_advance'
    assert result['next_action']['operation'] == 'advance'
    assert 'decision.accepted_risk_ref' in result['next_action']['required_inputs']
    assert {step['step_kind'] for step in result['mechanical_steps']} >= {'derive_engineering_questions', 'derive_packet_pressure'}
    version = ledger.ledger_version(ids[0])
    read = external.call(*ids, 'provider_validation')
    projected = overlay.projection(*ids, packet=ledger.change_state(ids[0], ids[1])['packets'][0],
        work_plan=ledger.packet_work_plan_state(*ids))
    assert read['next_gate']['lifecycle_operation'] == 'decide_residual_risk'
    assert projected['next_action']['operation'] == 'advance'
    assert projected['next_action']['lifecycle_operation'] == 'decide_residual_risk'
    assert ledger.ledger_version(ids[0]) == version
    assert provider.commands == [] and provider.capability_provider.calls == 0
    accepted = coordinator.advance(*ids, actor='engineer', request_id='risk-decision',
        decision={'operation': 'accept_residual_risk', 'accepted_risk_ref': 'qualification:risk-review'})
    assert accepted['decision_response_consumed'] is True
    assert accepted['next_action']['operation'] == 'negotiate_provider'
    assert negotiate(executor, ids, revs, 'after-risk')['status'] == 'success'
    assert executor.admission(*ids)['allowed'] is True
    assert provider.commands == []


def test_required_cleanup_question_keeps_ordinary_engineering_answer_route(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path, negotiated=False,
        fixture_options={'target_policy': 'code_targets_required', 'producer_operation': 'extract_move'})
    guards, coordinator = upstream_coordinator(ledger, external, overlay)
    result = coordinator.advance(*ids, actor='engineer', request_id='derive-cleanup-questions')
    assert result['decision']['next_operation'] == 'answer_engineering_questions'
    assert result['next_action']['tool'] == 'fow_packet_author'
    assert result['next_action']['operation'] == 'answer_gate'
    assert executor.admission(*ids)['reason'] == 'engineering_answer_missing'
    audit = ledger.packet_construction_audit_for_packet(*ids)
    assert any(q['question_key'] == 'cleanup' and q['required'] and q['status'] == 'open' for q in audit['questions'])
    version = ledger.ledger_version(ids[0])
    read = external.call(*ids, 'provider_validation')
    assert read['next_gate']['operation'] == 'answer_gate'
    assert ledger.ledger_version(ids[0]) == version
    assert ledger.packet_provider_outbox_entries(*ids) == [] and provider.commands == []


def test_stale_accepted_pressure_is_derived_again_before_new_risk_decision(tmp_path):
    from dataclasses import fields
    from flow_of_work_mcp import PacketWorkPlanDraft, WorkPlanUnit
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path, negotiated=False)
    guards, coordinator = upstream_coordinator(ledger, external, overlay)
    coordinator.advance(*ids, actor='engineer', request_id='prepare-old-pressure')
    coordinator.advance(*ids, actor='engineer', request_id='accept-old-pressure',
        decision={'operation': 'accept_residual_risk', 'accepted_risk_ref': 'qualification:old-risk'})
    old_pressure = ledger.latest_packet_pressure(*ids)
    previous = ledger.packet_work_plan_state(*ids)
    revised = ChangeControlService(ledger).refine_packet(*ids, objective='Create a and b with clarified contracts.', actor='engineer')
    packet = next(p for p in revised['packets'] if p['packet_id'] == ids[2])
    units = tuple(WorkPlanUnit(**{field.name: row[field.name] for field in fields(WorkPlanUnit) if field.name in row})
                  for row in previous['units'])
    plan = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'], units),
        actor='engineer', expected_current_plan_revision=previous['plan_revision'])
    ledger.transition_packet_work_plan(ids[0], plan['work_plan_id'], plan['plan_revision'], status='accepted',
        expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'],
        rationale='Retain complete contracts after the ordinary revision.', actor='engineer')
    assert executor.admission(*ids)['reason'] == 'accepted_risk_context_stale'
    assert guards.evaluate(*ids).next_operation == 'derive_packet_pressure'
    assert external.call(*ids, 'provider_validation')['next_gate']['lifecycle_operation'] == 'derive_packet_pressure'
    result = coordinator.advance(*ids, actor='engineer', request_id='refresh-stale-pressure')
    assert result['decision']['state'] == 'needs_risk_decision'
    current = ledger.latest_packet_pressure(*ids)
    assert current['pressure_id'] != old_pressure['pressure_id']
    current_packet = next(p for p in ledger.change_state(ids[0], ids[1])['packets'] if p['packet_id'] == ids[2])
    assert current['packet_revision'] == current_packet['spec_revision']
    assert current['accepted_risk_refs'] == []
    assert provider.commands == []


def test_running_drift_keeps_frozen_status_ahead_of_current_unit_hashes(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    for unit in ('producer', 'consumer'):
        socket.submit(*ids, command=unit_command(executor, ids, revs, unit, key=unit), actor='engineer')
    start = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'start',
        delivery_fingerprint='start-before-drift', **socket.validation_fields(*ids, operation='start'))
    socket.submit(*ids, command=start, actor='engineer')
    frozen = executor.frozen_context(*ids)
    drift(ledger, ids)
    assert executor.admission(*ids)['allowed'] is False
    guards, coordinator = upstream_coordinator(ledger, external, overlay)
    assert guards.evaluate(*ids).next_operation == 'observe_provider_packet'
    before = len(provider.commands)
    coordinator.advance(*ids, actor='engineer', request_id='observe-running-drift')
    assert len(provider.commands) == before + 1
    assert provider.commands[-1].operation == 'status'
    assert provider.commands[-1].validation_context == frozen
    assert executor.admission(*ids)['allowed'] is False
    assert guards.evaluate(*ids).execution_ready is False


def test_frozen_control_accepts_current_outer_spec_after_packet_revision(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    old = executor.frozen_context(*ids)
    revised = ChangeControlService(ledger).refine_packet(*ids, rationale='Clarified design rationale.', actor='engineer')
    packet = revised['packets'][0]
    assert packet['spec_revision'] > old['spec_revision']
    stop = PacketProviderCommand(ids[0], ids[2], packet['spec_revision'], 'stop',
        delivery_fingerprint='stop-revised', **socket.validation_fields(*ids, operation='stop'))
    assert socket.submit(*ids, command=stop, actor='engineer')['state'] == 'provider_delivered'
    assert provider.commands[-1].validation_context == old


def test_completed_provider_cannot_replay_as_fresh_start(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    for unit in ('producer', 'consumer'):
        socket.submit(*ids, command=unit_command(executor, ids, revs, unit, key=unit), actor='engineer')
    provider.state, provider.phase = 'completed', 'completed'
    socket.observe_status(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')
    before = len(provider.commands)
    start = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'start',
        delivery_fingerprint='replay-completed', **socket.validation_fields(*ids, operation='start'))
    with pytest.raises(ChangeControlBlockedError, match='completed_work_replay_prohibited'):
        socket.submit(*ids, command=start, actor='engineer')
    assert len(provider.commands) == before
    with pytest.raises(ChangeControlBlockedError, match='completed_work_replay_prohibited'):
        socket.submit(*ids, command=unit_command(executor, ids, revs, key='fresh-completed-add'), actor='engineer')
    assert len(provider.commands) == before


def test_remove_cannot_delete_unit_still_in_accepted_plan(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    socket.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    remove = PacketProviderCommand(ids[0], ids[2], revs['expected_spec_revision'], 'remove',
        flow_unit_ref='producer', delivery_fingerprint='remove-current-unit',
        **socket.validation_fields(*ids, operation='remove', unit_key='producer'))
    before = len(provider.commands)
    with pytest.raises(ChangeControlBlockedError, match='remove_correlation_required'):
        socket.submit(*ids, command=remove, actor='engineer')
    assert len(provider.commands) == before


def test_v3_combined_envelope_is_bounded_before_enqueue(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    technical = deepcopy(command.semantic_input)
    technical['unit']['instructions'] = ['x' * 4096] * 31 + ['y' * 2048]
    with pytest.raises(ValueError, match='complete command exceeds'):
        replace(command, semantic_input=technical)
    assert ledger.packet_provider_outbox_entries(*ids) == []
    assert provider.commands == []


def test_low_level_context_only_guard_is_independent_of_executor(tmp_path, monkeypatch):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    monkeypatch.setattr(ledger, 'remediation_context', lambda *args: {'predecessor_dependency_policy': 'context_only'})
    with pytest.raises(ChangeControlBlockedError, match='context_only_provider_execution_prohibited'):
        socket.submit(*ids, command=command, actor='engineer')
    direct = PacketProviderSocketService(ledger, mode='required', provider=provider)
    with pytest.raises(ChangeControlBlockedError, match='context_only_provider_execution_prohibited'):
        direct.submit(*ids, command=command, actor='engineer')
    assert provider.commands == []


@pytest.mark.parametrize('route', ['submit', 'draft', 'targets'])
def test_bare_socket_cannot_revert_explicit_provider_selection_to_legacy_v2(tmp_path, route):
    ledger = SQLiteRequirementLedger(tmp_path / 'unselected-legacy.sqlite')
    RequirementService(ledger).create_project('alpha', 'Legacy ownership boundary', actor='engineer')
    requirement = RequirementService(ledger).register('alpha', RequirementDraft(
        title='Single executor', statement='The selected executor shall own delivery.',
        category='functional', rationale='Preserve execution ownership.'), actor='engineer')
    changes = ChangeControlService(ledger)
    change = changes.create_change('alpha', GovernedChangeDraft(
        title='Legacy socket', rationale='Explicit ownership must govern low-level calls.',
        requirement_ids=(requirement['requirement_id'],)), actor='engineer')
    packet = changes.add_packet('alpha', change['change_id'], ImplementationPacketDraft(
        title='Legacy unit', objective='Deliver bounded work.', rationale='Preserve one owner.',
        completion_criteria=('Bounded work completes.',)), actor='engineer')['packets'][0]
    ids = ('alpha', change['change_id'], packet['packet_id'])
    class NeverCalledProvider:
        kind = 'codingcastle'
        mutations = 0
        def session_for_project(self, project_id):
            return 'fixture-session'
        def execute(self, command):
            self.mutations += 1
            raise AssertionError('Explicit executor admission was bypassed')
    provider = NeverCalledProvider()
    external = ExternalWorkService(ledger)
    executor = PacketExecutorService(ledger, provider=provider, semantic_projection=external.provider_validation)
    revs = {'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0}
    select(executor, ids, revs)
    assert executor.admission(*ids)['reason'] == 'packet_validation_upgrade_required'
    bare = PacketProviderSocketService(ledger, mode='required', provider=provider)
    with pytest.raises(ChangeControlBlockedError, match='provider_executor_service_required'):
        if route == 'submit':
            command = PacketProviderCommand(ids[0], ids[2], packet['spec_revision'], 'add',
                flow_unit_ref='unit-1', delivery_fingerprint='legacy-bypass', semantic_input={'unit': {
                    'kind': 'create_file', 'future_target': {'member_label': 'app', 'surface': 'workspace',
                    'relative_path': 'src/a.py'}, 'instructions': ['Implement bounded work.'],
                    'unit_checks': ['Local check passes.']}})
            bare.submit(*ids, command=command, actor='engineer')
        elif route == 'draft':
            bare.ensure_draft(*ids, flow_spec_revision=revs['expected_spec_revision'], actor='engineer')
        else:
            bare.preview_targets(*ids, flow_spec_revision=revs['expected_spec_revision'], flow_unit_ref='unit-1', actor='engineer')
    assert provider.mutations == 0
    assert ledger.packet_provider_outbox_entries(*ids) == []
    assert ledger.packet_provider_receipts(*ids) == []


def test_socket_cannot_dispatch_through_a_different_provider_kind(tmp_path):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    class OtherProvider:
        kind = 'other_provider'
        def execute_bound(self, command, *, binding_identity):
            return replace(provider.execute_bound(command, binding_identity=binding_identity), provider_kind=self.kind)
    other = PacketProviderSocketService(ledger, mode='required', provider=OtherProvider(), executor=executor)
    with pytest.raises(ChangeControlBlockedError, match='provider_executor_kind_mismatch'):
        other.submit(*ids, command=unit_command(executor, ids, revs), actor='engineer')
    assert provider.commands == []
    assert ledger.packet_provider_outbox_entries(*ids) == []


@pytest.mark.parametrize('mutation', ['instruction', 'path', 'unit_check', 'missing_unit'])
def test_envelope_cannot_bless_noncanonical_coding_input(tmp_path, mutation):
    ledger, external, executor, provider, socket, overlay, ids, revs = setup(tmp_path)
    command = unit_command(executor, ids, revs)
    technical = deepcopy(command.semantic_input)
    if mutation == 'instruction':
        technical['unit']['instructions'] = ['Implement unrelated code.']
    elif mutation == 'path':
        technical['unit']['future_target']['relative_path'] = 'unrelated.py'
    elif mutation == 'unit_check':
        technical['unit']['unit_checks'] = ['Skip every check.']
    else:
        from flow_of_work_mcp.core.domain.provider_validation import context_for_unit
        with pytest.raises(ValueError, match='selected unit missing'):
            replace(command, flow_unit_ref='absent', validation_context=context_for_unit(command.validation_context, 'absent'))
        return
    with pytest.raises(ChangeControlBlockedError, match='canonical_unit_mismatch'):
        socket.submit(*ids, command=replace(command, semantic_input=technical), actor='engineer')
    assert provider.commands == []
    assert ledger.packet_provider_outbox_entries(*ids) == []
