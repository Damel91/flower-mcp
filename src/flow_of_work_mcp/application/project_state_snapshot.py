"""Deterministic, bounded project-state snapshot for model recovery."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from flow_of_work_mcp.application.grounding_readiness import (
    live_grounding_readiness,
)
from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
from flow_of_work_mcp.application.milestone_traceability import (
    MilestoneTraceabilityProjectionService,
)
from flow_of_work_mcp.application.packet_lifecycle_projection import (
    PacketLifecycleProjectionService,
)
from flow_of_work_mcp.application.packet_next_action import (
    PacketNextActionProjectionService,
)
from flow_of_work_mcp.core.domain import PACKET_INACTIVE_STATUS_VALUES
from flow_of_work_mcp.core.ports import (
    AssuranceRepository,
    ChangeControlRepository,
    ConsistentReadScope,
    GoalGraphRepository,
    GroundingAuditRepository,
    PacketWorkPlanRepository,
    ProviderProjectBindingRepository,
)


SNAPSHOT_PROFILE_VERSION = "project-state-snapshot-v1"
_FOCUS_KINDS = frozenset(
    {"project", "milestone", "use_case", "sequence", "packet", "gate"}
)
_ITEM_REFERENCE_LIMIT = 10


class ProjectStateSnapshotService:
    """Compose existing lifecycle authorities into one read-only projection."""

    def __init__(
        self,
        *,
        consistent_reads: ConsistentReadScope,
        goals: GoalGraphRepository,
        grounding_audits: GroundingAuditRepository,
        changes: ChangeControlRepository,
        assurance: AssuranceRepository,
        campaign_authority,
        work_plans: PacketWorkPlanRepository,
        provider_bindings: ProviderProjectBindingRepository,
        lifecycle: LifecycleControlService,
        traceability: MilestoneTraceabilityProjectionService,
        packet_guards,
        packet_next_actions: PacketNextActionProjectionService,
        packet_lifecycle: PacketLifecycleProjectionService,
        provider_enabled: bool,
    ) -> None:
        self._consistent_reads = consistent_reads
        self._goals = goals
        self._grounding_audits = grounding_audits
        self._changes = changes
        self._assurance = assurance
        self._campaign_authority = campaign_authority
        self._work_plans = work_plans
        self._provider_bindings = provider_bindings
        self._lifecycle = lifecycle
        self._traceability = traceability
        self._packet_guards = packet_guards
        self._packet_next_actions = packet_next_actions
        self._packet_lifecycle = packet_lifecycle
        self._provider_enabled = bool(provider_enabled)

    def snapshot(
        self,
        project_id: str,
        *,
        focus_kind: str = "project",
        focus_ref: str = "",
        limit: int = 10,
    ) -> Mapping[str, object]:
        focus = _normalize_focus(focus_kind, focus_ref)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 25
        ):
            raise ValueError("limit must be between 1 and 25")

        with self._consistent_reads.consistent_read():
            graph = self._goals.goal_graph(project_id)
            traceability = self._traceability.projection(project_id)
            changes = list(self._changes.list_changes(project_id))
            grounding_audits = list(self._grounding_audits.grounding_audits(project_id))
            lifecycle_actions = [
                _lifecycle_action(item)
                for item in self._lifecycle.what_next(project_id)
            ]
            packet_actions = self._packet_actions(project_id, changes)
            ordered_actions = _ordered_actions(lifecycle_actions, packet_actions)
            findings_by_change = {
                str(change["change_id"]): list(
                    self._assurance.findings_for_change(
                        project_id, str(change["change_id"])
                    )
                )
                for change in changes
            }
            campaigns_by_change: dict[str, list[Mapping[str, object]]] = {}
            for change in changes:
                change_id = str(change["change_id"])
                projected_campaigns = []
                for campaign in self._assurance.campaigns_for_change(
                    project_id, change_id
                ):
                    projection = self._campaign_authority.inspect(
                        project_id,
                        campaign_id=str(campaign["campaign_id"]),
                        view="summary",
                    )
                    summary = projection.get("campaign")
                    if isinstance(summary, Mapping):
                        projected_campaigns.append(
                            {
                                **dict(summary),
                                "lifecycle_gate": dict(
                                    projection.get("lifecycle_gate") or {}
                                ),
                            }
                        )
                campaigns_by_change[change_id] = projected_campaigns
            work_plans = _work_plan_basis(self._work_plans, project_id, changes)
            provider_bindings = list(
                self._provider_bindings.list_provider_bindings(project_id)
            )
            entry_diagnostics = list(
                self._lifecycle.milestone_entry_policy_diagnostics(project_id)
            )

            context = _SnapshotContext(
                project_id=project_id,
                graph=graph,
                traceability=traceability,
                changes=changes,
                grounding_audits=grounding_audits,
                lifecycle_actions=lifecycle_actions,
                packet_actions=packet_actions,
                ordered_actions=ordered_actions,
                findings_by_change=findings_by_change,
                campaigns_by_change=campaigns_by_change,
                work_plans=work_plans,
                provider_bindings=provider_bindings,
                entry_diagnostics=entry_diagnostics,
            )
            focus = context.validate_focus(focus)
            focused_actions = context.actions_for_focus(focus)
            primary_action = focused_actions[0] if focused_actions else None
            next_gate = _next_gate(project_id, primary_action, traceability)
            active = context.active_work(focus, primary_action)
            packet_lifecycle = self._active_packet_lifecycle(project_id, active)
            active_work = context.active_work_projection(
                active,
                packet_lifecycle=packet_lifecycle,
                provider_enabled=self._provider_enabled,
            )
            all_goal_reach = context.goal_reach()
            focused_goal_reach = context.focus_goal_reach(
                all_goal_reach, focus, primary_action
            )
            goal_projection = _bounded_goal_projection(focused_goal_reach, limit)
            secondary_actions = [
                _next_gate(project_id, item, traceability)
                for item in focused_actions[1 : limit + 1]
            ]
            blockers = context.blockers(active, next_gate=next_gate, limit=limit)
            open_decisions = _open_decisions(primary_action)
            detail_references = context.detail_references(
                focus,
                active,
                next_gate=next_gate,
            )
            accepted_evidence_boundary = context.accepted_evidence_boundary(
                packet_lifecycle=packet_lifecycle,
                limit=limit,
            )

            canonical_project_basis = {
                "profile_version": SNAPSHOT_PROFILE_VERSION,
                "project_id": project_id,
                "goal_graph": graph,
                "traceability": traceability,
                "changes": changes,
                "grounding_audits": grounding_audits,
                "lifecycle_actions": lifecycle_actions,
                "packet_actions": packet_actions,
                "findings_by_change": findings_by_change,
                "campaigns_by_change": campaigns_by_change,
                "work_plans": work_plans,
                "provider_bindings": provider_bindings,
                "provider_enabled": self._provider_enabled,
                "entry_diagnostics": entry_diagnostics,
            }
            project_fingerprint = _fingerprint(canonical_project_basis)
            fingerprint = _fingerprint(
                {
                    "project_fingerprint": project_fingerprint,
                    "focus": focus,
                    "limit": limit,
                }
            )

        source_version = int(traceability.get("source_ledger_version") or 0)
        unavailable_sources = []
        if not self._provider_enabled:
            unavailable_sources.append("implementation_provider")
        truncated_sections = [
            name
            for name, truncated in (
                ("goal_reach.items", bool(goal_projection["truncated"])),
                ("secondary_actions", len(focused_actions) > limit + 1),
                ("blockers", bool(blockers["truncated"])),
            )
            if truncated
        ]
        return {
            "profile_version": SNAPSHOT_PROFILE_VERSION,
            "project": {"project_id": project_id},
            "project_revision": (f"flow:{source_version}:{project_fingerprint[:16]}"),
            "source_ledger_version": source_version,
            "snapshot_fingerprint": fingerprint,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "focus": dict(focus),
            "goal_reach": goal_projection,
            "active_work": active_work,
            "next_gate": next_gate,
            "secondary_actions": secondary_actions,
            "blockers": blockers["items"],
            "open_decisions": open_decisions,
            "accepted_evidence_boundary": accepted_evidence_boundary,
            "detail_references": detail_references,
            "completeness": {
                "coherent_read": True,
                "canonical_sources": [
                    "flow_ledger",
                    "goal_graph",
                    "traceability",
                    "packet_lifecycle",
                ],
                "unavailable_sources": unavailable_sources,
                "truncated_sections": truncated_sections,
                "omitted": {
                    "goal_reach_items": int(goal_projection["omitted_count"]),
                    "secondary_actions": max(0, len(focused_actions) - 1 - limit),
                    "blockers": int(blockers["omitted_count"]),
                },
            },
        }

    def _packet_actions(
        self,
        project_id: str,
        changes: list[Mapping[str, object]],
    ) -> list[Mapping[str, object]]:
        actions: list[Mapping[str, object]] = []
        for change in changes:
            change_id = str(change.get("change_id") or "")
            for packet in change.get("packets", []):
                if not isinstance(packet, Mapping):
                    continue
                if str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES:
                    continue
                packet_id = str(packet.get("packet_id") or "")
                guard = self._packet_guards.evaluate(project_id, change_id, packet_id)
                plan = self._work_plans.packet_work_plan_state(
                    project_id, change_id, packet_id
                )
                action = self._packet_next_actions.project(
                    guard,
                    project_id=project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    spec_revision=int(
                        packet.get("spec_revision")
                        or packet.get("current_revision")
                        or 0
                    ),
                    plan_revision=(int(plan.get("plan_revision") or 0) if plan else 0),
                )
                actions.append(
                    {
                        **dict(action),
                        "scope": {
                            "change_id": change_id,
                            "packet_id": packet_id,
                        },
                    }
                )
        return actions

    def _active_packet_lifecycle(
        self,
        project_id: str,
        active: Mapping[str, str],
    ) -> Mapping[str, object]:
        change_id = str(active.get("change_id") or "")
        packet_id = str(active.get("packet_id") or "")
        if not change_id or not packet_id:
            return {}
        return self._packet_lifecycle.get_packet(
            project_id,
            change_id,
            packet_id,
            detail_level="standard",
            view="summary",
        )


class _SnapshotContext:
    def __init__(
        self,
        *,
        project_id: str,
        graph: Mapping[str, object],
        traceability: Mapping[str, object],
        changes: list[Mapping[str, object]],
        grounding_audits: list[Mapping[str, object]],
        lifecycle_actions: list[Mapping[str, object]],
        packet_actions: list[Mapping[str, object]],
        ordered_actions: list[Mapping[str, object]],
        findings_by_change: Mapping[str, list[Mapping[str, object]]],
        campaigns_by_change: Mapping[str, list[Mapping[str, object]]],
        work_plans: Mapping[str, object],
        provider_bindings: list[Mapping[str, object]],
        entry_diagnostics: list[Mapping[str, object]],
    ) -> None:
        self.project_id = project_id
        self.graph = graph
        self.traceability = traceability
        self.changes = changes
        self.grounding_audits = grounding_audits
        self.lifecycle_actions = lifecycle_actions
        self.packet_actions = packet_actions
        self.ordered_actions = ordered_actions
        self.findings_by_change = findings_by_change
        self.campaigns_by_change = campaigns_by_change
        self.work_plans = work_plans
        self.provider_bindings = provider_bindings
        self.entry_diagnostics = entry_diagnostics
        self.nodes = {
            str(item.get("goal_node_id") or ""): item
            for item in graph.get("nodes", [])
            if isinstance(item, Mapping)
        }
        self.milestones = {
            str(item.get("milestone_id") or ""): item
            for item in traceability.get("milestones", [])
            if isinstance(item, Mapping)
        }
        self.change_by_id = {str(item.get("change_id") or ""): item for item in changes}
        self.packet_owner: dict[
            str, tuple[Mapping[str, object], Mapping[str, object]]
        ] = {}
        for change in changes:
            for packet in change.get("packets", []):
                if isinstance(packet, Mapping):
                    self.packet_owner[str(packet.get("packet_id") or "")] = (
                        change,
                        packet,
                    )

    def validate_focus(self, focus: Mapping[str, str]) -> Mapping[str, str]:
        kind = focus["kind"]
        ref = focus["ref"]
        if kind == "project":
            if ref:
                raise ValueError("focus_ref must be empty for project focus")
            return focus
        if kind == "milestone" and ref not in self.milestones:
            raise ValueError(f"unknown milestone focus: {ref}")
        if kind in {"use_case", "sequence"}:
            node = self.nodes.get(ref)
            if node is None or str(node.get("node_type") or "") != kind:
                raise ValueError(f"unknown {kind} focus: {ref}")
        if kind == "packet" and ref not in self.packet_owner:
            raise ValueError(f"unknown packet focus: {ref}")
        if kind == "gate":
            candidates = self.ordered_actions
            if not ref:
                return {
                    "kind": "gate",
                    "ref": _action_identity(candidates[0]) if candidates else "idle",
                }
            if ref == "idle" and not candidates:
                return focus
            if not any(_action_matches_gate(item, ref) for item in candidates):
                raise ValueError(f"unknown gate focus: {ref}")
        return focus

    def actions_for_focus(self, focus: Mapping[str, str]) -> list[Mapping[str, object]]:
        actions = list(self.ordered_actions)
        kind = focus["kind"]
        ref = focus["ref"]
        if kind == "project":
            return actions
        if kind == "gate":
            return [item for item in actions if _action_matches_gate(item, ref)]
        scope = self._focus_scope(focus)
        return [item for item in actions if _action_overlaps(item, scope)]

    def active_work(
        self,
        focus: Mapping[str, str],
        primary_action: Mapping[str, object] | None,
    ) -> Mapping[str, str]:
        scope = dict(primary_action.get("scope") or {}) if primary_action else {}
        packet_id = str(scope.get("packet_id") or _first(primary_action, "packet_ids"))
        change_id = str(scope.get("change_id") or _first(primary_action, "change_ids"))
        milestone_id = str(_first(primary_action, "milestone_ids"))
        campaign_id = str(_first(primary_action, "campaign_ids"))
        finding_id = str(_first(primary_action, "finding_ids"))
        if focus["kind"] == "packet":
            packet_id = focus["ref"]
        if packet_id and packet_id in self.packet_owner:
            change, _packet = self.packet_owner[packet_id]
            change_id = str(change.get("change_id") or "")
        if focus["kind"] == "milestone":
            milestone_id = focus["ref"]
        if change_id and change_id in self.change_by_id:
            milestone_id = str(
                self.change_by_id[change_id].get("milestone_id") or milestone_id
            )
        if not milestone_id:
            milestone_id = next(
                (
                    key
                    for key, value in self.milestones.items()
                    if str(value.get("status") or "") != "accepted"
                ),
                "",
            )
        if not change_id and milestone_id:
            change_id = next(
                (
                    str(item.get("change_id") or "")
                    for item in self.changes
                    if str(item.get("milestone_id") or "") == milestone_id
                    and str(item.get("status") or "") != "accepted"
                ),
                "",
            )
        if not packet_id and change_id:
            packet_id = next(
                (
                    str(item.get("packet_id") or "")
                    for item in self.change_by_id[change_id].get("packets", [])
                    if isinstance(item, Mapping)
                    and str(item.get("status") or "")
                    not in PACKET_INACTIVE_STATUS_VALUES
                ),
                "",
            )
        if not campaign_id and change_id:
            campaign_id = next(
                (
                    str(item.get("campaign_id") or "")
                    for item in self.campaigns_by_change.get(change_id, [])
                    if str(item.get("qualification") or "") == "current"
                    and str((item.get("lifecycle_gate") or {}).get("state") or "")
                    not in {"accepted", "inactive"}
                ),
                "",
            )
        return {
            "milestone_id": milestone_id,
            "change_id": change_id,
            "packet_id": packet_id,
            "campaign_id": campaign_id,
            "finding_id": finding_id,
        }

    def active_work_projection(
        self,
        active: Mapping[str, str],
        *,
        packet_lifecycle: Mapping[str, object],
        provider_enabled: bool,
    ) -> Mapping[str, object]:
        milestone = self.milestones.get(active["milestone_id"])
        change = self.change_by_id.get(active["change_id"])
        packet_owner = self.packet_owner.get(active["packet_id"])
        packet = packet_owner[1] if packet_owner else None
        execution = dict(packet_lifecycle.get("execution") or {})
        review = dict(packet_lifecycle.get("workspace_review") or {})
        provider_state = _provider_state(
            execution,
            provider_enabled=provider_enabled,
            has_packet=packet is not None,
        )
        remediation = self._remediation_projection(active["packet_id"])
        campaign = next(
            (
                item
                for item in self.campaigns_by_change.get(active["change_id"], [])
                if str(item.get("campaign_id") or "") == active["campaign_id"]
            ),
            None,
        )
        return {
            "milestone": _milestone_summary(milestone),
            "change": _change_summary(change),
            "packet": _packet_summary(packet),
            "provider_execution": provider_state,
            "review": _review_state(review, provider_state),
            "remediation": remediation,
            "campaign": _campaign_summary(campaign),
        }

    def goal_reach(self) -> list[Mapping[str, object]]:
        rows = [
            item
            for item in self.traceability.get("rows", [])
            if isinstance(item, Mapping)
        ]
        edges = [
            item for item in self.graph.get("edges", []) if isinstance(item, Mapping)
        ]
        result = []
        for goal_id, node in self.nodes.items():
            node_type = str(node.get("node_type") or "")
            if node_type not in {"use_case", "sequence"}:
                continue
            grounding = live_grounding_readiness(
                project_id=self.project_id,
                goal_node_ids=(goal_id,),
                audits=self.grounding_audits,
            )
            covering_rows = [
                row
                for row in rows
                if goal_id
                in {
                    str(value)
                    for value in row.get(
                        "covered_use_case_goal_node_ids"
                        if node_type == "use_case"
                        else "covered_sequence_goal_node_ids",
                        [],
                    )
                }
            ]
            related_goal_ids = sorted(_related_goal_ids(goal_id, edges))
            result.append(
                {
                    "goal_node_id": goal_id,
                    "node_type": node_type,
                    "title": str(node.get("title") or ""),
                    "related_goal_node_ids": related_goal_ids[:_ITEM_REFERENCE_LIMIT],
                    "related_goal_node_ids_truncated": (
                        len(related_goal_ids) > _ITEM_REFERENCE_LIMIT
                    ),
                    "implementation_grounding": _grounding_dimension(grounding),
                    "deterministic_verification": _verification_dimension(
                        covering_rows, "tested_deterministically"
                    ),
                    "live_verification": _verification_dimension(
                        covering_rows, "tested_live"
                    ),
                    "detail_reference": _snapshot_detail_ref(
                        self.project_id, node_type, goal_id
                    ),
                }
            )
        return result

    def focus_goal_reach(
        self,
        goals: list[Mapping[str, object]],
        focus: Mapping[str, str],
        primary_action: Mapping[str, object] | None,
    ) -> list[Mapping[str, object]]:
        if focus["kind"] == "project":
            return goals
        goal_ids = set(self._focus_scope(focus)["goal_ids"])
        if focus["kind"] == "gate" and primary_action:
            goal_ids.update(
                str(item) for item in primary_action.get("goal_node_ids", [])
            )
            goal_ids.update(
                self._goal_ids_for_requirements(
                    primary_action.get("requirement_ids", [])
                )
            )
        expanded = set(goal_ids)
        for goal_id in tuple(goal_ids):
            expanded.update(_related_goal_ids(goal_id, self.graph.get("edges", [])))
        return [item for item in goals if str(item["goal_node_id"]) in expanded]

    def blockers(
        self,
        active: Mapping[str, str],
        *,
        next_gate: Mapping[str, object],
        limit: int,
    ) -> Mapping[str, object]:
        values: list[Mapping[str, object]] = []
        gate_kind = str(next_gate.get("kind") or "")
        if gate_kind in {"technical_blockage", "authority_decision_required"}:
            values.append(
                {
                    "code": str(next_gate.get("reason") or gate_kind),
                    "scope_ref": str(
                        active.get("packet_id") or active.get("change_id") or ""
                    ),
                }
            )
        packet_owner = self.packet_owner.get(active["packet_id"])
        if packet_owner:
            packet = packet_owner[1]
            for code in list(packet.get("readiness_blockers", [])) + list(
                packet.get("blocking_reasons", [])
            ):
                values.append({"code": str(code), "scope_ref": active["packet_id"]})
        for gap in self.traceability.get("gaps", []):
            if isinstance(gap, Mapping):
                relevant = self._active_requirement_ids(active)
                gap_requirements = {
                    str(item) for item in gap.get("requirement_ids", [])
                }
                if relevant and not relevant.intersection(gap_requirements):
                    continue
                values.append(
                    {
                        "code": str(gap.get("reason") or ""),
                        "requirement_ids": [
                            str(item) for item in gap.get("requirement_ids", [])[:5]
                        ],
                    }
                )
        deduped = _dedupe_mappings(values)
        return {
            "items": deduped[:limit],
            "truncated": len(deduped) > limit,
            "omitted_count": max(0, len(deduped) - limit),
        }

    def detail_references(
        self,
        focus: Mapping[str, str],
        active: Mapping[str, str],
        *,
        next_gate: Mapping[str, object],
    ) -> list[Mapping[str, object]]:
        refs: list[Mapping[str, object]] = [
            {
                "kind": "next_work",
                "tool": "fow_what_next",
                "arguments": {
                    "project_id": self.project_id,
                    "detail_level": "audit",
                },
            },
            {
                "kind": "goal_graph",
                "tool": "fow_goal",
                "arguments": {
                    "project_id": self.project_id,
                    "operation": "view",
                    "view": "nodes",
                },
            },
        ]
        if active["milestone_id"]:
            refs.append(
                {
                    "kind": "milestone_traceability",
                    "tool": "fow_traceability",
                    "arguments": {
                        "project_id": self.project_id,
                        "milestone_id": active["milestone_id"],
                    },
                }
            )
        if active["packet_id"]:
            refs.append(
                {
                    "kind": "packet",
                    "tool": "fow_packet_inspect",
                    "arguments": {
                        "project_id": self.project_id,
                        "packet_id": active["packet_id"],
                        "view": "summary",
                    },
                }
            )
        if focus["kind"] in {"use_case", "sequence", "packet", "milestone"}:
            refs.append(
                {
                    "kind": "focused_snapshot",
                    "tool": "fow_handover",
                    "arguments": {
                        "project_id": self.project_id,
                        "operation": "project_state_snapshot",
                        "focus_kind": focus["kind"],
                        "focus_ref": focus["ref"],
                    },
                }
            )
        return _dedupe_mappings(refs)

    def accepted_evidence_boundary(
        self,
        *,
        packet_lifecycle: Mapping[str, object],
        limit: int,
    ) -> Mapping[str, object]:
        accepted_milestones = [
            milestone_id
            for milestone_id, milestone in self.milestones.items()
            if str(milestone.get("status") or "") == "accepted"
        ]
        accepted_campaigns = sorted(
            {
                str(campaign.get("campaign_id") or "")
                for campaigns in self.campaigns_by_change.values()
                for campaign in campaigns
                if _campaign_is_accepted(campaign)
            }
        )
        review = dict(packet_lifecycle.get("workspace_review") or {})
        review_ref = (
            str(review.get("workspace_review_id") or "")
            if str(review.get("disposition") or "") == "approved"
            else ""
        )
        return {
            "accepted_milestone_ids": accepted_milestones[:limit],
            "accepted_campaign_ids": accepted_campaigns[:limit],
            "current_approved_review_id": review_ref,
            "truncated": (
                len(accepted_milestones) > limit or len(accepted_campaigns) > limit
            ),
        }

    def _focus_scope(self, focus: Mapping[str, str]) -> Mapping[str, set[str]]:
        scope = {
            "milestone_ids": set(),
            "change_ids": set(),
            "packet_ids": set(),
            "requirement_ids": set(),
            "goal_ids": set(),
        }
        kind = focus["kind"]
        ref = focus["ref"]
        if kind == "milestone":
            scope["milestone_ids"].add(ref)
            scope["requirement_ids"].update(
                str(item) for item in self.milestones[ref].get("requirement_ids", [])
            )
            for change in self.changes:
                if str(change.get("milestone_id") or "") == ref:
                    scope["change_ids"].add(str(change.get("change_id") or ""))
                    scope["packet_ids"].update(
                        str(item.get("packet_id") or "")
                        for item in change.get("packets", [])
                        if isinstance(item, Mapping)
                    )
                    for packet in change.get("packets", []):
                        if isinstance(packet, Mapping):
                            scope["goal_ids"].update(
                                str(item) for item in packet.get("goal_ids", [])
                            )
        elif kind in {"use_case", "sequence"}:
            scope["goal_ids"].add(ref)
            for audit in reversed(self.grounding_audits):
                for item in audit.get("items", []):
                    if not isinstance(item, Mapping):
                        continue
                    if str(item.get("goal_node_id") or "") == ref:
                        scope["requirement_ids"].update(
                            str(value) for value in item.get("requirement_ids", [])
                        )
            for row in self.traceability.get("rows", []):
                if not isinstance(row, Mapping):
                    continue
                covered = {
                    str(value)
                    for key in (
                        "covered_use_case_goal_node_ids",
                        "covered_sequence_goal_node_ids",
                    )
                    for value in row.get(key, [])
                }
                if ref in covered:
                    scope["requirement_ids"].add(str(row.get("requirement_id") or ""))
        elif kind == "packet":
            change, packet = self.packet_owner[ref]
            scope["packet_ids"].add(ref)
            scope["change_ids"].add(str(change.get("change_id") or ""))
            milestone_id = str(change.get("milestone_id") or "")
            if milestone_id:
                scope["milestone_ids"].add(milestone_id)
            scope["requirement_ids"].update(
                str(item) for item in packet.get("requirement_ids", [])
            )
            scope["goal_ids"].update(str(item) for item in packet.get("goal_ids", []))
        scope["goal_ids"].update(
            self._goal_ids_for_requirements(scope["requirement_ids"])
        )
        for change in self.changes:
            change_requirements = {
                str(item) for item in change.get("requirement_ids", [])
            }
            packets = [
                item for item in change.get("packets", []) if isinstance(item, Mapping)
            ]
            packet_goal_ids = {
                str(goal_id)
                for packet in packets
                for goal_id in packet.get("goal_ids", [])
            }
            if not (
                scope["requirement_ids"].intersection(change_requirements)
                or scope["goal_ids"].intersection(packet_goal_ids)
            ):
                continue
            scope["change_ids"].add(str(change.get("change_id") or ""))
            milestone_id = str(change.get("milestone_id") or "")
            if milestone_id:
                scope["milestone_ids"].add(milestone_id)
            scope["packet_ids"].update(
                str(packet.get("packet_id") or "") for packet in packets
            )
            scope["goal_ids"].update(packet_goal_ids)
        return scope

    def _goal_ids_for_requirements(self, requirement_ids) -> set[str]:
        requested = {str(item) for item in requirement_ids}
        result: set[str] = set()
        for row in self.traceability.get("rows", []):
            if (
                not isinstance(row, Mapping)
                or str(row.get("requirement_id") or "") not in requested
            ):
                continue
            result.update(
                str(item) for item in row.get("covered_use_case_goal_node_ids", [])
            )
            result.update(
                str(item) for item in row.get("covered_sequence_goal_node_ids", [])
            )
        for audit in reversed(self.grounding_audits):
            for item in audit.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                if requested.intersection(
                    str(value) for value in item.get("requirement_ids", [])
                ):
                    goal_id = str(item.get("goal_node_id") or "")
                    if goal_id:
                        result.add(goal_id)
        return result

    def _active_requirement_ids(self, active: Mapping[str, str]) -> set[str]:
        packet_owner = self.packet_owner.get(active.get("packet_id", ""))
        if packet_owner:
            return {str(item) for item in packet_owner[1].get("requirement_ids", [])}
        change = self.change_by_id.get(active.get("change_id", ""))
        if change:
            return {str(item) for item in change.get("requirement_ids", [])}
        milestone = self.milestones.get(active.get("milestone_id", ""))
        if milestone:
            return {str(item) for item in milestone.get("requirement_ids", [])}
        return set()

    def _remediation_projection(self, active_packet_id: str) -> Mapping[str, object]:
        if not active_packet_id:
            return {"state": "not_active"}
        links = []
        for findings in self.findings_by_change.values():
            for finding in findings:
                for link in finding.get("fixing_packets", []):
                    if (
                        not isinstance(link, Mapping)
                        or str(link.get("packet_id") or "") != active_packet_id
                    ):
                        continue
                    links.append(
                        {
                            "finding_id": str(finding.get("finding_id") or ""),
                            "primary_packet_id": str(finding.get("packet_id") or ""),
                            "disposition": str(finding.get("disposition") or ""),
                        }
                    )
        return {
            "state": "active" if links else "not_active",
            "links": links[:10],
            "truncated": len(links) > 10,
        }


def _normalize_focus(kind: str, ref: str) -> Mapping[str, str]:
    normalized_kind = str(kind or "project").strip().lower()
    if normalized_kind not in _FOCUS_KINDS:
        raise ValueError(
            "focus_kind must be project, milestone, use_case, sequence, packet or gate"
        )
    normalized_ref = str(ref or "").strip()
    if (
        normalized_kind != "project"
        and normalized_kind != "gate"
        and not normalized_ref
    ):
        raise ValueError(f"focus_ref is required for {normalized_kind} focus")
    return {"kind": normalized_kind, "ref": normalized_ref}


def _lifecycle_action(action) -> Mapping[str, object]:
    value = asdict(action)
    value["kind"] = action.kind.value
    value["execution_class"] = action.execution_class.value
    return value


def _work_plan_basis(
    repository: PacketWorkPlanRepository,
    project_id: str,
    changes: list[Mapping[str, object]],
) -> Mapping[str, object]:
    values: dict[str, object] = {}
    for change in changes:
        change_id = str(change.get("change_id") or "")
        for packet in change.get("packets", []):
            if not isinstance(packet, Mapping):
                continue
            packet_id = str(packet.get("packet_id") or "")
            plan = repository.packet_work_plan_state(project_id, change_id, packet_id)
            if plan is not None:
                values[packet_id] = plan
    return values


def _ordered_actions(
    lifecycle_actions: list[Mapping[str, object]],
    packet_actions: list[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Preserve global lifecycle priority while refining packet-local routes."""

    packet_action_by_id = {
        str(dict(action.get("scope") or {}).get("packet_id") or ""): action
        for action in packet_actions
        if str(dict(action.get("scope") or {}).get("packet_id") or "")
    }
    represented_packet_ids: set[str] = set()
    ordered: list[Mapping[str, object]] = []
    for lifecycle_action in lifecycle_actions:
        packet_ids = [
            str(item) for item in lifecycle_action.get("packet_ids", []) if str(item)
        ]
        detail = next(
            (
                packet_action_by_id[packet_id]
                for packet_id in packet_ids
                if packet_id in packet_action_by_id
            ),
            None,
        )
        if detail is None:
            ordered.append(lifecycle_action)
            continue
        represented_packet_ids.update(packet_ids)
        ordered.append(
            {
                **dict(lifecycle_action),
                **dict(detail),
                "action_id": str(lifecycle_action.get("action_id") or ""),
                "priority": int(lifecycle_action.get("priority") or 0),
                "lifecycle_kind": str(lifecycle_action.get("kind") or ""),
                "scope": {
                    **dict(_action_scope(lifecycle_action)),
                    **dict(detail.get("scope") or {}),
                },
            }
        )
    ordered.extend(
        action
        for packet_id, action in packet_action_by_id.items()
        if packet_id not in represented_packet_ids
    )
    return ordered


