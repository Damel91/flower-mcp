"""Complete compound commands retain original answers without answering new gates."""
from copy import deepcopy
import json

import pytest

from flow_of_work_mcp import RequirementDraft, RequirementService
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_change, handle_packet_author, _question_resolution_drafts
from tests.test_author_receipts import snapshot, current, call


@pytest.fixture
def empty_packet(tmp_path):
    runtime = build_runtime(database_path=tmp_path / 'ledger.sqlite3', import_root=tmp_path)
    service = RequirementService(runtime.ledger)
    service.create_project('alpha', 'Owned authoring', actor='engineer')
    service.register('alpha', RequirementDraft(title='Local export', statement='The system shall export status.',
        category='functional', rationale='Owned test.'), actor='engineer')
    change = handle_change(runtime, project_id='alpha', operation='create_change', actor='engineer',
        title='Local export', rationale='Owned test.', requirement_ids=['REQ-000001'])
    cid = change['result']['change']['change_id']
    packet = handle_packet_author(runtime, project_id='alpha', change_id=cid, operation='start_packet',
        title='Local exporter', intent='Implement the local exporter.', completion_criteria=['Export status.'],
        actor='engineer', request_id='start', requirement_ids=['REQ-000001'])
    ids = ('alpha', cid, packet['result']['packet']['packet_id'])
    try:
        yield runtime, ids
    finally:
        runtime.close()


def arguments(runtime, ids, *, all_answers=True, revisions=True):
    audit = runtime.packet_construction.audit_for_packet(*ids)
    questions = audit['questions'] if all_answers else audit['questions'][:1]
    return {'work_plan': {'units': [{'client_unit_key': 'exporter', 'operation_kind': 'new_file',
        'file_path': 'src/exporter.py', 'instructions': ['Export local status as Markdown.'],
        'unit_checks': ['A fixed status exports expected Markdown.']}]},
        'answers': [{'question_id': q['question_id'], 'answer_summary': 'Owned explicit design and bounded verification.'}
                    for q in questions], **(current(runtime, ids) if revisions else {})}


def success(response):
    assert response['status'] == 'success', response
    return response['result']


def test_original_target_question_is_recorded_then_ceases_applicability(empty_packet):
    runtime, ids = empty_packet
    audit = runtime.packet_construction.audit_for_packet(*ids)
    q = next(q for q in audit['questions'] if q['question_key'] == 'target_selection')
    args = arguments(runtime, ids)
    result = success(call(runtime, ids, 'replace_plan', 'compound', **args))
    receipt = result['engineering_questions']
    row = next(r for r in receipt['answers'] if r['question']['question_id'] == q['question_id'])
    assert row['question']['dependency_fingerprint'] == q['dependency_fingerprint']
    assert row['recorded_status'] == 'answered'
    assert row['disposition'] == 'ceased_applicable' and row['current_status'] is None
    normalized_answer = args['answers'][1] | {'evidence_refs': [], 'linked_navigation_refs': [],
        'waiver_rationale': '', 'policy_ref': '', 'blocker_reason': '', 'answer_source': 'explicit'}
    assert json.loads(json.dumps(row['submitted_answer'])) == normalized_answer
    current_audit = runtime.packet_construction.audit_for_packet(*ids)
    assert q['question_id'] not in {q['question_id'] for q in current_audit['questions']}
    assert runtime.ledger.packet_work_plan_state(*ids)['authoring_receipt'] == receipt
    assert receipt['original_authority'] == {'spec_revision': 2, 'plan_revision': 0}
    assert result['packet']['spec_revision'] > 2 and len(runtime.ledger.packet_work_plan_state(*ids)['units']) == 1
    for transition in receipt['answers']:
        after = next((q for q in current_audit['questions'] if q['question_id'] == transition['question']['question_id']), None)
        if transition['disposition'] == 'reopened_by_changed_dependency':
            assert after['status'] == 'open' and after['answer_summary'] == ''
        elif transition['disposition'] == 'retained':
            assert after['status'] == transition['recorded_status']


@pytest.mark.parametrize('revisions', [True, False])
def test_replay_is_historical_pure_and_does_not_answer_new_blocker(empty_packet, monkeypatch, revisions):
    runtime, ids = empty_packet
    args = arguments(runtime, ids, revisions=revisions)
    original = success(call(runtime, ids, 'replace_plan', 'compound', **args))
    success(call(runtime, ids, 'revise_packet', 'new-question', unresolved_questions=['Choose output retention policy.'], **current(runtime, ids)))
    before = snapshot(runtime)
    def forbidden(*a, **k):
        raise AssertionError('Replay cannot repair, answer or queue')
    monkeypatch.setattr(runtime.packet_factory, 'ensure_packet_lifecycle', forbidden)
    monkeypatch.setattr(runtime.ledger, 'resolve_packet_questions_batch', forbidden)
    monkeypatch.setattr(runtime.packet_provider_overlay, 'queue_plan_delta', forbidden)
    replay = success(call(runtime, ids, 'replace_plan', 'compound', **args))
    assert replay['semantic_delta']['replayed'] is True
    assert replay['engineering_questions'] == original['engineering_questions']
    assert replay['packet'] == original['packet']
    assert replay['current_authority'] == current(runtime, ids)
    assert snapshot(runtime) == before
    assert any(q['status'] == 'open' and q['question_key'] == 'authority_blocker'
               for q in runtime.packet_construction.audit_for_packet(*ids)['questions'])


