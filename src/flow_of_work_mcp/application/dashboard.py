"""Bounded browser observations over the canonical runtime services."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json

from flow_of_work_mcp.application.milestone_traceability import REQUIREMENT_LEDGER_VERSION_NAMESPACE
from flow_of_work_mcp.application.dashboard_markdown import limited_reader, markdown_reader
from flow_of_work_mcp.core.domain.identifiers import validate_project_id


SECTIONS = frozenset({"overview", "roadmap", "packets", "verification", "architecture", "evidence"})
MAXIMUM_EVIDENCE_BYTES = 2 * 1024 * 1024


def _pagination(offset: int, limit: int) -> None:
    """Validate pagination before binding values to SQLite's signed integers."""
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < 2**63:
        raise ValueError("dashboard offset must be a nonnegative SQLite integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
        raise ValueError("dashboard limit must be between 1 and 25")


def _bounds(total: int, offset: int, count: int, limit: int) -> dict[str, object]:
    more = offset + count < total
    return {"offset": offset, "limit": limit, "total": total, "count": count,
            "next_offset": offset + count if more else None, "truncated": offset > 0 or more}


def _bounded_record(value: object, limit: int) -> object:
    """Annotate every nested list that is shortened in the browser projection."""
    if isinstance(value, Mapping):
        result = {}
        for name, item in value.items():
            if isinstance(item, (list, tuple)):
                result[name] = [_bounded_record(child, limit) for child in item[:limit]]
                result[name + "_bounds"] = _bounds(len(item), 0, len(result[name]), limit)
            else:
                result[name] = _bounded_record(item, limit)
        return result
    return value


def _observed_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_response_bytes(result: Mapping[str, object]) -> int:
    """Match the UTF-8 JSON success envelope emitted by the browser adapter."""
    return len(json.dumps({"status": "success", "result": result}, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8"))


class DashboardProjectionService:
    """Derive read-only sections without selecting a chat project or capability lens."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._ledger = runtime.ledger

    def projects(self, *, search: str = "", offset: int = 0, limit: int = 25) -> dict[str, object]:
        _pagination(offset, limit)
        if not isinstance(search, str) or len(search) > 256:
            raise ValueError("dashboard search must be text of at most 256 characters")
        with self._ledger.consistent_read():
            page = self._ledger.dashboard_projects(search=search, offset=offset, limit=limit)
            rows = page["items"]
            bounds = _bounds(page["total"], offset, len(rows), limit)
            return {"projects": rows, "count": len(rows), "total": page["total"],
                    "offset": offset, "limit": limit, "next_offset": bounds["next_offset"],
                    "observed_at": _observed_at()}

    def project(self, project_id: str, section: str = "overview", *, offset: int = 0, limit: int = 25) -> dict[str, object]:
        _pagination(offset, limit)
        project_id = validate_project_id(project_id)
        if section not in SECTIONS:
            raise ValueError("unsupported dashboard section")
        with self._ledger.consistent_read():
            project = self._ledger.dashboard_project(project_id)
            if section == "architecture":
                projection = self._runtime.architecture.call(project_id, "inspect", payload={"offset": offset, "limit": limit})
                items = projection["items"]
                total = projection["total"]
                summary = {key: value for key, value in projection.items()
                           if key not in {"items", "count", "offset", "limit", "total", "next_offset", "complete"}}
            else:
                page = self._ledger.dashboard_items(project_id, section, offset=offset, limit=limit)
                items, total = page["items"], page["total"]
                summary = {}
                if section == "overview":
                    summary = self._runtime.project_state_snapshot.snapshot(project_id, limit=limit)
                    summary = {**summary, "requirements_total": total}
                elif section == "roadmap" and items:
                    progress = self._runtime.milestone_traceability.progress(
                        project_id, milestone_ids=tuple(row["milestone_id"] for row in items))
                    items = progress["milestones"]
                    summary = {key: value for key, value in progress.items()
                               if key not in {"milestones", "criteria", "deferred_obligations"}}
                    summary["scope"] = "visible_milestones"
                elif section == "packets":
                    items = [self._packet(project_id, row, limit) for row in items]
                elif section == "verification":
                    items = [self._campaign(project_id, row, limit) for row in items]
            return {"project": project, "section": section,
                    "source_ledger_version": self._ledger.ledger_version(project_id),
                    "source_ledger_version_namespace": REQUIREMENT_LEDGER_VERSION_NAMESPACE,
                    "observed_at": _observed_at(), "coherent_read": True,
                    "items": [_bounded_record(row, limit) for row in items],
                    "summary": _bounded_record(summary, limit),
                    "bounds": _bounds(total, offset, len(items), limit)}

    def _packet(self, project_id: str, row: Mapping[str, object], limit: int) -> dict[str, object]:
        ids = (project_id, row["change_id"], row["packet_id"])
        validation = self._runtime.external_work.validation(*ids)
        todo = self._runtime.external_work.todo(*ids)
        units = list(todo.get("todos", []))
        plan = self._ledger.packet_work_plan_state(*ids)
        return {**row, "plan_revision": (plan or {}).get("plan_revision", 0),
                "consumption_mode": todo.get("consumption_mode", validation.get("consumption_mode", "")),
                "validation": validation.get("validation"),
                "execution_allowed": validation.get("execution_allowed", False),
                "next_gate": todo.get("next_gate", validation.get("next_gate")),
                "todo_status": todo.get("status"), "todo_reason": todo.get("reason", ""),
                "reported_units": ({"completed": sum(unit["status"] == "complete" for unit in units),
                                    "total": len(units), "provenance": "external_agent_report"}
                                   if "todos" in todo else None),
                "units": [{key: unit.get(key) for key in ("unit_key", "unit_number", "status", "report_key", "dependencies_pending")}
                          for unit in units[:limit]],
                "units_bounds": _bounds(len(units), 0, min(len(units), limit), limit),
                "acceptance": "not_inferred"}

    def _campaign(self, project_id: str, row: Mapping[str, object], limit: int) -> dict[str, object]:
        campaign_id = row["campaign_id"]
        current = self._runtime.campaign_authority.inspect(project_id, campaign_id=campaign_id, view="summary")
        oracles = self._runtime.campaign_authority.inspect(project_id, campaign_id=campaign_id, view="oracles", limit=limit)
        evidence = self._runtime.campaign_authority.inspect(project_id, campaign_id=campaign_id, view="evidence", limit=limit)
        return {**row, **dict(current.get("campaign") or {}),
                "lifecycle_gate": current["lifecycle_gate"],
                "oracles": oracles.get("oracles", []), "oracles_bounds": oracles.get("page", {}),
                "evidence": evidence.get("evidence", []), "evidence_bounds": evidence.get("page", {}),
                "acceptance": "not_inferred"}

    def evidence(self, project_id: str, kind: str, identity: str) -> dict[str, object]:
        project_id = validate_project_id(project_id)
        if kind not in {"artifact", "handover", "verification"}:
            raise ValueError("unsupported dashboard evidence kind")
        if not isinstance(identity, str) or not identity or len(identity) > 128:
            raise ValueError("dashboard evidence identity must contain 1 to 128 characters")
        if kind in {"artifact", "verification"} and (not identity.isascii() or not identity.isdecimal() or int(identity) < 1):
            raise ValueError("dashboard evidence identity must be a positive integer")
        with self._ledger.consistent_read():
            project = self._ledger.dashboard_project(project_id)
            retained = dict(self._ledger.dashboard_retained_evidence(
                project_id, kind, identity, maximum_bytes=MAXIMUM_EVIDENCE_BYTES))
            content = retained.pop("content")
            if kind == "artifact":
                if sha256(content.encode()).hexdigest() != retained["content_sha256"]:
                    raise ValueError("dashboard artifact content does not match its retained digest")
                content_type = "text/markdown"
            else:
                payload = json.loads(content)
                if kind == "verification":
                    payload = {**retained, "metadata": payload}
                content = json.dumps(payload, ensure_ascii=False, indent=2)
                content_type = "application/json"
            result = {"project": project, "kind": kind, "identity": identity,
                      "source_ledger_version": self._ledger.ledger_version(project_id),
                      "observed_at": _observed_at(), "content": content,
                      "content_type": content_type, **retained}
            if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
                raise ValueError("dashboard evidence exceeds the 2 MiB read limit")
            if content_type == "text/markdown":
                result["reader"] = markdown_reader(content)
                if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
                    result["reader"] = limited_reader("reader_response_limit")
                if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
                    del result["reader"]
            return result
