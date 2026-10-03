"""Durable outbox and receipt projection for the packet-provider socket."""

from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from typing import Any, Mapping, Sequence

from flow_of_work_mcp.adapters.sqlite.common import _utc_now
from flow_of_work_mcp.core.domain.change_control import (
    validate_change_id,
    validate_packet_id,
)
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id
from flow_of_work_mcp.core.domain.packet_provider import (
    PacketProviderCommand,
    PacketProviderOperation,
    PacketProviderOutboxState,
    PacketProviderReceipt,
    PacketProviderUnitReceipt,
    provider_observation_active,
    provider_observation_terminal,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError,
    RequirementConflictError,
)


_RECOVERABLE_STATES = frozenset(
    {
        PacketProviderOutboxState.PENDING.value,
        PacketProviderOutboxState.DELIVERING.value,
        PacketProviderOutboxState.UNKNOWN.value,
    }
)
_TERMINAL_STATES = frozenset(
    {
        PacketProviderOutboxState.DELIVERED.value,
        PacketProviderOutboxState.REJECTED.value,
    }
)
_REPLACEABLE_PROVIDER_STATES = frozenset({"blocked", "failed", "stopped"})
_REPLACEABLE_RUN_PHASES = frozenset(
    {
        "blocked",
        "execution_blocked",
        "execution_failed",
        "failed",
        "planning_reconciliation_blocked",
        "recovery_blocked",
        "stopped",
    }
)
_FRESH_PROVIDER_STATES = frozenset({"draft"})
_FRESH_RUN_PHASES = frozenset({"authoring", "idle"})
_MAX_CORRELATION_RECOVERY_DELIVERIES = 4096


