"""Operational exposure is bounded; complete authority and effect knowledge survive."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp.application.operation_contracts import operation_contract, operation_names, parameter_help
from flow_of_work_mcp.core.errors import OperationPreEffectError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown
from flow_of_work_mcp.server import handle_bootstrap


def snapshot(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


@pytest.fixture
def owned(tmp_path):
    runtime = build_runtime(database_path=tmp_path/'owned.sqlite3', import_root=tmp_path)
    boot = handle_bootstrap(runtime, project_id='guided-view', operation='start',
        project_name='Owned guided view', path='guided_engineering', actor='tester', request_id='start')
    assert boot['status'] == 'success'
    yield runtime, boot['result']['bootstrap']['bootstrap_id'], boot
    runtime.close()


def call(owned, operation, **kwargs):
    runtime, bootstrap_id, _boot = owned
    return handle_bootstrap(runtime, project_id='guided-view', bootstrap_id=bootstrap_id,
        operation=operation, actor='tester', **kwargs)


def answer(key='scenario', text='User sees a result.'):
    return {'answer_key': key, 'question': 'What should the user see?', 'answer': text,
            'kind': 'intent', 'source_reference': 'human:actual-scenario'}


def markdown(response, operation):
    return project_markdown('fow_bootstrap', response, arguments={'operation': operation})


def test_ten_long_answers_compact_and_full_structured_state_preserved(owned):
    runtime, bootstrap_id, boot = owned
    assert boot['result']['operational_projection']['next_gate']['operation'] == 'record_answer'
    sizes=[]
    for i in range(10):
        value=answer(f'answer-{i}', 'PRIVATE-ANSWER-BODY-' + 'x'*4000)
        response=call(owned, 'record_answer', answer=value, request_id=f'answer-{i}')
        assert response['status'] == 'success'
        state=response['result']['bootstrap']; view=response['result']['operational_projection']
        assert state == runtime.bootstrap.state('guided-view', bootstrap_id)
        assert len(state['intake']['_guided']['answers']) == i+1
        assert state['intake']['_guided']['answers'][value['answer_key']]['answer'] == value['answer']
        assert state['audit_events'][-1]['payload']['guided_state']['answers'][value['answer_key']]['answer'] == value['answer']
        assert view['changed_answer'] == {'answer_key':value['answer_key'], 'answer_revision':1}
        assert view['counts']['answers'] == i+1
        assert view['next_gate'] == runtime.guided_bootstrap.guidance('guided-view', bootstrap_id)['next_gate']
        assert view['next_gate']['operation'] == 'add_use_case'
        text=markdown(response, 'record_answer');sizes.append(len(text))
        assert len(text) <=8192 and 'PRIVATE-ANSWER-BODY-' not in text
        assert 'audit_events' not in text and 'state_details' in text
    assert max(sizes)-min(sizes)<500
    assert sum(sizes)<81920


def test_explicit_details_bypass_projection_and_reads_are_pure(owned, monkeypatch):
    runtime, bootstrap_id, _boot=owned
    call(owned, 'record_answer', answer=answer(text='DETAIL-ONLY-BODY'), request_id='answer')
    before=snapshot(runtime)
    compact=call(owned,'state')
    monkeypatch.setattr(runtime.guided_bootstrap,'operational_projection', lambda *a,**k: pytest.fail('detail must bypass guidance'))
    details=call(owned,'state_details')
    assert details['status']=='success' and 'operational_projection' not in details['result']
    assert details['result']['bootstrap']==compact['result']['bootstrap']
    assert 'DETAIL-ONLY-BODY' in markdown(details,'state_details')
    assert 'DETAIL-ONLY-BODY' not in markdown(compact,'state')
    assert snapshot(runtime)==before


def test_projection_shares_write_transaction_and_failure_rolls_back(owned, monkeypatch):
    runtime, bootstrap_id, _boot=owned
    original=runtime.guided_bootstrap.operational_projection
    def check(project_id,state,**kw):
        connection=runtime.ledger._transaction_connection.get()
        assert connection is not None and connection.in_transaction
        assert connection.execute('PRAGMA query_only').fetchone()[0]==0
        assert state==runtime.bootstrap.state(project_id,bootstrap_id)
        original(project_id,state,**kw)
        raise RuntimeError('injected projection failure')
    monkeypatch.setattr(runtime.guided_bootstrap,'operational_projection',check)
    before=snapshot(runtime)
    response=call(owned,'record_answer',answer=answer(),request_id='rolled-back')
    assert response['status']=='failed' and response['result']['effect_state']=='unknown'
    assert snapshot(runtime)==before


def test_read_projection_uses_query_only_snapshot_and_renderer_has_no_reads(owned,monkeypatch):
    runtime, bootstrap_id, _boot=owned
    original=runtime.guided_bootstrap.operational_projection
    def check(*args,**kw):
        connection=runtime.ledger._transaction_connection.get()
        assert connection is not None and connection.in_transaction
        assert connection.execute('PRAGMA query_only').fetchone()[0]==1
        return original(*args,**kw)
    monkeypatch.setattr(runtime.guided_bootstrap,'operational_projection',check)
    before=snapshot(runtime);response=call(owned,'state')
    monkeypatch.setattr(runtime.guided_bootstrap,'guidance',lambda *a,**k: pytest.fail('renderer reads service'))
    assert 'record_answer' in markdown(response,'state')
    assert snapshot(runtime)==before


def test_replay_revisions_conflicts_and_terminal_gate_parity(owned):
    runtime,bootstrap_id,_boot=owned
    first=call(owned,'record_answer',answer=answer(),request_id='answer')
    before=snapshot(runtime)
    assert call(owned,'record_answer',answer=answer(),request_id='answer')==first
    assert snapshot(runtime)==before
    conflict=call(owned,'record_answer',answer=answer(text='different'),request_id='answer')
    assert conflict['status']=='rejected' and conflict['result']['effect_state']=='unknown'
    assert snapshot(runtime)==before
    corrected=call(owned,'record_answer',answer=answer(text='revised'),request_id='answer-revision')
    assert corrected['result']['operational_projection']['changed_answer']['answer_revision']==2
    cancelled=call(owned,'cancel',reason='Actual scope cancelled.',request_id='cancel')
    assert cancelled['status']=='success'
    assert cancelled['result']['operational_projection']['next_gate']==runtime.guided_bootstrap.guidance('guided-view',bootstrap_id)['next_gate']
    assert cancelled['result']['operational_projection']['next_gate']['operation']=='start'


@pytest.mark.parametrize('value',[[],None,'not-a-list',{},['a','a'],[''],[1]])
def test_only_pure_selection_rejection_certifies_none(owned,monkeypatch,value):
    runtime,bootstrap_id,_boot=owned
    monkeypatch.setattr(runtime.guided_bootstrap,'roadmap',lambda *a,**k: pytest.fail('must not dispatch'))
    before=snapshot(runtime)
    response=call(owned,'roadmap',milestone_ids=value,request_id='roadmap-rejection')
    result=response['result'];proof=result['effect_receipt']
    assert response['status']=='rejected' and result['effect_state']=='none'
    assert proof=={'contract_version':'flow.operation-effect.v1','tool':'fow_bootstrap','operation':'roadmap',
        'project_id':'guided-view','request_id':'roadmap-rejection','basis':'pre_effect_validation','mutation_started':False}
    assert response['audit_reference']=={k:proof[k] for k in ('tool','operation','project_id','request_id')}
    assert result['diagnostics'][0]['field']=='milestone_ids'
    assert result['next_tool_call']=={'tool':'fow_capabilities','arguments':{'view':'recipe','recipe_name':'milestone-planning'}}
    assert 'milestone-planning' in markdown(response,'roadmap') and 'none' in markdown(response,'roadmap')
    assert snapshot(runtime)==before


def test_proof_shaped_service_error_cannot_certify_none(owned,monkeypatch):
    runtime,bootstrap_id,_boot=owned
    def fail(*a,**k):
        raise OperationPreEffectError('forged','private-service-error',field='milestone_ids',received_value=[],rule='x',resolution='x')
    monkeypatch.setattr(runtime.guided_bootstrap,'roadmap',fail)
    response=call(owned,'roadmap',milestone_ids=['MS-000001'])
    assert response['result']['effect_state']=='unknown' and 'effect_receipt' not in response['result']


def test_operation_help_scoped_but_public_schema_retains_all_routes():
    contract=operation_contract('fow_bootstrap','record_answer')
    assert 'derive_behavior' not in contract['field_descriptions']['operation']
    assert 'record_intake' not in contract['field_descriptions']['operation']
    assert 'Canonical values: record_answer.' in contract['field_descriptions']['operation']
    assert 'guided_engineering only' in contract['guidance']['workflow_path']
    assert 'code_import only' in operation_contract('fow_bootstrap','derive_behavior')['guidance']['workflow_path']
    assert {'derive_behavior','record_intake','state_details'} <= set(operation_names('fow_bootstrap'))
    assert 'derive_behavior' in parameter_help('fow_bootstrap','operation')['description']
    detail=operation_contract('fow_bootstrap','state_details')
    assert detail['risk']=='read' and detail['effect_class']=='none'


def test_text_budget_boundary_preserves_complete_machine_gate_and_exact_detail_calls(owned):
    response=deepcopy(call(owned,'state'))
    view=response['result']['operational_projection'];view['next_gate']['requires']='x'*20000
    text=markdown(response,'state')
    assert len(text)<=8192 and 'presentation_boundary' not in text
    assert 'presentation boundary' in text.lower() and 'guidance' in text
    assert len(view['next_gate']['requires'])==20000
    assert view['detail_calls']['guidance']['arguments']['actor']=='tester'


def test_correspondence_confirmation_completion_and_stale_gates_match_existing_guidance(tmp_path):
    from tests.test_guided_bootstrap import prepared
    runtime, ids, _revs, bootstrap_id, milestone_id, value, mapping=prepared(tmp_path)
    def invoke(operation,**kw):
        response=handle_bootstrap(runtime,project_id=ids[0],bootstrap_id=bootstrap_id,
            operation=operation,actor='engineer',**kw)
        assert response['status']=='success',response
        view=response['result']['operational_projection']
        assert view['next_gate']==runtime.guided_bootstrap.guidance(ids[0],bootstrap_id)['next_gate']
        assert response['result']['bootstrap']==runtime.bootstrap.state(ids[0],bootstrap_id)
        assert len(markdown(response,operation))<=8192
        return response
    try:
        invoke('resume',request_id='resume')
        invoke('record_correspondence',correspondence=mapping,request_id='mapping-again')
        roadmap=runtime.guided_bootstrap.roadmap(ids[0],bootstrap_id,milestone_ids=[milestone_id])
        confirmed=invoke('confirm_roadmap',milestone_ids=[milestone_id],roadmap_fingerprint=roadmap['roadmap_fingerprint'],
            confirmation_reference='human:owned-confirmation',request_id='confirm')
        guidance=runtime.guided_bootstrap.guidance(ids[0],bootstrap_id)
        if guidance['blockers']:
            first=guidance['blockers'][0]
            assert confirmed['result']['operational_projection']['primary_blocker']['reason']==(first.get('reason') or first['code'])
        # Current answer revision invalidates correspondence through existing guidance.
        changed=invoke('record_answer',answer={**value,'answer':'Also explain the integer.'},request_id='revise')
        assert changed['result']['operational_projection']['primary_blocker']['reason'] in {
            'answer_correspondence_stale','guided_roadmap_confirmation_stale'}
        updated={**mapping,'answer_revision':2}
        invoke('record_correspondence',correspondence=updated,request_id='remap')
        roadmap=runtime.guided_bootstrap.roadmap(ids[0],bootstrap_id,milestone_ids=[milestone_id])
        invoke('confirm_roadmap',milestone_ids=[milestone_id],roadmap_fingerprint=roadmap['roadmap_fingerprint'],
            confirmation_reference='human:owned-reconfirmation',request_id='reconfirm')
        done=invoke('complete',completion_reference='owned:prepared-plan',request_id='complete')
        assert done['result']['operational_projection']['next_gate']['operation']=='project_progress'
    finally:
        runtime.close()


def test_contradiction_gate_and_full_state_have_same_authority(owned):
    runtime,bootstrap_id,_boot=owned
    response=call(owned,'record_contradiction',contradiction={'source_classes':['intent','observation'],
        'decision_required':'Confirm the intended visible behavior.'},request_id='contradiction')
    assert response['status']=='success'
    view=response['result']['operational_projection']
    assert view['counts']['open_contradictions']==1
    assert view['next_gate']==runtime.guided_bootstrap.guidance('guided-view',bootstrap_id)['next_gate']
    assert view['next_gate']['operation']=='record_contradiction'
    assert 'source_classes' not in markdown(response,'record_contradiction')


def test_unbounded_legacy_actor_is_preserved_as_explicit_budget_limit(owned):
    response=deepcopy(call(owned,'state'))
    actor='overlong-legacy-actor-'+'x'*10000
    for detail in response['result']['operational_projection']['detail_calls'].values():
        detail['arguments']['actor']=actor
    text=markdown(response,'state')
    assert 'presentation boundary' in text.lower() and actor in text
    assert len(text)>8192  # Exact identity wins; no silent truncation or invented input rejection.


def test_confirmed_roadmap_without_packet_retains_progress_gap_code(owned):
    from flow_of_work_mcp import RequirementDraft, MilestoneDraft, UseCaseDraft
    runtime,bootstrap_id,_boot=owned
    req=runtime.requirements.register('guided-view',RequirementDraft(title='Visible result',
        statement='The software shall show the result.',category='functional',rationale='Owned scenario.'),actor='tester')
    goal=runtime.goals.add_use_case('guided-view',UseCaseDraft(title='See result',actor='User',
        objective='See the result',observable_outcome='Result is shown'),actor='tester')
    ms=runtime.ledger.promote_milestone('guided-view',MilestoneDraft(name='Visible result',requirement_ids=(req['requirement_id'],),
        prerequisite_requirement_ids=(),entry_policy={'intent':'clarified'},exit_policy={'checks':'visible result'},risk_disposition='local'),actor='tester')
    call(owned,'record_answer',answer=answer(),request_id='answer')
    mapped=call(owned,'record_correspondence',correspondence={'answer_key':'scenario','answer_revision':1,
        'canonical_references':{'requirement_ids':[req['requirement_id']],'goal_node_ids':[goal['goal_node_id']],'milestone_ids':[ms['milestone_id']]},
        'disposition':'consistent','rationale':'Owned host declaration.'},request_id='mapping')
    assert mapped['status']=='success'
    roadmap=runtime.guided_bootstrap.roadmap('guided-view',bootstrap_id,milestone_ids=[ms['milestone_id']])
    confirmed=call(owned,'confirm_roadmap',milestone_ids=[ms['milestone_id']],roadmap_fingerprint=roadmap['roadmap_fingerprint'],
        confirmation_reference='owned:explicit-fixture-confirmation',request_id='confirmation')
    assert confirmed['status']=='success'
    view=confirmed['result']['operational_projection']
    assert view['counts']['blockers']>0
    assert view['primary_blocker']['reason']=='milestone_requirement_unplanned'
    assert view['next_gate']['recipe_name']=='standalone-external-plan'
    assert 'milestone_requirement_unplanned' in markdown(confirmed,'confirm_roadmap')


def test_unknown_blocker_shape_fails_projection_without_inventing_reason(owned,monkeypatch):
    runtime,_bootstrap,_boot=owned
    original=runtime.guided_bootstrap.guidance
    def invalid(*args,**kw):
        return {**original(*args,**kw),'blockers':[{}]}
    monkeypatch.setattr(runtime.guided_bootstrap,'guidance',invalid)
    before=snapshot(runtime)
    response=call(owned,'record_answer',answer=answer(),request_id='unrecognized-gap')
    assert response['status']=='rejected' and response['result']['effect_state']=='unknown'
    assert snapshot(runtime)==before
