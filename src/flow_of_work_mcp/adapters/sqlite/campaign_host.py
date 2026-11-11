"""Append-only host check attempts and observations in the campaign ledger."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Mapping
from uuid import uuid4

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.assurance import validate_campaign_id, validate_case_id
from flow_of_work_mcp.core.domain.campaign_authority import semantic_fingerprint
from flow_of_work_mcp.core.domain.campaign_host import (
    HostCampaignCheck,
    HostCampaignResult,
    campaign_case_lane,
    host_case_supported,
    host_rejection,
    independent_host_obligations,
    next_host_case,
    required_host_cases,
)
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.oracle_questions import oracle_source_repair


_ISSUED = "campaign_host_check_issued"
_REPORTED = "campaign_host_result_reported"


class CampaignHostStoreMixin:
    def issue_campaign_host_check(
        self, project_id: str, campaign_id: str, case_id: str, check: HostCampaignCheck,
        *, actor: str, request_id: str, expected_fingerprint: str = "",
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        case_id = validate_case_id(case_id)
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        data = asdict(check)
        fingerprint = self._host_request_fingerprint({
            "case_id": case_id, "expected_fingerprint": expected_fingerprint, **data,
        })
        with self._transaction() as connection:
            replay = self._host_request_replay(
                connection, project_id, campaign_id, actor, request_id, _ISSUED, fingerprint,
            )
            if replay is not None:
                return replay
            state = self._campaign_authority_value(connection, project_id, campaign_id)
            execution = state.get("host_execution", {})
            declared_source = execution.get("declared_source_revision")
            self._qualified_campaign_head(
                connection, project_id, campaign_id,
                allow_host_completed=bool(declared_source and declared_source != check.source_revision),
            )
            if expected_fingerprint and state["fingerprint"] != expected_fingerprint:
                raise host_rejection("expected_fingerprint", expected_fingerprint, "The campaign basis has changed.")
            case = self._require_current_host_case(state, check.source_revision)
            if case_id != case["case_id"]:
                raise host_rejection("case_id", case_id, f"Current host check is {case['case_id']}.")
            active = execution["current_attempts"].get(case_id)
            if active and not execution["current_receipts"].get(case_id) and check.source_revision == active["source_revision"]:
                raise host_rejection("case_id", case_id, f"Report the existing attempt {active['attempt_id']}.")
            latest = execution["current_receipts"].get(case_id)
            if latest and latest["source_revision"] == check.source_revision and latest["outcome"] == "product_failed":
                raise host_rejection("case_id", case_id, "Record the product failure and supply its corrected source before reissuing.")
            if (latest and latest["source_revision"] == check.source_revision
                    and latest["outcome"] == "test_invalid" and latest["check_reference"] == check.check_reference):
                raise host_rejection("host_check.check_reference", check.check_reference, "Supply the corrected check reference.")
            basis = _host_case_basis(state, case)
            occurred_at = _utc_now()
            attempt = {
                "attempt_id": "HOST-" + uuid4().hex[:16],
                "case_id": case_id, "campaign_id": campaign_id, "actor": actor,
                "provenance": "host_declared", "issued_at": occurred_at,
                "campaign_revision": state["revision"], "campaign_fingerprint": state["fingerprint"],
                "scope_fingerprint": semantic_fingerprint(state["scope"]),
                "source_generation": execution["source_generation"]
                + int(execution["declared_source_revision"] != check.source_revision),
                "basis": basis,
                "check": {
                    key: case[key] for key in (
                        "title", "setup", "action", "observation_point", "expected_outcome",
                        "prohibited_outcome", "cleanup", "execution_class",
                    )
                },
                **data,
            }
            case_ids = (
                [item["case_id"] for item in required_host_cases(state)]
                if execution.get("declared_source_revision") not in {"", check.source_revision}
                else [case_id]
            )
            for target in case_ids:
                self._invalidate_case_execution_authority(
                    connection, project_id, campaign_id, target, actor=actor, request_id=request_id,
                )
            self._append_campaign_authority_event(
                connection, project_id=project_id, campaign_id=campaign_id, case_id=case_id,
                oracle_id=basis["oracle"]["oracle_id"], event_type=_ISSUED,
                semantic_revision=state["revision"], actor=actor, request_id=request_id,
                occurred_at=occurred_at, payload={"value": attempt, "input_fingerprint": fingerprint},
            )
            return self._campaign_authority_value(connection, project_id, campaign_id) | {
                "host_attempt": attempt,
            }

    def report_campaign_host_result(
        self, project_id: str, campaign_id: str, result: HostCampaignResult,
        *, actor: str, request_id: str,
    ) -> Mapping[str, object]:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        fingerprint = self._host_request_fingerprint(asdict(result))
        with self._transaction() as connection:
            replay = self._host_request_replay(
                connection, project_id, campaign_id, actor, request_id, _REPORTED, fingerprint,
            )
            if replay is not None:
                return replay
            self._qualified_campaign_head(connection, project_id, campaign_id)
            state = self._campaign_authority_value(connection, project_id, campaign_id)
            case = self._require_current_host_case(state)
            case_id = case["case_id"]
            execution = state["host_execution"]
            attempt = execution["current_attempts"].get(case_id)
            if attempt is None or attempt["attempt_id"] != result.attempt_id or execution["current_receipts"].get(case_id):
                raise host_rejection("host_result.attempt_id", result.attempt_id, "This attempt is unavailable, stale or already reported.")
            if attempt["actor"] != actor:
                raise host_rejection("actor", actor, "Report with the host actor that received this attempt.")
            if attempt["source_revision"] != result.source_revision:
                raise host_rejection(
                    "host_result.source_revision", result.source_revision,
                    f"Attempt source is {attempt['source_revision']}. Issue a check for the observed revision.",
                )
            occurred_at = _utc_now()
            receipt = {
                **asdict(result), "receipt_id": "HRES-" + uuid4().hex[:16],
                "case_id": case_id, "campaign_id": campaign_id, "actor": actor,
                "provenance": "host_reported", "observed_at": occurred_at,
                "campaign_revision": attempt["campaign_revision"],
                "scope_fingerprint": attempt["scope_fingerprint"],
                "basis": attempt["basis"], "check_reference": attempt["check_reference"],
                "execution_profile": attempt["execution_profile"],
                "evidence_kind": case["evidence_kind"],
            }
            case_result = {
                "passed": "passed", "product_failed": "failed",
                "test_invalid": "invalid_evidence", "environment_failed": "blocked",
            }[result.outcome]
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = ?, evidence_reference = ?, metadata_json = ?,
                    updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (case_result, result.evidence_reference, self._json({
                    "campaign_evidence_id": receipt["receipt_id"], "provenance": "host_reported",
                    "source_revision": result.source_revision, "execution_profile": attempt["execution_profile"],
                }), occurred_at, actor, request_id, project_id, campaign_id, case_id),
            )
            self._derive_campaign_status(connection, project_id, campaign_id, occurred_at)
            self._append_campaign_authority_event(
                connection, project_id=project_id, campaign_id=campaign_id, case_id=case_id,
                oracle_id=attempt["basis"]["oracle"]["oracle_id"], event_type=_REPORTED,
                semantic_revision=state["revision"], actor=actor, request_id=request_id,
                occurred_at=occurred_at, payload={"value": receipt, "input_fingerprint": fingerprint},
            )
            return self._campaign_authority_value(connection, project_id, campaign_id) | {
                "host_receipt": receipt,
            }

    def _host_request_replay(self, connection, project_id, campaign_id, actor, request_id, event_type, fingerprint):
        event = self._campaign_authority_request_event(connection, project_id, event_type, request_id)
        if event is None:
            return None
        payload = json.loads(event["payload_json"])
        if event["campaign_id"] != campaign_id or event["actor"] != actor or payload["input_fingerprint"] != fingerprint:
            raise host_rejection("request_id", request_id, "This request ID already identifies another host action.")
        key = "host_attempt" if event_type == _ISSUED else "host_receipt"
        return self._campaign_authority_value(connection, project_id, campaign_id) | {
            key: payload["value"], "replayed": True,
        }

    def _host_request_fingerprint(self, value):
        return sha256(self._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _require_current_host_case(state, observed_source_revision=""):
        if (
            state["constructibility"] != "ready_to_run"
            or oracle_source_repair(state)
            or not state.get("obligation_applicability", {"current": True})["current"]
        ):
            raise host_rejection("campaign_id", state["campaign_id"], "Resolve the current scope, obligation or Oracle gate first.")
        case = next_host_case(state, observed_source_revision)
        if case is None:
            raise host_rejection("campaign_id", state["campaign_id"], "There is no pending required host check.")
        case_id = case["case_id"]
        blockers = independent_host_obligations(state, case_id)
        if blockers:
            raise host_rejection("case_id", case_id, "Independent proof is required for " + ", ".join(blockers) + ".")
        if not host_case_supported(case):
            raise host_rejection("case_id", case_id, "The host lane requires a compatible deterministic or live case.")
        return case

    def _campaign_host_execution(self, connection, project_id, campaign_id, state):
        events = connection.execute(
            """
            SELECT event_type, payload_json FROM campaign_authority_events
            WHERE project_id = ? AND campaign_id = ? AND event_type IN (?, ?)
            ORDER BY event_id
            """,
            (project_id, campaign_id, _ISSUED, _REPORTED),
        ).fetchall()
        declared_source = ""
        source_generation = 0
        attempts = {}
        attempt_history = []
        receipts = {}
        for event in events:
            value = json.loads(event["payload_json"])["value"]
            if event["event_type"] == _ISSUED:
                attempts[value["case_id"]] = value
                attempt_history.append(value)
                declared_source = value["source_revision"]
                source_generation = value["source_generation"]
            else:
                receipts[value["attempt_id"]] = value
        current_attempts = {}
        current_receipts = {}
        for case in required_host_cases(state):
            case_id = case["case_id"]
            attempt = attempts.get(case_id)
            if (
                attempt is None or attempt["source_generation"] != source_generation
                or attempt["basis"] != _host_case_basis(state, case)
                or independent_host_obligations(state, case_id)
                or not host_case_supported(case)
            ):
                continue
            current_attempts[case_id] = attempt
            receipt = receipts.get(attempt["attempt_id"])
            if receipt is not None:
                current_receipts[case_id] = receipt
        current_ids = {receipt["receipt_id"] for receipt in current_receipts.values()}
        current_attempt_ids = {attempt["attempt_id"] for attempt in current_attempts.values()}
        return {
            "declared_source_revision": declared_source,
            "source_generation": source_generation,
            "current_attempts": current_attempts,
            "current_receipts": current_receipts,
            "attempts": [
                value | {"current": value["attempt_id"] in current_attempt_ids}
                for value in reversed(attempt_history)
            ],
            "evidence": [
                value | {"current": value["receipt_id"] in current_ids}
                for value in reversed(receipts.values())
            ],
        }

    def _require_provider_campaign_case(self, connection, project_id, campaign_id, case_id):
        plan = self._current_campaign_plan_payload(connection, project_id, campaign_id)
        case = next((item for item in plan["cases"] if item["case_id"] == case_id), None)
        if case is not None and campaign_case_lane(plan["scope"], case) == "host":
            raise host_rejection("case_id", case_id, "This case uses host execution. Follow its current campaign action.")

    @staticmethod
    def _guard_campaign_execution_lane_change(connection, project_id, campaign_id, case_id, old_lane, new_lane):
        if old_lane != "provider" or new_lane != "host":
            return
        if connection.execute(
            """
            SELECT 1 FROM campaign_attestation_intents
            WHERE project_id = ? AND campaign_id = ? AND case_id = ? LIMIT 1
            """,
            (project_id, campaign_id, case_id),
        ).fetchone() is not None:
            raise host_rejection("case_id", case_id, "This case has provider proof history. Retain its provider lane.")


def _host_case_basis(state, case):
    case_id = case["case_id"]
    oracle = next((value for value in state["oracle_bindings"] if value["case_id"] == case_id), {})
    bound = [item for item in state["obligation_bindings"] if item["case_id"] == case_id]
    by_id = {item["obligation_id"]: item for item in state["obligations"]}
    scope = state["scope"]
    return {
        "case_revision": case["revision"], "case_fingerprint": case["fingerprint"],
        "oracle": oracle,
        "scope": {
            key: scope.get(key) for key in ("change_id", "milestone_id", "environment_assumptions")
        },
        "bindings": [
            item | {"obligation": by_id[item["obligation_id"]]}
            for item in bound if item["obligation_id"] in by_id
        ],
    }
