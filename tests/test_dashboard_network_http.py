"""Verify persistent LAN settings and the wildcard HTTPS ingress authority."""
from types import SimpleNamespace
from uuid import uuid4

from starlette.testclient import TestClient

from flow_of_work_mcp.dashboard_network import DashboardNetworkSettings
from tests.test_dashboard_http import fixture, request_csrf


LOCAL = 'http://127.0.0.1:18760'
NETWORK = '/dashboard/api/network'


def test_dashboard_saves_profile_network_settings_and_rejects_stale_writes(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    config = dashboard.maintenance.config_path
    original_config = config.read_bytes()
    try:
        with TestClient(mcp.streamable_http_app(), base_url=LOCAL, client=('127.0.0.1', 1234)) as client:
            assert client.get(NETWORK).status_code == 401
            csrf = request_csrf(client)
            first = client.get(NETWORK).json()['result']
            assert first['enabled'] is False and first['port'] == 8443
            assert first['active'] == {'mode': 'local', 'port': None, 'cli_override': False}
            update = {'revision': first['revision'], 'enabled': True, 'port': 18443}
            assert client.post(NETWORK, json=update).status_code == 403
            assert client.post(NETWORK, json=update, headers={'Origin': LOCAL, 'X-Flower-CSRF': 'bad'}).status_code == 403
            headers = {'Origin': LOCAL, 'X-Flower-CSRF': csrf}
            assert client.post(NETWORK, json={**update, 'port': True}, headers=headers).status_code == 400
            collision = client.post(NETWORK, json={**update, 'port': 18760}, headers=headers)
            assert collision.status_code == 400 and collision.json()['reason'] == 'dashboard_network_port_conflict'
            saved = client.post(NETWORK, json=update, headers=headers)
            assert saved.status_code == 200
            view = saved.json()['result']
            assert view['active']['mode'] == 'local'
            assert view['enabled'] is True and view['revision'] != first['revision']
            assert DashboardNetworkSettings(config).snapshot() == {
                'revision': view['revision'], 'enabled': True, 'port': 18443,
            }
            assert DashboardNetworkSettings(config.with_name('another.yaml')).snapshot()['enabled'] is False
            assert config.read_bytes() == original_config
            stale = client.post(NETWORK, json=update, headers=headers)
            assert stale.status_code == 409 and stale.json()['reason'] == 'dashboard_network_changed'
            endpoint = '/dashboard/api/projects/project-a/deletion/'
            body = {'deletion_id': str(uuid4())}
            assert client.post(endpoint + 'prepare', json=body, headers=headers).status_code == 200
            disable = {'revision': view['revision'], 'enabled': False, 'port': view['port']}
            assert client.post(NETWORK, json=disable, headers=headers).status_code == 503
            assert client.post(endpoint + 'cancel', json=body, headers=headers).status_code == 200
            assert client.post(NETWORK, json=disable, headers=headers).status_code == 200
            assert DashboardNetworkSettings(config).snapshot()['enabled'] is False
    finally:
        dashboard.close()
        runtime.close()


def test_untrusted_persisted_settings_fail_closed(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url=LOCAL, client=('127.0.0.1', 1234)) as client:
            csrf = request_csrf(client)
            original = client.get(NETWORK).json()['result']
            request = {'revision': original['revision'], 'enabled': True, 'port': 8443}
            headers = {'Origin': LOCAL, 'X-Flower-CSRF': csrf}
            assert client.post(NETWORK, json=request, headers=headers).status_code == 200
            # A private file containing ambiguous JSON is still invalid.
            bad = b'{"revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","enabled":false,"enabled":true,"port":8443}'
            dashboard.network.path.write_bytes(bad)
            for response in (client.get(NETWORK), client.post(NETWORK, json=request, headers=headers)):
                assert response.status_code == 409
                assert response.json()['reason'] == 'dashboard_network_state_invalid'
            assert dashboard.network.path.read_bytes() == bad
    finally:
        dashboard.close()
        runtime.close()


def test_wildcard_authority_is_the_actual_tls_socket_destination(tmp_path):
    runtime, dashboard, _ = fixture(tmp_path)
    try:
        tls = SimpleNamespace(
            bind='0.0.0.0', port=8443, names=('192.0.2.1', '192.0.2.2'), hostnames=('flower.local',),
        )
        app = dashboard.remote_dashboard_app(tls)
        destination = 'https://192.0.2.1:8443'
        with TestClient(app, base_url=destination, client=('192.0.2.99', 4321)) as client:
            assert client.get('/dashboard').status_code == 200
            landing = client.get('/', follow_redirects=False)
            assert landing.status_code == 307 and landing.headers['location'] == '/dashboard'
            assert client.get('/', headers={'Host': 'unexpected.test:8443'}, follow_redirects=False).status_code == 403
            assert client.get('/mcp').status_code == 404
            assert client.get(NETWORK).status_code == 401
            assert client.get('/dashboard', headers={'Host': '192.0.2.2:8443'}).status_code == 403
            assert client.get('/dashboard', headers={'Host': '0.0.0.0:8443'}).status_code == 403
            assert client.get('/dashboard', headers={'Host': '192.0.2.1:8444'}).status_code == 403
            assert client.get('/dashboard', headers={'Origin': 'https://192.0.2.2:8443'}).status_code == 403
            hostname = 'flower.local:8443'
            assert client.get('/dashboard', headers={'Host': hostname}).status_code == 200
            assert client.get('/dashboard', headers={'Host': hostname, 'Origin': destination}).status_code == 403
            assert client.get('/dashboard', headers={'Host': hostname, 'Origin': 'https://' + hostname}).status_code == 200
            assert client.get('/dashboard', headers=[('Origin', destination), ('Origin', destination)]).status_code == 403
            assert client.get('http://192.0.2.1:8443/dashboard',
                              headers={'X-Forwarded-Proto': 'https'}).status_code == 403
            assert client.post(NETWORK, json={}, headers={'Origin': destination}).status_code == 401
            assert client.post(NETWORK, json={}).status_code == 403
            tls.names = ('192.0.2.2',)
            assert client.get('/dashboard').status_code == 403
            assert client.get('https://192.0.2.2:8443/dashboard').status_code == 200
    finally:
        dashboard.close()
        runtime.close()