def _next_gate(
    project_id: str,
    action: Mapping[str, object] | None,
    traceability: Mapping[str, object],
) -> Mapping[str, object]:
    if action is None:
        return {
            "kind": "idle",
            "state": "satisfied",
            "reason": "no_pending_action_in_focus",
            "decision_class": "mechanical",
            "continuation_policy": "return_to_model",
            "route": None,
            "scope": {},
        }
    action_kind = str(
        action.get("lifecycle_operation")
        or action.get("operation")
        or action.get("kind")
        or ""
    )
    reason = str(action.get("reason") or action.get("rationale") or action_kind)
    gate_kind = _gate_kind(action_kind, reason, traceability)
    route = None
    if str(action.get("tool") or ""):
        route = {
            "tool": str(action.get("tool") or ""),
            "operation": str(action.get("operation") or ""),
            "arguments": dict(action.get("arguments") or {}),
            "required_inputs": [
                str(item) for item in action.get("required_inputs", [])
            ],
        }
    else:
        route = {
            "tool": "fow_what_next",
            "operation": "inspect_current_action",
            "arguments": {"project_id": project_id, "detail_level": "audit"},
            "required_inputs": [],
        }
    return {
        "kind": gate_kind,
        "state": str(action.get("state") or "pending"),
        "action_id": _action_identity(action),
        "reason": reason,
        "decision_class": str(
            action.get("decision_class")
            or action.get("execution_class")
            or "orchestration"
        ),
        "continuation_policy": str(
            action.get("continuation_policy") or "return_to_model"
        ),
        "route": route,
        "scope": _action_scope(action),
    }


