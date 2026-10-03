"""SQLite persistence for project-scoped implementation-provider bindings."""
from __future__ import annotations

import json
from typing import Any, Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.provider_binding import (
    ImplementationProviderKind,
    ProviderProjectBinding,
    ProviderProjectBindingDraft,
)
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


class ProviderBindingStoreMixin:
    def bind_provider_project(
        self,
        project_id: str,
        draft: ProviderProjectBindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        kind = draft.provider_kind.value
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            existing = connection.execute(
                """
                SELECT * FROM provider_project_bindings
                WHERE project_id = ? AND provider_kind = ?
                """,
                (project_id, kind),
            ).fetchone()
            if existing is not None:
                same = (
                    str(existing["provider_id"]) == draft.provider_id
                    and str(existing["scope_id"]) == draft.scope_id
                    and tuple(json.loads(str(existing["surfaces_json"]))) == draft.surfaces
                    and str(existing["provider_context_id"]) == draft.provider_context_id
                    and json.loads(str(existing["repository_json"])) == draft.repository
                    and str(existing["status"]) == "active"
                )
                if same:
                    return self._provider_binding_value(existing)
                if not draft.replacement_reason:
                    raise ChangeControlBlockedError(
                        "implementation_provider_binding_conflict",
                        details={"project_id": project_id, "provider_kind": kind},
                    )
                revision = int(existing["revision"]) + 1
                connection.execute(
                    """
                    UPDATE provider_project_bindings
                    SET provider_id = ?, scope_id = ?, surfaces_json = ?,
                        provider_context_id = ?, repository_json = ?, status = 'active',
                        revision = ?, updated_at = ?, actor = ?, request_id = ?,
                        replacement_reason = ?
                    WHERE project_id = ? AND provider_kind = ?
                    """,
                    (
                        draft.provider_id,
                        draft.scope_id,
                        self._json(list(draft.surfaces)),
                        draft.provider_context_id,
                        self._json(draft.repository),
                        revision,
                        occurred_at,
                        actor,
                        str(request_id or ""),
                        draft.replacement_reason,
                        project_id,
                        kind,
                    ),
                )
                event_type = "provider_binding_replaced"
            else:
                revision = 1
                connection.execute(
                    """
                    INSERT INTO provider_project_bindings(
                        project_id, provider_kind, provider_id, scope_id, surfaces_json,
                        provider_context_id, repository_json, status, revision, created_at, updated_at, actor, request_id,
                        replacement_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        kind,
                        draft.provider_id,
                        draft.scope_id,
                        self._json(list(draft.surfaces)),
                        draft.provider_context_id,
                        self._json(draft.repository),
                        occurred_at,
                        occurred_at,
                        actor,
                        str(request_id or ""),
                        draft.replacement_reason,
                    ),
                )
                event_type = "provider_binding_created"
            event_ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                    FROM provider_project_binding_events
                    WHERE project_id = ? AND provider_kind = ?
                    """,
                    (project_id, kind),
                ).fetchone()["ordinal"]
            )
            connection.execute(
                """
                INSERT INTO provider_project_binding_events(
                    project_id, provider_kind, ordinal, event_type, revision,
                    payload_json, occurred_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    kind,
                    event_ordinal,
                    event_type,
                    revision,
                    self._json(
                        {
                            "provider_id": draft.provider_id,
                            "scope_id": draft.scope_id,
                            "surfaces": list(draft.surfaces),
                            "provider_context_id": draft.provider_context_id,
                            "repository": draft.repository,
                            "replacement_reason": draft.replacement_reason,
                        }
                    ),
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM provider_project_bindings
                WHERE project_id = ? AND provider_kind = ?
                """,
                (project_id, kind),
            ).fetchone()
            return self._provider_binding_value(row)

    def resolve_provider_binding(
        self,
        project_id: str,
        provider_kind: ImplementationProviderKind | str,
    ) -> ProviderProjectBinding | None:
        project_id = validate_project_id(project_id)
        kind = ImplementationProviderKind(provider_kind)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                """
                SELECT * FROM provider_project_bindings
                WHERE project_id = ? AND provider_kind = ? AND status = 'active'
                """,
                (project_id, kind.value),
            ).fetchone()
            if row is None:
                return None
            return ProviderProjectBinding(
                project_id=project_id,
                provider_kind=kind,
                provider_id=str(row["provider_id"]),
                scope_id=str(row["scope_id"]),
                surfaces=tuple(json.loads(str(row["surfaces_json"]))),
                provider_context_id=str(row["provider_context_id"]),
                revision=int(row["revision"]),
                repository=json.loads(str(row["repository_json"])),
            )

    def list_provider_bindings(self, project_id: str) -> list[Mapping[str, object]]:
        project_id = validate_project_id(project_id)
        supported = tuple(kind.value for kind in ImplementationProviderKind)
        placeholders = ", ".join("?" for _ in supported)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            rows = connection.execute(
                f"""
                SELECT * FROM provider_project_bindings
                WHERE project_id = ?
                  AND provider_kind IN ({placeholders})
                ORDER BY provider_kind
                """,
                (project_id, *supported),
            ).fetchall()
            return [self._provider_binding_value(row) for row in rows]

    @staticmethod
    def _provider_binding_value(row: Any) -> Mapping[str, object]:
        return {
            "project_id": str(row["project_id"]),
            "provider_kind": str(row["provider_kind"]),
            "provider_id": str(row["provider_id"]),
            "scope_id": str(row["scope_id"]),
            "surfaces": list(json.loads(str(row["surfaces_json"]))),
            "provider_context_id": str(row["provider_context_id"]),
            "repository": json.loads(str(row["repository_json"])),
            "status": str(row["status"]),
            "revision": int(row["revision"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "actor": str(row["actor"]),
            "request_id": str(row["request_id"]),
            "replacement_reason": str(row["replacement_reason"]),
        }
