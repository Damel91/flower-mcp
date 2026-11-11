"""Pure PVP topology/currentness matrix, independent of runtime integrations."""
from copy import deepcopy

import pytest

from flow_of_work_mcp.core.domain.external_work import fingerprint, normalize_declarations
from flow_of_work_mcp.core.domain.packet_validation_projection import (
    CRITERION_RESPONSIBILITY_GAPS, derive_packet_validation,
)


def snapshot():
    criteria = [{'number': 1, 'statement': 'Exact protocol', 'active': 1}]
    unit = {'unit_number': 1, 'client_unit_key': 'producer', 'depends_on': [], 'implements': [1],
            'unit_checks': ['local'], 'provides': [{'name': 'shape', 'kind': 'data_shape', 'clauses': ['a and b are independent']}],
            'requires': [], 'verifies': [{'criterion': 1, 'kind': 'unit_check', 'statement': 'local'},
                                        {'criterion': 1, 'kind': 'oracle', 'statement': 'Check independent dimensions under accepted stimulus.'}]}
    return {'packet': {'spec_revision': 2, 'objective': 'Independent protocol', 'rationale': 'Bounded',
                       'in_scope': ['one module'], 'invariants': ['two independent fields'], 'completion_criteria': ['Exact protocol']},
            'plan': {'packet_revision': 2, 'plan_revision': 1, 'status': 'accepted', 'units': [unit]},
            'external': {'validation_version': 1, 'criterion_statement_fingerprint': fingerprint(['Exact protocol']), 'criteria': criteria},
            'resolved_authorities': {}, 'authority_basis': {'packet_revision': 2, 'plan_revision': 1}}


def test_closed_future_contract_needs_no_file_symbol_or_provider():
    value = snapshot()
    value['plan']['units'][0]['provides'][0].update({'file_path': 'future/a.py', 'symbol': 'future_symbol'})
    pvp = derive_packet_validation(value)
    assert pvp['status'] == 'closed'
    assert pvp['contract_version'] == 'flow.external_packet_validation_projection.v1'
    assert pvp['consumer_scope'] == 'external_agent'
    assert pvp['verification_claim'] == 'plan_constructibility_only'
    assert any(v['kind'] == 'oracle' for v in pvp['criteria'][0]['verification'])
    assert derive_packet_validation(value) == pvp


def test_multiple_consumers_use_single_canonical_producer_clauses():
    value = snapshot()
    for key in ('left', 'right'):
        value['plan']['units'].append({'unit_number': len(value['plan']['units']) + 1, 'client_unit_key': key,
            'depends_on': ['producer'], 'implements': [], 'unit_checks': [], 'provides': [],
            'requires': [{'producer_unit_key': 'producer', 'contract_name': 'shape', 'use': 'Consume both fields'}], 'verifies': []})
    pvp = derive_packet_validation(value)
    assert pvp['status'] == 'closed'
    for unit in pvp['units'][1:]:
        assert unit['resolved_requires'][0]['contract']['clauses'] == ['a and b are independent']
        assert unit['resolved_requires'][0]['temporal_state'] == 'planned'


@pytest.mark.parametrize('mutation,reason', [
    (lambda v: v['plan']['units'][0].update(implements=[], verifies=[]), 'criterion_owner_missing'),
    (lambda v: v['plan']['units'][0].update(verifies=[]), 'verification_intent_missing'),
    (lambda v: v['plan']['units'][0].update(implements=[5]), 'criterion_unknown_or_retired'),
    (lambda v: v['packet'].update(completion_criteria=['Changed text']), 'criterion_authority_stale'),
    (lambda v: v['external'].update(validation_version=0), 'packet_validation_upgrade_required'),
    (lambda v: v['plan'].update(packet_revision=1), 'work_plan_stale'),
    (lambda v: v['plan'].update(status='proposed'), 'work_plan_not_accepted'),
    (lambda v: v['packet'].update(unresolved_questions=['Unapproved invariant']), 'packet_unresolved_authority_questions'),
    (lambda v: v['plan']['units'][0].update(unit_checks=['missing local intent']), 'unit_check_verification_missing'),
    (lambda v: v['plan']['units'][0].update(mutation_target_binding_id='opaque-target'), 'portable_target_context_missing'),
    (lambda v: v['plan']['units'][0].update(context_target_binding_ids=['opaque-context']), 'portable_context_content_missing'),
    (lambda v: v['plan']['units'][0].update(depends_on=['producer']), 'dependency_cycle'),
])
def test_missing_stale_historical_and_authority_boundaries_fail_closed(mutation, reason):
    value = snapshot()
    mutation(value)
    pvp = derive_packet_validation(value)
    assert pvp['status'] != 'closed'
    assert reason in {g['code'] for g in pvp['gaps']}


