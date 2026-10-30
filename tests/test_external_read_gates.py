"""Read gates never become mutation uncertainty or implicit confirmation."""
import sqlite3

import pytest

from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import handle_external_work
from tests.test_guided_bootstrap import prepared


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as c: return tuple(c.iterdump())


@pytest.mark.parametrize('detail', ['standard', 'full'])
@pytest.mark.parametrize('operation', ['validation', ' validation '])
def test_real_unconfirmed_roadmap_read_preserves_gate_and_all_state(tmp_path, detail, operation):
    runtime, ids, _revs, _bootstrap_id, _milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        before = dump(runtime)
        response = handle_external_work(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2],
            operation=operation, payload={'detail': detail})
        assert response['status'] == 'blocked' and response['reason'] == 'guided_roadmap_confirmation_required'
        result = response['result']
        assert result['execution_allowed'] is False
        assert result['execution_admission']['reason'] == response['reason']
        assert not {'effect_state', 'operation_state', 'effect_receipt', 'recovery_guidance'} & result.keys()
        assert result['next_tool_call'] == {'tool': 'fow_capabilities', 'arguments': {
            'view': 'operation', 'operation_tool': 'fow_bootstrap', 'operation_name': 'guidance'}}
        if detail == 'full': assert 'report_history' in result
        text = project_markdown('fow_external_work', response, arguments={'operation': 'validation'})
        assert 'guided_roadmap_confirmation_required' in text and 'Effect state' not in text
        assert dump(runtime) == before
    finally: runtime.close()


@pytest.mark.parametrize('operation', ['criteria', 'validation', 'provider_validation', 'todo'])
def test_unexpected_read_failure_is_observation_error_not_unknown_write(tmp_path, monkeypatch, operation):
    runtime, ids, *_ = prepared(tmp_path)
    try:
        before = dump(runtime)
        monkeypatch.setattr(runtime.external_work, 'call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('PRIVATE ERROR')))
        response = handle_external_work(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2], operation=operation)
        assert response['status'] == 'failed' and response['reason'] == 'internal_error'
        assert response['result']['read_only'] is True
        assert response['result']['diagnostics'][0]['code'] == 'read_failed'
        assert not {'effect_state', 'operation_state', 'effect_receipt', 'recovery_guidance'} & response['result'].keys()
        assert response['result']['next_tool_call']['arguments']['operation_name'] == operation
        assert 'PRIVATE ERROR' not in str(response) and dump(runtime) == before
    finally: runtime.close()


def test_invalid_read_and_unknown_mutation_remain_different(tmp_path, monkeypatch):
    runtime, ids, *_ = prepared(tmp_path)
    try:
        before = dump(runtime)
        bad = handle_external_work(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2],
                                   operation='validation', payload={'detail': 'invented'})
        assert bad['status'] == 'rejected' and 'effect_state' not in bad['result']
        monkeypatch.setattr(runtime.external_work, 'call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('late')))
        unknown = handle_external_work(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2], operation='set_mode')
        assert unknown['result']['effect_state'] == 'unknown' and 'effect_receipt' not in unknown['result']
        assert dump(runtime) == before
    finally: runtime.close()
