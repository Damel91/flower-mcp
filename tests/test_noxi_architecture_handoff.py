"""Selected architecture survives offline artifacts and honest currentness checks."""
from copy import deepcopy
import json
import sqlite3

import pytest

from flow_of_work_mcp import HandoverDraft, PacketWorkPlanDraft
from flow_of_work_mcp.application.architecture import ArchitectureService
from flow_of_work_mcp.application.packet_work_plan import _unit_from_payload
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import handle_handover
from tests.test_architecture_authority import adopt, definition
from tests.test_external_work import fixture, report


def repin(runtime, ids, revision):
    old = runtime.ledger.packet_work_plan_state(*ids)
    packet = runtime.changes.refine_packet(*ids,
        architecture_refs=({'revision': revision, 'kind': 'decision', 'entity_id': 'Ownership'},),
        actor='engineer')['packets'][0]
    plan = runtime.ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(
        ids[1], ids[2], packet['spec_revision'], tuple(_unit_from_payload(u) for u in old['units'])),
        expected_current_plan_revision=old['plan_revision'], actor='engineer')
    runtime.ledger.transition_packet_work_plan(ids[0], plan['work_plan_id'], plan['plan_revision'],
        status='accepted', expected_packet_revision=plan['packet_revision'],
        expected_current_plan_revision=plan['plan_revision'], rationale='Review the complete re-pinned plan.',
        actor='engineer')
    return {'expected_spec_revision': plan['packet_revision'], 'expected_plan_revision': plan['plan_revision']}


def prepared(tmp_path):
    ledger, _, ids, _ = fixture(tmp_path)
    runtime = build_runtime(database_path=ledger.database_path, import_root=tmp_path, ledger=ledger)
    authority = definition()
    authority['decisions'][0]['links'] = [{'kind': 'requirement', 'requirement_id': 'REQ-000001'}]
    adopted = adopt(runtime.architecture, authority, expected=runtime.ledger.architecture_revision(ids[0])['revision'])
    return runtime, ids, repin(runtime, ids, adopted['revision']), authority, adopted['revision']


def test_complete_export_and_hand_freeze_forward_architecture_and_original_intent(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        exported = runtime.external_work.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='issued')
        for text in ['Selected project architecture authority', 'Pi owns the loop', 'Own lifecycle authority.',
                     'Unknown effects do not authorize another writer.', 'increment-api',
                     'Call increment to implement next_value.', 'deferred control-plane verification']:
            assert text in exported['content']
        assert 'A producer shall expose increment and a consumer shall use it.' in exported['content']
        assert 'Own this explicit bounded responsibility.' not in exported['content']  # Unselected Noxi component.
        assert exported['draft'] is False
        frozen = runtime.handover.create_handover(ids[0], HandoverDraft(change_id=ids[1], packet_id=ids[2]),
                                                  actor='agent', request_id='frozen')
        assert frozen['payload']['architecture'] == frozen['payload']['recovery']['architecture']
        assert frozen['payload']['recovery']['authority']['authority_fingerprint'] == exported['authority_fingerprint']
        before = runtime.ledger.ledger_version(ids[0])
        current = runtime.handover.resume_context(ids[0], handover_id=frozen['handover_id'])
        assert current['architecture_comparison']['state'] == 'current'
        assert current['historical_comparison']['state'] == 'current'
        assert runtime.ledger.ledger_version(ids[0]) == before
    finally:
        runtime.close()