def _gate_kind(
    action_kind: str,
    reason: str,
    traceability: Mapping[str, object],
) -> str:
    if action_kind == "external_validation":
        return "packet_construction"
    if action_kind in {"external_todo", "external_reconcile"}:
        return "external_agent_work"
    if action_kind == "external_verification":
        return "deterministic_verification"
    if action_kind == "external_acceptance":
        return "acceptance"
    lowered = f"{action_kind} {reason}".lower()
    if any(value in lowered for value in ("blocked", "failed", "unavailable", "stale")):
        return "technical_blockage"
    if action_kind in {
        "packet_author",
        "add_unit",
        "replace_plan",
        "resolve_questions",
        "answer_gate",
        "accept_work_plan",
        "derive_engineering_questions",
        "answer_engineering_questions",
        "evaluate_packet_readiness",
        "derive_packet_pressure",
        "decide_residual_risk",
        "accept_residual_risk",
        "resolve_change_packet_graph",
        "collect_packet_evidence",
        "reconcile_packet_evidence",
        "resolve_reconciliation_residual",
    }:
        return "packet_construction"
    if action_kind in {
        "bind_implementation_provider",
        "implement_packet",
        "start_implementation_run",
        "execute_run_step",
        "close_packet_after_run",
    }:
        return "provider_execution"
    if action_kind in {"review_workspace", "record_workspace_review"}:
        return "workspace_review"
    if action_kind in {
        "retry_or_remediate",
        "triage_finding",
        "resolve_finding",
        "repair_failed_campaign",
        "repair_failed_verification",
        "resolve_packet_blocker",
        "resolve_run_blocker",
    }:
        return "remediation_construction"
    if action_kind in {
        "record_verification",
        "start_campaign",
        "collect_verification_evidence",
    }:
        if any(
            isinstance(row, Mapping)
            and bool((row.get("live_campaign_readiness") or {}).get("ready"))
            for row in traceability.get("rows", [])
        ):
            return "live_campaign_readiness"
        return "deterministic_verification"
    if action_kind == "run_verification_campaign":
        return "campaign_execution"
    if action_kind in {"request_change_acceptance", "review_milestone_risk"}:
        return "acceptance"
    if action_kind in {
        "implement_requirement",
        "create_milestone_change",
        "resolve_partial_requirement",
        "resolve_grounding_divergence",
        "review_requirement_candidate",
        "resolve_validation_findings",
    }:
        return "intent_work"
    if action_kind == "run_phase_audit":
        return "lifecycle_audit"
    if str(action_kind) == "":
        return "authority_decision_required"
    return "authority_decision_required"


