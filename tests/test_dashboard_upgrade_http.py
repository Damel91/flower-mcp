"""Owner approval and receipt observation at the managed upgrade HTTP boundary."""
from uuid import uuid4

from starlette.testclient import TestClient

from flow_of_work_mcp.managed_service import ServiceError
from tests.test_dashboard_http import fixture, request_csrf


class UpgradeProbe:
    def __init__(self):
        self.preview_id = uuid4().hex
        self.previews = []
        self.applies = []
        self.operation = None

    def status(self):
        return {'available': self.operation is None, 'installed_version': '1.0.0',
                'operation': self.operation}

    def preview(self, version):
        self.previews.append(version)
        return {'id': self.preview_id, 'installed_version': '1.0.0', 'version': version}

    def apply(self, preview_id):
        if preview_id != self.preview_id or self.operation is not None:
            raise ServiceError('upgrade_preview_stale', 'Review the exact version again.')
        self.applies.append(preview_id)
        self.operation = {'id': preview_id, 'previous_version': '1.0.0', 'version': '1.0.1',
                          'phase': 'queued', 'backup_directory': '', 'reason': ''}
        return {'operation': self.operation}


def test_upgrade_http_requires_owner_csrf_exact_preview_and_fresh_password(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    probe = dashboard.upgrade = UpgradeProbe()
    endpoint = '/dashboard/api/upgrade'
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760',
                        client=('127.0.0.1', 12345)) as client:
            assert client.get(endpoint).status_code == 401
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': request_csrf(client)}
            assert client.get(endpoint, headers={'Origin': 'https://unrelated.test'}).status_code == 403
            assert client.get(endpoint).json()['result']['operation'] is None
            assert client.post(endpoint + '/preview', json={'version': '1.0.1'},
                               headers={'Origin': headers['Origin']}).status_code == 403
            assert client.post(endpoint + '/preview', json={'version': '1.0.1', 'path': '/tmp/not-an-asset'},
                               headers=headers).status_code == 400
            preview = client.post(endpoint + '/preview', json={'version': '1.0.1'}, headers=headers)
            assert preview.status_code == 200
            assert preview.json()['result'] == {'id': probe.preview_id, 'installed_version': '1.0.0', 'version': '1.0.1'}
            assert probe.previews == ['1.0.1']
            bad = client.post(endpoint + '/apply',
                              json={'id': probe.preview_id, 'password': 'wrong-synthetic'}, headers=headers)
            assert bad.status_code == 403
            assert bad.json()['reason'] == 'dashboard_upgrade_password_denied'
            assert 'wrong-synthetic' not in bad.text
            assert not probe.applies
            stale = client.post(endpoint + '/apply',
                                json={'id': 'stale', 'password': 'synthetic-fixture-only'}, headers=headers)
            assert stale.status_code == 409
            assert stale.json()['reason'] == 'upgrade_preview_stale'
            assert not probe.applies
            accepted = client.post(endpoint + '/apply',
                                   json={'id': probe.preview_id, 'password': 'synthetic-fixture-only'}, headers=headers)
            assert accepted.status_code == 202
            assert accepted.json()['result']['operation']['id'] == probe.preview_id
            assert 'synthetic-fixture-only' not in accepted.text
            assert probe.applies == [probe.preview_id]
            client.cookies.clear()
            assert client.get(endpoint).status_code == 401
            request_csrf(client)
            assert client.get(endpoint).json()['result']['operation']['phase'] == 'queued'
            probe.operation['reason'] = 'upgrade_worker_unconfirmed'
            observed = client.get(endpoint).json()['result']['operation']
            assert observed['id'] == probe.preview_id and observed['phase'] == 'queued'
            assert observed['reason'] == 'upgrade_worker_unconfirmed'
            assert probe.applies == [probe.preview_id]
    finally:
        runtime.close()


def test_upgrade_submission_respects_project_maintenance_without_hiding_receipt(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    probe = dashboard.upgrade = UpgradeProbe()
    endpoint = '/dashboard/api/upgrade'
    try:
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760',
                        client=('127.0.0.1', 12345)) as client:
            headers = {'Origin': 'http://127.0.0.1:18760', 'X-Flower-CSRF': request_csrf(client)}
            path = '/dashboard/api/projects/project-a/deletion/'
            body = {'deletion_id': str(uuid4())}
            assert client.post(path + 'prepare', json=body, headers=headers).status_code == 200
            assert client.get(endpoint).status_code == 200
            assert client.post(endpoint + '/preview', json={'version': '1.0.1'}, headers=headers).status_code == 503
            assert client.post(endpoint + '/apply',
                               json={'id': probe.preview_id, 'password': 'synthetic-fixture-only'},
                               headers=headers).status_code == 503
            assert not probe.previews and not probe.applies
            assert client.post(path + 'cancel', json=body, headers=headers).status_code == 200
    finally:
        runtime.close()
