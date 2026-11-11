"""Only pure pre-dispatch rejection carries architecture no-effect proof."""
from copy import deepcopy
import asyncio
import sqlite3

import pytest

from flow_of_work_mcp.core.domain.external_work import CONTRACT_KINDS
from flow_of_work_mcp.core.errors import OperationPreEffectError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import create_app, handle_architecture, handle_capabilities


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


def test_proposal_reports_missing_fields_for_all_entity_types_before_dispatch(runtime, monkeypatch):
    args = request()
    definition = args['payload']['definition']
    del definition['components'][0]['links']
    definition['interfaces'] = [{
        'id': 'Output', 'name': 'Output', 'kind': 'api', 'provider_component_id': 'Core',
    }]
    definition['decisions'] = [{
        'id': 'Ownership', 'statement': 'Core owns the output', 'rationale': 'One writer',
    }]
    before = snapshot(runtime)
    with monkeypatch.context() as patch:
        patch.setattr(runtime.architecture, 'call', lambda *a, **k: pytest.fail('invalid input dispatched'))
        rejected = handle_architecture(runtime, **args)
    none(rejected, args, 'payload.definition')
    rows = rejected['result']['diagnostics'][0]['missing_entity_fields']
    assert [(row['path'], row['entity_id']) for row in rows] == [
        ('payload.definition.components[0]', 'Core'),
        ('payload.definition.interfaces[0]', 'Output'),
        ('payload.definition.decisions[0]', 'Ownership'),
    ]
    assert rows[0]['missing_fields'] == rows[0]['empty_list_fields'] == ['links']
    assert rows[1]['missing_fields'] == ['clauses', 'compatibility', 'consumer_component_ids', 'failure_contract', 'links']
    assert rows[1]['empty_list_fields'] == ['compatibility', 'failure_contract', 'links']
    assert rows[2]['missing_fields'] == ['component_ids', 'interface_ids', 'links', 'supersedes_decision_id']
    assert rows[2]['empty_list_fields'] == ['component_ids', 'interface_ids', 'links']
    assert snapshot(runtime) == before
    markdown = project_markdown('fow_architecture', rejected, arguments={'operation': 'propose'})
    assert all(row['path'] in markdown for row in rows)
    assert 'Use []' in markdown and 'supersedes_decision_id' in markdown
    assert '```json' not in markdown

    definition['components'][0]['links'] = []
    definition['interfaces'][0].update(clauses=['Return the output'], compatibility=[],
                                      consumer_component_ids=['Core'], failure_contract=[], links=[])
    definition['decisions'][0].update(component_ids=['Core'], interface_ids=['Output'],
                                     links=[], supersedes_decision_id='')
    assert handle_architecture(runtime, **args)['status'] == 'success'


def test_exact_proposal_help_starts_with_minimum_shape_and_preserves_machine_contract(runtime):
    async def run():
        app = create_app(runtime)
        response = await app.call_tool('fow_capabilities', {
            'view': 'operation', 'operation_tool': 'fow_architecture', 'operation_name': 'propose',
        })
        result = response.structuredContent['result']['result']
        contract = result['operation_contract']
        markdown = response.content[0].text
        assert markdown.startswith('# Flower Architecture: propose\n\n## Minimum definition shape')
        assert len(markdown) < 3500 and '```json' not in markdown
        for fields in contract['guidance']['entity_fields'].values():
            assert all(f'`{field}`' in markdown for field in fields)
        assert contract['example']['payload']['definition']['components']
        assert result == handle_capabilities(runtime, view='operation', operation_tool='fow_architecture',
                                             operation_name='propose')['result']

    asyncio.run(run())


