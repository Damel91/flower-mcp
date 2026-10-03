"""SQLite persistence for revisioned, atomically accepted packet work plans."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.external_work import normalize_declarations
from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.packet_work_plan import (
    PacketWorkPlanDraft,
    PacketWorkPlanStatus,
    WorkPlanUnit,
    validate_packet_work_plan_id,
)
from flow_of_work_mcp.core.domain.provider_surfaces import (
    codingcastle_provider_surface,
)
from flow_of_work_mcp.core.errors import RequirementConflictError


def _draft_fingerprint(draft: PacketWorkPlanDraft) -> str:
    payload = {
        "change_id": draft.change_id,
        "packet_id": draft.packet_id,
        "units": [
            {
                "client_unit_key": unit.client_unit_key,
                "operation_kind": unit.operation_kind.value,
                "mutation_target_binding_id": unit.mutation_target_binding_id,
                "target_description": unit.target_description,
                "member_label": unit.member_label,
                "file_path": unit.file_path,
                "context_target_binding_ids": list(unit.context_target_binding_ids),
                "instructions": list(unit.instructions),
                "unit_checks": list(unit.unit_checks),
                "constraints": list(unit.constraints),
                "out_of_scope": list(unit.out_of_scope),
                "depends_on": list(unit.depends_on),
                "replaces": list(unit.replaces),
                "surface": unit.surface,
                "implements": list(unit.implements), "provides": list(unit.provides),
                "requires": list(unit.requires), "verifies": list(unit.verifies),
            }
            for unit in draft.units
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PacketWorkPlanStoreMixin:
    def save_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        intent_fingerprint: str,
        unit: Mapping[str, object],
        candidate_window: list[Mapping[str, object]],
        spec_revision: int,
        plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        client_unit_key = required_text(client_unit_key, "client_unit_key")
        intent_fingerprint = required_text(
            intent_fingerprint, "intent_fingerprint"
        )
        actor = required_text(actor, "actor")
        request_id = str(request_id or "").strip()
        if int(spec_revision) <= 0 or int(plan_revision) < 0:
            raise ValueError("packet unit authoring revisions are invalid")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT * FROM packet_unit_authoring_intents
                    WHERE project_id = ? AND prepare_request_id = ?
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    if (
                        str(replay["change_id"]) != change_id
                        or str(replay["packet_id"]) != packet_id
                        or str(replay["client_unit_key"]) != client_unit_key
                        or str(replay["intent_fingerprint"]) != intent_fingerprint
                    ):
                        raise RequirementConflictError(
                            "unit authoring request_id conflicts with durable history"
                        )
                    return self._packet_unit_authoring_intent_value(replay)
            existing = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            if existing is not None:
                if str(existing["intent_fingerprint"]) != intent_fingerprint:
                    raise RequirementConflictError(
                        "client_unit_key already belongs to another authoring intent"
                    )
                if (
                    int(existing["spec_revision"]) != int(spec_revision)
                    or int(existing["plan_revision"]) != int(plan_revision)
                ):
                    raise RequirementConflictError(
                        "unit authoring intent revisions are stale"
                    )
                if str(existing["state"]) == "pending" and candidate_window:
                    connection.execute(
                        """
                        UPDATE packet_unit_authoring_intents
                        SET candidate_window_json = ?, updated_at = ?, actor = ?
                        WHERE project_id = ? AND change_id = ? AND packet_id = ?
                          AND client_unit_key = ?
                        """,
                        (
                            self._json([dict(item) for item in candidate_window]),
                            occurred_at,
                            actor,
                            project_id,
                            change_id,
                            packet_id,
                            client_unit_key,
                        ),
                    )
                row = connection.execute(
                    """
                    SELECT * FROM packet_unit_authoring_intents
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND client_unit_key = ?
                    """,
                    (project_id, change_id, packet_id, client_unit_key),
                ).fetchone()
                return self._packet_unit_authoring_intent_value(row)
            connection.execute(
                """
                INSERT INTO packet_unit_authoring_intents(
                    project_id, change_id, packet_id, client_unit_key,
                    intent_fingerprint, unit_json, candidate_window_json, state,
                    spec_revision, plan_revision, created_at, updated_at, actor,
                    prepare_request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    client_unit_key,
                    intent_fingerprint,
                    self._json(dict(unit)),
                    self._json([dict(item) for item in candidate_window]),
                    int(spec_revision),
                    int(plan_revision),
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            return self._packet_unit_authoring_intent_value(row)

    def packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        client_unit_key = required_text(client_unit_key, "client_unit_key")
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            return (
                None
                if row is None
                else self._packet_unit_authoring_intent_value(row)
            )

    def rebase_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        intent_fingerprint: str,
        unit: Mapping[str, object],
        spec_revision: int,
        plan_revision: int,
        actor: str,
    ) -> Mapping[str, Any]:
        """Refresh unresolved authoring state without discarding unit intent."""

        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        client_unit_key = required_text(client_unit_key, "client_unit_key")
        intent_fingerprint = required_text(
            intent_fingerprint, "intent_fingerprint"
        )
        actor = required_text(actor, "actor")
        if int(spec_revision) <= 0 or int(plan_revision) < 0:
            raise ValueError("packet unit authoring revisions are invalid")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            if row is None:
                raise RequirementConflictError("unit authoring intent is missing")
            if str(row["intent_fingerprint"]) != intent_fingerprint:
                raise RequirementConflictError(
                    "client_unit_key already belongs to another authoring intent"
                )
            if str(row["state"]) == "committed":
                raise RequirementConflictError(
                    "committed unit authoring intent cannot be rebased"
                )
            connection.execute(
                """
                UPDATE packet_unit_authoring_intents
                SET unit_json = ?, candidate_window_json = '[]', state = 'pending',
                    spec_revision = ?, plan_revision = ?,
                    committed_plan_revision = 0, commit_request_id = '',
                    updated_at = ?, actor = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (
                    self._json(dict(unit)),
                    int(spec_revision),
                    int(plan_revision),
                    occurred_at,
                    actor,
                    project_id,
                    change_id,
                    packet_id,
                    client_unit_key,
                ),
            )
            updated = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            return self._packet_unit_authoring_intent_value(updated)

    def mark_packet_unit_targets_committed(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        unit: Mapping[str, object],
        candidate_window: list[Mapping[str, object]],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        client_unit_key = required_text(client_unit_key, "client_unit_key")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "").strip()
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            if row is None:
                raise RequirementConflictError("unit authoring intent is missing")
            if str(row["state"]) == "committed":
                return self._packet_unit_authoring_intent_value(row)
            connection.execute(
                """
                UPDATE packet_unit_authoring_intents
                SET unit_json = ?, candidate_window_json = ?,
                    state = 'targets_committed', updated_at = ?, actor = ?,
                    commit_request_id = CASE
                        WHEN commit_request_id = '' THEN ? ELSE commit_request_id END
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (
                    self._json(dict(unit)),
                    self._json([dict(item) for item in candidate_window]),
                    occurred_at,
                    actor,
                    request_id,
                    project_id,
                    change_id,
                    packet_id,
                    client_unit_key,
                ),
            )
            updated = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            return self._packet_unit_authoring_intent_value(updated)

    def commit_packet_unit_authoring_intent(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        client_unit_key: str,
        *,
        committed_plan_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        client_unit_key = required_text(client_unit_key, "client_unit_key")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "").strip()
        if int(committed_plan_revision) <= 0:
            raise ValueError("committed_plan_revision must be positive")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            if row is None:
                raise RequirementConflictError("unit authoring intent is missing")
            if str(row["state"]) == "committed":
                if int(row["committed_plan_revision"]) != int(
                    committed_plan_revision
                ):
                    raise RequirementConflictError(
                        "unit authoring commit conflicts with durable history"
                    )
                return self._packet_unit_authoring_intent_value(row)
            if str(row["state"]) != "targets_committed":
                raise RequirementConflictError(
                    "unit targets must be committed before plan mutation"
                )
            connection.execute(
                """
                UPDATE packet_unit_authoring_intents
                SET state = 'committed', committed_plan_revision = ?,
                    updated_at = ?, actor = ?,
                    commit_request_id = CASE
                        WHEN commit_request_id = '' THEN ? ELSE commit_request_id END
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (
                    int(committed_plan_revision),
                    occurred_at,
                    actor,
                    request_id,
                    project_id,
                    change_id,
                    packet_id,
                    client_unit_key,
                ),
            )
            updated = connection.execute(
                """
                SELECT * FROM packet_unit_authoring_intents
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND client_unit_key = ?
                """,
                (project_id, change_id, packet_id, client_unit_key),
            ).fetchone()
            return self._packet_unit_authoring_intent_value(updated)

    def create_packet_work_plan(
        self,
        project_id: str,
        draft: PacketWorkPlanDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_current_plan_revision: int | None = None,
        request_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "").strip()
        request_fingerprint = str(request_fingerprint or "").strip() or _draft_fingerprint(
            draft
        )
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT work_plan_id, plan_revision
                    FROM packet_work_plan_revisions
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    self._assert_work_plan_request_fingerprint(
                        connection,
                        project_id,
                        str(replay["work_plan_id"]),
                        int(replay["plan_revision"]),
                        request_fingerprint,
                    )
                    value = self._work_plan_revision_value(
                        connection,
                        project_id,
                        str(replay["work_plan_id"]),
                        int(replay["plan_revision"]),
                    )
                    if (
                        value["change_id"] != draft.change_id
                        or value["packet_id"] != draft.packet_id
                    ):
                        raise RequirementConflictError(
                            "request_id already belongs to another packet work plan"
                        )
                    return value

            current_packet_revision = int(packet["spec_revision"])
            compatibility_revision = int(packet["current_revision"])
            if draft.packet_revision not in {
                current_packet_revision,
                compatibility_revision,
            }:
                raise RequirementConflictError(
                    "stale packet revision for packet work plan: "
                    f"expected {current_packet_revision}, received {draft.packet_revision}"
                )
            plan_row = connection.execute(
                """
                SELECT work_plan_id FROM packet_work_plans
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (project_id, draft.change_id, draft.packet_id),
            ).fetchone()
            current_plan_revision = 0
            if plan_row is not None:
                current_plan_revision = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(plan_revision), 0) AS revision
                        FROM packet_work_plan_revisions
                        WHERE project_id = ? AND work_plan_id = ?
                        """,
                        (project_id, str(plan_row["work_plan_id"])),
                    ).fetchone()["revision"]
                )
            if (
                current_plan_revision > 0
                and expected_current_plan_revision is None
            ):
                raise RequirementConflictError(
                    "expected current work-plan revision is required when "
                    "replacing an existing plan"
                )
            if (
                expected_current_plan_revision is not None
                and int(expected_current_plan_revision) != current_plan_revision
            ):
                raise RequirementConflictError(
                    "stale current work-plan revision: "
                    f"expected {current_plan_revision}, received "
                    f"{int(expected_current_plan_revision)}"
                )

            self._validate_work_plan_bindings(connection, project_id, draft)
            authored_packet_revision = current_packet_revision + 1
            aggregate_revision = compatibility_revision + 1
            rebased_audits = connection.execute(
                """
                SELECT construction_audit_id, packet_revision, profile
                FROM packet_construction_audits
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state NOT IN ('superseded', 'closed')
                """,
                (project_id, draft.change_id, draft.packet_id),
            ).fetchall()
            connection.execute(
                """
                UPDATE implementation_packets
                SET spec_revision = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    authored_packet_revision,
                    aggregate_revision,
                    occurred_at,
                    project_id,
                    draft.change_id,
                    draft.packet_id,
                ),
            )
            self._append_packet_revision_from_current(
                connection,
                project_id,
                draft.change_id,
                draft.packet_id,
                actor,
                occurred_at,
            )
            work_plan_id = (
                str(plan_row["work_plan_id"])
                if plan_row is not None
                else self._create_work_plan_identity(
                    connection, project_id, draft, actor=actor, occurred_at=occurred_at
                )
            )
            plan_revision = current_plan_revision + 1
            proposed_rows = connection.execute(
                """
                SELECT plan_revision FROM packet_work_plan_revisions
                WHERE project_id = ? AND work_plan_id = ? AND status = 'proposed'
                ORDER BY plan_revision
                """,
                (project_id, work_plan_id),
            ).fetchall()
            for previous in proposed_rows:
                previous_revision = int(previous["plan_revision"])
                connection.execute(
                    """
                    UPDATE packet_work_plan_revisions
                    SET status = ?, transition_rationale = ?, updated_at = ?, actor = ?
                    WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                    """,
                    (
                        PacketWorkPlanStatus.SUPERSEDED.value,
                        f"superseded by proposed revision {plan_revision}",
                        occurred_at,
                        actor,
                        project_id,
                        work_plan_id,
                        previous_revision,
                    ),
                )
                self._append_work_plan_event(
                    connection,
                    project_id=project_id,
                    work_plan_id=work_plan_id,
                    plan_revision=previous_revision,
                    event_type="work_plan_superseded",
                    actor=actor,
                    request_id="",
                    payload={"superseded_by_revision": plan_revision},
                    occurred_at=occurred_at,
                )

            connection.execute(
                """
                INSERT INTO packet_work_plan_revisions(
                    project_id, work_plan_id, plan_revision, packet_revision, status,
                    transition_rationale, created_at, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    work_plan_id,
                    plan_revision,
                    authored_packet_revision,
                    PacketWorkPlanStatus.PROPOSED.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            for ordinal, unit in enumerate(draft.units, start=1):
                self._insert_work_plan_unit(
                    connection,
                    project_id=project_id,
                    work_plan_id=work_plan_id,
                    plan_revision=plan_revision,
                    ordinal=ordinal,
                    unit=unit,
                )
            # Re-evaluate question applicability after the authored units exist.
            # A work plan may preserve prior answers, but it must not make a
            # newly introduced authority question appear current by revision
            # number alone.
            authored_packet = self._packet_row(
                connection,
                project_id,
                draft.change_id,
                draft.packet_id,
            )
            for audit in rebased_audits:
                audit_id = str(audit["construction_audit_id"])
                self._refresh_construction_questions(
                    connection,
                    project_id,
                    audit_id,
                    authored_packet,
                    str(audit["profile"]),
                    actor=actor,
                    occurred_at=occurred_at,
                )
                self._append_construction_event(
                    connection,
                    project_id=project_id,
                    construction_audit_id=audit_id,
                    event_type="construction_audit_rebased_to_work_plan",
                    actor=actor,
                    request_id=request_id,
                    payload={
                        "previous_packet_revision": int(audit["packet_revision"]),
                        "packet_revision": authored_packet_revision,
                    },
                    occurred_at=occurred_at,
                )
            self._append_work_plan_event(
                connection,
                project_id=project_id,
                work_plan_id=work_plan_id,
                plan_revision=plan_revision,
                event_type="work_plan_proposed",
                actor=actor,
                request_id=request_id,
                payload={
                    "packet_revision": authored_packet_revision,
                    "previous_spec_revision": current_packet_revision,
                    "compatibility_revision": compatibility_revision,
                    "unit_count": len(draft.units),
                    "request_fingerprint": request_fingerprint,
                },
                occurred_at=occurred_at,
            )
            return self._work_plan_revision_value(
                connection, project_id, work_plan_id, plan_revision
            )

    def packet_work_plan_request_replay(
        self,
        project_id: str,
        request_id: str,
        *,
        request_fingerprint: str,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        request_id = required_text(request_id, "request_id")
        request_fingerprint = required_text(
            request_fingerprint, "request_fingerprint"
        )
        with self._read_connection() as connection:
            replay = connection.execute(
                """
                SELECT work_plan_id, plan_revision
                FROM packet_work_plan_revisions
                WHERE project_id = ? AND request_id = ?
                """,
                (project_id, request_id),
            ).fetchone()
            if replay is None:
                return None
            work_plan_id = str(replay["work_plan_id"])
            plan_revision = int(replay["plan_revision"])
            self._assert_work_plan_request_fingerprint(
                connection,
                project_id,
                work_plan_id,
                plan_revision,
                request_fingerprint,
            )
            return self._work_plan_revision_value(
                connection,
                project_id,
                work_plan_id,
                plan_revision,
            )

    def packet_work_plan_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        plan_revision: int | None = None,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            plan = connection.execute(
                """
                SELECT work_plan_id FROM packet_work_plans
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if plan is None:
                return self._legacy_work_plan_projection(
                    connection, project_id, change_id, packet_id, int(packet["spec_revision"])
                )
            work_plan_id = str(plan["work_plan_id"])
            revision = plan_revision
            if revision is None:
                row = connection.execute(
                    """
                    SELECT MAX(plan_revision) AS revision
                    FROM packet_work_plan_revisions
                    WHERE project_id = ? AND work_plan_id = ?
                    """,
                    (project_id, work_plan_id),
                ).fetchone()
                revision = int(row["revision"])
            return self._work_plan_revision_value(
                connection, project_id, work_plan_id, int(revision)
            )

    def accepted_packet_work_plan(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            row = connection.execute(
                """
                SELECT revisions.work_plan_id, revisions.plan_revision
                FROM packet_work_plan_revisions AS revisions
                JOIN packet_work_plans AS plans
                  ON plans.project_id = revisions.project_id
                 AND plans.work_plan_id = revisions.work_plan_id
                JOIN implementation_packets AS packets
                  ON packets.project_id = plans.project_id
                 AND packets.change_id = plans.change_id
                 AND packets.packet_id = plans.packet_id
                WHERE plans.project_id = ? AND plans.change_id = ? AND plans.packet_id = ?
                  AND revisions.status = 'accepted'
                  AND revisions.packet_revision = packets.spec_revision
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if row is None:
                return None
            return self._work_plan_revision_value(
                connection,
                project_id,
                str(row["work_plan_id"]),
                int(row["plan_revision"]),
            )

    def packet_work_plan_history(
        self, project_id: str, change_id: str, packet_id: str
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            plan = connection.execute(
                """
                SELECT work_plan_id FROM packet_work_plans
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if plan is None:
                legacy = self._legacy_work_plan_projection(
                    connection, project_id, change_id, packet_id, int(packet["spec_revision"])
                )
                return [legacy] if legacy is not None else []
            work_plan_id = str(plan["work_plan_id"])
            revisions = connection.execute(
                """
                SELECT plan_revision FROM packet_work_plan_revisions
                WHERE project_id = ? AND work_plan_id = ? ORDER BY plan_revision
                """,
                (project_id, work_plan_id),
            ).fetchall()
            return [
                self._work_plan_revision_value(
                    connection, project_id, work_plan_id, int(row["plan_revision"])
                )
                for row in revisions
            ]

    def finalize_packet_authoring_revision(
        self,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        *,
        construction_audit_id: str = "",
    ) -> Mapping[str, Any]:
        """Bind artifacts created in one atomic author call to its final spec revision."""
        project_id = validate_project_id(project_id)
        work_plan_id = validate_packet_work_plan_id(work_plan_id)
        with self._transaction() as connection:
            plan = connection.execute(
                """
                SELECT change_id, packet_id FROM packet_work_plans
                WHERE project_id = ? AND work_plan_id = ?
                """,
                (project_id, work_plan_id),
            ).fetchone()
            if plan is None:
                raise RequirementConflictError(f"unknown packet work plan: {work_plan_id}")
            packet = self._packet_row(
                connection, project_id, str(plan["change_id"]), str(plan["packet_id"])
            )
            spec_revision = int(packet["spec_revision"])
            connection.execute(
                """
                UPDATE packet_work_plan_revisions
                SET packet_revision = ?
                WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                """,
                (spec_revision, project_id, work_plan_id, int(plan_revision)),
            )
            if construction_audit_id:
                connection.execute(
                    """
                    UPDATE packet_construction_audits
                    SET packet_revision = ?
                    WHERE project_id = ? AND construction_audit_id = ?
                      AND change_id = ? AND packet_id = ?
                    """,
                    (
                        spec_revision,
                        project_id,
                        construction_audit_id,
                        str(plan["change_id"]),
                        str(plan["packet_id"]),
                    ),
                )
            return self._work_plan_revision_value(
                connection, project_id, work_plan_id, int(plan_revision)
            )

    def transition_packet_work_plan(
        self,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        *,
        status: str,
        expected_packet_revision: int,
        expected_current_plan_revision: int,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        work_plan_id = validate_packet_work_plan_id(work_plan_id)
        plan_revision = int(plan_revision)
        if plan_revision <= 0:
            raise ValueError("plan_revision must be positive")
        next_status = PacketWorkPlanStatus(status)
        if next_status not in {
            PacketWorkPlanStatus.ACCEPTED,
            PacketWorkPlanStatus.REJECTED,
        }:
            raise ValueError("work-plan transition supports accepted or rejected")
        rationale = required_text(rationale, "rationale")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "").strip()
        occurred_at = _utc_now()
        with self._transaction() as connection:
            if request_id:
                replay = connection.execute(
                    """
                    SELECT work_plan_id, plan_revision, event_type
                    FROM packet_work_plan_events
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY event_id LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    if (
                        str(replay["work_plan_id"]) != work_plan_id
                        or int(replay["plan_revision"]) != plan_revision
                    ):
                        raise RequirementConflictError(
                            "request_id already belongs to another work-plan transition"
                        )
                    expected_event_type = f"work_plan_{next_status.value}"
                    if str(replay["event_type"]) != expected_event_type:
                        raise RequirementConflictError(
                            "request_id already belongs to another work-plan operation"
                        )
                    return self._work_plan_revision_value(
                        connection, project_id, work_plan_id, plan_revision
                    )
            plan = connection.execute(
                """
                SELECT change_id, packet_id FROM packet_work_plans
                WHERE project_id = ? AND work_plan_id = ?
                """,
                (project_id, work_plan_id),
            ).fetchone()
            if plan is None:
                raise RequirementConflictError(f"unknown packet work plan: {work_plan_id}")
            packet = self._packet_row(
                connection,
                project_id,
                str(plan["change_id"]),
                str(plan["packet_id"]),
            )
            current_packet_revision = int(packet["spec_revision"])
            if int(expected_packet_revision) not in {
                current_packet_revision,
                int(packet["current_revision"]),
            }:
                raise RequirementConflictError(
                    "stale packet revision during work-plan transition"
                )
            latest_revision = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(plan_revision), 0) AS revision
                    FROM packet_work_plan_revisions
                    WHERE project_id = ? AND work_plan_id = ?
                    """,
                    (project_id, work_plan_id),
                ).fetchone()["revision"]
            )
            if latest_revision != int(expected_current_plan_revision):
                raise RequirementConflictError(
                    "stale current work-plan revision during transition"
                )
            revision = connection.execute(
                """
                SELECT status, packet_revision FROM packet_work_plan_revisions
                WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                """,
                (project_id, work_plan_id, plan_revision),
            ).fetchone()
            if revision is None:
                raise RequirementConflictError(
                    f"unknown work-plan revision: {work_plan_id}@{plan_revision}"
                )
            if str(revision["status"]) != PacketWorkPlanStatus.PROPOSED.value:
                raise RequirementConflictError("only proposed work-plan revisions may transition")
            if int(revision["packet_revision"]) != current_packet_revision:
                raise RequirementConflictError("work-plan revision targets a stale packet revision")

            if next_status == PacketWorkPlanStatus.ACCEPTED:
                self._revalidate_persisted_bindings(
                    connection, project_id, work_plan_id, plan_revision
                )
                previous = connection.execute(
                    """
                    SELECT plan_revision FROM packet_work_plan_revisions
                    WHERE project_id = ? AND work_plan_id = ? AND status = 'accepted'
                    """,
                    (project_id, work_plan_id),
                ).fetchone()
                if previous is not None:
                    previous_revision = int(previous["plan_revision"])
                    connection.execute(
                        """
                        UPDATE packet_work_plan_revisions
                        SET status = ?, transition_rationale = ?, updated_at = ?, actor = ?
                        WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                        """,
                        (
                            PacketWorkPlanStatus.SUPERSEDED.value,
                            f"superseded by accepted revision {plan_revision}",
                            occurred_at,
                            actor,
                            project_id,
                            work_plan_id,
                            previous_revision,
                        ),
                    )
                    self._append_work_plan_event(
                        connection,
                        project_id=project_id,
                        work_plan_id=work_plan_id,
                        plan_revision=previous_revision,
                        event_type="work_plan_superseded",
                        actor=actor,
                        request_id="",
                        payload={"superseded_by_revision": plan_revision},
                        occurred_at=occurred_at,
                    )
            connection.execute(
                """
                UPDATE packet_work_plan_revisions
                SET status = ?, transition_rationale = ?, updated_at = ?, actor = ?
                WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                """,
                (
                    next_status.value,
                    rationale,
                    occurred_at,
                    actor,
                    project_id,
                    work_plan_id,
                    plan_revision,
                ),
            )
            active_audits = connection.execute(
                """
                SELECT construction_audit_id, question_plan_revision, profile
                FROM packet_construction_audits
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state NOT IN ('superseded', 'closed')
                """,
                (
                    project_id,
                    str(plan["change_id"]),
                    str(plan["packet_id"]),
                ),
            ).fetchall()
            for audit in active_audits:
                audit_id = str(audit["construction_audit_id"])
                previous_question_revision = int(audit["question_plan_revision"])
                self._refresh_construction_questions(
                    connection,
                    project_id,
                    audit_id,
                    packet,
                    str(audit["profile"]),
                    actor=actor,
                    occurred_at=occurred_at,
                )
                refreshed_audit = self._construction_audit_row(
                    connection, project_id, audit_id
                )
                if (
                    int(refreshed_audit["question_plan_revision"])
                    == previous_question_revision
                ):
                    continue
                self._append_construction_event(
                    connection,
                    project_id=project_id,
                    construction_audit_id=audit_id,
                    event_type="construction_audit_refreshed_after_plan_transition",
                    actor=actor,
                    request_id=request_id,
                    payload={
                        "work_plan_id": work_plan_id,
                        "plan_revision": plan_revision,
                        "status": next_status.value,
                        "previous_question_plan_revision": previous_question_revision,
                        "question_plan_revision": int(
                            refreshed_audit["question_plan_revision"]
                        ),
                    },
                    occurred_at=occurred_at,
                )
            aggregate_revision = int(packet["current_revision"]) + 1
            state_revision = int(packet["state_revision"]) + 1
            connection.execute(
                """
                UPDATE implementation_packets
                SET state_revision = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    state_revision,
                    aggregate_revision,
                    occurred_at,
                    project_id,
                    str(plan["change_id"]),
                    str(plan["packet_id"]),
                ),
            )
            self._append_packet_revision_from_current(
                connection,
                project_id,
                str(plan["change_id"]),
                str(plan["packet_id"]),
                actor,
                occurred_at,
            )
            self._append_work_plan_event(
                connection,
                project_id=project_id,
                work_plan_id=work_plan_id,
                plan_revision=plan_revision,
                event_type=f"work_plan_{next_status.value}",
                actor=actor,
                request_id=request_id,
                payload={"rationale": rationale},
                occurred_at=occurred_at,
            )
            return self._work_plan_revision_value(
                connection, project_id, work_plan_id, plan_revision
            )

    def _create_work_plan_identity(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        draft: PacketWorkPlanDraft,
        *,
        actor: str,
        occurred_at: str,
    ) -> str:
        connection.execute(
            """
            INSERT OR IGNORE INTO packet_work_plan_sequences(
                project_id, next_work_plan_ordinal
            ) VALUES (?, 1)
            """,
            (project_id,),
        )
        ordinal = int(
            connection.execute(
                """
                SELECT next_work_plan_ordinal FROM packet_work_plan_sequences
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()["next_work_plan_ordinal"]
        )
        work_plan_id = f"WPLAN-{ordinal:06d}"
        connection.execute(
            """
            INSERT INTO packet_work_plans(
                project_id, work_plan_id, ordinal, change_id, packet_id,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                work_plan_id,
                ordinal,
                draft.change_id,
                draft.packet_id,
                occurred_at,
                actor,
            ),
        )
        connection.execute(
            """
            UPDATE packet_work_plan_sequences SET next_work_plan_ordinal = ?
            WHERE project_id = ?
            """,
            (ordinal + 1, project_id),
        )
        return work_plan_id

    @staticmethod
    def _packet_unit_authoring_intent_value(
        row: sqlite3.Row,
    ) -> Mapping[str, Any]:
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "client_unit_key": str(row["client_unit_key"]),
            "intent_fingerprint": str(row["intent_fingerprint"]),
            "unit": json.loads(str(row["unit_json"] or "{}")),
            "candidate_window": json.loads(
                str(row["candidate_window_json"] or "[]")
            ),
            "state": str(row["state"]),
            "spec_revision": int(row["spec_revision"]),
            "plan_revision": int(row["plan_revision"]),
            "committed_plan_revision": int(row["committed_plan_revision"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _validate_work_plan_bindings(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        draft: PacketWorkPlanDraft,
    ) -> None:
        for unit in draft.units:
            if unit.mutation_target_binding_id:
                binding = self._work_plan_binding_row(
                    connection,
                    project_id,
                    draft.change_id,
                    draft.packet_id,
                    unit.mutation_target_binding_id,
                )
                if _normalize_surface(str(binding["surface_id"])) != unit.surface:
                    raise RequirementConflictError(
                        "mutation target binding surface does not match work-plan unit"
                    )
            for binding_id in unit.context_target_binding_ids:
                self._work_plan_binding_row(
                    connection,
                    project_id,
                    draft.change_id,
                    draft.packet_id,
                    binding_id,
                )

    def _revalidate_persisted_bindings(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
    ) -> None:
        value = self._work_plan_revision_value(
            connection, project_id, work_plan_id, plan_revision
        )
        draft = PacketWorkPlanDraft(
            change_id=str(value["change_id"]),
            packet_id=str(value["packet_id"]),
            packet_revision=int(value["packet_revision"]),
            units=tuple(_unit_from_value(unit) for unit in value["units"]),
        )
        self._validate_work_plan_bindings(connection, project_id, draft)

    def _work_plan_binding_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        binding_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT bindings.binding_id, blocks.change_id, blocks.packet_id, blocks.state,
                   targets.surface_id
            FROM navigation_target_bindings AS bindings
            JOIN navigation_audit_blocks AS blocks
              ON blocks.project_id = bindings.project_id
             AND blocks.navigation_audit_id = bindings.navigation_audit_id
            JOIN navigation_candidate_targets AS targets
              ON targets.project_id = bindings.project_id
             AND targets.candidate_set_id = bindings.candidate_set_id
             AND targets.candidate_id = bindings.candidate_id
            WHERE bindings.project_id = ? AND bindings.binding_id = ?
            """,
            (project_id, required_text(binding_id, "binding_id")),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown navigation binding: {binding_id}")
        if str(row["change_id"]) != change_id or str(row["packet_id"]) != packet_id:
            raise RequirementConflictError("navigation binding belongs to another packet")
        if str(row["state"]) != "accepted_for_packet":
            raise RequirementConflictError("navigation binding is not accepted for packet")
        return row

    def _insert_work_plan_unit(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        ordinal: int,
        unit: WorkPlanUnit,
    ) -> None:
        connection.execute(
            """
            INSERT INTO packet_work_plan_units(
                project_id, work_plan_id, plan_revision, unit_ordinal,
                client_unit_key, operation_kind, mutation_target_binding_id, file_path,
                target_description, member_label,
                context_target_binding_ids_json, instructions_json, unit_checks_json,
                constraints_json, out_of_scope_json, depends_on_json, replaces_json,
                surface, unit_number, implements_json, provides_json, requires_json, verifies_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                work_plan_id,
                plan_revision,
                ordinal,
                unit.client_unit_key,
                unit.operation_kind.value,
                unit.mutation_target_binding_id,
                unit.file_path,
                unit.target_description,
                unit.member_label,
                json.dumps(list(unit.context_target_binding_ids), sort_keys=True),
                json.dumps(list(unit.instructions), sort_keys=True),
                json.dumps(list(unit.unit_checks), sort_keys=True),
                json.dumps(list(unit.constraints), sort_keys=True),
                json.dumps(list(unit.out_of_scope), sort_keys=True),
                json.dumps(list(unit.depends_on), sort_keys=True),
                json.dumps(list(unit.replaces), sort_keys=True),
                unit.surface,
                self._external_unit_number(connection, project_id, work_plan_id, unit.client_unit_key),
                json.dumps(list(unit.implements)), json.dumps(list(unit.provides)),
                json.dumps(list(unit.requires)), json.dumps(list(unit.verifies)),
            ),
        )

    def _work_plan_revision_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
    ) -> Mapping[str, Any]:
        row = connection.execute(
            """
            SELECT plans.change_id, plans.packet_id, revisions.*
            FROM packet_work_plan_revisions AS revisions
            JOIN packet_work_plans AS plans
              ON plans.project_id = revisions.project_id
             AND plans.work_plan_id = revisions.work_plan_id
            WHERE revisions.project_id = ? AND revisions.work_plan_id = ?
              AND revisions.plan_revision = ?
            """,
            (project_id, work_plan_id, plan_revision),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown work-plan revision: {work_plan_id}@{plan_revision}"
            )
        units = []
        for unit in connection.execute(
            """
            SELECT * FROM packet_work_plan_units
            WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
            ORDER BY unit_ordinal
            """,
            (project_id, work_plan_id, plan_revision),
        ).fetchall():
            units.append(
                {
                    "unit_ordinal": int(unit["unit_ordinal"]),
                    "unit_number": int(unit["unit_number"]),
                    **_stored_validation_declarations(unit),
                    "client_unit_key": str(unit["client_unit_key"]),
                    "operation_kind": str(unit["operation_kind"]),
                    "mutation_target_binding_id": str(unit["mutation_target_binding_id"]),
                    "target_description": str(unit["target_description"]),
                    "member_label": str(unit["member_label"]),
                    "file_path": str(unit["file_path"]),
                    "context_target_binding_ids": _json_list(
                        unit["context_target_binding_ids_json"]
                    ),
                    "instructions": _json_list(unit["instructions_json"]),
                    "unit_checks": _json_list(unit["unit_checks_json"]),
                    "constraints": _json_list(unit["constraints_json"]),
                    "out_of_scope": _json_list(unit["out_of_scope_json"]),
                    "depends_on": _json_list(unit["depends_on_json"]),
                    "replaces": _json_list(unit["replaces_json"]),
                    "surface": str(unit["surface"]),
                }
            )
        events = [
            {
                **dict(event),
                "payload": json.loads(str(event["payload_json"] or "{}")),
            }
            for event in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at
                FROM packet_work_plan_events
                WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
                ORDER BY event_id
                """,
                (project_id, work_plan_id, plan_revision),
            ).fetchall()
        ]
        for event in events:
            event.pop("payload_json", None)
        return {
            "project_id": project_id,
            "work_plan_id": work_plan_id,
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "packet_revision": int(row["packet_revision"]),
            "plan_revision": int(row["plan_revision"]),
            "status": str(row["status"]),
            "transition_rationale": str(row["transition_rationale"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "actor": str(row["actor"]),
            "request_id": str(row["request_id"]),
            "units": units,
            "events": events,
        }

    @staticmethod
    def _append_work_plan_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO packet_work_plan_events(
                project_id, work_plan_id, plan_revision, event_type, actor,
                request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                work_plan_id,
                plan_revision,
                event_type,
                actor,
                request_id,
                json.dumps(dict(payload), sort_keys=True),
                occurred_at,
            ),
        )

    @staticmethod
    def _assert_work_plan_request_fingerprint(
        connection: sqlite3.Connection,
        project_id: str,
        work_plan_id: str,
        plan_revision: int,
        request_fingerprint: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT payload_json
            FROM packet_work_plan_events
            WHERE project_id = ? AND work_plan_id = ? AND plan_revision = ?
              AND event_type = 'work_plan_proposed'
            ORDER BY event_id
            LIMIT 1
            """,
            (project_id, work_plan_id, int(plan_revision)),
        ).fetchone()
        if row is None:
            return
        payload = json.loads(str(row["payload_json"]) or "{}")
        stored = str(payload.get("request_fingerprint") or "")
        if stored and stored != request_fingerprint:
            raise RequirementConflictError(
                "request_id replay payload does not match the original work-plan request"
            )

    @staticmethod
    def _legacy_work_plan_projection(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        packet_revision: int,
    ) -> Mapping[str, Any] | None:
        rows = connection.execute(
            """
            SELECT proposal_id, status, operation_kind, goal, created_at
            FROM packet_unit_proposals
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
            ORDER BY ordinal
            """,
            (project_id, change_id, packet_id),
        ).fetchall()
        if not rows:
            return None
        return {
            "project_id": project_id,
            "work_plan_id": "",
            "change_id": change_id,
            "packet_id": packet_id,
            "packet_revision": packet_revision,
            "plan_revision": 0,
            "status": PacketWorkPlanStatus.LEGACY_NON_EXECUTABLE.value,
            "transition_rationale": "legacy proposals do not contain executable instructions",
            "units": [],
            "legacy_proposals": [dict(row) for row in rows],
            "events": [],
        }


def _unit_from_value(value: Mapping[str, object]) -> WorkPlanUnit:
    return WorkPlanUnit(
        client_unit_key=str(value["client_unit_key"]),
        operation_kind=str(value["operation_kind"]),
        mutation_target_binding_id=str(value.get("mutation_target_binding_id") or ""),
        target_description=str(value.get("target_description") or ""),
        member_label=str(value.get("member_label") or ""),
        file_path=str(value.get("file_path") or ""),
        context_target_binding_ids=tuple(
            str(item) for item in value.get("context_target_binding_ids", [])
        ),
        instructions=tuple(str(item) for item in value.get("instructions", [])),
        unit_checks=tuple(str(item) for item in value.get("unit_checks", [])),
        constraints=tuple(str(item) for item in value.get("constraints", [])),
        out_of_scope=tuple(str(item) for item in value.get("out_of_scope", [])),
        depends_on=tuple(str(item) for item in value.get("depends_on", [])),
        replaces=tuple(str(item) for item in value.get("replaces", [])),
        surface=str(value.get("surface") or "repo"),
        implements=tuple(value.get("implements", [])), provides=tuple(value.get("provides", [])),
        requires=tuple(value.get("requires", [])), verifies=tuple(value.get("verifies", [])),
    )


def _json_list(raw: object) -> list[str]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, ValueError) as exc:
        raise RequirementConflictError("stored work-plan list is invalid") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RequirementConflictError("stored work-plan list is invalid")
    return [str(item) for item in value]


def _normalize_surface(value: str) -> str:
    return codingcastle_provider_surface(value)


def _stored_validation_declarations(unit) -> dict[str, object]:
    try:
        return normalize_declarations({field: json.loads(unit[field + "_json"]) for field in ("implements", "provides", "requires", "verifies")})
    except (ValueError, TypeError) as exc:
        raise RequirementConflictError("stored validation declaration is invalid") from exc
