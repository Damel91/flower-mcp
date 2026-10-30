"""Bounded architecture definitions and selected, provider-neutral closure."""
from __future__ import annotations

import re
from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import (
    CONTRACT_KINDS, canonical_json, fields, number, objects, strings, text,
)

ARCHITECTURE_CONTRACT = 'flow.architecture.v1'
ARCHITECTURE_CONTEXT_CONTRACT = 'flow.architecture_context.v1'
ENTITY_KINDS = ('component', 'interface', 'decision')
ENTITY_LISTS = {'component': 'components', 'interface': 'interfaces', 'decision': 'decisions'}
ENTITY_ID_PATTERN = r'^[A-Za-z][A-Za-z0-9_.-]{0,79}$'
_IDENTITY = re.compile(ENTITY_ID_PATTERN)
_ENTITY_FIELDS = {
    'component': {'id', 'name', 'responsibility', 'boundaries', 'invariants', 'links'},
    'interface': {'id', 'name', 'provider_component_id', 'consumer_component_ids', 'kind', 'clauses', 'failure_contract', 'compatibility', 'links'},
    'decision': {'id', 'statement', 'rationale', 'component_ids', 'interface_ids', 'supersedes_decision_id', 'links'},
}
_LINK_FIELDS = {'requirement': {'kind', 'requirement_id'}, 'goal': {'kind', 'goal_node_id'},
                'packet': {'kind', 'change_id', 'packet_id'}, 'evidence': {'kind', 'evidence_id'}}


def nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**63 - 1:
        raise ValueError(f'{field} must be a nonnegative SQLite integer')
    return value


def positive_integer(value: object, field: str) -> int:
    return number(nonnegative_integer(value, field), field)


def entity_id(value: object, field: str = 'entity_id') -> str:
    value = text(value, field)
    if not _IDENTITY.fullmatch(value):
        raise ValueError(f'{field} must match [A-Za-z][A-Za-z0-9_.-]{{0,79}}')
    return value


def _exact(value: Mapping[str, object], allowed: set[str], field: str) -> None:
    fields(value, allowed, field)
    if set(value) != allowed:
        raise ValueError(f'{field} missing fields: {", ".join(sorted(allowed - set(value)))}')


def normalize_link(value: Mapping[str, object]) -> dict[str, object]:
    kind = text(value.get('kind'), 'link.kind')
    if kind not in _LINK_FIELDS:
        raise ValueError('unsupported architecture link kind')
    _exact(value, _LINK_FIELDS[kind], 'link')
    return {key: (positive_integer(raw, key) if key == 'evidence_id' else text(raw, key))
            for key, raw in value.items()}


