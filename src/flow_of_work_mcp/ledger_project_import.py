"""Transactional import of a validated project image into an owned ledger."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
import json
from pathlib import Path
import sqlite3
from typing import Any

from flow_of_work_mcp.ledger_archive import ArchiveError, _read_only, _SESSION_TABLES
from flow_of_work_mcp.native_project_purge import _Problem, _validate_schema


_ORIGINS = "project_import_origins"
_IDENTITIES = "project_import_identities"
_ORIGINALS = "project_import_originals"
_IMPORT_TABLES = frozenset({_ORIGINS, _IDENTITIES, _ORIGINALS})
_SQLITE_MAX_INTEGER = (1 << 63) - 1
_LOCAL_EVIDENCE_ARRAYS = {
    ("phase_audit_requirements", "evidence_ids_json"),
    ("phase_audit_deltas", "evidence_added_ids_json"),
}
# These are application projections and retained operation results. Provider
# envelopes and user-supplied JSON elsewhere are outside this rewrite boundary.
_PROJECT_PROJECTIONS = {
    "architecture_requests": ("result_json",),
    "assurance_events": ("payload_json",),
    "bootstrap_events": ("payload_json",),
    "bootstraps": ("completion_handoff_json",),
    "campaign_authority_events": ("payload_json",),
    "change_events": ("payload_json",),
    "external_work_requests": ("result_json",),
    "handover_snapshots": ("payload_json",),
    "jobs": ("result_json",),
    "packet_advancement_receipts": ("outcome_json",),
    "packet_executor_requests": ("result_json",),
    "requirement_events": ("payload_json",),
    "run_events": ("payload_json",),
    "semantic_assignment_events": ("payload_json",),
    "semantic_assignments": ("preparation_json", "result_json", "adoption_json"),
}
_PROJECTION_IDENTITIES = {
    "adoption_id": "architecture_adoptions",
    "artifact_id": "generated_artifacts",
    "criterion_identity": "packet_criteria",
    "edge_id": "goal_edges",
    "generation_id": "artifact_generations",
    "grounding_audit_id": "grounding_audits",
    "phase_audit_id": "phase_audits",
    "previous_phase_audit_id": "phase_audits",
    "report_identity": "external_work_reports",
    "validation_audit_id": "validation_audits",
}
_OPAQUE_FIELDS = frozenset({
    "assessment", "diagnostics", "implementation_anchors", "intent_context", "metadata", "observation",
    "output", "provenance", "source_anchor",
})
_DISPATCH_TABLES = (
    "packet_provider_bindings",
    "packet_provider_outbox",
    "test_provider_outbox",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _unsupported(message: str) -> ArchiveError:
    return ArchiveError("archive_import_unsupported", message, 409)


def _next_project_id(target: sqlite3.Connection, source_id: str) -> str:
    if target.execute("SELECT 1 FROM projects WHERE project_id = ?", (source_id,)).fetchone() is None:
        return source_id
    for number in count(2):
        suffix = f"-{number}"
        candidate = source_id[:64 - len(suffix)] + suffix
        if target.execute("SELECT 1 FROM projects WHERE project_id = ?", (candidate,)).fetchone() is None:
            return candidate
    raise AssertionError("project ID search did not terminate")


def _check_execution(source: sqlite3.Connection) -> None:
    for table in _DISPATCH_TABLES:
        if source.execute(f"SELECT 1 FROM {_q(table)} LIMIT 1").fetchone() is not None:
            raise _unsupported("This archive contains provider execution authority. Restore it in a separate database.")
    active = (
        ("jobs", "status IN ('queued','running')"),
        ("semantic_assignments", "state = 'internal_running'"),
        ("implementation_runs", "status = 'running' OR ((external_ref <> '' OR orchestrator_ref <> '') "
                                "AND (status <> 'completed' OR completion_reference = ''))"),
        ("run_steps", "status = 'in_progress'"),
        ("semantic_assignments", "state = 'internal_running'"),
    )
    for table, predicate in active:
        if source.execute(f"SELECT 1 FROM {_q(table)} WHERE {predicate} LIMIT 1").fetchone() is not None:
            raise _unsupported("The project has unfinished execution. Reconcile it before creating a new export.")


@dataclass(frozen=True)
class _Table:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    integer_key: str | None
    foreign_identities: dict[str, str]

    @classmethod
    def discover(cls, source: sqlite3.Connection, columns: dict[str, tuple[str, ...]]) -> dict[str, _Table]:
        keys = {}
        integer_keys = {}
        for table in columns:
            fields = [row for row in source.execute(f"PRAGMA table_info({_q(table)})") if row[5]]
            keys[table] = tuple(row[1] for row in sorted(fields, key=lambda row: row[5]))
            if len(fields) == 1 and fields[0][2].upper() == "INTEGER":
                integer_keys[table] = fields[0][1]
        result = {}
        for table, names in columns.items():
            if table in _SESSION_TABLES or table == "schema_migrations":
                continue
            if not keys[table]:
                raise _unsupported("The archive contains a table without a supported row identity.")
            links = {row[3]: row[2] for row in source.execute(f"PRAGMA foreign_key_list({_q(table)})")
                     if row[2] in integer_keys and row[4] == integer_keys[row[2]]}
            result[table] = cls(table, names, keys[table], integer_keys.get(table), links)
        return result

    def rows(self, source: sqlite3.Connection):
        fields = ",".join(map(_q, self.columns))
        order = ",".join(map(_q, self.key))
        return source.execute(f"SELECT {fields} FROM {_q(self.name)} ORDER BY {order}")

    def insert(self, target: sqlite3.Connection, values: dict) -> None:
        fields = ",".join(map(_q, self.columns))
        placeholders = ",".join("?" for _ in self.columns)
        target.execute(f"INSERT INTO {_q(self.name)} ({fields}) VALUES ({placeholders})",
                       tuple(values[name] for name in self.columns))


class _Mapping:
    def __init__(self, source: sqlite3.Connection, target: sqlite3.Connection, tables: dict[str, _Table],
                 source_project: str, project: str) -> None:
        self.source_project = source_project
        self.project = project
        self.identities: dict[str, dict[int, int]] = {}
        self.source_aliases: dict[str, dict[int, int]] = {}
        if _IDENTITIES in tables:
            for row in tables[_IDENTITIES].rows(source):
                by_kind = self.source_aliases.setdefault(row["identity_kind"], {})
                if by_kind.setdefault(row["source_id"], row["local_id"]) != row["local_id"]:
                    raise _unsupported("An imported identity is ambiguous across archive origins.")
        for table in tables.values():
            if table.integer_key is not None:
                self.identities[table.name] = self._allocate(source, target, table)
        for kind, aliases in self.source_aliases.items():
            physical = self.identities.get(kind, {})
            if any(local_id not in physical or (source_id in physical and source_id != local_id)
                   for source_id, local_id in aliases.items()):
                raise _unsupported("An archived internal identifier is ambiguous or no longer resolves.")

    def _allocate(self, source: sqlite3.Connection, target: sqlite3.Connection, table: _Table) -> dict[int, int]:
        assert table.integer_key is not None
        key = _q(table.integer_key)
        selection = f"SELECT {key} FROM {_q(table.name)}"
        source_ids = [row[0] for row in source.execute(f"{selection} ORDER BY {key}")]
        if not source_ids:
            return {}
        if source_ids[0] <= 0:
            raise _unsupported("The archive contains an unsupported internal identifier.")
        ceiling = target.execute(f"SELECT MAX({key}) FROM {_q(table.name)}").fetchone()[0] or 0
        sequence = target.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table.name,)).fetchone()
        start = max(0, ceiling, source_ids[-1], sequence[0] if sequence else 0,
                    max(self.source_aliases.get(table.name, ()), default=0)) + 1
        if start + len(source_ids) - 1 > _SQLITE_MAX_INTEGER:
            raise _unsupported("There are no safe internal identifiers available for this project.")
        return {source_id: local_id for local_id, source_id in enumerate(source_ids, start)}

    def identity(self, table: str, value: int, *, aliases: bool = False) -> int:
        if type(value) is not int or value <= 0:
            raise _unsupported("The archive contains an unsupported internal identifier.")
        try:
            current = self.identities[table]
            if aliases and value not in current:
                value = self.source_aliases.get(table, {}).get(value, value)
            return current[value]
        except KeyError as exc:
            raise _unsupported("An internal reference does not resolve inside the archived project.") from exc

    def projection(self, table: str, value: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(value, list):
            return [self.projection(table, item, path) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            kind = _projection_identity(table, path, key)
            if kind and type(item) is int and item > 0:
                result[key] = self.identity(kind, item, aliases=True)
            elif key == "project_id" and item == self.source_project:
                result[key] = self.project
            elif key == "artifact_ids" and table == "requirement_events" and not path and isinstance(item, list):
                result[key] = [self.identity("generated_artifacts", item_id, aliases=True) for item_id in item]
            elif key in {"audit_ids", "action_id"} and path[-1:] == ("actions",):
                result[key] = self._action_reference(value, key)
            elif key in _OPAQUE_FIELDS or (table == "campaign_authority_events" and not path and key == "receipt"):
                result[key] = item
            else:
                result[key] = self.projection(table, item, (*path, key))
        return result

    def _action_reference(self, action: dict, key: str) -> Any:
        raw = action[key]
        action_id = action.get("action_id")
        if not isinstance(action_id, str):
            return raw
        namespace, _, rest = action_id.partition(":")
        kind = {"grounding": "grounding_audits", "validation": "validation_audits"}.get(namespace)
        if kind is None:
            return raw
        if key == "audit_ids" and isinstance(raw, list):
            return [self.identity(kind, identity, aliases=True) for identity in raw]
        old, separator, suffix = rest.partition(":")
        if key == "action_id" and old.isdecimal():
            return f"{namespace}:{self.identity(kind, int(old), aliases=True)}{separator}{suffix}"
        return raw


def _projection_identity(table: str, path: tuple[str, ...], key: str) -> str | None:
    if key == "event_id":
        if table == "handover_snapshots" and path == ("change", "events"):
            return "change_events"
        if table == "assurance_events" and path[:1] == ("receipt",):
            return "assurance_events"
        return None
    if key == "audit_id" and table == "requirement_events" and not path:
        return "grounding_audits"
    if key == "latest_audit_id" and path[-1:] == ("repository_review",):
        return "phase_audits"
    if key in {"audit_event_id", "evidence_id"}:
        if ((table == "campaign_authority_events" and path == ("propagation", "propagated"))
                or (table == "requirement_events" and not path)):
            return "verification_evidence" if key == "evidence_id" else "requirement_events"
        return None
    return _PROJECTION_IDENTITIES.get(key)


def _replace_json(table: str, column: str, raw: str, mapping: _Mapping) -> str:
    original = json.loads(raw)
    if (table, column) in _LOCAL_EVIDENCE_ARRAYS:
        if not isinstance(original, list) or any(type(value) is not int for value in original):
            raise _unsupported("An archived phase audit has invalid evidence links.")
        updated = [mapping.identity("verification_evidence", value) for value in original]
    else:
        updated = mapping.projection(table, original)
    return raw if updated == original else _json(updated)


def _remap_row(table: _Table, original: dict, mapping: _Mapping) -> tuple[dict, dict[str, str]]:
    result = original.copy()
    originals = {}
    if "project_id" in result:
        if result["project_id"] != mapping.source_project:
            raise _unsupported("The archived row belongs to a different project.")
        result["project_id"] = mapping.project
    if table.integer_key is not None:
        result[table.integer_key] = mapping.identity(table.name, original[table.integer_key])
    for column, identity_kind in table.foreign_identities.items():
        if original[column] is not None:
            result[column] = mapping.identity(identity_kind, original[column])
    if table.name == _IDENTITIES:
        result["local_id"] = mapping.identity(result["identity_kind"], result["local_id"])
    if table.name == "provider_project_bindings" and result["status"] == "active":
        # Import retains history; the destination operator must establish a
        # binding explicitly before a provider can resolve it as active.
        result["status"] = "imported_inactive"
        originals["status"] = original["status"]
    if table.name == "artifact_mappings" and result["canonical_kind"] == "phase_audit":
        result["canonical_id"] = str(mapping.identity("phase_audits", int(original["canonical_id"])))
        originals["canonical_id"] = original["canonical_id"]
    for column in table.columns:
        if ((table.name, column) in _LOCAL_EVIDENCE_ARRAYS
                or column in _PROJECT_PROJECTIONS.get(table.name, ())):
            raw = original[column]
            if raw:
                result[column] = _replace_json(table.name, column, raw, mapping)
                if result[column] != raw:
                    originals[column] = raw
    return result, originals


def _copy_project(source: sqlite3.Connection, target: sqlite3.Connection, source_columns: dict,
                  source_project: str, project: str, digest: str) -> dict[str, int]:
    source.row_factory = sqlite3.Row
    tables = _Table.discover(source, source_columns)
    mapping = _Mapping(source, target, tables, source_project, project)
    target.execute(f"INSERT INTO {_ORIGINS} (project_id, origin_digest, source_project_id, imported_at) "
                   "VALUES (?, ?, ?, ?)", (project, digest, source_project, datetime.now(timezone.utc).isoformat()))
    for kind, identities in mapping.identities.items():
        target.executemany(f"INSERT INTO {_IDENTITIES} (project_id, origin_digest, identity_kind, source_id, local_id) "
                           "VALUES (?, ?, ?, ?, ?)",
                           ((project, digest, kind, source_id, local_id) for source_id, local_id in identities.items()))
    counts = {}
    for table in tables.values():
        copied = 0
        for row in table.rows(source):
            values, originals = _remap_row(table, dict(row), mapping)
            table.insert(target, values)
            copied += 1
            if originals:
                row_key = _json([row[column] for column in table.key])
                target.executemany(f"INSERT INTO {_ORIGINALS} (project_id, origin_digest, table_name, row_key, "
                                   "column_name, original_value) VALUES (?, ?, ?, ?, ?, ?)",
                                   ((project, digest, table.name, row_key, column, original)
                                    for column, original in originals.items()))
        if copied and table.name not in _IMPORT_TABLES:
            counts[table.name] = copied
    return counts


def import_project_image(database_path: Path, extracted_database: Path, manifest: dict) -> dict:
    """Import an already validated project image during exclusive runtime maintenance."""
    if manifest["kind"] != "project":
        raise ArchiveError("archive_project_required", "Choose a single-project Flower export.")
    source_project = manifest["project_id"]
    digest = manifest["database_sha256"]
    try:
        with closing(_read_only(extracted_database, immutable=True)) as source:
            columns = _validate_schema(source)
            _check_execution(source)
            with closing(sqlite3.connect(database_path.as_uri() + "?mode=rw", uri=True, timeout=2)) as target, target:
                target.execute("PRAGMA foreign_keys = ON")
                target.execute("PRAGMA trusted_schema = OFF")
                target.execute("BEGIN IMMEDIATE")
                target.execute("PRAGMA defer_foreign_keys = ON")
                destination = _validate_schema(target)
                if not _IMPORT_TABLES <= destination.keys() or any(destination.get(name) != fields
                                                                  for name, fields in columns.items()):
                    raise _unsupported("The archive and destination do not have compatible ledger schemas.")
                project = _next_project_id(target, source_project)
                counts = _copy_project(source, target, columns, source_project, project, digest)
                if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise _unsupported("The imported project would contain unresolved ledger relationships.")
        return {"project_id": project, "source_project_id": source_project, "origin_digest": digest, "counts": counts}
    except (_Problem, sqlite3.IntegrityError) as exc:
        raise ArchiveError("archive_import_conflict", "The project could not be added to this database. No changes were saved.", 409) from exc
    except (ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, ArchiveError):
            raise
        raise _unsupported("The archive contains an unsupported project reference.") from exc
    except sqlite3.OperationalError as exc:
        if (getattr(exc, "sqlite_errorcode", 0) & 0xff) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            raise ArchiveError("archive_import_busy", "The destination is busy. Try again when Flower is idle.", 409) from exc
        raise ArchiveError("archive_io_failure", "The project could not be saved. Check the destination database.", 500) from exc
    except sqlite3.DatabaseError as exc:
        raise ArchiveError("archive_io_failure", "The project could not be saved. Check the destination database.", 500) from exc
