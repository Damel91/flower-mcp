"""Criterion accounting, semantic invalidation and standalone authority gates."""
import pytest

from flow_of_work_mcp import (
    ChangeControlService, LifecycleStatus, MilestoneDraft, PacketStatus, PacketTransition, PacketWorkPlanDraft,
    RequirementDraft, RequirementService, VerificationDraft, VerificationKind, VerificationOutcome,
)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.milestone_traceability import MilestoneTraceabilityProjectionService
from flow_of_work_mcp.application.packet_work_plan import _unit_from_payload
from tests.test_external_work import fixture, report


def progress_fixture(tmp_path, *, evidence=()):
    ledger, external, ids, revs = fixture(tmp_path)
    requirement_id = ledger.change_state(ids[0], ids[1])['requirement_ids'][0]
    milestone = ledger.promote_milestone(ids[0], MilestoneDraft(
        name='Offline milestone', requirement_ids=(requirement_id,), prerequisite_requirement_ids=(),
        entry_policy={'scope': 'declared'}, exit_policy={'acceptance': 'human'}, risk_disposition='bounded',
        acceptance_evidence=evidence), actor='human')
    ChangeControlService(ledger).link_change_milestone(*ids[:2], milestone['milestone_id'], actor='human')
    projection = MilestoneTraceabilityProjectionService(requirements=ledger, lifecycle=ledger, changes=ledger,
        navigation=ledger, assurance=ledger, execution_runs=ledger, ledger_versions=ledger, grounding_audits=ledger,
        external_work=external)
    return ledger, external, projection, ids, revs, milestone, requirement_id


def submit(external, ids, revs, unit='producer', key='producer-1', **patch):
    payload = {**report(external, ids, revs, unit, report_key=key), **patch}
    return external.call(*ids, 'report_outcome', actor='agent', request_id='request-' + key, payload=payload)


def read(projection, ids, milestone):
    return projection.progress(ids[0], milestone_ids=(milestone['milestone_id'],))


def accept_units(ledger, ids, units):
    previous = ledger.packet_work_plan_state(*ids)
    packet = ledger.change_state(*ids[:2])['packets'][0]
    proposed = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'],
        tuple(_unit_from_payload(unit) for unit in units)), actor='human', expected_current_plan_revision=previous['plan_revision'])
    ledger.transition_packet_work_plan(ids[0], proposed['work_plan_id'], proposed['plan_revision'], status='accepted',
        expected_packet_revision=proposed['packet_revision'], expected_current_plan_revision=proposed['plan_revision'],
        rationale='The revised exact declarations are accepted.', actor='human')
    return {'expected_spec_revision': proposed['packet_revision'], 'expected_plan_revision': proposed['plan_revision']}


def test_progress_counts_unique_active_criteria_and_preserves_acceptance_boundaries(tmp_path):
    ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    before = read(projection, ids, milestone)
    assert before['active_criteria'] == 2
    assert before['implementation']['percent'] == 0
    assert before['local_verification']['percent'] == 0
    submit(external, ids, revs)
    middle = read(projection, ids, milestone)
    assert middle['scope_revision'] == before['scope_revision']
    assert middle['progress_revision'] != before['progress_revision']
    assert middle['progress_revision'] == read(projection, ids, milestone)['progress_revision']
    assert middle['implementation']['percent'] == 50
    assert middle['local_verification']['percent'] == 50
    submit(external, ids, revs, 'consumer', 'consumer-1')
    version = ledger.ledger_version(ids[0])
    after = read(projection, ids, milestone)
    assert ledger.ledger_version(ids[0]) == version
    assert after['implementation']['percent'] == after['local_verification']['percent'] == 100
    assert after['implementation']['provenance'] == 'host_reported'
    assert after['implementation_complete'] and after['local_verification_complete']
    assert after['fully_completed'] is False
    assert after['deferred_obligations'][0]['state'] == 'verification_pending'
    assert after['milestones'][0]['acceptance']['state'] == 'missing'
    assert after['criteria'][0]['current_evidence'][0]['report_key'] == 'producer-1'
    assert after['criteria'][0]['number'] == 1