def _action_identity(action: Mapping[str, object]) -> str:
    return str(
        action.get("action_id")
        or action.get("operation")
        or action.get("reason")
        or "pending"
    )


def _action_matches_gate(action: Mapping[str, object], ref: str) -> bool:
    return ref in {
        _action_identity(action),
        str(action.get("kind") or ""),
        str(action.get("operation") or ""),
    }


def _action_scope(action: Mapping[str, object]) -> Mapping[str, object]:
    scope = dict(action.get("scope") or {})
    for key in (
        "requirement_ids",
        "goal_node_ids",
        "milestone_ids",
        "change_ids",
        "packet_ids",
        "finding_ids",
        "campaign_ids",
        "run_ids",
    ):
        values = [str(item) for item in action.get(key, []) if str(item)]
        if values:
            scope[key] = values
    return scope


def _action_overlaps(
    action: Mapping[str, object], scope: Mapping[str, set[str]]
) -> bool:
    action_scope = _action_scope(action)
    singular = {"change_id": "change_ids", "packet_id": "packet_ids"}
    for key, plural in singular.items():
        value = str(action_scope.get(key) or "")
        if value and value in scope[plural]:
            return True
    for key in scope:
        values = {str(item) for item in action_scope.get(key, [])}
        if values.intersection(scope[key]):
            return True
    return False


