"""Immutable project architecture authority in the canonical lifecycle ledger."""
from __future__ import annotations

import json

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.architecture import (
    ARCHITECTURE_CONTRACT, ARCHITECTURE_CONTEXT_CONTRACT, ENTITY_LISTS,
    applicability, nonnegative_integer, positive_integer, normalize_architecture_refs, normalize_definition, selected_closure,
)
from flow_of_work_mcp.core.domain.external_work import canonical_json, fingerprint, number, text
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError


class ArchitectureStoreMixin:
    @staticmethod
    def _architecture_head(connection, project_id):
        row = connection.execute('SELECT revision FROM architecture_adoptions WHERE project_id=? ORDER BY adoption_id DESC LIMIT 1',
                                 (project_id,)).fetchone()
        return int(row['revision']) if row else 0

    def _architecture_value(self, connection, project_id, revision=0):
        head = self._architecture_head(connection, project_id)
        selected = revision or head
        if not selected:
            return {'project_id': project_id, 'revision': 0, 'current_adopted_revision': 0, 'state': 'absent',
                    'definition': {name: [] for name in ENTITY_LISTS.values()}, 'definition_fingerprint': '',
                    'provenance': None}
        row = connection.execute('SELECT * FROM architecture_revisions WHERE project_id=? AND revision=?',
                                 (project_id, selected)).fetchone()
        if row is None:
            raise ChangeControlBlockedError('architecture_revision_not_found')
        adoption = connection.execute('SELECT * FROM architecture_adoptions WHERE project_id=? AND revision=?',
                                      (project_id, selected)).fetchone()
        provenance = {'proposed_by': row['actor'], 'proposed_at': row['created_at'],
                      'adopted_by': adoption['actor'] if adoption else None,
                      'adopted_at': adoption['adopted_at'] if adoption else None,
                      'adoption_rationale': adoption['rationale'] if adoption else None}
        return {'project_id': project_id, 'revision': selected, 'base_revision': int(row['base_revision']),
                'current_adopted_revision': head, 'state': 'adopted' if adoption else 'proposed',
                'definition': json.loads(row['definition_json']), 'definition_fingerprint': row['definition_fingerprint'],
                'provenance': provenance}

    def architecture_revision(self, project_id, revision=0):
        project_id = validate_project_id(project_id)
        nonnegative_integer(revision, 'revision')
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            return self._architecture_value(connection, project_id, revision)

    def architecture_revision_count(self, project_id):
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            return int(connection.execute('SELECT COUNT(*) AS total FROM architecture_revisions WHERE project_id=?',
                                          (project_id,)).fetchone()['total'])

    def architecture_revision_history(self, project_id, *, offset=0, limit=100):
        project_id = validate_project_id(project_id)
        nonnegative_integer(offset, 'offset')
        number(limit, 'limit')
        if limit > 100:
            raise ValueError('architecture history limit must be at most 100')
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            head = self._architecture_head(connection, project_id)
            revisions = connection.execute('''SELECT r.revision,r.base_revision,r.definition_fingerprint,r.actor,r.created_at,
                a.actor AS adopted_by,a.adopted_at,a.rationale FROM architecture_revisions r
                LEFT JOIN architecture_adoptions a ON a.project_id=r.project_id AND a.revision=r.revision
                WHERE r.project_id=? ORDER BY r.revision LIMIT ? OFFSET ?''', (project_id, limit, offset)).fetchall()
            return [{'project_id': project_id, 'revision': int(row['revision']), 'base_revision': int(row['base_revision']),
                     'current_adopted_revision': head, 'state': 'adopted' if row['adopted_by'] is not None else 'proposed',
                     'definition_fingerprint': row['definition_fingerprint'],
                     'provenance': {'proposed_by': row['actor'], 'proposed_at': row['created_at'],
                                    'adopted_by': row['adopted_by'], 'adopted_at': row['adopted_at'],
                                    'adoption_rationale': row['rationale']}} for row in revisions]

    @staticmethod
    def _architecture_replay(connection, project_id, request_id, request_fingerprint):
        row = connection.execute('SELECT request_fingerprint,result_json FROM architecture_requests WHERE project_id=? AND request_id=?',
                                 (project_id, request_id)).fetchone()
        if row is None:
            return None
        if row['request_fingerprint'] != request_fingerprint:
            raise RequirementConflictError('architecture request_id conflicts with durable history')
        return json.loads(row['result_json'])

    def _architecture_record_request(self, connection, project_id, operation, request_id, request_fingerprint, result, actor, timestamp):
        connection.execute('INSERT INTO architecture_requests(project_id,request_id,operation,request_fingerprint,result_json,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                           (project_id, request_id, operation, request_fingerprint, canonical_json(result), actor, timestamp))
        self._append_event(connection, project_id=project_id, requirement_id=None,
                           event_type='architecture_' + ('proposed' if operation == 'propose' else 'adopted'),
                           actor=actor, request_id=request_id,
                           payload={'revision': result['revision'], 'definition_fingerprint': result['definition_fingerprint'],
                                    'authority_class': 'engineering_design', 'acceptance': 'not_inferred'}, occurred_at=timestamp)

    @staticmethod
    def _architecture_canonical_link(connection, project_id, link):
        """Resolve original authority; packet links carry intent, never nested execution plans."""
        kind = link['kind']
        if kind == 'requirement':
            row = connection.execute('''SELECT r.requirement_id,r.title,r.statement,r.category,r.current_revision,
                r.lifecycle_status,r.source_anchor,v.rationale FROM requirements r JOIN requirement_revisions v
                ON v.project_id=r.project_id AND v.requirement_id=r.requirement_id AND v.revision=r.current_revision
                WHERE r.project_id=? AND r.requirement_id=?''', (project_id, link['requirement_id'])).fetchone()
        elif kind == 'goal':
            row = connection.execute('SELECT goal_node_id,node_type,title,payload_json,source_anchor_json FROM goal_nodes WHERE project_id=? AND goal_node_id=?',
                                     (project_id, link['goal_node_id'])).fetchone()
        elif kind == 'packet':
            row = connection.execute('''SELECT change_id,packet_id,title,objective,rationale,spec_revision,
                requirement_ids_json,goal_ids_json,in_scope_json,out_of_scope_json,invariants_json,completion_criteria_json
                FROM implementation_packets WHERE project_id=? AND change_id=? AND packet_id=?''',
                                     (project_id, link['change_id'], link['packet_id'])).fetchone()
        else:
            row = connection.execute('''SELECT evidence_id,project_id,requirement_id,verification_kind,outcome,reference,
                actor,metadata_json,recorded_at FROM verification_evidence WHERE project_id=? AND evidence_id=?''',
                                     (project_id, link['evidence_id'])).fetchone()
        if row is None:
            raise ChangeControlBlockedError('architecture_link_not_found', details={'link': link})
        return {key.removesuffix('_json'): json.loads(raw) if key.endswith('_json') else raw for key, raw in dict(row).items()}

    def _validate_architecture_definition(self, connection, project_id, definition, current):
        for name in ENTITY_LISTS.values():
            for item in definition[name]:
                for link in item['links']:
                    self._architecture_canonical_link(connection, project_id, link)
        proposed_decisions = {item['id']: item for item in definition['decisions']}
        for decision in current['definition']['decisions']:
            if proposed_decisions.get(decision['id']) != decision:
                raise ChangeControlBlockedError('architecture_adopted_decision_immutable', details={'decision_id': decision['id']})

    def propose_architecture(self, project_id, definition, *, expected_revision, actor, request_id):
        project_id = validate_project_id(project_id)
        expected_revision = nonnegative_integer(expected_revision, 'expected_revision')
        actor, request_id = text(actor, 'actor'), text(request_id, 'request_id')
        normalized = normalize_definition(definition)
        request_fingerprint = fingerprint({'operation': 'propose', 'expected_revision': expected_revision,
                                           'definition': definition, 'actor': actor})
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            replay = self._architecture_replay(connection, project_id, request_id, request_fingerprint)
            if replay is not None:
                return replay
            current = self._architecture_value(connection, project_id)
            if current['revision'] != expected_revision:
                raise ChangeControlBlockedError('architecture_revision_stale', details={'expected_revision': expected_revision,
                                                                                        'current_adopted_revision': current['revision']})
            self._validate_architecture_definition(connection, project_id, normalized, current)
            revision = int(connection.execute('SELECT COALESCE(MAX(revision),0)+1 AS revision FROM architecture_revisions WHERE project_id=?',
                                              (project_id,)).fetchone()['revision'])
            timestamp = _utc_now()
            digest = fingerprint(normalized)
            connection.execute('INSERT INTO architecture_revisions(project_id,revision,base_revision,definition_json,definition_fingerprint,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                               (project_id, revision, expected_revision, canonical_json(normalized), digest, actor, timestamp))
            result = {'status': 'success', 'contract': ARCHITECTURE_CONTRACT, 'project_id': project_id, 'revision': revision,
                      'base_revision': expected_revision, 'state': 'proposed', 'definition_fingerprint': digest,
                      'provenance': {'proposed_by': actor, 'proposed_at': timestamp},
                      'acceptance': 'not_inferred', 'verification': 'not_inferred'}
            self._architecture_record_request(connection, project_id, 'propose', request_id, request_fingerprint, result, actor, timestamp)
            return result

    def adopt_architecture(self, project_id, revision, *, expected_revision, rationale, actor, request_id):
        project_id = validate_project_id(project_id)
        revision, expected_revision = positive_integer(revision, 'revision'), nonnegative_integer(expected_revision, 'expected_revision')
        rationale, actor, request_id = text(rationale, 'rationale'), text(actor, 'actor'), text(request_id, 'request_id')
        request_fingerprint = fingerprint({'operation': 'adopt', 'revision': revision, 'expected_revision': expected_revision,
                                           'rationale': rationale, 'actor': actor})
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            replay = self._architecture_replay(connection, project_id, request_id, request_fingerprint)
            if replay is not None:
                return replay
            current = self._architecture_value(connection, project_id)
            selected = self._architecture_value(connection, project_id, revision)
            if current['revision'] != expected_revision or selected['base_revision'] != current['revision']:
                raise ChangeControlBlockedError('architecture_revision_stale')
            if selected['state'] != 'proposed':
                raise ChangeControlBlockedError('architecture_revision_already_adopted')
            self._validate_architecture_definition(connection, project_id, selected['definition'], current)
            timestamp = _utc_now()
            connection.execute('INSERT INTO architecture_adoptions(project_id,revision,previous_revision,rationale,actor,adopted_at) VALUES(?,?,?,?,?,?)',
                               (project_id, revision, expected_revision, rationale, actor, timestamp))
            result = {'status': 'success', 'contract': ARCHITECTURE_CONTRACT, 'project_id': project_id,
                      'revision': revision, 'previous_revision': expected_revision, 'state': 'adopted',
                      'definition_fingerprint': selected['definition_fingerprint'],
                      'provenance': {**selected['provenance'], 'adopted_by': actor, 'adopted_at': timestamp, 'adoption_rationale': rationale},
                      'acceptance': 'not_inferred', 'verification': 'not_inferred'}
            self._architecture_record_request(connection, project_id, 'adopt', request_id, request_fingerprint, result, actor, timestamp)
            return result

    def _validate_architecture_refs(self, connection, project_id, refs):
        normalized = normalize_architecture_refs(refs)
        if not normalized:
            return normalized, None
        selected = self._architecture_value(connection, project_id, normalized[0]['revision'])
        if selected['state'] != 'adopted':
            raise ChangeControlBlockedError('architecture_revision_not_adopted')
        selected_closure(selected['definition'], normalized)
        return normalized, selected

    def validate_architecture_refs(self, project_id, refs):
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            normalized, _ = self._validate_architecture_refs(connection, project_id, refs)
            return normalized

    def resolve_architecture_refs(self, project_id, refs):
        project_id = validate_project_id(project_id)
        with self.consistent_read():
            with self._read_connection() as connection:
                self._ensure_project(connection, project_id)
                normalized, selected = self._validate_architecture_refs(connection, project_id, refs)
                if not normalized:
                    return None
                closure = selected_closure(selected['definition'], normalized)
                current = self._architecture_value(connection, project_id)
                currentness = applicability(closure, current['definition'])
                unique_links = {canonical_json(link): link for name in ENTITY_LISTS.values() for entity in closure[name] for link in entity['links']}
                canonical_links = [{'link': link, 'content': self._architecture_canonical_link(connection, project_id, link)}
                                   for _, link in sorted(unique_links.items())]
                return {'contract': ARCHITECTURE_CONTEXT_CONTRACT,
                        'selected_context': {'refs': list(normalized), 'revision': selected['revision'], 'definition': closure,
                                             'provenance': selected['provenance'], 'canonical_links': canonical_links},
                        'applicability': currentness,
                        'gaps': [{'code': 'architecture_authority_stale', **currentness}] if currentness['status'] == 'stale' else []}
