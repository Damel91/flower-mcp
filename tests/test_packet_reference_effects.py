"""Malformed refs never enter repair; late failure never becomes no-effect."""
import asyncio
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp import GovernedChangeDraft, ImplementationPacketDraft, RequirementDraft
from flow_of_work_mcp.core.errors import OperationPreEffectError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app, handle_packet_author


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as c: return tuple(c.iterdump())


@pytest.fixture
def owned(tmp_path):
    runtime = build_runtime(database_path=tmp_path / 'owned.sqlite3', import_root=tmp_path)
    runtime.requirements.create_project('refs', 'Owned references', actor='engineer')
    requirement = runtime.requirements.register('refs', RequirementDraft(title='Reference ownership',
        statement='The software shall preserve selected architecture.', category='functional', rationale='Owned regression'), actor='engineer')
    change = runtime.changes.create_change('refs', GovernedChangeDraft(title='References', rationale='Bind architecture',
        requirement_ids=(requirement['requirement_id'],)), actor='engineer')
    packet = runtime.changes.add_packet('refs', change['change_id'], ImplementationPacketDraft(
        title='Refs', objective='Select authority', completion_criteria=('Refs selected',), target_policy='documental_only'), actor='engineer')['packets'][0]
    definition = {'components': [{'id': 'Core', 'name': 'Core', 'responsibility': 'Own state',
        'boundaries': ['One writer'], 'invariants': [], 'links': []}], 'interfaces': [], 'decisions': []}
    runtime.architecture.call('refs', 'propose', actor='engineer', request_id='arch-propose', payload={'expected_revision': 0, 'definition': definition})
    runtime.architecture.call('refs', 'adopt', actor='engineer', request_id='arch-adopt', payload={'expected_revision': 0, 'revision': 1, 'rationale': 'Investigated'})
    args = {'project_id': 'refs', 'change_id': change['change_id'], 'packet_id': packet['packet_id'],
            'actor': 'engineer', 'request_id': 'original', 'operation': 'revise_packet',
            'architecture_refs': [{'revision': 1, 'kind': 'component', 'entity_id': 'Core'}]}
    yield runtime, args
    runtime.close()


@pytest.mark.parametrize('refs', [[{'id': 'adapters', 'kind': 'component'}], 'wrong',
    [{'revision': True, 'kind': 'component', 'entity_id': 'Core'}],
    [{'revision': 1, 'kind': 'wrong', 'entity_id': 'Core'}],
    [{'revision': 1, 'kind': 'component', 'entity_id': 'Core', 'extra': 1}],
    [{'revision': 1, 'kind': 'component', 'entity_id': 'Core'}] * 2])
def test_malformed_refs_prove_none_before_address_or_ancillary_repair(owned, monkeypatch, refs):
    runtime, args = owned
    before = dump(runtime)
    import flow_of_work_mcp.server as server
    monkeypatch.setattr(server, '_resolve_packet_address', lambda *a, **k: pytest.fail('resolved before validation'))
    monkeypatch.setattr(runtime.packet_factory, 'ensure_packet_lifecycle', lambda *a, **k: pytest.fail('repair before validation'))
    args = {**args, 'architecture_refs': refs}
    response = handle_packet_author(runtime, **args)
    correlation = {key: args[key] for key in ('operation', 'project_id', 'request_id')}
    correlation['tool'] = 'fow_packet_author'
    assert response['status'] == 'rejected' and response['audit_reference'] == correlation
    result = response['result']
    assert result['effect_state'] == 'none' and result['operation_state'] == 'rejected'
    assert result['effect_receipt'] == {'contract_version': 'flow.operation-effect.v1', **correlation,
        'basis': 'pre_effect_validation', 'mutation_started': False}
    diagnostic = result['diagnostics'][0]
    assert diagnostic['field'] == 'architecture_refs'
    assert diagnostic['required_fields'] == ['revision', 'kind', 'entity_id']
    assert result['next_tool_call']['arguments']['operation_name'] == 'revise_packet'
    assert dump(runtime) == before