def normalize_definition(value: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(value, Mapping):
        raise ValueError('definition must be an object')
    _exact(value, set(ENTITY_LISTS.values()), 'definition')
    result = {}
    total_links = 0
    for kind, list_name in ENTITY_LISTS.items():
        entities = []
        for item in objects(value[list_name], list_name):
            _exact(item, _ENTITY_FIELDS[kind], kind)
            entity = {'id': entity_id(item['id'], kind + '.id')}
            for field in _ENTITY_FIELDS[kind] - {'id', 'links'}:
                if field in {'boundaries', 'invariants', 'clauses', 'failure_contract', 'compatibility',
                             'component_ids', 'interface_ids', 'consumer_component_ids'}:
                    entity[field] = list(strings(item[field], field))
                    if field in {'component_ids', 'interface_ids', 'consumer_component_ids'}:
                        entity[field] = sorted(entity_id(raw, field) for raw in entity[field])
                elif field == 'supersedes_decision_id':
                    entity[field] = entity_id(item[field], field) if item[field] else text(item[field], field, required=False)
                elif field == 'provider_component_id':
                    entity[field] = entity_id(item[field], field)
                else:
                    entity[field] = text(item[field], field)
            links = [normalize_link(link) for link in objects(item['links'], 'links')]
            if len({canonical_json(link) for link in links}) != len(links):
                raise ValueError('architecture links must be unique within an entity')
            entity['links'] = sorted(links, key=canonical_json)
            total_links += len(links)
            if kind == 'interface':
                if entity['kind'] not in CONTRACT_KINDS:
                    raise ValueError('unsupported architecture interface kind')
                if not entity['clauses'] or not entity['consumer_component_ids']:
                    raise ValueError('interface requires clauses and consumers')
            entities.append(entity)
        if len({item['id'] for item in entities}) != len(entities):
            raise ValueError(f'duplicate architecture {kind} identity')
        result[list_name] = sorted(entities, key=lambda item: item['id'])
    if sum(len(items) for items in result.values()) > 128:
        raise ValueError('architecture supports at most 128 entities')
    if total_links > 512:
        raise ValueError('architecture supports at most 512 links')
    if len(canonical_json(result).encode('utf-8')) > 256 * 1024:
        raise ValueError('architecture definition exceeds 256KiB')
    components = {item['id'] for item in result['components']}
    interfaces = {item['id'] for item in result['interfaces']}
    decisions = {item['id']: item for item in result['decisions']}
    for interface in result['interfaces']:
        if not {interface['provider_component_id'], *interface['consumer_component_ids']} <= components:
            raise ValueError('architecture interface endpoint missing')
    for decision in result['decisions']:
        if not set(decision['component_ids']) <= components or not set(decision['interface_ids']) <= interfaces:
            raise ValueError('architecture decision subject missing')
        seen = {decision['id']}
        previous = decision['supersedes_decision_id']
        while previous:
            if previous in seen:
                raise ValueError('architecture decision supersession cycle')
            if previous not in decisions:
                raise ValueError('architecture superseded decision missing')
            seen.add(previous)
            previous = decisions[previous]['supersedes_decision_id']
    return result


def normalize_architecture_refs(value: object) -> tuple[dict[str, object], ...]:
    result = []
    for item in objects(value, 'architecture_refs'):
        _exact(item, {'revision', 'kind', 'entity_id'}, 'architecture_ref')
        kind = text(item['kind'], 'kind')
        if kind not in ENTITY_KINDS:
            raise ValueError('unsupported architecture reference kind')
        result.append({'revision': positive_integer(item['revision'], 'revision'), 'kind': kind,
                       'entity_id': entity_id(item['entity_id'])})
    if len({item['revision'] for item in result}) > 1:
        raise ValueError('architecture references must select one adopted revision')
    if len({(item['kind'], item['entity_id']) for item in result}) != len(result):
        raise ValueError('architecture references must be unique')
    return tuple(sorted(result, key=lambda item: (item['kind'], item['entity_id'])))


def selected_closure(definition: Mapping[str, object], refs: object) -> dict[str, list[dict[str, object]]]:
    """Follow only explicit forward endpoints, subjects and decision lineage."""
    normalized = normalize_architecture_refs(refs)
    by_kind = {kind: {item['id']: item for item in definition[name]} for kind, name in ENTITY_LISTS.items()}
    selected = {kind: set() for kind in ENTITY_KINDS}
    pending = [(ref['kind'], ref['entity_id']) for ref in normalized]
    while pending:
        kind, identity = pending.pop()
        if identity in selected[kind]:
            continue
        item = by_kind[kind].get(identity)
        if item is None:
            raise ValueError('architecture reference entity missing')
        selected[kind].add(identity)
        if kind == 'interface':
            pending.extend(('component', key) for key in [item['provider_component_id'], *item['consumer_component_ids']])
        elif kind == 'decision':
            pending.extend(('component', key) for key in item['component_ids'])
            pending.extend(('interface', key) for key in item['interface_ids'])
            if item['supersedes_decision_id']:
                pending.append(('decision', item['supersedes_decision_id']))
    return {name: [by_kind[kind][key] for key in sorted(selected[kind])] for kind, name in ENTITY_LISTS.items()}


def applicability(closure: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    changed = []
    for kind, name in ENTITY_LISTS.items():
        by_id = {item['id']: item for item in current[name]}
        for item in closure[name]:
            if by_id.get(item['id']) != item:
                changed.append({'kind': kind, 'entity_id': item['id']})
    selected_decisions = {item['id'] for item in closure['decisions']}
    superseded = sorted({item['supersedes_decision_id'] for item in current['decisions']
                         if item['supersedes_decision_id'] in selected_decisions and item['id'] not in selected_decisions})
    return {'status': 'stale' if changed or superseded else 'current',
            'changed_entities': changed, 'superseded_decision_ids': superseded}
