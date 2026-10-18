"""Approved progressive bootstrap preserves intent and execution boundaries."""
import asyncio
from copy import deepcopy

import pytest

from tests.test_external_work import fixture as external_fixture, report
from flow_of_work_mcp import ImplementationPacketDraft, MilestoneDraft, RequirementDraft, UseCaseDraft
from flow_of_work_mcp.core.domain.change_control import PacketStatus, PacketTransition
from flow_of_work_mcp.core.domain.packet_construction import PacketConstructionAuditDraft
from flow_of_work_mcp.core.domain.enums import LifecycleStatus
from flow_of_work_mcp.core.errors import BootstrapBlockedError, ChangeControlBlockedError, RequirementConflictError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import create_app, handle_bootstrap


def prepared(tmp_path):
    ledger, _service, ids, revs = external_fixture(tmp_path)
    runtime = build_runtime(database_path=tmp_path / 'flower.sqlite', import_root=tmp_path, ledger=ledger)
    requirement_id = ledger.change_state(ids[0], ids[1])['requirement_ids'][0]
    goal = runtime.goals.add_use_case(ids[0], UseCaseDraft(title='Increment an integer', actor='User',
        objective='Obtain the successor', observable_outcome='The client returns value + 1'), actor='engineer')
    milestone = ledger.promote_milestone(ids[0], MilestoneDraft(name='Successor behavior',
        requirement_ids=(requirement_id,), prerequisite_requirement_ids=(),
        entry_policy={'intent':'scenario clarified'}, exit_policy={'checks':'declared criteria'},
        risk_disposition='no external effects'), actor='engineer')
    ledger.link_change_milestone(ids[0], ids[1], milestone['milestone_id'], actor='engineer')
    boot = runtime.bootstrap.start(ids[0], project_name='Offline example', path='guided_engineering', actor='human', request_id='guided-start')
    answer = {'answer_key':'scenario', 'question':'What should it do?', 'answer':'Show the successor of my integer.',
              'kind':'intent', 'source_reference':'stakeholder-dialogue:1'}
    runtime.guided_bootstrap.record_answer(ids[0], boot['bootstrap_id'], answer=answer, actor='engineer', request_id='answer')
    refs = {'requirement_ids':[requirement_id], 'goal_node_ids':[goal['goal_node_id']], 'milestone_ids':[milestone['milestone_id']]}
    correspondence = {'answer_key':'scenario', 'answer_revision':1, 'canonical_references':refs,
                      'disposition':'consistent', 'rationale':'The scenario and requirement express the same successor behavior.'}
    runtime.guided_bootstrap.record_correspondence(ids[0], boot['bootstrap_id'], correspondence=correspondence,
                                                actor='engineer', request_id='mapping')
    return runtime, ids, revs, boot['bootstrap_id'], milestone['milestone_id'], answer, correspondence


def confirm(runtime, ids, bootstrap_id, milestone_id):
    roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
    assert roadmap['confirmable'] and not roadmap['confirmed']
    runtime.guided_bootstrap.confirm_roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id],
        roadmap_fingerprint=roadmap['roadmap_fingerprint'], confirmation_reference='human:explicit-roadmap-confirmation',
        actor='human', request_id='confirmation')
    return roadmap


def test_guided_new_and_populated_routes_preserve_legacy_and_private_exploration(tmp_path):
    runtime = build_runtime(database_path=tmp_path/'new.sqlite', import_root=tmp_path)
    try:
        boot = runtime.bootstrap.start('new', project_name='New', path='guided_engineering', actor='human')
        guidance = runtime.guided_bootstrap.guidance('new', boot['bootstrap_id'])
        assert guidance['next_gate']['operation'] == 'record_answer'
        assert 'what should the software do and show' in guidance['markdown'].lower()
        assert runtime.ledger.traceability_matrix('new') == []
        with pytest.raises(BootstrapBlockedError, match='guided_operations'):
            runtime.bootstrap.record_intake('new', boot['bootstrap_id'], intake={'_guided':{'forged':True}}, actor='host')
        with pytest.raises(BootstrapBlockedError):
            runtime.bootstrap.complete('new', boot['bootstrap_id'], completion_reference='fake', actor='host')
        with pytest.raises(BootstrapBlockedError):
            runtime.guided_bootstrap.complete('new', boot['bootstrap_id'], completion_reference='fake', actor='host', request_id='early')
    finally:
        runtime.close()