class PacketProviderSocketStoreMixin:
    def enqueue_packet_provider_command(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
        command: PacketProviderCommand,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        actor = required_text(actor, "actor")
        request_id = str(request_id or "")
        if command.flow_session_ref != project_id:
            raise RequirementConflictError(
                "packet provider project correlation mismatch"
            )
        if command.flow_packet_ref != packet_id:
            raise RequirementConflictError(
                "packet provider packet correlation mismatch"
            )
        if command.operation == PacketProviderOperation.STATUS:
            raise ValueError("status observations do not enter the mutation outbox")
        payload = command.as_payload()
        encoded = _canonical_json(payload)
        fingerprint = _sha256(encoded)
        occurred_at = _utc_now()
        with self._transaction() as connection:
            packet = self._packet_row(connection, project_id, change_id, packet_id)
            if int(packet["spec_revision"]) != command.flow_spec_revision:
                raise RequirementConflictError(
                    "packet provider command semantic revision mismatch"
                )
            binding = connection.execute(
                """
                SELECT flow_binding_generation FROM packet_provider_bindings
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND provider_kind = ?
                """,
                (project_id, change_id, packet_id, provider_kind),
            ).fetchone()
            flow_binding_generation = (
                int(binding["flow_binding_generation"]) if binding is not None else 0
            )
            existing = connection.execute(
                """
                SELECT outbox_id, command_fingerprint
                FROM packet_provider_outbox
                WHERE project_id = ? AND provider_kind = ?
                  AND delivery_fingerprint = ?
                """,
                (project_id, provider_kind, command.delivery_fingerprint),
            ).fetchone()
            if existing is not None:
                if str(existing["command_fingerprint"]) != fingerprint:
                    raise RequirementConflictError(
                        "packet provider delivery fingerprint changed semantic payload"
                    )
                return self._packet_provider_outbox_value(
                    connection, project_id, str(existing["outbox_id"])
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO packet_provider_sequences(
                    project_id, next_outbox_ordinal, next_receipt_ordinal
                ) VALUES (?, 1, 1)
                """,
                (project_id,),
            )
            ordinal = int(
                connection.execute(
                    """
                    SELECT next_outbox_ordinal FROM packet_provider_sequences
                    WHERE project_id = ?
                    """,
                    (project_id,),
                ).fetchone()["next_outbox_ordinal"]
            )
            outbox_id = f"POUT-{ordinal:06d}"
            connection.execute(
                """
                INSERT INTO packet_provider_outbox(
                    project_id, outbox_id, ordinal, change_id, packet_id,
                    provider_kind, flow_binding_generation, flow_spec_revision,
                    operation, flow_unit_ref,
                    delivery_fingerprint, command_json, command_fingerprint, state,
                    created_at, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    outbox_id,
                    ordinal,
                    change_id,
                    packet_id,
                    provider_kind,
                    flow_binding_generation,
                    command.flow_spec_revision,
                    command.operation.value,
                    command.flow_unit_ref,
                    command.delivery_fingerprint,
                    encoded,
                    fingerprint,
                    PacketProviderOutboxState.PENDING.value,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            connection.execute(
                """
                UPDATE packet_provider_sequences
                SET next_outbox_ordinal = ? WHERE project_id = ?
                """,
                (ordinal + 1, project_id),
            )
            return self._packet_provider_outbox_value(connection, project_id, outbox_id)

    def packet_provider_outbox_entry(
        self, project_id: str, outbox_id: str
    ) -> Mapping[str, Any]:
        with self._read_connection() as connection:
            return self._packet_provider_outbox_value(
                connection,
                validate_project_id(project_id),
                required_text(outbox_id, "outbox_id"),
            )

    def packet_provider_recoverable_commands(
        self,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        flow_binding_generation: int | None = None,
        limit: int = 64,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 256
        ):
            raise ValueError("packet provider recovery limit must be between 1 and 256")
        clauses = ["project_id = ?", "state IN ('pending', 'delivering', 'unknown')"]
        values: list[object] = [project_id]
        if change_id:
            clauses.append("change_id = ?")
            values.append(validate_change_id(change_id))
        if packet_id:
            clauses.append("packet_id = ?")
            values.append(validate_packet_id(packet_id))
        if flow_binding_generation is not None:
            if (
                isinstance(flow_binding_generation, bool)
                or not isinstance(flow_binding_generation, int)
                or flow_binding_generation < 0
            ):
                raise ValueError("flow_binding_generation must be non-negative")
            clauses.append("flow_binding_generation = ?")
            values.append(flow_binding_generation)
        values.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT outbox_id FROM packet_provider_outbox
                WHERE {" AND ".join(clauses)}
                ORDER BY ordinal LIMIT ?
                """,
                tuple(values),
            ).fetchall()
            return [
                self._packet_provider_outbox_value(
                    connection, project_id, str(row["outbox_id"])
                )
                for row in rows
            ]

    def packet_provider_outbox_entries(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_unit_ref: str = "",
        flow_binding_generation: int | None = None,
        limit: int = 256,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 256
        ):
            raise ValueError("packet provider outbox limit must be between 1 and 256")
        clauses = ["project_id = ?", "change_id = ?", "packet_id = ?"]
        values: list[object] = [project_id, change_id, packet_id]
        if flow_unit_ref:
            clauses.append("flow_unit_ref = ?")
            values.append(required_text(flow_unit_ref, "flow_unit_ref"))
        if flow_binding_generation is not None:
            if (
                isinstance(flow_binding_generation, bool)
                or not isinstance(flow_binding_generation, int)
                or flow_binding_generation < 0
            ):
                raise ValueError("flow_binding_generation must be non-negative")
            clauses.append("flow_binding_generation = ?")
            values.append(flow_binding_generation)
        values.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT outbox_id FROM packet_provider_outbox
                WHERE {" AND ".join(clauses)}
                ORDER BY ordinal DESC LIMIT ?
                """,
                tuple(values),
            ).fetchall()
            return [
                self._packet_provider_outbox_value(
                    connection, project_id, str(row["outbox_id"])
                )
                for row in reversed(rows)
            ]

    def packet_provider_delivered_unit_entries(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
        provider_packet_ref: str,
        flow_unit_ref: str,
        limit: int = 256,
    ) -> list[Mapping[str, Any]]:
        """Return delivered unit commands proven to belong to one provider packet."""

        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        provider_packet_ref = required_text(
            provider_packet_ref, "provider_packet_ref"
        )
        flow_unit_ref = required_text(flow_unit_ref, "flow_unit_ref")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 256
        ):
            raise ValueError("packet provider delivered-entry limit is invalid")
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT outbox.outbox_id
                FROM packet_provider_outbox AS outbox
                JOIN packet_provider_receipts AS receipt
                  ON receipt.project_id = outbox.project_id
                 AND receipt.receipt_id = outbox.receipt_id
                WHERE outbox.project_id = ? AND outbox.change_id = ?
                  AND outbox.packet_id = ? AND outbox.provider_kind = ?
                  AND outbox.flow_unit_ref = ? AND outbox.state = 'delivered'
                  AND receipt.provider_kind = ?
                  AND receipt.provider_packet_ref = ?
                ORDER BY outbox.ordinal DESC LIMIT ?
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    provider_kind,
                    flow_unit_ref,
                    provider_kind,
                    provider_packet_ref,
                    limit,
                ),
            ).fetchall()
            return [
                self._packet_provider_outbox_value(
                    connection, project_id, str(row["outbox_id"])
                )
                for row in reversed(rows)
            ]

    def recover_packet_provider_correlations(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
    ) -> Mapping[str, int]:
        """Rebuild the active correlation projection from immutable deliveries."""

        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        with self._transaction() as connection:
            binding = connection.execute(
                """
                SELECT * FROM packet_provider_bindings
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND provider_kind = ?
                """,
                (project_id, change_id, packet_id, provider_kind),
            ).fetchone()
            if binding is None:
                return {"restored": 0, "refreshed": 0}
            rows = connection.execute(
                """
                SELECT outbox.flow_unit_ref, outbox.ordinal,
                       receipt.receipt_json
                FROM packet_provider_outbox AS outbox
                JOIN packet_provider_receipts AS receipt
                  ON receipt.project_id = outbox.project_id
                 AND receipt.receipt_id = outbox.receipt_id
                WHERE outbox.project_id = ? AND outbox.change_id = ?
                  AND outbox.packet_id = ? AND outbox.provider_kind = ?
                  AND outbox.flow_unit_ref <> ''
                  AND outbox.state = 'delivered'
                  AND receipt.provider_kind = ?
                  AND receipt.provider_packet_ref = ?
                ORDER BY outbox.ordinal
                LIMIT ?
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    provider_kind,
                    provider_kind,
                    str(binding["provider_packet_ref"]),
                    _MAX_CORRELATION_RECOVERY_DELIVERIES + 1,
                ),
            ).fetchall()
            if len(rows) > _MAX_CORRELATION_RECOVERY_DELIVERIES:
                raise ImplementationProviderContractError(
                    "packet_provider_correlation_recovery_history_exceeds_bound"
                )

            latest: dict[str, PacketProviderUnitReceipt] = {}
            provider_owners: dict[str, str] = {}
            for row in rows:
                flow_unit_ref = str(row["flow_unit_ref"])
                unit = _persisted_unit_receipt(
                    str(row["receipt_json"]), flow_unit_ref=flow_unit_ref
                )
                previous = latest.get(flow_unit_ref)
                if previous is not None and (
                    previous.provider_unit_ref != unit.provider_unit_ref
                    or (
                        previous.unit_number is not None
                        and unit.unit_number is not None
                        and previous.unit_number != unit.unit_number
                    )
                ):
                    raise ImplementationProviderContractError(
                        "packet_provider_correlation_recovery_unit_conflict"
                    )
                owner = provider_owners.get(unit.provider_unit_ref)
                if owner is not None and owner != flow_unit_ref:
                    raise ImplementationProviderContractError(
                        "packet_provider_correlation_recovery_unit_conflict"
                    )
                provider_owners[unit.provider_unit_ref] = flow_unit_ref
                latest[flow_unit_ref] = unit

            restored = 0
            refreshed = 0
            occurred_at = _utc_now()
            for flow_unit_ref, unit in latest.items():
                existing = connection.execute(
                    """
                    SELECT provider_packet_ref, provider_unit_ref,
                           provider_unit_number, unit_state,
                           provider_packet_revision, binding_epoch, event_seq
                    FROM packet_provider_unit_correlations
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND provider_kind = ? AND flow_unit_ref = ?
                    """,
                    (
                        project_id,
                        change_id,
                        packet_id,
                        provider_kind,
                        flow_unit_ref,
                    ),
                ).fetchone()
                if existing is not None and (
                    str(existing["provider_packet_ref"])
                    != str(binding["provider_packet_ref"])
                    or str(existing["provider_unit_ref"])
                    != unit.provider_unit_ref
                    or (
                        existing["provider_unit_number"] is not None
                        and unit.unit_number is not None
                        and int(existing["provider_unit_number"])
                        != unit.unit_number
                    )
                ):
                    raise ImplementationProviderContractError(
                        "packet_provider_correlation_recovery_unit_conflict"
                    )
                if existing is not None and (
                    str(existing["unit_state"]) == unit.state
                    and int(existing["provider_packet_revision"])
                    == int(binding["provider_packet_revision"])
                    and int(existing["binding_epoch"])
                    == int(binding["binding_epoch"])
                    and int(existing["event_seq"]) == int(binding["event_seq"])
                    and (
                        existing["provider_unit_number"] is not None
                        or unit.unit_number is None
                    )
                ):
                    continue
                try:
                    connection.execute(
                        """
                        INSERT INTO packet_provider_unit_correlations(
                            project_id, change_id, packet_id, provider_kind,
                            flow_unit_ref, provider_packet_ref, provider_unit_ref,
                            provider_unit_number, unit_state,
                            provider_packet_revision, binding_epoch,
                            event_seq, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(
                            project_id, change_id, packet_id,
                            provider_kind, flow_unit_ref
                        ) DO UPDATE SET
                            provider_unit_number = COALESCE(
                                packet_provider_unit_correlations.provider_unit_number,
                                excluded.provider_unit_number
                            ),
                            unit_state = excluded.unit_state,
                            provider_packet_revision = excluded.provider_packet_revision,
                            binding_epoch = excluded.binding_epoch,
                            event_seq = excluded.event_seq,
                            updated_at = excluded.updated_at
                        """,
                        (
                            project_id,
                            change_id,
                            packet_id,
                            provider_kind,
                            flow_unit_ref,
                            str(binding["provider_packet_ref"]),
                            unit.provider_unit_ref,
                            unit.unit_number,
                            unit.state,
                            int(binding["provider_packet_revision"]),
                            int(binding["binding_epoch"]),
                            int(binding["event_seq"]),
                            occurred_at,
                            occurred_at,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ImplementationProviderContractError(
                        "packet_provider_correlation_recovery_unit_conflict"
                    ) from exc
                if existing is None:
                    restored += 1
                else:
                    refreshed += 1
            return {"restored": restored, "refreshed": refreshed}

    def claim_packet_provider_command(
        self, project_id: str, outbox_id: str
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        outbox_id = required_text(outbox_id, "outbox_id")
        occurred_at = _utc_now()
        with self._transaction() as connection:
            row = self._packet_provider_outbox_row(connection, project_id, outbox_id)
            if str(row["state"]) in _TERMINAL_STATES:
                return self._packet_provider_outbox_value(
                    connection, project_id, outbox_id
                )
            connection.execute(
                """
                UPDATE packet_provider_outbox
                SET state = 'delivering', attempts = attempts + 1,
                    last_error = '', updated_at = ?
                WHERE project_id = ? AND outbox_id = ?
                """,
                (occurred_at, project_id, outbox_id),
            )
            return self._packet_provider_outbox_value(connection, project_id, outbox_id)

    def mark_packet_provider_command_unknown(
        self,
        project_id: str,
        outbox_id: str,
        *,
        reason: str,
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        outbox_id = required_text(outbox_id, "outbox_id")
        reason = required_text(reason, "reason")[:512]
        with self._transaction() as connection:
            row = self._packet_provider_outbox_row(connection, project_id, outbox_id)
            if str(row["state"]) not in _TERMINAL_STATES:
                connection.execute(
                    """
                    UPDATE packet_provider_outbox
                    SET state = 'unknown', last_error = ?, updated_at = ?
                    WHERE project_id = ? AND outbox_id = ?
                    """,
                    (reason, _utc_now(), project_id, outbox_id),
                )
            return self._packet_provider_outbox_value(connection, project_id, outbox_id)

    def reject_packet_provider_command(
        self,
        project_id: str,
        outbox_id: str,
        *,
        reason: str,
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        outbox_id = required_text(outbox_id, "outbox_id")
        reason = required_text(reason, "reason")[:512]
        with self._transaction() as connection:
            row = self._packet_provider_outbox_row(connection, project_id, outbox_id)
            if str(row["state"]) == PacketProviderOutboxState.DELIVERED.value:
                return self._packet_provider_outbox_value(
                    connection, project_id, outbox_id
                )
            connection.execute(
                """
                UPDATE packet_provider_outbox
                SET state = 'rejected', last_error = ?, updated_at = ?
                WHERE project_id = ? AND outbox_id = ?
                """,
                (reason, _utc_now(), project_id, outbox_id),
            )
            return self._packet_provider_outbox_value(connection, project_id, outbox_id)

    def record_packet_provider_receipt(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        flow_spec_revision: int,
        receipt: PacketProviderReceipt,
        actor: str,
        outbox_id: str = "",
        observation_kind: str = "command",
        allow_terminal_replacement: bool = False,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        actor = required_text(actor, "actor")
        outbox_id = str(outbox_id or "").strip()
        request_id = str(request_id or "")
        if observation_kind not in {"command", "status"}:
            raise ValueError("packet provider observation kind is invalid")
        if not isinstance(allow_terminal_replacement, bool):
            raise ValueError("allow_terminal_replacement must be boolean")
        if (
            isinstance(flow_spec_revision, bool)
            or not isinstance(flow_spec_revision, int)
            or flow_spec_revision <= 0
        ):
            raise ValueError("flow_spec_revision must be positive")
        payload = receipt.persisted_payload()
        encoded = _canonical_json(payload)
        fingerprint = _sha256(encoded)
        occurred_at = _utc_now()
        with self._transaction() as connection:
            self._packet_row(connection, project_id, change_id, packet_id)
            outbox = None
            if outbox_id:
                outbox = self._packet_provider_outbox_row(
                    connection, project_id, outbox_id
                )
                if (
                    str(outbox["change_id"]) != change_id
                    or str(outbox["packet_id"]) != packet_id
                    or str(outbox["provider_kind"]) != receipt.provider_kind
                ):
                    raise ImplementationProviderContractError(
                        "packet_provider_receipt_outbox_mismatch"
                    )
            current = connection.execute(
                """
                SELECT * FROM packet_provider_bindings
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND provider_kind = ?
                """,
                (project_id, change_id, packet_id, receipt.provider_kind),
            ).fetchone()
            existing = connection.execute(
                """
                SELECT receipt_id FROM packet_provider_receipts
                WHERE project_id = ? AND provider_kind = ?
                  AND provider_packet_ref = ? AND binding_epoch = ?
                  AND event_seq = ? AND receipt_fingerprint = ?
                """,
                (
                    project_id,
                    receipt.provider_kind,
                    receipt.provider_packet_ref,
                    receipt.binding_epoch,
                    receipt.event_seq,
                    fingerprint,
                ),
            ).fetchone()
            current_receipt_id = (
                str(current["last_receipt_id"] or "") if current is not None else ""
            )
            stale = bool(
                current is not None
                and receipt.provider_packet_ref
                == str(current["provider_packet_ref"] or "")
                and (receipt.binding_epoch, receipt.event_seq)
                < (int(current["binding_epoch"]), int(current["event_seq"]))
            )
            if existing is not None:
                existing_receipt_id = str(existing["receipt_id"])
                if current_receipt_id and existing_receipt_id != current_receipt_id:
                    receipt_id = current_receipt_id
                    observation_disposition = "stale"
                else:
                    receipt_id = existing_receipt_id
                    observation_disposition = "duplicate"
            elif stale:
                receipt_id = current_receipt_id
                observation_disposition = "stale"
            else:
                receipt_id = self._insert_packet_provider_receipt(
                    connection,
                    project_id=project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    outbox_id=outbox_id,
                    flow_spec_revision=flow_spec_revision,
                    receipt=receipt,
                    observation_kind=observation_kind,
                    fingerprint=fingerprint,
                    encoded=encoded,
                    occurred_at=occurred_at,
                    actor=actor,
                    request_id=request_id,
                )
                self._project_packet_provider_receipt(
                    connection,
                    project_id=project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    flow_spec_revision=flow_spec_revision,
                    receipt_id=receipt_id,
                    receipt=receipt,
                    actor=actor,
                    request_id=request_id,
                    occurred_at=occurred_at,
                    observation_kind=observation_kind,
                    allow_terminal_replacement=allow_terminal_replacement,
                    outbox_id=outbox_id,
                )
                observation_disposition = "applied"
            if outbox_id:
                connection.execute(
                    """
                    UPDATE packet_provider_outbox
                    SET state = 'delivered', receipt_id = ?, last_error = '',
                        delivered_at = CASE
                            WHEN delivered_at = '' THEN ? ELSE delivered_at END,
                        updated_at = ?
                    WHERE project_id = ? AND outbox_id = ?
                    """,
                    (
                        receipt_id,
                        occurred_at,
                        occurred_at,
                        project_id,
                        outbox_id,
                    ),
                )
            return {
                "receipt": self._packet_provider_receipt_value(
                    connection, project_id, receipt_id
                ),
                "binding": self._packet_provider_binding_value(
                    connection,
                    project_id,
                    change_id,
                    packet_id,
                    receipt.provider_kind,
                ),
                "outbox": (
                    self._packet_provider_outbox_value(
                        connection, project_id, outbox_id
                    )
                    if outbox_id
                    else None
                ),
                "observation_disposition": observation_disposition,
            }

    def packet_provider_binding(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        provider_kind: str,
    ) -> Mapping[str, Any] | None:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        provider_kind = required_text(provider_kind, "provider_kind")
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM packet_provider_bindings
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND provider_kind = ?
                """,
                (project_id, change_id, packet_id, provider_kind),
            ).fetchone()
            if row is None:
                return None
            return self._packet_provider_binding_value(
                connection, project_id, change_id, packet_id, provider_kind
            )

    def packet_provider_unit_correlation(
        self,
        project_id: str,
        packet_id: str,
        flow_unit_ref: str,
        *,
        provider_kind: str = "codingcastle",
    ) -> Mapping[str, Any] | None:
        """Resolve one durable provider reference/number pair."""

        project_id = validate_project_id(project_id)
        packet_id = validate_packet_id(packet_id)
        flow_unit_ref = required_text(flow_unit_ref, "flow_unit_ref")
        provider_kind = required_text(provider_kind, "provider_kind")
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT provider_unit_ref, provider_unit_number
                FROM packet_provider_unit_correlations
                WHERE project_id = ? AND packet_id = ?
                  AND provider_kind = ? AND flow_unit_ref = ?
                  AND unit_state NOT IN ('removed', 'deleted', 'abandoned')
                """,
                (project_id, packet_id, provider_kind, flow_unit_ref),
            ).fetchall()
        values = {
            (
                str(row["provider_unit_ref"] or ""),
                row["provider_unit_number"],
            )
            for row in rows
        }
        values = {value for value in values if value[0]}
        if len(values) > 1:
            raise ImplementationProviderContractError(
                "packet_provider_unit_correlation_ambiguous"
            )
        if not values:
            return None
        provider_unit_ref, provider_unit_number = next(iter(values))
        return {
            "provider_unit_ref": provider_unit_ref,
            "unit_number": provider_unit_number,
        }

    def packet_provider_receipts(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        limit: int = 64,
    ) -> list[Mapping[str, Any]]:
        project_id = validate_project_id(project_id)
        change_id = validate_change_id(change_id)
        packet_id = validate_packet_id(packet_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 256
        ):
            raise ValueError("packet provider receipt limit must be between 1 and 256")
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT receipt_id FROM packet_provider_receipts
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                ORDER BY ordinal DESC LIMIT ?
                """,
                (project_id, change_id, packet_id, limit),
            ).fetchall()
            return [
                self._packet_provider_receipt_value(
                    connection, project_id, str(row["receipt_id"])
                )
                for row in rows
            ]

    def recover_interrupted_packet_provider_commands(self) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE packet_provider_outbox
                SET state = 'unknown',
                    last_error = 'interrupted_before_receipt',
                    updated_at = ?
                WHERE state = 'delivering'
                """,
                (_utc_now(),),
            )
            return int(cursor.rowcount)

    def _insert_packet_provider_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        packet_id: str,
        outbox_id: str,
        flow_spec_revision: int,
        receipt: PacketProviderReceipt,
        observation_kind: str,
        fingerprint: str,
        encoded: str,
        occurred_at: str,
        actor: str,
        request_id: str,
    ) -> str:
        connection.execute(
            """
            INSERT OR IGNORE INTO packet_provider_sequences(
                project_id, next_outbox_ordinal, next_receipt_ordinal
            ) VALUES (?, 1, 1)
            """,
            (project_id,),
        )
        ordinal = int(
            connection.execute(
                """
                SELECT next_receipt_ordinal FROM packet_provider_sequences
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()["next_receipt_ordinal"]
        )
        receipt_id = f"PREC-{ordinal:06d}"
        connection.execute(
            """
            INSERT INTO packet_provider_receipts(
                project_id, receipt_id, ordinal, change_id, packet_id,
                outbox_id, provider_kind, flow_spec_revision,
                provider_contract_version, provider_packet_ref,
                provider_packet_revision, provider_state, binding_epoch,
                event_seq, observation_kind, receipt_fingerprint,
                receipt_json, observed_at, actor, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                receipt_id,
                ordinal,
                change_id,
                packet_id,
                outbox_id,
                receipt.provider_kind,
                flow_spec_revision,
                receipt.provider_contract_version,
                receipt.provider_packet_ref,
                receipt.provider_packet_revision,
                receipt.provider_state,
                receipt.binding_epoch,
                receipt.event_seq,
                observation_kind,
                fingerprint,
                encoded,
                occurred_at,
                actor,
                request_id,
            ),
        )
        connection.execute(
            """
            UPDATE packet_provider_sequences
            SET next_receipt_ordinal = ? WHERE project_id = ?
            """,
            (ordinal + 1, project_id),
        )
        return receipt_id

    def _project_packet_provider_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        change_id: str,
        packet_id: str,
        flow_spec_revision: int,
        receipt_id: str,
        receipt: PacketProviderReceipt,
        actor: str,
        request_id: str,
        occurred_at: str,
        observation_kind: str,
        allow_terminal_replacement: bool,
        outbox_id: str,
    ) -> None:
        current = connection.execute(
            """
            SELECT * FROM packet_provider_bindings
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND provider_kind = ?
            """,
            (project_id, change_id, packet_id, receipt.provider_kind),
        ).fetchone()
        incoming_clock = (receipt.binding_epoch, receipt.event_seq)
        if current is None:
            connection.execute(
                """
                INSERT INTO packet_provider_bindings(
                    project_id, change_id, packet_id, provider_kind,
                    provider_packet_ref, provider_packet_revision,
                    flow_spec_revision, binding_epoch, event_seq,
                    flow_binding_generation, provider_state, run_phase,
                    provider_job_ref, current_step,
                    last_receipt_id, created_at, updated_at, actor, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    receipt.provider_kind,
                    receipt.provider_packet_ref,
                    receipt.provider_packet_revision,
                    flow_spec_revision,
                    receipt.binding_epoch,
                    receipt.event_seq,
                    1,
                    receipt.provider_state,
                    receipt.run_phase,
                    receipt.provider_job_ref,
                    receipt.current_step,
                    receipt_id,
                    occurred_at,
                    occurred_at,
                    actor,
                    request_id,
                ),
            )
            project_current = True
        else:
            current_clock = (int(current["binding_epoch"]), int(current["event_seq"]))
            current_ref = str(current["provider_packet_ref"])
            current_generation = int(current["flow_binding_generation"])
            ref_changed = receipt.provider_packet_ref != current_ref
            boundary_changed = ref_changed
            if not boundary_changed and incoming_clock == current_clock:
                current_receipt = self._packet_provider_receipt_value(
                    connection,
                    project_id,
                    str(current["last_receipt_id"]),
                )
                _validate_same_clock_observation(
                    current_binding=current,
                    current_receipt=current_receipt,
                    incoming=receipt,
                )
            reset_clock_replacement = ref_changed and (
                receipt.binding_epoch <= current_clock[0]
            )
            if reset_clock_replacement:
                if not allow_terminal_replacement:
                    if receipt.binding_epoch == current_clock[0]:
                        raise ImplementationProviderContractError(
                            "packet_provider_binding_changed_within_epoch"
                        )
                    raise ImplementationProviderContractError(
                        "packet_provider_binding_replacement_not_authorized"
                    )
                if observation_kind != "status":
                    raise ImplementationProviderContractError(
                        "packet_provider_binding_replacement_requires_status"
                    )
                current_terminal = (
                    str(current["provider_state"]) in _REPLACEABLE_PROVIDER_STATES
                    or str(current["run_phase"]) in _REPLACEABLE_RUN_PHASES
                )
                incoming_fresh = (
                    receipt.provider_state in _FRESH_PROVIDER_STATES
                    and receipt.run_phase in _FRESH_RUN_PHASES
                    and not receipt.provider_job_ref
                )
                if not current_terminal:
                    raise ImplementationProviderContractError(
                        "packet_provider_binding_replacement_requires_terminal"
                    )
                if not incoming_fresh:
                    raise ImplementationProviderContractError(
                        "packet_provider_binding_replacement_requires_fresh_draft"
                    )
                project_current = True
            else:
                project_current = incoming_clock >= current_clock
            if project_current:
                if boundary_changed:
                    uncertain = connection.execute(
                        """
                        SELECT 1 FROM packet_provider_outbox
                        WHERE project_id = ? AND change_id = ? AND packet_id = ?
                          AND provider_kind = ? AND flow_binding_generation = ?
                          AND state IN ('pending', 'delivering', 'unknown')
                          AND outbox_id <> ?
                        LIMIT 1
                        """,
                        (
                            project_id,
                            change_id,
                            packet_id,
                            receipt.provider_kind,
                            current_generation,
                            outbox_id,
                        ),
                    ).fetchone()
                    if uncertain is not None:
                        raise ImplementationProviderContractError(
                            "packet_provider_binding_replacement_has_uncertain_delivery"
                        )
                    connection.execute(
                        """
                        DELETE FROM packet_provider_unit_correlations
                        WHERE project_id = ? AND change_id = ? AND packet_id = ?
                          AND provider_kind = ?
                        """,
                        (project_id, change_id, packet_id, receipt.provider_kind),
                    )
                elif incoming_clock > current_clock:
                    connection.execute(
                        """
                        UPDATE packet_provider_unit_correlations
                        SET provider_packet_revision = ?, binding_epoch = ?,
                            event_seq = ?, updated_at = ?
                        WHERE project_id = ? AND change_id = ? AND packet_id = ?
                          AND provider_kind = ? AND provider_packet_ref = ?
                        """,
                        (
                            receipt.provider_packet_revision,
                            receipt.binding_epoch,
                            receipt.event_seq,
                            occurred_at,
                            project_id,
                            change_id,
                            packet_id,
                            receipt.provider_kind,
                            current_ref,
                        ),
                    )
                flow_binding_generation = (
                    current_generation + 1 if boundary_changed else current_generation
                )
                connection.execute(
                    """
                    UPDATE packet_provider_bindings
                    SET provider_packet_ref = ?, provider_packet_revision = ?,
                        flow_spec_revision = ?, binding_epoch = ?, event_seq = ?,
                        flow_binding_generation = ?,
                        provider_state = ?, run_phase = ?, provider_job_ref = ?,
                        current_step = ?, last_receipt_id = ?, updated_at = ?,
                        actor = ?, request_id = ?
                    WHERE project_id = ? AND change_id = ? AND packet_id = ?
                      AND provider_kind = ?
                    """,
                    (
                        receipt.provider_packet_ref,
                        receipt.provider_packet_revision,
                        flow_spec_revision,
                        receipt.binding_epoch,
                        receipt.event_seq,
                        flow_binding_generation,
                        receipt.provider_state,
                        receipt.run_phase,
                        receipt.provider_job_ref,
                        receipt.current_step,
                        receipt_id,
                        occurred_at,
                        actor,
                        request_id,
                        project_id,
                        change_id,
                        packet_id,
                        receipt.provider_kind,
                    ),
                )
        if not project_current:
            return
        for unit in receipt.unit_receipts:
            existing = connection.execute(
                """
                SELECT provider_unit_ref, provider_unit_number, binding_epoch
                FROM packet_provider_unit_correlations
                WHERE project_id = ? AND change_id = ? AND packet_id = ?
                  AND provider_kind = ? AND flow_unit_ref = ?
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    receipt.provider_kind,
                    unit.flow_unit_ref,
                ),
            ).fetchone()
            if (
                existing is not None
                and int(existing["binding_epoch"]) == receipt.binding_epoch
                and str(existing["provider_unit_ref"]) != unit.provider_unit_ref
            ):
                raise ImplementationProviderContractError(
                    "packet_provider_unit_changed_within_epoch"
                )
            if (
                existing is not None
                and int(existing["binding_epoch"]) == receipt.binding_epoch
                and existing["provider_unit_number"] is not None
                and unit.unit_number is not None
                and int(existing["provider_unit_number"]) != unit.unit_number
            ):
                raise ImplementationProviderContractError(
                    "packet_provider_unit_number_changed_within_epoch"
                )
            connection.execute(
                """
                INSERT INTO packet_provider_unit_correlations(
                    project_id, change_id, packet_id, provider_kind,
                    flow_unit_ref, provider_packet_ref, provider_unit_ref,
                    provider_unit_number, unit_state,
                    provider_packet_revision, binding_epoch,
                    event_seq, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    project_id, change_id, packet_id, provider_kind, flow_unit_ref
                ) DO UPDATE SET
                    provider_packet_ref = excluded.provider_packet_ref,
                    provider_unit_ref = excluded.provider_unit_ref,
                    provider_unit_number = CASE
                        WHEN excluded.binding_epoch =
                             packet_provider_unit_correlations.binding_epoch
                        THEN COALESCE(
                            excluded.provider_unit_number,
                            packet_provider_unit_correlations.provider_unit_number
                        )
                        ELSE excluded.provider_unit_number
                    END,
                    unit_state = excluded.unit_state,
                    provider_packet_revision = excluded.provider_packet_revision,
                    binding_epoch = excluded.binding_epoch,
                    event_seq = excluded.event_seq,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    change_id,
                    packet_id,
                    receipt.provider_kind,
                    unit.flow_unit_ref,
                    receipt.provider_packet_ref,
                    unit.provider_unit_ref,
                    unit.unit_number,
                    unit.state,
                    receipt.provider_packet_revision,
                    receipt.binding_epoch,
                    receipt.event_seq,
                    occurred_at,
                    occurred_at,
                ),
            )

    def _packet_provider_outbox_row(
        self, connection: sqlite3.Connection, project_id: str, outbox_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_provider_outbox
            WHERE project_id = ? AND outbox_id = ?
            """,
            (project_id, outbox_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown packet provider outbox entry: {outbox_id}"
            )
        return row

    def _packet_provider_outbox_value(
        self, connection: sqlite3.Connection, project_id: str, outbox_id: str
    ) -> Mapping[str, Any]:
        value = dict(
            self._packet_provider_outbox_row(connection, project_id, outbox_id)
        )
        value["command"] = json.loads(value.pop("command_json"))
        return value

    def _packet_provider_receipt_row(
        self, connection: sqlite3.Connection, project_id: str, receipt_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM packet_provider_receipts
            WHERE project_id = ? AND receipt_id = ?
            """,
            (project_id, receipt_id),
        ).fetchone()
        if row is None:
            raise RequirementConflictError(
                f"unknown packet provider receipt: {receipt_id}"
            )
        return row

    def _packet_provider_receipt_value(
        self, connection: sqlite3.Connection, project_id: str, receipt_id: str
    ) -> Mapping[str, Any]:
        value = dict(
            self._packet_provider_receipt_row(connection, project_id, receipt_id)
        )
        value["receipt"] = json.loads(value.pop("receipt_json"))
        return value

    def _packet_provider_binding_value(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        change_id: str,
        packet_id: str,
        provider_kind: str,
    ) -> Mapping[str, Any]:
        row = connection.execute(
            """
            SELECT * FROM packet_provider_bindings
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND provider_kind = ?
            """,
            (project_id, change_id, packet_id, provider_kind),
        ).fetchone()
        if row is None:
            raise RequirementConflictError("packet provider binding is unavailable")
        units = connection.execute(
            """
            SELECT flow_unit_ref, provider_unit_ref, provider_unit_number, unit_state,
                   provider_packet_revision, binding_epoch, event_seq
            FROM packet_provider_unit_correlations
            WHERE project_id = ? AND change_id = ? AND packet_id = ?
              AND provider_kind = ?
            ORDER BY flow_unit_ref
            """,
            (project_id, change_id, packet_id, provider_kind),
        ).fetchall()
        value = dict(row)
        value["unit_correlations"] = [dict(item) for item in units]
        return value


