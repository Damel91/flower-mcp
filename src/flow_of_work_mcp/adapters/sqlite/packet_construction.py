"""SQLite packet-construction audit persistence."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.packet_construction import (
    PacketConstructionAuditDraft,
    PacketConstructionAuditState,
    PacketQuestionCategory,
    PacketQuestionResolutionDraft,
    PacketQuestionStatus,
    validate_construction_audit_id,
    validate_packet_question_id,
)
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from flow_of_work_mcp.core.domain.engineering_question_policy import (
    QUESTION_POLICY_VERSION,
    applicable_question_rules,
    dependency_fingerprint,
    question_is_required,
    question_prompt,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now


_TERMINAL_AUDIT_STATES = {
    PacketConstructionAuditState.SUPERSEDED.value,
    PacketConstructionAuditState.CLOSED.value,
}


class PacketConstructionStoreMixin:
    def start_packet_construction_audit(
        self,
        project_id: str,
        draft: PacketConstructionAuditDraft,
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
            packet = self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = self._construction_event_for_request(
                    connection,
                    project_id,
                    "construction_audit_started",
                    request_id,
                )
                if replay is not None:
                    return self._construction_audit_value(
                        connection, project_id, str(replay["construction_audit_id"])
                    )
            existing = connection.execute(
                """
                SELECT construction_audit_id FROM packet_construction_audits
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state NOT IN ('superseded', 'closed')
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, draft.change_id, draft.packet_id),
            ).fetchone()
            if existing is not None:
                self._refresh_construction_questions(
                    connection,
                    project_id,
                    str(existing["construction_audit_id"]),
                    packet,
                    draft.profile,
                    actor=actor,
                    occurred_at=occurred_at,
                )
                return self._construction_audit_value(
                    connection, project_id, str(existing["construction_audit_id"])
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO packet_construction_sequences(
                    project_id, next_audit_ordinal, next_question_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            sequence = connection.execute(
                """
                SELECT next_audit_ordinal, next_question_ordinal
                FROM packet_construction_sequences WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            audit_ordinal = int(sequence["next_audit_ordinal"])
            question_ordinal = int(sequence["next_question_ordinal"])
            construction_audit_id = f"PCAUD-{audit_ordinal:06d}"
            questions = self._derive_questions_for_packet(
                connection, project_id, draft.change_id, draft.packet_id, packet, draft.profile
            )
            connection.execute(
                """
                INSERT INTO packet_construction_audits(
                    project_id, construction_audit_id, ordinal, milestone_id, change_id,
                    packet_id, packet_revision, question_plan_revision, state,
                    target_policy, profile, created_at, updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    construction_audit_id,
                    audit_ordinal,
                    draft.milestone_id,
                    draft.change_id,
                    draft.packet_id,
                    int(packet["spec_revision"]),
                    PacketConstructionAuditState.OPEN.value,
                    str(packet["target_policy"]),
                    draft.profile,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            for local_ordinal, question in enumerate(questions, start=1):
                question_id = f"PQUESTION-{question_ordinal:06d}"
                question_ordinal += 1
                connection.execute(
                    """
                    INSERT INTO packet_construction_questions(
                        project_id, construction_audit_id, question_id, ordinal, question_key,
                        category, prompt, required, status, dependency_keys_json,
                        dependency_fingerprint, created_at, updated_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        construction_audit_id,
                        question_id,
                        local_ordinal,
                        question["question_key"],
                        question["category"],
                        question["prompt"],
                        1 if question["required"] else 0,
                        PacketQuestionStatus.OPEN.value,
                        _json(list(question["dependency_keys"])),
                        question["dependency_fingerprint"],
                        occurred_at,
                        occurred_at,
                        actor,
                        request_id,
                    ),
                )
            connection.execute(
                """
                UPDATE packet_construction_sequences
                SET next_audit_ordinal = ?, next_question_ordinal = ?
                WHERE project_id = ?
                """,
                (audit_ordinal + 1, question_ordinal, project_id),
            )
            state = self._derive_construction_state(
                connection,
                project_id,
                construction_audit_id,
            )
            connection.execute(
                """
                UPDATE packet_construction_audits
                SET state = ?, updated_at = ?
                WHERE project_id = ? AND construction_audit_id = ?
                """,
                (
                    state.value,
                    occurred_at,
                    project_id,
                    construction_audit_id,
                ),
            )
            self._append_construction_event(
                connection,
                project_id=project_id,
                construction_audit_id=construction_audit_id,
                event_type="construction_audit_started",
                actor=actor,
                request_id=request_id,
                payload={
                    "change_id": draft.change_id,
                    "packet_id": draft.packet_id,
                    "profile": draft.profile,
                    "question_count": len(questions),
                    "state": state.value,
                },
                occurred_at=occurred_at,
            )
            return self._construction_audit_value(connection, project_id, construction_audit_id)

    def packet_construction_audit_state(
        self, project_id: str, construction_audit_id: str
    ) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._construction_audit_value(
                connection,
                validate_project_id(project_id),
                validate_construction_audit_id(construction_audit_id),
            )

    def packet_construction_audit_for_packet(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT construction_audit_id FROM packet_construction_audits
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND state NOT IN ('superseded', 'closed')
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if row is None:
                return None
            return self._construction_audit_value(
                connection, project_id, str(row["construction_audit_id"])
            )

    def answer_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        if not (draft.answer_summary or draft.evidence_refs or draft.linked_navigation_refs):
            raise ValueError("answer requires summary or evidence")
        spec_revision = self._packet_spec_revision_for_audit(
            project_id, construction_audit_id
        )
        return self.resolve_packet_questions_batch(
            project_id,
            construction_audit_id,
            (draft,),
            expected_spec_revision=spec_revision,
            actor=actor,
            request_id=request_id,
        )

    def waive_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        required_text(draft.waiver_rationale, "waiver_rationale")
        required_text(draft.policy_ref, "policy_ref")
        spec_revision = self._packet_spec_revision_for_audit(
            project_id, construction_audit_id
        )
        return self.resolve_packet_questions_batch(
            project_id,
            construction_audit_id,
            (draft,),
            expected_spec_revision=spec_revision,
            actor=actor,
            request_id=request_id,
        )

    def block_packet_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        required_text(draft.blocker_reason, "blocker_reason")
        spec_revision = self._packet_spec_revision_for_audit(
            project_id, construction_audit_id
        )
        return self.resolve_packet_questions_batch(
            project_id,
            construction_audit_id,
            (draft,),
            expected_spec_revision=spec_revision,
            actor=actor,
            request_id=request_id,
        )

    def resolve_packet_questions_batch(
        self,
        project_id: str,
        construction_audit_id: str,
        drafts: tuple[PacketQuestionResolutionDraft, ...],
        *,
        expected_spec_revision: int,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        construction_audit_id = validate_construction_audit_id(construction_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        if not drafts:
            raise ValueError("question answer batch must not be empty")
        question_ids = [draft.question_id for draft in drafts]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question answer batch contains duplicate question_id")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            audit = self._construction_audit_row(connection, project_id, construction_audit_id)
            if str(audit["state"]) in _TERMINAL_AUDIT_STATES:
                raise ChangeControlBlockedError("packet_construction_audit_terminal_state")
            packet = self._packet_row(
                connection, project_id, str(audit["change_id"]), str(audit["packet_id"])
            )
            current_spec_revision = int(packet["spec_revision"])
            if current_spec_revision != int(expected_spec_revision):
                raise RequirementConflictError(
                    "stale spec_revision for question batch: "
                    f"expected {current_spec_revision}, received {int(expected_spec_revision)}"
                )
            self._refresh_construction_questions(
                connection,
                project_id,
                construction_audit_id,
                packet,
                str(audit["profile"]),
                actor=actor,
                occurred_at=occurred_at,
            )
            audit = self._construction_audit_row(
                connection, project_id, construction_audit_id
            )
            if request_id:
                replay = self._construction_event_for_request(
                    connection, project_id, "packet_questions_batch_resolved", request_id
                )
                if replay is not None:
                    return self._construction_audit_value(
                        connection, project_id, construction_audit_id
                    )

            rows = {
                str(row["question_id"]): row
                for row in connection.execute(
                    """
                    SELECT * FROM packet_construction_questions
                    WHERE project_id = ? AND construction_audit_id = ?
                    """,
                    (project_id, construction_audit_id),
                ).fetchall()
            }
            rules = {rule.key: rule for rule in applicable_question_rules(
                self._packet_operation_kinds(
                    connection, project_id, str(audit["change_id"]), str(audit["packet_id"])
                ),
                target_policy=str(packet["target_policy"]),
                profile=str(audit["profile"]),
            )}
            validated: list[tuple[PacketQuestionResolutionDraft, sqlite3.Row, PacketQuestionStatus]] = []
            for draft in drafts:
                row = rows.get(draft.question_id)
                if row is None:
                    raise RequirementConflictError(
                        f"unknown packet question: {draft.question_id}"
                    )
                rule = rules.get(str(row["question_key"]))
                if rule is None:
                    raise RequirementConflictError(
                        f"question is no longer applicable: {draft.question_id}"
                    )
                if draft.answer_source == "model_proposal":
                    raise ValueError(
                        f"{draft.question_id}: model_proposal must be explicitly accepted first"
                    )
                if draft.blocker_reason:
                    status = PacketQuestionStatus.BLOCKED
                elif draft.waiver_rationale or draft.policy_ref:
                    if not rule.waiver_allowed:
                        raise ValueError(f"{draft.question_id}: waiver is not allowed")
                    required_text(draft.waiver_rationale, "waiver_rationale")
                    required_text(draft.policy_ref, "policy_ref")
                    status = PacketQuestionStatus.WAIVED
                else:
                    if not (draft.answer_summary or draft.evidence_refs or draft.linked_navigation_refs):
                        raise ValueError(f"{draft.question_id}: answer requires summary or evidence")
                    if draft.answer_source == "deterministic_evidence":
                        if not rule.deterministic_evidence_allowed:
                            raise ValueError(
                                f"{draft.question_id}: deterministic evidence cannot satisfy this question"
                            )
                        if not draft.evidence_refs:
                            raise ValueError(
                                f"{draft.question_id}: deterministic evidence references are required"
                            )
                    status = PacketQuestionStatus.ANSWERED
                validated.append((draft, row, status))

            changed_resolutions: list[tuple[PacketQuestionResolutionDraft, sqlite3.Row, PacketQuestionStatus]] = []
            semantic_change = False
            for draft, row, status in validated:
                current_value = (
                    str(row["status"]),
                    _json_string_list(row["evidence_refs_json"]),
                    _json_string_list(row["linked_navigation_refs_json"]),
                    str(row["answer_summary"]),
                    str(row["answer_source"]),
                    str(row["blocker_reason"]),
                    str(row["waiver_rationale"]),
                    str(row["policy_ref"]),
                )
                requested_value = (
                    status.value,
                    list(draft.evidence_refs),
                    list(draft.linked_navigation_refs),
                    draft.answer_summary,
                    draft.answer_source,
                    draft.blocker_reason,
                    draft.waiver_rationale,
                    draft.policy_ref,
                )
                if current_value != requested_value:
                    changed_resolutions.append((draft, row, status))
                    current_semantics = (
                        str(row["status"]),
                        str(row["answer_summary"]),
                        str(row["blocker_reason"]),
                        str(row["waiver_rationale"]),
                        str(row["policy_ref"]),
                    )
                    requested_semantics = (
                        status.value,
                        draft.answer_summary,
                        draft.blocker_reason,
                        draft.waiver_rationale,
                        draft.policy_ref,
                    )
                    semantic_change = semantic_change or (
                        current_semantics != requested_semantics
                    )

            if not changed_resolutions:
                return self._construction_audit_value(
                    connection, project_id, construction_audit_id
                )

            for draft, row, status in changed_resolutions:
                connection.execute(
                    """
                    UPDATE packet_construction_questions
                    SET status = ?, evidence_refs_json = ?, answer_evidence_refs_json = ?,
                        linked_navigation_refs_json = ?, answer_summary = ?,
                        answer_source = ?, blocker_reason = ?, waiver_rationale = ?,
                        policy_ref = ?, updated_at = ?, actor = ?, request_id = ?
                    WHERE project_id = ? AND construction_audit_id = ? AND question_id = ?
                    """,
                    (
                        status.value,
                        _json(list(draft.evidence_refs)),
                        _json(list(draft.evidence_refs)),
                        _json(list(draft.linked_navigation_refs)),
                        draft.answer_summary,
                        draft.answer_source,
                        draft.blocker_reason,
                        draft.waiver_rationale,
                        draft.policy_ref,
                        occurred_at,
                        actor,
                        request_id,
                        project_id,
                        construction_audit_id,
                        draft.question_id,
                    ),
                )
            new_spec_revision = current_spec_revision
            if semantic_change:
                new_spec_revision += 1
                aggregate_revision = int(packet["current_revision"]) + 1
                connection.execute(
                    """
                    UPDATE implementation_packets
                    SET spec_revision = ?, current_revision = ?, updated_at = ?
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                    """,
                    (
                        new_spec_revision,
                        aggregate_revision,
                        occurred_at,
                        project_id,
                        str(audit["change_id"]),
                        str(audit["packet_id"]),
                    ),
                )
                self._append_packet_revision_from_current(
                    connection,
                    project_id,
                    str(audit["change_id"]),
                    str(audit["packet_id"]),
                    actor,
                    occurred_at,
                )
            else:
                self._bump_packet_state_revision(
                    connection,
                    project_id,
                    str(audit["change_id"]),
                    str(audit["packet_id"]),
                    actor=actor,
                    occurred_at=occurred_at,
                )
            new_state = self._derive_construction_state(
                connection, project_id, construction_audit_id
            )
            connection.execute(
                """
                UPDATE packet_construction_audits
                SET state = ?, packet_revision = ?, updated_at = ?
                WHERE project_id = ? AND construction_audit_id = ?
                """,
                (
                    new_state.value,
                    new_spec_revision,
                    occurred_at,
                    project_id,
                    construction_audit_id,
                ),
            )
            self._append_construction_event(
                connection,
                project_id=project_id,
                construction_audit_id=construction_audit_id,
                event_type="packet_questions_batch_resolved",
                actor=actor,
                request_id=request_id,
                payload={
                    "question_ids": [item[0].question_id for item in changed_resolutions],
                    "previous_spec_revision": current_spec_revision,
                    "spec_revision": new_spec_revision,
                    "revision_class": "semantic" if semantic_change else "evidence",
                    "policy_version": QUESTION_POLICY_VERSION,
                },
                occurred_at=occurred_at,
            )
            return self._construction_audit_value(
                connection, project_id, construction_audit_id
            )

    def construction_readiness_blockers(
        self, project_id: str, change_id: str, packet_id: str
    ) -> tuple[str, ...]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            return self._construction_readiness_blockers_for_connection(
                connection, project_id, change_id, packet_id
            )

    def _construction_readiness_blockers_for_connection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> tuple[str, ...]:
        self._packet_row(connection, project_id, change_id, packet_id)
        audit = connection.execute(
            """
            SELECT construction_audit_id, state, packet_revision FROM packet_construction_audits
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND state NOT IN ('superseded', 'closed')
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, change_id, packet_id),
        ).fetchone()
        if audit is None:
            return ("packet_construction_audit_missing",)
        if self._construction_audit_is_stale(
            connection,
            project_id,
            change_id,
            packet_id,
            int(audit["packet_revision"]),
        ):
            return ("packet_construction_audit_stale",)
        questions = connection.execute(
            """
            SELECT category, required, status FROM packet_construction_questions
            WHERE project_id = ? AND construction_audit_id = ?
            ORDER BY ordinal
            """,
            (project_id, str(audit["construction_audit_id"])),
        ).fetchall()
        blockers: list[str] = []
        if str(audit["state"]) == PacketConstructionAuditState.BLOCKED.value:
            blockers.append("packet_authority_blocker_open")
        unresolved_required = [
            question
            for question in questions
            if int(question["required"]) == 1
            and str(question["status"]) not in {"answered", "waived"}
        ]
        if unresolved_required:
            blockers.append("packet_construction_questions_open")
        for question in unresolved_required:
            category = str(question["category"])
            if category == PacketQuestionCategory.ENTRYPOINT_SURFACE.value:
                blockers.append("packet_entrypoint_surface_missing")
            elif category == PacketQuestionCategory.SYMBOL_CONTRACT.value:
                blockers.append("packet_symbol_contract_missing")
            elif category == PacketQuestionCategory.IMPACT.value:
                blockers.append("packet_impact_evidence_missing")
            elif category == PacketQuestionCategory.CLEANUP.value:
                blockers.append("packet_cleanup_evidence_missing")
            elif category == PacketQuestionCategory.TEST_EVIDENCE.value:
                blockers.append("packet_test_evidence_missing")
            elif category == PacketQuestionCategory.AUTHORITY_BLOCKER.value:
                blockers.append("packet_authority_blocker_open")
        return tuple(sorted(set(blockers)))

    def _resolve_question(
        self,
        project_id: str,
        construction_audit_id: str,
        draft: PacketQuestionResolutionDraft,
        *,
        status: PacketQuestionStatus,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        construction_audit_id = validate_construction_audit_id(construction_audit_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            audit = self._construction_audit_row(connection, project_id, construction_audit_id)
            if str(audit["state"]) in _TERMINAL_AUDIT_STATES:
                raise ChangeControlBlockedError(
                    "packet_construction_audit_terminal_state",
                    details={
                        "construction_audit_id": construction_audit_id,
                        "state": str(audit["state"]),
                    },
                )
            question = self._construction_question_row(
                connection, project_id, construction_audit_id, draft.question_id
            )
            packet = self._packet_row(
                connection,
                project_id,
                str(audit["change_id"]),
                str(audit["packet_id"]),
            )
            if request_id:
                replay = self._construction_event_for_request(
                    connection,
                    project_id,
                    f"packet_question_{status.value}",
                    request_id,
                )
                if replay is not None:
                    return self._construction_audit_value(connection, project_id, construction_audit_id)
            connection.execute(
                """
                UPDATE packet_construction_questions
                SET status = ?, evidence_refs_json = ?, linked_navigation_refs_json = ?,
                    answer_summary = ?, blocker_reason = ?, waiver_rationale = ?,
                    policy_ref = ?, updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND construction_audit_id = ? AND question_id = ?
                """,
                (
                    status.value,
                    _json(list(draft.evidence_refs)),
                    _json(list(draft.linked_navigation_refs)),
                    draft.answer_summary,
                    draft.blocker_reason,
                    draft.waiver_rationale,
                    draft.policy_ref,
                    occurred_at,
                    actor,
                    request_id,
                    project_id,
                    construction_audit_id,
                    draft.question_id,
                ),
            )
            new_state = self._derive_construction_state(connection, project_id, construction_audit_id)
            connection.execute(
                """
                UPDATE packet_construction_audits
                SET state = ?, packet_revision = ?, updated_at = ?
                WHERE project_id = ? AND construction_audit_id = ?
                """,
                (
                    new_state.value,
                    int(packet["spec_revision"]),
                    occurred_at,
                    project_id,
                    construction_audit_id,
                ),
            )
            self._append_construction_event(
                connection,
                project_id=project_id,
                construction_audit_id=construction_audit_id,
                question_id=str(question["question_id"]),
                event_type=f"packet_question_{status.value}",
                actor=actor,
                request_id=request_id,
                payload={
                    "question_id": draft.question_id,
                    "status": status.value,
                    "evidence_refs": list(draft.evidence_refs),
                    "linked_navigation_refs": list(draft.linked_navigation_refs),
                },
                occurred_at=occurred_at,
            )
            return self._construction_audit_value(connection, project_id, construction_audit_id)

    def _construction_audit_is_stale(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        audit_packet_revision: int,
    ) -> bool:
        packet = self._packet_row(connection, project_id, change_id, packet_id)
        return int(packet["spec_revision"]) != int(audit_packet_revision)

    def _derive_construction_state(
        self, connection: sqlite3.Connection, project_id: str, construction_audit_id: str
    ) -> PacketConstructionAuditState:
        questions = connection.execute(
            """
            SELECT required, status FROM packet_construction_questions
            WHERE project_id = ? AND construction_audit_id = ?
            """,
            (project_id, construction_audit_id),
        ).fetchall()
        if any(
            int(question["required"]) == 1
            and str(question["status"]) == PacketQuestionStatus.BLOCKED.value
            for question in questions
        ):
            return PacketConstructionAuditState.BLOCKED
        if all(
            int(question["required"]) != 1
            or str(question["status"]) in {"answered", "waived"}
            for question in questions
        ):
            return PacketConstructionAuditState.READY_FOR_READINESS
        return PacketConstructionAuditState.OPEN

    def _construction_audit_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        construction_audit_id: str,
    ) -> Mapping[str, Any]:
        row = self._construction_audit_row(connection, project_id, construction_audit_id)
        questions = [
            self._construction_question_value(question)
            for question in connection.execute(
                """
                SELECT * FROM packet_construction_questions
                WHERE project_id = ? AND construction_audit_id = ?
                ORDER BY ordinal
                """,
                (project_id, construction_audit_id),
            ).fetchall()
        ]
        return {
            "project_id": str(row["project_id"]),
            "construction_audit_id": str(row["construction_audit_id"]),
            "ordinal": int(row["ordinal"]),
            "milestone_id": str(row["milestone_id"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "packet_revision": int(row["packet_revision"]),
            "question_plan_revision": int(row["question_plan_revision"]),
            "state": str(row["state"]),
            "target_policy": str(row["target_policy"]),
            "profile": str(row["profile"]),
            "questions": questions,
            "open_required_question_ids": [
                str(question["question_id"])
                for question in questions
                if question["required"] and question["status"] not in {"answered", "waived"}
            ],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "created_by": str(row["created_by"]),
        }

    def _construction_audit_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        construction_audit_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_construction_audits
            WHERE project_id = ? AND construction_audit_id = ?
            """,
            (project_id, validate_construction_audit_id(construction_audit_id)),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown construction audit: {construction_audit_id}")
        return row

    def _construction_question_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        construction_audit_id: str,
        question_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_construction_questions
            WHERE project_id = ? AND construction_audit_id = ? AND question_id = ?
            """,
            (project_id, construction_audit_id, validate_packet_question_id(question_id)),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown packet question: {question_id}")
        return row

    @staticmethod
    def _construction_question_value(row: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "question_id": str(row["question_id"]),
            "ordinal": int(row["ordinal"]),
            "question_key": str(row["question_key"]),
            "category": str(row["category"]),
            "prompt": str(row["prompt"]),
            "required": bool(row["required"]),
            "status": str(row["status"]),
            "evidence_refs": _json_string_list(row["evidence_refs_json"]),
            "linked_navigation_refs": _json_string_list(row["linked_navigation_refs_json"]),
            "answer_summary": str(row["answer_summary"]),
            "blocker_reason": str(row["blocker_reason"]),
            "waiver_rationale": str(row["waiver_rationale"]),
            "policy_ref": str(row["policy_ref"]),
            "dependency_keys": _json_string_list(row["dependency_keys_json"]),
            "dependency_fingerprint": str(row["dependency_fingerprint"]),
            "answer_source": str(row["answer_source"]),
            "answer_evidence_refs": _json_string_list(row["answer_evidence_refs_json"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _derive_questions_for_packet(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        packet: sqlite3.Row,
        profile: str,
    ) -> list[Mapping[str, object]]:
        packet_value = self._packet_semantic_value(packet)
        return [
            {
                "question_key": rule.key,
                "category": rule.category.value,
                "prompt": question_prompt(rule, packet_value),
                "required": question_is_required(rule, packet_value),
                "dependency_keys": rule.dependency_keys,
                "dependency_fingerprint": dependency_fingerprint(
                    packet_value, rule.dependency_keys
                ),
            }
            for rule in applicable_question_rules(
                self._packet_operation_kinds(
                    connection, project_id, change_id, packet_id
                ),
                target_policy=str(packet["target_policy"]),
                profile=profile,
            )
        ]

    def _packet_spec_revision_for_audit(
        self, project_id: str, construction_audit_id: str
    ) -> int:
        project_id = validate_project_id(project_id)
        construction_audit_id = validate_construction_audit_id(
            construction_audit_id
        )
        with self._read_connection() as connection:
            audit = self._construction_audit_row(
                connection, project_id, construction_audit_id
            )
            packet = self._packet_row(
                connection,
                project_id,
                str(audit["change_id"]),
                str(audit["packet_id"]),
            )
            return int(packet["spec_revision"])

    def _refresh_construction_questions(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        construction_audit_id: str,
        packet: sqlite3.Row,
        profile: str,
        *,
        actor: str,
        occurred_at: str,
    ) -> None:
        audit = self._construction_audit_row(
            connection, project_id, construction_audit_id
        )
        questions = self._derive_questions_for_packet(
            connection,
            project_id,
            str(audit["change_id"]),
            str(audit["packet_id"]),
            packet,
            profile,
        )
        desired = {str(item["question_key"]): item for item in questions}
        existing = {
            str(row["question_key"]): row
            for row in connection.execute(
                """
                SELECT * FROM packet_construction_questions
                WHERE project_id = ? AND construction_audit_id = ?
                """,
                (project_id, construction_audit_id),
            ).fetchall()
        }
        changed = (
            int(audit["packet_revision"]) != int(packet["spec_revision"])
            or set(existing) != set(desired)
            or any(
                str(existing[key]["dependency_fingerprint"])
                != str(desired[key]["dependency_fingerprint"])
                or str(existing[key]["prompt"]) != str(desired[key]["prompt"])
                or bool(existing[key]["required"]) != bool(desired[key]["required"])
                for key in set(existing) & set(desired)
            )
        )
        if not changed:
            return
        for question_key in set(existing) - set(desired):
            connection.execute(
                """
                DELETE FROM packet_construction_questions
                WHERE project_id = ? AND construction_audit_id = ? AND question_key = ?
                """,
                (project_id, construction_audit_id, question_key),
            )
        sequence = connection.execute(
            """
            SELECT next_question_ordinal FROM packet_construction_sequences
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        next_question_ordinal = int(sequence["next_question_ordinal"])
        next_local_ordinal = 1
        for question in questions:
            key = str(question["question_key"])
            row = existing.get(key)
            if row is None:
                question_id = f"PQUESTION-{next_question_ordinal:06d}"
                next_question_ordinal += 1
                connection.execute(
                    """
                    INSERT INTO packet_construction_questions(
                        project_id, construction_audit_id, question_id, ordinal,
                        question_key, category, prompt, required, status,
                        dependency_keys_json, dependency_fingerprint,
                        created_at, updated_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                    """,
                    (
                        project_id,
                        construction_audit_id,
                        question_id,
                        next_local_ordinal,
                        key,
                        question["category"],
                        question["prompt"],
                        1 if question["required"] else 0,
                        PacketQuestionStatus.OPEN.value,
                        _json(list(question["dependency_keys"])),
                        question["dependency_fingerprint"],
                        occurred_at,
                        occurred_at,
                        actor,
                    ),
                )
            else:
                fingerprint_changed = (
                    str(row["dependency_fingerprint"])
                    != str(question["dependency_fingerprint"])
                )
                connection.execute(
                    """
                    UPDATE packet_construction_questions
                    SET ordinal = ?, category = ?, prompt = ?, required = ?,
                        dependency_keys_json = ?, dependency_fingerprint = ?,
                        status = CASE WHEN ? THEN 'open' ELSE status END,
                        evidence_refs_json = CASE WHEN ? THEN '[]' ELSE evidence_refs_json END,
                        answer_evidence_refs_json = CASE WHEN ? THEN '[]' ELSE answer_evidence_refs_json END,
                        linked_navigation_refs_json = CASE WHEN ? THEN '[]' ELSE linked_navigation_refs_json END,
                        answer_summary = CASE WHEN ? THEN '' ELSE answer_summary END,
                        answer_source = CASE WHEN ? THEN '' ELSE answer_source END,
                        blocker_reason = CASE WHEN ? THEN '' ELSE blocker_reason END,
                        waiver_rationale = CASE WHEN ? THEN '' ELSE waiver_rationale END,
                        policy_ref = CASE WHEN ? THEN '' ELSE policy_ref END,
                        updated_at = ?, actor = ?
                    WHERE project_id = ? AND construction_audit_id = ? AND question_key = ?
                    """,
                    (
                        next_local_ordinal,
                        question["category"],
                        question["prompt"],
                        1 if question["required"] else 0,
                        _json(list(question["dependency_keys"])),
                        question["dependency_fingerprint"],
                        *([1 if fingerprint_changed else 0] * 9),
                        occurred_at,
                        actor,
                        project_id,
                        construction_audit_id,
                        key,
                    ),
                )
            next_local_ordinal += 1
        connection.execute(
            """
            UPDATE packet_construction_sequences SET next_question_ordinal = ?
            WHERE project_id = ?
            """,
            (next_question_ordinal, project_id),
        )
        state = self._derive_construction_state(
            connection, project_id, construction_audit_id
        )
        connection.execute(
            """
            UPDATE packet_construction_audits
            SET packet_revision = ?, question_plan_revision = question_plan_revision + 1,
                state = ?, updated_at = ?
            WHERE project_id = ? AND construction_audit_id = ?
            """,
            (
                int(packet["spec_revision"]),
                state.value,
                occurred_at,
                project_id,
                construction_audit_id,
            ),
        )

    @staticmethod
    def _packet_operation_kinds(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT DISTINCT units.operation_kind
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
            ORDER BY units.operation_kind
            """,
            (project_id, change_id, packet_id),
        ).fetchall()
        # Before a work plan exists, preserve both bounded authoring branches.
        # The first authored plan narrows the policy and removes non-applicable
        # questions without invalidating answers whose dependencies still match.
        return tuple(str(row["operation_kind"]) for row in rows) or (
            "modify_existing",
            "new_file",
        )

    @staticmethod
    def _packet_semantic_value(packet: sqlite3.Row) -> Mapping[str, object]:
        return {
            "target_policy": str(packet["target_policy"]),
            "objective": str(packet["objective"]),
            "rationale": str(packet["rationale"]),
            "requirement_ids": _json_string_list(packet["requirement_ids_json"]),
            "goal_ids": _json_string_list(packet["goal_ids_json"]),
            "in_scope": _json_string_list(packet["in_scope_json"]),
            "out_of_scope": _json_string_list(packet["out_of_scope_json"]),
            "invariants": _json_string_list(packet["invariants_json"]),
            "unresolved_questions": _json_string_list(packet["unresolved_questions_json"]),
            "navigation_audit_ids": _json_string_list(packet["navigation_audit_ids_json"]),
            "target_binding_ids": _json_string_list(packet["target_binding_ids_json"]),
            "candidate_set_ids": _json_string_list(packet["candidate_set_ids_json"]),
            "context_snapshot_ids": _json_string_list(packet["context_snapshot_ids_json"]),
            "completion_criteria": _json_string_list(packet["completion_criteria_json"]),
        }

    @staticmethod
    def _append_construction_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        construction_audit_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
        question_id: str = "",
    ) -> None:
        connection.execute(
            """
            INSERT INTO packet_construction_events(
                project_id, construction_audit_id, question_id, event_type, actor,
                request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                construction_audit_id,
                question_id,
                event_type,
                actor,
                request_id,
                _json(dict(payload)),
                occurred_at,
            ),
        )

    @staticmethod
    def _construction_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT construction_audit_id FROM packet_construction_events
            WHERE project_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, event_type, request_id),
        ).fetchone()

def _construction_signature(packet: sqlite3.Row) -> tuple[object, ...]:
    """Fields that make existing construction answers semantically reusable."""

    return (
        str(packet["target_policy"]),
        str(packet["objective"]),
        str(packet["rationale"]),
        str(packet["requirement_ids_json"]),
        str(packet["goal_ids_json"]),
        str(packet["in_scope_json"]),
        str(packet["out_of_scope_json"]),
        str(packet["invariants_json"]),
        str(packet["unresolved_questions_json"]),
        str(packet["completion_criteria_json"]),
    )
def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value or "[]"))
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _json_list(value: object) -> list[Mapping[str, object]]:
    decoded = json.loads(str(value or "[]"))
    if not isinstance(decoded, list):
        return []
    return [dict(item) for item in decoded if isinstance(item, Mapping)]


def _json_object(value: object) -> Mapping[str, object]:
    decoded = json.loads(str(value or "{}"))
    return dict(decoded) if isinstance(decoded, Mapping) else {}
