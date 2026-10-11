"""Ordinary packet pins, selected closure, provenance and scoped currentness."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from flow_of_work_mcp import ChangeControlService, GovernedChangeDraft, ImplementationPacketDraft
from flow_of_work_mcp.application.architecture import ArchitectureService
from flow_of_work_mcp.core.domain.architecture import normalize_architecture_refs
from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from tests.test_architecture_authority import adopt, definition, setup


def linked_fixture(tmp_path):
    ledger, architecture = setup(tmp_path)
    requirement = ledger.add_requirement('alpha', title='One lifecycle', statement='Flower shall own lifecycle authority.',
                                         category='functional', actor='stakeholder', rationale='Recover without chat history.')
    goal = ledger.create_goal_node('alpha', node_type='use_case', title='Continue engineering',
                                   payload={'objective': 'Recover the accepted engineering plan.'}, source_anchor=None, actor='stakeholder')
    evidence = ledger.record_verification('alpha', requirement['requirement_id'], kind='tested_deterministically', outcome='passed',
                                          reference='host:synthetic-test-log', actor='external-agent',
                                          metadata={'provenance': 'host-reported', 'excerpt': 'Prima riga\nSeconda riga è originale.'})
    changes = ChangeControlService(ledger)
    change = changes.create_change('alpha', GovernedChangeDraft(title='Use Flower lifecycle', rationale='Bounded increment.',
                                                               requirement_ids=(requirement['requirement_id'],)), actor='engineer')
    draft = ImplementationPacketDraft(title='Connect lifecycle', completion_criteria=('Lifecycle is preserved.',))
    packet = changes.add_packet('alpha', change['change_id'], draft, actor='engineer')['packets'][0]
    value = definition()
    value['decisions'][0]['links'] = [
        {'kind': 'requirement', 'requirement_id': requirement['requirement_id']},
        {'kind': 'goal', 'goal_node_id': goal['goal_node_id']},
        {'kind': 'packet', 'change_id': change['change_id'], 'packet_id': packet['packet_id']},
        {'kind': 'evidence', 'evidence_id': evidence['evidence_id']},
    ]
    receipt = adopt(architecture, value)
    refs = ({'revision': receipt['revision'], 'kind': 'decision', 'entity_id': 'Ownership'},)
    return ledger, architecture, changes, change['change_id'], packet, draft, value, refs


def test_ordinary_packet_refine_revise_history_omission_and_explicit_clear(tmp_path):
    ledger, _, changes, change_id, packet, draft, _, refs = linked_fixture(tmp_path)
    updated = changes.refine_packet('alpha', change_id, packet['packet_id'], architecture_refs=refs, actor='engineer')['packets'][0]
    assert updated['architecture_refs'] == list(refs)
    assert updated['spec_revision'] == packet['spec_revision'] + 1
    retained = changes.refine_packet('alpha', change_id, packet['packet_id'], objective='Connect under recorded design.', actor='engineer')['packets'][0]
    assert retained['architecture_refs'] == list(refs)
    direct = changes.revise_packet('alpha', change_id, packet['packet_id'], replace(draft, objective='Direct ordinary revision.'), actor='engineer')['packets'][0]
    assert direct['architecture_refs'] == list(refs)
    cleared = changes.refine_packet('alpha', change_id, packet['packet_id'], architecture_refs=(), actor='engineer')['packets'][0]
    assert 'architecture_refs' not in cleared
    with ledger._read_connection() as connection:
        history = connection.execute('SELECT architecture_refs_json FROM implementation_packet_revisions WHERE project_id=? AND packet_id=? ORDER BY revision',
                                     ('alpha', packet['packet_id'])).fetchall()
    assert json.loads(history[0]['architecture_refs_json']) == []
    assert json.loads(history[1]['architecture_refs_json']) == list(refs)
    assert json.loads(history[-1]['architecture_refs_json']) == []


def test_selected_forward_closure_and_exact_original_evidence(tmp_path):
    ledger, _, _, _, _, _, _, refs = linked_fixture(tmp_path)
    context = ledger.resolve_architecture_refs('alpha', refs)
    assert context['applicability']['status'] == 'current'
    assert {c['id'] for c in context['selected_context']['definition']['components']} == {'Pi', 'Flower'}
    linked = {entry['link']['kind']: entry['content'] for entry in context['selected_context']['canonical_links']}
    assert linked['requirement']['rationale'] == 'Recover without chat history.'
    assert linked['goal']['payload']['objective'] == 'Recover the accepted engineering plan.'
    assert linked['packet']['completion_criteria'] == ['Lifecycle is preserved.']
    assert 'plan' not in linked['packet'] and 'target_binding_ids' not in linked['packet']
    assert linked['evidence']['actor'] == 'external-agent'
    assert linked['evidence']['metadata'] == {'provenance': 'host-reported', 'excerpt': 'Prima riga\nSeconda riga è originale.'}
    component_only = ledger.resolve_architecture_refs('alpha', [{'revision': refs[0]['revision'], 'kind': 'component', 'entity_id': 'Pi'}])
    assert component_only['selected_context']['definition']['decisions'] == []
    assert component_only['selected_context']['definition']['interfaces'] == []
    assert ledger.resolve_architecture_refs('alpha', []) is None


def test_packet_add_pins_and_proposed_refs_fail_without_allocating_packet_identity(tmp_path):
    ledger, architecture, changes, change_id, _, draft, value, refs = linked_fixture(tmp_path)
    added = changes.add_packet('alpha', change_id, replace(draft, architecture_refs=refs), actor='engineer', request_id='pinned-add')['packets'][-1]
    assert added['architecture_refs'] == list(refs)
    replay = changes.add_packet('alpha', change_id, replace(draft, architecture_refs=refs), actor='engineer', request_id='pinned-add')['packets'][-1]
    assert replay['packet_id'] == added['packet_id']
    proposed = architecture.call('alpha', 'propose', actor='engineer', request_id='new-proposal',
                                 payload={'expected_revision': refs[0]['revision'], 'definition': value})
    before = ledger.change_state('alpha', change_id)
    with pytest.raises(ChangeControlBlockedError, match='not_adopted'):
        changes.add_packet('alpha', change_id, replace(draft, architecture_refs=({**refs[0], 'revision': proposed['revision']},)), actor='engineer')
    assert ledger.change_state('alpha', change_id) == before


def test_linked_current_intent_changes_fingerprint_without_reclassifying_host_evidence(tmp_path):
    ledger, _, _, _, _, _, _, refs = linked_fixture(tmp_path)
    before = ledger.resolve_architecture_refs('alpha', refs)
    requirement = next(item['content'] for item in before['selected_context']['canonical_links'] if item['link']['kind'] == 'requirement')
    ledger.revise_requirement('alpha', requirement['requirement_id'], title=requirement['title'],
                              statement='Flower shall own lifecycle and preserve explicit authority.', category='functional',
                              rationale='Clarified original behavior.', actor='stakeholder')
    after = ledger.resolve_architecture_refs('alpha', refs)
    assert before['applicability'] == after['applicability']
    assert fingerprint(before) != fingerprint(after)
    evidence_before = next(item for item in before['selected_context']['canonical_links'] if item['link']['kind'] == 'evidence')
    evidence_after = next(item for item in after['selected_context']['canonical_links'] if item['link']['kind'] == 'evidence')
    assert evidence_after == evidence_before


def test_unrelated_adoption_proposals_versus_relevant_change_and_supersession(tmp_path):
    ledger, architecture, _, _, _, _, original, refs = linked_fixture(tmp_path)
    first_context = ledger.resolve_architecture_refs('alpha', refs)
    unrelated = deepcopy(original)
    unrelated['components'][2]['responsibility'] = 'Render the project UI and keep correlations.'
    second = adopt(architecture, unrelated, expected=refs[0]['revision'], key='unrelated')
    assert ledger.resolve_architecture_refs('alpha', refs) == first_context
    proposed = deepcopy(unrelated)
    proposed['components'][0]['responsibility'] = 'Changed but not yet adopted.'
    architecture.call('alpha', 'propose', actor='engineer', request_id='proposal-only',
                      payload={'expected_revision': second['revision'], 'definition': proposed})
    assert ledger.resolve_architecture_refs('alpha', refs) == first_context
    third = adopt(architecture, proposed, expected=second['revision'], key='relevant')
    stale = ledger.resolve_architecture_refs('alpha', refs)
    assert stale['gaps'][0]['code'] == 'architecture_authority_stale'
    assert stale['applicability']['changed_entities'] == [{'kind': 'component', 'entity_id': 'Pi'}]
    assert fingerprint(stale) != fingerprint(first_context)
    revised_refs = [{**refs[0], 'revision': third['revision']}]
    superseding = deepcopy(proposed)
    superseding['decisions'].append({**superseding['decisions'][0], 'id': 'Ownership2',
                                     'statement': 'Explicit technical refinement.', 'supersedes_decision_id': 'Ownership'})
    fourth = adopt(architecture, superseding, expected=third['revision'], key='superseding')
    assert ledger.resolve_architecture_refs('alpha', revised_refs)['applicability']['superseded_decision_ids'] == ['Ownership']
    new = ledger.resolve_architecture_refs('alpha', [{'revision': fourth['revision'], 'kind': 'decision', 'entity_id': 'Ownership2'}])
    assert [d['id'] for d in new['selected_context']['definition']['decisions']] == ['Ownership', 'Ownership2']
    assert new['applicability']['status'] == 'current'


def test_same_project_links_are_revalidated_at_adoption_and_packet_refs_are_strict(tmp_path):
    ledger, architecture, changes, change_id, packet, _, value, refs = linked_fixture(tmp_path)
    foreign = ledger.create_goal_node('beta', node_type='use_case', title='Foreign goal', payload={}, source_anchor=None, actor='engineer')
    missing = deepcopy(value)
    missing['components'][2]['links'] = [{'kind': 'goal', 'goal_node_id': foreign['goal_node_id'] + '-foreign'}]
    with pytest.raises(ChangeControlBlockedError, match='link_not_found'):
        architecture.call('alpha', 'propose', actor='engineer', request_id='foreign-link',
                          payload={'expected_revision': refs[0]['revision'], 'definition': missing})
    with pytest.raises(ChangeControlBlockedError, match='not_found'):
        ledger.validate_architecture_refs('beta', refs)
    for invalid in [[{**refs[0], 'entity_id': 'Missing'}], [{**refs[0], 'revision': 999}]]:
        with pytest.raises((ChangeControlBlockedError, ValueError)):
            changes.refine_packet('alpha', change_id, packet['packet_id'], architecture_refs=tuple(invalid), actor='engineer')
    with pytest.raises(ValueError, match='one adopted revision'):
        normalize_architecture_refs([refs[0], {**refs[0], 'revision': 2, 'entity_id': 'Other'}])
    with pytest.raises(ValueError, match='unique'):
        normalize_architecture_refs([refs[0], refs[0]])
    fresh_goal = ledger.create_goal_node('alpha', node_type='use_case', title='Temporary goal', payload={}, source_anchor=None, actor='engineer')
    proposed = deepcopy(value)
    proposed['components'][2]['links'] = [{'kind': 'goal', 'goal_node_id': fresh_goal['goal_node_id']}]
    proposal = architecture.call('alpha', 'propose', actor='engineer', request_id='before-link-loss',
                                 payload={'expected_revision': refs[0]['revision'], 'definition': proposed})
    with ledger._transaction() as connection:
        connection.execute('DELETE FROM goal_nodes WHERE project_id=? AND goal_node_id=?', ('alpha', fresh_goal['goal_node_id']))
    before = ledger.ledger_version('alpha')
    with pytest.raises(ChangeControlBlockedError, match='link_not_found'):
        architecture.call('alpha', 'adopt', actor='engineer', request_id='after-link-loss',
                          payload={'expected_revision': refs[0]['revision'], 'revision': proposal['revision'], 'rationale': 'Must revalidate links.'})
    assert ledger.ledger_version('alpha') == before
    assert ledger.architecture_revision('alpha', proposal['revision'])['state'] == 'proposed'


def test_all_canonical_link_kinds_validate_actual_project_ownership(tmp_path):
    ledger, architecture, _, _, _, _, value, refs = linked_fixture(tmp_path)
    foreign_requirements = [ledger.add_requirement('beta', title=f'Foreign {i}', statement=f'Foreign project shall own behavior {i}.',
                                                   category='functional', actor='engineer') for i in range(2)]
    foreign_goals = [ledger.create_goal_node('beta', node_type='use_case', title=f'Foreign goal {i}', payload={}, source_anchor=None, actor='engineer') for i in range(2)]
    beta_changes = ChangeControlService(ledger)
    change = beta_changes.create_change('beta', GovernedChangeDraft(title='Foreign change', rationale='Separate project.',
                                                                   requirement_ids=(foreign_requirements[0]['requirement_id'],)), actor='engineer')
    for i in range(2):
        beta_changes.add_packet('beta', change['change_id'], ImplementationPacketDraft(title=f'Foreign packet {i}', completion_criteria=('Foreign complete.',)), actor='engineer')
    evidence = ledger.record_verification('beta', foreign_requirements[0]['requirement_id'], kind='tested_live', outcome='passed',
                                          reference='host:foreign-log', metadata={'provenance': 'host-reported'}, actor='external-agent')
    foreign_links = [
        {'kind': 'requirement', 'requirement_id': foreign_requirements[1]['requirement_id']},
        {'kind': 'goal', 'goal_node_id': foreign_goals[1]['goal_node_id']},
        {'kind': 'packet', 'change_id': change['change_id'], 'packet_id': 'PACKET-000002'},
        {'kind': 'evidence', 'evidence_id': evidence['evidence_id']},
    ]
    for link in foreign_links:
        invalid = deepcopy(value)
        invalid['components'][2]['links'] = [link]
        before = ledger.ledger_version('alpha')
        with pytest.raises(ChangeControlBlockedError, match='link_not_found'):
            architecture.call('alpha', 'propose', actor='engineer', request_id='foreign-' + link['kind'],
                              payload={'expected_revision': refs[0]['revision'], 'definition': invalid})
        assert ledger.ledger_version('alpha') == before
