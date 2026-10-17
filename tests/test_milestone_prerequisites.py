"""Realized scope, previous ownership and immutable milestone replay authority."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3

import pytest

from flow_of_work_mcp import LifecycleStatus, MilestoneDraft, SQLiteRequirementLedger
from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
from flow_of_work_mcp.core.errors import (
    BootstrapBlockedError, ChangeControlBlockedError, MilestonePreEffectError,
)


def setup(tmp_path):
    ledger = SQLiteRequirementLedger(tmp_path / 'milestones.sqlite')
    ledger.create_project('alpha', 'Milestone fixture', actor='human')
    requirements = [ledger.add_requirement('alpha', title=f'Requirement {number}',
        statement=f'The software shall implement behavior {number}.', category='functional',
        rationale='Bounded fixture scope.', actor='human')['requirement_id'] for number in range(3)]
    return ledger, requirements


def draft(name, requirements, prerequisites=(), **patch):
    return MilestoneDraft(name=name, requirement_ids=tuple(requirements),
        prerequisite_requirement_ids=tuple(prerequisites), entry_policy={'intent': 'declared'},
        exit_policy={'verification': 'bounded'}, risk_disposition='none', **patch)


def logical_dump(ledger):
    with sqlite3.connect(ledger.database_path) as connection:
        return '\n'.join(connection.iterdump())


def historical_extra(ledger, project, milestone_id, realized, extra):
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute('UPDATE milestones SET dependency_closure_ids_json=? WHERE project_id=? AND milestone_id=?',
            (json.dumps([*realized, extra]), project, milestone_id))


def test_first_empty_and_successor_previous_owners_do_not_infer_acceptance(tmp_path):
    ledger, (first, second, _third) = setup(tmp_path)
    one = ledger.promote_milestone('alpha', draft('first', [first]), actor='engineer')
    another = ledger.promote_milestone('alpha', draft('another owner', [first]), actor='engineer')
    successor = ledger.promote_milestone('alpha', draft('successor', [second], [first]), actor='engineer')
    assert one['prerequisite_requirement_ids'] == []
    assert successor['requirement_ids'] == [second]
    assert successor['prerequisite_requirement_ids'] == [first]
    assert successor['prerequisite_producers'] == {first: [one['milestone_id'], another['milestone_id']]}
    assert successor['prerequisite_mapping_gaps'] == []
    assert {m['status'] for m in ledger.milestones('alpha')} == {'planned'}
    assert 'dependency_closure_ids' not in successor
    with sqlite3.connect(ledger.database_path) as connection:
        assert json.loads(connection.execute('SELECT dependency_closure_ids_json FROM milestones WHERE milestone_id=?',
            (successor['milestone_id'],)).fetchone()[0]) == [second, first]
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 55


@pytest.mark.parametrize('patch,code', [
    ({'requirement_ids': ()}, 'milestone_requirements_empty'),
    ({'requirement_ids': ('REQ-000001', 'REQ-000001')}, 'milestone_ids_duplicate'),
    ({'prerequisite_requirement_ids': ('REQ-000002', 'REQ-000002')}, 'milestone_ids_duplicate'),
    ({'prerequisite_requirement_ids': ('REQ-000001',)}, 'milestone_requirements_overlap'),
    ({'prerequisite_requirement_ids': ('bad-id',)}, 'milestone_input_invalid'),
    ({'entry_policy': {'invalid': float('nan')}}, 'milestone_input_invalid'),
])
def test_invalid_draft_has_typed_pre_effect_proof(tmp_path, patch, code):
    ledger, requirements = setup(tmp_path)
    before = logical_dump(ledger)
    with pytest.raises(MilestonePreEffectError) as rejected:
        replace(draft('invalid', requirements[:1]), **patch)
    assert rejected.value.reason == code
    assert {'code', 'rule', 'resolution'} <= rejected.value.details.keys()
    assert logical_dump(ledger) == before


@pytest.mark.parametrize('kind,code', [('unknown', 'milestone_requirement_missing'),
    ('foreign', 'milestone_requirement_missing'), ('unassigned', 'milestone_prerequisite_unassigned')])
def test_repository_rejections_do_not_consume_rows_sequences_or_events(tmp_path, kind, code):
    ledger, (first, second, _third) = setup(tmp_path)
    prerequisite = second
    if kind == 'unknown':
        prerequisite = 'REQ-999999'
    elif kind == 'foreign':
        ledger.create_project('beta', 'Other project', actor='human')
        for index in range(4):
            prerequisite = ledger.add_requirement('beta', title=f'Foreign {index}',
                statement=f'The other software shall do {index}.', category='functional',
                rationale='Other authority.', actor='human')['requirement_id']
    before = logical_dump(ledger)
    with pytest.raises(MilestonePreEffectError) as rejected:
        ledger.promote_milestone('alpha', draft('invalid', [first], [prerequisite]), actor='engineer', request_id='rejected')
    assert rejected.value.reason == code
    assert logical_dump(ledger) == before
    corrected = ledger.promote_milestone('alpha', draft('corrected', [first]), actor='engineer', request_id='rejected')
    assert corrected['milestone_id'] == 'MILE-000001'


def test_replay_fingerprints_initial_evidence_and_actor_not_mutable_acceptance(tmp_path):
    ledger, requirements = setup(tmp_path)
    original = draft('original', requirements[:1], acceptance_evidence=('initial:reference',))
    milestone = ledger.promote_milestone('alpha', original, actor='engineer', request_id='same')
    ledger.accept_milestone('alpha', milestone['milestone_id'], acceptance_evidence=('human:later',), actor='human')
    before = logical_dump(ledger)
    replay = ledger.promote_milestone('alpha', original, actor='engineer', request_id='same')
    assert replay['status'] == 'accepted' and replay['acceptance_evidence'] == ['initial:reference', 'human:later']
    for changed, actor in ((replace(original, acceptance_evidence=('different:reference',)), 'engineer'),
                           (original, 'different-actor'), (replace(original, name='different'), 'engineer')):
        with pytest.raises(MilestonePreEffectError) as conflict:
            ledger.promote_milestone('alpha', changed, actor=actor, request_id='same')
        assert conflict.value.reason == 'milestone_request_conflict'
        assert logical_dump(ledger) == before


def test_legacy_replay_without_original_proof_is_inspectable_not_backfilled(tmp_path):
    ledger, requirements = setup(tmp_path)
    original = draft('legacy', requirements[:1])
    ledger.promote_milestone('alpha', original, actor='engineer', request_id='legacy')
    with sqlite3.connect(ledger.database_path) as connection:
        event_id, payload = connection.execute("SELECT event_id,payload_json FROM requirement_events WHERE event_type='milestone_promoted'").fetchone()
        payload = json.loads(payload)
        payload.pop('original_request_fingerprint')
        connection.execute('UPDATE requirement_events SET payload_json=? WHERE event_id=?', (json.dumps(payload), event_id))
    before = logical_dump(ledger)
    with pytest.raises(MilestonePreEffectError) as rejected:
        ledger.promote_milestone('alpha', original, actor='engineer', request_id='legacy')
    assert rejected.value.reason == 'milestone_request_replay_unverifiable'
    reopened = SQLiteRequirementLedger(ledger.database_path)
    assert reopened.milestones('alpha')[0]['name'] == 'legacy'
    assert logical_dump(reopened) == before


def test_concurrent_allocation_remains_monotonic_and_owner_validation_atomic(tmp_path):
    ledger, requirements = setup(tmp_path)
    def promote(index):
        return ledger.promote_milestone('alpha', draft(f'parallel-{index}', requirements[:1]), actor='engineer')
    with ThreadPoolExecutor(max_workers=2) as pool:
        milestones = list(pool.map(promote, range(2)))
    assert sorted(m['ordinal'] for m in milestones) == [1, 2]
    successor = ledger.promote_milestone('alpha', draft('after both', requirements[1:2], requirements[:1]), actor='engineer')
    assert successor['ordinal'] == 3
    assert successor['prerequisite_producers'][requirements[0]] == ['MILE-000001', 'MILE-000002']


def test_predecessor_requirements_are_context_not_current_progress_or_unit_tasks(tmp_path):
    from tests.test_external_milestone_progress import progress_fixture, read, submit
    ledger, external, projection, ids, revisions, _first, realized = progress_fixture(tmp_path)
    prior = ledger.add_requirement(ids[0], title='Prior behavior', statement='The dependency shall return a stable identifier.',
        category='functional', rationale='Earlier reusable behavior.', actor='human')['requirement_id']
    producer = ledger.promote_milestone(ids[0], draft('producer', [prior]), actor='engineer')
    consumer = ledger.promote_milestone(ids[0], draft('consumer', [realized], [prior]), actor='engineer')
    ledger.link_change_milestone(*ids[:2], consumer['milestone_id'], actor='engineer')
    submit(external, ids, revisions)
    submit(external, ids, revisions, 'consumer', 'consumer-1')
    result = read(projection, ids, consumer)
    assert result['scope_complete'] and result['implementation']['percent'] == 100
    assert result['active_criteria'] == 2
    assert result['milestones'][0]['prerequisite_producers'] == {prior: [producer['milestone_id']]}
    exported = external.call(*ids, 'export_plan', actor='engineer', request_id='offline-prerequisites', payload=revisions)
    assert 'The dependency shall return a stable identifier.' in exported['content']
    assert 'Prerequisite requirement ids' in exported['content']


def test_historical_gap_blocks_all_current_execution_and_acceptance_routes(tmp_path):
    from tests.test_external_milestone_progress import progress_fixture
    ledger, external, _projection, ids, revisions, milestone, realized = progress_fixture(tmp_path)
    extra = ledger.add_requirement(ids[0], title='Unowned prior scope', statement='The missing predecessor shall be investigated.',
        category='functional', rationale='Historical fixture only.', actor='human')['requirement_id']
    historical_extra(ledger, ids[0], milestone['milestone_id'], [realized], extra)
    service = LifecycleControlService(requirements=ledger, goals=ledger, grounding_audits=ledger,
        control=ledger, change_control=ledger, assurance=ledger)
    before = logical_dump(ledger)
    assert service.milestone_entry_policy_diagnostics(ids[0])[0]['code'] == 'milestone_prerequisite_owner_missing'
    executable_kinds = {'create_milestone_change', 'implement_packet', 'start_implementation_run',
                        'execute_run_step', 'close_packet_after_run', 'request_change_acceptance'}
    assert not any(action.kind.value in executable_kinds for action in service.what_next(ids[0]))
    assert any(b['reason'] == 'milestone_prerequisite_owner_missing'
               for b in service.milestone_closure_state(ids[0], milestone['milestone_id'])['blockers'])
    with pytest.raises(ChangeControlBlockedError):
        service.accept_milestone(ids[0], milestone['milestone_id'], acceptance_evidence=['human:claim'], actor='human')
    with pytest.raises(ChangeControlBlockedError):
        ledger.accept_milestone(ids[0], milestone['milestone_id'], acceptance_evidence=('human:claim',), actor='human')
    assert external.validation(*ids)['status'] == 'blocked'
    assert external.todo(*ids)['status'] == 'blocked'
    assert external.provider_validation(*ids)['status'] != 'closed'
    for allow_draft in (False, True):
        with pytest.raises(ChangeControlBlockedError, match='milestone_prerequisite_owner_missing'):
            external.call(*ids, 'export_plan', actor='engineer', request_id=f'invalid-export-{allow_draft}',
                          payload={**revisions, 'allow_draft': allow_draft})
    assert logical_dump(ledger) == before


def test_historical_gap_invalidates_guided_confirmation_without_history_rewrite(tmp_path):
    from tests.test_guided_bootstrap import prepared, confirm
    runtime, ids, _revisions, bootstrap, milestone, _answer, _mapping = prepared(tmp_path)
    try:
        confirm(runtime, ids, bootstrap, milestone)
        realized = runtime.ledger.milestones(ids[0])[0]['requirement_ids']
        extra = runtime.ledger.add_requirement(ids[0], title='Unowned historical prerequisite',
            statement='The missing prior behavior shall be identified.', category='functional', rationale='Fixture.', actor='human')['requirement_id']
        historical_extra(runtime.ledger, ids[0], milestone, realized, extra)
        before = logical_dump(runtime.ledger)
        roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap, milestone_ids=[milestone])
        assert not roadmap['confirmable'] and not roadmap['confirmed']
        assert any(gap['reason'] == 'milestone_prerequisite_owner_missing' for gap in roadmap['gaps'])
        with pytest.raises(BootstrapBlockedError):
            runtime.guided_bootstrap.complete(ids[0], bootstrap, completion_reference='invalid', actor='human', request_id='invalid-complete')
        assert logical_dump(runtime.ledger) == before
    finally:
        runtime.close()


@pytest.mark.parametrize('missing', [False, True])
def test_current_prerequisite_authority_blocks_execution_without_expanding_work(tmp_path, missing):
    from tests.test_external_milestone_progress import progress_fixture, read
    ledger, external, projection, ids, revisions, _first, realized = progress_fixture(tmp_path)
    prerequisite = ledger.add_requirement(ids[0], title='Reusable prior behavior',
        statement='The earlier component shall supply a stable dependency.', category='functional',
        rationale='Previous milestone authority.', actor='human')['requirement_id']
    producer = ledger.promote_milestone(ids[0], draft('prior producer', [prerequisite]), actor='engineer')
    consumer = ledger.promote_milestone(ids[0], draft('current consumer', [realized], [prerequisite]), actor='engineer')
    ledger.link_change_milestone(*ids[:2], consumer['milestone_id'], actor='engineer')
    assert external.validation(*ids)['execution_allowed']
    assert external.todo(*ids)['status'] == 'success'
    if missing:
        # Separate corrupt historical JSON fixture: the declared prior owner
        # exists, but its referenced requirement never existed in the ledger.
        missing_id = 'REQ-999999'
        with sqlite3.connect(ledger.database_path) as connection:
            connection.execute('UPDATE milestones SET requirement_ids_json=?,dependency_closure_ids_json=? WHERE milestone_id=?',
                (json.dumps([missing_id]), json.dumps([missing_id]), producer['milestone_id']))
        historical_extra(ledger, ids[0], consumer['milestone_id'], [realized], missing_id)
        code = 'milestone_prerequisite_requirement_missing'
    else:
        ledger.set_lifecycle_status(ids[0], prerequisite, status=LifecycleStatus.REMOVED, actor='human',
            reason='The prior behavior is retired by explicit fixture authority.', governance_reference='human:retirement')
        code = 'milestone_prerequisite_requirement_retired'
    before = logical_dump(ledger)
    milestone = next(m for m in ledger.milestones(ids[0]) if m['milestone_id'] == consumer['milestone_id'])
    assert milestone['prerequisite_mapping_gaps'] == []
    assert milestone['prerequisite_authority_gaps'][0]['code'] == code
    assert milestone['prerequisite_authority_gaps'][0]['provenance'] == 'canonical_ledger_current_state'
    validation = external.validation(*ids)
    assert validation['status'] == 'blocked' and not validation['execution_allowed']
    assert not validation['plan_executable']
    assert external.todo(*ids)['status'] == 'blocked'
    assert external.provider_validation(*ids)['status'] != 'closed'
    for allow_draft in (False, True):
        with pytest.raises(ChangeControlBlockedError, match=code):
            external.call(*ids, 'export_plan', actor='engineer', request_id=f'authority-{allow_draft}',
                          payload={**revisions, 'allow_draft': allow_draft})
    service = LifecycleControlService(requirements=ledger, goals=ledger, grounding_audits=ledger,
        control=ledger, change_control=ledger, assurance=ledger)
    assert any(item['code'] == code for item in service.milestone_entry_policy_diagnostics(ids[0]))
    assert any(gap['reason'] == code for gap in service.milestone_closure_state(ids[0], consumer['milestone_id'])['blockers'])
    with pytest.raises(ChangeControlBlockedError):
        service.accept_milestone(ids[0], consumer['milestone_id'], acceptance_evidence=['human:claim'], actor='human')
    assert not any(action.milestone_ids == (consumer['milestone_id'],) and action.kind.value == 'create_milestone_change'
                   for action in service.what_next(ids[0]))
    progress = read(projection, ids, consumer)
    assert not progress['scope_complete']
    assert progress['active_criteria'] == 2  # Prerequisites never become current criteria.
    assert logical_dump(ledger) == before


def test_retired_prerequisite_invalidates_guided_preparation_and_completion(tmp_path):
    from tests.test_guided_bootstrap import prepared, confirm
    runtime, ids, _revisions, bootstrap, _first, _answer, correspondence = prepared(tmp_path)
    try:
        ledger = runtime.ledger
        realized = ledger.change_state(*ids[:2])['requirement_ids'][0]
        prerequisite = ledger.add_requirement(ids[0], title='Earlier dependency',
            statement='The earlier component shall provide reusable identity.', category='functional',
            rationale='Declared predecessor fixture.', actor='human')['requirement_id']
        ledger.promote_milestone(ids[0], draft('previous identity', [prerequisite]), actor='engineer')
        consumer = ledger.promote_milestone(ids[0], draft('guided consumer', [realized], [prerequisite]), actor='engineer')
        ledger.link_change_milestone(*ids[:2], consumer['milestone_id'], actor='engineer')
        correspondence['canonical_references']['milestone_ids'] = [consumer['milestone_id']]
        correspondence['canonical_references']['requirement_ids'] = [realized, prerequisite]
        runtime.guided_bootstrap.record_correspondence(ids[0], bootstrap,
            correspondence=correspondence, actor='engineer', request_id='predecessor-correspondence')
        confirm(runtime, ids, bootstrap, consumer['milestone_id'])
        ledger.set_lifecycle_status(ids[0], prerequisite, status=LifecycleStatus.REMOVED, actor='human',
            reason='Explicit predecessor retirement fixture.', governance_reference='human:retirement')
        before = logical_dump(ledger)
        roadmap = runtime.guided_bootstrap.roadmap(ids[0], bootstrap, milestone_ids=[consumer['milestone_id']])
        assert not roadmap['confirmable'] and not roadmap['confirmed']
        assert any(gap['reason'] == 'milestone_prerequisite_requirement_retired' for gap in roadmap['gaps'])
        with pytest.raises(BootstrapBlockedError):
            runtime.guided_bootstrap.complete(ids[0], bootstrap, completion_reference='invalid', actor='human', request_id='retired-complete')
        assert logical_dump(ledger) == before
    finally:
        runtime.close()