def test_confirmation_full_scope_execution_handoff_progress_and_restart(tmp_path):
    runtime, ids, revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        blocked = runtime.external_work.todo(*ids)
        assert blocked['status'] == 'blocked' and blocked['reason'] == 'guided_roadmap_confirmation_required'
        roadmap = confirm(runtime, ids, bootstrap_id, milestone_id)
        complete = runtime.guided_bootstrap.complete(ids[0], bootstrap_id, completion_reference='prepared-plan:1', actor='host', request_id='handoff')
        assert complete['status'] == 'completed'
        assert complete['completion_handoff']['implementation_claim'] == 'not_inferred'
        assert complete['completion_handoff']['packets'][0]['packet_id'] == ids[2]
        exported = runtime.external_work.call(*ids, 'export_plan', actor='host', request_id='export', payload=revs)
        assert 'increment(value: int) -> int' in exported['content']
        initial = runtime.milestone_traceability.progress(ids[0], milestone_ids=(milestone_id,))
        assert initial['implementation']['percent'] == 0
        payload = report(runtime.external_work, ids, revs)
        runtime.external_work.call(*ids, 'report_outcome', actor='host', request_id='producer-done', payload=payload)
        changed = runtime.milestone_traceability.progress(ids[0], milestone_ids=(milestone_id,))
        assert changed['scope_revision'] == initial['scope_revision']
        assert changed['progress_revision'] != initial['progress_revision']
        with pytest.raises(BootstrapBlockedError, match='progress_revision_stale'):
            runtime.guided_bootstrap.record_continuation(ids[0], bootstrap_id, continuation_choice='continue',
                continuation_reference='human:continue', roadmap_fingerprint=roadmap['roadmap_fingerprint'],
                progress_revision=initial['progress_revision'], reason='Checkpoint with one unit complete', actor='human', request_id='stale-progress')
        continued = runtime.guided_bootstrap.record_continuation(ids[0], bootstrap_id, continuation_choice='review',
            continuation_reference='human:review', roadmap_fingerprint=roadmap['roadmap_fingerprint'],
            progress_revision=changed['progress_revision'], reason='Review current result and residual criteria', actor='human', request_id='review')
        assert continued['intake']['_guided']['continuation']['human_acceptance'] is False
        assert runtime.ledger.milestones(ids[0])[0]['status'] == 'planned'
    finally:
        runtime.close()
    reopened = build_runtime(database_path=tmp_path/'flower.sqlite', import_root=tmp_path)
    try:
        assert reopened.guided_bootstrap.guidance(ids[0], bootstrap_id)['next_gate']['operation'] == 'project_progress'
        assert reopened.external_work.todo(*ids)['current_unit']['unit_key'] == 'consumer'
        assert reopened.guided_bootstrap.complete(ids[0], bootstrap_id, completion_reference='prepared-plan:1', actor='host', request_id='handoff')['status'] == 'completed'
    finally:
        reopened.close()


