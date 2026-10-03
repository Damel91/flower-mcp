"""SQLite navigation-audit persistence mixin."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.navigation_audit import (
    CandidateRejectionDraft,
    CandidateTargetSetDraft,
    ContextSnapshotRefDraft,
    NavigationAuditBlockDraft,
    NavigationAuditState,
    ProviderAuditWindowDraft,
    ProviderAuditWindowState,
    ProviderNavigationAuditSnapshotDraft,
    TargetBindingDraft,
    validate_candidate_set_id,
    validate_navigation_audit_id,
)
from flow_of_work_mcp.core.errors import RequirementConflictError


class NavigationAuditStoreMixin:
    def open_navigation_audit(
        self,
        project_id: str,
        draft: NavigationAuditBlockDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            if draft.change_id:
                self._change_row(connection, project_id, draft.change_id)
            if draft.packet_id:
                self._packet_for_navigation(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT navigation_audit_id FROM navigation_audit_blocks
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._navigation_audit_value(
                        connection, project_id, str(replay["navigation_audit_id"])
                    )
            connection.execute(
                """
                INSERT OR IGNORE INTO navigation_audit_sequences(
                    project_id, next_navigation_ordinal, next_candidate_set_ordinal,
                    next_binding_ordinal, next_snapshot_ordinal
                ) VALUES (?, 1, 1, 1, 1)
                """,
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    """
                    SELECT next_navigation_ordinal FROM navigation_audit_sequences
                    WHERE project_id = ?
                    """,
                    (project_id,),
                ).fetchone()["next_navigation_ordinal"]
            )
            navigation_audit_id = f"NAV-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO navigation_audit_blocks(
                    project_id, navigation_audit_id, ordinal, milestone_id, change_id,
                    packet_id, related_campaign_id, state, active_provider, source_revision,
                    opened_by, request_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    ordinal,
                    draft.milestone_id,
                    draft.change_id,
                    draft.packet_id,
                    draft.related_campaign_id,
                    NavigationAuditState.OPENED.value,
                    draft.active_provider,
                    draft.source_revision,
                    actor,
                    request_id,
                    occurred_at,
                    occurred_at,
                ),
            )
            connection.execute(
                """
                UPDATE navigation_audit_sequences
                SET next_navigation_ordinal = ?
                WHERE project_id = ?
                """,
                (ordinal + 1, project_id),
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="navigation_audit_opened",
                actor=actor,
                request_id=request_id,
                payload={
                    "milestone_id": draft.milestone_id,
                    "change_id": draft.change_id,
                    "packet_id": draft.packet_id,
                    "active_provider": draft.active_provider,
                    "source_revision": draft.source_revision,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def navigation_audit_state(
        self, project_id: str, navigation_audit_id: str
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        with self._read_connection() as connection:
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def list_navigation_audits(self, project_id: str) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT navigation_audit_id FROM navigation_audit_blocks
                WHERE project_id = ?
                ORDER BY ordinal
                """,
                (project_id,),
            ).fetchall()
            return [
                self._navigation_audit_value(connection, project_id, str(row["navigation_audit_id"]))
                for row in rows
            ]

    def append_candidate_set(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateTargetSetDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT candidate_set_id FROM navigation_candidate_sets
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._navigation_audit_value(connection, project_id, navigation_audit_id)
            candidate_set_id = self._next_candidate_set_id(connection, project_id)
            ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                    FROM navigation_candidate_sets
                    WHERE project_id = ? AND navigation_audit_id = ?
                    """,
                    (project_id, navigation_audit_id),
                ).fetchone()["ordinal"]
            )
            connection.execute(
                """
                INSERT INTO navigation_candidate_sets(
                    project_id, navigation_audit_id, candidate_set_id, ordinal, provider,
                    provider_capability_version, semantic_seeds_json, metadata_json,
                    source_revision, truncated, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    candidate_set_id,
                    ordinal,
                    draft.provider,
                    draft.provider_capability_version,
                    self._json(list(draft.semantic_seeds)),
                    self._json(dict(draft.metadata)),
                    draft.source_revision,
                    1 if draft.truncated else 0,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            for candidate in draft.candidates:
                connection.execute(
                    """
                    INSERT INTO navigation_candidate_targets(
                        project_id, candidate_set_id, candidate_id, target_handle,
                        target_kind, surface_id, repo_or_workspace_id, file_path,
                        symbol_name, line_start, line_end, confidence,
                        selection_reason, semantic_seed, graph_evidence_json,
                        traversal_path_json, diagnostics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        candidate_set_id,
                        candidate.candidate_id,
                        candidate.target_handle,
                        candidate.target_kind,
                        candidate.surface_id,
                        candidate.repo_or_workspace_id,
                        candidate.file_path,
                        candidate.symbol_name,
                        candidate.line_start,
                        candidate.line_end,
                        candidate.confidence,
                        candidate.selection_reason,
                        candidate.semantic_seed,
                        self._json(dict(candidate.graph_evidence)),
                        self._json(list(candidate.traversal_path)),
                        self._json(list(candidate.diagnostics)),
                    ),
                )
            self._set_navigation_state(
                connection,
                project_id,
                navigation_audit_id,
                NavigationAuditState.COLLECTING,
                occurred_at,
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="candidate_set_appended",
                actor=actor,
                request_id=request_id,
                payload={
                    "candidate_set_id": candidate_set_id,
                    "candidate_count": len(draft.candidates),
                    "provider": draft.provider,
                    "truncated": draft.truncated,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def accept_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: TargetBindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            candidate = self._candidate_row(
                connection, project_id, draft.candidate_set_id, draft.candidate_id
            )
            candidate_nav = self._candidate_navigation_audit_id(
                connection, project_id, draft.candidate_set_id
            )
            if candidate_nav != navigation_audit_id:
                raise RequirementConflictError("candidate does not belong to navigation audit")
            rejected = connection.execute(
                """
                SELECT 1 FROM navigation_rejected_candidates
                WHERE project_id = ? AND navigation_audit_id = ? AND candidate_set_id = ?
                  AND candidate_id = ?
                """,
                (project_id, navigation_audit_id, draft.candidate_set_id, draft.candidate_id),
            ).fetchone()
            if rejected is not None:
                raise RequirementConflictError("rejected candidate cannot be accepted without new evidence")
            binding_id = self._next_target_binding_id(connection, project_id)
            connection.execute(
                """
                INSERT INTO navigation_target_bindings(
                    project_id, navigation_audit_id, binding_id, candidate_set_id,
                    candidate_id, target_handle, selection_reason, created_at, actor,
                    request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    binding_id,
                    draft.candidate_set_id,
                    draft.candidate_id,
                    str(candidate["target_handle"]),
                    draft.selection_reason,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._set_navigation_state(
                connection,
                project_id,
                navigation_audit_id,
                NavigationAuditState.NEEDS_ORCHESTRATOR_REVIEW,
                occurred_at,
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="candidate_accepted",
                actor=actor,
                request_id=request_id,
                payload={
                    "binding_id": binding_id,
                    "candidate_set_id": draft.candidate_set_id,
                    "candidate_id": draft.candidate_id,
                    "selection_reason": draft.selection_reason,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def reject_candidate(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: CandidateRejectionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            self._candidate_row(connection, project_id, draft.candidate_set_id, draft.candidate_id)
            candidate_nav = self._candidate_navigation_audit_id(
                connection, project_id, draft.candidate_set_id
            )
            if candidate_nav != navigation_audit_id:
                raise RequirementConflictError("candidate does not belong to navigation audit")
            accepted = connection.execute(
                """
                SELECT 1 FROM navigation_target_bindings
                WHERE project_id = ? AND navigation_audit_id = ? AND candidate_set_id = ?
                  AND candidate_id = ?
                """,
                (project_id, navigation_audit_id, draft.candidate_set_id, draft.candidate_id),
            ).fetchone()
            if accepted is not None:
                raise RequirementConflictError("accepted candidate cannot be rejected")
            connection.execute(
                """
                INSERT INTO navigation_rejected_candidates(
                    project_id, navigation_audit_id, candidate_set_id, candidate_id,
                    rationale, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    draft.candidate_set_id,
                    draft.candidate_id,
                    draft.rationale,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._set_navigation_state(
                connection,
                project_id,
                navigation_audit_id,
                NavigationAuditState.NEEDS_ORCHESTRATOR_REVIEW,
                occurred_at,
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="candidate_rejected",
                actor=actor,
                request_id=request_id,
                payload={
                    "candidate_set_id": draft.candidate_set_id,
                    "candidate_id": draft.candidate_id,
                    "rationale": draft.rationale,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def attach_context_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ContextSnapshotRefDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        metadata_json = self._json(dict(draft.metadata))
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            existing = connection.execute(
                """
                SELECT provider, source_revision, summary, metadata_json
                FROM navigation_context_snapshots
                WHERE project_id = ? AND navigation_audit_id = ?
                  AND context_snapshot_id = ?
                """,
                (project_id, navigation_audit_id, draft.context_snapshot_id),
            ).fetchone()
            if existing is not None:
                existing_payload = (
                    str(existing["provider"]),
                    str(existing["source_revision"]),
                    str(existing["summary"]),
                    str(existing["metadata_json"]),
                )
                requested_payload = (
                    draft.provider,
                    draft.source_revision,
                    draft.summary,
                    metadata_json,
                )
                if existing_payload != requested_payload:
                    raise RequirementConflictError(
                        "context snapshot identity reused with different content"
                    )
                return self._navigation_audit_value(
                    connection, project_id, navigation_audit_id
                )
            connection.execute(
                """
                INSERT INTO navigation_context_snapshots(
                    project_id, navigation_audit_id, context_snapshot_id, provider,
                    source_revision, summary, metadata_json, created_at, actor,
                    request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    draft.context_snapshot_id,
                    draft.provider,
                    draft.source_revision,
                    draft.summary,
                    metadata_json,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="context_snapshot_attached",
                actor=actor,
                request_id=request_id,
                payload={
                    "context_snapshot_id": draft.context_snapshot_id,
                    "provider": draft.provider,
                    "source_revision": draft.source_revision,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def transition_navigation_audit(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: NavigationAuditState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            self._set_navigation_state(connection, project_id, navigation_audit_id, state, occurred_at)
            if state in {NavigationAuditState.CLOSED, NavigationAuditState.SUPERSEDED}:
                connection.execute(
                    """
                    UPDATE navigation_audit_blocks
                    SET closed_at = ?
                    WHERE project_id = ? AND navigation_audit_id = ?
                    """,
                    (occurred_at, project_id, navigation_audit_id),
                )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="navigation_audit_transitioned",
                actor=actor,
                request_id=str(request_id or ""),
                payload={"state": state.value, "rationale": str(rationale or "")},
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def start_provider_audit_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderAuditWindowDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            self._set_provider_window(
                connection,
                project_id,
                navigation_audit_id,
                ProviderAuditWindowState.RECORDING,
                occurred_at,
                provider=draft.provider,
                provider_capability_version=draft.provider_capability_version,
                target_scope=dict(draft.target_scope),
                snapshot_at="",
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="provider_audit_window_started",
                actor=actor,
                request_id=request_id,
                payload={
                    "provider": draft.provider,
                    "provider_capability_version": draft.provider_capability_version,
                    "target_scope": dict(draft.target_scope),
                    "source_revision": draft.source_revision,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def import_provider_navigation_snapshot(
        self,
        project_id: str,
        navigation_audit_id: str,
        draft: ProviderNavigationAuditSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._navigation_audit_row(connection, project_id, navigation_audit_id)
            existing = connection.execute(
                """
                SELECT * FROM navigation_provider_audit_snapshots
                WHERE project_id = ? AND navigation_audit_id = ?
                  AND provider = ? AND provider_snapshot_id = ?
                ORDER BY ordinal LIMIT 1
                """,
                (
                    project_id,
                    navigation_audit_id,
                    draft.provider,
                    draft.provider_snapshot_id,
                ),
            ).fetchone()
            if existing is not None:
                expected = (
                    draft.fingerprint,
                    self._json(dict(draft.target_scope)),
                    draft.selection_ref,
                    self._json([dict(value) for value in draft.exact_identities]),
                )
                actual = (
                    str(existing["fingerprint"]),
                    str(existing["target_scope_json"]),
                    str(existing["selection_ref"]),
                    str(existing["exact_identities_json"]),
                )
                if actual != expected:
                    raise RequirementConflictError(
                        "provider navigation snapshot identity reused with conflicting payload"
                    )
                return self._navigation_audit_value(
                    connection, project_id, navigation_audit_id
                )
            if request_id:
                replay = connection.execute(
                    """
                    SELECT snapshot_id FROM navigation_provider_audit_snapshots
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._navigation_audit_value(connection, project_id, navigation_audit_id)
            snapshot_id = self._next_provider_snapshot_id(connection, project_id)
            ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                    FROM navigation_provider_audit_snapshots
                    WHERE project_id = ? AND navigation_audit_id = ?
                    """,
                    (project_id, navigation_audit_id),
                ).fetchone()["ordinal"]
            )
            connection.execute(
                """
                INSERT INTO navigation_provider_audit_snapshots(
                    project_id, navigation_audit_id, snapshot_id, ordinal, provider,
                    provider_capability_version, target_scope_json, source_revision,
                    events_count, visited_files_json, visited_symbols_json,
                    visited_chunks_json, selected_target_handles_json,
                    rejected_target_handles_json, ambiguous_target_handles_json,
                    traversal_evidence_json, diagnostics_json, truncated, created_at,
                    actor, request_id, provider_snapshot_id, selection_ref, fingerprint,
                    exact_identities_json, page_refs_json, first_sequence, last_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    navigation_audit_id,
                    snapshot_id,
                    ordinal,
                    draft.provider,
                    draft.provider_capability_version,
                    self._json(dict(draft.target_scope)),
                    draft.source_revision,
                    draft.events_count,
                    self._json(list(draft.visited_files)),
                    self._json(list(draft.visited_symbols)),
                    self._json(list(draft.visited_chunks)),
                    self._json(list(draft.selected_target_handles)),
                    self._json(list(draft.rejected_target_handles)),
                    self._json(list(draft.ambiguous_target_handles)),
                    self._json(dict(draft.traversal_evidence)),
                    self._json(list(draft.diagnostics)),
                    1 if draft.truncated else 0,
                    occurred_at,
                    actor,
                    request_id,
                    draft.provider_snapshot_id,
                    draft.selection_ref,
                    draft.fingerprint,
                    self._json([dict(value) for value in draft.exact_identities]),
                    self._json(list(draft.page_refs)),
                    draft.first_sequence,
                    draft.last_sequence,
                ),
            )
            self._set_provider_window(
                connection,
                project_id,
                navigation_audit_id,
                ProviderAuditWindowState.IMPORTED_BY_FLOW,
                occurred_at,
                provider=draft.provider,
                provider_capability_version=draft.provider_capability_version,
                target_scope=dict(draft.target_scope),
                snapshot_at=occurred_at,
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="provider_navigation_snapshot_imported",
                actor=actor,
                request_id=request_id,
                payload={
                    "snapshot_id": snapshot_id,
                    "provider": draft.provider,
                    "events_count": draft.events_count,
                    "truncated": draft.truncated,
                },
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def transition_provider_audit_window(
        self,
        project_id: str,
        navigation_audit_id: str,
        state: ProviderAuditWindowState,
        *,
        actor: str,
        rationale: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        actor = required_text(actor, "actor")
        target_state = ProviderAuditWindowState(state)
        if target_state in {
            ProviderAuditWindowState.RECORDING,
            ProviderAuditWindowState.SNAPSHOT_READY,
            ProviderAuditWindowState.IMPORTED_BY_FLOW,
        }:
            raise RequirementConflictError("provider audit window transition must be terminal")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._navigation_audit_row(connection, project_id, navigation_audit_id)
            current_state = str(row["provider_window_state"])
            if target_state == ProviderAuditWindowState.FINALIZED and current_state not in {
                ProviderAuditWindowState.IMPORTED_BY_FLOW.value,
                ProviderAuditWindowState.FINALIZED.value,
            }:
                raise RequirementConflictError("provider audit window requires imported snapshot")
            if target_state == ProviderAuditWindowState.DISCARDED:
                required_text(rationale, "rationale")
            self._set_provider_window(
                connection,
                project_id,
                navigation_audit_id,
                target_state,
                occurred_at,
                provider=str(row["provider_window_provider"]),
                provider_capability_version=str(row["provider_window_capability_version"]),
                target_scope=json.loads(str(row["provider_window_target_scope_json"] or "{}")),
                snapshot_at=str(row["provider_window_snapshot_at"]),
            )
            self._append_navigation_event(
                connection,
                project_id=project_id,
                navigation_audit_id=navigation_audit_id,
                event_type="provider_audit_window_transitioned",
                actor=actor,
                request_id=str(request_id or ""),
                payload={"state": target_state.value, "rationale": str(rationale or "")},
                occurred_at=occurred_at,
            )
            return self._navigation_audit_value(connection, project_id, navigation_audit_id)

    def _navigation_audit_row(
        self, connection: sqlite3.Connection, project_id: str, navigation_audit_id: str
    ) -> sqlite3.Row:
        project_id = validate_project_id(project_id)
        navigation_audit_id = validate_navigation_audit_id(navigation_audit_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            """
            SELECT * FROM navigation_audit_blocks
            WHERE project_id = ? AND navigation_audit_id = ?
            """,
            (project_id, navigation_audit_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown navigation audit in project {project_id}: {navigation_audit_id}"
            )
        return row

    def _navigation_audit_value(
        self, connection: sqlite3.Connection, project_id: str, navigation_audit_id: str
    ) -> Mapping[str, Any]:
        row = self._navigation_audit_row(connection, project_id, navigation_audit_id)
        candidate_sets = [
            self._candidate_set_value(connection, project_id, str(item["candidate_set_id"]))
            for item in connection.execute(
                """
                SELECT candidate_set_id FROM navigation_candidate_sets
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY ordinal
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        target_bindings = [
            dict(item)
            for item in connection.execute(
                """
                SELECT binding_id, candidate_set_id, candidate_id, target_handle,
                       selection_reason, created_at, actor, request_id
                FROM navigation_target_bindings
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY binding_id
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        rejected = [
            dict(item)
            for item in connection.execute(
                """
                SELECT candidate_set_id, candidate_id, rationale, created_at, actor, request_id
                FROM navigation_rejected_candidates
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY created_at, candidate_set_id, candidate_id
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        context_snapshots = [
            {
                **dict(item),
                "metadata": json.loads(str(item["metadata_json"] or "{}")),
            }
            for item in connection.execute(
                """
                SELECT context_snapshot_id, provider, source_revision, summary,
                       metadata_json, created_at, actor, request_id
                FROM navigation_context_snapshots
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY created_at, context_snapshot_id
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        for item in context_snapshots:
            item.pop("metadata_json", None)
        provider_snapshots = [
            self._provider_snapshot_value(item)
            for item in connection.execute(
                """
                SELECT * FROM navigation_provider_audit_snapshots
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY ordinal
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        events = [
            {
                **dict(item),
                "payload": json.loads(str(item["payload_json"] or "{}")),
            }
            for item in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at
                FROM navigation_audit_events
                WHERE project_id = ? AND navigation_audit_id = ?
                ORDER BY event_id
                """,
                (project_id, navigation_audit_id),
            ).fetchall()
        ]
        for item in events:
            item.pop("payload_json", None)
        return {
            "project_id": str(row["project_id"]),
            "navigation_audit_id": str(row["navigation_audit_id"]),
            "ordinal": int(row["ordinal"]),
            "milestone_id": str(row["milestone_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "related_campaign_id": str(row["related_campaign_id"]),
            "state": str(row["state"]),
            "active_provider": str(row["active_provider"]),
            "source_revision": str(row["source_revision"]),
            "provider_audit_window": {
                "state": str(row["provider_window_state"]),
                "provider": str(row["provider_window_provider"]),
                "provider_capability_version": str(row["provider_window_capability_version"]),
                "target_scope": json.loads(str(row["provider_window_target_scope_json"] or "{}")),
                "started_at": str(row["provider_window_started_at"]),
                "snapshot_at": str(row["provider_window_snapshot_at"]),
            },
            "opened_by": str(row["opened_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "closed_at": str(row["closed_at"]),
            "candidate_sets": candidate_sets,
            "target_bindings": target_bindings,
            "rejected_candidates": rejected,
            "context_snapshots": context_snapshots,
            "provider_navigation_snapshots": provider_snapshots,
            "events": events,
        }

    @staticmethod
    def _provider_snapshot_value(row: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "snapshot_id": str(row["snapshot_id"]),
            "navigation_audit_id": str(row["navigation_audit_id"]),
            "ordinal": int(row["ordinal"]),
            "provider": str(row["provider"]),
            "provider_capability_version": str(row["provider_capability_version"]),
            "target_scope": json.loads(str(row["target_scope_json"] or "{}")),
            "source_revision": str(row["source_revision"]),
            "events_count": int(row["events_count"]),
            "visited_files": json.loads(str(row["visited_files_json"] or "[]")),
            "visited_symbols": json.loads(str(row["visited_symbols_json"] or "[]")),
            "visited_chunks": json.loads(str(row["visited_chunks_json"] or "[]")),
            "selected_target_handles": json.loads(str(row["selected_target_handles_json"] or "[]")),
            "rejected_target_handles": json.loads(str(row["rejected_target_handles_json"] or "[]")),
            "ambiguous_target_handles": json.loads(str(row["ambiguous_target_handles_json"] or "[]")),
            "traversal_evidence": json.loads(str(row["traversal_evidence_json"] or "{}")),
            "diagnostics": json.loads(str(row["diagnostics_json"] or "[]")),
            "truncated": bool(row["truncated"]),
            "provider_snapshot_id": str(row["provider_snapshot_id"]),
            "selection_ref": str(row["selection_ref"]),
            "fingerprint": str(row["fingerprint"]),
            "exact_identities": json.loads(str(row["exact_identities_json"] or "[]")),
            "page_refs": json.loads(str(row["page_refs_json"] or "[]")),
            "first_sequence": int(row["first_sequence"]),
            "last_sequence": int(row["last_sequence"]),
            "created_at": str(row["created_at"]),
            "actor": str(row["actor"]),
            "request_id": str(row["request_id"]),
        }

    def _candidate_set_value(
        self, connection: sqlite3.Connection, project_id: str, candidate_set_id: str
    ) -> Mapping[str, Any]:
        candidate_set_id = validate_candidate_set_id(candidate_set_id)
        row = connection.execute(
            """
            SELECT * FROM navigation_candidate_sets
            WHERE project_id = ? AND candidate_set_id = ?
            """,
            (project_id, candidate_set_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown candidate set: {candidate_set_id}")
        candidates = [
            self._candidate_value(candidate)
            for candidate in connection.execute(
                """
                SELECT * FROM navigation_candidate_targets
                WHERE project_id = ? AND candidate_set_id = ?
                ORDER BY candidate_id
                """,
                (project_id, candidate_set_id),
            ).fetchall()
        ]
        return {
            "candidate_set_id": str(row["candidate_set_id"]),
            "navigation_audit_id": str(row["navigation_audit_id"]),
            "ordinal": int(row["ordinal"]),
            "provider": str(row["provider"]),
            "provider_capability_version": str(row["provider_capability_version"]),
            "semantic_seeds": json.loads(str(row["semantic_seeds_json"] or "[]")),
            "metadata": json.loads(str(row["metadata_json"] or "{}")),
            "source_revision": str(row["source_revision"]),
            "truncated": bool(row["truncated"]),
            "created_at": str(row["created_at"]),
            "actor": str(row["actor"]),
            "candidates": candidates,
        }

    @staticmethod
    def _candidate_value(row: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "candidate_id": str(row["candidate_id"]),
            "target_handle": str(row["target_handle"]),
            "target_kind": str(row["target_kind"]),
            "surface_id": str(row["surface_id"]),
            "repo_or_workspace_id": str(row["repo_or_workspace_id"]),
            "file_path": str(row["file_path"]),
            "symbol_name": str(row["symbol_name"]),
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "confidence": row["confidence"],
            "selection_reason": str(row["selection_reason"]),
            "semantic_seed": str(row["semantic_seed"]),
            "graph_evidence": json.loads(str(row["graph_evidence_json"] or "{}")),
            "traversal_path": json.loads(str(row["traversal_path_json"] or "[]")),
            "diagnostics": json.loads(str(row["diagnostics_json"] or "[]")),
        }

    def _candidate_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        candidate_set_id: str,
        candidate_id: str,
    ) -> sqlite3.Row:
        candidate_set_id = validate_candidate_set_id(candidate_set_id)
        candidate_id = required_text(candidate_id, "candidate_id")
        row = connection.execute(
            """
            SELECT * FROM navigation_candidate_targets
            WHERE project_id = ? AND candidate_set_id = ? AND candidate_id = ?
            """,
            (project_id, candidate_set_id, candidate_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError("unknown navigation candidate")
        return row

    @staticmethod
    def _candidate_navigation_audit_id(
        connection: sqlite3.Connection, project_id: str, candidate_set_id: str
    ) -> str:
        row = connection.execute(
            """
            SELECT navigation_audit_id FROM navigation_candidate_sets
            WHERE project_id = ? AND candidate_set_id = ?
            """,
            (project_id, candidate_set_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError("unknown candidate set")
        return str(row["navigation_audit_id"])

    def _packet_for_navigation(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> sqlite3.Row:
        if change_id:
            return self._packet_row(connection, project_id, change_id, packet_id)
        row = connection.execute(
            """
            SELECT * FROM implementation_packets
            WHERE project_id = ? AND packet_id = ?
            """,
            (project_id, packet_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown packet in project {project_id}: {packet_id}")
        return row

    def _next_candidate_set_id(self, connection: sqlite3.Connection, project_id: str) -> str:
        ordinal = int(
            connection.execute(
                """
                SELECT next_candidate_set_ordinal FROM navigation_audit_sequences
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()["next_candidate_set_ordinal"]
        )
        connection.execute(
            """
            UPDATE navigation_audit_sequences
            SET next_candidate_set_ordinal = ?
            WHERE project_id = ?
            """,
            (ordinal + 1, project_id),
        )
        return f"CSET-{ordinal:06d}"

    def _next_target_binding_id(self, connection: sqlite3.Connection, project_id: str) -> str:
        ordinal = int(
            connection.execute(
                """
                SELECT next_binding_ordinal FROM navigation_audit_sequences
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()["next_binding_ordinal"]
        )
        connection.execute(
            """
            UPDATE navigation_audit_sequences
            SET next_binding_ordinal = ?
            WHERE project_id = ?
            """,
            (ordinal + 1, project_id),
        )
        return f"TBIND-{ordinal:06d}"

    def _next_provider_snapshot_id(self, connection: sqlite3.Connection, project_id: str) -> str:
        ordinal = int(
            connection.execute(
                """
                SELECT next_snapshot_ordinal FROM navigation_audit_sequences
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()["next_snapshot_ordinal"]
        )
        connection.execute(
            """
            UPDATE navigation_audit_sequences
            SET next_snapshot_ordinal = ?
            WHERE project_id = ?
            """,
            (ordinal + 1, project_id),
        )
        return f"NSNAP-{ordinal:06d}"

    @staticmethod
    def _set_navigation_state(
        connection: sqlite3.Connection,
        project_id: str,
        navigation_audit_id: str,
        state: NavigationAuditState,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE navigation_audit_blocks
            SET state = ?, updated_at = ?
            WHERE project_id = ? AND navigation_audit_id = ?
            """,
            (state.value, occurred_at, project_id, navigation_audit_id),
        )

    def _set_provider_window(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        navigation_audit_id: str,
        state: ProviderAuditWindowState,
        occurred_at: str,
        *,
        provider: str,
        provider_capability_version: str,
        target_scope: Mapping[str, object],
        snapshot_at: str,
    ) -> None:
        started_at = occurred_at if state == ProviderAuditWindowState.RECORDING else None
        if started_at is None:
            row = self._navigation_audit_row(connection, project_id, navigation_audit_id)
            started_at = str(row["provider_window_started_at"])
        connection.execute(
            """
            UPDATE navigation_audit_blocks
            SET provider_window_state = ?,
                provider_window_provider = ?,
                provider_window_capability_version = ?,
                provider_window_target_scope_json = ?,
                provider_window_started_at = ?,
                provider_window_snapshot_at = ?,
                updated_at = ?
            WHERE project_id = ? AND navigation_audit_id = ?
            """,
            (
                state.value,
                provider,
                provider_capability_version,
                self._json(dict(target_scope)),
                started_at,
                snapshot_at,
                occurred_at,
                project_id,
                navigation_audit_id,
            ),
        )

    def _append_navigation_event(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        navigation_audit_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO navigation_audit_events(
                project_id, navigation_audit_id, event_type, actor, request_id,
                payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                navigation_audit_id,
                event_type,
                actor,
                request_id,
                self._json(dict(payload)),
                occurred_at,
            ),
        )
