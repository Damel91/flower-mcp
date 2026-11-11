"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

from dataclasses import asdict, replace
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
from flow_of_work_mcp.core.domain.change_control import validate_milestone_id
from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.domain.lifecycle_control import milestone_prerequisite_gaps, roadmap_correspondence
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
                    original = connection.execute(
                        "SELECT json_extract(payload_json, '$.outcome.previous_milestone') AS snapshot FROM bootstrap_events "
                        "WHERE project_id=? AND event_type='guided_revise_draft_milestone' "
                        "AND json_extract(payload_json, '$.outcome.milestone.milestone_id')=? "
                        "AND json_extract(payload_json, '$.outcome.changed')=1 ORDER BY event_id LIMIT 1",
                        (project_id, milestone_id),
                    ).fetchone()
                    if original is not None:
                        snapshot = payload.get("milestone_snapshot") or json.loads(original["snapshot"])
                        return {key: value for key, value in snapshot.items() if key != "revision"}
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
            milestone = self._milestone_row(connection, project_id, milestone_id)
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
                    "milestone_snapshot": milestone,
                },
                occurred_at=occurred_at,
            )
            return milestone

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
            revisions = self._milestone_revisions(connection, project_id)
            values = []
            for row in records:
                value = self._milestone_value(row)
                value["revision"] = revisions.get(value["milestone_id"], 1)
                self._milestone_prerequisites(connection, project_id, value, values)
                values.append(value)
            return values

    @staticmethod
    def _milestone_revisions(connection, project_id):
        rows = connection.execute(
            "SELECT json_extract(payload_json, '$.outcome.milestone.milestone_id') AS milestone_id, "
            "MAX(json_extract(payload_json, '$.outcome.current_revision')) AS revision "
            "FROM bootstrap_events WHERE project_id=? AND event_type='guided_revise_draft_milestone' "
            "AND json_extract(payload_json, '$.outcome.changed')=1 GROUP BY milestone_id", (project_id,),
        )
        return {row["milestone_id"]: row["revision"] for row in rows}

    def revise_milestone_definition(self, project_id, milestone_id, *, expected_revision, replacements):
        """Revise the existing row within the guided operation's write transaction."""

        def reject(code, field, value, rule, resolution, **details):
            raise MilestonePreEffectError(code, rule, field=field, received_value=value,
                                          rule=rule, resolution=resolution, details=details)

        with self._transaction() as connection:
            milestones = {m["milestone_id"]: m for m in self.milestones(project_id)}
            current = milestones[milestone_id]
            if current["revision"] != expected_revision:
                reject("milestone_draft_revision_stale", "expected_revision", expected_revision,
                       "The milestone revision has changed.", "Read the current roadmap before proposing a revision.",
                       current_revision=current["revision"])
            definition = MilestoneDraft(**{key: current[key] for key in MilestoneDraft.__dataclass_fields__})
            revised = replace(definition, **replacements)
            prospective = {**current, **asdict(revised)}
            for field in ("requirement_ids", "prerequisite_requirement_ids", "acceptance_evidence"):
                prospective[field] = list(prospective[field])
            for field in ("requirement_ids", "prerequisite_requirement_ids"):
                for identity in prospective[field]:
                    try:
                        requirement = self._requirement_row(connection, project_id, identity)
                    except RequirementNotFoundError:
                        requirement = None
                    if requirement is None or requirement["lifecycle_status"] == "removed":
                        reject("milestone_requirement_not_current", field, identity,
                               "The requirement must be current in this project.", "Inspect this project's canonical requirements.")
            if any(m["name"] == revised.name and m is not current for m in milestones.values()):
                reject("milestone_name_conflict", "name", revised.name,
                       "The name is already used by another milestone.", "Choose a distinct name or inspect the other milestone.")
            earlier = [m for m in milestones.values() if m["ordinal"] < current["ordinal"]]
            predecessor_ids = revised.entry_policy.get("requires_milestone", [])
            try:
                valid_predecessors = (isinstance(predecessor_ids, list)
                    and len(set(validate_milestone_id(m) for m in predecessor_ids)) == len(predecessor_ids)
                    and set(predecessor_ids) <= milestones.keys() - {milestone_id})
            except (TypeError, ValueError):
                valid_predecessors = False
            if not valid_predecessors:
                reject("milestone_entry_policy_invalid", "entry_policy", predecessor_ids,
                       "requires_milestone must list unique other milestone IDs in this project.",
                       "Use the roadmap's predecessor IDs or an empty list.")
            self._milestone_prerequisites(connection, project_id, prospective, earlier)
            if gaps := milestone_prerequisite_gaps(prospective):
                reject(gaps[0]["code"], "prerequisite_requirement_ids", gaps[0]["requirement_id"],
                       "Each prerequisite needs a current lower-ordinal producer in this project.",
                       "Check earlier milestones and keep realized scope separate from prerequisites.", gaps=gaps)

            changed = definition != revised
            affected = {milestone_id}
            if changed:
                scope_delta = set(current["requirement_ids"]) ^ set(revised.requirement_ids)
                for dependent_id, dependent in milestones.items():
                    if dependent["ordinal"] <= current["ordinal"]:
                        continue
                    if scope_delta.intersection(dependent["prerequisite_requirement_ids"]):
                        new_previous = [prospective if m is current else m for m in milestones.values()
                                        if m["ordinal"] < dependent["ordinal"]]
                        new_dependent = dict(dependent)
                        self._milestone_prerequisites(connection, project_id, new_dependent, new_previous)
                        old_missing = {g["requirement_id"] for g in dependent["prerequisite_mapping_gaps"]}
                        new_missing = {g["requirement_id"] for g in new_dependent["prerequisite_mapping_gaps"]}
                        if orphaned := sorted(new_missing - old_missing):
                            reject("milestone_draft_orphans_prerequisite", "requirement_ids", orphaned,
                                   "The revision would remove the last producer of a downstream prerequisite.",
                                   "Keep the producer or repair the dependent draft before retrying.",
                                   dependent_milestone_id=dependent_id)
                        affected.add(dependent_id)
                while True:
                    policy_dependents = set()
                    for dependent_id, dependent in milestones.items():
                        predecessors = dependent["entry_policy"].get("requires_milestone", [])
                        if isinstance(predecessors, list) and any(isinstance(item, str) and item in affected
                                                                 for item in predecessors):
                            policy_dependents.add(dependent_id)
                    if policy_dependents <= affected:
                        break
                    affected.update(policy_dependents)

            confirmed = self._confirmed_milestone_authority(connection, project_id, milestones)
            protected = sorted(affected & confirmed)
            protected.extend(m for m in sorted(affected - confirmed) if milestones[m]["status"] != "planned")
            if protected:
                reject("milestone_draft_authority_locked", "milestone_id", milestone_id,
                       "The milestone or an affected dependent has confirmed or accepted authority.",
                       "Keep the recorded scope and use ordinary authorized scope change instead.",
                       protected_milestone_ids=protected)
            for change in connection.execute(
                "SELECT change_id, milestone_id, status, requirement_ids_json, "
                "EXISTS(SELECT 1 FROM implementation_packets AS p WHERE p.project_id=c.project_id "
                "AND p.change_id=c.change_id) AS has_packets "
                "FROM change_units AS c WHERE project_id=? AND milestone_id<>'' ORDER BY ordinal", (project_id,),
            ):
                linked = change["milestone_id"]
                if linked not in affected:
                    continue
                scope = prospective["requirement_ids"] if linked == milestone_id else milestones[linked]["requirement_ids"]
                if (change["status"] != "planned" or change["has_packets"]
                        or not set(json.loads(change["requirement_ids_json"])) <= set(scope)):
                    reject("milestone_draft_linked_work_locked", "milestone_id", milestone_id,
                           "Linked work is governed or cannot be proved inert and scope-compatible.",
                           "Inspect the linked change and use the ordinary scope-change route.",
                           change_id=change["change_id"], linked_milestone_id=linked)

            if changed:
                connection.execute(
                    "UPDATE milestones SET name=?, requirement_ids_json=?, dependency_closure_ids_json=?, "
                    "entry_policy_json=?, exit_policy_json=?, risk_disposition=? WHERE project_id=? AND milestone_id=?",
                    (revised.name, self._json(list(revised.requirement_ids)),
                     self._json([*revised.requirement_ids, *revised.prerequisite_requirement_ids]),
                     self._json(dict(revised.entry_policy)), self._json(dict(revised.exit_policy)),
                     revised.risk_disposition, project_id, milestone_id),
                )
                prospective["revision"] += 1
            return current, prospective

    def _confirmed_milestone_authority(self, connection, project_id, milestones):
        confirmed = set()
        context = None
        for row in connection.execute(
            "SELECT payload_json FROM bootstrap_events WHERE project_id=? AND event_type='guided_confirm_roadmap'",
            (project_id,),
        ):
            event = json.loads(row["payload_json"])
            selected = set(event["input"]["mutation"]["milestone_ids"])
            confirmed.update(selected)
            if "authority_milestone_ids" in event:
                confirmed.update(event["authority_milestone_ids"])
                continue
            # Older confirmations retained all draft correspondence, without a
            # projection of which entries governed the selected scope. Protect
            # recorded references with a positive link to that scope.
            scope_requirements = {identity for milestone_id in selected if milestone_id in milestones
                                  for field in ("requirement_ids", "prerequisite_requirement_ids")
                                  for identity in milestones[milestone_id][field]}
            mappings = event.get("guided_state", {}).get("correspondence", {})
            if not mappings:
                continue
            if context is None:
                context = self.list_changes(project_id), self.goal_graph(project_id)["edges"]
            changes, edges = context
            scope_goals = {goal for change in changes if change.get("milestone_id") in selected
                           for packet in change.get("packets", [])
                           for goal in (*packet.get("goal_ids", []), *change.get("goal_ids", []))}
            relevant, _ = roadmap_correspondence(mappings, scope_requirements, selected, scope_goals, edges)
            confirmed.update(milestone for mapping in relevant.values()
                             for milestone in mapping["canonical_references"]["milestone_ids"])
        return confirmed

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
