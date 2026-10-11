"""Immutable executor selections and explicit provider capability observations."""
from __future__ import annotations

import json
from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.external_work import canonical_json
from flow_of_work_mcp.core.errors import RequirementConflictError


class PacketExecutorStoreMixin:
    def migrate_packet_provider_admissions(self) -> None:
        with self._transaction() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS packet_provider_admissions(
                project_id TEXT NOT NULL, outbox_id TEXT NOT NULL,
                change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                capability_identity INTEGER NOT NULL, binding_identity_json TEXT NOT NULL,
                context_sha256 TEXT NOT NULL, unit_key TEXT NOT NULL,
                actor TEXT NOT NULL, admitted_at TEXT NOT NULL,
                PRIMARY KEY(project_id,outbox_id),
                FOREIGN KEY(project_id,outbox_id) REFERENCES packet_provider_outbox(project_id,outbox_id),
                FOREIGN KEY(capability_identity) REFERENCES packet_provider_capabilities(capability_identity),
                FOREIGN KEY(project_id,change_id,packet_id) REFERENCES implementation_packets(project_id,change_id,packet_id))''')
            connection.execute('''CREATE INDEX IF NOT EXISTS packet_provider_admissions_context
                ON packet_provider_admissions(project_id,change_id,packet_id,unit_key,context_sha256)''')
            connection.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(55,?)', (_utc_now(),))

    @staticmethod
    def _provider_admission_value(row):
        if row is None:
            return None
        item = dict(row)
        item['binding_identity'] = json.loads(item.pop('binding_identity_json'))
        return item

    def packet_provider_capability(self, project_id, capability_identity):
        with self._read_connection() as connection:
            row = connection.execute('SELECT * FROM packet_provider_capabilities WHERE project_id=? AND capability_identity=?',
                                     (project_id, capability_identity)).fetchone()
            if row is None:
                raise RequirementConflictError('packet_provider_capability_not_found')
            item = dict(row)
            item['binding_identity'] = json.loads(item.pop('binding_identity_json'))
            item['capability'] = json.loads(item.pop('capability_json'))
            item['supported'] = bool(item['supported'])
            return item

    def packet_provider_admission(self, project_id, outbox_id):
        with self._read_connection() as connection:
            row = connection.execute('SELECT * FROM packet_provider_admissions WHERE project_id=? AND outbox_id=?',
                                     (project_id, outbox_id)).fetchone()
            return self._provider_admission_value(row)

    def packet_provider_admissions(self, project_id, change_id, packet_id, *, limit=256):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ValueError('packet provider admission limit must be between 1 and 256')
        with self._read_connection() as connection:
            rows = connection.execute('''SELECT admission.* FROM packet_provider_admissions admission
                JOIN packet_provider_outbox outbox USING(project_id,outbox_id)
                WHERE admission.project_id=? AND admission.change_id=? AND admission.packet_id=?
                ORDER BY outbox.ordinal LIMIT ?''', (project_id, change_id, packet_id, limit))
            return [self._provider_admission_value(row) for row in rows]

    def packet_provider_command_admission(self, project_id, change_id, packet_id, delivery_fingerprint):
        with self._read_connection() as connection:
            row = connection.execute('''SELECT admission.* FROM packet_provider_admissions admission
                JOIN packet_provider_outbox outbox USING(project_id,outbox_id)
                WHERE admission.project_id=? AND admission.change_id=? AND admission.packet_id=?
                  AND outbox.delivery_fingerprint=? ORDER BY outbox.ordinal DESC LIMIT 1''',
                (project_id, change_id, packet_id, delivery_fingerprint)).fetchone()
            return self._provider_admission_value(row)

    def record_packet_provider_admission(self, project_id, change_id, packet_id, *, outbox_id, capability, command, actor):
        with self._transaction() as connection:
            entry = self.packet_provider_outbox_entry(project_id, outbox_id)
            actual = self.packet_provider_capability(project_id, capability['capability_identity'])
            context = command.validation_context
            if (entry['command'] != command.as_payload() or entry['change_id'] != change_id or entry['packet_id'] != packet_id
                    or actual['change_id'] != change_id or actual['packet_id'] != packet_id or not actual['supported']
                    or any(actual[field] != context[field] for field in ('authority_fingerprint', 'spec_revision', 'plan_revision'))):
                raise RequirementConflictError('packet_provider_admission_mismatch')
            existing = self.packet_provider_admission(project_id, outbox_id)
            if existing is not None:
                if (existing['binding_identity'] != actual['binding_identity'] or existing['context_sha256'] != context['context_sha256']
                        or existing['unit_key'] != command.flow_unit_ref):
                    raise RequirementConflictError('packet_provider_admission_conflict')
                return existing
            connection.execute('''INSERT INTO packet_provider_admissions VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (project_id, outbox_id, change_id, packet_id, actual['capability_identity'],
                 canonical_json(actual['binding_identity']), context['context_sha256'], command.flow_unit_ref, actor, _utc_now()))
            return self.packet_provider_admission(project_id, outbox_id)

    def packet_provider_ack_entry(self, project_id, change_id, packet_id, *, unit_key, context_sha256):
        with self._read_connection() as connection:
            row = connection.execute('''SELECT outbox.outbox_id FROM packet_provider_admissions admission
                JOIN packet_provider_outbox outbox USING(project_id,outbox_id)
                WHERE admission.project_id=? AND admission.change_id=? AND admission.packet_id=?
                  AND admission.unit_key=? AND admission.context_sha256=?
                  AND outbox.state='delivered' AND outbox.operation IN ('add','edit')
                ORDER BY outbox.ordinal DESC LIMIT 1''', (project_id, change_id, packet_id, unit_key, context_sha256)).fetchone()
            return self._packet_provider_outbox_value(connection, project_id, row['outbox_id']) if row is not None else None

    def migrate_packet_executor(self) -> None:
        with self._transaction() as connection:
            ddl = '''
                CREATE TABLE IF NOT EXISTS packet_executor_selections(
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    selection_revision INTEGER NOT NULL CHECK(selection_revision=1),
                    executor TEXT NOT NULL CHECK(executor IN ('external_agent','provider')),
                    provider_kind TEXT NOT NULL, spec_revision INTEGER NOT NULL,
                    plan_revision INTEGER NOT NULL, authority_fingerprint TEXT NOT NULL,
                    actor TEXT NOT NULL, selected_at TEXT NOT NULL,
                    PRIMARY KEY(project_id,change_id,packet_id),
                    FOREIGN KEY(project_id,change_id,packet_id)
                        REFERENCES implementation_packets(project_id,change_id,packet_id));
                CREATE TABLE IF NOT EXISTS packet_provider_capabilities(
                    capability_identity INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL, change_id TEXT NOT NULL, packet_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL, binding_identity_json TEXT NOT NULL,
                    flow_binding_generation INTEGER NOT NULL CHECK(flow_binding_generation>=0),
                    selection_revision INTEGER NOT NULL CHECK(selection_revision=1),
                    selection_fingerprint TEXT NOT NULL, spec_revision INTEGER NOT NULL,
                    plan_revision INTEGER NOT NULL, authority_fingerprint TEXT NOT NULL,
                    supported INTEGER NOT NULL CHECK(supported IN (0,1)), reason TEXT NOT NULL,
                    capability_json TEXT NOT NULL, actor TEXT NOT NULL, observed_at TEXT NOT NULL,
                    FOREIGN KEY(project_id,change_id,packet_id)
                        REFERENCES implementation_packets(project_id,change_id,packet_id));
                CREATE TABLE IF NOT EXISTS packet_executor_requests(
                    project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
                    actor TEXT NOT NULL, operation TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    PRIMARY KEY(project_id,request_id));
            '''
            for statement in ddl.split(';'):
                if statement.strip():
                    connection.execute(statement)
            connection.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(54,?)', (_utc_now(),))

    def packet_executor_state(self, project_id: str, change_id: str, packet_id: str) -> Mapping[str, object]:
        with self._read_connection() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            key = (project_id, change_id, packet_id)
            selection = connection.execute('SELECT * FROM packet_executor_selections WHERE project_id=? AND change_id=? AND packet_id=?', key).fetchone()
            capabilities = []
            for row in connection.execute('SELECT * FROM packet_provider_capabilities WHERE project_id=? AND change_id=? AND packet_id=? ORDER BY capability_identity', key):
                item = dict(row)
                item['binding_identity'] = json.loads(item.pop('binding_identity_json'))
                item['capability'] = json.loads(item.pop('capability_json'))
                item['supported'] = bool(item['supported'])
                capabilities.append(item)
            return {'selection': dict(selection) if selection is not None else None, 'capabilities': capabilities}

    def record_executor_selection(self, project_id: str, change_id: str, packet_id: str,
                                  selection: Mapping[str, object], *, actor: str) -> Mapping[str, object]:
        with self._transaction() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            connection.execute('''INSERT INTO packet_executor_selections(project_id,change_id,packet_id,
                selection_revision,executor,provider_kind,spec_revision,plan_revision,authority_fingerprint,actor,selected_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (project_id, change_id, packet_id, 1, selection['executor'], selection.get('provider_kind', ''),
                 selection['spec_revision'], selection['plan_revision'], selection['authority_fingerprint'], actor, _utc_now()))
            self.set_external_work_mode(project_id, change_id, packet_id, str(selection['executor']))
            return self.packet_executor_state(project_id, change_id, packet_id)['selection']

    def record_provider_capability(self, project_id: str, change_id: str, packet_id: str,
                                   capability: Mapping[str, object], *, actor: str) -> Mapping[str, object]:
        with self._transaction() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            cursor = connection.execute('''INSERT INTO packet_provider_capabilities(project_id,change_id,packet_id,
                provider_kind,binding_identity_json,flow_binding_generation,selection_revision,selection_fingerprint,
                spec_revision,plan_revision,authority_fingerprint,supported,reason,capability_json,actor,observed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (project_id, change_id, packet_id, capability['provider_kind'], canonical_json(capability['binding_identity']),
                 capability['flow_binding_generation'], capability['selection_revision'], capability['selection_fingerprint'],
                 capability['spec_revision'], capability['plan_revision'], capability['authority_fingerprint'],
                 int(bool(capability['supported'])), capability['reason'], canonical_json(capability['capability']), actor, _utc_now()))
            return next(row for row in self.packet_executor_state(project_id, change_id, packet_id)['capabilities']
                        if row['capability_identity'] == cursor.lastrowid)

    def executor_request_replay(self, project_id: str, request_id: str, request_fingerprint: str):
        with self._read_connection() as connection:
            row = connection.execute('SELECT request_fingerprint,result_json FROM packet_executor_requests WHERE project_id=? AND request_id=?', (project_id, request_id)).fetchone()
            if row is None:
                return None
            if row['request_fingerprint'] != request_fingerprint:
                raise RequirementConflictError('packet_executor_request_conflict')
            return json.loads(row['result_json'])

    def record_executor_request(self, project_id: str, request_id: str, request_fingerprint: str,
                                result: Mapping[str, object], *, actor: str, operation: str) -> None:
        with self._transaction() as connection:
            timestamp = _utc_now()
            connection.execute('INSERT INTO packet_executor_requests VALUES(?,?,?,?,?,?,?)',
                               (project_id, request_id, request_fingerprint, canonical_json(result), actor, operation, timestamp))
            self._append_event(connection, project_id=project_id, requirement_id=None,
                event_type='packet_executor_' + operation, actor=actor, request_id=request_id,
                payload={'request_fingerprint': request_fingerprint, 'result': dict(result)}, occurred_at=timestamp)