def test_corrections_stale_mapping_confirmation_and_normalized_replay(tmp_path):
    runtime, ids, _revs, bootstrap_id, milestone_id, answer, mapping = prepared(tmp_path)
    try:
        confirm(runtime, ids, bootstrap_id, milestone_id)
        correction = {**answer, 'answer':'Also explain overflow behavior.'}
        runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=correction, actor=' host ', request_id=' correction ')
        again = runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=correction, actor=' host ', request_id=' correction ')
        assert again['intake']['_guided']['answers']['scenario']['revision'] == 2
        with pytest.raises(RequirementConflictError):
            runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=answer, actor='host', request_id='correction')
        blocked = runtime.external_work.todo(*ids)
        assert blocked['status'] == 'blocked' and blocked['reason'] == 'guided_roadmap_confirmation_stale'
        with pytest.raises(BootstrapBlockedError, match='revision_stale'):
            runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap_id, correspondence=mapping, actor='host', request_id='old-mapping')
        with pytest.raises(RequirementConflictError, match='start_request_conflict'):
            runtime.bootstrap.start(ids[0], project_name='Wrong', path='guided_engineering', actor='human', request_id='guided-start')
        assert runtime.guided_bootstrap.guidance(ids[0], bootstrap_id)['next_gate']['operation'] == 'record_correspondence'
    finally:
        runtime.close()


def test_meaning_staleness_retirement_missing_milestone_scope_and_no_progress_noise(tmp_path):
    runtime, ids, _revs, bootstrap_id, milestone_id, _answer, mapping = prepared(tmp_path)
    try:
        roadmap = confirm(runtime, ids, bootstrap_id, milestone_id)
        requirement_id = mapping['canonical_references']['requirement_ids'][0]
        runtime.ledger.set_lifecycle_status(ids[0], requirement_id, status=LifecycleStatus.PARTIAL, actor='host', reason='An outcome is recorded')
        assert runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])['roadmap_fingerprint'] == roadmap['roadmap_fingerprint']
        extra = runtime.requirements.register(ids[0], RequirementDraft(title='Explain overflow', statement='Explain overflow.',
             category='functional', rationale='Separate behavior'), actor='human')
        other = runtime.ledger.promote_milestone(ids[0], MilestoneDraft(name='Overflow', requirement_ids=(extra['requirement_id'],),
            prerequisite_requirement_ids=(), entry_policy={'intent':'defined'}, exit_policy={'check':'observable'},
            risk_disposition='requires further planning'), actor='host')
        extra_roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id,other['milestone_id']])
        runtime.guided_bootstrap.confirm_roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id,other['milestone_id']],
            roadmap_fingerprint=extra_roadmap['roadmap_fingerprint'], confirmation_reference='human:both', actor='human', request_id='both')
        with pytest.raises(BootstrapBlockedError, match='incompletely_planned'):
            runtime.guided_bootstrap.complete(ids[0], bootstrap_id, completion_reference='partial', actor='host', request_id='incomplete-handoff')
        runtime.ledger.set_lifecycle_status(ids[0], requirement_id, status=LifecycleStatus.REMOVED, actor='human', reason='Changed intended spectrum', governance_reference='human:retirement')
        stale = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert not stale['confirmable'] and stale['roadmap_fingerprint'] != roadmap['roadmap_fingerprint']
    finally:
        runtime.close()


def test_registered_guided_markdown_and_progress_channels_are_complete(tmp_path):
    runtime, ids, _revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer={
        'answer_key':'future', 'question':'Any later work?', 'answer':'UNASSIGNED_REAL_DRAFT_SENTINEL',
        'kind':'proposal', 'source_reference':'synthetic-dialogue:future',
    }, actor='engineer', request_id='future-draft')
    async def run():
        app = create_app(runtime)
        result = await app.call_tool('fow_bootstrap', {'project_id':ids[0], 'operation':'roadmap',
            'bootstrap_id':bootstrap_id, 'milestone_ids':[milestone_id], 'actor':'host'})
        assert not result.isError
        payload = result.structuredContent['result']['result']['bootstrap']
        assert payload['markdown'] in result.content[0].text
        assert '\n## Milestones' in result.content[0].text
        assert payload['draft_context']['authority'] == 'outside_selected_scope'
        for fact in ('The client returns value + 1', 'UNASSIGNED_REAL_DRAFT_SENTINEL', 'outside_selected_scope'):
            assert payload['markdown'].count(fact) == result.content[0].text.count(fact) == 1
        progress = await app.call_tool('fow_handover', {'project_id':ids[0], 'operation':'project_progress', 'milestone_ids':[milestone_id]})
        assert not progress.isError
        assert progress.structuredContent['result']['result']['project_progress']['contract_version'] == 'flow.milestone_progress.v1'
    try:
        asyncio.run(run())
    finally:
        runtime.close()


