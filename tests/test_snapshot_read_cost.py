"""Coherent-read reuse must preserve authority and fresh write-boundary gates."""
from collections import Counter
from contextlib import closing
from copy import deepcopy
from threading import Event, Thread

import pytest

from flow_of_work_mcp import (ChangeControlService, GovernedChangeDraft,
    ImplementationPacketDraft, MilestoneDraft, PacketWorkPlanDraft, RequirementDraft,
    RequirementService, SQLiteRequirementLedger, WorkPlanUnit)
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.engineer_gate import EngineerGateService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ProjectNotFoundError
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.core.domain.assurance import ReviewFindingDraft
from tests.test_external_work import fixture
from tests.engineering_cycle_support import adopt_minimal_architecture
import flow_of_work_mcp.application.external_work as external_module


def _basic_project(runtime):
    requirements = RequirementService(runtime.ledger)
    requirements.create_project('alpha', 'Snapshot cost fixture', actor='fixture')
    requirement = requirements.register('alpha', RequirementDraft(title='Complete recovery',
        statement='The server shall expose complete current authority.', category='functional'), actor='fixture')
    milestone = runtime.lifecycle.promote_milestone('alpha', MilestoneDraft(name='Recovery',
        requirement_ids=(requirement['requirement_id'],), prerequisite_requirement_ids=(),
        entry_policy={}, exit_policy={}, risk_disposition='none'), actor='fixture')
    return requirements, requirement, milestone


