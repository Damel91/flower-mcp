"""Explicit ownership and capability discovery cannot imply executor transfer."""
from copy import deepcopy

import pytest

from flow_of_work_mcp import (
    ChangeControlService, GovernedChangeDraft, ImplementationPacketDraft,
    PacketWorkPlanDraft, RequirementDraft, RequirementService, SQLiteRequirementLedger, WorkPlanUnit,
)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.packet_executor import PacketExecutorService
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind, ProviderProjectBindingDraft
from flow_of_work_mcp.core.domain.provider_validation import build_context, validate_capability, validate_context
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from flow_of_work_mcp.core.errors import ImplementationProviderUnavailableError
from tests.engineering_cycle_support import adopt_minimal_architecture


CAPABILITY = {
    'contract_version': 'codingcastle.packet_validation_capability.v1',
    'command_versions': ['flow.packet_provider.semantic.v3'],
    'context_versions': ['flow.packet_validation_context.v1'],
    'receipt_versions': ['codingcastle.packet.receipt.v3'],
    'acknowledgement': 'exact_context_sha256',
    'materialization': 'producer_contracts_before_consumers',
}


class CapabilityProvider:
    kind = 'codingcastle'

    def __init__(self, ledger):
        self.ledger = ledger
        self.calls = 0
        self.capability = deepcopy(CAPABILITY)
        self.on_discovery = None

    def binding_identity(self, project_id):
        b = self.ledger.resolve_provider_binding(project_id, 'packet_execution')
        return {'provider_kind': 'packet_execution', 'provider_id': b.provider_id,
                'provider_context_id': b.provider_context_id, 'binding_revision': b.revision}

    def validation_capabilities(self, project_id):
        self.calls += 1
        if self.on_discovery:
            self.on_discovery()
        return deepcopy(self.capability)


