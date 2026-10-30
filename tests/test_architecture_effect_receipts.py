"""Only pure pre-dispatch rejection carries architecture no-effect proof."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp.core.errors import OperationPreEffectError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_architecture


@pytest.fixture
def runtime(tmp_path):
    value = build_runtime(database_path=tmp_path / 'owned.sqlite3', import_root=tmp_path)
    value.requirements.create_project('owned', 'Owned architecture regression', actor='engineer')
    yield value
    value.close()


def request():
    return {'project_id': 'owned', 'operation': 'propose', 'actor': 'engineer', 'request_id': 'original',
            'payload': {'expected_revision': 0, 'definition': {'components': [
                {'id': 'Core', 'name': 'Core', 'responsibility': 'Own state', 'boundaries': ['One writer'],
                 'invariants': [], 'links': []}], 'interfaces': [], 'decisions': []}}}


def snapshot(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


def none(response, args, field):
    correlation = {key: args[key] for key in ('project_id', 'operation', 'request_id')}
    correlation['tool'] = 'fow_architecture'
    assert response['status'] == 'rejected'
    assert response['audit_reference'] == correlation
    result = response['result']
    assert result['operation_state'] == 'rejected' and result['effect_state'] == 'none'
    assert result['effect_receipt'] == {'contract_version': 'flow.operation-effect.v1', **correlation,
                                      'basis': 'pre_effect_validation', 'mutation_started': False}
    assert result['diagnostics'][0]['field'] == field
    assert result['next_tool_call']['arguments']['operation_name'] == args['operation']


@pytest.mark.parametrize('case,field', [('boundaries', 'payload.definition'), ('unknown', 'payload'),
    ('revision', 'payload.expected_revision'), ('actor', 'actor'), ('request_id', 'request_id'),
    ('project', 'project_id'), ('payload', 'payload')])
def test_invalid_input_never_dispatches_and_preserves_full_ledger(runtime, monkeypatch, case, field):
    args = request()
    if case == 'boundaries': args['payload']['definition']['components'][0]['boundaries'] = 'wrong string'
    elif case == 'unknown': args['payload']['unexpected'] = True
    elif case == 'revision': args['payload']['expected_revision'] = True
    elif case in {'actor', 'request_id'}: args[case] = ''
    elif case == 'project': args['project_id'] = 'Bad Project'
    else: args['payload'] = []
    before = snapshot(runtime)
    monkeypatch.setattr(runtime.architecture, 'call', lambda *a, **k: pytest.fail('invalid input dispatched'))
    none(handle_architecture(runtime, **args), args, field)
    assert snapshot(runtime) == before


@pytest.mark.parametrize('payload,field', [({'revision': True, 'expected_revision': 0, 'rationale': 'x'}, 'payload.revision'),
    ({'revision': 1, 'expected_revision': 0, 'rationale': ''}, 'payload.rationale')])
def test_adopt_structural_rejection_is_pure(runtime, payload, field):
    args = {**request(), 'operation': 'adopt', 'payload': payload}
    before = snapshot(runtime)
    none(handle_architecture(runtime, **args), args, field)
    assert snapshot(runtime) == before


@pytest.mark.parametrize('late', ['value', 'typed', 'commit', 'projection'])
def test_dispatched_failures_never_certify_none(runtime, monkeypatch, late):
    args = request()
    original = runtime.architecture.call
    def failed(*a, **k):
        if late == 'commit': original(*a, **k)
        if late == 'typed':
            raise OperationPreEffectError('not-proof-here', 'late error', field='payload', received_value=None,
                rule='x', resolution='x')
        raise ValueError('unproved dispatched failure')
    if late == 'projection':
        import flow_of_work_mcp.server as server
        monkeypatch.setattr(server, '_standalone_receipt', lambda *a, **k: (_ for _ in ()).throw(ValueError('projection')))
    else:
        monkeypatch.setattr(runtime.architecture, 'call', failed)
    response = handle_architecture(runtime, **args)
    assert response['result']['effect_state'] == 'unknown'
    assert 'effect_receipt' not in response['result']


def test_rejection_does_not_erase_prior_effect_and_exact_replay_stays_original(runtime):
    args = request()
    original = handle_architecture(runtime, **args)
    assert original['status'] == 'success'
    before = snapshot(runtime)
    malformed = deepcopy(args)
    malformed['payload']['definition']['components'][0]['boundaries'] = 'invalid'
    none(handle_architecture(runtime, **malformed), malformed, 'payload.definition')
    assert snapshot(runtime) == before
    assert handle_architecture(runtime, **args) == original
    changed = deepcopy(args)
    changed['actor'] = 'other'
    assert handle_architecture(runtime, **changed)['result']['effect_state'] == 'unknown'
    assert snapshot(runtime) == before


def test_failure_after_insert_inside_transaction_is_unknown_even_when_rolled_back(runtime, monkeypatch):
    before = snapshot(runtime)
    original = runtime.ledger._architecture_record_request
    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('failed after architecture insert and event')
    monkeypatch.setattr(runtime.ledger, '_architecture_record_request', fail_after_write)
    result = handle_architecture(runtime, **request())
    assert result['result']['effect_state'] == 'unknown'
    assert 'effect_receipt' not in result['result']
    assert snapshot(runtime) == before
