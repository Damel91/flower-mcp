"""Public application boundary for ordinary engineering architecture authority."""
from __future__ import annotations

from flow_of_work_mcp.core.domain.architecture import ARCHITECTURE_CONTRACT, ENTITY_LISTS, nonnegative_integer, normalize_definition
from flow_of_work_mcp.core.domain.external_work import fields, number, text
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, InputValidationError, OperationPreEffectError
from flow_of_work_mcp.markdown_adapter import render_structured, safe_inline


def prepare_architecture_mutation(project_id, operation, *, payload, actor, request_id):
    """Validate pure input only; never consult a service or open a transaction.

    Preserve the raw definition for the existing exact-request fingerprint.
    Callers may trust this phase's rejection, never the same exception after
    dispatch. Repository validation still protects direct ledger callers.
    """
    field, value = 'project_id', project_id
    try:
        validate_project_id(project_id)
        field, value = 'actor', actor
        actor = text(actor, field)
        field, value = 'request_id', request_id
        request_id = text(request_id, field)
        field, value = 'payload', payload
        if not isinstance(payload, dict):
            raise ValueError('architecture payload must be an object')
        if operation == 'propose':
            fields(payload, {'definition', 'expected_revision'}, operation)
        elif operation == 'adopt':
            fields(payload, {'revision', 'expected_revision', 'rationale'}, operation)
        else:
            raise ValueError('unsupported architecture mutation')
        field, value = 'payload.expected_revision', payload.get('expected_revision')
        expected = nonnegative_integer(value, field)
        result = {'project_id': project_id, 'expected_revision': expected,
                  'actor': actor, 'request_id': request_id}
        if operation == 'propose':
            field, value = 'payload.definition', payload.get('definition')
            normalize_definition(value)
            return {**result, 'definition': value}
        field, value = 'payload.revision', payload.get('revision')
        revision = number(nonnegative_integer(value, field), field)
        field, value = 'payload.rationale', payload.get('rationale')
        return {**result, 'revision': revision, 'rationale': text(value, field)}
    except InputValidationError as exc:
        if 'missing_entity_fields' in exc.details:
            raise OperationPreEffectError(
                'architecture_input_invalid', str(exc), field=field, received_value=exc.received_value,
                rule='Provide every required field for each indexed entity.',
                resolution='Supply all listed fields in one correction. Use [] where an empty list is allowed; interface clauses and consumer_component_ids must be nonempty. Use an empty string for supersedes_decision_id when there is no predecessor. This invocation started no mutation.',
                details=exc.details,
            ) from exc
        is_markdown = exc.field == 'markdown'
        raise OperationPreEffectError('architecture_input_invalid', str(exc),
            field=f'{field}.{exc.field}', received_value=exc.received_value,
            rule=str(exc) if is_markdown else 'Use an accepted interface kind.',
            resolution=(
                'Supply bounded UTF-8 Markdown or omit the optional field.' if is_markdown
                else 'Choose the allowed kind that describes this interface and correct the indexed field.'
            ) + ' This invocation started no mutation; earlier work under the same ID is unchanged.',
            details={**exc.details, 'accepted_values': list(exc.accepted_values)}) from exc
    except (ValueError, TypeError) as exc:
        raise OperationPreEffectError('architecture_input_invalid', str(exc),
            field=field, received_value=value,
            rule='Use the exact architecture operation contract, including array-valued collections.',
            resolution='Read the named operation contract and correct the intended input. This invocation started no mutation; earlier work under the same ID is unchanged.') from exc


class ArchitectureService:
    def __init__(self, ledger) -> None:
        self._ledger = ledger

    def call(self, project_id, operation, *, payload=None, actor='', request_id=''):
        payload = {} if payload is None else payload
        if operation in {'propose', 'adopt'}:
            prepared = prepare_architecture_mutation(project_id, operation,
                payload=payload, actor=actor, request_id=request_id)
            if operation == 'propose':
                return self._ledger.propose_architecture(**prepared)
            return self._ledger.adopt_architecture(**prepared)
        if not isinstance(payload, dict):
            raise ValueError('architecture payload must be an object')
        if operation == 'export':
            fields(payload, {'revision'}, operation)
            revision = nonnegative_integer(payload.get('revision', 0), 'revision')
            return self._export(project_id, revision)
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

    def _export(self, project_id: str, revision: int) -> dict[str, object]:
        state = self._ledger.architecture_revision(project_id, revision)
        if state['state'] == 'absent':
            raise ChangeControlBlockedError('architecture_not_adopted', details={'project_id': project_id})
        definition = state['definition']
        entity_sections = {name: definition[name] for name in ENTITY_LISTS.values()}
        markdown = '\n'.join([
            '# Project architecture',
            '',
            f"- **Project:** {safe_inline(project_id)}",
            f"- **Architecture revision:** {state['revision']}",
            f"- **State:** {state['state']}",
            f"- **Definition fingerprint:** {state['definition_fingerprint']}",
            '',
            render_structured(entity_sections),
        ])
        if definition.get('markdown'):
            markdown += '\n## Architecture narrative\n\n' + definition['markdown']
        return {'contract': ARCHITECTURE_CONTRACT, **state, 'markdown': markdown,
                'acceptance': 'not_inferred', 'verification': 'not_inferred'}
