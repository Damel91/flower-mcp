"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    ChangeStatus,
    GovernedChangeDraft,
    ImplementationPacketDraft,
    PACKET_TERMINAL_STATUS_VALUES,
    PacketReadinessState,
    PacketStatus,
    PacketTargetPolicy,
    PacketTransition,
)
from flow_of_work_mcp.core.domain.change_control import (
    validate_change_id,
    validate_milestone_id,
    validate_packet_id,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_project_id,
)
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    RequirementConflictError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class ChangeStoreMixin:
    def create_change(
        self,
        project_id: str,
        draft: GovernedChangeDraft,
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
            milestone_id = str(draft.milestone_id or "")
            if milestone_id:
                validate_milestone_id(milestone_id)
                self._milestone_row(connection, project_id, milestone_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT change_id FROM change_units
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._change_value(connection, project_id, str(replay["change_id"]))
            for requirement_id in draft.requirement_ids:
                self._requirement_row(connection, project_id, requirement_id)
            connection.execute(
                """
                INSERT OR IGNORE INTO change_sequences(
                    project_id, next_change_ordinal, next_packet_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    "SELECT next_change_ordinal FROM change_sequences WHERE project_id = ?",
                    (project_id,),
                ).fetchone()["next_change_ordinal"]
            )
            change_id = f"CHANGE-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO change_units(
                    project_id, change_id, ordinal, title, rationale, status, milestone_id,
                    requirement_ids_json, source_refs_json, baseline_refs_json,
                    current_revision, created_at, updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    change_id,
                    ordinal,
                    draft.title,
                    draft.rationale,
                    ChangeStatus.PLANNED.value,
                    milestone_id,
                    self._json(list(draft.requirement_ids)),
                    self._json(list(draft.source_refs)),
                    self._json(list(draft.baseline_refs)),
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            connection.execute(
                "UPDATE change_sequences SET next_change_ordinal = ? WHERE project_id = ?",
                (ordinal + 1, project_id),
            )
            for requirement_id in draft.requirement_ids:
                connection.execute(
                    """
                    INSERT INTO change_requirement_scope(project_id, change_id, requirement_id)
                    VALUES (?, ?, ?)
                    """,
                    (project_id, change_id, requirement_id),
                )
            self._append_change_revision(
                connection,
                project_id=project_id,
                change_id=change_id,
                revision=1,
                title=draft.title,
                rationale=draft.rationale,
                status=ChangeStatus.PLANNED.value,
                milestone_id=milestone_id,
                requirement_ids=draft.requirement_ids,
                source_refs=draft.source_refs,
                baseline_refs=draft.baseline_refs,
                actor=actor,
                occurred_at=occurred_at,
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                event_type="change_created",
                actor=actor,
                request_id=request_id,
                payload={
                    "requirement_ids": list(draft.requirement_ids),
                    "source_refs": list(draft.source_refs),
                    "baseline_refs": list(draft.baseline_refs),
                    "milestone_id": milestone_id,
                },
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    def change_state(self, project_id: str, change_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._change_value(connection, project_id, change_id)

    def list_changes(self, project_id: str) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            rows = connection.execute(
                "SELECT change_id FROM change_units WHERE project_id = ? ORDER BY ordinal",
                (project_id,),
            ).fetchall()
            return [self._change_value(connection, project_id, str(row["change_id"])) for row in rows]

    def packet_change_id(self, project_id: str, packet_id: str) -> str:
        project_id = validate_project_id(project_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                """
                SELECT change_id
                FROM implementation_packets
                WHERE project_id = ? AND packet_id = ?
                """,
                (project_id, packet_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown packet in project: {packet_id}")
            return str(row["change_id"])

    def link_change_milestone(
        self,
        project_id: str,
        change_id: str,
        milestone_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        milestone_id = validate_milestone_id(milestone_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            change = self._change_row(connection, project_id, change_id)
            self._milestone_row(connection, project_id, milestone_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "change_milestone_linked", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            if str(change["milestone_id"]) == milestone_id:
                return self._change_value(connection, project_id, change_id)
            revision = int(change["current_revision"]) + 1
            connection.execute(
                """
                UPDATE change_units
                SET milestone_id = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ?
                """,
                (milestone_id, revision, occurred_at, project_id, change_id),
            )
            self._append_change_revision(
                connection,
                project_id=project_id,
                change_id=change_id,
                revision=revision,
                title=str(change["title"]),
                rationale=str(change["rationale"]),
                status=str(change["status"]),
                milestone_id=milestone_id,
                requirement_ids=tuple(self._json_string_list(change["requirement_ids_json"])),
                source_refs=tuple(self._json_string_list(change["source_refs_json"])),
                baseline_refs=tuple(self._json_string_list(change["baseline_refs_json"])),
                actor=actor,
                occurred_at=occurred_at,
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                event_type="change_milestone_linked",
                actor=actor,
                request_id=request_id,
                payload={"milestone_id": milestone_id},
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    def add_packet(
        self,
        project_id: str,
        change_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        with self._transaction() as connection:
            self._add_packet_in_transaction(
                connection,
                project_id=project_id,
                change_id=change_id,
                draft=draft,
                actor=actor,
                request_id=request_id,
            )
            return self._change_value(connection, project_id, change_id)

    def _add_packet_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        draft: ImplementationPacketDraft,
        actor: str,
        request_id: str = "",
        occurred_at: str = "",
    ) -> str:
        """Insert one ordinary packet inside an existing ledger transaction."""

        self._change_row(connection, project_id, change_id)
        if request_id:
            replay = connection.execute(
                """
                SELECT change_id, packet_id FROM implementation_packets
                WHERE project_id = ? AND request_id = ?
                ORDER BY ordinal LIMIT 1
                """,
                (project_id, request_id),
            ).fetchone()
            if replay is not None:
                replay_change_id = str(replay["change_id"])
                replay_packet_id = str(replay["packet_id"])
                if replay_change_id != change_id:
                    raise RequirementConflictError(
                        "packet creation request_id conflicts with durable history"
                    )
                original = connection.execute(
                    """
                    SELECT * FROM implementation_packet_revisions
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND revision = 1
                    """,
                    (project_id, replay_change_id, replay_packet_id),
                ).fetchone()
                if original is None or self._packet_semantic_projection(
                    original
                ) != self._packet_draft_semantic_projection(draft):
                    raise RequirementConflictError(
                        "packet creation request_id conflicts with durable history"
                    )
                return replay_packet_id
        timestamp = occurred_at or _utc_now()
        sequence = connection.execute(
            "SELECT next_packet_ordinal FROM change_sequences WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if sequence is None:
            connection.execute(
                """
                INSERT INTO change_sequences(
                    project_id, next_change_ordinal, next_packet_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            packet_global_ordinal = 1
        else:
            packet_global_ordinal = int(sequence["next_packet_ordinal"])
        packet_id = f"PACKET-{packet_global_ordinal:06d}"
        packet_ordinal = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                FROM implementation_packets
                WHERE project_id = ? AND change_id = ?
                """,
                (project_id, change_id),
            ).fetchone()["ordinal"]
        )
        connection.execute(
            """
            INSERT INTO implementation_packets(
                project_id, change_id, packet_id, ordinal, title, status,
                readiness_state, target_policy, objective, rationale,
                requirement_ids_json, goal_ids_json, in_scope_json, out_of_scope_json,
                invariants_json, unresolved_questions_json, navigation_audit_ids_json,
                target_binding_ids_json, candidate_set_ids_json, context_snapshot_ids_json,
                readiness_blockers_json,
                completion_criteria_json, criterion_results_json,
                blocking_reasons_json, disposition, successor_packet_id,
                spec_revision, state_revision, current_revision,
                created_at, updated_at, created_by, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '[]', '', '', 1, 1, 1, ?, ?, ?, ?)
            """,
            (
                project_id, change_id, packet_id, packet_ordinal, draft.title,
                PacketStatus.PLANNED.value, draft.readiness_state.value,
                draft.target_policy.value, draft.objective, draft.rationale,
                self._json(list(draft.requirement_ids)), self._json(list(draft.goal_ids)),
                self._json(list(draft.in_scope)), self._json(list(draft.out_of_scope)),
                self._json(list(draft.invariants)),
                self._json(list(draft.unresolved_questions)),
                self._json(list(draft.navigation_audit_ids)),
                self._json(list(draft.target_binding_ids)),
                self._json(list(draft.candidate_set_ids)),
                self._json(list(draft.context_snapshot_ids)),
                self._json(list(draft.readiness_blockers)),
                self._json(list(draft.completion_criteria)),
                timestamp, timestamp, actor, request_id,
            ),
        )
        connection.execute(
            "UPDATE change_sequences SET next_packet_ordinal = ? WHERE project_id = ?",
            (packet_global_ordinal + 1, project_id),
        )
        self._append_packet_revision(
            connection,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            revision=1,
            title=draft.title,
            status=PacketStatus.PLANNED.value,
            readiness_state=draft.readiness_state.value,
            target_policy=draft.target_policy.value,
            objective=draft.objective,
            rationale=draft.rationale,
            requirement_ids=draft.requirement_ids,
            goal_ids=draft.goal_ids,
            in_scope=draft.in_scope,
            out_of_scope=draft.out_of_scope,
            invariants=draft.invariants,
            unresolved_questions=draft.unresolved_questions,
            navigation_audit_ids=draft.navigation_audit_ids,
            target_binding_ids=draft.target_binding_ids,
            candidate_set_ids=draft.candidate_set_ids,
            context_snapshot_ids=draft.context_snapshot_ids,
            readiness_blockers=draft.readiness_blockers,
            completion_criteria=draft.completion_criteria,
            criterion_results={},
            blocking_reasons=(),
            disposition="",
            successor_packet_id="",
            actor=actor,
            occurred_at=timestamp,
        )
        self._append_change_event(
            connection,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            event_type="packet_added",
            actor=actor,
            request_id=request_id,
            payload={
                "completion_criteria": list(draft.completion_criteria),
                "target_policy": draft.target_policy.value,
                "readiness_state": draft.readiness_state.value,
                "navigation_audit_ids": list(draft.navigation_audit_ids),
            },
            occurred_at=timestamp,
        )
        self._update_change_status(connection, project_id, change_id, actor, timestamp)
        return packet_id

    def revise_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "packet_revised", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            current_semantic = self._packet_semantic_projection(packet)
            requested_semantic = {
                "title": draft.title,
                "objective": draft.objective,
                "rationale": draft.rationale,
                "requirement_ids": list(draft.requirement_ids),
                "goal_ids": list(draft.goal_ids),
                "in_scope": list(draft.in_scope),
                "out_of_scope": list(draft.out_of_scope),
                "invariants": list(draft.invariants),
                "unresolved_questions": list(draft.unresolved_questions),
                "navigation_audit_ids": list(draft.navigation_audit_ids),
                "target_binding_ids": list(draft.target_binding_ids),
                "candidate_set_ids": list(draft.candidate_set_ids),
                "context_snapshot_ids": list(draft.context_snapshot_ids),
                "target_policy": draft.target_policy.value,
                "completion_criteria": list(draft.completion_criteria),
            }
            if requested_semantic == current_semantic:
                return self._change_value(connection, project_id, change_id)
            revision = int(packet["current_revision"]) + 1
            spec_revision = int(packet["spec_revision"]) + 1
            retained_results = {
                key: value
                for key, value in self._json_dict(packet["criterion_results_json"]).items()
                if key in set(draft.completion_criteria)
            }
            connection.execute(
                """
                UPDATE implementation_packets
                SET title = ?, objective = ?, rationale = ?, requirement_ids_json = ?,
                    goal_ids_json = ?, in_scope_json = ?, out_of_scope_json = ?,
                    invariants_json = ?, unresolved_questions_json = ?,
                    navigation_audit_ids_json = ?, target_binding_ids_json = ?,
                    candidate_set_ids_json = ?, context_snapshot_ids_json = ?,
                    target_policy = ?, readiness_state = ?, readiness_blockers_json = ?,
                    completion_criteria_json = ?, criterion_results_json = ?,
                    spec_revision = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    draft.title,
                    draft.objective,
                    draft.rationale,
                    self._json(list(draft.requirement_ids)),
                    self._json(list(draft.goal_ids)),
                    self._json(list(draft.in_scope)),
                    self._json(list(draft.out_of_scope)),
                    self._json(list(draft.invariants)),
                    self._json(list(draft.unresolved_questions)),
                    self._json(list(draft.navigation_audit_ids)),
                    self._json(list(draft.target_binding_ids)),
                    self._json(list(draft.candidate_set_ids)),
                    self._json(list(draft.context_snapshot_ids)),
                    draft.target_policy.value,
                    draft.readiness_state.value,
                    self._json(list(draft.readiness_blockers)),
                    self._json(list(draft.completion_criteria)),
                    self._json(retained_results),
                    spec_revision,
                    revision,
                    occurred_at,
                    project_id,
                    change_id,
                    packet_id,
                ),
            )
            self._append_packet_revision_from_current(
                connection, project_id, change_id, packet_id, actor, occurred_at
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                event_type="packet_revised",
                actor=actor,
                request_id=request_id,
                payload={
                    "completion_criteria": list(draft.completion_criteria),
                    "target_policy": draft.target_policy.value,
                    "readiness_state": draft.readiness_state.value,
                    "navigation_audit_ids": list(draft.navigation_audit_ids),
                },
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    def link_packet_dependency(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        depends_on_packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        depends_on_packet_id = validate_packet_id(depends_on_packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        if packet_id == depends_on_packet_id:
            raise ChangeControlBlockedError(
                "packet_dependency_self_link",
                details={"packet_id": packet_id},
            )
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            self._packet_row(connection, project_id, change_id, depends_on_packet_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "packet_dependency_linked", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            if self._packet_depends_on(
                connection,
                project_id,
                change_id,
                start_packet_id=depends_on_packet_id,
                target_packet_id=packet_id,
            ):
                raise ChangeControlBlockedError(
                    "packet_dependency_cycle",
                    details={
                        "packet_id": packet_id,
                        "depends_on_packet_id": depends_on_packet_id,
                    },
                )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO packet_dependencies(
                    project_id, change_id, packet_id, depends_on_packet_id,
                    created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    depends_on_packet_id,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            if cursor.rowcount:
                revision = int(packet["current_revision"]) + 1
                spec_revision = int(packet["spec_revision"]) + 1
                connection.execute(
                    """
                    UPDATE implementation_packets
                    SET spec_revision = ?, current_revision = ?, updated_at = ?
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                    """,
                    (
                        spec_revision,
                        revision,
                        occurred_at,
                        project_id,
                        change_id,
                        packet_id,
                    ),
                )
                self._append_packet_revision_from_current(
                    connection, project_id, change_id, packet_id, actor, occurred_at
                )
                self._append_change_event(
                    connection,
                    project_id=project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    event_type="packet_dependency_linked",
                    actor=actor,
                    request_id=request_id,
                    payload={"depends_on_packet_id": depends_on_packet_id},
                    occurred_at=occurred_at,
                )
            return self._change_value(connection, project_id, change_id)

    def set_packet_target_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        target_policy: str = "",
        readiness_state: str = "",
        navigation_audit_ids: tuple[str, ...] = (),
        target_binding_ids: tuple[str, ...] = (),
        candidate_set_ids: tuple[str, ...] = (),
        context_snapshot_ids: tuple[str, ...] = (),
        readiness_blockers: tuple[str, ...] = (),
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "packet_target_state_updated", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            resolved_target_policy = (
                PacketTargetPolicy(target_policy).value
                if target_policy
                else str(packet["target_policy"])
            )
            resolved_readiness = (
                PacketReadinessState(readiness_state).value
                if readiness_state
                else str(packet["readiness_state"])
            )
            semantic_changed = any(
                (
                    resolved_target_policy != str(packet["target_policy"]),
                    list(navigation_audit_ids)
                    != ChangeStoreMixin._json_list(packet["navigation_audit_ids_json"]),
                    list(target_binding_ids)
                    != ChangeStoreMixin._json_list(packet["target_binding_ids_json"]),
                    list(candidate_set_ids)
                    != ChangeStoreMixin._json_list(packet["candidate_set_ids_json"]),
                    list(context_snapshot_ids)
                    != ChangeStoreMixin._json_list(packet["context_snapshot_ids_json"]),
                )
            )
            lifecycle_changed = any(
                (
                    resolved_readiness != str(packet["readiness_state"]),
                    list(readiness_blockers)
                    != ChangeStoreMixin._json_list(packet["readiness_blockers_json"]),
                )
            )
            if not semantic_changed and not lifecycle_changed:
                return self._change_value(connection, project_id, change_id)
            revision = int(packet["current_revision"]) + 1
            spec_revision = int(packet["spec_revision"]) + int(semantic_changed)
            state_revision = int(packet["state_revision"]) + int(lifecycle_changed)
            connection.execute(
                """
                UPDATE implementation_packets
                SET target_policy = ?, readiness_state = ?, navigation_audit_ids_json = ?,
                    target_binding_ids_json = ?, candidate_set_ids_json = ?,
                    context_snapshot_ids_json = ?, readiness_blockers_json = ?,
                    spec_revision = ?, state_revision = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    resolved_target_policy,
                    resolved_readiness,
                    self._json(list(navigation_audit_ids)),
                    self._json(list(target_binding_ids)),
                    self._json(list(candidate_set_ids)),
                    self._json(list(context_snapshot_ids)),
                    self._json(list(readiness_blockers)),
                    spec_revision,
                    state_revision,
                    revision,
                    occurred_at,
                    project_id,
                    change_id,
                    packet_id,
                ),
            )
            self._append_packet_revision_from_current(
                connection, project_id, change_id, packet_id, actor, occurred_at
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                event_type="packet_target_state_updated",
                actor=actor,
                request_id=request_id,
                payload={
                    "target_policy": resolved_target_policy,
                    "readiness_state": resolved_readiness,
                    "navigation_audit_ids": list(navigation_audit_ids),
                    "target_binding_ids": list(target_binding_ids),
                    "candidate_set_ids": list(candidate_set_ids),
                    "context_snapshot_ids": list(context_snapshot_ids),
                    "readiness_blockers": list(readiness_blockers),
                },
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    @staticmethod
    def _packet_semantic_projection(packet: Mapping[str, object]) -> dict[str, object]:
        return {
            "title": str(packet["title"]),
            "objective": str(packet["objective"]),
            "rationale": str(packet["rationale"]),
            "requirement_ids": ChangeStoreMixin._json_list(packet["requirement_ids_json"]),
            "goal_ids": ChangeStoreMixin._json_list(packet["goal_ids_json"]),
            "in_scope": ChangeStoreMixin._json_list(packet["in_scope_json"]),
            "out_of_scope": ChangeStoreMixin._json_list(packet["out_of_scope_json"]),
            "invariants": ChangeStoreMixin._json_list(packet["invariants_json"]),
            "unresolved_questions": ChangeStoreMixin._json_list(
                packet["unresolved_questions_json"]
            ),
            "navigation_audit_ids": ChangeStoreMixin._json_list(
                packet["navigation_audit_ids_json"]
            ),
            "target_binding_ids": ChangeStoreMixin._json_list(
                packet["target_binding_ids_json"]
            ),
            "candidate_set_ids": ChangeStoreMixin._json_list(packet["candidate_set_ids_json"]),
            "context_snapshot_ids": ChangeStoreMixin._json_list(
                packet["context_snapshot_ids_json"]
            ),
            "target_policy": str(packet["target_policy"]),
            "completion_criteria": ChangeStoreMixin._json_list(
                packet["completion_criteria_json"]
            ),
        }

    @staticmethod
    def _packet_draft_semantic_projection(
        draft: ImplementationPacketDraft,
    ) -> dict[str, object]:
        return {
            "title": draft.title,
            "objective": draft.objective,
            "rationale": draft.rationale,
            "requirement_ids": list(draft.requirement_ids),
            "goal_ids": list(draft.goal_ids),
            "in_scope": list(draft.in_scope),
            "out_of_scope": list(draft.out_of_scope),
            "invariants": list(draft.invariants),
            "unresolved_questions": list(draft.unresolved_questions),
            "navigation_audit_ids": list(draft.navigation_audit_ids),
            "target_binding_ids": list(draft.target_binding_ids),
            "candidate_set_ids": list(draft.candidate_set_ids),
            "context_snapshot_ids": list(draft.context_snapshot_ids),
            "target_policy": draft.target_policy.value,
            "completion_criteria": list(draft.completion_criteria),
        }

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []

    def _bump_packet_state_revision(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        occurred_at: str,
    ) -> tuple[int, int]:
        packet = self._packet_row(connection, project_id, change_id, packet_id)
        state_revision = int(packet["state_revision"]) + 1
        current_revision = int(packet["current_revision"]) + 1
        connection.execute(
            """
            UPDATE implementation_packets
            SET state_revision = ?, current_revision = ?, updated_at = ?
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
            """,
            (
                state_revision,
                current_revision,
                occurred_at,
                project_id,
                change_id,
                packet_id,
            ),
        )
        self._append_packet_revision_from_current(
            connection, project_id, change_id, packet_id, actor, occurred_at
        )
        return state_revision, current_revision

    def evaluate_packet_readiness(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "packet_readiness_evaluated", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            target_policy = PacketTargetPolicy(str(packet["target_policy"]))
            blockers: list[str] = []
            navigation_audit_ids: list[str] = []
            target_binding_ids: list[str] = []
            candidate_set_ids: list[str] = []
            context_snapshot_ids: list[str] = []
            if not str(packet["objective"]).strip():
                blockers.append("packet_objective_missing")
            if not str(packet["rationale"]).strip():
                blockers.append("packet_rationale_missing")
            if not (
                self._json_string_list(packet["requirement_ids_json"])
                or self._json_string_list(packet["goal_ids_json"])
                or self._json_string_list(packet["in_scope_json"])
            ):
                blockers.append("packet_scope_missing")
            if not self._json_string_list(packet["invariants_json"]):
                blockers.append("packet_invariants_missing")
            if not self._json_string_list(packet["completion_criteria_json"]):
                blockers.append("packet_completion_criteria_missing")
            if self._json_string_list(packet["unresolved_questions_json"]):
                blockers.append("packet_unresolved_authority_questions")
            baseline_only_new_file_plan = (
                target_policy != PacketTargetPolicy.DOCUMENTAL_ONLY
                and self._current_plan_is_baseline_only_new_files(
                    connection,
                    project_id,
                    change_id,
                    packet_id,
                    packet_revision=int(packet["spec_revision"]),
                )
            )
            if target_policy != PacketTargetPolicy.DOCUMENTAL_ONLY:
                selected_navigation_ids = self._json_string_list(
                    packet["navigation_audit_ids_json"]
                )
                pending_provider_windows = connection.execute(
                    """
                    SELECT navigation_audit_id FROM navigation_audit_blocks
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND provider_window_state IN ('recording', 'snapshot_ready', 'imported_by_flow')
                    ORDER BY ordinal
                    """,
                    (project_id, change_id, packet_id),
                ).fetchall()
                if selected_navigation_ids:
                    selected_set = set(selected_navigation_ids)
                    pending_provider_windows = [
                        item
                        for item in pending_provider_windows
                        if str(item["navigation_audit_id"]) in selected_set
                    ]
                if pending_provider_windows and not baseline_only_new_file_plan:
                    blockers.append("provider_navigation_audit_snapshot_pending")
                accepted_rows = connection.execute(
                    """
                    SELECT navigation_audit_id FROM navigation_audit_blocks
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND state = 'accepted_for_packet'
                    ORDER BY ordinal
                    """,
                    (project_id, change_id, packet_id),
                ).fetchall()
                accepted_ids = [str(item["navigation_audit_id"]) for item in accepted_rows]
                if selected_navigation_ids:
                    accepted_set = set(accepted_ids)
                    accepted_navigation_ids = [
                        audit_id
                        for audit_id in selected_navigation_ids
                        if audit_id in accepted_set
                    ]
                    navigation_audit_ids = list(selected_navigation_ids)
                    if (
                        len(accepted_navigation_ids) != len(selected_navigation_ids)
                        and not baseline_only_new_file_plan
                    ):
                        blockers.append("selected_navigation_audit_not_accepted")
                else:
                    navigation_audit_ids = accepted_ids
                    accepted_navigation_ids = accepted_ids
                for navigation_audit_id in accepted_navigation_ids:
                    target_binding_ids.extend(
                        str(item["binding_id"])
                        for item in connection.execute(
                            """
                            SELECT binding_id FROM navigation_target_bindings
                            WHERE project_id = ? AND navigation_audit_id = ?
                            ORDER BY binding_id
                            """,
                            (project_id, navigation_audit_id),
                        ).fetchall()
                    )
                    candidate_set_ids.extend(
                        str(item["candidate_set_id"])
                        for item in connection.execute(
                            """
                            SELECT candidate_set_id FROM navigation_candidate_sets
                            WHERE project_id = ? AND navigation_audit_id = ?
                            ORDER BY ordinal
                            """,
                            (project_id, navigation_audit_id),
                        ).fetchall()
                    )
                    context_snapshot_ids.extend(
                        str(item["context_snapshot_id"])
                        for item in connection.execute(
                            """
                            SELECT context_snapshot_id FROM navigation_context_snapshots
                            WHERE project_id = ? AND navigation_audit_id = ?
                            ORDER BY created_at, context_snapshot_id
                            """,
                            (project_id, navigation_audit_id),
                        ).fetchall()
                    )
                if not accepted_navigation_ids and not baseline_only_new_file_plan:
                    blockers.append("accepted_navigation_audit_missing")
            if (
                target_policy != PacketTargetPolicy.DOCUMENTAL_ONLY
                and not target_binding_ids
                and not baseline_only_new_file_plan
            ):
                blockers.append("accepted_target_binding_missing")
            blockers.extend(
                self._construction_readiness_blockers_for_connection(
                    connection, project_id, change_id, packet_id
                )
            )
            if hasattr(self, "_packet_reconciliation_blockers_for_connection"):
                blockers.extend(
                    self._packet_reconciliation_blockers_for_connection(
                        connection, project_id, change_id, packet_id
                    )
                )
            if not blockers:
                readiness = PacketReadinessState.EXECUTION_READY
            elif "packet_unresolved_authority_questions" in blockers:
                readiness = PacketReadinessState.NEEDS_AUTHORITY
            elif "packet_authority_blocker_open" in blockers:
                readiness = PacketReadinessState.NEEDS_AUTHORITY
            elif "packet_construction_audit_stale" in blockers:
                readiness = PacketReadinessState.STALE
            elif any(
                blocker in blockers
                for blocker in (
                    "selected_navigation_audit_not_accepted",
                    "accepted_navigation_audit_missing",
                    "accepted_target_binding_missing",
                    "provider_navigation_audit_snapshot_pending",
                )
            ):
                readiness = PacketReadinessState.NEEDS_TARGETS
            else:
                readiness = PacketReadinessState.DRAFT
            if (
                str(packet["readiness_state"]) == readiness.value
                and self._json_string_list(packet["navigation_audit_ids_json"])
                == navigation_audit_ids
                and self._json_string_list(packet["target_binding_ids_json"])
                == target_binding_ids
                and self._json_string_list(packet["candidate_set_ids_json"])
                == candidate_set_ids
                and self._json_string_list(packet["context_snapshot_ids_json"])
                == context_snapshot_ids
                and self._json_string_list(packet["readiness_blockers_json"])
                == blockers
            ):
                return self._change_value(connection, project_id, change_id)
            revision = int(packet["current_revision"]) + 1
            state_revision = int(packet["state_revision"]) + 1
            connection.execute(
                """
                UPDATE implementation_packets
                SET readiness_state = ?, navigation_audit_ids_json = ?,
                    target_binding_ids_json = ?, candidate_set_ids_json = ?,
                    context_snapshot_ids_json = ?, readiness_blockers_json = ?,
                    state_revision = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    readiness.value,
                    self._json(navigation_audit_ids),
                    self._json(target_binding_ids),
                    self._json(candidate_set_ids),
                    self._json(context_snapshot_ids),
                    self._json(blockers),
                    state_revision,
                    revision,
                    occurred_at,
                    project_id,
                    change_id,
                    packet_id,
                ),
            )
            self._append_packet_revision_from_current(
                connection, project_id, change_id, packet_id, actor, occurred_at
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                event_type="packet_readiness_evaluated",
                actor=actor,
                request_id=request_id,
                payload={
                    "readiness_state": readiness.value,
                    "target_policy": target_policy.value,
                    "readiness_blockers": blockers,
                    "navigation_audit_ids": navigation_audit_ids,
                    "target_binding_ids": target_binding_ids,
                },
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    @staticmethod
    def _current_plan_is_baseline_only_new_files(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        packet_revision: int,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT units.operation_kind,
                   units.mutation_target_binding_id,
                   units.context_target_binding_ids_json
            FROM packet_work_plans AS plans
            JOIN packet_work_plan_revisions AS revisions
              ON revisions.project_id = plans.project_id
             AND revisions.work_plan_id = plans.work_plan_id
            JOIN packet_work_plan_units AS units
              ON units.project_id = revisions.project_id
             AND units.work_plan_id = revisions.work_plan_id
             AND units.plan_revision = revisions.plan_revision
            WHERE plans.project_id = ? AND plans.change_id = ? AND plans.packet_id = ?
              AND revisions.status IN ('proposed', 'accepted')
              AND revisions.packet_revision = ?
              AND revisions.plan_revision = (
                  SELECT MAX(current_revision.plan_revision)
                  FROM packet_work_plan_revisions AS current_revision
                  WHERE current_revision.project_id = revisions.project_id
                    AND current_revision.work_plan_id = revisions.work_plan_id
              )
            ORDER BY units.unit_ordinal
            """,
            (project_id, change_id, packet_id, int(packet_revision)),
        ).fetchall()
        return bool(rows) and all(
            str(row["operation_kind"]) == "new_file"
            and not str(row["mutation_target_binding_id"] or "")
            and not json.loads(str(row["context_target_binding_ids_json"] or "[]"))
            for row in rows
        )

    def transition_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        transition: PacketTransition,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "packet_transitioned", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            if transition.successor_packet_id:
                if transition.successor_packet_id == packet_id:
                    raise ChangeControlBlockedError(
                        "packet_successor_self_link",
                        details={"packet_id": packet_id},
                    )
                self._packet_row(
                    connection, project_id, change_id, transition.successor_packet_id
                )
            revision = int(packet["current_revision"]) + 1
            state_revision = int(packet["state_revision"]) + 1
            merged_results = self._json_dict(packet["criterion_results_json"])
            merged_results.update(dict(transition.criterion_results))
            connection.execute(
                """
                UPDATE implementation_packets
                SET status = ?, criterion_results_json = ?, blocking_reasons_json = ?,
                    disposition = ?, successor_packet_id = ?, state_revision = ?, current_revision = ?,
                    updated_at = ?
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                """,
                (
                    transition.status.value,
                    self._json(merged_results),
                    self._json(list(transition.blocking_reasons)),
                    transition.disposition,
                    transition.successor_packet_id,
                    state_revision,
                    revision,
                    occurred_at,
                    project_id,
                    change_id,
                    packet_id,
                ),
            )
            self._append_packet_revision_from_current(
                connection, project_id, change_id, packet_id, actor, occurred_at
            )
            self._append_change_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                packet_id=packet_id,
                event_type="packet_transitioned",
                actor=actor,
                request_id=request_id,
                payload={
                    "from_status": str(packet["status"]),
                    "to_status": transition.status.value,
                    "criterion_result_count": len(transition.criterion_results),
                    "blocking_reasons": list(transition.blocking_reasons),
                    "disposition": transition.disposition,
                    "successor_packet_id": transition.successor_packet_id,
                },
                occurred_at=occurred_at,
            )
            self._update_change_status(connection, project_id, change_id, actor, occurred_at)
            return self._change_value(connection, project_id, change_id)

    @staticmethod
    def _json_dict(value: object) -> dict[str, str]:
        try:
            decoded = json.loads(str(value or "{}"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError("stored change-control object is invalid") from exc
        if not isinstance(decoded, dict):
            raise RequirementConflictError("stored change-control object is invalid")
        return {str(key): str(item) for key, item in decoded.items()}

    @staticmethod
    def _json_string_list(value: object) -> list[str]:
        try:
            decoded = json.loads(str(value or "[]"))
        except (TypeError, ValueError) as exc:
            raise RequirementConflictError("stored change-control list is invalid") from exc
        if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
            raise RequirementConflictError("stored change-control list is invalid")
        return [str(item) for item in decoded]

    def _change_row(
        self, connection: sqlite3.Connection, project_id: str, change_id: str
    ) -> sqlite3.Row:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM change_units WHERE project_id = ? AND change_id = ?",
            (project_id, change_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown change in project {project_id}: {change_id}")
        return row

    def _packet_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> sqlite3.Row:
        self._change_row(connection, project_id, change_id)
        row = connection.execute(
            """
            SELECT * FROM implementation_packets
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
            """,
            (project_id, change_id, packet_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown packet in change {change_id}: {packet_id}"
            )
        return row

    def _change_value(
        self, connection: sqlite3.Connection, project_id: str, change_id: str
    ) -> Mapping[str, Any]:
        row = self._change_row(connection, project_id, change_id)
        packets = [
            self._packet_value(connection, project_id, change_id, str(packet["packet_id"]))
            for packet in connection.execute(
                """
                SELECT packet_id FROM implementation_packets
                WHERE project_id = ? AND change_id = ?
                ORDER BY ordinal
                """,
                (project_id, change_id),
            ).fetchall()
        ]
        events = [
            dict(item)
            for item in connection.execute(
                """
                SELECT event_id, change_id, packet_id, event_type, actor, request_id,
                       payload_json, occurred_at
                FROM change_events
                WHERE project_id = ? AND change_id = ?
                ORDER BY event_id
                """,
                (project_id, change_id),
            ).fetchall()
        ]
        for event in events:
            event["payload"] = json.loads(event.pop("payload_json"))
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "ordinal": int(row["ordinal"]),
            "title": str(row["title"]),
            "rationale": str(row["rationale"]),
            "status": str(row["status"]),
            "milestone_id": str(row["milestone_id"]),
            "requirement_ids": self._json_string_list(row["requirement_ids_json"]),
            "source_refs": self._json_string_list(row["source_refs_json"]),
            "baseline_refs": self._json_string_list(row["baseline_refs_json"]),
            "current_revision": int(row["current_revision"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "created_by": str(row["created_by"]),
            "packets": packets,
            "events": events,
        }

    def _packet_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, Any]:
        row = self._packet_row(connection, project_id, change_id, packet_id)
        dependencies = [
            str(item["depends_on_packet_id"])
            for item in connection.execute(
                """
                SELECT depends_on_packet_id FROM packet_dependencies
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                ORDER BY depends_on_packet_id
                """,
                (project_id, change_id, packet_id),
            ).fetchall()
        ]
        dependents = [
            str(item["packet_id"])
            for item in connection.execute(
                """
                SELECT packet_id FROM packet_dependencies
                WHERE project_id = ? AND change_id = ? AND depends_on_packet_id = ?
                ORDER BY packet_id
                """,
                (project_id, change_id, packet_id),
            ).fetchall()
        ]
        remediation_links = connection.execute(
            """
            SELECT finding_id, required_regression_evidence,
                   required_campaign_ids_json
            FROM finding_packet_links
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
            ORDER BY finding_id
            """,
            (project_id, change_id, packet_id),
        ).fetchall()
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "purpose": "remediation" if remediation_links else "implementation",
            "ordinal": int(row["ordinal"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "readiness_state": str(row["readiness_state"]),
            "target_policy": str(row["target_policy"]),
            "objective": str(row["objective"]),
            "rationale": str(row["rationale"]),
            "requirement_ids": self._json_string_list(row["requirement_ids_json"]),
            "goal_ids": self._json_string_list(row["goal_ids_json"]),
            "in_scope": self._json_string_list(row["in_scope_json"]),
            "out_of_scope": self._json_string_list(row["out_of_scope_json"]),
            "invariants": self._json_string_list(row["invariants_json"]),
            "unresolved_questions": self._json_string_list(row["unresolved_questions_json"]),
            "navigation_audit_ids": self._json_string_list(row["navigation_audit_ids_json"]),
            "target_binding_ids": self._json_string_list(row["target_binding_ids_json"]),
            "candidate_set_ids": self._json_string_list(row["candidate_set_ids_json"]),
            "context_snapshot_ids": self._json_string_list(row["context_snapshot_ids_json"]),
            "readiness_blockers": self._json_string_list(row["readiness_blockers_json"]),
            "completion_criteria": self._json_string_list(row["completion_criteria_json"]),
            "criterion_results": self._json_dict(row["criterion_results_json"]),
            "blocking_reasons": self._json_string_list(row["blocking_reasons_json"]),
            "disposition": str(row["disposition"]),
            "successor_packet_id": str(row["successor_packet_id"]),
            "spec_revision": int(row["spec_revision"]),
            "state_revision": int(row["state_revision"]),
            "current_revision": int(row["current_revision"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "created_by": str(row["created_by"]),
            "dependency_packet_ids": dependencies,
            "dependent_packet_ids": dependents,
            "remediation": {
                "finding_ids": [str(item["finding_id"]) for item in remediation_links],
                "required_regression_evidence": sorted(
                    {
                        str(item["required_regression_evidence"])
                        for item in remediation_links
                        if str(item["required_regression_evidence"])
                    }
                ),
                "required_campaign_ids": sorted(
                    {
                        campaign_id
                        for item in remediation_links
                        for campaign_id in self._json_string_list(
                            item["required_campaign_ids_json"]
                        )
                    }
                ),
            },
        }

    @staticmethod
    def _append_change_revision(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        revision: int,
        title: str,
        rationale: str,
        status: str,
        milestone_id: str,
        requirement_ids: tuple[str, ...],
        source_refs: tuple[str, ...],
        baseline_refs: tuple[str, ...],
        actor: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO change_unit_revisions(
                project_id, change_id, revision, title, rationale, status,
                milestone_id, requirement_ids_json, source_refs_json, baseline_refs_json,
                actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                change_id,
                revision,
                title,
                rationale,
                status,
                milestone_id,
                json.dumps(list(requirement_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(source_refs), sort_keys=True, separators=(",", ":")),
                json.dumps(list(baseline_refs), sort_keys=True, separators=(",", ":")),
                actor,
                occurred_at,
            ),
        )

    @staticmethod
    def _append_packet_revision(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        packet_id: str,
        revision: int,
        title: str,
        status: str,
        readiness_state: str,
        target_policy: str,
        objective: str,
        rationale: str,
        requirement_ids: tuple[str, ...],
        goal_ids: tuple[str, ...],
        in_scope: tuple[str, ...],
        out_of_scope: tuple[str, ...],
        invariants: tuple[str, ...],
        unresolved_questions: tuple[str, ...],
        navigation_audit_ids: tuple[str, ...],
        target_binding_ids: tuple[str, ...],
        candidate_set_ids: tuple[str, ...],
        context_snapshot_ids: tuple[str, ...],
        readiness_blockers: tuple[str, ...],
        completion_criteria: tuple[str, ...],
        criterion_results: Mapping[str, str],
        blocking_reasons: tuple[str, ...],
        disposition: str,
        successor_packet_id: str,
        actor: str,
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO implementation_packet_revisions(
                project_id, change_id, packet_id, revision, title, status,
                readiness_state, target_policy, objective, rationale,
                requirement_ids_json, goal_ids_json, in_scope_json, out_of_scope_json,
                invariants_json, unresolved_questions_json, navigation_audit_ids_json,
                target_binding_ids_json, candidate_set_ids_json, context_snapshot_ids_json,
                readiness_blockers_json,
                completion_criteria_json, criterion_results_json,
                blocking_reasons_json, disposition, successor_packet_id,
                actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                change_id,
                packet_id,
                revision,
                title,
                status,
                readiness_state,
                target_policy,
                objective,
                rationale,
                json.dumps(list(requirement_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(goal_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(in_scope), sort_keys=True, separators=(",", ":")),
                json.dumps(list(out_of_scope), sort_keys=True, separators=(",", ":")),
                json.dumps(list(invariants), sort_keys=True, separators=(",", ":")),
                json.dumps(list(unresolved_questions), sort_keys=True, separators=(",", ":")),
                json.dumps(list(navigation_audit_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(target_binding_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(candidate_set_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(context_snapshot_ids), sort_keys=True, separators=(",", ":")),
                json.dumps(list(readiness_blockers), sort_keys=True, separators=(",", ":")),
                json.dumps(list(completion_criteria), sort_keys=True, separators=(",", ":")),
                json.dumps(dict(criterion_results), sort_keys=True, separators=(",", ":")),
                json.dumps(list(blocking_reasons), sort_keys=True, separators=(",", ":")),
                disposition,
                successor_packet_id,
                actor,
                occurred_at,
            ),
        )

    def _append_packet_revision_from_current(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        actor: str,
        occurred_at: str,
    ) -> None:
        row = self._packet_row(connection, project_id, change_id, packet_id)
        self._append_packet_revision(
            connection,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            revision=int(row["current_revision"]),
            title=str(row["title"]),
            status=str(row["status"]),
            readiness_state=str(row["readiness_state"]),
            target_policy=str(row["target_policy"]),
            objective=str(row["objective"]),
            rationale=str(row["rationale"]),
            requirement_ids=tuple(self._json_string_list(row["requirement_ids_json"])),
            goal_ids=tuple(self._json_string_list(row["goal_ids_json"])),
            in_scope=tuple(self._json_string_list(row["in_scope_json"])),
            out_of_scope=tuple(self._json_string_list(row["out_of_scope_json"])),
            invariants=tuple(self._json_string_list(row["invariants_json"])),
            unresolved_questions=tuple(self._json_string_list(row["unresolved_questions_json"])),
            navigation_audit_ids=tuple(self._json_string_list(row["navigation_audit_ids_json"])),
            target_binding_ids=tuple(self._json_string_list(row["target_binding_ids_json"])),
            candidate_set_ids=tuple(self._json_string_list(row["candidate_set_ids_json"])),
            context_snapshot_ids=tuple(self._json_string_list(row["context_snapshot_ids_json"])),
            readiness_blockers=tuple(self._json_string_list(row["readiness_blockers_json"])),
            completion_criteria=tuple(self._json_string_list(row["completion_criteria_json"])),
            criterion_results=self._json_dict(row["criterion_results_json"]),
            blocking_reasons=tuple(self._json_string_list(row["blocking_reasons_json"])),
            disposition=str(row["disposition"]),
            successor_packet_id=str(row["successor_packet_id"]),
            actor=actor,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _append_change_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
        packet_id: str = "",
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO change_events(
                project_id, change_id, packet_id, event_type, actor, request_id,
                payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                change_id,
                packet_id,
                event_type,
                actor,
                str(request_id or ""),
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _change_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT event_id FROM change_events
            WHERE project_id = ? AND change_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, change_id, event_type, str(request_id)),
        ).fetchone()

    def _packet_depends_on(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        *,
        start_packet_id: str,
        target_packet_id: str,
    ) -> bool:
        stack = [start_packet_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target_packet_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(
                str(item["depends_on_packet_id"])
                for item in connection.execute(
                    """
                    SELECT depends_on_packet_id FROM packet_dependencies
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                    """,
                    (project_id, change_id, current),
                ).fetchall()
            )
        return False

    def _update_change_status(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        actor: str,
        occurred_at: str,
    ) -> None:
        change = self._change_row(connection, project_id, change_id)
        if str(change["status"]) == ChangeStatus.ACCEPTED.value:
            return
        packets = connection.execute(
            """
            SELECT status, blocking_reasons_json FROM implementation_packets
            WHERE project_id = ? AND change_id = ?
            ORDER BY ordinal
            """,
            (project_id, change_id),
        ).fetchall()
        if not packets:
            status = ChangeStatus.PLANNED.value
        elif any(self._json_string_list(packet["blocking_reasons_json"]) for packet in packets):
            status = ChangeStatus.BLOCKED.value
        elif all(
            str(packet["status"])
            in {PacketStatus.IMPLEMENTED.value, PacketStatus.SUPERSEDED.value}
            for packet in packets
        ):
            status = ChangeStatus.IMPLEMENTED.value
        elif all(
            str(packet["status"]) == PacketStatus.CANCELLED.value
            for packet in packets
        ):
            status = ChangeStatus.CANCELLED.value
        elif all(
            str(packet["status"]) in PACKET_TERMINAL_STATUS_VALUES
            for packet in packets
        ):
            status = ChangeStatus.PARTIAL.value
        elif any(
            str(packet["status"]) == PacketStatus.PARTIAL.value
            for packet in packets
        ):
            status = ChangeStatus.PARTIAL.value
        elif any(
            str(packet["status"]) != PacketStatus.PLANNED.value
            for packet in packets
        ):
            status = ChangeStatus.ACTIVE.value
        else:
            status = ChangeStatus.PLANNED.value
        if str(change["status"]) == status:
            return
        revision = int(change["current_revision"]) + 1
        connection.execute(
            """
            UPDATE change_units
            SET status = ?, current_revision = ?, updated_at = ?
            WHERE project_id = ? AND change_id = ?
            """,
            (status, revision, occurred_at, project_id, change_id),
        )
        self._append_change_revision(
            connection,
            project_id=project_id,
            change_id=change_id,
            revision=revision,
            title=str(change["title"]),
            rationale=str(change["rationale"]),
            status=status,
            milestone_id=str(change["milestone_id"]),
            requirement_ids=tuple(self._json_string_list(change["requirement_ids_json"])),
            source_refs=tuple(self._json_string_list(change["source_refs_json"])),
            baseline_refs=tuple(self._json_string_list(change["baseline_refs_json"])),
            actor=actor,
            occurred_at=occurred_at,
        )
