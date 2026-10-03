"""Durable outbox and evidence receipts for the campaign test provider."""

from __future__ import annotations

from collections import Counter
import json
import sqlite3
from typing import Any, Mapping

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.assurance import validate_campaign_id
from flow_of_work_mcp.core.domain.campaign_authority import (
    CampaignEvidenceDisposition,
    TEST_PROVIDER_COMMAND_VERSION,
    TEST_PROVIDER_RECEIPT_VERSION,
    exact_fingerprint,
    MaterializationAttestationState,
    TestProviderCommand,
    TestProviderMaterializationMode,
    TestProviderOperation,
    TestProviderReceipt,
    deterministic_materialization_failure_receipt,
    semantic_fingerprint,
    source_manifest_digest,
    validate_test_command_id,
)
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.oracle_ir_projection import compile_oracle_ir
from flow_of_work_mcp.core.errors import AssuranceBlockedError, RequirementConflictError


class TestProviderSocketStoreMixin:
    def enqueue_test_provider_command(
        self,
        project_id: str,
        *,
        provider_kind: str,
        command: TestProviderCommand,
        actor: str,
        request_id: str = "",
        retry_of_command_id: str = "",
        retry_rationale: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        retry_of_command_id = str(retry_of_command_id or "").strip()
        retry_rationale = str(retry_rationale or "").strip()
        if retry_of_command_id:
            retry_of_command_id = validate_test_command_id(retry_of_command_id)
            retry_rationale = required_text(retry_rationale, "retry_rationale")
        elif retry_rationale:
            raise AssuranceBlockedError("test_provider_retry_predecessor_required")
        if command.flow_session_ref != project_id:
            raise AssuranceBlockedError("test_provider_session_mismatch")
        if command.contract_version != TEST_PROVIDER_COMMAND_VERSION:
            raise AssuranceBlockedError("test_provider_command_v1_write_retired")
        with self._transaction() as connection:
            context = self._campaign_provider_context_value(
                connection, project_id, command.campaign_id, command.case_id
            )
            self._validate_test_command_context(command, context)
            command_payload = command.as_payload()
            command_fingerprint = exact_fingerprint(command_payload)
            existing = connection.execute(
                """
                SELECT * FROM test_provider_outbox
                WHERE project_id = ? AND provider_kind = ? AND delivery_fingerprint = ?
                """,
                (project_id, provider_kind, command.delivery_fingerprint),
            ).fetchone()
            if existing is not None:
                if str(existing["command_fingerprint"]) != command_fingerprint:
                    raise RequirementConflictError(
                        "test provider delivery fingerprint conflicts with durable command"
                    )
                self._validate_test_provider_retry_replay(
                    existing,
                    retry_of_command_id=retry_of_command_id,
                    retry_rationale=retry_rationale,
                )
                return self._test_provider_outbox_value(existing) | {"replayed": True}
            if request_id:
                replay = connection.execute(
                    """
                    SELECT * FROM test_provider_outbox
                    WHERE project_id = ? AND request_id = ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (project_id, request_id),
                ).fetchone()
                if replay is not None:
                    if str(replay["command_fingerprint"]) != command_fingerprint:
                        raise RequirementConflictError(
                            "test provider request_id conflicts with durable command"
                        )
                    self._validate_test_provider_retry_replay(
                        replay,
                        retry_of_command_id=retry_of_command_id,
                        retry_rationale=retry_rationale,
                    )
                    return self._test_provider_outbox_value(replay) | {"replayed": True}
            if retry_of_command_id:
                predecessor = self._test_provider_outbox_row(
                    connection, project_id, retry_of_command_id
                )
                predecessor_state = str(predecessor["state"])
                if predecessor_state not in {"rejected", "delivered"}:
                    raise AssuranceBlockedError(
                        "test_provider_retry_predecessor_not_terminal"
                    )
                if str(predecessor["provider_kind"]) != provider_kind:
                    raise AssuranceBlockedError("test_provider_retry_kind_mismatch")
                predecessor_command = TestProviderCommand.from_payload(
                    json.loads(str(predecessor["command_json"]))
                )
                if predecessor_state == "delivered":
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
                        predecessor_command.operation
                        != TestProviderOperation.MATERIALIZE
                        or command.operation != TestProviderOperation.MATERIALIZE
                        or not deterministic_materialization_failure_receipt(
                            receipt_payload,
                            reconciled_attestation_state=(
                                str(receipt["attestation_state"])
                                if receipt is not None
                                else ""
                            ),
                        )
                    ):
                        raise AssuranceBlockedError(
                            "test_provider_technical_retry_predecessor_invalid"
                        )
                if _test_provider_retry_basis(predecessor_command) != (
                    _test_provider_retry_basis(command)
                ):
                    raise AssuranceBlockedError("test_provider_retry_basis_mismatch")
                later_lineage = connection.execute(
                    """
                    SELECT command_id FROM test_provider_outbox
                    WHERE project_id = ? AND campaign_id = ?
                      AND case_id = ? AND operation = ? AND ordinal > ?
                    ORDER BY ordinal LIMIT 1
                    """,
                    (
                        project_id,
                        command.campaign_id,
                        command.case_id,
                        command.operation.value,
                        int(predecessor["ordinal"]),
                    ),
                ).fetchone()
                if later_lineage is not None:
                    raise AssuranceBlockedError("test_provider_rejection_superseded")
            ordinal = self._next_campaign_authority_ordinal(
                connection, project_id, "command"
            )
            command_id = f"TCMD-{ordinal:06d}"
            persisted = TestProviderCommand(
                flow_session_ref=command.flow_session_ref,
                campaign_id=command.campaign_id,
                case_id=command.case_id,
                operation=command.operation,
                oracle_id=command.oracle_id,
                oracle_revision=command.oracle_revision,
                oracle_fingerprint=command.oracle_fingerprint,
                attestation_intent_ref=command.attestation_intent_ref,
                source_manifest_digest=command.source_manifest_digest,
                semantic_input=command.semantic_input,
                delivery_fingerprint=command.delivery_fingerprint,
                command_id=command_id,
                materialization_mode=command.materialization_mode,
                authority_input_fingerprint=command.authority_input_fingerprint,
                oracle_ir=command.oracle_ir,
                requested_capability=command.requested_capability,
            )
            payload = persisted.as_payload()
            occurred_at = _utc_now()
            connection.execute(
                """
                INSERT INTO test_provider_outbox(
                    project_id, command_id, ordinal, campaign_id, case_id,
                    provider_kind, operation, delivery_fingerprint,
                    command_fingerprint, command_json, state, attempts,
                    created_at, updated_at, actor, request_id,
                    retry_of_command_id, retry_rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    command_id,
                    ordinal,
                    command.campaign_id,
                    command.case_id,
                    provider_kind,
                    command.operation.value,
                    command.delivery_fingerprint,
                    command_fingerprint,
                    self._json(payload),
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                    retry_of_command_id,
                    retry_rationale,
                ),
            )
            row = self._test_provider_outbox_row(connection, project_id, command_id)
            return self._test_provider_outbox_value(row)

    def test_provider_outbox_entry(
        self, project_id: str, command_id: str
    ) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            row = self._test_provider_outbox_row(
                connection,
                validate_project_id(project_id),
                validate_test_command_id(command_id),
            )
            return self._test_provider_outbox_value(row)

    def test_provider_recoverable_commands(
        self,
        project_id: str,
        *,
        campaign_id: str = "",
        limit: int = 64,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        limit = _bounded_limit(limit)
        with self._read_connection() as connection:
            params: list[object] = [project_id]
            where = "project_id = ? AND state IN ('pending', 'unknown')"
            if campaign_id:
                where += " AND campaign_id = ?"
                params.append(campaign_id)
            params.append(limit)
            rows = connection.execute(
                f"""
                SELECT * FROM test_provider_outbox
                WHERE {where} ORDER BY ordinal LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [self._test_provider_outbox_value(row) for row in rows]

    def latest_test_provider_command(
        self,
        project_id: str,
        *,
        campaign_id: str,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM test_provider_outbox
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, campaign_id),
            ).fetchone()
            return self._test_provider_outbox_value(row) if row is not None else None

    def next_unresolved_test_provider_rejection(
        self,
        project_id: str,
        *,
        campaign_id: str,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        campaign_id = validate_campaign_id(campaign_id)
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT rejected.*
                FROM test_provider_outbox AS rejected
                WHERE rejected.project_id = ?
                  AND rejected.campaign_id = ?
                  AND rejected.state = 'rejected'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM test_provider_outbox AS later
                      WHERE later.project_id = rejected.project_id
                        AND later.campaign_id = rejected.campaign_id
                        AND later.case_id = rejected.case_id
                        AND later.operation = rejected.operation
                        AND later.ordinal > rejected.ordinal
                  )
                ORDER BY rejected.ordinal
                LIMIT 1
                """,
                (project_id, campaign_id),
            ).fetchone()
            return self._test_provider_outbox_value(row) if row is not None else None

    def claim_test_provider_command(
        self, project_id: str, command_id: str
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        command_id = validate_test_command_id(command_id)
        with self._transaction() as connection:
            row = self._test_provider_outbox_row(connection, project_id, command_id)
            if str(row["state"]) in {"delivered", "rejected"}:
                return self._test_provider_outbox_value(row)
            command = TestProviderCommand.from_payload(
                json.loads(str(row["command_json"]))
            )
            context = self._campaign_provider_context_value(
                connection, project_id, command.campaign_id, command.case_id
            )
            try:
                self._validate_test_command_context(command, context)
            except AssuranceBlockedError as exc:
                connection.execute(
                    """
                    UPDATE test_provider_outbox
                    SET state = 'rejected', last_error = ?, updated_at = ?
                    WHERE project_id = ? AND command_id = ?
                    """,
                    (exc.reason, _utc_now(), project_id, command_id),
                )
                return self._test_provider_outbox_value(
                    self._test_provider_outbox_row(connection, project_id, command_id)
                )
            connection.execute(
                """
                UPDATE test_provider_outbox
                SET state = 'delivering', attempts = attempts + 1,
                    updated_at = ?, last_error = ''
                WHERE project_id = ? AND command_id = ?
                """,
                (_utc_now(), project_id, command_id),
            )
            return self._test_provider_outbox_value(
                self._test_provider_outbox_row(connection, project_id, command_id)
            )

    def mark_test_provider_command_unknown(
        self, project_id: str, command_id: str, *, reason: str
    ) -> Mapping[str, Any]:
        return self._set_test_provider_command_state(
            project_id, command_id, state="unknown", reason=reason
        )

    def reject_test_provider_command(
        self, project_id: str, command_id: str, *, reason: str
    ) -> Mapping[str, Any]:
        return self._set_test_provider_command_state(
            project_id, command_id, state="rejected", reason=reason
        )

    def record_test_provider_receipt(
        self,
        project_id: str,
        *,
        provider_kind: str,
        receipt: TestProviderReceipt,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        actor = required_text(actor, "actor")
        if receipt.contract_version != TEST_PROVIDER_RECEIPT_VERSION:
            raise AssuranceBlockedError("test_provider_receipt_v1_write_retired")
        with self._transaction() as connection:
            command_row = self._test_provider_outbox_row(
                connection, project_id, receipt.command_id
            )
            if str(command_row["provider_kind"]) != provider_kind:
                raise AssuranceBlockedError("test_provider_receipt_provider_mismatch")
            command = TestProviderCommand.from_payload(
                json.loads(str(command_row["command_json"]))
            )
            self._validate_test_receipt_context(command, receipt)
            receipt_payload = receipt.as_payload()
            fingerprint = semantic_fingerprint(receipt_payload)
            replay = connection.execute(
                """
                SELECT * FROM test_provider_receipts
                WHERE project_id = ? AND command_id = ? AND provider_event_seq = ?
                ORDER BY ordinal LIMIT 1
                """,
                (project_id, receipt.command_id, receipt.provider_event_seq),
            ).fetchone()
            if replay is not None:
                if str(replay["receipt_fingerprint"]) != fingerprint:
                    raise RequirementConflictError(
                        "test provider event sequence conflicts with durable receipt"
                    )
                return self._test_provider_delivery_value(
                    connection, command_row, replay
                ) | {"replayed": True}
            latest_event = connection.execute(
                """
                SELECT MAX(provider_event_seq) AS event_seq
                FROM test_provider_receipts
                WHERE project_id = ? AND command_id = ?
                """,
                (project_id, receipt.command_id),
            ).fetchone()
            if (
                latest_event is not None
                and latest_event["event_seq"] is not None
                and receipt.provider_event_seq < int(latest_event["event_seq"])
            ):
                raise AssuranceBlockedError("test_provider_receipt_out_of_order")
            attestation = connection.execute(
                """
                SELECT * FROM campaign_attestation_intents
                WHERE project_id = ? AND attestation_id = ?
                """,
                (project_id, command.attestation_intent_ref),
            ).fetchone()
            if attestation is None:
                raise AssuranceBlockedError("test_provider_attestation_intent_missing")
            authority_current = bool(
                str(attestation["state"])
                in {
                    MaterializationAttestationState.PENDING_TECHNICAL_VALIDATION.value,
                    MaterializationAttestationState.ATTESTED_CURRENT.value,
                }
                and self._oracle_ir_attestation_dependency_current(
                    connection, attestation
                )
            )
            attestation_state, effective_disposition, basis = _reconcile_attestation(
                attestation,
                receipt,
                authority_current=authority_current,
            )
            prior_basis = json.loads(str(attestation["basis_json"]))
            technical_retry = (
                prior_basis.get("technical_retry")
                if isinstance(prior_basis, Mapping)
                else None
            )
            if isinstance(technical_retry, Mapping):
                basis = {**dict(basis), "technical_retry": dict(technical_retry)}
            if command.operation.value not in {"run", "promote"}:
                effective_disposition = CampaignEvidenceDisposition.DIAGNOSTIC_ONLY
                basis = {
                    **dict(basis),
                    "operation_authority": "diagnostic_only",
                    "provider_disposition_retained": receipt.evidence_disposition.value,
                }
            ordinal = self._next_campaign_authority_ordinal(
                connection, project_id, "receipt"
            )
            receipt_id = f"TRCPT-{ordinal:06d}"
            occurred_at = _utc_now()
            connection.execute(
                """
                INSERT INTO test_provider_receipts(
                    project_id, receipt_id, ordinal, command_id, campaign_id,
                    case_id, provider_kind, provider_event_seq,
                    receipt_fingerprint, receipt_json, evidence_disposition,
                    attestation_state, observed_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    receipt_id,
                    ordinal,
                    receipt.command_id,
                    str(command_row["campaign_id"]),
                    str(command_row["case_id"]),
                    provider_kind,
                    receipt.provider_event_seq,
                    fingerprint,
                    self._json(receipt_payload),
                    effective_disposition.value,
                    attestation_state.value,
                    occurred_at,
                    actor,
                    str(request_id or ""),
                ),
            )
            connection.execute(
                """
                UPDATE campaign_attestation_intents
                SET state = ?, provider_materialization_ref = ?,
                    representation_fingerprint = ?, basis_json = ?,
                    updated_at = ?, actor = ?
                WHERE project_id = ? AND attestation_id = ?
                """,
                (
                    attestation_state.value,
                    receipt.materialization_ref,
                    receipt.representation_fingerprint,
                    self._json(basis),
                    occurred_at,
                    actor,
                    project_id,
                    command.attestation_intent_ref,
                ),
            )
            connection.execute(
                """
                UPDATE test_provider_outbox
                SET state = 'delivered', receipt_id = ?, updated_at = ?, last_error = ''
                WHERE project_id = ? AND command_id = ?
                """,
                (receipt_id, occurred_at, project_id, receipt.command_id),
            )
            receipt_row = connection.execute(
                """
                SELECT * FROM test_provider_receipts
                WHERE project_id = ? AND receipt_id = ?
                """,
                (project_id, receipt_id),
            ).fetchone()
            self._record_campaign_execution_evidence(
                connection,
                project_id=project_id,
                command_row=command_row,
                receipt_row=receipt_row,
                command=command,
                receipt=receipt,
                attestation_state=attestation_state,
                effective_disposition=effective_disposition,
                basis=basis,
                actor=actor,
                request_id=str(request_id or ""),
                occurred_at=occurred_at,
            )
            command_row = self._test_provider_outbox_row(
                connection, project_id, receipt.command_id
            )
            return self._test_provider_delivery_value(
                connection, command_row, receipt_row
            )

    def test_provider_receipts(
        self,
        project_id: str,
        campaign_id: str,
        *,
        limit: int = 100,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        limit = _bounded_limit(limit, maximum=200)
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM test_provider_receipts
                WHERE project_id = ? AND campaign_id = ?
                ORDER BY ordinal DESC LIMIT ?
                """,
                (project_id, campaign_id, limit),
            ).fetchall()
            return [self._test_provider_receipt_value(row) for row in rows]

    def campaign_execution_evidence(
        self,
        project_id: str,
        campaign_id: str,
        *,
        case_id: str = "",
        limit: int = 100,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        limit = _bounded_limit(limit, maximum=200)
        with self._read_connection() as connection:
            return self._campaign_execution_evidence_values(
                connection,
                project_id,
                campaign_id,
                case_id=case_id,
                limit=limit,
            )

    def recover_interrupted_test_provider_commands(self) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE test_provider_outbox
                SET state = 'unknown',
                    last_error = 'process_interrupted_during_delivery',
                    updated_at = ?
                WHERE state = 'delivering'
                """,
                (_utc_now(),),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _validate_test_command_context(
        command: TestProviderCommand, context: Mapping[str, object]
    ) -> None:
        oracle = context["oracle"]
        attestation = context["attestation"]
        if not isinstance(oracle, Mapping) or not isinstance(attestation, Mapping):
            raise AssuranceBlockedError("test_provider_context_incomplete")
        expected = (
            str(oracle["oracle_id"]),
            int(oracle["revision"]),
            str(oracle["fingerprint"]),
            str(attestation["attestation_id"]),
            str(attestation["materialization_mode"]),
            str(attestation["authority_input_fingerprint"]),
        )
        received = (
            command.oracle_id,
            command.oracle_revision,
            command.oracle_fingerprint,
            command.attestation_intent_ref,
            command.materialization_mode.value,
            command.authority_input_fingerprint,
        )
        if received != expected:
            raise AssuranceBlockedError(
                "test_provider_command_stale",
                details={"expected_oracle_revision": expected[1]},
            )
        if str(attestation.get("state") or "") not in {
            MaterializationAttestationState.PENDING_TECHNICAL_VALIDATION.value,
            MaterializationAttestationState.ATTESTED_CURRENT.value,
        }:
            raise AssuranceBlockedError("test_provider_attestation_not_current")
        if (
            command.materialization_mode
            == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
            and command.operation.value in {"materialize", "edit"}
        ):
            source_files = command.semantic_input.get("source_files")
            if not isinstance(source_files, Mapping):
                raise AssuranceBlockedError("test_provider_command_source_missing")
            if source_manifest_digest(source_files) != command.source_manifest_digest:
                raise AssuranceBlockedError(
                    "test_provider_command_source_manifest_mismatch"
                )
        elif (
            command.materialization_mode
            == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR
        ):
            projection = compile_oracle_ir(oracle)
            if (
                not projection.constructible
                or projection.snapshot is None
                or projection.snapshot.fingerprint
                != command.authority_input_fingerprint
                or str(attestation.get("oracle_ir_fingerprint") or "")
                != str(command.oracle_ir.get("canonical_ir_fingerprint") or "")
                or str(attestation.get("requested_capability_fingerprint") or "")
                != semantic_fingerprint(command.requested_capability)
            ):
                raise AssuranceBlockedError("test_provider_command_oracle_ir_stale")

    @staticmethod
    def _validate_test_receipt_context(
        command: TestProviderCommand, receipt: TestProviderReceipt
    ) -> None:
        if (
            receipt.oracle_id != command.oracle_id
            or receipt.oracle_revision != command.oracle_revision
            or receipt.oracle_fingerprint != command.oracle_fingerprint
            or receipt.materialization_mode != command.materialization_mode
            or receipt.authority_input_fingerprint
            != command.authority_input_fingerprint
        ):
            raise AssuranceBlockedError("test_provider_receipt_binding_mismatch")
        if (
            command.materialization_mode
            == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR
        ):
            _validate_oracle_ir_materialization_evidence(command, receipt)

    def _set_test_provider_command_state(
        self, project_id: str, command_id: str, *, state: str, reason: str
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        command_id = validate_test_command_id(command_id)
        reason = required_text(reason, "reason")
        with self._transaction() as connection:
            row = self._test_provider_outbox_row(connection, project_id, command_id)
            if str(row["state"]) in {"delivered", "rejected"}:
                return self._test_provider_outbox_value(row)
            connection.execute(
                """
                UPDATE test_provider_outbox SET state = ?, last_error = ?, updated_at = ?
                WHERE project_id = ? AND command_id = ?
                """,
                (state, reason, _utc_now(), project_id, command_id),
            )
            return self._test_provider_outbox_value(
                self._test_provider_outbox_row(connection, project_id, command_id)
            )

    @staticmethod
    def _test_provider_outbox_row(
        connection: sqlite3.Connection, project_id: str, command_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM test_provider_outbox
            WHERE project_id = ? AND command_id = ?
            """,
            (project_id, command_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown test provider command: {command_id}"
            )
        return row

    @staticmethod
    def _test_provider_outbox_value(row: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "command_id": str(row["command_id"]),
            "campaign_id": str(row["campaign_id"]),
            "case_id": str(row["case_id"]),
            "provider_kind": str(row["provider_kind"]),
            "operation": str(row["operation"]),
            "delivery_fingerprint": str(row["delivery_fingerprint"]),
            "state": str(row["state"]),
            "attempts": int(row["attempts"]),
            "last_error": str(row["last_error"]),
            "receipt_id": str(row["receipt_id"]),
            "retry_of_command_id": str(row["retry_of_command_id"]),
            "retry_rationale": str(row["retry_rationale"]),
            "command": json.loads(str(row["command_json"])),
        }

    @staticmethod
    def _validate_test_provider_retry_replay(
        row: sqlite3.Row,
        *,
        retry_of_command_id: str,
        retry_rationale: str,
    ) -> None:
        if (
            str(row["retry_of_command_id"]),
            str(row["retry_rationale"]),
        ) != (retry_of_command_id, retry_rationale):
            raise RequirementConflictError(
                "test provider retry metadata conflicts with durable command"
            )

    @staticmethod
    def _test_provider_receipt_value(row: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "receipt_id": str(row["receipt_id"]),
            "command_id": str(row["command_id"]),
            "campaign_id": str(row["campaign_id"]),
            "case_id": str(row["case_id"]),
            "provider_kind": str(row["provider_kind"]),
            "provider_event_seq": int(row["provider_event_seq"]),
            "fingerprint": str(row["receipt_fingerprint"]),
            "provider_receipt": json.loads(str(row["receipt_json"])),
            "evidence_disposition": str(row["evidence_disposition"]),
            "attestation_state": str(row["attestation_state"]),
            "observed_at": str(row["observed_at"]),
        }

    def _test_provider_delivery_value(
        self,
        connection: sqlite3.Connection,
        command_row: sqlite3.Row,
        receipt_row: sqlite3.Row,
    ) -> Mapping[str, Any]:
        attestation_ref = str(
            json.loads(str(command_row["command_json"]))["attestation_intent_ref"]
        )
        attestation = connection.execute(
            """
            SELECT * FROM campaign_attestation_intents
            WHERE project_id = ? AND attestation_id = ?
            """,
            (str(command_row["project_id"]), attestation_ref),
        ).fetchone()
        return {
            "outbox": self._test_provider_outbox_value(command_row),
            "receipt": self._test_provider_receipt_value(receipt_row),
            "attestation": self._attestation_value(connection, attestation),
        }

    def _record_campaign_execution_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        command_row: sqlite3.Row,
        receipt_row: sqlite3.Row,
        command: TestProviderCommand,
        receipt: TestProviderReceipt,
        attestation_state: MaterializationAttestationState,
        effective_disposition: CampaignEvidenceDisposition,
        basis: Mapping[str, object],
        actor: str,
        request_id: str,
        occurred_at: str,
    ) -> None:
        campaign_id = str(command_row["campaign_id"])
        case_id = str(command_row["case_id"])
        head = self._qualified_campaign_head(connection, project_id, campaign_id)
        case_revision = self._active_case_revision(
            connection, project_id, campaign_id, case_id
        )
        bindings = self._case_obligation_binding_snapshot(
            connection, project_id, campaign_id, case_id
        )
        binding_fingerprint = semantic_fingerprint(bindings)
        receipt_id = str(receipt_row["receipt_id"])
        evidence_id = f"CEVID-{int(receipt_row['ordinal']):06d}"
        evidence_kind_row = connection.execute(
            """
            SELECT evidence_kind FROM campaign_cases
            WHERE project_id = ? AND campaign_id = ? AND case_id = ?
            """,
            (project_id, campaign_id, case_id),
        ).fetchone()
        if evidence_kind_row is None:
            raise AssuranceBlockedError("campaign_evidence_case_missing")
        authoritative = (
            command.operation.value in {"run", "promote"}
            and attestation_state == MaterializationAttestationState.ATTESTED_CURRENT
            and receipt.current
            and receipt.complete
            and receipt.integrity_preserved
            and effective_disposition
            in {
                CampaignEvidenceDisposition.PASSED,
                CampaignEvidenceDisposition.PRODUCT_FAILED,
            }
        )
        connection.execute(
            """
            INSERT INTO campaign_execution_evidence(
                project_id, evidence_id, receipt_id, command_id, campaign_id,
                campaign_revision, case_id, case_revision, oracle_id,
                oracle_revision, oracle_fingerprint, attestation_id,
                attestation_state, provider_kind, provider_test_ref,
                materialization_ref, materialization_revision,
                obligation_bindings_json, obligation_binding_fingerprint,
                execution_attempt, operation, technical_state,
                provider_disposition, effective_disposition, evidence_kind,
                evidence_reference, observed_current,
                authoritative_at_recording, complete, integrity_preserved,
                basis_json, observed_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                evidence_id,
                receipt_id,
                receipt.command_id,
                campaign_id,
                int(head["current_revision"]),
                case_id,
                int(case_revision["revision"]),
                receipt.oracle_id,
                receipt.oracle_revision,
                receipt.oracle_fingerprint,
                command.attestation_intent_ref,
                attestation_state.value,
                str(command_row["provider_kind"]),
                receipt.provider_test_ref,
                receipt.materialization_ref,
                receipt.materialization_revision,
                self._json(bindings),
                binding_fingerprint,
                int(command_row["attempts"]),
                command.operation.value,
                receipt.technical_state,
                receipt.evidence_disposition.value,
                effective_disposition.value,
                str(evidence_kind_row["evidence_kind"]),
                receipt.evidence_reference,
                int(receipt.current),
                int(authoritative),
                int(receipt.complete),
                int(receipt.integrity_preserved),
                self._json(dict(basis)),
                occurred_at,
                actor,
                request_id,
            ),
        )
        result = _case_result_for_evidence(effective_disposition)
        if result is not None:
            connection.execute(
                """
                UPDATE campaign_cases
                SET result = ?, evidence_reference = ?, metadata_json = ?,
                    updated_at = ?, actor = ?, request_id = ?
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                """,
                (
                    result,
                    receipt.evidence_reference,
                    self._json(
                        {
                            "campaign_evidence_id": evidence_id,
                            "effective_disposition": effective_disposition.value,
                            "attestation_state": attestation_state.value,
                            "authoritative": authoritative,
                            "oracle_fingerprint": receipt.oracle_fingerprint,
                        }
                    ),
                    occurred_at,
                    actor,
                    request_id,
                    project_id,
                    campaign_id,
                    case_id,
                ),
            )
            self._derive_campaign_status(
                connection, project_id, campaign_id, occurred_at
            )
        self._append_campaign_authority_event(
            connection,
            project_id=project_id,
            campaign_id=campaign_id,
            case_id=case_id,
            oracle_id=receipt.oracle_id,
            attestation_id=command.attestation_intent_ref,
            event_type="campaign_evidence_recorded",
            semantic_revision=int(head["current_revision"]),
            payload={
                "evidence_id": evidence_id,
                "receipt_id": receipt_id,
                "operation": command.operation.value,
                "provider_disposition": receipt.evidence_disposition.value,
                "effective_disposition": effective_disposition.value,
                "authoritative": authoritative,
            },
            actor=actor,
            request_id=request_id,
            occurred_at=occurred_at,
        )

    def _campaign_execution_evidence_values(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        *,
        case_id: str = "",
        limit: int | None = 100,
    ) -> list[Mapping[str, Any]]:
        params: list[object] = [project_id, campaign_id]
        case_clause = ""
        if case_id:
            case_clause = " AND e.case_id = ?"
            params.append(case_id)
        limit_clause = ""
        if limit is not None:
            params.append(limit)
            limit_clause = " LIMIT ?"
        rows = connection.execute(
            f"""
            SELECT e.*, o.command_json AS command_json
            FROM campaign_execution_evidence e
            JOIN test_provider_outbox o
              ON o.project_id = e.project_id AND o.command_id = e.command_id
            WHERE e.project_id = ? AND e.campaign_id = ? {case_clause}
            ORDER BY e.observed_at DESC, e.evidence_id DESC{limit_clause}
            """,
            tuple(params),
        ).fetchall()
        values: list[Mapping[str, Any]] = []
        for row in rows:
            current_case = connection.execute(
                """
                SELECT revision FROM campaign_case_revisions
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                  AND active = 1 ORDER BY revision DESC LIMIT 1
                """,
                (project_id, campaign_id, str(row["case_id"])),
            ).fetchone()
            current_oracle = connection.execute(
                """
                SELECT oracle_id, oracle_revision, oracle_fingerprint
                FROM campaign_case_oracle_bindings
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                  AND active = 1 ORDER BY oracle_revision DESC LIMIT 1
                """,
                (project_id, campaign_id, str(row["case_id"])),
            ).fetchone()
            latest_attestation = connection.execute(
                """
                SELECT * FROM campaign_attestation_intents
                WHERE project_id = ? AND campaign_id = ? AND case_id = ?
                ORDER BY ordinal DESC LIMIT 1
                """,
                (project_id, campaign_id, str(row["case_id"])),
            ).fetchone()
            bindings = self._case_obligation_binding_snapshot(
                connection, project_id, campaign_id, str(row["case_id"])
            )
            semantic_current = bool(
                current_case is not None
                and int(current_case["revision"]) == int(row["case_revision"])
                and current_oracle is not None
                and str(current_oracle["oracle_id"]) == str(row["oracle_id"])
                and int(current_oracle["oracle_revision"])
                == int(row["oracle_revision"])
                and str(current_oracle["oracle_fingerprint"])
                == str(row["oracle_fingerprint"])
                and latest_attestation is not None
                and str(latest_attestation["attestation_id"])
                == str(row["attestation_id"])
                and str(latest_attestation["state"])
                == MaterializationAttestationState.ATTESTED_CURRENT.value
                and self._oracle_ir_attestation_dependency_current(
                    connection, latest_attestation
                )
                and semantic_fingerprint(bindings)
                == str(row["obligation_binding_fingerprint"])
            )
            authoritative = bool(row["authoritative_at_recording"]) and semantic_current
            effective = str(row["effective_disposition"])
            command_payload = json.loads(str(row["command_json"]))
            semantic_input = command_payload.get("semantic_input")
            promotion_evidence_id = (
                str(semantic_input.get("promotion_evidence_id") or "")
                if isinstance(semantic_input, Mapping)
                else ""
            )
            values.append(
                {
                    "evidence_id": str(row["evidence_id"]),
                    "receipt_id": str(row["receipt_id"]),
                    "command_id": str(row["command_id"]),
                    "campaign_revision": int(row["campaign_revision"]),
                    "case_id": str(row["case_id"]),
                    "case_revision": int(row["case_revision"]),
                    "oracle_id": str(row["oracle_id"]),
                    "oracle_revision": int(row["oracle_revision"]),
                    "oracle_fingerprint": str(row["oracle_fingerprint"]),
                    "attestation_id": str(row["attestation_id"]),
                    "attestation_state": str(row["attestation_state"]),
                    "provider_kind": str(row["provider_kind"]),
                    "provider_test_ref": str(row["provider_test_ref"]),
                    "materialization_ref": str(row["materialization_ref"]),
                    "materialization_revision": int(row["materialization_revision"]),
                    "obligation_bindings": json.loads(
                        str(row["obligation_bindings_json"])
                    ),
                    "execution_attempt": int(row["execution_attempt"]),
                    "operation": str(row["operation"]),
                    "promotion_evidence_id": promotion_evidence_id,
                    "technical_state": str(row["technical_state"]),
                    "provider_disposition": str(row["provider_disposition"]),
                    "effective_disposition": effective,
                    "acceptance_disposition": (
                        effective
                        if semantic_current
                        else CampaignEvidenceDisposition.DIAGNOSTIC_ONLY.value
                    ),
                    "evidence_kind": str(row["evidence_kind"]),
                    "evidence_reference": str(row["evidence_reference"]),
                    "current": semantic_current,
                    "authoritative": authoritative,
                    "complete": bool(row["complete"]),
                    "integrity_preserved": bool(row["integrity_preserved"]),
                    "basis": json.loads(str(row["basis_json"])),
                    "observed_at": str(row["observed_at"]),
                }
            )
        return values

    @staticmethod
    def _case_obligation_binding_snapshot(
        connection: sqlite3.Connection,
        project_id: str,
        campaign_id: str,
        case_id: str,
    ) -> list[dict[str, object]]:
        return [
            {
                "obligation_id": str(row["obligation_id"]),
                "coverage_intent": str(row["coverage_intent"]),
                "kind": str(row["kind"]),
                "source_kind": str(row["source_kind"]),
                "source_ref": str(row["source_ref"]),
                "source_revision": str(row["source_revision"]),
            }
            for row in connection.execute(
                """
                SELECT b.obligation_id, b.coverage_intent, o.kind,
                       o.source_kind, o.source_ref, o.source_revision
                FROM campaign_case_obligation_bindings b
                JOIN campaign_obligations o
                  ON o.project_id = b.project_id
                 AND o.campaign_id = b.campaign_id
                 AND o.obligation_id = b.obligation_id
                WHERE b.project_id = ? AND b.campaign_id = ? AND b.case_id = ?
                  AND o.active = 1
                ORDER BY b.obligation_id
                """,
                (project_id, campaign_id, case_id),
            ).fetchall()
        ]


def _test_provider_retry_basis(command: TestProviderCommand) -> str:
    payload = command.as_payload()
    payload.pop("command_ref", None)
    payload.pop("delivery_fingerprint", None)
    return exact_fingerprint(payload)


def _validate_oracle_ir_materialization_evidence(
    command: TestProviderCommand,
    receipt: TestProviderReceipt,
) -> None:
    evidence = dict(receipt.materialization_evidence)
    required_fields = {
        "oracle_ir_contract_version",
        "operator_profile",
        "materializer_version",
        "adapter_version",
        "semantic_ast_fingerprint",
        "rendered_source_fingerprint",
        "ir_node_lineage",
    }
    if set(evidence) != required_fields:
        raise AssuranceBlockedError(
            "test_provider_oracle_ir_evidence_contract_mismatch"
        )
    if (
        _oracle_ir_evidence_text(
            evidence["oracle_ir_contract_version"],
            "oracle_ir_contract_version",
        )
        != str(command.oracle_ir.get("contract_version") or "")
        or _oracle_ir_evidence_text(evidence["operator_profile"], "operator_profile")
        != str(command.oracle_ir.get("operator_profile") or "")
        or _oracle_ir_evidence_text(
            evidence["rendered_source_fingerprint"],
            "rendered_source_fingerprint",
        )
        != receipt.representation_fingerprint
    ):
        raise AssuranceBlockedError("test_provider_oracle_ir_evidence_binding_mismatch")
    for field_name in (
        "materializer_version",
        "adapter_version",
        "semantic_ast_fingerprint",
        "rendered_source_fingerprint",
    ):
        _oracle_ir_evidence_text(evidence[field_name], field_name)
    for field_name in (
        "oracle_ir_contract_version",
        "operator_profile",
        "materializer_version",
        "adapter_version",
    ):
        if _oracle_ir_evidence_text(evidence[field_name], field_name) != str(
            command.requested_capability.get(field_name) or ""
        ):
            raise AssuranceBlockedError(
                "test_provider_oracle_ir_materializer_version_mismatch"
            )
    raw_lineage = evidence["ir_node_lineage"]
    if not isinstance(raw_lineage, list):
        raise AssuranceBlockedError("test_provider_oracle_ir_lineage_invalid")
    expected_nodes = _oracle_ir_node_occurrences(command.oracle_ir)
    observed_nodes: list[str] = []
    observed_identities: set[tuple[str, str]] = set()
    for item in raw_lineage:
        if not isinstance(item, Mapping) or set(item) != {
            "ir_node_id",
            "semantic_ast_node_id",
            "source_region_fingerprint",
        }:
            raise AssuranceBlockedError("test_provider_oracle_ir_lineage_invalid")
        ir_node_id = _oracle_ir_lineage_text(item["ir_node_id"], "ir_node_id")
        semantic_ast_node_id = _oracle_ir_lineage_text(
            item["semantic_ast_node_id"], "semantic_ast_node_id"
        )
        _oracle_ir_lineage_text(
            item["source_region_fingerprint"],
            "source_region_fingerprint",
        )
        identity = (ir_node_id, semantic_ast_node_id)
        if identity in observed_identities:
            raise AssuranceBlockedError("test_provider_oracle_ir_lineage_invalid")
        observed_identities.add(identity)
        observed_nodes.append(ir_node_id)
    if Counter(observed_nodes) != Counter(expected_nodes):
        raise AssuranceBlockedError(
            "test_provider_oracle_ir_lineage_incomplete",
            details={
                "expected_node_count": len(expected_nodes),
                "observed_node_count": len(observed_nodes),
            },
        )


def _oracle_ir_evidence_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AssuranceBlockedError("test_provider_oracle_ir_evidence_incomplete")
    try:
        return required_text(value, field_name)
    except ValueError as exc:
        raise AssuranceBlockedError(
            "test_provider_oracle_ir_evidence_incomplete"
        ) from exc


def _oracle_ir_lineage_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AssuranceBlockedError("test_provider_oracle_ir_lineage_invalid")
    try:
        return required_text(value, field_name)
    except ValueError as exc:
        raise AssuranceBlockedError("test_provider_oracle_ir_lineage_invalid") from exc


def _oracle_ir_node_occurrences(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    cases = value.get("cases")
    if not isinstance(cases, list):
        return []
    result: list[str] = []
    observation_fields = (
        "preconditions",
        "observations",
        "invariants",
        "forbidden_effects",
        "expected_failure_transitions",
        "oracle_violation_conditions",
    )
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        case_node_id = case.get("node_id")
        if isinstance(case_node_id, str) and case_node_id:
            result.append(case_node_id)
        stimulus = case.get("stimulus")
        if isinstance(stimulus, Mapping):
            stimulus_node_id = stimulus.get("node_id")
            if isinstance(stimulus_node_id, str) and stimulus_node_id:
                result.append(stimulus_node_id)
        for field in observation_fields:
            observations = case.get(field)
            if not isinstance(observations, list):
                continue
            result.extend(
                str(item["node_id"])
                for item in observations
                if isinstance(item, Mapping)
                and isinstance(item.get("node_id"), str)
                and item["node_id"]
            )
    return result


def _reconcile_attestation(
    attestation: sqlite3.Row,
    receipt: TestProviderReceipt,
    *,
    authority_current: bool = True,
) -> tuple[
    MaterializationAttestationState,
    CampaignEvidenceDisposition,
    Mapping[str, object],
]:
    exact = (
        str(attestation["oracle_id"]) == receipt.oracle_id
        and int(attestation["oracle_revision"]) == receipt.oracle_revision
        and str(attestation["oracle_fingerprint"]) == receipt.oracle_fingerprint
        and str(attestation["materialization_mode"])
        == receipt.materialization_mode.value
        and str(attestation["authority_input_fingerprint"])
        == receipt.authority_input_fingerprint
    )
    equivalent, equivalence_basis = _representation_equivalence(receipt)
    attestation_integrity = (
        authority_current
        and exact
        and equivalent
        and receipt.integrity_preserved
        and receipt.attestation_state
        == MaterializationAttestationState.ATTESTED_CURRENT
    )
    if attestation_integrity:
        state = MaterializationAttestationState.ATTESTED_CURRENT
    elif receipt.attestation_state == MaterializationAttestationState.REJECTED:
        state = MaterializationAttestationState.REJECTED
    elif not authority_current:
        state = MaterializationAttestationState.INVALIDATED
    elif (
        not exact
        or not receipt.integrity_preserved
        or receipt.attestation_state == MaterializationAttestationState.INVALIDATED
    ):
        state = MaterializationAttestationState.INVALIDATED
    else:
        state = MaterializationAttestationState.PENDING_TECHNICAL_VALIDATION
    authoritative_product_observation = (
        state == MaterializationAttestationState.ATTESTED_CURRENT
        and authority_current
        and receipt.current
        and receipt.complete
        and receipt.integrity_preserved
    )
    if (
        receipt.evidence_disposition
        in {
            CampaignEvidenceDisposition.PASSED,
            CampaignEvidenceDisposition.PRODUCT_FAILED,
        }
        and not authoritative_product_observation
    ):
        disposition = CampaignEvidenceDisposition.DIAGNOSTIC_ONLY
    elif not exact or not authority_current:
        disposition = CampaignEvidenceDisposition.DIAGNOSTIC_ONLY
    else:
        disposition = receipt.evidence_disposition
    return (
        state,
        disposition,
        {
            "exact_authority_binding": exact,
            "authority_current": authority_current,
            "materialization_mode": receipt.materialization_mode.value,
            "authority_input_fingerprint": receipt.authority_input_fingerprint,
            "produced_source_manifest_digest": receipt.source_manifest_digest,
            "representation_equivalent": equivalent,
            "representation_equivalence_basis": equivalence_basis,
            "provider_current": receipt.current,
            "provider_complete": receipt.complete,
            "integrity_preserved": receipt.integrity_preserved,
            "provider_technical_state": receipt.technical_state,
            "provider_disposition": receipt.evidence_disposition.value,
            "effective_disposition": disposition.value,
            "authoritative_product_observation": authoritative_product_observation,
        },
    )


def _representation_equivalence(
    receipt: TestProviderReceipt,
) -> tuple[bool, str]:
    """Validate an exact representation or one closed successor proof."""

    if (
        receipt.materialization_mode
        == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
        and receipt.representation_fingerprint
        != receipt.authority_input_fingerprint
    ):
        return False, "canonical_representation_mismatch"
    if receipt.representation_fingerprint == receipt.source_manifest_digest:
        return True, "exact_produced_representation"
    if not receipt.representation_lineage:
        return False, "lineage_missing"
    previous_target = ""
    for proof in receipt.representation_lineage:
        authority_fingerprint = str(
            proof.get("authority_input_fingerprint") or ""
        ).strip()
        source_ref = str(proof.get("from_materialization_ref") or "").strip()
        target_ref = str(proof.get("to_materialization_ref") or "").strip()
        integrity_proof = str(
            proof.get("integrity_proof_fingerprint") or ""
        ).strip()
        if not (
            str(proof.get("source_manifest_digest") or "")
            == receipt.representation_fingerprint
            and proof.get("complete") is True
            and proof.get("integrity_preserved") is True
            and source_ref
            and target_ref
            and source_ref != target_ref
            and integrity_proof
            and (not previous_target or source_ref == previous_target)
            and (
                not authority_fingerprint
                or authority_fingerprint == receipt.authority_input_fingerprint
            )
        ):
            return False, "lineage_invalid"
        previous_target = target_ref
    if previous_target != receipt.materialization_ref:
        return False, "lineage_invalid"
    return True, "representation_lineage"


def _case_result_for_evidence(
    disposition: CampaignEvidenceDisposition,
) -> str | None:
    return {
        CampaignEvidenceDisposition.PASSED: "passed",
        CampaignEvidenceDisposition.PRODUCT_FAILED: "failed",
        CampaignEvidenceDisposition.TEST_INVALID: "invalid_evidence",
        CampaignEvidenceDisposition.ENVIRONMENT_FAILED: "blocked",
        CampaignEvidenceDisposition.FLAKY: "blocked",
        CampaignEvidenceDisposition.INCOMPLETE: "blocked",
    }.get(disposition)


def _bounded_limit(value: int, *, maximum: int = 100) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("limit must be a positive integer")
    return min(value, maximum)
