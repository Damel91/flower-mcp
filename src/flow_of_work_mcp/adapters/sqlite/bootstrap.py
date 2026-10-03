"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_project_id,
)
from flow_of_work_mcp.core.domain.bootstrap import BootstrapPath
from flow_of_work_mcp.core.errors import (
    BootstrapBlockedError,
    BootstrapStartConflictError,
    InputValidationError,
    RequirementConflictError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class BootstrapStoreMixin:
    def start_bootstrap(
        self,
        project_id: str,
        *,
        project_name: str,
        path: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        project_name = required_text(project_name, "project_name")
        path = self._bootstrap_path(path)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            if request_id:
                replay = connection.execute(
                    """
                    SELECT bootstrap_id, path, created_by FROM bootstraps
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal DESC LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    if path == 'guided_engineering' or replay['path'] == 'guided_engineering':
                        event = connection.execute("SELECT payload_json FROM bootstrap_events WHERE project_id = ? AND bootstrap_id = ? AND event_type = 'bootstrap_started' ORDER BY event_id LIMIT 1", (project_id, replay['bootstrap_id'])).fetchone()
                        if (str(replay['created_by']) != actor or not event or
                            self._json_object(event['payload_json']) != {'path':path, 'project_name':project_name}):
                            raise BootstrapStartConflictError(
                                'guided_bootstrap_start_request_conflict',
                                'The start request already belongs to a different bootstrap payload or actor.',
                                context={'project_id': project_id, 'bootstrap_id': str(replay['bootstrap_id']), 'actor': actor},
                            )
                    return self._bootstrap_value(connection, project_id, str(replay["bootstrap_id"]))
            project = connection.execute(
                "SELECT project_id, name FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project is None:
                connection.execute(
                    "INSERT INTO projects(project_id, name, created_at, created_by) VALUES (?, ?, ?, ?)",
                    (project_id, project_name, occurred_at, actor),
                )
                connection.execute(
                    "INSERT INTO project_sequences(project_id, next_requirement_ordinal) VALUES (?, 1)",
                    (project_id,),
                )
                connection.execute(
                    """
                    INSERT INTO goal_sequences(project_id, next_goal_ordinal, next_candidate_ordinal)
                    VALUES (?, 1, 1)
                    """,
                    (project_id,),
                )
                self._append_event(
                    connection,
                    project_id=project_id,
                    requirement_id=None,
                    event_type="project_created",
                    actor=actor,
                    request_id=request_id,
                    payload={"name": project_name, "origin": "bootstrap"},
                    occurred_at=occurred_at,
                )
            elif str(project["name"]) != project_name:
                existing = connection.execute(
                    "SELECT bootstrap_id FROM bootstraps WHERE project_id = ? AND status IN ('in_progress', 'blocked') ORDER BY ordinal DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
                raise BootstrapStartConflictError(
                    "bootstrap_project_name_conflict", "bootstrap project name conflicts with existing project",
                    context={"project_id": project_id, "registered_project_name": str(project["name"]),
                             "path": path, "actor": actor, "request_id": request_id,
                             **({"bootstrap_id": str(existing["bootstrap_id"])} if existing else {})},
                )
            active = connection.execute(
                """
                SELECT bootstrap_id FROM bootstraps
                WHERE project_id = ? AND status IN ('in_progress', 'blocked')
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if active is not None:
                raise BootstrapStartConflictError(
                    "bootstrap_already_active", "project already has a non-terminal bootstrap",
                    context={"project_id": project_id, "bootstrap_id": str(active["bootstrap_id"]), "actor": actor},
                )
            populated = connection.execute(
                """
                SELECT EXISTS(SELECT 1 FROM requirements WHERE project_id = ?) AS requirements,
                       EXISTS(SELECT 1 FROM goal_nodes WHERE project_id = ?) AS goals,
                       EXISTS(SELECT 1 FROM baseline_imports WHERE project_id = ?) AS baseline
                """,
                (project_id, project_id, project_id),
            ).fetchone()
            if path != BootstrapPath.GUIDED_ENGINEERING.value and (populated["requirements"] or populated["goals"] or populated["baseline"]):
                raise RequirementConflictError("bootstrap adoption requires an otherwise empty canonical project")
            connection.execute(
                "INSERT OR IGNORE INTO bootstrap_sequences(project_id, next_bootstrap_ordinal) VALUES (?, 1)",
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    "SELECT next_bootstrap_ordinal FROM bootstrap_sequences WHERE project_id = ?",
                    (project_id,),
                ).fetchone()["next_bootstrap_ordinal"]
            )
            bootstrap_id = f"BOOT-{ordinal:06d}"
            connection.execute(
                "UPDATE bootstrap_sequences SET next_bootstrap_ordinal = ? WHERE project_id = ?",
                (ordinal + 1, project_id),
            )
            connection.execute(
                """
                INSERT INTO bootstraps(
                    project_id, bootstrap_id, ordinal, path, status, stage, created_at,
                    updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, 'in_progress', 'intake', ?, ?, ?, ?)
                """,
                (project_id, bootstrap_id, ordinal, path, occurred_at, occurred_at, actor, request_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_started",
                actor=actor,
                request_id=request_id,
                payload={"path": path, "project_name": project_name},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def bootstrap_state(self, project_id: str, bootstrap_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def resume_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["status"]) in {"completed", "cancelled"}:
                raise RequirementConflictError("terminal bootstrap cannot resume")
            if self._has_open_bootstrap_contradictions(row):
                raise BootstrapBlockedError("bootstrap_contradiction_unresolved")
            if str(row["status"]) == "blocked":
                connection.execute(
                    """
                    UPDATE bootstraps SET status = 'in_progress', blocking_reason = '', updated_at = ?
                    WHERE project_id = ? AND bootstrap_id = ?
                    """,
                    (occurred_at, project_id, bootstrap_id),
                )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_resumed",
                actor=actor,
                request_id=request_id,
                payload={"stage": row["stage"]},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def latest_guided_bootstrap(self, project_id: str) -> Mapping[str, Any] | None:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                "SELECT bootstrap_id FROM bootstraps WHERE project_id = ? "
                "AND path = 'guided_engineering' ORDER BY ordinal DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            return self._bootstrap_value(connection, project_id, row["bootstrap_id"]) if row else None

    def guided_bootstrap_replay(self, project_id: str, bootstrap_id: str, *,
                                operation: str, mutation: Mapping[str, object],
                                actor: str, request_id: str) -> Mapping[str, Any] | None:
        if not request_id:
            return None
        with self._read_connection() as connection:
            self._bootstrap_row(connection, project_id, bootstrap_id)
            row = connection.execute(
                "SELECT event_type, payload_json FROM bootstrap_events WHERE project_id = ? "
                "AND bootstrap_id = ? AND request_id = ? ORDER BY event_id LIMIT 1",
                (project_id, bootstrap_id, request_id),
            ).fetchone()
            if row is None:
                return None
            expected = {"operation": operation, "mutation": dict(mutation), "actor": actor}
            recorded = self._json_object(row["payload_json"])
            if recorded.get("input") != expected:
                raise RequirementConflictError("guided_bootstrap_request_conflict")
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def record_guided_bootstrap(self, project_id: str, bootstrap_id: str, *,
                                operation: str, mutation: Mapping[str, object],
                                guided: Mapping[str, object], actor: str, request_id: str,
                                stage: str = "intake", handoff: Mapping[str, object] | None = None,
                                completion_reference: str = "") -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        with self._transaction() as connection:
            replay = self.guided_bootstrap_replay(project_id, bootstrap_id,
                operation=operation, mutation=mutation, actor=actor, request_id=request_id)
            if replay is not None:
                return replay
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["path"]) != "guided_engineering":
                raise BootstrapBlockedError("guided_bootstrap_route_required")
            if row["status"] == "cancelled" or (row["status"] == "completed" and operation != "record_continuation"):
                raise RequirementConflictError("terminal bootstrap cannot mutate")
            intake = dict(self._json_object(row["intake_json"]))
            intake["_guided"] = dict(guided)
            status = "completed" if operation == "complete" else str(row["status"])
            effective_stage = "completed" if status == "completed" else stage
            connection.execute(
                "UPDATE bootstraps SET intake_json = ?, stage = ?, status = ?, updated_at = ?, "
                "completion_reference = ?, completion_handoff_json = ? "
                "WHERE project_id = ? AND bootstrap_id = ?",
                (self._json(intake), effective_stage, status, _utc_now(),
                 completion_reference or row["completion_reference"],
                 self._json(dict(handoff)) if handoff is not None else row["completion_handoff_json"],
                 project_id, bootstrap_id),
            )
            self._append_bootstrap_event(connection, project_id=project_id, bootstrap_id=bootstrap_id,
                event_type="guided_" + operation, actor=actor, request_id=request_id,
                payload={"input": {"operation": operation, "mutation": dict(mutation), "actor": actor},
                         "guided_state": dict(guided), "handoff": dict(handoff or {})}, occurred_at=_utc_now())
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def record_bootstrap_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        intake: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["path"]) == "guided_engineering":
                raise BootstrapBlockedError("guided_bootstrap_requires_guided_operations")
            self._assert_bootstrap_mutable(row)
            replay = self._bootstrap_event_for_request(
                connection, project_id, bootstrap_id, "bootstrap_intake_recorded", request_id
            )
            if replay is not None:
                return self._bootstrap_value(connection, project_id, bootstrap_id)
            merged = dict(self._json_object(row["intake_json"]))
            merged.update(dict(intake))
            connection.execute(
                """
                UPDATE bootstraps
                SET status = 'in_progress', stage = 'intake', intake_json = ?, blocking_reason = '', updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (self._json(merged), occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_intake_recorded",
                actor=actor,
                request_id=request_id,
                payload={"fields": sorted(str(key) for key in intake)},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def record_bootstrap_contradiction(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        contradiction: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            self._assert_bootstrap_mutable(row)
            replay = self._bootstrap_event_for_request(
                connection, project_id, bootstrap_id, "bootstrap_contradiction_recorded", request_id
            )
            if replay is not None:
                return self._bootstrap_value(connection, project_id, bootstrap_id)
            values = list(self._json_list(row["contradictions_json"]))
            item = dict(contradiction)
            status = str(item.get("status") or "open").strip()
            if status not in {"open", "resolved"}:
                raise ValueError("bootstrap contradiction status is invalid")
            contradiction_id = str(item.get("contradiction_id") or "").strip()
            if status == "resolved":
                if not contradiction_id:
                    raise ValueError("resolved contradiction requires contradiction_id")
                found = False
                for value in values:
                    if str(value.get("contradiction_id") or "") == contradiction_id:
                        value["status"] = "resolved"
                        value["resolution"] = required_text(
                            str(item.get("resolution") or ""), "contradiction resolution"
                        )
                        found = True
                        break
                if not found:
                    raise RequirementConflictError("bootstrap contradiction not found")
            else:
                if not isinstance(item.get("source_classes"), list) or not item["source_classes"]:
                    raise ValueError("open contradiction requires source_classes")
                item["contradiction_id"] = contradiction_id or f"CTR-{len(values) + 1:03d}"
                item["decision_required"] = required_text(
                    str(item.get("decision_required") or ""), "contradiction decision_required"
                )
                item["status"] = "open"
                values.append(item)
            open_items = any(str(value.get("status") or "") == "open" for value in values)
            stage = "awaiting_contradiction_resolution" if open_items else self._stage_after_resolution(row)
            connection.execute(
                """
                UPDATE bootstraps
                SET status = ?, stage = ?, contradictions_json = ?, blocking_reason = ?, updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (
                    "blocked" if open_items else "in_progress",
                    stage,
                    self._json(values),
                    "bootstrap_contradiction_unresolved" if open_items else "",
                    occurred_at,
                    project_id,
                    bootstrap_id,
                ),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_contradiction_recorded",
                actor=actor,
                request_id=request_id,
                payload={"status": status, "contradiction_id": contradiction_id or item.get("contradiction_id", "")},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def confirm_bootstrap_intake(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        confirmation_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        confirmation_reference = required_text(confirmation_reference, "confirmation_reference")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["path"]) == "guided_engineering":
                raise BootstrapBlockedError("guided_bootstrap_requires_guided_operations")
            self._assert_bootstrap_mutable(row)
            if self._has_open_bootstrap_contradictions(row):
                raise BootstrapBlockedError("bootstrap_contradiction_unresolved")
            replay = self._bootstrap_event_for_request(
                connection, project_id, bootstrap_id, "bootstrap_intake_confirmed", request_id
            )
            if replay is not None:
                return self._bootstrap_value(connection, project_id, bootstrap_id)
            stage = self._stage_after_confirmation(str(row["path"]))
            connection.execute(
                """
                UPDATE bootstraps
                SET status = 'in_progress', stage = ?, confirmation_reference = ?, blocking_reason = '', updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (stage, confirmation_reference, occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_intake_confirmed",
                actor=actor,
                request_id=request_id,
                payload={"confirmation_reference": confirmation_reference, "next_stage": stage},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def record_bootstrap_behavior_draft(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        draft: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            self._assert_bootstrap_mutable(row)
            if str(row["path"]) != "code_import" or str(row["stage"]) != "ready_for_derivation":
                raise BootstrapBlockedError("bootstrap_behavior_derivation_not_ready")
            replay = self._bootstrap_event_for_request(
                connection, project_id, bootstrap_id, "bootstrap_behavior_derived", request_id
            )
            if replay is not None:
                return self._bootstrap_value(connection, project_id, bootstrap_id)
            connection.execute(
                """
                UPDATE bootstraps
                SET status = 'in_progress', stage = 'awaiting_authority_acceptance',
                    behavior_draft_json = ?, blocking_reason = '', updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (self._json(dict(draft)), occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_behavior_derived",
                actor=actor,
                request_id=request_id,
                payload={
                    "provider_id": draft.get("provider_id", ""),
                    "source_revision": draft.get("source_revision", ""),
                    "use_case_count": len(draft.get("use_cases", [])),
                    "sequence_count": len(draft.get("sequences", [])),
                    "requirement_count": len(draft.get("requirements", [])),
                },
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def complete_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        completion_reference: str,
        handoff: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        completion_reference = required_text(completion_reference, "completion_reference")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["status"]) == "completed":
                return self._bootstrap_value(connection, project_id, bootstrap_id)
            self._assert_bootstrap_mutable(row)
            if self._has_open_bootstrap_contradictions(row):
                raise BootstrapBlockedError("bootstrap_contradiction_unresolved")
            path = str(row["path"])
            stage = str(row["stage"])
            if path == "requirements_import" and stage != "ready_for_import":
                raise BootstrapBlockedError("bootstrap_requirements_import_not_ready")
            if path == "code_import" and stage != "awaiting_authority_acceptance":
                raise BootstrapBlockedError("bootstrap_behavior_acceptance_not_ready")
            if path == "guided_engineering" and (stage != "ready_for_completion" or not handoff.get("roadmap_fingerprint")):
                raise BootstrapBlockedError("guided_bootstrap_plan_handoff_not_ready")
            if path == "requirements_creation" and stage != "ready_for_completion":
                raise BootstrapBlockedError("bootstrap_requirements_creation_not_ready")
            if path in {"requirements_import", "code_import"}:
                baseline = connection.execute(
                    "SELECT baseline_id FROM baseline_imports WHERE project_id = ? LIMIT 1",
                    (project_id,),
                ).fetchone()
                if baseline is None:
                    raise BootstrapBlockedError("bootstrap_canonical_baseline_missing")
            connection.execute(
                """
                UPDATE bootstraps
                SET status = 'completed', stage = 'completed', completion_reference = ?,
                    completion_handoff_json = ?, blocking_reason = '', updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (completion_reference, self._json(dict(handoff)), occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_completed",
                actor=actor,
                request_id=request_id,
                payload={
                    "completion_reference": completion_reference,
                    "path": path,
                    "handoff_action_count": len(handoff.get("actions", [])),
                },
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def cancel_bootstrap(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        reason = required_text(reason, "reason")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            if str(row["status"]) in {"completed", "cancelled"}:
                raise RequirementConflictError("terminal bootstrap cannot cancel")
            connection.execute(
                """
                UPDATE bootstraps
                SET status = 'cancelled', stage = 'cancelled', blocking_reason = ?, updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (reason, occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_cancelled",
                actor=actor,
                request_id=request_id,
                payload={"reason": reason},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    def mark_bootstrap_blocked(
        self,
        project_id: str,
        bootstrap_id: str,
        *,
        reason: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        reason = required_text(reason, "reason")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._bootstrap_row(connection, project_id, bootstrap_id)
            self._assert_bootstrap_mutable(row)
            connection.execute(
                """
                UPDATE bootstraps SET status = 'blocked', blocking_reason = ?, updated_at = ?
                WHERE project_id = ? AND bootstrap_id = ?
                """,
                (reason, occurred_at, project_id, bootstrap_id),
            )
            self._append_bootstrap_event(
                connection,
                project_id=project_id,
                bootstrap_id=bootstrap_id,
                event_type="bootstrap_blocked",
                actor=actor,
                request_id=request_id,
                payload={"reason": reason},
                occurred_at=occurred_at,
            )
            return self._bootstrap_value(connection, project_id, bootstrap_id)

    @staticmethod
    def _bootstrap_path(value: str) -> str:
        path = required_text(value, "bootstrap path")
        try:
            return BootstrapPath(path).value
        except ValueError as exc:
            accepted = tuple(item.value for item in BootstrapPath)
            raise InputValidationError(
                "bootstrap path is a workflow mode, not a filesystem path",
                field="path",
                received_value=path,
                accepted_values=accepted,
            ) from exc

    def _bootstrap_row(
        self, connection: sqlite3.Connection, project_id: str, bootstrap_id: str
    ) -> sqlite3.Row:
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM bootstraps WHERE project_id = ? AND bootstrap_id = ?",
            (project_id, required_text(bootstrap_id, "bootstrap_id")),
        ).fetchone()
        if row is None:
            raise RequirementConflictError("bootstrap not found")
        return row

    def _bootstrap_value(
        self, connection: sqlite3.Connection, project_id: str, bootstrap_id: str
    ) -> Mapping[str, Any]:
        row = self._bootstrap_row(connection, project_id, bootstrap_id)
        value = dict(row)
        intake = self._json_object(value.pop("intake_json"))
        contradictions = self._json_list(value.pop("contradictions_json"))
        draft = self._json_object(value.pop("behavior_draft_json"))
        handoff = self._json_object(value.pop("completion_handoff_json"))
        events = connection.execute(
            """
            SELECT event_id, event_type, occurred_at, payload_json FROM bootstrap_events
            WHERE project_id = ? AND bootstrap_id = ?
            ORDER BY event_id DESC LIMIT 10
            """,
            (project_id, bootstrap_id),
        ).fetchall()
        value.update(
            {
                "intake": intake,
                "contradictions": contradictions,
                "behavior_draft": draft,
                "completion_handoff": handoff,
                "open_contradiction_count": sum(
                    1 for item in contradictions if str(item.get("status") or "") == "open"
                ),
                "audit_events": [{"event_id": item["event_id"], "event_type": item["event_type"],
                                  "occurred_at": item["occurred_at"],
                                  "payload": self._json_object(item["payload_json"])}
                                 for item in reversed(events)],
            }
        )
        return value

    @staticmethod
    def _assert_bootstrap_mutable(row: sqlite3.Row) -> None:
        if str(row["status"]) in {"completed", "cancelled"}:
            raise RequirementConflictError("terminal bootstrap cannot mutate")

    def _has_open_bootstrap_contradictions(self, row: sqlite3.Row) -> bool:
        return any(
            str(item.get("status") or "") == "open"
            for item in self._json_list(row["contradictions_json"])
        )

    @staticmethod
    def _stage_after_confirmation(path: str) -> str:
        return {
            "requirements_import": "ready_for_import",
            "code_import": "ready_for_derivation",
            "requirements_creation": "ready_for_completion",
            "guided_engineering": "ready_for_completion",
        }[path]

    def _stage_after_resolution(self, row: sqlite3.Row) -> str:
        if str(row["confirmation_reference"] or ""):
            return self._stage_after_confirmation(str(row["path"]))
        return "intake"

    @staticmethod
    def _append_bootstrap_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        bootstrap_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO bootstrap_events(
                project_id, bootstrap_id, event_type, actor, request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                bootstrap_id,
                event_type,
                actor,
                str(request_id or ""),
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _bootstrap_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        bootstrap_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT event_id FROM bootstrap_events
            WHERE project_id = ? AND bootstrap_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, bootstrap_id, event_type, str(request_id)),
        ).fetchone()