def _first(action: Mapping[str, object] | None, key: str) -> str:
    if action is None:
        return ""
    values = action.get(key, [])
    return str(values[0]) if isinstance(values, (list, tuple)) and values else ""


def _related_goal_ids(goal_id: str, edges) -> set[str]:
    related: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("source_goal_id") or "")
        target = str(edge.get("target_goal_id") or "")
        if source == goal_id and target:
            related.add(target)
        if target == goal_id and source:
            related.add(source)
    return related


def _grounding_dimension(grounding: Mapping[str, object]) -> Mapping[str, object]:
    state = str(grounding.get("state") or "needs_implementation_projection")
    if bool(grounding.get("ready")):
        normalized = "grounded"
    elif state == "blocked_by_grounding":
        normalized = "contradicted"
    elif state == "partial_live_readiness":
        normalized = "partial"
    elif state == "grounding_truncated":
        normalized = "incomplete"
    else:
        normalized = "unavailable"
    gaps = [str(item) for item in grounding.get("gaps", [])]
    return {
        "state": normalized,
        "audit_id": str(grounding.get("audit_id") or ""),
        "source_revision": str(grounding.get("source_revision") or ""),
        "gaps": gaps[:_ITEM_REFERENCE_LIMIT],
        "gaps_truncated": len(gaps) > _ITEM_REFERENCE_LIMIT,
    }


