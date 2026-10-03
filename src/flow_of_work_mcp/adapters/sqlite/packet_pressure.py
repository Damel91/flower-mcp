"""SQLite packet residual-risk pressure persistence."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.change_control import validate_change_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.packet_pressure import (
    ImprovementPressure,
    PacketPressureDraft,
    PacketPressureSource,
    SemanticConfidence,
    validate_pressure_id,
)
from flow_of_work_mcp.core.errors import RequirementConflictError

from flow_of_work_mcp.adapters.sqlite.common import _utc_now


class PacketPressureStoreMixin:
    def derive_packet_pressure(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        profile: str = "balanced",
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        with self._read_connection() as connection:
            packet = self._packet_value(connection, project_id, change_id, packet_id)
            construction = self._latest_construction_for_pressure(
                connection, project_id, change_id, packet_id
            )
        derived = _derive_pressure(packet, construction, profile)
        return self.record_packet_pressure(
            project_id,
            PacketPressureDraft(
                change_id=change_id,
                packet_id=packet_id,
                semantic_confidence=derived["semantic_confidence"],
                improvement_pressure=derived["improvement_pressure"],
                residual_risks=tuple(derived["residual_risks"]),
                challenge_questions=tuple(derived["challenge_questions"]),
                accepted_risk_refs=tuple(derived["accepted_risk_refs"]),
                source=PacketPressureSource.DETERMINISTIC,
                packet_revision=int(packet["spec_revision"]),
                profile=profile,
            ),
            actor=actor,
            request_id=request_id,
        )

    def record_packet_pressure(
        self,
        project_id: str,
        draft: PacketPressureDraft,
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
            packet_revision = draft.packet_revision or int(packet["spec_revision"])
            if request_id:
                replay = self._pressure_event_for_request(
                    connection, project_id, "packet_pressure_recorded", request_id
                )
                if replay is not None:
                    return self._pressure_value(connection, project_id, str(replay["pressure_id"]))
            connection.execute(
                """
                INSERT OR IGNORE INTO packet_pressure_sequences(project_id, next_pressure_ordinal)
                VALUES (?, 1)
                """,
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    """
                    SELECT next_pressure_ordinal FROM packet_pressure_sequences
                    WHERE project_id = ?
                    """,
                    (project_id,),
                ).fetchone()["next_pressure_ordinal"]
            )
            pressure_id = f"PRESS-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO packet_residual_risk_pressure(
                    project_id, pressure_id, ordinal, change_id, packet_id,
                    packet_revision, semantic_confidence, improvement_pressure,
                    residual_risks_json, challenge_questions_json,
                    accepted_risk_refs_json, source, profile, created_at, updated_at,
                    actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    pressure_id,
                    ordinal,
                    draft.change_id,
                    draft.packet_id,
                    packet_revision,
                    draft.semantic_confidence.value,
                    draft.improvement_pressure.value,
                    _json(list(draft.residual_risks)),
                    _json(list(draft.challenge_questions)),
                    _json(list(draft.accepted_risk_refs)),
                    draft.source.value,
                    draft.profile,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            connection.execute(
                "UPDATE packet_pressure_sequences SET next_pressure_ordinal = ? WHERE project_id = ?",
                (ordinal + 1, project_id),
            )
            self._append_pressure_event(
                connection,
                project_id=project_id,
                pressure_id=pressure_id,
                event_type="packet_pressure_recorded",
                actor=actor,
                request_id=request_id,
                payload={
                    "change_id": draft.change_id,
                    "packet_id": draft.packet_id,
                    "semantic_confidence": draft.semantic_confidence.value,
                    "improvement_pressure": draft.improvement_pressure.value,
                },
                occurred_at=occurred_at,
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                draft.change_id,
                draft.packet_id,
                actor=actor,
                occurred_at=occurred_at,
            )
            return self._pressure_value(connection, project_id, pressure_id)

    def packet_pressure_state(self, project_id: str, pressure_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._pressure_value(
                connection,
                validate_project_id(project_id),
                validate_pressure_id(pressure_id),
            )

    def latest_packet_pressure(
        self, project_id: str, change_id: str, packet_id: str
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT pressure_id FROM packet_residual_risk_pressure
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, change_id, packet_id),
            ).fetchone()
            if row is None:
                return None
            return self._pressure_value(connection, project_id, str(row["pressure_id"]))

    def accept_residual_risk(
        self,
        project_id: str,
        pressure_id: str,
        *,
        accepted_risk_ref: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        pressure_id = validate_pressure_id(pressure_id)
        accepted_risk_ref = required_text(accepted_risk_ref, "accepted_risk_ref")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._pressure_row(connection, project_id, pressure_id)
            refs = _json_string_list(row["accepted_risk_refs_json"])
            if accepted_risk_ref in refs:
                return self._pressure_value(connection, project_id, pressure_id)
            refs.append(accepted_risk_ref)
            connection.execute(
                """
                UPDATE packet_residual_risk_pressure
                SET accepted_risk_refs_json = ?, updated_at = ?
                WHERE project_id = ? AND pressure_id = ?
                """,
                (_json(refs), occurred_at, project_id, pressure_id),
            )
            self._append_pressure_event(
                connection,
                project_id=project_id,
                pressure_id=pressure_id,
                event_type="residual_risk_accepted",
                actor=actor,
                request_id=request_id,
                payload={"accepted_risk_ref": accepted_risk_ref},
                occurred_at=occurred_at,
            )
            self._bump_packet_state_revision(
                connection,
                project_id,
                str(row["change_id"]),
                str(row["packet_id"]),
                actor=actor,
                occurred_at=occurred_at,
            )
            return self._pressure_value(connection, project_id, pressure_id)

    def _pressure_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        pressure_id: str,
    ) -> Mapping[str, Any]:
        row = self._pressure_row(connection, project_id, pressure_id)
        return {
            "project_id": str(row["project_id"]),
            "pressure_id": str(row["pressure_id"]),
            "ordinal": int(row["ordinal"]),
            "change_id": str(row["change_id"]),
            "packet_id": str(row["packet_id"]),
            "packet_revision": int(row["packet_revision"]),
            "semantic_confidence": str(row["semantic_confidence"]),
            "improvement_pressure": str(row["improvement_pressure"]),
            "residual_risks": _json_string_list(row["residual_risks_json"]),
            "challenge_questions": _json_string_list(row["challenge_questions_json"]),
            "accepted_risk_refs": _json_string_list(row["accepted_risk_refs_json"]),
            "source": str(row["source"]),
            "profile": str(row["profile"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "actor": str(row["actor"]),
        }

    def _pressure_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        pressure_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_residual_risk_pressure
            WHERE project_id = ? AND pressure_id = ?
            """,
            (project_id, validate_pressure_id(pressure_id)),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown pressure snapshot: {pressure_id}")
        return row

    @staticmethod
    def _latest_construction_for_pressure(
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, object] | None:
        audit = connection.execute(
            """
            SELECT construction_audit_id, state FROM packet_construction_audits
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND state NOT IN ('superseded', 'closed')
            ORDER BY ordinal DESC LIMIT 1
            """,
            (project_id, change_id, packet_id),
        ).fetchone()
        if audit is None:
            return None
        questions = [
            {
                "category": str(row["category"]),
                "required": bool(row["required"]),
                "status": str(row["status"]),
            }
            for row in connection.execute(
                """
                SELECT category, required, status FROM packet_construction_questions
                WHERE project_id = ? AND construction_audit_id = ?
                ORDER BY ordinal
                """,
                (project_id, str(audit["construction_audit_id"])),
            ).fetchall()
        ]
        return {
            "construction_audit_id": str(audit["construction_audit_id"]),
            "state": str(audit["state"]),
            "questions": questions,
        }

    @staticmethod
    def _append_pressure_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        pressure_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO packet_pressure_events(
                project_id, pressure_id, event_type, actor, request_id,
                payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, pressure_id, event_type, actor, request_id, _json(dict(payload)), occurred_at),
        )

    @staticmethod
    def _pressure_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT pressure_id FROM packet_pressure_events
            WHERE project_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, event_type, request_id),
        ).fetchone()


