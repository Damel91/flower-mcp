"""HTTP owner-authority contracts using a deterministic native seam, not OS acceptance."""
import asyncio
from uuid import uuid4
from types import SimpleNamespace

from starlette.testclient import TestClient

from flow_of_work_mcp.dashboard_http import DashboardHTTP
from flow_of_work_mcp.dashboard_auth import DashboardAuth
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership
from flow_of_work_mcp.server import create_app
from tests.test_native_project_purge import _fixture, _rows


def fixture(tmp_path):
    config, database = _fixture(tmp_path.resolve())
    lease = acquire_runtime_ownership(database)
    runtime = build_runtime(database_path=database, import_root=tmp_path, runtime_ownership=lease)
    dashboard = DashboardHTTP(runtime, config, port=18760)
    dashboard.auth.close()
    class Verifier:
        def capability(self, owner):
            return {'availability': 'ready', 'reason': None}
        def __call__(self, owner, username, password):
            if username != 'synthetic-owner' or password != 'synthetic-fixture-only':
                return {'outcome': 'denied', 'identity': None, 'reason': 'credentials_denied'}
            return {'outcome': 'verified', 'identity': {**owner, 'local': True}, 'reason': None}
    dashboard.auth = DashboardAuth(config, database, port=18760,
        binding=SimpleNamespace(owner={'kind': 'uid', 'value': '12345'}, check=lambda: None),
        verifier=Verifier())
    mcp = create_app(runtime, host='127.0.0.1', port=18760, dashboard=dashboard)
    return runtime, dashboard, mcp


def request_csrf(client):
    response = client.get('/dashboard/api/auth')
    assert response.status_code == 200
    state = response.json()['result']
    if state['authenticated']:
        return state['csrf_token']
    response = client.post('/dashboard/api/login',
        json={'username': 'synthetic-owner', 'password': 'synthetic-fixture-only'},
        headers={'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': state['csrf_token']})
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/dashboard' in cookie
    assert 'Max-Age' not in cookie and 'Expires' not in cookie and 'Domain=' not in cookie
    return response.json()['result']['csrf_token']


