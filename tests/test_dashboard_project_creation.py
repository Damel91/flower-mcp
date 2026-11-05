"""Authenticated dashboard creation through the canonical project service."""
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from tests.test_dashboard_http import fixture, request_csrf
from tests.test_native_project_purge import _rows


ORIGIN = 'http://127.0.0.1:18760'
PROJECTS = '/dashboard/api/projects'


@pytest.fixture
def browser(tmp_path):
    runtime, dashboard, mcp = fixture(tmp_path)
    try:
        with TestClient(mcp.streamable_http_app(), base_url=ORIGIN, client=('127.0.0.1', 12345)) as client:
            yield runtime, client
    finally:
        dashboard.close()
        runtime.close()


def authenticated_headers(client):
    return {'Origin': ORIGIN, 'X-Flower-CSRF': request_csrf(client)}


def test_create_persists_empty_project_and_refuses_duplicate(browser):
    runtime, client = browser
    headers = authenticated_headers(client)
    response = client.post(PROJECTS, json={'project_id': 'new_project-1', 'name': '  Nuovo progetto  '}, headers=headers)
    assert response.status_code == 201
    project = response.json()['result']
    assert project['project_id'] == 'new_project-1'
    assert project['name'] == 'Nuovo progetto'
    assert project['created_at']

    overview = client.get(PROJECTS + '/new_project-1/sections/overview')
    assert overview.status_code == 200
    result = overview.json()['result']
    assert result['project']['project_id'] == project['project_id']
    assert result['project']['name'] == project['name']
    assert result['summary']['requirements_total'] == 0
    before_duplicate = _rows(runtime.ledger.database_path)

    duplicate = client.post(PROJECTS, json={'project_id': 'new_project-1', 'name': 'Replacement'}, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()['reason'] == 'dashboard_project_conflict'
    assert _rows(runtime.ledger.database_path) == before_duplicate


def test_create_checks_owner_origin_csrf_and_closed_bounded_input(browser):
    runtime, client = browser
    body = {'project_id': 'protected-project', 'name': 'Protected project'}
    before = _rows(runtime.ledger.database_path)
    assert client.post(PROJECTS, json=body, headers={'Origin': ORIGIN}).status_code == 401

    headers = authenticated_headers(client)
    for invalid_headers in (
        {'X-Flower-CSRF': headers['X-Flower-CSRF']},
        {**headers, 'Origin': 'https://other.example'},
        {**headers, 'X-Flower-CSRF': 'incorrect'},
    ):
        assert client.post(PROJECTS, json=body, headers=invalid_headers).status_code == 403

    for invalid_body in (
        {**body, 'actor': 'forged'},
        {**body, 'project_id': 'Invalid ID'},
        {**body, 'name': 12},
        {**body, 'name': '   '},
        {**body, 'name': 'a' * 257},
    ):
        response = client.post(PROJECTS, json=invalid_body, headers=headers)
        assert response.status_code == 400
        assert response.json()['reason'] == 'dashboard_input_invalid'
    assert _rows(runtime.ledger.database_path) == before


def test_create_is_fenced_during_maintenance(browser):
    runtime, client = browser
    headers = authenticated_headers(client)
    deletion = PROJECTS + '/project-a/deletion/'
    intent = {'deletion_id': str(uuid4())}
    prepared = client.post(deletion + 'prepare', json=intent, headers=headers)
    assert prepared.json()['result']['maintenance']['state'] == 'maintenance'
    before = _rows(runtime.ledger.database_path)

    blocked = client.post(PROJECTS, json={'project_id': 'blocked-project', 'name': 'Blocked project'}, headers=headers)
    assert blocked.status_code == 503
    assert blocked.json()['reason'] == 'server_maintenance'
    assert _rows(runtime.ledger.database_path) == before

    cancelled = client.post(deletion + 'cancel', json=intent, headers=headers)
    assert cancelled.json()['result']['maintenance']['state'] == 'ready'
