"""Canonical bounded engineering authority; no provider or model required."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from flow_of_work_mcp import SQLiteRequirementLedger
from flow_of_work_mcp.application.architecture import ArchitectureService
from flow_of_work_mcp.core.domain.architecture import normalize_definition
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError


def component(identity, **patch):
    return {'id': identity, 'name': identity, 'responsibility': 'Own this explicit bounded responsibility.',
            'boundaries': ['No concurrent lifecycle writer.'], 'invariants': [], 'links': [], **patch}


def definition():
    return {'components': [component('Pi', responsibility='Own the loop.'),
                           component('Flower', responsibility='Own lifecycle authority.'), component('Noxi')],
            'interfaces': [{'id': 'Lifecycle', 'name': 'Lifecycle MCP', 'provider_component_id': 'Flower',
                            'consumer_component_ids': ['Pi'], 'kind': 'protocol',
                            'clauses': ['Call canonical lifecycle mutations with issued revision authority.'],
                            'failure_contract': ['Unknown effects do not authorize another writer.'],
                            'compatibility': ['Standalone agent execution remains available.'], 'links': []}],
            'decisions': [{'id': 'Ownership', 'statement': 'Pi owns the loop and Flower owns lifecycle.',
                           'rationale': 'Avoid a second semantic store in Noxi.', 'component_ids': ['Pi', 'Flower'],
                           'interface_ids': ['Lifecycle'], 'supersedes_decision_id': '', 'links': []}]}


def setup(tmp_path):
    ledger = SQLiteRequirementLedger(tmp_path / 'architecture.sqlite')
    ledger.create_project('alpha', 'Noxi synthetic authority', actor='engineer')
    ledger.create_project('beta', 'Separate project', actor='engineer')
    return ledger, ArchitectureService(ledger)


def adopt(service, value=None, *, expected=0, key='first'):
    proposal = service.call('alpha', 'propose', actor='engineer', request_id=key + '-propose',
                            payload={'expected_revision': expected, 'definition': value or definition()})
    receipt = service.call('alpha', 'adopt', actor='engineer', request_id=key + '-adopt',
                           payload={'expected_revision': expected, 'revision': proposal['revision'],
                                    'rationale': 'Ordinary engineering decision after investigation.'})
    return receipt


def test_absent_inspection_is_bounded_read_only_and_proposals_are_not_authority(tmp_path):
    ledger, service = setup(tmp_path)
    before = ledger.ledger_version('alpha')
    absent = service.call('alpha', 'inspect')
    assert absent['state'] == 'absent' and absent['revision'] == 0 and absent['items'] == []
    assert ledger.ledger_version('alpha') == before
    proposal = service.call('alpha', 'propose', actor='engineer', request_id='proposal',
                            payload={'expected_revision': 0, 'definition': definition()})
    assert service.call('alpha', 'inspect')['state'] == 'absent'
    proposed = service.call('alpha', 'inspect', payload={'revision': proposal['revision'], 'limit': 2})
    assert proposed['state'] == 'proposed' and proposed['count'] == 2 and proposed['total'] == 5
    assert not proposed['complete'] and proposed['next_offset'] == 2
    remainder = service.call('alpha', 'inspect', payload={'revision': proposal['revision'], 'offset': 2, 'limit': 100})
    assert remainder['complete'] and remainder['count'] == 3
    with pytest.raises(ChangeControlBlockedError, match='not_adopted'):
        ledger.validate_architecture_refs('alpha', [{'revision': proposal['revision'], 'kind': 'component', 'entity_id': 'Pi'}])


def test_exact_replay_actor_payload_and_operation_conflicts_and_restart(tmp_path):
    ledger, service = setup(tmp_path)
    payload = {'expected_revision': 0, 'definition': definition()}
    first = service.call('alpha', 'propose', actor='engineer', request_id='one', payload=payload)
    version = ledger.ledger_version('alpha')
    assert service.call('alpha', 'propose', actor='engineer', request_id='one', payload=payload) == first
    assert ledger.ledger_version('alpha') == version
    for actor, value in [('other', payload), ('engineer', {**payload, 'definition': {'components': [], 'interfaces': [], 'decisions': []}})]:
        with pytest.raises(RequirementConflictError):
            service.call('alpha', 'propose', actor=actor, request_id='one', payload=value)
    adoption = {'expected_revision': 0, 'revision': first['revision'], 'rationale': 'Investigated technical choice.'}
    with pytest.raises(RequirementConflictError):
        service.call('alpha', 'adopt', actor='engineer', request_id='one', payload=adoption)
    result = service.call('alpha', 'adopt', actor='engineer', request_id='adopt-one', payload=adoption)
    reopened = ArchitectureService(SQLiteRequirementLedger(tmp_path / 'architecture.sqlite'))
    assert reopened.call('alpha', 'adopt', actor='engineer', request_id='adopt-one', payload=adoption) == result
    assert reopened.call('alpha', 'propose', actor='engineer', request_id='one', payload=payload) == first
    assert result['acceptance'] == result['verification'] == 'not_inferred'
    assert reopened.call('alpha', 'inspect')['provenance']['adopted_by'] == 'engineer'
    assert reopened.call('beta', 'inspect')['state'] == 'absent'
    history = reopened.call('alpha', 'inspect', payload={'kind': 'history', 'limit': 1})
    assert history['total'] == 1 and history['count'] == 1 and history['complete']
    assert history['items'][0]['state'] == 'adopted'
    interface = reopened.call('alpha', 'inspect', payload={'kind': 'interface'})['items'][0]
    assert interface['kind'] == 'interface' and interface['entity']['kind'] == 'protocol'


def test_stale_adoption_and_concurrent_cas_do_not_partially_mutate_authority(tmp_path):
    ledger, service = setup(tmp_path)
    proposals = [service.call('alpha', 'propose', actor='engineer', request_id=f'p-{i}',
                             payload={'expected_revision': 0, 'definition': definition()}) for i in range(2)]
    def attempt(proposal):
        try:
            return service.call('alpha', 'adopt', actor='engineer', request_id=f'a-{proposal["revision"]}',
                                payload={'expected_revision': 0, 'revision': proposal['revision'], 'rationale': 'CAS adoption.'})['state']
        except ChangeControlBlockedError as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, proposals))
    assert sorted(results) == ['adopted', 'architecture_revision_stale']
    head = service.call('alpha', 'inspect')['revision']
    before = ledger.ledger_version('alpha')
    with pytest.raises(ChangeControlBlockedError, match='stale'):
        service.call('alpha', 'propose', actor='engineer', request_id='stale-new',
                     payload={'expected_revision': 0, 'definition': definition()})
    assert ledger.ledger_version('alpha') == before
    assert service.call('alpha', 'inspect')['revision'] == head


def test_adopted_decisions_are_immutable_and_lineage_retained(tmp_path):
    ledger, service = setup(tmp_path)
    first = adopt(service)
    changed = definition()
    changed['decisions'][0]['statement'] = 'Silently replace the previous choice.'
    with pytest.raises(ChangeControlBlockedError, match='immutable'):
        service.call('alpha', 'propose', actor='engineer', request_id='rewrite',
                     payload={'expected_revision': first['revision'], 'definition': changed})
    changed = definition()
    changed['decisions'] = []
    with pytest.raises(ChangeControlBlockedError, match='immutable'):
        service.call('alpha', 'propose', actor='engineer', request_id='erase',
                     payload={'expected_revision': first['revision'], 'definition': changed})
    changed = definition()
    changed['decisions'].append({**changed['decisions'][0], 'id': 'Ownership2',
                                'statement': 'Refine the observed ownership boundary.', 'supersedes_decision_id': 'Ownership'})
    second = adopt(service, changed, expected=first['revision'], key='second')
    assert second['revision'] > first['revision']
    assert ledger.architecture_revision('alpha', first['revision'])['definition'] == normalize_definition(definition())


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(extra=True),
    lambda d: d['components'].append(deepcopy(d['components'][0])),
    lambda d: d['interfaces'][0].update(provider_component_id='Missing'),
    lambda d: d['interfaces'][0].update(kind='graph_authority'),
    lambda d: d['decisions'][0].update(supersedes_decision_id='Ownership'),
    lambda d: d['decisions'][0].update(supersedes_decision_id='Missing'),
    lambda d: d['components'][0].update(responsibility='x' * 4097),
    lambda d: d['components'][0].update(links=[{'kind': 'requirement', 'requirement_id': 'REQ-000001', 'project_id': 'beta'}]),
])
def test_malformed_definitions_are_atomic(tmp_path, mutation):
    ledger, service = setup(tmp_path)
    value = definition()
    mutation(value)
    before = ledger.ledger_version('alpha')
    with pytest.raises(ValueError):
        service.call('alpha', 'propose', actor='engineer', request_id='invalid',
                     payload={'expected_revision': 0, 'definition': value})
    assert ledger.ledger_version('alpha') == before
    assert ledger.architecture_revision_history('alpha') == []


def test_entity_link_utf8_aggregate_and_paging_bounds(tmp_path):
    _, service = setup(tmp_path)
    with pytest.raises(ValueError, match='128 entities'):
        normalize_definition({'components': [component(f'C{i}') for i in range(128)],
                              'interfaces': [], 'decisions': [definition()['decisions'][0]]})
    links = [{'kind': 'requirement', 'requirement_id': f'REQ-{i:06d}'} for i in range(128)]
    with pytest.raises(ValueError, match='512 links'):
        normalize_definition({'components': [component(f'C{i}', links=links) for i in range(5)], 'interfaces': [], 'decisions': []})
    with pytest.raises(ValueError, match='256KiB'):
        normalize_definition({'components': [component(f'C{i}', responsibility='è' * 4096) for i in range(40)], 'interfaces': [], 'decisions': []})
    for payload in [{'limit': 101}, {'limit': True}, {'offset': -1}, {'revision': True}, {'revision': 2**63}, {'extra': 1}]:
        with pytest.raises(ValueError):
            service.call('alpha', 'inspect', payload=payload)
