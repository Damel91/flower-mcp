"""Self-contained semantic authority must be prose, not a JSON transcript."""
from copy import deepcopy

from flow_of_work_mcp.application.external_plan_markdown import render_plan
from tests.test_external_work import fixture, governing_milestone
from tests.test_external_packet_dependencies import dependent_fixture


def test_export_preserves_full_semantic_context_and_physical_prose_lines(tmp_path):
    ledger, external, ids, _revs = fixture(tmp_path)
    governing_milestone(ledger, ids)
    snapshot = external._snapshot(*ids)
    snapshot['goals'] = [{'goal_node_id': 'GOAL-1', 'title': 'Offline consumer', 'node_type': 'sequence',
                          'payload': {'participants': ['Engineer', 'Flower'], 'normal_steps': ['Export accepted work.', 'Execute offline.'],
                                      'failure_steps': ['Retain stale report as history.'], 'expected_effects': ['No fabricated acceptance.']},
                          'source_anchor': {'path': 'authority.md', 'line_start': 8}}]
    snapshot['answers'] = [{'question_key': 'contract', 'prompt': 'What must remain?', 'status': 'answered',
                            'answer_summary': 'Stable IDs.\nPreserve authority.', 'answer_source': 'host_declared', 'evidence_refs': ['reference:8']}]
    snapshot['pressure_context'] = {'residual_risks': ['Host checks are declared.'], 'accepted_risk_refs': ['risk:known'], 'actor': 'engineer'}
    snapshot['resolved_authorities'] = {'oracle:1': {'oracle_id': '1', 'revision': 2, 'semantic_fields': {'forbidden_effects': ['No hidden side effects.']}}}
    projection = external._projection(snapshot)
    before = deepcopy(snapshot)
    content = render_plan(snapshot, projection, project_predecessor=external._projection)
    assert snapshot == before
    assert content == render_plan(snapshot, projection, project_predecessor=external._projection)
    for context in ['Entry policy', 'Exit policy', 'Requirement ids', 'Dependency closure ids',
                    'sequence', 'Participants', 'Export accepted work.', 'Execute offline.', 'Failure steps',
                    'authority.md', 'Stable IDs.\n', 'Preserve authority.', 'host_declared', 'risk:known',
                    'No hidden side effects.', 'Revision', 'reference:8']:
        assert context in content
    assert '```json' not in content and '"normal_steps"' not in content
    assert 'Unit-local checks' in content and 'deferred control-plane verification; not a current coding instruction' in content
    assert projection['authority_fingerprint'] in content
    assert content.index('- **Risk disposition:**') < content.index('#### Exit policy')
    assert 'None recorded.\nNone recorded.' not in content


def test_offline_outcome_contract_supplies_exact_transport_types_and_issued_authority(tmp_path):
    _ledger, external, ids, revs = fixture(tmp_path)
    exported = external.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='offline-contract')
    content = exported['content']
    for required in ['Exact offline outcome report contract', 'operation="report_outcome"',
                     'Criterion references are positive integer stable numbers',
                     'String: complete, blocked or failed.', 'String: pass, fail or not_run.',
                     'host_reported_test_execution', 'explicitly labelled artifact content identity',
                     'Supplemental checks belong in evidence artifacts']:
        assert required in content
    assert f"Positive integer {revs['expected_spec_revision']}; retain the issued value." in content
    assert f"String {exported['authority_fingerprint']}; retain the issued value." in content
    assert '```json' not in content


def test_dependent_export_embeds_full_predecessors_in_order_once(tmp_path):
    ledger, external, first_ids, _first_revs, ids, _revs = dependent_fixture(tmp_path)
    snapshot = external._snapshot(*ids)
    content = render_plan(snapshot, external._projection(snapshot), project_predecessor=external._projection)
    assert content.count('Predecessor packet ' + first_ids[2]) == 1
    assert content.index('Unit 1: producer') < content.index('Unit 2: consumer') < content.index('Unit 1: facade')
    assert 'reconcile predecessor unit reports before consumer reports' in content
    assert 'Canonical producer clause:' in content and '```json' not in content
    assert not any(line.startswith('#######') for line in content.splitlines())


def test_corrective_context_is_historical_without_false_materialization(tmp_path):
    ledger, external, ids, _revs = fixture(tmp_path)
    original = external._snapshot(*ids)
    snapshot = deepcopy(original)
    snapshot['packet_id'] = 'PACKET-CORRECTIVE'
    snapshot['remediation_context'] = {'predecessor_packet_id': ids[2], 'predecessor_dependency_policy': 'context_only',
                                       'finding_ids': ['FINDING-1'], 'required_regression_evidence': 'Reject unknown outcomes.'}
    snapshot['contextual_predecessor'] = original
    snapshot['engineer_gate'] = {'execution_allowed': True, 'relevant_findings': [{'finding_id': 'FINDING-1',
                                'latest_intent_assessment': {'classification': 'correction_within_intent'}, 'assessment_current': True}]}
    content = render_plan(snapshot, external._projection(snapshot), project_predecessor=external._projection)
    assert 'Historical context-only predecessor authority' in content
    assert 'unfinished original units are not prerequisites' in content
    assert 'not executable work in this handoff' in content and 'context_only' in content
    assert 'Reject unknown outcomes.' in content and 'correction_within_intent' in content
    assert 'Canonical predecessor packet boundary' not in content
    assert '"latest_intent_assessment"' not in content
