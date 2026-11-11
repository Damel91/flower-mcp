"""SQLite persistence for explicit Project Context selection."""

from __future__ import annotations

from collections.abc import Iterator
import json
from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.project_context import ProjectContextBinding
from flow_of_work_mcp.core.domain.interaction_projection import CapabilityLensBinding


_DASHBOARD_REPOSITORY_REVIEWS = """
    FROM requirement_events e JOIN phase_audits a ON a.project_id = e.project_id
       AND a.phase_audit_id = json_extract(e.payload_json, '$.phase_audit_id')
    WHERE e.project_id = ? AND e.event_type = 'phase_audit_recorded'
      AND json_type(e.payload_json, '$.repository_review') = 'object'
"""

_DASHBOARD_REQUIREMENT_COLUMNS = (
    "requirement_id, title, statement, category, lifecycle_status, current_revision, source_anchor"
)

_DASHBOARD_VERIFICATION_CHANNELS = {
    "campaign": (
        "SELECT campaign_id, change_id, title, status FROM verification_campaigns WHERE project_id = ?",
        "ordinal, campaign_id", "",
    ),
    "verification": (
        """SELECT 'verification' AS kind, CAST(evidence_id AS TEXT) AS identity,
                  verification_kind AS title, evidence_id, requirement_id, outcome,
                  recorded_at, actor, 'recorded_verification_evidence' AS provenance
             FROM verification_evidence WHERE project_id = ?""",
        "evidence_id DESC", "requirement_id",
    ),
    "external_report": (
        """SELECT 'external_report' AS kind, CAST(report_identity AS TEXT) AS identity,
                  unit_key AS title, unit_key, packet_id, change_id, report_key,
                  spec_revision, plan_revision, authority_fingerprint, disposition AS recorded_disposition,
                  json_extract(payload_json, '$.source_revision') AS source_revision,
                  json_extract(payload_json, '$.outcome') AS outcome,
                  occurred_at AS recorded_at, actor, 'host_reported' AS provenance
             FROM external_work_reports WHERE project_id = ?""",
        "report_identity DESC", "packet_id",
    ),
    "repository_review": (
        """SELECT 'repository_review' AS kind, CAST(a.phase_audit_id AS TEXT) AS identity,
                  a.scope_id AS title, a.phase_audit_id, a.created_at AS recorded_at, a.created_by AS actor,
                  json_extract(e.payload_json, '$.repository_review.change_id') AS change_id,
                  json_extract(e.payload_json, '$.repository_review.packet_id') AS packet_id,
                  json_extract(e.payload_json, '$.repository_review.source_revision') AS source_revision,
                  json_extract(e.payload_json, '$.repository_review.expected_basis_fingerprint') AS basis_fingerprint,
                  'host_declared' AS provenance""" + _DASHBOARD_REPOSITORY_REVIEWS,
        "a.phase_audit_id DESC", "json_extract(e.payload_json, '$.repository_review.packet_id')",
    ),
}