def _verification_dimension(
    rows: list[Mapping[str, object]], field: str
) -> Mapping[str, object]:
    outcomes = [str(row.get(field) or "") for row in rows]
    if "failed" in outcomes:
        state = "failed"
    elif rows and all(item == "passed" for item in outcomes):
        state = "passed"
    elif "passed" in outcomes:
        state = "partial"
    else:
        state = "not_verified"
    campaign_ids = sorted(
        {
            str(campaign_id)
            for row in rows
            for campaign_id in row.get("accepted_campaign_ids", [])
            if str(campaign_id)
        }
    )
    return {
        "state": state,
        "accepted_campaign_ids": campaign_ids[:_ITEM_REFERENCE_LIMIT],
        "accepted_campaign_ids_truncated": (len(campaign_ids) > _ITEM_REFERENCE_LIMIT),
    }


def _bounded_goal_projection(
    goals: list[Mapping[str, object]], limit: int
) -> Mapping[str, object]:
    ordered = sorted(
        goals,
        key=lambda item: (
            _goal_is_satisfied(item),
            str(item.get("goal_node_id") or ""),
        ),
    )
    visible = ordered[:limit]
    return {
        "summary": {
            "total": len(ordered),
            "implementation_grounded": sum(
                str(item["implementation_grounding"]["state"]) == "grounded"
                for item in ordered
            ),
            "deterministically_verified": sum(
                str(item["deterministic_verification"]["state"]) == "passed"
                for item in ordered
            ),
            "live_verified": sum(
                str(item["live_verification"]["state"]) == "passed" for item in ordered
            ),
            "unresolved": sum(not _goal_is_satisfied(item) for item in ordered),
        },
        "items": visible,
        "truncated": len(ordered) > limit,
        "omitted_count": max(0, len(ordered) - limit),
    }