def test_export_returns_a_complete_native_document_and_pinned_machine_data(runtime):
    async def run():
        app = create_app(runtime)
        args = request()
        narrative = '# Operating notes\n\n' + 'é' * 4000 + '\n\n~~~mermaid\ngraph LR\nA --> B\n~~~\n'
        args['payload']['definition']['markdown'] = narrative
        proposal = await app.call_tool('fow_architecture', args)
        revision = proposal.structuredContent['result']['result']['revision']
        export = await app.call_tool('fow_architecture', {
            'project_id': 'owned', 'operation': 'export', 'payload': {'revision': revision},
        })
        envelope = export.structuredContent['result']
        document = envelope['result']
        assert envelope['status'] == 'success' and document['revision'] == revision
        assert document['state'] == 'proposed'
        assert document['definition']['markdown'] == narrative
        assert document['markdown'].endswith(narrative)
        assert 'Own state' in document['markdown']
        assert export.content[0].text == document['markdown']
        assert project_markdown('fow_architecture', envelope, arguments={'operation': 'export'},
                                output_budget=1024) == document['markdown']

    asyncio.run(run())


@pytest.mark.parametrize('narrative', [None, 'é' * (32 * 1024 + 1), '\ud800'])
def test_invalid_narrative_reports_exact_field_without_dispatch(runtime, monkeypatch, narrative):
    args = request()
    args['payload']['definition']['markdown'] = narrative
    before = snapshot(runtime)
    monkeypatch.setattr(runtime.architecture, 'call', lambda *a, **k: pytest.fail('invalid input dispatched'))
    result = handle_architecture(runtime, **args)
    none(result, args, 'payload.definition.markdown')
    assert snapshot(runtime) == before


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


@pytest.mark.parametrize('received', ['http_api', 7])
def test_interface_kind_reports_input_index_entity_and_vocabulary_before_dispatch(runtime, monkeypatch, received):
    args = request()
    definition = args['payload']['definition']
    interface = {'id': 'Z-first', 'name': 'Local API', 'provider_component_id': 'Core',
                 'consumer_component_ids': ['Core'], 'kind': 'api', 'clauses': ['Own state'],
                 'failure_contract': [], 'compatibility': [], 'links': []}
    definition['interfaces'] = [interface, {**interface, 'id': 'A-second', 'kind': received}]
    field = 'payload.definition.interfaces[1].kind'
    accepted = sorted(CONTRACT_KINDS)
    before = snapshot(runtime)
    with monkeypatch.context() as patch:
        patch.setattr(runtime.architecture, 'call', lambda *a, **k: pytest.fail('invalid enum dispatched'))
        rejection = handle_architecture(runtime, **args)
    none(rejection, args, field)
    assert rejection['reason'] == 'architecture_input_invalid'
    diagnostic = rejection['result']['diagnostics'][0]
    assert diagnostic['entity_id'] == 'A-second'
    assert diagnostic['received_value'] == received
    assert diagnostic['accepted_values'] == accepted
    assert snapshot(runtime) == before
    markdown = project_markdown('fow_architecture', rejection, arguments={'operation': 'propose'})
    assert field in markdown and 'A-second' in markdown and str(received) in markdown
    assert all(kind in markdown for kind in accepted)

    help_args = {'view': 'operation', 'operation_tool': 'fow_architecture', 'operation_name': 'propose'}
    help_result = handle_capabilities(runtime, **help_args)
    help_field = 'payload.definition.interfaces[].kind'
    assert help_result['result']['operation_contract']['accepted_values'][help_field] == accepted
    help_markdown = project_markdown('fow_capabilities', help_result, arguments=help_args)
    assert help_field in help_markdown and all(kind in help_markdown for kind in accepted)

    definition['interfaces'][1]['kind'] = ' protocol '
    proposal = handle_architecture(runtime, **args)
    assert proposal['status'] == 'success'
    inspect = handle_architecture(runtime, project_id='owned', operation='inspect',
                                  payload={'revision': proposal['result']['revision'], 'kind': 'interface'})
    assert [(item['entity']['id'], item['entity']['kind']) for item in inspect['result']['items']] == [
        ('A-second', 'protocol'), ('Z-first', 'api'),
    ]


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
