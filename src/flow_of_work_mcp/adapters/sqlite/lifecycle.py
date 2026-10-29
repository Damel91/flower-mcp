"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

from dataclasses import replace
import json
import sqlite3
from typing import Mapping

from flow_of_work_mcp.core.domain import (
    MilestoneDraft,
    PhaseAudit,
    PhaseAuditScope,
    PhaseChangeType,
    PhaseRequirementDelta,
    PhaseRequirementSnapshot,
    ValidationAuditRecord,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_project_id,
)
from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.domain.lifecycle_control import milestone_prerequisite_gaps
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    MilestonePreEffectError,
    ProjectNotFoundError,
    RequirementConflictError,
    RequirementNotFoundError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class LifecycleStoreMixin:
    def promote_milestone(
        self,
        project_id: str,
        draft: MilestoneDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Freeze a bounded production milestone without changing requirements."""

        def reject(code, field, value, rule, resolution):
            raise MilestonePreEffectError(code, rule, field=field, received_value=value,
                                         rule=rule, resolution=resolution)

        try:
            if not isinstance(project_id, str):
                raise ValueError()
            project_id = validate_project_id(project_id)
        except ValueError:
            reject("milestone_project_invalid", "project_id", project_id,
                   "project_id must be a canonical project identity.", "Inspect the current project and use its exact identity.")
        if not isinstance(actor, str) or not actor.strip():
            reject("milestone_actor_invalid", "actor", actor, "actor must be nonempty text.", "Supply the original recording actor.")
        actor = actor.strip()
        if not isinstance(request_id, str):
            reject("milestone_request_invalid", "request_id", request_id,
                   "request_id must be text.", "Use the original request identity when replaying the same plan.")
        original_fingerprint = fingerprint({"actor": actor, "name": draft.name,
            "requirement_ids": draft.requirement_ids,
            "prerequisite_requirement_ids": draft.prerequisite_requirement_ids,
            "entry_policy": draft.entry_policy, "exit_policy": draft.exit_policy,
            "risk_disposition": draft.risk_disposition, "acceptance_evidence": draft.acceptance_evidence})
        occurred_at = _utc_now()
        with self._transaction() as connection:
            try:
                self._ensure_project(connection, project_id)
            except ProjectNotFoundError:
                reject("milestone_project_missing", "project_id", project_id,
                       "The milestone must belong to an existing project.", "Inspect or explicitly create the intended lifecycle project first.")
            if request_id:
                existing = connection.execute(
                    """
                    SELECT milestone_id FROM milestones
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (project_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    milestone_id = str(existing["milestone_id"])
                    events = connection.execute(
                        "SELECT payload_json FROM requirement_events WHERE project_id=? "
                        "AND event_type='milestone_promoted' AND request_id=? ORDER BY event_id",
                        (project_id, request_id)).fetchall()
                    payload = json.loads(events[0]["payload_json"]) if len(events) == 1 else {}
                    if payload.get("milestone_id") != milestone_id or not payload.get("original_request_fingerprint"):
                        reject("milestone_request_replay_unverifiable", "request_id", request_id,
                               "Historical promotion has no immutable original-request fingerprint.",
                               "Inspect the existing milestone; do not backfill proof or blindly retry the mutation.")
                    if payload["original_request_fingerprint"] != original_fingerprint:
                        reject("milestone_request_conflict", "request_id", request_id,
                               "A request identity must retain every original normalized planning input and actor.",
                               "Inspect the milestone recorded for this request; use a new request only for an explicitly intended new plan.")
                    return self._milestone_row(connection, project_id, milestone_id)
            for field, identities in (("requirement_ids", draft.requirement_ids),
                                      ("prerequisite_requirement_ids", draft.prerequisite_requirement_ids)):
                for requirement_id in identities:
                    try:
                        self._requirement_row(connection, project_id, requirement_id)
                    except RequirementNotFoundError:
                        reject("milestone_requirement_missing", field, requirement_id,
                               "Every requirement must exist in this project.",
                               "Inspect this project's requirements; a requirement in another project is not authority here.")
            sequence = connection.execute(
                "SELECT next_milestone_ordinal FROM lifecycle_sequences WHERE project_id=?", (project_id,)).fetchone()
            ordinal = int(sequence["next_milestone_ordinal"]) if sequence is not None else 1
            previous = connection.execute(
                "SELECT milestone_id, requirement_ids_json FROM milestones WHERE project_id=? AND ordinal<? ORDER BY ordinal",
                (project_id, ordinal)).fetchall()
            previous_requirements = {identity for row in previous for identity in json.loads(row["requirement_ids_json"])}
            for requirement_id in draft.prerequisite_requirement_ids:
                if requirement_id not in previous_requirements:
                    reject("milestone_prerequisite_unassigned", "prerequisite_requirement_ids", requirement_id,
                           "A prerequisite must be realized by at least one already registered lower-ordinal milestone in this project.",
                           "Inspect previous milestones. Put current work in requirement_ids; use [] when there is no predecessor.")
            if connection.execute("SELECT 1 FROM milestones WHERE project_id=? AND name=?", (project_id, draft.name)).fetchone():
                reject("milestone_name_conflict", "name", draft.name,
                       "Milestone names must be unique within the project.", "Inspect the existing milestone or choose an explicit new plan name.")
            # All proof-bearing rejections above precede the operation's first write.
            connection.execute("INSERT OR IGNORE INTO lifecycle_sequences(project_id, next_milestone_ordinal) VALUES (?, 1)",
                               (project_id,))
            milestone_id = f"MILE-{ordinal:06d}"
            try:
                connection.execute(
                    """
                    INSERT INTO milestones(
                        project_id, milestone_id, ordinal, name, requirement_ids_json,
                        dependency_closure_ids_json, entry_policy_json, exit_policy_json,
                        risk_disposition, acceptance_evidence_json, status, created_at, created_by,
                        request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
                    """,
                    (
                        project_id,
                        milestone_id,
                        ordinal,
                        draft.name,
                        json.dumps(list(draft.requirement_ids), separators=(",", ":")),
                        json.dumps([*draft.requirement_ids, *draft.prerequisite_requirement_ids], separators=(",", ":")),
                        json.dumps(dict(draft.entry_policy), sort_keys=True, separators=(",", ":")),
                        json.dumps(dict(draft.exit_policy), sort_keys=True, separators=(",", ":")),
                        draft.risk_disposition,
                        json.dumps(list(draft.acceptance_evidence), separators=(",", ":")),
                        occurred_at,
                        actor,
                        str(request_id or ""),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RequirementConflictError(
                    f"milestone name already exists in project: {draft.name}"
                ) from exc
            connection.execute(
                """
                UPDATE lifecycle_sequences
                SET next_milestone_ordinal = ?
                WHERE project_id = ?
                """,
                (ordinal + 1, project_id),
            )
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="milestone_promoted",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "milestone_id": milestone_id,
                    "requirement_count": len(draft.requirement_ids),
                    "prerequisite_requirement_count": len(draft.prerequisite_requirement_ids),
                    "risk_disposition": draft.risk_disposition,
                    "original_request_fingerprint": original_fingerprint,
                },
                occurred_at=occurred_at,
            )
            return self._milestone_row(connection, project_id, milestone_id)

    def milestones(self, project_id: str) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            records = connection.execute(
                """
                SELECT milestone_id, ordinal, name, requirement_ids_json,
                       dependency_closure_ids_json, entry_policy_json, exit_policy_json,
                       risk_disposition, acceptance_evidence_json, status, created_at, created_by,
                       request_id
                FROM milestones
                WHERE project_id = ?
                ORDER BY ordinal
                """,
                (project_id,),
            ).fetchall()
            values = []
            for row in records:
                value = self._milestone_value(row)
                self._milestone_prerequisites(connection, project_id, value, values)
                values.append(value)
            return values

    def accept_milestone(
        self,
        project_id: str,
        milestone_id: str,
        *,
        acceptance_evidence: tuple[str, ...],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        actor = required_text(actor, "actor")
        milestone_id = required_text(milestone_id, "milestone_id")
        evidence = tuple(required_text(item, "acceptance_evidence") for item in acceptance_evidence)
        if not evidence:
            raise ValueError("accept_milestone requires acceptance evidence")
        if len(set(evidence)) != len(evidence):
            raise ValueError("milestone acceptance evidence must be unique")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            existing_request = self._mutation_event_for_request(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="milestone_accepted",
                request_id=request_id,
            )
            if existing_request is not None:
                return self._milestone_row(connection, project_id, milestone_id)
            milestone = self._milestone_row(connection, project_id, milestone_id)
            prerequisite_gaps = milestone_prerequisite_gaps(milestone)
            if prerequisite_gaps:
                raise ChangeControlBlockedError(prerequisite_gaps[0]['code'],
                    details={"milestone_id": milestone_id, "gaps": prerequisite_gaps})
            existing_evidence = tuple(str(item) for item in milestone["acceptance_evidence"])
            merged_evidence = tuple(dict.fromkeys((*existing_evidence, *evidence)))
            connection.execute(
                """
                UPDATE milestones
                SET acceptance_evidence_json = ?, status = ?
                WHERE project_id = ? AND milestone_id = ?
                """,
                (
                    json.dumps(list(merged_evidence), separators=(",", ":")),
                    "accepted",
                    project_id,
                    milestone_id,
                ),
            )
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="milestone_accepted",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "milestone_id": milestone_id,
                    "acceptance_evidence": list(evidence),
                    "acceptance_evidence_count": len(merged_evidence),
                },
                occurred_at=occurred_at,
            )
            return self._milestone_row(connection, project_id, milestone_id)

    def record_phase_audit(
        self,
        audit: PhaseAudit,
        *,
        actor: str,
        request_id: str = "",
    ) -> PhaseAudit:
        if audit.audit_id is not None:
            raise ValueError("only a new phase audit can be recorded")
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, audit.project_id)
            if request_id:
                existing = connection.execute(
                    """
                    SELECT phase_audit_id FROM phase_audits
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (audit.project_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    stored = self._phase_audit_value(connection, int(existing["phase_audit_id"]))
                    if (audit.repository_review is not None or stored.get("repository_review") is not None) and (
                        stored.get("request_fingerprint") != audit.request_fingerprint
                        or stored.get("created_by") != actor
                        or stored.get("repository_review") != audit.repository_review
                    ):
                        raise RequirementConflictError("phase_audit_request_conflict")
                    return self._phase_audit_to_domain(
                        stored
                    )
            if audit.previous_audit_id is not None:
                previous = connection.execute(
                    """
                    SELECT project_id, scope_id FROM phase_audits WHERE phase_audit_id = ?
                    """,
                    (audit.previous_audit_id,),
                ).fetchone()
                if previous is None or previous["project_id"] != audit.project_id:
                    raise ValueError("previous phase audit does not belong to project")
                if previous["scope_id"] != audit.scope.scope_id:
                    raise ValueError("previous phase audit does not match scope")
            for snapshot in audit.snapshots:
                self._requirement_row(connection, audit.project_id, snapshot.requirement_id)
            cursor = connection.execute(
                """
                INSERT INTO phase_audits(
                    project_id, scope_id, scope_requirement_ids_json, previous_phase_audit_id,
                    policy_version, created_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.project_id,
                    audit.scope.scope_id,
                    json.dumps(list(audit.scope.requirement_ids), separators=(",", ":")),
                    audit.previous_audit_id,
                    audit.policy_version,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            audit_id = int(cursor.lastrowid)
            for snapshot in audit.snapshots:
                connection.execute(
                    """
                    INSERT INTO phase_audit_requirements(
                        phase_audit_id, requirement_id, revision, lifecycle_status,
                        verification_json, evidence_ids_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        snapshot.requirement_id,
                        snapshot.revision,
                        snapshot.lifecycle_status,
                        json.dumps(dict(snapshot.verification), sort_keys=True, separators=(",", ":")),
                        json.dumps(list(snapshot.evidence_ids), separators=(",", ":")),
                    ),
                )
            for delta in audit.deltas:
                connection.execute(
                    """
                    INSERT INTO phase_audit_deltas(
                        phase_audit_id, requirement_id, change_types_json, evidence_added_ids_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        delta.requirement_id,
                        json.dumps([item.value for item in delta.change_types], separators=(",", ":")),
                        json.dumps(list(delta.evidence_added_ids), separators=(",", ":")),
                    ),
                )
            self._append_event(
                connection,
                project_id=audit.project_id,
                requirement_id=None,
                event_type="phase_audit_recorded",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "phase_audit_id": audit_id,
                    "scope_id": audit.scope.scope_id,
                    "previous_phase_audit_id": audit.previous_audit_id,
                    "snapshot_count": len(audit.snapshots),
                    "delta_count": len(audit.deltas),
                    "policy_version": audit.policy_version,
                    **({"repository_review": dict(audit.repository_review),
                        "request_fingerprint": audit.request_fingerprint}
                       if audit.repository_review is not None else {}),
                },
                occurred_at=occurred_at,
            )
        return replace(audit, audit_id=audit_id)

    def latest_phase_audit(
        self, project_id: str, scope_id: str
    ) -> Mapping[str, object] | None:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                """
                SELECT phase_audit_id FROM phase_audits
                WHERE project_id = ? AND scope_id = ?
                ORDER BY phase_audit_id DESC
                LIMIT 1
                """,
                (project_id, required_text(scope_id, "scope_id")),
            ).fetchone()
            return None if row is None else self._phase_audit_value(connection, int(row["phase_audit_id"]))

    def phase_audits(self, project_id: str, scope_id: str) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            records = connection.execute(
                """
                SELECT phase_audit_id FROM phase_audits
                WHERE project_id = ? AND scope_id = ?
                ORDER BY phase_audit_id
                """,
                (project_id, required_text(scope_id, "scope_id")),
            ).fetchall()
            reviews = self._phase_audit_review_payloads(connection, project_id)
            return [self._phase_audit_value(connection, int(row["phase_audit_id"]), reviews) for row in records]

    def all_phase_audits(self, project_id: str) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            records = connection.execute(
                """
                SELECT phase_audit_id FROM phase_audits
                WHERE project_id = ?
                ORDER BY phase_audit_id
                """,
                (project_id,),
            ).fetchall()
            reviews = self._phase_audit_review_payloads(connection, project_id)
            return [self._phase_audit_value(connection, int(row["phase_audit_id"]), reviews) for row in records]

    def phase_audit_request_replay(self, project_id, request_id, request_fingerprint):
        """Return a reserved exact job; never reuse an unrelated/legacy request."""
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            rows = connection.execute(
                "SELECT payload_json FROM requirement_events WHERE project_id=? "
                "AND event_type='phase_audit_requested' AND request_id=? ORDER BY event_id",
                (project_id, request_id)).fetchall()
            if rows:
                payload = json.loads(rows[0]["payload_json"])
                if len(rows) != 1 or payload.get("request_fingerprint") != request_fingerprint:
                    raise RequirementConflictError("phase_audit_request_conflict")
                return self._job_row(connection, project_id, payload["job_id"])
            if connection.execute("SELECT 1 FROM jobs WHERE project_id=? AND request_id=?",
                                  (project_id, request_id)).fetchone() is not None:
                raise RequirementConflictError("phase_audit_request_conflict")
            return None

    def reserve_phase_audit_request(self, project_id, *, request_id, actor,
                                   request_fingerprint, job_id, repository_review):
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            self._append_event(connection, project_id=project_id, requirement_id=None,
                event_type="phase_audit_requested", actor=actor, request_id=request_id,
                payload={"request_fingerprint": request_fingerprint, "job_id": job_id,
                         "change_id": repository_review["change_id"],
                         "packet_id": repository_review["packet_id"]}, occurred_at=_utc_now())

    def phase_audit_request_context(self, project_id, request_id):
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute("SELECT payload_json,actor,request_id FROM requirement_events WHERE project_id=? "
                "AND event_type='phase_audit_requested' AND request_id=? ORDER BY event_id LIMIT 1",
                (project_id, request_id)).fetchone()
            return {**json.loads(row["payload_json"]), "actor": row["actor"],
                    "request_id": row["request_id"]} if row is not None else None

    def phase_audit_record_replay(self, project_id, *, request_id, actor, request_fingerprint):
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute("SELECT phase_audit_id,created_by FROM phase_audits "
                "WHERE project_id=? AND request_id=? ORDER BY phase_audit_id LIMIT 1",
                (project_id, request_id)).fetchone()
            if row is None:
                return None
            value = self._phase_audit_value(connection, int(row["phase_audit_id"]))
            if value.get("request_fingerprint") != request_fingerprint or row["created_by"] != actor:
                raise RequirementConflictError("phase_audit_request_conflict")
            return self._phase_audit_to_domain(value)

    def record_validation_audit(
        self,
        project_id: str,
        audit: ValidationAuditRecord,
        *,
        actor: str,
        request_id: str = "",
    ) -> ValidationAuditRecord:
        if audit.audit_id is not None:
            raise ValueError("only a new validation audit can be recorded")
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            if request_id:
                existing = connection.execute(
                    """
                    SELECT validation_audit_id FROM validation_audits
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (project_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    return replace(audit, audit_id=int(existing["validation_audit_id"]))
            cursor = connection.execute(
                """
                INSERT INTO validation_audits(
                    project_id, source_ref, disposition, finding_codes_json, profile_id,
                    created_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    audit.source_ref,
                    audit.disposition.value,
                    json.dumps(list(audit.finding_codes), separators=(",", ":")),
                    audit.profile_id,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            audit_id = int(cursor.lastrowid)
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="validation_audit_recorded",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "validation_audit_id": audit_id,
                    "disposition": audit.disposition.value,
                    "finding_count": len(audit.finding_codes),
                    "profile_id": audit.profile_id,
                },
                occurred_at=occurred_at,
            )
        return replace(audit, audit_id=audit_id)

    def validation_audits(self, project_id: str) -> list[Mapping[str, object]]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            records = connection.execute(
                """
                SELECT validation_audit_id, source_ref, disposition, finding_codes_json,
                       profile_id, created_at, created_by, request_id
                FROM validation_audits
                WHERE project_id = ?
                ORDER BY validation_audit_id
                """,
                (project_id,),
            ).fetchall()
            values = []
            for row in records:
                value: dict[str, object] = dict(row)
                value["finding_codes"] = json.loads(value.pop("finding_codes_json"))
                values.append(value)
            return values

    def ledger_version(self, project_id: str) -> int:
        """Return the latest durable project event identifier before generation."""

        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            row = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) AS ledger_version FROM requirement_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return int(row["ledger_version"])

    def _milestone_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        milestone_id: str,
    ) -> Mapping[str, object]:
        row = connection.execute(
            """
            SELECT milestone_id, ordinal, name, requirement_ids_json,
                   dependency_closure_ids_json, entry_policy_json, exit_policy_json,
                   risk_disposition, acceptance_evidence_json, status, created_at, created_by,
                   request_id
            FROM milestones
            WHERE project_id = ? AND milestone_id = ?
            """,
            (project_id, milestone_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown milestone in project {project_id}: {milestone_id}")
        value = self._milestone_value(row)
        previous = connection.execute(
            "SELECT milestone_id, requirement_ids_json FROM milestones WHERE project_id=? AND ordinal<? ORDER BY ordinal",
            (project_id, value["ordinal"])).fetchall()
        self._milestone_prerequisites(connection, project_id, value, [{"milestone_id": prior["milestone_id"],
            "requirement_ids": json.loads(prior["requirement_ids_json"])} for prior in previous])
        return value

    def _milestone_prerequisites(self, connection: sqlite3.Connection, project_id: str, value: dict, previous: list) -> None:
        producers = {identity: [str(prior["milestone_id"]) for prior in previous
                               if identity in prior["requirement_ids"]]
                     for identity in value["prerequisite_requirement_ids"]}
        value["prerequisite_producers"] = producers
        value["prerequisite_mapping_gaps"] = [
            {"code": "milestone_prerequisite_owner_missing", "milestone_id": value["milestone_id"],
             "requirement_id": identity,
             "resolution": "Create a correctly defined milestone, explicitly relink affected changes, reconfirm the roadmap and re-export work; preserve this historical milestone."}
            for identity, candidates in producers.items() if not candidates]
        authority_gaps = []
        for identity in value['prerequisite_requirement_ids']:
            try:
                requirement = self._requirement_row(connection, project_id, identity)
            except RequirementNotFoundError:
                requirement = None
            if requirement is None or requirement['lifecycle_status'] == 'removed':
                authority_gaps.append({
                    'code': 'milestone_prerequisite_requirement_missing' if requirement is None
                            else 'milestone_prerequisite_requirement_retired',
                    'milestone_id': value['milestone_id'], 'requirement_id': identity,
                    'provenance': 'canonical_ledger_current_state',
                    'requirement_revision': None if requirement is None else requirement['current_revision'],
                    'resolution': 'Inspect current requirement intent and the governing milestone; correct scope through ordinary authority, reconfirm and re-export affected work. Do not silently reinstate retired requirements.'})
        value['prerequisite_authority_gaps'] = authority_gaps

    @staticmethod
    def _milestone_value(row: sqlite3.Row) -> Mapping[str, object]:
        value: dict[str, object] = dict(row)
        value["requirement_ids"] = json.loads(value.pop("requirement_ids_json"))
        # Schema55 retains its physical inclusive representation; it is not a
        # second public input or an independently mutable prerequisite store.
        inclusive = json.loads(value.pop("dependency_closure_ids_json"))
        value["prerequisite_requirement_ids"] = [identity for identity in inclusive if identity not in value["requirement_ids"]]
        value["entry_policy"] = json.loads(value.pop("entry_policy_json"))
        value["exit_policy"] = json.loads(value.pop("exit_policy_json"))
        value["acceptance_evidence"] = json.loads(value.pop("acceptance_evidence_json"))
        return value

    @staticmethod
    def _phase_audit_review_payloads(connection, project_id):
        result = {}
        for row in connection.execute("SELECT payload_json FROM requirement_events WHERE project_id=? "
            "AND event_type='phase_audit_recorded' ORDER BY event_id", (project_id,)):
            payload = json.loads(row["payload_json"])
            if payload.get("repository_review") is not None:
                result[int(payload["phase_audit_id"])] = payload
        return result

    @staticmethod
    def _phase_audit_value(
        connection: sqlite3.Connection,
        phase_audit_id: int,
        review_payloads=None,
    ) -> Mapping[str, object]:
        row = connection.execute(
            """
            SELECT phase_audit_id, project_id, scope_id, scope_requirement_ids_json,
                   previous_phase_audit_id, policy_version, created_at, created_by, request_id
            FROM phase_audits
            WHERE phase_audit_id = ?
            """,
            (phase_audit_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown phase audit: {phase_audit_id}")
        value: dict[str, object] = dict(row)
        value["scope_requirement_ids"] = json.loads(value.pop("scope_requirement_ids_json"))
        snapshots = []
        for snapshot_row in connection.execute(
            """
            SELECT requirement_id, revision, lifecycle_status, verification_json, evidence_ids_json
            FROM phase_audit_requirements
            WHERE phase_audit_id = ?
            ORDER BY requirement_id
            """,
            (phase_audit_id,),
        ).fetchall():
            snapshot = dict(snapshot_row)
            snapshot["verification"] = json.loads(snapshot.pop("verification_json"))
            snapshot["evidence_ids"] = json.loads(snapshot.pop("evidence_ids_json"))
            snapshots.append(snapshot)
        deltas = []
        for delta_row in connection.execute(
            """
            SELECT requirement_id, change_types_json, evidence_added_ids_json
            FROM phase_audit_deltas
            WHERE phase_audit_id = ?
            ORDER BY requirement_id
            """,
            (phase_audit_id,),
        ).fetchall():
            delta = dict(delta_row)
            delta["change_types"] = json.loads(delta.pop("change_types_json"))
            delta["evidence_added_ids"] = json.loads(delta.pop("evidence_added_ids_json"))
            deltas.append(delta)
        value["snapshots"] = snapshots
        value["deltas"] = deltas
        if review_payloads is None:
            review_payloads = LifecycleStoreMixin._phase_audit_review_payloads(connection, value["project_id"])
        payload = review_payloads.get(phase_audit_id, {})
        value["repository_review"] = payload.get("repository_review")
        value["request_fingerprint"] = payload.get("request_fingerprint", "")
        return value

    @staticmethod
    def _phase_audit_to_domain(value: Mapping[str, object]) -> PhaseAudit:
        snapshots = tuple(
            PhaseRequirementSnapshot(
                requirement_id=str(item["requirement_id"]),
                revision=int(item["revision"]),
                lifecycle_status=str(item["lifecycle_status"]),
                verification=dict(item["verification"]),
                evidence_ids=tuple(int(evidence_id) for evidence_id in item["evidence_ids"]),
            )
            for item in value["snapshots"]
        )
        deltas = tuple(
            PhaseRequirementDelta(
                requirement_id=str(item["requirement_id"]),
                change_types=tuple(PhaseChangeType(change) for change in item["change_types"]),
                evidence_added_ids=tuple(
                    int(evidence_id) for evidence_id in item["evidence_added_ids"]
                ),
            )
            for item in value["deltas"]
        )
        return PhaseAudit(
            project_id=str(value["project_id"]),
            scope=PhaseAuditScope(
                str(value["scope_id"]),
                tuple(str(item) for item in value["scope_requirement_ids"]),
            ),
            previous_audit_id=(
                None
                if value["previous_phase_audit_id"] is None
                else int(value["previous_phase_audit_id"])
            ),
            snapshots=snapshots,
            deltas=deltas,
            policy_version=str(value["policy_version"]),
            audit_id=int(value["phase_audit_id"]),
            repository_review=value.get("repository_review"),
            request_fingerprint=str(value.get("request_fingerprint", "")),
        )

    def _ledger_version(self, connection: sqlite3.Connection, project_id: str) -> int:
        totals = []
        for table in ("requirement_events", "change_events", "assurance_events", "run_events"):
            row = connection.execute(
                f"SELECT COALESCE(MAX(event_id), 0) AS version FROM {table} WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            totals.append(int(row["version"]))
        return sum(totals)
