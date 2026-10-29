"""Host grounding is bounded evidence reconciliation, never source auditing or acceptance."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import json
import sqlite3

import pytest

from flow_of_work_mcp import BehavioralExpectationDraft, RequirementDraft
from flow_of_work_mcp.core.domain.grounding import ImplementationAnchor, ImplementationGraphSnapshot
from flow_of_work_mcp.core.errors import ModelBackendError, RequirementConflictError
from flow_of_work_mcp.core.ports import ModelResult
from flow_of_work_mcp.application.grounding_readiness import live_grounding_readiness
from flow_of_work_mcp.mcp_runtime import build_runtime
from tests.support.model_gateway import CallableModelGateway


def _receipt():
    return {'contract_version': 'flower-host-grounding-evidence-v1', 'source_identity': 'repo:example',
            'source_revision': 'git:abc123', 'truncated': False, 'anchors': [
                {'anchor_id': 'HOST-1', 'kind': 'symbol', 'label': 'send_confirmation',
                 'summary': 'Creates a visible confirmation.', 'source_path': 'src/orders.py',
                 'source_excerpt': 'def send_confirmation():\n    return "Order confirmed"\n',
                 'evidence_ids': ['test:orders-confirmation'], 'test_evidence_ids': ['test:orders-confirmation']}]}


def _runtime(tmp_path, **kwargs):
    runtime = build_runtime(database_path=tmp_path / 'ledger.sqlite3', import_root=tmp_path, **kwargs)
    runtime.requirements.create_project('alpha', 'Alpha', actor='operator')
    requirement = runtime.requirements.register('alpha', RequirementDraft(
        title='Visible confirmation', statement='A successful order shows confirmation.', category='functional'), actor='operator')
    goal = runtime.goals.add_behavioral_expectation('alpha', BehavioralExpectationDraft(
        title='Confirm successful order', statement='A successful order shows confirmation.', category='functional',
        observable_outcome='The customer sees the confirmation.'), actor='operator')
    candidate = runtime.goals.derive_requirement_candidates('alpha', actor='operator')[0]
    return runtime, goal, requirement, candidate


def _prepare(runtime, goal, *, mode='host', receipt=None, request_id='prepare-1'):
    fields = {'host_evidence': _receipt() if receipt is None else receipt} if mode == 'host' else {'source_revision': 'git:abc123'}
    return runtime.semantic_assignments.prepare('alpha', role='intention_grounding', execution_mode=mode,
        goal_node_ids=(goal['goal_node_id'],), actor='operator', request_id=request_id, **fields)


def _result(goal, requirement, candidate, **updates):
    item = {'goal_node_id': goal['goal_node_id'], 'anchor_ids': ['HOST-1'],
            'requirement_ids': [requirement['requirement_id']], 'candidate_ids': [candidate['candidate_id']],
            'classification': 'converged', 'confidence': 0.9, 'rationale': 'The supplied excerpt and declared test refer to the desired confirmation.'}
    item.update(updates)
    return {'assessments': [item]}


def _submit(runtime, prepared, result, *, revision='git:abc123', request_id='submit-1', executor='external-agent'):
    return runtime.semantic_assignments.submit('alpha', prepared['assignment_id'], result=result,
        source_revision=revision, executor_ref=executor, actor='operator', request_id=request_id)


def test_host_grounding_freezes_portable_context_and_adopts_only_audit(tmp_path, monkeypatch):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        monkeypatch.setattr(runtime.structural_validation, 'validate', lambda *a, **k: pytest.fail('Host grounding must not read SRS/source files'))
        before_requirements = deepcopy(runtime.requirements.traceability('alpha'))
        before_goals = deepcopy(runtime.goals.view('alpha'))
        prepared = _prepare(runtime, goal)
        assert prepared['state'] == 'prepared'
        assert prepared['evidence_authority'] == 'host_declared'
        assert prepared['external_source_verified'] is False
        markdown = prepared['preparation']['task_markdown']
        assert 'send_confirmation' in markdown and 'Order confirmed' in markdown
        assert 'Source evidence authority: host_declared' in markdown
        assert prepared['preparation']['flow_authority_fingerprint'] in markdown
        assert _prepare(runtime, goal)['assignment_id'] == prepared['assignment_id']
        submitted = _submit(runtime, prepared, _result(goal, requirement, candidate))
        assert submitted['state'] == 'validated'
        assert submitted['source_currentness'] == 'host_declared_as_of_submission'
        assert runtime.ledger.grounding_audits('alpha') == []
        adopted = runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator', request_id='adopt-1')
        assert adopted['adoption']['authority_scope'] == 'grounding_audit_only'
        assert adopted['human_acceptance'] is False and adopted['semantic_truth_verified'] is False
        audits = runtime.ledger.grounding_audits('alpha')
        assert len(audits) == 1
        assert audits[0]['provider_id'] == '' and audits[0]['evidence_authority'] == 'host_declared'
        assert audits[0]['provenance']['executor_ref'] == 'external-agent'
        assert audits[0]['anchors'][0]['source_excerpt'] == _receipt()['anchors'][0]['source_excerpt']
        projection = live_grounding_readiness(project_id='alpha', goal_node_ids=(goal['goal_node_id'],), audits=audits)
        assert projection['ready'] is True  # Semantic readiness still requires an actual campaign.
        assert projection['contract_version'] == 'flower-host-grounding-evidence-v1'
        assert projection['evidence_authority'] == 'host_declared'
        assert projection['source_currentness'] == 'host_declared_as_of_submission'
        assert projection['provenance']['executor_ref'] == 'external-agent'
        assert projection['provider_audited'] is False
        assert projection['external_source_verified'] is False and projection['behavior_verified'] is False
        assert runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')['adoption'] == adopted['adoption']
        assert len(runtime.ledger.grounding_audits('alpha')) == 1
        assert runtime.requirements.traceability('alpha') == before_requirements
        assert runtime.goals.view('alpha') == before_goals
    finally:
        runtime.close()


@pytest.mark.parametrize('case', ['extra', 'unknown_anchor', 'unknown_requirement', 'extra_item', 'missing_field',
                                 'duplicate_goal', 'missing_goal', 'boolean_confidence', 'string_id', 'duplicate_ref'])
def test_invalid_grounding_output_retains_attempt_and_accepts_corrected_result(tmp_path, case):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        prepared = _prepare(runtime, goal)
        output = _result(goal, requirement, candidate)
        item = output['assessments'][0]
        if case == 'extra': output['acceptance'] = True
        elif case == 'unknown_anchor': item['anchor_ids'] = ['HOST-UNKNOWN']
        elif case == 'unknown_requirement': item['requirement_ids'] = ['REQ-999999']
        elif case == 'extra_item': item['accepted'] = True
        elif case == 'missing_field': item.pop('confidence')
        elif case == 'duplicate_goal': output['assessments'].append(deepcopy(item))
        elif case == 'missing_goal': output['assessments'] = []
        elif case == 'boolean_confidence': item['confidence'] = True
        elif case == 'string_id': item['anchor_ids'] = [1]
        elif case == 'duplicate_ref': item['anchor_ids'] = ['HOST-1', 'HOST-1']
        bad = _submit(runtime, prepared, output, request_id='bad')
        assert bad['reason'] == 'semantic_output_invalid' and bad['durable_state'] == 'prepared'
        assert runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_result_not_validated'
        corrected = _submit(runtime, prepared, _result(goal, requirement, candidate), request_id='corrected')
        assert corrected['state'] == 'validated'
        assert corrected['event_count'] == 3
    finally:
        runtime.close()


@pytest.mark.parametrize('case', ['unknown_field', 'provider_claim', 'unknown_version', 'nonboolean', 'duplicate_anchor',
                                 'open_dependency', 'excerpt_bound', 'aggregate_bound', 'absolute_path', 'url_path',
                                 'traversal', 'excerpt_without_path', 'metadata_type', 'anchor_type',
                                 'anchor_count', 'receipt_bytes', 'nonfinite_json', 'nonjson'])
def test_strict_host_evidence_rejects_malformed_or_unbounded_receipts(tmp_path, case):
    runtime, goal, _, _ = _runtime(tmp_path)
    try:
        receipt = _receipt()
        anchor = receipt['anchors'][0]
        if case == 'unknown_field': receipt['commands'] = ['run source']
        elif case == 'provider_claim': receipt['provider_id'] = 'audited-provider'
        elif case == 'unknown_version': receipt['contract_version'] = 'vNext'
        elif case == 'nonboolean': receipt['truncated'] = 1
        elif case == 'duplicate_anchor': receipt['anchors'].append(deepcopy(anchor))
        elif case == 'open_dependency': anchor['dependency_anchor_ids'] = ['HOST-OTHER']
        elif case == 'excerpt_bound': anchor['source_excerpt'] = 'a' * 4097
        elif case == 'aggregate_bound': receipt['anchors'] = [{**anchor, 'anchor_id': f'HOST-{n}', 'source_excerpt': 'a' * 4096} for n in range(6)]
        elif case == 'absolute_path': anchor['source_path'] = '/private/src/example.py'
        elif case == 'url_path': anchor['source_path'] = 'https://example.com/source.py'
        elif case == 'traversal': anchor['source_path'] = '../secret.py'
        elif case == 'excerpt_without_path': anchor.pop('source_path')
        elif case == 'metadata_type': anchor['metadata'] = {'counter': 1}
        elif case == 'anchor_type': anchor['anchor_id'] = 1
        elif case == 'anchor_count': receipt['anchors'] = [{**anchor, 'anchor_id': f'HOST-{n}'} for n in range(129)]
        elif case == 'receipt_bytes': anchor['evidence_ids'] = [f'{n:04d}' + 'x' * 2044 for n in range(128)]
        elif case == 'nonfinite_json': anchor['metadata'] = {'assertion': float('nan')}
        elif case == 'nonjson': anchor['metadata'] = {'assertion': {'set-value'}}
        with pytest.raises(ValueError):
            _prepare(runtime, goal, receipt=receipt)
        with sqlite3.connect(tmp_path / 'ledger.sqlite3') as connection:
            assert connection.execute('select count(*) from semantic_assignments').fetchone()[0] == 0
    finally:
        runtime.close()


def test_host_restart_replay_conflicts_and_changed_source_remain_truthful(tmp_path):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    prepared = _prepare(runtime, goal)
    markdown = prepared['preparation']['task_markdown']
    runtime.close()
    resumed = build_runtime(database_path=tmp_path / 'ledger.sqlite3', import_root=tmp_path)
    try:
        assert resumed.semantic_assignments.inspect('alpha', prepared['assignment_id'])['preparation']['task_markdown'] == markdown
        stale = _submit(resumed, prepared, _result(goal, requirement, candidate), revision='git:changed', request_id='stale')
        assert stale['reason'] == 'semantic_source_stale' and stale['durable_state'] == 'prepared'
        assert resumed.semantic_assignments.inspect('alpha', prepared['assignment_id'])['current'] is False
        submitted = _submit(resumed, prepared, _result(goal, requirement, candidate))
        assert submitted['state'] == 'validated'
        assert _submit(resumed, prepared, _result(goal, requirement, candidate))['result'] == submitted['result']
        with pytest.raises(RequirementConflictError):
            _submit(resumed, prepared, _result(goal, requirement, candidate), request_id='changed-provenance', executor='other-agent')
        changed_later = _submit(resumed, prepared, _result(goal, requirement, candidate), revision='git:new', request_id='later-change')
        assert changed_later['reason'] == 'semantic_source_stale' and changed_later['durable_state'] == 'validated'
        assert resumed.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_source_stale'
        inspected = resumed.semantic_assignments.inspect('alpha', prepared['assignment_id'])
        assert inspected['result'] == submitted['result'] and inspected['event_count'] == 4
        assert inspected['source_currentness'] == changed_later['source_currentness'] == 'host_declared_changed'
    finally:
        resumed.close()


def test_changed_flow_semantics_blocks_submission_and_adoption(tmp_path):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        prepared = _prepare(runtime, goal)
        _submit(runtime, prepared, _result(goal, requirement, candidate))
        runtime.requirements.revise('alpha', requirement['requirement_id'], RequirementDraft(
            title='Confirmation', statement='A successful order shows confirmation and a receipt.', category='functional'),
            actor='operator', rationale='Changed intended behavior')
        assert runtime.semantic_assignments.inspect('alpha', prepared['assignment_id'])['currentness_reason'] == 'semantic_flow_authority_stale'
        assert runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_flow_authority_stale'
        stale = _submit(runtime, prepared, _result(goal, requirement, candidate), request_id='stale-flow')
        assert stale['reason'] == 'semantic_flow_authority_stale'
        assert stale['events'][-1]['payload']['currentness_reason'] == 'semantic_flow_authority_stale'
    finally:
        runtime.close()


def test_semantic_fingerprint_ignores_audit_metadata_but_tracks_goal_edges_and_candidates(tmp_path, monkeypatch):
    runtime, goal, _, _ = _runtime(tmp_path)
    try:
        original = runtime.ledger.goal_graph
        def metadata_only(project_id):
            graph = deepcopy(original(project_id))
            for item in graph['nodes'] + graph['requirement_candidates'] + graph['edges']:
                item['created_at'] = 'changed bookkeeping timestamp'
                item['created_by'] = 'different audit actor'
            return graph
        prepared = _prepare(runtime, goal)
        monkeypatch.setattr(runtime.ledger, 'goal_graph', metadata_only)
        assert runtime.semantic_assignments.inspect('alpha', prepared['assignment_id'])['current'] is True
        def changed_candidate(project_id):
            graph = metadata_only(project_id)
            graph['requirement_candidates'][0]['statement'] = 'Changed intended outcome'
            return graph
        monkeypatch.setattr(runtime.ledger, 'goal_graph', changed_candidate)
        assert runtime.semantic_assignments.inspect('alpha', prepared['assignment_id'])['currentness_reason'] == 'semantic_flow_authority_stale'
        monkeypatch.setattr(runtime.ledger, 'goal_graph', original)
        second = runtime.goals.add_behavioral_expectation('alpha', BehavioralExpectationDraft(
            title='Receipt', statement='The customer receives a receipt.', category='functional',
            observable_outcome='A receipt is visible.'), actor='operator')
        runtime.goals.link('alpha', source_goal_id=goal['goal_node_id'], target_goal_id=second['goal_node_id'],
                           relation='supports', actor='operator')
        assert runtime.semantic_assignments.inspect('alpha', prepared['assignment_id'])['currentness_reason'] == 'semantic_flow_authority_stale'
    finally:
        runtime.close()


def test_validator_keeps_candidates_local_to_each_selected_goal(tmp_path):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        second = runtime.goals.add_behavioral_expectation('alpha', BehavioralExpectationDraft(
            title='Receipt', statement='The customer receives a receipt.', category='functional',
            observable_outcome='A receipt is visible.'), actor='operator')
        runtime.goals.derive_requirement_candidates('alpha', actor='operator')
        graph = runtime.goals.view('alpha')
        other_candidate = next(c for c in graph['requirement_candidates'] if c['source_goal_id'] == second['goal_node_id'])
        prepared = runtime.semantic_assignments.prepare('alpha', role='intention_grounding', execution_mode='host',
            goal_node_ids=(goal['goal_node_id'], second['goal_node_id']), host_evidence=_receipt(), actor='operator')
        output = _result(goal, requirement, candidate)
        output['assessments'].append({**output['assessments'][0], 'goal_node_id': second['goal_node_id'],
                                      'candidate_ids': [candidate['candidate_id']]})
        assert _submit(runtime, prepared, output)['reason'] == 'semantic_output_invalid'
        output['assessments'][1]['candidate_ids'] = [other_candidate['candidate_id']]
        assert _submit(runtime, prepared, output, request_id='corrected')['state'] == 'validated'
    finally:
        runtime.close()


def test_host_declared_truncation_and_empty_evidence_remain_explicit(tmp_path):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        receipt = _receipt()
        receipt['truncated'], receipt['anchors'] = True, []
        prepared = _prepare(runtime, goal, receipt=receipt)
        assert prepared['preparation']['scope']['coverage']['anchor_count'] == 0
        assert 'not a completed source investigation' in prepared['preparation']['task_markdown']
        assert 'omitted evidence has not been assessed' in prepared['preparation']['task_markdown']
        result = _submit(runtime, prepared, _result(goal, requirement, candidate,
            anchor_ids=[], classification='evidence_missing'))
        assert result['result']['audit']['disposition'] == 'needs_review'
        adopted = runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')
        assert adopted['adoption']['disposition'] == 'needs_review'
        projection = live_grounding_readiness(project_id='alpha', goal_node_ids=(goal['goal_node_id'],),
                                               audits=runtime.ledger.grounding_audits('alpha'))
        assert projection['ready'] is False and projection['provider_audited'] is False
    finally:
        runtime.close()


@pytest.mark.parametrize('empty_receipt', [True, False])
def test_host_convergence_without_cited_goal_evidence_is_not_live_ready(tmp_path, empty_receipt):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        receipt = _receipt()
        if empty_receipt:
            receipt['anchors'] = []
        prepared = _prepare(runtime, goal, receipt=receipt)
        submitted = _submit(runtime, prepared, _result(goal, requirement, candidate, anchor_ids=[]))
        assert submitted['state'] == 'validated'  # Structural conformance is separate from readiness.
        runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')
        projection = live_grounding_readiness(project_id='alpha', goal_node_ids=(goal['goal_node_id'],),
                                               audits=runtime.ledger.grounding_audits('alpha'))
        assert projection['ready'] is False
        assert projection['uncited_goal_ids'] == [goal['goal_node_id']]
        assert projection['gaps'] == ['implementation_grounding_goal_evidence_missing']
        assert projection['evidence_authority'] == 'host_declared'
    finally:
        runtime.close()


def test_shared_validator_rejects_ids_omitted_from_bounded_prompt(tmp_path):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        second = runtime.requirements.register('alpha', RequirementDraft(title='Second', statement='A second outcome is required.', category='functional'), actor='operator')
        receipt = _receipt()
        receipt['anchors'].append({**receipt['anchors'][0], 'anchor_id': 'HOST-2'})
        runtime.grounding._policy = replace(runtime.grounding._policy, max_anchors=1, max_requirements=1)
        prepared = _prepare(runtime, goal, receipt=receipt)
        assert prepared['preparation']['input_truncated'] is True
        for i, update in enumerate(({'anchor_ids': ['HOST-2']}, {'requirement_ids': [second['requirement_id']]})):
            bad = _submit(runtime, prepared, _result(goal, requirement, candidate, **update), request_id=f'hidden-{i}')
            assert bad['reason'] == 'semantic_output_invalid'
        good = _submit(runtime, prepared, _result(goal, requirement, candidate), request_id='visible')
        assert good['result']['audit']['disposition'] == 'needs_review'
        assert {a['anchor_id'] for a in good['result']['audit']['anchors']} == {'HOST-1'}
        assert not any(i['anchor_ids'] == ['HOST-2'] for i in good['result']['audit']['items'])
    finally:
        runtime.close()


def test_atomic_grounding_adoption_rolls_back_audit_and_receipt(tmp_path, monkeypatch):
    runtime, goal, requirement, candidate = _runtime(tmp_path)
    try:
        prepared = _prepare(runtime, goal)
        _submit(runtime, prepared, _result(goal, requirement, candidate))
        original = runtime.ledger.adopt_semantic_assignment
        def fail_receipt(*a, **k):
            raise RuntimeError('simulated response loss before receipt')
        monkeypatch.setattr(runtime.ledger, 'adopt_semantic_assignment', fail_receipt)
        with pytest.raises(RuntimeError, match='simulated response loss'):
            runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')
        assert runtime.ledger.grounding_audits('alpha') == []
        assert runtime.semantic_assignments.inspect('alpha', prepared['assignment_id'])['state'] == 'validated'
        monkeypatch.setattr(runtime.ledger, 'adopt_semantic_assignment', original)
        runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')
        assert len(runtime.ledger.grounding_audits('alpha')) == 1
    finally:
        runtime.close()


class Provider:
    def __init__(self): self.calls = []
    def snapshot(self, request):
        self.calls.append(request)
        return ImplementationGraphSnapshot(project_id='alpha', provider_id='provider:test', source_revision='git:abc123',
            anchors=(ImplementationAnchor(anchor_id='HOST-1', kind='symbol', label='send_confirmation',
                summary='Creates a visible confirmation.', source_path='src/orders.py',
                source_excerpt=_receipt()['anchors'][0]['source_excerpt']),))


def test_internal_assignment_and_legacy_route_use_shared_contract(tmp_path):
    provider, requests = Provider(), []
    state = {}
    gateway = CallableModelGateway(lambda request: requests.append(request) or ModelResult(text='',
        structured_output=state['output'], model='grounder:test', terminal_reason='completed'))
    runtime, goal, requirement, candidate = _runtime(tmp_path, implementation_provider=provider, model_gateway=gateway)
    try:
        state['output'] = _result(goal, requirement, candidate)
        internal = _prepare(runtime, goal, mode='internal')
        assert not requests and len(provider.calls) == 1
        host = _prepare(runtime, goal, request_id='host')
        host_result = _submit(runtime, host, state['output'])
        executed = runtime.semantic_assignments.execute_internal('alpha', internal['assignment_id'], actor='operator', request_id='run')
        assert executed['state'] == 'validated' and len(requests) == 1
        assert executed['result']['audit']['items'] == host_result['result']['audit']['items']
        assert requests[0].messages[0] == internal['preparation']['request']['messages'][0]
        assert requests[0].output_schema == host['preparation']['request']['output_schema']
        runtime.semantic_assignments.execute_internal('alpha', internal['assignment_id'], actor='operator')
        assert len(requests) == 1
        legacy = runtime.grounding.ground('alpha', goal_node_ids=(goal['goal_node_id'],), actor='operator')
        assert legacy.prompt_version == 'intention-grounding-v2'
        assert requests[-1].messages[0] == requests[0].messages[0]
        assert legacy.evidence_authority == 'provider_snapshot'
    finally:
        runtime.close()


def test_internal_failed_or_interrupted_grounding_never_reinvokes(tmp_path):
    calls = []
    gateway = CallableModelGateway(lambda r: calls.append(r) or (_ for _ in ()).throw(ModelBackendError('failure')))
    runtime, goal, _, _ = _runtime(tmp_path, implementation_provider=Provider(), model_gateway=gateway)
    prepared = _prepare(runtime, goal, mode='internal')
    try:
        failed = runtime.semantic_assignments.execute_internal('alpha', prepared['assignment_id'], actor='operator')
        assert failed['durable_state'] == 'internal_failed'
        assert runtime.semantic_assignments.execute_internal('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_internal_already_attempted'
        assert len(calls) == 1
        second = _prepare(runtime, goal, mode='internal', request_id='second')
        runtime.ledger.begin_semantic_internal('alpha', second['assignment_id'], actor='operator')
    finally:
        runtime.close()
    resumed = build_runtime(database_path=tmp_path / 'ledger.sqlite3', import_root=tmp_path,
                            implementation_provider=Provider(), model_gateway=gateway)
    try:
        assert resumed.semantic_assignments.inspect('alpha', second['assignment_id'])['state'] == 'internal_interrupted'
        assert resumed.semantic_assignments.execute_internal('alpha', second['assignment_id'], actor='operator')['reason'] == 'semantic_internal_already_attempted'
        assert len(calls) == 1
    finally:
        resumed.close()


def test_internal_authority_change_during_execution_retains_failed_receipt(tmp_path):
    state, calls = {}, []
    def change_authority(request):
        calls.append(request)
        runtime = state['runtime']
        runtime.requirements.revise('alpha', state['requirement']['requirement_id'], RequirementDraft(
            title='Changed confirmation', statement='Confirmation includes a receipt.', category='functional'),
            actor='operator', rationale='Intent changed during bounded execution')
        return ModelResult(text='', structured_output=state['output'], model='internal', terminal_reason='completed')
    runtime, goal, requirement, candidate = _runtime(tmp_path, implementation_provider=Provider(),
        model_gateway=CallableModelGateway(change_authority))
    state.update(runtime=runtime, requirement=requirement, output=_result(goal, requirement, candidate))
    try:
        prepared = _prepare(runtime, goal, mode='internal')
        blocked = runtime.semantic_assignments.execute_internal('alpha', prepared['assignment_id'], actor='operator')
        assert blocked['reason'] == 'semantic_flow_authority_stale'
        assert blocked['durable_state'] == 'internal_failed'
        assert blocked['events'][-1]['payload']['terminal_reason'] == 'completed'
        assert blocked['events'][-1]['payload']['currentness_reason'] == 'semantic_flow_authority_stale'
        assert runtime.semantic_assignments.adopt('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_flow_authority_stale'
        assert runtime.semantic_assignments.execute_internal('alpha', prepared['assignment_id'], actor='operator')['reason'] == 'semantic_internal_already_attempted'
        assert len(calls) == 1 and runtime.ledger.grounding_audits('alpha') == []
    finally:
        runtime.close()


def test_migration_preserves_historical_provider_audit_defaults(tmp_path):
    output = {}
    gateway = CallableModelGateway(lambda r: ModelResult(text='', structured_output=output['result'], model='internal', terminal_reason='completed'))
    runtime, goal, requirement, candidate = _runtime(tmp_path, implementation_provider=Provider(), model_gateway=gateway)
    output['result'] = _result(goal, requirement, candidate)
    runtime.grounding.ground('alpha', goal_node_ids=(goal['goal_node_id'],), actor='operator')
    runtime.close()
    with sqlite3.connect(tmp_path / 'ledger.sqlite3') as connection:
        connection.execute('ALTER TABLE grounding_audits DROP COLUMN evidence_authority')
        connection.execute('ALTER TABLE grounding_audits DROP COLUMN provenance_json')
        connection.execute('ALTER TABLE grounding_audit_anchors DROP COLUMN source_excerpt')
        connection.execute('DELETE FROM schema_migrations WHERE version = 52')
    resumed = build_runtime(database_path=tmp_path / 'ledger.sqlite3', import_root=tmp_path)
    try:
        audit = resumed.ledger.grounding_audits('alpha')[0]
        assert audit['audit_id'] == 1 and audit['provider_id'] == 'provider:test'
        assert audit['evidence_authority'] == 'provider_snapshot' and audit['provenance'] == {}
        assert audit['anchors'][0]['source_excerpt'] == ''
        projection = live_grounding_readiness(project_id='alpha', goal_node_ids=(goal['goal_node_id'],), audits=[audit])
        assert projection['contract_version'] == 'implementation-graph-snapshot-v1'
        assert projection['evidence_authority'] == 'provider_snapshot'
        assert projection['provider_audited'] is False
        assert projection['behavior_verified'] is False
    finally:
        resumed.close()


def test_registered_public_host_grounding_without_optional_integrations(tmp_path):
    from flow_of_work_mcp.server import create_app
    async def run():
        runtime, goal, requirement, candidate = _runtime(tmp_path)
        try:
            app = create_app(runtime)
            async def call(operation, **fields):
                response = await app.call_tool('fow_semantic', {'project_id': 'alpha', 'operation': operation, **fields})
                assert response.isError is False
                envelope = response.structuredContent['result']
                assert envelope['reason'] != 'internal_error'
                return envelope, response.content[0].text
            prepared, markdown = await call('prepare', role='intention_grounding', execution_mode='host',
                goal_node_ids=[goal['goal_node_id']], host_evidence=_receipt(), actor='operator')
            assert prepared['status'] == 'success'
            assignment = prepared['result']
            assert assignment['preparation']['task_markdown'] in markdown
            submitted, _ = await call('submit', assignment_id=assignment['assignment_id'],
                result=_result(goal, requirement, candidate), source_revision='git:abc123', executor_ref='public-agent', actor='operator')
            assert submitted['status'] == 'success'
            adopted, _ = await call('adopt', assignment_id=assignment['assignment_id'], actor='operator')
            assert adopted['status'] == 'success' and adopted['result']['adoption']['grounding_audit_id'] == 1
            assert adopted['result']['evidence_authority'] == 'host_declared'
            assert adopted['result']['external_source_verified'] is False
            absent, _ = await call('prepare', role='intention_grounding', execution_mode='internal',
                goal_node_ids=[goal['goal_node_id']], actor='operator')
            assert absent['status'] == 'blocked' and absent['reason'] == 'semantic_grounding_provider_unconfigured'
        finally:
            runtime.close()
    asyncio.run(run())
