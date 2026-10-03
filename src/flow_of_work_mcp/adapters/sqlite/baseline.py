"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Mapping

from flow_of_work_mcp.core.domain import (
    BaselineImportPlan,
    GoalNodeType,
    LifecycleStatus,
)
from flow_of_work_mcp.core.domain.identifiers import (
    normalize_requirement_statement,
    required_text,
)
from flow_of_work_mcp.core.domain.srs import SourceAnchor
from flow_of_work_mcp.core.errors import (
    RequirementConflictError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class BaselineStoreMixin:
    def import_baseline(
        self,
        plan: BaselineImportPlan,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Materialize one accepted initial SRS baseline in a single transaction.

        This deliberately has no update mode. A later SRS revision needs its own
        governed design instead of silently rewriting canonical requirements or
        Goal Graph identities created by the initial baseline.
        """

        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, plan.project_id)
            if request_id:
                existing = connection.execute(
                    """
                    SELECT baseline_id FROM baseline_imports
                    WHERE project_id = ? AND request_id = ?
                    """,
                    (plan.project_id, request_id),
                ).fetchone()
                if existing is not None:
                    return self._baseline_import_value(
                        connection, plan.project_id, str(existing["baseline_id"])
                    )
            existing = connection.execute(
                "SELECT baseline_id FROM baseline_imports WHERE project_id = ? LIMIT 1",
                (plan.project_id,),
            ).fetchone()
            if existing is not None:
                raise RequirementConflictError(
                    "an initial baseline already exists for this project"
                )
            populated = connection.execute(
                """
                SELECT
                    EXISTS(SELECT 1 FROM requirements WHERE project_id = ?) AS has_requirements,
                    EXISTS(SELECT 1 FROM goal_nodes WHERE project_id = ?) AS has_goals
                """,
                (plan.project_id, plan.project_id),
            ).fetchone()
            if populated["has_requirements"] or populated["has_goals"]:
                raise RequirementConflictError(
                    "initial baseline requires an otherwise empty canonical project"
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO baseline_sequences(project_id, next_baseline_ordinal)
                VALUES (?, 1)
                """,
                (plan.project_id,),
            )
            baseline_ordinal = int(
                connection.execute(
                    "SELECT next_baseline_ordinal FROM baseline_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()["next_baseline_ordinal"]
            )
            baseline_id = f"BASE-{baseline_ordinal:06d}"
            connection.execute(
                """
                UPDATE baseline_sequences SET next_baseline_ordinal = ? WHERE project_id = ?
                """,
                (baseline_ordinal + 1, plan.project_id),
            )
            connection.execute(
                """
                INSERT INTO baseline_imports(
                    project_id, baseline_id, ordinal, source_path, content_sha256,
                    profile_id, profile_version, origin, previous_baseline_id, created_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    plan.project_id,
                    baseline_id,
                    baseline_ordinal,
                    plan.source_path,
                    plan.content_sha256,
                    plan.profile_id,
                    plan.profile_version,
                    plan.origin,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO goal_sequences(
                    project_id, next_goal_ordinal, next_candidate_ordinal
                ) VALUES (?, 1, 1)
                """,
                (plan.project_id,),
            )

            def add_mapping(
                source_entity_id: str,
                source_kind: str,
                canonical_kind: str,
                canonical_id: str,
                anchor: SourceAnchor | None,
                entity_sha256: str = "",
            ) -> None:
                connection.execute(
                    """
                    INSERT INTO baseline_entity_mappings(
                        project_id, baseline_id, source_entity_id, source_kind,
                        canonical_kind, canonical_id, source_anchor_json, entity_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.project_id,
                        baseline_id,
                        source_entity_id,
                        source_kind,
                        canonical_kind,
                        canonical_id,
                        self._anchor_to_json(anchor),
                        entity_sha256,
                    ),
                )

            def add_goal(
                node_type: GoalNodeType,
                title: str,
                payload: Mapping[str, object],
                anchor: SourceAnchor | None,
            ) -> str:
                sequence = connection.execute(
                    "SELECT next_goal_ordinal FROM goal_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()
                ordinal = int(sequence["next_goal_ordinal"])
                goal_node_id = f"GOAL-{ordinal:06d}"
                connection.execute(
                    "UPDATE goal_sequences SET next_goal_ordinal = ? WHERE project_id = ?",
                    (ordinal + 1, plan.project_id),
                )
                connection.execute(
                    """
                    INSERT INTO goal_nodes(
                        project_id, goal_node_id, node_type, title, payload_json,
                        source_anchor_json, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.project_id,
                        goal_node_id,
                        node_type.value,
                        title,
                        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                        self._anchor_to_json(anchor),
                        occurred_at,
                        actor,
                    ),
                )
                self._append_event(
                    connection,
                    project_id=plan.project_id,
                    requirement_id=None,
                    event_type="goal_node_created",
                    actor=actor,
                    request_id=request_id,
                    payload={"goal_node_id": goal_node_id, "node_type": node_type.value},
                    occurred_at=occurred_at,
                )
                return goal_node_id

            def add_candidate(
                source_entity_id: str,
                expectation_id: str,
                category: str,
                statement: str,
                anchor: SourceAnchor | None,
            ) -> str:
                sequence = connection.execute(
                    "SELECT next_candidate_ordinal FROM goal_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()
                ordinal = int(sequence["next_candidate_ordinal"])
                candidate_id = f"CAND-{ordinal:06d}"
                connection.execute(
                    "UPDATE goal_sequences SET next_candidate_ordinal = ? WHERE project_id = ?",
                    (ordinal + 1, plan.project_id),
                )
                connection.execute(
                    """
                    INSERT INTO goal_requirement_candidates(
                        project_id, candidate_id, source_goal_id, category, statement,
                        normalized_statement, source_anchor_json, status, created_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
                    """,
                    (
                        plan.project_id,
                        candidate_id,
                        expectation_id,
                        category,
                        statement,
                        normalize_requirement_statement(statement),
                        self._anchor_to_json(anchor),
                        occurred_at,
                        actor,
                    ),
                )
                self._append_event(
                    connection,
                    project_id=plan.project_id,
                    requirement_id=None,
                    event_type="goal_requirement_candidate_created",
                    actor=actor,
                    request_id=request_id,
                    payload={"candidate_id": candidate_id, "source_goal_id": expectation_id},
                    occurred_at=occurred_at,
                )
                add_mapping(
                    source_entity_id,
                    "derived_candidate",
                    "goal_requirement_candidate",
                    candidate_id,
                    anchor,
                )
                return candidate_id

            requirement_ids: list[str] = []
            for item in plan.requirements:
                draft = item.draft
                normalized_statement = normalize_requirement_statement(draft.statement)
                duplicate = connection.execute(
                    """
                    SELECT requirement_id FROM requirements
                    WHERE project_id = ? AND normalized_statement = ?
                    """,
                    (plan.project_id, normalized_statement),
                ).fetchone()
                if duplicate is not None:
                    raise RequirementConflictError(
                        f"duplicate requirement statement: {duplicate['requirement_id']}"
                    )
                sequence = connection.execute(
                    "SELECT next_requirement_ordinal FROM project_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()
                ordinal = int(sequence["next_requirement_ordinal"])
                requirement_id = f"REQ-{ordinal:06d}"
                connection.execute(
                    "UPDATE project_sequences SET next_requirement_ordinal = ? WHERE project_id = ?",
                    (ordinal + 1, plan.project_id),
                )
                source_anchor = self._anchor_to_text(item.source_anchor)
                connection.execute(
                    """
                    INSERT INTO requirements(
                        project_id, requirement_id, ordinal, title, statement,
                        normalized_statement, category, lifecycle_status,
                        current_revision, source_anchor, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        plan.project_id,
                        requirement_id,
                        ordinal,
                        draft.title,
                        draft.statement,
                        normalized_statement,
                        draft.category,
                        LifecycleStatus.PLANNED.value,
                        source_anchor,
                        occurred_at,
                        occurred_at,
                    ),
                )
                self._append_revision(
                    connection,
                    project_id=plan.project_id,
                    requirement_id=requirement_id,
                    revision=1,
                    title=draft.title,
                    statement=draft.statement,
                    category=draft.category,
                    source_anchor=source_anchor,
                    rationale=draft.rationale,
                    actor=actor,
                    occurred_at=occurred_at,
                )
                self._append_event(
                    connection,
                    project_id=plan.project_id,
                    requirement_id=requirement_id,
                    event_type="requirement_created",
                    actor=actor,
                    request_id=request_id,
                    payload={
                        "revision": 1,
                        "lifecycle_status": LifecycleStatus.PLANNED.value,
                        "category": draft.category,
                        "source_anchor": source_anchor,
                        "baseline_id": baseline_id,
                    },
                    occurred_at=occurred_at,
                )
                add_mapping(
                    item.source_id,
                    "requirement",
                    "requirement",
                    requirement_id,
                    item.source_anchor,
                    self._baseline_entity_digest(
                        "requirement",
                        item.source_id,
                        {
                            "title": draft.title,
                            "statement": draft.statement,
                            "category": draft.category,
                        },
                    ),
                )
                requirement_ids.append(requirement_id)

            use_case_ids: dict[str, str] = {}
            for item in plan.use_cases:
                draft = item.draft
                goal_id = add_goal(
                    GoalNodeType.USE_CASE,
                    draft.title,
                    {
                        "actor": draft.actor,
                        "objective": draft.objective,
                        "observable_outcome": draft.observable_outcome,
                        "preconditions": list(draft.preconditions),
                        "postconditions": list(draft.postconditions),
                        "invariants": list(draft.invariants),
                    },
                    draft.source_anchor,
                )
                use_case_ids[item.source_id] = goal_id
                add_mapping(
                    item.source_id,
                    "use_case",
                    "goal_node",
                    goal_id,
                    draft.source_anchor,
                    self._baseline_entity_digest(
                        "use_case",
                        item.source_id,
                        {
                            "title": draft.title,
                            "actor": draft.actor,
                            "objective": draft.objective,
                            "observable_outcome": draft.observable_outcome,
                            "preconditions": list(draft.preconditions),
                            "postconditions": list(draft.postconditions),
                            "invariants": list(draft.invariants),
                        },
                    ),
                )

                expectation_id = add_goal(
                    GoalNodeType.BEHAVIORAL_EXPECTATION,
                    f"{draft.title} expected behavior",
                    {
                        "statement": f"{draft.objective}. Expected outcome: {draft.observable_outcome}",
                        "category": "functional",
                        "observable_outcome": draft.observable_outcome,
                    },
                    draft.source_anchor,
                )
                add_mapping(
                    f"{item.source_id}::expectation",
                    "derived_expectation",
                    "goal_node",
                    expectation_id,
                    draft.source_anchor,
                )
                add_candidate(
                    f"{item.source_id}::candidate",
                    expectation_id,
                    "functional",
                    f"{draft.objective}. Expected outcome: {draft.observable_outcome}",
                    draft.source_anchor,
                )

            sequences: list[tuple[str, str]] = []
            for item in plan.sequences:
                draft = item.draft
                goal_id = add_goal(
                    GoalNodeType.SEQUENCE,
                    draft.title,
                    {
                        "participants": list(draft.participants),
                        "normal_steps": list(draft.normal_steps),
                        "alternate_steps": list(draft.alternate_steps),
                        "failure_steps": list(draft.failure_steps),
                        "expected_effects": list(draft.expected_effects),
                    },
                    draft.source_anchor,
                )
                add_mapping(
                    item.source_id,
                    "sequence",
                    "goal_node",
                    goal_id,
                    draft.source_anchor,
                    self._baseline_entity_digest(
                        "sequence",
                        item.source_id,
                        {
                            "title": draft.title,
                            "participants": list(draft.participants),
                            "normal_steps": list(draft.normal_steps),
                            "alternate_steps": list(draft.alternate_steps),
                            "failure_steps": list(draft.failure_steps),
                            "expected_effects": list(draft.expected_effects),
                            "related_use_case_source_id": item.related_use_case_source_id,
                        },
                    ),
                )
                sequences.append((item.related_use_case_source_id, goal_id))

                expected_effects = "; ".join(draft.expected_effects)
                statement = f"{draft.title}. Expected effect: {expected_effects}"
                expectation_id = add_goal(
                    GoalNodeType.BEHAVIORAL_EXPECTATION,
                    f"{draft.title} expected behavior",
                    {
                        "statement": statement,
                        "category": "functional",
                        "observable_outcome": expected_effects,
                    },
                    draft.source_anchor,
                )
                add_mapping(
                    f"{item.source_id}::expectation",
                    "derived_expectation",
                    "goal_node",
                    expectation_id,
                    draft.source_anchor,
                )
                add_candidate(
                    f"{item.source_id}::candidate",
                    expectation_id,
                    "functional",
                    statement,
                    draft.source_anchor,
                )

            for related_use_case_source_id, sequence_goal_id in sequences:
                if not related_use_case_source_id:
                    continue
                use_case_goal_id = use_case_ids.get(related_use_case_source_id)
                if use_case_goal_id is None:
                    raise ValueError(
                        "sequence references an unknown imported use case: "
                        f"{related_use_case_source_id}"
                    )
                connection.execute(
                    """
                    INSERT INTO goal_edges(
                        project_id, source_goal_id, target_goal_id, relation, created_at, created_by
                    ) VALUES (?, ?, ?, 'realizes', ?, ?)
                    """,
                    (plan.project_id, sequence_goal_id, use_case_goal_id, occurred_at, actor),
                )
                self._append_event(
                    connection,
                    project_id=plan.project_id,
                    requirement_id=None,
                    event_type="goal_edge_created",
                    actor=actor,
                    request_id=request_id,
                    payload={
                        "source_goal_id": sequence_goal_id,
                        "target_goal_id": use_case_goal_id,
                        "relation": "realizes",
                    },
                    occurred_at=occurred_at,
                )

            self._append_event(
                connection,
                project_id=plan.project_id,
                requirement_id=None,
                event_type="baseline_imported",
                actor=actor,
                request_id=request_id,
                payload={
                    "baseline_id": baseline_id,
                    "requirement_count": len(requirement_ids),
                    "use_case_count": len(plan.use_cases),
                    "sequence_count": len(plan.sequences),
                },
                occurred_at=occurred_at,
            )
            return self._baseline_import_value(connection, plan.project_id, baseline_id)

    def revise_baseline(
        self,
        plan: BaselineImportPlan,
        *,
        previous_baseline_id: str,
        actor: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Append one source-proven baseline revision or return a no-mutation review.

        Behavioral Goal Graph revisions are intentionally unsupported until that
        graph gains immutable node/edge revision semantics. This method still
        classifies every source entity, but it commits only changes whose
        canonical continuity can be proven without rewriting behavioral state.
        """

        actor = required_text(actor, "actor")
        previous_baseline_id = required_text(previous_baseline_id, "previous_baseline_id")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._ensure_project(connection, plan.project_id)
            if request_id:
                repeated = connection.execute(
                    """
                    SELECT baseline_id FROM baseline_imports
                    WHERE project_id = ? AND request_id = ? AND previous_baseline_id != ''
                    """,
                    (plan.project_id, request_id),
                ).fetchone()
                if repeated is not None:
                    return {
                        "revised": True,
                        "disposition": "accepted",
                        "baseline": self._baseline_import_value(
                            connection, plan.project_id, str(repeated["baseline_id"])
                        ),
                        "classifications": [],
                        "idempotent_replay": True,
                    }

            previous = connection.execute(
                """
                SELECT baseline_id, ordinal, profile_id, profile_version
                FROM baseline_imports WHERE project_id = ? AND baseline_id = ?
                """,
                (plan.project_id, previous_baseline_id),
            ).fetchone()
            if previous is None:
                raise RequirementConflictError("baseline_predecessor_not_found")
            latest = connection.execute(
                """
                SELECT baseline_id FROM baseline_imports
                WHERE project_id = ? ORDER BY ordinal DESC LIMIT 1
                """,
                (plan.project_id,),
            ).fetchone()
            if latest is None or str(latest["baseline_id"]) != previous_baseline_id:
                raise RequirementConflictError("baseline_predecessor_not_latest")
            if (
                str(previous["profile_id"]) != plan.profile_id
                or str(previous["profile_version"]) != plan.profile_version
            ):
                return self._baseline_revision_review(
                    connection,
                    plan.project_id,
                    previous_baseline_id,
                    actor=actor,
                    request_id=request_id,
                    reason="baseline_profile_continuity_unprovable",
                    classifications=(),
                    occurred_at=occurred_at,
                )

            previous_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT source_entity_id, source_kind, canonical_kind, canonical_id,
                           source_anchor_json, entity_sha256
                    FROM baseline_entity_mappings
                    WHERE project_id = ? AND baseline_id = ?
                    ORDER BY source_entity_id
                    """,
                    (plan.project_id, previous_baseline_id),
                ).fetchall()
            ]
            prior_primary = {
                str(row["source_entity_id"]): row
                for row in previous_rows
                if str(row["source_kind"]) in {"requirement", "use_case", "sequence"}
            }
            if not prior_primary or any(not str(row["entity_sha256"]) for row in prior_primary.values()):
                return self._baseline_revision_review(
                    connection,
                    plan.project_id,
                    previous_baseline_id,
                    actor=actor,
                    request_id=request_id,
                    reason="baseline_source_digest_unavailable",
                    classifications=(),
                    occurred_at=occurred_at,
                )

            current_entities = self._baseline_primary_entities(plan)
            classifications = self._classify_baseline_entities(prior_primary, current_entities)
            behavioral_change = any(
                item["source_kind"] != "requirement" and item["status"] != "retained"
                for item in classifications
            )
            unresolved = any(item["status"] == "unresolved" for item in classifications)
            if unresolved or behavioral_change:
                return self._baseline_revision_review(
                    connection,
                    plan.project_id,
                    previous_baseline_id,
                    actor=actor,
                    request_id=request_id,
                    reason=(
                        "baseline_source_continuity_unresolved"
                        if unresolved
                        else "goal_graph_revision_required"
                    ),
                    classifications=classifications,
                    occurred_at=occurred_at,
                )

            deprecated_requirements = [
                item
                for item in classifications
                if item["source_kind"] == "requirement" and item["status"] == "deprecated"
            ]
            if deprecated_requirements and not str(governed_approval_reference or "").strip():
                return self._baseline_revision_review(
                    connection,
                    plan.project_id,
                    previous_baseline_id,
                    actor=actor,
                    request_id=request_id,
                    reason="governed_approval_required",
                    classifications=classifications,
                    occurred_at=occurred_at,
                )

            duplicate_content = connection.execute(
                """
                SELECT baseline_id FROM baseline_imports
                WHERE project_id = ? AND content_sha256 = ?
                """,
                (plan.project_id, plan.content_sha256),
            ).fetchone()
            if duplicate_content is not None:
                return self._baseline_revision_review(
                    connection,
                    plan.project_id,
                    previous_baseline_id,
                    actor=actor,
                    request_id=request_id,
                    reason="baseline_content_unchanged",
                    classifications=classifications,
                    occurred_at=occurred_at,
                )

            connection.execute(
                "INSERT OR IGNORE INTO baseline_sequences(project_id, next_baseline_ordinal) VALUES (?, 1)",
                (plan.project_id,),
            )
            ordinal = int(
                connection.execute(
                    "SELECT next_baseline_ordinal FROM baseline_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()["next_baseline_ordinal"]
            )
            baseline_id = f"BASE-{ordinal:06d}"
            connection.execute(
                "UPDATE baseline_sequences SET next_baseline_ordinal = ? WHERE project_id = ?",
                (ordinal + 1, plan.project_id),
            )
            connection.execute(
                """
                INSERT INTO baseline_imports(
                    project_id, baseline_id, ordinal, source_path, content_sha256,
                    profile_id, profile_version, origin, previous_baseline_id, created_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.project_id, baseline_id, ordinal, plan.source_path, plan.content_sha256,
                    plan.profile_id, plan.profile_version, plan.origin, previous_baseline_id, occurred_at, actor, request_id,
                ),
            )

            classification_by_source = {item["source_entity_id"]: item for item in classifications}

            def add_mapping(
                *,
                source_entity_id: str,
                source_kind: str,
                canonical_kind: str,
                canonical_id: str,
                anchor: SourceAnchor | None,
                entity_sha256: str,
                continuity_status: str,
                previous_canonical_id: str = "",
                classification_reason: str = "",
            ) -> None:
                connection.execute(
                    """
                    INSERT INTO baseline_entity_mappings(
                        project_id, baseline_id, source_entity_id, source_kind, canonical_kind,
                        canonical_id, source_anchor_json, entity_sha256, continuity_status,
                        previous_baseline_id, previous_canonical_id, classification_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.project_id, baseline_id, source_entity_id, source_kind, canonical_kind,
                        canonical_id, self._anchor_to_json(anchor), entity_sha256, continuity_status,
                        previous_baseline_id, previous_canonical_id, classification_reason,
                    ),
                )

            def add_requirement(item: Mapping[str, object]) -> str:
                draft = item["draft"]
                source_anchor = self._anchor_to_text(item["anchor"])
                normalized = normalize_requirement_statement(draft.statement)
                duplicate = connection.execute(
                    "SELECT requirement_id FROM requirements WHERE project_id = ? AND normalized_statement = ?",
                    (plan.project_id, normalized),
                ).fetchone()
                if duplicate is not None:
                    raise RequirementConflictError("baseline_requirement_statement_conflict")
                sequence = connection.execute(
                    "SELECT next_requirement_ordinal FROM project_sequences WHERE project_id = ?",
                    (plan.project_id,),
                ).fetchone()
                requirement_id = f"REQ-{int(sequence['next_requirement_ordinal']):06d}"
                connection.execute(
                    "UPDATE project_sequences SET next_requirement_ordinal = ? WHERE project_id = ?",
                    (int(sequence["next_requirement_ordinal"]) + 1, plan.project_id),
                )
                connection.execute(
                    """
                    INSERT INTO requirements(
                        project_id, requirement_id, ordinal, title, statement, normalized_statement,
                        category, lifecycle_status, current_revision, source_anchor, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        plan.project_id, requirement_id, int(sequence["next_requirement_ordinal"]),
                        draft.title, draft.statement, normalized, draft.category,
                        LifecycleStatus.PLANNED.value, source_anchor, occurred_at, occurred_at,
                    ),
                )
                self._append_revision(
                    connection, project_id=plan.project_id, requirement_id=requirement_id,
                    revision=1, title=draft.title, statement=draft.statement, category=draft.category,
                    source_anchor=source_anchor, rationale=draft.rationale, actor=actor, occurred_at=occurred_at,
                )
                self._append_event(
                    connection, project_id=plan.project_id, requirement_id=requirement_id,
                    event_type="requirement_created", actor=actor, request_id=request_id,
                    payload={"revision": 1, "lifecycle_status": LifecycleStatus.PLANNED.value, "baseline_id": baseline_id},
                    occurred_at=occurred_at,
                )
                return requirement_id

            for source_id, item in current_entities.items():
                classification = classification_by_source[source_id]
                prior = prior_primary.get(source_id)
                status = str(classification["status"])
                if item["source_kind"] != "requirement":
                    assert prior is not None and status == "retained"
                    add_mapping(
                        source_entity_id=source_id, source_kind=str(item["source_kind"]),
                        canonical_kind=str(prior["canonical_kind"]), canonical_id=str(prior["canonical_id"]),
                        anchor=item["anchor"], entity_sha256=str(item["entity_sha256"]),
                        continuity_status=status, previous_canonical_id=str(prior["canonical_id"]),
                    )
                    continue
                if status == "added":
                    canonical_id = add_requirement(item)
                    previous_canonical_id = ""
                else:
                    assert prior is not None
                    canonical_id = str(prior["canonical_id"])
                    previous_canonical_id = canonical_id
                    if status == "revised":
                        draft = item["draft"]
                        current = self._requirement_row(connection, plan.project_id, canonical_id)
                        normalized = normalize_requirement_statement(draft.statement)
                        conflict = connection.execute(
                            """
                            SELECT requirement_id FROM requirements
                            WHERE project_id = ? AND normalized_statement = ? AND requirement_id != ?
                            """,
                            (plan.project_id, normalized, canonical_id),
                        ).fetchone()
                        if conflict is not None:
                            raise RequirementConflictError("baseline_requirement_statement_conflict")
                        revision = int(current["current_revision"]) + 1
                        source_anchor = self._anchor_to_text(item["anchor"])
                        connection.execute(
                            """
                            UPDATE requirements SET title = ?, statement = ?, normalized_statement = ?, category = ?,
                                current_revision = ?, source_anchor = ?, updated_at = ?
                            WHERE project_id = ? AND requirement_id = ?
                            """,
                            (
                                draft.title, draft.statement, normalized, draft.category, revision,
                                source_anchor, occurred_at, plan.project_id, canonical_id,
                            ),
                        )
                        self._append_revision(
                            connection, project_id=plan.project_id, requirement_id=canonical_id,
                            revision=revision, title=draft.title, statement=draft.statement,
                            category=draft.category, source_anchor=source_anchor,
                            rationale="Revised by accepted SRS baseline revision.", actor=actor,
                            occurred_at=occurred_at,
                        )
                        self._append_event(
                            connection, project_id=plan.project_id, requirement_id=canonical_id,
                            event_type="requirement_revised", actor=actor, request_id=request_id,
                            payload={"baseline_id": baseline_id, "from_revision": current["current_revision"], "to_revision": revision},
                            occurred_at=occurred_at,
                        )
                add_mapping(
                    source_entity_id=source_id, source_kind="requirement", canonical_kind="requirement",
                    canonical_id=canonical_id, anchor=item["anchor"], entity_sha256=str(item["entity_sha256"]),
                    continuity_status=status, previous_canonical_id=previous_canonical_id,
                )

            for item in classifications:
                if item["source_kind"] != "requirement" or item["status"] != "deprecated":
                    continue
                prior = prior_primary[str(item["source_entity_id"])]
                requirement_id = str(prior["canonical_id"])
                current = self._requirement_row(connection, plan.project_id, requirement_id)
                connection.execute(
                    "UPDATE requirements SET lifecycle_status = ?, updated_at = ? WHERE project_id = ? AND requirement_id = ?",
                    (LifecycleStatus.REMOVED.value, occurred_at, plan.project_id, requirement_id),
                )
                self._append_event(
                    connection, project_id=plan.project_id, requirement_id=requirement_id,
                    event_type="lifecycle_status_changed", actor=actor, request_id=request_id,
                    payload={
                        "from_status": current["lifecycle_status"], "to_status": LifecycleStatus.REMOVED.value,
                        "reason": "source entity deprecated by accepted baseline revision",
                        "governance_reference": governed_approval_reference, "baseline_id": baseline_id,
                    },
                    occurred_at=occurred_at,
                )
                add_mapping(
                    source_entity_id=str(item["source_entity_id"]), source_kind="requirement",
                    canonical_kind="requirement", canonical_id=requirement_id, anchor=None,
                    entity_sha256=str(prior["entity_sha256"]), continuity_status="deprecated",
                    previous_canonical_id=requirement_id,
                )

            # Derived behavioral identities are retained only when their parent source is retained.
            for row in previous_rows:
                source_entity_id = str(row["source_entity_id"])
                if "::" not in source_entity_id:
                    continue
                parent_id = source_entity_id.split("::", 1)[0]
                parent = classification_by_source.get(parent_id)
                if parent is None or parent["status"] != "retained":
                    continue
                parent_entity = current_entities[parent_id]
                add_mapping(
                    source_entity_id=source_entity_id, source_kind=str(row["source_kind"]),
                    canonical_kind=str(row["canonical_kind"]), canonical_id=str(row["canonical_id"]),
                    anchor=parent_entity["anchor"], entity_sha256="", continuity_status="retained",
                    previous_canonical_id=str(row["canonical_id"]),
                )

            self._append_event(
                connection, project_id=plan.project_id, requirement_id=None,
                event_type="baseline_revised", actor=actor, request_id=request_id,
                payload={
                    "baseline_id": baseline_id, "previous_baseline_id": previous_baseline_id,
                    "classification_counts": self._classification_counts(classifications),
                    "governance_reference": governed_approval_reference,
                },
                occurred_at=occurred_at,
            )
            return {
                "revised": True,
                "disposition": "accepted",
                "baseline": self._baseline_import_value(connection, plan.project_id, baseline_id),
                "classifications": classifications,
            }

    @staticmethod
    def _baseline_entity_digest(
        source_kind: str,
        source_entity_id: str,
        payload: Mapping[str, object],
    ) -> str:
        canonical = json.dumps(
            {
                "source_kind": source_kind,
                "source_entity_id": source_entity_id,
                "payload": dict(payload),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _baseline_primary_entities(
        self,
        plan: BaselineImportPlan,
    ) -> dict[str, Mapping[str, object]]:
        entities: dict[str, Mapping[str, object]] = {}
        for item in plan.requirements:
            draft = item.draft
            entities[item.source_id] = {
                "source_kind": "requirement",
                "draft": draft,
                "anchor": item.source_anchor,
                "entity_sha256": self._baseline_entity_digest(
                    "requirement",
                    item.source_id,
                        {
                            "title": draft.title,
                            "statement": draft.statement,
                            "category": draft.category,
                        },
                ),
            }
        for item in plan.use_cases:
            draft = item.draft
            entities[item.source_id] = {
                "source_kind": "use_case",
                "draft": draft,
                "anchor": draft.source_anchor,
                "entity_sha256": self._baseline_entity_digest(
                    "use_case",
                    item.source_id,
                    {
                        "title": draft.title,
                        "actor": draft.actor,
                        "objective": draft.objective,
                        "observable_outcome": draft.observable_outcome,
                        "preconditions": list(draft.preconditions),
                        "postconditions": list(draft.postconditions),
                        "invariants": list(draft.invariants),
                    },
                ),
            }
        for item in plan.sequences:
            draft = item.draft
            entities[item.source_id] = {
                "source_kind": "sequence",
                "draft": draft,
                "anchor": draft.source_anchor,
                "entity_sha256": self._baseline_entity_digest(
                    "sequence",
                    item.source_id,
                    {
                        "title": draft.title,
                        "participants": list(draft.participants),
                        "normal_steps": list(draft.normal_steps),
                        "alternate_steps": list(draft.alternate_steps),
                        "failure_steps": list(draft.failure_steps),
                        "expected_effects": list(draft.expected_effects),
                        "related_use_case_source_id": item.related_use_case_source_id,
                    },
                ),
            }
        return entities

    @staticmethod
    def _classify_baseline_entities(
        previous: Mapping[str, Mapping[str, object]],
        current: Mapping[str, Mapping[str, object]],
    ) -> list[dict[str, str]]:
        classifications: list[dict[str, str]] = []
        for source_entity_id in sorted(set(previous).union(current)):
            prior = previous.get(source_entity_id)
            present = current.get(source_entity_id)
            if prior is None:
                classifications.append(
                    {
                        "source_entity_id": source_entity_id,
                        "source_kind": str(present["source_kind"]),
                        "status": "added",
                        "reason": "source_entity_not_present_in_predecessor",
                    }
                )
                continue
            if present is None:
                classifications.append(
                    {
                        "source_entity_id": source_entity_id,
                        "source_kind": str(prior["source_kind"]),
                        "status": "deprecated",
                        "reason": "source_entity_not_present_in_successor",
                    }
                )
                continue
            if str(prior["source_kind"]) != str(present["source_kind"]):
                classifications.append(
                    {
                        "source_entity_id": source_entity_id,
                        "source_kind": str(present["source_kind"]),
                        "status": "unresolved",
                        "reason": "source_kind_changed",
                    }
                )
                continue
            classifications.append(
                {
                    "source_entity_id": source_entity_id,
                    "source_kind": str(present["source_kind"]),
                    "status": (
                        "retained"
                        if str(prior["entity_sha256"]) == str(present["entity_sha256"])
                        else "revised"
                    ),
                    "reason": "source_digest_equal" if str(prior["entity_sha256"]) == str(present["entity_sha256"]) else "source_digest_changed",
                }
            )
        return classifications

    @staticmethod
    def _classification_counts(classifications: list[Mapping[str, str]]) -> Mapping[str, int]:
        return {
            status: sum(1 for item in classifications if item["status"] == status)
            for status in ("retained", "revised", "added", "deprecated", "unresolved")
        }

    def _baseline_revision_review(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        previous_baseline_id: str,
        *,
        actor: str,
        request_id: str,
        reason: str,
        classifications: list[Mapping[str, str]] | tuple[()],
        occurred_at: str,
    ) -> Mapping[str, object]:
        self._append_event(
            connection,
            project_id=project_id,
            requirement_id=None,
            event_type="baseline_revision_reviewed",
            actor=actor,
            request_id=request_id,
            payload={
                "previous_baseline_id": previous_baseline_id,
                "reason": reason,
                "classification_counts": self._classification_counts(list(classifications)),
            },
            occurred_at=occurred_at,
        )
        return {
            "revised": False,
            "disposition": "needs_review",
            "reason": reason,
            "previous_baseline_id": previous_baseline_id,
            "classifications": list(classifications),
        }

    def _baseline_import_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        baseline_id: str,
    ) -> Mapping[str, object]:
        baseline = connection.execute(
            """
            SELECT baseline_id, ordinal, source_path, content_sha256, profile_id,
                   profile_version, origin, previous_baseline_id, created_at, created_by, request_id
            FROM baseline_imports
            WHERE project_id = ? AND baseline_id = ?
            """,
            (project_id, baseline_id),
        ).fetchone()
        if baseline is None:
            raise RequirementConflictError(f"unknown baseline import: {baseline_id}")
        mappings = []
        for row in connection.execute(
            """
            SELECT source_entity_id, source_kind, canonical_kind, canonical_id,
                   source_anchor_json, entity_sha256, continuity_status,
                   previous_baseline_id, previous_canonical_id, classification_reason
            FROM baseline_entity_mappings
            WHERE project_id = ? AND baseline_id = ?
            ORDER BY source_entity_id
            """,
            (project_id, baseline_id),
        ).fetchall():
            value = dict(row)
            value["source_anchor"] = self._anchor_from_json(value.pop("source_anchor_json"))
            mappings.append(value)
        ledger_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) AS ledger_version FROM requirement_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()["ledger_version"]
        )
        baseline_value = dict(baseline)
        return {
            "project_id": project_id,
            "baseline": baseline_value,
            "mappings": mappings,
            "source_ledger_version": ledger_version,
            "artifact_profile": {
                "profile_id": baseline_value["profile_id"],
                "profile_version": baseline_value["profile_version"],
            },
        }