class ProjectContextStoreMixin:
    def dashboard_projects(self, *, search: str, offset: int, limit: int) -> Mapping[str, object]:
        """Read one literal-search catalog page without hydrating project state."""
        where = "instr(lower(project_id || ' ' || name), lower(?)) > 0"
        with self._read_connection() as connection:
            total = int(connection.execute(
                "SELECT COUNT(*) FROM projects WHERE " + where, (search,)
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT project_id, name, created_at, "
                "(SELECT COALESCE(MAX(event_id), 0) FROM requirement_events e "
                " WHERE e.project_id = projects.project_id) AS source_ledger_version "
                "FROM projects WHERE " + where + " ORDER BY project_id LIMIT ? OFFSET ?",
                (search, limit, offset),
            ).fetchall()
            return {"items": [dict(row) for row in rows], "total": total}

    def dashboard_project(self, project_id: str) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            return dict(connection.execute(
                "SELECT project_id, name, created_at FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone())

    def dashboard_items(self, project_id: str, section: str, *, offset: int, limit: int) -> Mapping[str, object]:
        """Read selected metadata only; section names never become SQL identifiers."""
        project_id = validate_project_id(project_id)
        queries = {
            "overview": ("requirements", _DASHBOARD_REQUIREMENT_COLUMNS, "ordinal"),
            "roadmap": ("milestones", "milestone_id, name, status", "ordinal"),
            "packets": ("implementation_packets", "packet_id, change_id, title, status, spec_revision", "ordinal"),
        }
        if section == "evidence":
            return self._dashboard_evidence_items(project_id, offset=offset, limit=limit)
        if section not in queries:
            raise ValueError("unsupported dashboard metadata section")
        table, columns, ordering = queries[section]
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT {columns} FROM {table} WHERE project_id = ? ORDER BY {ordering} LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            ).fetchall()
            return {"items": [dict(row) for row in rows], "total": total}

    def dashboard_milestone_requirements(self, project_id: str, milestone_id: str) -> tuple[str, ...] | None:
        """Read realized membership from the scoped milestone record."""
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT requirement_ids_json FROM milestones WHERE project_id = ? AND milestone_id = ?",
                (project_id, milestone_id),
            ).fetchone()
            return tuple(json.loads(row["requirement_ids_json"])) if row is not None else None

    def dashboard_requirement_rows(
        self, project_id: str, requirement_ids: tuple[str, ...] | None,
    ) -> Iterator[Mapping[str, object]]:
        """Stream current scoped records in ledger order without loading verification history."""
        query = f"SELECT {_DASHBOARD_REQUIREMENT_COLUMNS} FROM requirements WHERE project_id = ?"
        parameters = (project_id,)
        if requirement_ids is not None:
            query += " AND requirement_id IN (SELECT value FROM json_each(?))"
            parameters = (project_id, json.dumps(requirement_ids))
        with self._read_connection() as connection:
            for row in connection.execute(query + " ORDER BY ordinal", parameters):
                yield dict(row)

    def dashboard_verification_items(self, project_id: str, *, channel: str, scope_id: str,
                                     offset: int, limit: int) -> Mapping[str, object]:
        """Page one proof channel without treating host records as direct verification."""
        project_id = validate_project_id(project_id)
        query, order, scope_column = _DASHBOARD_VERIFICATION_CHANNELS[channel]
        parameters = (project_id,)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            counts = {
                kind: connection.execute("SELECT COUNT(*) FROM (" + query + ")", parameters).fetchone()[0]
                for kind, (query, _, _) in _DASHBOARD_VERIFICATION_CHANNELS.items()
            }
            total = counts[channel]
            if scope_id:
                query += f" AND {scope_column} = ?"
                parameters = (project_id, scope_id)
                total = connection.execute("SELECT COUNT(*) FROM (" + query + ")", parameters).fetchone()[0]
            rows = connection.execute(query + f" ORDER BY {order} LIMIT ? OFFSET ?",
                                      (*parameters, limit, offset)).fetchall()
            return {"items": [dict(row) for row in rows], "total": total, "counts": counts}

    def dashboard_packet_requirement_evidence(self, project_id: str, packet_id: str, *, limit: int) -> Mapping[str, object]:
        """Count retained typed proofs for the packet's exact requirement scope."""
        with self._read_connection() as connection:
            packet = connection.execute(
                """SELECT CASE WHEN json_array_length(p.requirement_ids_json) > 0
                          THEN p.requirement_ids_json ELSE c.requirement_ids_json END AS requirement_ids_json
                   FROM implementation_packets p JOIN change_units c USING(project_id, change_id)
                   WHERE p.project_id = ? AND p.packet_id = ?""",
                (project_id, packet_id),
            ).fetchone()
            requirement_ids = packet["requirement_ids_json"]
            rows = connection.execute(
                """SELECT scope.value AS requirement_id,
                          (SELECT COUNT(*) FROM verification_evidence v
                           WHERE v.project_id = ? AND v.requirement_id = scope.value) AS recorded_count
                   FROM json_each(?) scope ORDER BY scope.key LIMIT ?""",
                (project_id, requirement_ids, limit),
            ).fetchall()
            total = connection.execute("SELECT json_array_length(?)", (requirement_ids,)).fetchone()[0]
            return {"items": [dict(row) for row in rows], "total": total}

    def _dashboard_evidence_items(self, project_id: str, *, offset: int, limit: int) -> Mapping[str, object]:
        query = """
            SELECT 'artifact' AS kind, CAST(a.artifact_id AS TEXT) AS identity,
                   a.artifact_kind AS title, g.generated_at AS recorded_at,
                   g.created_by AS actor, 'retained_artifact' AS provenance
            FROM generated_artifacts a JOIN artifact_generations g USING(generation_id)
            WHERE g.project_id = ?
            UNION ALL
            SELECT 'handover', handover_id, handover_id, created_at, actor, 'retained_handover'
            FROM handover_snapshots WHERE project_id = ?
            UNION ALL
            SELECT 'verification', CAST(evidence_id AS TEXT), verification_kind,
                   recorded_at, actor, 'recorded_verification_evidence'
            FROM verification_evidence WHERE project_id = ?
        """
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            parameters = (project_id, project_id, project_id)
            total = int(connection.execute("SELECT COUNT(*) FROM (" + query + ")", parameters).fetchone()[0])
            rows = connection.execute(
                query + " ORDER BY recorded_at DESC, kind, identity LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
            return {"items": [dict(row) for row in rows], "total": total}

    def dashboard_retained_evidence(self, project_id: str, kind: str, identity: str, *, maximum_bytes: int) -> Mapping[str, object]:
        """Retrieve an exact same-project retained value, without file or URL access."""
        project_id = validate_project_id(project_id)
        queries = {
            "artifact": ("SELECT a.content AS content, a.content_sha256, a.artifact_kind, a.generation_id "
                         "FROM generated_artifacts a JOIN artifact_generations g USING(generation_id) "
                         "WHERE g.project_id = ? AND a.artifact_id = ?"),
            "handover": ("SELECT payload_json AS content, profile_version FROM handover_snapshots "
                         "WHERE project_id = ? AND handover_id = ?"),
            "verification": ("SELECT metadata_json AS content, requirement_id, verification_kind, outcome, reference, actor, recorded_at "
                             "FROM verification_evidence WHERE project_id = ? AND evidence_id = ?"),
            "external_report": ("SELECT payload_json AS content, unit_key AS title, packet_id, change_id, report_key, "
                                "spec_revision, plan_revision, authority_fingerprint, disposition AS recorded_disposition, "
                                "occurred_at AS recorded_at, actor, 'host_reported' AS provenance "
                                "FROM external_work_reports WHERE project_id = ? AND report_identity = ?"),
            "repository_review": ("SELECT json_extract(e.payload_json, '$.repository_review') AS content, "
                                  "a.scope_id AS title, a.created_at AS recorded_at, a.created_by AS actor, "
                                  "'host_declared' AS provenance" + _DASHBOARD_REPOSITORY_REVIEWS +
                                  " AND a.phase_audit_id = ?"),
        }
        if kind not in queries:
            raise ValueError("unsupported dashboard evidence kind")
        query = queries[kind]
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                "SELECT length(CAST(content AS BLOB)) FROM (" + query + ")", (project_id, identity)
            ).fetchone()
            if row is None:
                raise ValueError("dashboard evidence was not found in the selected project")
            if int(row[0]) > maximum_bytes:
                raise ValueError("dashboard evidence exceeds the 2 MiB read limit")
            return dict(connection.execute(query, (project_id, identity)).fetchone())

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

    def read_interaction_catalog_snapshot(self, interaction_session_ref: str) -> Mapping[str, object]:
        """Observe raw selection and prerequisite counts in one query-only snapshot.

        In particular, do not repair stale lenses or allocate a continuation.
        Event heads retain the identity of cleared selections.
        """
        interaction = required_text(interaction_session_ref, "interaction_session_ref")
        with self.consistent_read() as connection:
            context = self.get_interaction_project_context(interaction)
            lens = self.get_interaction_capability_lens(interaction)
            if context is not None and (type(context.revision) is not int or context.revision < 1):
                raise ValueError("lens_catalog_state_invalid")
            revisions = {}
            for key, table, binding in (
                ("project_context", "interaction_project_context_events", context),
                ("capability_lens", "interaction_capability_lens_events", lens),
            ):
                head = connection.execute(
                    f"SELECT MAX(revision) FROM {table} WHERE interaction_session_ref = ?",
                    (interaction,),
                ).fetchone()[0]
                head = 0 if head is None else head
                if type(head) is not int or head < 0 or (binding and head < binding.revision):
                    raise ValueError("lens_catalog_state_invalid")
                revisions[key] = head
            exists = bool(context and connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (context.project_id,)
            ).fetchone())
            counts = {key: 0 for key in ("requirements", "milestones", "changes", "packets")}
            if exists:
                for key, table in (("requirements", "requirements"),
                                   ("milestones", "milestones"),
                                   ("changes", "change_units"),
                                   ("packets", "implementation_packets")):
                    counts[key] = connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
                        (context.project_id,),
                    ).fetchone()[0]
            return {
                "project_context": None if context is None else {
                    "project_id": context.project_id, "revision": context.revision,
                    "provider_configured": bool(context.provider_context_id),
                },
                "capability_lens": None if lens is None else {
                    "provider": lens.producing_provider, "area": lens.selected_area,
                    "revision": lens.revision, "project_id": lens.project_id,
                    "project_context_revision": lens.project_context_revision,
                },
                "revisions": revisions, "project_exists": exists,
                "prerequisite_counts": counts,
            }

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