def _validate_same_clock_observation(
    *,
    current_binding: sqlite3.Row,
    current_receipt: Mapping[str, object],
    incoming: PacketProviderReceipt,
) -> None:
    if incoming.provider_packet_revision != int(
        current_binding["provider_packet_revision"]
    ):
        raise ImplementationProviderContractError(
            "packet_provider_revision_changed_within_clock"
        )
    current_payload = current_receipt.get("receipt")
    if not isinstance(current_payload, Mapping):
        raise ImplementationProviderContractError(
            "packet_provider_current_receipt_invalid"
        )
    current_technical = current_payload.get("technical")
    if not isinstance(current_technical, Mapping):
        current_technical = {}
    current_state = str(current_payload.get("provider_state") or "")
    current_phase = str(current_technical.get("phase") or "idle")
    current_job_ref = str(current_technical.get("job_ref") or "")
    current_active = provider_observation_active(
        provider_state=current_state,
        run_phase=current_phase,
        provider_job_ref=current_job_ref,
    )
    incoming_active = provider_observation_active(
        provider_state=incoming.provider_state,
        run_phase=incoming.run_phase,
        provider_job_ref=incoming.provider_job_ref,
    )
    current_terminal = provider_observation_terminal(
        provider_state=current_state,
        run_phase=current_phase,
    )
    if (
        current_active
        and current_job_ref
        and incoming.provider_job_ref
        and incoming.provider_job_ref != current_job_ref
    ):
        raise ImplementationProviderContractError(
            "packet_provider_job_changed_while_active"
        )
    if current_terminal and incoming_active:
        retryable_terminal = current_state in {"blocked", "failed", "stopped"}
        new_job = bool(
            incoming.provider_job_ref
            and incoming.provider_job_ref != current_job_ref
        )
        if not (retryable_terminal and new_job):
            raise ImplementationProviderContractError(
                "packet_provider_terminal_state_regressed_within_clock"
            )


