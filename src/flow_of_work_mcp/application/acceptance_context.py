"""Bounded evidence and acceptance reads over the existing lifecycle checks."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.application.grounding_readiness import live_grounding_readiness
from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
from flow_of_work_mcp.application.milestone_traceability import REQUIREMENT_LEDGER_VERSION_NAMESPACE
from flow_of_work_mcp.core.domain.change_control import validate_milestone_id, validate_packet_id
from flow_of_work_mcp.core.ports import (
    ChangeControlRepository, ConsistentReadScope, GoalGraphRepository, GroundingAuditRepository,
    LedgerVersionReader, RequirementLedger,
)


class AcceptanceContextService:
    """Explain a selected packet or milestone without modifying its records."""

    def __init__(self, *, reads: ConsistentReadScope, changes: ChangeControlRepository,
                 lifecycle: LifecycleControlService, external_work: ExternalWorkService,
                 requirements: RequirementLedger, ledger_versions: LedgerVersionReader,
                 goals: GoalGraphRepository, grounding_audits: GroundingAuditRepository) -> None:
        self._reads = reads
        self._changes = changes
        self._lifecycle = lifecycle
        self._external_work = external_work
        self._requirements = requirements
        self._ledger_versions = ledger_versions
        self._goals = goals
        self._grounding_audits = grounding_audits

    def read(self, project_id: str, *, packet_id: str = "", milestone_id: str = "",
             limit: int = 10, packet_frontier: Mapping[str, object] | None = None,
             goal_graph: Mapping[str, object] | None = None,
             grounding_audits: list[Mapping[str, object]] | None = None) -> Mapping[str, object]:
        if bool(packet_id) == bool(milestone_id):
            raise ValueError("select exactly one packet or milestone for acceptance context")
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        focus_kind = "packet" if packet_id else "milestone"
        focus_ref = validate_packet_id(packet_id) if packet_id else validate_milestone_id(milestone_id)
        with self._reads.consistent_read():
            scope = {"project_id": project_id}
            frontier = None
            if packet_id:
                packet_id = focus_ref
                change_id = self._changes.packet_change_id(project_id, packet_id)
                change = self._changes.change_state(project_id, change_id)
                packet = next(row for row in change["packets"] if row["packet_id"] == packet_id)
                scope.update(change_id=change_id, packet_id=packet_id)
                milestone_id = str(change.get("milestone_id") or "")
                packets = [packet]
                requirement_ids = set(packet.get("requirement_ids") or change.get("requirement_ids", []))
                if self._external_work.mode_for_packet(project_id, packet_id) == "external_agent":
                    frontier = (packet_frontier if packet_frontier is not None else
                                self._external_work.todo(project_id, change_id, packet_id))
                checkpoint = _packet_checkpoint(packet, frontier)
            else:
                milestone_id = focus_ref
                checkpoint = None
                packets = [packet for change in self._changes.list_changes(project_id)
                           if change.get("milestone_id") == milestone_id for packet in change["packets"]
                           if packet["status"] not in {"cancelled", "superseded"}]
            if milestone_id:
                scope["milestone_id"] = milestone_id
                acceptance = self._lifecycle.milestone_acceptance_context(project_id, milestone_id)
                if not packet_id:
                    requirement_ids = set(acceptance["requirement_ids"])
            else:
                acceptance = {"state": "unavailable", "reason": "packet_milestone_not_linked",
                              "recorded_status": "", "blockers": [], "awaited_inputs": [],
                              "external_progress_applies": False}
            progress = acceptance.get("external_progress")
            if progress is not None:
                deferred = [row for row in progress.get("deferred_obligations", [])
                            if not packet_id or row.get("packet_id") == packet_id]
            else:
                deferred = list((frontier or {}).get("deferred_verification", []))
            selected_requirements = sorted(requirement_ids)
            goal_ids = sorted({str(goal) for packet in packets for goal in packet.get("goal_ids", [])})
            result = {
                "scope": scope,
                "packet_checkpoint": checkpoint,
                "milestone_acceptance": _acceptance_summary(acceptance, limit),
                "requirements": self._requirement_evidence(project_id, selected_requirements[:limit]),
                "goal_grounding": self._goal_grounding(project_id, goal_ids[:limit], goal_graph, grounding_audits),
                "deferred_obligations": [_deferred_summary(row, applies=progress is not None)
                                         for row in deferred[:limit]],
                "counts": {"requirements": len(selected_requirements), "goal_grounding": len(goal_ids),
                           "deferred_obligations": len(deferred)},
                "detail_reference": {"tool": "fow_handover", "arguments": {
                    "project_id": project_id, "operation": "project_state_snapshot",
                    "focus_kind": focus_kind, "focus_ref": focus_ref,
                }},
                "source_ledger_version": self._ledger_versions.ledger_version(project_id),
                "source_ledger_version_namespace": REQUIREMENT_LEDGER_VERSION_NAMESPACE,
            }
            result["truncated"] = (
                any(total > limit for total in result["counts"].values())
                or result["milestone_acceptance"]["truncated"]
                or any(row.get("direct_evidence_truncated") for row in result["requirements"])
                or any(row["title_truncated"] for row in result["goal_grounding"])
                or any(row["statement_truncated"] for row in result["deferred_obligations"])
            )
            return result

    def _requirement_evidence(self, project_id: str, requirement_ids: list[str]) -> list[dict]:
        rows = self._requirements.scoped_requirement_evidence(project_id, tuple(requirement_ids), limit=3)
        by_id = {row["requirement_id"]: row for row in rows}
        result = []
        for requirement_id in requirement_ids:
            row = by_id.get(requirement_id)
            if row is None:
                result.append({"requirement_id": requirement_id, "lifecycle_status": "unavailable",
                               "direct_evidence_state": "unavailable", "direct_evidence": []})
                continue
            proof = [{**item, "provenance": "recorded_verification_evidence", "currentness": "as_recorded",
                      "detail_reference": {"tool": "fow_traceability", "arguments": {
                          "project_id": project_id, "evidence_id": item["evidence_id"], "detail_level": "audit",
                      }}}
                     for item in row["direct_evidence"]]
            result.append({**row, "direct_evidence": proof,
                           "direct_evidence_state": "recorded" if proof else "missing_registration",
                           "direct_evidence_truncated": row["direct_evidence_count"] > len(proof) or any(
                               item["reference_truncated"] for item in proof)})
        return result

    def _goal_grounding(self, project_id: str, goal_ids: list[str], graph: Mapping[str, object] | None,
                        audits: list[Mapping[str, object]] | None) -> list[dict]:
        if not goal_ids:
            return []
        if graph is None:
            graph = self._goals.goal_graph(project_id)
        if audits is None:
            audits = self._grounding_audits.grounding_audits(project_id)
        nodes = {node["goal_node_id"]: node for node in graph["nodes"]}
        result = []
        for goal_id in goal_ids:
            node = nodes.get(goal_id)
            grounding = (live_grounding_readiness(project_id=project_id, goal_node_ids=(goal_id,), audits=audits)
                         if node is not None else {"state": "unavailable", "gaps": ["goal_authority_missing"]})
            title = str((node or {}).get("title") or "")
            result.append({"goal_node_id": goal_id, "title": title[:256], "title_truncated": len(title) > 256,
                           "applicability": "context", **{key: grounding[key] for key in (
                               "state", "gaps", "audit_id", "source_revision", "evidence_authority", "source_currentness",
                           ) if key in grounding}})
        return result


def _packet_checkpoint(packet: Mapping[str, object], frontier: Mapping[str, object] | None) -> dict:
    result = {"state": "not_applicable", "recorded_status": packet["status"],
              "reason": "external_agent_checkpoint_not_applicable", "next_gate": None,
              "reported_units": None, "repository_review": None}
    if frontier is None:
        return result
    gate = frontier.get("next_gate") or {}
    operation = gate.get("external_operation") or gate.get("operation")
    gate_fields = ("action_kind", "external_operation", "tool", "operation", "reason")
    if operation == "record_technical_disposition":
        gate_fields += ("arguments", "required_inputs", "criterion_result_keys")
    review = frontier.get("repository_review") or {}
    units = frontier.get("todos")
    return {**result,
            "state": operation or frontier.get("status") or "unavailable",
            "reason": frontier.get("reason") or gate.get("reason") or "",
            "next_gate": {key: gate[key] for key in gate_fields if key in gate} or None,
            "reported_units": ({"completed": sum(unit["status"] == "complete" for unit in units),
                                "total": len(units), "provenance": "external_agent_report"}
                               if units is not None else None),
            "repository_review": {key: review[key] for key in ("state", "required", "complete", "latest_audit_id", "source")
                                  if key in review} or None}


def _acceptance_summary(acceptance: Mapping[str, object], limit: int) -> dict:
    blockers = acceptance["blockers"]
    evidence = acceptance.get("acceptance_evidence", [])
    changes = acceptance.get("linked_change_ids", [])
    progress = acceptance.get("external_progress") or {}
    progress_gaps = progress.get("gaps", [])
    external_progress = {key: progress[key] for key in ("scope_complete", "implementation_complete",
                                                       "local_verification_complete", "implementation",
                                                       "local_verification") if key in progress}
    if progress:
        external_progress["gaps"] = [{key: gap[key] for key in ("code", "packet_id", "unit_key", "requirement_id", "criterion")
                                     if key in gap} for gap in progress_gaps[:limit]]
        external_progress["gap_count"] = len(progress_gaps)
        external_progress["deferred_pending_count"] = sum(row.get("state") != "verified"
                                                          for row in progress.get("deferred_obligations", []))
    summarized = []
    for blocker in blockers[:limit]:
        item = {}
        for key, value in blocker.items():
            if isinstance(value, (list, tuple)):
                item[key] = value[:limit]
                item[key + "_count"] = len(value)
            else:
                item[key] = value
        summarized.append(item)
    return {**{key: acceptance[key] for key in ("state", "reason", "recorded_status", "recorded_acceptance",
                                              "prerequisites_satisfied", "awaited_inputs", "external_progress_applies")
               if key in acceptance},
            "blockers": summarized, "blocker_count": len(blockers),
            "linked_change_ids": changes[:limit], "linked_change_count": len(changes),
            "acceptance_evidence": [str(ref)[:512] for ref in evidence[:limit]],
            "acceptance_evidence_count": len(evidence),
            "external_progress": external_progress,
            "truncated": any(len(items) > limit for items in (blockers, changes, evidence, progress_gaps)) or any(
                len(str(reference)) > 512 for reference in evidence[:limit]) or any(
                isinstance(value, (list, tuple)) and len(value) > limit for row in blockers for value in row.values())}


def _deferred_summary(obligation: Mapping[str, object], *, applies: bool) -> dict:
    statement = str(obligation.get("statement") or "")
    return {**{key: obligation[key] for key in ("packet_id", "unit_key", "criterion", "kind", "state", "authority_ref", "attestation")
               if key in obligation}, "statement": statement[:512], "statement_truncated": len(statement) > 512,
            "applicability": "acceptance_prerequisite" if applies else "packet_context"}
