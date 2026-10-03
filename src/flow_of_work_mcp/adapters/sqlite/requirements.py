"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    LifecycleStatus,
    VerificationKind,
    VerificationOutcome,
)
from flow_of_work_mcp.core.domain.identifiers import (
    normalize_requirement_statement,
    required_text,
    validate_project_id,
    validate_requirement_id,
)
from flow_of_work_mcp.core.errors import (
    ProjectNotFoundError,
    RequirementConflictError,
    RequirementNotFoundError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class RequirementStoreMixin:
    def create_project(self, project_id: str, name: str, *, actor: str) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        name = required_text(name, "name")
        actor = required_text(actor, "actor")
        created_at = _utc_now()
        with self._transaction() as connection:
            try:
                connection.execute(
                    "INSERT INTO projects(project_id, name, created_at, created_by) VALUES (?, ?, ?, ?)",
                    (project_id, name, created_at, actor),
                )
                connection.execute(
                    "INSERT INTO project_sequences(project_id, next_requirement_ordinal) VALUES (?, 1)",
                    (project_id,),
                )
                connection.execute(
                    """
                    INSERT INTO goal_sequences(
                        project_id, next_goal_ordinal, next_candidate_ordinal
                    ) VALUES (?, 1, 1)
                    """,
                    (project_id,),
                )
            except sqlite3.IntegrityError as exc:
                raise RequirementConflictError(f"project already exists: {project_id}") from exc
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="project_created",
                actor=actor,
                request_id="",
                payload={"name": name},
                occurred_at=created_at,
            )
        return {"project_id": project_id, "name": name, "created_at": created_at}

    def add_requirement(
        self,
        project_id: str,
        *,
        title: str,
        statement: str,
        category: str,
        actor: str,
        rationale: str = "",
        source_anchor: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        title = required_text(title, "title")
        statement = required_text(statement, "statement")
        category = required_text(category, "category")
        actor = required_text(actor, "actor")
        normalized_statement = normalize_requirement_statement(statement)
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            existing_request = self._mutation_event_for_request(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="requirement_created",
                request_id=request_id,
            )
            if existing_request is not None:
                return self._requirement_mutation_value(
                    connection,
                    project_id,
                    str(existing_request["requirement_id"]),
                    audit_event_id=int(existing_request["event_id"]),
                )
            existing = connection.execute(
                "SELECT requirement_id FROM requirements WHERE project_id = ? AND normalized_statement = ?",
                (project_id, normalized_statement),
            ).fetchone()
            if existing is not None:
                raise RequirementConflictError(
                    f"duplicate requirement statement: {existing['requirement_id']}"
                )

            ordinal = connection.execute(
                "SELECT next_requirement_ordinal FROM project_sequences WHERE project_id = ?",
                (project_id,),
            ).fetchone()["next_requirement_ordinal"]
            requirement_id = f"REQ-{int(ordinal):06d}"
            connection.execute(
                "UPDATE project_sequences SET next_requirement_ordinal = ? WHERE project_id = ?",
                (int(ordinal) + 1, project_id),
            )
            connection.execute(
                """
                INSERT INTO requirements(
                    project_id, requirement_id, ordinal, title, statement,
                    normalized_statement, category, lifecycle_status,
                    current_revision, source_anchor, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    project_id,
                    requirement_id,
                    ordinal,
                    title,
                    statement,
                    normalized_statement,
                    category,
                    LifecycleStatus.PLANNED.value,
                    str(source_anchor or ""),
                    occurred_at,
                    occurred_at,
                ),
            )
            self._append_revision(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                revision=1,
                title=title,
                statement=statement,
                category=category,
                source_anchor=str(source_anchor or ""),
                rationale=str(rationale or ""),
                actor=actor,
                occurred_at=occurred_at,
            )
            event_id = self._append_event(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="requirement_created",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "revision": 1,
                    "lifecycle_status": LifecycleStatus.PLANNED.value,
                    "category": category,
                    "source_anchor": str(source_anchor or ""),
                },
                occurred_at=occurred_at,
            )
            return self._requirement_mutation_value(
                connection,
                project_id,
                requirement_id,
                audit_event_id=event_id,
            )

    def revise_requirement(
        self,
        project_id: str,
        requirement_id: str,
        *,
        title: str,
        statement: str,
        category: str,
        actor: str,
        rationale: str,
        source_anchor: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        title = required_text(title, "title")
        statement = required_text(statement, "statement")
        category = required_text(category, "category")
        actor = required_text(actor, "actor")
        rationale = required_text(rationale, "rationale")
        requirement_id = validate_requirement_id(requirement_id)
        normalized_statement = normalize_requirement_statement(statement)
        occurred_at = _utc_now()
        with self._transaction() as connection:
            existing_request = self._mutation_event_for_request(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="requirement_revised",
                request_id=request_id,
            )
            if existing_request is not None:
                return self._requirement_mutation_value(
                    connection,
                    project_id,
                    requirement_id,
                    audit_event_id=int(existing_request["event_id"]),
                )
            current = self._requirement_row(connection, project_id, requirement_id)
            conflict = connection.execute(
                """
                SELECT requirement_id FROM requirements
                WHERE project_id = ? AND normalized_statement = ? AND requirement_id != ?
                """,
                (project_id, normalized_statement, requirement_id),
            ).fetchone()
            if conflict is not None:
                raise RequirementConflictError(
                    f"duplicate requirement statement: {conflict['requirement_id']}"
                )
            revision = int(current["current_revision"]) + 1
            connection.execute(
                """
                UPDATE requirements
                SET title = ?, statement = ?, normalized_statement = ?, category = ?,
                    current_revision = ?, source_anchor = ?, updated_at = ?
                WHERE project_id = ? AND requirement_id = ?
                """,
                (
                    title,
                    statement,
                    normalized_statement,
                    category,
                    revision,
                    str(source_anchor or ""),
                    occurred_at,
                    project_id,
                    requirement_id,
                ),
            )
            self._append_revision(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                revision=revision,
                title=title,
                statement=statement,
                category=category,
                source_anchor=str(source_anchor or ""),
                rationale=rationale,
                actor=actor,
                occurred_at=occurred_at,
            )
            event_id = self._append_event(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="requirement_revised",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "from_revision": current["current_revision"],
                    "to_revision": revision,
                    "previous_lifecycle_status": current["lifecycle_status"],
                },
                occurred_at=occurred_at,
            )
            self._invalidate_stale_oracle_ir_authority(
                connection,
                project_id,
                actor=actor,
                request_id=str(request_id or ""),
                reason="requirement_revised",
            )
            return self._requirement_mutation_value(
                connection,
                project_id,
                requirement_id,
                audit_event_id=event_id,
            )

    def set_lifecycle_status(
        self,
        project_id: str,
        requirement_id: str,
        *,
        status: LifecycleStatus,
        actor: str,
        reason: str,
        governance_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        requirement_id = validate_requirement_id(requirement_id)
        actor = required_text(actor, "actor")
        reason = required_text(reason, "reason")
        governance_reference = str(governance_reference or "").strip()
        try:
            status = LifecycleStatus(status)
        except ValueError as exc:
            raise ValueError(f"unsupported lifecycle status: {status}") from exc
        occurred_at = _utc_now()
        with self._transaction() as connection:
            existing_request = self._mutation_event_for_request(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="lifecycle_status_changed",
                request_id=request_id,
            )
            if existing_request is not None:
                return self._requirement_mutation_value(
                    connection,
                    project_id,
                    requirement_id,
                    audit_event_id=int(existing_request["event_id"]),
                )
            current = self._requirement_row(connection, project_id, requirement_id)
            connection.execute(
                """
                UPDATE requirements SET lifecycle_status = ?, updated_at = ?
                WHERE project_id = ? AND requirement_id = ?
                """,
                (status.value, occurred_at, project_id, requirement_id),
            )
            event_id = self._append_event(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="lifecycle_status_changed",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "from": current["lifecycle_status"],
                    "to": status.value,
                    "reason": reason,
                    "governance_reference": governance_reference,
                },
                occurred_at=occurred_at,
            )
            self._invalidate_stale_oracle_ir_authority(
                connection,
                project_id,
                actor=actor,
                request_id=str(request_id or ""),
                reason="requirement_lifecycle_changed",
            )
            return self._requirement_mutation_value(
                connection,
                project_id,
                requirement_id,
                audit_event_id=event_id,
            )

    def record_verification(
        self,
        project_id: str,
        requirement_id: str,
        *,
        kind: VerificationKind,
        outcome: VerificationOutcome,
        reference: str,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        requirement_id = validate_requirement_id(requirement_id)
        reference = required_text(reference, "reference")
        actor = required_text(actor, "actor")
        try:
            kind = VerificationKind(kind)
            outcome = VerificationOutcome(outcome)
        except ValueError as exc:
            raise ValueError("unsupported verification kind or outcome") from exc
        occurred_at = _utc_now()
        metadata_json = json.dumps(dict(metadata or {}), sort_keys=True, separators=(",", ":"))
        with self._transaction() as connection:
            if request_id:
                existing = connection.execute(
                    """
                    SELECT evidence_id, verification_kind, outcome, reference, recorded_at
                    FROM verification_evidence
                    WHERE project_id = ? AND requirement_id = ? AND request_id = ?
                    ORDER BY evidence_id LIMIT 1
                    """,
                    (project_id, requirement_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    event = self._mutation_event_for_request(
                        connection,
                        project_id=project_id,
                        requirement_id=requirement_id,
                        event_type="verification_recorded",
                        request_id=request_id,
                    )
                    return {
                        "evidence_id": int(existing["evidence_id"]),
                        "project_id": project_id,
                        "requirement_id": requirement_id,
                        "kind": str(existing["verification_kind"]),
                        "outcome": str(existing["outcome"]),
                        "reference": str(existing["reference"]),
                        "recorded_at": str(existing["recorded_at"]),
                        "audit_event_id": 0 if event is None else int(event["event_id"]),
                    }
            self._requirement_row(connection, project_id, requirement_id)
            cursor = connection.execute(
                """
                INSERT INTO verification_evidence(
                    project_id, requirement_id, verification_kind, outcome,
                    reference, actor, request_id, metadata_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    requirement_id,
                    kind.value,
                    outcome.value,
                    reference,
                    actor,
                    str(request_id or ""),
                    metadata_json,
                    occurred_at,
                ),
            )
            evidence_id = int(cursor.lastrowid)
            event_id = self._append_event(
                connection,
                project_id=project_id,
                requirement_id=requirement_id,
                event_type="verification_recorded",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "evidence_id": evidence_id,
                    "kind": kind.value,
                    "outcome": outcome.value,
                    "reference": reference,
                },
                occurred_at=occurred_at,
            )
        return {
            "evidence_id": evidence_id,
            "project_id": project_id,
            "requirement_id": requirement_id,
            "kind": kind.value,
            "outcome": outcome.value,
            "reference": reference,
            "recorded_at": occurred_at,
            "audit_event_id": event_id,
        }

    def traceability_matrix(self, project_id: str) -> list[Mapping[str, Any]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            requirements = connection.execute(
                """
                SELECT project_id, requirement_id, ordinal, title, statement, category,
                       lifecycle_status, current_revision, source_anchor, updated_at
                FROM requirements WHERE project_id = ? ORDER BY ordinal
                """,
                (project_id,),
            ).fetchall()
            rows: list[Mapping[str, Any]] = []
            for requirement in requirements:
                evidence_rows = connection.execute(
                    """
                    SELECT evidence_id, verification_kind, outcome, reference, actor,
                           metadata_json, recorded_at
                    FROM verification_evidence
                    WHERE project_id = ? AND requirement_id = ?
                    ORDER BY evidence_id
                    """,
                    (project_id, requirement["requirement_id"]),
                ).fetchall()
                latest: dict[str, Mapping[str, Any]] = {}
                evidence: list[Mapping[str, Any]] = []
                for record in evidence_rows:
                    value = dict(record)
                    value["metadata"] = json.loads(value.pop("metadata_json"))
                    latest[value["verification_kind"]] = value
                    evidence.append(value)
                row = dict(requirement)
                row["verification"] = {
                    kind.value: latest.get(kind.value, {}).get("outcome")
                    for kind in VerificationKind
                }
                row["evidence"] = evidence
                rows.append(row)
            return rows

    def requirement_history(self, project_id: str, requirement_id: str) -> Mapping[str, Any]:
        requirement_id = validate_requirement_id(requirement_id)
        with self._read_connection() as connection:
            requirement = self._requirement_row(connection, project_id, requirement_id)
            revisions = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT revision, title, statement, category, source_anchor, rationale,
                           actor, created_at
                    FROM requirement_revisions
                    WHERE project_id = ? AND requirement_id = ? ORDER BY revision
                    """,
                    (project_id, requirement_id),
                ).fetchall()
            ]
            events = []
            for row in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at
                FROM requirement_events
                WHERE project_id = ? AND requirement_id = ? ORDER BY event_id
                """,
                (project_id, requirement_id),
            ).fetchall():
                value = dict(row)
                value["payload"] = json.loads(value.pop("payload_json"))
                events.append(value)
            return {"requirement": dict(requirement), "revisions": revisions, "events": events}

    @staticmethod
    def _append_revision(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        requirement_id: str,
        revision: int,
        title: str,
        statement: str,
        category: str,
        source_anchor: str,
        rationale: str,
        actor: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO requirement_revisions(
                project_id, requirement_id, revision, title, statement, category,
                source_anchor, rationale, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                requirement_id,
                revision,
                title,
                statement,
                category,
                source_anchor,
                rationale,
                actor,
                occurred_at,
            ),
        )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        requirement_id: str | None,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, Any],
        occurred_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO requirement_events(
                project_id, requirement_id, event_type, actor, request_id,
                payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                requirement_id,
                event_type,
                actor,
                request_id,
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _mutation_event_for_request(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        requirement_id: str | None,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        if requirement_id is None:
            return connection.execute(
                """
                SELECT event_id, requirement_id FROM requirement_events
                WHERE project_id = ? AND event_type = ? AND request_id = ?
                ORDER BY event_id LIMIT 1
                """,
                (project_id, event_type, str(request_id)),
            ).fetchone()
        return connection.execute(
            """
            SELECT event_id, requirement_id FROM requirement_events
            WHERE project_id = ? AND requirement_id = ?
              AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, requirement_id, event_type, str(request_id)),
        ).fetchone()

    def _requirement_mutation_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        requirement_id: str,
        *,
        audit_event_id: int,
    ) -> Mapping[str, Any]:
        value = dict(self._requirement_row(connection, project_id, requirement_id))
        value["audit_event_id"] = audit_event_id
        return value

    @staticmethod
    def _ensure_project(connection: sqlite3.Connection, project_id: str) -> None:
        row = connection.execute(
            "SELECT project_id FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(f"unknown project: {project_id}")

    def _requirement_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        requirement_id: str,
    ) -> sqlite3.Row:
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM requirements WHERE project_id = ? AND requirement_id = ?",
            (project_id, requirement_id),
        ).fetchone()
        if row is None:
            raise RequirementNotFoundError(
                f"unknown requirement in project {project_id}: {requirement_id}"
            )
        return row
