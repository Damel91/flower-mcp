"""Browser routes need their own local session and request protections."""
import asyncio
from uuid import uuid4

from starlette.testclient import TestClient

from flow_of_work_mcp.dashboard_http import DashboardHTTP
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership
from flow_of_work_mcp.server import create_app
from tests.test_native_project_purge import _fixture


def fixture(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    lease = acquire_runtime_ownership(database)
    runtime = build_runtime(database_path=database, import_root=tmp_path, runtime_ownership=lease)
    dashboard = DashboardHTTP(runtime, config, port=18760)
    mcp = create_app(runtime, host='127.0.0.1', port=18760, dashboard=dashboard)
    return runtime, dashboard, mcp


def activate(client, dashboard):
    token = dashboard.activation_url('127.0.0.1').split('#connect=')[1]
    response = client.post('/dashboard/api/session', json={'token': token}, headers={'Origin': 'http://127.0.0.1:18760'})
    assert response.status_code == 200
    return response.json()['result']['csrf_token']


def test_authentication_origin_and_csrf_protect_browser_data_and_commands(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            assert client.get('/dashboard/api/projects').status_code == 401
            assert client.get('/dashboard/api/session').json()['result'] == {'authenticated': False}
            token = dashboard.activation_url('127.0.0.1').split('#connect=')[1]
            assert client.post('/dashboard/api/session', json={'token': token}).status_code == 403
            assert client.get('/dashboard/api/session', headers={'Origin': 'null'}).status_code == 403
            assert client.get('/dashboard/api/session', headers={'Host': 'evil.example:18760'}).status_code == 403
            csrf = activate(client, dashboard)
            assert client.get('/dashboard/api/projects').status_code == 200
            assert client.get('/dashboard/api/projects', headers={'Origin': 'https://evil.example'}).status_code == 403
            endpoint = '/dashboard/api/projects/project-a/deletion/prepare'
            body = {'deletion_id': str(uuid4())}
            assert client.post(endpoint, json=body, headers={'Origin': 'http://127.0.0.1:18760'}).status_code == 403
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': csrf}
            prepared = client.post(endpoint, json=body, headers=headers)
            assert prepared.status_code == 200
            assert prepared.json()['result']['deletion']['deletion_state'] == 'prepared'
            assert client.get('/dashboard/api/projects').status_code == 503
            assert client.get('/dashboard/api/status').json()['result']['state'] == 'maintenance'
            cancelled = client.post('/dashboard/api/projects/project-a/deletion/cancel', json=body, headers=headers)
            assert cancelled.json()['result']['maintenance']['state'] == 'ready'
            assert client.get('/dashboard/api/projects').status_code == 200
            assert client.post('/dashboard/api/session', json={'token': token}, headers=headers).status_code == 401
    finally:
        runtime.close()


def test_remote_peer_is_rejected_even_with_local_host(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('192.0.2.10', 12345)) as client:
            assert client.get('/dashboard/api/session').status_code == 403
    finally:
        runtime.close()


def test_expired_activation_closed_fields_and_bounded_body(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            token = dashboard.activation_url('127.0.0.1').split('#connect=')[1]
            dashboard._activation_until = 0
            headers = {'Origin': 'http://127.0.0.1:18760'}
            assert client.post('/dashboard/api/session', json={'token': token}, headers=headers).status_code == 401
            assert client.post('/dashboard/api/session', json={'token': 'x' * 17000}, headers=headers).status_code == 400
            assert client.post('/dashboard/api/session', json={'token': token, 'project': 'other'}, headers=headers).status_code == 400
            assert client.get('/dashboard/assets/../config.yaml').status_code != 200
    finally:
        runtime.close()


def test_dashboard_does_not_change_the_public_mcp_catalog(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        with_dashboard = asyncio.run(mcp.list_tools())
        plain = asyncio.run(create_app(runtime).list_tools())
        assert len(with_dashboard) == 37
        assert [tool.model_dump() for tool in with_dashboard] == [tool.model_dump() for tool in plain]
    finally:
        runtime.close()


def test_missing_project_read_returns_specific_not_found_recovery(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            activate(client, dashboard)
            response = client.get('/dashboard/api/projects/no-longer-present/sections/overview')
            assert response.status_code == 404
            assert response.json()['reason'] == 'dashboard_project_not_found'
            assert 'project list' in response.json()['message']
            assert 'maintenance intent' not in response.json()['message']
    finally:
        runtime.close()


def test_oversized_evidence_read_returns_specific_limit_rejection(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        generation = runtime.ledger.record_artifact_generation(ArtifactGeneration(
            project_id='project-a', profile_id='owned-large-evidence', profile_version='1',
            source_ledger_version=runtime.ledger.ledger_version('project-a'), generated_at='2026-11-04T00:00:00Z',
            artifacts=(ArtifactDraft(ArtifactKind.SRS, 'x' * (2 * 1024 * 1024 + 1), ()),)), actor='test')
        with runtime.ledger._read_connection() as connection:
            artifact_id = connection.execute('SELECT artifact_id FROM generated_artifacts WHERE generation_id=?',
                                             (generation.generation_id,)).fetchone()[0]
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            activate(client, dashboard)
            response = client.get(f'/dashboard/api/projects/project-a/evidence/artifact/{artifact_id}')
            assert response.status_code == 413
            assert response.json()['reason'] == 'dashboard_evidence_too_large'
            assert '2 MiB' in response.json()['message']
            assert 'content' not in response.json()
    finally:
        runtime.close()