def dag_fixture(tmp_path, count=8):
    runtime = build_runtime(database_path=tmp_path / 'dag.sqlite', import_root=tmp_path)
    reqs, requirement, milestone = _basic_project(runtime)
    architecture_refs = adopt_minimal_architecture(runtime.ledger)
    second = reqs.register('alpha', RequirementDraft(title='Shared scope',
        statement='The shared packet shall retain all recovery authority.', category='functional'), actor='fixture')
    changes = ChangeControlService(runtime.ledger)
    change = changes.create_change('alpha', GovernedChangeDraft(title='Shared predecessors',
        rationale='Repeated requirements and DAG ancestors must not multiply work.',
        milestone_id=milestone['milestone_id'],
        requirement_ids=(requirement['requirement_id'], second['requirement_id'])), actor='fixture')
    setup = ExternalWorkService(runtime.ledger)
    packets = []
    for index in range(count):
        packet = changes.add_packet('alpha', change['change_id'], ImplementationPacketDraft(
            title=f'Output {index}', objective=f'Produce output {index}.', rationale='A bounded shared predecessor.',
            completion_criteria=(f'Output {index} passes its check',),
            in_scope=(f'src/output_{index}.py',), invariants=('Preserve predecessor authority.',),
            architecture_refs=architecture_refs), actor='fixture')['packets'][-1]
        ids = ('alpha', change['change_id'], packet['packet_id'])
        for previous in packets[max(0, index-2):index]:
            changes.link_dependency(*ids, previous, actor='fixture')
        packet = runtime.ledger.change_state(*ids[:2])['packets'][-1]
        setup.call(*ids, 'upgrade_validation', actor='fixture', request_id=f'upgrade-{index}',
            payload={'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0})
        check = f'output_{index}() == {index}'
        unit = WorkPlanUnit(client_unit_key=f'output-{index}', operation_kind='new_file', file_path=f'src/output_{index}.py',
            instructions=(f'Implement output_{index}() returning {index}.',), unit_checks=(check,), implements=(1,),
            verifies=({'criterion': 1, 'kind': 'unit_check', 'statement': check},))
        plan = runtime.ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(
            ids[1], ids[2], packet['spec_revision'], (unit,)), actor='fixture')
        runtime.ledger.transition_packet_work_plan('alpha', plan['work_plan_id'], plan['plan_revision'], status='accepted',
            expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'],
            rationale='Complete bounded fixture.', actor='fixture')
        setup.call(*ids, 'set_mode', actor='fixture', request_id=f'mode-{index}', payload={'mode': 'external_agent',
            'expected_spec_revision': plan['packet_revision'], 'expected_plan_revision': plan['plan_revision']})
        packets.append(packet['packet_id'])
    return runtime, change['change_id'], packets


def test_read_memo_is_nested_copy_isolated_and_discarded_on_failure(tmp_path):
    ledger = SQLiteRequirementLedger(tmp_path / 'memo.sqlite')
    calls = []
    def produce():
        calls.append(1)
        return {'nested': [{'value': len(calls)}]}
    with pytest.raises(RuntimeError, match='outer failure'):
        with ledger.consistent_read():
            first = ledger.read_projection('test', ('alpha',), produce)
            first['nested'][0]['value'] = -1
            with ledger.consistent_read():
                second = ledger.read_projection('test', ('alpha',), produce)
                assert second['nested'][0]['value'] == 1
                second['nested'].clear()
            assert ledger.read_projection('test', ('alpha',), produce)['nested']
            assert ledger.read_projection('test', ('beta',), produce)['nested'][0]['value'] == 2
            raise RuntimeError('outer failure')
    assert ledger._transaction_connection.get() is None
    assert ledger._read_projection_memo.get() is None
    with ledger.consistent_read():
        assert ledger.read_projection('test', ('alpha',), produce)['nested'][0]['value'] == 3


def test_failed_producer_is_not_cached_and_atomic_reads_see_writes(tmp_path):
    ledger, _external, ids, _ = fixture(tmp_path)
    attempts = []
    def fail():
        attempts.append(1)
        raise ZeroDivisionError
    with ledger.consistent_read():
        for _ in range(2):
            with pytest.raises(ZeroDivisionError):
                ledger.read_projection('failure', ids, fail)
    assert len(attempts) == 2
    changes = ChangeControlService(ledger)
    with ledger.atomic():
        assert ledger._read_projection_memo.get() is None
        before = ledger.change_state(*ids[:2])
        ledger.list_changes(ids[0])
        changes.refine_packet(*ids, invariants=('A fresh invariant in this transaction.',), actor='engineer')
        after = ledger.change_state(*ids[:2])
        assert after['packets'][0]['spec_revision'] > before['packets'][0]['spec_revision']
        assert ledger.list_changes(ids[0])[0]['packets'][0] == after['packets'][0]


def test_rollback_failure_still_releases_memo_connection_and_context(tmp_path, monkeypatch):
    ledger = SQLiteRequirementLedger(tmp_path / 'rollback.sqlite')
    connect = ledger._connect
    closed = []
    class BrokenRollback:
        def __init__(self):
            self.connection = connect()
        def execute(self, *args):
            return self.connection.execute(*args)
        def rollback(self):
            raise RuntimeError('rollback failed')
        def close(self):
            self.connection.close()
            closed.append(True)
    with monkeypatch.context() as m:
        m.setattr(ledger, '_connect', BrokenRollback)
        with pytest.raises(RuntimeError, match='rollback failed'):
            with ledger.consistent_read():
                ledger.read_projection('test', ('alpha',), lambda: {'value': 1})
    assert closed == [True]
    assert ledger._transaction_connection.get() is None
    assert ledger._read_projection_memo.get() is None
    with ledger.consistent_read():
        assert ledger.read_projection('test', ('alpha',), lambda: {'value': 2}) == {'value': 2}


def test_gate_reads_after_semantic_write_are_fresh_even_in_same_atomic_scope(tmp_path):
    ledger, _external, ids, _ = fixture(tmp_path)
    gate = EngineerGateService(ledger)
    with ledger.consistent_read():
        assert gate.projection(ids[0], ids[2])['execution_allowed']
    with ledger.atomic():
        assert gate.projection(ids[0], ids[2])['execution_allowed']
        ledger.record_finding(ids[0], ReviewFindingDraft(change_id=ids[1], packet_id=ids[2],
            severity='medium', finding_kind='semantic', title='Observed intent mismatch',
            rationale='The implemented arithmetic differs from the accepted requirement.',
            expected_correction='Restore the accepted arithmetic.', scope_kind='packet', scope_ref=ids[2],
            implementation_ref='host-review:001'), actor='engineer')
        result = gate.projection(ids[0], ids[2])
        assert not result['execution_allowed']
        assert result['blockers'][0]['reason'] == 'semantic_finding_unresolved'
        with pytest.raises(ChangeControlBlockedError, match='engineer_semantic_findings_open'):
            gate.execution_guard(ids[0], ids[2])


@pytest.mark.parametrize('packet', ['', 'invalid', ' PACKET-000001 ', 'PACKET-999999'])
def test_mode_lookup_preserves_raw_packet_and_project_error_precedence(tmp_path, packet):
    ledger, external, ids, _ = fixture(tmp_path)
    ledger.list_changes = lambda *_: pytest.fail('mode lookup must not hydrate all changes')
    assert external.mode_for_packet(ids[0], ids[2]) == 'external_agent'
    with pytest.raises(ChangeControlBlockedError, match='packet_not_found'):
        external.mode_for_packet(ids[0], packet)
    with pytest.raises(ProjectNotFoundError):
        external.mode_for_packet('missing-project', packet)
    with pytest.raises(ValueError, match='project_id'):
        external.mode_for_packet('INVALID PROJECT', packet)


def test_shared_dag_projection_is_linear_and_matches_uncached_reference(tmp_path, monkeypatch):
    runtime, change_id, packets = dag_fixture(tmp_path, count=12)
    try:
        with runtime.ledger.consistent_read():
            snapshot = runtime.external_work._snapshot('alpha', change_id, packets[-1])
        counts = Counter()
        derive = external_module.derive_packet_validation
        def counted(value, **kwargs):
            counts[(value['packet_id'], kwargs.get('consumer_scope'))] += 1
            return derive(value, **kwargs)
        monkeypatch.setattr(external_module, 'derive_packet_validation', counted)
        projection = ExternalWorkService._projection(snapshot)
        assert sum(counts.values()) == len(packets)
        assert all(value == 1 for value in counts.values())
        original = ExternalWorkService._projection
        memo = {}
        first = original(snapshot, _cache=memo)
        pristine = deepcopy(first)
        first['criteria'][0]['statement'] = 'Caller mutation before a memo hit'
        first['units'][0]['unit_checks'].append('Caller-added check')
        assert original(snapshot, _cache=memo) == pristine
        assert original(snapshot, consumer_scope='provider', _cache=memo)['consumer_scope'] == 'provider'
        def uncached(value, *, consumer_scope='external_agent', _cache=None):
            return original(value, consumer_scope=consumer_scope)
        with monkeypatch.context() as m:
            m.setattr(ExternalWorkService, '_projection', staticmethod(uncached))
            reference = uncached(snapshot)
        assert projection == reference
        assert sum(counts.values()) > 12 * len(packets)  # Retained old path amplification.
        projection['criteria'][0]['statement'] = 'Caller mutation'
        assert original(snapshot) == reference
        assert original(snapshot, consumer_scope='provider')['consumer_scope'] == 'provider'
        assert original(snapshot, consumer_scope='provider')['contract_version'] != reference['contract_version']
        assert not any('projection' in key for key in snapshot)
    finally:
        runtime.close()


def test_complete_snapshot_matches_uncached_reads_and_reuses_packet_gates(tmp_path, monkeypatch):
    runtime, change_id, packets = dag_fixture(tmp_path)
    try:
        # Materialize/close independently so the comparison itself owns no read lock.
        with closing(runtime.ledger._connect()) as connection:
            before = list(connection.iterdump())
        calls = Counter()
        original = runtime.engineer_gate._projection
        def count(project_id, packet_id):
            calls[packet_id] += 1
            return original(project_id, packet_id)
        monkeypatch.setattr(runtime.engineer_gate, '_projection', count)
        cached = runtime.project_state_snapshot.snapshot('alpha')
        assert calls and max(calls.values()) == 1
        with monkeypatch.context() as m:
            m.setattr(runtime.ledger, 'read_projection', lambda namespace, key, producer: producer())
            uncached = runtime.project_state_snapshot.snapshot('alpha')
        cached.pop('generated_at'); uncached.pop('generated_at')
        assert cached == uncached
        with closing(runtime.ledger._connect()) as connection:
            assert list(connection.iterdump()) == before
        ChangeControlService(runtime.ledger).refine_packet('alpha', change_id, packets[0],
            invariants=('New upstream semantic authority.',), actor='engineer')
        changed = runtime.project_state_snapshot.snapshot('alpha')
        assert changed['snapshot_fingerprint'] != cached['snapshot_fingerprint']
        assert runtime.external_work.validation('alpha', change_id, packets[-1])['plan_executable'] is False
    finally:
        runtime.close()


def test_direct_traceability_is_one_coherent_scope_with_fresh_next_read(tmp_path, monkeypatch):
    runtime = build_runtime(database_path=tmp_path / 'coherent.sqlite', import_root=tmp_path)
    try:
        requirements, _, _ = _basic_project(runtime)
        read_done, writer_attempted = Event(), Event()
        errors = []
        original = runtime.ledger.traceability_matrix
        def paused(project_id):
            value = original(project_id)
            read_done.set()
            assert writer_attempted.wait(2)
            return value
        def write():
            try:
                assert read_done.wait(2)
                writer_attempted.set()
                requirements.register('alpha', RequirementDraft(title='Later authority',
                    statement='The next read shall contain this requirement.', category='functional'), actor='writer')
            except BaseException as exc:
                errors.append(exc)
        monkeypatch.setattr(runtime.ledger, 'traceability_matrix', paused)
        thread = Thread(target=write)
        thread.start()
        during = runtime.milestone_traceability.projection('alpha')
        thread.join(5)
        assert not thread.is_alive() and not errors
        monkeypatch.setattr(runtime.ledger, 'traceability_matrix', original)
        after = runtime.milestone_traceability.projection('alpha')
        assert len(during['rows']) == 1 and len(after['rows']) == 2
        assert after['source_ledger_version'] > during['source_ledger_version']
    finally:
        runtime.close()