@pytest.mark.parametrize('selected', [(), ('MILE-000001', 'MILE-000001'), ('MILE-999999',), (' ',), (' MILE-000001',), ('MILE-000001',) * 129, 'MILE-000001'])
def test_explicit_milestone_scope_rejects_ambiguous_or_invalid_selection(tmp_path, selected):
    _ledger, _external, projection, ids, _revs, _milestone, _req = progress_fixture(tmp_path)
    with pytest.raises(ValueError):
        projection.progress(ids[0], milestone_ids=selected)


def test_missing_selected_scope_never_infers_hundred_percent(tmp_path):
    ledger, external, projection, ids, revs, milestone, req = progress_fixture(tmp_path)
    submit(external, ids, revs)
    submit(external, ids, revs, 'consumer', 'consumer-1')
    other = ledger.promote_milestone(ids[0], MilestoneDraft(name='Unplanned', requirement_ids=(req,),
        prerequisite_requirement_ids=(), entry_policy={}, exit_policy={}, risk_disposition='unknown'), actor='human')
    selected = (other['milestone_id'], milestone['milestone_id'])
    result = projection.progress(ids[0], milestone_ids=selected)
    assert result['milestone_ids'] == sorted(selected)
    assert result['scope_complete'] is False
    assert result['implementation']['completed'] == 2
    assert result['implementation']['percent'] is None
    assert result['local_verification']['percent'] is None
    assert result['fully_completed'] is False
    assert any(g['code'] == 'milestone_criterion_scope_unplanned' for g in result['gaps'])
    empty = projection.progress(ids[0], milestone_ids=(other['milestone_id'],))
    assert empty['active_criteria'] == 0 and empty['implementation']['percent'] is None


def test_passing_local_evidence_in_blocked_report_does_not_complete_implementation(tmp_path):
    _ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    submit(external, ids, revs, outcome='blocked', unresolved=['Output contract awaits implementation'])
    result = read(projection, ids, milestone)
    assert result['implementation']['completed'] == 0
    assert result['local_verification']['completed'] == 1
    assert result['criteria'][0]['current_evidence'][0]['report_outcome'] == 'blocked'
    assert result['criteria'][0]['local_verification_state'] == 'passed'
    assert result['criteria'][0]['implementation_state'] == 'pending'


def test_conflicts_and_predecessor_replacement_do_not_count_as_current_progress(tmp_path):
    _ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    submit(external, ids, revs)
    submit(external, ids, revs, 'consumer', 'consumer-1')
    submit(external, ids, revs, key='producer-2', source_revision='new-source')
    conflict = read(projection, ids, milestone)
    assert conflict['implementation']['completed'] == conflict['local_verification']['completed'] == 0
    external.call(*ids, 'reconcile_outcome', actor='human', request_id='choose-producer-2',
        payload={'report_key': 'producer-2', **revs, 'rationale': 'The new producer revision supersedes old host evidence.'})
    replaced = read(projection, ids, milestone)
    assert replaced['implementation']['completed'] == replaced['local_verification']['completed'] == 1
    assert replaced['criteria'][1]['current_evidence'] == []


def test_evidence_and_requirement_status_noise_preserve_report_and_scope_currentness(tmp_path):
    ledger, external, projection, ids, revs, milestone, req = progress_fixture(tmp_path)
    submit(external, ids, revs)
    before = read(projection, ids, milestone)
    authority = external.todo(*ids)['authority_fingerprint']
    requirements = RequirementService(ledger)
    requirements.record_verification(ids[0], req, VerificationDraft(kind=VerificationKind.DETERMINISTIC,
        outcome=VerificationOutcome.PASSED, reference='human-recorded:test'), actor='human')
    requirements.set_lifecycle(ids[0], req, LifecycleStatus.IMPLEMENTED, actor='human', reason='Recorded actual lifecycle state.')
    after = read(projection, ids, milestone)
    assert before['scope_revision'] == after['scope_revision']
    assert external.todo(*ids)['authority_fingerprint'] == authority
    assert after['implementation']['completed'] == 1
    assert external.todo(*ids)['current_unit']['unit_key'] == 'consumer'