def test_roadmap_presentation_cannot_change_canonical_scope_confirmation_or_public_envelope(tmp_path, monkeypatch):
    from hashlib import sha256
    import json
    from flow_of_work_mcp.application import guided_bootstrap

    runtime, ids, _revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        confirm(runtime, ids, bootstrap_id, milestone_id)
        arguments = {'project_id':ids[0], 'operation':'roadmap', 'bootstrap_id':bootstrap_id,
                     'milestone_ids':[milestone_id], 'actor':'engineer'}
        original = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        encoded_basis = json.dumps(original['canonical_scope'], sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False).encode()
        assert original['roadmap_fingerprint'] == sha256(encoded_basis).hexdigest()
        version = runtime.ledger.ledger_version(ids[0])
        state = deepcopy(runtime.bootstrap.state(ids[0], bootstrap_id))
        todo = deepcopy(runtime.external_work.todo(*ids))
        with monkeypatch.context() as rendering:
            rendering.setattr(guided_bootstrap, 'render_roadmap', lambda *_args, **_kwargs: 'PRESENTATION_ONLY')
            alternate = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert alternate['markdown'] == 'PRESENTATION_ONLY'
        assert {k:v for k,v in alternate.items() if k != 'markdown'} == {
            k:v for k,v in original.items() if k != 'markdown'}
        assert runtime.ledger.ledger_version(ids[0]) == version
        assert runtime.bootstrap.state(ids[0], bootstrap_id) == state
        assert runtime.external_work.todo(*ids) == todo
        raw = handle_bootstrap(runtime, **arguments)

        async def run():
            projected = await create_app(runtime).call_tool('fow_bootstrap', arguments)
            assert not projected.isError
            assert projected.structuredContent == {'result':raw}
            assert original['markdown'] in projected.content[0].text
            assert '"entry_policy"' not in original['markdown']
            assert '"canonical_references"' not in original['markdown']
        asyncio.run(run())
    finally:
        runtime.close()


def test_explicit_external_implemented_transition_uses_current_reports_without_acceptance(tmp_path):
    from flow_of_work_mcp.core.domain.change_control import PacketStatus, PacketTransition
    runtime, ids, revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        confirm(runtime, ids, bootstrap_id, milestone_id)
        packet = runtime.ledger.change_state(ids[0], ids[1])['packets'][0]
        transition = PacketTransition(status=PacketStatus.IMPLEMENTED,
            criterion_results={criterion:True for criterion in packet['completion_criteria']})
        with pytest.raises(ChangeControlBlockedError, match='external_packet_implementation_incomplete'):
            runtime.changes.transition_packet(*ids, transition, actor='host', request_id='too-early')
        for key in ('producer', 'consumer'):
            runtime.external_work.call(*ids, 'report_outcome', actor='host', request_id=key+'-report',
                payload=report(runtime.external_work, ids, revs, key, report_key=key+'-done'))
        assert runtime.ledger.change_state(ids[0], ids[1])['packets'][0]['status'] == 'planned'
        missing = PacketTransition(status=PacketStatus.IMPLEMENTED)
        with pytest.raises(ChangeControlBlockedError, match='criteria_missing'):
            runtime.changes.transition_packet(*ids, missing, actor='host', request_id='missing-explicit-results')
        changed = runtime.changes.transition_packet(*ids, transition, actor='host', request_id='explicit-implemented')
        assert changed['packets'][0]['status'] == 'implemented'
        progress = runtime.milestone_traceability.progress(ids[0], milestone_ids=(milestone_id,))
        assert progress['implementation_complete'] and progress['local_verification_complete']
        assert not progress['fully_completed']
        assert runtime.ledger.milestones(ids[0])[0]['status'] == 'planned'
        assert progress['deferred_obligations']
        with pytest.raises(ChangeControlBlockedError, match='verification_pending'):
            runtime.lifecycle.accept_milestone(ids[0], milestone_id, acceptance_evidence=('fixture:reviewed',), actor='human')
    finally:
        runtime.close()


