"""Risk prose and non-attestation never manufacture stakeholder approval gates."""
from copy import deepcopy
from dataclasses import asdict
import sqlite3

import pytest

from flow_of_work_mcp import LifecycleControlService, MilestoneDraft, RequirementDraft, RequirementService
from flow_of_work_mcp.application.project_state_snapshot import _gate_kind, _next_gate, _open_decisions
from flow_of_work_mcp.application.external_plan_markdown import REVIEW_ACCEPTANCE_MEANING
from flow_of_work_mcp.application.lifecycle_recipes import get_recipe
from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.model_facing import project_markdown, _present_repository_reviews
from tests.test_engineering_cycle_exposure import review_projection


@pytest.fixture
def owned(tmp_path):
    runtime = build_runtime(database_path=tmp_path/'advisory.sqlite3', import_root=tmp_path)
    requirements = RequirementService(runtime.ledger)
    requirements.create_project('alpha', 'Owned milestone progression', actor='engineer')
    ids = [requirements.register('alpha', RequirementDraft(title='Stage '+str(n),
        statement='The system shall expose stage '+str(n)+' behavior.', category='functional'), actor='engineer')['requirement_id'] for n in [1, 2]]
    lifecycle = LifecycleControlService(requirements=runtime.ledger, goals=runtime.ledger,
        grounding_audits=runtime.ledger, control=runtime.ledger, change_control=runtime.ledger)
    yield runtime, lifecycle, ids
    runtime.close()


def promote(context, text, *, requirement=0, prerequisite=False, entry=None):
    _runtime, service, ids = context
    return service.promote_milestone('alpha', MilestoneDraft(name='Owned stage '+str(len(_runtime.ledger.milestones('alpha'))+1),
        requirement_ids=(ids[requirement],), prerequisite_requirement_ids=(ids[0],) if prerequisite else (),
        entry_policy=entry or {}, exit_policy={'acceptance':['Actual technical criteria.']},
        risk_disposition=text), actor='engineer')


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize('text', [
    'Known risks reviewed', 'open', 'needs_review',
    'Accept the risk that documentation and source disagree by treating source as authoritative.',
    'Investigate blocked/stale documentation against executable source; user intent is unchanged.',
])
def test_recorded_risk_is_advisory_read_not_pending_stakeholder_decision(owned, text):
    runtime, service, _ = owned
    milestone = promote(owned, text)
    before = dump(runtime)
    action = next(a for a in service.what_next('alpha') if a.action_id == 'milestone-risk:'+milestone['milestone_id'])
    assert action.execution_class == 'orchestration' and action.decision_class == 'orchestration'
    assert action.priority == 80 and not action.automatic_eligible
    assert text in action.rationale
    assert action.tool == 'fow_traceability' and action.operation == 'call'
    assert action.arguments == {'project_id':'alpha','milestone_id':milestone['milestone_id']}
    gate = _next_gate('alpha', asdict(action), {})
    assert gate['kind'] == 'intent_work' and gate['state'] == 'pending'
    assert gate['advisory'] is True and gate['establishes_global_admission'] is False
    assert gate['route']['tool'] == 'fow_traceability' and gate['route']['arguments'] == action.arguments
    assert gate['route']['required_inputs'] == [] and gate['continuation_policy'] == 'return_to_model'
    assert _open_decisions('alpha', [asdict(action)], limit=20)['items'] == []
    snapshot = runtime.project_state_snapshot.snapshot('alpha', limit=20)
    assert 'not conjunctive' in snapshot['secondary_actions_policy']['interpretation']
    assert not any(d['action_id'].startswith('milestone-risk:') for d in snapshot['open_decisions'])
    assert dump(runtime) == before
    assert next(m for m in runtime.ledger.milestones('alpha') if m['milestone_id']==milestone['milestone_id'])['risk_disposition'] == text


@pytest.mark.parametrize('text', ['accepted', 'none'])
def test_existing_exact_suppression_is_preserved_without_risk_acceptance_mutation(owned, text):
    runtime, service, _ = owned
    milestone = promote(owned, text)
    before = dump(runtime)
    assert not any(a.action_id == 'milestone-risk:'+milestone['milestone_id'] for a in service.what_next('alpha'))
    assert runtime.ledger.milestones('alpha')[0]['status'] != 'accepted'
    assert dump(runtime) == before


def test_later_milestone_eligibility_depends_on_explicit_entry_not_previous_acceptance(owned):
    runtime, service, _ = owned
    first = promote(owned, 'Source is authoritative within delegated technical scope.')
    second = promote(owned, 'Known risks reviewed', requirement=1, prerequisite=True,
                     entry={'preconditions':['M1 contracts are recorded']})
    gated = promote(owned, 'open', requirement=1, prerequisite=True,
                    entry={'requires_milestone':[first['milestone_id']]})
    before = dump(runtime)
    diagnostics = service.milestone_entry_policy_diagnostics('alpha')
    assert not any(d['milestone_id'] == second['milestone_id'] for d in diagnostics)
    assert next(d for d in diagnostics if d['milestone_id']==gated['milestone_id'])['code'] == 'required_milestone_not_accepted'
    actions = {a.action_id for a in service.what_next('alpha')}
    assert 'milestone-change:'+second['milestone_id'] in actions
    assert 'milestone-change:'+gated['milestone_id'] not in actions
    assert dump(runtime) == before


def test_genuine_governed_action_is_not_hidden_or_reclassified():
    actual = {'action_id':'actual-authority', 'kind':'request_change_acceptance',
              'execution_class':'governed_decision','decision_class':'governed_decision', 'rationale':'Actual acceptance requested'}
    assert _next_gate('alpha', actual, {})['kind'] == 'acceptance'
    assert _open_decisions('alpha', [actual], limit=20)['items'][0]['action_id'] == 'actual-authority'
    assert _gate_kind('resolve_packet_blocker', 'real blocked packet', {}) == 'technical_blockage'


@pytest.mark.parametrize('full', [False, True])
def test_review_non_attestation_is_explained_without_changing_flags_or_requested_coverage(full):
    review = review_projection(state='open')
    original = deepcopy(review)
    presented = _present_repository_reviews(review, full_review=full)
    assert presented['human_acceptance'] is False and review == original
    assert presented['human_acceptance_meaning'] == REVIEW_ACCEPTANCE_MEANING
    if full:
        assert presented['coverage'] == original['coverage']
    else:
        assert all(set(row) == {'dimension','state'} for row in presented['coverage'])
    payload = {'status':'success','result':{'repository_review':review}}
    markdown = project_markdown('fow_external_work', payload,
        arguments={'operation':'validation','payload':{'detail':'full' if full else 'standard'}})
    assert 'not by itself a new human approval prerequisite' in markdown
    assert 'Human acceptance' in markdown and payload['result']['repository_review'] == original
    if full:
        assert 'FIRST_PRIVATE_DETAIL' in markdown


def test_recipe_and_exact_help_preserve_real_predicates_and_milestone_continuity():
    recipe = str(get_recipe('provider-agnostic-engineering-cycle'))
    assert 'Continue across confirmed milestones' in recipe and 'actual scoped entry/admission' in recipe
    guidance = operation_contract('fow_promote_milestone','call')['guidance']
    assert 'free-text risk treatment' in guidance['risk_disposition']
    assert 'explicit canonical authority' in guidance['risk_disposition']
    help = operation_contract('fow_what_next','call')
    assert help['accepted_values']['detail_level'] == ['standard','audit']
    assert 'not conjunctive' in help['guidance']['actions']
