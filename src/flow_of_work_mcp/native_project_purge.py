"""Native, explicitly confirmed project deletion; never a model MCP operation.

The gateway opens an existing ledger under its OS lease, without composing a
runtime, running migrations/recovery or contacting any provider. The sidecar is
an intent/continuation record, not a copy of the deleted project.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from typing import Any
from uuid import UUID

import yaml

from flow_of_work_mcp.config import load_config
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.native_purge_schema import SCHEMA55_TABLE_HASHES
from flow_of_work_mcp.profiles import profile_config_path
from flow_of_work_mcp.runtime_ownership import (
    RuntimeOwnershipError, acquire_runtime_ownership,
)

CONTRACT = "flower.project-purge.v1"
_JOURNAL_KEYS = frozenset({
    "contract", "deletion_id", "project_id", "database_identity", "config_identity",
    "schema_version", "schema_fingerprint", "prepared_fingerprint", "project_identity",
    "counts", "stage", "created_at", "updated_at", "host_quiescence_ref",
    "host_stopped_run_ids", "provenance",
})
_INDIRECT = {
    "generated_artifacts": "generation_id IN (SELECT generation_id FROM artifact_generations WHERE project_id = ?)",
    "artifact_mappings": "artifact_id IN (SELECT artifact_id FROM generated_artifacts WHERE generation_id IN (SELECT generation_id FROM artifact_generations WHERE project_id = ?))",
    "grounding_audit_items": "audit_id IN (SELECT audit_id FROM grounding_audits WHERE project_id = ?)",
    "grounding_audit_anchors": "audit_id IN (SELECT audit_id FROM grounding_audits WHERE project_id = ?)",
    "phase_audit_requirements": "phase_audit_id IN (SELECT phase_audit_id FROM phase_audits WHERE project_id = ?)",
    "phase_audit_deltas": "phase_audit_id IN (SELECT phase_audit_id FROM phase_audits WHERE project_id = ?)",
    "packet_criterion_history": "criterion_identity IN (SELECT criterion_identity FROM packet_criteria WHERE project_id = ?)",
}
_ACTIVE_STATES = frozenset({"queued", "running", "stopping"})
_ACTIVE_PHASES = frozenset({"execution", "execution_recovery", "queued", "remediating",
    "running", "stopping", "technical_remediation"})
_TERMINAL_STATES = frozenset({"abandoned", "blocked", "completed", "failed", "partial", "stopped"})
_TERMINAL_PHASES = frozenset({"idle", "blocked", "completed", "completion", "execution_blocked",
    "execution_failed", "failed", "partial", "planning_reconciliation_blocked", "recovery_blocked", "stopped"})
_UNSTARTED_STATES = frozenset({"draft", "planned", "ready", "idle", "created", "pending", "uninitialized"})
_UNSTARTED_PHASES = frozenset({"idle", "planning", "ready", "draft", "planned", "construction"})
_EXIT_CODES = {"success": 0, "rejected": 2, "blocked": 3, "failed": 4}


class _Problem(Exception):
    def __init__(self, code: str, message: str, resolution: str, *, status: str = "rejected") -> None:
        self.code, self.message, self.resolution, self.status = code, message, resolution, status
        super().__init__(code)


def _encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: object, limit: int = 160) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")[:limit]


def _safe_path(path: Path, *, directory: bool = False, private: bool = False) -> os.stat_result:
    if not path.is_absolute():
        raise _Problem("path_not_absolute", "Select an absolute local path.", "Use an explicit absolute config or profile root.")
    # Do not resolve away a symlink before checking it, including ancestors.
    for part in (path, *path.parents):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            raise _Problem("path_missing", "A selected existing path is missing.", "Inspect the native host's configuration and select an existing owned ledger.") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise _Problem("path_unsafe", "Symbolic-link paths are not accepted for native deletion.", "Select the original owned regular config and ledger without symlink aliases.")
    metadata = path.lstat()
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected or (not directory and metadata.st_nlink != 1):
        raise _Problem("path_unsafe", "Selected paths must be regular and without hard-link aliases.", "Inspect the selected file identity without replacing or unlinking it.")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise _Problem("path_not_owned", "The selected path is not owned by this OS user.", "Run native management as the owning user; do not change another user's files.")
    if private and os.name == "posix" and stat.S_IMODE(metadata.st_mode) != (0o700 if directory else 0o600):
        raise _Problem("journal_not_private", "The native deletion journal is not private.", "Inspect the journal ownership and restore its required private permissions explicitly.", status="blocked")
    return metadata


def _read_regular(path: Path, *, private: bool = False, limit: int = 1_048_576) -> tuple[bytes, os.stat_result]:
    before = _safe_path(path, private=private)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(descriptor, "rb") as stream:
        held = os.fstat(stream.fileno())
        content = stream.read(limit + 1)
    after = _safe_path(path, private=private)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns
    ) or (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or len(content) > limit:
        raise _Problem("path_changed", "A selected file changed during validation or exceeds the native limit.", "Stop other writers and inspect the original selected files.", status="blocked")
    return content, after


def _fsync_directory(path: Path) -> None:
    """Prove the required durability primitive rather than silently weakening it."""
    _safe_path(path, directory=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise _Problem("native_purge_durability_unavailable", "Durable directory synchronization is unavailable on the selected platform/filesystem.", "Use a separately qualified native purge platform/filesystem; do not bypass the durability requirement.", status="blocked") from None


def _shape(connection: sqlite3.Connection, name: str) -> tuple[list, list, list]:
    columns = sorted((row[1], row[2].upper(), row[3], row[4], row[5], row[6])
                     for row in connection.execute(f"PRAGMA table_xinfo({name})"))
    groups: dict[int, list] = defaultdict(list)
    for row in connection.execute(f"PRAGMA foreign_key_list({name})"):
        groups[row[0]].append(tuple(row[1:]))
    foreign_keys = sorted(sorted(rows) for rows in groups.values())
    unique = []
    for row in connection.execute(f"PRAGMA index_list({name})"):
        if row[2]:
            # Index names come from SQLite, not caller input.
            quoted = row[1].replace('"', '""')
            unique.append((row[4], tuple((item[2], item[3], item[4], item[5])
                for item in connection.execute(f'PRAGMA index_xinfo("{quoted}")'))))
    return columns, foreign_keys, sorted(unique)


def _validate_schema(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    objects = list(connection.execute("SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','view','trigger')"))
    names = {row[1] for row in objects if row[1] != "sqlite_sequence"}
    if names != set(SCHEMA55_TABLE_HASHES) or any(row[0] != "table" or "VIRTUAL TABLE" in str(row[2]).upper() for row in objects):
        raise _Problem("purge_schema_unsupported", "The ledger has unexpected or missing tables, views, triggers or virtual schema.", "Use a supported exact schema55 ledger; do not remove unknown schema to force deletion.", status="blocked")
    if connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] != 55:
        raise _Problem("purge_schema_unsupported", "Native deletion supports schema55 only.", "Keep this ledger intact and obtain a separately qualified native gateway for its schema.", status="blocked")
    columns = {}
    for name, expected in SCHEMA55_TABLE_HASHES.items():
        shape = _shape(connection, name)
        if _digest(shape) != expected:
            raise _Problem("purge_schema_unsupported", "A schema55 table has an unsupported structure.", "Inspect schema drift and use the native gateway matching the ledger's actual structure.", status="blocked")
        columns[name] = tuple(row[0] for row in shape[0])
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise _Problem("purge_foreign_key_corruption", "The ledger has foreign-key corruption.", "Reconcile ledger integrity before destructive native management.", status="blocked")
    return columns


def _scope(name: str, project_id: str) -> tuple[str, tuple[str, ...]]:
    if name == "interaction_project_context_events":
        return "project_id = ? OR previous_project_id = ?", (project_id, project_id)
    return _INDIRECT.get(name, "project_id = ?"), (project_id,)


def _sql_value(value: object) -> object:
    # A typed encoding avoids collisions between SQLite TEXT/BLOB/numeric cells.
    if value is None:
        return ["null"]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    return [type(value).__name__, value]


def _inventory(connection: sqlite3.Connection, columns: dict, project_id: str) -> dict[str, Any]:
    digest = hashlib.sha256()
    counts = {}
    for name in sorted(set(columns) - {"schema_migrations"}):
        names = columns[name]
        digest.update(_encoded([name, names]))
        where, parameters = _scope(name, project_id)
        ordering = tuple(row[1] for row in sorted(connection.execute(f"PRAGMA table_xinfo({name})"), key=lambda row: row[5]) if row[5])
        order = ",".join(ordering or names)
        count = 0
        for row in connection.execute(f"SELECT {','.join(names)} FROM {name} WHERE {where} ORDER BY {order}", parameters):
            encoded = _encoded([_sql_value(value) for value in row])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        counts[name] = count
    project = connection.execute("SELECT project_id, created_at, created_by FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    return {"fingerprint": digest.hexdigest(), "counts": counts, "project_present": project is not None,
            "project_identity": _digest(list(project)) if project is not None else ""}


def _packet_payload_digest(value: object) -> str:
    # This is the existing packet socket's exact persisted encoding, whose
    # Unicode policy differs from the native journal's encoding.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _packet_receipt(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    try:
        from flow_of_work_mcp.core.domain.packet_provider import PacketProviderReceipt, PacketProviderUnitReceipt
        body = json.loads(row["receipt_json"])
        technical = body["technical"]
        value = PacketProviderReceipt(
            provider_kind=body["provider_kind"], provider_contract_version=body["provider_contract_version"],
            provider_packet_ref=body["provider_packet_ref"], provider_packet_revision=body["provider_packet_revision"],
            provider_state=body["provider_state"], binding_epoch=body["binding_epoch"], event_seq=body["event_seq"],
            changed=body["changed"], unit_receipts=tuple(PacketProviderUnitReceipt(**unit) for unit in body["unit_receipts"]),
            readiness_gaps=body["readiness_gaps"], current_step=body["current_step"], question=body["question"],
            choices=(), required_input=body["required_input"], available_actions=body["available_actions"],
            run_phase=technical["phase"], provider_job_ref=technical["job_ref"], retry=technical["retry"],
            unit_receipts_truncated=body["unit_receipts_truncated"], readiness_gaps_truncated=body["readiness_gaps_truncated"],
            choices_truncated=body["choices_truncated"], contract_version=body["contract_version"],
            validation_ack=body.get("validation_ack", {}))
        fields = ("provider_kind", "provider_contract_version", "provider_packet_ref", "provider_packet_revision",
                  "provider_state", "binding_epoch", "event_seq")
        if value.persisted_payload() != body or any(body[field] != row[field] for field in fields) or _packet_payload_digest(body) != row["receipt_fingerprint"]:
            return None
        return body
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def _packet_command(row: sqlite3.Row) -> bool:
    try:
        from flow_of_work_mcp.core.domain.packet_provider import PacketProviderCommand
        body = json.loads(row["command_json"])
        value = PacketProviderCommand.from_payload(body)
        return (value.as_payload() == body and value.flow_session_ref == row["project_id"]
            and value.flow_packet_ref == row["packet_id"] and value.flow_spec_revision == row["flow_spec_revision"]
            and value.operation.value == row["operation"] and value.flow_unit_ref == row["flow_unit_ref"]
            and value.delivery_fingerprint == row["delivery_fingerprint"]
            and _packet_payload_digest(body) == row["command_fingerprint"])
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _receipt_for_command(connection: sqlite3.Connection, command: sqlite3.Row) -> tuple[sqlite3.Row, dict] | None:
    row = connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id=? AND receipt_id=?",
                             (command["project_id"], command["receipt_id"])).fetchone()
    body = _packet_receipt(row)
    if body is None or not _packet_command(command):
        return None
    if (row["change_id"], row["packet_id"], row["outbox_id"], row["provider_kind"], row["flow_spec_revision"], row["observation_kind"]) != (
        command["change_id"], command["packet_id"], command["outbox_id"], command["provider_kind"], command["flow_spec_revision"], "command"):
        return None
    return row, body


def _terminal_packet_body(body: dict) -> bool:
    return body["provider_state"] in _TERMINAL_STATES and body["technical"]["phase"] in _TERMINAL_PHASES


def _packet_start_terminal(connection: sqlite3.Connection, start: sqlite3.Row) -> bool:
    """Prove each retained START, including history hidden by a newer binding.

    Receipt rows have no Flow generation column. For historical generations only
    exact command-linked terminal evidence of that same generation is supported;
    a new binding or an ambiguous later status cannot close an older START.
    """
    binding = connection.execute("""SELECT * FROM packet_provider_bindings WHERE project_id=? AND change_id=?
        AND packet_id=? AND provider_kind=?""", (start["project_id"], start["change_id"], start["packet_id"], start["provider_kind"])).fetchone()
    original = _receipt_for_command(connection, start)
    if binding is None or original is None or start["flow_binding_generation"] <= 0:
        return False
    bound_receipt = connection.execute("SELECT * FROM packet_provider_receipts WHERE project_id=? AND receipt_id=?",
        (start["project_id"], binding["last_receipt_id"])).fetchone()
    bound_body = _packet_receipt(bound_receipt)
    fields = ("change_id", "packet_id", "provider_kind", "flow_spec_revision", "provider_packet_ref",
              "provider_packet_revision", "provider_state", "binding_epoch", "event_seq")
    if (bound_body is None or any(bound_receipt[field] != binding[field] for field in fields)
        or bound_body["technical"]["phase"] != binding["run_phase"]
        or (bound_body["technical"]["job_ref"] or "") != binding["provider_job_ref"]):
        return False
    origin, origin_body = original
    generation = start["flow_binding_generation"]
    if binding["flow_binding_generation"] < generation:
        return False
    matching = list(connection.execute("""SELECT * FROM packet_provider_receipts WHERE project_id=? AND change_id=?
        AND packet_id=? AND provider_kind=? AND provider_packet_ref=? AND binding_epoch=? ORDER BY ordinal""",
        (start["project_id"], start["change_id"], start["packet_id"], start["provider_kind"],
         origin["provider_packet_ref"], origin["binding_epoch"])))
    from flow_of_work_mcp.core.domain.packet_provider import provider_observation_active
    execution_facts = {}
    newest_event = max(row["event_seq"] for row in matching)
    for row in matching:
        body = _packet_receipt(row)
        if body is None:
            return False
        technical = body["technical"]
        # The ordinary socket permits metadata/changed-flag variations at one
        # clock. Compare execution knowledge, not complete receipt hashes: a
        # terminal disposition can vary while preserving the same quiescence.
        # Active/unknown knowledge, packet revision or a new job cannot fork
        # the same retained producer clock and still prove this START terminal.
        facts = (body["provider_packet_revision"], _terminal_packet_body(body),
            provider_observation_active(provider_state=body["provider_state"], run_phase=technical["phase"],
                                        provider_job_ref=technical["job_ref"] or ""), technical["job_ref"] or "")
        clock = (row["binding_epoch"], row["event_seq"])
        # Older producer clocks are stale relative to a genuinely newer
        # terminal proof. This permits ordinary retry reconciliation instead
        # of making a historical same-clock retry an irreversible purge hold.
        if row["event_seq"] == newest_event and clock in execution_facts and execution_facts[clock] != facts:
            return False
        execution_facts[clock] = facts
    latest_clock = max((row["event_seq"], row["provider_packet_revision"]) for row in matching)

    def sufficient(row, body):
        return (_terminal_packet_body(body) and row["ordinal"] >= origin["ordinal"]
            and row["provider_packet_ref"] == origin["provider_packet_ref"]
            and row["binding_epoch"] == origin["binding_epoch"]
            and (row["event_seq"], row["provider_packet_revision"]) >= latest_clock)

    if binding["flow_binding_generation"] == generation:
        latest, body = bound_receipt, bound_body
        if latest["observation_kind"] == "command":
            command = connection.execute("SELECT * FROM packet_provider_outbox WHERE project_id=? AND outbox_id=?",
                                         (start["project_id"], latest["outbox_id"])).fetchone()
            if command is None or command["flow_binding_generation"] != generation or command["state"] != "delivered" or _receipt_for_command(connection, command) is None:
                return False
        return sufficient(latest, body)
    if sufficient(origin, origin_body):
        return True
    for command in connection.execute("""SELECT * FROM packet_provider_outbox WHERE project_id=? AND change_id=?
        AND packet_id=? AND provider_kind=? AND flow_binding_generation=? AND state='delivered' AND ordinal>=?""",
        (start["project_id"], start["change_id"], start["packet_id"], start["provider_kind"], generation, start["ordinal"])):
        candidate = _receipt_for_command(connection, command)
        if candidate is not None and sufficient(*candidate):
            return True
    return False


def _blockers(connection: sqlite3.Connection, project_id: str, host_stopped: set[str]) -> list[dict[str, str]]:
    blockers = []
    for table, identity in (("packet_provider_outbox", "outbox_id"), ("test_provider_outbox", "command_id")):
        for row in connection.execute(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY ordinal", (project_id,)):
            if row["state"] in {"delivered", "rejected"} or (row["state"] == "pending" and row["attempts"] == 0):
                continue
            blockers.append({"code": "external_command_unresolved", "owner": _safe_text(row["provider_kind"]),
                "command_id": _safe_text(row[identity]), "state": _safe_text(row["state"]),
                "resolution": "Use the existing provider read/status/stop/reconcile workflow for this exact command; native purge never forces remote abandonment."})
    for start in connection.execute("SELECT * FROM packet_provider_outbox WHERE project_id=? AND operation='start' AND state='delivered' ORDER BY ordinal", (project_id,)):
        if not _packet_start_terminal(connection, start):
            blockers.append({"code": "external_packet_start_unresolved", "owner": _safe_text(start["provider_kind"]),
                "command_id": _safe_text(start["outbox_id"]), "packet_id": _safe_text(start["packet_id"]),
                "resolution": "Reconcile this exact START generation and its retained binding/command receipts to supported terminal evidence. Missing or newer unrelated bindings cannot waive an older START."})
    for row in connection.execute("SELECT * FROM packet_provider_bindings WHERE project_id = ?", (project_id,)):
        state, phase = row["provider_state"], row["run_phase"]
        started = connection.execute("""SELECT 1 FROM packet_provider_outbox WHERE project_id = ? AND change_id = ?
            AND packet_id = ? AND provider_kind = ? AND flow_binding_generation=? AND operation = 'start' AND state = 'delivered' LIMIT 1""",
            (project_id, row["change_id"], row["packet_id"], row["provider_kind"], row["flow_binding_generation"])).fetchone() is not None
        terminal = state in _TERMINAL_STATES and phase in _TERMINAL_PHASES
        unstarted = not started and state in _UNSTARTED_STATES and phase in _UNSTARTED_PHASES
        if state in _ACTIVE_STATES or phase in _ACTIVE_PHASES or not (terminal or unstarted):
            blockers.append({"code": "external_packet_writer_unresolved", "owner": _safe_text(row["provider_kind"]),
                "packet_id": _safe_text(row["packet_id"]), "state": _safe_text(state), "run_phase": _safe_text(phase),
                "resolution": "Observe and stop/reconcile the actual packet provider through its existing public workflow; missing provider availability is not quiescence."})
    for row in connection.execute("SELECT * FROM test_provider_outbox WHERE project_id = ? AND operation = 'run' AND state = 'delivered'", (project_id,)):
        receipt = connection.execute("""SELECT * FROM test_provider_receipts WHERE project_id = ? AND command_id = ?
            ORDER BY provider_event_seq DESC, ordinal DESC LIMIT 1""", (project_id, row["command_id"])).fetchone()
        proven = False
        if receipt is not None and receipt["provider_kind"] == row["provider_kind"] and receipt["campaign_id"] == row["campaign_id"] and receipt["case_id"] == row["case_id"]:
            try:
                from flow_of_work_mcp.core.domain.campaign_authority import TestProviderReceipt
                value = TestProviderReceipt.from_payload(json.loads(receipt["receipt_json"]))
                proven = (value.command_id == row["command_id"]
                    and value.provider_event_seq == receipt["provider_event_seq"]
                    and value.fingerprint == receipt["receipt_fingerprint"]
                    and value.complete is True and value.integrity_preserved is True
                    and value.technical_state == "completed")
            except (ValueError, TypeError, KeyError):
                proven = False
        if not proven:
            blockers.append({"code": "external_test_writer_unresolved", "owner": _safe_text(row["provider_kind"]),
                "command_id": _safe_text(row["command_id"]), "campaign_id": _safe_text(row["campaign_id"]),
                "resolution": "Obtain a complete integrity-preserved terminal receipt for this original RUN. A distinct REPORT has no original-run proof in schema55 and cannot waive this blocker."})
    for row in connection.execute("SELECT * FROM implementation_runs WHERE project_id = ?", (project_id,)):
        if not (row["external_ref"] or row["orchestrator_ref"]):
            continue
        if row["run_id"] in host_stopped or (row["status"] == "completed" and bool(row["completion_reference"])):
            continue
        blockers.append({"code": "externally_referenced_run_unresolved", "run_id": _safe_text(row["run_id"]),
            "state": _safe_text(row["status"]),
            "resolution": "Reconcile the external execution to a known terminal outcome, or have its actual native host stop it and declare this exact current --host-stopped-run-id. Local blocked/cancelled history is not stop proof."})
    return blockers


def _delete_rows(connection: sqlite3.Connection, columns: dict, project_id: str) -> None:
    remaining = set(columns) - {"schema_migrations"}
    parents: dict[str, set[str]] = {}
    incoming = {name: 0 for name in remaining}
    for name in remaining:
        parents[name] = {row[2] for row in connection.execute(f"PRAGMA foreign_key_list({name})") if row[2] != name and row[2] in remaining}
        for parent in parents[name]:
            incoming[parent] += 1
    order = []
    while remaining:
        leaves = sorted(name for name in remaining if incoming[name] == 0)
        if not leaves:
            raise _Problem("purge_dependency_cycle", "Unsupported cyclic table ownership prevents a proved deletion order.", "Inspect the actual schema; do not disable foreign keys.", status="blocked")
        for name in leaves:
            order.append(name)
            remaining.remove(name)
            for parent in parents[name]:
                incoming[parent] -= 1
    for name in order:
        if name == "phase_audits":
            # Self-referencing previous_phase_audit_id requires child-first rows.
            identities = {row[0] for row in connection.execute("SELECT phase_audit_id FROM phase_audits WHERE project_id = ?", (project_id,))}
            while identities:
                referenced = {row[0] for row in connection.execute("SELECT previous_phase_audit_id FROM phase_audits WHERE previous_phase_audit_id IS NOT NULL")}
                leaves = identities - referenced
                if not leaves:
                    raise _Problem("purge_cross_project_or_cycle", "A phase-audit dependency is cyclic or referenced by another project.", "Reconcile the dependency without deleting another project's authority.", status="blocked")
                for identity in sorted(leaves, reverse=True):
                    connection.execute("DELETE FROM phase_audits WHERE project_id = ? AND phase_audit_id = ?", (project_id, identity))
                identities -= leaves
        else:
            where, parameters = _scope(name, project_id)
            connection.execute(f"DELETE FROM {name} WHERE {where}", parameters)


class _Gateway:
    def __init__(self, args: Any) -> None:
        self.args = args
        self.journal: dict[str, Any] | None = None
        self.config_path: Path | None = None
        self.database: Path | None = None
        self.config_identity: dict | None = None
        self.database_identity: dict | None = None
        self.result = {"contract": CONTRACT, "operation": args.purge_operation, "status": "failed",
            "project_id": args.project_id, "deletion_id": args.deletion_id, "deletion_state": "unknown",
            "project_present": None, "schema_version": None, "fingerprint": "", "prepared_fingerprint": "",
            "current_fingerprint": "", "project_effect_state": "unknown", "journal_changed": False,
            "blockers": [], "diagnostics": [], "next_action": "Inspect the native invocation and selected owned files."}

    def _validate_arguments(self) -> None:
        try:
            if str(UUID(self.args.deletion_id)) != self.args.deletion_id:
                raise ValueError()
            if validate_project_id(self.args.project_id) != self.args.project_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise _Problem("purge_identity_invalid", "Use a canonical UUID deletion ID and a valid project ID.", "Correct the native identifiers without retrying a destructive operation blindly.") from None
        if self.args.config is not None:
            if self.args.profile is not None or self.args.profile_root is not None:
                raise _Problem("purge_location_invalid", "--config cannot be combined with profile selection.", "Select exactly one existing config or explicit profile/root pair.")
            self.config_path = self.args.config.expanduser()
        else:
            if self.args.profile is None or self.args.profile_root is None or not self.args.profile_root.is_absolute():
                raise _Problem("purge_location_invalid", "Native deletion requires an explicit existing config or profile and absolute profile root.", "Provide --config ABSOLUTE_CONFIG or --profile PROFILE --profile-root ABSOLUTE_ROOT.")
            # Check the unnormalized root before the profile helper resolves it.
            _safe_path(self.args.profile_root, directory=True)
            self.config_path = profile_config_path(self.args.profile_root, self.args.profile)
    def _validate_operation_arguments(self) -> None:
        args = self.args
        if args.expected_fingerprint and not re.fullmatch(r"[0-9a-f]{64}", args.expected_fingerprint):
            raise _Problem("purge_fingerprint_invalid", "Expected fingerprint must be a lowercase SHA256 digest.", "Use the exact prepared_fingerprint returned by prepare.")
        if args.purge_operation == "delete":
            if args.confirm_project_id != args.project_id or not args.expected_fingerprint:
                raise _Problem("purge_confirmation_required", "Delete requires the exact project confirmation and prepared fingerprint.", "Inspect the prepared native intent and provide matching --confirm-project-id and --expected-fingerprint.")
            reference = args.host_quiescence_ref
            if not reference or not reference.strip() or len(reference) > 256 or any(ord(char) < 32 for char in reference):
                raise _Problem("host_quiescence_required", "Delete requires a bounded nonblank native host stop reference.", "Stop actual owned chat/Bash workers and Flow, prevent respawn, then provide the host's opaque --host-quiescence-ref.")
            if len(args.host_stopped_run_id) > 64 or len(set(args.host_stopped_run_id)) != len(args.host_stopped_run_id) or any(not re.fullmatch(r"RUN-[0-9]{6}", value) for value in args.host_stopped_run_id):
                raise _Problem("host_run_declaration_invalid", "Host-stopped run IDs must be at most64 distinct canonical current RUN IDs.", "Declare only actual executions owned and stopped by this native host.")
        elif args.confirm_project_id or args.host_quiescence_ref or args.host_stopped_run_id or (args.expected_fingerprint and args.purge_operation != "reconcile"):
            raise _Problem("purge_argument_not_applicable", "Confirmation/host-stop arguments apply only to delete; recovery fingerprint applies only to reconcile.", "Use the documented arguments for this native operation.")
        if args.acknowledge_host_cleanup and args.purge_operation != "reconcile":
            raise _Problem("purge_ack_not_applicable", "Host-cleanup acknowledgement applies only to reconcile.", "Acknowledge only after Flow scrub and the native host's local cleanup have completed.")

    def _select_database(self) -> None:
        content, metadata = _read_regular(self.config_path)
        self.config_path = self.config_path.resolve()
        try:
            raw = yaml.safe_load(content)
            raw_database = Path(raw["runtime"]["database_path"]).expanduser()
            if not raw_database.is_absolute():
                raw_database = self.config_path.parent / raw_database
            _safe_path(raw_database)
            config = load_config(self.config_path)
        except _Problem:
            raise
        except (ValueError, TypeError, KeyError, yaml.YAMLError):
            raise _Problem("purge_config_invalid", "The selected configuration is not a supported existing Flower configuration.", "Inspect the configuration with native file tools; no profile or runtime was initialized.") from None
        self.config_identity = {"path": str(self.config_path), "device": metadata.st_dev, "inode": metadata.st_ino,
                                "sha256": hashlib.sha256(content).hexdigest()}
        self.database = config.runtime.database_path
        metadata = _safe_path(self.database)
        self.database_identity = {"path": str(self.database), "device": metadata.st_dev, "inode": metadata.st_ino}
        self.journal_directory = self.database.with_name(self.database.name + ".project-purge")
        self.journal_path = self.journal_directory / (self.args.deletion_id + ".json")

    def _assert_identity(self) -> None:
        content, metadata = _read_regular(self.config_path)
        current = {"path": str(self.config_path), "device": metadata.st_dev, "inode": metadata.st_ino,
                   "sha256": hashlib.sha256(content).hexdigest()}
        database_metadata = _safe_path(self.database)
        actual = {"path": str(self.database), "device": database_metadata.st_dev, "inode": database_metadata.st_ino}
        if current != self.config_identity or actual != self.database_identity:
            raise _Problem("purge_identity_changed", "The selected config or ledger identity changed.", "Inspect the original bound files; never rebind an existing destructive intent.", status="blocked")
        for suffix in ("-wal", "-shm", "-journal"):
            path = self.database.with_name(self.database.name + suffix)
            if path.exists() or path.is_symlink():
                _safe_path(path)

    def _read_journal(self) -> None:
        if not self.journal_directory.exists() and not self.journal_directory.is_symlink():
            self.result["project_effect_state"] = "none"
            return
        _safe_path(self.journal_directory, directory=True, private=True)
        if not self.journal_path.exists() and not self.journal_path.is_symlink():
            self.result["project_effect_state"] = "none"
            return
        content, _ = _read_regular(self.journal_path, private=True)
        try:
            journal = json.loads(content)
            if not isinstance(journal, dict) or set(journal) != _JOURNAL_KEYS or journal["contract"] != CONTRACT or journal["stage"] not in {"prepared", "deleting", "ledger_deleted", "scrubbed"}:
                raise ValueError()
            if journal["database_identity"] != self.database_identity or journal["config_identity"] != self.config_identity or journal["project_id"] != self.args.project_id or journal["deletion_id"] != self.args.deletion_id:
                raise _Problem("purge_intent_conflict", "The deletion ID is bound to a different project/config/ledger identity.", "Inspect the original intent; use a new ID only for a genuinely new native preparation.", status="blocked")
            if journal["schema_version"] != 55 or journal["schema_fingerprint"] != _digest(SCHEMA55_TABLE_HASHES) or not re.fullmatch(r"[0-9a-f]{64}", journal["prepared_fingerprint"]) or not re.fullmatch(r"[0-9a-f]{64}", journal["project_identity"]):
                raise ValueError()
            if not isinstance(journal["counts"], dict) or set(journal["counts"]) != set(SCHEMA55_TABLE_HASHES) - {"schema_migrations"} or any(type(value) is not int or value < 0 for value in journal["counts"].values()):
                raise ValueError()
            if journal["provenance"] not in {"", "host_declared"} or not isinstance(journal["host_quiescence_ref"], str) or len(journal["host_quiescence_ref"]) > 256 or not isinstance(journal["host_stopped_run_ids"], list) or len(journal["host_stopped_run_ids"]) > 64:
                raise ValueError()
        except _Problem:
            raise
        except (ValueError, TypeError, KeyError):
            raise _Problem("purge_journal_invalid", "The minimal native intent journal is invalid or unsupported.", "Preserve it and inspect native recovery state; never replace it with an inferred success.", status="blocked") from None
        self.journal = journal
        self._project_journal()

    def _project_journal(self) -> None:
        if self.journal is None:
            return
        stage = self.journal["stage"]
        self.result.update(deletion_state=stage, schema_version=55,
            prepared_fingerprint=self.journal["prepared_fingerprint"],
            fingerprint=self.journal["prepared_fingerprint"],
            project_effect_state="applied" if stage in {"ledger_deleted", "scrubbed"} else "unknown" if stage == "deleting" else "none")

    def _write_journal(self, value: dict) -> None:
        if not self.journal_directory.exists():
            self.journal_directory.mkdir(mode=0o700)
            _fsync_directory(self.database.parent)
        _safe_path(self.journal_directory, directory=True, private=True)
        _fsync_directory(self.journal_directory)
        if self.journal_path.exists() or self.journal_path.is_symlink():
            _read_regular(self.journal_path, private=True)
        descriptor, temporary = tempfile.mkstemp(prefix=self.args.deletion_id + ".", suffix=".tmp", dir=self.journal_directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_encoded(value) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            _safe_path(self.journal_directory, directory=True, private=True)
            os.replace(temporary, self.journal_path)
            self.result["journal_changed"] = True
            try:
                _fsync_directory(self.journal_directory)
            except BaseException:
                # Publishing the name happened even if its crash durability
                # could not be acknowledged. Do not report unchanged/none.
                self.result["deletion_state"] = value["stage"]
                if value["stage"] == "deleting" and self.result["project_effect_state"] != "applied":
                    self.result["project_effect_state"] = "unknown"
                raise
            self.journal = value
            self._project_journal()
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _stage(self, stage: str, **extra: object) -> None:
        self._write_journal({**self.journal, "stage": stage, "updated_at": _now(), **extra})

    def _observe(self, inventory: dict) -> None:
        self.result.update(project_present=inventory["project_present"], schema_version=55,
            current_fingerprint=inventory["fingerprint"], counts=inventory["counts"])
        if self.journal is None:
            self.result.update(fingerprint=inventory["fingerprint"], deletion_state="unprepared" if inventory["project_present"] else "absent")
            if not inventory["project_present"]:
                self.result["project_effect_state"] = "unknown"

    def _validate_target(self, inventory: dict) -> None:
        if self.journal is None:
            return
        if inventory["project_present"]:
            if self.journal["stage"] in {"ledger_deleted", "scrubbed"} or inventory["project_identity"] != self.journal["project_identity"]:
                raise _Problem("purge_project_recreated", "The target was recreated or no longer has the prepared project identity.", "Preserve this intent and inspect the new project; do not scrub or delete it as recovery.", status="blocked")
            if inventory["fingerprint"] != self.journal["prepared_fingerprint"]:
                raise _Problem("purge_preparation_stale", "The target inventory changed after preparation.", "Inspect original/current fingerprints and create a new explicit native preparation ID; the approved scope was not rebased.")
        elif any(inventory["counts"].values()):
            raise _Problem("purge_remaining_records", "The project row is absent but owned project records remain.", "Inspect integrity and recover the original intent; absence of projects alone is not completion.", status="blocked")

    def _checkpoint_wal(self, connection: sqlite3.Connection) -> None:
        self._assert_identity()
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is None or result[0] != 0 or (result[1] >= 0 and result[2] != result[1]):
            raise _Problem("purge_scrub_busy", "WAL truncation could not complete.", "Close the remaining ledger readers/writers and reconcile this same native intent.", status="blocked")
        wal = self.database.with_name(self.database.name + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise _Problem("purge_scrub_busy", "WAL content remains after checkpoint.", "Close ledger readers/writers and reconcile before reporting deletion complete.", status="blocked")

    def _verify_absence(self, connection: sqlite3.Connection, columns: dict) -> dict:
        self._assert_identity()
        inventory = _inventory(connection, columns, self.args.project_id)
        self._observe(inventory)
        if inventory["project_present"] or any(inventory["counts"].values()):
            raise _Problem("purge_project_recreated", "The target is present during deletion recovery.", "Stop recovery and inspect the recreated or remaining project; no further destructive SQL is permitted.", status="blocked")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None or [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise _Problem("purge_integrity_failed", "Post-deletion integrity could not be established.", "Preserve the minimal journal and inspect ledger integrity before claiming completion.", status="blocked")
        return inventory

    def _scrub(self, connection: sqlite3.Connection, columns: dict) -> None:
        self._verify_absence(connection, columns)
        # A durable deleting intent plus verified complete absence supports
        # recovery, without pretending a lost response proved no earlier effect.
        if self.journal["stage"] == "deleting":
            self._stage("ledger_deleted")
        self.result["project_effect_state"] = "applied"
        if self.journal["stage"] != "scrubbed":
            self._checkpoint_wal(connection)
            self._assert_identity()
            connection.execute("VACUUM")
            self._checkpoint_wal(connection)
            self._verify_absence(connection, columns)
            self._stage("scrubbed")
        else:
            self._checkpoint_wal(connection)
            self._verify_absence(connection, columns)

    def _delete(self, connection: sqlite3.Connection, columns: dict, inventory: dict) -> None:
        if self.journal is None:
            raise _Problem("purge_unprepared", "Delete requires an existing prepared native intent.", "Prepare and inspect this exact project/deletion ID before confirming deletion.")
        if self.args.expected_fingerprint != self.journal["prepared_fingerprint"]:
            raise _Problem("purge_fingerprint_conflict", "The supplied fingerprint differs from the immutable preparation.", "Inspect this intent and use its original prepared_fingerprint; do not substitute the current fingerprint.")
        self._validate_target(inventory)
        if not inventory["project_present"]:
            if not set(self.args.host_stopped_run_id) <= set(self.journal["host_stopped_run_ids"]):
                raise _Problem("host_run_declaration_stale", "A replay cannot add a new host-stopped execution to deleted inventory.", "Use the original declaration recorded with this prepared intent; inspect current state before changing scope.")
            if self.journal["stage"] == "prepared":
                raise _Problem("purge_absence_unattributed", "The prepared target disappeared before this intent began deletion.", "Inspect the actual deletion owner; this request has no committed destructive intent.", status="blocked")
            self._scrub(connection, columns)
            return
        all_runs = {row[0] for row in connection.execute("SELECT run_id FROM implementation_runs WHERE project_id = ?", (self.args.project_id,))}
        host_stopped = set(self.args.host_stopped_run_id)
        if not host_stopped <= all_runs:
            raise _Problem("host_run_declaration_stale", "A host-stopped run ID does not belong to this current project inventory.", "Inspect actual owned executions; never attest a missing or another project's run.")
        blockers = _blockers(connection, self.args.project_id, host_stopped)
        self.result["blockers"] = blockers
        if blockers:
            raise _Problem("purge_external_activity_blocked", "External work is still active or lacks supported terminal proof.", "Resolve the exact listed owner/command/run before native deletion; missing provider availability cannot waive it.", status="blocked")
        _fsync_directory(self.database.parent)
        _fsync_directory(self.journal_directory)
        connection.execute("PRAGMA secure_delete = ON")
        secure_delete = connection.execute("PRAGMA secure_delete").fetchone()
        if secure_delete is None or secure_delete[0] != 1:
            raise _Problem("purge_secure_delete_unavailable", "SQLite secure_delete=ON could not be established.", "Use a separately qualified SQLite/native platform before deleting project data.", status="blocked")
        connection.execute("BEGIN IMMEDIATE")
        try:
            self._assert_identity()
            _validate_schema(connection)
            fresh = _inventory(connection, columns, self.args.project_id)
            self._validate_target(fresh)
            if not fresh["project_present"]:
                raise _Problem("purge_target_changed", "The target changed during native preflight.", "Inspect the current ledger and original intent; no deletion was performed.", status="blocked")
            blockers = _blockers(connection, self.args.project_id, host_stopped)
            self.result["blockers"] = blockers
            if blockers:
                raise _Problem("purge_external_activity_blocked", "External activity changed during native preflight.", "Resolve the listed activities and inspect this same intent before retrying.", status="blocked")
            self._stage("deleting", host_quiescence_ref=self.args.host_quiescence_ref,
                host_stopped_run_ids=sorted(host_stopped), provenance="host_declared")
            _delete_rows(connection, columns, self.args.project_id)
            self._verify_absence(connection, columns)
            connection.commit()
            # Mark knowledge before a journal publication can fail.
            self.result.update(project_effect_state="applied", deletion_state="ledger_deleted")
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
                # An observation inside rolled-back destructive SQL is not a
                # current durable absence observation.
                self.result.update(project_present=None, current_fingerprint="")
            raise
        self._stage("ledger_deleted")
        self._scrub(connection, columns)

    def execute(self) -> dict:
        self._validate_arguments()
        self._select_database()
        with acquire_runtime_ownership(self.database) as lease:
            self._assert_identity()
            self._read_journal()
            self._validate_operation_arguments()
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=1,
                                         isolation_level=None)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA trusted_schema = OFF")
                lease.assert_resource(self.database)
                self._assert_identity()
                connection.execute("BEGIN")
                try:
                    columns = _validate_schema(connection)
                    inventory = _inventory(connection, columns, self.args.project_id)
                    self._observe(inventory)
                    if not inventory["project_present"] and any(inventory["counts"].values()):
                        if self.journal is None:
                            self.result.update(deletion_state="unknown", project_effect_state="unknown")
                        raise _Problem("purge_remaining_records", "The project row is absent but owned project records remain.", "Inspect original project ownership and ledger integrity; no project identity or successful cleanup was invented.", status="blocked")
                    blockers = _blockers(connection, self.args.project_id, set())
                    self.result["blockers"] = blockers
                finally:
                    connection.rollback()
                operation = self.args.purge_operation
                if operation == "prepare" and self.journal is None and inventory["project_present"]:
                    _fsync_directory(self.database.parent)
                    self._write_journal({"contract": CONTRACT, "deletion_id": self.args.deletion_id,
                        "project_id": self.args.project_id, "database_identity": self.database_identity,
                        "config_identity": self.config_identity, "schema_version": 55,
                        "schema_fingerprint": _digest(SCHEMA55_TABLE_HASHES),
                        "prepared_fingerprint": inventory["fingerprint"], "project_identity": inventory["project_identity"],
                        "counts": inventory["counts"], "stage": "prepared", "created_at": _now(), "updated_at": _now(),
                        "host_quiescence_ref": "", "host_stopped_run_ids": [], "provenance": ""})
                elif operation == "delete":
                    self._delete(connection, columns, inventory)
                elif self.journal is not None:
                    if self.args.expected_fingerprint and self.args.expected_fingerprint != self.journal["prepared_fingerprint"]:
                        raise _Problem("purge_fingerprint_conflict", "Recovery fingerprint differs from the original preparation.", "Inspect and bind recovery to the immutable prepared fingerprint.")
                    self._validate_target(inventory)
                    if not inventory["project_present"] and self.journal["stage"] in {"deleting", "ledger_deleted", "scrubbed"}:
                        if operation == "reconcile":
                            _fsync_directory(self.journal_directory)
                            self._scrub(connection, columns)
                        elif self.journal["stage"] == "deleting":
                            self.result["project_effect_state"] = "applied"
                            self.result["deletion_state"] = "ledger_deleted"
                    elif not inventory["project_present"]:
                        raise _Problem("purge_absence_unattributed", "The target is absent without a committed deletion intent for this request.", "Inspect the actual deletion owner; do not invent a successful request receipt.", status="blocked")
                if self.args.acknowledge_host_cleanup:
                    if self.journal is None:
                        self.result["next_action"] = "Target absence is observable; this missing journal cannot attest the earlier request."
                    elif self.journal["stage"] != "scrubbed":
                        raise _Problem("purge_ack_before_scrub", "Native cleanup cannot be acknowledged before verified Flow scrub.", "Reconcile Flow deletion and scrub before acknowledging the host's local cleanup.", status="blocked")
                    else:
                        self._verify_absence(connection, columns)
                        _read_regular(self.journal_path, private=True)
                        self.journal_path.unlink()
                        self.result["journal_changed"] = True
                        _fsync_directory(self.journal_directory)
                        self.result.update(journal_changed=True, deletion_state="acknowledged", project_effect_state="applied")
                self.result["status"] = "success"
                if self.result["deletion_state"] in {"scrubbed", "acknowledged"}:
                    self.result["next_action"] = "Flow deletion and scrub are verified. Complete owned native chat/session cleanup and acknowledge it per ledger; no Noxi cleanup is inferred."
                elif self.result["deletion_state"] in {"deleting", "ledger_deleted"}:
                    self.result["next_action"] = "Inspect/reconcile this exact intent; use delete with original confirmation only if original target data remain after rollback."
                elif self.journal is not None:
                    self.result["next_action"] = "Inspect the immutable preparation and blockers; stop actual owned workers before an explicit confirmed delete."
                else:
                    self.result["next_action"] = "No request journal exists. Target presence/absence does not prove an earlier deletion request succeeded."
                self._assert_identity()
        return self.result


def run_project_purge(args: Any) -> tuple[dict, int]:
    """Produce one safe JSON-ready result for the native CLI invocation."""
    gateway = _Gateway(args)
    try:
        result = gateway.execute()
    except _Problem as exc:
        result = gateway.result
        result.update(status=exc.status, diagnostics=[{"code": exc.code, "message": exc.message, "resolution": exc.resolution}],
                      next_action=exc.resolution)
    except RuntimeOwnershipError as exc:
        result = gateway.result
        result.update(status="blocked", diagnostics=[{"code": exc.code,
            "message": "The selected ledger ownership could not be acquired safely.",
            "resolution": "Stop the actual owning Flow process and prevent respawn, or select the correct owned ledger; never unlink an ownership lock to bypass it."}],
            next_action="Have the native owner stop this ledger runtime, then inspect this same intent.")
    except Exception:
        # Never expose YAML/parser/SQL text, project contents or provider secrets.
        result = gateway.result
        result.update(status="failed", diagnostics=[{"code": "native_purge_failed",
            "message": "Native project management could not complete its current stage.",
            "resolution": "Inspect/reconcile the same deletion ID and selected ledger; a failed response is not proof of no effect."}],
            next_action="Inspect/reconcile this same native intent before any destructive retry.")
    return result, _EXIT_CODES[result["status"]]
