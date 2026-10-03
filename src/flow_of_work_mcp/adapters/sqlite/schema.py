"""Internal SQLite ledger mixin extracted from ledger_store.py."""

from __future__ import annotations

import json
import sqlite3


from flow_of_work_mcp.adapters.sqlite.common import _utc_now


CURRENT_SCHEMA_VERSION = 52


class SchemaMixin:
    def _migrate(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interaction_project_contexts (
                    interaction_session_ref TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    provider_context_id TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS interaction_project_context_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interaction_session_ref TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    event_type TEXT NOT NULL,
                    previous_project_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_interaction_context_events
                    ON interaction_project_context_events(interaction_session_ref, event_id);

                CREATE TABLE IF NOT EXISTS interaction_capability_lenses (
                    interaction_session_ref TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    project_context_revision INTEGER NOT NULL CHECK(project_context_revision > 0),
                    producing_provider TEXT NOT NULL,
                    selected_area TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS interaction_capability_lens_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interaction_session_ref TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    producing_provider TEXT NOT NULL,
                    selected_area TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_interaction_lens_events
                    ON interaction_capability_lens_events(interaction_session_ref, event_id);

                CREATE TABLE IF NOT EXISTS interaction_projection_continuations (
                    interaction_session_ref TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '',
                    project_context_revision INTEGER NOT NULL DEFAULT 0 CHECK(project_context_revision >= 0),
                    owner TEXT NOT NULL,
                    query TEXT NOT NULL DEFAULT '',
                    offset INTEGER NOT NULL CHECK(offset >= 0),
                    source_fingerprint TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_project_bindings (
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    provider_kind TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    surfaces_json TEXT NOT NULL,
                    provider_context_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    replacement_reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, provider_kind)
                );

                CREATE TABLE IF NOT EXISTS provider_project_binding_events (
                    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
                    provider_kind TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    event_type TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, provider_kind, ordinal)
                );

                CREATE TABLE IF NOT EXISTS project_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_requirement_ordinal INTEGER NOT NULL CHECK(next_requirement_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS requirements (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    requirement_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    normalized_statement TEXT NOT NULL,
                    category TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    current_revision INTEGER NOT NULL CHECK(current_revision > 0),
                    source_anchor TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, requirement_id),
                    UNIQUE (project_id, ordinal),
                    UNIQUE (project_id, normalized_statement)
                );

                CREATE TABLE IF NOT EXISTS requirement_revisions (
                    project_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    title TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, requirement_id, revision),
                    FOREIGN KEY (project_id, requirement_id)
                        REFERENCES requirements(project_id, requirement_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS requirement_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    requirement_id TEXT,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY (project_id, requirement_id)
                        REFERENCES requirements(project_id, requirement_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS verification_evidence (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    verification_kind TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (project_id, requirement_id)
                        REFERENCES requirements(project_id, requirement_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_requirements_project_status
                    ON requirements(project_id, lifecycle_status, ordinal);
                CREATE INDEX IF NOT EXISTS idx_events_project_event
                    ON requirement_events(project_id, event_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_requirement_kind
                    ON verification_evidence(project_id, requirement_id, verification_kind, evidence_id);

                CREATE TABLE IF NOT EXISTS goal_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_goal_ordinal INTEGER NOT NULL CHECK(next_goal_ordinal > 0),
                    next_candidate_ordinal INTEGER NOT NULL CHECK(next_candidate_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS goal_nodes (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    goal_node_id TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_anchor_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY (project_id, goal_node_id)
                );

                CREATE TABLE IF NOT EXISTS goal_edges (
                    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    source_goal_id TEXT NOT NULL,
                    target_goal_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    UNIQUE(project_id, source_goal_id, target_goal_id, relation),
                    FOREIGN KEY(project_id, source_goal_id)
                        REFERENCES goal_nodes(project_id, goal_node_id) ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, target_goal_id)
                        REFERENCES goal_nodes(project_id, goal_node_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS goal_requirement_candidates (
                    project_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    source_goal_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    normalized_statement TEXT NOT NULL,
                    source_anchor_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY(project_id, candidate_id),
                    UNIQUE(project_id, source_goal_id, normalized_statement),
                    FOREIGN KEY(project_id, source_goal_id)
                        REFERENCES goal_nodes(project_id, goal_node_id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_goal_nodes_project_type
                    ON goal_nodes(project_id, node_type);
                CREATE INDEX IF NOT EXISTS idx_goal_candidates_project_status
                    ON goal_requirement_candidates(project_id, status, candidate_id);

                CREATE TABLE IF NOT EXISTS grounding_audits (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    provider_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    selected_goal_ids_json TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    terminal_reason TEXT NOT NULL DEFAULT '',
                    prompt_version TEXT NOT NULL DEFAULT '',
                    input_truncated INTEGER NOT NULL DEFAULT 0,
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS grounding_audit_items (
                    audit_id INTEGER NOT NULL REFERENCES grounding_audits(audit_id)
                        ON DELETE RESTRICT,
                    item_ordinal INTEGER NOT NULL CHECK(item_ordinal > 0),
                    divergence TEXT NOT NULL,
                    goal_node_id TEXT NOT NULL DEFAULT '',
                    anchor_ids_json TEXT NOT NULL,
                    candidate_ids_json TEXT NOT NULL,
                    confidence REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    origin TEXT NOT NULL,
                    PRIMARY KEY(audit_id, item_ordinal)
                );

                CREATE TABLE IF NOT EXISTS grounding_audit_anchors (
                    audit_id INTEGER NOT NULL REFERENCES grounding_audits(audit_id)
                        ON DELETE RESTRICT,
                    anchor_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_path TEXT NOT NULL DEFAULT '',
                    evidence_ids_json TEXT NOT NULL,
                    dependency_anchor_ids_json TEXT NOT NULL DEFAULT '[]',
                    test_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(audit_id, anchor_id)
                );

                CREATE INDEX IF NOT EXISTS idx_grounding_audits_project_audit
                    ON grounding_audits(project_id, audit_id);
                CREATE INDEX IF NOT EXISTS idx_grounding_items_divergence
                    ON grounding_audit_items(divergence, audit_id);
                CREATE INDEX IF NOT EXISTS idx_grounding_anchors_anchor
                    ON grounding_audit_anchors(anchor_id, audit_id);

                CREATE TABLE IF NOT EXISTS lifecycle_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_milestone_ordinal INTEGER NOT NULL CHECK(next_milestone_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS milestones (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    milestone_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    name TEXT NOT NULL,
                    requirement_ids_json TEXT NOT NULL,
                    dependency_closure_ids_json TEXT NOT NULL,
                    entry_policy_json TEXT NOT NULL,
                    exit_policy_json TEXT NOT NULL,
                    risk_disposition TEXT NOT NULL,
                    acceptance_evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, milestone_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, name)
                );

                CREATE TABLE IF NOT EXISTS phase_audits (
                    phase_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    scope_id TEXT NOT NULL,
                    scope_requirement_ids_json TEXT NOT NULL,
                    previous_phase_audit_id INTEGER,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(previous_phase_audit_id)
                        REFERENCES phase_audits(phase_audit_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS phase_audit_requirements (
                    phase_audit_id INTEGER NOT NULL REFERENCES phase_audits(phase_audit_id)
                        ON DELETE RESTRICT,
                    requirement_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    lifecycle_status TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    PRIMARY KEY(phase_audit_id, requirement_id)
                );

                CREATE TABLE IF NOT EXISTS phase_audit_deltas (
                    phase_audit_id INTEGER NOT NULL REFERENCES phase_audits(phase_audit_id)
                        ON DELETE RESTRICT,
                    requirement_id TEXT NOT NULL,
                    change_types_json TEXT NOT NULL,
                    evidence_added_ids_json TEXT NOT NULL,
                    PRIMARY KEY(phase_audit_id, requirement_id)
                );

                CREATE TABLE IF NOT EXISTS validation_audits (
                    validation_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    source_ref TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    finding_codes_json TEXT NOT NULL,
                    profile_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_milestones_project_ordinal
                    ON milestones(project_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_phase_audits_project_scope
                    ON phase_audits(project_id, scope_id, phase_audit_id);
                CREATE INDEX IF NOT EXISTS idx_validation_audits_project_disposition
                    ON validation_audits(project_id, disposition, validation_audit_id);

                CREATE TABLE IF NOT EXISTS artifact_generations (
                    generation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    profile_id TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    source_ledger_version INTEGER NOT NULL CHECK(source_ledger_version >= 0),
                    generated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS generated_artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_id INTEGER NOT NULL REFERENCES artifact_generations(generation_id)
                        ON DELETE RESTRICT,
                    artifact_kind TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(generation_id, artifact_kind)
                );

                CREATE TABLE IF NOT EXISTS artifact_mappings (
                    artifact_id INTEGER NOT NULL REFERENCES generated_artifacts(artifact_id)
                        ON DELETE RESTRICT,
                    canonical_kind TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(artifact_id, canonical_kind, canonical_id)
                );

                CREATE INDEX IF NOT EXISTS idx_artifact_generations_project_generation
                    ON artifact_generations(project_id, generation_id);
                CREATE INDEX IF NOT EXISTS idx_artifact_mappings_canonical
                    ON artifact_mappings(canonical_kind, canonical_id, artifact_id);

                CREATE TABLE IF NOT EXISTS job_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_job_ordinal INTEGER NOT NULL CHECK(next_job_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    job_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL CHECK(progress >= 0 AND progress <= 100),
                    terminal_reason TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, job_id),
                    UNIQUE(project_id, ordinal)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_project_status
                    ON jobs(project_id, status, ordinal);

                CREATE TABLE IF NOT EXISTS baseline_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_baseline_ordinal INTEGER NOT NULL CHECK(next_baseline_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS baseline_imports (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    baseline_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    source_path TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT 'srs_import',
                    previous_baseline_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, baseline_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, content_sha256)
                );

                CREATE TABLE IF NOT EXISTS baseline_entity_mappings (
                    project_id TEXT NOT NULL,
                    baseline_id TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    canonical_kind TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    source_anchor_json TEXT NOT NULL,
                    entity_sha256 TEXT NOT NULL DEFAULT '',
                    continuity_status TEXT NOT NULL DEFAULT 'initial',
                    previous_baseline_id TEXT NOT NULL DEFAULT '',
                    previous_canonical_id TEXT NOT NULL DEFAULT '',
                    classification_reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, baseline_id, source_entity_id),
                    FOREIGN KEY(project_id, baseline_id)
                        REFERENCES baseline_imports(project_id, baseline_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_baseline_mappings_canonical
                    ON baseline_entity_mappings(project_id, canonical_kind, canonical_id);

                CREATE TABLE IF NOT EXISTS bootstrap_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_bootstrap_ordinal INTEGER NOT NULL CHECK(next_bootstrap_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS bootstraps (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    bootstrap_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    intake_json TEXT NOT NULL DEFAULT '{}',
                    contradictions_json TEXT NOT NULL DEFAULT '[]',
                    behavior_draft_json TEXT NOT NULL DEFAULT '{}',
                    confirmation_reference TEXT NOT NULL DEFAULT '',
                    completion_reference TEXT NOT NULL DEFAULT '',
                    completion_handoff_json TEXT NOT NULL DEFAULT '{}',
                    blocking_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, bootstrap_id),
                    UNIQUE(project_id, ordinal)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_bootstraps_project_active
                    ON bootstraps(project_id)
                    WHERE status IN ('in_progress', 'blocked');

                CREATE TABLE IF NOT EXISTS bootstrap_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    bootstrap_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, bootstrap_id)
                        REFERENCES bootstraps(project_id, bootstrap_id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_bootstrap_events_project_bootstrap
                    ON bootstrap_events(project_id, bootstrap_id, event_id);

                CREATE TABLE IF NOT EXISTS change_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_change_ordinal INTEGER NOT NULL CHECK(next_change_ordinal > 0),
                    next_packet_ordinal INTEGER NOT NULL CHECK(next_packet_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS change_units (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    change_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    milestone_id TEXT NOT NULL DEFAULT '',
                    requirement_ids_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    baseline_refs_json TEXT NOT NULL,
                    current_revision INTEGER NOT NULL CHECK(current_revision > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id),
                    UNIQUE(project_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS change_unit_revisions (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    milestone_id TEXT NOT NULL DEFAULT '',
                    requirement_ids_json TEXT NOT NULL,
                    source_refs_json TEXT NOT NULL,
                    baseline_refs_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, change_id, revision),
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS change_requirement_scope (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, change_id, requirement_id),
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, requirement_id)
                        REFERENCES requirements(project_id, requirement_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS implementation_packets (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    readiness_state TEXT NOT NULL DEFAULT 'execution_ready',
                    target_policy TEXT NOT NULL DEFAULT 'documental_only',
                    objective TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    requirement_ids_json TEXT NOT NULL DEFAULT '[]',
                    goal_ids_json TEXT NOT NULL DEFAULT '[]',
                    in_scope_json TEXT NOT NULL DEFAULT '[]',
                    out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                    invariants_json TEXT NOT NULL DEFAULT '[]',
                    unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
                    navigation_audit_ids_json TEXT NOT NULL DEFAULT '[]',
                    target_binding_ids_json TEXT NOT NULL DEFAULT '[]',
                    candidate_set_ids_json TEXT NOT NULL DEFAULT '[]',
                    context_snapshot_ids_json TEXT NOT NULL DEFAULT '[]',
                    readiness_blockers_json TEXT NOT NULL DEFAULT '[]',
                    completion_criteria_json TEXT NOT NULL,
                    criterion_results_json TEXT NOT NULL DEFAULT '{}',
                    blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
                    disposition TEXT NOT NULL DEFAULT '',
                    successor_packet_id TEXT NOT NULL DEFAULT '',
                    spec_revision INTEGER NOT NULL DEFAULT 1 CHECK(spec_revision > 0),
                    state_revision INTEGER NOT NULL DEFAULT 1 CHECK(state_revision > 0),
                    current_revision INTEGER NOT NULL CHECK(current_revision > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id, packet_id),
                    UNIQUE(project_id, packet_id),
                    UNIQUE(project_id, change_id, ordinal),
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS implementation_packet_revisions (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    readiness_state TEXT NOT NULL DEFAULT 'execution_ready',
                    target_policy TEXT NOT NULL DEFAULT 'documental_only',
                    objective TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    requirement_ids_json TEXT NOT NULL DEFAULT '[]',
                    goal_ids_json TEXT NOT NULL DEFAULT '[]',
                    in_scope_json TEXT NOT NULL DEFAULT '[]',
                    out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                    invariants_json TEXT NOT NULL DEFAULT '[]',
                    unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
                    navigation_audit_ids_json TEXT NOT NULL DEFAULT '[]',
                    target_binding_ids_json TEXT NOT NULL DEFAULT '[]',
                    candidate_set_ids_json TEXT NOT NULL DEFAULT '[]',
                    context_snapshot_ids_json TEXT NOT NULL DEFAULT '[]',
                    readiness_blockers_json TEXT NOT NULL DEFAULT '[]',
                    completion_criteria_json TEXT NOT NULL,
                    criterion_results_json TEXT NOT NULL,
                    blocking_reasons_json TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    successor_packet_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, change_id, packet_id, revision),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_dependencies (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    depends_on_packet_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id, packet_id, depends_on_packet_id),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, change_id, depends_on_packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS change_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_change_events_project_change
                    ON change_events(project_id, change_id, event_id);

                CREATE TABLE IF NOT EXISTS navigation_audit_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_navigation_ordinal INTEGER NOT NULL CHECK(next_navigation_ordinal > 0),
                    next_candidate_set_ordinal INTEGER NOT NULL CHECK(next_candidate_set_ordinal > 0),
                    next_binding_ordinal INTEGER NOT NULL CHECK(next_binding_ordinal > 0),
                    next_snapshot_ordinal INTEGER NOT NULL CHECK(next_snapshot_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS navigation_audit_blocks (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    navigation_audit_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    milestone_id TEXT NOT NULL DEFAULT '',
                    change_id TEXT NOT NULL DEFAULT '',
                    packet_id TEXT NOT NULL DEFAULT '',
                    related_campaign_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    active_provider TEXT NOT NULL DEFAULT '',
                    source_revision TEXT NOT NULL DEFAULT '',
                    provider_window_state TEXT NOT NULL DEFAULT 'inactive',
                    provider_window_provider TEXT NOT NULL DEFAULT '',
                    provider_window_capability_version TEXT NOT NULL DEFAULT '',
                    provider_window_target_scope_json TEXT NOT NULL DEFAULT '{}',
                    provider_window_started_at TEXT NOT NULL DEFAULT '',
                    provider_window_snapshot_at TEXT NOT NULL DEFAULT '',
                    opened_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, navigation_audit_id),
                    UNIQUE(project_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS navigation_candidate_sets (
                    project_id TEXT NOT NULL,
                    navigation_audit_id TEXT NOT NULL,
                    candidate_set_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    provider TEXT NOT NULL,
                    provider_capability_version TEXT NOT NULL,
                    semantic_seeds_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    source_revision TEXT NOT NULL DEFAULT '',
                    truncated INTEGER NOT NULL CHECK(truncated IN (0, 1)),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, candidate_set_id),
                    UNIQUE(project_id, navigation_audit_id, ordinal),
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_candidate_targets (
                    project_id TEXT NOT NULL,
                    candidate_set_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    target_handle TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    surface_id TEXT NOT NULL,
                    repo_or_workspace_id TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL DEFAULT '',
                    symbol_name TEXT NOT NULL DEFAULT '',
                    line_start INTEGER,
                    line_end INTEGER,
                    confidence REAL,
                    selection_reason TEXT NOT NULL DEFAULT '',
                    semantic_seed TEXT NOT NULL DEFAULT '',
                    graph_evidence_json TEXT NOT NULL DEFAULT '{}',
                    traversal_path_json TEXT NOT NULL DEFAULT '[]',
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(project_id, candidate_set_id, candidate_id),
                    FOREIGN KEY(project_id, candidate_set_id)
                        REFERENCES navigation_candidate_sets(project_id, candidate_set_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_target_bindings (
                    project_id TEXT NOT NULL,
                    navigation_audit_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    candidate_set_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    target_handle TEXT NOT NULL,
                    selection_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, binding_id),
                    UNIQUE(project_id, navigation_audit_id, candidate_set_id, candidate_id),
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, candidate_set_id, candidate_id)
                        REFERENCES navigation_candidate_targets(project_id, candidate_set_id, candidate_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_rejected_candidates (
                    project_id TEXT NOT NULL,
                    navigation_audit_id TEXT NOT NULL,
                    candidate_set_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, navigation_audit_id, candidate_set_id, candidate_id),
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, candidate_set_id, candidate_id)
                        REFERENCES navigation_candidate_targets(project_id, candidate_set_id, candidate_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_context_snapshots (
                    project_id TEXT NOT NULL,
                    navigation_audit_id TEXT NOT NULL,
                    context_snapshot_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, navigation_audit_id, context_snapshot_id),
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    navigation_audit_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS navigation_provider_audit_snapshots (
                    project_id TEXT NOT NULL,
                    navigation_audit_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    provider TEXT NOT NULL,
                    provider_capability_version TEXT NOT NULL,
                    target_scope_json TEXT NOT NULL DEFAULT '{}',
                    source_revision TEXT NOT NULL DEFAULT '',
                    events_count INTEGER NOT NULL CHECK(events_count >= 0),
                    visited_files_json TEXT NOT NULL DEFAULT '[]',
                    visited_symbols_json TEXT NOT NULL DEFAULT '[]',
                    visited_chunks_json TEXT NOT NULL DEFAULT '[]',
                    selected_target_handles_json TEXT NOT NULL DEFAULT '[]',
                    rejected_target_handles_json TEXT NOT NULL DEFAULT '[]',
                    ambiguous_target_handles_json TEXT NOT NULL DEFAULT '[]',
                    traversal_evidence_json TEXT NOT NULL DEFAULT '{}',
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    truncated INTEGER NOT NULL CHECK(truncated IN (0, 1)),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    provider_snapshot_id TEXT NOT NULL DEFAULT '',
                    selection_ref TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL DEFAULT '',
                    exact_identities_json TEXT NOT NULL DEFAULT '[]',
                    page_refs_json TEXT NOT NULL DEFAULT '[]',
                    first_sequence INTEGER NOT NULL DEFAULT 0,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(project_id, navigation_audit_id, snapshot_id),
                    UNIQUE(project_id, navigation_audit_id, ordinal),
                    FOREIGN KEY(project_id, navigation_audit_id)
                        REFERENCES navigation_audit_blocks(project_id, navigation_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_navigation_events_project_block
                    ON navigation_audit_events(project_id, navigation_audit_id, event_id);

                CREATE TABLE IF NOT EXISTS packet_construction_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_audit_ordinal INTEGER NOT NULL CHECK(next_audit_ordinal > 0),
                    next_question_ordinal INTEGER NOT NULL CHECK(next_question_ordinal > 0),
                    next_proposal_ordinal INTEGER NOT NULL DEFAULT 1 CHECK(next_proposal_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_construction_audits (
                    project_id TEXT NOT NULL,
                    construction_audit_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    milestone_id TEXT NOT NULL DEFAULT '',
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    packet_revision INTEGER NOT NULL CHECK(packet_revision > 0),
                    question_plan_revision INTEGER NOT NULL CHECK(question_plan_revision > 0),
                    state TEXT NOT NULL,
                    target_policy TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, construction_audit_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_construction_questions (
                    project_id TEXT NOT NULL,
                    construction_audit_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    question_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    required INTEGER NOT NULL CHECK(required IN (0, 1)),
                    status TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    linked_navigation_refs_json TEXT NOT NULL DEFAULT '[]',
                    answer_summary TEXT NOT NULL DEFAULT '',
                    blocker_reason TEXT NOT NULL DEFAULT '',
                    waiver_rationale TEXT NOT NULL DEFAULT '',
                    policy_ref TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, construction_audit_id, question_id),
                    UNIQUE(project_id, construction_audit_id, question_key),
                    FOREIGN KEY(project_id, construction_audit_id)
                        REFERENCES packet_construction_audits(project_id, construction_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_construction_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    construction_audit_id TEXT NOT NULL,
                    question_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, construction_audit_id)
                        REFERENCES packet_construction_audits(project_id, construction_audit_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_construction_events_project_audit
                    ON packet_construction_events(project_id, construction_audit_id, event_id);

                CREATE TABLE IF NOT EXISTS packet_unit_proposals (
                    project_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    packet_revision INTEGER NOT NULL CHECK(packet_revision > 0),
                    proposal_revision INTEGER NOT NULL CHECK(proposal_revision > 0),
                    status TEXT NOT NULL,
                    operation_kind TEXT NOT NULL,
                    file_path TEXT NOT NULL DEFAULT '',
                    target_binding_ids_json TEXT NOT NULL DEFAULT '[]',
                    goal TEXT NOT NULL,
                    intent_points_json TEXT NOT NULL DEFAULT '[]',
                    acceptance_checks_json TEXT NOT NULL DEFAULT '[]',
                    constraints_json TEXT NOT NULL DEFAULT '[]',
                    out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    context_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_reason TEXT NOT NULL DEFAULT '',
                    target_adequacy_json TEXT NOT NULL DEFAULT '{}',
                    residual_reason TEXT NOT NULL DEFAULT '',
                    surface TEXT NOT NULL DEFAULT 'repo',
                    transition_rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, proposal_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_unit_proposals_packet
                    ON packet_unit_proposals(project_id, change_id, packet_id, ordinal);

                CREATE TABLE IF NOT EXISTS packet_unit_proposal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    proposal_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, proposal_id)
                        REFERENCES packet_unit_proposals(project_id, proposal_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_unit_proposal_events_project
                    ON packet_unit_proposal_events(project_id, proposal_id, event_id);

                CREATE TABLE IF NOT EXISTS packet_work_plan_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_work_plan_ordinal INTEGER NOT NULL CHECK(next_work_plan_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_work_plans (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    work_plan_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY(project_id, work_plan_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, change_id, packet_id),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_work_plan_revisions (
                    project_id TEXT NOT NULL,
                    work_plan_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL CHECK(plan_revision > 0),
                    packet_revision INTEGER NOT NULL CHECK(packet_revision > 0),
                    status TEXT NOT NULL,
                    transition_rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, work_plan_id, plan_revision),
                    FOREIGN KEY(project_id, work_plan_id)
                        REFERENCES packet_work_plans(project_id, work_plan_id)
                        ON DELETE RESTRICT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_work_plan_one_accepted
                    ON packet_work_plan_revisions(project_id, work_plan_id)
                    WHERE status = 'accepted';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_work_plan_request
                    ON packet_work_plan_revisions(project_id, request_id)
                    WHERE request_id <> '';

                CREATE TABLE IF NOT EXISTS packet_work_plan_units (
                    project_id TEXT NOT NULL,
                    work_plan_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL CHECK(plan_revision > 0),
                    unit_ordinal INTEGER NOT NULL CHECK(unit_ordinal > 0),
                    client_unit_key TEXT NOT NULL,
                    operation_kind TEXT NOT NULL,
                    mutation_target_binding_id TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL DEFAULT '',
                    target_description TEXT NOT NULL DEFAULT '',
                    member_label TEXT NOT NULL DEFAULT '',
                    context_target_binding_ids_json TEXT NOT NULL DEFAULT '[]',
                    instructions_json TEXT NOT NULL,
                    unit_checks_json TEXT NOT NULL DEFAULT '[]',
                    constraints_json TEXT NOT NULL DEFAULT '[]',
                    out_of_scope_json TEXT NOT NULL DEFAULT '[]',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    replaces_json TEXT NOT NULL DEFAULT '[]',
                    surface TEXT NOT NULL,
                    PRIMARY KEY(project_id, work_plan_id, plan_revision, client_unit_key),
                    UNIQUE(project_id, work_plan_id, plan_revision, unit_ordinal),
                    FOREIGN KEY(project_id, work_plan_id, plan_revision)
                        REFERENCES packet_work_plan_revisions(
                            project_id, work_plan_id, plan_revision
                        ) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_work_plan_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    work_plan_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL CHECK(plan_revision > 0),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, work_plan_id, plan_revision)
                        REFERENCES packet_work_plan_revisions(
                            project_id, work_plan_id, plan_revision
                        ) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_work_plan_packet
                    ON packet_work_plans(project_id, change_id, packet_id);

                CREATE INDEX IF NOT EXISTS idx_packet_work_plan_events_revision
                    ON packet_work_plan_events(
                        project_id, work_plan_id, plan_revision, event_id
                    );

                CREATE TABLE IF NOT EXISTS packet_reconciliation_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_scope_ordinal INTEGER NOT NULL CHECK(next_scope_ordinal > 0),
                    next_claim_ordinal INTEGER NOT NULL CHECK(next_claim_ordinal > 0),
                    next_snapshot_ordinal INTEGER NOT NULL CHECK(next_snapshot_ordinal > 0),
                    next_run_ordinal INTEGER NOT NULL CHECK(next_run_ordinal > 0),
                    next_item_ordinal INTEGER NOT NULL CHECK(next_item_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_reconciliation_scopes (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    reconciliation_scope_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, reconciliation_scope_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_reconciliation_scope_packet
                    ON packet_reconciliation_scopes(project_id, change_id, packet_id, ordinal);

                CREATE TABLE IF NOT EXISTS packet_evidence_snapshots (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    snapshot_id TEXT NOT NULL,
                    reconciliation_scope_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    contract_version TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    provider_scope_id TEXT NOT NULL,
                    provider_snapshot_id TEXT NOT NULL,
                    selection_ref TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    workspace_revision TEXT NOT NULL DEFAULT '',
                    surfaces_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    truncated INTEGER NOT NULL CHECK(truncated IN (0, 1)),
                    completeness_json TEXT NOT NULL,
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, snapshot_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, provider_id, provider_snapshot_id),
                    FOREIGN KEY(project_id, reconciliation_scope_id)
                        REFERENCES packet_reconciliation_scopes(project_id, reconciliation_scope_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_evidence_snapshot_scope
                    ON packet_evidence_snapshots(project_id, reconciliation_scope_id, ordinal);

                CREATE TABLE IF NOT EXISTS packet_evidence_claims (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    claim_id TEXT NOT NULL,
                    reconciliation_scope_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL DEFAULT '',
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    origin TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    claim_key TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_ref TEXT NOT NULL DEFAULT '',
                    assertion_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    required INTEGER NOT NULL CHECK(required IN (0, 1)),
                    dynamic INTEGER NOT NULL CHECK(dynamic IN (0, 1)),
                    contradicted INTEGER NOT NULL CHECK(contradicted IN (0, 1)),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, claim_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, reconciliation_scope_id)
                        REFERENCES packet_reconciliation_scopes(project_id, reconciliation_scope_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_evidence_claim_scope_key
                    ON packet_evidence_claims(
                        project_id, reconciliation_scope_id, origin, claim_type,
                        claim_key, status
                    );

                CREATE TABLE IF NOT EXISTS packet_reconciliation_runs (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    run_id TEXT NOT NULL,
                    reconciliation_scope_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    packet_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    superseded INTEGER NOT NULL CHECK(superseded IN (0, 1)),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, run_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, reconciliation_scope_id)
                        REFERENCES packet_reconciliation_scopes(project_id, reconciliation_scope_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, snapshot_id)
                        REFERENCES packet_evidence_snapshots(project_id, snapshot_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_reconciliation_run_scope
                    ON packet_reconciliation_runs(
                        project_id, reconciliation_scope_id, superseded, ordinal
                    );

                CREATE TABLE IF NOT EXISTS packet_reconciliation_items (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    item_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    reconciliation_scope_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    claim_type TEXT NOT NULL,
                    claim_key TEXT NOT NULL,
                    declared_claim_ids_json TEXT NOT NULL DEFAULT '[]',
                    observed_claim_ids_json TEXT NOT NULL DEFAULT '[]',
                    classification TEXT NOT NULL,
                    blocking INTEGER NOT NULL CHECK(blocking IN (0, 1)),
                    severity TEXT NOT NULL,
                    closure_condition TEXT NOT NULL,
                    next_action_json TEXT NOT NULL DEFAULT '{}',
                    disposition TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    policy_ref TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, item_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, run_id)
                        REFERENCES packet_reconciliation_runs(project_id, run_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, reconciliation_scope_id)
                        REFERENCES packet_reconciliation_scopes(project_id, reconciliation_scope_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_reconciliation_item_open
                    ON packet_reconciliation_items(
                        project_id, reconciliation_scope_id, run_id, blocking,
                        disposition
                    );

                CREATE TABLE IF NOT EXISTS packet_reconciliation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    reconciliation_scope_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, reconciliation_scope_id)
                        REFERENCES packet_reconciliation_scopes(project_id, reconciliation_scope_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_reconciliation_events_scope
                    ON packet_reconciliation_events(
                        project_id, reconciliation_scope_id, event_id
                    );

                CREATE TABLE IF NOT EXISTS packet_pressure_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_pressure_ordinal INTEGER NOT NULL CHECK(next_pressure_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_residual_risk_pressure (
                    project_id TEXT NOT NULL,
                    pressure_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    packet_revision INTEGER NOT NULL CHECK(packet_revision > 0),
                    semantic_confidence TEXT NOT NULL,
                    improvement_pressure TEXT NOT NULL,
                    residual_risks_json TEXT NOT NULL DEFAULT '[]',
                    challenge_questions_json TEXT NOT NULL DEFAULT '[]',
                    accepted_risk_refs_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, pressure_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_pressure_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    pressure_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(project_id, pressure_id)
                        REFERENCES packet_residual_risk_pressure(project_id, pressure_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_pressure_events_project_pressure
                    ON packet_pressure_events(project_id, pressure_id, event_id);

                CREATE TABLE IF NOT EXISTS assurance_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_finding_ordinal INTEGER NOT NULL CHECK(next_finding_ordinal > 0),
                    next_campaign_ordinal INTEGER NOT NULL CHECK(next_campaign_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS review_findings (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    packet_id TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    expected_correction TEXT NOT NULL,
                    scope_kind TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    source_anchor TEXT NOT NULL DEFAULT '',
                    implementation_ref TEXT NOT NULL DEFAULT '',
                    disposition TEXT NOT NULL,
                    disposition_rationale TEXT NOT NULL DEFAULT '',
                    disposition_reference TEXT NOT NULL DEFAULT '',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    supersedes_finding_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, finding_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS finding_packet_links (
                    project_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    expected_correction TEXT NOT NULL,
                    required_regression_evidence TEXT NOT NULL,
                    required_campaign_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, finding_id, packet_id),
                    FOREIGN KEY(project_id, finding_id)
                        REFERENCES review_findings(project_id, finding_id) ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS verification_campaigns (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_requirement_ids_json TEXT NOT NULL DEFAULT '[]',
                    target_packet_ids_json TEXT NOT NULL DEFAULT '[]',
                    target_finding_ids_json TEXT NOT NULL DEFAULT '[]',
                    environment_assumptions_json TEXT NOT NULL DEFAULT '[]',
                    exception_reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, campaign_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id)
                        REFERENCES change_units(project_id, change_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_cases (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    case_kind TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    required INTEGER NOT NULL CHECK(required IN (0, 1)),
                    result TEXT NOT NULL,
                    evidence_reference TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    covered_requirement_ids_json TEXT NOT NULL DEFAULT '[]',
                    covered_use_case_goal_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    covered_sequence_goal_node_ids_json TEXT NOT NULL DEFAULT '[]',
                    coverage_notes TEXT NOT NULL DEFAULT '',
                    out_of_scope_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, campaign_id, case_id),
                    FOREIGN KEY(project_id, campaign_id)
                        REFERENCES verification_campaigns(project_id, campaign_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS assurance_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    change_id TEXT NOT NULL DEFAULT '',
                    finding_id TEXT NOT NULL DEFAULT '',
                    campaign_id TEXT NOT NULL DEFAULT '',
                    case_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_assurance_events_project
                    ON assurance_events(project_id, event_id);

                CREATE TABLE IF NOT EXISTS execution_run_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_run_ordinal INTEGER NOT NULL CHECK(next_run_ordinal > 0),
                    next_handover_ordinal INTEGER NOT NULL CHECK(next_handover_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS implementation_runs (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    orchestrator_ref TEXT NOT NULL DEFAULT '',
                    external_ref TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL DEFAULT '',
                    completion_reference TEXT NOT NULL DEFAULT '',
                    terminal_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    terminal_at TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, run_id),
                    UNIQUE(project_id, ordinal),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS run_steps (
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    title TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dependency_step_ids_json TEXT NOT NULL DEFAULT '[]',
                    target_refs_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
                    retry_rationale TEXT NOT NULL DEFAULT '',
                    blocking_reason TEXT NOT NULL DEFAULT '',
                    next_expected_action TEXT NOT NULL DEFAULT '',
                    required INTEGER NOT NULL CHECK(required IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, run_id, step_id),
                    FOREIGN KEY(project_id, run_id)
                        REFERENCES implementation_runs(project_id, run_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    change_id TEXT NOT NULL DEFAULT '',
                    packet_id TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    step_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_run_events_project
                    ON run_events(project_id, event_id);

                CREATE TABLE IF NOT EXISTS handover_snapshots (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    handover_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL DEFAULT '',
                    packet_id TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    profile_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, handover_id),
                    UNIQUE(project_id, ordinal)
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(2, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(3, ?)",
                (_utc_now(),),
            )
            grounding_item_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(grounding_audit_items)"
                ).fetchall()
            }
            if "requirement_ids_json" not in grounding_item_columns:
                connection.execute(
                    """
                    ALTER TABLE grounding_audit_items
                    ADD COLUMN requirement_ids_json TEXT NOT NULL DEFAULT '[]'
                    """
                )
            grounding_anchor_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(grounding_audit_anchors)"
                ).fetchall()
            }
            for column in ("dependency_anchor_ids_json", "test_evidence_ids_json"):
                if column not in grounding_anchor_columns:
                    connection.execute(
                        f"ALTER TABLE grounding_audit_anchors ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(4, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(5, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(6, ?)",
                (_utc_now(),),
            )
            milestone_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(milestones)"
                ).fetchall()
            }
            if "request_id" not in milestone_columns:
                connection.execute(
                    "ALTER TABLE milestones ADD COLUMN request_id TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(7, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(8, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(9, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(10, ?)",
                (_utc_now(),),
            )
            baseline_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(baseline_imports)"
                ).fetchall()
            }
            if "previous_baseline_id" not in baseline_columns:
                connection.execute(
                    "ALTER TABLE baseline_imports ADD COLUMN previous_baseline_id TEXT NOT NULL DEFAULT ''"
                )
            if "origin" not in baseline_columns:
                connection.execute(
                    "ALTER TABLE baseline_imports ADD COLUMN origin TEXT NOT NULL DEFAULT 'srs_import'"
                )
            mapping_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(baseline_entity_mappings)"
                ).fetchall()
            }
            for column, definition in (
                ("entity_sha256", "TEXT NOT NULL DEFAULT ''"),
                ("continuity_status", "TEXT NOT NULL DEFAULT 'initial'"),
                ("previous_baseline_id", "TEXT NOT NULL DEFAULT ''"),
                ("previous_canonical_id", "TEXT NOT NULL DEFAULT ''"),
                ("classification_reason", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in mapping_columns:
                    connection.execute(
                        f"ALTER TABLE baseline_entity_mappings ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(11, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(12, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(13, ?)",
                (_utc_now(),),
            )
            bootstrap_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(bootstraps)"
                ).fetchall()
            }
            if "completion_handoff_json" not in bootstrap_columns:
                connection.execute(
                    "ALTER TABLE bootstraps ADD COLUMN completion_handoff_json TEXT NOT NULL DEFAULT '{}'"
                )
            self._ensure_columns(
                connection,
                "change_units",
                (("milestone_id", "TEXT NOT NULL DEFAULT ''"),),
            )
            self._ensure_columns(
                connection,
                "change_unit_revisions",
                (("milestone_id", "TEXT NOT NULL DEFAULT ''"),),
            )
            packet_state_columns = (
                ("readiness_state", "TEXT NOT NULL DEFAULT 'execution_ready'"),
                ("target_policy", "TEXT NOT NULL DEFAULT 'documental_only'"),
                ("objective", "TEXT NOT NULL DEFAULT ''"),
                ("rationale", "TEXT NOT NULL DEFAULT ''"),
                ("requirement_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("goal_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("in_scope_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("out_of_scope_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("invariants_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("unresolved_questions_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("navigation_audit_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("target_binding_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("candidate_set_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("context_snapshot_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("readiness_blockers_json", "TEXT NOT NULL DEFAULT '[]'"),
            )
            self._ensure_columns(
                connection, "implementation_packets", packet_state_columns
            )
            self._ensure_columns(
                connection,
                "implementation_packet_revisions",
                packet_state_columns,
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(14, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(15, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(16, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(17, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(18, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(19, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(20, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "navigation_audit_sequences",
                (
                    (
                        "next_snapshot_ordinal",
                        "INTEGER NOT NULL DEFAULT 1 CHECK(next_snapshot_ordinal > 0)",
                    ),
                ),
            )
            self._ensure_columns(
                connection,
                "navigation_audit_blocks",
                (
                    ("provider_window_state", "TEXT NOT NULL DEFAULT 'inactive'"),
                    ("provider_window_provider", "TEXT NOT NULL DEFAULT ''"),
                    ("provider_window_capability_version", "TEXT NOT NULL DEFAULT ''"),
                    ("provider_window_target_scope_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("provider_window_started_at", "TEXT NOT NULL DEFAULT ''"),
                    ("provider_window_snapshot_at", "TEXT NOT NULL DEFAULT ''"),
                ),
            )
            self._ensure_columns(
                connection,
                "navigation_candidate_sets",
                (("metadata_json", "TEXT NOT NULL DEFAULT '{}'"),),
            )
            self._ensure_columns(
                connection,
                "packet_construction_sequences",
                (
                    (
                        "next_proposal_ordinal",
                        "INTEGER NOT NULL DEFAULT 1 CHECK(next_proposal_ordinal > 0)",
                    ),
                ),
            )
            self._ensure_columns(
                connection,
                "campaign_cases",
                (
                    ("covered_requirement_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
                    (
                        "covered_use_case_goal_node_ids_json",
                        "TEXT NOT NULL DEFAULT '[]'",
                    ),
                    (
                        "covered_sequence_goal_node_ids_json",
                        "TEXT NOT NULL DEFAULT '[]'",
                    ),
                    ("coverage_notes", "TEXT NOT NULL DEFAULT ''"),
                    ("out_of_scope_reason", "TEXT NOT NULL DEFAULT ''"),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(21, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(22, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(23, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(24, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "provider_project_bindings",
                (("provider_context_id", "TEXT NOT NULL DEFAULT ''"),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(25, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "packet_unit_proposals",
                (("file_path", "TEXT NOT NULL DEFAULT ''"),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(26, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(27, ?)",
                (_utc_now(),),
            )
            packet_revision_columns = (
                (
                    "spec_revision",
                    "INTEGER NOT NULL DEFAULT 1 CHECK(spec_revision > 0)",
                ),
                (
                    "state_revision",
                    "INTEGER NOT NULL DEFAULT 1 CHECK(state_revision > 0)",
                ),
            )
            existing_packet_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(implementation_packets)"
                ).fetchall()
            }
            self._ensure_columns(
                connection, "implementation_packets", packet_revision_columns
            )
            if "spec_revision" not in existing_packet_columns:
                connection.execute(
                    "UPDATE implementation_packets SET spec_revision = current_revision"
                )
            self._ensure_columns(
                connection,
                "packet_construction_questions",
                (
                    ("dependency_keys_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("dependency_fingerprint", "TEXT NOT NULL DEFAULT ''"),
                    ("answer_source", "TEXT NOT NULL DEFAULT ''"),
                    ("answer_evidence_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ),
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS packet_advancement_receipts (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    spec_revision INTEGER NOT NULL CHECK(spec_revision > 0),
                    step_kind TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(
                        project_id, change_id, packet_id, spec_revision,
                        step_kind, input_fingerprint
                    ),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(28, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(29, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "navigation_provider_audit_snapshots",
                (
                    ("provider_snapshot_id", "TEXT NOT NULL DEFAULT ''"),
                    ("selection_ref", "TEXT NOT NULL DEFAULT ''"),
                    ("fingerprint", "TEXT NOT NULL DEFAULT ''"),
                    ("exact_identities_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("page_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("first_sequence", "INTEGER NOT NULL DEFAULT 0"),
                    ("last_sequence", "INTEGER NOT NULL DEFAULT 0"),
                ),
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_navigation_provider_snapshot_identity
                ON navigation_provider_audit_snapshots(
                    project_id, navigation_audit_id, provider,
                    provider_snapshot_id, fingerprint
                )
                WHERE provider_snapshot_id <> '' AND fingerprint <> ''
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(30, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(31, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(32, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(33, ?)",
                (_utc_now(),),
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS packet_unit_authoring_intents (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    client_unit_key TEXT NOT NULL,
                    intent_fingerprint TEXT NOT NULL,
                    unit_json TEXT NOT NULL,
                    candidate_window_json TEXT NOT NULL DEFAULT '[]',
                    state TEXT NOT NULL CHECK(state IN (
                        'pending', 'targets_committed', 'committed'
                    )),
                    spec_revision INTEGER NOT NULL CHECK(spec_revision > 0),
                    plan_revision INTEGER NOT NULL CHECK(plan_revision >= 0),
                    committed_plan_revision INTEGER NOT NULL DEFAULT 0
                        CHECK(committed_plan_revision >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    prepare_request_id TEXT NOT NULL DEFAULT '',
                    commit_request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id, packet_id, client_unit_key),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(project_id, change_id, packet_id)
                        ON DELETE RESTRICT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_unit_intent_prepare_request
                    ON packet_unit_authoring_intents(project_id, prepare_request_id)
                    WHERE prepare_request_id <> '';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_unit_intent_commit_request
                    ON packet_unit_authoring_intents(project_id, commit_request_id)
                    WHERE commit_request_id <> '';
                """
            )
            self._ensure_columns(
                connection,
                "packet_reconciliation_scopes",
                (
                    (
                        "applicability",
                        "TEXT NOT NULL DEFAULT 'deferred' CHECK(applicability IN ('applicable', 'deferred', 'not_applicable'))",
                    ),
                    (
                        "applicability_reason",
                        "TEXT NOT NULL DEFAULT 'work_plan_not_accepted'",
                    ),
                    ("applicability_plan_revision", "INTEGER NOT NULL DEFAULT 0"),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(34, ?)",
                (_utc_now(),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(35, ?)",
                (_utc_now(),),
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS packet_provider_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_outbox_ordinal INTEGER NOT NULL
                        CHECK(next_outbox_ordinal > 0),
                    next_receipt_ordinal INTEGER NOT NULL
                        CHECK(next_receipt_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_provider_bindings (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    provider_packet_ref TEXT NOT NULL,
                    provider_packet_revision INTEGER NOT NULL
                        CHECK(provider_packet_revision >= 0),
                    flow_spec_revision INTEGER NOT NULL
                        CHECK(flow_spec_revision > 0),
                    binding_epoch INTEGER NOT NULL CHECK(binding_epoch >= 0),
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 0),
                    flow_binding_generation INTEGER NOT NULL DEFAULT 1
                        CHECK(flow_binding_generation > 0),
                    provider_state TEXT NOT NULL,
                    run_phase TEXT NOT NULL DEFAULT 'idle',
                    provider_job_ref TEXT NOT NULL DEFAULT '',
                    current_step TEXT NOT NULL DEFAULT '',
                    last_receipt_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, change_id, packet_id, provider_kind),
                    UNIQUE(project_id, provider_kind, provider_packet_ref),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(
                            project_id, change_id, packet_id
                        ) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_provider_unit_correlations (
                    project_id TEXT NOT NULL,
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    flow_unit_ref TEXT NOT NULL,
                    provider_packet_ref TEXT NOT NULL,
                    provider_unit_ref TEXT NOT NULL,
                    provider_unit_number INTEGER
                        CHECK(provider_unit_number IS NULL OR provider_unit_number > 0),
                    unit_state TEXT NOT NULL,
                    provider_packet_revision INTEGER NOT NULL
                        CHECK(provider_packet_revision >= 0),
                    binding_epoch INTEGER NOT NULL CHECK(binding_epoch >= 0),
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(
                        project_id, change_id, packet_id,
                        provider_kind, flow_unit_ref
                    ),
                    UNIQUE(
                        project_id, provider_kind,
                        provider_packet_ref, provider_unit_ref
                    ),
                    FOREIGN KEY(project_id, change_id, packet_id, provider_kind)
                        REFERENCES packet_provider_bindings(
                            project_id, change_id, packet_id, provider_kind
                        ) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_provider_outbox (
                    project_id TEXT NOT NULL,
                    outbox_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    flow_binding_generation INTEGER NOT NULL DEFAULT 0
                        CHECK(flow_binding_generation >= 0),
                    flow_spec_revision INTEGER NOT NULL
                        CHECK(flow_spec_revision > 0),
                    operation TEXT NOT NULL CHECK(operation IN (
                        'add', 'edit', 'remove', 'start', 'stop'
                    )),
                    flow_unit_ref TEXT NOT NULL DEFAULT '',
                    delivery_fingerprint TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    command_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'pending', 'delivering', 'unknown',
                        'delivered', 'rejected'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    last_error TEXT NOT NULL DEFAULT '',
                    receipt_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, outbox_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, provider_kind, delivery_fingerprint),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(
                            project_id, change_id, packet_id
                        ) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS packet_provider_receipts (
                    project_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    outbox_id TEXT NOT NULL DEFAULT '',
                    provider_kind TEXT NOT NULL,
                    flow_spec_revision INTEGER NOT NULL
                        CHECK(flow_spec_revision > 0),
                    provider_contract_version TEXT NOT NULL,
                    provider_packet_ref TEXT NOT NULL,
                    provider_packet_revision INTEGER NOT NULL
                        CHECK(provider_packet_revision >= 0),
                    provider_state TEXT NOT NULL,
                    binding_epoch INTEGER NOT NULL CHECK(binding_epoch >= 0),
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 0),
                    observation_kind TEXT NOT NULL CHECK(observation_kind IN (
                        'command', 'status'
                    )),
                    receipt_fingerprint TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, receipt_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(
                        project_id, provider_kind, provider_packet_ref,
                        binding_epoch, event_seq, receipt_fingerprint
                    ),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(
                            project_id, change_id, packet_id
                        ) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_provider_outbox_recovery
                    ON packet_provider_outbox(project_id, state, ordinal);
                CREATE INDEX IF NOT EXISTS idx_packet_provider_receipts_packet
                    ON packet_provider_receipts(
                        project_id, change_id, packet_id, ordinal DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_packet_provider_units_packet
                    ON packet_provider_unit_correlations(
                        project_id, change_id, packet_id, provider_kind
                    );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(36, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "packet_work_plan_units",
                (
                    ("target_description", "TEXT NOT NULL DEFAULT ''"),
                    ("member_label", "TEXT NOT NULL DEFAULT ''"),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(37, ?)",
                (_utc_now(),),
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS packet_provider_workspace_review_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_review_ordinal INTEGER NOT NULL
                        CHECK(next_review_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS packet_provider_workspace_reviews (
                    project_id TEXT NOT NULL,
                    workspace_review_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    change_id TEXT NOT NULL,
                    packet_id TEXT NOT NULL,
                    spec_revision INTEGER NOT NULL CHECK(spec_revision > 0),
                    provider_kind TEXT NOT NULL,
                    provider_packet_ref TEXT NOT NULL,
                    provider_packet_revision INTEGER NOT NULL
                        CHECK(provider_packet_revision >= 0),
                    binding_epoch INTEGER NOT NULL CHECK(binding_epoch >= 0),
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 0),
                    provider_job_ref TEXT NOT NULL DEFAULT '',
                    provider_revision TEXT NOT NULL,
                    workspace_candidate_id TEXT NOT NULL DEFAULT '',
                    candidate_revision TEXT NOT NULL DEFAULT '',
                    provider_review_ref TEXT NOT NULL DEFAULT '',
                    completeness TEXT NOT NULL CHECK(completeness IN (
                        'complete', 'partial'
                    )),
                    disposition TEXT NOT NULL CHECK(disposition IN (
                        'approved', 'findings', 'rejected'
                    )),
                    reviewed_target_refs_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    provider_findings_json TEXT NOT NULL DEFAULT '[]',
                    existing_finding_ids_json TEXT NOT NULL DEFAULT '[]',
                    normalized_finding_ids_json TEXT NOT NULL DEFAULT '[]',
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, workspace_review_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(
                        project_id, provider_kind, provider_packet_ref,
                        binding_epoch, event_seq
                    ),
                    UNIQUE(project_id, fingerprint),
                    FOREIGN KEY(project_id, change_id, packet_id)
                        REFERENCES implementation_packets(
                            project_id, change_id, packet_id
                        ) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_packet_provider_reviews_current
                    ON packet_provider_workspace_reviews(
                        project_id, change_id, packet_id,
                        spec_revision, ordinal DESC
                    );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_provider_review_ref
                    ON packet_provider_workspace_reviews(
                        project_id, provider_kind, provider_review_ref
                    ) WHERE provider_review_ref <> '';
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(38, ?)",
                (_utc_now(),),
            )
            self._migrate_packet_provider_semantic_socket(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(39, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "packet_provider_unit_correlations",
                (
                    (
                        "provider_unit_number",
                        "INTEGER CHECK(provider_unit_number IS NULL OR provider_unit_number > 0)",
                    ),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(40, ?)",
                (_utc_now(),),
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaign_authority_sequences (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    next_obligation_ordinal INTEGER NOT NULL DEFAULT 1
                        CHECK(next_obligation_ordinal > 0),
                    next_oracle_ordinal INTEGER NOT NULL DEFAULT 1
                        CHECK(next_oracle_ordinal > 0),
                    next_attestation_ordinal INTEGER NOT NULL DEFAULT 1
                        CHECK(next_attestation_ordinal > 0),
                    next_command_ordinal INTEGER NOT NULL DEFAULT 1
                        CHECK(next_command_ordinal > 0),
                    next_receipt_ordinal INTEGER NOT NULL DEFAULT 1
                        CHECK(next_receipt_ordinal > 0)
                );

                CREATE TABLE IF NOT EXISTS campaign_plan_heads (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    current_revision INTEGER NOT NULL CHECK(current_revision > 0),
                    semantic_fingerprint TEXT NOT NULL,
                    constructibility TEXT NOT NULL,
                    qualification TEXT NOT NULL CHECK(qualification IN (
                        'current', 'legacy_unqualified'
                    )),
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    PRIMARY KEY(project_id, campaign_id),
                    FOREIGN KEY(project_id, campaign_id)
                        REFERENCES verification_campaigns(project_id, campaign_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_plan_revisions (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    contract_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    semantic_fingerprint TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, campaign_id, revision),
                    UNIQUE(project_id, campaign_id, semantic_fingerprint),
                    FOREIGN KEY(project_id, campaign_id)
                        REFERENCES verification_campaigns(project_id, campaign_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_case_revisions (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    payload_json TEXT NOT NULL,
                    semantic_fingerprint TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, campaign_id, case_id, revision),
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_obligations (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    obligation_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    kind TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    expected_behavior TEXT NOT NULL DEFAULT '',
                    prohibited_behavior TEXT NOT NULL DEFAULT '',
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    dependency_fingerprint TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, campaign_id, obligation_id),
                    UNIQUE(project_id, campaign_id, ordinal),
                    UNIQUE(project_id, campaign_id, dependency_fingerprint),
                    FOREIGN KEY(project_id, campaign_id)
                        REFERENCES verification_campaigns(project_id, campaign_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_case_obligation_bindings (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    obligation_id TEXT NOT NULL,
                    coverage_intent TEXT NOT NULL,
                    campaign_revision INTEGER NOT NULL CHECK(campaign_revision > 0),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    PRIMARY KEY(project_id, campaign_id, case_id, obligation_id),
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, campaign_id, obligation_id)
                        REFERENCES campaign_obligations(project_id, campaign_id, obligation_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS behavioral_oracles (
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    oracle_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    current_revision INTEGER NOT NULL CHECK(current_revision > 0),
                    current_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('current', 'stale', 'retired')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    PRIMARY KEY(project_id, oracle_id),
                    UNIQUE(project_id, ordinal)
                );

                CREATE TABLE IF NOT EXISTS behavioral_oracle_revisions (
                    project_id TEXT NOT NULL,
                    oracle_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision > 0),
                    contract_version TEXT NOT NULL,
                    oracle_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    semantic_fingerprint TEXT NOT NULL,
                    authority_reference TEXT NOT NULL,
                    dependency_fingerprint TEXT NOT NULL,
                    field_authority_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL CHECK(status IN ('draft', 'constructible', 'stale')),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, oracle_id, revision),
                    UNIQUE(project_id, oracle_id, semantic_fingerprint),
                    FOREIGN KEY(project_id, oracle_id)
                        REFERENCES behavioral_oracles(project_id, oracle_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_case_oracle_bindings (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    oracle_id TEXT NOT NULL,
                    oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                    oracle_fingerprint TEXT NOT NULL,
                    campaign_revision INTEGER NOT NULL CHECK(campaign_revision > 0),
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    PRIMARY KEY(project_id, campaign_id, case_id, oracle_id, oracle_revision),
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, oracle_id, oracle_revision)
                        REFERENCES behavioral_oracle_revisions(project_id, oracle_id, revision)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS oracle_questions (
                    project_id TEXT NOT NULL,
                    oracle_id TEXT NOT NULL,
                    oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                    question_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    question_scope TEXT NOT NULL DEFAULT 'source'
                        CHECK(question_scope IN ('source', 'oracle_ir')),
                    field_name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    choices_json TEXT NOT NULL,
                    required INTEGER NOT NULL CHECK(required IN (0, 1)),
                    answer_authority TEXT NOT NULL DEFAULT '',
                    answer_json TEXT NOT NULL DEFAULT 'null',
                    provenance_json TEXT NOT NULL DEFAULT '[]',
                    waiver_scope TEXT NOT NULL DEFAULT '',
                    answered_at TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, oracle_id, oracle_revision, question_id),
                    UNIQUE(project_id, oracle_id, oracle_revision, ordinal),
                    FOREIGN KEY(project_id, oracle_id, oracle_revision)
                        REFERENCES behavioral_oracle_revisions(project_id, oracle_id, revision)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_attestation_intents (
                    project_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    attestation_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    oracle_id TEXT NOT NULL,
                    oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                    oracle_fingerprint TEXT NOT NULL,
                    materialization_mode TEXT NOT NULL
                        CHECK(materialization_mode IN (
                            'orchestrator_source', 'deterministic_oracle_ir'
                        )),
                    authority_input_fingerprint TEXT NOT NULL,
                    source_manifest_digest TEXT NOT NULL,
                    source_manifest_json TEXT NOT NULL,
                    oracle_ir_contract_version TEXT NOT NULL DEFAULT '',
                    oracle_ir_operator_profile TEXT NOT NULL DEFAULT '',
                    oracle_ir_fingerprint TEXT NOT NULL DEFAULT '',
                    oracle_ir_json TEXT NOT NULL DEFAULT '{}',
                    requested_capability_json TEXT NOT NULL DEFAULT '{}',
                    requested_capability_fingerprint TEXT NOT NULL DEFAULT '',
                    harness_json TEXT NOT NULL DEFAULT '{"disposition":"repository","participants":[]}',
                    harness_fingerprint TEXT NOT NULL DEFAULT '',
                    authority_reference TEXT NOT NULL,
                    state TEXT NOT NULL,
                    provider_materialization_ref TEXT NOT NULL DEFAULT '',
                    representation_fingerprint TEXT NOT NULL DEFAULT '',
                    basis_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, attestation_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, campaign_id, case_id, oracle_id,
                           oracle_revision, materialization_mode,
                           authority_input_fingerprint,
                           requested_capability_fingerprint),
                    CHECK(
                        (
                            materialization_mode = 'orchestrator_source'
                            AND source_manifest_digest <> ''
                            AND oracle_ir_contract_version = ''
                            AND oracle_ir_operator_profile = ''
                            AND oracle_ir_fingerprint = ''
                            AND oracle_ir_json = '{}'
                            AND (
                                (requested_capability_json = '{}'
                                 AND requested_capability_fingerprint = '')
                                OR
                                (requested_capability_json <> '{}'
                                 AND requested_capability_fingerprint <> '')
                            )
                        ) OR (
                            materialization_mode = 'deterministic_oracle_ir'
                            AND source_manifest_digest = ''
                            AND source_manifest_json = '{}'
                            AND oracle_ir_contract_version <> ''
                            AND oracle_ir_operator_profile <> ''
                            AND oracle_ir_fingerprint <> ''
                            AND oracle_ir_json <> '{}'
                            AND requested_capability_json <> '{}'
                            AND requested_capability_fingerprint <> ''
                        )
                    ),
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, oracle_id, oracle_revision)
                        REFERENCES behavioral_oracle_revisions(project_id, oracle_id, revision)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS test_provider_outbox (
                    project_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    delivery_fingerprint TEXT NOT NULL,
                    command_fingerprint TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'pending', 'delivering', 'unknown', 'delivered', 'rejected'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    last_error TEXT NOT NULL DEFAULT '',
                    receipt_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    retry_of_command_id TEXT NOT NULL DEFAULT '',
                    retry_rationale TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, command_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, provider_kind, delivery_fingerprint),
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS test_provider_receipts (
                    project_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                    command_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    provider_event_seq INTEGER NOT NULL CHECK(provider_event_seq >= 0),
                    receipt_fingerprint TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    evidence_disposition TEXT NOT NULL,
                    attestation_state TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, receipt_id),
                    UNIQUE(project_id, ordinal),
                    UNIQUE(project_id, command_id, provider_event_seq, receipt_fingerprint),
                    FOREIGN KEY(project_id, command_id)
                        REFERENCES test_provider_outbox(project_id, command_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS campaign_authority_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id)
                        ON DELETE RESTRICT,
                    campaign_id TEXT NOT NULL DEFAULT '',
                    case_id TEXT NOT NULL DEFAULT '',
                    oracle_id TEXT NOT NULL DEFAULT '',
                    attestation_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    semantic_revision INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_campaign_plan_current
                    ON campaign_plan_heads(project_id, constructibility, updated_at);
                CREATE INDEX IF NOT EXISTS idx_campaign_obligation_decision
                    ON campaign_obligations(project_id, campaign_id, decision, ordinal);
                CREATE INDEX IF NOT EXISTS idx_oracle_status
                    ON behavioral_oracles(project_id, status, ordinal);
                CREATE INDEX IF NOT EXISTS idx_attestation_case
                    ON campaign_attestation_intents(
                        project_id, campaign_id, case_id, ordinal DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_test_provider_outbox_recovery
                    ON test_provider_outbox(project_id, state, ordinal);
                CREATE INDEX IF NOT EXISTS idx_test_provider_receipt_command
                    ON test_provider_receipts(project_id, command_id, ordinal DESC);
                CREATE INDEX IF NOT EXISTS idx_campaign_authority_events
                    ON campaign_authority_events(project_id, campaign_id, event_id);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(41, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "campaign_attestation_intents",
                (
                    (
                        "harness_json",
                        'TEXT NOT NULL DEFAULT \'{"disposition":"repository","participants":[]}\'',
                    ),
                    ("harness_fingerprint", "TEXT NOT NULL DEFAULT ''"),
                ),
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaign_execution_evidence (
                    project_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    campaign_revision INTEGER NOT NULL CHECK(campaign_revision > 0),
                    case_id TEXT NOT NULL,
                    case_revision INTEGER NOT NULL CHECK(case_revision > 0),
                    oracle_id TEXT NOT NULL,
                    oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                    oracle_fingerprint TEXT NOT NULL,
                    attestation_id TEXT NOT NULL,
                    attestation_state TEXT NOT NULL,
                    provider_kind TEXT NOT NULL,
                    provider_test_ref TEXT NOT NULL DEFAULT '',
                    materialization_ref TEXT NOT NULL,
                    materialization_revision INTEGER NOT NULL
                        CHECK(materialization_revision >= 0),
                    obligation_bindings_json TEXT NOT NULL,
                    obligation_binding_fingerprint TEXT NOT NULL,
                    execution_attempt INTEGER NOT NULL CHECK(execution_attempt > 0),
                    operation TEXT NOT NULL,
                    technical_state TEXT NOT NULL,
                    provider_disposition TEXT NOT NULL,
                    effective_disposition TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    evidence_reference TEXT NOT NULL,
                    observed_current INTEGER NOT NULL CHECK(observed_current IN (0, 1)),
                    authoritative_at_recording INTEGER NOT NULL
                        CHECK(authoritative_at_recording IN (0, 1)),
                    complete INTEGER NOT NULL CHECK(complete IN (0, 1)),
                    integrity_preserved INTEGER NOT NULL
                        CHECK(integrity_preserved IN (0, 1)),
                    basis_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(project_id, evidence_id),
                    UNIQUE(project_id, receipt_id),
                    FOREIGN KEY(project_id, receipt_id)
                        REFERENCES test_provider_receipts(project_id, receipt_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, campaign_id, case_id)
                        REFERENCES campaign_cases(project_id, campaign_id, case_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, oracle_id, oracle_revision)
                        REFERENCES behavioral_oracle_revisions(
                            project_id, oracle_id, revision
                        ) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_campaign_evidence_current
                    ON campaign_execution_evidence(
                        project_id, campaign_id, case_id, observed_at DESC
                    );
                CREATE INDEX IF NOT EXISTS idx_campaign_evidence_receipt
                    ON campaign_execution_evidence(project_id, receipt_id);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(42, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "test_provider_outbox",
                (
                    ("retry_of_command_id", "TEXT NOT NULL DEFAULT ''"),
                    ("retry_rationale", "TEXT NOT NULL DEFAULT ''"),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(43, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "behavioral_oracle_revisions",
                (("field_authority_json", "TEXT NOT NULL DEFAULT '{}'"),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(44, ?)",
                (_utc_now(),),
            )
            self._ensure_columns(
                connection,
                "oracle_questions",
                (("question_scope", "TEXT NOT NULL DEFAULT 'source'"),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(45, ?)",
                (_utc_now(),),
            )
            self._migrate_dual_mode_attestation_intents(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(46, ?)",
                (_utc_now(),),
            )
            migration_47_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 47"
            ).fetchone()
            self._ensure_columns(
                connection,
                "packet_provider_bindings",
                (
                    (
                        "flow_binding_generation",
                        "INTEGER NOT NULL DEFAULT 1 CHECK(flow_binding_generation > 0)",
                    ),
                ),
            )
            self._ensure_columns(
                connection,
                "packet_provider_outbox",
                (
                    (
                        "flow_binding_generation",
                        "INTEGER NOT NULL DEFAULT 0 CHECK(flow_binding_generation >= 0)",
                    ),
                ),
            )
            if migration_47_applied is None:
                connection.execute(
                    """
                    UPDATE packet_provider_outbox
                    SET flow_binding_generation = COALESCE((
                        SELECT binding.flow_binding_generation
                        FROM packet_provider_bindings AS binding
                        WHERE binding.project_id = packet_provider_outbox.project_id
                          AND binding.change_id = packet_provider_outbox.change_id
                          AND binding.packet_id = packet_provider_outbox.packet_id
                          AND binding.provider_kind = packet_provider_outbox.provider_kind
                    ), 0)
                    WHERE flow_binding_generation = 0
                    """
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(47, ?)",
                (_utc_now(),),
            )
            self._migrate_source_attestation_capability(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(48, ?)",
                (_utc_now(),),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        table: str,
        columns: tuple[tuple[str, str], ...],
    ) -> None:
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, definition in columns:
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

    @staticmethod
    def _migrate_source_attestation_capability(
        connection: sqlite3.Connection,
    ) -> None:
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 48"
        ).fetchone()
        if applied is not None:
            return
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP INDEX IF EXISTS idx_attestation_case;
            ALTER TABLE campaign_attestation_intents
                RENAME TO campaign_attestation_intents_v47;

            CREATE TABLE campaign_attestation_intents (
                project_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                attestation_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                oracle_id TEXT NOT NULL,
                oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                oracle_fingerprint TEXT NOT NULL,
                materialization_mode TEXT NOT NULL
                    CHECK(materialization_mode IN (
                        'orchestrator_source', 'deterministic_oracle_ir'
                    )),
                authority_input_fingerprint TEXT NOT NULL,
                source_manifest_digest TEXT NOT NULL,
                source_manifest_json TEXT NOT NULL,
                oracle_ir_contract_version TEXT NOT NULL DEFAULT '',
                oracle_ir_operator_profile TEXT NOT NULL DEFAULT '',
                oracle_ir_fingerprint TEXT NOT NULL DEFAULT '',
                oracle_ir_json TEXT NOT NULL DEFAULT '{}',
                requested_capability_json TEXT NOT NULL DEFAULT '{}',
                requested_capability_fingerprint TEXT NOT NULL DEFAULT '',
                harness_json TEXT NOT NULL
                    DEFAULT '{"disposition":"repository","participants":[]}',
                harness_fingerprint TEXT NOT NULL DEFAULT '',
                authority_reference TEXT NOT NULL,
                state TEXT NOT NULL,
                provider_materialization_ref TEXT NOT NULL DEFAULT '',
                representation_fingerprint TEXT NOT NULL DEFAULT '',
                basis_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                request_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(project_id, attestation_id),
                UNIQUE(project_id, ordinal),
                UNIQUE(project_id, campaign_id, case_id, oracle_id,
                       oracle_revision, materialization_mode,
                       authority_input_fingerprint,
                       requested_capability_fingerprint),
                CHECK(
                    (
                        materialization_mode = 'orchestrator_source'
                        AND source_manifest_digest <> ''
                        AND oracle_ir_contract_version = ''
                        AND oracle_ir_operator_profile = ''
                        AND oracle_ir_fingerprint = ''
                        AND oracle_ir_json = '{}'
                        AND (
                            (requested_capability_json = '{}'
                             AND requested_capability_fingerprint = '')
                            OR
                            (requested_capability_json <> '{}'
                             AND requested_capability_fingerprint <> '')
                        )
                    ) OR (
                        materialization_mode = 'deterministic_oracle_ir'
                        AND source_manifest_digest = ''
                        AND source_manifest_json = '{}'
                        AND oracle_ir_contract_version <> ''
                        AND oracle_ir_operator_profile <> ''
                        AND oracle_ir_fingerprint <> ''
                        AND oracle_ir_json <> '{}'
                        AND requested_capability_json <> '{}'
                        AND requested_capability_fingerprint <> ''
                    )
                ),
                FOREIGN KEY(project_id, campaign_id, case_id)
                    REFERENCES campaign_cases(project_id, campaign_id, case_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(project_id, oracle_id, oracle_revision)
                    REFERENCES behavioral_oracle_revisions(
                        project_id, oracle_id, revision
                    ) ON DELETE RESTRICT
            );

            INSERT INTO campaign_attestation_intents(
                project_id, campaign_id, case_id, attestation_id, ordinal,
                oracle_id, oracle_revision, oracle_fingerprint,
                materialization_mode, authority_input_fingerprint,
                source_manifest_digest, source_manifest_json,
                oracle_ir_contract_version, oracle_ir_operator_profile,
                oracle_ir_fingerprint, oracle_ir_json,
                requested_capability_json, requested_capability_fingerprint,
                harness_json, harness_fingerprint, authority_reference,
                state, provider_materialization_ref, representation_fingerprint,
                basis_json, created_at, updated_at, actor, request_id
            )
            SELECT
                project_id, campaign_id, case_id, attestation_id, ordinal,
                oracle_id, oracle_revision, oracle_fingerprint,
                materialization_mode, authority_input_fingerprint,
                source_manifest_digest, source_manifest_json,
                oracle_ir_contract_version, oracle_ir_operator_profile,
                oracle_ir_fingerprint, oracle_ir_json,
                requested_capability_json, requested_capability_fingerprint,
                harness_json, harness_fingerprint, authority_reference,
                state, provider_materialization_ref, representation_fingerprint,
                basis_json, created_at, updated_at, actor, request_id
            FROM campaign_attestation_intents_v47;

            DROP TABLE campaign_attestation_intents_v47;
            CREATE INDEX idx_attestation_case
                ON campaign_attestation_intents(
                    project_id, campaign_id, case_id, ordinal DESC
                );
            COMMIT;
            """
        )

    @staticmethod
    def _migrate_dual_mode_attestation_intents(
        connection: sqlite3.Connection,
    ) -> None:
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 46"
        ).fetchone()
        if applied is not None:
            return
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(campaign_attestation_intents)"
            ).fetchall()
        }
        if "materialization_mode" in columns:
            return
        connection.executescript(
            """
            DROP INDEX IF EXISTS idx_attestation_case;
            ALTER TABLE campaign_attestation_intents
                RENAME TO campaign_attestation_intents_v1;

            CREATE TABLE campaign_attestation_intents (
                project_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                attestation_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                oracle_id TEXT NOT NULL,
                oracle_revision INTEGER NOT NULL CHECK(oracle_revision > 0),
                oracle_fingerprint TEXT NOT NULL,
                materialization_mode TEXT NOT NULL
                    CHECK(materialization_mode IN (
                        'orchestrator_source', 'deterministic_oracle_ir'
                    )),
                authority_input_fingerprint TEXT NOT NULL,
                source_manifest_digest TEXT NOT NULL,
                source_manifest_json TEXT NOT NULL,
                oracle_ir_contract_version TEXT NOT NULL DEFAULT '',
                oracle_ir_operator_profile TEXT NOT NULL DEFAULT '',
                oracle_ir_fingerprint TEXT NOT NULL DEFAULT '',
                oracle_ir_json TEXT NOT NULL DEFAULT '{}',
                requested_capability_json TEXT NOT NULL DEFAULT '{}',
                requested_capability_fingerprint TEXT NOT NULL DEFAULT '',
                harness_json TEXT NOT NULL,
                harness_fingerprint TEXT NOT NULL DEFAULT '',
                authority_reference TEXT NOT NULL,
                state TEXT NOT NULL,
                provider_materialization_ref TEXT NOT NULL DEFAULT '',
                representation_fingerprint TEXT NOT NULL DEFAULT '',
                basis_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                request_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(project_id, attestation_id),
                UNIQUE(project_id, ordinal),
                UNIQUE(project_id, campaign_id, case_id, oracle_id,
                       oracle_revision, materialization_mode,
                       authority_input_fingerprint,
                       requested_capability_fingerprint),
                CHECK(
                    (
                        materialization_mode = 'orchestrator_source'
                        AND source_manifest_digest <> ''
                        AND oracle_ir_contract_version = ''
                        AND oracle_ir_operator_profile = ''
                        AND oracle_ir_fingerprint = ''
                        AND oracle_ir_json = '{}'
                        AND (
                            (requested_capability_json = '{}'
                             AND requested_capability_fingerprint = '')
                            OR
                            (requested_capability_json <> '{}'
                             AND requested_capability_fingerprint <> '')
                        )
                    ) OR (
                        materialization_mode = 'deterministic_oracle_ir'
                        AND source_manifest_digest = ''
                        AND source_manifest_json = '{}'
                        AND oracle_ir_contract_version <> ''
                        AND oracle_ir_operator_profile <> ''
                        AND oracle_ir_fingerprint <> ''
                        AND oracle_ir_json <> '{}'
                        AND requested_capability_json <> '{}'
                        AND requested_capability_fingerprint <> ''
                    )
                ),
                FOREIGN KEY(project_id, campaign_id, case_id)
                    REFERENCES campaign_cases(project_id, campaign_id, case_id)
                    ON DELETE RESTRICT,
                FOREIGN KEY(project_id, oracle_id, oracle_revision)
                    REFERENCES behavioral_oracle_revisions(
                        project_id, oracle_id, revision
                    ) ON DELETE RESTRICT
            );

            INSERT INTO campaign_attestation_intents(
                project_id, campaign_id, case_id, attestation_id, ordinal,
                oracle_id, oracle_revision, oracle_fingerprint,
                materialization_mode, authority_input_fingerprint,
                source_manifest_digest, source_manifest_json,
                oracle_ir_contract_version, oracle_ir_operator_profile,
                oracle_ir_fingerprint, oracle_ir_json,
                requested_capability_json, requested_capability_fingerprint,
                harness_json, harness_fingerprint, authority_reference,
                state, provider_materialization_ref, representation_fingerprint,
                basis_json, created_at, updated_at, actor, request_id
            )
            SELECT
                project_id, campaign_id, case_id, attestation_id, ordinal,
                oracle_id, oracle_revision, oracle_fingerprint,
                'orchestrator_source', source_manifest_digest,
                source_manifest_digest, source_manifest_json,
                '', '', '', '{}', '{}', '',
                harness_json, harness_fingerprint, authority_reference,
                state, provider_materialization_ref, representation_fingerprint,
                basis_json, created_at, updated_at, actor, request_id
            FROM campaign_attestation_intents_v1;

            DROP TABLE campaign_attestation_intents_v1;
            CREATE INDEX idx_attestation_case
                ON campaign_attestation_intents(
                    project_id, campaign_id, case_id, ordinal DESC
                );
            """
        )

    @staticmethod
    def _migrate_packet_provider_semantic_socket(
        connection: sqlite3.Connection,
    ) -> None:
        binding_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(packet_provider_bindings)"
            ).fetchall()
        }
        if "next_action" in binding_columns and "current_step" not in binding_columns:
            connection.execute(
                "ALTER TABLE packet_provider_bindings "
                "RENAME COLUMN next_action TO current_step"
            )

        outbox_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(packet_provider_outbox)"
            ).fetchall()
        }
        if "delivery_fingerprint" in outbox_columns:
            return
        legacy_rows = connection.execute(
            "SELECT * FROM packet_provider_outbox ORDER BY project_id, ordinal"
        ).fetchall()
        connection.execute(
            "ALTER TABLE packet_provider_outbox RENAME TO packet_provider_outbox_v1"
        )
        connection.executescript(
            """
            CREATE TABLE packet_provider_outbox (
                project_id TEXT NOT NULL,
                outbox_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                change_id TEXT NOT NULL,
                packet_id TEXT NOT NULL,
                provider_kind TEXT NOT NULL,
                flow_spec_revision INTEGER NOT NULL CHECK(flow_spec_revision > 0),
                operation TEXT NOT NULL CHECK(operation IN (
                    'add', 'edit', 'remove', 'start', 'stop'
                )),
                flow_unit_ref TEXT NOT NULL DEFAULT '',
                delivery_fingerprint TEXT NOT NULL,
                command_json TEXT NOT NULL,
                command_fingerprint TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN (
                    'pending', 'delivering', 'unknown', 'delivered', 'rejected'
                )),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                last_error TEXT NOT NULL DEFAULT '',
                receipt_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                delivered_at TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL,
                request_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(project_id, outbox_id),
                UNIQUE(project_id, ordinal),
                UNIQUE(project_id, provider_kind, delivery_fingerprint),
                FOREIGN KEY(project_id, change_id, packet_id)
                    REFERENCES implementation_packets(
                        project_id, change_id, packet_id
                    ) ON DELETE RESTRICT
            );
            """
        )
        for row in legacy_rows:
            fingerprint = "retired-v1:" + str(row["command_fingerprint"] or "")
            command = {
                "contract_version": "flow.packet_provider.semantic.v2",
                "flow_session_ref": str(row["project_id"]),
                "flow_packet_ref": str(row["packet_id"]),
                "flow_spec_revision": int(row["flow_spec_revision"]),
                "flow_unit_ref": str(row["flow_unit_ref"] or "") or None,
                "operation": str(row["operation"]),
                "semantic_input": {},
                "delivery_fingerprint": fingerprint,
            }
            connection.execute(
                """
                INSERT INTO packet_provider_outbox(
                    project_id, outbox_id, ordinal, change_id, packet_id,
                    provider_kind, flow_spec_revision, operation, flow_unit_ref,
                    delivery_fingerprint, command_json, command_fingerprint,
                    state, attempts, last_error, receipt_id, created_at,
                    updated_at, delivered_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rejected', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row["project_id"]),
                    str(row["outbox_id"]),
                    int(row["ordinal"]),
                    str(row["change_id"]),
                    str(row["packet_id"]),
                    str(row["provider_kind"]),
                    int(row["flow_spec_revision"]),
                    str(row["operation"]),
                    str(row["flow_unit_ref"] or ""),
                    fingerprint,
                    json.dumps(command, sort_keys=True, separators=(",", ":")),
                    str(row["command_fingerprint"]),
                    int(row["attempts"] or 0),
                    "semantic_cutover_retired_legacy_command",
                    str(row["receipt_id"] or ""),
                    str(row["created_at"]),
                    str(row["updated_at"]),
                    str(row["delivered_at"] or ""),
                    str(row["actor"]),
                    str(row["request_id"] or ""),
                ),
            )
        connection.execute("DROP TABLE packet_provider_outbox_v1")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_provider_outbox_recovery "
            "ON packet_provider_outbox(project_id, state, ordinal)"
        )

    def migrate_grounding_provenance(self) -> None:
        """Add explicit evidence authority while preserving historical audits."""
        with self._transaction() as connection:
            for table, columns in {
                "grounding_audits": {"evidence_authority": "TEXT NOT NULL DEFAULT 'provider_snapshot'",
                                     "provenance_json": "TEXT NOT NULL DEFAULT '{}'"},
                "grounding_audit_anchors": {"source_excerpt": "TEXT NOT NULL DEFAULT ''"},
            }.items():
                existing = {row["name"] for row in connection.execute("PRAGMA table_info(" + table + ")")}
                for column, declaration in columns.items():
                    if column not in existing:
                        connection.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + declaration)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(52, ?)", (_utc_now(),))