def _derive_pressure(
    packet: Mapping[str, object],
    construction: Mapping[str, object] | None,
    profile: str,
) -> Mapping[str, object]:
    residual_risks: list[str] = []
    challenge_questions: list[str] = []
    if str(packet.get("readiness_state") or "") != "execution_ready":
        residual_risks.append("Packet is not execution-ready; readiness blockers remain authoritative.")
    if not construction:
        residual_risks.append("Packet construction audit has not been recorded.")
        challenge_questions.append("Which construction evidence would make this packet target choice reviewable?")
    else:
        open_required = [
            question
            for question in construction.get("questions", [])
            if question.get("required") and question.get("status") not in {"answered", "waived"}
        ]
        if open_required:
            residual_risks.append("Required construction questions remain unresolved.")
            challenge_questions.append("Which unresolved question would most likely change the packet target?")
        if str(construction.get("state") or "") == "blocked":
            residual_risks.append("Construction audit is blocked by an authority or evidence question.")
    if str(packet.get("target_policy") or "") == "code_targets_required":
        challenge_questions.append("What assumption would make the accepted target selection wrong?")
        challenge_questions.append("What existing symbol or boundary might make a new target unnecessary?")
    if not packet.get("out_of_scope"):
        residual_risks.append("Out-of-scope work is empty; boundary creep may be under-specified.")
    if profile == "strict_local_orchestrator":
        challenge_questions.append("Which cleanup task would prevent this implementation from leaving repository debris?")
    elif profile == "minimal":
        challenge_questions = challenge_questions[:1]
    if not residual_risks:
        residual_risks.append("No deterministic residual risk was detected; semantic uncertainty still remains.")
    if not challenge_questions:
        challenge_questions.append("What evidence would make you change this implementation plan?")
    confidence = (
        SemanticConfidence.LOW.value
        if any("not execution-ready" in risk or "blocked" in risk for risk in residual_risks)
        else SemanticConfidence.MEDIUM.value
        if residual_risks
        else SemanticConfidence.HIGH.value
    )
    pressure = (
        ImprovementPressure.HIGH.value
        if profile == "strict_local_orchestrator" or confidence == SemanticConfidence.LOW.value
        else ImprovementPressure.LOW.value
        if profile == "minimal" and confidence == SemanticConfidence.HIGH.value
        else ImprovementPressure.NORMAL.value
    )
    return {
        "semantic_confidence": confidence,
        "improvement_pressure": pressure,
        "residual_risks": _unique(residual_risks),
        "challenge_questions": _unique(challenge_questions),
        "accepted_risk_refs": [],
    }


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value or "[]"))
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)