@pytest.mark.parametrize('changed', ['answers', 'actor', 'expected_spec_revision', 'expected_plan_revision', 'work_plan'])
def test_changed_compound_identity_is_rejected_without_effect(empty_packet, changed):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    success(call(runtime, ids, 'replace_plan', 'compound', **args))
    before = snapshot(runtime)
    altered = deepcopy(args)
    if changed == 'answers': altered['answers'][0]['answer_summary'] = 'Different answer.'
    elif changed == 'actor':
        response = handle_packet_author(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2],
            operation='replace_plan', actor='different', request_id='compound', **altered)
    elif changed.startswith('expected_'): altered[changed] += 1
    else: altered['work_plan']['units'][0]['instructions'] = ['A different export.']
    if changed != 'actor': response = call(runtime, ids, 'replace_plan', 'compound', **altered)
    assert response['status'] == 'rejected' and response['reason'] == 'state_conflict'
    assert response['result']['effect_state'] == 'unknown'
    assert snapshot(runtime) == before


@pytest.mark.parametrize('kind', ['unknown_last', 'duplicate', 'over64', 'bad_source', 'model_proposal', 'waiver', 'extra_field'])
def test_complete_invalid_batch_is_atomic(empty_packet, kind):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    if kind == 'unknown_last': args['answers'].append({'question_id': 'PQUESTION-999999', 'answer_summary': 'Unknown'})
    elif kind == 'duplicate': args['answers'].append(deepcopy(args['answers'][0]))
    elif kind == 'over64': args['answers'] = args['answers'] * 9
    elif kind == 'bad_source': args['answers'][-1]['answer_source'] = 'invented'
    elif kind == 'model_proposal': args['answers'][-1]['answer_source'] = 'model_proposal'
    elif kind == 'waiver': args['answers'][1].update(waiver_rationale='Skip', policy_ref='invented')
    else: args['answers'][-1]['made_up'] = True
    before = snapshot(runtime)
    response = call(runtime, ids, 'replace_plan', 'invalid-' + kind, **args)
    assert response['status'] == 'rejected' and response['reason'] == 'invalid_input', response
    assert response['result']['effect_state'] == 'unknown'
    assert response['result']['original_request']['request_id'] == 'invalid-' + kind
    assert response['result']['diagnostics']
    assert snapshot(runtime) == before


@pytest.mark.parametrize('field', ['expected_spec_revision', 'expected_plan_revision'])
def test_stale_original_cas_does_not_apply_answers(empty_packet, field):
    runtime, ids = empty_packet
    args = arguments(runtime, ids);args[field] += 100
    before = snapshot(runtime)
    response = call(runtime, ids, 'replace_plan', 'stale', **args)
    assert response['status'] == 'rejected' and response['reason'] == 'state_conflict'
    assert snapshot(runtime) == before


def test_failure_after_answer_rolls_back_without_false_effect_proof(empty_packet, monkeypatch):
    runtime, ids = empty_packet
    args = arguments(runtime, ids);before = snapshot(runtime)
    def fail(*a, **k): raise RuntimeError('Injected after original answers')
    monkeypatch.setattr(runtime.ledger, 'create_packet_work_plan', fail)
    result = call(runtime, ids, 'replace_plan', 'failed', **args)
    assert result['result']['effect_state'] == 'unknown' and 'effect_receipt' not in result['result']
    assert snapshot(runtime) == before


def test_failure_after_commit_is_unknown_with_reconcilable_receipt(empty_packet, monkeypatch):
    import flow_of_work_mcp.server as server
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    def fail(*a, **k): raise RuntimeError('Injected continuation failure')
    monkeypatch.setattr(server, '_packet_author_continuation', fail)
    result = call(runtime, ids, 'replace_plan', 'committed', **args)
    assert result['result']['effect_state'] == 'unknown'
    plan = runtime.ledger.packet_work_plan_state(*ids)
    assert plan['authoring_receipt']['request_id'] == 'committed' and len(plan['units']) == 1


def test_legacy_plan_only_replay_does_not_certify_answers(empty_packet):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    runtime.packet_work_plan.set_plan(*ids, args['work_plan'], expected_packet_revision=args['expected_spec_revision'],
        expected_current_plan_revision=0, actor='engineer', request_id='legacy')
    before = snapshot(runtime)
    result = call(runtime, ids, 'replace_plan', 'legacy', **args)
    assert result['status'] == 'rejected' and result['reason'] == 'invalid_input'
    assert 'legacy_compound_receipt_unverifiable' in str(result['result']['diagnostics'])
    assert snapshot(runtime) == before
    args.pop('answers')
    success(call(runtime, ids, 'replace_plan', 'legacy', **args))
    assert snapshot(runtime) == before


