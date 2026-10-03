"""Canonical host associations, separate from implementation-provider bindings."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


class AssociationStoreMixin:
    def migrate_associations(self) -> None:
        """Add schema 49 without changing existing binding/evidence values."""
        with self._transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS host_project_associations (
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    host_id TEXT NOT NULL,
                    repository_locator TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    replacement_reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, host_id)
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS host_project_association_events (
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    host_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    event_type TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, host_id, ordinal)
                )"""
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(provider_project_bindings)")
            }
            if "repository_json" not in columns:
                connection.execute(
                    "ALTER TABLE provider_project_bindings "
                    "ADD COLUMN repository_json TEXT NOT NULL DEFAULT 'null'"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(49, ?)",
                (_utc_now(),),
            )

    def bind_host_project(
        self, project_id: str, *, host_id: str, repository_locator: str,
        actor: str, replacement_reason: str = "", request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        host_id = required_text(host_id, "host_id")
        locator = required_text(repository_locator, "repository_locator")
        actor = required_text(actor, "actor")
        reason = str(replacement_reason or "").strip()
        now = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            existing = connection.execute(
                "SELECT * FROM host_project_associations WHERE project_id=? AND host_id=?",
                (project_id, host_id),
            ).fetchone()
            if existing is not None:
                if str(existing["repository_locator"]) == locator:
                    return dict(existing)
                if not reason:
                    raise ChangeControlBlockedError(
                        "host_association_conflict",
                        details={"project_id": project_id, "host_id": host_id},
                    )
                revision = int(existing["revision"]) + 1
                connection.execute(
                    """UPDATE host_project_associations SET repository_locator=?, revision=?,
                       updated_at=?, actor=?, request_id=?, replacement_reason=?
                       WHERE project_id=? AND host_id=?""",
                    (locator, revision, now, actor, request_id, reason, project_id, host_id),
                )
                event_type = "host_association_replaced"
            else:
                revision = 1
                connection.execute(
                    """INSERT INTO host_project_associations VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                    (project_id, host_id, locator, now, now, actor, request_id, reason),
                )
                event_type = "host_association_created"
            connection.execute(
                """INSERT INTO host_project_association_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id, host_id, revision, event_type, revision,
                    self._json({"repository_locator": locator, "replacement_reason": reason}),
                    now, actor, request_id,
                ),
            )
            return dict(connection.execute(
                "SELECT * FROM host_project_associations WHERE project_id=? AND host_id=?",
                (project_id, host_id),
            ).fetchone())

    def list_host_associations(self, project_id: str) -> list[Mapping[str, object]]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM host_project_associations WHERE project_id=? ORDER BY host_id",
                (project_id,),
            ).fetchall()]