def unrelated_scope(runtime, project_id):
    requirement = runtime.requirements.register(project_id, RequirementDraft(
        title='Explain overflow', statement='Explain integer overflow to the user.',
        category='functional', rationale='A separate possible increment.'), actor='engineer')
    goal = runtime.goals.add_use_case(project_id, UseCaseDraft(
        title='Understand overflow', actor='User', objective='Understand bounds',
        observable_outcome='The client explains its integer limits.'), actor='engineer')
    milestone = runtime.lifecycle.promote_milestone(project_id, MilestoneDraft(
        name='Overflow explanation', requirement_ids=(requirement['requirement_id'],),
        prerequisite_requirement_ids=(),
        entry_policy={'intent':'overflow behavior clarified'},
        exit_policy={'check':'integer limits explained'}, risk_disposition='separate scope'), actor='engineer')
    answer = {'answer_key':'overflow', 'question':'Should it explain overflow?',
              'answer':'Consider an overflow explanation later.', 'kind':'proposal',
              'source_reference':'stakeholder-dialogue:later'}
    mapping = {'answer_key':'overflow', 'answer_revision':1,
               'canonical_references':{'requirement_ids':[requirement['requirement_id']],
                    'goal_node_ids':[goal['goal_node_id']], 'milestone_ids':[milestone['milestone_id']]},
               'disposition':'needs_clarification', 'rationale':'This future scenario is not yet agreed.'}
    return requirement, goal, milestone, answer, mapping


def test_unrelated_and_unassigned_intake_preserves_current_scope_admission_and_restart(tmp_path):
    runtime, ids, revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        original = confirm(runtime, ids, bootstrap_id, milestone_id)
        issued_confirmation = deepcopy(runtime.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation'])
        requirement, _goal, _milestone, answer, mapping = unrelated_scope(runtime, ids[0])
        runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=answer,
                                             actor='engineer', request_id='future-answer')
        unassigned = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert unassigned['confirmed'] and unassigned['roadmap_fingerprint'] == original['roadmap_fingerprint']
        assert unassigned['draft_context']['unassigned_answers']['overflow']['kind'] == 'proposal'
        assert 'overflow' not in unassigned['canonical_scope']['answers']
        assert 'do not govern this roadmap' in unassigned['markdown']
        runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap_id, correspondence=mapping,
                                                     actor='engineer', request_id='future-mapping')
        updated = {**answer, 'answer':'Explore an overflow explanation in a later scope.'}
        runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=updated,
                                             actor='engineer', request_id='future-answer-revision')
        stale_unrelated_mapping = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert stale_unrelated_mapping['confirmed']
        assert stale_unrelated_mapping['draft_context']['outside_scope_correspondence']['overflow']['answer_revision'] == 1
        revised_mapping = {**mapping, 'answer_revision':2}
        runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap_id, correspondence=revised_mapping,
                                                     actor='engineer', request_id='future-mapping-revision')
        runtime.requirements.revise(ids[0], requirement['requirement_id'], RequirementDraft(
            title='Explain overflow', statement='Explain overflow and representable integer bounds.',
            category='functional', rationale='Refine future intent.'), actor='engineer', rationale='Separate later scope.')
        roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert roadmap['confirmed'] and not roadmap['gaps']
        assert roadmap['roadmap_fingerprint'] == original['roadmap_fingerprint']
        assert set(roadmap['canonical_scope']['answers']) == {'scenario'}
        assert roadmap['draft_context']['outside_scope_answers']['overflow']['revision'] == 2
        guidance = runtime.guided_bootstrap.guidance(ids[0], bootstrap_id)
        assert not guidance['blockers'] and guidance['next_gate']['operation'] == 'complete'
        assert runtime.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation'] == issued_confirmation
        assert runtime.external_work.todo(*ids)['current_unit']['unit_key'] == 'producer'
        validation = runtime.external_work.validation(*ids)
        assert validation['plan_executable'] and validation['execution_allowed']
        exported = runtime.external_work.call(*ids, 'export_plan', actor='engineer', request_id='scoped-export', payload=revs)
        assert not exported['draft']
        runtime.external_work.call(*ids, 'report_outcome', actor='engineer', request_id='scoped-outcome',
            payload=report(runtime.external_work, ids, revs))
    finally:
        runtime.close()
    reopened = build_runtime(database_path=tmp_path/'flower.sqlite', import_root=tmp_path)
    try:
        roadmap = reopened.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert roadmap['confirmed'] and roadmap['roadmap_fingerprint'] == original['roadmap_fingerprint']
        assert reopened.external_work.todo(*ids)['current_unit']['unit_key'] == 'consumer'
        replay = reopened.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=updated,
                                                       actor='engineer', request_id='future-answer-revision')
        assert replay['intake']['_guided']['answers']['overflow']['revision'] == 2
        assert reopened.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation'] == issued_confirmation
        assert not reopened.guided_bootstrap.guidance(ids[0], bootstrap_id)['human_acceptance']
    finally:
        reopened.close()


