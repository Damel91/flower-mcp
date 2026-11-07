"""Read-only browser projections over canonical temporary ledgers."""
import json
import sqlite3

import pytest

from flow_of_work_mcp import HandoverDraft, LifecycleStatus, MilestoneDraft, RequirementDraft, RequirementService
from flow_of_work_mcp.application.dashboard import DashboardProjectionService, MAXIMUM_EVIDENCE_BYTES
from flow_of_work_mcp.application.engineering_cycle import DIMENSIONS, RepositoryReviewService
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind
from flow_of_work_mcp.core.domain.lifecycle_control import PhaseAuditScope
from flow_of_work_mcp.mcp_runtime import build_runtime
from tests.test_campaign_authority import _complete_typed_ir_fields, _start
from tests.test_external_work import report
from tests.test_noxi_architecture_handoff import prepared
from flow_of_work_mcp.core.domain.campaign_authority import BehavioralOracleDraft


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return '\n'.join(connection.iterdump())


def test_catalog_is_sql_paged_literal_and_does_not_hydrate_projects(tmp_path, monkeypatch):
    runtime = build_runtime(database_path=tmp_path / 'dashboard.sqlite', import_root=tmp_path)
    try:
        for index in range(31):
            runtime.requirements.create_project(f'project-{index:02d}', f'Project {index}', actor='human')
        runtime.requirements.create_project('literal', 'A 100% _literal_ project', actor='human')
        monkeypatch.setattr(runtime.project_state_snapshot, 'snapshot', lambda *args, **kwargs: pytest.fail('Catalog hydrated project snapshot'))
        before = dump(runtime)
        service = DashboardProjectionService(runtime)
        first = service.projects()
        second = service.projects(offset=first['next_offset'])
        assert first['count'] == 25 and first['total'] == 32
        assert second['count'] == 7 and second['next_offset'] is None
        assert not {row['project_id'] for row in first['projects']} & {row['project_id'] for row in second['projects']}
        for term in ('%', '_literal_', "' OR 1=1 --"):
            found = service.projects(search=term)
            assert found['total'] == (0 if term.startswith("'") else 1)
        assert all(isinstance(row['source_ledger_version'], int) for row in first['projects'])
        assert dump(runtime) == before
    finally:
        runtime.close()


@pytest.mark.parametrize('invalid', [{'limit': 0}, {'limit': 26}, {'limit': True}, {'offset': -1}, {'offset': False}, {'search': 'x' * 257}])
def test_catalog_rejects_invalid_bounds_before_reading(tmp_path, invalid):
    runtime = build_runtime(database_path=tmp_path / 'dashboard.sqlite', import_root=tmp_path)
    try:
        before = dump(runtime)
        with pytest.raises(ValueError):
            DashboardProjectionService(runtime).projects(**invalid)
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_oversized_offset_rejects_before_any_sqlite_parameter_binding(tmp_path, monkeypatch):
    runtime = build_runtime(database_path=tmp_path / 'dashboard.sqlite', import_root=tmp_path)
    try:
        service = DashboardProjectionService(runtime)
        monkeypatch.setattr(runtime.ledger, 'dashboard_projects', lambda **kwargs: pytest.fail('Bound oversized offset to SQLite'))
        with pytest.raises(ValueError, match='SQLite integer'):
            service.projects(offset=10**90)
        with pytest.raises(ValueError, match='SQLite integer'):
            service.project('alpha', offset=2**63)
    finally:
        runtime.close()