@pytest.mark.parametrize('producer,dependencies,reason', [('absent', [], 'planned_contract_missing'), ('producer', [], 'contract_not_in_dependency_closure')])
def test_contract_topology_requires_exact_predecessor(producer, dependencies, reason):
    value = snapshot()
    value['plan']['units'].append({'unit_number': 2, 'client_unit_key': 'consumer', 'depends_on': dependencies,
        'unit_checks': [], 'implements': [], 'provides': [], 'verifies': [],
        'requires': [{'producer_unit_key': producer, 'contract_name': 'shape', 'use': 'Use both dimensions.'}]})
    pvp = derive_packet_validation(value)
    assert reason in {g['code'] for g in pvp['gaps']}


def test_consumer_cannot_redefine_canonical_clauses_and_duplicate_names_reject():
    for declaration in [
        {'requires': [{'producer_unit_key': 'producer', 'contract_name': 'shape', 'use': 'Read', 'clauses': ['competing copy']}]},
        {'provides': [{'name': 'shape', 'kind': 'api', 'clauses': ['a']}, {'name': 'shape', 'kind': 'protocol', 'clauses': ['b']}]},
        {'verifies': [{'criterion': True, 'kind': 'unit_check', 'statement': 'Invalid ordinal'}]},
        {'requires': [{'producer_unit_key': 'producer', 'contract_name': 'shape'}]},
        {'provides': [{'name': 'shape', 'kind': 'api', 'clauses': ['a'], 'file_path': '../escape.py'}]},
    ]:
        with pytest.raises(ValueError):
            normalize_declarations(declaration)


def test_explicit_authority_requires_included_authoritative_content():
    value = snapshot()
    value['plan']['units'][0]['verifies'].append({'criterion': 1, 'kind': 'explicit_authority', 'statement': 'Approved exception', 'authority_ref': 'decision:bounded'})
    assert derive_packet_validation(value)['next_gap'] == {
        'code': 'external_authority_missing', 'unit_key': 'producer', 'authority_ref': 'decision:bounded',
    }
    value['resolved_authorities']['decision:bounded'] = {'content': 'The accepted exception is bounded to this unit.', 'provenance': 'human'}
    assert derive_packet_validation(value)['status'] == 'closed'


def test_structural_closure_does_not_treat_campaign_oracle_as_local_check():
    value = snapshot()
    pvp = derive_packet_validation(value)
    assert pvp['units'][0]['unit_checks'] == ['local']
    assert pvp['criteria'][0]['verification'][1]['kind'] == 'oracle'
    assert 'Check independent dimensions' not in ' '.join(pvp['units'][0]['unit_checks'])


def test_provider_only_construction_questions_do_not_block_standalone_authority():
    value = snapshot()
    value['construction'] = {'packet_revision': 1, 'questions': [
        {'question_id': 'opaque-target', 'question_key': 'target_selection', 'required': True, 'status': 'open'},
        {'question_id': 'opaque-impact', 'question_key': 'impact', 'required': True, 'status': 'open'}]}
    assert derive_packet_validation(value)['status'] == 'closed'
    value['construction']['questions'].append({'question_id': 'invariant', 'question_key': 'invariant_confirmation', 'required': True, 'status': 'open'})
    projection = derive_packet_validation(value)
    assert projection['status'] == 'stale'
    assert {'engineering_answer_missing', 'engineering_answers_stale'}.issubset({gap['code'] for gap in projection['gaps']})


def strict_snapshot():
    value = snapshot()
    value['packet_id'] = 'PACKET-000002'
    value['packet']['packet_id'] = value['packet_id']
    value['external'].update(validation_version=2, consumption_mode='external_agent',
                             criterion_dispositions=[{'number': 1, 'disposition': 'implementation'}])
    return value


