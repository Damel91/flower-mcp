"""SQLite persistence for explicit Project Context selection."""

from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.project_context import ProjectContextBinding
from flow_of_work_mcp.core.domain.interaction_projection import CapabilityLensBinding


class ProjectContextStoreMixin:
    def list_projects_for_interaction(self) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT project_id, name, created_at FROM projects ORDER BY created_at, project_id"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_interaction_project_context(
        self, interaction_session_ref: str
    ) -> ProjectContextBinding | None:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT interaction_session_ref, project_id, provider_context_id, revision
                FROM interaction_project_contexts
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            return ProjectContextBinding(**dict(row)) if row is not None else None

    def set_interaction_project_context(
        self,
        interaction_session_ref: str,
        project_id: str,
        *,
        provider_context_id: str = "",
        transition: str = "upsert",
        actor: str,
        request_id: str = "",
    ) -> ProjectContextBinding:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        project = validate_project_id(project_id)
        transition_kind = str(transition or "").strip().lower()
        if transition_kind not in {"upsert", "select", "switch"}:
            raise ValueError("project_context_transition_invalid")
        selected_actor = required_text(actor, "actor")
        now = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project)
            row = connection.execute(
                "SELECT * FROM interaction_project_contexts WHERE interaction_session_ref = ?",
                (interaction,),
            ).fetchone()
            if (
                transition_kind == "select"
                and row is not None
                and (
                    str(row["project_id"]) != project
                    or str(row["provider_context_id"]) != str(provider_context_id or "")
                )
            ):
                raise ValueError("project_context_switch_required")
            if transition_kind == "switch" and row is None:
                raise ValueError("project_context_select_required")
            if row is not None and (
                str(row["project_id"]) == project
                and str(row["provider_context_id"]) == str(provider_context_id or "")
            ):
                return ProjectContextBinding(
                    interaction_session_ref=interaction,
                    project_id=project,
                    provider_context_id=str(provider_context_id or ""),
                    revision=int(row["revision"]),
                )
            last = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM interaction_project_context_events
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            revision = (
                max(
                    int(row["revision"]) if row is not None else 0,
                    int(last["revision"] or 0),
                )
                + 1
            )
            previous_project = str(row["project_id"]) if row is not None else ""
            if row is not None:
                self._invalidate_lens_for_context_change(
                    connection, interaction, selected_actor, request_id, now
                )
            connection.execute(
                """
                INSERT INTO interaction_project_contexts(
                    interaction_session_ref, project_id, provider_context_id,
                    revision, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interaction_session_ref) DO UPDATE SET
                    project_id = excluded.project_id,
                    provider_context_id = excluded.provider_context_id,
                    revision = excluded.revision,
                    updated_at = excluded.updated_at,
                    actor = excluded.actor,
                    request_id = excluded.request_id
                """,
                (
                    interaction,
                    project,
                    str(provider_context_id or ""),
                    revision,
                    now,
                    selected_actor,
                    str(request_id or ""),
                ),
            )
            self._append_project_context_event(
                connection,
                interaction,
                revision,
                "switched" if previous_project else "selected",
                previous_project,
                project,
                selected_actor,
                request_id,
                now,
            )
        return ProjectContextBinding(
            interaction_session_ref=interaction,
            project_id=project,
            provider_context_id=str(provider_context_id or ""),
            revision=revision,
        )

    def clear_interaction_project_context(
        self,
        interaction_session_ref: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        selected_actor = required_text(actor, "actor")
        now = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM interaction_project_contexts WHERE interaction_session_ref = ?",
                (interaction,),
            ).fetchone()
            if row is None:
                return {"cleared": False, "reason": "project_context_not_selected"}
            revision = int(row["revision"]) + 1
            previous_project = str(row["project_id"])
            self._invalidate_lens_for_context_change(
                connection, interaction, selected_actor, request_id, now
            )
            connection.execute(
                "DELETE FROM interaction_project_contexts WHERE interaction_session_ref = ?",
                (interaction,),
            )
            self._append_project_context_event(
                connection,
                interaction,
                revision,
                "cleared",
                previous_project,
                "",
                selected_actor,
                request_id,
                now,
            )
            return {"cleared": True, "previous_project_id": previous_project}

    def get_interaction_capability_lens(
        self, interaction_session_ref: str
    ) -> CapabilityLensBinding | None:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT interaction_session_ref, project_id, project_context_revision,
                       producing_provider, selected_area, revision
                FROM interaction_capability_lenses
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            return CapabilityLensBinding(**dict(row)) if row is not None else None

    def set_interaction_capability_lens(
        self,
        interaction_session_ref: str,
        *,
        project_id: str,
        project_context_revision: int,
        producing_provider: str,
        selected_area: str,
        transition: str = "upsert",
        actor: str,
        request_id: str = "",
    ) -> CapabilityLensBinding:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        project = validate_project_id(project_id)
        provider = required_text(producing_provider, "producing_provider")
        area = required_text(selected_area, "selected_area")
        transition_kind = str(transition or "").strip().lower()
        if transition_kind not in {"upsert", "select", "switch"}:
            raise ValueError("capability_lens_transition_invalid")
        selected_actor = required_text(actor, "actor")
        now = _utc_now()
        with self._transaction() as connection:
            context = connection.execute(
                """
                SELECT project_id, revision FROM interaction_project_contexts
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            if context is None:
                raise ValueError("project_context_not_selected")
            if str(context["project_id"]) != project or int(context["revision"]) != int(
                project_context_revision
            ):
                raise ValueError("project_context_changed")
            current = connection.execute(
                "SELECT * FROM interaction_capability_lenses WHERE interaction_session_ref = ?",
                (interaction,),
            ).fetchone()
            if current is not None and (
                str(current["project_id"]) != project
                or int(current["project_context_revision"])
                != int(project_context_revision)
            ):
                self._release_interaction_projection(connection, interaction)
                current = None
            if (
                transition_kind == "select"
                and current is not None
                and (
                    str(current["producing_provider"]) != provider
                    or str(current["selected_area"]) != area
                )
            ):
                raise ValueError("capability_lens_switch_required")
            if transition_kind == "switch" and current is None:
                raise ValueError("capability_lens_select_required")
            if current is not None and (
                str(current["producing_provider"]) == provider
                and str(current["selected_area"]) == area
            ):
                return CapabilityLensBinding(
                    interaction_session_ref=interaction,
                    project_id=project,
                    project_context_revision=int(project_context_revision),
                    producing_provider=provider,
                    selected_area=area,
                    revision=int(current["revision"]),
                )
            last = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM interaction_capability_lens_events
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            revision = int(last["revision"] or 0) + 1
            connection.execute(
                """
                INSERT INTO interaction_capability_lenses(
                    interaction_session_ref, project_id, project_context_revision,
                    producing_provider, selected_area, revision, updated_at, actor,
                    request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interaction_session_ref) DO UPDATE SET
                    project_id = excluded.project_id,
                    project_context_revision = excluded.project_context_revision,
                    producing_provider = excluded.producing_provider,
                    selected_area = excluded.selected_area,
                    revision = excluded.revision,
                    updated_at = excluded.updated_at,
                    actor = excluded.actor,
                    request_id = excluded.request_id
                """,
                (
                    interaction,
                    project,
                    int(project_context_revision),
                    provider,
                    area,
                    revision,
                    now,
                    selected_actor,
                    str(request_id or ""),
                ),
            )
            self._append_lens_event(
                connection,
                interaction,
                project,
                provider,
                area,
                revision,
                "switched" if current is not None else "selected",
                selected_actor,
                request_id,
                now,
            )
        return CapabilityLensBinding(
            interaction_session_ref=interaction,
            project_id=project,
            project_context_revision=int(project_context_revision),
            producing_provider=provider,
            selected_area=area,
            revision=revision,
        )

    def clear_interaction_capability_lens(
        self,
        interaction_session_ref: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> bool:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        selected_actor = required_text(actor, "actor")
        now = _utc_now()
        with self._transaction() as connection:
            current = connection.execute(
                "SELECT * FROM interaction_capability_lenses WHERE interaction_session_ref = ?",
                (interaction,),
            ).fetchone()
            if current is None:
                self._clear_interaction_continuation(connection, interaction)
                return False
            last = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM interaction_capability_lens_events
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            revision = int(last["revision"] or current["revision"]) + 1
            self._append_lens_event(
                connection,
                interaction,
                str(current["project_id"]),
                str(current["producing_provider"]),
                "",
                revision,
                "cleared",
                selected_actor,
                request_id,
                now,
            )
            self._release_interaction_projection(connection, interaction)
            return True

    def set_interaction_continuation(
        self,
        interaction_session_ref: str,
        *,
        project_id: str,
        project_context_revision: int,
        owner: str,
        query: str,
        offset: int,
        source_fingerprint: str = "",
    ) -> None:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        now = _utc_now()
        with self._transaction() as connection:
            project = str(project_id or "").strip()
            context = connection.execute(
                """
                SELECT project_id, revision FROM interaction_project_contexts
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            if project:
                if context is None:
                    raise ValueError("project_context_not_selected")
                if str(context["project_id"]) != validate_project_id(project) or int(
                    context["revision"]
                ) != int(project_context_revision):
                    raise ValueError("project_context_changed")
            elif context is not None or int(project_context_revision) != 0:
                raise ValueError("project_context_changed")
            connection.execute(
                """
                INSERT INTO interaction_projection_continuations(
                    interaction_session_ref, project_id, project_context_revision,
                    owner, query, offset, source_fingerprint, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interaction_session_ref) DO UPDATE SET
                    project_id = excluded.project_id,
                    project_context_revision = excluded.project_context_revision,
                    owner = excluded.owner,
                    query = excluded.query,
                    offset = excluded.offset,
                    source_fingerprint = excluded.source_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    interaction,
                    validate_project_id(project) if project else "",
                    int(project_context_revision),
                    required_text(owner, "owner"),
                    str(query or ""),
                    int(offset),
                    str(source_fingerprint or ""),
                    now,
                ),
            )

    def get_interaction_continuation(
        self, interaction_session_ref: str
    ) -> Mapping[str, object] | None:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT interaction_session_ref, project_id, project_context_revision,
                       owner, query, offset, source_fingerprint
                FROM interaction_projection_continuations
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            return dict(row) if row is not None else None

    def clear_interaction_continuation(self, interaction_session_ref: str) -> None:
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        with self._transaction() as connection:
            self._clear_interaction_continuation(connection, interaction)

    @staticmethod
    def _append_lens_event(
        connection,
        interaction: str,
        project: str,
        provider: str,
        area: str,
        revision: int,
        event_type: str,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO interaction_capability_lens_events(
                interaction_session_ref, project_id, producing_provider,
                selected_area, revision, event_type, occurred_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction,
                project,
                provider,
                area,
                revision,
                event_type,
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )

    @staticmethod
    def _clear_interaction_continuation(connection, interaction: str) -> None:
        connection.execute(
            "DELETE FROM interaction_projection_continuations WHERE interaction_session_ref = ?",
            (interaction,),
        )

    @classmethod
    def _release_interaction_projection(cls, connection, interaction: str) -> None:
        connection.execute(
            "DELETE FROM interaction_capability_lenses WHERE interaction_session_ref = ?",
            (interaction,),
        )
        cls._clear_interaction_continuation(connection, interaction)

    @classmethod
    def _invalidate_lens_for_context_change(
        cls,
        connection,
        interaction: str,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM interaction_capability_lenses WHERE interaction_session_ref = ?",
            (interaction,),
        ).fetchone()
        if current is not None:
            last = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM interaction_capability_lens_events
                WHERE interaction_session_ref = ?
                """,
                (interaction,),
            ).fetchone()
            revision = int(last["revision"] or current["revision"]) + 1
            cls._append_lens_event(
                connection,
                interaction,
                str(current["project_id"]),
                str(current["producing_provider"]),
                "",
                revision,
                "project_context_invalidated",
                actor,
                request_id,
                occurred_at,
            )
        cls._release_interaction_projection(connection, interaction)

    @staticmethod
    def _append_project_context_event(
        connection,
        interaction: str,
        revision: int,
        event_type: str,
        previous_project: str,
        project: str,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO interaction_project_context_events(
                interaction_session_ref, revision, event_type,
                previous_project_id, project_id, occurred_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction,
                revision,
                event_type,
                previous_project,
                project,
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )
