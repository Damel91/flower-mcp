"""Standalone PVP/artifact/outcome qualification without provider/model state."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp import (ChangeControlService, GovernedChangeDraft, ImplementationPacketDraft, MilestoneDraft,
                             PacketWorkPlanDraft, RequirementDraft, RequirementService,
                             SQLiteRequirementLedger, WorkPlanUnit)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from tests.engineering_cycle_support import record_test_repository_review
from tests.engineering_cycle_support import adopt_minimal_architecture


def fixture(tmp_path):
    ledger = SQLiteRequirementLedger(tmp_path / 'flower.sqlite')
    requirements = RequirementService(ledger)
    requirements.create_project('alpha', 'Offline example', actor='human')
    requirement = requirements.register('alpha', RequirementDraft(
        title='Exact producer consumer handoff', statement='A producer shall expose increment and a consumer shall use it.',
        category='functional', rationale='The offline task must preserve a declared protocol.'), actor='human')
    architecture_refs = adopt_minimal_architecture(ledger)
    changes = ChangeControlService(ledger)
    change = changes.create_change('alpha', GovernedChangeDraft(title='Offline task', rationale='Bounded standalone trial',
                                                               requirement_ids=(requirement['requirement_id'],)), actor='human')
    packet = changes.add_packet('alpha', change['change_id'], ImplementationPacketDraft(
        title='Increment protocol', objective='Produce increment and a client.', rationale='An exact producer contract drives the consumer.',
        completion_criteria=('increment preserves its exact arithmetic contract', 'consumer calls increment'),
        requirement_ids=(requirement['requirement_id'],), in_scope=('src/increment.py and src/client.py',),
        invariants=('increment takes one integer and returns its successor',), out_of_scope=('Packaging/publication',),
        architecture_refs=architecture_refs), actor='human')['packets'][0]
    service = ExternalWorkService(ledger)
    ids = ('alpha', change['change_id'], packet['packet_id'])
    service.call(*ids, 'upgrade_validation', actor='human', request_id='upgrade',
                 payload={'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0})
    producer = WorkPlanUnit(client_unit_key='producer', operation_kind='new_file', file_path='src/increment.py',
        instructions=('Create src/increment.py exposing increment(value: int) -> int.', 'Return value + 1 and keep zero/negative inputs valid.'),
        unit_checks=('increment(0) == 1 and increment(-1) == 0',), implements=(1,),
        provides=({'name': 'increment-api', 'kind': 'api', 'clauses': ['One integer argument named value.', 'Return value + 1.', 'No I/O side effects.'],
                   'file_path': 'src/increment.py', 'symbol': 'increment', 'signature': '(value: int) -> int'},),
        verifies=({'criterion': 1, 'kind': 'unit_check', 'statement': 'increment(0) == 1 and increment(-1) == 0'},
                  {'criterion': 1, 'kind': 'live_campaign', 'statement': 'Run the installed CLI with representative integers.'}))
    consumer = WorkPlanUnit(client_unit_key='consumer', operation_kind='new_file', file_path='src/client.py',
        instructions=('Import increment from the predecessor module.', 'Expose next_value that calls increment(value).'),
        unit_checks=('next_value(4) == 5',), depends_on=('producer',), implements=(2,),
        requires=({'producer_unit_key': 'producer', 'contract_name': 'increment-api', 'use': 'Call increment to implement next_value.'},),
        verifies=({'criterion': 2, 'kind': 'unit_check', 'statement': 'next_value(4) == 5'},))
    proposed = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(change['change_id'], packet['packet_id'], packet['spec_revision'], (producer, consumer)), actor='human', request_id='plan')
    ledger.transition_packet_work_plan('alpha', proposed['work_plan_id'], proposed['plan_revision'], status='accepted',
        expected_packet_revision=proposed['packet_revision'], expected_current_plan_revision=proposed['plan_revision'],
        rationale='Exact bounded contracts accepted.', actor='human', request_id='accept-plan')
    revs = {'expected_spec_revision': proposed['packet_revision'], 'expected_plan_revision': proposed['plan_revision']}
    service.call(*ids, 'set_mode', actor='human', request_id='mode', payload={'mode': 'external_agent', **revs})
    return ledger, service, ids, revs


def report(service, ids, revs, key='producer', *, report_key='producer-1', outcome='complete'):
    todo = service.todo(*ids)
    unit = next(row['unit'] for row in todo['todos'] if row['unit_key'] == key)
    artifacts = [{'reference': unit['file_path'], 'description': 'Host-created output'}]
    return {'report_key': report_key, **revs, 'authority_fingerprint': todo['authority_fingerprint'],
            'unit_key': key, 'outcome': outcome, 'summary': 'Implemented and tested the bounded unit.', 'source_revision': 'host-revision-1',
            'artifacts': artifacts, 'produced_contracts': [{'name': c['name'], 'artifact_ref': unit['file_path']} for c in unit['provides']],
            'verification': [{'criterion': v['criterion'], 'kind': v['kind'], 'statement': v['statement'], 'status': 'pass',
                              'evidence_ref': 'host-test-log:001', 'provenance': 'host_reported_test_execution'} for v in unit['verifies'] if v['kind'] == 'unit_check'],
            'unresolved': []}


def test_complete_export_is_self_contained_deterministic_and_artifact_backed(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    first = service.call(*ids, 'export_plan', actor='agent', request_id='export-1', payload=revs)
    second = service.call(*ids, 'export_plan', actor='agent', request_id='export-2', payload=revs)
    assert first['content'] == second['content']
    assert first['content_sha256'] == second['content_sha256']
    assert first['content'].index('Unit 1: producer') < first['content'].index('Unit 2: consumer')
    for essential in ['Return value + 1.', 'Call increment to implement next_value.', 'No I/O side effects.',
                      'unit-local', 'deferred control-plane verification; not a current coding instruction',
                      'authority fingerprint', 'report_outcome', 'reconcile_outcome', 'host-reported', 'A producer shall expose increment']:
        assert essential in first['content']
    assert 'codingcastle' not in first['content'].casefold()
    assert first['draft'] is False
    assert ledger.artifact_generations('alpha')[-1]['artifacts'][0]['content'] == first['content']
    assert service.todo(*ids)['authority_fingerprint'] == first['authority_fingerprint']
    assert service.call(*ids, 'export_plan', actor='agent', request_id='export-1', payload=revs) == first


def test_dependency_frontier_report_restart_offline_replay_and_deferred_gate(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    version = ledger.ledger_version('alpha')
    todo = service.todo(*ids)
    assert ledger.ledger_version('alpha') == version
    assert todo['current_unit']['unit_key'] == 'producer'
    assert todo['todos'][1]['dependencies_pending'] == ['producer']
    producer = report(service, ids, revs)
    receipt = service.call(*ids, 'report_outcome', actor='agent', request_id='outcome-1', payload=producer)
    reopened = SQLiteRequirementLedger(tmp_path / 'flower.sqlite')
    resumed = ExternalWorkService(reopened)
    assert resumed.call(*ids, 'report_outcome', actor='agent', request_id='outcome-1', payload=producer) == receipt
    todo = resumed.todo(*ids)
    assert todo['current_unit']['unit_key'] == 'consumer'
    use = todo['current_unit']['unit']['resolved_requires'][0]
    assert use['temporal_state'] == 'host_reported_materialized'
    assert use['provenance'] == 'external_agent_report'
    consumer = report(resumed, ids, revs, 'consumer', report_key='consumer-1')
    resumed.call(*ids, 'report_outcome', actor='agent', request_id='outcome-2', payload=consumer)
    assert resumed.todo(*ids)['next_gate']['tool'] == 'fow_audit_phase'
    record_test_repository_review(reopened, ids)
    complete = resumed.todo(*ids)
    assert complete['current_unit'] is None
    assert complete['next_gate']['external_operation'] == 'obtain_deferred_verification'
    assert complete['acceptance'] == 'not_inferred'
    assert complete['deferred_verification'][0]['kind'] == 'live_campaign'
    assert reopened.change_state('alpha', ids[1])['packets'][0]['status'] == 'planned'


def test_completion_cannot_skip_local_check_outputs_unresolved_or_dependency(tmp_path):
    _ledger, service, ids, revs = fixture(tmp_path)
    data = report(service, ids, revs)
    for patch in [{'verification': []}, {'produced_contracts': []}, {'unresolved': ['Open local defect']}]:
        with pytest.raises(ValueError):
            service.call(*ids, 'report_outcome', actor='agent', request_id='bad-' + next(iter(patch)), payload={**data, **patch})
    premature = report(service, ids, revs, 'consumer', report_key='too-soon')
    with pytest.raises(ChangeControlBlockedError, match='predecessor_pending'):
        service.call(*ids, 'report_outcome', actor='agent', request_id='premature', payload=premature)
    assert all(t['status'] != 'complete' for t in service.todo(*ids)['todos'])


def test_conflicting_report_requires_explicit_reconciliation_and_never_replays_code(tmp_path):
    _ledger, service, ids, revs = fixture(tmp_path)
    first = report(service, ids, revs)
    service.call(*ids, 'report_outcome', actor='agent', request_id='first', payload=first)
    with pytest.raises(RequirementConflictError, match='request_conflict'):
        service.call(*ids, 'report_outcome', actor='agent', request_id='first', payload={**first, 'summary': 'Different assertion'})
    conflict = {**first, 'report_key': 'producer-2', 'outcome': 'failed', 'unresolved': ['A defect remains']}
    receipt = service.call(*ids, 'report_outcome', actor='agent', request_id='conflict', payload=conflict)
    assert receipt['status'] == 'conflict'
    assert service.todo(*ids)['current_unit']['status'] == 'conflict'
    service.call(*ids, 'reconcile_outcome', actor='human', request_id='reconcile', payload={'report_key': first['report_key'], **revs, 'rationale': 'Later report is erroneous; original test log reviewed.'})
    assert service.todo(*ids)['current_unit']['unit_key'] == 'consumer'


def test_old_authority_report_is_historical_and_cannot_close_current_work(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    old = report(service, ids, revs)
    ChangeControlService(ledger).refine_packet(*ids, invariants=('New accepted invariant: inputs are bounded to signed 64-bit integers.',), actor='human')
    receipt = service.call(*ids, 'report_outcome', actor='agent', request_id='offline-old', payload=old)
    assert receipt['status'] == 'historical'
    assert service.todo(*ids)['status'] == 'blocked'
    with pytest.raises(ChangeControlBlockedError, match='stale'):
        service.call(*ids, 'reconcile_outcome', actor='human', request_id='cannot-reconcile-old', payload={'report_key': old['report_key'],
            'expected_spec_revision': revs['expected_spec_revision'] + 1, 'expected_plan_revision': revs['expected_plan_revision'], 'rationale': 'Cannot simply promote old evidence.'})


def test_identity_numbers_do_not_compact_and_unknown_declarations_block(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    # Stable criterion 3 is retired only when it has no references.
    added = service.call(*ids, 'add_criterion', actor='human', request_id='criterion-3', payload={'statement': 'Optional additional boundary', 'expected_spec_revision': revs['expected_spec_revision']})
    removed = service.call(*ids, 'remove_criterion', actor='human', request_id='retire-3', payload={'number': 3, 'expected_spec_revision': added['spec_revision']})
    fourth = service.call(*ids, 'add_criterion', actor='human', request_id='criterion-4', payload={'statement': 'Another boundary', 'expected_spec_revision': removed['spec_revision']})
    assert fourth['number'] == 4
    criteria = service.call(*ids, 'criteria')['criteria']
    assert [(c['number'], c['active']) for c in criteria] == [(1, 1), (2, 1), (3, 0), (4, 1)]
    with pytest.raises(ChangeControlBlockedError, match='unit_references'):
        service.call(*ids, 'remove_criterion', actor='human', request_id='invalid-remove', payload={'number': 1, 'expected_spec_revision': fourth['spec_revision']})
    state = ledger.packet_work_plan_state(*ids)
    units = [u for u in state['units'] if u['client_unit_key'] != 'consumer']
    from flow_of_work_mcp.application.packet_work_plan import _unit_from_payload
    changed = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(ids[1], ids[2], fourth['spec_revision'], tuple(_unit_from_payload(u) for u in units)), actor='human', expected_current_plan_revision=1)
    assert changed['units'][0]['unit_number'] == 1
    consumer = deepcopy(state['units'][1])
    consumer['client_unit_key'] = 'replacement'
    new = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(ids[1], ids[2], changed['packet_revision'], tuple(_unit_from_payload(u) for u in [*units, consumer])), actor='human', expected_current_plan_revision=changed['plan_revision'])
    assert [u['unit_number'] for u in new['units']] == [1, 3]


def test_edit_criterion_keeps_identity_and_retains_history(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    before = service.call(*ids, 'criteria')
    edited = service.call(*ids, 'edit_criterion', actor='human', request_id='edit-1', payload={'number': 1, 'statement': 'Revised arithmetic boundary', 'expected_spec_revision': revs['expected_spec_revision']})
    assert edited['number'] == 1
    after = service.call(*ids, 'criteria')
    assert len(after['history']) == len(before['history']) + 1
    assert after['history'][0]['statement'] == before['criteria'][0]['statement']
    assert service.validation(*ids)['reason'] == 'work_plan_stale'


def test_external_reads_and_export_do_not_call_optional_integrations(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('optional provider operation called')
    monkeypatch.setattr(ledger, 'packet_provider_binding', forbidden)
    for operation, payload in [('criteria', {}), ('validation', {}), ('todo', {}), ('export_plan', revs)]:
        result = service.call(*ids, operation, actor='agent', request_id='no-provider-' + operation, payload=payload)
        assert result['status'] == 'success'


def test_draft_export_visibly_preserves_open_obligations(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    ChangeControlService(ledger).refine_packet(*ids, unresolved_questions=('Which public entrypoint is approved?',), actor='human')
    current = {**revs, 'expected_spec_revision': revs['expected_spec_revision'] + 1}
    with pytest.raises(ChangeControlBlockedError):
        service.call(*ids, 'export_plan', actor='agent', request_id='strict', payload=current)
    draft = service.call(*ids, 'export_plan', actor='agent', request_id='draft', payload={**current, 'allow_draft': True})
    assert draft['draft']
    assert 'DRAFT / NOT EXECUTABLE' in draft['content']
    assert 'Which public entrypoint is approved?' in draft['content']


def test_repeated_report_key_with_new_request_is_idempotent_and_changed_payload_conflicts(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    data = report(service, ids, revs)
    service.call(*ids, 'report_outcome', actor='agent', request_id='one', payload=data)
    replay = service.call(*ids, 'report_outcome', actor='agent', request_id='two', payload=data)
    assert replay['replayed'] is True
    assert len(ledger.external_work_state(*ids)['reports']) == 1
    with pytest.raises(RequirementConflictError, match='report_key_conflict'):
        service.call(*ids, 'report_outcome', actor='agent', request_id='three', payload={**data, 'summary': 'changed'})


def test_stale_criterion_view_requires_explicit_full_identity_mapping(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    ChangeControlService(ledger).refine_packet(*ids, completion_criteria=('A changed producer clause', 'consumer calls increment'), actor='human')
    assert service.validation(*ids)['reason'] == 'criterion_authority_stale'
    payload = {'expected_spec_revision': revs['expected_spec_revision'] + 1, 'rationale': 'Human explicitly maps changed producer wording to criterion one.',
               'criteria': [{'number': 1, 'statement': 'A changed producer clause', 'active': True},
                            {'number': 2, 'statement': 'consumer calls increment', 'active': True}], 'new_statements': []}
    for malformed in [{**payload, 'criteria': payload['criteria'][:1]},
                      {**payload, 'criteria': [{'number': 7, 'statement': 'Invented', 'active': True}, payload['criteria'][1]]},
                      {**payload, 'criteria': [{**payload['criteria'][0], 'active': False}, payload['criteria'][1]]}]:
        with pytest.raises((ValueError, ChangeControlBlockedError)):
            service.call(*ids, 'reconcile_criteria', actor='human', request_id='bad-' + str(malformed['criteria']), payload=malformed)
    reconciled = service.call(*ids, 'reconcile_criteria', actor='human', request_id='criteria-map', payload=payload)
    assert [c['number'] for c in reconciled['criteria']] == [1, 2]
    assert service.validation(*ids)['reason'] == 'work_plan_stale'
    assert service.call(*ids, 'criteria')['criteria'][0]['statement'] == 'A changed producer clause'


def test_changed_producer_report_invalidates_prior_consumer_evidence(tmp_path):
    _ledger, service, ids, revs = fixture(tmp_path)
    producer = report(service, ids, revs)
    service.call(*ids, 'report_outcome', actor='agent', request_id='original-producer', payload=producer)
    consumer = report(service, ids, revs, 'consumer', report_key='consumer-original')
    service.call(*ids, 'report_outcome', actor='agent', request_id='original-consumer', payload=consumer)
    replacement = {**producer, 'report_key': 'producer-rebuilt', 'source_revision': 'host-revision-2'}
    service.call(*ids, 'report_outcome', actor='agent', request_id='changed-producer', payload=replacement)
    assert service.todo(*ids)['todos'][1]['status'] == 'blocked'
    service.call(*ids, 'reconcile_outcome', actor='human', request_id='choose-rebuilt', payload={'report_key': replacement['report_key'], **revs, 'rationale': 'The rebuilt producer replaces previous output.'})
    todo = service.todo(*ids)
    assert todo['todos'][1]['status'] == 'stale'
    assert todo['current_unit']['unit_key'] == 'consumer'
    assert todo['next_gate']['external_operation'] == 'resolve_external_blocker'


def test_referenced_campaign_oracle_revisions_and_stable_obligations(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    from flow_of_work_mcp.core.domain.campaign_authority import CampaignCaseSemanticDraft, CampaignScopeDraft, BehavioralOracleDraft
    requirement_id = ledger.change_state('alpha', ids[1])['requirement_ids'][0]
    case = CampaignCaseSemanticDraft(title='Producer result', purpose='Check exact producer arithmetic.', case_kind='positive',
                                    action='Call increment(0).', expected_outcome='Return integer one.', observation_point='Return value')
    campaign = ledger.start_campaign_authority('alpha', title='Deferred semantic proof', scope=CampaignScopeDraft(change_id=ids[1],
        requirement_ids=(requirement_id,), packet_ids=(ids[2],)), first_case=case, actor='human', request_id='campaign-start')
    campaign_id = campaign['campaign_id']
    obligations = ledger.derive_campaign_obligations('alpha', campaign_id, actor='human', request_id='obligations')
    criterion_obligations = [o for o in obligations['obligations'] if o['source_kind'] == 'packet_criterion']
    assert [o['source_ref'] for o in criterion_obligations] == [ids[2] + ':criterion:1', ids[2] + ':criterion:2']
    assert not any(o['source_kind'] == 'packet_completion_criterion' for o in obligations['obligations'])
    oracle_state = ledger.author_behavioral_oracle('alpha', campaign_id, campaign['cases'][0]['case_id'],
        BehavioralOracleDraft(oracle_kind='behavior', subject_bindings=(requirement_id,), authority_reference='decision:oracle-draft',
                              semantic_fields={'preconditions': ['The producer has passed its local checks.']}), actor='human', request_id='oracle-first')
    oracle = oracle_state['oracles'][0]
    from flow_of_work_mcp.application.packet_work_plan import _unit_from_payload
    current_plan = ledger.packet_work_plan_state(*ids)
    producer = deepcopy(current_plan['units'][0])
    producer['verifies'][1]['authority_ref'] = 'campaign:' + campaign_id
    producer['verifies'].append({'criterion': 1, 'kind': 'oracle', 'statement': 'Verify arithmetic against the current accepted oracle.',
                                'authority_ref': 'oracle:' + oracle['oracle_id']})
    new_plan = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(ids[1], ids[2], revs['expected_spec_revision'],
        tuple(_unit_from_payload(u) for u in [producer, current_plan['units'][1]])), actor='human', expected_current_plan_revision=1)
    ledger.transition_packet_work_plan('alpha', new_plan['work_plan_id'], new_plan['plan_revision'], status='accepted',
        expected_packet_revision=new_plan['packet_revision'], expected_current_plan_revision=new_plan['plan_revision'], rationale='Reference canonical deferred campaign.', actor='human')
    new_revs = {'expected_spec_revision': new_plan['packet_revision'], 'expected_plan_revision': new_plan['plan_revision']}
    before = service.call(*ids, 'export_plan', actor='agent', request_id='campaign-export', payload=new_revs)
    assert 'Referenced authority: campaign:' + campaign_id in before['content']
    assert 'Referenced authority: oracle:' + oracle['oracle_id'] in before['content']
    assert '**Status:** draft' in before['content']
    assert '**Revision:**' in before['content']
    ledger.author_behavioral_oracle('alpha', campaign_id, campaign['cases'][0]['case_id'],
        BehavioralOracleDraft(oracle_kind='behavior', subject_bindings=(requirement_id,), authority_reference='decision:oracle-revised',
                              semantic_fields={'preconditions': ['The producer is installed in a clean environment.']}),
        oracle_id=oracle['oracle_id'], actor='human', request_id='oracle-second')
    oracle_fingerprint = service.todo(*ids)['authority_fingerprint']
    assert oracle_fingerprint != before['authority_fingerprint']
    ledger.edit_campaign_authority_case('alpha', campaign_id, campaign['cases'][0]['case_id'],
        draft=CampaignCaseSemanticDraft(title='Producer result revised', purpose='Check a new observation.', case_kind='positive',
            action='Call increment(-1).', expected_outcome='Return zero.', observation_point='Return value'), actor='human', request_id='edit-campaign')
    assert service.todo(*ids)['authority_fingerprint'] != oracle_fingerprint


def test_historical_report_cannot_impersonate_current_fingerprint_or_poison_conflicts(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    old = report(service, ids, revs)
    from flow_of_work_mcp.application.packet_work_plan import _unit_from_payload
    plan = ledger.packet_work_plan_state(*ids)
    producer = deepcopy(plan['units'][0])
    producer['instructions'].append('Keep the public signature unchanged.')
    revised = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(ids[1], ids[2], revs['expected_spec_revision'],
        tuple(_unit_from_payload(u) for u in [producer, plan['units'][1]])), actor='human', expected_current_plan_revision=1)
    ledger.transition_packet_work_plan('alpha', revised['work_plan_id'], revised['plan_revision'], status='accepted',
        expected_packet_revision=revised['packet_revision'], expected_current_plan_revision=revised['plan_revision'],
        rationale='The additional signature constraint is accepted.', actor='human')
    current_revs = {'expected_spec_revision': revised['packet_revision'], 'expected_plan_revision': revised['plan_revision']}
    spoof = {**old, 'authority_fingerprint': service.todo(*ids)['authority_fingerprint']}
    receipt = service.call(*ids, 'report_outcome', actor='agent', request_id='old-plan-current-fingerprint', payload=spoof)
    assert receipt['status'] == 'historical'
    todo = service.todo(*ids)
    assert todo['current_unit']['unit_key'] == 'producer'
    assert todo['historical_reports'] == [spoof['report_key']]
    with pytest.raises(ChangeControlBlockedError, match='stale'):
        service.call(*ids, 'reconcile_outcome', actor='human', request_id='reject-promotion', payload={**current_revs,
            'report_key': spoof['report_key'], 'rationale': 'Wrong plan revision cannot be adopted.'})
    current = report(service, ids, current_revs, report_key='current-plan')
    assert service.call(*ids, 'report_outcome', actor='agent', request_id='current-plan', payload=current)['status'] == 'success'
    assert service.todo(*ids)['current_unit']['unit_key'] == 'consumer'


def test_current_accepted_risks_export_and_stale_risks_fail_closed(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    from flow_of_work_mcp.core.domain.packet_pressure import PacketPressureDraft
    before = service.todo(*ids)['authority_fingerprint']
    ledger.record_packet_pressure('alpha', PacketPressureDraft(ids[1], ids[2], semantic_confidence='medium',
        improvement_pressure='normal', residual_risks=('Large integer behavior remains a deferred qualification.',),
        challenge_questions=('Does the clean installation retain integer semantics?',), accepted_risk_refs=('human-decision:large-integers',),
        source='authority', packet_revision=revs['expected_spec_revision']), actor='human', request_id='current-risk')
    exported = service.call(*ids, 'export_plan', actor='agent', request_id='with-risk', payload=revs)
    assert exported['authority_fingerprint'] != before
    assert 'Large integer behavior remains a deferred qualification.' in exported['content']
    assert 'human-decision:large-integers' in exported['content']
    ChangeControlService(ledger).refine_packet(*ids, invariants=('A new accepted arithmetic constraint.',), actor='human')
    validation = service.validation(*ids, detail='full')['validation']
    assert validation['status'] == 'stale'
    assert 'accepted_risk_context_stale' in {gap['code'] for gap in validation['gaps']}


def test_criterion_mutations_reject_ignored_fields_and_reconcile_full_historical_identity_set(tmp_path):
    ledger, service, ids, revs = fixture(tmp_path)
    for operation, data in [('add_criterion', {'number': 9, 'statement': 'New'}), ('remove_criterion', {'number': 1, 'statement': 'Ignored'})]:
        with pytest.raises(ValueError, match='unsupported fields'):
            service.call(*ids, operation, actor='human', request_id=operation + '-ignored', payload={**data, 'expected_spec_revision': revs['expected_spec_revision']})
    # Historical canonical packets were not limited to128 completion criteria.
    packet = ChangeControlService(ledger).add_packet(ids[0], ids[1], ImplementationPacketDraft(title='Large historical criterion authority',
        objective='Preserve every preexisting criterion identity.', rationale='No truncation or renumbering during upgrade.',
        completion_criteria=tuple('Existing criterion ' + str(i) for i in range(129)), in_scope=('one module',), invariants=('Stable identity',)), actor='human')['packets'][-1]
    large_ids = (ids[0], ids[1], packet['packet_id'])
    service.call(*large_ids, 'upgrade_validation', actor='human', request_id='large-upgrade', payload={'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0})
    criteria = service.call(*large_ids, 'criteria')['criteria']
    mapped = [{'number': c['number'], 'statement': c['statement'], 'active': bool(c['active'])} for c in criteria]
    receipt = service.call(*large_ids, 'reconcile_criteria', actor='human', request_id='large-map', payload={'expected_spec_revision': packet['spec_revision'],
        'criteria': mapped, 'rationale': 'Explicitly preserve every known criterion number.'})
    assert len(receipt['criteria']) == 129
    assert receipt['criteria'][-1]['number'] == 129


def test_schema_migration_atomic_failure_preserves_prior_database(tmp_path):
    path = tmp_path / 'failed-migration.sqlite'
    class FailingMigration(SQLiteRequirementLedger):
        @staticmethod
        def _ensure_columns(connection, table, columns):
            if table == 'external_work_reports':
                raise RuntimeError('isolated migration failure')
            return SQLiteRequirementLedger._ensure_columns(connection, table, columns)
    with pytest.raises(RuntimeError, match='isolated migration failure'):
        FailingMigration(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='packet_criteria'").fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=50').fetchone()[0] == 0
    recovered = SQLiteRequirementLedger(path)
    assert recovered.database_path == path.resolve()


def governing_milestone(ledger, ids):
    requirement_id = ledger.change_state(*ids[:2])['requirement_ids'][0]
    milestone = ledger.promote_milestone(ids[0], MilestoneDraft(
        name='Offline producer and consumer delivery', requirement_ids=(requirement_id,),
        prerequisite_requirement_ids=(), entry_policy={'intent': 'Scenario scope is explicitly confirmed.'},
        exit_policy={'verification': 'An independent delivery campaign remains deferred.'},
        risk_disposition='Integer overflow compatibility remains an explicitly bounded delivery risk.'), actor='human')
    ChangeControlService(ledger).link_change_milestone(*ids[:2], milestone['milestone_id'], actor='human')
    return milestone


def test_export_resolves_governing_milestone_context_without_creating_unit_obligations(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    milestone = governing_milestone(ledger, ids)
    accepted_plan = ledger.packet_work_plan_state(*ids)

    def forbidden(*_args, **_kwargs):
        raise AssertionError('Standalone milestone context invoked a provider')
    monkeypatch.setattr(ledger, 'packet_provider_binding', forbidden)
    exported = service.call(*ids, 'export_plan', actor='agent', request_id='milestone-context', payload=revs)
    repeated = service.call(*ids, 'export_plan', actor='agent', request_id='milestone-context-again', payload=revs)
    assert exported['content'] == repeated['content']
    assert exported['content_sha256'] == repeated['content_sha256']
    context = exported['content'].split('### Governing milestone', 1)[1].split('### In scope', 1)[0]
    for essential in [milestone['milestone_id'], milestone['name'],
                      milestone['entry_policy']['intent'], milestone['exit_policy']['verification'],
                      milestone['risk_disposition'], 'Requirement ids', 'Prerequisite requirement ids',
                      'milestone context and deferred lifecycle authority']:
        assert essential in context
    assert '**Status:**' not in context and 'Acceptance evidence' not in context and 'Created at' not in context
    mappings = ledger.artifact_generations(ids[0])[-1]['artifacts'][0]['mappings']
    assert {'canonical_kind': 'milestone', 'canonical_id': milestone['milestone_id'], 'source_anchor': ''} in mappings
    assert ledger.packet_work_plan_state(*ids) == accepted_plan
    todo = service.todo(*ids)
    assert todo['current_unit']['unit_key'] == 'producer'
    assert todo['deferred_verification'][0]['statement'] == 'Run the installed CLI with representative integers.'
    assert not any(v['statement'] == milestone['exit_policy']['verification']
                   for row in todo['todos'] for v in row['unit']['verifies'])


def test_milestone_semantic_policy_drift_stales_host_reports_without_spec_revision_change(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    milestone = governing_milestone(ledger, ids)
    original = report(service, ids, revs)
    service.call(*ids, 'report_outcome', actor='agent', request_id='before-policy-drift', payload=original)
    assert service.todo(*ids)['current_unit']['unit_key'] == 'consumer'
    # Milestone policies are currently immutable through authoring. Exercise
    # changed canonical repository authority at the same identity without
    # inventing a new public mutation or changing packet/plan revisions.
    revised = deepcopy(milestone)
    revised['exit_policy'] = {'verification': 'Compatibility now requires an independently approved overflow campaign.'}
    monkeypatch.setattr(ledger, 'milestones', lambda project_id: [revised])
    todo = service.todo(*ids)
    assert todo['authority_fingerprint'] != original['authority_fingerprint']
    assert (todo['spec_revision'], todo['plan_revision']) == (revs['expected_spec_revision'], revs['expected_plan_revision'])
    assert todo['current_unit']['unit_key'] == 'producer'
    assert todo['historical_reports'] == [original['report_key']]
    late = {**original, 'report_key': 'offline-old-policy'}
    historical = service.call(*ids, 'report_outcome', actor='agent', request_id='late-old-policy', payload=late)
    assert historical['status'] == 'historical'
    with pytest.raises(ChangeControlBlockedError, match='stale'):
        service.call(*ids, 'reconcile_outcome', actor='human', request_id='cannot-promote-old-policy',
            payload={**revs, 'report_key': original['report_key'], 'rationale': 'Old policy evidence cannot silently become current.'})


def test_milestone_status_acceptance_and_creation_noise_preserve_plan_authority(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    milestone = governing_milestone(ledger, ids)
    original = service.call(*ids, 'export_plan', actor='agent', request_id='planned-milestone', payload=revs)
    payload = report(service, ids, revs)
    service.call(*ids, 'report_outcome', actor='agent', request_id='before-acceptance', payload=payload)
    accepted = ledger.accept_milestone(ids[0], milestone['milestone_id'],
        acceptance_evidence=('human:fixture-acceptance',), actor='human', request_id='canonical-acceptance')
    assert accepted['status'] == 'accepted' and accepted['acceptance_evidence']
    noise = {**accepted, 'created_at': 'changed migration metadata', 'created_by': 'historical actor', 'request_id': 'other replay key'}
    monkeypatch.setattr(ledger, 'milestones', lambda project_id: [noise])
    current = service.call(*ids, 'export_plan', actor='agent', request_id='accepted-milestone', payload=revs)
    assert current['authority_fingerprint'] == original['authority_fingerprint']
    assert current['content'] == original['content'] and current['content_sha256'] == original['content_sha256']
    assert service.todo(*ids)['current_unit']['unit_key'] == 'consumer'
    assert service.todo(*ids)['historical_reports'] == []
    assert service.todo(*ids)['acceptance'] == 'not_inferred'


def test_missing_linked_milestone_is_explicitly_blocked_and_exportable_only_as_draft(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    milestone = governing_milestone(ledger, ids)
    monkeypatch.setattr(ledger, 'milestones', lambda project_id: [])
    validation = service.validation(*ids, detail='full')
    assert validation['status'] == 'blocked' and not validation['plan_executable']
    assert validation['reason'] == 'milestone_authority_missing'
    assert {'code': 'milestone_authority_missing', 'reference': milestone['milestone_id']} in validation['validation']['gaps']
    assert service.todo(*ids)['status'] == 'blocked'
    with pytest.raises(ChangeControlBlockedError, match='milestone_authority_missing'):
        service.call(*ids, 'export_plan', actor='agent', request_id='missing-linked-milestone', payload=revs)
    draft = service.call(*ids, 'export_plan', actor='agent', request_id='draft-missing-milestone', payload={**revs, 'allow_draft': True})
    assert draft['draft'] and '**Validation:** open' in draft['content']
    assert 'milestone_authority_missing' in draft['content'] and milestone['milestone_id'] in draft['content']
    assert '### Governing milestone' not in draft['content']
    assert not any(m['canonical_kind'] == 'milestone' for m in ledger.artifact_generations(ids[0])[-1]['artifacts'][0]['mappings'])


def test_unlinked_plan_ignores_unrelated_milestones_and_preserves_export_identity(tmp_path, monkeypatch):
    ledger, service, ids, revs = fixture(tmp_path)
    original = service.call(*ids, 'export_plan', actor='agent', request_id='unlinked-original', payload=revs)
    requirement_id = ledger.change_state(*ids[:2])['requirement_ids'][0]
    ledger.promote_milestone(ids[0], MilestoneDraft(name='Unrelated canonical milestone', requirement_ids=(requirement_id,),
        prerequisite_requirement_ids=(), entry_policy={'intent': 'Different delivery'},
        exit_policy={'check': 'Different verification'}, risk_disposition='Unrelated risk'), actor='human')
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Unlinked packet consulted unrelated milestones')
    monkeypatch.setattr(ledger, 'milestones', forbidden)
    current = service.call(*ids, 'export_plan', actor='agent', request_id='unlinked-current', payload=revs)
    assert current['authority_fingerprint'] == original['authority_fingerprint']
    assert current['content'] == original['content'] and current['content_sha256'] == original['content_sha256']
    assert '### Governing milestone' not in current['content']
    assert service.todo(*ids)['current_unit']['unit_key'] == 'producer'
