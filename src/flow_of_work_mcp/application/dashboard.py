"""Bounded browser observations over the canonical runtime services."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json

from flow_of_work_mcp.application.dashboard_markdown import limited_reader, markdown_reader
from flow_of_work_mcp.application.milestone_traceability import REQUIREMENT_LEDGER_VERSION_NAMESPACE
from flow_of_work_mcp.application.roadmap_markdown import render_requirement
from flow_of_work_mcp.core.domain.change_control import validate_milestone_id, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import validate_project_id, validate_requirement_id
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.markdown_adapter import render_structured


SECTIONS = frozenset({"overview", "roadmap", "packets", "verification", "architecture", "evidence"})
VERIFICATION_CHANNELS = frozenset({"campaign", "verification", "external_report", "repository_review"})
_EVIDENCE_CONTENT_KEYS = {"verification": "metadata", "external_report": "report", "repository_review": "repository_review"}
MAXIMUM_EVIDENCE_BYTES = 2 * 1024 * 1024


class DashboardDocumentNotFound(LookupError):
    """A valid selector does not resolve in the selected project."""


class DashboardDocumentTooLarge(ValueError):
    """The complete document cannot fit the dashboard response."""


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


def _bounded_document(result: dict[str, object], *, size_error: ValueError) -> dict[str, object]:
    if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
        raise size_error
    if result["content_type"] == "text/markdown":
        result["reader"] = markdown_reader(result["content"])
        if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
            result["reader"] = limited_reader("reader_response_limit")
            if _evidence_response_bytes(result) > MAXIMUM_EVIDENCE_BYTES:
                del result["reader"]
    return result


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

    def project(self, project_id: str, section: str = "overview", *, offset: int = 0, limit: int = 25,
                channel: str = "campaign", scope_id: str = "") -> dict[str, object]:
        _pagination(offset, limit)
        project_id = validate_project_id(project_id)
        if section not in SECTIONS:
            raise ValueError("unsupported dashboard section")
        if not isinstance(channel, str) or channel not in VERIFICATION_CHANNELS or not isinstance(scope_id, str):
            raise ValueError("unsupported dashboard verification channel or scope")
        if channel != "campaign" and section != "verification":
            raise ValueError("verification channel requires the verification section")
        if scope_id:
            if section == "verification":
                if channel == "campaign":
                    raise ValueError("campaign listing does not accept a requirement or packet scope")
                scope_id = (validate_requirement_id(scope_id) if channel == "verification"
                            else validate_packet_id(scope_id))
            elif section == "packets":
                scope_id = validate_packet_id(scope_id)
            elif section == "roadmap":
                scope_id = validate_milestone_id(scope_id)
            else:
                raise ValueError("scope requires the verification, packets or roadmap section")
            if section != "verification" and offset:
                raise ValueError("focused acceptance context does not accept a page offset")
        with self._ledger.consistent_read():
            project = self._ledger.dashboard_project(project_id)
            if section == "architecture":
                projection = self._runtime.architecture.call(project_id, "inspect", payload={"offset": offset, "limit": limit})
                items = projection["items"]
                total = projection["total"]
                summary = {key: value for key, value in projection.items()
                           if key not in {"items", "count", "offset", "limit", "total", "next_offset", "complete"}}
            elif section == "verification":
                page = self._ledger.dashboard_verification_items(project_id, channel=channel, scope_id=scope_id,
                                                                  offset=offset, limit=limit)
                items, total = page["items"], page["total"]
                summary = {"evidence_channels": page["counts"], "channel": channel, "scope_id": scope_id}
                if channel == "campaign":
                    items = [self._campaign(project_id, row, limit) for row in items]
            elif scope_id:
                selected = {"packet_id" if section == "packets" else "milestone_id": scope_id}
                context = self._runtime.project_state_snapshot.acceptance_context(
                    project_id, **selected, limit=limit)
                items, total = [], 0
                summary = {"acceptance_context": context}
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
            return {"project": project, "section": section,
                    "source_ledger_version": self._ledger.ledger_version(project_id),
                    "source_ledger_version_namespace": REQUIREMENT_LEDGER_VERSION_NAMESPACE,
                    "observed_at": _observed_at(), "coherent_read": True,
                    "items": [_bounded_record(row, limit) for row in items],
                    "summary": _bounded_record(summary, limit),
                    "bounds": _bounds(total, offset, len(items), limit)}

    def _packet(self, project_id: str, row: Mapping[str, object], limit: int) -> dict[str, object]:
        ids = (project_id, row["change_id"], row["packet_id"])
        validation = self._runtime.external_work.validation(*ids, detail="full")
        # Full validation keeps the immutable reports readable when current
        # authority cannot be resolved. In that case TODO cannot resolve it either.
        validation_projection = validation.get("validation")
        todo = self._runtime.external_work.todo(*ids) if validation_projection is not None else validation
        units = list(todo.get("todos", []))
        plan = self._ledger.packet_work_plan_state(*ids)
        proof = self._ledger.dashboard_packet_requirement_evidence(project_id, row["packet_id"], limit=limit)
        history = [
            {key: record.get(key) for key in ("report_identity", "report_key", "unit_key", "spec_revision", "plan_revision",
                "authority_fingerprint", "source_revision", "outcome", "provenance", "currentness")}
            for record in validation["report_history"][:min(limit, 5)]
        ]
        history_total = validation["report_history_page"]["total"]
        return {**row, "plan_revision": (plan or {}).get("plan_revision", 0),
                "consumption_mode": todo.get("consumption_mode", validation.get("consumption_mode", "")),
                "validation": ({key: validation_projection.get(key) for key in (
                    "contract_version", "consumer_scope", "status", "authority_fingerprint",
                    "spec_revision", "plan_revision", "next_gap")} if validation_projection is not None else None),
                "execution_allowed": todo.get("execution_allowed", validation.get("execution_allowed", False)),
                "next_gate": todo.get("next_gate", validation.get("next_gate")),
                "todo_status": todo.get("status"), "todo_reason": todo.get("reason", ""),
                "reported_units": ({"completed": sum(unit["status"] == "complete" for unit in units),
                                    "total": len(units), "provenance": "external_agent_report"}
                                   if "todos" in todo else None),
                "units": [{key: unit[key] for key in ("unit_key", "unit_number", "status", "report_key", "dependencies_pending", "historical_outcome")
                           if key in unit}
                          for unit in units[:limit]],
                "units_bounds": _bounds(len(units), 0, min(len(units), limit), limit),
                "repository_review": todo.get("repository_review", validation.get("repository_review")),
                "report_history": history, "report_history_bounds": _bounds(history_total, 0, len(history), limit),
                "requirement_evidence": proof["items"],
                "requirement_evidence_bounds": _bounds(proof["total"], 0, len(proof["items"]), limit),
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

    def requirement_document(self, project_id: str, scope: str, scope_id: str = "") -> dict[str, object]:
        project_id = validate_project_id(project_id)
        if scope == "requirement":
            scope_id = validate_requirement_id(scope_id)
        elif scope == "milestone":
            scope_id = validate_milestone_id(scope_id)
        elif scope != "project" or scope_id:
            raise ValueError("unsupported dashboard requirement scope")

        with self._ledger.consistent_read():
            project = self._ledger.dashboard_project(project_id)
            ledger_version = self._ledger.ledger_version(project_id)
            requirement_ids = None
            provenance = {"project_id": project_id, "scope": scope, "source_ledger_version": ledger_version,
                          "source_ledger_version_namespace": REQUIREMENT_LEDGER_VERSION_NAMESPACE}
            if scope == "requirement":
                requirement_ids = (scope_id,)
                title = f"Requirement {scope_id}"
                provenance["requirement_id"] = scope_id
            elif scope == "milestone":
                requirement_ids = self._ledger.dashboard_milestone_requirements(project_id, scope_id)
                if requirement_ids is None:
                    raise DashboardDocumentNotFound
                title = f"Requirements realized by {scope_id}"
                provenance.update(milestone_id=scope_id, membership_source="milestone.requirement_ids",
                                  body_basis="Current requirement revisions observed in this read")
            else:
                title = "Project requirements catalogue"

            parts = [f"# {title}", render_structured(provenance)]
            pins = []
            body_bytes = sum(len(part.encode("utf-8")) for part in parts)
            for row in self._ledger.dashboard_requirement_rows(project_id, requirement_ids):
                body = render_requirement(row, level=2).rstrip()
                body_bytes += len(body.encode("utf-8")) + 2
                if body_bytes > MAXIMUM_EVIDENCE_BYTES:
                    raise DashboardDocumentTooLarge
                parts.append(body)
                pins.append({"requirement_id": row["requirement_id"], "revision": row["current_revision"]})
            if requirement_ids is not None and len(pins) != len(requirement_ids):
                raise DashboardDocumentNotFound
            if not pins:
                parts.append("No requirements recorded for this scope (0 requirements).")
            if scope == "requirement":
                filename = f"flower-{project_id}-{scope_id}-r{pins[0]['revision']}.md"
            elif scope == "milestone":
                filename = f"flower-{project_id}-{scope_id}-requirements-ledger-{ledger_version}.md"
            else:
                filename = f"flower-{project_id}-requirements-ledger-{ledger_version}.md"
            return self._document(project, kind="requirements", title=title, filename=filename,
                                  content="\n\n".join(parts) + "\n", **provenance,
                                  scope_id=scope_id, requirements=pins)

    @staticmethod
    def _document(project: Mapping[str, object], *, kind: str, title: str, filename: str,
                  content: str, **metadata) -> dict[str, object]:
        return _bounded_document({"project": project, "kind": kind, "title": title, "filename": filename,
                                  "content": content, "content_type": "text/markdown", **metadata},
                                 size_error=DashboardDocumentTooLarge())

    def architecture_history(self, project_id: str, *, offset: int, limit: int) -> dict[str, object]:
        _pagination(offset, limit)
        project_id = validate_project_id(project_id)
        with self._ledger.consistent_read():
            history = self._runtime.architecture.call(project_id, "inspect", payload={
                "kind": "history", "offset": offset, "limit": limit,
            })
            items = [{"revision": row["revision"], "state": row["state"]} for row in history["items"]]
            return {"current_adopted_revision": history["current_adopted_revision"],
                    "items": items, "bounds": _bounds(history["total"], offset, len(items), limit)}

    def architecture_document(self, project_id: str, revision: str | None) -> dict[str, object]:
        project_id = validate_project_id(project_id)
        selected = 0
        if revision is not None:
            if not revision.isascii() or not revision.isdecimal() or len(revision) > 19:
                raise ValueError("dashboard architecture revision must be a positive SQLite integer")
            selected = int(revision)
            if not 1 <= selected < 2**63:
                raise ValueError("dashboard architecture revision must be a positive SQLite integer")
        with self._ledger.consistent_read():
            project = self._ledger.dashboard_project(project_id)
            try:
                exported = self._runtime.architecture.call(project_id, "export", payload={"revision": selected})
            except ChangeControlBlockedError as exc:
                if exc.reason in {"architecture_not_adopted", "architecture_revision_not_found"}:
                    raise DashboardDocumentNotFound from exc
                raise
            exact = exported["revision"]
            return self._document(
                project, kind="architecture", title=f"Architettura · revisione {exact}",
                filename=f"flower-{project_id}-architecture-r{exact}.md",
                content=exported["markdown"], revision=exact, state=exported["state"],
                current_adopted_revision=exported["current_adopted_revision"],
                definition_fingerprint=exported["definition_fingerprint"],
                source_ledger_version=self._ledger.ledger_version(project_id),
            )

    def evidence(self, project_id: str, kind: str, identity: str) -> dict[str, object]:
        project_id = validate_project_id(project_id)
        if kind not in {"artifact", "handover", *_EVIDENCE_CONTENT_KEYS}:
            raise ValueError("unsupported dashboard evidence kind")
        if not isinstance(identity, str) or not identity or len(identity) > 128:
            raise ValueError("dashboard evidence identity must contain 1 to 128 characters")
        if kind != "handover" and (not identity.isascii() or not identity.isdecimal() or int(identity) < 1):
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
                if kind in _EVIDENCE_CONTENT_KEYS:
                    payload = {**retained, _EVIDENCE_CONTENT_KEYS[kind]: payload}
                content = json.dumps(payload, ensure_ascii=False, indent=2)
                content_type = "application/json"
            result = {"project": project, "kind": kind, "identity": identity,
                      "source_ledger_version": self._ledger.ledger_version(project_id),
                      "observed_at": _observed_at(), "content": content,
                      "content_type": content_type, **retained}
            return _bounded_document(result, size_error=ValueError("dashboard evidence exceeds the 2 MiB read limit"))