@pytest.mark.parametrize('retire', [False, True])
def test_requirement_revision_or_retirement_invalidates_current_claims(tmp_path, retire):
    ledger, external, projection, ids, revs, milestone, req = progress_fixture(tmp_path)
    submit(external, ids, revs)
    before = read(projection, ids, milestone)
    requirements = RequirementService(ledger)
    if retire:
        requirements.set_lifecycle(ids[0], req, LifecycleStatus.REMOVED, actor='human', reason='Scope removed.',
            governed_approval_reference='human:scope-removal')
    else:
        requirements.revise(ids[0], req, RequirementDraft(title='Revised contract', statement='The implementation shall bound inputs.',
            category='functional', rationale='Explicit scope change'), actor='human', rationale='Approved semantic revision.')
    after = read(projection, ids, milestone)
    assert before['scope_revision'] != after['scope_revision']
    assert after['implementation']['completed'] == after['local_verification']['completed'] == 0
    if retire:
        assert after['scope_complete'] is False
        assert after['implementation']['percent'] is None
        assert external.todo(*ids)['reason'] == 'requirement_retired'
    else:
        assert external.todo(*ids)['current_unit']['unit_key'] == 'producer'


def test_planned_milestone_with_evidence_is_pending_acceptance(tmp_path):
    ledger, _external, projection, ids, _revs, milestone, _req = progress_fixture(tmp_path, evidence=('stakeholder-note',))
    result = read(projection, ids, milestone)
    assert result['milestones'][0]['status'] == 'planned'
    assert result['milestones'][0]['acceptance'] == {'state': 'pending', 'evidence': ['stakeholder-note']}
    traceability = projection.projection(ids[0], milestone_id=milestone['milestone_id'])
    assert traceability['rows'][0]['milestone_acceptance']['state'] == 'pending'
    assert 'milestone_not_accepted' in traceability['rows'][0]['acceptance_blockers']
    ledger.accept_milestone(ids[0], milestone['milestone_id'], acceptance_evidence=('actual-human-decision',), actor='human')
    accepted = read(projection, ids, milestone)
    assert accepted['milestones'][0]['acceptance']['state'] == 'accepted'
    assert accepted['scope_revision'] == result['scope_revision']
    assert accepted['progress_revision'] != result['progress_revision']
    assert accepted['fully_completed'] is False


def test_external_milestone_readiness_bypasses_only_provider_prerequisites(tmp_path):
    _ledger, external, projection, ids, _revs, milestone, _req = progress_fixture(tmp_path)
    # Provider readiness is unresolved in this fixture. Exact external PVP is closed.
    assert external.validation(*ids)['validation']['status'] == 'closed'
    row = projection.projection(ids[0], milestone_id=milestone['milestone_id'])['rows'][0]
    assert 'packet_not_execution_ready' not in row['acceptance_blockers']
    assert 'navigation_audit_unresolved' not in row['acceptance_blockers']
    assert row['readiness_projection']['execution_ready_packet_ids'] == [ids[2]]
    assert {'campaign_missing', 'acceptance_evidence_missing'}.issubset(row['acceptance_blockers'])


