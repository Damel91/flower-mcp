"""Inert native Markdown nodes, retained originals and bounded presentation."""
from copy import deepcopy
import sqlite3

import pytest

from flow_of_work_mcp.application import dashboard as dashboard_module
from flow_of_work_mcp.application.dashboard import DashboardProjectionService, _evidence_response_bytes
from flow_of_work_mcp.application.dashboard_markdown import (
    ALLOWED_TAGS, MAXIMUM_NODES, MAXIMUM_SOURCE_BYTES, limited_reader, markdown_reader,
)
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind
from flow_of_work_mcp.mcp_runtime import build_runtime


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get('children', []))


def test_native_reader_preserves_document_structure_and_local_outline():
    source = ('# Intro *uno*\n\n[Salta](#intro-uno) [Ripetuto](#intro-uno-1)\n\n'
              '## Intro *uno*\n\n> Nota **importante** e ~~superata~~.\n\n'
              '0. Primo\n1. Secondo\n\n- Punto\n\n'
              '| Nome | Stato |\n| :--- | ---: |\n| A | pronto |\n\n'
              '```javascript\nwindow.alert("test");\n```\n')
    reader = markdown_reader(source)
    assert reader['status'] == 'ready'
    nodes = list(walk(reader['nodes']))
    tags = {node['tag'] for node in nodes if 'tag' in node}
    assert {'h1', 'h2', 'p', 'blockquote', 'strong', 'em', 's', 'ol', 'ul', 'li', 'table', 'th', 'td', 'pre', 'code'} <= tags
    assert reader['outline'] == [
        {'id': 'flower-md-heading-1', 'text': 'Intro uno', 'level': 1},
        {'id': 'flower-md-heading-2', 'text': 'Intro uno', 'level': 2},
    ]
    assert [node['href'] for node in nodes if node.get('tag') == 'a'] == ['#flower-md-heading-1', '#flower-md-heading-2']
    assert next(node for node in nodes if node.get('tag') == 'ol')['start'] == 0
    assert any(node.get('text') == 'window.alert("test");\n' for node in nodes)
    assert {node['align'] for node in nodes if 'align' in node} == {'left', 'right'}


def test_untrusted_html_images_and_unsafe_links_cannot_become_executable_nodes():
    source = ('<script>window.stolen = true</script>\n\n'
              '<img src="/dashboard/api/session" onerror="alert(1)">\n\n'
              '[Script](javascript:alert(1)) [Data](data:text/html,test) '
              '[File](file:///etc/passwd) [Relativo](../secret) [UI](#delete-project)\n\n'
              '[HTTP](https://example.org/a?q=1)\n\n'
              '![**Immagine** leggibile](https://tracker.example/pixel.png)\n')
    reader = markdown_reader(source)
    nodes = list(walk(reader['nodes']))
    assert reader['status'] == 'ready'
    assert all(node.get('tag') in ALLOWED_TAGS for node in nodes if 'tag' in node)
    assert all(set(node) <= {'text', 'tag', 'children', 'href', 'start', 'align', 'id'} for node in nodes)
    assert [node['href'] for node in nodes if 'href' in node] == ['https://example.org/a?q=1']
    assert any(node.get('text') == 'Immagine leggibile' for node in nodes)
    assert not any(node.get('tag') in {'img', 'script', 'iframe', 'style'} for node in nodes)
    assert any('<script>' in node.get('text', '') for node in nodes)


def test_unicode_source_bound_uses_utf8_bytes_without_changing_source():
    source = 'é' * (MAXIMUM_SOURCE_BYTES // 2 + 1)
    reader = markdown_reader(source)
    assert reader == limited_reader('reader_source_limit')
    assert len(source) < MAXIMUM_SOURCE_BYTES


def test_node_limit_is_explicit_and_returns_no_partial_document():
    source = '*a* ' * (MAXIMUM_NODES // 2)
    assert len(source.encode()) < MAXIMUM_SOURCE_BYTES
    assert markdown_reader(source) == limited_reader('reader_node_limit')


@pytest.mark.parametrize('source', ['', 'Text **unfinished', '\n'.join('> ' * 30 + 'Nested' for _ in range(5))])
def test_empty_incomplete_and_deep_markdown_remain_safe_presentations(source):
    reader = markdown_reader(source)
    assert reader['status'] == 'ready'
    assert len(list(walk(reader['nodes']))) <= MAXIMUM_NODES


def retained_fixture(tmp_path, source):
    runtime = build_runtime(database_path=tmp_path / 'reader.sqlite3', import_root=tmp_path)
    runtime.requirements.create_project('reader', 'Reader fixture', actor='test')
    generation = runtime.ledger.record_artifact_generation(ArtifactGeneration(
        project_id='reader', profile_id='test:reader', profile_version='1',
        source_ledger_version=runtime.ledger.ledger_version('reader'), generated_at='2026-11-04T00:00:00Z',
        artifacts=(ArtifactDraft(ArtifactKind.SRS, source, ()),)), actor='test')
    with runtime.ledger._read_connection() as connection:
        identity = str(connection.execute('SELECT artifact_id FROM generated_artifacts WHERE generation_id=?',
                                          (generation.generation_id,)).fetchone()[0])
    return runtime, identity


def dump(runtime):
    with sqlite3.connect(runtime.ledger.database_path) as connection:
        return '\n'.join(connection.iterdump())


def test_evidence_adds_reader_without_altering_original_digest_or_ledger(tmp_path):
    source = '# Documento\n\n| Requisito | Esito |\n| --- | --- |\n| A | da verificare |'
    runtime, identity = retained_fixture(tmp_path, source)
    try:
        before = dump(runtime)
        result = DashboardProjectionService(runtime).evidence('reader', 'artifact', identity)
        assert result['content'] == source and result['content_type'] == 'text/markdown'
        assert result['reader']['status'] == 'ready'
        assert result['content_sha256'] == runtime.ledger.artifact_generations('reader')[0]['artifacts'][0]['content_sha256']
        assert dump(runtime) == before
    finally:
        runtime.close()


@pytest.mark.parametrize('room_for_descriptor', [False, True])
def test_reader_response_budget_limits_or_omits_reader_without_rejecting_original(tmp_path, monkeypatch, room_for_descriptor):
    source = ('# Titolo\n\n' + '*a* ' * 500).strip()
    runtime, identity = retained_fixture(tmp_path, source)
    try:
        monkeypatch.setattr(dashboard_module, '_observed_at', lambda: '2026-11-04T00:00:00+00:00')
        service = DashboardProjectionService(runtime)
        full = service.evidence('reader', 'artifact', identity)
        original = deepcopy(full)
        del original['reader']
        original_size = _evidence_response_bytes(original)
        limited = {**original, 'reader': limited_reader('reader_response_limit')}
        budget = _evidence_response_bytes(limited) + 8 if room_for_descriptor else original_size
        assert _evidence_response_bytes(full) > budget
        monkeypatch.setattr(dashboard_module, 'MAXIMUM_EVIDENCE_BYTES', budget)
        before = dump(runtime)
        result = service.evidence('reader', 'artifact', identity)
        assert result['content'] == source and result['content_sha256'] == full['content_sha256']
        assert _evidence_response_bytes(result) <= budget
        if room_for_descriptor:
            assert result['reader'] == limited_reader('reader_response_limit')
        else:
            assert 'reader' not in result
        assert dump(runtime) == before
    finally:
        runtime.close()
