"""Public application boundary for ordinary engineering architecture authority."""
from __future__ import annotations

from flow_of_work_mcp.core.domain.architecture import ARCHITECTURE_CONTRACT, ENTITY_LISTS, nonnegative_integer
from flow_of_work_mcp.core.domain.external_work import fields, number, text


class ArchitectureService:
    def __init__(self, ledger) -> None:
        self._ledger = ledger

    def call(self, project_id, operation, *, payload=None, actor='', request_id=''):
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise ValueError('architecture payload must be an object')
        if operation == 'propose':
            fields(payload, {'definition', 'expected_revision'}, operation)
            return self._ledger.propose_architecture(project_id, payload.get('definition'),
                expected_revision=nonnegative_integer(payload.get('expected_revision'), 'expected_revision'),
                actor=text(actor, 'actor'), request_id=text(request_id, 'request_id'))
        if operation == 'adopt':
            fields(payload, {'revision', 'expected_revision', 'rationale'}, operation)
            return self._ledger.adopt_architecture(project_id, number(payload.get('revision'), 'revision'),
                expected_revision=nonnegative_integer(payload.get('expected_revision'), 'expected_revision'),
                rationale=text(payload.get('rationale'), 'rationale'), actor=text(actor, 'actor'), request_id=text(request_id, 'request_id'))
        if operation != 'inspect':
            raise ValueError('unsupported architecture operation')
        fields(payload, {'revision', 'kind', 'offset', 'limit'}, operation)
        revision = nonnegative_integer(payload.get('revision', 0), 'revision')
        offset = nonnegative_integer(payload.get('offset', 0), 'offset')
        limit = number(payload.get('limit', 20), 'limit')
        if limit > 100:
            raise ValueError('architecture inspect limit must be at most 100')
        kind = payload.get('kind', 'all')
        if kind not in {'all', 'history', *ENTITY_LISTS}:
            raise ValueError('unsupported architecture inspect kind')
        with self._ledger.consistent_read():
            state = self._ledger.architecture_revision(project_id, revision)
            if kind == 'history':
                total = self._ledger.architecture_revision_count(project_id)
                page = self._ledger.architecture_revision_history(project_id, offset=offset, limit=limit)
            else:
                items = [{'kind': entity_kind, 'entity': item} for entity_kind, name in ENTITY_LISTS.items()
                         if kind in {'all', entity_kind} for item in state['definition'][name]]
                total = len(items)
                page = items[offset:offset + limit]
            more = offset + len(page) < total
            return {'contract': ARCHITECTURE_CONTRACT, **{key: value for key, value in state.items() if key != 'definition'},
                    'items': page, 'total': total, 'count': len(page), 'offset': offset, 'limit': limit,
                    'complete': not more, 'next_offset': offset + len(page) if more else None,
                    'acceptance': 'not_inferred', 'verification': 'not_inferred'}
