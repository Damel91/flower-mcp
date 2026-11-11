"""Scoped architecture documents through the authenticated dashboard."""
import asyncio

from starlette.testclient import TestClient

from flow_of_work_mcp.application import dashboard as dashboard_module
from tests.test_architecture_authority import definition
from tests.test_dashboard_http import fixture, request_csrf
from tests.test_native_project_purge import _rows


BASE = '/dashboard/api/projects/project-a/documents/architecture'
NARRATIVE = '  Café.\r\n\r\n```mermaid\r\ngraph LR\r\nA --> B\r\n```\r\n\r\n![offline](https://example.test/img.png)\r\n'


def propose(runtime, project, key, *, expected=0, narrative=None):
    value = definition()
    if narrative is not None:
        value['markdown'] = narrative
    return runtime.architecture.call(project, 'propose',
        payload={'expected_revision': expected, 'definition': value},
        actor='fixture-owner', request_id=key)['revision']


def adopt(runtime, project, revision, *, expected=0):
    runtime.architecture.call(project, 'adopt', payload={'revision': revision,
        'expected_revision': expected, 'rationale': 'Verified design on the owned fixture.'},
        actor='fixture-owner', request_id=f'adopt-{revision}')


def test_exact_markdown_matches_mcp_with_adoption_history_and_original_mermaid(tmp_path):
    runtime, _, mcp = fixture(tmp_path)
    try:
        legacy = propose(runtime, 'project-a', 'legacy')
        adopt(runtime, 'project-a', legacy)
        current = propose(runtime, 'project-a', 'current', expected=legacy, narrative=NARRATIVE)
        adopt(runtime, 'project-a', current, expected=legacy)
        draft = propose(runtime, 'project-a', 'draft', expected=current, narrative='Future prose.')
        before = _rows(runtime.ledger.database_path)

        async def mcp_markdown(revision):
            result = await mcp.call_tool('fow_architecture', {
                'project_id': 'project-a', 'operation': 'export', 'payload': {'revision': revision},
            })
            assert not result.isError
            return result.content[0].text

        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760',
                        client=('127.0.0.1', 12345)) as client:
            assert client.get(BASE).status_code == 401
            assert client.get(f'{BASE}/history').status_code == 401
            request_csrf(client)
            response = client.get(f'{BASE}/history?limit=2')
            assert response.status_code == 200, response.text
            history = response.json()['result']
            assert history['current_adopted_revision'] == current
            assert history['bounds']['next_offset'] == 2
            assert [(r['revision'], r['state']) for r in history['items']] == [
                (legacy, 'adopted'), (current, 'adopted')]
            next_page = client.get(f'{BASE}/history?offset=2&limit=2').json()['result']
            assert [(r['revision'], r['state']) for r in next_page['items']] == [(draft, 'proposed')]
            assert next_page['bounds']['next_offset'] is None
            assert client.get(BASE).json()['result']['revision'] == current
            for revision, state in [(legacy, 'adopted'), (current, 'adopted'), (draft, 'proposed')]:
                response = client.get(f'{BASE}?revision={revision}')
                assert response.status_code == 200, response.text
                result = response.json()['result']
                assert result['revision'] == revision and result['state'] == state
                assert result['content_type'] == 'text/markdown'
                assert result['filename'] == f'flower-project-a-architecture-r{revision}.md'
                assert result['definition_fingerprint']
                assert result['content'].encode() == asyncio.run(mcp_markdown(revision)).encode()
            original = client.get(f'{BASE}?revision={current}').json()['result']
            assert original['content'].endswith(NARRATIVE)
            assert original['reader']['status'] == 'ready'
            assert any(node == {'tag': 'pre', 'children': [{'tag': 'code', 'children': [
                {'text': 'graph LR\nA --> B\n'}]}]} for node in original['reader']['nodes'])
            assert 'https://example.test/img.png' not in str(original['reader'])
        assert _rows(runtime.ledger.database_path) == before
    finally:
        runtime.close()


def test_proposals_require_exact_selection_and_invalid_scopes_are_bounded(tmp_path, monkeypatch):
    runtime, _, mcp = fixture(tmp_path)
    try:
        propose(runtime, 'project-a', 'a-1')
        propose(runtime, 'project-a', 'a-2')
        proposal = propose(runtime, 'project-b', 'b-1', narrative=NARRATIVE)
        before = _rows(runtime.ledger.database_path)
        with TestClient(mcp.streamable_http_app(), base_url='http://127.0.0.1:18760',
                        client=('127.0.0.1', 12345)) as client:
            request_csrf(client)
            other = BASE.replace('project-a', 'project-b')
            foreign = client.get(f'{other}?revision=2')
            missing = client.get(f'{other}?revision=999')
            assert foreign.status_code == missing.status_code == 404
            assert foreign.json() == missing.json()
            assert client.get(other).status_code == 404
            history = client.get(f'{other}/history').json()['result']
            assert history['current_adopted_revision'] == 0
            assert client.get(f'{other}?revision={proposal}').json()['result']['state'] == 'proposed'
            for query in ('revision=', 'revision=0', 'revision=-1', 'revision=9223372036854775808',
                          'revision=1&revision=2', 'revision=1&offset=2'):
                assert client.get(f'{other}?{query}').status_code == 400, query
            assert client.get(f'{other}/history?limit=26').status_code == 400

            monkeypatch.setattr(dashboard_module, 'MAXIMUM_EVIDENCE_BYTES', 128)
            assert client.get(f'{other}?revision={proposal}').status_code == 413
        assert _rows(runtime.ledger.database_path) == before
    finally:
        runtime.close()
