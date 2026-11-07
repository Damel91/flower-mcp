"""Real owned SQLite and process-lease boundaries for browser administration."""
import json
import sqlite3
from threading import Event, Thread
from uuid import uuid4

import pytest

from flow_of_work_mcp import dashboard_maintenance
from flow_of_work_mcp.application.jobs import JobBlockedError
from flow_of_work_mcp.dashboard_maintenance import DashboardMaintenance, MaintenanceUnavailable
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership
from tests.test_native_project_purge import _call, _fixture, _rows


def start_owned(tmp_path, config, database):
    lease = acquire_runtime_ownership(database)
    runtime = build_runtime(database_path=database, import_root=tmp_path, runtime_ownership=lease)
    return runtime, DashboardMaintenance(runtime, config, drain_timeout=0.05)


def owned(tmp_path, *, rich=False):
    config, database = _fixture(tmp_path.resolve(), rich=rich)
    runtime, maintenance = start_owned(tmp_path, config, database)
    return runtime, maintenance, config, database


def delete(maintenance, project_id='project-a'):
    return maintenance.operate(project_id, 'delete', {'confirm_project_id': project_id},
                               authorize_delete=lambda: None)


def test_direct_delete_fences_writes_and_removes_external_metadata_without_journal(tmp_path, monkeypatch):
    runtime, maintenance, config, database = owned(tmp_path, rich=True)
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE implementation_runs SET external_ref='host:unresolved' WHERE project_id='project-a'")
            connection.execute("UPDATE packet_provider_outbox SET state='pending', attempts=1 WHERE project_id='project-a'")
        before = _rows(database)
        config_bytes = config.read_bytes()
        original = dashboard_maintenance.run_dashboard_project_purge

        def during_purge(*args, **kwargs):
            assert maintenance.status()['state'] == 'maintenance'
            with pytest.raises(RuntimeOwnershipError):
                acquire_runtime_ownership(database)
            with pytest.raises(MaintenanceUnavailable):
                maintenance.read(runtime.ledger.traceability_matrix, 'project-b')
            with pytest.raises(JobBlockedError, match='server_maintenance'):
                runtime.jobs.submit(project_id='project-b', kind='test', actor='test',
                                    request_id='paused', operation=lambda: {})
            def forbidden(**arguments):
                raise AssertionError('admitted MCP handler during maintenance')
            result = maintenance.wrap_tool(forbidden, 'fow_capabilities')(view='summary')
            assert result.structuredContent['result']['reason'] == 'server_maintenance'
            assert 'maintenance' in result.content[0].text.lower()
            return original(*args, **kwargs)

        monkeypatch.setattr(dashboard_maintenance, 'run_dashboard_project_purge', during_purge)
        result = delete(maintenance)
        assert result['deletion']['deletion_state'] == 'scrubbed', result
        assert result['deletion']['project_effect_state'] == 'applied'
        assert result['maintenance']['state'] == 'ready'
        assert not database.with_name(database.name + '.project-purge').exists()
        after = _rows(database)
        assert after['projects'] == [before['projects'][1]]
        assert after['implementation_runs'] == [before['implementation_runs'][1]]
        assert after['packet_provider_outbox'] == [before['packet_provider_outbox'][1]]
        assert after['sqlite_sequence'] == before['sqlite_sequence']
        assert config.read_bytes() == config_bytes
        with pytest.raises(RuntimeOwnershipError):
            acquire_runtime_ownership(database)
    finally:
        runtime.close()


def test_busy_jobs_refuse_delete_without_cancelling_or_creating_new_job(tmp_path):
    runtime, maintenance, _, database = owned(tmp_path)
    started, finish = Event(), Event()
    def work():
        started.set()
        assert finish.wait(5)
        return {'synthetic': True}
    try:
        job = runtime.jobs.submit(project_id='project-a', kind='test', actor='test', request_id='busy', operation=work)
        assert started.wait(2)
        before = _rows(database)
        with pytest.raises(MaintenanceUnavailable, match='maintenance_jobs_busy'):
            delete(maintenance)
        assert maintenance.status()['state'] == 'ready'
        assert _rows(database) == before
        finish.set()
        runtime.jobs.wait('project-a', job.job_id, timeout=2)
    finally:
        finish.set()
        runtime.close()


