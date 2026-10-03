"""SQLite persistence for packet evidence reconciliation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    PacketEvidenceClaimDraft,
    PacketEvidenceClaimOrigin,
    PacketEvidenceClaimType,
    PacketEvidenceSnapshotDraft,
    PacketReconciliationScopeDraft,
    ReconciliationClassification,
    ReconciliationItemDisposition,
    ReconciliationItemDispositionDraft,
    ReconciliationItemDraft,
    ReconciliationScopeState,
    validate_evidence_claim_id,
    validate_evidence_snapshot_id,
    validate_reconciliation_item_id,
    validate_reconciliation_run_id,
    validate_reconciliation_scope_id,
)
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError


class PacketReconciliationStoreMixin:
    def set_packet_reconciliation_applicability(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        *,
        applicability: str,
        reason: str,
        plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        reconciliation_scope_id = validate_reconciliation_scope_id(
            reconciliation_scope_id
        )
        applicability = str(applicability or "").strip().lower()
        if applicability not in {"applicable", "deferred", "not_applicable"}:
            raise ValueError("invalid packet reconciliation applicability")
        reason = required_text(reason, "reason")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        if int(plan_revision) < 0:
            raise ValueError("plan_revision cannot be negative")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._scope_row(
                connection, project_id, reconciliation_scope_id
            )
            current = (
                str(row["applicability"]),
                str(row["applicability_reason"]),
                int(row["applicability_plan_revision"]),
            )
            desired = (applicability, reason, int(plan_revision))
            if current == desired:
                return self._reconciliation_state_value(
                    connection, project_id, reconciliation_scope_id
                )
            connection.execute(
                """
                UPDATE packet_reconciliation_scopes
                SET applicability = ?, applicability_reason = ?,
                    applicability_plan_revision = ?, updated_at = ?, actor = ?,
                    request_id = ?
                WHERE project_id = ? AND reconciliation_scope_id = ?
                """,
                (
                    applicability,
                    reason,
                    int(plan_revision),
                    occurred_at,
                    actor,
                    request_id,
                    project_id,
                    reconciliation_scope_id,
                ),
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=reconciliation_scope_id,
                event_type="reconciliation_applicability_set",
                actor=actor,
                request_id=request_id,
                payload={
                    "applicability": applicability,
                    "reason": reason,
                    "plan_revision": int(plan_revision),
                },
                occurred_at=occurred_at,
            )
            return self._reconciliation_state_value(
                connection, project_id, reconciliation_scope_id
            )

    def open_packet_reconciliation_scope(
        self,
        project_id: str,
        draft: PacketReconciliationScopeDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            current = connection.execute(
                """
                SELECT reconciliation_scope_id
                FROM packet_reconciliation_scopes
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state != 'superseded'
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, draft.change_id, draft.packet_id),
            ).fetchone()
            if current is not None:
                return self._reconciliation_state_value(
                    connection, project_id, str(current["reconciliation_scope_id"])
                )
            ordinal = self._next_reconciliation_ordinal(connection, project_id, "scope")
            scope_id = f"PRECON-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO packet_reconciliation_scopes(
                    project_id, reconciliation_scope_id, ordinal, change_id,
                    packet_id, profile, state, created_at, updated_at, actor,
                    request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    scope_id,
                    ordinal,
                    draft.change_id,
                    draft.packet_id,
                    draft.profile,
                    ReconciliationScopeState.COLLECTING.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=scope_id,
                event_type="reconciliation_scope_opened",
                actor=actor,
                request_id=request_id,
                payload={"profile": draft.profile},
                occurred_at=occurred_at,
            )
            return self._reconciliation_state_value(connection, project_id, scope_id)

    def packet_reconciliation_state(
        self, project_id: str, reconciliation_scope_id: str
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        reconciliation_scope_id = validate_reconciliation_scope_id(
            reconciliation_scope_id
        )
        with self._read_connection() as connection:
            return self._reconciliation_state_value(
                connection, project_id, reconciliation_scope_id
            )

    def packet_reconciliation_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object] | None:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT reconciliation_scope_id
                FROM packet_reconciliation_scopes
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state != 'superseded'
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if row is None:
                return None
            return self._reconciliation_state_value(
                connection, project_id, str(row["reconciliation_scope_id"])
            )

    def list_packet_reconciliations(self, project_id: str) -> list[Mapping[str, object]]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT reconciliation_scope_id FROM packet_reconciliation_scopes
                WHERE project_id = ? AND state != 'superseded'
                ORDER BY ordinal
                """,
                (project_id,),
            ).fetchall()
            return [
                self._reconciliation_state_value(
                    connection, project_id, str(row["reconciliation_scope_id"])
                )
                for row in rows
            ]

    def append_packet_evidence_claim(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        draft: PacketEvidenceClaimDraft,
        *,
        origin: str,
        snapshot_id: str = "",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        reconciliation_scope_id = validate_reconciliation_scope_id(
            reconciliation_scope_id
        )
        origin_value = PacketEvidenceClaimOrigin(origin).value
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        snapshot_id = str(snapshot_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            scope = self._scope_row(connection, project_id, reconciliation_scope_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT * FROM packet_evidence_claims
                    WHERE project_id = ? AND reconciliation_scope_id = ?
                      AND request_id = ? ORDER BY ordinal DESC LIMIT 1
                    """,
                    (project_id, reconciliation_scope_id, request_id),
                ).fetchone()
                if replay is not None:
                    if self._claim_row_semantics(replay) != self._claim_draft_semantics(
                        draft
                    ):
                        raise RequirementConflictError(
                            "request_id reused with conflicting packet evidence claim"
                        )
                    return self._claim_value(
                        connection, project_id, str(replay["claim_id"])
                    )
            existing = connection.execute(
                """
                SELECT * FROM packet_evidence_claims
                WHERE project_id = ? AND reconciliation_scope_id = ?
                  AND origin = ? AND snapshot_id = ? AND claim_key = ?
                  AND status = 'active'
                ORDER BY ordinal DESC LIMIT 1
                """,
                (
                    project_id,
                    reconciliation_scope_id,
                    origin_value,
                    snapshot_id,
                    draft.claim_key,
                ),
            ).fetchone()
            if existing is not None:
                if self._claim_row_semantics(existing) != self._claim_draft_semantics(
                    draft
                ):
                    raise RequirementConflictError(
                        "active claim key reused with different semantics"
                    )
                return self._claim_value(
                    connection, project_id, str(existing["claim_id"])
                )
            result = self._insert_claim(
                connection,
                project_id=project_id,
                reconciliation_scope_id=reconciliation_scope_id,
                draft=draft,
                origin=origin_value,
                snapshot_id=snapshot_id,
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                str(scope["change_id"]),
                str(scope["packet_id"]),
                actor=actor,
                occurred_at=occurred_at,
            )
            return result

    def supersede_packet_evidence_claim(
        self,
        project_id: str,
        claim_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        claim_id = validate_evidence_claim_id(claim_id)
        rationale = required_text(rationale, "rationale")
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._claim_row(connection, project_id, claim_id)
            if str(row["origin"]) != PacketEvidenceClaimOrigin.DECLARED.value:
                raise ChangeControlBlockedError("observed_claim_is_immutable")
            if str(row["status"]) == "superseded":
                return self._claim_value(connection, project_id, claim_id)
            connection.execute(
                """
                UPDATE packet_evidence_claims
                SET status = 'superseded', updated_at = ?
                WHERE project_id = ? AND claim_id = ?
                """,
                (occurred_at, project_id, claim_id),
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=str(row["reconciliation_scope_id"]),
                event_type="declared_claim_superseded",
                actor=actor,
                request_id=request_id,
                payload={"claim_id": claim_id, "rationale": rationale},
                occurred_at=occurred_at,
            )
            self._mark_scope_reconciliation_required(
                connection,
                project_id,
                str(row["reconciliation_scope_id"]),
                occurred_at,
            )
            return self._claim_value(connection, project_id, claim_id)

    def import_packet_evidence_snapshot(
        self,
        project_id: str,
        draft: PacketEvidenceSnapshotDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            scope = self._scope_row(
                connection, project_id, draft.reconciliation_scope_id
            )
            if str(scope["packet_id"]) != draft.packet_id:
                raise ChangeControlBlockedError("packet_evidence_scope_mismatch")
            existing = connection.execute(
                """
                SELECT * FROM packet_evidence_snapshots
                WHERE project_id = ? AND provider_id = ? AND provider_snapshot_id = ?
                """,
                (project_id, draft.provider_id, draft.provider_snapshot_id),
            ).fetchone()
            if existing is not None:
                if self._snapshot_row_identity(existing) != self._snapshot_draft_identity(
                    draft
                ):
                    raise RequirementConflictError(
                        "provider snapshot identity reused with conflicting payload"
                    )
                return self._snapshot_value(
                    connection, project_id, str(existing["snapshot_id"])
                )
            ordinal = self._next_reconciliation_ordinal(connection, project_id, "snapshot")
            snapshot_id = f"PESNAP-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO packet_evidence_snapshots(
                    project_id, snapshot_id, reconciliation_scope_id, ordinal,
                    contract_version, packet_id, provider_id, provider_scope_id,
                    provider_snapshot_id, selection_ref, source_revision,
                    workspace_revision, surfaces_json, fingerprint, truncated,
                    completeness_json, diagnostics_json, created_at, actor,
                    request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    snapshot_id,
                    draft.reconciliation_scope_id,
                    ordinal,
                    draft.contract_version,
                    draft.packet_id,
                    draft.provider_id,
                    draft.provider_scope_id,
                    draft.provider_snapshot_id,
                    draft.selection_ref,
                    draft.source_revision,
                    draft.workspace_revision,
                    self._json(list(draft.surfaces)),
                    draft.fingerprint,
                    int(draft.truncated),
                    self._json(dict(draft.completeness)),
                    self._json(list(draft.diagnostics)),
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            for claim in draft.claims:
                self._insert_claim(
                    connection,
                    project_id=project_id,
                    reconciliation_scope_id=draft.reconciliation_scope_id,
                    draft=claim,
                    origin=PacketEvidenceClaimOrigin.OBSERVED.value,
                    snapshot_id=snapshot_id,
                    actor=actor,
                    request_id="",
                    occurred_at=occurred_at,
                )
            self._mark_scope_reconciliation_required(
                connection,
                project_id,
                draft.reconciliation_scope_id,
                occurred_at,
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=draft.reconciliation_scope_id,
                event_type="packet_evidence_snapshot_imported",
                actor=actor,
                request_id=request_id,
                payload={
                    "snapshot_id": snapshot_id,
                    "provider_snapshot_id": draft.provider_snapshot_id,
                    "claim_count": len(draft.claims),
                },
                occurred_at=occurred_at,
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                str(scope["change_id"]),
                str(scope["packet_id"]),
                actor=actor,
                occurred_at=occurred_at,
            )
            return self._snapshot_value(connection, project_id, snapshot_id)

    def record_packet_reconciliation_run(
        self,
        project_id: str,
        reconciliation_scope_id: str,
        snapshot_id: str,
        *,
        packet_fingerprint: str,
        items: tuple[ReconciliationItemDraft, ...],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        reconciliation_scope_id = validate_reconciliation_scope_id(
            reconciliation_scope_id
        )
        snapshot_id = validate_evidence_snapshot_id(snapshot_id)
        packet_fingerprint = required_text(packet_fingerprint, "packet_fingerprint")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            scope = self._scope_row(connection, project_id, reconciliation_scope_id)
            snapshot = connection.execute(
                """
                SELECT reconciliation_scope_id FROM packet_evidence_snapshots
                WHERE project_id = ? AND snapshot_id = ?
                """,
                (project_id, snapshot_id),
            ).fetchone()
            if snapshot is None:
                raise ValueError("unknown packet evidence snapshot")
            if str(snapshot["reconciliation_scope_id"]) != reconciliation_scope_id:
                raise ChangeControlBlockedError("packet_evidence_scope_mismatch")
            if request_id:
                replay = connection.execute(
                    """
                    SELECT run_id, snapshot_id, packet_fingerprint
                    FROM packet_reconciliation_runs
                    WHERE project_id = ? AND reconciliation_scope_id = ?
                      AND request_id = ? ORDER BY ordinal DESC LIMIT 1
                    """,
                    (project_id, reconciliation_scope_id, request_id),
                ).fetchone()
                if replay is not None:
                    if (
                        str(replay["snapshot_id"]) != snapshot_id
                        or str(replay["packet_fingerprint"]) != packet_fingerprint
                    ):
                        raise RequirementConflictError(
                            "request_id reused with conflicting reconciliation run"
                        )
                    return self._packet_reconciliation_run_value(
                        connection, project_id, str(replay["run_id"])
                    )
            prior_runs = connection.execute(
                """
                SELECT run_id FROM packet_reconciliation_runs
                WHERE project_id = ? AND reconciliation_scope_id = ? AND superseded = 0
                """,
                (project_id, reconciliation_scope_id),
            ).fetchall()
            for prior in prior_runs:
                prior_id = str(prior["run_id"])
                connection.execute(
                    """
                    UPDATE packet_reconciliation_runs SET superseded = 1
                    WHERE project_id = ? AND run_id = ?
                    """,
                    (project_id, prior_id),
                )
                connection.execute(
                    """
                    UPDATE packet_reconciliation_items
                    SET disposition = 'superseded', updated_at = ?
                    WHERE project_id = ? AND run_id = ? AND disposition = 'open'
                    """,
                    (occurred_at, project_id, prior_id),
                )
            run_ordinal = self._next_reconciliation_ordinal(connection, project_id, "run")
            run_id = f"RCRUN-{run_ordinal:06d}"
            blocking_count = sum(1 for item in items if item.blocking)
            run_state = "ready" if blocking_count == 0 else "blocked"
            summary = {
                "item_count": len(items),
                "blocking_count": blocking_count,
                "classifications": {
                    value: sum(1 for item in items if item.classification.value == value)
                    for value in sorted({item.classification.value for item in items})
                },
            }
            connection.execute(
                """
                INSERT INTO packet_reconciliation_runs(
                    project_id, run_id, reconciliation_scope_id, snapshot_id,
                    ordinal, packet_fingerprint, state, summary_json,
                    superseded, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    project_id,
                    run_id,
                    reconciliation_scope_id,
                    snapshot_id,
                    run_ordinal,
                    packet_fingerprint,
                    run_state,
                    self._json(summary),
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            for item in items:
                item_ordinal = self._next_reconciliation_ordinal(
                    connection, project_id, "item"
                )
                item_id = f"RCITEM-{item_ordinal:06d}"
                connection.execute(
                    """
                    INSERT INTO packet_reconciliation_items(
                        project_id, item_id, run_id, reconciliation_scope_id,
                        ordinal, claim_type, claim_key, declared_claim_ids_json,
                        observed_claim_ids_json, classification, blocking,
                        severity, closure_condition, next_action_json,
                        disposition, rationale, policy_ref, attempt_count,
                        max_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', '', '', 0, ?, ?, ?)
                    """,
                    (
                        project_id,
                        item_id,
                        run_id,
                        reconciliation_scope_id,
                        item_ordinal,
                        item.claim_type.value,
                        item.claim_key,
                        self._json(list(item.declared_claim_ids)),
                        self._json(list(item.observed_claim_ids)),
                        item.classification.value,
                        int(item.blocking),
                        item.severity,
                        item.closure_condition,
                        self._json(dict(item.next_action)),
                        item.max_attempts,
                        occurred_at,
                        occurred_at,
                    ),
                )
            connection.execute(
                """
                UPDATE packet_reconciliation_scopes SET state = ?, updated_at = ?
                WHERE project_id = ? AND reconciliation_scope_id = ?
                """,
                (
                    ReconciliationScopeState.READY.value
                    if run_state == "ready"
                    else ReconciliationScopeState.BLOCKED.value,
                    occurred_at,
                    project_id,
                    reconciliation_scope_id,
                ),
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=reconciliation_scope_id,
                event_type="packet_evidence_reconciled",
                actor=actor,
                request_id=request_id,
                payload={"run_id": run_id, **summary},
                occurred_at=occurred_at,
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                str(scope["change_id"]),
                str(scope["packet_id"]),
                actor=actor,
                occurred_at=occurred_at,
            )
            return self._packet_reconciliation_run_value(
                connection, project_id, run_id
            )

    def disposition_packet_reconciliation_item(
        self,
        project_id: str,
        draft: ReconciliationItemDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._item_row(connection, project_id, draft.item_id)
            if str(row["disposition"]) == ReconciliationItemDisposition.SUPERSEDED.value:
                raise ChangeControlBlockedError("reconciliation_item_superseded")
            if draft.disposition == ReconciliationItemDisposition.RESOLVED:
                raise ChangeControlBlockedError(
                    "reconciliation_resolution_requires_new_evidence"
                )
            if (
                draft.disposition == ReconciliationItemDisposition.REJECTED
                and str(row["classification"])
                != ReconciliationClassification.PROPOSED.value
            ):
                raise ChangeControlBlockedError(
                    "reconciliation_rejection_requires_provider_proposal"
                )
            connection.execute(
                """
                UPDATE packet_reconciliation_items
                SET disposition = ?, rationale = ?, policy_ref = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE project_id = ? AND item_id = ?
                """,
                (
                    draft.disposition.value,
                    draft.rationale,
                    draft.policy_ref,
                    occurred_at,
                    project_id,
                    draft.item_id,
                ),
            )
            scope_id = str(row["reconciliation_scope_id"])
            open_blocking = connection.execute(
                """
                SELECT 1 FROM packet_reconciliation_items i
                JOIN packet_reconciliation_runs r
                  ON r.project_id = i.project_id AND r.run_id = i.run_id
                WHERE i.project_id = ? AND i.reconciliation_scope_id = ?
                  AND r.superseded = 0 AND i.blocking = 1
                  AND i.disposition IN ('open', 'rejected', 'escalated')
                LIMIT 1
                """,
                (project_id, scope_id),
            ).fetchone()
            connection.execute(
                """
                UPDATE packet_reconciliation_scopes SET state = ?, updated_at = ?
                WHERE project_id = ? AND reconciliation_scope_id = ?
                """,
                (
                    ReconciliationScopeState.BLOCKED.value
                    if open_blocking is not None
                    else ReconciliationScopeState.READY.value,
                    occurred_at,
                    project_id,
                    scope_id,
                ),
            )
            connection.execute(
                """
                UPDATE packet_reconciliation_runs SET state = ?
                WHERE project_id = ? AND run_id = ? AND superseded = 0
                """,
                (
                    "blocked" if open_blocking is not None else "ready",
                    project_id,
                    str(row["run_id"]),
                ),
            )
            self._append_reconciliation_event(
                connection,
                project_id=project_id,
                reconciliation_scope_id=scope_id,
                event_type="reconciliation_item_dispositioned",
                actor=actor,
                request_id=request_id,
                payload={
                    "item_id": draft.item_id,
                    "disposition": draft.disposition.value,
                    "policy_ref": draft.policy_ref,
                },
                occurred_at=occurred_at,
            )
            return self._reconciliation_state_value(connection, project_id, scope_id)

    def packet_reconciliation_fingerprint(
        self, project_id: str, change_id: str, packet_id: str
    ) -> str:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            return self._packet_reconciliation_fingerprint_for_connection(
                connection, project_id, change_id, packet_id
            )

    def packet_reconciliation_expected_source_revisions(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            return self._expected_source_revisions_for_connection(
                connection, project_id, change_id, packet_id
            )

    def packet_reconciliation_expected_evidence_context(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            rows = self._accepted_target_rows(connection, project_id, change_id, packet_id)
            source_revisions: set[str] = set()
            workspace_revisions: set[str] = set()
            provider_ids: set[str] = set()
            provider_scope_ids: set[str] = set()
            selection_refs: set[str] = set()
            surface_ids: set[str] = set()
            contexts_by_identity: dict[tuple[str, ...], dict[str, object]] = {}
            for row in rows:
                metadata = self._reconciliation_json_mapping(row["metadata_json"])
                provider_snapshot_marker = str(
                    metadata.get("provider_snapshot_id") or ""
                ).strip()
                authoritative_snapshot_found = bool(
                    str(row["authoritative_provider_snapshot_id"] or "").strip()
                )
                authoritative_scope = self._reconciliation_json_mapping(
                    row["authoritative_target_scope_json"]
                )
                if provider_snapshot_marker and authoritative_snapshot_found:
                    provider_id = str(row["authoritative_provider"] or "").strip()
                    source_revision = str(
                        row["authoritative_source_revision"] or ""
                    ).strip()
                    provider_scope_id = str(
                        authoritative_scope.get("scope_id") or ""
                    ).strip()
                    workspace_revision = str(
                        authoritative_scope.get("workspace_revision") or ""
                    ).strip()
                    selection_ref = str(
                        row["authoritative_selection_ref"] or ""
                    ).strip()
                    surface_id = str(
                        authoritative_scope.get("surface") or ""
                    ).strip()
                elif provider_snapshot_marker:
                    provider_id = ""
                    source_revision = ""
                    provider_scope_id = ""
                    workspace_revision = ""
                    selection_ref = ""
                    surface_id = ""
                else:
                    provider_id = str(row["provider"])
                    source_revision = str(row["source_revision"])
                    provider_scope_id = str(
                        metadata.get("provider_scope_id") or ""
                    ).strip()
                    workspace_revision = str(
                        metadata.get("workspace_revision") or ""
                    ).strip()
                    selection_ref = str(
                        metadata.get("provider_selection_ref")
                        or row["candidate_set_id"]
                    ).strip()
                    surface_id = str(
                        metadata.get("provider_surface_id") or ""
                    ).strip()
                if source_revision:
                    source_revisions.add(source_revision)
                if provider_id:
                    provider_ids.add(provider_id)
                if provider_scope_id:
                    provider_scope_ids.add(provider_scope_id)
                if workspace_revision:
                    workspace_revisions.add(workspace_revision)
                if selection_ref:
                    selection_refs.add(selection_ref)
                if surface_id:
                    surface_ids.add(surface_id)
                context_identity = (
                    provider_id,
                    provider_scope_id,
                    selection_ref,
                    source_revision,
                    workspace_revision,
                    surface_id,
                )
                context = contexts_by_identity.setdefault(
                    context_identity,
                    {
                        "provider_id": provider_id,
                        "provider_scope_id": provider_scope_id,
                        "selection_ref": selection_ref,
                        "source_revision": source_revision,
                        "workspace_revision": workspace_revision,
                        "provider_surface_id": surface_id,
                        "target_handles": [],
                        "binding_ids": [],
                        "latest_binding_id": "",
                        "provider_snapshot_id": provider_snapshot_marker,
                        "authoritative_snapshot_found": (
                            authoritative_snapshot_found
                            if provider_snapshot_marker
                            else True
                        ),
                    },
                )
                target_handle = str(row["target_handle"])
                target_handles = context["target_handles"]
                if isinstance(target_handles, list) and target_handle not in target_handles:
                    target_handles.append(target_handle)
                binding_id = str(row["binding_id"])
                binding_ids = context["binding_ids"]
                if isinstance(binding_ids, list):
                    binding_ids.append(binding_id)
                context["latest_binding_id"] = binding_id
            return {
                "provider_ids": sorted(provider_ids),
                "provider_scope_ids": sorted(provider_scope_ids),
                "selection_refs": sorted(selection_refs),
                "source_revisions": sorted(source_revisions),
                "workspace_revisions": sorted(workspace_revisions),
                "surface_ids": sorted(surface_ids),
                "contexts": sorted(
                    contexts_by_identity.values(),
                    key=lambda item: (
                        str(item.get("latest_binding_id") or ""),
                        str(item.get("selection_ref") or ""),
                    ),
                ),
            }

    def packet_reconciliation_run(
        self, project_id: str, run_id: str
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        run_id = validate_reconciliation_run_id(run_id)
        with self._read_connection() as connection:
            return self._packet_reconciliation_run_value(connection, project_id, run_id)

    def packet_reconciliation_target_claims(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[PacketEvidenceClaimDraft, ...]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            rows = self._accepted_target_rows(connection, project_id, change_id, packet_id)
            grouped: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault(str(row["target_handle"]), []).append(row)
            return tuple(
                PacketEvidenceClaimDraft(
                    claim_type=PacketEvidenceClaimType.TARGET,
                    claim_key=f"target:{target_handle}",
                    subject_ref=target_handle,
                    predicate="selected_target",
                    assertion={
                        "derived_from": "accepted_target_binding",
                        "binding_ids": sorted(
                            str(row["binding_id"]) for row in target_rows
                        ),
                        "surfaces": sorted(
                            {str(row["surface_id"]) for row in target_rows}
                        ),
                        "file_paths": sorted(
                            {str(row["file_path"]) for row in target_rows}
                        ),
                        "symbol_names": sorted(
                            {str(row["symbol_name"]) for row in target_rows}
                        ),
                    },
                    evidence_refs=tuple(
                        sorted(str(row["binding_id"]) for row in target_rows)
                    ),
                    required=True,
                )
                for target_handle, target_rows in sorted(grouped.items())
            )

    def packet_reconciliation_readiness_blockers(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            return self._packet_reconciliation_blockers_for_connection(
                connection, project_id, change_id, packet_id
            )

    def _packet_reconciliation_blockers_for_connection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> tuple[str, ...]:
        scope = connection.execute(
            """
            SELECT * FROM packet_reconciliation_scopes
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND state != 'superseded'
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, change_id, packet_id),
        ).fetchone()
        if scope is None:
            return ()
        if str(scope["applicability"]) != "applicable":
            return ()
        blockers: list[str] = []
        snapshot = connection.execute(
            """
            SELECT snapshot_id FROM packet_evidence_snapshots
            WHERE project_id = ? AND reconciliation_scope_id = ?
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, scope["reconciliation_scope_id"]),
        ).fetchone()
        if snapshot is None:
            blockers.append("packet_evidence_snapshot_missing")
        run = connection.execute(
            """
            SELECT * FROM packet_reconciliation_runs
            WHERE project_id = ? AND reconciliation_scope_id = ? AND superseded = 0
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, scope["reconciliation_scope_id"]),
        ).fetchone()
        if run is None:
            blockers.append("packet_evidence_reconciliation_missing")
        else:
            if snapshot is not None and str(run["snapshot_id"]) != str(
                snapshot["snapshot_id"]
            ):
                blockers.append("packet_evidence_reconciliation_stale")
            current_fingerprint = self._packet_reconciliation_fingerprint_for_connection(
                connection, project_id, change_id, packet_id
            )
            if str(run["packet_fingerprint"]) != current_fingerprint:
                blockers.append("packet_evidence_reconciliation_stale")
            open_item = connection.execute(
                """
                SELECT 1 FROM packet_reconciliation_items
                WHERE project_id = ? AND run_id = ? AND blocking = 1
                  AND disposition IN ('open', 'rejected', 'escalated') LIMIT 1
                """,
                (project_id, run["run_id"]),
            ).fetchone()
            if open_item is not None:
                blockers.append("packet_evidence_residuals_open")
        return tuple(dict.fromkeys(blockers))

    def _insert_claim(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        reconciliation_scope_id: str,
        draft: PacketEvidenceClaimDraft,
        origin: str,
        snapshot_id: str,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> Mapping[str, object]:
        ordinal = self._next_reconciliation_ordinal(connection, project_id, "claim")
        claim_id = f"PECLAIM-{ordinal:06d}"
        connection.execute(
            """
            INSERT INTO packet_evidence_claims(
                project_id, claim_id, reconciliation_scope_id, snapshot_id,
                ordinal, origin, claim_type, claim_key, subject_ref, predicate,
                object_ref, assertion_json, evidence_refs_json, required,
                dynamic, contradicted, status, created_at, updated_at, actor,
                request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                project_id,
                claim_id,
                reconciliation_scope_id,
                snapshot_id,
                ordinal,
                origin,
                draft.claim_type.value,
                draft.claim_key,
                draft.subject_ref,
                draft.predicate,
                draft.object_ref,
                self._json(dict(draft.assertion)),
                self._json(list(draft.evidence_refs)),
                int(draft.required),
                int(draft.dynamic),
                int(draft.contradicted),
                occurred_at,
                occurred_at,
                actor,
                request_id,
            ),
        )
        return self._claim_value(connection, project_id, claim_id)

    def _reconciliation_state_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        reconciliation_scope_id: str,
    ) -> Mapping[str, object]:
        scope = self._scope_row(connection, project_id, reconciliation_scope_id)
        claims = [
            self._claim_row_value(row)
            for row in connection.execute(
                """
                SELECT * FROM packet_evidence_claims
                WHERE project_id = ? AND reconciliation_scope_id = ?
                ORDER BY ordinal
                """,
                (project_id, reconciliation_scope_id),
            ).fetchall()
        ]
        snapshots = [
            self._snapshot_row_value(row)
            for row in connection.execute(
                """
                SELECT * FROM packet_evidence_snapshots
                WHERE project_id = ? AND reconciliation_scope_id = ?
                ORDER BY ordinal
                """,
                (project_id, reconciliation_scope_id),
            ).fetchall()
        ]
        run_row = connection.execute(
            """
            SELECT * FROM packet_reconciliation_runs
            WHERE project_id = ? AND reconciliation_scope_id = ? AND superseded = 0
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, reconciliation_scope_id),
        ).fetchone()
        latest_run = {} if run_row is None else self._run_row_value(connection, run_row)
        blockers = self._packet_reconciliation_blockers_for_connection(
            connection,
            project_id,
            str(scope["change_id"]),
            str(scope["packet_id"]),
        )
        return {
            "reconciliation_scope_id": reconciliation_scope_id,
            "project_id": project_id,
            "change_id": str(scope["change_id"]),
            "packet_id": str(scope["packet_id"]),
            "profile": str(scope["profile"]),
            "state": str(scope["state"]),
            "applicability": str(scope["applicability"]),
            "applicability_reason": str(scope["applicability_reason"]),
            "applicability_plan_revision": int(
                scope["applicability_plan_revision"]
            ),
            "created_at": str(scope["created_at"]),
            "updated_at": str(scope["updated_at"]),
            "claims": claims,
            "snapshots": snapshots,
            "latest_run": latest_run,
            "readiness_blockers": list(blockers),
        }

    def _packet_reconciliation_run_value(
        self, connection: sqlite3.Connection, project_id: str, run_id: str
    ) -> Mapping[str, object]:
        row = connection.execute(
            "SELECT * FROM packet_reconciliation_runs WHERE project_id = ? AND run_id = ?",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown packet reconciliation run")
        return self._run_row_value(connection, row)

    def _run_row_value(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Mapping[str, object]:
        items = [
            self._item_row_value(item)
            for item in connection.execute(
                """
                SELECT * FROM packet_reconciliation_items
                WHERE project_id = ? AND run_id = ? ORDER BY ordinal
                """,
                (row["project_id"], row["run_id"]),
            ).fetchall()
        ]
        return {
            "run_id": str(row["run_id"]),
            "reconciliation_scope_id": str(row["reconciliation_scope_id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "packet_fingerprint": str(row["packet_fingerprint"]),
            "state": str(row["state"]),
            "summary": self._reconciliation_json_mapping(row["summary_json"]),
            "superseded": bool(row["superseded"]),
            "created_at": str(row["created_at"]),
            "items": items,
        }

    def _claim_value(
        self, connection: sqlite3.Connection, project_id: str, claim_id: str
    ) -> Mapping[str, object]:
        return self._claim_row_value(self._claim_row(connection, project_id, claim_id))

    def _claim_row_value(self, row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "claim_id": str(row["claim_id"]),
            "reconciliation_scope_id": str(row["reconciliation_scope_id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "origin": str(row["origin"]),
            "claim_type": str(row["claim_type"]),
            "claim_key": str(row["claim_key"]),
            "subject_ref": str(row["subject_ref"]),
            "predicate": str(row["predicate"]),
            "object_ref": str(row["object_ref"]),
            "assertion": self._reconciliation_json_mapping(row["assertion_json"]),
            "evidence_refs": self._reconciliation_json_string_list(
                row["evidence_refs_json"]
            ),
            "required": bool(row["required"]),
            "dynamic": bool(row["dynamic"]),
            "contradicted": bool(row["contradicted"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _snapshot_value(
        self, connection: sqlite3.Connection, project_id: str, snapshot_id: str
    ) -> Mapping[str, object]:
        row = connection.execute(
            "SELECT * FROM packet_evidence_snapshots WHERE project_id = ? AND snapshot_id = ?",
            (project_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown packet evidence snapshot")
        return self._snapshot_row_value(row)

    def _snapshot_row_value(self, row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "snapshot_id": str(row["snapshot_id"]),
            "reconciliation_scope_id": str(row["reconciliation_scope_id"]),
            "contract_version": str(row["contract_version"]),
            "packet_id": str(row["packet_id"]),
            "provider_id": str(row["provider_id"]),
            "provider_scope_id": str(row["provider_scope_id"]),
            "provider_snapshot_id": str(row["provider_snapshot_id"]),
            "selection_ref": str(row["selection_ref"]),
            "source_revision": str(row["source_revision"]),
            "workspace_revision": str(row["workspace_revision"]),
            "surfaces": self._reconciliation_json_string_list(row["surfaces_json"]),
            "fingerprint": str(row["fingerprint"]),
            "truncated": bool(row["truncated"]),
            "completeness": self._reconciliation_json_mapping(
                row["completeness_json"]
            ),
            "diagnostics": self._reconciliation_json_string_list(
                row["diagnostics_json"]
            ),
            "created_at": str(row["created_at"]),
        }

    def _item_row_value(self, row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "item_id": str(row["item_id"]),
            "run_id": str(row["run_id"]),
            "claim_type": str(row["claim_type"]),
            "claim_key": str(row["claim_key"]),
            "declared_claim_ids": self._reconciliation_json_string_list(
                row["declared_claim_ids_json"]
            ),
            "observed_claim_ids": self._reconciliation_json_string_list(
                row["observed_claim_ids_json"]
            ),
            "classification": str(row["classification"]),
            "blocking": bool(row["blocking"]),
            "severity": str(row["severity"]),
            "closure_condition": str(row["closure_condition"]),
            "next_action": self._reconciliation_json_mapping(
                row["next_action_json"]
            ),
            "disposition": str(row["disposition"]),
            "rationale": str(row["rationale"]),
            "policy_ref": str(row["policy_ref"]),
            "attempt_count": int(row["attempt_count"]),
            "max_attempts": int(row["max_attempts"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _packet_reconciliation_fingerprint_for_connection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> str:
        packet = self._packet_row(connection, project_id, change_id, packet_id)
        fields = {
            "title": str(packet["title"]),
            "objective": str(packet["objective"]),
            "rationale": str(packet["rationale"]),
            "requirement_ids": self._reconciliation_json_string_list(
                packet["requirement_ids_json"]
            ),
            "goal_ids": self._reconciliation_json_string_list(packet["goal_ids_json"]),
            "in_scope": self._reconciliation_json_string_list(packet["in_scope_json"]),
            "out_of_scope": self._reconciliation_json_string_list(
                packet["out_of_scope_json"]
            ),
            "invariants": self._reconciliation_json_string_list(
                packet["invariants_json"]
            ),
            "completion_criteria": self._reconciliation_json_string_list(
                packet["completion_criteria_json"]
            ),
            "targets": [
                {
                    "binding_id": str(row["binding_id"]),
                    "target_handle": str(row["target_handle"]),
                    "source_revision": str(row["source_revision"]),
                }
                for row in self._accepted_target_rows(
                    connection, project_id, change_id, packet_id
                )
            ],
            "declared_claims": [
                {
                    "claim_type": str(row["claim_type"]),
                    "claim_key": str(row["claim_key"]),
                    "subject_ref": str(row["subject_ref"]),
                    "predicate": str(row["predicate"]),
                    "object_ref": str(row["object_ref"]),
                    "assertion": self._reconciliation_json_mapping(
                        row["assertion_json"]
                    ),
                    "required": bool(row["required"]),
                    "dynamic": bool(row["dynamic"]),
                    "contradicted": bool(row["contradicted"]),
                }
                for row in connection.execute(
                    """
                    SELECT claim_type, claim_key, subject_ref, predicate,
                           object_ref, assertion_json, required, dynamic,
                           contradicted
                    FROM packet_evidence_claims
                    WHERE project_id = ? AND reconciliation_scope_id = (
                        SELECT reconciliation_scope_id
                        FROM packet_reconciliation_scopes
                        WHERE project_id = ? AND change_id = ? AND packet_id = ?
                          AND state != 'superseded'
                        ORDER BY ordinal DESC LIMIT 1
                    ) AND origin = 'declared' AND status = 'active'
                    ORDER BY claim_key, claim_id
                    """,
                    (project_id, project_id, change_id, packet_id),
                ).fetchall()
            ],
        }
        encoded = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _expected_source_revisions_for_connection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> tuple[str, ...]:
        values = {
            str(row["source_revision"])
            for row in self._accepted_target_rows(connection, project_id, change_id, packet_id)
            if str(row["source_revision"])
        }
        return tuple(sorted(values))

    def _claim_row_semantics(self, row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "claim_type": str(row["claim_type"]),
            "subject_ref": str(row["subject_ref"]),
            "predicate": str(row["predicate"]),
            "object_ref": str(row["object_ref"]),
            "assertion": self._reconciliation_json_mapping(row["assertion_json"]),
            "evidence_refs": self._reconciliation_json_string_list(
                row["evidence_refs_json"]
            ),
            "required": bool(row["required"]),
            "dynamic": bool(row["dynamic"]),
            "contradicted": bool(row["contradicted"]),
        }

    @staticmethod
    def _claim_draft_semantics(draft: PacketEvidenceClaimDraft) -> Mapping[str, object]:
        return {
            "claim_type": draft.claim_type.value,
            "subject_ref": draft.subject_ref,
            "predicate": draft.predicate,
            "object_ref": draft.object_ref,
            "assertion": dict(draft.assertion),
            "evidence_refs": list(draft.evidence_refs),
            "required": draft.required,
            "dynamic": draft.dynamic,
            "contradicted": draft.contradicted,
        }

    def _snapshot_row_identity(self, row: sqlite3.Row) -> Mapping[str, object]:
        return {
            "reconciliation_scope_id": str(row["reconciliation_scope_id"]),
            "contract_version": str(row["contract_version"]),
            "packet_id": str(row["packet_id"]),
            "provider_scope_id": str(row["provider_scope_id"]),
            "selection_ref": str(row["selection_ref"]),
            "source_revision": str(row["source_revision"]),
            "workspace_revision": str(row["workspace_revision"]),
            "surfaces": self._reconciliation_json_string_list(row["surfaces_json"]),
            "fingerprint": str(row["fingerprint"]),
            "truncated": bool(row["truncated"]),
            "completeness": self._reconciliation_json_mapping(
                row["completeness_json"]
            ),
            "diagnostics": self._reconciliation_json_string_list(
                row["diagnostics_json"]
            ),
        }

    @staticmethod
    def _snapshot_draft_identity(
        draft: PacketEvidenceSnapshotDraft,
    ) -> Mapping[str, object]:
        return {
            "reconciliation_scope_id": draft.reconciliation_scope_id,
            "contract_version": draft.contract_version,
            "packet_id": draft.packet_id,
            "provider_scope_id": draft.provider_scope_id,
            "selection_ref": draft.selection_ref,
            "source_revision": draft.source_revision,
            "workspace_revision": draft.workspace_revision,
            "surfaces": list(draft.surfaces),
            "fingerprint": draft.fingerprint,
            "truncated": draft.truncated,
            "completeness": dict(draft.completeness),
            "diagnostics": list(draft.diagnostics),
        }

    @staticmethod
    def _reconciliation_json_mapping(value: object) -> dict[str, object]:
        try:
            decoded = json.loads(str(value or "{}"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError(
                "stored packet reconciliation object is invalid"
            ) from exc
        if not isinstance(decoded, dict):
            raise RequirementConflictError(
                "stored packet reconciliation object is invalid"
            )
        return {str(key): item for key, item in decoded.items()}

    @staticmethod
    def _reconciliation_json_string_list(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value or "[]"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError(
                "stored packet reconciliation list is invalid"
            ) from exc
        if not isinstance(decoded, list) or any(
            not isinstance(item, str) for item in decoded
        ):
            raise RequirementConflictError(
                "stored packet reconciliation list is invalid"
            )
        return list(decoded)

    @staticmethod
    def _accepted_target_rows(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT b.binding_id, b.target_handle, b.candidate_set_id,
                   b.candidate_id, c.surface_id, c.file_path, c.symbol_name,
                   s.provider, s.source_revision, s.metadata_json,
                   p.provider_snapshot_id AS authoritative_provider_snapshot_id,
                   p.provider AS authoritative_provider,
                   p.source_revision AS authoritative_source_revision,
                   p.selection_ref AS authoritative_selection_ref,
                   p.target_scope_json AS authoritative_target_scope_json
            FROM navigation_target_bindings b
            JOIN navigation_audit_blocks n
              ON n.project_id = b.project_id
             AND n.navigation_audit_id = b.navigation_audit_id
            JOIN navigation_candidate_targets c
              ON c.project_id = b.project_id
             AND c.candidate_set_id = b.candidate_set_id
             AND c.candidate_id = b.candidate_id
            JOIN navigation_candidate_sets s
              ON s.project_id = b.project_id
             AND s.candidate_set_id = b.candidate_set_id
            LEFT JOIN navigation_provider_audit_snapshots p
              ON p.project_id = b.project_id
             AND p.navigation_audit_id = b.navigation_audit_id
             AND p.provider_snapshot_id = json_extract(
                    s.metadata_json, '$.provider_snapshot_id'
                 )
            WHERE b.project_id = ? AND n.change_id = ? AND n.packet_id = ?
              AND n.state = 'accepted_for_packet'
            ORDER BY b.binding_id
            """,
            (project_id, change_id, packet_id),
        ).fetchall()

    @staticmethod
    def _scope_row(
        connection: sqlite3.Connection,
        project_id: str,
        reconciliation_scope_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_reconciliation_scopes
            WHERE project_id = ? AND reconciliation_scope_id = ?
            """,
            (project_id, reconciliation_scope_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown packet reconciliation scope")
        return row

    @staticmethod
    def _claim_row(
        connection: sqlite3.Connection, project_id: str, claim_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM packet_evidence_claims WHERE project_id = ? AND claim_id = ?",
            (project_id, claim_id),
        ).fetchone()
        if row is None:
            raise ValueError("unknown packet evidence claim")
        return row

    @staticmethod
    def _item_row(
        connection: sqlite3.Connection, project_id: str, item_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM packet_reconciliation_items WHERE project_id = ? AND item_id = ?",
            (project_id, validate_reconciliation_item_id(item_id)),
        ).fetchone()
        if row is None:
            raise ValueError("unknown packet reconciliation item")
        return row

    def _next_reconciliation_ordinal(
        self, connection: sqlite3.Connection, project_id: str, kind: str
    ) -> int:
        columns = {
            "scope": "next_scope_ordinal",
            "claim": "next_claim_ordinal",
            "snapshot": "next_snapshot_ordinal",
            "run": "next_run_ordinal",
            "item": "next_item_ordinal",
        }
        column = columns[kind]
        connection.execute(
            """
            INSERT OR IGNORE INTO packet_reconciliation_sequences(
                project_id, next_scope_ordinal, next_claim_ordinal,
                next_snapshot_ordinal, next_run_ordinal, next_item_ordinal
            ) VALUES (?, 1, 1, 1, 1, 1)
            """,
            (project_id,),
        )
        ordinal = int(
            connection.execute(
                f"SELECT {column} AS value FROM packet_reconciliation_sequences WHERE project_id = ?",
                (project_id,),
            ).fetchone()["value"]
        )
        connection.execute(
            f"UPDATE packet_reconciliation_sequences SET {column} = ? WHERE project_id = ?",
            (ordinal + 1, project_id),
        )
        return ordinal

    @staticmethod
    def _append_reconciliation_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        reconciliation_scope_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO packet_reconciliation_events(
                project_id, reconciliation_scope_id, event_type, actor,
                request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                reconciliation_scope_id,
                event_type,
                actor,
                request_id,
                json.dumps(dict(payload), sort_keys=True),
                occurred_at,
            ),
        )

    @staticmethod
    def _mark_scope_reconciliation_required(
        connection: sqlite3.Connection,
        project_id: str,
        reconciliation_scope_id: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE packet_reconciliation_scopes
            SET state = 'reconciliation_required', updated_at = ?
            WHERE project_id = ? AND reconciliation_scope_id = ?
            """,
            (occurred_at, project_id, reconciliation_scope_id),
        )
