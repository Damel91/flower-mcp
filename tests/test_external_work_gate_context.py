"""Observed gates explain preparation without becoming admission authority."""
from copy import deepcopy

import pytest

from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.model_facing import project_markdown
from tests.test_external_work import fixture
from tests.test_guided_bootstrap import prepared, confirm
from tests.test_plan_authoring_repair import dump, revise

CHECK = 'npm run typecheck and npm test both resolve to declared scripts and exit without unknown-script errors.'
CANDIDATE = 'The declared typecheck and test scripts exist and resolve, so the automated assertions required by this packet are actually executable.'


@pytest.mark.parametrize('count', [0, 1, 12])
def test_roadmap_hold_keeps_exact_pvp_repair_and_count_not_test_passes(tmp_path, count):
    runtime, ids, _revs, *_ = prepared(tmp_path)
    try:
        units = deepcopy(runtime.ledger.packet_work_plan_state(*ids)['units'])
        units[0]['unit_checks'] = [CHECK]
        candidates = [CANDIDATE] if count == 1 else [f'Candidate declaration {n:02}' for n in range(count)]
        # Deferred verification is retained; candidate statements do not prove checks ran.
        units[0]['verifies'] = [v for v in units[0]['verifies'] if v['kind'] != 'unit_check'] + [
            {'criterion': 1, 'kind': 'unit_check', 'statement': statement} for statement in candidates]
        revise(runtime.ledger, ids, units)
        service = runtime.external_work
        original = service._projection(service._snapshot(*ids))
        before = dump(runtime.ledger)
        standard = service.validation(*ids)
        full = service.validation(*ids, detail='full')
        assert dump(runtime.ledger) == before
        assert full['validation'] == original
        assert standard['gate_context'] == full['gate_context']
        assert full['reason'] == 'guided_roadmap_confirmation_required'
        assert full['next_gate']['reason'] == full['reason'] and not full['execution_allowed']
        ctx = full['gate_context']
        assert ctx['engineer_gate'] == {'scope': 'semantic_findings_only', 'state': 'passed', 'establishes_global_admission': False}
        assert full['engineer_gate']['execution_allowed'] is True
        assert ctx['admission']['state'] == 'blocked'
        assert ctx['admission']['next_gate'] == full['execution_admission']['next_gate']
        gap = original['next_gap']
        assert gap['code'] == 'unit_check_verification_missing'
        assert ctx['validation']['next_gap'] == gap
        repair = ctx['validation']['next_gate']['repair']
        diagnostic = ctx['validation']['diagnostic']
        assert all(diagnostic[key] == value for key, value in gap.items())
        assert diagnostic['received'] == CHECK and diagnostic['expected'] == sorted(candidates)[:10]
        assert diagnostic['expected_count'] == count and diagnostic['expected_truncated'] is (count > 10)
        assert diagnostic['declaration_match'] is False
        assert 'not test executions' in diagnostic['expected_count_meaning']
        assert 'criterion prose and implements' in diagnostic['rule']
        assert repair['ready_to_call'] is False and 'unit_patch' not in repair['operation']['arguments']
        markdown = project_markdown('fow_external_work', {'status': 'blocked', 'result': full}, arguments={'operation': 'validation'})
        assert CHECK in markdown and all(item in markdown for item in candidates[:10])
        assert 'Declared comparison candidates (not passed checks)' in markdown
        assert 'Semantic findings subgate' in markdown and 'does not establish global' in markdown
        assert 'first observed guard result' in markdown and 'read-only observation' in markdown
    finally:
        runtime.close()


def test_proposed_plan_diagnostic_selects_repair_without_reordering_next_gap(tmp_path):
    ledger, service, ids, _ = fixture(tmp_path)
    units = deepcopy(ledger.packet_work_plan_state(*ids)['units'])
    units[0]['unit_checks'] = [CHECK]
    revise(ledger, ids, units, accept=False)
    view = service.validation(*ids, detail='full')
    ctx = view['gate_context']['validation']
    assert ctx['next_gap'] == view['validation']['next_gap']
    assert ctx['next_gap']['code'] == 'work_plan_not_accepted'
    assert ctx['diagnostic']['code'] == 'unit_check_verification_missing'
    assert ctx['diagnostic']['received'] == CHECK and not view['execution_allowed']