@pytest.mark.parametrize('failure', ['late_typed', 'after_repair_write', 'post_revision_projection'])
def test_dispatched_errors_preserve_unknown_and_prior_effects(owned, monkeypatch, failure):
    runtime, args = owned
    if failure == 'post_revision_projection':
        import flow_of_work_mcp.server as server
        monkeypatch.setattr(server, '_packet_author_continuation', lambda *a, **k: (_ for _ in ()).throw(ValueError('after revision')))
    else:
        def fail(*a, **k):
            if failure == 'after_repair_write':
                runtime.requirements.register('refs', RequirementDraft(title='Retained effect', statement='The system shall preserve state.',
                    category='functional', rationale='Late failure'), actor='engineer')
            raise OperationPreEffectError('late', 'not proof here', field='architecture_refs', received_value=None,
                                          rule='x', resolution='x')
        monkeypatch.setattr(runtime.packet_factory, 'ensure_packet_lifecycle', fail)
    before = dump(runtime)
    response = handle_packet_author(runtime, **args)
    assert response['result']['effect_state'] == 'unknown'
    assert 'effect_receipt' not in response['result']
    assert response['result']['original_request']['request_id'] == args['request_id']
    if failure in {'after_repair_write', 'post_revision_projection'}: assert dump(runtime) != before


def test_valid_revision_replay_omission_clear_and_invalid_prior_identity(owned):
    runtime, args = owned
    response = handle_packet_author(runtime, **args)
    assert response['status'] == 'success', response
    first = runtime.changes.get_change('refs', args['change_id'])['packets'][0]
    assert first['architecture_refs'] == args['architecture_refs']
    malformed = {**args, 'architecture_refs': [{'id': 'Core', 'kind': 'component'}]}
    before = dump(runtime)
    assert handle_packet_author(runtime, **malformed)['result']['effect_state'] == 'none'
    assert dump(runtime) == before
    assert handle_packet_author(runtime, **args)['status'] == 'success'
    assert runtime.changes.get_change('refs', args['change_id'])['packets'][0]['spec_revision'] == first['spec_revision']
    omitted = {k: v for k, v in args.items() if k != 'architecture_refs'}
    assert handle_packet_author(runtime, **{**omitted, 'title': 'Renamed', 'request_id': 'rename'})['status'] == 'success'
    assert runtime.changes.get_change('refs', args['change_id'])['packets'][0]['architecture_refs'] == args['architecture_refs']
    assert handle_packet_author(runtime, **{**args, 'request_id': 'clear', 'architecture_refs': []})['status'] == 'success'
    assert runtime.changes.get_change('refs', args['change_id'])['packets'][0].get('architecture_refs', []) == []
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        assert connection.execute('SELECT architecture_refs_json FROM implementation_packets WHERE project_id=? AND packet_id=?',
            ('refs', args['packet_id'])).fetchone()[0] == '[]'


def test_actual_public_nested_schema_guides_without_preempting_handler_proof(owned):
    runtime, args = owned
    app = create_app(runtime)
    tools = {t.name: t for t in asyncio.run(app.list_tools())}
    for name in ('fow_packet_author', 'fow_change'):
        schema = tools[name].inputSchema['properties']['architecture_refs']['anyOf'][0]
        assert schema['maxItems'] == 128 and schema['items']['additionalProperties'] is False
        assert schema['items']['required'] == ['revision', 'kind', 'entity_id']
        assert schema['items']['properties']['kind']['enum'] == ['component', 'interface', 'decision']
    malformed = {**args, 'architecture_refs': [{'id': 'Core', 'kind': 'component'}]}
    result = asyncio.run(app.call_tool('fow_packet_author', malformed))
    structured = result[1] if isinstance(result, tuple) else result.structuredContent
    assert structured['result']['result']['effect_state'] == 'none'
