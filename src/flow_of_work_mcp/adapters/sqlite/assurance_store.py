"""Internal SQLite ledger mixin extracted from ledger_store.py."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    CampaignCaseDraft,
    CampaignCaseKind,
    CampaignCaseResult,
    CampaignDraft,
    CampaignEvidenceDraft,
    CampaignStatus,
    ChangeStatus,
    FindingDisposition,
    FindingDispositionDraft,
    GoalNodeType,
)
from flow_of_work_mcp.core.domain.assurance import (
    FixingPacketLinkDraft,
    RemediationRelationshipsDraft,
    ReviewFindingDraft,
    normalize_campaign_case_kind,
    validate_campaign_id,
    validate_case_id,
    validate_finding_id,
)
from flow_of_work_mcp.core.domain.change_control import validate_change_id
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_project_id,
)
from flow_of_work_mcp.core.errors import (
    AssuranceBlockedError,
    RequirementConflictError,
)

from flow_of_work_mcp.adapters.sqlite.common import _utc_now



class AssuranceStoreMixin:
    def record_finding(
        self,
        project_id: str,
        draft: ReviewFindingDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._change_row(connection, project_id, draft.change_id)
            if draft.packet_id:
                self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = connection.execute(
                    """
                    SELECT finding_id FROM review_findings
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._finding_value(connection, project_id, str(replay["finding_id"]))
            ordinal = self._next_assurance_ordinal(connection, project_id, "finding")
            finding_id = f"FIND-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO review_findings(
                    project_id, change_id, finding_id, ordinal, packet_id, severity,
                    title, rationale, expected_correction, scope_kind, scope_ref,
                    source_anchor, implementation_ref, disposition, created_at,
                    updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.change_id,
                    finding_id,
                    ordinal,
                    draft.packet_id,
                    draft.severity.value,
                    draft.title,
                    draft.rationale,
                    draft.expected_correction,
                    draft.scope_kind,
                    draft.scope_ref,
                    draft.source_anchor,
                    draft.implementation_ref,
                    FindingDisposition.OPEN.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=draft.change_id,
                finding_id=finding_id,
                event_type="finding_recorded",
                actor=actor,
                request_id=request_id,
                payload={"severity": draft.severity.value, "scope_kind": draft.scope_kind, "finding_kind": draft.finding_kind},
                occurred_at=occurred_at,
            )
            return self._finding_value(connection, project_id, finding_id)

    def finding_state(self, project_id: str, finding_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._finding_value(connection, project_id, finding_id)

    def intent_reassessment_replay(self, project_id, finding_id, assessment, *, actor, request_id):
        """Return the original scoped receipt before evaluating current authority."""
        project_id = validate_project_id(project_id)
        finding_id = validate_finding_id(finding_id)
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT finding_id, actor, payload_json FROM assurance_events "
                "WHERE project_id=? AND event_type='finding_intent_reassessed' AND request_id=?",
                (project_id, request_id),
            ).fetchone()
            if row is None:
                return None
            stored = json.loads(row["payload_json"])
            if row["finding_id"] != finding_id or row["actor"] != actor or stored["assessment"] != dict(assessment):
                raise RequirementConflictError("intent reassessment request conflicts with its immutable receipt")
            return stored["receipt"]

    def record_intent_reassessment(self, project_id, finding_id, assessment, *, actor, request_id, intent_context=None):
        project_id = validate_project_id(project_id)
        finding_id = validate_finding_id(finding_id)
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        with self._transaction() as connection:
            replay = self.intent_reassessment_replay(project_id, finding_id, assessment, actor=actor, request_id=request_id)
            if replay is not None:
                return replay
            finding = self._finding_row(connection, project_id, finding_id)
            receipt = {"project_id": project_id, "change_id": str(finding["change_id"]),
                       "finding_id": finding_id, "actor": actor, "request_id": request_id,
                       "assessment": dict(assessment), "intent_context": dict(intent_context or {}),
                       "provenance": "host_declared", "acceptance_inferred": False}
            event_id = self._append_assurance_event(connection, project_id=project_id,
                change_id=str(finding["change_id"]), finding_id=finding_id,
                event_type="finding_intent_reassessed", actor=actor, request_id=request_id,
                payload={"assessment": dict(assessment), "receipt": receipt}, occurred_at=_utc_now())
            receipt["event_id"] = event_id
            connection.execute("UPDATE assurance_events SET payload_json=? WHERE event_id=?",
                (json.dumps({"assessment": dict(assessment), "receipt": receipt}, sort_keys=True), event_id))
            return receipt

    def remediation_context(self, project_id, change_id, packet_id):
        with self._read_connection() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            rows = connection.execute(
                "SELECT payload_json FROM assurance_events WHERE project_id=? AND change_id=? "
                "AND event_type='remediation_relationships_linked' ORDER BY event_id DESC",
                (project_id, change_id),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                if payload.get("packet_id") == packet_id:
                    return {**payload, "predecessor_dependency_policy": payload.get("predecessor_dependency_policy", "materialized")}
            return None

    def findings_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        with self._read_connection() as connection:
            self._change_row(connection, project_id, change_id)
            rows = connection.execute(
                """
                SELECT finding_id FROM review_findings
                WHERE project_id = ? AND change_id = ?
                ORDER BY ordinal
                """,
                (project_id, change_id),
            ).fetchall()
            return [self._finding_value(connection, project_id, str(row["finding_id"])) for row in rows]

    def set_finding_disposition(
        self,
        project_id: str,
        finding_id: str,
        draft: FindingDispositionDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        finding_id = validate_finding_id(finding_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._finding_row(connection, project_id, finding_id)
            replay = self._assurance_event_for_request(
                connection, project_id, "finding_disposition_set", request_id
            )
            if replay is not None:
                return self._finding_value(connection, project_id, finding_id)
            if draft.supersedes_finding_id:
                self._finding_row(connection, project_id, draft.supersedes_finding_id)
            connection.execute(
                """
                UPDATE review_findings
                SET disposition = ?, disposition_rationale = ?,
                    disposition_reference = ?, evidence_refs_json = ?,
                    supersedes_finding_id = ?, updated_at = ?
                WHERE project_id = ? AND finding_id = ?
                """,
                (
                    draft.disposition.value,
                    draft.rationale,
                    draft.disposition_reference,
                    self._json(list(draft.evidence_refs)),
                    draft.supersedes_finding_id,
                    occurred_at,
                    project_id,
                    finding_id,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=str(row["change_id"]),
                finding_id=finding_id,
                event_type="finding_disposition_set",
                actor=actor,
                request_id=request_id,
                payload={
                    "disposition": draft.disposition.value,
                    "evidence_refs": list(draft.evidence_refs),
                    "disposition_reference": draft.disposition_reference,
                },
                occurred_at=occurred_at,
            )
            return self._finding_value(connection, project_id, finding_id)

    def link_fixing_packet(
        self,
        project_id: str,
        draft: FixingPacketLinkDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            finding = self._finding_row(connection, project_id, draft.finding_id)
            self._packet_row(connection, project_id, str(finding["change_id"]), draft.packet_id)
            for campaign_id in draft.required_campaign_ids:
                self._campaign_row(connection, project_id, campaign_id)
            replay = self._assurance_event_for_request(
                connection, project_id, "fixing_packet_linked", request_id
            )
            if replay is not None:
                return self._finding_value(connection, project_id, draft.finding_id)
            connection.execute(
                """
                INSERT OR REPLACE INTO finding_packet_links(
                    project_id, finding_id, change_id, packet_id,
                    expected_correction, required_regression_evidence,
                    required_campaign_ids_json, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.finding_id,
                    str(finding["change_id"]),
                    draft.packet_id,
                    draft.expected_correction,
                    draft.required_regression_evidence,
                    self._json(list(draft.required_campaign_ids)),
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=str(finding["change_id"]),
                finding_id=draft.finding_id,
                event_type="fixing_packet_linked",
                actor=actor,
                request_id=request_id,
                payload={"packet_id": draft.packet_id},
                occurred_at=occurred_at,
            )
            return self._finding_value(connection, project_id, draft.finding_id)

    def link_remediation_relationships(
        self,
        project_id: str,
        draft: RemediationRelationshipsDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        """Validate and attach remediation relations to an existing packet."""

        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        terminal_dispositions = {
            FindingDisposition.RESOLVED.value,
            FindingDisposition.ACCEPTED_EXCEPTION.value,
            FindingDisposition.SUPERSEDED.value,
            FindingDisposition.CANCELLED.value,
        }
        relationship_payload = {
            "packet_id": draft.packet_id,
            "predecessor_packet_id": draft.predecessor_packet_id,
            "finding_ids": sorted(draft.finding_ids),
            "required_regression_evidence": draft.required_regression_evidence,
            "required_campaign_ids": sorted(draft.required_campaign_ids),
        }
        if draft.predecessor_dependency_policy == "context_only":
            relationship_payload["predecessor_dependency_policy"] = "context_only"
        with self._transaction() as connection:
            self._change_row(connection, project_id, draft.change_id)
            self._packet_row(connection, project_id, draft.change_id, draft.packet_id)
            if request_id:
                replay = self._assurance_event_for_request(
                    connection,
                    project_id,
                    "remediation_relationships_linked",
                    request_id,
                )
                if replay is not None:
                    try:
                        payload = json.loads(str(replay["payload_json"] or "{}"))
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise RequirementConflictError(
                            "stored remediation replay payload is invalid"
                        ) from exc
                    if (
                        str(replay["change_id"]) != draft.change_id
                        or not isinstance(payload, dict)
                        or payload != relationship_payload
                    ):
                        raise RequirementConflictError(
                            "remediation request_id conflicts with durable history"
                        )
                    return self._remediation_packet_value(
                        connection, project_id, draft.change_id, draft.packet_id
                    )

            if draft.predecessor_dependency_policy == "context_only":
                mode = self.external_work_state(project_id, draft.change_id, draft.predecessor_packet_id)["consumption_mode"]
                if mode != "external_agent":
                    raise AssuranceBlockedError("context_only_requires_external_predecessor")
            if draft.predecessor_packet_id:
                self._packet_row(
                    connection,
                    project_id,
                    draft.change_id,
                    draft.predecessor_packet_id,
                )
            findings: list[sqlite3.Row] = []
            for finding_id in draft.finding_ids:
                finding = self._finding_row(connection, project_id, finding_id)
                if str(finding["change_id"]) != draft.change_id:
                    raise AssuranceBlockedError(
                        "remediation_finding_cross_change",
                        details={"finding_id": finding_id},
                    )
                disposition = str(finding["disposition"])
                if disposition in terminal_dispositions:
                    raise AssuranceBlockedError(
                        "remediation_finding_terminal",
                        details={"finding_id": finding_id, "disposition": disposition},
                    )
                findings.append(finding)
            for campaign_id in draft.required_campaign_ids:
                campaign = self._campaign_row(connection, project_id, campaign_id)
                if str(campaign["change_id"]) != draft.change_id:
                    raise AssuranceBlockedError(
                        "remediation_campaign_cross_change",
                        details={"campaign_id": campaign_id},
                    )

            if draft.predecessor_packet_id and draft.predecessor_dependency_policy == "materialized":
                connection.execute(
                    """
                    INSERT INTO packet_dependencies(
                        project_id, change_id, packet_id, depends_on_packet_id,
                        created_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        draft.change_id,
                        draft.packet_id,
                        draft.predecessor_packet_id,
                        occurred_at,
                        actor,
                        request_id,
                    ),
                )
                self._append_change_event(
                    connection,
                    project_id=project_id,
                    change_id=draft.change_id,
                    packet_id=draft.packet_id,
                    event_type="packet_dependency_linked",
                    actor=actor,
                    request_id=request_id,
                    payload={"depends_on_packet_id": draft.predecessor_packet_id},
                    occurred_at=occurred_at,
                )

            for finding in findings:
                finding_id = str(finding["finding_id"])
                connection.execute(
                    """
                    INSERT INTO finding_packet_links(
                        project_id, finding_id, change_id, packet_id,
                        expected_correction, required_regression_evidence,
                        required_campaign_ids_json, created_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        finding_id,
                        draft.change_id,
                        draft.packet_id,
                        str(finding["expected_correction"]),
                        draft.required_regression_evidence,
                        self._json(list(draft.required_campaign_ids)),
                        occurred_at,
                        actor,
                        request_id,
                    ),
                )
                self._append_assurance_event(
                    connection,
                    project_id=project_id,
                    change_id=draft.change_id,
                    finding_id=finding_id,
                    event_type="fixing_packet_linked",
                    actor=actor,
                    request_id=request_id,
                    payload={"packet_id": draft.packet_id},
                    occurred_at=occurred_at,
                )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=draft.change_id,
                event_type="remediation_relationships_linked",
                actor=actor,
                request_id=request_id,
                payload=relationship_payload,
                occurred_at=occurred_at,
            )
            return self._remediation_packet_value(
                connection, project_id, draft.change_id, draft.packet_id
            )

    def _remediation_packet_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, Any]:
        packet = self._packet_value(connection, project_id, change_id, packet_id)
        rows = connection.execute(
            """
            SELECT link.finding_id, link.required_regression_evidence,
                   link.required_campaign_ids_json, finding.title, finding.severity,
                   finding.disposition, finding.expected_correction
            FROM finding_packet_links AS link
            JOIN review_findings AS finding
              ON finding.project_id = link.project_id
             AND finding.finding_id = link.finding_id
            WHERE link.project_id = ? AND link.change_id = ? AND link.packet_id = ?
            ORDER BY link.finding_id
            """,
            (project_id, change_id, packet_id),
        ).fetchall()
        return {
            "project_id": project_id,
            "change_id": change_id,
            "packet": packet,
            "predecessor_packet_id": (self.remediation_context(project_id, change_id, packet_id) or {}).get("predecessor_packet_id", ""),
            "predecessor_dependency_policy": (self.remediation_context(project_id, change_id, packet_id) or {}).get("predecessor_dependency_policy", "materialized"),
            "findings": [
                {
                    "finding_id": str(row["finding_id"]),
                    "title": str(row["title"]),
                    "severity": str(row["severity"]),
                    "disposition": str(row["disposition"]),
                    "expected_correction": str(row["expected_correction"]),
                    "required_regression_evidence": str(row["required_regression_evidence"]),
                    "required_campaign_ids": self._json_string_list(
                        row["required_campaign_ids_json"]
                    ),
                }
                for row in rows
            ],
        }

    def create_campaign(
        self,
        project_id: str,
        draft: CampaignDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._change_row(connection, project_id, draft.change_id)
            for requirement_id in draft.target_requirement_ids:
                self._requirement_row(connection, project_id, requirement_id)
            for packet_id in draft.target_packet_ids:
                self._packet_row(connection, project_id, draft.change_id, packet_id)
            for finding_id in draft.target_finding_ids:
                finding = self._finding_row(connection, project_id, finding_id)
                if str(finding["change_id"]) != draft.change_id:
                    raise AssuranceBlockedError("campaign_finding_cross_change")
            if request_id:
                replay = connection.execute(
                    """
                    SELECT campaign_id FROM verification_campaigns
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    return self._campaign_value(connection, project_id, str(replay["campaign_id"]))
            ordinal = self._next_assurance_ordinal(connection, project_id, "campaign")
            campaign_id = f"CAMP-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO verification_campaigns(
                    project_id, change_id, campaign_id, ordinal, title, status,
                    target_requirement_ids_json, target_packet_ids_json,
                    target_finding_ids_json, environment_assumptions_json,
                    exception_reference, created_at, updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.change_id,
                    campaign_id,
                    ordinal,
                    draft.title,
                    CampaignStatus.PLANNED.value,
                    self._json(list(draft.target_requirement_ids)),
                    self._json(list(draft.target_packet_ids)),
                    self._json(list(draft.target_finding_ids)),
                    self._json(list(draft.environment_assumptions)),
                    draft.exception_reference,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=draft.change_id,
                campaign_id=campaign_id,
                event_type="campaign_created",
                actor=actor,
                request_id=request_id,
                payload={"title": draft.title},
                occurred_at=occurred_at,
            )
            return self._campaign_value(connection, project_id, campaign_id)

    def campaign_state(self, project_id: str, campaign_id: str) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._campaign_value(connection, project_id, campaign_id)

    def campaigns_for_change(self, project_id: str, change_id: str) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        with self._read_connection() as connection:
            self._change_row(connection, project_id, change_id)
            rows = connection.execute(
                """
                SELECT campaign_id FROM verification_campaigns
                WHERE project_id = ? AND change_id = ?
                ORDER BY ordinal
                """,
                (project_id, change_id),
            ).fetchall()
            return [self._campaign_value(connection, project_id, str(row["campaign_id"])) for row in rows]

    def add_campaign_case(
        self,
        project_id: str,
        draft: CampaignCaseDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            campaign = self._campaign_row(connection, project_id, draft.campaign_id)
            self._validate_campaign_case_coverage(connection, project_id, draft)
            replay = self._assurance_event_for_request(
                connection, project_id, "campaign_case_recorded", request_id
            )
            if replay is not None:
                return self._campaign_value(connection, project_id, draft.campaign_id)
            ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                    FROM campaign_cases WHERE project_id = ? AND campaign_id = ?
                    """,
                    (project_id, draft.campaign_id),
                ).fetchone()["ordinal"]
            )
            case_id = f"CASE-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO campaign_cases(
                    project_id, campaign_id, case_id, ordinal, title, purpose,
                    case_kind, evidence_kind, required, result, created_at,
                    updated_at, actor, request_id, covered_requirement_ids_json,
                    covered_use_case_goal_node_ids_json,
                    covered_sequence_goal_node_ids_json, coverage_notes,
                    out_of_scope_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    draft.campaign_id,
                    case_id,
                    ordinal,
                    draft.title,
                    draft.purpose,
                    draft.case_kind.value,
                    draft.evidence_kind.value,
                    1 if draft.required else 0,
                    CampaignCaseResult.PENDING.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                    self._json(list(draft.covered_requirement_ids)),
                    self._json(list(draft.covered_use_case_goal_node_ids)),
                    self._json(list(draft.covered_sequence_goal_node_ids)),
                    draft.coverage_notes,
                    draft.out_of_scope_reason,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=str(campaign["change_id"]),
                campaign_id=draft.campaign_id,
                case_id=case_id,
                event_type="campaign_case_recorded",
                actor=actor,
                request_id=request_id,
                payload={
                    "case_kind": draft.case_kind.value,
                    "normalized_case_kind": normalize_campaign_case_kind(
                        draft.case_kind,
                        draft.evidence_kind,
                        has_sequence_coverage=bool(draft.covered_sequence_goal_node_ids),
                        milestone_scoped=draft.case_kind == CampaignCaseKind.MILESTONE_ACCEPTANCE,
                    ),
                    "required": draft.required,
                    "covered_requirement_ids": list(draft.covered_requirement_ids),
                    "covered_use_case_goal_node_ids": list(draft.covered_use_case_goal_node_ids),
                    "covered_sequence_goal_node_ids": list(draft.covered_sequence_goal_node_ids),
                },
                occurred_at=occurred_at,
            )
            self._derive_campaign_status(connection, project_id, draft.campaign_id, occurred_at)
            return self._campaign_value(connection, project_id, draft.campaign_id)

    def record_campaign_evidence(
        self,
        project_id: str,
        draft: CampaignEvidenceDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            campaign = self._campaign_row(connection, project_id, draft.campaign_id)
            self._campaign_case_row(connection, project_id, draft.campaign_id, draft.case_id)
            replay = self._assurance_event_for_request(
                connection, project_id, "campaign_evidence_recorded", request_id
            )
            if replay is not None:
                return self._campaign_value(connection, project_id, draft.campaign_id)
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = ?, evidence_kind = ?, evidence_reference = ?,
                    metadata_json = ?, updated_at = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    draft.result.value,
                    draft.evidence_kind.value,
                    draft.reference,
                    self._json(dict(draft.metadata)),
                    occurred_at,
                    project_id,
                    draft.campaign_id,
                    draft.case_id,
                ),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=str(campaign["change_id"]),
                campaign_id=draft.campaign_id,
                case_id=draft.case_id,
                event_type="campaign_evidence_recorded",
                actor=actor,
                request_id=request_id,
                payload={
                    "result": draft.result.value,
                    "evidence_kind": draft.evidence_kind.value,
                    "reference": draft.reference,
                },
                occurred_at=occurred_at,
            )
            self._derive_campaign_status(connection, project_id, draft.campaign_id, occurred_at)
            return self._campaign_value(connection, project_id, draft.campaign_id)

    def set_campaign_disposition(
        self,
        project_id: str,
        campaign_id: str,
        status: CampaignStatus,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        status = CampaignStatus(status)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            campaign = self._campaign_row(connection, project_id, campaign_id)
            replay = self._assurance_event_for_request(
                connection, project_id, "campaign_disposition_set", request_id
            )
            if replay is not None:
                return self._campaign_value(connection, project_id, campaign_id)
            connection.execute(
                """
                UPDATE verification_campaigns
                SET status = ?, exception_reference = ?, updated_at = ?
                WHERE project_id = ? AND campaign_id = ?
                """,
                (status.value, disposition_reference, occurred_at, project_id, campaign_id),
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=str(campaign["change_id"]),
                campaign_id=campaign_id,
                event_type="campaign_disposition_set",
                actor=actor,
                request_id=request_id,
                payload={"status": status.value, "disposition_reference": disposition_reference},
                occurred_at=occurred_at,
            )
            return self._campaign_value(connection, project_id, campaign_id)

    def record_coverage_diagnostic(
        self,
        project_id: str,
        *,
        change_id: str,
        campaign_id: str,
        case_id: str,
        diagnostic: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        payload = dict(diagnostic)
        with self._transaction() as connection:
            campaign = self._campaign_row(connection, project_id, campaign_id)
            if str(campaign["change_id"]) != change_id:
                raise AssuranceBlockedError("coverage_diagnostic_cross_change")
            self._campaign_case_row(connection, project_id, campaign_id, case_id)
            replay = self._assurance_event_for_request(
                connection, project_id, "coverage_diagnostic_recorded", request_id
            )
            if replay is None:
                self._append_assurance_event(
                    connection,
                    project_id=project_id,
                    change_id=change_id,
                    campaign_id=campaign_id,
                    case_id=case_id,
                    event_type="coverage_diagnostic_recorded",
                    actor=actor,
                    request_id=request_id,
                    payload=payload,
                    occurred_at=occurred_at,
                )
        return {
            "project_id": project_id,
            "change_id": change_id,
            "campaign_id": campaign_id,
            "case_id": case_id,
            "diagnostic": payload,
            "recorded_at": occurred_at,
        }

    def accept_change(
        self,
        project_id: str,
        change_id: str,
        *,
        acceptance_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        acceptance_reference = required_text(acceptance_reference, "acceptance_reference")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            change = self._change_row(connection, project_id, change_id)
            replay = self._change_event_for_request(
                connection, project_id, change_id, "change_accepted", request_id
            )
            if replay is not None:
                return self._change_value(connection, project_id, change_id)
            revision = int(change["current_revision"]) + 1
            connection.execute(
                """
                UPDATE change_units
                SET status = ?, current_revision = ?, updated_at = ?
                WHERE project_id = ? AND change_id = ?
                """,
                (ChangeStatus.ACCEPTED.value, revision, occurred_at, project_id, change_id),
            )
            self._append_change_revision(
                connection,
                project_id=project_id,
                change_id=change_id,
                revision=revision,
                title=str(change["title"]),
                rationale=str(change["rationale"]),
                status=ChangeStatus.ACCEPTED.value,
                milestone_id=str(change["milestone_id"]),
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
                event_type="change_accepted",
                actor=actor,
                request_id=request_id,
                payload={"acceptance_reference": acceptance_reference},
                occurred_at=occurred_at,
            )
            self._append_assurance_event(
                connection,
                project_id=project_id,
                change_id=change_id,
                event_type="change_acceptance_recorded",
                actor=actor,
                request_id=request_id,
                payload={"acceptance_reference": acceptance_reference},
                occurred_at=occurred_at,
            )
            return self._change_value(connection, project_id, change_id)

    def _next_assurance_ordinal(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        kind: str,
    ) -> int:
        connection.execute(
            """
            INSERT OR IGNORE INTO assurance_sequences(
                project_id, next_finding_ordinal, next_campaign_ordinal
            ) VALUES (?, 1, 1)
            """,
            (project_id,),
        )
        column = {
            "finding": "next_finding_ordinal",
            "campaign": "next_campaign_ordinal",
        }[kind]
        ordinal = int(
            connection.execute(
                f"SELECT {column} FROM assurance_sequences WHERE project_id = ?",
                (project_id,),
            ).fetchone()[column]
        )
        connection.execute(
            f"UPDATE assurance_sequences SET {column} = ? WHERE project_id = ?",
            (ordinal + 1, project_id),
        )
        return ordinal

    def _finding_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        finding_id: str,
    ) -> sqlite3.Row:
        project_id = validate_project_id(project_id)
        finding_id = validate_finding_id(finding_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM review_findings WHERE project_id = ? AND finding_id = ?",
            (project_id, finding_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown finding in project {project_id}: {finding_id}")
        return row

    def _finding_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        finding_id: str,
    ) -> Mapping[str, Any]:
        row = self._finding_row(connection, project_id, finding_id)
        links = [
            {
                "packet_id": str(item["packet_id"]),
                "expected_correction": str(item["expected_correction"]),
                "required_regression_evidence": str(item["required_regression_evidence"]),
                "required_campaign_ids": self._json_string_list(item["required_campaign_ids_json"]),
            }
            for item in connection.execute(
                """
                SELECT packet_id, expected_correction, required_regression_evidence,
                       required_campaign_ids_json
                FROM finding_packet_links
                WHERE project_id = ? AND finding_id = ?
                ORDER BY packet_id
                """,
                (project_id, finding_id),
            ).fetchall()
        ]
        events = [
            dict(item)
            for item in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at
                FROM assurance_events
                WHERE project_id = ? AND finding_id = ?
                ORDER BY event_id
                """,
                (project_id, finding_id),
            ).fetchall()
        ]
        for event in events:
            event["payload"] = json.loads(event.pop("payload_json"))
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "finding_id": str(row["finding_id"]),
            "packet_id": str(row["packet_id"]),
            "severity": str(row["severity"]),
            "finding_kind": next((event["payload"].get("finding_kind", "unspecified") for event in events if event["event_type"] == "finding_recorded"), "unspecified"),
            "latest_intent_assessment": next((event["payload"].get("receipt") for event in reversed(events) if event["event_type"] == "finding_intent_reassessed"), None),
            "title": str(row["title"]),
            "rationale": str(row["rationale"]),
            "expected_correction": str(row["expected_correction"]),
            "scope_kind": str(row["scope_kind"]),
            "scope_ref": str(row["scope_ref"]),
            "source_anchor": str(row["source_anchor"]),
            "implementation_ref": str(row["implementation_ref"]),
            "disposition": str(row["disposition"]),
            "disposition_rationale": str(row["disposition_rationale"]),
            "disposition_reference": str(row["disposition_reference"]),
            "evidence_refs": self._json_string_list(row["evidence_refs_json"]),
            "supersedes_finding_id": str(row["supersedes_finding_id"]),
            "fixing_packets": links,
            "events": events,
        }

    def _campaign_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
    ) -> sqlite3.Row:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        self._ensure_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM verification_campaigns WHERE project_id = ? AND campaign_id = ?",
            (project_id, campaign_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown campaign in project {project_id}: {campaign_id}"
            )
        return row

    def _campaign_case_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> sqlite3.Row:
        validate_case_id(case_id)
        self._campaign_row(connection, project_id, campaign_id)
        row = connection.execute(
            """
            SELECT * FROM campaign_cases
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
            """,
            (project_id, campaign_id, case_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown campaign case: {case_id}")
        return row

    def _campaign_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
    ) -> Mapping[str, Any]:
        row = self._campaign_row(connection, project_id, campaign_id)
        cases = []
        for case in connection.execute(
            """
            SELECT * FROM campaign_cases
            WHERE project_id = ? AND campaign_id = ?
            ORDER BY ordinal
            """,
            (project_id, campaign_id),
        ).fetchall():
            covered_requirement_ids = self._json_string_list(case["covered_requirement_ids_json"])
            covered_use_case_goal_node_ids = self._json_string_list(
                case["covered_use_case_goal_node_ids_json"]
            )
            covered_sequence_goal_node_ids = self._json_string_list(
                case["covered_sequence_goal_node_ids_json"]
            )
            case_kind = str(case["case_kind"])
            evidence_kind = str(case["evidence_kind"])
            cases.append(
                {
                    "case_id": str(case["case_id"]),
                    "title": str(case["title"]),
                    "purpose": str(case["purpose"]),
                    "case_kind": case_kind,
                    "normalized_case_kind": normalize_campaign_case_kind(
                        case_kind,
                        evidence_kind,
                        has_sequence_coverage=bool(covered_sequence_goal_node_ids),
                        milestone_scoped=case_kind == CampaignCaseKind.MILESTONE_ACCEPTANCE.value,
                    ),
                    "evidence_kind": evidence_kind,
                    "required": bool(case["required"]),
                    "result": str(case["result"]),
                    "evidence_reference": str(case["evidence_reference"]),
                    "metadata": self._json_object(case["metadata_json"]),
                    "covered_requirement_ids": covered_requirement_ids,
                    "covered_use_case_goal_node_ids": covered_use_case_goal_node_ids,
                    "covered_sequence_goal_node_ids": covered_sequence_goal_node_ids,
                    "coverage_notes": str(case["coverage_notes"]),
                    "out_of_scope_reason": str(case["out_of_scope_reason"]),
                }
            )
        events = [
            dict(item)
            for item in connection.execute(
                """
                SELECT event_id, event_type, actor, request_id, payload_json, occurred_at
                FROM assurance_events
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY event_id
                """,
                (project_id, campaign_id),
            ).fetchall()
        ]
        for event in events:
            event["payload"] = json.loads(event.pop("payload_json"))
        return {
            "project_id": str(row["project_id"]),
            "change_id": str(row["change_id"]),
            "campaign_id": str(row["campaign_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "target_requirement_ids": self._json_string_list(row["target_requirement_ids_json"]),
            "target_packet_ids": self._json_string_list(row["target_packet_ids_json"]),
            "target_finding_ids": self._json_string_list(row["target_finding_ids_json"]),
            "environment_assumptions": self._json_string_list(row["environment_assumptions_json"]),
            "exception_reference": str(row["exception_reference"]),
            "cases": cases,
            "events": events,
        }

    def _derive_campaign_status(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        occurred_at: str,
    ) -> None:
        campaign = self._campaign_row(connection, project_id, campaign_id)
        if str(campaign["status"]) in {
            CampaignStatus.ACCEPTED_EXCEPTION.value,
            CampaignStatus.CANCELLED.value,
        }:
            return
        cases = connection.execute(
            """
            SELECT required, result FROM campaign_cases
            WHERE project_id = ? AND campaign_id = ?
            """,
            (project_id, campaign_id),
        ).fetchall()
        if not cases:
            status = CampaignStatus.PLANNED.value
        elif any(bool(case["required"]) and str(case["result"]) == "failed" for case in cases):
            status = CampaignStatus.FAILED.value
        elif all((not bool(case["required"])) or str(case["result"]) == "passed" for case in cases):
            status = CampaignStatus.PASSED.value
        elif any(str(case["result"]) != "pending" for case in cases):
            status = CampaignStatus.PARTIAL.value
        else:
            status = CampaignStatus.PLANNED.value
        if str(campaign["status"]) != status:
            connection.execute(
                """
                UPDATE verification_campaigns
                SET status = ?, updated_at = ?
                WHERE project_id = ? AND campaign_id = ?
                """,
                (status, occurred_at, project_id, campaign_id),
            )

    def _validate_campaign_case_coverage(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        draft: CampaignCaseDraft,
    ) -> None:
        for requirement_id in draft.covered_requirement_ids:
            self._requirement_row(connection, project_id, requirement_id)
        use_case_ids: set[str] = set()
        sequence_ids: set[str] = set()
        for goal_node_id in draft.covered_use_case_goal_node_ids:
            goal_node_id = self._validate_goal_node_id(goal_node_id)
            row = self._goal_node_row(connection, project_id, goal_node_id)
            if str(row["node_type"]) != GoalNodeType.USE_CASE.value:
                raise AssuranceBlockedError(
                    "campaign_coverage_wrong_goal_type",
                    details={
                        "goal_node_id": goal_node_id,
                        "expected": GoalNodeType.USE_CASE.value,
                        "actual": str(row["node_type"]),
                    },
                )
            use_case_ids.add(goal_node_id)
        for goal_node_id in draft.covered_sequence_goal_node_ids:
            goal_node_id = self._validate_goal_node_id(goal_node_id)
            row = self._goal_node_row(connection, project_id, goal_node_id)
            if str(row["node_type"]) != GoalNodeType.SEQUENCE.value:
                raise AssuranceBlockedError(
                    "campaign_coverage_wrong_goal_type",
                    details={
                        "goal_node_id": goal_node_id,
                        "expected": GoalNodeType.SEQUENCE.value,
                        "actual": str(row["node_type"]),
                    },
                )
            sequence_ids.add(goal_node_id)
        normalized = normalize_campaign_case_kind(
            draft.case_kind,
            draft.evidence_kind,
            has_sequence_coverage=bool(sequence_ids),
            milestone_scoped=draft.case_kind == CampaignCaseKind.MILESTONE_ACCEPTANCE,
        )
        if normalized == CampaignCaseKind.LIVE_SEQUENCE.value and not draft.covered_requirement_ids:
            raise AssuranceBlockedError("campaign_live_coverage_requires_requirements")
        if normalized == CampaignCaseKind.LIVE_SEQUENCE.value and not sequence_ids:
            raise AssuranceBlockedError("campaign_live_coverage_requires_sequence")
        if normalized == CampaignCaseKind.LIVE_SEQUENCE.value and sequence_ids and not use_case_ids:
            raise AssuranceBlockedError("campaign_live_sequence_requires_use_case")
        if normalized == CampaignCaseKind.LIVE_SEQUENCE.value and not self._coverage_has_goal_link(
            connection,
            project_id,
            use_case_ids,
            sequence_ids,
        ):
            raise AssuranceBlockedError("campaign_live_sequence_unlinked")

    @staticmethod
    def _coverage_has_goal_link(
        connection: sqlite3.Connection,
        project_id: str,
        use_case_ids: set[str],
        sequence_ids: set[str],
    ) -> bool:
        if not sequence_ids:
            return True
        if not use_case_ids:
            return False
        row = connection.execute(
            """
            SELECT 1 FROM goal_edges
            WHERE project_id = ?
              AND source_goal_id IN ({use_placeholders})
              AND target_goal_id IN ({sequence_placeholders})
            LIMIT 1
            """.format(
                use_placeholders=",".join("?" for _ in use_case_ids),
                sequence_placeholders=",".join("?" for _ in sequence_ids),
            ),
            (project_id, *sorted(use_case_ids), *sorted(sequence_ids)),
        ).fetchone()
        return row is not None

    @staticmethod
    def _append_assurance_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        event_type: str,
        actor: str,
        request_id: str,
        payload: Mapping[str, object],
        occurred_at: str,
        change_id: str = "",
        finding_id: str = "",
        campaign_id: str = "",
        case_id: str = "",
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO assurance_events(
                project_id, change_id, finding_id, campaign_id, case_id,
                event_type, actor, request_id, payload_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                change_id,
                finding_id,
                campaign_id,
                case_id,
                event_type,
                actor,
                str(request_id or ""),
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _assurance_event_for_request(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT event_id, change_id, payload_json FROM assurance_events
            WHERE project_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, event_type, str(request_id)),
        ).fetchone()