def _goal_is_satisfied(item: Mapping[str, object]) -> bool:
    return (
        str((item.get("implementation_grounding") or {}).get("state") or "")
        == "grounded"
        and str((item.get("deterministic_verification") or {}).get("state") or "")
        == "passed"
        and str((item.get("live_verification") or {}).get("state") or "") == "passed"
    )


def _provider_state(
    execution: Mapping[str, object], *, provider_enabled: bool, has_packet: bool
) -> Mapping[str, object]:
    if not has_packet:
        return {"state": "not_applicable", "evidence_ref": ""}
    if execution.get("consumption_mode") == "external_agent":
        return {"state": "not_applicable", "consumption_mode": "external_agent",
                "evidence_ref": "", "provenance": "host_supplied"}
    status = str(execution.get("status") or "not_started")
    if status in {"provider_technically_complete", "provider_complete"}:
        state = "technically_satisfied"
    elif status in {"provider_failed", "blocked", "failed", "partial"}:
        state = "blocked"
    elif (
        status
        in {
            "provider_pending",
            "provider_running",
            "created",
            "queued",
            "running",
            "not_started",
        }
        and provider_enabled
    ):
        state = "pending"
    else:
        state = "unavailable"
    return {
        "state": state,
        "provider_status": status,
        "evidence_ref": str(execution.get("provider_packet_ref") or ""),
        "provider_packet_revision": int(execution.get("provider_packet_revision") or 0),
        "provider_job_ref": str(execution.get("provider_job_ref") or ""),
        "continuation_policy": str(
            execution.get("continuation_policy") or "return_to_model"
        ),
        "retry": dict(execution.get("retry") or {}),
        "terminal_receipt": execution.get("terminal_receipt"),
    }