@pytest.mark.parametrize('references', ['full_scope', 'goal_only'])
def test_unassigned_answer_becomes_governing_only_through_explicit_scope_correspondence(tmp_path, references):
    runtime, ids, revs, bootstrap_id, milestone_id, _answer, mapping = prepared(tmp_path)
    try:
        original = confirm(runtime, ids, bootstrap_id, milestone_id)
        outcome = report(runtime.external_work, ids, revs)
        answer = {'answer_key':'negative', 'question':'What should negative integers show?',
                  'answer':'Show their successor too.', 'kind':'intent', 'source_reference':'stakeholder-dialogue:2'}
        runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id, answer=answer,
                                             actor='engineer', request_id='additional-answer')
        assert runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])['confirmed']
        linked = {**mapping, 'answer_key':'negative', 'rationale':'The negative-input scenario governs the selected increment.'}
        if references == 'goal_only':
            linked['canonical_references'] = {'requirement_ids':[], 'milestone_ids':[],
                'goal_node_ids':mapping['canonical_references']['goal_node_ids']}
        runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap_id, correspondence=linked,
                                                     actor='engineer', request_id='additional-correspondence')
        roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert roadmap['confirmable'] and not roadmap['confirmed']
        assert roadmap['roadmap_fingerprint'] != original['roadmap_fingerprint']
        assert 'negative' in roadmap['canonical_scope']['answers']
        assert runtime.external_work.todo(*ids)['reason'] == 'guided_roadmap_confirmation_stale'
        validation = runtime.external_work.validation(*ids)
        assert validation['plan_executable'] and not validation['execution_allowed']
        assert validation['reason'] == 'guided_roadmap_confirmation_stale'
        with pytest.raises(ChangeControlBlockedError, match='confirmation_stale'):
            runtime.external_work.call(*ids, 'report_outcome', actor='engineer', request_id='premature-report', payload=outcome)
        with pytest.raises(ChangeControlBlockedError, match='confirmation_stale'):
            runtime.external_work.call(*ids, 'export_plan', actor='engineer', request_id='premature-export', payload=revs)
        runtime.guided_bootstrap.confirm_roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id],
            roadmap_fingerprint=roadmap['roadmap_fingerprint'], confirmation_reference='human:negative-scenario',
            actor='human', request_id='additional-confirmation')
        assert runtime.external_work.todo(*ids)['current_unit']['unit_key'] == 'producer'
    finally:
        runtime.close()