def _canonical_json(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("packet provider persistence payload must be JSON") from exc


def _sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _persisted_unit_receipt(
    encoded_receipt: str, *, flow_unit_ref: str
) -> PacketProviderUnitReceipt:
    try:
        payload = json.loads(encoded_receipt)
        units = payload.get("unit_receipts")
        if not isinstance(units, list):
            raise ValueError("unit receipts are unavailable")
        matching = [
            item
            for item in units
            if isinstance(item, Mapping)
            and str(item.get("flow_unit_ref") or "") == flow_unit_ref
        ]
        if len(matching) != 1:
            raise ValueError("delivered receipt does not identify one Flow unit")
        item = matching[0]
        raw_number = item.get("unit_number")
        if raw_number is not None and (
            isinstance(raw_number, bool) or not isinstance(raw_number, int)
        ):
            raise ValueError("unit number is invalid")
        return PacketProviderUnitReceipt(
            flow_unit_ref=flow_unit_ref,
            provider_unit_ref=str(item.get("provider_unit_ref") or ""),
            state=str(item.get("state") or ""),
            unit_number=raw_number,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ImplementationProviderContractError(
            "packet_provider_correlation_recovery_receipt_invalid"
        ) from exc


__all__: Sequence[str] = ("PacketProviderSocketStoreMixin",)
