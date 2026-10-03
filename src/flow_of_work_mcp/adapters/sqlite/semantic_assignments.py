"""Canonical SQLite semantic assignment execution and immutable result history."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping
from uuid import uuid4

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


class SemanticAssignmentStoreMixin:
    def ensure_semantic_project(self, project_id: str) -> None:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)

    def migrate_semantic_assignments(self) -> None:
        """Add execution history without rewriting any project authority."""

        with self._transaction() as connection:
            # execute individually: executescript would commit an active transaction.
            statements = (
                """CREATE TABLE IF NOT EXISTS semantic_assignments (
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    assignment_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('host', 'internal')),
                    preparation_json TEXT NOT NULL,
                    preparation_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared', 'internal_running',
                        'internal_failed', 'internal_interrupted', 'validated', 'adopted')),
                    result_json TEXT NOT NULL DEFAULT '{}',
                    result_fingerprint TEXT NOT NULL DEFAULT '',
                    adoption_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, assignment_id)
                )""",
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_prepare_replay
                    ON semantic_assignments(project_id, request_id) WHERE request_id <> ''""",
                """CREATE TABLE IF NOT EXISTS semantic_assignment_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(project_id, assignment_id)
                        REFERENCES semantic_assignments(project_id, assignment_id) ON DELETE RESTRICT
                )""",
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_event_replay
                    ON semantic_assignment_events(project_id, operation, request_id)
                    WHERE request_id <> ''""",
            )
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(51, ?)",
                (_utc_now(),),
            )
            interrupted = connection.execute(
                "SELECT project_id, assignment_id FROM semantic_assignments WHERE state = 'internal_running'"
            ).fetchall()
            for row in interrupted:
                connection.execute(
                    "UPDATE semantic_assignments SET state = 'internal_interrupted' WHERE project_id = ? AND assignment_id = ?",
                    (row["project_id"], row["assignment_id"]),
                )
                self._semantic_event(
                    connection, str(row["project_id"]), str(row["assignment_id"]),
                    operation="internal_interrupted", payload={"reason": "execution_outcome_unknown"},
                    actor="runtime-recovery", request_id="",
                )

    def prepare_semantic_assignment(
        self, project_id: str, *, role: str, execution_mode: str,
        preparation: Mapping[str, object], actor: str, request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        semantic = {"role": role, "execution_mode": execution_mode, "preparation": dict(preparation)}
        fingerprint = _fingerprint(semantic)
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            if request_id:
                row = connection.execute(
                    "SELECT * FROM semantic_assignments WHERE project_id = ? AND request_id = ?",
                    (project_id, request_id),
                ).fetchone()
                if row is not None:
                    if row["preparation_fingerprint"] != fingerprint:
                        raise RequirementConflictError("semantic prepare request_id conflicts with durable input")
                    return self._semantic_view(connection, row)
            assignment_id = f"SEM-{uuid4().hex}"
            connection.execute(
                """INSERT INTO semantic_assignments(project_id, assignment_id, role,
                    execution_mode, preparation_json, preparation_fingerprint, state,
                    created_at, created_by, request_id) VALUES(?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?)""",
                (project_id, assignment_id, role, execution_mode, _encoded(preparation),
                 fingerprint, _utc_now(), actor, request_id),
            )
            self._semantic_event(connection, project_id, assignment_id, operation="prepare",
                                 payload=semantic, actor=actor, request_id="")
            return self._semantic_view(connection, self._semantic_row(connection, project_id, assignment_id))

    def semantic_assignment(self, project_id: str, assignment_id: str) -> Mapping[str, object]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            return self._semantic_view(connection, self._semantic_row(connection, project_id, assignment_id))

    def record_semantic_submission(
        self, project_id: str, assignment_id: str, *, result: Mapping[str, object],
        usable: bool, actor: str, request_id: str = "", internal: bool = False,
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        payload = {"result": dict(result), "usable": usable}
        operation = "internal_result" if internal else "submit"
        with self._transaction() as connection:
            row = self._semantic_row(connection, project_id, assignment_id)
            expected_mode = "internal" if internal else "host"
            if row["execution_mode"] != expected_mode:
                raise ChangeControlBlockedError("semantic_execution_mode_mismatch")
            if self._semantic_replay(connection, project_id, assignment_id, operation, request_id, payload):
                return self._semantic_view(connection, row)
            if not usable and not internal:
                # Invalid/stale host attempts remain history even after a usable
                # result, without replacing that result or its adoption receipt.
                self._semantic_event(connection, project_id, assignment_id, operation=operation,
                                     payload=payload, actor=actor, request_id=request_id)
                return self._semantic_view(connection, row)
            fingerprint = _fingerprint(result)
            if row["result_fingerprint"]:
                if row["result_fingerprint"] != fingerprint:
                    raise RequirementConflictError("semantic assignment already has a different usable result")
                if request_id:
                    self._semantic_event(connection, project_id, assignment_id, operation=operation,
                                         payload=payload, actor=actor, request_id=request_id)
                return self._semantic_view(connection, row)
            allowed_state = "internal_running" if internal else "prepared"
            if row["state"] != allowed_state:
                raise ChangeControlBlockedError("semantic_assignment_not_awaiting_result")
            if usable:
                connection.execute(
                    """UPDATE semantic_assignments SET state = 'validated',
                        result_json = ?, result_fingerprint = ?
                        WHERE project_id = ? AND assignment_id = ?""",
                    (_encoded(result), fingerprint, project_id, assignment_id),
                )
            elif internal:
                connection.execute(
                    "UPDATE semantic_assignments SET state = 'internal_failed' WHERE project_id = ? AND assignment_id = ?",
                    (project_id, assignment_id),
                )
            self._semantic_event(connection, project_id, assignment_id, operation=operation,
                                 payload=payload, actor=actor, request_id=request_id)
            return self._semantic_view(connection, self._semantic_row(connection, project_id, assignment_id))

    def begin_semantic_internal(
        self, project_id: str, assignment_id: str, *, actor: str, request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        with self._transaction() as connection:
            row = self._semantic_row(connection, project_id, assignment_id)
            if row["execution_mode"] != "internal":
                raise ChangeControlBlockedError("semantic_execution_mode_mismatch")
            if row["state"] != "prepared":
                raise ChangeControlBlockedError("semantic_internal_already_attempted")
            payload = {"assignment_id": assignment_id}
            # Even an equal replay must not invoke inference a second time.
            self._semantic_replay(connection, project_id, assignment_id, "execute_internal", request_id, payload)
            connection.execute(
                "UPDATE semantic_assignments SET state = 'internal_running' WHERE project_id = ? AND assignment_id = ?",
                (project_id, assignment_id),
            )
            self._semantic_event(connection, project_id, assignment_id, operation="execute_internal",
                                 payload=payload, actor=actor, request_id=request_id)
            return self._semantic_view(connection, self._semantic_row(connection, project_id, assignment_id))

    def adopt_semantic_assignment(
        self, project_id: str, assignment_id: str, *, adoption: Mapping[str, object],
        actor: str, request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        with self._transaction() as connection:
            row = self._semantic_row(connection, project_id, assignment_id)
            if self._semantic_replay(connection, project_id, assignment_id, "adopt", request_id, adoption):
                return self._semantic_view(connection, row)
            if row["state"] == "adopted":
                if _encoded(adoption) != row["adoption_json"]:
                    raise RequirementConflictError("semantic adoption conflicts with durable receipt")
                return self._semantic_view(connection, row)
            if row["state"] != "validated":
                raise ChangeControlBlockedError("semantic_result_not_validated")
            connection.execute(
                "UPDATE semantic_assignments SET state = 'adopted', adoption_json = ? WHERE project_id = ? AND assignment_id = ?",
                (_encoded(adoption), project_id, assignment_id),
            )
            self._semantic_event(connection, project_id, assignment_id, operation="adopt",
                                 payload=adoption, actor=actor, request_id=request_id)
            return self._semantic_view(connection, self._semantic_row(connection, project_id, assignment_id))

    def _semantic_row(self, connection, project_id: str, assignment_id: str) -> sqlite3.Row:
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM semantic_assignments WHERE project_id = ? AND assignment_id = ?",
            (project_id, assignment_id),
        ).fetchone()
        if row is None:
            raise ChangeControlBlockedError("semantic_assignment_not_found")
        return row

    @staticmethod
    def _semantic_view(connection, row: sqlite3.Row) -> Mapping[str, object]:
        event_count = int(connection.execute(
            "SELECT COUNT(*) FROM semantic_assignment_events WHERE project_id = ? AND assignment_id = ?",
            (row["project_id"], row["assignment_id"]),
        ).fetchone()[0])
        events = connection.execute(
            "SELECT operation, payload_json, occurred_at, actor FROM semantic_assignment_events WHERE project_id = ? AND assignment_id = ? ORDER BY event_id DESC LIMIT 8",
            (row["project_id"], row["assignment_id"]),
        ).fetchall()
        event_views = []
        for event in reversed(events):
            payload = json.loads(event["payload_json"])
            result = payload.get("result", {})
            audit = result.get("audit", {})
            summary = {
                "usable": payload.get("usable"),
                "reason": payload.get("reason", ""),
                "disposition": audit.get("disposition", ""),
                "terminal_reason": audit.get("terminal_reason", ""),
                "currentness_reason": result.get("currentness_reason", ""),
                "provenance": result.get("provenance", {}),
            }
            event_views.append({"operation": event["operation"], "payload": summary,
                                "occurred_at": event["occurred_at"], "actor": event["actor"]})
        return {
            "project_id": row["project_id"], "assignment_id": row["assignment_id"],
            "role": row["role"], "execution_mode": row["execution_mode"], "state": row["state"],
            "preparation": json.loads(row["preparation_json"]),
            "preparation_fingerprint": row["preparation_fingerprint"],
            "result": json.loads(row["result_json"]), "adoption": json.loads(row["adoption_json"]),
            "created_at": row["created_at"], "created_by": row["created_by"],
            "events": event_views, "event_count": event_count,
            "event_coverage": {"returned": len(event_views), "omitted": event_count - len(event_views),
                               "projection": "most recent bounded execution summaries"},
        }

    @staticmethod
    def _semantic_replay(connection, project_id, assignment_id, operation, request_id, payload) -> bool:
        if not request_id:
            return False
        row = connection.execute(
            "SELECT assignment_id, input_fingerprint FROM semantic_assignment_events WHERE project_id = ? AND operation = ? AND request_id = ?",
            (project_id, operation, request_id),
        ).fetchone()
        if row is None:
            return False
        if row["assignment_id"] != assignment_id or row["input_fingerprint"] != _fingerprint(payload):
            raise RequirementConflictError("semantic request_id conflicts with durable input")
        return True

    @staticmethod
    def _semantic_event(connection, project_id, assignment_id, *, operation, payload, actor, request_id):
        connection.execute(
            """INSERT INTO semantic_assignment_events(project_id, assignment_id, operation,
                input_fingerprint, payload_json, occurred_at, actor, request_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, assignment_id, operation, _fingerprint(payload), _encoded(payload),
             _utc_now(), actor, request_id),
        )