def test_actual_reader_is_counted_until_it_settles(tmp_path):
    runtime, maintenance, _, database = owned(tmp_path)
    started, finish = Event(), Event()
    def read():
        with maintenance.admission():
            started.set()
            finish.wait(5)
    worker = Thread(target=read)
    try:
        worker.start()
        assert started.wait(2)
        before = _rows(database)
        with pytest.raises(MaintenanceUnavailable, match='maintenance_requests_busy'):
            delete(maintenance)
        assert maintenance.status()['state'] == 'ready'
        assert _rows(database) == before
        finish.set()
        worker.join(2)
        assert delete(maintenance)['deletion']['deletion_state'] == 'scrubbed'
    finally:
        finish.set()
        worker.join(2)
        runtime.close()


def test_committed_delete_reports_incomplete_scrub_and_resumes_without_journal(tmp_path):
    runtime, maintenance, _, database = owned(tmp_path)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == 'wal'
    reader = sqlite3.connect(database)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM projects").fetchall()
    try:
        result = delete(maintenance)
        assert result['deletion']['project_effect_state'] == 'applied', result
        assert result['deletion']['deletion_state'] == 'ledger_deleted'
        assert result['maintenance']['state'] == 'ready'
        assert not database.with_name(database.name + '.project-purge').exists()
        assert maintenance.read(runtime.ledger.traceability_matrix, 'project-b') == []
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT project_id FROM projects").fetchall() == [('project-b',)]
    finally:
        reader.close()
        runtime.close()


def test_existing_unfinished_native_intent_retains_startup_fence(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    deletion_id = str(uuid4())
    _, code = _call(config, 'prepare', deletion_id)
    assert code == 0
    path = database.with_name(database.name + '.project-purge') / (deletion_id + '.json')
    journal = json.loads(path.read_text())
    journal['stage'] = 'deleting'
    content = json.dumps(journal)
    path.write_text(content)
    runtime, maintenance = start_owned(tmp_path, config, database)
    try:
        assert maintenance.status()['state'] == 'recovery_required'
        assert maintenance.status()['deletion_id'] == deletion_id
        with pytest.raises(MaintenanceUnavailable):
            delete(maintenance, 'project-b')
        assert path.read_text() == content
    finally:
        runtime.close()


def test_finished_native_journal_does_not_turn_later_config_changes_into_recovery(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    deletion_id = str(uuid4())
    prepared, code = _call(config, 'prepare', deletion_id)
    assert code == 0
    result, code = _call(config, 'delete', deletion_id, fingerprint=prepared['prepared_fingerprint'])
    assert code == 0 and result['deletion_state'] == 'scrubbed'
    config.write_text(config.read_text() + '\n# A later legitimate configuration edit.\n')
    runtime, maintenance = start_owned(tmp_path, config, database)
    try:
        assert maintenance.status()['state'] == 'ready'
        assert maintenance.read(runtime.ledger.traceability_matrix, 'project-b') == []
    finally:
        runtime.close()


def test_malformed_native_journal_holds_startup_without_rewriting_it(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    deletion_id = str(uuid4())
    _, code = _call(config, 'prepare', deletion_id)
    assert code == 0
    path = database.with_name(database.name + '.project-purge') / (deletion_id + '.json')
    original = json.loads(path.read_text())
    malformed = [
        {},
        {**original, 'project_id': []},
        {**original, 'deletion_id': 'not-a-uuid'},
        {**original, 'config_identity': None},
        {**original, 'config_identity': {**original['config_identity'], 'path': 'relative.yaml'}},
        {**original, 'config_identity': {**original['config_identity'], 'sha256': 'invalid'}},
        {**original, 'database_identity': {**original['database_identity'], 'inode': True}},
    ]
    runtime, _ = start_owned(tmp_path, config, database)
    try:
        for journal in malformed:
            content = json.dumps(journal)
            path.write_text(content)
            reopened = DashboardMaintenance(runtime, config)
            assert reopened.status()['state'] == 'recovery_required'
            with pytest.raises(MaintenanceUnavailable):
                reopened.read(runtime.ledger.traceability_matrix, 'project-b')
            with pytest.raises(MaintenanceUnavailable):
                delete(reopened, 'project-b')
            assert path.read_text() == content
    finally:
        runtime.close()