def _set_criteria(value, statements):
    value['packet']['completion_criteria'] = statements
    value['external'].update(criterion_statement_fingerprint=fingerprint(statements), criteria=[
        {'number': number, 'statement': statement, 'active': 1}
        for number, statement in enumerate(statements, start=1)
    ])


def _verifier(number, *, depends_on=(), key='verify'):
    return {'client_unit_key': key, 'depends_on': list(depends_on), 'implements': [],
            'unit_checks': [], 'verifies': [{'criterion': number, 'kind': 'live_campaign',
                                            'statement': 'Exercise the observable behavior.'}]}


def test_strict_policy_blocks_r3_label_only_shape_and_preserves_legacy_projection():
    value = strict_snapshot()
    _set_criteria(value, [f'REQ-{number:06d}' for number in range(1, 19)])
    value['external']['criterion_dispositions'] = []
    unit = value['plan']['units'][0]
    checks = [f'Local check {number}' for number in range(1, 19)]
    unit.update(implements=[], unit_checks=checks, verifies=[
        {'criterion': number, 'kind': 'unit_check', 'statement': statement}
        for number, statement in enumerate(checks, start=1)
    ])
    strict = derive_packet_validation(value)
    assert strict['status'] == 'open'
    assert strict['validation_version'] == 2
    for code in ('criterion_statement_id_only', 'criterion_disposition_missing'):
        assert code in CRITERION_RESPONSIBILITY_GAPS
        assert [gap['criterion'] for gap in strict['gaps'] if gap['code'] == code] == list(range(1, 19))
    legacy = deepcopy(value)
    legacy['external']['validation_version'] = 1
    legacy['external'].pop('criterion_dispositions')
    assert derive_packet_validation(legacy)['status'] == 'closed'
    assert derive_packet_validation(value, consumer_scope='provider') == derive_packet_validation(legacy, consumer_scope='provider')
    value['external']['consumption_mode'] = 'provider'
    assert derive_packet_validation(value) == derive_packet_validation(legacy)


def test_explicit_implementation_owner_and_verification_are_distinct_before_plan_acceptance():
    value = strict_snapshot()
    value['plan']['status'] = 'proposed'
    assert derive_packet_validation(value)['next_gap']['code'] == 'work_plan_not_accepted'
    assert derive_packet_validation(value, require_accepted_plan=False)['status'] == 'closed'
    value['plan']['units'][0]['implements'] = []
    projection = derive_packet_validation(value)
    assert projection['next_gap']['code'] == 'criterion_owner_missing'
    assert projection['criteria'][0]['disposition'] == 'implementation'
    assert projection['criteria'][0]['implementation_units'] == []
    assert derive_packet_validation(value, require_accepted_plan=False)['next_gap']['code'] == 'criterion_owner_missing'
    value['plan']['status'] = 'rejected'
    assert any(gap['code'] == 'work_plan_not_accepted'
               for gap in derive_packet_validation(value, require_accepted_plan=False)['gaps'])


def test_verification_only_targets_exact_same_packet_implementation_in_dependency_closure():
    value = strict_snapshot()
    _set_criteria(value, ['Publish the protocol', 'Independently verify the protocol'])
    declaration = {'number': 2, 'disposition': 'verification_only', 'target': {'kind': 'criterion', 'criterion': 1}}
    value['external']['criterion_dispositions'].append(declaration)
    value['plan']['units'].extend([_verifier(2, key='bridge', depends_on=['producer']), _verifier(2, depends_on=['bridge'])])
    closed = derive_packet_validation(value)
    assert closed['status'] == 'closed'
    assert closed['criteria'][1]['implementation_units'] == []
    assert closed['criteria'][1]['target'] == {'kind': 'criterion', 'criterion': 1}
    assert all(row['kind'] == 'live_campaign' for row in closed['criteria'][1]['verification'])
    value['plan']['units'][-1]['depends_on'] = []
    gap = derive_packet_validation(value)['next_gap']
    assert (gap['code'], gap['criterion'], gap['unit_key']) == ('criterion_verification_target_dependency_missing', 2, 'verify')
    declaration['target']['criterion'] = 2
    assert derive_packet_validation(value)['next_gap']['code'] == 'criterion_verification_target_invalid'
    declaration['target']['criterion'] = 1
    value['plan']['units'][-1]['implements'] = [2]
    assert 'criterion_implementation_owner_unexpected' in {gap['code'] for gap in derive_packet_validation(value)['gaps']}


