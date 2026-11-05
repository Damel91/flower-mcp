"""Authenticated dashboard archive delivery; native login has its own campaign."""
from __future__ import annotations

import asyncio
from io import BytesIO
import json
from threading import Event
from uuid import uuid4
import zipfile

import pytest
from starlette.testclient import TestClient

from flow_of_work_mcp import dashboard_http
from tests.test_dashboard_http import fixture, request_csrf
from tests.test_native_project_purge import _rows


_ORIGIN = 'http://127.0.0.1:18760'
_ARCHIVE = '/dashboard/api/archive'
_BACKUPS = '/dashboard/api/backups'


@pytest.fixture
def browser(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url=_ORIGIN, client=('127.0.0.1', 12345)) as client:
            yield runtime, dashboard, client
    finally:
        dashboard.close()
        runtime.close()


@pytest.fixture
def workspaces(monkeypatch):
    seen = []
    original = dashboard_http._ArchiveLifetime.temporary_archive

    def capture(lifetime):
        path = original(lifetime)
        seen.append(path.parent)
        return path

    monkeypatch.setattr(dashboard_http._ArchiveLifetime, 'temporary_archive', capture)
    return seen


def _headers(client):
    return {'Origin': _ORIGIN, 'X-Flower-CSRF': request_csrf(client)}


def _manifest(content):
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert archive.namelist() == ['manifest.json', 'ledger.sqlite3']
        assert archive.testzip() is None
        return json.loads(archive.read('manifest.json'))


def test_transient_full_and_project_archives_are_streamed_without_source_mutation(browser, workspaces):
    runtime, dashboard, client = browser
    headers = _headers(client)
    before = _rows(runtime.ledger.database_path)
    for project, kind, file in ((None, 'backup', 'flower-backup.flower.zip'),
                                ('project-a', 'project', 'flower-project.flower.zip')):
        response = client.post(_ARCHIVE, json={'project_id': project}, headers=headers)
        assert response.status_code == 200, response.text[:350] if response.status_code != 200 else ''
        assert response.headers['content-type'] == 'application/zip'
        assert response.headers['content-disposition'] == f'attachment; filename="{file}"'
        assert response.headers['cache-control'] == 'no-store'
        assert int(response.headers['content-length']) == len(response.content)
        manifest = _manifest(response.content)
        assert manifest['kind'] == kind and manifest['project_id'] == project
        assert not dashboard._archive_gate.locked()
    assert len(workspaces) == 2 and all(not folder.exists() for folder in workspaces)
    assert _rows(runtime.ledger.database_path) == before
    assert not dashboard.backups.directory.exists()


def test_archive_request_gates_and_closed_fields_do_not_touch_private_files(browser, workspaces):
    _, dashboard, client = browser
    body = {'project_id': None}
    assert client.post(_ARCHIVE, json=body, headers={'Origin': _ORIGIN}).status_code == 401
    assert client.get(_BACKUPS).status_code == 401
    headers = _headers(client)
    for invalid_headers in (
        {'X-Flower-CSRF': headers['X-Flower-CSRF']},
        {**headers, 'Origin': 'https://other.invalid'},
        {**headers, 'Host': 'other.invalid:18760'},
        {**headers, 'X-Flower-CSRF': 'incorrect'},
    ):
        assert client.post(_ARCHIVE, json=body, headers=invalid_headers).status_code == 403
    assert client.get(_ARCHIVE).status_code == 404
    for invalid in ({}, {**body, 'destination': '/untrusted/path'}, {'project_id': False}, {'project_id': '../hidden'}):
        response = client.post(_ARCHIVE, json=invalid, headers=headers)
        assert response.status_code == 400 and response.json()['reason'] == 'dashboard_input_invalid'
    assert client.post(_BACKUPS, json={'path': '/untrusted/path'}, headers=headers).status_code == 400
    assert client.post(_BACKUPS + '/bad-id/download', json={}, headers=headers).status_code == 400
    assert client.post(_ARCHIVE, content='{"project_id":null,"project_id":"project-a"}',
        headers={**headers, 'Content-Type': 'application/json'}).status_code == 400
    assert not workspaces and not dashboard.backups.directory.exists()


def test_archives_respect_maintenance_and_serialize_downloads(browser, workspaces):
    _, dashboard, client = browser
    headers = _headers(client)
    deletion = '/dashboard/api/projects/project-a/deletion/'
    intent = {'deletion_id': str(uuid4())}
    assert client.post(deletion + 'prepare', json=intent, headers=headers).status_code == 200
    for endpoint, body in ((_ARCHIVE, {'project_id': None}), (_BACKUPS, {})):
        response = client.post(endpoint, json=body, headers=headers)
        assert response.status_code == 503 and response.json()['reason'] == 'server_maintenance'
    assert client.get(_BACKUPS).status_code == 503
    assert not workspaces and not dashboard.backups.directory.exists()
    assert client.post(deletion + 'cancel', json=intent, headers=headers).status_code == 200
    assert dashboard._archive_gate.acquire(blocking=False)
    try:
        for endpoint, body in ((_ARCHIVE, {'project_id': None}), (_BACKUPS, {})):
            response = client.post(endpoint, json=body, headers=headers)
            assert response.status_code == 409 and response.json()['reason'] == 'dashboard_archive_busy'
        assert client.get(_BACKUPS).json()['result'] == {'backups': []}
    finally:
        dashboard._archive_gate.release()
    assert not workspaces and not dashboard.backups.directory.exists()


