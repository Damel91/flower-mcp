"""Authenticated archive uploads publish only a new, stopped Flower profile."""
import asyncio
from pathlib import Path
import sqlite3

import httpx
import pytest
from starlette.testclient import TestClient

from flow_of_work_mcp import dashboard_http, ledger_recovery
from flow_of_work_mcp.config import load_config
from tests.test_dashboard_http import fixture, request_csrf
from tests.test_native_project_purge import _rows


ORIGIN = 'http://127.0.0.1:18760'
RESTORE = '/dashboard/api/restore/'


@pytest.fixture
def restore_browser(tmp_path, monkeypatch, request):
    flower_home = tmp_path / 'isolated-home'
    monkeypatch.setenv('FLOWER_HOME', str(flower_home))
    if getattr(request, 'param', False):
        root = tmp_path / 'managed-root'
        active = root / 'profiles' / 'active'
    else:
        root = flower_home
        active = tmp_path / 'active'
    runtime, dashboard, mcp = fixture(active)
    try:
        with TestClient(mcp.streamable_http_app(), base_url=ORIGIN, client=('127.0.0.1', 12345)) as client:
            yield runtime, dashboard, client, root / 'profiles'
    finally:
        dashboard.close()
        runtime.close()


def upload_headers(client):
    return {'Origin': ORIGIN, 'X-Flower-CSRF': request_csrf(client), 'Content-Type': 'application/zip'}


def download(client, headers, project_id=None):
    response = client.post('/dashboard/api/archive', json={'project_id': project_id},
                           headers={key: value for key, value in headers.items() if key != 'Content-Type'})
    assert response.status_code == 200, response.text if response.status_code != 200 else ''
    return response.content


@pytest.mark.parametrize(
    ('restore_browser', 'kind', 'project_id', 'expected_projects'),
    [(False, 'backup', None, ['project-a', 'project-b']), (True, 'project', 'project-a', ['project-a'])],
    indirect=['restore_browser'],
)
def test_restore_publishes_a_new_profile_and_preserves_active_state(
    restore_browser, kind, project_id, expected_projects,
):
    runtime, dashboard, client, profiles = restore_browser
    headers = upload_headers(client)
    archive = download(client, headers, project_id)
    active_config = dashboard.maintenance.config_path
    config_bytes = active_config.read_bytes()
    before = _rows(runtime.ledger.database_path)

    response = client.post(RESTORE + 'restored', content=archive, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()['result'] == {'profile_name': 'restored', 'kind': kind, 'project_id': project_id}
    restored = profiles / 'restored'
    config = load_config(restored / 'flower.yaml')
    assert config.runtime.database_path == (restored / 'ledger.sqlite3').resolve()
    assert config.runtime.import_root == (restored / 'imports').resolve()
    with sqlite3.connect(config.runtime.database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ('ok',)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert [row[0] for row in connection.execute("SELECT project_id FROM projects ORDER BY project_id")] == expected_projects
    original_restored = _rows(config.runtime.database_path)
    repeated = client.post(RESTORE + 'restored', content=archive, headers=headers)
    assert repeated.status_code == 409 and repeated.json()['reason'] == 'archive_destination_exists'
    assert _rows(config.runtime.database_path) == original_restored
    assert _rows(runtime.ledger.database_path) == before
    assert active_config.read_bytes() == config_bytes
    assert client.get('/dashboard/api/projects').status_code == 200


def test_restore_rejects_invalid_upload_and_untrusted_requests(restore_browser, monkeypatch):
    runtime, dashboard, client, profiles = restore_browser
    before = _rows(runtime.ledger.database_path)
    anonymous = client.post(RESTORE + 'new-profile', content=b'broken', headers={
        'Origin': ORIGIN, 'Content-Type': 'application/zip',
    })
    assert anonymous.status_code == 401
    headers = upload_headers(client)
    for name, content, submitted, status, reason in (
        ('new-profile', b'broken', {**headers, 'Origin': 'https://elsewhere.invalid'}, 403, None),
        ('new-profile', b'broken', {**headers, 'X-Flower-CSRF': 'bad'}, 403, None),
        ('bad%20name', b'broken', headers, 400, 'archive_profile_name_invalid'),
        ('new-profile', b'broken', {**headers, 'Content-Type': 'application/json'}, 415, 'archive_restore_media_type'),
        ('new-profile', b'broken', headers, 400, 'archive_invalid'),
        ('new-profile', b'', headers, 400, 'archive_invalid'),
    ):
        response = client.post(RESTORE + name, content=content, headers=submitted)
        assert response.status_code == status, response.text
        if reason:
            assert response.json()['reason'] == reason

    monkeypatch.setattr(dashboard_http, 'MAX_ARCHIVE_BYTES', 32)
    for content in (b'x' * 33, iter([b'x' * 16, b'x' * 17])):
        response = client.post(RESTORE + 'new-profile', content=content, headers=headers)
        assert response.status_code == 413
        assert response.json()['reason'] == 'archive_size_exceeded'
    assert not (profiles / 'new-profile').exists()
    assert not dashboard._archive_gate.locked()
    assert _rows(runtime.ledger.database_path) == before


def test_restore_rechecks_session_after_validating_archive(restore_browser, monkeypatch):
    _, dashboard, client, profiles = restore_browser
    headers = upload_headers(client)
    archive = download(client, headers, 'project-a')
    cookie = client.cookies.get(dashboard.auth.cookie_name)
    original = ledger_recovery.read_archive

    def revoke_after_validation(archive_path: Path, database_path: Path):
        manifest = original(archive_path, database_path)
        dashboard.auth.logout(cookie, headers['X-Flower-CSRF'])
        return manifest

    monkeypatch.setattr(ledger_recovery, 'read_archive', revoke_after_validation)
    response = client.post(RESTORE + 'revoked', content=archive, headers=headers)
    assert response.status_code == 401 and response.json()['reason'] == 'dashboard_session_required'
    assert not (profiles / 'revoked').exists()
    assert not list(profiles.glob('.flower-restore-*'))
    assert not dashboard._archive_gate.locked()


def test_stalled_upload_times_out_and_releases_archive_gate(restore_browser, monkeypatch):
    _, dashboard, client, profiles = restore_browser
    headers = upload_headers(client)
    archive = download(client, headers, 'project-a')
    paused = False

    async def stalled_body():
        nonlocal paused
        yield archive[:32]
        paused = True
        await asyncio.Event().wait()

    async def stalled_restore():
        transport = httpx.ASGITransport(app=client.app, client=('127.0.0.1', 12345))
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, cookies=client.cookies) as stalled:
            return await asyncio.wait_for(
                stalled.post(RESTORE + 'stalled', content=stalled_body(), headers=headers), timeout=5,
            )

    with monkeypatch.context() as patch:
        patch.setattr(dashboard_http, '_RESTORE_UPLOAD_TIMEOUT', 0.2)
        timed_out = asyncio.run(stalled_restore())

    assert paused
    assert timed_out.status_code == 408
    assert timed_out.json()['reason'] == 'archive_restore_timeout'
    assert not dashboard._archive_gate.locked()
    assert not (profiles / 'stalled').exists()
    restored = client.post(RESTORE + 'after-timeout', content=archive, headers=headers)
    assert restored.status_code == 201, restored.text
    assert (profiles / 'after-timeout' / 'flower.yaml').is_file()
