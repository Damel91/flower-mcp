"""Real owned SQLite and process-lease boundaries for browser administration."""
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest

from flow_of_work_mcp.application.jobs import JobBlockedError
from flow_of_work_mcp.dashboard_maintenance import DashboardMaintenance, MaintenanceUnavailable
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership
from tests.test_native_project_purge import _fixture, _rows


def owned(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    lease = acquire_runtime_ownership(database)
    runtime = build_runtime(database_path=database, import_root=tmp_path, runtime_ownership=lease)
    return runtime, DashboardMaintenance(runtime, config, drain_timeout=0.05), config, database


def test_prepare_cancel_and_delete_keep_lease_other_project_and_native_journal(tmp_path):
    runtime, maintenance, config, database = owned(tmp_path)
    try:
        before = _rows(database)
        deletion = str(uuid4())
        prepared = maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        assert prepared['deletion']['deletion_state'] == 'prepared'
        assert maintenance.status()['state'] == 'maintenance'
        with pytest.raises(RuntimeOwnershipError):
            acquire_runtime_ownership(database)
        with pytest.raises(MaintenanceUnavailable):
            maintenance.read(runtime.ledger.traceability_matrix, 'project-b')
        version = runtime.ledger.ledger_version('project-b')
        with pytest.raises(JobBlockedError, match='server_maintenance'):
            runtime.jobs.submit(project_id='project-b', kind='test', actor='test', request_id='paused', operation=lambda: {})
        assert runtime.ledger.ledger_version('project-b') == version
        cancelled = maintenance.operate('project-a', 'cancel', {'deletion_id': deletion})
        assert cancelled['maintenance']['state'] == 'ready'
        journal = database.with_name(database.name + '.project-purge') / (deletion + '.json')
        assert journal.exists()
        assert _rows(database) == before
        again = maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        result = maintenance.operate('project-a', 'delete', {'deletion_id': deletion,
            'expected_fingerprint': again['deletion']['prepared_fingerprint'], 'confirm_project_id': 'project-a',
            'host_quiescence_ref': 'test-owner:external-workers-stopped'}, authorize_delete=lambda: None)
        assert result['deletion']['deletion_state'] == 'scrubbed'
        assert result['maintenance']['state'] == 'ready'
        assert journal.exists()
        assert runtime.ledger.traceability_matrix('project-b') == []
        with pytest.raises(RuntimeOwnershipError):
            acquire_runtime_ownership(database)
        assert config.exists()
    finally:
        runtime.close()


def test_busy_jobs_refuse_preparation_without_cancelling_or_creating_new_job(tmp_path):
    runtime, maintenance, _, _ = owned(tmp_path)
    started, finish = Event(), Event()
    def work():
        started.set()
        assert finish.wait(5)
        return {'synthetic': True}
    try:
        job = runtime.jobs.submit(project_id='project-a', kind='test', actor='test', request_id='busy', operation=work)
        assert started.wait(2)
        with pytest.raises(MaintenanceUnavailable, match='maintenance_jobs_busy'):
            maintenance.operate('project-a', 'prepare', {'deletion_id': str(uuid4())})
        assert maintenance.status()['state'] == 'ready'
        finish.set()
        runtime.jobs.wait('project-a', job.job_id, timeout=2)
    finally:
        finish.set()
        runtime.close()


def test_actual_reader_is_counted_until_it_settles_and_mcp_refusal_has_both_channels(tmp_path):
    runtime, maintenance, _, _ = owned(tmp_path)
    started, finish = Event(), Event()
    def read():
        with maintenance.admission():
            started.set()
            finish.wait(5)
    worker = Thread(target=read)
    try:
        worker.start()
        assert started.wait(2)
        with pytest.raises(MaintenanceUnavailable, match='maintenance_requests_busy'):
            maintenance.operate('project-a', 'prepare', {'deletion_id': str(uuid4())})
        finish.set()
        worker.join(2)
        maintenance.operate('project-a', 'prepare', {'deletion_id': str(uuid4())})
        def forbidden(**kwargs):
            raise AssertionError('admitted MCP handler during maintenance')
        result = maintenance.wrap_tool(forbidden, 'fow_capabilities')(view='summary')
        assert result.structuredContent['result']['reason'] == 'server_maintenance'
        assert 'maintenance' in result.content[0].text.lower()
    finally:
        finish.set()
        worker.join(2)
        runtime.close()


def test_malformed_startup_journal_holds_admissions_and_cannot_be_replaced(tmp_path):
    runtime, maintenance, config, database = owned(tmp_path)
    try:
        deletion = str(uuid4())
        maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        path = database.with_name(database.name + '.project-purge') / (deletion + '.json')
        path.write_text('{}')
        restarted = DashboardMaintenance(runtime, config)
        assert restarted.status()['state'] == 'recovery_required'
        with pytest.raises(MaintenanceUnavailable):
            restarted.operate('project-b', 'prepare', {'deletion_id': str(uuid4())})
        assert path.read_text() == '{}'
    finally:
        runtime.close()


def test_committed_deletion_with_failed_scrub_stays_fenced_until_same_intent_reconcile(tmp_path, monkeypatch):
    from flow_of_work_mcp import native_project_purge
    runtime, maintenance, config, database = owned(tmp_path)
    deletion = str(uuid4())
    try:
        prepared = maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        original = native_project_purge._Gateway._scrub
        def fail_scrub(*args):
            raise OSError('synthetic interrupted filesystem scrub')
        monkeypatch.setattr(native_project_purge._Gateway, '_scrub', fail_scrub)
        result = maintenance.operate('project-a', 'delete', {'deletion_id': deletion,
            'expected_fingerprint': prepared['deletion']['prepared_fingerprint'], 'confirm_project_id': 'project-a',
            'host_quiescence_ref': 'test-owner:external-workers-stopped'}, authorize_delete=lambda: None)
        assert result['deletion']['project_effect_state'] == 'applied'
        assert result['deletion']['deletion_state'] == 'ledger_deleted'
        assert result['maintenance']['state'] == 'recovery_required'
        restarted = DashboardMaintenance(runtime, config)
        assert restarted.status()['deletion_id'] == deletion
        assert restarted.operate('project-a', 'cancel', {'deletion_id': deletion})['maintenance']['state'] == 'recovery_required'
        with pytest.raises(MaintenanceUnavailable):
            restarted.operate('project-b', 'prepare', {'deletion_id': str(uuid4())})
        monkeypatch.setattr(native_project_purge._Gateway, '_scrub', original)
        recovered = restarted.operate('project-a', 'reconcile', {'deletion_id': deletion})
        assert recovered['deletion']['deletion_state'] == 'scrubbed'
        assert recovered['maintenance']['state'] == 'ready'
        assert runtime.ledger.traceability_matrix('project-b') == []
        with pytest.raises(RuntimeOwnershipError):
            acquire_runtime_ownership(database)
    finally:
        runtime.close()


def test_recovered_intent_cannot_bypass_an_existing_runtime_job(tmp_path, monkeypatch):
    import json
    runtime, maintenance, config, database = owned(tmp_path)
    deletion = str(uuid4())
    started, finish = Event(), Event()
    try:
        maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        maintenance.operate('project-a', 'cancel', {'deletion_id': deletion})
        path = database.with_name(database.name + '.project-purge') / (deletion + '.json')
        journal = json.loads(path.read_text())
        journal['stage'] = 'deleting'  # Simulate a crash after intent publication, before commit.
        path.write_text(json.dumps(journal))
        def work():
            started.set()
            finish.wait(5)
            return {}
        job = runtime.jobs.submit(project_id='project-b', kind='test', actor='test', request_id='existing', operation=work)
        assert started.wait(2)
        recovered = DashboardMaintenance(runtime, config)
        assert recovered.status()['state'] == 'recovery_required'
        def forbidden(*args, **kwargs):
            raise AssertionError('native gateway entered while job was live')
        monkeypatch.setattr('flow_of_work_mcp.dashboard_maintenance.run_project_purge', forbidden)
        with pytest.raises(MaintenanceUnavailable, match='maintenance_jobs_busy'):
            recovered.operate('project-a', 'inspect', {'deletion_id': deletion})
        finish.set()
        runtime.jobs.wait('project-b', job.job_id, timeout=2)
    finally:
        finish.set()
        runtime.close()


def test_finished_journal_does_not_turn_later_config_changes_into_recovery(tmp_path):
    runtime, maintenance, config, _ = owned(tmp_path)
    deletion = str(uuid4())
    try:
        prepared = maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        maintenance.operate('project-a', 'delete', {'deletion_id': deletion,
            'expected_fingerprint': prepared['deletion']['prepared_fingerprint'], 'confirm_project_id': 'project-a',
            'host_quiescence_ref': 'test-owner:external-workers-stopped'}, authorize_delete=lambda: None)
        config.write_text(config.read_text() + '\n# A later legitimate configuration edit.\n')
        reopened = DashboardMaintenance(runtime, config)
        assert reopened.status()['state'] == 'ready'
        assert reopened.read(runtime.ledger.traceability_matrix, 'project-b') == []
    finally:
        runtime.close()


def test_malformed_historical_identity_holds_startup_without_rewriting_journal(tmp_path):
    import json
    runtime, maintenance, config, database = owned(tmp_path)
    deletion = str(uuid4())
    try:
        maintenance.operate('project-a', 'prepare', {'deletion_id': deletion})
        maintenance.operate('project-a', 'cancel', {'deletion_id': deletion})
        path = database.with_name(database.name + '.project-purge') / (deletion + '.json')
        original = json.loads(path.read_text())
        malformed = [
            {**original, 'project_id': []},
            {**original, 'deletion_id': 'not-a-uuid'},
            {**original, 'config_identity': None},
            {**original, 'config_identity': {**original['config_identity'], 'path': 'relative.yaml'}},
            {**original, 'config_identity': {**original['config_identity'], 'sha256': 'invalid'}},
            {**original, 'database_identity': {**original['database_identity'], 'inode': True}},
        ]
        for journal in malformed:
            content = json.dumps(journal)
            path.write_text(content)
            reopened = DashboardMaintenance(runtime, config)
            assert reopened.status()['state'] == 'recovery_required'
            with pytest.raises(MaintenanceUnavailable):
                reopened.read(runtime.ledger.traceability_matrix, 'project-b')
            assert path.read_text() == content
    finally:
        runtime.close()
