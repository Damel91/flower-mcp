"""SQLite persistence for packet-provider workspace review receipts."""
from __future__ import annotations

import json
from typing import Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.packet_review import validate_workspace_review_id
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


class PacketReviewStoreMixin:
    def workspace_review_for_provider_event(
        self,
        project_id: str,
        *,
        provider_kind: str,
        provider_packet_ref: str,
        binding_epoch: int,
        event_seq: int,
    ) -> Mapping[str, object] | None:
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT workspace_review_id
                FROM packet_provider_workspace_reviews
                WHERE project_id = ? AND provider_kind = ?
                  AND provider_packet_ref = ? AND binding_epoch = ?
                  AND event_seq = ?
                """,
                (
                    project_id,
                    required_text(provider_kind, "provider_kind"),
                    required_text(provider_packet_ref, "provider_packet_ref"),
                    int(binding_epoch),
                    int(event_seq),
                ),
            ).fetchone()
            if row is None:
                return None
            return self._workspace_review_value(
                connection, project_id, str(row["workspace_review_id"])
            )

    def record_workspace_review(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        provider_kind: str,
        provider_packet_ref: str,
        provider_packet_revision: int,
        binding_epoch: int,
        event_seq: int,
        provider_job_ref: str,
        provider_revision: str,
        workspace_candidate_id: str,
        candidate_revision: str,
        provider_review_ref: str,
        completeness: str,
        disposition: str,
        reviewed_target_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        provider_findings: tuple[Mapping[str, object], ...],
        existing_finding_ids: tuple[str, ...],
        normalized_finding_ids: tuple[str, ...],
        fingerprint: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        fingerprint = required_text(fingerprint, "fingerprint")
        provider_kind = required_text(provider_kind, "provider_kind")
        provider_packet_ref = required_text(
            provider_packet_ref, "provider_packet_ref"
        )
        provider_revision = required_text(provider_revision, "provider_revision")
        for field, value in (
            ("spec_revision", spec_revision),
            ("provider_packet_revision", provider_packet_revision),
            ("binding_epoch", binding_epoch),
            ("event_seq", event_seq),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be non-negative")
        if spec_revision <= 0:
            raise ValueError("spec_revision must be positive")
        completeness = required_text(completeness, "completeness")
        if completeness not in {"complete", "partial"}:
            raise ValueError("completeness must be complete or partial")
        if disposition == "approved" and completeness != "complete":
            raise ChangeControlBlockedError("workspace_review_evidence_partial")
        if completeness == "complete":
            required_text(workspace_candidate_id, "workspace_candidate_id")
            required_text(candidate_revision, "candidate_revision")
            required_text(provider_review_ref, "provider_review_ref")
        existing_finding_ids = tuple(
            required_text(item, "existing_finding_ids")
            for item in existing_finding_ids
        )
        if len(set(existing_finding_ids)) != len(existing_finding_ids):
            raise ValueError("existing_finding_ids values must be unique")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT workspace_review_id, fingerprint
                FROM packet_provider_workspace_reviews
                WHERE project_id = ? AND provider_kind = ?
                  AND provider_packet_ref = ? AND binding_epoch = ?
                  AND event_seq = ?
                """,
                (
                    project_id,
                    provider_kind,
                    provider_packet_ref,
                    binding_epoch,
                    event_seq,
                ),
            ).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != fingerprint:
                    raise ChangeControlBlockedError(
                        "workspace_review_conflicting_replay",
                        details={
                            "provider_packet_ref": provider_packet_ref,
                            "binding_epoch": binding_epoch,
                            "event_seq": event_seq,
                        },
                    )
                return self._workspace_review_value(
                    connection, project_id, str(existing["workspace_review_id"])
                )
            for finding_id in existing_finding_ids:
                finding = connection.execute(
                    """
                    SELECT change_id, packet_id FROM review_findings
                    WHERE project_id = ? AND finding_id = ?
                    """,
                    (project_id, finding_id),
                ).fetchone()
                if finding is None:
                    raise ChangeControlBlockedError(
                        "workspace_review_existing_finding_invalid",
                        details={"finding_id": finding_id, "reason": "unknown"},
                    )
                if (
                    str(finding["change_id"]) != change_id
                    or str(finding["packet_id"]) != packet_id
                ):
                    raise ChangeControlBlockedError(
                        "workspace_review_existing_finding_invalid",
                        details={"finding_id": finding_id, "reason": "cross_scope"},
                    )
            if provider_review_ref:
                prior = connection.execute(
                    """
                    SELECT provider_packet_ref, binding_epoch, event_seq
                    FROM packet_provider_workspace_reviews
                    WHERE project_id = ? AND provider_kind = ?
                      AND provider_review_ref = ?
                    """,
                    (project_id, provider_kind, provider_review_ref),
                ).fetchone()
                if prior is not None:
                    raise ChangeControlBlockedError(
                        "workspace_review_provider_ref_conflict",
                        details={
                            "provider_review_ref": provider_review_ref,
                            "existing_provider_packet_ref": str(
                                prior["provider_packet_ref"]
                            ),
                        },
                    )
            connection.execute(
                """
                INSERT OR IGNORE INTO packet_provider_workspace_review_sequences(
                    project_id, next_review_ordinal
                ) VALUES (?, 1)
                """,
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    """
                    SELECT next_review_ordinal
                    FROM packet_provider_workspace_review_sequences
                    WHERE project_id = ?
                    """,
                    (project_id,),
                ).fetchone()["next_review_ordinal"]
            )
            review_id = f"WREV-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO packet_provider_workspace_reviews(
                    project_id, workspace_review_id, ordinal, change_id,
                    packet_id, spec_revision, provider_kind,
                    provider_packet_ref, provider_packet_revision,
                    binding_epoch, event_seq, provider_job_ref,
                    provider_revision, workspace_candidate_id,
                    candidate_revision, provider_review_ref, completeness,
                    disposition, reviewed_target_refs_json, evidence_refs_json,
                    provider_findings_json, existing_finding_ids_json,
                    normalized_finding_ids_json, fingerprint, created_at,
                    actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    review_id,
                    ordinal,
                    change_id,
                    packet_id,
                    spec_revision,
                    provider_kind,
                    provider_packet_ref,
                    provider_packet_revision,
                    binding_epoch,
                    event_seq,
                    str(provider_job_ref or ""),
                    provider_revision,
                    str(workspace_candidate_id or ""),
                    str(candidate_revision or ""),
                    str(provider_review_ref or ""),
                    completeness,
                    disposition,
                    json.dumps(list(reviewed_target_refs), separators=(",", ":")),
                    json.dumps(list(evidence_refs), separators=(",", ":")),
                    json.dumps(
                        list(provider_findings),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    json.dumps(list(existing_finding_ids), separators=(",", ":")),
                    json.dumps(list(normalized_finding_ids), separators=(",", ":")),
                    fingerprint,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE packet_provider_workspace_review_sequences
                SET next_review_ordinal = ? WHERE project_id = ?
                """,
                (ordinal + 1, project_id),
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                change_id,
                packet_id,
                actor=actor,
                occurred_at=occurred_at,
            )
            return self._workspace_review_value(connection, project_id, review_id)

    def latest_workspace_review(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        spec_revision: int,
        *,
        provider_kind: str,
        provider_packet_ref: str,
        provider_packet_revision: int,
        binding_epoch: int,
        event_seq: int,
        provider_job_ref: str,
    ) -> Mapping[str, object] | None:
        if not provider_kind or not provider_packet_ref:
            return None
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT workspace_review_id
                FROM packet_provider_workspace_reviews
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND spec_revision = ?
                  AND provider_kind = ? AND provider_packet_ref = ?
                  AND provider_packet_revision = ? AND binding_epoch = ?
                  AND event_seq = ? AND provider_job_ref = ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    int(spec_revision),
                    provider_kind,
                    provider_packet_ref,
                    int(provider_packet_revision),
                    int(binding_epoch),
                    int(event_seq),
                    str(provider_job_ref or ""),
                ),
            ).fetchone()
            if row is None:
                return None
            return self._workspace_review_value(
                connection, project_id, str(row["workspace_review_id"])
            )

    @staticmethod
    def _workspace_review_value(connection, project_id: str, review_id: str):
        row = connection.execute(
            """
            SELECT * FROM packet_provider_workspace_reviews
            WHERE project_id = ? AND workspace_review_id = ?
            """,
            (project_id, validate_workspace_review_id(review_id)),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown workspace review: {review_id}")
        value = dict(row)
        for field in (
            "reviewed_target_refs",
            "evidence_refs",
            "provider_findings",
            "existing_finding_ids",
            "normalized_finding_ids",
        ):
            value[field] = json.loads(str(value.pop(f"{field}_json")))
        return value


__all__ = ["PacketReviewStoreMixin"]