def test_todo_early_blocks_do_not_evaluate_admission_or_dependencies(tmp_path, monkeypatch):
    ledger, service, ids, _ = fixture(tmp_path)
    units = deepcopy(ledger.packet_work_plan_state(*ids)['units'])
    units[0]['unit_checks'] = [CHECK]
    revise(ledger, ids, units)
    snapshot = service._snapshot(*ids)
    def forbidden(*args, **kwargs):
        raise AssertionError('metadata must not evaluate short-circuited work')
    monkeypatch.setattr(service, '_assert_execution_allowed', forbidden)
    monkeypatch.setattr(service, '_packet_dependencies', forbidden)
    before = dump(ledger)
    todo = service._todo(snapshot)
    assert todo['reason'] == 'unit_check_verification_missing'
    assert todo['gate_context']['admission']['state'] == 'not_evaluated'
    assert todo['gate_context']['admission']['inspection_route']['arguments']['payload'] == {'detail': 'full'}
    snapshot['external']['consumption_mode'] = 'legacy'
    mode = service._todo(snapshot)
    assert mode['reason'] == 'external_mode_not_selected'
    assert mode['gate_context']['admission']['state'] == 'not_evaluated'
    assert dump(ledger) == before


def test_closed_pvp_can_be_read_without_roadmap_admission_then_confirmed_normally(tmp_path):
    runtime, ids, _, bootstrap_id, milestone_id, *_ = prepared(tmp_path)
    try:
        before = dump(runtime.ledger)
        view = runtime.external_work.validation(*ids)
        todo = runtime.external_work.todo(*ids)
        assert dump(runtime.ledger) == before
        for result in [view, todo]:
            assert result['reason'] == 'guided_roadmap_confirmation_required'
            assert result['gate_context']['validation']['state'] == 'closed'
            assert result['gate_context']['validation']['diagnostic'] is None
            assert not result['gate_context']['execution_allowed']
        fingerprint = view['validation']['authority_fingerprint']
        confirm(runtime, ids, bootstrap_id, milestone_id)
        before = dump(runtime.ledger)
        allowed = runtime.external_work.validation(*ids)
        success = runtime.external_work.todo(*ids)
        assert dump(runtime.ledger) == before
        assert allowed['execution_allowed'] and allowed['gate_context']['admission']['state'] == 'passed'
        assert allowed['validation']['authority_fingerprint'] == fingerprint
        assert success['status'] == 'success' and 'gate_context' not in success
    finally:
        runtime.close()


def test_history_fallback_never_invents_current_context(tmp_path, monkeypatch):
    ledger, service, ids, _ = fixture(tmp_path)
    def unresolved(*args):
        raise ValueError('current authority unavailable')
    monkeypatch.setattr(service, '_snapshot', unresolved)
    before = dump(ledger)
    view = service.validation(*ids, detail='full')
    assert dump(ledger) == before
    assert not view['execution_allowed'] and view['execution_readiness'] == 'not_evaluated'
    assert 'gate_context' not in view and 'validation' not in view


def test_dependency_hold_preserves_single_observed_guard(tmp_path, monkeypatch):
    ledger, service, ids, _ = fixture(tmp_path)
    snapshot = service._snapshot(*ids)
    calls = []
    monkeypatch.setattr(service, '_assert_execution_allowed', lambda value: calls.append(value['packet_id']))
    monkeypatch.setattr(service, '_packet_dependencies', lambda value: {'ready': False, 'predecessors': [{'complete': False, 'packet_id': 'owned-predecessor'}]})
    todo = service._todo(snapshot)
    assert calls == [ids[2]] and todo['reason'] == 'packet_dependencies_unresolved'
    assert todo['gate_context']['admission']['state'] == 'passed'
    assert not todo['gate_context']['execution_allowed']


@pytest.mark.parametrize('operation', ['validation', 'todo'])
def test_exact_help_explains_composite_gates_and_agent_consent_recording(operation):
    guidance = operation_contract('fow_external_work', operation)['guidance']
    assert 'flow.external-work-gates.v1' in guidance['gate_context']
    assert 'never passed tests' in guidance['gate_context']
    assert 'No native UI is mandatory' in guidance['read_semantics']
    assert 'actual applicable consent/delegation' in guidance['read_semantics']
