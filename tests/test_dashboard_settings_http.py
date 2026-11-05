"""Settings HTTP admission and draft behavior with an isolated owned profile."""
import os
from uuid import uuid4

import pytest

from starlette.testclient import TestClient

from tests.test_dashboard_http import fixture, request_csrf


@pytest.mark.skipif(os.name == 'posix' and os.geteuid() == 0,
                    reason='Settings require a normal local owner account.')
def test_settings_routes_protect_and_stage_the_current_profile(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    config = dashboard.maintenance.config_path
    original = config.read_bytes()
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760', client=('127.0.0.1', 12345)) as client:
            settings = '/dashboard/api/settings'
            assert client.get(settings).status_code == 401
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': request_csrf(client)}
            assert client.get(settings, headers={'Origin': 'https://example.test'}).status_code == 403
            response = client.get(settings)
            assert response.status_code == 200
            snapshot = response.json()['result']
            assert snapshot['draft'] is None
            assert {field['section'] for field in snapshot['fields']} == {'basic', 'advanced'}
            assert all(field['key'] != 'runtime.database_path' for field in snapshot['fields'])
            body = {'revision': snapshot['revision'], 'draft_id': None,
                    'changes': {'logging.level': 'WARNING'}}
            assert client.post(settings + '/draft', json=body, headers={'Origin': headers['Origin']}).status_code == 403
            response = client.post(settings + '/draft', json=body, headers=headers)
            assert response.status_code == 200
            draft = response.json()['result']['draft']
            assert draft['state'] == 'pending'
            assert draft['changes'] == body['changes']
            assert config.read_bytes() == original
            assert client.post(settings + '/draft', json=body, headers=headers).status_code == 409
            deletion = '/dashboard/api/projects/project-a/deletion/'
            intent = {'deletion_id': str(uuid4())}
            assert client.post(deletion + 'prepare', json=intent, headers=headers).status_code == 200
            assert client.get(settings).status_code == 503
            assert client.post(settings + '/draft', json=body, headers=headers).status_code == 503
            assert client.post(deletion + 'cancel', json=intent, headers=headers).status_code == 200
            discarded = client.post(settings + '/draft',
                json={**body, 'draft_id': draft['id'], 'changes': {}}, headers=headers)
            assert discarded.status_code == 200
            assert discarded.json()['result']['draft'] is None
            assert config.read_bytes() == original
    finally:
        runtime.close()
