"""Provider-neutral handover and ledger projection views."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain import HandoverDraft
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.ports import ExecutionRunRepository


class HandoverService:
    """Creates bounded resume contexts from canonical ledger state."""

    def __init__(self, repository: ExecutionRunRepository, *, recovery=None) -> None:
        self._repository = repository
        self._recovery = recovery

    def create_handover(
        self,
        project_id: str,
        draft: HandoverDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        options = {"recovery_builder": self._recovery.compose} if self._recovery is not None else {}
        return self._repository.create_handover(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
            **options,
        )

    def get_handover(self, project_id: str, handover_id: str) -> Mapping[str, object]:
        return self._repository.handover_state(project_id, handover_id)

    def resume_context(
        self,
        project_id: str,
        *,
        change_id: str = "",
        packet_id: str = "",
        run_id: str = "",
        handover_id: str = "",
    ) -> Mapping[str, object]:
        if self._recovery is not None:
            return self._recovery.resume(
                project_id, change_id=change_id, packet_id=packet_id,
                run_id=run_id, handover_id=handover_id,
            )
        return self._repository.resume_context(
            project_id, change_id=change_id, packet_id=packet_id, run_id=run_id
        )

    def ledger_projection(
        self,
        project_id: str,
        *,
        projection_kind: str = "lifecycle",
    ) -> Mapping[str, object]:
        return self._repository.ledger_projection(project_id, projection_kind=projection_kind)


class ExternalRecoveryProjection:
    """Compose frozen external recovery from existing, coherently read authorities.

    Capture is called by the repository inside its write transaction. Current
    resume is explicitly read-only; stored handovers are never enriched on get.
    """

    def __init__(self, ledger, *, snapshot, external_work, limit: int = 10) -> None:
        self._ledger = ledger
        self._snapshot = snapshot
        self._external_work = external_work
        self._limit = limit

    def compose(self, context: Mapping[str, object]) -> Mapping[str, object]:
        value = dict(context)
        project_id = str(context["project_id"])
        objective = context["objective"]
        change_id = str(objective.get("change_id") or "")
        packet_id = str(objective.get("packet_id") or "")
        if packet_id and not change_id:
            change_id = next((str(c["change_id"]) for c in self._ledger.list_changes(project_id)
                              if any(p["packet_id"] == packet_id for p in c.get("packets", []))), "")
        # Provider run continuity retains its established projection. Only an
        # explicitly selected external packet receives the external contract.
        if not packet_id or not change_id:
            return value
        state = self._ledger.external_work_state(project_id, change_id, packet_id)
        if state["consumption_mode"] != "external_agent":
            return value
        snapshot = self._snapshot.snapshot(project_id, focus_kind="packet", focus_ref=packet_id, limit=self._limit)
        value["provider_run_context"] = {
            "applicability": "not_applicable_to_external_execution",
            "run_count": len(value.get("runs", [])),
            "detail_route": {"tool": "fow_handover", "arguments": {
                "project_id": project_id, "operation": "resume_context", "change_id": change_id}},
        }
        # Legacy resume scans all runs in the change. Those run steps must not
        # become instructions for a selected external packet (or its siblings).
        value["runs"] = []
        value["task_views"] = []
        value["blockers"] = snapshot["blockers"]
        value["next_action"] = snapshot["next_gate"]
        todo = self._external_work.todo(project_id, change_id, packet_id)
        validation = self._external_work.validation(project_id, change_id, packet_id)
        structural = validation.get("validation") or validation
        plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id) or {}
        rows = list(todo.get("todos", []))
        reports_by_key = {r["report_key"]: r for r in state["reports"]}
        selected = []
        for row in rows:
            report = reports_by_key.get(row.get("report_key"))
            if report is not None:
                selected.append({
                    "unit_key": row["unit_key"], "unit_status": row["status"],
                    "report_key": report["report_key"], "outcome": report["payload"]["outcome"],
                    "source_revision": report["payload"]["source_revision"],
                    "summary": report["payload"]["summary"],
                    "unresolved": report["payload"]["unresolved"][:self._limit],
                    "unresolved_total": len(report["payload"]["unresolved"]),
                    "evidence_authority": "external_agent_report",
                })
        deferred = list(todo.get("deferred_verification", []))
        artifacts = list(self._ledger.packet_artifact_references(project_id, packet_id, limit=self._limit + 1))
        call = lambda tool, **args: {"tool": tool, "arguments": {"project_id": project_id, **args}}
        routes = {
            "current_snapshot": call("fow_handover", operation="project_state_snapshot", focus_kind="packet", focus_ref=packet_id),
            "work_plan": call("fow_packet_inspect", packet_id=packet_id, view="units", detail_level="audit", offset=0, limit=self._limit),
            "todo": call("fow_external_work", change_id=change_id, packet_id=packet_id, operation="todo"),
            "validation": call("fow_external_work", change_id=change_id, packet_id=packet_id, operation="validation"),
            "evidence": call("fow_traceability", detail_level="audit", offset=0, limit=self._limit),
            "continuation": call("fow_bootstrap", operation="guidance", actor="recovery-reader"),
        }
        if artifacts:
            routes["artifacts"] = call("fow_get_artifacts", generation_id=artifacts[0]["generation_id"],
                                       artifact_kind="implementation_plan", include_content=False)
        value["recovery"] = {
            "contract": "flower.external-recovery.v1",
            "project_id": project_id, "change_id": change_id, "packet_id": packet_id,
            "source_ledger_version": context["source_ledger_version"],
            "consumption_mode": "external_agent",
            "authority": {"spec_revision": structural.get("spec_revision"),
                          "plan_revision": structural.get("plan_revision", plan.get("plan_revision")),
                          "authority_fingerprint": structural.get("authority_fingerprint", todo.get("authority_fingerprint"))},
            "plan": {"work_plan_id": plan.get("work_plan_id"), "status": plan.get("status"),
                     "unit_count": len(plan.get("units", []))},
            "readiness": snapshot["active_work"].get("packet", {}),
            "next_gate": snapshot["next_gate"],
            "external_gate": todo.get("next_gate"),
            "todo_status": todo.get("status"), "todo_reason": todo.get("reason", ""),
            "current_unit": ({k: todo["current_unit"].get(k) for k in ("unit_key", "unit_number", "status", "dependencies_pending")}
                             if todo.get("current_unit") else None),
            "units": [{k: row.get(k) for k in ("unit_key", "unit_number", "status", "report_key", "dependencies_pending")}
                      for row in rows[:self._limit]],
            "selected_reports": selected[:self._limit],
            "artifacts": artifacts[:self._limit],
            "deferred_verification": deferred[:self._limit],
            "bounds": {"limit": self._limit, "unit_total": len(rows), "report_total": len(selected),
                       "deferred_total": len(deferred),
                       "more_artifacts": len(artifacts) > self._limit,
                       "full_details": "Use the exact public calls below; this frozen recovery block is bounded."},
            "acceptance": "not_inferred", "recovery_calls": routes,
            "historical_boundary": "Frozen at capture. Resume with handover_id to compare current authority; get_handover never refreshes history.",
            "offline_boundary": "Execute only the issued complete Markdown artifact offline; reconnect and report with its original revisions and fingerprint. Stale reports remain history.",
        }
        return value

    def resume(self, project_id: str, *, change_id: str = "", packet_id: str = "",
               run_id: str = "", handover_id: str = "") -> Mapping[str, object]:
        with self._ledger.consistent_read():
            historical = self._ledger.handover_state(project_id, handover_id) if handover_id else None
            if historical is not None:
                objective = historical["payload"]["objective"]
                requested = {"change_id": change_id, "packet_id": packet_id, "run_id": run_id}
                for field, supplied in requested.items():
                    original = str(objective.get(field) or "")
                    if supplied and supplied != original:
                        raise ValueError(f"{field} conflicts with the selected historical handover")
                change_id, packet_id, run_id = (str(objective.get(k) or "") for k in requested)
            context = self.compose(self._ledger.resume_context(
                project_id, change_id=change_id, packet_id=packet_id, run_id=run_id))
            if historical is not None:
                frozen = historical["payload"].get("recovery") or {}
                current = context.get("recovery") or {}
                before, after = frozen.get("authority"), current.get("authority")
                context["historical_comparison"] = {
                    "handover_id": handover_id,
                    "state": "legacy_without_recovery" if not frozen else "current" if before == after else "stale",
                    "frozen_authority": before, "current_authority": after,
                    "frozen_ledger_version": historical["payload"]["source_ledger_version"],
                    "current_ledger_version": context["source_ledger_version"],
                    "outcomes_may_have_changed": historical["payload"]["source_ledger_version"] != context["source_ledger_version"],
                    "historical_payload_unchanged": True,
                }
            return context
