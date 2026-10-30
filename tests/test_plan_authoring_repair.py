"""Engineering preparation continues while PVP holds repository effects."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp import WorkPlanUnit
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.lifecycle_recipes import get_recipe
from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.model_facing import project_markdown
from tests.test_external_work import fixture


def dump(ledger):
    with sqlite3.connect(ledger.database_path) as connection:
        return tuple(connection.iterdump())


def plans(ledger):
    return PacketWorkPlanService(ledger, changes=ledger, navigation=ledger)


def revise(ledger, ids, units, *, accept=True):
    service = plans(ledger)
    old = ledger.packet_work_plan_state(*ids)
    current = ExternalWorkService(ledger)._snapshot(*ids)['packet']
    new = service.set_plan(*ids, {'units': units}, expected_packet_revision=current['spec_revision'],
        expected_current_plan_revision=old['plan_revision'], actor='engineer', request_id='deliberate-plan-change')
    if accept:
        service.accept(*ids, plan_revision=new['plan_revision'], expected_packet_revision=new['packet_revision'],
            expected_current_plan_revision=new['plan_revision'], rationale='Reviewed investigated declarations.',
            actor='engineer', request_id='accept-deliberate-plan-change')
    return new


def missing_local(ledger, ids, *, accept=True):
    units = deepcopy(ledger.packet_work_plan_state(*ids)['units'])
    # Deferred intent is legitimate, but cannot satisfy the existing local check.
    units[0]['verifies'] = [v for v in units[0]['verifies'] if v['kind'] != 'unit_check']
    return revise(ledger, ids, units, accept=accept)


@pytest.mark.parametrize('operation', ['replace_plan', 'revise_unit'])
def test_exact_authoring_help_has_real_shapes_and_correspondence(operation):
    contract = operation_contract('fow_packet_author', operation)
    guidance = contract['guidance']['work_plan']['unit'] if operation == 'replace_plan' else contract['guidance']['unit']
    assert 'same-unit' in guidance['verification_correspondence']
    assert 'criterion prose' in guidance['verification_correspondence']
    assert 'implements does not determine' in guidance['verification_correspondence']
    assert 'whole arrays' in guidance['authoring_cycle'] and 'proposed plan' in guidance['authoring_cycle']
    example = contract['example']
    assert example['expected_spec_revision'] > 0 and example['expected_plan_revision'] > 0
    if operation == 'replace_plan':
        unit = example['work_plan']['units'][0]
        WorkPlanUnit(**unit)
        assert unit['unit_checks'][0] == unit['verifies'][0]['statement']
        assert unit['implements'] == [unit['verifies'][0]['criterion']]
    else:
        assert example['unit_patch']['verifies'][0]['kind'] == 'unit_check'
        assert 'entire previous array' in contract['guidance']['unit_patch']['patch_rule']


@pytest.mark.parametrize('accepted', [True, False])
def test_real_missing_local_read_preserves_pvp_and_all_state(tmp_path, accepted):
    ledger, external, ids, _ = fixture(tmp_path)
    missing_local(ledger, ids, accept=accepted)
    before = dump(ledger)
    projection = external._projection(external._snapshot(*ids))
    todo = external.todo(*ids)
    validation = external.validation(*ids, detail='full')
    assert todo['status'] == 'blocked' and todo['execution_allowed'] is False
    assert validation['execution_allowed'] is False and todo['validation'] == projection
    if not accepted:
        assert projection['next_gap']['code'] == 'work_plan_not_accepted'
    repair = todo['next_gate']['repair']
    assert repair == validation['next_gate']['repair']
    assert repair['obligation']['code'] == 'unit_check_verification_missing'
    assert todo['next_gate']['obligation'] == projection['next_gap']
    assert repair['contract_version'] == 'flow.plan-authoring-repair.v1'
    assert repair['ready_to_call'] is False and repair['execution_allowed'] is False
    args = repair['operation']['arguments']
    assert args['client_unit_key'] == 'producer'
    assert args['expected_plan_revision'] == projection['plan_revision']
    assert args['expected_spec_revision'] == projection['spec_revision']
    assert not {'unit_patch', 'criterion', 'actor', 'request_id'} & args.keys()
    assert set(repair['required_input']) == {'unit_patch', 'actor', 'request_id'}
    assert repair['help_route']['arguments']['operation_name'] == 'revise_unit'
    assert repair['inspection_route']['arguments']['payload']['detail'] == 'full'
    assert todo['next_gate']['tool'] == 'fow_external_work' and todo['next_gate']['operation'] == 'validation'
    assert todo['next_gate']['authority_fingerprint'] == projection['authority_fingerprint']
    markdown = project_markdown('fow_external_work', {'status': 'blocked', 'result': todo}, arguments={'operation': 'todo'})
    assert 'flow.plan-authoring-repair.v1' in markdown and 'revise_unit' in markdown
    assert dump(ledger) == before


@pytest.mark.parametrize('code', ['criterion_owner_missing', 'verification_intent_missing', 'planned_contract_missing'])
def test_ambiguous_repair_never_chooses_owner_or_contract_side(tmp_path, code):
    ledger, external, ids, _ = fixture(tmp_path)
    snapshot = external._snapshot(*ids)
    projection = external._projection(snapshot)
    gap = {'code': code, 'criterion': 2} if 'criterion' in code or code == 'verification_intent_missing' else {
        'code': code, 'unit_key': 'consumer', 'producer_unit_key': 'producer', 'contract_name': 'absent'}
    projection.update(status='open', gaps=[gap], next_gap=gap)
    before = deepcopy(projection)
    repair = external._validation_gate(projection, snapshot)['repair']
    assert 'client_unit_key' not in repair['operation']['arguments']
    assert 'client_unit_key' in repair['required_input']
    assert 'unit_patch' not in repair['operation']['arguments']
    assert projection == before


@pytest.mark.parametrize('kind', ['inactive', 'unknown', 'accepted_with_no_declaration_gap'])
def test_no_new_mutation_hint_for_other_authority_states(tmp_path, kind):
    ledger, external, ids, _ = fixture(tmp_path)
    snapshot = external._snapshot(*ids)
    projection = external._projection(snapshot)
    gap = {'code': 'unit_check_verification_missing', 'unit_key': 'producer'}
    if kind == 'inactive':
        snapshot['packet']['status'] = 'cancelled'
    elif kind == 'unknown':
        gap = {'code': 'unknown_future_authority'}
    else:
        gap = {'code': 'work_plan_not_accepted'}
    projection.update(status='open', gaps=[gap], next_gap=gap)
    assert 'repair' not in external._validation_gate(projection, snapshot)


def test_explicit_targeted_repair_preserves_arrays_reaccepts_and_rejects_old_cas(tmp_path):
    ledger, external, ids, _ = fixture(tmp_path)
    missing_local(ledger, ids)
    state = ledger.packet_work_plan_state(*ids)
    previous_consumer = deepcopy(state['units'][1])
    verifies = deepcopy(state['units'][0]['verifies'])
    check = state['units'][0]['unit_checks'][0]
    # This mapping is an explicit fixture engineering decision, never hint output.
    verifies.append({'criterion': 1, 'kind': 'unit_check', 'statement': check})
    arguments = dict(operation='revise_unit', client_unit_key='producer', unit_patch={'verifies': verifies},
        expected_packet_revision=state['packet_revision'], expected_current_plan_revision=state['plan_revision'],
        actor='engineer', request_id='explicit-targeted-repair')
    service = plans(ledger)
    proposed = service.mutate_plan(*ids, **arguments)
    assert external.todo(*ids)['reason'] == 'work_plan_not_accepted'
    current = ledger.packet_work_plan_state(*ids)
    assert current['units'][1] == previous_consumer
    assert current['units'][0]['verifies'] == verifies
    assert any(v['kind'] == 'live_campaign' for v in verifies)
    before = dump(ledger)
    with pytest.raises(ChangeControlBlockedError, match='stale_current_work_plan_revision'):
        service.mutate_plan(*ids, **{**arguments, 'request_id': 'old-cas-new-request'})
    assert dump(ledger) == before
    service.accept(*ids, plan_revision=proposed['plan_revision'], expected_packet_revision=proposed['packet_revision'],
        expected_current_plan_revision=proposed['plan_revision'], rationale='Reviewed the deliberate criterion mapping.',
        actor='engineer', request_id='accept-targeted-repair')
    assert external.validation(*ids)['validation']['status'] == 'closed'
    assert external.todo(*ids)['status'] == 'success'


def test_draft_and_closed_exports_carry_self_contained_preparation_policy(tmp_path):
    ledger, external, ids, revs = fixture(tmp_path)
    closed = external.call(*ids, 'export_plan', actor='engineer', request_id='closed-export', payload=revs)['content']
    proposed = missing_local(ledger, ids)
    payload = {'expected_spec_revision': proposed['packet_revision'], 'expected_plan_revision': proposed['plan_revision']}
    with pytest.raises(ChangeControlBlockedError, match='unit_check_verification_missing'):
        external.call(*ids, 'export_plan', actor='engineer', request_id='blocked-export', payload=payload)
    draft = external.call(*ids, 'export_plan', actor='engineer', request_id='draft-export', payload={**payload, 'allow_draft': True})['content']
    assert 'DRAFT / NOT EXECUTABLE' in draft and 'DRAFT / NOT EXECUTABLE' not in closed
    for content in [draft, closed]:
        assert 'Engineering authoring while execution is held' in content
        assert 'editing this markdown never changes canonical authority' in content.lower()
        assert 'exact same-unit verifies' in content and 'implements does not choose' in content
        assert 'Execute only a closed accepted issued plan' in content
        assert 'proposed technical declarations' in content
    recipe = get_recipe('standalone-external-plan')
    assert any('continue engineering authoring within confirmed intent' in condition for condition in recipe['stop_conditions'])


def test_revise_unit_failure_preserves_prior_effect_and_unknown_correlation(tmp_path, monkeypatch):
    import flow_of_work_mcp.server as server
    effect = tmp_path / 'maintenance.txt'

    def late_failure(*args, **kwargs):
        effect.write_text('Ancillary repair already occurred.')
        raise ChangeControlBlockedError('stale_current_work_plan_revision')

    monkeypatch.setattr(server, '_execute_packet_command', late_failure)
    result = server.handle_packet_author(object(), operation='revise_unit', project_id='owned',
        packet_id='PACKET-000001', client_unit_key='producer', unit_patch={'verifies': []},
        expected_plan_revision=1, actor='engineer', request_id='retained-original')
    assert result['status'] == 'blocked' and result['reason'] == 'stale_current_work_plan_revision'
    assert effect.read_text() == 'Ancillary repair already occurred.'
    assert result['result']['effect_state'] == 'unknown'
    assert 'effect_receipt' not in result['result']
    assert result['result']['original_request'] == {'tool': 'fow_packet_author', 'operation': 'revise_unit',
        'project_id': 'owned', 'request_id': 'retained-original'}
