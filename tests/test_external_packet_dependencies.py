"""Canonical packet boundaries, offline plans and temporal external evidence."""
from copy import deepcopy

import pytest

from flow_of_work_mcp import ChangeControlService, ImplementationPacketDraft, PacketWorkPlanDraft, WorkPlanUnit
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from tests.test_external_work import fixture, report
from tests.engineering_cycle_support import record_test_repository_review


def dependent_fixture(tmp_path):
    ledger, external, first_ids, first_revs = fixture(tmp_path)
    changes = ChangeControlService(ledger)
    architecture_refs = tuple(ledger.change_state(*first_ids[:2])['packets'][0]['architecture_refs'])
    packet = changes.add_packet(first_ids[0], first_ids[1], ImplementationPacketDraft(title='Downstream facade',
        objective='Add a facade consuming the predecessor protocol.', rationale='Canonical packet order preserves producer materialization.',
        completion_criteria=('facade returns the next integer',), in_scope=('src/facade.py',),
        invariants=('Use the predecessor increment contract without changing arithmetic',),
        architecture_refs=architecture_refs), actor='human')['packets'][-1]
    ids = (first_ids[0], first_ids[1], packet['packet_id'])
    external.call(*ids, 'upgrade_validation', actor='human', request_id='facade-upgrade',
        payload={'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0})
    changes.link_dependency(*ids, first_ids[2], actor='human')
    packet = ledger.change_state(*ids[:2])['packets'][-1]
    unit = WorkPlanUnit(client_unit_key='facade', operation_kind='new_file', file_path='src/facade.py',
        instructions=('Consume increment-api from the canonical predecessor packet declaration included in the export.',
                      'Create advance(value) that returns increment(value).'), unit_checks=('advance(2) == 3',),
        implements=(1,), verifies=({'criterion': 1, 'kind': 'unit_check', 'statement': 'advance(2) == 3'},))
    plan = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'], (unit,)), actor='human')
    ledger.transition_packet_work_plan(ids[0], plan['work_plan_id'], plan['plan_revision'], status='accepted',
        expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'],
        rationale='Accept the bounded downstream context and check.', actor='human')
    revs = {'expected_spec_revision': plan['packet_revision'], 'expected_plan_revision': plan['plan_revision']}
    external.call(*ids, 'set_mode', actor='human', request_id='facade-mode', payload={'mode': 'external_agent', **revs})
    return ledger, external, first_ids, first_revs, ids, revs


def offline_facade_payload(external, ids, revs, fingerprint, *, key='facade-1'):
    return {'report_key': key, **revs, 'authority_fingerprint': fingerprint, 'unit_key': 'facade', 'outcome': 'complete',
        'summary': 'Facade implemented against the embedded producer protocol.', 'source_revision': 'host:facade-1',
        'artifacts': [{'reference': 'src/facade.py', 'description': 'Offline host output'}], 'produced_contracts': [],
        'verification': [{'criterion': 1, 'kind': 'unit_check', 'statement': 'advance(2) == 3', 'status': 'pass',
            'evidence_ref': 'host:facade-tests', 'provenance': 'host_reported_execution'}], 'unresolved': []}


def finish_predecessor(external, ids, revs):
    for unit in ('producer', 'consumer'):
        payload = report(external, ids, revs, unit, report_key='first-' + unit)
        external.call(*ids, 'report_outcome', actor='agent', request_id='submit-' + unit, payload=payload)
    if all(row['status'] == 'complete' for row in external.todo(*ids)['todos']):
        record_test_repository_review(external._ledger, ids)


def test_export_carries_predecessor_context_offline_order_and_stable_semantic_identity(tmp_path, monkeypatch):
    ledger, external, first_ids, first_revs, ids, revs = dependent_fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Standalone dependency projection invoked provider')
    monkeypatch.setattr(ledger, 'packet_provider_binding', forbidden)
    validation = external.validation(*ids)
    assert validation['plan_executable'] is True
    assert validation['execution_allowed'] is False
    assert external.todo(*ids)['reason'] == 'packet_dependencies_unresolved'
    export = external.call(*ids, 'export_plan', actor='agent', request_id='offline-dependent-export', payload=revs)
    content = export['content']
    assert export['draft'] is False
    for context in ['Exact producer consumer handoff', 'No I/O side effects.', 'Run the installed CLI with representative integers.',
                    'Future path: src/increment.py', first_ids[2], 'Complete each predecessor plan', 'reconcile predecessor unit reports before consumer reports']:
        assert context in content
    assert content.index('Unit 1: producer') < content.index('Unit 2: consumer') < content.index('Unit 1: facade')
    data = offline_facade_payload(external, ids, revs, export['authority_fingerprint'])
    with pytest.raises(ChangeControlBlockedError, match='packet_dependencies_unresolved'):
        external.call(*ids, 'report_outcome', actor='agent', request_id='premature-facade', payload=data)
    finish_predecessor(external, first_ids, first_revs)
    assert external.todo(*ids)['authority_fingerprint'] == export['authority_fingerprint']
    assert external.validation(*ids)['execution_allowed'] is True
    assert external.todo(*ids)['current_unit']['unit_key'] == 'facade'
    external.call(*ids, 'report_outcome', actor='agent', request_id='offline-facade', payload=data)
    record_test_repository_review(ledger, ids)
    assert external.todo(*ids)['current_unit'] is None
    stamped = ledger.external_work_state(*ids)['reports'][0]['predecessor_reports']
    assert stamped == {'packet:' + first_ids[2] + ':unit:producer': 'first-producer',
                       'packet:' + first_ids[2] + ':unit:consumer': 'first-consumer'}
    assert external.implementation_closure(*ids)['complete'] is True
    assert ledger.change_state(*ids[:2])['packets'][0]['status'] == 'planned'


def test_predecessor_conflict_and_replacement_invalidate_downstream_evidence(tmp_path):
    _ledger, external, first_ids, first_revs, ids, revs = dependent_fixture(tmp_path)
    finish_predecessor(external, first_ids, first_revs)
    fingerprint = external.todo(*ids)['authority_fingerprint']
    data = offline_facade_payload(external, ids, revs, fingerprint)
    external.call(*ids, 'report_outcome', actor='agent', request_id='facade-original', payload=data)
    producer = report(external, first_ids, first_revs, report_key='producer-rebuilt')
    producer['source_revision'] = 'host:rebuilt-producer'
    external.call(*first_ids, 'report_outcome', actor='agent', request_id='producer-rebuilt', payload=producer)
    assert external.todo(*ids)['reason'] == 'packet_dependencies_unresolved'
    assert external.implementation_closure(*ids)['complete'] is False
    external.call(*first_ids, 'reconcile_outcome', actor='human', request_id='choose-rebuilt-producer',
        payload={**first_revs, 'report_key': producer['report_key'], 'rationale': 'Select the rebuilt producer.'})
    consumer = report(external, first_ids, first_revs, 'consumer', report_key='consumer-rechecked')
    external.call(*first_ids, 'report_outcome', actor='agent', request_id='consumer-rechecked', payload=consumer)
    external.call(*first_ids, 'reconcile_outcome', actor='human', request_id='choose-rechecked-consumer',
        payload={**first_revs, 'report_key': consumer['report_key'], 'rationale': 'The client was rechecked against rebuilt producer.'})
    record_test_repository_review(_ledger, first_ids)
    todo = external.todo(*ids)
    assert todo['authority_fingerprint'] == fingerprint
    assert todo['current_unit']['status'] == 'stale'
    assert external.implementation_closure(*ids)['complete'] is False
    assert external.criterion_progress(*ids)['criteria'][0]['local_verification_state'] == 'pending'


def test_predecessor_semantic_revision_stales_consumer_and_export_is_draft_until_closed(tmp_path):
    ledger, external, first_ids, first_revs, ids, revs = dependent_fixture(tmp_path)
    before = external.call(*ids, 'export_plan', actor='agent', request_id='original-semantic', payload=revs)
    ChangeControlService(ledger).refine_packet(*first_ids, invariants=('Increment preserves signed64 bounds.',), actor='human')
    after = external.validation(*ids)
    assert after['validation']['authority_fingerprint'] != before['authority_fingerprint']
    assert after['plan_executable'] is False
    with pytest.raises(ChangeControlBlockedError, match='packet_dependency_plan_not_executable'):
        external.call(*ids, 'export_plan', actor='agent', request_id='strict-stale-dependency', payload=revs)
    draft = external.call(*ids, 'export_plan', actor='agent', request_id='draft-stale-dependency', payload={**revs, 'allow_draft': True})
    assert draft['draft'] and 'Increment preserves signed64 bounds.' in draft['content']
    assert 'work_plan_stale' in draft['content']


def test_producer_only_unit_without_criterion_ownership_is_required_by_closure(tmp_path):
    ledger, external, ids, revs = fixture(tmp_path)
    from tests.test_external_milestone_progress import accept_units
    units = deepcopy(ledger.packet_work_plan_state(*ids)['units'])
    extra = deepcopy(units[0])
    extra.update(client_unit_key='producer-only', file_path='src/support.py', implements=[], unit_checks=['Support behaves deterministically.'],
        verifies=[{'criterion': 1, 'kind': 'unit_check', 'statement': 'Support behaves deterministically.'}],
        provides=[{'name': 'support-contract', 'kind': 'protocol', 'clauses': ['Support is deterministic.']}])
    revs = accept_units(ledger, ids, [*units, extra])
    finish_predecessor(external, ids, revs)
    closure = external.implementation_closure(*ids)
    assert closure['scope_complete'] is True and closure['implementation_complete'] is False
    assert closure['complete'] is False
    extra_report = report(external, ids, revs, 'producer-only', report_key='producer-only-1')
    external.call(*ids, 'report_outcome', actor='agent', request_id='producer-only-1', payload=extra_report)
    record_test_repository_review(ledger, ids)
    assert external.implementation_closure(*ids)['complete'] is True


def test_default_provider_closure_returns_none_and_does_not_probe_optional_provider(tmp_path, monkeypatch):
    ledger, external, first_ids, _first_revs = fixture(tmp_path)
    packet = ChangeControlService(ledger).add_packet(*first_ids[:2], ImplementationPacketDraft(title='Provider history',
        completion_criteria=('criterion',)), actor='human')['packets'][-1]
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected provider read')
    monkeypatch.setattr(ledger, 'packet_provider_binding', forbidden)
    assert external.implementation_closure(*first_ids[:2], packet['packet_id']) is None