def test_owner_login_protects_all_private_status_reads_and_administration(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        assert dashboard.local_url('127.0.0.1') == 'http://127.0.0.1:18760/dashboard'
        assert dashboard.local_url('::1') == 'http://[::1]:18760/dashboard'
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            assert client.get('/dashboard/api/projects').status_code == 401
            assert client.get('/dashboard/api/status').status_code == 401
            state = client.get('/dashboard/api/auth').json()['result']
            assert set(state) == {'authenticated', 'availability', 'reason', 'csrf_token', 'instance_id'}
            assert not state['authenticated'] and state['availability'] == 'ready'
            assert not client.cookies
            assert client.get('/dashboard/api/session').status_code == 404
            assert client.get('/dashboard/api/auth', headers={'Origin': 'null'}).status_code == 403
            assert client.get('/dashboard/api/auth', headers={'Host': 'evil.example:18760'}).status_code == 403
            csrf = request_csrf(client)
            assert client.get('/dashboard/api/projects').status_code == 200
            assert client.get('/dashboard/api/projects', headers={'Origin': 'https://evil.example'}).status_code == 403
            endpoint = '/dashboard/api/projects/project-a/deletion/prepare'
            body = {'deletion_id': str(uuid4())}
            assert client.post(endpoint, json=body).status_code == 403
            assert client.post(endpoint, json=body, headers={'Origin': 'http://127.0.0.1:18760'}).status_code == 403
            assert client.post(endpoint, json=body, headers={'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': 'wrong'}).status_code == 403
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': csrf}
            prepared = client.post(endpoint, json=body, headers=headers)
            assert prepared.status_code == 200
            assert prepared.json()['result']['deletion']['deletion_state'] == 'prepared'
            assert client.get('/dashboard/api/projects').status_code == 503
            assert client.get('/dashboard/api/status').json()['result']['state'] == 'maintenance'
            cancelled = client.post('/dashboard/api/projects/project-a/deletion/cancel', json=body, headers=headers)
            assert cancelled.json()['result']['maintenance']['state'] == 'ready'
            assert client.get('/dashboard/api/projects').status_code == 200
            assert client.post('/dashboard/api/logout', json={}, headers=headers).status_code == 200
            assert client.get('/dashboard/api/status').status_code == 401
            assert client.get('/dashboard/api/projects').status_code == 401
            request_csrf(client)
            assert client.get('/dashboard/api/projects').status_code == 200
    finally:
        runtime.close()


def test_final_delete_requires_fresh_owner_password_and_preserves_prepared_intent_on_refusal(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    database = runtime.ledger.database_path
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': request_csrf(client)}
            endpoint = '/dashboard/api/projects/project-a/deletion/'
            intent = {'deletion_id': str(uuid4())}
            prepared = client.post(endpoint + 'prepare', json=intent, headers=headers)
            assert prepared.status_code == 200
            fingerprint = prepared.json()['result']['deletion']['prepared_fingerprint']
            body = {**intent, 'expected_fingerprint': fingerprint, 'confirm_project_id': 'project-a',
                    'host_quiescence_ref': 'synthetic-fixture:idle'}
            before = _rows(database)
            for supplied, status, reason in (
                ({}, 400, 'dashboard_delete_password_required'),
                ({'password': 'wrong-synthetic'}, 403, 'dashboard_delete_password_denied'),
            ):
                refused = client.post(endpoint + 'delete', json={**body, **supplied}, headers=headers)
                assert refused.status_code == status
                assert refused.json()['reason'] == reason
                assert 'wrong-synthetic' not in refused.text
                assert _rows(database) == before
                inspected = client.post(endpoint + 'inspect', json=intent, headers=headers)
                assert inspected.json()['result']['deletion']['deletion_state'] == 'prepared'
            deleted = client.post(endpoint + 'delete',
                json={**body, 'password': 'synthetic-fixture-only'}, headers=headers)
            assert deleted.status_code == 200
            assert deleted.json()['result']['deletion']['deletion_state'] == 'scrubbed'
            assert 'synthetic-fixture-only' not in deleted.text
            journal = database.with_name(database.name + '.project-purge') / (intent['deletion_id'] + '.json')
            assert 'synthetic-fixture-only' not in journal.read_text()
            assert client.post(endpoint + 'delete', json=body, headers=headers).status_code == 400
            assert client.get('/dashboard/api/status').json()['result']['state'] == 'ready'
    finally:
        runtime.close()


def test_new_browser_reauthenticates_without_activation_or_server_restart(tmp_path):
    runtime, dashboard, _ = fixture(tmp_path)
    try:
        for _ in range(2):
            fresh_app = create_app(runtime, host='127.0.0.1', port=18760, dashboard=dashboard)
            with TestClient(fresh_app.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
                assert client.get('/dashboard').status_code == 200
                assert client.get('/dashboard/api/projects').status_code == 401
                assert request_csrf(client)
                assert client.get('/dashboard/api/projects').status_code == 200
    finally:
        runtime.close()


def test_remote_peer_is_rejected_even_with_local_host(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('192.0.2.10', 12345)) as client:
            assert client.get('/dashboard/api/auth').status_code == 403
    finally:
        runtime.close()


def test_administration_keeps_closed_fields_and_bounded_body(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': request_csrf(client)}
            endpoint = '/dashboard/api/projects/project-a/deletion/prepare'
            assert client.post(endpoint, json={'deletion_id': 'x' * 17000}, headers=headers).status_code == 400
            assert client.post(endpoint, json={'deletion_id': str(uuid4()), 'project': 'other'}, headers=headers).status_code == 400
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


def test_login_rejects_bad_credentials_and_nonclosed_json_without_private_disclosure(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            state = client.get('/dashboard/api/auth').json()['result']
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': state['csrf_token'], 'Content-Type': 'application/json'}
            for username in ('synthetic-owner', 'different-owner'):
                response = client.post('/dashboard/api/login', json={'username': username, 'password': 'wrong-synthetic'}, headers=headers)
                assert response.status_code == 401
                assert response.json()['reason'] == 'dashboard_login_denied'
                assert 'wrong-synthetic' not in response.text
                assert 'set-cookie' not in response.headers
            for body in ('{"username":"a","password":"b","password":"c"}',
                         '{"username":"a","password":NaN}',
                         '{"username":"a","password":"b","owner":"injected"}'):
                assert client.post('/dashboard/api/login', content=body, headers=headers).status_code == 400
            assert client.get('/dashboard/api/status').status_code == 401
    finally:
        runtime.close()


def test_missing_project_read_returns_specific_not_found_recovery(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            request_csrf(client)
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
            request_csrf(client)
            response = client.get(f'/dashboard/api/projects/project-a/evidence/artifact/{artifact_id}')
            assert response.status_code == 413
            assert response.json()['reason'] == 'dashboard_evidence_too_large'
            assert '2 MiB' in response.json()['message']
            assert 'content' not in response.json()
    finally:
        runtime.close()