def test_verification_only_requires_exact_recorded_change_baseline():
    value = strict_snapshot()
    value['change'] = {'baseline_refs': ['baseline:tested-service']}
    declaration = {'number': 1, 'disposition': 'verification_only', 'target': {'kind': 'baseline', 'ref': 'baseline:tested-service'}}
    value['external']['criterion_dispositions'] = [declaration]
    value['plan']['units'] = [_verifier(1)]
    assert derive_packet_validation(value)['status'] == 'closed'
    declaration['target']['ref'] = 'baseline:similar-service'
    assert derive_packet_validation(value)['next_gap']['code'] == 'criterion_verification_target_invalid'


@pytest.mark.parametrize('predecessor_version', [1, 2])
def test_verification_only_targets_current_declared_predecessor_with_implementing_owner(predecessor_version):
    value = strict_snapshot()
    value['external']['criterion_dispositions'] = [{
        'number': 1, 'disposition': 'verification_only',
        'target': {'kind': 'criterion', 'packet_id': 'PACKET-000001', 'criterion': 1},
    }]
    value['plan']['units'] = [_verifier(1)]
    predecessor = strict_snapshot() if predecessor_version == 2 else snapshot()
    predecessor['packet_id'] = 'PACKET-000001'
    value['packet']['dependency_packet_ids'] = ['PACKET-000001']
    value['predecessor_packets'] = [predecessor]
    assert derive_packet_validation(value)['status'] == 'closed'
    undeclared = deepcopy(value)
    undeclared['packet']['dependency_packet_ids'] = []
    assert derive_packet_validation(undeclared)['next_gap']['code'] == 'criterion_verification_target_invalid'
    stale = deepcopy(value)
    stale['predecessor_packets'][0]['plan']['packet_revision'] -= 1
    assert derive_packet_validation(stale)['next_gap']['code'] == 'criterion_verification_target_invalid'
    if predecessor_version == 2:
        unclassified = deepcopy(value)
        unclassified['predecessor_packets'][0]['external']['criterion_dispositions'] = []
        assert derive_packet_validation(unclassified)['next_gap']['code'] == 'criterion_verification_target_invalid'
    predecessor['plan']['units'][0]['implements'] = []
    assert derive_packet_validation(value)['next_gap']['code'] == 'criterion_verification_target_invalid'


def test_explicit_authority_requires_accepted_answer_and_exact_deferred_verification():
    value = strict_snapshot()
    ref = 'decision:scoped-answer'
    value['external']['criterion_dispositions'] = [{
        'number': 1, 'disposition': 'external_authority', 'target': {'kind': 'authority', 'ref': ref},
    }]
    value['plan']['units'] = [_verifier(1)]
    intent = value['plan']['units'][0]['verifies'][0]
    value['resolved_authorities'][ref] = {'kind': 'campaign'}
    assert derive_packet_validation(value)['next_gap']['code'] == 'criterion_external_authority_unaccepted'
    value['resolved_authorities'][ref] = {'kind': 'accepted_engineering_answer', 'content': 'Bounded accepted answer.',
                                          'provenance': 'stakeholder'}
    assert derive_packet_validation(value)['next_gap']['code'] == 'criterion_external_authority_verification_missing'
    intent.update(kind='explicit_authority', authority_ref=ref)
    closed = derive_packet_validation(value)
    assert closed['status'] == 'closed'
    assert closed['criteria'][0]['verification'][0]['kind'] == 'explicit_authority'
    assert closed['units'][0]['unit_checks'] == []

    value['plan']['status'] = 'proposed'
    value['construction'] = {'packet_revision': value['packet']['spec_revision'] - 1, 'questions': [
        {'question_id': 'bounded-answer', 'question_key': 'invariant', 'required': True, 'status': 'answered'},
    ]}
    draft = derive_packet_validation(value, require_accepted_plan=False)
    assert [gap for gap in draft['gaps'] if gap['code'] in CRITERION_RESPONSIBILITY_GAPS] == [{
        'code': 'criterion_external_authority_unaccepted', 'criterion': 1, 'field': 'criteria.1.target',
        'authority_state': 'stale',
    }]
    value['construction']['packet_revision'] = value['packet']['spec_revision']
    assert derive_packet_validation(value, require_accepted_plan=False)['status'] == 'closed'
