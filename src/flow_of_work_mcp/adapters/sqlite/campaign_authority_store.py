"""Revisioned campaign, obligation, oracle and attestation persistence."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from typing import Any, Mapping, Sequence

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.assurance import (
    CampaignStatus,
    validate_campaign_id,
    validate_case_id,
)
from flow_of_work_mcp.core.domain.campaign_authority import (
    CAMPAIGN_PLAN_CONTRACT_VERSION,
    ORACLE_SNAPSHOT_CONTRACT_VERSION,
    BehavioralOracleDraft,
    CampaignCaseSemanticDraft,
    CampaignConstructibility,
    CampaignObligationDecision,
    CampaignObligationKind,
    CampaignScopeDraft,
    MaterializationAttestationState,
    OracleAnswerAuthority,
    TestProviderMaterializationMode,
    canonical_materializer_capability,
    canonical_semantic_value,
    canonical_test_harness,
    deterministic_materialization_failure_receipt,
    deterministic_materialization_retry_eligible,
    semantic_fingerprint,
    source_manifest_digest,
    validate_obligation_id,
    validate_oracle_id,
)
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.change_control import (
    validate_change_id,
    validate_packet_id,
)
from flow_of_work_mcp.core.domain.oracle_ir_projection import compile_oracle_ir
from flow_of_work_mcp.core.errors import AssuranceBlockedError, RequirementConflictError


_ORACLE_REQUIRED_FIELDS = (
    "preconditions",
    "stimulus",
    "input_domain",
    "expected_observations",
    "invariants",
    "forbidden_effects",
    "tolerances",
    "expected_failure_transitions",
    "oracle_violation_conditions",
    "execution_class",
    "verification_intent",
)
_ORACLE_IR_ANSWERABLE_FIELDS = frozenset(
    {
        "operator_profile",
        "fixture_bindings",
        *_ORACLE_REQUIRED_FIELDS,
    }
)
_ORACLE_EXPLICIT_EMPTY_FIELDS = frozenset(
    {
        "preconditions",
        "input_domain",
        "invariants",
        "forbidden_effects",
        "tolerances",
        "expected_failure_transitions",
        "oracle_violation_conditions",
    }
)


class CampaignAuthorityStoreMixin:
    """Owns the qualified campaign aggregate without rewriting legacy history."""

    def start_campaign_authority(
        self,
        project_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        first_case: CampaignCaseSemanticDraft | None,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        title = required_text(title, "title")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        occurred_at = _utc_now()
        input_payload = {
            "title": title,
            "scope": scope.as_payload(),
            "first_case": first_case.as_payload() if first_case is not None else None,
        }
        input_fingerprint = semantic_fingerprint(input_payload)
        with self._transaction() as connection:
            self._validate_campaign_scope(connection, project_id, scope)
            replay = self._campaign_authority_request_event(
                connection, project_id, "campaign_authority_started", request_id
            )
            if replay is not None:
                self._assert_replay_fingerprint(
                    replay,
                    input_fingerprint,
                    event_type="campaign_authority_started",
                    input_payload=input_payload,
                )
                return self._campaign_authority_value(
                    connection, project_id, str(replay["campaign_id"])
                ) | {"replayed": True}

            ordinal = self._next_assurance_ordinal(connection, project_id, "campaign")
            campaign_id = f"CAMP-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO verification_campaigns(
                    project_id, change_id, campaign_id, ordinal, title, status,
                    target_requirement_ids_json, target_packet_ids_json,
                    target_finding_ids_json, environment_assumptions_json,
                    exception_reference, created_at, updated_at, created_by, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    scope.change_id,
                    campaign_id,
                    ordinal,
                    title,
                    CampaignStatus.PLANNED.value,
                    self._json(list(scope.requirement_ids)),
                    self._json(list(scope.packet_ids)),
                    self._json(list(scope.finding_ids)),
                    self._json(list(scope.environment_assumptions)),
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            case_order: list[str] = []
            if first_case is not None:
                case_id = self._insert_campaign_case(
                    connection,
                    project_id,
                    campaign_id,
                    first_case,
                    actor=actor,
                    request_id=request_id,
                    occurred_at=occurred_at,
                )
                case_order.append(case_id)
            payload = self._campaign_plan_payload(
                connection,
                project_id,
                campaign_id,
                title=title,
                scope=scope.as_payload(),
                case_order=case_order,
            )
            self._append_campaign_plan_revision(
                connection,
                project_id,
                campaign_id,
                payload,
                reason="campaign_started",
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                event_type="campaign_authority_started",
                semantic_revision=1,
                payload={"input_fingerprint": input_fingerprint},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def campaign_authority_state(
        self,
        project_id: str,
        campaign_id: str,
        *,
        history_limit: int = 20,
    ) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._campaign_authority_value(
                connection,
                validate_project_id(project_id),
                validate_campaign_id(campaign_id),
                history_limit=_bounded_limit(history_limit, maximum=100),
            )

    def active_campaign_authority(
        self,
        project_id: str,
        *,
        change_id: str = "",
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        with self._read_connection() as connection:
            self._ensure_project(connection, project_id)
            params: list[object] = [project_id]
            where = "WHERE c.project_id = ?"
            if change_id:
                where += " AND c.change_id = ?"
                params.append(change_id)
            row = connection.execute(
                f"""
                SELECT c.campaign_id
                FROM verification_campaigns c
                JOIN campaign_plan_heads h
                  ON h.project_id = c.project_id AND h.campaign_id = c.campaign_id
                {where}
                  AND c.status NOT IN ('cancelled', 'accepted_exception')
                  AND NOT EXISTS (
                      SELECT 1 FROM campaign_authority_events e
                      WHERE e.project_id = c.project_id
                        AND e.campaign_id = c.campaign_id
                        AND e.event_type = 'campaign_completion_recorded'
                        AND e.semantic_revision = h.current_revision
                  )
                ORDER BY c.ordinal DESC LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if row is None:
                return None
            return self._campaign_authority_value(
                connection, project_id, str(row["campaign_id"])
            )

    def completed_campaign_for_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
    ) -> Mapping[str, Any] | None:
        """Return current qualified completion evidence for one packet."""

        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        with self._read_connection() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            rows = connection.execute(
                """
                SELECT c.campaign_id, c.target_packet_ids_json
                FROM verification_campaigns c
                JOIN campaign_plan_heads h
                  ON h.project_id = c.project_id AND h.campaign_id = c.campaign_id
                WHERE c.project_id = ? AND c.change_id = ? AND c.status = 'passed'
                  AND EXISTS (
                      SELECT 1 FROM campaign_authority_events e
                      WHERE e.project_id = c.project_id
                        AND e.campaign_id = c.campaign_id
                        AND e.event_type = 'campaign_completion_recorded'
                        AND e.semantic_revision = h.current_revision
                  )
                ORDER BY c.ordinal DESC
                """,
                (project_id, change_id),
            ).fetchall()
            for row in rows:
                if packet_id not in self._json_string_list(
                    row["target_packet_ids_json"]
                ):
                    continue
                return self._campaign_authority_value(
                    connection, project_id, str(row["campaign_id"])
                )
            return None

    def add_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        actor = required_text(actor, "actor")
        input_payload = {"case": draft.as_payload()}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_case_added",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            current = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._guard_campaign_fingerprint(current, expected_fingerprint)
            case_id = self._insert_campaign_case(
                connection,
                project_id,
                campaign_id,
                draft,
                actor=actor,
                request_id=request_id,
                occurred_at=_utc_now(),
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="case_added",
                event_type="campaign_case_added",
                event_payload=input_payload | {"case_id": case_id},
                actor=actor,
                request_id=request_id,
                request_input_payload=input_payload,
            )

    def edit_campaign_authority_scope(
        self,
        project_id: str,
        campaign_id: str,
        *,
        title: str,
        scope: CampaignScopeDraft,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        title = required_text(title, "title")
        actor = required_text(actor, "actor")
        input_payload = {"title": title, "scope": scope.as_payload()}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_scope_edited",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            current = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._guard_campaign_fingerprint(current, expected_fingerprint)
            campaign = self._campaign_row(connection, project_id, campaign_id)
            if str(campaign["change_id"]) != scope.change_id:
                raise AssuranceBlockedError("campaign_change_is_immutable")
            self._validate_campaign_scope(connection, project_id, scope)
            occurred_at = _utc_now()
            connection.execute(
                """
                UPDATE verification_campaigns
                SET title = ?, target_requirement_ids_json = ?,
                    target_packet_ids_json = ?, target_finding_ids_json = ?,
                    environment_assumptions_json = ?, updated_at = ?
                WHERE project_id = ? AND campaign_id = ?
                """,
                (
                    title,
                    self._json(list(scope.requirement_ids)),
                    self._json(list(scope.packet_ids)),
                    self._json(list(scope.finding_ids)),
                    self._json(list(scope.environment_assumptions)),
                    occurred_at,
                    project_id,
                    campaign_id,
                ),
            )
            old_payload = self._current_campaign_plan_payload(
                connection, project_id, campaign_id
            )
            payload = self._campaign_plan_payload(
                connection,
                project_id,
                campaign_id,
                title=title,
                scope=scope.as_payload(),
                case_order=list(old_payload.get("case_order", [])),
            )
            revision = self._append_campaign_plan_revision(
                connection,
                project_id,
                campaign_id,
                payload,
                reason="scope_edited",
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                event_type="campaign_scope_edited",
                semantic_revision=revision,
                payload=input_payload
                | {"input_fingerprint": semantic_fingerprint(input_payload)},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def cancel_campaign_authority(
        self,
        project_id: str,
        campaign_id: str,
        *,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        disposition_reference = required_text(
            disposition_reference, "disposition_reference"
        )
        actor = required_text(actor, "actor")
        input_payload = {"disposition_reference": disposition_reference}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_authority_cancelled",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            connection.execute(
                """
                UPDATE verification_campaigns
                SET status = 'cancelled', exception_reference = ?, updated_at = ?
                WHERE project_id = ? AND campaign_id = ?
                """,
                (disposition_reference, _utc_now(), project_id, campaign_id),
            )
            occurred_at = _utc_now()
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                event_type="campaign_authority_cancelled",
                semantic_revision=int(head["current_revision"]),
                payload=input_payload
                | {"input_fingerprint": semantic_fingerprint(input_payload)},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def accept_campaign_exception(
        self,
        project_id: str,
        campaign_id: str,
        *,
        obligation_ids: Sequence[str],
        evidence_gaps: Sequence[str],
        risk_authority: str,
        disposition_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        obligations = tuple(validate_obligation_id(item) for item in obligation_ids)
        if not obligations or len(set(obligations)) != len(obligations):
            raise ValueError("campaign exception requires unique obligation_ids")
        gaps = tuple(
            required_text(str(item), "evidence_gaps") for item in evidence_gaps
        )
        if not gaps or len(set(gaps)) != len(gaps):
            raise ValueError("campaign exception requires unique evidence_gaps")
        risk_authority = required_text(risk_authority, "risk_authority")
        disposition_reference = required_text(
            disposition_reference, "disposition_reference"
        )
        actor = required_text(actor, "actor")
        input_payload = {
            "obligation_ids": list(obligations),
            "evidence_gaps": list(gaps),
            "risk_authority": risk_authority,
            "disposition_reference": disposition_reference,
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_exception_accepted",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            known = {
                str(row["obligation_id"])
                for row in connection.execute(
                    """
                    SELECT obligation_id FROM campaign_obligations
                    WHERE project_id = ? AND campaign_id = ? AND active = 1
                    """,
                    (project_id, campaign_id),
                ).fetchall()
            }
            missing = sorted(set(obligations).difference(known))
            if missing:
                raise RequirementConflictError(
                    f"campaign exception obligation is unknown: {missing[0]}"
                )
            state = self._campaign_authority_value(
                connection, project_id, campaign_id
            )
            unresolved = _unresolved_campaign_obligation_ids(state)
            received = set(obligations)
            if received != unresolved:
                raise AssuranceBlockedError(
                    "campaign_exception_obligation_scope_mismatch",
                    details={
                        "missing_obligation_ids": sorted(unresolved - received),
                        "unexpected_obligation_ids": sorted(received - unresolved),
                    },
                )
            occurred_at = _utc_now()
            connection.execute(
                """
                UPDATE verification_campaigns
                SET status = 'accepted_exception', exception_reference = ?,
                    updated_at = ?
                WHERE project_id = ? AND campaign_id = ?
                """,
                (
                    disposition_reference,
                    occurred_at,
                    project_id,
                    campaign_id,
                ),
            )
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                event_type="campaign_exception_accepted",
                semantic_revision=int(head["current_revision"]),
                payload=input_payload
                | {"input_fingerprint": semantic_fingerprint(input_payload)},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def authorize_campaign_promotion(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        evidence_id: str,
        authority_reference: str,
        regression_obligation: bool,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        evidence_id = required_text(evidence_id, "evidence_id")
        authority_reference = required_text(authority_reference, "authority_reference")
        if not isinstance(regression_obligation, bool):
            raise ValueError("regression_obligation must be boolean")
        actor = required_text(actor, "actor")
        input_payload = {
            "case_id": case_id,
            "evidence_id": evidence_id,
            "authority_reference": authority_reference,
            "regression_obligation": regression_obligation,
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_promotion_authorized",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._active_case_revision(connection, project_id, campaign_id, case_id)
            evidence_values = self._campaign_execution_evidence_values(
                connection,
                project_id,
                campaign_id,
                case_id=case_id,
                limit=None,
            )
            evidence = next(
                (
                    item
                    for item in evidence_values
                    if str(item.get("evidence_id") or "") == evidence_id
                ),
                None,
            )
            if evidence is None:
                raise RequirementConflictError(
                    f"unknown campaign execution evidence: {evidence_id}"
                )
            latest_run = next(
                (
                    item
                    for item in evidence_values
                    if bool(item.get("current"))
                    and str(item.get("operation") or "") == "run"
                ),
                None,
            )
            if (
                latest_run is None
                or str(latest_run.get("evidence_id") or "") != evidence_id
                or not bool(evidence.get("current"))
                or not bool(evidence.get("authoritative"))
                or str(evidence.get("acceptance_disposition") or "") != "passed"
                or str(evidence.get("operation") or "") != "run"
            ):
                raise AssuranceBlockedError(
                    "campaign_promotion_requires_current_passed_run",
                    details={"case_id": case_id, "evidence_id": evidence_id},
                )
            provider_test_ref = required_text(
                str(evidence.get("provider_test_ref") or ""), "provider_test_ref"
            )
            occurred_at = _utc_now()
            payload = {
                **input_payload,
                "attestation_id": str(evidence.get("attestation_id") or ""),
                "oracle_id": str(evidence.get("oracle_id") or ""),
                "oracle_revision": int(evidence.get("oracle_revision") or 0),
                "provider_test_ref": provider_test_ref,
                "materialization_revision": int(
                    evidence.get("materialization_revision") or 0
                ),
            }
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                case_id=case_id,
                oracle_id=str(evidence.get("oracle_id") or ""),
                attestation_id=str(evidence.get("attestation_id") or ""),
                event_type="campaign_promotion_authorized",
                semantic_revision=int(head["current_revision"]),
                payload=payload
                | {"input_fingerprint": semantic_fingerprint(input_payload)},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def record_campaign_completion(
        self,
        project_id: str,
        campaign_id: str,
        *,
        propagation: Mapping[str, object],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        actor = required_text(actor, "actor")
        propagation = canonical_semantic_value(dict(propagation or {}))
        input_payload = {
            "propagation_fingerprint": semantic_fingerprint(propagation),
            "propagated_count": len(propagation.get("propagated", [])),
            "diagnostic_count": len(propagation.get("diagnostics", [])),
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_completion_recorded",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            campaign = self._campaign_row(connection, project_id, campaign_id)
            if str(campaign["status"]) != "passed":
                raise AssuranceBlockedError("campaign_completion_requires_passed_cases")
            state = self._campaign_authority_value(connection, project_id, campaign_id)
            required_case_ids = {
                str(item.get("case_id") or "")
                for item in state.get("cases", [])
                if bool(item.get("required"))
            }
            latest_runs: dict[str, Mapping[str, object]] = {}
            latest_promotions: dict[str, Mapping[str, object]] = {}
            for item in state.get("evidence", []):
                if not isinstance(item, Mapping) or not bool(item.get("current")):
                    continue
                case_id = str(item.get("case_id") or "")
                operation = str(item.get("operation") or "")
                if operation == "run":
                    latest_runs.setdefault(case_id, item)
                elif operation == "promote":
                    latest_promotions.setdefault(case_id, item)
            promoted = {
                case_id: promotion
                for case_id in required_case_ids
                if (run := latest_runs.get(case_id)) is not None
                and (promotion := latest_promotions.get(case_id)) is not None
                and bool(run.get("authoritative"))
                and str(run.get("acceptance_disposition") or "") == "passed"
                and bool(promotion.get("authoritative"))
                and str(promotion.get("acceptance_disposition") or "") == "passed"
                and str(promotion.get("promotion_evidence_id") or "")
                == str(run.get("evidence_id") or "")
            }
            missing = sorted(required_case_ids.difference(promoted))
            if missing:
                raise AssuranceBlockedError(
                    "campaign_completion_requires_current_promotions",
                    details={"case_ids": missing},
                )
            promotion_evidence_ids = sorted(
                str(promoted[case_id].get("evidence_id") or "")
                for case_id in required_case_ids
            )
            occurred_at = _utc_now()
            payload = {
                **input_payload,
                "promotion_evidence_ids": promotion_evidence_ids,
                "propagation": propagation,
            }
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                event_type="campaign_completion_recorded",
                semantic_revision=int(head["current_revision"]),
                payload=payload
                | {"input_fingerprint": semantic_fingerprint(input_payload)},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )
            return self._campaign_authority_value(connection, project_id, campaign_id)

    def edit_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        actor = required_text(actor, "actor")
        input_payload = {"case_id": case_id, "case": draft.as_payload()}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_case_edited",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            current = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._guard_campaign_fingerprint(current, expected_fingerprint)
            self._active_case_revision(connection, project_id, campaign_id, case_id)
            revision = self._next_case_revision(
                connection, project_id, campaign_id, case_id
            )
            occurred_at = _utc_now()
            payload = draft.as_payload()
            connection.execute(
                """
                INSERT INTO campaign_case_revisions(
                    project_id, campaign_id, case_id, revision, payload_json,
                    semantic_fingerprint, active, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    revision,
                    self._json(payload),
                    semantic_fingerprint(payload),
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE campaign_cases
                SET title = ?, purpose = ?, case_kind = ?, required = ?, updated_at = ?, actor = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    draft.title,
                    draft.purpose,
                    draft.case_kind,
                    int(draft.required),
                    occurred_at,
                    actor,
                    project_id,
                    campaign_id,
                    case_id,
                ),
            )
            self._sync_case_coverage_from_obligations(
                connection, project_id, campaign_id, case_id
            )
            self._invalidate_case_execution_authority(
                connection,
                project_id,
                campaign_id,
                case_id,
                actor=actor,
                request_id=request_id,
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="case_edited",
                event_type="campaign_case_edited",
                event_payload=input_payload,
                actor=actor,
                request_id=request_id,
            )

    def remove_campaign_authority_case(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        rationale: str,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        rationale = required_text(rationale, "rationale")
        actor = required_text(actor, "actor")
        input_payload = {"case_id": case_id, "rationale": rationale}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_case_removed",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            current = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._guard_campaign_fingerprint(current, expected_fingerprint)
            previous = self._active_case_revision(
                connection, project_id, campaign_id, case_id
            )
            revision = self._next_case_revision(
                connection, project_id, campaign_id, case_id
            )
            connection.execute(
                """
                INSERT INTO campaign_case_revisions(
                    project_id, campaign_id, case_id, revision, payload_json,
                    semantic_fingerprint, active, created_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    revision,
                    str(previous["payload_json"]),
                    str(previous["semantic_fingerprint"]),
                    _utc_now(),
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE campaign_case_oracle_bindings SET active = 0
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (project_id, campaign_id, case_id),
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="case_removed",
                event_type="campaign_case_removed",
                event_payload=input_payload,
                actor=actor,
                request_id=request_id,
                remove_from_order=case_id,
            )

    def reorder_campaign_authority_cases(
        self,
        project_id: str,
        campaign_id: str,
        case_order: Sequence[str],
        *,
        actor: str,
        request_id: str = "",
        expected_fingerprint: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        normalized = tuple(validate_case_id(item) for item in case_order)
        if len(set(normalized)) != len(normalized):
            raise ValueError("case_order must contain unique case IDs")
        actor = required_text(actor, "actor")
        input_payload = {"case_order": list(normalized)}
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_cases_reordered",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            current = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._guard_campaign_fingerprint(current, expected_fingerprint)
            active = {
                str(item["case_id"])
                for item in self._active_campaign_cases(
                    connection, project_id, campaign_id
                )
            }
            if set(normalized) != active:
                raise AssuranceBlockedError(
                    "campaign_case_order_mismatch",
                    details={
                        "expected": sorted(active),
                        "received": sorted(normalized),
                    },
                )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="cases_reordered",
                event_type="campaign_cases_reordered",
                event_payload=input_payload,
                actor=actor,
                request_id=request_id,
                case_order=list(normalized),
            )

    def derive_campaign_obligations(
        self,
        project_id: str,
        campaign_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        actor = required_text(actor, "actor")
        with self._transaction() as connection:
            replay = self._campaign_authority_request_event(
                connection, project_id, "campaign_obligations_derived", request_id
            )
            if replay is not None and str(replay["campaign_id"]) == campaign_id:
                return self._campaign_authority_value(
                    connection, project_id, campaign_id
                ) | {"replayed": True}
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            scope = self._current_scope(connection, project_id, campaign_id)
            candidates = self._obligation_candidates(
                connection,
                project_id,
                campaign_id,
                scope,
                int(head["current_revision"]),
            )
            active_fingerprints: set[str] = set()
            created: list[str] = []
            occurred_at = _utc_now()
            for candidate in candidates:
                fingerprint = semantic_fingerprint(candidate)
                active_fingerprints.add(fingerprint)
                existing = connection.execute(
                    """
                    SELECT obligation_id FROM campaign_obligations
                    WHERE project_id = ? AND campaign_id = ? AND dependency_fingerprint = ?
                    """,
                    (project_id, campaign_id, fingerprint),
                ).fetchone()
                if existing is not None:
                    connection.execute(
                        """
                        UPDATE campaign_obligations SET active = 1, updated_at = ?
                        WHERE project_id = ? AND campaign_id = ? AND obligation_id = ?
                        """,
                        (
                            occurred_at,
                            project_id,
                            campaign_id,
                            str(existing["obligation_id"]),
                        ),
                    )
                    continue
                ordinal = self._next_campaign_authority_ordinal(
                    connection, project_id, "obligation"
                )
                obligation_id = f"OBL-{ordinal:06d}"
                connection.execute(
                    """
                    INSERT INTO campaign_obligations(
                        project_id, campaign_id, obligation_id, ordinal, kind,
                        subject_ref, source_kind, source_ref, source_revision,
                        statement, expected_behavior, prohibited_behavior,
                        decision, rationale, dependency_fingerprint, active,
                        created_at, updated_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        campaign_id,
                        obligation_id,
                        ordinal,
                        candidate["kind"],
                        candidate["subject_ref"],
                        candidate["source_kind"],
                        candidate["source_ref"],
                        candidate["source_revision"],
                        candidate["statement"],
                        candidate["expected_behavior"],
                        candidate["prohibited_behavior"],
                        CampaignObligationDecision.UNCLASSIFIED.value,
                        fingerprint,
                        occurred_at,
                        occurred_at,
                        actor,
                        str(request_id or ""),
                    ),
                )
                created.append(obligation_id)
            existing_rows = connection.execute(
                """
                SELECT obligation_id, dependency_fingerprint
                FROM campaign_obligations
                WHERE project_id = ? AND campaign_id = ? AND active = 1
                """,
                (project_id, campaign_id),
            ).fetchall()
            for row in existing_rows:
                if str(row["dependency_fingerprint"]) not in active_fingerprints:
                    connection.execute(
                        """
                        UPDATE campaign_obligations SET active = 0, updated_at = ?
                        WHERE project_id = ? AND campaign_id = ? AND obligation_id = ?
                        """,
                        (
                            occurred_at,
                            project_id,
                            campaign_id,
                            str(row["obligation_id"]),
                        ),
                    )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="obligations_derived",
                event_type="campaign_obligations_derived",
                event_payload={"created": created, "candidate_count": len(candidates)},
                actor=actor,
                request_id=request_id,
            )

    def decide_campaign_obligation(
        self,
        project_id: str,
        campaign_id: str,
        obligation_id: str,
        *,
        decision: CampaignObligationDecision,
        rationale: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        obligation_id = validate_obligation_id(obligation_id)
        decision = CampaignObligationDecision(decision)
        rationale = required_text(rationale, "rationale")
        actor = required_text(actor, "actor")
        input_payload = {
            "obligation_id": obligation_id,
            "decision": decision.value,
            "rationale": rationale,
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_obligation_decided",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            row = self._obligation_row(
                connection, project_id, campaign_id, obligation_id
            )
            if not bool(row["active"]):
                raise AssuranceBlockedError("campaign_obligation_stale")
            connection.execute(
                """
                UPDATE campaign_obligations
                SET decision = ?, rationale = ?, updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND obligation_id = ?
                """,
                (
                    decision.value,
                    rationale,
                    _utc_now(),
                    actor,
                    str(request_id or ""),
                    project_id,
                    campaign_id,
                    obligation_id,
                ),
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="obligation_decided",
                event_type="campaign_obligation_decided",
                event_payload=input_payload,
                actor=actor,
                request_id=request_id,
            )

    def bind_campaign_case_obligation(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        obligation_id: str,
        *,
        coverage_intent: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        obligation_id = validate_obligation_id(obligation_id)
        coverage_intent = required_text(coverage_intent, "coverage_intent")
        actor = required_text(actor, "actor")
        input_payload = {
            "case_id": case_id,
            "obligation_id": obligation_id,
            "coverage_intent": coverage_intent,
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "campaign_obligation_bound",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            self._active_case_revision(connection, project_id, campaign_id, case_id)
            obligation = self._obligation_row(
                connection, project_id, campaign_id, obligation_id
            )
            if not bool(obligation["active"]):
                raise AssuranceBlockedError("campaign_obligation_stale")
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            connection.execute(
                """
                INSERT INTO campaign_case_obligation_bindings(
                    project_id, campaign_id, case_id, obligation_id,
                    coverage_intent, campaign_revision, created_at, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, campaign_id, case_id, obligation_id)
                DO UPDATE SET coverage_intent = excluded.coverage_intent,
                              campaign_revision = excluded.campaign_revision,
                              created_at = excluded.created_at,
                              actor = excluded.actor
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    obligation_id,
                    coverage_intent,
                    int(head["current_revision"]),
                    _utc_now(),
                    actor,
                ),
            )
            self._sync_case_coverage_from_obligations(
                connection, project_id, campaign_id, case_id
            )
            self._invalidate_case_execution_authority(
                connection,
                project_id,
                campaign_id,
                case_id,
                actor=actor,
                request_id=request_id,
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="obligation_bound",
                event_type="campaign_obligation_bound",
                event_payload=input_payload,
                actor=actor,
                request_id=request_id,
            )

    def author_behavioral_oracle(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        draft: BehavioralOracleDraft,
        *,
        actor: str,
        oracle_id: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        actor = required_text(actor, "actor")
        if oracle_id:
            oracle_id = validate_oracle_id(oracle_id)
        input_payload = {
            "case_id": case_id,
            "oracle_id": oracle_id,
            "oracle": draft.as_payload(),
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "behavioral_oracle_authored",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            self._active_case_revision(connection, project_id, campaign_id, case_id)
            occurred_at = _utc_now()
            if not oracle_id:
                ordinal = self._next_campaign_authority_ordinal(
                    connection, project_id, "oracle"
                )
                oracle_id = f"ORACLE-{ordinal:06d}"
                revision = 1
                connection.execute(
                    """
                    INSERT INTO behavioral_oracles(
                        project_id, oracle_id, ordinal, current_revision,
                        current_fingerprint, status, created_at, updated_at, actor
                    ) VALUES (?, ?, ?, 1, '', 'current', ?, ?, ?)
                    """,
                    (project_id, oracle_id, ordinal, occurred_at, occurred_at, actor),
                )
            else:
                current = self._oracle_head(connection, project_id, oracle_id)
                revision = int(current["current_revision"]) + 1
            payload = draft.as_payload()
            fingerprint = semantic_fingerprint(payload)
            dependency_fingerprint = self._current_oracle_dependency_fingerprint(
                connection,
                project_id,
                payload,
            )
            status = (
                "constructible"
                if self._oracle_missing_fields(payload) == []
                else "draft"
            )
            field_authority = _initial_oracle_field_authority(
                payload,
                draft.authority_reference,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO behavioral_oracle_revisions(
                        project_id, oracle_id, revision, contract_version,
                        oracle_kind, payload_json, semantic_fingerprint,
                        authority_reference, dependency_fingerprint,
                        field_authority_json, status,
                        created_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        oracle_id,
                        revision,
                        ORACLE_SNAPSHOT_CONTRACT_VERSION,
                        draft.oracle_kind,
                        self._json(payload),
                        fingerprint,
                        draft.authority_reference,
                        dependency_fingerprint,
                        self._json(field_authority),
                        status,
                        occurred_at,
                        actor,
                        str(request_id or ""),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RequirementConflictError(
                    "oracle revision duplicates an existing semantic revision"
                ) from exc
            connection.execute(
                """
                UPDATE behavioral_oracles
                SET current_revision = ?, current_fingerprint = ?, status = 'current',
                    updated_at = ?, actor = ?
                WHERE project_id = ? AND oracle_id = ?
                """,
                (revision, fingerprint, occurred_at, actor, project_id, oracle_id),
            )
            connection.execute(
                """
                UPDATE campaign_case_oracle_bindings SET active = 0
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (project_id, campaign_id, case_id),
            )
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            connection.execute(
                """
                INSERT INTO campaign_case_oracle_bindings(
                    project_id, campaign_id, case_id, oracle_id, oracle_revision,
                    oracle_fingerprint, campaign_revision, active, created_at, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    oracle_id,
                    revision,
                    fingerprint,
                    int(head["current_revision"]),
                    occurred_at,
                    actor,
                ),
            )
            self._replace_oracle_questions(
                connection,
                project_id,
                oracle_id,
                revision,
                payload,
            )
            self._invalidate_case_execution_authority(
                connection,
                project_id,
                campaign_id,
                case_id,
                actor=actor,
                request_id=request_id,
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="oracle_authored",
                event_type="behavioral_oracle_authored",
                event_payload=input_payload
                | {"oracle_id": oracle_id, "oracle_revision": revision},
                actor=actor,
                request_id=request_id,
                request_input_payload=input_payload,
                oracle_id=oracle_id,
            )

    def answer_oracle_question(
        self,
        project_id: str,
        campaign_id: str,
        oracle_id: str,
        question_id: str,
        *,
        answer: object,
        authority: OracleAnswerAuthority,
        provenance: Sequence[str],
        waiver_scope: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        oracle_id = validate_oracle_id(oracle_id)
        question_id = required_text(question_id, "question_id")
        authority = OracleAnswerAuthority(authority)
        actor = required_text(actor, "actor")
        provenance_values = tuple(
            required_text(item, "provenance") for item in provenance
        )
        if (
            authority
            in {
                OracleAnswerAuthority.GROUNDED_FACT,
                OracleAnswerAuthority.ACCEPTED_DECISION,
            }
            and not provenance_values
        ):
            raise AssuranceBlockedError("oracle_answer_requires_provenance")
        if authority == OracleAnswerAuthority.WAIVED:
            waiver_scope = required_text(waiver_scope, "waiver_scope")
        input_payload = {
            "oracle_id": oracle_id,
            "question_id": question_id,
            "answer": canonical_semantic_value(answer),
            "authority": authority.value,
            "provenance": list(provenance_values),
            "waiver_scope": str(waiver_scope or ""),
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "oracle_question_answered",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            head = self._oracle_head(connection, project_id, oracle_id)
            revision = int(head["current_revision"])
            current_question = connection.execute(
                """
                SELECT q.*
                FROM campaign_case_oracle_bindings b
                JOIN oracle_questions q
                  ON q.project_id = b.project_id
                 AND q.oracle_id = b.oracle_id
                 AND q.oracle_revision = b.oracle_revision
                WHERE b.project_id = ? AND b.campaign_id = ? AND b.active = 1
                ORDER BY b.case_id, b.oracle_id,
                         CASE q.question_scope WHEN 'source' THEN 0 ELSE 1 END,
                         q.ordinal
                LIMIT 1
                """,
                (project_id, campaign_id),
            ).fetchone()
            if current_question is None:
                raise RequirementConflictError(
                    "campaign has no current oracle question"
                )
            expected_oracle_id = str(current_question["oracle_id"])
            expected_question_id = str(current_question["question_id"])
            if oracle_id != expected_oracle_id or question_id != expected_question_id:
                raise RequirementConflictError(
                    "oracle_question_not_current: "
                    f"expected {expected_oracle_id}/{expected_question_id}"
                )
            if int(current_question["oracle_revision"]) != revision:
                raise RequirementConflictError("oracle_question_revision_not_current")
            question = current_question
            current_revision = self._oracle_revision_row(
                connection, project_id, oracle_id, revision
            )
            payload = json.loads(str(current_revision["payload_json"]))
            if authority in {
                OracleAnswerAuthority.GROUNDED_FACT,
                OracleAnswerAuthority.ACCEPTED_DECISION,
            }:
                fields = dict(payload.get("semantic_fields") or {})
                fields[str(question["field_name"])] = canonical_semantic_value(answer)
                payload["semantic_fields"] = fields
                field_authority = json.loads(
                    str(current_revision["field_authority_json"] or "{}")
                )
                field_authority[str(question["field_name"])] = {
                    "authority": authority.value,
                    "provenance": list(provenance_values),
                }
                new_revision = revision + 1
                fingerprint = semantic_fingerprint(payload)
                occurred_at = _utc_now()
                connection.execute(
                    """
                    INSERT INTO behavioral_oracle_revisions(
                        project_id, oracle_id, revision, contract_version,
                        oracle_kind, payload_json, semantic_fingerprint,
                        authority_reference, dependency_fingerprint,
                        field_authority_json, status,
                        created_at, actor, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        oracle_id,
                        new_revision,
                        ORACLE_SNAPSHOT_CONTRACT_VERSION,
                        str(current_revision["oracle_kind"]),
                        self._json(payload),
                        fingerprint,
                        str(current_revision["authority_reference"]),
                        str(current_revision["dependency_fingerprint"]),
                        self._json(field_authority),
                        "constructible"
                        if not self._oracle_missing_fields(payload)
                        else "draft",
                        occurred_at,
                        actor,
                        str(request_id or ""),
                    ),
                )
                connection.execute(
                    """
                    UPDATE behavioral_oracles
                    SET current_revision = ?, current_fingerprint = ?, updated_at = ?, actor = ?
                    WHERE project_id = ? AND oracle_id = ?
                    """,
                    (
                        new_revision,
                        fingerprint,
                        occurred_at,
                        actor,
                        project_id,
                        oracle_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE campaign_case_oracle_bindings SET active = 0
                    WHERE project_id = ? AND campaign_id = ? AND oracle_id = ?
                    """,
                    (project_id, campaign_id, oracle_id),
                )
                case_rows = connection.execute(
                    """
                    SELECT DISTINCT case_id FROM campaign_case_oracle_bindings
                    WHERE project_id = ? AND campaign_id = ? AND oracle_id = ?
                    """,
                    (project_id, campaign_id, oracle_id),
                ).fetchall()
                campaign_head = self._qualified_campaign_head(
                    connection, project_id, campaign_id
                )
                for case_row in case_rows:
                    connection.execute(
                        """
                        INSERT INTO campaign_case_oracle_bindings(
                            project_id, campaign_id, case_id, oracle_id,
                            oracle_revision, oracle_fingerprint, campaign_revision,
                            active, created_at, actor
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            project_id,
                            campaign_id,
                            str(case_row["case_id"]),
                            oracle_id,
                            new_revision,
                            fingerprint,
                            int(campaign_head["current_revision"]),
                            occurred_at,
                            actor,
                        ),
                    )
                    self._invalidate_case_execution_authority(
                        connection,
                        project_id,
                        campaign_id,
                        str(case_row["case_id"]),
                        actor=actor,
                        request_id=request_id,
                    )
                self._replace_oracle_questions(
                    connection,
                    project_id,
                    oracle_id,
                    new_revision,
                    payload,
                )
                revision = new_revision
            else:
                connection.execute(
                    """
                    UPDATE oracle_questions
                    SET answer_authority = ?, answer_json = ?, provenance_json = ?,
                        waiver_scope = ?, answered_at = ?, actor = ?, request_id = ?
                    WHERE project_id = ? AND oracle_id = ? AND oracle_revision = ?
                      AND question_id = ?
                    """,
                    (
                        authority.value,
                        self._json(canonical_semantic_value(answer)),
                        self._json(list(provenance_values)),
                        str(waiver_scope or ""),
                        _utc_now(),
                        actor,
                        str(request_id or ""),
                        project_id,
                        oracle_id,
                        revision,
                        question_id,
                    ),
                )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="oracle_question_answered",
                event_type="oracle_question_answered",
                event_payload=input_payload | {"oracle_revision": revision},
                actor=actor,
                request_id=request_id,
                request_input_payload=input_payload,
                oracle_id=oracle_id,
            )

    def create_campaign_attestation_intent(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        source_files: Mapping[str, str],
        authority_reference: str,
        actor: str,
        request_id: str = "",
        harness: Mapping[str, object] | None = None,
        requested_capability: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        authority_reference = required_text(authority_reference, "authority_reference")
        actor = required_text(actor, "actor")
        harness_value = canonical_test_harness(harness)
        harness_fingerprint = semantic_fingerprint(harness_value)
        capability = (
            canonical_materializer_capability(requested_capability)
            if requested_capability is not None
            else {}
        )
        if set(capability).difference({"language", "framework"}):
            raise ValueError(
                "source requested_capability supports language and framework only"
            )
        capability_fingerprint = (
            semantic_fingerprint(capability) if capability else ""
        )
        manifest = {
            path.replace("\\", "/"): sha256(content.encode("utf-8")).hexdigest()
            for path, content in sorted(source_files.items())
        }
        digest = source_manifest_digest(source_files)
        input_payload = {
            "case_id": case_id,
            "source_manifest_digest": digest,
            "harness_fingerprint": harness_fingerprint,
            "requested_capability_fingerprint": capability_fingerprint,
            "authority_reference": authority_reference,
        }
        with self._transaction() as connection:
            replay = self._mutation_replay(
                connection,
                project_id,
                campaign_id,
                "attestation_intent_created",
                request_id,
                input_payload,
            )
            if replay is not None:
                return replay
            binding = self._current_case_oracle_binding(
                connection, project_id, campaign_id, case_id
            )
            oracle_revision = self._oracle_revision_row(
                connection,
                project_id,
                str(binding["oracle_id"]),
                int(binding["oracle_revision"]),
            )
            if str(oracle_revision["status"]) != "constructible":
                raise AssuranceBlockedError("attestation_requires_constructible_oracle")
            ordinal = self._next_campaign_authority_ordinal(
                connection, project_id, "attestation"
            )
            attestation_id = f"ATTEST-{ordinal:06d}"
            occurred_at = _utc_now()
            connection.execute(
                """
                UPDATE campaign_attestation_intents
                SET state = 'invalidated', updated_at = ?, actor = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                  AND state IN ('pending_technical_validation', 'attested_current')
                """,
                (occurred_at, actor, project_id, campaign_id, case_id),
            )
            connection.execute(
                """
                INSERT INTO campaign_attestation_intents(
                    project_id, campaign_id, case_id, attestation_id, ordinal,
                    oracle_id, oracle_revision, oracle_fingerprint,
                    materialization_mode, authority_input_fingerprint,
                    source_manifest_digest, source_manifest_json,
                    oracle_ir_contract_version, oracle_ir_operator_profile,
                    oracle_ir_fingerprint, oracle_ir_json,
                    requested_capability_json, requested_capability_fingerprint,
                    harness_json, harness_fingerprint, authority_reference,
                    state, created_at, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    attestation_id,
                    ordinal,
                    str(binding["oracle_id"]),
                    int(binding["oracle_revision"]),
                    str(binding["oracle_fingerprint"]),
                    TestProviderMaterializationMode.ORCHESTRATOR_SOURCE.value,
                    digest,
                    digest,
                    self._json(manifest),
                    "",
                    "",
                    "",
                    "{}",
                    self._json(capability),
                    capability_fingerprint,
                    self._json(harness_value),
                    harness_fingerprint,
                    authority_reference,
                    MaterializationAttestationState.PENDING_TECHNICAL_VALIDATION.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = 'pending', evidence_reference = '', metadata_json = '{}',
                    updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    occurred_at,
                    actor,
                    str(request_id or ""),
                    project_id,
                    campaign_id,
                    case_id,
                ),
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="attestation_intent_created",
                event_type="attestation_intent_created",
                event_payload=input_payload | {"attestation_id": attestation_id},
                actor=actor,
                request_id=request_id,
                request_input_payload=input_payload,
                case_id=case_id,
                oracle_id=str(binding["oracle_id"]),
                attestation_id=attestation_id,
            )

    def create_campaign_materialization_intent(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        requested_capability: Mapping[str, object],
        authority_reference: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        capability = canonical_materializer_capability(requested_capability)
        capability_fingerprint = semantic_fingerprint(capability)
        authority_reference = required_text(authority_reference, "authority_reference")
        actor = required_text(actor, "actor")
        harness_value = canonical_test_harness(None)
        harness_fingerprint = semantic_fingerprint(harness_value)
        with self._transaction() as connection:
            binding = self._current_case_oracle_binding(
                connection, project_id, campaign_id, case_id
            )
            oracle = self._oracle_value(
                connection,
                project_id,
                str(binding["oracle_id"]),
                revision=int(binding["oracle_revision"]),
            )
            projection = compile_oracle_ir(oracle)
            if not projection.constructible or projection.snapshot is None:
                raise AssuranceBlockedError(
                    "oracle_ir_unconstructible",
                    details={
                        "residuals": [item.as_payload() for item in projection.residuals],
                        "next_action": "answer the current oracle IR question or attest source",
                    },
                )
            snapshot = projection.snapshot
            input_payload = {
                "case_id": case_id,
                "materialization_mode": (
                    TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value
                ),
                "oracle_ir_fingerprint": snapshot.fingerprint,
                "requested_capability_fingerprint": capability_fingerprint,
                "authority_reference": authority_reference,
            }
            for replay_event in (
                "materialization_intent_created",
                "materialization_retry_authorized",
            ):
                replay = self._mutation_replay(
                    connection,
                    project_id,
                    campaign_id,
                    replay_event,
                    request_id,
                    input_payload,
                )
                if replay is not None:
                    return replay
            existing = connection.execute(
                """
                SELECT * FROM campaign_attestation_intents
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                  AND oracle_id = ? AND oracle_revision = ?
                  AND materialization_mode = 'deterministic_oracle_ir'
                  AND authority_input_fingerprint = ?
                  AND requested_capability_fingerprint = ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    snapshot.oracle_id,
                    snapshot.oracle_revision,
                    snapshot.fingerprint,
                    capability_fingerprint,
                ),
            ).fetchone()
            if existing is not None:
                existing_value = self._attestation_value(connection, existing)
                latest = connection.execute(
                    """
                    SELECT attestation_id FROM campaign_attestation_intents
                    WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                    ORDER BY ordinal DESC LIMIT 1
                    """,
                    (project_id, campaign_id, case_id),
                ).fetchone()
                latest_intent = bool(
                    latest is not None
                    and str(latest["attestation_id"]) == str(existing["attestation_id"])
                )
                if (
                    not latest_intent
                    or not deterministic_materialization_retry_eligible(existing_value)
                ):
                    raise AssuranceBlockedError(
                        "deterministic_materialization_successor_not_available",
                        details={
                            "attestation_state": str(existing_value.get("state") or ""),
                            "basis": existing_value.get("basis") or {},
                            "latest_intent": latest_intent,
                        },
                    )
                predecessor = connection.execute(
                    """
                    SELECT * FROM test_provider_outbox
                    WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                      AND operation = 'materialize'
                      AND json_extract(
                          command_json, '$.attestation_intent_ref'
                      ) = ?
                    ORDER BY ordinal DESC LIMIT 1
                    """,
                    (
                        project_id,
                        campaign_id,
                        case_id,
                        str(existing["attestation_id"]),
                    ),
                ).fetchone()
                if predecessor is None or str(predecessor["state"]) != "delivered":
                    raise AssuranceBlockedError(
                        "deterministic_materialization_failed_attempt_missing"
                    )
                receipt = connection.execute(
                    """
                    SELECT receipt_json, attestation_state
                    FROM test_provider_receipts
                    WHERE project_id = ? AND receipt_id = ?
                    """,
                    (project_id, str(predecessor["receipt_id"])),
                ).fetchone()
                receipt_payload = (
                    json.loads(str(receipt["receipt_json"]))
                    if receipt is not None
                    else {}
                )
                if (
                    not deterministic_materialization_failure_receipt(
                        receipt_payload,
                        reconciled_attestation_state=(
                            str(receipt["attestation_state"])
                            if receipt is not None
                            else ""
                        ),
                    )
                    or str(receipt_payload.get("authority_input_fingerprint") or "")
                    != snapshot.fingerprint
                ):
                    raise AssuranceBlockedError(
                        "deterministic_materialization_failed_attempt_mismatch"
                    )
                occurred_at = _utc_now()
                retry_basis = {
                    "technical_retry": {
                        "predecessor_command_id": str(predecessor["command_id"]),
                        "reason": "provider_attestation_invalidated",
                        "technical_state": str(
                            receipt_payload.get("technical_state") or ""
                        ),
                    }
                }
                connection.execute(
                    """
                    UPDATE campaign_attestation_intents
                    SET state = 'pending_technical_validation',
                        provider_materialization_ref = '',
                        representation_fingerprint = '', basis_json = ?,
                        updated_at = ?, actor = ?
                    WHERE project_id = ? AND attestation_id = ?
                    """,
                    (
                        self._json(retry_basis),
                        occurred_at,
                        actor,
                        project_id,
                        str(existing["attestation_id"]),
                    ),
                )
                connection.execute(
                    """
                    UPDATE campaign_cases
                    SET result = 'pending', evidence_reference = '',
                        metadata_json = '{}', updated_at = ?, actor = ?,
                        request_id = ?
                    WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                    """,
                    (
                        occurred_at,
                        actor,
                        str(request_id or ""),
                        project_id,
                        campaign_id,
                        case_id,
                    ),
                )
                return self._refresh_campaign_plan(
                    connection,
                    project_id,
                    campaign_id,
                    reason="materialization_retry_authorized",
                    event_type="materialization_retry_authorized",
                    event_payload=input_payload
                    | {
                        "attestation_id": str(existing["attestation_id"]),
                        "predecessor_command_id": str(predecessor["command_id"]),
                    },
                    actor=actor,
                    request_id=request_id,
                    request_input_payload=input_payload,
                    case_id=case_id,
                    oracle_id=snapshot.oracle_id,
                    attestation_id=str(existing["attestation_id"]),
                )
            ordinal = self._next_campaign_authority_ordinal(
                connection, project_id, "attestation"
            )
            attestation_id = f"ATTEST-{ordinal:06d}"
            occurred_at = _utc_now()
            connection.execute(
                """
                UPDATE campaign_attestation_intents
                SET state = 'invalidated', updated_at = ?, actor = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                  AND state IN ('pending_technical_validation', 'attested_current')
                """,
                (occurred_at, actor, project_id, campaign_id, case_id),
            )
            connection.execute(
                """
                INSERT INTO campaign_attestation_intents(
                    project_id, campaign_id, case_id, attestation_id, ordinal,
                    oracle_id, oracle_revision, oracle_fingerprint,
                    materialization_mode, authority_input_fingerprint,
                    source_manifest_digest, source_manifest_json,
                    oracle_ir_contract_version, oracle_ir_operator_profile,
                    oracle_ir_fingerprint, oracle_ir_json,
                    requested_capability_json, requested_capability_fingerprint,
                    harness_json, harness_fingerprint, authority_reference,
                    state, created_at, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    campaign_id,
                    case_id,
                    attestation_id,
                    ordinal,
                    snapshot.oracle_id,
                    snapshot.oracle_revision,
                    snapshot.oracle_fingerprint,
                    TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value,
                    snapshot.fingerprint,
                    "",
                    "{}",
                    snapshot.contract_version,
                    snapshot.operator_profile,
                    snapshot.fingerprint,
                    self._json(snapshot.as_payload()),
                    self._json(capability),
                    capability_fingerprint,
                    self._json(harness_value),
                    harness_fingerprint,
                    authority_reference,
                    MaterializationAttestationState.PENDING_TECHNICAL_VALIDATION.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = 'pending', evidence_reference = '', metadata_json = '{}',
                    updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    occurred_at,
                    actor,
                    str(request_id or ""),
                    project_id,
                    campaign_id,
                    case_id,
                ),
            )
            return self._refresh_campaign_plan(
                connection,
                project_id,
                campaign_id,
                reason="materialization_intent_created",
                event_type="materialization_intent_created",
                event_payload=input_payload | {"attestation_id": attestation_id},
                actor=actor,
                request_id=request_id,
                request_input_payload=input_payload,
                case_id=case_id,
                oracle_id=snapshot.oracle_id,
                attestation_id=attestation_id,
            )

    def campaign_provider_context(
        self,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        with self._read_connection() as connection:
            return self._campaign_provider_context_value(
                connection, project_id, campaign_id, case_id
            )

    def _campaign_provider_context_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> Mapping[str, Any]:
        state = self._campaign_authority_value(connection, project_id, campaign_id)
        case = next(
            (item for item in state["cases"] if item["case_id"] == case_id), None
        )
        if case is None:
            raise RequirementConflictError(f"unknown active campaign case: {case_id}")
        binding = self._current_case_oracle_binding(
            connection, project_id, campaign_id, case_id
        )
        oracle = self._oracle_value(
            connection,
            project_id,
            str(binding["oracle_id"]),
            revision=int(binding["oracle_revision"]),
        )
        attestation = connection.execute(
            """
            SELECT * FROM campaign_attestation_intents
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
              AND oracle_id = ? AND oracle_revision = ?
            ORDER BY ordinal DESC LIMIT 1
            """,
            (
                project_id,
                campaign_id,
                case_id,
                str(binding["oracle_id"]),
                int(binding["oracle_revision"]),
            ),
        ).fetchone()
        provider_rows = connection.execute(
            """
            SELECT r.receipt_json, o.operation
            FROM test_provider_receipts r
            JOIN test_provider_outbox o
              ON o.project_id = r.project_id AND o.command_id = r.command_id
            WHERE r.project_id = ? AND r.campaign_id = ? AND r.case_id = ?
            ORDER BY r.ordinal DESC
            """,
            (project_id, campaign_id, case_id),
        ).fetchall()
        provider_test_ref = ""
        materialization_revision = 0
        if provider_rows and str(provider_rows[0]["operation"]) != "discard":
            for provider_row in provider_rows:
                receipt_payload = json.loads(str(provider_row["receipt_json"]))
                candidate = str(receipt_payload.get("provider_test_ref") or "").strip()
                if candidate:
                    provider_test_ref = candidate
                    materialization = receipt_payload.get("materialization")
                    if isinstance(materialization, Mapping):
                        materialization_revision = int(
                            materialization.get("revision") or 0
                        )
                    break
        evidence = self._campaign_execution_evidence_values(
            connection,
            project_id,
            campaign_id,
            case_id=case_id,
            limit=None,
        )
        current_run_evidence = next(
            (
                item
                for item in evidence
                if bool(item.get("current"))
                and str(item.get("operation") or "") == "run"
            ),
            None,
        )
        return {
            "campaign": {
                "campaign_id": campaign_id,
                "revision": state["revision"],
                "fingerprint": state["fingerprint"],
            },
            "case": case,
            "oracle": oracle,
            "attestation": self._attestation_value(connection, attestation)
            if attestation
            else None,
            "provider_test_ref": provider_test_ref,
            "materialization_revision": materialization_revision,
            "latest_evidence": evidence[0] if evidence else None,
            "current_run_evidence": current_run_evidence,
        }

    def _refresh_campaign_plan(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        reason: str,
        event_type: str,
        event_payload: Mapping[str, object],
        actor: str,
        request_id: str,
        request_input_payload: Mapping[str, object] | None = None,
        case_order: list[str] | None = None,
        remove_from_order: str = "",
        case_id: str = "",
        oracle_id: str = "",
        attestation_id: str = "",
    ) -> Mapping[str, Any]:
        current = self._current_campaign_plan_payload(
            connection, project_id, campaign_id
        )
        order = list(
            case_order if case_order is not None else current.get("case_order", [])
        )
        active_case_ids = [
            str(item["case_id"])
            for item in self._active_campaign_cases(connection, project_id, campaign_id)
        ]
        if remove_from_order:
            order = [item for item in order if item != remove_from_order]
        order = [item for item in order if item in active_case_ids]
        order.extend(item for item in active_case_ids if item not in order)
        payload = self._campaign_plan_payload(
            connection,
            project_id,
            campaign_id,
            title=str(current.get("title") or ""),
            scope=dict(current.get("scope") or {}),
            case_order=order,
        )
        occurred_at = _utc_now()
        revision = self._append_campaign_plan_revision(
            connection,
            project_id,
            campaign_id,
            payload,
            reason=reason,
            actor=actor,
            request_id=request_id,
            occurred_at=occurred_at,
        )
        self._append_campaign_authority_event(
            connection,
            project_id=project_id,
            campaign_id=campaign_id,
            case_id=case_id or str(event_payload.get("case_id") or ""),
            oracle_id=oracle_id,
            attestation_id=attestation_id,
            event_type=event_type,
            semantic_revision=revision,
            payload={
                **dict(event_payload),
                "input_fingerprint": semantic_fingerprint(
                    request_input_payload
                    if request_input_payload is not None
                    else event_payload
                ),
            },
            actor=actor,
            request_id=request_id,
            occurred_at=occurred_at,
        )
        return self._campaign_authority_value(connection, project_id, campaign_id)

    def _campaign_plan_payload(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        title: str,
        scope: Mapping[str, object],
        case_order: Sequence[str],
    ) -> dict[str, object]:
        cases = self._active_campaign_cases(connection, project_id, campaign_id)
        obligations = self._campaign_obligation_values(
            connection, project_id, campaign_id, active_only=True
        )
        bindings = [
            dict(row)
            for row in connection.execute(
                """
                SELECT case_id, obligation_id, coverage_intent
                FROM campaign_case_obligation_bindings
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY case_id, obligation_id
                """,
                (project_id, campaign_id),
            ).fetchall()
        ]
        oracle_bindings = [
            {
                "case_id": str(row["case_id"]),
                "oracle_id": str(row["oracle_id"]),
                "oracle_revision": int(row["oracle_revision"]),
                "oracle_fingerprint": str(row["oracle_fingerprint"]),
            }
            for row in connection.execute(
                """
                SELECT case_id, oracle_id, oracle_revision, oracle_fingerprint
                FROM campaign_case_oracle_bindings
                WHERE project_id = ? AND campaign_id = ? AND active = 1
                ORDER BY case_id, oracle_id
                """,
                (project_id, campaign_id),
            ).fetchall()
        ]
        constructibility, residuals = self._derive_constructibility(
            connection,
            project_id,
            campaign_id,
            scope=scope,
            cases=cases,
            obligations=obligations,
            bindings=bindings,
            oracle_bindings=oracle_bindings,
        )
        ordered = [item for item in case_order if item in {c["case_id"] for c in cases}]
        ordered.extend(c["case_id"] for c in cases if c["case_id"] not in ordered)
        return {
            "contract_version": CAMPAIGN_PLAN_CONTRACT_VERSION,
            "campaign_id": campaign_id,
            "title": required_text(title, "title"),
            "scope": canonical_semantic_value(dict(scope)),
            "case_order": ordered,
            "cases": cases,
            "obligations": obligations,
            "obligation_bindings": bindings,
            "oracle_bindings": oracle_bindings,
            "constructibility": constructibility.value,
            "residuals": residuals,
            "qualification": "current",
        }

    def _derive_constructibility(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        scope: Mapping[str, object],
        cases: Sequence[Mapping[str, object]],
        obligations: Sequence[Mapping[str, object]],
        bindings: Sequence[Mapping[str, object]],
        oracle_bindings: Sequence[Mapping[str, object]],
    ) -> tuple[CampaignConstructibility, list[dict[str, object]]]:
        residuals: list[dict[str, object]] = []
        if not str(scope.get("change_id") or ""):
            return CampaignConstructibility.NEEDS_SCOPE, [
                _residual("scope_ambiguous", "select one governed change", "edit_scope")
            ]
        if not obligations:
            return CampaignConstructibility.NEEDS_OBLIGATIONS, [
                _residual(
                    "obligations_missing",
                    "derive proof obligations from current scope",
                    "derive_obligations",
                )
            ]
        undecided = [
            item
            for item in obligations
            if item["decision"]
            in {
                CampaignObligationDecision.UNCLASSIFIED.value,
                CampaignObligationDecision.INVESTIGATE.value,
            }
        ]
        if undecided:
            return CampaignConstructibility.NEEDS_OBLIGATIONS, [
                _residual(
                    "obligation_decision_required",
                    f"classify {item['obligation_id']}",
                    "decide_obligation",
                    subject_ref=str(item["obligation_id"]),
                )
                for item in undecided
            ]
        required_obligations = {
            str(item["obligation_id"])
            for item in obligations
            if item["decision"] == CampaignObligationDecision.REQUIRED.value
        }
        required_cases = {
            str(item["case_id"]) for item in cases if bool(item["required"])
        }
        if not required_cases:
            residuals.append(
                _residual("required_case_missing", "add a required case", "add_case")
            )
        bound_obligations = {
            str(item["obligation_id"])
            for item in bindings
            if str(item["case_id"]) in required_cases
        }
        for obligation_id in sorted(required_obligations - bound_obligations):
            residuals.append(
                _residual(
                    "obligation_unbound",
                    f"bind {obligation_id} to a required case",
                    "bind_obligation",
                    subject_ref=obligation_id,
                )
            )
        if residuals:
            return CampaignConstructibility.NEEDS_CASES, residuals
        oracle_by_case = {str(item["case_id"]): item for item in oracle_bindings}
        for case_id in sorted(required_cases):
            binding = oracle_by_case.get(case_id)
            if binding is None:
                residuals.append(
                    _residual(
                        "oracle_missing",
                        f"author an oracle for {case_id}",
                        "author_oracle",
                        subject_ref=case_id,
                    )
                )
                continue
            revision = self._oracle_revision_row(
                connection,
                project_id,
                str(binding["oracle_id"]),
                int(binding["oracle_revision"]),
            )
            if str(revision["status"]) != "constructible":
                residuals.append(
                    _residual(
                        "oracle_incomplete",
                        f"answer the next required oracle question for {case_id}",
                        "answer_question",
                        subject_ref=str(binding["oracle_id"]),
                    )
                )
        if residuals:
            return CampaignConstructibility.NEEDS_ORACLE, residuals
        return CampaignConstructibility.READY_TO_RUN, []

    def _obligation_candidates(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        scope: Mapping[str, object],
        campaign_revision: int,
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for requirement_id in scope.get("requirement_ids", []):
            row = self._requirement_row(connection, project_id, str(requirement_id))
            candidates.append(
                _obligation_candidate(
                    CampaignObligationKind.PRIMARY_BEHAVIOR,
                    subject_ref=str(row["requirement_id"]),
                    source_kind="requirement",
                    source_ref=str(row["requirement_id"]),
                    source_revision=str(row["current_revision"]),
                    statement=str(row["statement"]),
                    expected_behavior=str(row["statement"]),
                )
            )
        for goal_id in scope.get("goal_ids", []):
            row = connection.execute(
                """
                SELECT * FROM goal_nodes WHERE project_id = ? AND goal_node_id = ?
                """,
                (project_id, str(goal_id)),
            ).fetchone()
            if row is None:
                raise RequirementConflictError(f"unknown campaign goal: {goal_id}")
            payload = json.loads(str(row["payload_json"]))
            node_type = str(row["node_type"])
            kind = (
                CampaignObligationKind.SEQUENCE_COMPLETION
                if node_type == "sequence"
                else CampaignObligationKind.PRIMARY_BEHAVIOR
            )
            expected = str(
                payload.get("observable_outcome")
                or " ".join(payload.get("expected_effects") or [])
                or row["title"]
            )
            candidates.append(
                _obligation_candidate(
                    kind,
                    subject_ref=str(row["goal_node_id"]),
                    source_kind=f"goal_{node_type}",
                    source_ref=str(row["goal_node_id"]),
                    source_revision=semantic_fingerprint(payload),
                    statement=str(row["title"]),
                    expected_behavior=expected,
                )
            )
        change_id = str(scope["change_id"])
        for packet_id in scope.get("packet_ids", []):
            row = self._packet_row(connection, project_id, change_id, str(packet_id))
            standalone = connection.execute(
                "SELECT validation_version,consumption_mode,criterion_statement_fingerprint FROM external_packet_authority WHERE project_id=? AND change_id=? AND packet_id=?",
                (project_id, change_id, str(packet_id)),
            ).fetchone()
            if standalone and standalone["validation_version"] and standalone["consumption_mode"] == "external_agent":
                from flow_of_work_mcp.core.domain.external_work import fingerprint
                if standalone["criterion_statement_fingerprint"] != fingerprint(self._json_string_list(row["completion_criteria_json"])):
                    raise AssuranceBlockedError("criterion_authority_stale")
                criteria = connection.execute(
                    "SELECT number,statement FROM packet_criteria WHERE project_id=? AND change_id=? AND packet_id=? AND active=1 ORDER BY number",
                    (project_id, change_id, str(packet_id)),
                ).fetchall()
                for criterion in criteria:
                    candidates.append(_obligation_candidate(
                        CampaignObligationKind.REGRESSION,
                        subject_ref=str(packet_id), source_kind="packet_criterion",
                        source_ref=f"{packet_id}:criterion:{criterion['number']}",
                        source_revision=str(row["spec_revision"]),
                        statement=str(criterion["statement"]), expected_behavior=str(criterion["statement"]),
                    ))
            else:
                for criterion in self._json_string_list(row["completion_criteria_json"]):
                    candidates.append(
                        _obligation_candidate(
                            CampaignObligationKind.REGRESSION,
                            subject_ref=str(packet_id),
                            source_kind="packet_completion_criterion",
                            source_ref=str(packet_id),
                            source_revision=str(row["spec_revision"]),
                            statement=criterion,
                            expected_behavior=criterion,
                        )
                    )
        for finding_id in scope.get("finding_ids", []):
            row = self._finding_row(connection, project_id, str(finding_id))
            candidates.append(
                _obligation_candidate(
                    CampaignObligationKind.REGRESSION,
                    subject_ref=str(finding_id),
                    source_kind="finding",
                    source_ref=str(finding_id),
                    source_revision=str(row["updated_at"]),
                    statement=str(row["expected_correction"]),
                    expected_behavior=str(row["expected_correction"]),
                    prohibited_behavior=str(row["rationale"]),
                )
            )
        for index, invariant in enumerate(scope.get("invariants", []), start=1):
            candidates.append(
                _obligation_candidate(
                    CampaignObligationKind.INVARIANT_PRESERVATION,
                    subject_ref=f"{campaign_id}:invariant:{index}",
                    source_kind="campaign_invariant",
                    source_ref=campaign_id,
                    source_revision=str(campaign_revision),
                    statement=str(invariant),
                    expected_behavior=str(invariant),
                    prohibited_behavior=f"violate: {invariant}",
                )
            )
        unique: dict[str, dict[str, str]] = {}
        for item in candidates:
            unique.setdefault(semantic_fingerprint(item), item)
        return list(unique.values())

    def _validate_campaign_scope(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        scope: CampaignScopeDraft,
    ) -> None:
        change = self._change_row(connection, project_id, scope.change_id)
        change_requirements = set(
            self._json_string_list(change["requirement_ids_json"])
        )
        for requirement_id in scope.requirement_ids:
            self._requirement_row(connection, project_id, requirement_id)
            if requirement_id not in change_requirements:
                raise AssuranceBlockedError(
                    "campaign_requirement_outside_change",
                    details={"requirement_id": requirement_id},
                )
        for packet_id in scope.packet_ids:
            self._packet_row(connection, project_id, scope.change_id, packet_id)
        for finding_id in scope.finding_ids:
            finding = self._finding_row(connection, project_id, finding_id)
            if str(finding["change_id"]) != scope.change_id:
                raise AssuranceBlockedError(
                    "campaign_finding_cross_change", details={"finding_id": finding_id}
                )
        if scope.milestone_id:
            row = connection.execute(
                """
                SELECT 1 FROM milestones WHERE project_id = ? AND milestone_id = ?
                """,
                (project_id, scope.milestone_id),
            ).fetchone()
            if row is None:
                raise RequirementConflictError(
                    f"unknown campaign milestone: {scope.milestone_id}"
                )
        for goal_id in scope.goal_ids:
            row = connection.execute(
                "SELECT 1 FROM goal_nodes WHERE project_id = ? AND goal_node_id = ?",
                (project_id, goal_id),
            ).fetchone()
            if row is None:
                raise RequirementConflictError(f"unknown campaign goal: {goal_id}")

    def _insert_campaign_case(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        draft: CampaignCaseSemanticDraft,
        *,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> str:
        ordinal = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(ordinal), 0) + 1 AS value
                FROM campaign_cases WHERE project_id = ? AND campaign_id = ?
                """,
                (project_id, campaign_id),
            ).fetchone()["value"]
        )
        case_id = f"CASE-{ordinal:06d}"
        evidence_kind = (
            "live_test"
            if draft.execution_class in {"live", "integration"}
            else "deterministic_test"
        )
        connection.execute(
            """
            INSERT INTO campaign_cases(
                project_id, campaign_id, case_id, ordinal, title, purpose,
                case_kind, evidence_kind, required, result, created_at,
                updated_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                project_id,
                campaign_id,
                case_id,
                ordinal,
                draft.title,
                draft.purpose,
                draft.case_kind,
                evidence_kind,
                int(draft.required),
                occurred_at,
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )
        payload = draft.as_payload()
        connection.execute(
            """
            INSERT INTO campaign_case_revisions(
                project_id, campaign_id, case_id, revision, payload_json,
                semantic_fingerprint, active, created_at, actor, request_id
            ) VALUES (?, ?, ?, 1, ?, ?, 1, ?, ?, ?)
            """,
            (
                project_id,
                campaign_id,
                case_id,
                self._json(payload),
                semantic_fingerprint(payload),
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )
        return case_id

    def _append_campaign_plan_revision(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        payload: Mapping[str, object],
        *,
        reason: str,
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> int:
        current = connection.execute(
            """
            SELECT current_revision FROM campaign_plan_heads
            WHERE project_id = ? AND campaign_id = ?
            """,
            (project_id, campaign_id),
        ).fetchone()
        fingerprint = semantic_fingerprint(payload)
        if current is not None:
            current_fingerprint = connection.execute(
                """
                SELECT semantic_fingerprint FROM campaign_plan_heads
                WHERE project_id = ? AND campaign_id = ?
                """,
                (project_id, campaign_id),
            ).fetchone()
            if (
                current_fingerprint is not None
                and str(current_fingerprint["semantic_fingerprint"]) == fingerprint
            ):
                return int(current["current_revision"])
        revision = int(current["current_revision"]) + 1 if current is not None else 1
        connection.execute(
            """
            INSERT INTO campaign_plan_revisions(
                project_id, campaign_id, revision, contract_version, payload_json,
                semantic_fingerprint, reason, created_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                campaign_id,
                revision,
                CAMPAIGN_PLAN_CONTRACT_VERSION,
                self._json(payload),
                fingerprint,
                required_text(reason, "reason"),
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )
        connection.execute(
            """
            INSERT INTO campaign_plan_heads(
                project_id, campaign_id, current_revision, semantic_fingerprint,
                constructibility, qualification, updated_at, actor
            ) VALUES (?, ?, ?, ?, ?, 'current', ?, ?)
            ON CONFLICT(project_id, campaign_id) DO UPDATE SET
                current_revision = excluded.current_revision,
                semantic_fingerprint = excluded.semantic_fingerprint,
                constructibility = excluded.constructibility,
                qualification = excluded.qualification,
                updated_at = excluded.updated_at,
                actor = excluded.actor
            """,
            (
                project_id,
                campaign_id,
                revision,
                fingerprint,
                str(payload["constructibility"]),
                occurred_at,
                actor,
            ),
        )
        connection.execute(
            """
            UPDATE verification_campaigns SET updated_at = ?
            WHERE project_id = ? AND campaign_id = ?
            """,
            (occurred_at, project_id, campaign_id),
        )
        return revision

    def _campaign_authority_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        history_limit: int = 20,
    ) -> Mapping[str, Any]:
        campaign = self._campaign_row(connection, project_id, campaign_id)
        head = connection.execute(
            """
            SELECT * FROM campaign_plan_heads
            WHERE project_id = ? AND campaign_id = ?
            """,
            (project_id, campaign_id),
        ).fetchone()
        if head is None:
            return {
                "project_id": project_id,
                "campaign_id": campaign_id,
                "change_id": str(campaign["change_id"]),
                "title": str(campaign["title"]),
                "status": str(campaign["status"]),
                "qualification": "legacy_unqualified",
                "constructibility": CampaignConstructibility.DRAFT.value,
                "revision": 0,
                "fingerprint": "",
                "cases": self._campaign_value(connection, project_id, campaign_id)[
                    "cases"
                ],
                "evidence": [],
                "exception": None,
                "residuals": [
                    _residual(
                        "legacy_campaign_unqualified",
                        "qualify this campaign through the canonical authoring surface",
                        "start_campaign",
                    )
                ],
            }
        revision = connection.execute(
            """
            SELECT * FROM campaign_plan_revisions
            WHERE project_id = ? AND campaign_id = ? AND revision = ?
            """,
            (project_id, campaign_id, int(head["current_revision"])),
        ).fetchone()
        if revision is None:
            raise RequirementConflictError(
                "campaign plan head references missing revision"
            )
        plan_payload = dict(json.loads(str(revision["payload_json"])))
        plan_payload["cases"] = self._campaign_case_runtime_values(
            connection,
            project_id,
            campaign_id,
            list(plan_payload.get("cases") or []),
        )
        history = [
            {
                "revision": int(row["revision"]),
                "fingerprint": str(row["semantic_fingerprint"]),
                "reason": str(row["reason"]),
                "created_at": str(row["created_at"]),
                "actor": str(row["actor"]),
            }
            for row in connection.execute(
                """
                SELECT revision, semantic_fingerprint, reason, created_at, actor
                FROM campaign_plan_revisions
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (project_id, campaign_id, history_limit),
            ).fetchall()
        ]
        oracles = []
        seen_oracles: set[str] = set()
        for binding in plan_payload.get("oracle_bindings", []):
            oracle_id = str(binding["oracle_id"])
            if oracle_id not in seen_oracles:
                oracles.append(self._oracle_value(connection, project_id, oracle_id))
                seen_oracles.add(oracle_id)
        attestations = [
            self._attestation_value(connection, row)
            for row in connection.execute(
                """
                SELECT * FROM campaign_attestation_intents
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY ordinal
                """,
                (project_id, campaign_id),
            ).fetchall()
        ]
        evidence = self._campaign_execution_evidence_values(
            connection,
            project_id,
            campaign_id,
            limit=None,
        )
        exception_row = connection.execute(
            """
            SELECT payload_json, occurred_at, actor
            FROM campaign_authority_events
            WHERE project_id = ? AND campaign_id = ?
              AND event_type = 'campaign_exception_accepted'
            ORDER BY event_id DESC LIMIT 1
            """,
            (project_id, campaign_id),
        ).fetchone()
        exception = None
        if exception_row is not None:
            exception = {
                **json.loads(str(exception_row["payload_json"])),
                "occurred_at": str(exception_row["occurred_at"]),
                "actor": str(exception_row["actor"]),
            }
        promotion_authorizations = []
        for row in connection.execute(
            """
            SELECT event_id, case_id, semantic_revision, payload_json,
                   occurred_at, actor, request_id
            FROM campaign_authority_events
            WHERE project_id = ? AND campaign_id = ?
              AND event_type = 'campaign_promotion_authorized'
            ORDER BY event_id DESC
            """,
            (project_id, campaign_id),
        ).fetchall():
            authorization_payload = json.loads(str(row["payload_json"]))
            promotion_authorizations.append(
                {
                    **authorization_payload,
                    "event_id": int(row["event_id"]),
                    "case_id": str(row["case_id"]),
                    "semantic_revision": int(row["semantic_revision"]),
                    "current": int(row["semantic_revision"])
                    == int(head["current_revision"]),
                    "occurred_at": str(row["occurred_at"]),
                    "actor": str(row["actor"]),
                    "request_id": str(row["request_id"]),
                }
            )
        completion_row = connection.execute(
            """
            SELECT event_id, semantic_revision, payload_json, occurred_at,
                   actor, request_id
            FROM campaign_authority_events
            WHERE project_id = ? AND campaign_id = ?
              AND event_type = 'campaign_completion_recorded'
            ORDER BY event_id DESC LIMIT 1
            """,
            (project_id, campaign_id),
        ).fetchone()
        completion = None
        if completion_row is not None:
            completion = {
                **json.loads(str(completion_row["payload_json"])),
                "event_id": int(completion_row["event_id"]),
                "semantic_revision": int(completion_row["semantic_revision"]),
                "current": int(completion_row["semantic_revision"])
                == int(head["current_revision"]),
                "occurred_at": str(completion_row["occurred_at"]),
                "actor": str(completion_row["actor"]),
                "request_id": str(completion_row["request_id"]),
            }
        return {
            "project_id": project_id,
            "campaign_id": campaign_id,
            "change_id": str(campaign["change_id"]),
            "status": str(campaign["status"]),
            "qualification": str(head["qualification"]),
            "constructibility": str(head["constructibility"]),
            "revision": int(head["current_revision"]),
            "fingerprint": str(head["semantic_fingerprint"]),
            **plan_payload,
            "oracles": oracles,
            "attestations": attestations,
            "evidence": evidence,
            "exception": exception,
            "promotion_authorizations": promotion_authorizations,
            "completion": completion,
            "history": history,
        }

    def _campaign_case_runtime_values(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        semantic_cases: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        runtime_rows = {
            str(row["case_id"]): row
            for row in connection.execute(
                """
                SELECT * FROM campaign_cases
                WHERE project_id = ? AND campaign_id = ?
                """,
                (project_id, campaign_id),
            ).fetchall()
        }
        result: list[dict[str, object]] = []
        for semantic in semantic_cases:
            value = dict(semantic)
            row = runtime_rows.get(str(value.get("case_id") or ""))
            if row is not None:
                value.update(
                    {
                        "ordinal": int(row["ordinal"]),
                        "evidence_kind": str(row["evidence_kind"]),
                        "result": str(row["result"]),
                        "evidence_reference": str(row["evidence_reference"]),
                        "evidence_metadata": json.loads(str(row["metadata_json"])),
                        "covered_requirement_ids": self._json_string_list(
                            row["covered_requirement_ids_json"]
                        ),
                        "covered_use_case_goal_node_ids": self._json_string_list(
                            row["covered_use_case_goal_node_ids_json"]
                        ),
                        "covered_sequence_goal_node_ids": self._json_string_list(
                            row["covered_sequence_goal_node_ids_json"]
                        ),
                        "coverage_notes": str(row["coverage_notes"]),
                    }
                )
            result.append(value)
        return result

    def _sync_case_coverage_from_obligations(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT o.source_kind, o.source_ref, b.coverage_intent
            FROM campaign_case_obligation_bindings b
            JOIN campaign_obligations o
              ON o.project_id = b.project_id
             AND o.campaign_id = b.campaign_id
             AND o.obligation_id = b.obligation_id
            WHERE b.project_id = ? AND b.campaign_id = ? AND b.case_id = ?
              AND o.active = 1
            ORDER BY o.ordinal
            """,
            (project_id, campaign_id, case_id),
        ).fetchall()
        requirements = sorted(
            {
                str(row["source_ref"])
                for row in rows
                if str(row["source_kind"]) == "requirement"
            }
        )
        use_cases = sorted(
            {
                str(row["source_ref"])
                for row in rows
                if str(row["source_kind"]) == "goal_use_case"
            }
        )
        sequences = sorted(
            {
                str(row["source_ref"])
                for row in rows
                if str(row["source_kind"]) == "goal_sequence"
            }
        )
        notes = "; ".join(dict.fromkeys(str(row["coverage_intent"]) for row in rows))
        connection.execute(
            """
            UPDATE campaign_cases
            SET covered_requirement_ids_json = ?,
                covered_use_case_goal_node_ids_json = ?,
                covered_sequence_goal_node_ids_json = ?,
                coverage_notes = ?
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
            """,
            (
                self._json(requirements),
                self._json(use_cases),
                self._json(sequences),
                notes,
                project_id,
                campaign_id,
                case_id,
            ),
        )

    def _invalidate_case_execution_authority(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
        *,
        actor: str,
        request_id: str,
    ) -> None:
        occurred_at = _utc_now()
        connection.execute(
            """
            UPDATE campaign_attestation_intents
            SET state = 'invalidated', updated_at = ?, actor = ?
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
              AND state IN ('pending_technical_validation', 'attested_current')
            """,
            (occurred_at, actor, project_id, campaign_id, case_id),
        )
        connection.execute(
            """
            UPDATE campaign_cases
            SET result = 'pending', evidence_reference = '', metadata_json = '{}',
                updated_at = ?, actor = ?, request_id = ?
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
            """,
            (
                occurred_at,
                actor,
                str(request_id or ""),
                project_id,
                campaign_id,
                case_id,
            ),
        )
        self._derive_campaign_status(connection, project_id, campaign_id, occurred_at)

    def _invalidate_stale_oracle_ir_authority(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        *,
        actor: str,
        request_id: str,
        reason: str,
    ) -> tuple[str, ...]:
        """Invalidate active IR authority whose bound requirements have drifted."""

        rows = connection.execute(
            """
            SELECT * FROM campaign_attestation_intents
            WHERE project_id = ? AND materialization_mode = ?
              AND state IN ('pending_technical_validation', 'attested_current')
            ORDER BY ordinal
            """,
            (
                project_id,
                TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value,
            ),
        ).fetchall()
        stale = [
            row
            for row in rows
            if not self._oracle_ir_attestation_dependency_current(connection, row)
        ]
        if not stale:
            return ()

        occurred_at = _utc_now()
        stale_ids = {str(row["attestation_id"]) for row in stale}
        impacted_cases: set[tuple[str, str]] = set()
        for row in stale:
            basis = json.loads(str(row["basis_json"] or "{}"))
            basis["invalidation"] = {
                "reason": reason,
                "authority_input_fingerprint": str(
                    row["authority_input_fingerprint"]
                ),
            }
            connection.execute(
                """
                UPDATE campaign_attestation_intents
                SET state = 'invalidated', basis_json = ?, updated_at = ?, actor = ?
                WHERE project_id = ? AND attestation_id = ?
                """,
                (
                    self._json(basis),
                    occurred_at,
                    actor,
                    project_id,
                    str(row["attestation_id"]),
                ),
            )
            campaign_id = str(row["campaign_id"])
            case_id = str(row["case_id"])
            impacted_cases.add((campaign_id, case_id))
            head = self._qualified_campaign_head(connection, project_id, campaign_id)
            self._append_campaign_authority_event(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                case_id=case_id,
                oracle_id=str(row["oracle_id"]),
                attestation_id=str(row["attestation_id"]),
                event_type="oracle_ir_authority_invalidated",
                semantic_revision=int(head["current_revision"]),
                payload={"reason": reason},
                actor=actor,
                request_id=request_id,
                occurred_at=occurred_at,
            )

        for command_row in connection.execute(
            """
            SELECT command_id, command_json FROM test_provider_outbox
            WHERE project_id = ? AND state IN ('pending', 'unknown', 'delivering')
            """,
            (project_id,),
        ).fetchall():
            command = json.loads(str(command_row["command_json"]))
            if str(command.get("attestation_intent_ref") or "") not in stale_ids:
                continue
            connection.execute(
                """
                UPDATE test_provider_outbox
                SET state = 'rejected', last_error = ?, updated_at = ?
                WHERE project_id = ? AND command_id = ?
                """,
                (
                    "test_provider_command_oracle_ir_stale",
                    occurred_at,
                    project_id,
                    str(command_row["command_id"]),
                ),
            )

        for campaign_id, case_id in impacted_cases:
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = 'pending', evidence_reference = '', metadata_json = '{}',
                    updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    occurred_at,
                    actor,
                    str(request_id or ""),
                    project_id,
                    campaign_id,
                    case_id,
                ),
            )
            self._derive_campaign_status(
                connection, project_id, campaign_id, occurred_at
            )
        return tuple(sorted(stale_ids))

    def _oracle_ir_attestation_dependency_current(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> bool:
        if (
            str(row["materialization_mode"])
            != TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value
        ):
            return True
        try:
            oracle = self._oracle_value(
                connection,
                str(row["project_id"]),
                str(row["oracle_id"]),
                revision=int(row["oracle_revision"]),
            )
            projection = compile_oracle_ir(oracle)
        except (AssuranceBlockedError, RequirementConflictError, ValueError):
            return False
        return bool(
            projection.constructible
            and projection.snapshot is not None
            and projection.snapshot.fingerprint
            == str(row["authority_input_fingerprint"])
            and projection.snapshot.fingerprint == str(row["oracle_ir_fingerprint"])
        )

    def _oracle_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        oracle_id: str,
        *,
        revision: int | None = None,
    ) -> Mapping[str, Any]:
        head = self._oracle_head(connection, project_id, oracle_id)
        selected_revision = int(revision or head["current_revision"])
        row = self._oracle_revision_row(
            connection, project_id, oracle_id, selected_revision
        )
        question_values = [
            {
                "question_id": str(item["question_id"]),
                "scope": str(item["question_scope"]),
                "field_name": str(item["field_name"]),
                "prompt": str(item["prompt"]),
                "choices": json.loads(str(item["choices_json"])),
                "required": bool(item["required"]),
                "answer_authority": str(item["answer_authority"]),
                "answer": json.loads(str(item["answer_json"])),
                "provenance": json.loads(str(item["provenance_json"])),
                "waiver_scope": str(item["waiver_scope"]),
            }
            for item in connection.execute(
                """
                SELECT * FROM oracle_questions
                WHERE project_id = ? AND oracle_id = ? AND oracle_revision = ?
                ORDER BY ordinal
                """,
                (project_id, oracle_id, selected_revision),
            ).fetchall()
        ]
        questions = [
            item for item in question_values if item["scope"] == "source"
        ]
        oracle_ir_questions = [
            item for item in question_values if item["scope"] == "oracle_ir"
        ]
        return {
            "oracle_id": oracle_id,
            "revision": selected_revision,
            "fingerprint": str(row["semantic_fingerprint"]),
            "status": str(row["status"]),
            "current": selected_revision == int(head["current_revision"]),
            "dependency_fingerprint": str(row["dependency_fingerprint"]),
            "current_dependency_fingerprint": (
                self._current_oracle_dependency_fingerprint(
                    connection,
                    project_id,
                    json.loads(str(row["payload_json"])),
                )
            ),
            "field_authority": json.loads(str(row["field_authority_json"] or "{}")),
            "payload": json.loads(str(row["payload_json"])),
            "questions": questions,
            "oracle_ir_questions": oracle_ir_questions,
        }

    def _current_oracle_dependency_fingerprint(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        payload: Mapping[str, object],
    ) -> str:
        def binding(ref: object) -> dict[str, object]:
            value = str(ref or "")
            requirement = connection.execute(
                """
                SELECT current_revision, lifecycle_status
                FROM requirements
                WHERE project_id = ? AND requirement_id = ?
                """,
                (project_id, value),
            ).fetchone()
            if requirement is not None:
                return {
                    "kind": "requirement",
                    "ref": value,
                    "revision": int(requirement["current_revision"]),
                    "status": str(requirement["lifecycle_status"]),
                }
            goal = connection.execute(
                """
                SELECT node_type, title, payload_json, source_anchor_json
                FROM goal_nodes
                WHERE project_id = ? AND goal_node_id = ?
                """,
                (project_id, value),
            ).fetchone()
            if goal is not None:
                return {
                    "kind": "goal",
                    "ref": value,
                    "fingerprint": semantic_fingerprint(
                        {
                            "node_type": str(goal["node_type"]),
                            "title": str(goal["title"]),
                            "payload": json.loads(str(goal["payload_json"])),
                            "source_anchor": json.loads(
                                str(goal["source_anchor_json"])
                            ),
                        }
                    ),
                }
            return {"kind": "external", "ref": value}

        return semantic_fingerprint(
            {
                "authority_reference": str(payload.get("authority_reference") or ""),
                "subject_bindings": [
                    binding(item) for item in payload.get("subject_bindings", [])
                ],
                "goal_bindings": [
                    binding(item) for item in payload.get("goal_bindings", [])
                ],
            }
        )

    def _replace_oracle_questions(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        oracle_id: str,
        revision: int,
        payload: Mapping[str, object],
    ) -> None:
        missing = self._oracle_missing_fields(payload)
        for ordinal, field_name in enumerate(missing, start=1):
            connection.execute(
                """
                INSERT INTO oracle_questions(
                    project_id, oracle_id, oracle_revision, question_id,
                    ordinal, question_scope, field_name, prompt, choices_json, required
                ) VALUES (?, ?, ?, ?, ?, 'source', ?, ?, ?, 1)
                """,
                (
                    project_id,
                    oracle_id,
                    revision,
                    _oracle_question_id(field_name),
                    ordinal,
                    field_name,
                    _oracle_question_prompt(field_name),
                    self._json(_oracle_question_choices(field_name)),
                ),
            )
        if missing:
            return
        source = self._oracle_value(connection, project_id, oracle_id, revision=revision)
        projection = compile_oracle_ir(source)
        for ordinal, residual in enumerate(projection.residuals, start=1):
            if residual.field_name not in _ORACLE_IR_ANSWERABLE_FIELDS:
                continue
            connection.execute(
                """
                INSERT INTO oracle_questions(
                    project_id, oracle_id, oracle_revision, question_id,
                    ordinal, question_scope, field_name, prompt, choices_json, required
                ) VALUES (?, ?, ?, ?, ?, 'oracle_ir', ?, ?, ?, 1)
                """,
                (
                    project_id,
                    oracle_id,
                    revision,
                    residual.question_id,
                    ordinal,
                    residual.field_name,
                    _oracle_ir_question_prompt(residual.field_name, residual.detail),
                    self._json(_oracle_ir_question_choices(residual.value_shape)),
                ),
            )

    @staticmethod
    def _oracle_missing_fields(payload: Mapping[str, object]) -> list[str]:
        fields = payload.get("semantic_fields")
        values = fields if isinstance(fields, Mapping) else {}
        missing = [
            field
            for field in _ORACLE_REQUIRED_FIELDS
            if field not in values
            or (
                field not in _ORACLE_EXPLICIT_EMPTY_FIELDS
                and not _semantic_present(values.get(field))
            )
        ]
        kind = str(payload.get("oracle_kind") or "").lower()
        if any(
            token in kind
            for token in ("state", "async", "integration", "boundary", "failure")
        ):
            conditional = {
                "state": ("initial_state", "terminal_state", "cleanup_state"),
                "async": ("ordering", "timeout", "observation_timing"),
                "integration": ("participants", "real_mock_boundaries"),
                "boundary": ("partitions", "boundary_points"),
                "failure": ("failure_trigger", "forbidden_terminal_effects"),
            }
            for token, names in conditional.items():
                if token in kind:
                    missing.extend(
                        name
                        for name in names
                        if not _semantic_present(values.get(name))
                    )
        return missing

    def _active_campaign_cases(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT r.*
            FROM campaign_case_revisions r
            JOIN (
                SELECT case_id, MAX(revision) AS revision
                FROM campaign_case_revisions
                WHERE project_id = ? AND campaign_id = ?
                GROUP BY case_id
            ) latest ON latest.case_id = r.case_id AND latest.revision = r.revision
            WHERE r.project_id = ? AND r.campaign_id = ? AND r.active = 1
            ORDER BY r.case_id
            """,
            (project_id, campaign_id, project_id, campaign_id),
        ).fetchall()
        return [
            {
                "case_id": str(row["case_id"]),
                "revision": int(row["revision"]),
                "fingerprint": str(row["semantic_fingerprint"]),
                **json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]

    def _campaign_obligation_values(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        active_only: bool,
    ) -> list[dict[str, object]]:
        suffix = "AND active = 1" if active_only else ""
        return [
            {
                "obligation_id": str(row["obligation_id"]),
                "kind": str(row["kind"]),
                "subject_ref": str(row["subject_ref"]),
                "source_kind": str(row["source_kind"]),
                "source_ref": str(row["source_ref"]),
                "source_revision": str(row["source_revision"]),
                "statement": str(row["statement"]),
                "expected_behavior": str(row["expected_behavior"]),
                "prohibited_behavior": str(row["prohibited_behavior"]),
                "decision": str(row["decision"]),
                "rationale": str(row["rationale"]),
                "fresh": bool(row["active"]),
            }
            for row in connection.execute(
                f"""
                SELECT * FROM campaign_obligations
                WHERE project_id = ? AND campaign_id = ? {suffix}
                ORDER BY ordinal
                """,
                (project_id, campaign_id),
            ).fetchall()
        ]

    def _current_campaign_plan_payload(
        self, connection: sqlite3.Connection, project_id: str, campaign_id: str
    ) -> dict[str, object]:
        head = self._qualified_campaign_head(connection, project_id, campaign_id)
        row = connection.execute(
            """
            SELECT payload_json FROM campaign_plan_revisions
            WHERE project_id = ? AND campaign_id = ? AND revision = ?
            """,
            (project_id, campaign_id, int(head["current_revision"])),
        ).fetchone()
        if row is None:
            raise RequirementConflictError("campaign plan revision is missing")
        value = json.loads(str(row["payload_json"]))
        if not isinstance(value, dict):
            raise RequirementConflictError("campaign plan payload is invalid")
        return value

    def _current_scope(
        self, connection: sqlite3.Connection, project_id: str, campaign_id: str
    ) -> Mapping[str, object]:
        payload = self._current_campaign_plan_payload(
            connection, project_id, campaign_id
        )
        scope = payload.get("scope")
        if not isinstance(scope, Mapping):
            raise RequirementConflictError("campaign scope is invalid")
        return scope

    def _qualified_campaign_head(
        self, connection: sqlite3.Connection, project_id: str, campaign_id: str
    ) -> sqlite3.Row:
        campaign = self._campaign_row(connection, project_id, campaign_id)
        row = connection.execute(
            """
            SELECT * FROM campaign_plan_heads
            WHERE project_id = ? AND campaign_id = ?
            """,
            (project_id, campaign_id),
        ).fetchone()
        if row is None or str(row["qualification"]) != "current":
            raise AssuranceBlockedError("campaign_legacy_unqualified")
        if str(campaign["status"]) in {"cancelled", "accepted_exception"}:
            raise AssuranceBlockedError("campaign_inactive")
        completion = connection.execute(
            """
            SELECT 1 FROM campaign_authority_events
            WHERE project_id = ? AND campaign_id = ?
              AND event_type = 'campaign_completion_recorded'
              AND semantic_revision = ?
            LIMIT 1
            """,
            (project_id, campaign_id, int(row["current_revision"])),
        ).fetchone()
        if completion is not None:
            raise AssuranceBlockedError("campaign_inactive")
        return row

    def _active_case_revision(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> sqlite3.Row:
        self._campaign_case_row(connection, project_id, campaign_id, case_id)
        row = connection.execute(
            """
            SELECT * FROM campaign_case_revisions
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
            ORDER BY revision DESC LIMIT 1
            """,
            (project_id, campaign_id, case_id),
        ).fetchone()
        if row is None or not bool(row["active"]):
            raise RequirementConflictError(f"campaign case is not active: {case_id}")
        return row

    @staticmethod
    def _next_case_revision(
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> int:
        return int(
            connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) + 1 AS value
                FROM campaign_case_revisions
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (project_id, campaign_id, case_id),
            ).fetchone()["value"]
        )

    def _obligation_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        obligation_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM campaign_obligations
            WHERE project_id = ? AND campaign_id = ? AND obligation_id = ?
            """,
            (project_id, campaign_id, obligation_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown campaign obligation: {obligation_id}"
            )
        return row

    @staticmethod
    def _oracle_head(
        connection: sqlite3.Connection, project_id: str, oracle_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM behavioral_oracles WHERE project_id = ? AND oracle_id = ?
            """,
            (project_id, oracle_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(f"unknown behavioral oracle: {oracle_id}")
        return row

    @staticmethod
    def _oracle_revision_row(
        connection: sqlite3.Connection,
        project_id: str,
        oracle_id: str,
        revision: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM behavioral_oracle_revisions
            WHERE project_id = ? AND oracle_id = ? AND revision = ?
            """,
            (project_id, oracle_id, revision),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown behavioral oracle revision: {oracle_id}@{revision}"
            )
        return row

    @staticmethod
    def _current_case_oracle_binding(
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM campaign_case_oracle_bindings
            WHERE project_id = ? AND campaign_id = ? AND case_id = ? AND active = 1
            ORDER BY oracle_revision DESC LIMIT 1
            """,
            (project_id, campaign_id, case_id),
        ).fetchone()
        if row is None:
            raise AssuranceBlockedError(
                "campaign_case_oracle_missing", details={"case_id": case_id}
            )
        return row

    def _next_campaign_authority_ordinal(
        self, connection: sqlite3.Connection, project_id: str, kind: str
    ) -> int:
        connection.execute(
            """
            INSERT OR IGNORE INTO campaign_authority_sequences(project_id)
            VALUES (?)
            """,
            (project_id,),
        )
        column = {
            "obligation": "next_obligation_ordinal",
            "oracle": "next_oracle_ordinal",
            "attestation": "next_attestation_ordinal",
            "command": "next_command_ordinal",
            "receipt": "next_receipt_ordinal",
        }[kind]
        row = connection.execute(
            f"SELECT {column} AS value FROM campaign_authority_sequences WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        ordinal = int(row["value"])
        connection.execute(
            f"UPDATE campaign_authority_sequences SET {column} = ? WHERE project_id = ?",
            (ordinal + 1, project_id),
        )
        return ordinal

    def _mutation_replay(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        event_type: str,
        request_id: str,
        input_payload: Mapping[str, object],
    ) -> Mapping[str, Any] | None:
        replay = self._campaign_authority_request_event(
            connection, project_id, event_type, request_id
        )
        if replay is None:
            return None
        if str(replay["campaign_id"]) != campaign_id:
            raise RequirementConflictError(
                "campaign request_id conflicts across campaigns"
            )
        self._assert_replay_fingerprint(
            replay,
            semantic_fingerprint(input_payload),
            event_type=event_type,
            input_payload=input_payload,
        )
        return self._campaign_authority_value(connection, project_id, campaign_id) | {
            "replayed": True
        }

    @staticmethod
    def _campaign_authority_request_event(
        connection: sqlite3.Connection,
        project_id: str,
        event_type: str,
        request_id: str,
    ) -> sqlite3.Row | None:
        if not request_id:
            return None
        return connection.execute(
            """
            SELECT * FROM campaign_authority_events
            WHERE project_id = ? AND event_type = ? AND request_id = ?
            ORDER BY event_id LIMIT 1
            """,
            (project_id, event_type, request_id),
        ).fetchone()

    @staticmethod
    def _assert_replay_fingerprint(
        row: sqlite3.Row,
        expected: str,
        *,
        event_type: str,
        input_payload: Mapping[str, object],
    ) -> None:
        payload = json.loads(str(row["payload_json"]))
        stored = str(payload.get("input_fingerprint") or "")
        if stored == expected:
            return
        legacy_fields = {
            "campaign_case_added": ("case_id",),
            "behavioral_oracle_authored": ("oracle_id", "oracle_revision"),
            "oracle_question_answered": ("oracle_revision",),
            "attestation_intent_created": ("attestation_id",),
        }.get(event_type, ())
        legacy_input = dict(input_payload)
        for field in legacy_fields:
            if field in payload:
                legacy_input[field] = payload[field]
        if legacy_fields and stored == semantic_fingerprint(legacy_input):
            return
        raise RequirementConflictError(
            "campaign request_id conflicts with durable semantic input"
        )

    @staticmethod
    def _guard_campaign_fingerprint(row: sqlite3.Row, expected: str) -> None:
        if expected and str(row["semantic_fingerprint"]) != expected:
            raise AssuranceBlockedError(
                "campaign_revision_stale",
                details={"current_fingerprint": str(row["semantic_fingerprint"])},
            )

    @staticmethod
    def _append_campaign_authority_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        event_type: str,
        semantic_revision: int,
        payload: Mapping[str, object],
        actor: str,
        request_id: str,
        occurred_at: str,
        campaign_id: str = "",
        case_id: str = "",
        oracle_id: str = "",
        attestation_id: str = "",
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO campaign_authority_events(
                project_id, campaign_id, case_id, oracle_id, attestation_id,
                event_type, semantic_revision, payload_json, occurred_at,
                actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                campaign_id,
                case_id,
                oracle_id,
                attestation_id,
                event_type,
                semantic_revision,
                json.dumps(dict(payload), sort_keys=True, separators=(",", ":")),
                occurred_at,
                actor,
                str(request_id or ""),
            ),
        )
        return int(cursor.lastrowid)

    def _attestation_value(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> Mapping[str, object]:
        value: dict[str, object] = {
            "attestation_id": str(row["attestation_id"]),
            "ordinal": int(row["ordinal"]),
            "campaign_id": str(row["campaign_id"]),
            "case_id": str(row["case_id"]),
            "oracle_id": str(row["oracle_id"]),
            "oracle_revision": int(row["oracle_revision"]),
            "oracle_fingerprint": str(row["oracle_fingerprint"]),
            "materialization_mode": str(row["materialization_mode"]),
            "authority_input_fingerprint": str(row["authority_input_fingerprint"]),
            "source_manifest_digest": str(row["source_manifest_digest"]),
            "source_manifest": json.loads(str(row["source_manifest_json"])),
            "oracle_ir_contract_version": str(row["oracle_ir_contract_version"]),
            "oracle_ir_operator_profile": str(row["oracle_ir_operator_profile"]),
            "oracle_ir_fingerprint": str(row["oracle_ir_fingerprint"]),
            "oracle_ir": json.loads(str(row["oracle_ir_json"])),
            "requested_capability": json.loads(
                str(row["requested_capability_json"])
            ),
            "requested_capability_fingerprint": str(
                row["requested_capability_fingerprint"]
            ),
            "harness": json.loads(str(row["harness_json"])),
            "harness_fingerprint": str(row["harness_fingerprint"]),
            "authority_reference": str(row["authority_reference"]),
            "state": str(row["state"]),
            "provider_materialization_ref": str(row["provider_materialization_ref"]),
            "representation_fingerprint": str(row["representation_fingerprint"]),
            "basis": json.loads(str(row["basis_json"])),
        }
        if not self._oracle_ir_attestation_dependency_current(connection, row):
            value["state"] = MaterializationAttestationState.INVALIDATED.value
            value["basis"] = {
                **dict(value["basis"]),
                "effective_invalidation": {
                    "reason": "oracle_dependency_drift",
                    "persisted_state": str(row["state"]),
                },
            }
        return value


def _obligation_candidate(
    kind: CampaignObligationKind,
    *,
    subject_ref: str,
    source_kind: str,
    source_ref: str,
    source_revision: str,
    statement: str,
    expected_behavior: str = "",
    prohibited_behavior: str = "",
) -> dict[str, str]:
    return {
        "kind": kind.value,
        "subject_ref": required_text(subject_ref, "subject_ref"),
        "source_kind": required_text(source_kind, "source_kind"),
        "source_ref": required_text(source_ref, "source_ref"),
        "source_revision": required_text(source_revision, "source_revision"),
        "statement": required_text(statement, "statement"),
        "expected_behavior": str(expected_behavior or "").strip(),
        "prohibited_behavior": str(prohibited_behavior or "").strip(),
    }


def _residual(
    kind: str,
    missing_fact: str,
    next_operation: str,
    *,
    subject_ref: str = "",
) -> dict[str, object]:
    return {
        "kind": kind,
        "subject_ref": subject_ref,
        "missing_fact": missing_fact,
        "next_action": {
            "tool": "fow_campaign_author",
            "operation": next_operation,
        },
    }


def _semantic_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _initial_oracle_field_authority(
    payload: Mapping[str, object], authority_reference: str
) -> dict[str, dict[str, object]]:
    """Record explicit draft authorship without inferring legacy provenance."""

    fields = payload.get("semantic_fields")
    if not isinstance(fields, Mapping):
        return {}
    provenance = required_text(authority_reference, "authority_reference")
    return {
        str(field_name): {
            "authority": OracleAnswerAuthority.ACCEPTED_DECISION.value,
            "provenance": [provenance],
        }
        for field_name in fields
    }


def _unresolved_campaign_obligation_ids(
    state: Mapping[str, object],
) -> set[str]:
    """Return every current obligation an exception must explicitly own."""

    latest_runs: dict[str, Mapping[str, object]] = {}
    latest_promotions: dict[str, Mapping[str, object]] = {}
    for item in state.get("evidence", []):
        if not isinstance(item, Mapping) or not bool(item.get("current")):
            continue
        case_id = str(item.get("case_id") or "")
        operation = str(item.get("operation") or "")
        if operation == "run":
            latest_runs.setdefault(case_id, item)
        elif operation == "promote":
            latest_promotions.setdefault(case_id, item)
    accepted_cases = {
        case_id
        for case_id, run in latest_runs.items()
        if (promotion := latest_promotions.get(case_id)) is not None
        and bool(run.get("authoritative"))
        and str(run.get("acceptance_disposition") or "") == "passed"
        and bool(promotion.get("authoritative"))
        and str(promotion.get("acceptance_disposition") or "") == "passed"
        and str(promotion.get("promotion_evidence_id") or "")
        == str(run.get("evidence_id") or "")
    }
    required_cases = {
        str(item.get("case_id") or "")
        for item in state.get("cases", [])
        if isinstance(item, Mapping) and bool(item.get("required"))
    }
    bindings_by_obligation: dict[str, set[str]] = {}
    for item in state.get("obligation_bindings", []):
        if not isinstance(item, Mapping):
            continue
        bindings_by_obligation.setdefault(
            str(item.get("obligation_id") or ""), set()
        ).add(str(item.get("case_id") or ""))
    unresolved: set[str] = set()
    omitted = {
        CampaignObligationDecision.OUT_OF_SCOPE.value,
        CampaignObligationDecision.DUPLICATE.value,
        CampaignObligationDecision.WAIVED.value,
    }
    for item in state.get("obligations", []):
        if not isinstance(item, Mapping) or not bool(item.get("fresh")):
            continue
        obligation_id = str(item.get("obligation_id") or "")
        decision = str(item.get("decision") or "")
        if decision in omitted:
            continue
        bound_required_cases = bindings_by_obligation.get(obligation_id, set()).intersection(
            required_cases
        )
        if (
            decision != CampaignObligationDecision.REQUIRED.value
            or not bound_required_cases
            or not bound_required_cases.issubset(accepted_cases)
        ):
            unresolved.add(obligation_id)
    return unresolved


def _oracle_question_prompt(field_name: str) -> str:
    prompts = {
        "preconditions": "Which facts must hold before this behavior is exercised?",
        "stimulus": "What exact action or input triggers the behavior?",
        "input_domain": "Which input classes and ranges belong to this oracle?",
        "expected_observations": "What observable outputs or state changes prove success?",
        "invariants": "Which properties must remain true throughout execution?",
        "forbidden_effects": "Which side effects or states must never occur?",
        "tolerances": "Which numeric, timing or ordering tolerances are accepted?",
        "expected_failure_transitions": "Which failures are intended product behavior?",
        "oracle_violation_conditions": "Which observations prove a product defect?",
        "execution_class": "Is this deterministic, live, integration or manual execution?",
        "verification_intent": "What exact claim will this test evidence verify?",
    }
    return prompts.get(
        field_name, f"Define the current authoritative value for {field_name}."
    )


def _oracle_question_id(field_name: str) -> str:
    """Keep question authority stable while display ordinals change."""

    return f"Q-{required_text(field_name, 'field_name').replace('_', '-')}"


def _oracle_question_choices(field_name: str) -> list[str]:
    if field_name == "execution_class":
        return ["deterministic", "live", "integration", "manual"]
    return ["grounded_fact", "accepted_decision", "unknown", "waived"]


def _oracle_ir_question_prompt(field_name: str, detail: str) -> str:
    return (
        f"Restate {field_name} as one authoritative typed value for the "
        f"unit-contract oracle: {detail}"
    )


def _oracle_ir_question_choices(value_shape: str) -> list[dict[str, str]]:
    return [
        {"authority": "grounded_fact", "value_shape": value_shape},
        {"authority": "accepted_decision", "value_shape": value_shape},
    ]


def _bounded_limit(value: int, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("limit must be a positive integer")
    return min(value, maximum)