def test_every_section_is_a_coherent_read_without_context_or_lens_mutation(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        before = dump(runtime)
        service = DashboardProjectionService(runtime)
        for section in ('overview', 'roadmap', 'packets', 'verification', 'architecture', 'evidence'):
            result = service.project(ids[0], section, limit=1)
            assert result['project']['project_id'] == ids[0]
            assert result['section'] == section and result['coherent_read'] is True
            assert len(result['items']) <= 1
            assert result['bounds']['limit'] == 1
            assert result['source_ledger_version'] == runtime.ledger.ledger_version(ids[0])
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_packet_progress_is_host_reported_and_keeps_revision_and_next_gate(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        payload = report(runtime.external_work, ids, revs)
        runtime.external_work.call(*ids, 'report_outcome', actor='agent', request_id='reported', payload=payload)
        RequirementService(runtime.ledger).set_lifecycle(ids[0], 'REQ-000001', LifecycleStatus.IMPLEMENTED,
            actor='human', reason='Observed implementation progress.')
        before = dump(runtime)
        row = DashboardProjectionService(runtime).project(ids[0], 'packets', limit=1)['items'][0]
        assert row['spec_revision'] == revs['expected_spec_revision']
        assert row['plan_revision'] == revs['expected_plan_revision']
        assert row['reported_units'] == {'completed': 1, 'total': 2, 'provenance': 'external_agent_report'}
        assert row['units'][0]['status'] == 'complete'
        assert row['units_bounds']['total'] == 2 and row['units_bounds']['truncated'] is True
        assert row['next_gate'] and row['acceptance'] == 'not_inferred'
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_roadmap_progress_names_visible_scope_and_never_infers_acceptance(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        runtime.ledger.promote_milestone(ids[0], MilestoneDraft(name='Current scope', requirement_ids=('REQ-000001',),
            prerequisite_requirement_ids=(), entry_policy={}, exit_policy={}, risk_disposition='bounded'), actor='human')
        before = dump(runtime)
        result = DashboardProjectionService(runtime).project(ids[0], 'roadmap')
        assert result['summary']['scope'] == 'visible_milestones'
        assert result['items'][0]['name'] == 'Current scope'
        assert result['items'][0]['acceptance']['state'] != 'accepted'
        assert 'implementation' in result['items'][0] and 'local_verification' in result['items'][0]
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_oracle_source_ir_and_evidence_are_observed_without_execution(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        state = _start(runtime, ids[1], 'REQ-000001')
        runtime.ledger.author_behavioral_oracle(ids[0], state['campaign_id'], 'CASE-000001',
            BehavioralOracleDraft(oracle_kind='behavior', authority_reference='test:explicit',
                subject_bindings=('REQ-000001',), semantic_fields=_complete_typed_ir_fields()),
            actor='engineer', request_id='oracle')
        before = dump(runtime)
        row = DashboardProjectionService(runtime).project(ids[0], 'verification')['items'][0]
        assert row['campaign_id'] == state['campaign_id'] and row['oracle_count'] == 1
        assert row['oracles'][0]['oracle_id'] == 'ORACLE-000001'
        assert row['evidence_count'] == 0 and row['evidence'] == []
        assert row['acceptance'] == 'not_inferred' and row['completed'] is False
        assert row['lifecycle_gate']
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_retained_evidence_is_same_project_exact_and_never_generates(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        exported = runtime.external_work.call(*ids, 'export_plan', payload=revs, actor='agent', request_id='export')
        handover = runtime.handover.create_handover(ids[0], HandoverDraft(change_id=ids[1], packet_id=ids[2]), actor='agent')
        verification = runtime.ledger.record_verification(ids[0], 'REQ-000001', kind='tested_deterministically', outcome='passed',
            reference='host:fixture-test', metadata={'provenance': 'host_reported'}, actor='agent')
        runtime.requirements.create_project('other', 'Other project', actor='human')
        service = DashboardProjectionService(runtime)
        before = dump(runtime)
        rows = service.project(ids[0], 'evidence')['items']
        assert {row['kind'] for row in rows} == {'artifact', 'handover', 'verification'}
        artifact_id = next(row['identity'] for row in rows if row['kind'] == 'artifact')
        artifact = service.evidence(ids[0], 'artifact', artifact_id)
        assert artifact['content'] == exported['content']
        assert artifact['content_type'] == 'text/markdown'
        frozen = service.evidence(ids[0], 'handover', handover['handover_id'])
        assert json.loads(frozen['content']) == handover['payload']
        evidence = service.evidence(ids[0], 'verification', str(verification['evidence_id']))
        assert json.loads(evidence['content'])['metadata']['provenance'] == 'host_reported'
        with pytest.raises(ValueError, match='not found'):
            service.evidence('other', 'artifact', artifact_id)
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_verification_channels_keep_independent_evidence_and_exact_original_pins(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    project_id, change_id, packet_id = ids
    requirement_id = 'REQ-000001'
    try:
        payload = report(runtime.external_work, ids, revs)
        runtime.external_work.call(*ids, 'report_outcome', actor='agent', request_id='reported', payload=payload)
        first = runtime.ledger.record_verification(project_id, requirement_id, kind='tested_deterministically',
            outcome='failed', reference='host:failed-attempt', actor='agent')
        second = runtime.ledger.record_verification(project_id, requirement_id, kind='tested_deterministically',
            outcome='passed', reference='host:corrected-attempt', actor='agent')
        runtime.lifecycle.audit_phase(project_id, PhaseAuditScope('unrelated-phase'), actor='engineer')
        context = RepositoryReviewService(runtime.ledger).context(*ids)
        review = {"contract_version": "flow.repository-review.v1", "change_id": change_id, "packet_id": packet_id,
                  "expected_basis_fingerprint": context['basis_fingerprint'], "source_identity": "host:repo",
                  "source_revision": "git:exact-review-source", "coverage": [
                      {"dimension": dimension, "state": "aligned", "rationale": "Confirmed within the issued scope.",
                       "evidence_refs": [f"host:{dimension}"]} for dimension in DIMENSIONS]}
        job = RepositoryReviewService(runtime.ledger).submit(
            project_id, PhaseAuditScope(context['scope_id'], tuple(context['requirement_ids'])), review,
            actor='engineer', request_id='review', jobs=runtime.jobs, lifecycle=runtime.lifecycle)
        assert runtime.jobs.wait(project_id, job.job_id, timeout=10).status.value == 'completed'
        audit_id = runtime.ledger.latest_phase_audit(project_id, context['scope_id'])['phase_audit_id']
        runtime.requirements.create_project('other', 'Other project', actor='human')
        before = dump(runtime)
        service = DashboardProjectionService(runtime)
        campaigns = service.project(project_id, 'verification')
        assert campaigns['items'] == []
        assert campaigns['summary']['evidence_channels'] == {
            'campaign': 0, 'verification': 2, 'external_report': 1, 'repository_review': 1}

        direct = service.project(project_id, 'verification', channel='verification', scope_id=requirement_id, limit=1)
        next_page = service.project(project_id, 'verification', channel='verification', scope_id=requirement_id,
                                    offset=direct['bounds']['next_offset'], limit=1)
        assert direct['items'][0]['evidence_id'] == second['evidence_id']
        assert next_page['items'][0]['evidence_id'] == first['evidence_id']
        assert next_page['items'][0]['outcome'] == 'failed'

        external = service.project(project_id, 'verification', channel='external_report', scope_id=packet_id)['items'][0]
        assert external['recorded_disposition'] == 'current'
        assert external['authority_fingerprint'] == payload['authority_fingerprint']
        retained_report = service.evidence(project_id, external['kind'], external['identity'])
        assert json.loads(retained_report['content'])['report'] == payload
        reviews = service.project(project_id, 'verification', channel='repository_review', scope_id=packet_id)
        assert reviews['bounds']['total'] == 1 and reviews['items'][0]['phase_audit_id'] == audit_id
        retained_review = service.evidence(project_id, 'repository_review', str(audit_id))
        assert json.loads(retained_review['content'])['repository_review'] == review
        for kind, identity in [('verification', str(first['evidence_id'])), ('external_report', external['identity']),
                               ('repository_review', str(audit_id))]:
            with pytest.raises(ValueError, match='not found'):
                service.evidence('other', kind, identity)
        assert service.project(project_id, 'verification', channel='external_report', scope_id='PACKET-999999')['items'] == []
        packet = service.project(project_id, 'packets')['items'][0]
        assert packet['report_history'][0]['currentness'] == 'current_authority'
        assert packet['repository_review']['latest_audit_id'] == audit_id
        assert packet['requirement_evidence'] == [{'requirement_id': requirement_id, 'recorded_count': 2}]
        assert packet['acceptance'] == 'not_inferred'
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_packet_card_keeps_historical_reports_after_requirement_revision(tmp_path):
    runtime, ids, revs, _, _ = prepared(tmp_path)
    try:
        payload = report(runtime.external_work, ids, revs)
        runtime.external_work.call(*ids, 'report_outcome', actor='agent', request_id='old-outcome', payload=payload)
        RequirementService(runtime.ledger).revise(ids[0], 'REQ-000001', RequirementDraft(
            title='Scoped behavior', statement='The producer shall now double before exposing increment.', category='functional'),
            actor='human', rationale='A new requirement definition is separately governed.')
        packet = DashboardProjectionService(runtime).project(ids[0], 'packets', limit=1)['items'][0]
        assert packet['report_history'][0]['currentness'] == 'historical_on_original_pin'
        assert packet['report_history'][0]['authority_fingerprint'] == payload['authority_fingerprint']
        assert packet['report_history_bounds']['total'] == 1
        assert packet['requirement_evidence'] == [{'requirement_id': 'REQ-000001', 'recorded_count': 0}]
        assert packet['acceptance'] == 'not_inferred'
    finally:
        runtime.close()


def test_large_retained_evidence_has_explicit_read_limit_without_mutation(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    try:
        generation = ArtifactGeneration(project_id=ids[0], profile_id='test:large', profile_version='1',
            source_ledger_version=runtime.ledger.ledger_version(ids[0]), generated_at='2026-11-04T00:00:00Z',
            artifacts=(ArtifactDraft(ArtifactKind.SRS, 'x' * (MAXIMUM_EVIDENCE_BYTES + 1), ()),))
        runtime.ledger.record_artifact_generation(generation, actor='test')
        service = DashboardProjectionService(runtime)
        row = service.project(ids[0], 'evidence')['items'][0]
        before = dump(runtime)
        with pytest.raises(ValueError, match='2 MiB'):
            service.evidence(ids[0], 'artifact', row['identity'])
        assert dump(runtime) == before
    finally:
        runtime.close()


def test_verification_list_keeps_a_link_without_loading_oversized_reference(tmp_path):
    runtime, ids, _, _, _ = prepared(tmp_path)
    project_id = ids[0]
    try:
        evidence = runtime.ledger.record_verification(
            project_id, 'REQ-000001', kind='tested_deterministically', outcome='passed',
            reference='x' * (MAXIMUM_EVIDENCE_BYTES + 1), actor='agent')
        service = DashboardProjectionService(runtime)
        items = service.project(project_id, 'verification', channel='verification')['items']
        assert len(items) == 1
        assert items[0]['identity'] == str(evidence['evidence_id'])
        assert items[0]['outcome'] == 'passed'
        assert 'reference' not in items[0]
        with pytest.raises(ValueError, match='2 MiB'):
            service.evidence(project_id, 'verification', items[0]['identity'])
    finally:
        runtime.close()