@pytest.mark.parametrize('status', [PacketStatus.IMPLEMENTED, PacketStatus.IDLE, PacketStatus.CANCELLED])
def test_inactive_packet_blocks_new_execution_preserves_replay_and_criterion_inspection(tmp_path, status):
    ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    data = report(external, ids, revs)
    receipt = external.call(*ids, 'report_outcome', actor='agent', request_id='before-inactive', payload=data)
    ledger.transition_packet(*ids, PacketTransition(status=status, disposition='Bounded test disposition'), actor='human')
    assert external.todo(*ids)['reason'] == 'external_packet_inactive'
    assert external.validation(*ids)['execution_allowed'] is False
    assert external.call(*ids, 'report_outcome', actor='agent', request_id='before-inactive', payload=data) == receipt
    assert external.call(*ids, 'report_outcome', actor='agent', request_id='same-record-other-request', payload=data)['replayed']
    with pytest.raises(Exception, match='external_packet_inactive'):
        external.call(*ids, 'report_outcome', actor='agent', request_id='inactive-new', payload={**data, 'report_key': 'new-record'})
    with pytest.raises(Exception, match='external_packet_inactive'):
        external.call(*ids, 'export_plan', actor='agent', request_id='inactive-export', payload=revs)
    draft = external.call(*ids, 'export_plan', actor='agent', request_id='inactive-draft', payload={**revs, 'allow_draft': True})
    assert draft['draft'] and 'external_packet_inactive' in draft['content']
    progress = read(projection, ids, milestone)
    if status == PacketStatus.CANCELLED:
        assert progress['active_criteria'] == 0 and progress['scope_complete'] is False
    else:
        assert progress['implementation']['completed'] == 1


def test_guided_execution_callback_is_packet_specific_and_replay_precedes_admission(tmp_path):
    ledger, original, ids, revs = fixture(tmp_path)
    data = report(original, ids, revs)
    receipt = original.call(*ids, 'report_outcome', actor='agent', request_id='original-report', payload=data)
    calls = []
    from flow_of_work_mcp.core.errors import ChangeControlBlockedError
    def guard(project, packet):
        calls.append((project, packet))
        raise ChangeControlBlockedError('guided_authority_missing', details={'expected': 'current human confirmation'})
    external = ExternalWorkService(ledger, execution_guard=guard)
    assert external.call(*ids, 'report_outcome', actor='agent', request_id='original-report', payload=data) == receipt
    assert external.call(*ids, 'report_outcome', actor='agent', request_id='original-new-request', payload=data)['replayed']
    assert not calls
    assert external.todo(*ids)['reason'] == 'guided_authority_missing'
    with pytest.raises(ChangeControlBlockedError, match='guided_authority_missing'):
        external.call(*ids, 'report_outcome', actor='agent', request_id='guided-new', payload={**data, 'report_key': 'new-report'})
    with pytest.raises(ChangeControlBlockedError, match='guided_authority_missing'):
        external.call(*ids, 'export_plan', actor='agent', request_id='guided-executable', payload=revs)
    assert calls and all(call == (ids[0], ids[2]) for call in calls)
    assert external.validation(*ids)['validation']['status'] == 'closed'
    assert external.criterion_progress(*ids)['criteria'][0]['implementation_state'] == 'complete'
    draft = external.call(*ids, 'export_plan', actor='agent', request_id='guided-draft', payload={**revs, 'allow_draft': True})
    assert draft['draft'] and 'guided_authority_missing' in draft['content']


def test_parent_requirement_fallback_export_is_self_contained_and_explicit_subset_is_preserved(tmp_path):
    ledger, external, ids, revs = fixture(tmp_path)
    parent_requirement = ledger.change_state(*ids[:2])['requirement_ids'][0]
    ChangeControlService(ledger).refine_packet(*ids, requirement_ids=(), actor='human')
    current = accept_units(ledger, ids, ledger.packet_work_plan_state(*ids)['units'])
    snapshot = external._snapshot(*ids)
    assert [r['requirement_id'] for r in snapshot['requirements']] == [parent_requirement]
    assert snapshot['change']['title'] == 'Offline task'
    artifact = external.call(*ids, 'export_plan', actor='agent', request_id='inherited-export', payload=current)
    assert 'A producer shall expose increment and a consumer shall use it.' in artifact['content']
    assert 'Bounded standalone trial' in artifact['content']
    assert 'The offline task must preserve a declared protocol.' in artifact['content']
    other = RequirementService(ledger).register(ids[0], RequirementDraft(title='Explicit subset',
        statement='The agent shall follow only this selected requirement.', category='functional'), actor='human')
    ChangeControlService(ledger).refine_packet(*ids, requirement_ids=(other['requirement_id'],), actor='human')
    selected = external._snapshot(*ids)
    assert [r['requirement_id'] for r in selected['requirements']] == [other['requirement_id']]
    assert selected['authority_basis']['requirements'][0]['requirement_id'] != parent_requirement