@pytest.mark.parametrize('change', ['selected_answer', 'selected_requirement', 'related_goal', 'mapping_rebound'])
def test_material_selected_intent_drift_retains_but_stales_confirmation(tmp_path, change):
    runtime, ids, _revs, bootstrap_id, milestone_id, answer, mapping = prepared(tmp_path)
    try:
        original = confirm(runtime, ids, bootstrap_id, milestone_id)
        issued = deepcopy(runtime.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation'])
        if change == 'selected_answer':
            runtime.guided_bootstrap.record_answer(ids[0], bootstrap_id,
                answer={**answer, 'answer':'Show the predecessor instead.'}, actor='engineer', request_id='changed-intent')
        elif change == 'selected_requirement':
            runtime.requirements.revise(ids[0], mapping['canonical_references']['requirement_ids'][0], RequirementDraft(
                title='Predecessor', statement='Return the predecessor integer.', category='functional',
                rationale='Changed intended behavior.'), actor='engineer', rationale='Stakeholder changed intent.')
        elif change == 'related_goal':
            goal = runtime.goals.add_use_case(ids[0], UseCaseDraft(title='Explain the increment', actor='User',
                objective='Understand arithmetic', observable_outcome='The client explains the successor.'), actor='engineer')
            runtime.goals.link(ids[0], source_goal_id=mapping['canonical_references']['goal_node_ids'][0],
                target_goal_id=goal['goal_node_id'], relation='related_to', actor='engineer')
        else:
            _req, _goal, _milestone, _answer, outside = unrelated_scope(runtime, ids[0])
            runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap_id,
                correspondence={**outside, 'answer_key':'scenario', 'disposition':'consistent'},
                actor='engineer', request_id='rebound-correspondence')
        roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert not roadmap['confirmed'] and roadmap['roadmap_fingerprint'] != original['roadmap_fingerprint']
        assert runtime.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation'] == issued
        assert runtime.external_work.todo(*ids)['reason'] == 'guided_roadmap_confirmation_stale'
    finally:
        runtime.close()


@pytest.mark.parametrize('status', [PacketStatus.CANCELLED, PacketStatus.SUPERSEDED])
def test_inactive_packet_questions_audits_and_goal_context_do_not_block_selected_scope(tmp_path, status):
    runtime, ids, _revs, bootstrap_id, milestone_id, _answer, _mapping = prepared(tmp_path)
    try:
        original = confirm(runtime, ids, bootstrap_id, milestone_id)
        unrelated = runtime.goals.add_use_case(ids[0], UseCaseDraft(title='Unused attempt', actor='User',
            objective='Try another behavior', observable_outcome='An abandoned result.'), actor='engineer')
        packet = runtime.changes.add_packet(ids[0], ids[1], ImplementationPacketDraft(
            title='Abandoned packet', objective='An earlier uncertain implementation.',
            rationale='Historical scope', completion_criteria=('inspect earlier result',),
            goal_ids=(unrelated['goal_node_id'],), unresolved_questions=('Earlier unresolved requested behavior?',)),
            actor='engineer')['packets'][-1]
        audit = runtime.packet_construction.start_audit(ids[0], PacketConstructionAuditDraft(
            change_id=ids[1], packet_id=packet['packet_id']), actor='engineer')
        assert any(q['required'] and q['status'] == 'open' for q in audit['questions'])
        active = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert not active['confirmable'] and not active['confirmed']
        assert {'packet_intent_questions_open', 'packet_semantic_decisions_open'} <= {g['reason'] for g in active['gaps']}
        assert unrelated['goal_node_id'] in {g['goal_node_id'] for g in active['canonical_scope']['goals']}
        runtime.changes.transition_packet(ids[0], ids[1], packet['packet_id'], PacketTransition(
            status=status, disposition='Discarded historical attempt.',
            successor_packet_id=ids[2] if status == PacketStatus.SUPERSEDED else ''), actor='engineer')
        inactive = runtime.guided_bootstrap.roadmap(ids[0], bootstrap_id, milestone_ids=[milestone_id])
        assert inactive['confirmed'] and not inactive['gaps']
        assert inactive['roadmap_fingerprint'] == original['roadmap_fingerprint']
        assert unrelated['goal_node_id'] not in {g['goal_node_id'] for g in inactive['canonical_scope']['goals']}
        assert runtime.external_work.todo(*ids)['current_unit']['unit_key'] == 'producer'
        assert runtime.packet_construction.get_audit(ids[0], audit['construction_audit_id'])['questions']
    finally:
        runtime.close()