def fixture(tmp_path, *, bind=True, target_policy='documental_only', producer_operation='new_file'):
    ledger = SQLiteRequirementLedger(tmp_path / 'executor.sqlite')
    requirements = RequirementService(ledger)
    requirements.create_project('alpha', 'Explicit execution', actor='human')
    architecture_refs = adopt_minimal_architecture(ledger)
    requirement = requirements.register('alpha', RequirementDraft(title='Protocol',
        statement='a returns one and b calls a.', category='functional', rationale='Bounded contract.'), actor='human')
    changes = ChangeControlService(ledger)
    change = changes.create_change('alpha', GovernedChangeDraft(title='Protocol', rationale='Bounded protocol.',
        requirement_ids=(requirement['requirement_id'],)), actor='engineer')
    packet = changes.add_packet('alpha', change['change_id'], ImplementationPacketDraft(
        title='Producer and consumer', objective='Create a and b.', rationale='Canonical producer contract.',
        completion_criteria=('a returns one', 'b calls a'), in_scope=('src/a.py and src/b.py',),
        invariants=('No I/O.',), target_policy=target_policy, architecture_refs=architecture_refs), actor='engineer')['packets'][0]
    ids = ('alpha', change['change_id'], packet['packet_id'])
    external = ExternalWorkService(ledger)
    external.call(*ids, 'upgrade_validation', actor='engineer', request_id='upgrade',
                  payload={'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0})
    units = (
        WorkPlanUnit(client_unit_key='producer', operation_kind=producer_operation, file_path='src/a.py',
            target_description='The existing a boundary.' if producer_operation == 'extract_move' else '',
            instructions=('Implement a.',), unit_checks=('a() == 1',), implements=(1,),
            provides=({'name': 'a-api', 'kind': 'api', 'clauses': ['a returns one.'], 'file_path': 'src/a.py', 'symbol': 'a'},),
            verifies=({'criterion': 1, 'kind': 'unit_check', 'statement': 'a() == 1'},
                      {'criterion': 1, 'kind': 'live_campaign', 'statement': 'Run the installed CLI.'})),
        WorkPlanUnit(client_unit_key='consumer', operation_kind='new_file', file_path='src/b.py',
            instructions=('Call a from b.',), unit_checks=('b() == 1',), depends_on=('producer',), implements=(2,),
            requires=({'producer_unit_key': 'producer', 'contract_name': 'a-api', 'use': 'Implement b.'},),
            verifies=({'criterion': 2, 'kind': 'unit_check', 'statement': 'b() == 1'},)),
    )
    plan = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'], units), actor='engineer')
    ledger.transition_packet_work_plan(ids[0], plan['work_plan_id'], plan['plan_revision'], status='accepted',
        expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'],
        rationale='Complete contracts.', actor='engineer')
    if bind:
        ledger.bind_provider_project(ids[0], ProviderProjectBindingDraft(ImplementationProviderKind.PACKET_EXECUTION,
            'fixture-provider', '', (), provider_context_id='fixture-session'), actor='human')
    provider = CapabilityProvider(ledger)
    service = PacketExecutorService(ledger, provider=provider, semantic_projection=external.provider_validation)
    revs = {'expected_spec_revision': plan['packet_revision'], 'expected_plan_revision': plan['plan_revision']}
    return ledger, external, service, provider, ids, revs


def select(service, ids, revs, *, executor='provider', key='selection'):
    return service.call(*ids, 'select_executor', actor='engineer', request_id=key,
        payload={**revs, 'executor': executor, **({'provider_kind': 'codingcastle'} if executor == 'provider' else {})})


def negotiate(service, ids, revs, key='negotiation'):
    return service.call(*ids, 'negotiate_provider', actor='engineer', request_id=key, payload=revs)


def test_selection_is_immutable_even_without_reports_or_provider_calls(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    first = select(service, ids, revs, executor='external_agent')
    assert first['selection']['selection_revision'] == 1
    assert provider.calls == 0
    with pytest.raises(ChangeControlBlockedError, match='executor_transfer_not_supported'):
        select(service, ids, revs, key='opposite')
    assert select(service, ids, revs, executor='external_agent') == first
    assert service.inspect(*ids)['consumption_mode'] == 'external_agent'
    with pytest.raises(RequirementConflictError, match='request_conflict'):
        select(service, ids, revs)


def test_provider_selection_cannot_become_external_or_replay_changed_request(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    first = select(service, ids, revs)
    with pytest.raises(ChangeControlBlockedError, match='executor_transfer_not_supported'):
        select(service, ids, revs, executor='external_agent', key='external')
    assert service.inspect(*ids)['selection'] == first['selection']
    assert provider.calls == 0


def test_negotiation_is_explicit_durable_replay_and_reads_are_pure(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    assert service.admission(*ids)['allowed'] is False
    service.inspect(*ids)
    external.provider_validation(*ids)
    assert provider.calls == 0
    result = negotiate(service, ids, revs)
    assert result['status'] == 'success'
    assert provider.calls == 1
    assert negotiate(service, ids, revs) == result
    assert provider.calls == 1
    assert service.admission(*ids)['allowed'] is True
    restarted = SQLiteRequirementLedger(ledger.database_path)
    resumed = PacketExecutorService(restarted, provider=provider,
        semantic_projection=ExternalWorkService(restarted).provider_validation)
    assert resumed.inspect(*ids)['capabilities'] == service.inspect(*ids)['capabilities']
    assert resumed.validation_context(*ids)['authority_fingerprint'] == result['capability']['authority_fingerprint']


@pytest.mark.parametrize('patch', [
    {'command_versions': ['flow.packet_provider.semantic.v2']},
    {'context_versions': []}, {'receipt_versions': ['codingcastle.packet.receipt.v2']},
    {'materialization': 'unknown'}, {'extra': True},
])
def test_incompatible_capability_is_durably_blocked(tmp_path, patch):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    provider.capability.update(patch)
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'provider_validation_projection_unsupported'
    assert service.admission(*ids)['allowed'] is False
    assert service.inspect(*ids)['capabilities'][-1]['supported'] is False
    assert ledger.packet_provider_outbox_entries(*ids) == []


def test_missing_durable_binding_does_not_probe_and_records_block(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path, bind=False)
    select(service, ids, revs)
    result = negotiate(service, ids, revs)
    assert result['reason'] == 'provider_validation_durable_binding_required'
    assert provider.calls == 0


def test_binding_replacement_invalidates_capability_without_probing(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    negotiate(service, ids, revs)
    ledger.bind_provider_project(ids[0], ProviderProjectBindingDraft(ImplementationProviderKind.PACKET_EXECUTION,
        'fixture-provider', '', (), provider_context_id='another-session', replacement_reason='Explicit different target.'), actor='human')
    assert service.admission(*ids)['allowed'] is False
    assert provider.calls == 1


def test_binding_change_during_probe_never_authorizes_old_observation(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    provider.on_discovery = lambda: ledger.bind_provider_project(ids[0], ProviderProjectBindingDraft(
        ImplementationProviderKind.PACKET_EXECUTION, 'fixture-provider', '', (),
        provider_context_id='changed-during-probe', replacement_reason='Concurrent human decision.'), actor='human')
    with pytest.raises(ChangeControlBlockedError, match='provider_negotiation_authority_changed'):
        negotiate(service, ids, revs)
    assert service.inspect(*ids)['capabilities'] == []


def test_full_context_preserves_canonical_contracts_and_deferred_obligations(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    projection = external.provider_validation(*ids)
    context = build_context(projection, unit_key='consumer')
    assert context['authority_context']['packet']['objective'] == 'Create a and b.'
    assert context['units'][1]['resolved_requires'][0]['contract'] == context['units'][0]['provides'][0]
    assert context['units'][0]['deferred_verification'][0]['kind'] == 'live_campaign'
    assert all(v['kind'] == 'unit_check' for u in context['units'] for v in u['local_verification'])
    forged = deepcopy(context)
    forged['units'][0]['provides'][0]['clauses'] = ['Something else.']
    with pytest.raises(ValueError):
        validate_context(forged)


def test_legacy_external_choice_is_not_silently_transferred(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    external.call(*ids, 'set_mode', actor='human', request_id='legacy-mode', payload={**revs, 'mode': 'external_agent'})
    assert service.inspect(*ids)['selection'] is None
    with pytest.raises(ChangeControlBlockedError, match='executor_transfer_not_supported'):
        select(service, ids, revs)


def test_unavailable_negotiation_cannot_fall_back_to_earlier_success(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    negotiate(service, ids, revs)
    def unavailable():
        raise ImplementationProviderUnavailableError('provider_offline')
    provider.on_discovery = unavailable
    result = negotiate(service, ids, revs, 'offline-observation')
    assert result['status'] == 'blocked' and result['reason'] == 'provider_offline'
    assert service.admission(*ids)['allowed'] is False
    assert len(service.inspect(*ids)['capabilities']) == 2


@pytest.mark.parametrize('remote_reason', ['x' * 200000, 'remote error with private detail'])
def test_negative_capability_observation_bounds_untrusted_provider_reason(tmp_path, remote_reason):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    def unavailable():
        raise ImplementationProviderUnavailableError(remote_reason)
    provider.on_discovery = unavailable
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['reason'] == 'provider_validation_unavailable'
    assert result['capability']['reason'] == 'provider_validation_unavailable'
    assert result['capability']['capability'] == {}
    assert remote_reason not in str(service.inspect(*ids))
    assert negotiate(service, ids, revs) == result
    assert provider.calls == 1


def test_stale_selection_rejects_without_mutation(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    with pytest.raises(ChangeControlBlockedError, match='stale_work_plan_revision'):
        select(service, ids, {**revs, 'expected_plan_revision': 0})
    assert service.inspect(*ids)['selection'] is None
    assert provider.calls == 0


def test_existing_provider_outbox_prohibits_new_selection(tmp_path):
    from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    ledger.enqueue_packet_provider_command(*ids, provider_kind='codingcastle', actor='engineer',
        command=PacketProviderCommand(flow_session_ref=ids[0], flow_packet_ref=ids[2],
            flow_spec_revision=revs['expected_spec_revision'], operation='start', delivery_fingerprint='prior-provider-admission'))
    with pytest.raises(ChangeControlBlockedError, match='executor_transfer_not_supported'):
        select(service, ids, revs)
    assert service.inspect(*ids)['selection'] is None


def test_concurrent_opposite_selections_admit_exactly_one_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    barrier = Barrier(2)
    def attempt(executor):
        barrier.wait()
        try:
            return select(service, ids, revs, executor=executor, key=executor)['consumption_mode']
        except ChangeControlBlockedError as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, executor) for executor in ('external_agent', 'provider')]
        results = [f.result() for f in futures]
    assert results.count('executor_transfer_not_supported') == 1
    assert service.inspect(*ids)['selection']['executor'] in results
    assert ledger.packet_provider_outbox_entries(*ids) == []


def test_connected_requirement_drift_requires_new_negotiation(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    negotiate(service, ids, revs)
    old = service.validation_context(*ids)
    requirement = ledger.traceability_matrix(ids[0])[0]
    RequirementService(ledger).revise(ids[0], requirement['requirement_id'], RequirementDraft(
        title='Revised protocol', statement='a returns one and b calls a without I/O.',
        category='functional', rationale='Clarify observable intent.'), actor='human', rationale='Clarify observable intent.')
    assert service.admission(*ids)['allowed'] is False
    assert provider.calls == 1
    negotiate(service, ids, revs, 'new-authority')
    assert service.validation_context(*ids)['context_sha256'] != old['context_sha256']


def test_missing_packet_reports_a_bounded_block(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    missing = (*ids[:2], 'PACKET-999999')
    with pytest.raises(ChangeControlBlockedError, match='packet_not_found'):
        select(service, missing, revs)
    with pytest.raises(ChangeControlBlockedError, match='packet_not_found'):
        service.requires_validation(*missing)
    assert provider.calls == 0


def test_malformed_large_capability_records_bounded_negative_receipt(tmp_path):
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    select(service, ids, revs)
    provider.capability['untrusted_extra'] = 'x' * 1_000_000
    result = negotiate(service, ids, revs)
    assert result['status'] == 'blocked'
    assert result['capability']['capability'] == {}
    assert result['capability']['actor'] == 'engineer'
    assert result['capability']['binding_identity'] == provider.binding_identity(ids[0])


def test_executor_mutations_append_canonical_events_and_replay_reads_are_pure(tmp_path):
    import json
    ledger, external, service, provider, ids, revs = fixture(tmp_path)
    def events():
        with ledger._read_connection() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM requirement_events WHERE project_id=? ORDER BY event_id', (ids[0],))]
    before = events()
    selected = select(service, ids, revs)
    after_selection = events()
    assert len(after_selection) == len(before) + 1
    assert after_selection[-1]['event_type'] == 'packet_executor_select_executor'
    assert after_selection[-1]['actor'] == 'engineer'
    assert json.loads(after_selection[-1]['payload_json'])['result'] == selected
    assert select(service, ids, revs) == selected
    service.inspect(*ids)
    service.admission(*ids)
    external.provider_validation(*ids)
    assert events() == after_selection
    provider.capability['command_versions'] = ['unsupported.v1']
    negative = negotiate(service, ids, revs)
    after_negative = events()
    assert len(after_negative) == len(after_selection) + 1
    assert after_negative[-1]['event_type'] == 'packet_executor_negotiate_provider'
    assert json.loads(after_negative[-1]['payload_json'])['result'] == negative
    assert negotiate(service, ids, revs) == negative
    assert events() == after_negative