def test_offline_outcome_restart_and_relevant_architecture_drift_remain_historical(tmp_path):
    runtime, ids, revs, authority, revision = prepared(tmp_path)
    exported = runtime.external_work.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='offline-plan')
    payload = report(runtime.external_work, ids, revs)
    frozen = runtime.handover.create_handover(ids[0], HandoverDraft(change_id=ids[1], packet_id=ids[2]), actor='agent')
    runtime.close()

    reopened = build_runtime(database_path=tmp_path / 'flower.sqlite', import_root=tmp_path)
    try:
        unrelated = deepcopy(authority)
        unrelated['components'][2]['responsibility'] = 'Render a separate UI.'
        next_revision = adopt(reopened.architecture, unrelated, expected=revision, key='unrelated')['revision']
        same = reopened.external_work.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='same-plan')
        assert same['authority_fingerprint'] == exported['authority_fingerprint']
        assert same['content'] == exported['content']
        changed = deepcopy(unrelated)
        changed['components'][0]['invariants'] = ['Only one admitted execution owner.']
        current_revision = adopt(reopened.architecture, changed, expected=next_revision, key='changed')['revision']
        validation = reopened.external_work.validation(*ids, detail='full')
        assert any(gap['code'] == 'architecture_authority_stale' for gap in validation['validation']['gaps'])
        with pytest.raises(ChangeControlBlockedError):
            reopened.external_work.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='cannot-issue-stale')
        receipt = reopened.external_work.call(*ids, 'report_outcome', payload=payload,
                                               actor='agent', request_id='offline-outcome')
        assert receipt['status'] == 'historical'
        resumed = reopened.handover.resume_context(ids[0], handover_id=frozen['handover_id'])
        assert resumed['architecture_comparison']['state'] == 'stale'
        assert reopened.handover.get_handover(ids[0], frozen['handover_id']) == frozen
        new_revs = repin(reopened, ids, current_revision)
        current = reopened.external_work.call(*ids, 'export_plan', payload=new_revs,
                                              actor='agent', request_id='reviewed-new-plan')
        assert current['authority_fingerprint'] != exported['authority_fingerprint']
        assert 'Only one admitted execution owner.' in current['content']
        assert reopened.external_work.todo(*ids)['current_unit']['unit_key'] == 'producer'
        assert reopened.external_work.todo(*ids)['todos'][0]['status'] != 'complete'
        assert reopened.handover.get_handover(ids[0], frozen['handover_id']) == frozen
    finally:
        reopened.close()


def pre_policy_unpinned_fixture(tmp_path):
    ledger, external, ids, revs = fixture(tmp_path)
    plan = ledger.packet_work_plan_state(*ids)
    # Model pre-policy issued history explicitly, never an upgrade or a runtime
    # bypass. No report/evidence is promoted or assigned a new source pin.
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute("UPDATE implementation_packets SET architecture_refs_json='[]' WHERE project_id=? AND packet_id=?",
                           (ids[0], ids[2]))
        connection.execute("UPDATE implementation_packet_revisions SET architecture_refs_json='[]' WHERE project_id=? AND packet_id=?",
                           (ids[0], ids[2]))
        events = connection.execute('SELECT event_id,payload_json FROM packet_work_plan_events WHERE project_id=? AND work_plan_id=? AND event_type=?',
                                    (ids[0], plan['work_plan_id'], 'work_plan_accepted')).fetchall()
        for event_id, raw_payload in events:
            payload = json.loads(raw_payload)
            payload.pop('engineering_cycle_version', None)
            connection.execute('UPDATE packet_work_plan_events SET payload_json=? WHERE event_id=?',
                               (json.dumps(payload), event_id))
    assert ledger.packet_work_plan_state(*ids)['engineering_cycle_version'] is None
    return ledger, external, ids, revs


def test_unpinned_legacy_packet_ignores_unrelated_project_architecture(tmp_path):
    ledger, external, ids, revs = pre_policy_unpinned_fixture(tmp_path)
    original = external.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='before')
    adopt(ArchitectureService(ledger), expected=ledger.architecture_revision(ids[0])['revision'])
    after = external.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='after')
    assert original['authority_fingerprint'] == after['authority_fingerprint']
    assert original['content'] == after['content']
    assert 'architecture' not in external._snapshot(*ids)['authority_basis']


def test_handover_rejects_missing_packet_without_internal_failure_or_write(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        before = runtime.ledger.ledger_version(ids[0])
        result = handle_handover(runtime, project_id=ids[0], operation='resume_context',
                                 change_id=ids[1], packet_id='PKT-NOT-FOUND')
        assert result['status'] == 'blocked' and result['reason'] == 'packet_not_found'
        assert runtime.ledger.ledger_version(ids[0]) == before
    finally:
        runtime.close()