def test_retained_backup_download_uses_private_handle_and_delete_reauthenticates(browser):
    runtime, dashboard, client = browser
    headers = _headers(client)
    before = _rows(runtime.ledger.database_path)
    assert client.get(_BACKUPS).json()['result'] == {'backups': []}
    assert not dashboard.backups.directory.exists()
    created = client.post(_BACKUPS, json={}, headers=headers)
    assert created.status_code == 201, created.text
    record = created.json()['result']
    assert set(record) == {'id', 'created_at', 'size'}
    assert client.get(_BACKUPS).json()['result'] == {'backups': [record]}
    endpoint = _BACKUPS + '/' + record['id']
    downloaded = client.post(endpoint + '/download', json={}, headers=headers)
    assert downloaded.status_code == 200
    assert _manifest(downloaded.content)['kind'] == 'backup'
    assert len(downloaded.content) == record['size']
    assert not dashboard._archive_gate.locked()
    denied = client.post(endpoint + '/delete', json={'password': 'incorrect-synthetic'}, headers=headers)
    assert denied.status_code == 403 and denied.json()['reason'] == 'dashboard_delete_password_denied'
    assert 'incorrect-synthetic' not in denied.text
    assert client.get(_BACKUPS).json()['result'] == {'backups': [record]}
    removed = client.post(endpoint + '/delete', json={'password': 'synthetic-fixture-only'}, headers=headers)
    assert removed.status_code == 200 and removed.json()['result'] == {'deleted': True}
    assert client.get(_BACKUPS).json()['result'] == {'backups': []}
    gone = client.post(endpoint + '/download', json={}, headers=headers)
    assert gone.status_code == 404 and gone.json()['reason'] == 'archive_backup_not_found'
    assert _rows(runtime.ledger.database_path) == before


def test_archive_rechecks_session_after_generation_and_disposes_private_file(browser, workspaces, monkeypatch):
    _, dashboard, client = browser
    headers = _headers(client)
    original = dashboard_http.create_archive
    cookie = client.cookies.get(dashboard.auth.cookie_name)

    def revoke_after_generation(*args, **kwargs):
        result = original(*args, **kwargs)
        dashboard.auth.logout(cookie, headers['X-Flower-CSRF'])
        return result

    monkeypatch.setattr(dashboard_http, 'create_archive', revoke_after_generation)
    response = client.post(_ARCHIVE, json={'project_id': None}, headers=headers)
    assert response.status_code == 401 and response.json()['reason'] == 'dashboard_session_required'
    assert len(workspaces) == 1 and not workspaces[0].exists()
    assert not dashboard._archive_gate.locked()


def test_missing_project_is_json_and_removes_temporary_workspace(browser, workspaces):
    _, dashboard, client = browser
    response = client.post(_ARCHIVE, json={'project_id': 'missing-project'}, headers=_headers(client))
    assert response.status_code == 404 and response.json()['reason'] == 'archive_project_not_found'
    assert 'content-disposition' not in response.headers
    assert len(workspaces) == 1 and not workspaces[0].exists()
    assert not dashboard._archive_gate.locked()


def test_archive_cleanup_waits_for_a_cancelled_request_worker_to_settle(browser, workspaces, monkeypatch):
    _, dashboard, client = browser
    headers = _headers(client)
    cookie = client.cookies.get(dashboard.auth.cookie_name)
    generating, release, cleaned = Event(), Event(), Event()
    original = dashboard_http.create_archive
    dispose = dashboard_http._ArchiveLifetime._dispose

    def delayed(*args, **kwargs):
        generating.set()
        if not release.wait(5):
            raise RuntimeError('test generation did not resume')
        return original(*args, **kwargs)

    def track_dispose(lifetime):
        try:
            return dispose(lifetime)
        finally:
            cleaned.set()

    monkeypatch.setattr(dashboard_http, 'create_archive', delayed)
    monkeypatch.setattr(dashboard_http._ArchiveLifetime, '_dispose', track_dispose)

    async def simulate():
        async def unused(*args):
            raise AssertionError('Cancelled archive must not publish a response.')

        scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}}
        task = asyncio.create_task(dashboard._send_archive(scope, unused, unused, cookie,
            headers['X-Flower-CSRF'], None, None))
        try:
            assert await asyncio.to_thread(generating.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert workspaces[0].exists() and dashboard._archive_gate.locked()
        finally:
            release.set()
        assert await asyncio.to_thread(cleaned.wait, 3)

    asyncio.run(simulate())
    assert not workspaces[0].exists() and not dashboard._archive_gate.locked()


def test_stream_disconnect_closes_retained_handle_without_removing_backup(browser, monkeypatch):
    _, dashboard, client = browser
    headers = _headers(client)
    cookie = client.cookies.get(dashboard.auth.cookie_name)
    created = client.post(_BACKUPS, json={}, headers=headers).json()['result']
    original = dashboard.backups.open
    handles = []

    def track_open(backup_id):
        stream = original(backup_id)
        handles.append(stream)
        return stream

    monkeypatch.setattr(dashboard.backups, 'open', track_open)

    async def simulate():
        async def receive():
            raise AssertionError('ASGI 2.4 stream detects send failures.')

        async def send(message):
            if message['type'] == 'http.response.body':
                raise OSError('synthetic disconnect')

        await dashboard._send_archive({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send,
            cookie, headers['X-Flower-CSRF'], None, created['id'])

    asyncio.run(simulate())
    assert len(handles) == 1 and handles[0].closed
    assert not dashboard._archive_gate.locked()
    assert client.get(_BACKUPS).json()['result'] == {'backups': [created]}
