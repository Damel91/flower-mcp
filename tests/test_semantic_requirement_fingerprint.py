"""Indirect requirement currentness, issued outcomes and immutable legacy pins."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp import LifecycleStatus, RequirementService
from flow_of_work_mcp.core.domain.campaign_authority import BehavioralOracleDraft, semantic_fingerprint
from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.domain.oracle_ir_projection import compile_oracle_ir
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.mcp_runtime import build_runtime
from tests.test_campaign_authority import _complete_typed_ir_fields, _start
from tests.test_external_milestone_progress import accept_units
from tests.test_external_packet_dependencies import dependent_fixture, finish_predecessor
from tests.test_external_work import report
from tests.test_noxi_architecture_handoff import prepared


def set_status(ledger, status):
    return RequirementService(ledger).set_lifecycle(
        'alpha', 'REQ-000001', status, actor='human', reason='Record observed progress.',
        governed_approval_reference='human:explicit-test-transition')


@pytest.mark.parametrize('status', [LifecycleStatus.PARTIAL, LifecycleStatus.IMPLEMENTED])
def test_linked_architecture_preserves_issued_outcome_todo_display_and_restart(tmp_path, status):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    external = runtime.external_work
    try:
        issued = external.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='issued')
        offline = report(external, ids, revs, 'consumer', report_key='offline-consumer')
        producer = report(external, ids, revs)
        external.call(*ids, 'report_outcome', actor='agent', request_id='producer', payload=producer)
        history = deepcopy(runtime.ledger.external_work_state(*ids)['reports'])
        set_status(runtime.ledger, status)
        current = external.todo(*ids)
        assert current['authority_fingerprint'] == issued['authority_fingerprint']
        assert current['todos'][0]['status'] == 'complete'
        assert runtime.ledger.external_work_state(*ids)['reports'] == history
        basis = external.provider_validation(*ids)['authority_context']
        linked = basis['architecture']['selected_context']['canonical_links'][0]['content']
        assert linked['retired'] is False and 'lifecycle_status' not in linked
        refs = runtime.ledger.change_state(*ids[:2])['packets'][0]['architecture_refs']
        visible = runtime.ledger.resolve_architecture_refs(ids[0], refs)
        assert visible['selected_context']['canonical_links'][0]['content']['lifecycle_status'] == status.value
        receipt = external.call(*ids, 'report_outcome', actor='agent', request_id='offline-consumer', payload=offline)
        assert receipt['status'] == 'success'
        assert all(row['status'] == 'complete' for row in external.todo(*ids)['todos'])
    finally:
        runtime.close()
    reopened = build_runtime(database_path=tmp_path / 'flower.sqlite', import_root=tmp_path)
    try:
        assert reopened.external_work.todo(*ids)['authority_fingerprint'] == issued['authority_fingerprint']
        assert all(row['status'] == 'complete' for row in reopened.external_work.todo(*ids)['todos'])
        assert reopened.external_work.call(*ids, 'report_outcome', actor='agent', request_id='offline-consumer', payload=offline) == receipt
    finally:
        reopened.close()


@pytest.mark.parametrize('retire', [False, True])
def test_linked_requirement_meaning_or_retirement_stales_without_rewriting_reports(tmp_path, retire):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        old = report(runtime.external_work, ids, revs)
        runtime.external_work.call(*ids, 'report_outcome', actor='agent', request_id='original', payload=old)
        history = deepcopy(runtime.ledger.external_work_state(*ids)['reports'])
        if retire:
            set_status(runtime.ledger, LifecycleStatus.REMOVED)
        else:
            runtime.ledger.revise_requirement(ids[0], 'REQ-000001', title='Revised protocol',
                statement='The producer shall increment by two.', category='functional',
                rationale='Explicitly revised intent.', actor='human')
        assert runtime.external_work.provider_validation(*ids)['authority_fingerprint'] != old['authority_fingerprint']
        current = runtime.external_work.todo(*ids)
        if retire:
            assert current['status'] == 'blocked'
        else:
            assert current['todos'][0]['status'] != 'complete'
        assert runtime.ledger.external_work_state(*ids)['reports'] == history
        with pytest.raises(ChangeControlBlockedError, match='reconciliation_stale|requirement_retired'):
            runtime.external_work.call(*ids, 'reconcile_outcome', actor='human', request_id='cannot-promote',
                payload={**revs, 'report_key': old['report_key'], 'rationale': 'Inspect original evidence.'})
    finally:
        runtime.close()


def test_predecessor_architecture_lifecycle_change_preserves_downstream_authority(tmp_path, monkeypatch):
    def linked_fixture(path):
        runtime, ids, revs, _, _ = prepared(path)
        return runtime.ledger, runtime.external_work, ids, revs
    monkeypatch.setattr('tests.test_external_packet_dependencies.fixture', linked_fixture)
    ledger, external, first_ids, first_revs, ids, _ = dependent_fixture(tmp_path)
    finish_predecessor(external, first_ids, first_revs)
    before = external.provider_validation(*ids)['authority_context']
    set_status(ledger, LifecycleStatus.IMPLEMENTED)
    after = external.provider_validation(*ids)['authority_context']
    assert after == before
    assert all(row['status'] == 'complete' for row in external.todo(*first_ids)['todos'])


def oracle_fixture(runtime, ids, *, binding_kind='subject_bindings'):
    state = _start(runtime, ids[1], 'REQ-000001')
    draft = BehavioralOracleDraft(oracle_kind='behavior', authority_reference='decision:typed',
        semantic_fields=_complete_typed_ir_fields() if binding_kind == 'subject_bindings' else {
            **_complete_typed_ir_fields(), 'stimulus': {'operator': 'call', 'subject_ref': 'module:synthetic', 'arguments': []}}, **({'subject_bindings': ('REQ-000001',)}
            if binding_kind == 'subject_bindings' else {'subject_bindings': ('module:synthetic',), 'goal_bindings': ('REQ-000001',)}))
    state = runtime.ledger.author_behavioral_oracle('alpha', state['campaign_id'], 'CASE-000001',
        draft, actor='engineer', request_id='oracle')
    return state, draft


@pytest.mark.parametrize('binding_kind', ['subject_bindings', 'goal_bindings'])
@pytest.mark.parametrize('authority_ref_kind', ['oracle', 'campaign'])
def test_oracle_dependency_ir_and_referencing_packet_ignore_progress(tmp_path, binding_kind, authority_ref_kind):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        state, _ = oracle_fixture(runtime, ids, binding_kind=binding_kind)
        oracle = state['oracles'][0]
        before_ir = compile_oracle_ir(oracle)
        assert before_ir.constructible
        units = deepcopy(runtime.ledger.packet_work_plan_state(*ids)['units'])
        reference = 'oracle:' + oracle['oracle_id'] if authority_ref_kind == 'oracle' else 'campaign:' + state['campaign_id']
        units[0]['verifies'].append({'criterion': 1, 'kind': 'oracle', 'statement': 'Deferred exact Oracle.', 'authority_ref': reference})
        accept_units(runtime.ledger, ids, units)
        before = runtime.external_work.todo(*ids)['authority_fingerprint']
        for status in (LifecycleStatus.PARTIAL, LifecycleStatus.IMPLEMENTED, LifecycleStatus.PARTIAL, LifecycleStatus.PLANNED):
            set_status(runtime.ledger, status)
            current = runtime.ledger.campaign_authority_state('alpha', state['campaign_id'])['oracles'][0]
            assert current['current_dependency_fingerprint'] == oracle['dependency_fingerprint']
            assert compile_oracle_ir(current).snapshot.canonical_bytes == before_ir.snapshot.canonical_bytes
            assert runtime.external_work.todo(*ids)['authority_fingerprint'] == before
        set_status(runtime.ledger, LifecycleStatus.REMOVED)
        retired = runtime.ledger.campaign_authority_state('alpha', state['campaign_id'])['oracles'][0]
        assert compile_oracle_ir(retired).status.value == 'stale'
        assert runtime.external_work.provider_validation(*ids)['authority_fingerprint'] != before
    finally:
        runtime.close()


def test_legacy_oracle_hash_stays_historical_until_new_ordinary_oracle_identity(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        state, draft = oracle_fixture(runtime, ids)
        oracle = state['oracles'][0]
        # Exact published 0.8.2 dependency representation, with no algorithm version.
        old_hash = semantic_fingerprint({'authority_reference': 'decision:typed',
            'subject_bindings': [{'kind': 'requirement', 'ref': 'REQ-000001', 'revision': 1, 'status': 'planned'}],
            'goal_bindings': []})
        with runtime.ledger._transaction() as connection:
            connection.execute('UPDATE behavioral_oracle_revisions SET dependency_fingerprint=? WHERE oracle_id=?',
                               (old_hash, oracle['oracle_id']))
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            before = '\n'.join(connection.iterdump())
        legacy = runtime.ledger.campaign_authority_state('alpha', state['campaign_id'])['oracles'][0]
        assert legacy['dependency_fingerprint'] == old_hash
        assert compile_oracle_ir(legacy).status.value == 'stale'
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            assert '\n'.join(connection.iterdump()) == before
        refreshed = runtime.ledger.author_behavioral_oracle('alpha', state['campaign_id'], 'CASE-000001',
            draft, actor='engineer', request_id='explicit-new-oracle')
        current = next(row for row in refreshed['oracles'] if row['oracle_id'] != oracle['oracle_id'])
        assert compile_oracle_ir(current).constructible
        with sqlite3.connect(runtime.ledger.database_path) as connection:
            stored_hash = connection.execute('SELECT dependency_fingerprint FROM behavioral_oracle_revisions WHERE oracle_id=? AND revision=1',
                                             (oracle['oracle_id'],)).fetchone()[0]
        assert stored_hash == old_hash
    finally:
        runtime.close()


def test_old_architecture_hash_report_requires_explicit_current_reassessment(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        snapshot = runtime.external_work._snapshot(*ids)
        old_basis = deepcopy(snapshot['authority_basis'])
        old_basis['architecture'] = snapshot['architecture']
        original = report(runtime.external_work, ids, revs, report_key='old-issued')
        original['authority_fingerprint'] = fingerprint(old_basis)
        receipt = runtime.external_work.call(*ids, 'report_outcome', actor='agent',
            request_id='old-issued', payload=original)
        assert receipt['status'] == 'historical'
        history = deepcopy(runtime.ledger.external_work_state(*ids)['reports'])
        set_status(runtime.ledger, LifecycleStatus.IMPLEMENTED)
        assert runtime.external_work.todo(*ids)['todos'][0]['status'] != 'complete'
        with pytest.raises(ChangeControlBlockedError, match='reconciliation_stale'):
            runtime.external_work.call(*ids, 'reconcile_outcome', actor='human', request_id='old-select',
                payload={**revs, 'report_key': 'old-issued', 'rationale': 'Old evidence requires reassessment.'})
        assert runtime.ledger.external_work_state(*ids)['reports'] == history
        current = report(runtime.external_work, ids, revs, report_key='current-reassessed')
        current['summary'] = 'Reassessed the existing implementation and rechecked current obligations.'
        assert runtime.external_work.call(*ids, 'report_outcome', actor='agent', request_id='current', payload=current)['status'] == 'success'
        assert runtime.external_work.todo(*ids)['todos'][0]['status'] == 'complete'
        assert runtime.ledger.external_work_state(*ids)['reports'][0] == history[0]
    finally:
        runtime.close()
