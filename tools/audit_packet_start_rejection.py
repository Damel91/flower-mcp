#!/usr/bin/env python3
"""Read-only retrospective audit of the one supported Flower 0.6.3 path.

This development/owner-recovery utility never imports Flower or replays a tool.
See authorities/contracts/FLOWER-PACKET-START-SOURCE-AUDIT-V1.md. The original
response remains unknown; an owner-declared association is not independently
verified execution provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import zipfile


CONTRACT = "flow.packet-start-source-audit.v1"
SOURCE_COMMIT = "e6e6649bf631ed986217bf758ff3d9d8d389937e"
WHEEL_SHA256 = "dc1716e87c10f5417693edd7ed6656b49da95c7c9e72c27e7a3c9b952f613f20"
_CHANGE_ID = re.compile(r"CHANGE-[0-9]{6}")
_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class AuditRefused(ValueError):
    """A supported audit premise was not established."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditRefused("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise AuditRefused("nonfinite_json_value")


def _package_evidence(wheel: Path, package_root: Path, *, expected_digest: str | None = None) -> str:
    if _sha(wheel.read_bytes()) != (WHEEL_SHA256 if expected_digest is None else expected_digest):
        raise AuditRefused("unsupported_wheel_digest")
    with zipfile.ZipFile(wheel) as archive:
        expected = {}
        for member in archive.infolist():
            if not member.filename.startswith("flow_of_work_mcp/") or member.is_dir():
                continue
            relative = member.filename.removeprefix("flow_of_work_mcp/")
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or relative in expected:
                raise AuditRefused("invalid_wheel_inventory")
            expected[relative] = archive.read(member)
    if not expected or not package_root.is_dir():
        raise AuditRefused("missing_installed_package")
    actual = {
        path.relative_to(package_root).as_posix(): path
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(package_root).parts
    }
    if actual.keys() != expected.keys():
        raise AuditRefused("installed_package_inventory_mismatch")
    inventory = {}
    for relative, contents in expected.items():
        if actual[relative].read_bytes() != contents:
            raise AuditRefused("installed_package_bytes_mismatch")
        inventory[relative] = _sha(contents)
    return _sha(_canonical(inventory))


def _request_evidence(request_json: Path, expected_sha: str,
                      project_id: str, request_id: str) -> tuple[dict, str]:
    data = request_json.read_bytes()
    raw_sha = _sha(data)
    if raw_sha != expected_sha:
        raise AuditRefused("retained_request_digest_mismatch")
    request = json.loads(data, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
        raise AuditRefused("unsupported_request_shape")
    arguments = request["arguments"]
    if request["tool"] != "fow_packet_author" or not isinstance(arguments, dict):
        raise AuditRefused("unsupported_tool")
    if arguments.get("operation") != "start_packet" or arguments.get("purpose") != "implementation":
        raise AuditRefused("unsupported_operation_or_purpose")
    if (not _PROJECT_ID.fullmatch(project_id) or not request_id.strip()
            or request_id != request_id.strip()
            or arguments.get("project_id") != project_id
            or arguments.get("request_id") != request_id):
        raise AuditRefused("original_request_identity_mismatch")
    change_id = arguments.get("change_id")
    if not isinstance(change_id, str) or not change_id.strip() or _CHANGE_ID.fullmatch(change_id.strip()):
        raise AuditRefused("unsupported_change_identity")
    return arguments, raw_sha


def _ledger_evidence(database: Path, project_id: str, request_id: str) -> dict:
    database = database.resolve(strict=True)
    if not database.is_file():
        raise AuditRefused("missing_database")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        if connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] != 55:
            raise AuditRefused("unsupported_database_schema")
        if connection.execute("SELECT 1 FROM projects WHERE project_id = ?", (project_id,)).fetchone() is None:
            raise AuditRefused("original_project_not_found")
        matches = {}
        prefix = request_id + ":"
        for table, field in (("implementation_packets", "packet_request_matches"),
                             ("change_events", "change_event_request_matches")):
            matches[field] = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ? "
                "AND (request_id = ? OR substr(request_id, 1, ?) = ?)",
                (project_id, request_id, len(prefix), prefix),
            ).fetchone()[0]
        if any(matches.values()):
            raise AuditRefused("original_request_has_durable_history")
        return {"project_id": project_id, "database_locator_sha256": _sha(str(database).encode()),
                **matches, "read_only": True}
    finally:
        connection.rollback()
        connection.close()


def assess(*, wheel: Path, package_root: Path, request_json: Path,
           expected_request_sha256: str, project_id: str, request_id: str,
           database: Path, association_reference: str) -> dict:
    """Return a separate source assessment or a refusal; perform no writes.

    The caller must verify that the supplied files/ledger belong to the original
    retained execution. This utility labels that association owner_declared.
    """
    try:
        if not isinstance(association_reference, str) or not association_reference.strip():
            raise AuditRefused("missing_owner_association_reference")
        arguments, raw_sha = _request_evidence(
            request_json, expected_request_sha256, project_id, request_id,
        )
        inventory_sha = _package_evidence(wheel, package_root)
        ledger = _ledger_evidence(database, project_id, request_id)
        return {
            "contract_version": CONTRACT, "status": "assessed",
            "basis": "retrospective_source_audit",
            "original_request": {"tool": "fow_packet_author", "operation": "start_packet",
                                 "project_id": project_id, "request_id": request_id,
                                 "arguments_sha256": _sha(_canonical(arguments))},
            "retained_request_sha256": raw_sha,
            "original_effect_state": "unknown", "historical_result_rewritten": False,
            "recovery_resolution": {"effect_state": "none", "mutation_started": False},
            "producer": {"distribution_version": "0.6.3", "source_commit": SOURCE_COMMIT,
                         "wheel_sha256": WHEEL_SHA256, "package_files_sha256": inventory_sha},
            "ledger": ledger,
            "provenance": {"original_execution_association": "owner_declared",
                           "association_reference": association_reference},
            "limits": ["Retrospective assessment, not an originally emitted receipt.",
                       "Original execution/artifact/ledger association is owner-declared.",
                       "Current absence corroborates the pinned source proof only.",
                       "No conclusion about other requests or uncertain transport outcomes."],
        }
    except AuditRefused as exc:
        reason = str(exc)
    except (OSError, ValueError, TypeError, sqlite3.Error, zipfile.BadZipFile):
        # Do not expose paths, private payloads, arbitrary SQL or parser text.
        reason = "audit_input_or_storage_unverifiable"
    return {"contract_version": CONTRACT, "status": "refused",
            "effect_state": "unknown", "reason": reason}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "package-root", "request-json", "database"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("expected-request-sha256", "project-id", "request-id", "association-reference"):
        parser.add_argument("--" + name, required=True)
    result = assess(**vars(parser.parse_args(argv)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "assessed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