@pytest.mark.parametrize('field,value', [
    ('answer_summary', {'text': 'not text'}), ('evidence_refs', {}),
    ('linked_navigation_refs', 0), ('answer_source', 0), ('answer_source', ''),
    ('evidence_refs', [23]), ('question_id', 7),
])
def test_present_answer_values_cannot_be_coerced_or_discarded(empty_packet, field, value):
    runtime, ids = empty_packet
    args = arguments(runtime, ids);args['answers'][-1][field] = value
    before = snapshot(runtime)
    response = call(runtime, ids, 'replace_plan', 'invalid-type', **args)
    assert response['status'] == 'rejected'
    assert response['result']['diagnostics'][0]['field'].startswith('answers[')
    assert snapshot(runtime) == before


def test_foreign_question_id_cannot_answer_this_packet(empty_packet):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    other = success(handle_packet_author(runtime, project_id=ids[0], change_id=ids[1], operation='start_packet',
        actor='engineer', title='Other packet', intent='Other bounded intent.', completion_criteria=['Other.'], request_id='other'))
    other_ids = (*ids[:2], other['packet']['packet_id'])
    foreign = runtime.packet_construction.audit_for_packet(*other_ids)['questions'][0]['question_id']
    args['answers'][-1]['question_id'] = foreign
    before = snapshot(runtime)
    result = call(runtime, ids, 'replace_plan', 'foreign-question', **args)
    assert result['status'] == 'rejected'
    assert result['result']['diagnostics'][0]['received_value'] == foreign
    assert snapshot(runtime) == before


def test_retained_blocker_is_not_presented_as_answered(empty_packet):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    audit = runtime.packet_construction.audit_for_packet(*ids)
    qid = next(q['question_id'] for q in audit['questions'] if q['question_key'] == 'authority_blocker')
    answer = next(a for a in args['answers'] if a['question_id'] == qid)
    answer['blocker_reason'] = 'Unresolved product retention choice.'
    receipt = success(call(runtime, ids, 'replace_plan', 'blocked-answer', **args))['engineering_questions']
    row = next(a for a in receipt['answers'] if a['question']['question_id'] == qid)
    assert row['recorded_status'] == row['current_status'] == 'blocked'
    assert row['disposition'] == 'retained'


def test_receipt_survives_restart_and_replay_is_read_only(empty_packet, tmp_path):
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    original = success(call(runtime, ids, 'replace_plan', 'restart-receipt', **args))
    before = snapshot(runtime)
    path = runtime.ledger.database_path
    runtime.close()
    reopened = build_runtime(database_path=path, import_root=tmp_path)
    try:
        replay = success(call(reopened, ids, 'replace_plan', 'restart-receipt', **args))
        assert replay['engineering_questions'] == original['engineering_questions']
        assert snapshot(reopened) == before
    finally:
        reopened.close()



def test_public_history_exposes_old_receipt_after_successor_plan(empty_packet):
    from flow_of_work_mcp.server import handle_packet_inspect
    runtime, ids = empty_packet
    args = arguments(runtime, ids)
    original = success(call(runtime, ids, 'replace_plan', 'old-receipt', **args))
    later = arguments(runtime, ids, all_answers=False);later.pop('answers')
    success(call(runtime, ids, 'replace_plan', 'new-head', **later))
    before = snapshot(runtime)
    response = handle_packet_inspect(runtime, project_id=ids[0], change_id=ids[1], packet_id=ids[2],
        view='history', detail_level='audit', limit=100)
    result = success(response)['packet']
    rows = [e for e in result['events'] if e.get('kind') == 'work_plan_authoring']
    assert [e['request_id'] for e in rows] == ['old-receipt', 'new-head']
    assert rows[0]['plan_revision'] == 1 and rows[0]['actor'] == 'engineer'
    assert rows[0]['authoring_receipt'] == original['engineering_questions']
    assert snapshot(runtime) == before


def test_compound_receipt_uses_canonical_refreshed_question_basis(empty_packet):
    import sqlite3
    runtime, ids = empty_packet
    original = runtime.packet_construction.audit_for_packet(*ids)['questions'][0]
    # An ordinary question refresh may repair stored derived basis; the receipt
    # must bind the actual basis validated by the resolver, not the stale cache.
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        connection.execute('UPDATE packet_construction_questions SET dependency_fingerprint = ? WHERE question_id = ?',
                           ('stale-derived-basis', original['question_id']))
    args = arguments(runtime, ids, all_answers=False)
    result = runtime.packet_work_plan.replace_plan(*ids, args['work_plan'],
        answers=_question_resolution_drafts(args['answers']),
        expected_packet_revision=args['expected_spec_revision'], expected_current_plan_revision=0,
        declared_spec_revision=args['expected_spec_revision'], declared_plan_revision=0,
        actor='engineer', request_id='derived-refresh')
    row = result['authoring_receipt']['answers'][0]
    assert row['question']['dependency_fingerprint'] == original['dependency_fingerprint']
    assert row['disposition'] == 'retained'