def _review_state(
    review: Mapping[str, object], provider_state: Mapping[str, object]
) -> Mapping[str, object]:
    if str(review.get("state") or "") == "recorded":
        disposition = str(review.get("disposition") or "")
        completeness = str(review.get("completeness") or "partial")
        state = {
            "approved": "satisfied",
            "findings": "remediation_required",
            "rejected": "findings_awaiting_triage",
        }.get(disposition, "in_progress")
        if disposition == "approved" and completeness != "complete":
            state = "evidence_incomplete"
        finding_ids = [str(item) for item in review.get("finding_ids", [])]
        return {
            "state": state,
            "workspace_review_id": str(review.get("workspace_review_id") or ""),
            "workspace_candidate_id": str(review.get("workspace_candidate_id") or ""),
            "candidate_revision": str(review.get("candidate_revision") or ""),
            "provider_review_ref": str(review.get("provider_review_ref") or ""),
            "completeness": completeness,
            "disposition": disposition,
            "finding_ids": finding_ids[:_ITEM_REFERENCE_LIMIT],
            "finding_ids_truncated": len(finding_ids) > _ITEM_REFERENCE_LIMIT,
        }
    if str(provider_state.get("state") or "") == "technically_satisfied":
        return {"state": "not_started"}
    return {"state": "not_applicable"}


def _milestone_summary(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {"state": "not_active"}
    return {
        "state": "active",
        "milestone_id": str(value.get("milestone_id") or ""),
        "name": str(value.get("name") or ""),
        "status": str(value.get("status") or ""),
    }


def _change_summary(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {"state": "not_active"}
    return {
        "state": "active",
        "change_id": str(value.get("change_id") or ""),
        "title": str(value.get("title") or ""),
        "status": str(value.get("status") or ""),
        "current_revision": int(value.get("current_revision") or 0),
    }


def _packet_summary(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {"state": "not_active"}
    return {
        "state": "active",
        "packet_id": str(value.get("packet_id") or ""),
        "title": str(value.get("title") or ""),
        "status": str(value.get("status") or ""),
        "readiness_state": str(value.get("readiness_state") or ""),
        "spec_revision": int(value.get("spec_revision") or 0),
        "state_revision": int(value.get("state_revision") or 0),
    }


def _campaign_summary(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {"state": "not_active"}
    return {
        "state": "active",
        "campaign_id": str(value.get("campaign_id") or ""),
        "status": str(value.get("status") or ""),
        "qualification": str(value.get("qualification") or ""),
        "constructibility": str(value.get("constructibility") or ""),
        "case_count": int(value.get("case_count") or len(value.get("cases", []))),
        "completed": bool(value.get("completed")),
        "lifecycle_gate": dict(value.get("lifecycle_gate") or {}),
    }


def _campaign_is_accepted(value: Mapping[str, object]) -> bool:
    if str(value.get("qualification") or "") != "current":
        return False
    gate = value.get("lifecycle_gate")
    if not isinstance(gate, Mapping):
        return False
    status = str(value.get("status") or "")
    gate_state = str(gate.get("state") or "")
    return gate_state == "accepted" or (
        status == "accepted_exception" and gate_state == "inactive"
    )


def _snapshot_detail_ref(
    project_id: str, focus_kind: str, focus_ref: str
) -> Mapping[str, object]:
    return {
        "tool": "fow_handover",
        "operation": "project_state_snapshot",
        "arguments": {
            "project_id": project_id,
            "focus_kind": focus_kind,
            "focus_ref": focus_ref,
        },
    }


def _open_decisions(
    action: Mapping[str, object] | None,
) -> list[Mapping[str, object]]:
    if action is None:
        return []
    decision_class = str(
        action.get("decision_class") or action.get("execution_class") or ""
    )
    if decision_class not in {"semantic", "governed_decision"}:
        return []
    return [
        {
            "action_id": _action_identity(action),
            "decision_class": decision_class,
            "required_inputs": [
                str(item) for item in action.get("required_inputs", [])
            ],
            "reason": str(action.get("reason") or action.get("rationale") or ""),
        }
    ]


def _dedupe_mappings(values: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