def test_parent_semantic_context_invalidates_authority_but_current_change_status_does_not(tmp_path, monkeypatch):
    ledger, external, ids, _revs = fixture(tmp_path)
    before = external.validation(*ids)['validation']['authority_fingerprint']
    original = ledger.change_state
    def with_change(**overrides):
        def read_state(project, change):
            return {**original(project, change), **overrides}
        monkeypatch.setattr(ledger, 'change_state', read_state)
    with_change(status='implemented', current_revision=999)
    assert external.validation(*ids)['validation']['authority_fingerprint'] == before
    with_change(rationale='Changed governing intent')
    assert external.validation(*ids)['validation']['authority_fingerprint'] != before
    with_change(source_refs=['source:accepted-new-intent'])
    assert external.validation(*ids)['validation']['authority_fingerprint'] != before


def test_multiple_implementation_owners_and_exact_local_intents_all_must_close(tmp_path):
    ledger, external, projection, ids, _revs, milestone, _req = progress_fixture(tmp_path)
    units = ledger.packet_work_plan_state(*ids)['units']
    units[1]['implements'] = [1, 2]
    units[1]['verifies'].append({'criterion': 1, 'kind': 'unit_check', 'statement': 'next_value(4) == 5'})
    revs = accept_units(ledger, ids, units)
    submit(external, ids, revs)
    partial = read(projection, ids, milestone)
    assert partial['criteria'][0]['implementation_units'] == ['producer', 'consumer']
    assert partial['criteria'][0]['implementation_state'] == 'pending'
    assert partial['criteria'][0]['local_verification_state'] == 'pending'
    submit(external, ids, revs, 'consumer', 'consumer-1')
    closed = read(projection, ids, milestone)
    assert closed['criteria'][0]['implementation_state'] == 'complete'
    assert closed['criteria'][0]['local_verification_state'] == 'passed'


def test_verification_only_criterion_is_not_applicable_to_implementation(tmp_path):
    ledger, external, projection, ids, _revs, milestone, _req = progress_fixture(tmp_path)
    units = ledger.packet_work_plan_state(*ids)['units']
    for unit in units:
        unit['implements'] = []
        unit['verifies'] = [intent for intent in unit['verifies'] if intent['kind'] == 'unit_check']
    revs = accept_units(ledger, ids, units)
    submit(external, ids, revs)
    submit(external, ids, revs, 'consumer', 'consumer-1')
    result = read(projection, ids, milestone)
    assert result['implementation']['total'] == 0
    assert result['implementation']['percent'] is None
    assert result['implementation']['not_applicable'] == 2
    assert result['local_verification']['percent'] == 100
    assert result['fully_completed'] is False
    ledger.accept_milestone(ids[0], milestone['milestone_id'], acceptance_evidence=('human:actual-acceptance',), actor='human')
    assert read(projection, ids, milestone)['fully_completed'] is True


