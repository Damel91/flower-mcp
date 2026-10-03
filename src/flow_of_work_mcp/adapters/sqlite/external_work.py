"""Canonical standalone packet declarations and immutable host report history."""
from __future__ import annotations

import json
from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.external_work import canonical_json, fingerprint
from flow_of_work_mcp.core.errors import RequirementConflictError


class ExternalWorkStoreMixin:
    def migrate_external_work(self) -> None:
        with self._transaction() as connection:
            migration_ddl = '''
                CREATE TABLE IF NOT EXISTS external_packet_authority(
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    validation_version INTEGER NOT NULL DEFAULT 0,
                    consumption_mode TEXT NOT NULL DEFAULT 'provider',
                    criterion_statement_fingerprint TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id, packet_id),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id));
                CREATE TABLE IF NOT EXISTS packet_criteria(
                    criterion_identity INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    number INTEGER NOT NULL CHECK(number > 0), statement TEXT NOT NULL,
                    active INTEGER NOT NULL, UNIQUE(project_id, change_id, packet_id, number),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id));
                CREATE TABLE IF NOT EXISTS packet_criterion_history(
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    criterion_identity INTEGER NOT NULL REFERENCES packet_criteria(criterion_identity),
                    spec_revision INTEGER NOT NULL, statement TEXT NOT NULL,
                    active INTEGER NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS packet_unit_identities(
                    project_id TEXT NOT NULL, work_plan_id TEXT NOT NULL,
                    client_unit_key TEXT NOT NULL, unit_number INTEGER NOT NULL,
                    PRIMARY KEY(project_id,work_plan_id,client_unit_key),
                    UNIQUE(project_id,work_plan_id,unit_number),
                    FOREIGN KEY(project_id,work_plan_id) REFERENCES packet_work_plans(project_id,work_plan_id));
                CREATE TABLE IF NOT EXISTS external_work_reports(
                    report_identity INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    report_key TEXT NOT NULL, unit_key TEXT NOT NULL,
                    spec_revision INTEGER NOT NULL, plan_revision INTEGER NOT NULL,
                    authority_fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL, disposition TEXT NOT NULL,
                    reconciled INTEGER NOT NULL DEFAULT 0,
                    actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    UNIQUE(project_id,report_key),
                    FOREIGN KEY(project_id,change_id,packet_id)
                        REFERENCES implementation_packets(project_id,change_id,packet_id));
                CREATE TABLE IF NOT EXISTS external_work_report_selections(
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    unit_key TEXT NOT NULL, authority_fingerprint TEXT NOT NULL,
                    report_key TEXT NOT NULL, rationale TEXT NOT NULL,
                    PRIMARY KEY(project_id,change_id,packet_id,unit_key,authority_fingerprint));
                CREATE TABLE IF NOT EXISTS external_work_requests(
                    project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
                    PRIMARY KEY(project_id,request_id));
            '''
            for statement in migration_ddl.split(';'):
                if statement.strip():
                    connection.execute(statement)
            self._ensure_columns(connection, 'external_work_reports', (('predecessor_reports_json', "TEXT NOT NULL DEFAULT '{}'"),))
            self._ensure_columns(connection, 'packet_work_plan_units', (
                ('unit_number', 'INTEGER NOT NULL DEFAULT 0'),
                ('implements_json', "TEXT NOT NULL DEFAULT '[]'"),
                ('provides_json', "TEXT NOT NULL DEFAULT '[]'"),
                ('requires_json', "TEXT NOT NULL DEFAULT '[]'"),
                ('verifies_json', "TEXT NOT NULL DEFAULT '[]'"),
            ))
            rows = connection.execute('''SELECT project_id, work_plan_id, plan_revision,
                    client_unit_key FROM packet_work_plan_units AS units
                    WHERE unit_number=0 OR NOT EXISTS(SELECT 1 FROM packet_unit_identities AS identities WHERE identities.project_id=units.project_id AND identities.work_plan_id=units.work_plan_id AND identities.client_unit_key=units.client_unit_key)
                    ORDER BY project_id, work_plan_id, plan_revision, unit_ordinal''').fetchall()
            for row in rows:
                unit_number = self._external_unit_number(connection, row['project_id'], row['work_plan_id'], row['client_unit_key'])
                connection.execute('''UPDATE packet_work_plan_units SET unit_number=?
                    WHERE project_id=? AND work_plan_id=? AND plan_revision=? AND client_unit_key=?''',
                    (unit_number, row['project_id'], row['work_plan_id'], row['plan_revision'], row['client_unit_key']))
            connection.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(50,?)', (_utc_now(),))

    @staticmethod
    def _external_unit_number(connection, project_id: str, work_plan_id: str, key: str) -> int:
        row = connection.execute('''SELECT unit_number FROM packet_unit_identities
            WHERE project_id=? AND work_plan_id=? AND client_unit_key=?''', (project_id, work_plan_id, key)).fetchone()
        if row:
            return int(row['unit_number'])
        next_number = int(connection.execute('''SELECT COALESCE(MAX(unit_number),0)+1 AS n
            FROM packet_unit_identities WHERE project_id=? AND work_plan_id=?''', (project_id, work_plan_id)).fetchone()['n'])
        connection.execute('INSERT INTO packet_unit_identities VALUES(?,?,?,?)', (project_id, work_plan_id, key, next_number))
        return next_number

    def external_work_state(self, project_id: str, change_id: str, packet_id: str) -> Mapping[str, object]:
        with self._read_connection() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            row = connection.execute('''SELECT * FROM external_packet_authority
                WHERE project_id=? AND change_id=? AND packet_id=?''', (project_id, change_id, packet_id)).fetchone()
            criteria = [dict(item) for item in connection.execute('''SELECT number,statement,active
                FROM packet_criteria WHERE project_id=? AND change_id=? AND packet_id=? ORDER BY number''',
                (project_id, change_id, packet_id)).fetchall()]
            history = [dict(item) for item in connection.execute('''SELECT c.number,h.spec_revision,h.statement,h.active,h.actor,h.occurred_at
                FROM packet_criterion_history h JOIN packet_criteria c USING(criterion_identity)
                WHERE c.project_id=? AND c.change_id=? AND c.packet_id=? ORDER BY h.history_id''',
                (project_id, change_id, packet_id)).fetchall()]
            reports = []
            for report in connection.execute('''SELECT * FROM external_work_reports
                WHERE project_id=? AND change_id=? AND packet_id=? ORDER BY report_identity''', (project_id, change_id, packet_id)).fetchall():
                item = dict(report)
                item['payload'] = json.loads(item.pop('payload_json'))
                item['predecessor_reports'] = json.loads(item.pop('predecessor_reports_json'))
                reports.append(item)
            selections = [dict(item) for item in connection.execute('''SELECT * FROM external_work_report_selections
                WHERE project_id=? AND change_id=? AND packet_id=?''', (project_id, change_id, packet_id)).fetchall()]
            return {'validation_version': int(row['validation_version']) if row else 0,
                    'consumption_mode': str(row['consumption_mode']) if row else 'provider',
                    'criterion_statement_fingerprint': str(row['criterion_statement_fingerprint']) if row else '',
                    'criteria': criteria, 'criterion_history': history, 'reports': reports, 'selections': selections}

    def external_work_request_replay(self, project_id: str, request_id: str, request_fingerprint: str):
        with self._read_connection() as connection:
            row = connection.execute('SELECT * FROM external_work_requests WHERE project_id=? AND request_id=?', (project_id, request_id)).fetchone()
            if row is None:
                return None
            if row['request_fingerprint'] != request_fingerprint:
                raise RequirementConflictError('external_work_request_conflict')
            result = json.loads(row['result_json'])
            if result.get('artifact_kind') == 'implementation_plan':
                generation = self._artifact_generation_value(connection, int(result['generation_id']))
                result['content'] = next(a['content'] for a in generation['artifacts'] if a['artifact_kind'] == 'implementation_plan')
            return result

    def record_external_work_request(self, project_id: str, request_id: str, request_fingerprint: str,
                                     result: Mapping[str, object], *, actor: str, operation: str) -> None:
        result = {k: v for k, v in result.items() if not (k == 'content' and result.get('artifact_kind') == 'implementation_plan')}
        with self._transaction() as connection:
            connection.execute('INSERT INTO external_work_requests VALUES(?,?,?,?)', (project_id, request_id, request_fingerprint, canonical_json(result)))
            self._append_event(connection, project_id=project_id, requirement_id=None,
                               event_type='external_work_' + operation, actor=actor, request_id=request_id,
                               payload={'request_fingerprint': request_fingerprint, 'result': dict(result)}, occurred_at=_utc_now())

    def upgrade_external_criteria(self, project_id: str, change_id: str, packet_id: str,
                                 statements: list[str], *, spec_revision: int, actor: str) -> None:
        with self._transaction() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            row = connection.execute('''SELECT validation_version FROM external_packet_authority
                WHERE project_id=? AND change_id=? AND packet_id=?''', (project_id, change_id, packet_id)).fetchone()
            if row and row['validation_version']:
                raise RequirementConflictError('packet_validation_already_upgraded')
            connection.execute('''INSERT INTO external_packet_authority(project_id,change_id,packet_id,validation_version,criterion_statement_fingerprint)
                VALUES(?,?,?,1,?) ON CONFLICT(project_id,change_id,packet_id) DO UPDATE SET validation_version=1,criterion_statement_fingerprint=excluded.criterion_statement_fingerprint''',
                (project_id, change_id, packet_id, fingerprint(statements)))
            for num, statement in enumerate(statements, start=1):
                cursor = connection.execute('''INSERT INTO packet_criteria(project_id,change_id,packet_id,number,statement,active)
                    VALUES(?,?,?,?,?,1)''', (project_id, change_id, packet_id, num, statement))
                connection.execute('''INSERT INTO packet_criterion_history(criterion_identity,spec_revision,statement,active,actor,occurred_at)
                    VALUES(?,?,?,1,?,?)''', (cursor.lastrowid, spec_revision, statement, actor, _utc_now()))

    def write_external_criterion(self, project_id: str, change_id: str, packet_id: str,
                                 number: int, statement: str, active: bool, *, spec_revision: int, actor: str) -> None:
        with self._transaction() as connection:
            connection.execute('''INSERT INTO packet_criteria(project_id,change_id,packet_id,number,statement,active)
                VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,change_id,packet_id,number) DO UPDATE SET statement=excluded.statement,active=excluded.active''',
                (project_id, change_id, packet_id, number, statement, int(active)))
            row = connection.execute('''SELECT criterion_identity FROM packet_criteria WHERE project_id=? AND change_id=? AND packet_id=? AND number=?''', (project_id, change_id, packet_id, number)).fetchone()
            connection.execute('''INSERT INTO packet_criterion_history(criterion_identity,spec_revision,statement,active,actor,occurred_at)
                VALUES(?,?,?,?,?,?)''', (row['criterion_identity'], spec_revision, statement, int(active), actor, _utc_now()))
            statements = [r['statement'] for r in connection.execute('''SELECT statement FROM packet_criteria
                WHERE project_id=? AND change_id=? AND packet_id=? AND active=1 ORDER BY number''', (project_id, change_id, packet_id)).fetchall()]
            connection.execute('''UPDATE external_packet_authority SET criterion_statement_fingerprint=?
                WHERE project_id=? AND change_id=? AND packet_id=?''', (fingerprint(statements), project_id, change_id, packet_id))

    def synchronize_external_criterion_view(self, project_id: str, change_id: str, packet_id: str, statements: list[str]) -> None:
        with self._transaction() as connection:
            connection.execute('UPDATE external_packet_authority SET criterion_statement_fingerprint=? WHERE project_id=? AND change_id=? AND packet_id=?',
                               (fingerprint(statements), project_id, change_id, packet_id))

    def set_external_work_mode(self, project_id: str, change_id: str, packet_id: str, mode: str) -> None:
        with self._transaction() as connection:
            connection.execute('''INSERT INTO external_packet_authority(project_id,change_id,packet_id,consumption_mode)
                VALUES(?,?,?,?) ON CONFLICT(project_id,change_id,packet_id) DO UPDATE SET consumption_mode=excluded.consumption_mode''', (project_id, change_id, packet_id, mode))

    def record_external_outcome(self, project_id: str, change_id: str, packet_id: str,
                                payload: Mapping[str, object], *, disposition: str, actor: str, predecessor_reports: Mapping[str, str]) -> Mapping[str, object]:
        with self._transaction() as connection:
            report_key = str(payload['report_key'])
            digest = fingerprint(payload)
            existing = connection.execute('SELECT * FROM external_work_reports WHERE project_id=? AND report_key=?', (project_id, report_key)).fetchone()
            if existing:
                if existing['payload_fingerprint'] != digest or existing['change_id'] != change_id or existing['packet_id'] != packet_id or existing['actor'] != actor:
                    raise RequirementConflictError('external_outcome_report_key_conflict')
                return {'report_key': report_key, 'disposition': existing['disposition'], 'replayed': True}
            connection.execute('''INSERT INTO external_work_reports(project_id,change_id,packet_id,report_key,unit_key,spec_revision,plan_revision,
                authority_fingerprint,payload_json,payload_fingerprint,disposition,actor,occurred_at,predecessor_reports_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (project_id, change_id, packet_id, report_key, payload['unit_key'], payload['expected_spec_revision'], payload['expected_plan_revision'], payload['authority_fingerprint'],
                 canonical_json(payload), digest, disposition, actor, _utc_now(), canonical_json(predecessor_reports)))
            return {'report_key': report_key, 'disposition': disposition, 'replayed': False}

    def select_external_outcome(self, project_id: str, change_id: str, packet_id: str,
                               report: Mapping[str, object], rationale: str) -> None:
        with self._transaction() as connection:
            connection.execute('''INSERT INTO external_work_report_selections VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(project_id,change_id,packet_id,unit_key,authority_fingerprint)
                DO UPDATE SET report_key=excluded.report_key,rationale=excluded.rationale''',
                (project_id, change_id, packet_id, report['unit_key'], report['authority_fingerprint'], report['report_key'], rationale))
            connection.execute('''UPDATE external_work_reports SET reconciled=1
                WHERE project_id=? AND change_id=? AND packet_id=? AND unit_key=? AND authority_fingerprint=?''',
                (project_id, change_id, packet_id, report['unit_key'], report['authority_fingerprint']))
