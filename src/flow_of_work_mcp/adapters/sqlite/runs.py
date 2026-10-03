"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    PACKET_INACTIVE_STATUS_VALUES,
    PacketStatus,
    HandoverDraft,
    RunCompletionDraft,
    RunDraft,
    RunStatus,
    RunStepDraft,
    RunStepStatus,
    RunStepTransition,
)
from flow_of_work_mcp.core.domain.change_control import validate_change_id
from flow_of_work_mcp.core.domain.execution_run import (
    validate_handover_id,
    validate_run_id,
    validate_step_id,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_project_id,
)
from flow_of_work_mcp.core.errors import (
    RequirementConflictError,
    RunControlBlockedError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class RunStoreMixin:
    def create_run(
        self,
        project_id: str,
        draft: RunDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT run_id FROM implementation_runs
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._run_value(connection, project_id, str(replay["run_id"]))
            ordinal = self._next_execution_ordinal(connection, project_id, "run")
            run_id = f"RUN-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO implementation_runs(
                    project_id, change_id, packet_id, run_id, ordinal, objective,
                    status, orchestrator_ref, external_ref, source_ref, created_at,
                    updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.change_id,
                    draft.packet_id,
                    run_id,
                    ordinal,
                    draft.objective,
                    RunStatus.PLANNED.value,
                    draft.orchestrator_ref,
                    draft.external_ref,
                    draft.source_ref,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=draft.change_id,
                packet_id=draft.packet_id,
                run_id=run_id,
                event_type="run_created",
                actor=actor,
                request_id=request_id,
                payload={"objective": draft.objective},
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, run_id)

    def run_state(self, project_id: str, run_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._run_value(connection, project_id, run_id)

    def runs_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        with self._read_connection() as connection:
            self._change_row(connection, project_id, change_id)
            rows = connection.execute(
                """
                SELECT run_id FROM implementation_runs
                WHERE project_id = ? AND change_id = ?
                ORDER BY ordinal
                """,
                (project_id, change_id),
            ).fetchall()
            return [self._run_value(connection, project_id, str(row["run_id"])) for row in rows]

    def add_run_step(
        self,
        project_id: str,
        draft: RunStepDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run = self._run_row(connection, project_id, draft.run_id)
            replay = self._run_event_for_request(connection, project_id, "run_step_added", request_id)
            if replay is not None:
                return self._run_value(connection, project_id, draft.run_id)
            ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                    FROM run_steps WHERE project_id = ? AND run_id = ?
                    """,
                    (project_id, draft.run_id),
                ).fetchone()["ordinal"]
            )
            step_id = f"STEP-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO run_steps(
                    project_id, run_id, step_id, ordinal, title, action, status,
                    target_refs_json, evidence_refs_json, required, created_at,
                    updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.run_id,
                    step_id,
                    ordinal,
                    draft.title,
                    draft.action,
                    RunStepStatus.PENDING.value,
                    self._json(dict(draft.target_refs or {})),
                    self._json(list(draft.evidence_refs)),
                    1 if draft.required else 0,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=str(run["change_id"]),
                packet_id=str(run["packet_id"]),
                run_id=draft.run_id,
                step_id=step_id,
                event_type="run_step_added",
                actor=actor,
                request_id=request_id,
                payload={"title": draft.title},
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, draft.run_id)

    def link_run_step_dependency(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        depends_on_step_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        run_id = validate_run_id(run_id)
        step_id = validate_step_id(step_id)
        depends_on_step_id = validate_step_id(depends_on_step_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        if step_id == depends_on_step_id:
            raise RunControlBlockedError("run_step_dependency_self_link", details={"step_id": step_id})
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run = self._run_row(connection, project_id, run_id)
            step = self._run_step_row(connection, project_id, run_id, step_id)
            self._run_step_row(connection, project_id, run_id, depends_on_step_id)
            current = set(self._json_string_list(step["dependency_step_ids_json"]))
            current.add(depends_on_step_id)
            if self._run_step_dependency_reaches(connection, project_id, run_id, depends_on_step_id, step_id, current):
                raise RunControlBlockedError("run_step_dependency_cycle", details={"step_id": step_id})
            connection.execute(
                """
                UPDATE run_steps
                SET dependency_step_ids_json = ?, updated_at = ?
                WHERE project_id = ? AND run_id = ? AND step_id = ?
                """,
                (self._json(sorted(current)), occurred_at, project_id, run_id, step_id),
            )
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=str(run["change_id"]),
                packet_id=str(run["packet_id"]),
                run_id=run_id,
                step_id=step_id,
                event_type="run_step_dependency_linked",
                actor=actor,
                request_id=request_id,
                payload={"depends_on_step_id": depends_on_step_id},
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, run_id)

    def transition_run_step(
        self,
        project_id: str,
        run_id: str,
        step_id: str,
        transition: RunStepTransition,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        run_id = validate_run_id(run_id)
        step_id = validate_step_id(step_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run = self._run_row(connection, project_id, run_id)
            step = self._run_step_row(connection, project_id, run_id, step_id)
            if str(run["status"]) in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
                raise RunControlBlockedError(
                    "run_terminal_state",
                    details={"run_id": run_id, "status": str(run["status"])},
                )
            if transition.status == RunStepStatus.IN_PROGRESS:
                self._assert_run_step_dependencies_complete(connection, project_id, run_id, step_id)
            evidence_refs = set(self._json_string_list(step["evidence_refs_json"]))
            evidence_refs.update(transition.evidence_refs)
            retry_count = int(step["retry_count"])
            if transition.retry_rationale:
                retry_count += 1
            connection.execute(
                """
                UPDATE run_steps
                SET status = ?, evidence_refs_json = ?, retry_count = ?,
                    retry_rationale = ?, blocking_reason = ?,
                    next_expected_action = ?, updated_at = ?
                WHERE project_id = ? AND run_id = ? AND step_id = ?
                """,
                (
                    transition.status.value,
                    self._json(sorted(evidence_refs)),
                    retry_count,
                    transition.retry_rationale,
                    transition.blocking_reason,
                    transition.next_expected_action,
                    occurred_at,
                    project_id,
                    run_id,
                    step_id,
                ),
            )
            self._update_run_status_from_steps(connection, project_id, run_id, actor, occurred_at)
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=str(run["change_id"]),
                packet_id=str(run["packet_id"]),
                run_id=run_id,
                step_id=step_id,
                event_type="run_step_transitioned",
                actor=actor,
                request_id=request_id,
                payload={
                    "from_status": str(step["status"]),
                    "to_status": transition.status.value,
                    "evidence_refs": sorted(evidence_refs),
                    "blocking_reason": transition.blocking_reason,
                },
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, run_id)

    def complete_run(
        self,
        project_id: str,
        run_id: str,
        draft: RunCompletionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        run_id = validate_run_id(run_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run = self._run_row(connection, project_id, run_id)
            blockers = self._run_completion_blockers(connection, project_id, run_id)
            if blockers:
                raise RunControlBlockedError(
                    "run_completion_blocked",
                    details={"run_id": run_id, "blockers": blockers},
                )
            connection.execute(
                """
                UPDATE implementation_runs
                SET status = ?, completion_reference = ?, updated_at = ?,
                    terminal_at = ?
                WHERE project_id = ? AND run_id = ?
                """,
                (
                    RunStatus.COMPLETED.value,
                    draft.completion_reference,
                    occurred_at,
                    occurred_at,
                    project_id,
                    run_id,
                ),
            )
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=str(run["change_id"]),
                packet_id=str(run["packet_id"]),
                run_id=run_id,
                event_type="run_completed",
                actor=actor,
                request_id=request_id,
                payload={"completion_reference": draft.completion_reference},
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, run_id)

    def cancel_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        run_id = validate_run_id(run_id)
        reason = required_text(reason, "reason")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run = self._run_row(connection, project_id, run_id)
            connection.execute(
                """
                UPDATE implementation_runs
                SET status = ?, terminal_reason = ?, updated_at = ?, terminal_at = ?
                WHERE project_id = ? AND run_id = ?
                """,
                (RunStatus.CANCELLED.value, reason, occurred_at, occurred_at, project_id, run_id),
            )
            self._append_run_event(
                connection,
                project_id=project_id,
                change_id=str(run["change_id"]),
                packet_id=str(run["packet_id"]),
                run_id=run_id,
                event_type="run_cancelled",
                actor=actor,
                request_id=request_id,
                payload={"reason": reason},
                occurred_at=occurred_at,
            )
            return self._run_value(connection, project_id, run_id)

    def task_view(self, project_id: str, run_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._task_view_value(connection, project_id, run_id)

    def create_handover(
        self,
        project_id: str,
        draft: HandoverDraft,
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
            if request_id:
                replay = connection.execute(
                    """
                    SELECT handover_id FROM handover_snapshots
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._handover_value(connection, project_id, str(replay["handover_id"]))
            payload = self._resume_context_value(
                connection,
                project_id,
                change_id=draft.change_id,
                packet_id=draft.packet_id,
                run_id=draft.run_id,
            )
            ordinal = self._next_execution_ordinal(connection, project_id, "handover")
            handover_id = f"HAND-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO handover_snapshots(
                    project_id, handover_id, ordinal, change_id, packet_id, run_id,
                    profile_version, payload_json, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    handover_id,
                    ordinal,
                    draft.change_id,
                    draft.packet_id,
                    draft.run_id,
                    draft.profile_version,
                    self._json(payload),
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            return self._handover_value(connection, project_id, handover_id)

    def handover_state(self, project_id: str, handover_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._handover_value(connection, project_id, handover_id)

    def resume_context(
        self,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            return self._resume_context_value(
                connection, project_id, change_id=change_id, packet_id=packet_id, run_id=run_id
            )

    def ledger_projection(
        self,
        project_id: str,
        *,
        projection_kind: str = "lifecycle",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            matrix = self.traceability_matrix(project_id)
            changes = self.list_changes(project_id)
            runs = []
            for change in changes:
                runs.extend(self.runs_for_change(project_id, str(change["change_id"])))
            return {
                "project_id": project_id,
                "projection_kind": str(projection_kind or "lifecycle"),
                "profile_version": "ledger-projection-v1",
                "source_ledger_version": self._ledger_version(connection, project_id),
                "requirements": matrix,
                "changes": changes,
                "runs": runs,
            }

    def recover_interrupted_runs(self) -> None:
        occurred_at = _utc_now()
        with self._transaction() as connection:
            run_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'implementation_runs'"
            ).fetchone()
            if run_table is None:
                return
            rows = connection.execute(
                """
                SELECT project_id, change_id, packet_id, run_id FROM implementation_runs
                WHERE status = ?
                """,
                (RunStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE implementation_runs
                    SET status = ?, terminal_reason = ?, updated_at = ?
                    WHERE project_id = ? AND run_id = ?
                    """,
                    (
                        RunStatus.BLOCKED.value,
                        "interrupted_recovery",
                        occurred_at,
                        str(row["project_id"]),
                        str(row["run_id"]),
                    ),
                )
                self._append_run_event(
                    connection,
                    project_id=str(row["project_id"]),
                    change_id=str(row["change_id"]),
                    packet_id=str(row["packet_id"]),
                    run_id=str(row["run_id"]),
                    event_type="run_interrupted_recovered",
                    actor="system",
                    request_id="",
                    payload={"reason": "interrupted_recovery"},
                    occurred_at=occurred_at,
                )
            step_rows = connection.execute(
                """
                SELECT s.project_id, r.change_id, r.packet_id, s.run_id, s.step_id
                FROM run_steps s
                JOIN implementation_runs r
                  ON r.project_id = s.project_id AND r.run_id = s.run_id
                WHERE s.status = ?
                """,
                (RunStepStatus.IN_PROGRESS.value,),
            ).fetchall()
            for row in step_rows:
                connection.execute(
                    """
                    UPDATE run_steps
                    SET status = ?, blocking_reason = ?, next_expected_action = ?, updated_at = ?
                    WHERE project_id = ? AND run_id = ? AND step_id = ?
                    """,
                    (
                        RunStepStatus.BLOCKED.value,
                        "interrupted_recovery",
                        "review interrupted step before continuing",
                        occurred_at,
                        str(row["project_id"]),
                        str(row["run_id"]),
                        str(row["step_id"]),
                    ),
                )
                self._append_run_event(
                    connection,
                    project_id=str(row["project_id"]),
                    change_id=str(row["change_id"]),
                    packet_id=str(row["packet_id"]),
                    run_id=str(row["run_id"]),
                    step_id=str(row["step_id"]),
                    event_type="run_step_interrupted_recovered",
                    actor="system",
                    request_id="",
                    payload={"reason": "interrupted_recovery"},
                    occurred_at=occurred_at,
                )

    def _next_execution_ordinal(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        kind: str,
    ) -> int:
        connection.execute(
            """
            INSERT OR IGNORE INTO execution_run_sequences(
                project_id, next_run_ordinal, next_handover_ordinal
            ) VALUES (?, 1, 1)
            """,
            (project_id,),
        )
        column = {
            "run": "next_run_ordinal",
            "handover": "next_handover_ordinal",
        }[kind]
        ordinal = int(
            connection.execute(
                f"SELECT {column} FROM execution_run_sequences WHERE project_id = ?",
                (project_id,),
            ).fetchone()[column]
        )
        connection.execute(
            f"UPDATE execution_run_sequences SET {column} = ? WHERE project_id = ?",
            (ordinal + 1, project_id),
        )
        return ordinal

    def _run_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
    ) -> sqlite3.Row:
        project_id = validate_project_id(project_id)
        run_id = validate_run_id(run_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM implementation_runs WHERE project_id = ? AND run_id = ?",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown run in project {project_id}: {run_id}")
        return row

    def _run_step_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
        step_id: str,
    ) -> sqlite3.Row:
        validate_step_id(step_id)
        self._run_row(connection, project_id, run_id)
        row = connection.execute(
            """
            SELECT * FROM run_steps
            WHERE project_id = ? AND run_id = ? AND step_id = ?
            """,
            (project_id, run_id, step_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown run step: {step_id}")
        return row

    def _run_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        row = self._run_row(connection, project_id, run_id)
        steps = []
        for step in connection.execute(
            """
            SELECT * FROM run_steps
            WHERE project_id = ? AND run_id = ?
            ORDER BY ordinal
            """,
            (project_id, run_id),
        ).fetchall():
            steps.append(
                {
                    "step_id": str(step["step_id"]),
                    "ordinal": int(step["ordinal"]),
                    "title": str(step["title"]),
                    "action": str(step["action"]),
                    "status": str(step["status"]),
                    "dependency_step_ids": self._json_string_list(step["dependency_step_ids_json"]),
                    "target_refs": self._json_object(step["target_refs_json"]),
                    "evidence_refs": self._json_string_list(step["evidence_refs_json"]),
                    "retry_count": int(step["retry_count"]),
                    "retry_rationale": str(step["retry_rationale"]),
                    "blocking_reason": str(step["blocking_reason"]),
                    "next_expected_action": str(step["next_expected_action"]),
                    "required": bool(step["required"]),
                }
            )
        events = [
            dict(item)
            for item in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at,
                       step_id
                FROM run_events
                WHERE project_id = ? AND run_id = ?
                ORDER BY event_id
                """,
                (project_id, run_id),
            ).fetchall()
        ]
        for event in events:
            event["payload"] = json.loads(event.pop("payload_json"))
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "run_id": str(row["run_id"]),
            "ordinal": int(row["ordinal"]),
            "objective": str(row["objective"]),
            "status": str(row["status"]),
            "orchestrator_ref": str(row["orchestrator_ref"]),
            "external_ref": str(row["external_ref"]),
            "source_ref": str(row["source_ref"]),
            "completion_reference": str(row["completion_reference"]),
            "terminal_reason": str(row["terminal_reason"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "terminal_at": str(row["terminal_at"]),
            "created_by": str(row["created_by"]),
            "steps": steps,
            "events": events,
        }

    def _run_step_dependency_reaches(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
        start_step_id: str,
        target_step_id: str,
        pending_dependencies: set[str] | None = None,
    ) -> bool:
        stack = [start_step_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target_step_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            if pending_dependencies is not None and current == target_step_id:
                stack.extend(pending_dependencies)
            row = self._run_step_row(connection, project_id, run_id, current)
            stack.extend(self._json_string_list(row["dependency_step_ids_json"]))
        return False

    def _assert_run_step_dependencies_complete(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
        step_id: str,
    ) -> None:
        step = self._run_step_row(connection, project_id, run_id, step_id)
        blockers = []
        for dependency_id in self._json_string_list(step["dependency_step_ids_json"]):
            dependency = self._run_step_row(connection, project_id, run_id, dependency_id)
            if str(dependency["status"]) != RunStepStatus.COMPLETED.value:
                blockers.append({"step_id": dependency_id, "status": str(dependency["status"])})
        if blockers:
            raise RunControlBlockedError(
                "run_step_dependencies_unresolved",
                details={"step_id": step_id, "dependencies": blockers},
            )

    def _update_run_status_from_steps(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
        actor: str,
        occurred_at: str,
    ) -> None:
        run = self._run_row(connection, project_id, run_id)
        if str(run["status"]) in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
            return
        statuses = [
            str(row["status"])
            for row in connection.execute(
                "SELECT status FROM run_steps WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            ).fetchall()
        ]
        if any(status == RunStepStatus.BLOCKED.value for status in statuses):
            status = RunStatus.BLOCKED.value
        elif any(status == RunStepStatus.IN_PROGRESS.value for status in statuses):
            status = RunStatus.RUNNING.value
        elif statuses:
            status = RunStatus.PLANNED.value
        else:
            status = str(run["status"])
        if status == str(run["status"]):
            return
        connection.execute(
            """
            UPDATE implementation_runs
            SET status = ?, updated_at = ?
            WHERE project_id = ? AND run_id = ?
            """,
            (status, occurred_at, project_id, run_id),
        )
        self._append_run_event(
            connection,
            project_id=project_id,
            change_id=str(run["change_id"]),
            packet_id=str(run["packet_id"]),
            run_id=run_id,
            event_type="run_status_derived",
            actor=actor,
            request_id="",
            payload={"status": status},
            occurred_at=occurred_at,
        )

    def _run_completion_blockers(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
    ) -> list[Mapping[str, object]]:
        self._run_row(connection, project_id, run_id)
        steps = connection.execute(
            "SELECT * FROM run_steps WHERE project_id = ? AND run_id = ? ORDER BY ordinal",
            (project_id, run_id),
        ).fetchall()
        if not steps:
            return [{"kind": "run_has_no_steps", "run_id": run_id}]
        blockers: list[Mapping[str, object]] = []
        for step in steps:
            status = str(step["status"])
            if not bool(step["required"]) and status == RunStepStatus.CANCELLED.value:
                continue
            if bool(step["required"]) and status != RunStepStatus.COMPLETED.value:
                blockers.append(
                    {
                        "kind": "step_incomplete",
                        "step_id": str(step["step_id"]),
                        "status": status,
                    }
                )
            if status == RunStepStatus.BLOCKED.value:
                blockers.append(
                    {
                        "kind": "step_blocked",
                        "step_id": str(step["step_id"]),
                        "blocking_reason": str(step["blocking_reason"]),
                    }
                )
        return blockers

    def _handover_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        handover_id: str,
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        handover_id = validate_handover_id(handover_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM handover_snapshots WHERE project_id = ? AND handover_id = ?",
            (project_id, handover_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown handover in project {project_id}: {handover_id}"
            )
        return {
            "project_id": str(row["project_id"]),
            "handover_id": str(row["handover_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "run_id": str(row["run_id"]),
            "profile_version": str(row["profile_version"]),
            "created_at": str(row["created_at"]),
            "actor": str(row["actor"]),
            "payload": self._json_object(row["payload_json"]),
        }

    def _resume_context_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
    ) -> Mapping[str, Any]:
        self._ensure_project(connection, project_id)
        selected_run = self._run_value(connection, project_id, run_id) if run_id else None
        selected_change_id = change_id or (str(selected_run["change_id"]) if selected_run else "")
        selected_packet_id = packet_id or (str(selected_run["packet_id"]) if selected_run else "")
        change = self._change_value(connection, project_id, selected_change_id) if selected_change_id else None
        runs = []
        if selected_change_id:
            rows = connection.execute(
                """
                SELECT run_id FROM implementation_runs
                WHERE project_id = ? AND change_id = ?
                ORDER BY ordinal
                """,
                (project_id, selected_change_id),
            ).fetchall()
            runs = [self._run_value(connection, project_id, str(row["run_id"])) for row in rows]
        elif selected_run is not None:
            runs = [selected_run]
        task_views = [self._task_view_value(connection, project_id, str(run["run_id"])) for run in runs]
        blockers = []
        for view in task_views:
            blockers.extend(view["blocked_steps"])
        residual_risk_pressure = (
            self._latest_packet_pressure_for_resume(
                connection, project_id, selected_change_id, selected_packet_id
            )
            if selected_change_id and selected_packet_id
            else None
        )
        return {
            "project_id": project_id,
            "profile_version": "resume-context-v1",
            "source_ledger_version": self._ledger_version(connection, project_id),
            "objective": {
                "change_id": selected_change_id,
                "packet_id": selected_packet_id,
                "run_id": run_id,
                "change_title": "" if change is None else str(change["title"]),
            },
            "change": change,
            "runs": runs,
            "task_views": task_views,
            "blockers": blockers,
            "residual_risk_pressure": residual_risk_pressure,
            "next_action": self._resume_next_action(
                task_views, change, runs, residual_risk_pressure
            ),
        }

    @staticmethod
    def _resume_next_action(
        task_views: list[Mapping[str, Any]],
        change: Mapping[str, Any] | None,
        runs: list[Mapping[str, Any]],
        residual_risk_pressure: Mapping[str, Any] | None,
    ) -> Mapping[str, object]:
        inactive_packet_ids = {
            str(packet.get("packet_id") or "")
            for packet in (change or {}).get("packets", [])
            if isinstance(packet, Mapping)
            and str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES
        }
        active_run_ids = {
            str(run.get("run_id") or "")
            for run in runs
            if str(run.get("packet_id") or "") not in inactive_packet_ids
        }
        for view in task_views:
            if str(view.get("run_id") or "") not in active_run_ids:
                continue
            if view["blocked_steps"]:
                return {
                    "kind": "resolve_run_blocker",
                    "run_id": view["run_id"],
                    "step_id": view["blocked_steps"][0]["step_id"],
                }
            if view["ready_steps"]:
                return {
                    "kind": "execute_run_step",
                    "run_id": view["run_id"],
                    "step_id": view["ready_steps"][0]["step_id"],
                }
        for run in runs:
            if str(run.get("packet_id") or "") in inactive_packet_ids:
                continue
            if run["status"] == RunStatus.COMPLETED.value and change is not None:
                for packet in change.get("packets", []):
                    if packet["packet_id"] == run["packet_id"] and packet["status"] != PacketStatus.IMPLEMENTED.value:
                        return {
                            "kind": "close_packet_after_run",
                            "change_id": change["change_id"],
                            "packet_id": packet["packet_id"],
                            "run_id": run["run_id"],
                        }
        if residual_risk_pressure:
            challenge_questions = list(residual_risk_pressure.get("challenge_questions", []))
            if challenge_questions:
                return {
                    "kind": "review_residual_risk_pressure",
                    "pressure_id": residual_risk_pressure.get("pressure_id", ""),
                    "challenge_question": challenge_questions[0],
                }
        return {"kind": "inspect_what_next"}

    def _latest_packet_pressure_for_resume(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, Any] | None:
        row = connection.execute(
            """
            SELECT * FROM packet_residual_risk_pressure
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, change_id, packet_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "pressure_id": str(row["pressure_id"]),
            "semantic_confidence": str(row["semantic_confidence"]),
            "improvement_pressure": str(row["improvement_pressure"]),
            "residual_risks": self._json_string_list(row["residual_risks_json"]),
            "challenge_questions": self._json_string_list(row["challenge_questions_json"]),
            "accepted_risk_refs": self._json_string_list(row["accepted_risk_refs_json"]),
        }

    def _task_view_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        run = self._run_value(connection, project_id, run_id)
        steps = list(run["steps"])
        completed = {
            str(step["step_id"])
            for step in steps
            if step["status"] == RunStepStatus.COMPLETED.value
        }
        ready = [
            step for step in steps
            if step["status"] == RunStepStatus.PENDING.value
            and set(step["dependency_step_ids"]).issubset(completed)
        ]
        blocked = [step for step in steps if step["status"] == RunStepStatus.BLOCKED.value]
        in_progress = [step for step in steps if step["status"] == RunStepStatus.IN_PROGRESS.value]
        return {
            "project_id": run["project_id"],
            "run_id": run["run_id"],
            "change_id": run["change_id"],
            "packet_id": run["packet_id"],
            "status": run["status"],
            "ready_steps": ready,
            "in_progress_steps": in_progress,
            "blocked_steps": blocked,
        }

    @staticmethod
    def _append_run_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
        step_id: str = "",
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO run_events(
                project_id, change_id, packet_id, run_id, step_id,
                event_type, actor, request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                change_id,
                packet_id,
                run_id,
                step_id,
                event_type,
                actor,
                str(request_id or ""),
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _run_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT event_id FROM run_events
            WHERE project_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, event_type, str(request_id)),
        ).fetchone()