def test_superseded_scope_excludes_history_and_replacement_is_unplanned(tmp_path):
    ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    submit(external, ids, revs)
    from flow_of_work_mcp import ImplementationPacketDraft
    successor = ChangeControlService(ledger).add_packet(ids[0], ids[1], ImplementationPacketDraft(title='Successor',
        objective='Replace obsolete scope', rationale='Explicit new plan required', completion_criteria=('replacement verified',)), actor='human')['packets'][-1]
    ChangeControlService(ledger).transition_packet(*ids, PacketTransition(status=PacketStatus.SUPERSEDED,
        successor_packet_id=successor['packet_id']), actor='human')
    assert external.todo(*ids)['reason'] == 'external_packet_inactive'
    result = read(projection, ids, milestone)
    assert result['scope_complete'] is False
    assert result['active_criteria'] == 0
    assert result['implementation']['percent'] is None
    assert any(g['code'] == 'packet_validation_upgrade_required' for g in result['gaps'])


def test_rounded_percentage_cannot_display_full_completion_for_unsatisfied_scope():
    from flow_of_work_mcp.application.milestone_traceability import _progress_counter
    rows = [{'implementation_state': 'complete'}] * 99999 + [{'implementation_state': 'pending'}]
    count = _progress_counter(rows, 'implementation_state', 'complete', True)
    assert count['completed'] < count['total']
    assert count['percent'] < 100


def test_host_deferred_pass_remains_pending_after_canonical_milestone_acceptance(tmp_path):
    ledger, external, projection, ids, revs, milestone, _req = progress_fixture(tmp_path)
    data = report(external, ids, revs)
    data['verification'].append({'criterion': 1, 'kind': 'live_campaign',
        'statement': 'Run the installed CLI with representative integers.', 'status': 'pass',
        'evidence_ref': 'host:unattested-cli-log', 'provenance': 'host_reported_execution'})
    external.call(*ids, 'report_outcome', actor='agent', request_id='host-deferred-pass', payload=data)
    submit(external, ids, revs, 'consumer', 'consumer-1')
    ledger.accept_milestone(ids[0], milestone['milestone_id'], acceptance_evidence=('human:acceptance',), actor='human')
    result = read(projection, ids, milestone)
    obligation = result['deferred_obligations'][0]
    assert obligation['host_result']['status'] == 'pass'
    assert obligation['host_result']['provenance'] == 'host_reported_execution'
    assert obligation['attestation'] == 'not_inferred' and obligation['state'] == 'verification_pending'
    assert result['fully_completed'] is False


def test_historical_unassigned_milestone_prerequisite_blocks_work(tmp_path):
    ledger, external, projection, ids, revs, _milestone, req = progress_fixture(tmp_path)
    dependency = RequirementService(ledger).register(ids[0], RequirementDraft(title='Dependency',
        statement='An additional prerequisite shall be planned.', category='functional'), actor='human')
    milestone = ledger.promote_milestone(ids[0], MilestoneDraft(name='Extended dependency scope', requirement_ids=(req,),
        prerequisite_requirement_ids=(), entry_policy={}, exit_policy={}, risk_disposition='bounded'), actor='human')
    ChangeControlService(ledger).link_change_milestone(*ids[:2], milestone['milestone_id'], actor='human')
    submit(external, ids, revs)
    submit(external, ids, revs, 'consumer', 'consumer-1')
    import json
    import sqlite3
    with sqlite3.connect(ledger.database_path) as connection:
        # An original schema55 inclusive closure could name an unowned extra.
        # Seed that historical defect only; no new API accepts this plan.
        connection.execute('UPDATE milestones SET dependency_closure_ids_json=? WHERE project_id=? AND milestone_id=?',
            (json.dumps([req, dependency['requirement_id']]), ids[0], milestone['milestone_id']))
    result = read(projection, ids, milestone)
    assert result['implementation']['completed'] == 0
    assert result['scope_complete'] is False and result['implementation']['percent'] is None
    assert any(gap['code'] == 'milestone_prerequisite_owner_missing' and gap['requirement_id'] == dependency['requirement_id']
               for gap in result['milestones'][0]['gaps'])
    assert external.todo(*ids)['status'] == 'blocked'
