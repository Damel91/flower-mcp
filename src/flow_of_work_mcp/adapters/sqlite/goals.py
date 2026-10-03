"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

from dataclasses import replace
import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    GoalNodeType,
    GroundingAudit,
)
from flow_of_work_mcp.core.domain.identifiers import (
    normalize_requirement_statement,
    required_text,
)
from flow_of_work_mcp.core.domain.srs import SourceAnchor
from flow_of_work_mcp.core.errors import (
    GoalNodeNotFoundError,
    RequirementConflictError,
)

from flow_of_work_mcp.adapters.sqlite.common import _GOAL_NODE_ID_RE, _utc_now



class GoalStoreMixin:
    def create_goal_node(
        self,
        project_id: str,
        *,
        node_type: GoalNodeType,
        title: str,
        payload: Mapping[str, Any],
        source_anchor: SourceAnchor | None,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        try:
            node_type = GoalNodeType(node_type)
        except ValueError as exc:
            raise ValueError(f"unsupported goal node type: {node_type}") from exc
        title = required_text(title, "title")
        actor = required_text(actor, "actor")
        payload_json = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        anchor_json = self._anchor_to_json(source_anchor)
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            connection.execute(
                """
                INSERT OR IGNORE INTO goal_sequences(
                    project_id, next_goal_ordinal, next_candidate_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            ordinal = connection.execute(
                "SELECT next_goal_ordinal FROM goal_sequences WHERE project_id = ?",
                (project_id,),
            ).fetchone()["next_goal_ordinal"]
            goal_node_id = f"GOAL-{int(ordinal):06d}"
            connection.execute(
                "UPDATE goal_sequences SET next_goal_ordinal = ? WHERE project_id = ?",
                (int(ordinal) + 1, project_id),
            )
            connection.execute(
                """
                INSERT INTO goal_nodes(
                    project_id, goal_node_id, node_type, title, payload_json,
                    source_anchor_json, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    goal_node_id,
                    node_type.value,
                    title,
                    payload_json,
                    anchor_json,
                    occurred_at,
                    actor,
                ),
            )
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="goal_node_created",
                actor=actor,
                request_id=str(request_id or ""),
                payload={"goal_node_id": goal_node_id, "node_type": node_type.value},
                occurred_at=occurred_at,
            )
            return self._goal_node_row(connection, project_id, goal_node_id)

    def link_goal_nodes(
        self,
        project_id: str,
        *,
        source_goal_id: str,
        target_goal_id: str,
        relation: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        source_goal_id = self._validate_goal_node_id(source_goal_id)
        target_goal_id = self._validate_goal_node_id(target_goal_id)
        relation = required_text(relation, "relation")
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._goal_node_row(connection, project_id, source_goal_id)
            self._goal_node_row(connection, project_id, target_goal_id)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO goal_edges(
                        project_id, source_goal_id, target_goal_id, relation,
                        created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, source_goal_id, target_goal_id, relation, occurred_at, actor),
                )
            except sqlite3.IntegrityError as exc:
                raise RequirementConflictError("duplicate goal graph edge") from exc
            edge_id = int(cursor.lastrowid)
            self._append_event(
                connection,
                project_id=project_id,
                requirement_id=None,
                event_type="goal_edge_created",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "edge_id": edge_id,
                    "source_goal_id": source_goal_id,
                    "target_goal_id": target_goal_id,
                    "relation": relation,
                },
                occurred_at=occurred_at,
            )
            return {
                "edge_id": edge_id,
                "project_id": project_id,
                "source_goal_id": source_goal_id,
                "target_goal_id": target_goal_id,
                "relation": relation,
                "created_at": occurred_at,
            }

    def derive_requirement_candidates(
        self,
        project_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> list[Mapping[str, Any]]:
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        created: list[Mapping[str, Any]] = []
        with self._transaction() as connection:
            self._ensure_project(connection, project_id)
            connection.execute(
                """
                INSERT OR IGNORE INTO goal_sequences(
                    project_id, next_goal_ordinal, next_candidate_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            expectations = connection.execute(
                """
                SELECT goal_node_id, payload_json, source_anchor_json
                FROM goal_nodes
                WHERE project_id = ? AND node_type = ?
                ORDER BY goal_node_id
                """,
                (project_id, GoalNodeType.BEHAVIORAL_EXPECTATION.value),
            ).fetchall()
            for expectation in expectations:
                payload = json.loads(expectation["payload_json"])
                statement = required_text(str(payload.get("statement") or ""), "statement")
                normalized_statement = normalize_requirement_statement(statement)
                existing = connection.execute(
                    """
                    SELECT candidate_id FROM goal_requirement_candidates
                    WHERE project_id = ? AND source_goal_id = ? AND normalized_statement = ?
                    """,
                    (project_id, expectation["goal_node_id"], normalized_statement),
                ).fetchone()
                if existing is not None:
                    continue
                sequence = connection.execute(
                    "SELECT next_candidate_ordinal FROM goal_sequences WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                candidate_id = f"CAND-{int(sequence['next_candidate_ordinal']):06d}"
                connection.execute(
                    "UPDATE goal_sequences SET next_candidate_ordinal = ? WHERE project_id = ?",
                    (int(sequence["next_candidate_ordinal"]) + 1, project_id),
                )
                connection.execute(
                    """
                    INSERT INTO goal_requirement_candidates(
                        project_id, candidate_id, source_goal_id, category, statement,
                        normalized_statement, source_anchor_json, status, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
                    """,
                    (
                        project_id,
                        candidate_id,
                        expectation["goal_node_id"],
                        payload["category"],
                        statement,
                        normalized_statement,
                        expectation["source_anchor_json"],
                        occurred_at,
                        actor,
                    ),
                )
                item = {
                    "candidate_id": candidate_id,
                    "project_id": project_id,
                    "source_goal_id": expectation["goal_node_id"],
                    "category": payload["category"],
                    "statement": statement,
                    "status": "proposed",
                    "source_anchor": self._anchor_from_json(expectation["source_anchor_json"]),
                    "created_at": occurred_at,
                }
                created.append(item)
                self._append_event(
                    connection,
                    project_id=project_id,
                    requirement_id=None,
                    event_type="goal_requirement_candidate_created",
                    actor=actor,
                    request_id=str(request_id or ""),
                    payload={"candidate_id": candidate_id, "source_goal_id": expectation["goal_node_id"]},
                    occurred_at=occurred_at,
                )
        return created

    def goal_graph(self, project_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            nodes = []
            for row in connection.execute(
                """
                SELECT goal_node_id, node_type, title, payload_json, source_anchor_json,
                       created_at, created_by
                FROM goal_nodes WHERE project_id = ? ORDER BY goal_node_id
                """,
                (project_id,),
            ).fetchall():
                value = dict(row)
                value["payload"] = json.loads(value.pop("payload_json"))
                value["source_anchor"] = self._anchor_from_json(value.pop("source_anchor_json"))
                nodes.append(value)
            edges = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT project_id, edge_id, source_goal_id, target_goal_id, relation, created_at, created_by
                    FROM goal_edges WHERE project_id = ? ORDER BY edge_id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            candidates = []
            for row in connection.execute(
                """
                SELECT candidate_id, source_goal_id, category, statement, status,
                       source_anchor_json, created_at, created_by
                FROM goal_requirement_candidates WHERE project_id = ? ORDER BY candidate_id
                """,
                (project_id,),
            ).fetchall():
                value = dict(row)
                value["source_anchor"] = self._anchor_from_json(value.pop("source_anchor_json"))
                candidates.append(value)
            return {
                "project_id": project_id,
                "nodes": nodes,
                "edges": edges,
                "requirement_candidates": candidates,
            }

    def record_grounding_audit(
        self,
        audit: GroundingAudit,
        *,
        actor: str,
        request_id: str = "",
    ) -> GroundingAudit:
        """Append one reconciliation audit without changing goals or requirements."""

        if audit.audit_id is not None:
            raise ValueError("only a new grounding audit can be recorded")
        actor = required_text(actor, "actor")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, audit.project_id)
            for goal_node_id in audit.selected_goal_ids:
                self._goal_node_row(connection, audit.project_id, goal_node_id)
            cursor = connection.execute(
                """
                INSERT INTO grounding_audits(
                    project_id, provider_id, source_revision, selected_goal_ids_json,
                    disposition, model, terminal_reason, prompt_version, input_truncated,
                    diagnostics_json, created_at, created_by, request_id,
                    evidence_authority, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.project_id,
                    audit.provider_id,
                    audit.source_revision,
                    json.dumps(list(audit.selected_goal_ids), separators=(",", ":")),
                    audit.disposition.value,
                    audit.model,
                    audit.terminal_reason,
                    audit.prompt_version,
                    int(audit.input_truncated),
                    json.dumps(list(audit.diagnostics), separators=(",", ":")),
                    occurred_at,
                    actor,
                    str(request_id or ""),
                    audit.evidence_authority,
                    json.dumps(dict(audit.provenance), sort_keys=True, separators=(",", ":"), allow_nan=False),
                ),
            )
            audit_id = int(cursor.lastrowid)
            for anchor in audit.anchors:
                connection.execute(
                    """
                    INSERT INTO grounding_audit_anchors(
                        audit_id, anchor_id, kind, label, summary, source_path,
                        evidence_ids_json, dependency_anchor_ids_json,
                        test_evidence_ids_json, metadata_json, source_excerpt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        anchor.anchor_id,
                        anchor.kind,
                        anchor.label,
                        anchor.summary,
                        anchor.source_path,
                        json.dumps(list(anchor.evidence_ids), separators=(",", ":")),
                        json.dumps(list(anchor.dependency_anchor_ids), separators=(",", ":")),
                        json.dumps(list(anchor.test_evidence_ids), separators=(",", ":")),
                        json.dumps(dict(anchor.metadata), sort_keys=True, separators=(",", ":")),
                        anchor.source_excerpt,
                    ),
                )
            for item_ordinal, item in enumerate(audit.items, start=1):
                connection.execute(
                    """
                    INSERT INTO grounding_audit_items(
                        audit_id, item_ordinal, divergence, goal_node_id, anchor_ids_json,
                        requirement_ids_json, candidate_ids_json, confidence, rationale, origin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        item_ordinal,
                        item.divergence.value,
                        item.goal_node_id,
                        json.dumps(list(item.anchor_ids), separators=(",", ":")),
                        json.dumps(list(item.requirement_ids), separators=(",", ":")),
                        json.dumps(list(item.candidate_ids), separators=(",", ":")),
                        item.confidence,
                        item.rationale,
                        item.origin,
                    ),
                )
            self._append_event(
                connection,
                project_id=audit.project_id,
                requirement_id=None,
                event_type="intention_grounding_recorded",
                actor=actor,
                request_id=str(request_id or ""),
                payload={
                    "audit_id": audit_id,
                    "provider_id": audit.provider_id,
                    "source_revision": audit.source_revision,
                    "disposition": audit.disposition.value,
                    "item_count": len(audit.items),
                    "evidence_authority": audit.evidence_authority,
                },
                occurred_at=occurred_at,
            )
        return replace(audit, audit_id=audit_id)

    def grounding_audits(self, project_id: str) -> list[Mapping[str, object]]:
        """Return project-scoped audit projections without model prompts or reasoning."""

        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            audits: list[Mapping[str, object]] = []
            records = connection.execute(
                """
                SELECT audit_id, provider_id, source_revision, selected_goal_ids_json,
                       disposition, model, terminal_reason, prompt_version, input_truncated,
                       diagnostics_json, created_at, created_by, request_id,
                       evidence_authority, provenance_json
                FROM grounding_audits
                WHERE project_id = ?
                ORDER BY audit_id
                """,
                (project_id,),
            ).fetchall()
            for record in records:
                value: dict[str, object] = dict(record)
                audit_id = int(value["audit_id"])
                value["selected_goal_ids"] = json.loads(value.pop("selected_goal_ids_json"))
                value["diagnostics"] = json.loads(value.pop("diagnostics_json"))
                value["provenance"] = json.loads(value.pop("provenance_json"))
                value["input_truncated"] = bool(value["input_truncated"])
                anchors = []
                for anchor_record in connection.execute(
                    """
                    SELECT anchor_id, kind, label, summary, source_path,
                           evidence_ids_json, dependency_anchor_ids_json,
                           test_evidence_ids_json, metadata_json, source_excerpt
                    FROM grounding_audit_anchors
                    WHERE audit_id = ?
                    ORDER BY anchor_id
                    """,
                    (audit_id,),
                ).fetchall():
                    anchor = dict(anchor_record)
                    anchor["evidence_ids"] = json.loads(anchor.pop("evidence_ids_json"))
                    anchor["dependency_anchor_ids"] = json.loads(
                        anchor.pop("dependency_anchor_ids_json")
                    )
                    anchor["test_evidence_ids"] = json.loads(
                        anchor.pop("test_evidence_ids_json")
                    )
                    anchor["metadata"] = json.loads(anchor.pop("metadata_json"))
                    anchors.append(anchor)
                value["anchors"] = anchors
                items = []
                for item_record in connection.execute(
                    """
                    SELECT item_ordinal, divergence, goal_node_id, anchor_ids_json,
                           requirement_ids_json, candidate_ids_json, confidence, rationale, origin
                    FROM grounding_audit_items
                    WHERE audit_id = ?
                    ORDER BY item_ordinal
                    """,
                    (audit_id,),
                ).fetchall():
                    item = dict(item_record)
                    item["anchor_ids"] = json.loads(item.pop("anchor_ids_json"))
                    item["requirement_ids"] = json.loads(item.pop("requirement_ids_json"))
                    item["candidate_ids"] = json.loads(item.pop("candidate_ids_json"))
                    items.append(item)
                value["items"] = items
                audits.append(value)
            return audits

    @staticmethod
    def _validate_goal_node_id(goal_node_id: str) -> str:
        goal_node_id = required_text(goal_node_id, "goal_node_id")
        if not _GOAL_NODE_ID_RE.fullmatch(goal_node_id):
            raise ValueError("goal_node_id must match GOAL-000000")
        return goal_node_id

    def _goal_node_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        goal_node_id: str,
    ) -> Mapping[str, Any]:
        self._ensure_project(connection, project_id)
        row = connection.execute(
            """
            SELECT goal_node_id, node_type, title, payload_json, source_anchor_json,
                   created_at, created_by
            FROM goal_nodes WHERE project_id = ? AND goal_node_id = ?
            """,
            (project_id, goal_node_id),
        ).fetchone()
        if row is None:
            raise GoalNodeNotFoundError(
                f"unknown goal node in project {project_id}: {goal_node_id}"
            )
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        value["source_anchor"] = self._anchor_from_json(value.pop("source_anchor_json"))
        return value