def test_registered_scoped_intake_preserves_channels_and_only_governing_mapping_blocks_todo(tmp_path):
    runtime, ids, _revs, bootstrap_id, milestone_id, _answer, mapping = prepared(tmp_path)
    original = confirm(runtime, ids, bootstrap_id, milestone_id)
    app = create_app(runtime)

    async def run():
        answer = {'answer_key':'followup', 'question':'A later idea?', 'answer':'Consider a later explanation.',
                  'kind':'proposal', 'source_reference':'stakeholder-dialogue:later'}
        recorded = await app.call_tool('fow_bootstrap', {'project_id':ids[0], 'operation':'record_answer',
            'bootstrap_id':bootstrap_id, 'answer':answer, 'actor':'engineer', 'request_id':'public-unassigned'})
        assert not recorded.isError and recorded.structuredContent['result']['status'] == 'success'
        projected = await app.call_tool('fow_bootstrap', {'project_id':ids[0], 'operation':'roadmap',
            'bootstrap_id':bootstrap_id, 'milestone_ids':[milestone_id], 'actor':'engineer'})
        roadmap = projected.structuredContent['result']['result']['bootstrap']
        assert roadmap['confirmed'] and roadmap['roadmap_fingerprint'] == original['roadmap_fingerprint']
        assert roadmap['draft_context']['unassigned_answers']['followup']['answer'] == answer['answer']
        assert '\n## Draft intake outside the selected scope\n' in projected.content[0].text
        assert roadmap['markdown'] in projected.content[0].text
        todo_args = {'project_id':ids[0], 'change_id':ids[1], 'packet_id':ids[2], 'operation':'todo'}
        current = await app.call_tool('fow_external_work', todo_args)
        assert not current.isError and current.structuredContent['result']['status'] == 'success'
        assert current.structuredContent['result']['result']['current_unit']['unit_key'] == 'producer'
        linked = await app.call_tool('fow_bootstrap', {'project_id':ids[0], 'operation':'record_correspondence',
            'bootstrap_id':bootstrap_id, 'correspondence':{**mapping, 'answer_key':'followup'},
            'actor':'engineer', 'request_id':'public-governing'})
        assert not linked.isError and linked.structuredContent['result']['status'] == 'success'
        blocked = await app.call_tool('fow_external_work', todo_args)
        envelope = blocked.structuredContent['result']
        assert envelope['status'] == 'blocked' and envelope['reason'] == 'guided_roadmap_confirmation_stale'
        assert envelope['reason'] in blocked.content[0].text
        validation = await app.call_tool('fow_external_work', {**todo_args, 'operation':'validation'})
        admission = validation.structuredContent['result']['result']
        assert admission['plan_executable'] and not admission['execution_allowed']
        assert admission['reason'] == 'guided_roadmap_confirmation_stale'
        assert runtime.bootstrap.state(ids[0], bootstrap_id)['intake']['_guided']['roadmap_confirmation']['roadmap_fingerprint'] == original['roadmap_fingerprint']
    try:
        asyncio.run(run())
    finally:
        runtime.close()
