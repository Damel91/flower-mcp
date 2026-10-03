"""Deterministic milestones, phase audits and evidence-derived next work."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable, Any, Mapping, Protocol

from flow_of_work_mcp.core.domain import (
    ActionExecutionClass,
    LifecyclePolicy,
    LifecycleStatus,
    MilestoneDraft,
    NextAction,
    NextActionKind,
    PhaseAudit,
    PhaseAuditScope,
    PhaseChangeType,
    PhaseRequirementDelta,
    PhaseRequirementSnapshot,
    PACKET_INACTIVE_STATUS_VALUES,
    PACKET_TERMINAL_STATUS_VALUES,
    ValidationAuditRecord,
    ValidationDisposition,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.core.ports import (
    AssuranceRepository,
    ChangeControlRepository,
    ExecutionRunRepository,
    GoalGraphRepository,
    GroundingAuditRepository,
    LifecycleControlRepository,
    RequirementLedger,
)


_PHASE_CHANGE_ORDER = (
    PhaseChangeType.ADDED,
    PhaseChangeType.CHANGED,
    PhaseChangeType.REMOVED,
    PhaseChangeType.IMPLEMENTED,
    PhaseChangeType.PARTIALLY_IMPLEMENTED,
    PhaseChangeType.UNVERIFIED,
    PhaseChangeType.BLOCKED,
)


class _CampaignAuthority(Protocol):
    def inspect(
        self,
        project_id: str,
        *,
        campaign_id: str = "",
        change_id: str = "",
        view: str = "summary",
        offset: int = 0,
        limit: int = 20,
    ) -> Mapping[str, object]: ...


class LifecycleControlService:
    """Coordinates lifecycle control using persisted state, not chat history."""

    def __init__(
        self,
        *,
        requirements: RequirementLedger,
        goals: GoalGraphRepository,
        grounding_audits: GroundingAuditRepository,
        control: LifecycleControlRepository,
        change_control: ChangeControlRepository | None = None,
        assurance: AssuranceRepository | None = None,
        campaign_authority: _CampaignAuthority | None = None,
        execution_runs: ExecutionRunRepository | None = None,
        policy: LifecyclePolicy | None = None,
        external_milestone_progress: Callable[[str, str], Mapping[str, object] | None] | None = None,
    ) -> None:
        self._requirements = requirements
        self._goals = goals
        self._grounding_audits = grounding_audits
        self._control = control
        self._change_control = change_control
        self._assurance = assurance
        self._campaign_authority = campaign_authority
        self._execution_runs = execution_runs
        self._policy = policy or LifecyclePolicy()
        self._external_milestone_progress = external_milestone_progress

    def promote_milestone(
        self,
        project_id: str,
        draft: MilestoneDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._control.promote_milestone(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def accept_milestone(
        self,
        project_id: str,
        milestone_id: str,
        *,
        acceptance_evidence: Iterable[str],
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        with self._control.atomic():
            return self._accept_milestone(project_id, milestone_id, acceptance_evidence=acceptance_evidence,
                                          actor=actor, request_id=request_id)

    def _accept_milestone(self, project_id: str, milestone_id: str, *,
                          acceptance_evidence: Iterable[str], actor: str,
                          request_id: str = "") -> Mapping[str, object]:
        progress = (self._external_milestone_progress(project_id, milestone_id)
                    if self._external_milestone_progress is not None else None)
        if progress is not None and not all(progress.get(key) for key in
            ("scope_complete", "implementation_complete", "local_verification_complete")):
            raise ChangeControlBlockedError("external_milestone_scope_incomplete",
                                            details={"milestone_id":milestone_id, "progress":dict(progress)})
        if progress is not None and any(obligation.get('state') != 'verified' for obligation in progress.get('deferred_obligations', [])):
            raise ChangeControlBlockedError('external_milestone_verification_pending',
                details={'milestone_id':milestone_id, 'deferred_obligations':progress['deferred_obligations']})
        evidence = tuple(
            required_text(item, "acceptance_evidence") for item in acceptance_evidence
        )
        if not evidence:
            raise ValueError("accept_milestone requires acceptance evidence")
        closure = self.milestone_closure_state(project_id, milestone_id)
        remaining_blockers = [
            blocker
            for blocker in closure.get("blockers", [])
            if isinstance(blocker, Mapping)
            and str(blocker.get("reason") or "")
            != "required_acceptance_evidence_missing"
        ]
        if remaining_blockers:
            raise ChangeControlBlockedError(
                "milestone_acceptance_blocked",
                details={"milestone_id": milestone_id, "blockers": remaining_blockers},
            )
        return self._control.accept_milestone(
            project_id,
            milestone_id,
            acceptance_evidence=evidence,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def record_validation(
        self,
        project_id: str,
        audit: ValidationAuditRecord,
        *,
        actor: str,
        request_id: str = "",
    ) -> ValidationAuditRecord:
        """Store a compact validation disposition for future phase decisions."""

        return self._control.record_validation_audit(
            project_id,
            audit,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def milestone_closure_state(
        self,
        project_id: str,
        milestone_id: str,
    ) -> Mapping[str, object]:
        """Return evidence-derived milestone closure blockers without mutating state."""

        milestones = {
            str(item["milestone_id"]): item
            for item in self._control.milestones(project_id)
        }
        if milestone_id not in milestones:
            raise ValueError(
                f"unknown milestone in project {project_id}: {milestone_id}"
            )
        milestone = milestones[milestone_id]
        requirement_ids = tuple(
            str(item) for item in milestone.get("requirement_ids", [])
        )
        blockers: list[Mapping[str, object]] = []
        linked_changes: list[Mapping[str, object]] = []
        if self._change_control is None:
            blockers.append(
                {"reason": "change_control_unconfigured", "scope": milestone_id}
            )
        else:
            linked_changes = [
                change
                for change in self._change_control.list_changes(project_id)
                if str(change.get("milestone_id") or "") == milestone_id
            ]
            covered_requirements = {
                str(requirement_id)
                for change in linked_changes
                for requirement_id in change.get("requirement_ids", [])
            }
            uncovered = sorted(set(requirement_ids).difference(covered_requirements))
            if uncovered:
                blockers.append(
                    {
                        "reason": "required_change_unit_missing",
                        "requirement_ids": uncovered,
                    }
                )
            for change in linked_changes:
                change_id = str(change["change_id"])
                packets = [
                    packet
                    for packet in change.get("packets", [])
                    if isinstance(packet, Mapping)
                ]
                if not packets:
                    blockers.append(
                        {"reason": "packet_missing", "change_id": change_id}
                    )
                    continue
                for packet in packets:
                    status = str(packet["status"])
                    packet_id = str(packet["packet_id"])
                    if status not in PACKET_TERMINAL_STATUS_VALUES:
                        blockers.append(
                            {
                                "reason": "packet_unresolved",
                                "change_id": change_id,
                                "packet_id": packet_id,
                                "status": status,
                                "readiness_state": str(
                                    packet.get("readiness_state") or ""
                                ),
                            }
                        )
                    if (
                        status not in PACKET_INACTIVE_STATUS_VALUES
                        and str(packet.get("target_policy") or "")
                        == "code_targets_required"
                        and str(packet.get("readiness_state") or "")
                        != "execution_ready"
                    ):
                        blockers.append(
                            {
                                "reason": "navigation_audit_blocker",
                                "change_id": change_id,
                                "packet_id": packet_id,
                                "readiness_state": str(
                                    packet.get("readiness_state") or ""
                                ),
                                "readiness_blockers": list(
                                    packet.get("readiness_blockers", [])
                                ),
                            }
                        )
        if self._assurance is not None:
            for change in linked_changes:
                change_id = str(change["change_id"])
                findings = self._assurance.findings_for_change(project_id, change_id)
                unresolved_findings = [
                    str(finding["finding_id"])
                    for finding in findings
                    if str(finding["disposition"]) in {"open", "confirmed", "deferred"}
                ]
                if unresolved_findings:
                    blockers.append(
                        {
                            "reason": "finding_unresolved",
                            "change_id": change_id,
                            "finding_ids": unresolved_findings,
                        }
                    )
                campaigns = self._assurance.campaigns_for_change(project_id, change_id)
                if not campaigns:
                    blockers.append(
                        {"reason": "campaign_missing", "change_id": change_id}
                    )
                elif self._campaign_authority is not None:
                    qualified = []
                    for campaign in campaigns:
                        projection = self._campaign_authority.inspect(
                            project_id,
                            campaign_id=str(campaign["campaign_id"]),
                            view="summary",
                        )
                        summary = projection.get("campaign")
                        gate = projection.get("lifecycle_gate")
                        if (
                            isinstance(summary, Mapping)
                            and str(summary.get("qualification") or "") == "current"
                            and isinstance(gate, Mapping)
                        ):
                            qualified.append(projection)
                    authoritative = [
                        item
                        for item in qualified
                        if str(item["campaign"].get("status") or "") != "cancelled"
                    ]
                    if not authoritative:
                        blockers.append(
                            {
                                "reason": "qualified_campaign_missing",
                                "change_id": change_id,
                            }
                        )
                    else:
                        not_green = [
                            str(item["campaign"].get("campaign_id") or "")
                            for item in authoritative
                            if not _qualified_campaign_is_accepted(item)
                        ]
                        if not_green:
                            blockers.append(
                                {
                                    "reason": "campaign_not_green",
                                    "change_id": change_id,
                                    "campaign_ids": not_green,
                                }
                            )
                else:
                    not_green = [
                        str(campaign["campaign_id"])
                        for campaign in campaigns
                        if str(campaign["status"])
                        not in {"passed", "accepted_exception"}
                    ]
                    if not_green:
                        blockers.append(
                            {
                                "reason": "campaign_not_green",
                                "change_id": change_id,
                                "campaign_ids": not_green,
                            }
                        )
        if not milestone.get("acceptance_evidence"):
            blockers.append(
                {
                    "reason": "required_acceptance_evidence_missing",
                    "scope": milestone_id,
                }
            )
        return {
            "project_id": project_id,
            "milestone_id": milestone_id,
            "acceptance_state": "ready_for_acceptance" if not blockers else "blocked",
            "linked_change_ids": [
                str(change["change_id"]) for change in linked_changes
            ],
            "blockers": blockers,
        }

    def audit_phase(
        self,
        project_id: str,
        scope: PhaseAuditScope,
        *,
        actor: str,
        request_id: str = "",
    ) -> PhaseAudit:
        """Record a project/scope delta without applying a lifecycle transition."""

        matrix = self._requirements.traceability_matrix(project_id)
        current_rows = self._select_scope(matrix, scope)
        previous = self._control.latest_phase_audit(project_id, scope.scope_id)
        if previous is not None:
            previous_scope = tuple(
                str(item) for item in previous["scope_requirement_ids"]
            )
            if previous_scope != scope.requirement_ids:
                raise ValueError(
                    "phase audit scope_id cannot be reused with a different requirement set"
                )
        previous_snapshots = {
            str(item["requirement_id"]): item
            for item in (previous or {}).get("snapshots", [])
            if isinstance(item, Mapping)
        }
        snapshots = tuple(self._snapshot_from_row(row) for row in current_rows)
        current_by_id = {snapshot.requirement_id: snapshot for snapshot in snapshots}
        deltas = self._derive_deltas(current_by_id, previous_snapshots)
        audit = PhaseAudit(
            project_id=project_id,
            scope=scope,
            previous_audit_id=(
                None if previous is None else int(previous["phase_audit_id"])
            ),
            snapshots=snapshots,
            deltas=deltas,
            policy_version=self._policy.version,
        )
        return self._control.record_phase_audit(
            audit,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def what_next(
        self,
        project_id: str,
        *,
        scope_id: str = "project-default",
    ) -> tuple[NextAction, ...]:
        """Return an ordered action set derived only from project-scoped evidence."""

        matrix = self._requirements.traceability_matrix(project_id)
        actions: list[NextAction] = []
        for row in matrix:
            requirement_id = str(row["requirement_id"])
            lifecycle_status = LifecycleStatus(str(row["lifecycle_status"]))
            verification = dict(row.get("verification") or {})
            outcomes = set(value for value in verification.values() if value)
            if "failed" in outcomes:
                actions.append(
                    self._action(
                        action_id=f"repair-verification:{requirement_id}",
                        kind=NextActionKind.REPAIR_FAILED_VERIFICATION,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=10,
                        rationale="latest verification evidence contains a failed outcome",
                        requirement_ids=(requirement_id,),
                    )
                )
            if lifecycle_status == LifecycleStatus.PARTIAL:
                actions.append(
                    self._action(
                        action_id=f"resolve-partial:{requirement_id}",
                        kind=NextActionKind.RESOLVE_PARTIAL_REQUIREMENT,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=20,
                        rationale="requirement lifecycle state is partial",
                        requirement_ids=(requirement_id,),
                    )
                )
            elif lifecycle_status == LifecycleStatus.PLANNED:
                actions.append(
                    self._action(
                        action_id=f"implement:{requirement_id}",
                        kind=NextActionKind.IMPLEMENT_REQUIREMENT,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=50,
                        rationale="requirement is planned and has no implemented lifecycle state",
                        requirement_ids=(requirement_id,),
                    )
                )
            if (
                lifecycle_status
                in {LifecycleStatus.IMPLEMENTED, LifecycleStatus.PARTIAL}
                and "passed" not in outcomes
            ):
                actions.append(
                    self._action(
                        action_id=f"collect-evidence:{requirement_id}",
                        kind=NextActionKind.COLLECT_VERIFICATION_EVIDENCE,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=30,
                        rationale="implemented behavior has no passing verification evidence",
                        requirement_ids=(requirement_id,),
                    )
                )

        graph = self._goals.goal_graph(project_id)
        for candidate in graph.get("requirement_candidates", []):
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("status") != "proposed"
            ):
                continue
            candidate_id = str(candidate["candidate_id"])
            actions.append(
                self._action(
                    action_id=f"review-candidate:{candidate_id}",
                    kind=NextActionKind.REVIEW_REQUIREMENT_CANDIDATE,
                    execution_class=ActionExecutionClass.GOVERNED_DECISION,
                    priority=70,
                    rationale="a Goal Graph-derived requirement candidate remains proposed",
                    goal_node_ids=(str(candidate["source_goal_id"]),),
                    candidate_ids=(candidate_id,),
                )
            )

        grounding = self._grounding_audits.grounding_audits(project_id)
        if grounding:
            latest_grounding = grounding[-1]
            grounding_audit_id = int(latest_grounding["audit_id"])
            for item in latest_grounding.get("items", []):
                if not isinstance(item, Mapping):
                    continue
                divergence = str(item.get("divergence") or "")
                if divergence == "converged":
                    continue
                goal_node_id = str(item.get("goal_node_id") or "")
                if divergence == "requirement_stale_candidate":
                    kind = NextActionKind.REVIEW_REQUIREMENT_CANDIDATE
                    execution_class = ActionExecutionClass.GOVERNED_DECISION
                    priority = 15
                else:
                    kind = NextActionKind.RESOLVE_GROUNDING_DIVERGENCE
                    execution_class = ActionExecutionClass.ORCHESTRATION
                    priority = 12
                actions.append(
                    self._action(
                        action_id=f"grounding:{grounding_audit_id}:{divergence}:{goal_node_id or 'anchor'}",
                        kind=kind,
                        execution_class=execution_class,
                        priority=priority,
                        rationale=f"latest intention-grounding audit reports {divergence}",
                        requirement_ids=tuple(
                            str(value) for value in item.get("requirement_ids", [])
                        ),
                        goal_node_ids=(goal_node_id,) if goal_node_id else (),
                        audit_ids=(grounding_audit_id,),
                    )
                )

        rejected_by_source: dict[str, Mapping[str, object]] = {}
        for validation in self._control.validation_audits(project_id):
            if validation.get("disposition") == ValidationDisposition.REJECTED.value:
                rejected_by_source[str(validation["source_ref"])] = validation
        for validation in rejected_by_source.values():
            validation_id = int(validation["validation_audit_id"])
            actions.append(
                self._action(
                    action_id=f"validation:{validation_id}",
                    kind=NextActionKind.RESOLVE_VALIDATION_FINDINGS,
                    execution_class=ActionExecutionClass.ORCHESTRATION,
                    priority=5,
                    rationale="latest recorded validation for a source is rejected",
                    audit_ids=(validation_id,),
                )
            )

        actions.extend(self._milestone_native_actions(project_id))

        for milestone in self._control.milestones(project_id):
            risk_disposition = str(milestone["risk_disposition"])
            if risk_disposition in {"accepted", "none"}:
                continue
            actions.append(
                self._action(
                    action_id=f"milestone-risk:{milestone['milestone_id']}",
                    kind=NextActionKind.REVIEW_MILESTONE_RISK,
                    execution_class=ActionExecutionClass.GOVERNED_DECISION,
                    priority=80,
                    rationale=f"milestone retains risk disposition {risk_disposition}",
                    requirement_ids=tuple(
                        str(value) for value in milestone["requirement_ids"]
                    ),
                    milestone_ids=(str(milestone["milestone_id"]),),
                )
            )

        if self._change_control is not None:
            actions.extend(self._packet_actions(project_id))
        if self._assurance is not None:
            actions.extend(self._assurance_actions(project_id))
        if self._execution_runs is not None:
            actions.extend(self._run_actions(project_id))

        if self._control.latest_phase_audit(project_id, scope_id) is None:
            actions.append(
                self._action(
                    action_id=f"phase-audit:{scope_id}",
                    kind=NextActionKind.RUN_PHASE_AUDIT,
                    execution_class=ActionExecutionClass.DETERMINISTIC,
                    priority=90,
                    rationale="no phase audit has yet established a baseline for this scope",
                )
            )
        return tuple(
            sorted(
                self._deduplicate(actions),
                key=lambda item: (item.priority, item.action_id),
            )
        )

    def _milestone_native_actions(self, project_id: str) -> list[NextAction]:
        actions: list[NextAction] = []
        if self._change_control is None:
            return actions
        changes = self._change_control.list_changes(project_id)
        milestones = tuple(self._control.milestones(project_id))
        entry_states = {
            str(item["milestone_id"]): self._milestone_entry_state(item, milestones)
            for item in milestones
        }
        for milestone in milestones:
            milestone_id = str(milestone["milestone_id"])
            if str(milestone.get("status") or "") == "accepted":
                continue
            if entry_states[milestone_id]["state"] != "eligible":
                continue
            requirement_ids = tuple(
                str(item) for item in milestone.get("requirement_ids", [])
            )
            linked_changes = [
                change
                for change in changes
                if str(change.get("milestone_id") or "") == milestone_id
            ]
            covered_requirements = {
                str(requirement_id)
                for change in linked_changes
                for requirement_id in change.get("requirement_ids", [])
            }
            uncovered = tuple(
                sorted(set(requirement_ids).difference(covered_requirements))
            )
            if uncovered:
                actions.append(
                    self._action(
                        action_id=f"milestone-change:{milestone_id}",
                        kind=NextActionKind.CREATE_MILESTONE_CHANGE,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=25,
                        rationale="milestone has requirements not covered by a linked change unit",
                        requirement_ids=uncovered,
                        milestone_ids=(milestone_id,),
                    )
                )
        return actions

    def milestone_entry_policy_diagnostics(
        self, project_id: str
    ) -> list[Mapping[str, object]]:
        milestones = tuple(self._control.milestones(project_id))
        diagnostics: list[Mapping[str, object]] = []
        for milestone in milestones:
            state = self._milestone_entry_state(milestone, milestones)
            if state["state"] != "eligible":
                diagnostics.append(state)
        return diagnostics

    @staticmethod
    def _milestone_entry_state(
        milestone: Mapping[str, object],
        milestones: tuple[Mapping[str, object], ...],
    ) -> Mapping[str, object]:
        milestone_id = str(milestone.get("milestone_id") or "")
        policy = milestone.get("entry_policy")
        if not isinstance(policy, Mapping):
            policy = {}
        raw_required = policy.get("requires_milestone", [])
        if not isinstance(raw_required, list):
            return {
                "milestone_id": milestone_id,
                "state": "blocked",
                "code": "invalid_requires_milestone_policy",
                "required_milestone_ids": [],
                "blocked_milestone_ids": [],
                "unknown_milestone_ids": [],
            }
        required = tuple(
            str(item).strip() for item in raw_required if str(item).strip()
        )
        by_id = {str(item.get("milestone_id") or ""): item for item in milestones}
        unknown = tuple(item for item in required if item not in by_id)
        blocked = tuple(
            item
            for item in required
            if item in by_id and str(by_id[item].get("status") or "") != "accepted"
        )
        if unknown:
            code = "unknown_required_milestone"
        elif blocked:
            code = "required_milestone_not_accepted"
        else:
            code = "entry_policy_satisfied"
        return {
            "milestone_id": milestone_id,
            "state": "eligible" if not unknown and not blocked else "blocked",
            "code": code,
            "required_milestone_ids": list(required),
            "blocked_milestone_ids": list(blocked),
            "unknown_milestone_ids": list(unknown),
        }

    def _packet_actions(self, project_id: str) -> list[NextAction]:
        actions: list[NextAction] = []
        for change in self._change_control.list_changes(project_id):
            change_id = str(change["change_id"])
            packets = {
                str(packet["packet_id"]): packet
                for packet in change.get("packets", [])
                if isinstance(packet, Mapping)
            }
            if not packets:
                actions.append(
                    self._action(
                        action_id=f"change-packet-graph:{change_id}",
                        kind=NextActionKind.RESOLVE_CHANGE_PACKET_GRAPH,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=42,
                        rationale="change unit has no implementation packets",
                        requirement_ids=tuple(
                            str(item) for item in change.get("requirement_ids", [])
                        ),
                        change_ids=(change_id,),
                    )
                )
                continue
            ready_count = 0
            unresolved_count = 0
            for packet_id, packet in packets.items():
                status = str(packet["status"])
                if status in PACKET_INACTIVE_STATUS_VALUES:
                    continue
                if status == "planned" and self._packet_dependencies_satisfied(
                    packet, packets
                ):
                    ready_count += 1
                    readiness_state = str(packet.get("readiness_state") or "")
                    rationale = (
                        "packet is execution_ready; start implementation/run work, then campaign or acceptance gates remain separate"
                        if readiness_state == "execution_ready"
                        else "packet is planned and dependency predicates are satisfied"
                    )
                    actions.append(
                        self._action(
                            action_id=f"implement-packet:{change_id}:{packet_id}",
                            kind=NextActionKind.IMPLEMENT_PACKET,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=40,
                            rationale=rationale,
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            packet_ids=(packet_id,),
                        )
                    )
                elif status == "partial" and packet.get("blocking_reasons"):
                    ready_count += 1
                    actions.append(
                        self._action(
                            action_id=f"resolve-packet-blocker:{change_id}:{packet_id}",
                            kind=NextActionKind.RESOLVE_PACKET_BLOCKER,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=22,
                            rationale="packet is partial and retains explicit blockers",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            packet_ids=(packet_id,),
                        )
                    )
                unresolved_count += 1
            if unresolved_count and not ready_count:
                actions.append(
                    self._action(
                        action_id=f"change-packet-graph:{change_id}",
                        kind=NextActionKind.RESOLVE_CHANGE_PACKET_GRAPH,
                        execution_class=ActionExecutionClass.ORCHESTRATION,
                        priority=45,
                        rationale="change unit has unresolved packet work but no ready packet",
                        requirement_ids=tuple(
                            str(item) for item in change.get("requirement_ids", [])
                        ),
                        change_ids=(change_id,),
                    )
                )
        return actions

    def _run_actions(self, project_id: str) -> list[NextAction]:
        actions: list[NextAction] = []
        if self._change_control is None:
            return actions
        for change in self._change_control.list_changes(project_id):
            change_id = str(change["change_id"])
            runs = self._execution_runs.runs_for_change(project_id, change_id)
            runs_by_packet: dict[str, list[Mapping[str, object]]] = {}
            for run in runs:
                run_packet_id = str(run["packet_id"])
                packet = _packet_by_id(change, run_packet_id)
                if str(packet["status"]) in PACKET_INACTIVE_STATUS_VALUES:
                    continue
                runs_by_packet.setdefault(run_packet_id, []).append(run)
                view = self._execution_runs.task_view(project_id, str(run["run_id"]))
                for blocked in view.get("blocked_steps", []):
                    if not isinstance(blocked, Mapping):
                        continue
                    actions.append(
                        self._action(
                            action_id=f"resolve-run-blocker:{run['run_id']}:{blocked['step_id']}",
                            kind=NextActionKind.RESOLVE_RUN_BLOCKER,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=16,
                            rationale="implementation run has a blocked step",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            packet_ids=(str(run["packet_id"]),),
                            run_ids=(str(run["run_id"]),),
                            step_ids=(str(blocked["step_id"]),),
                        )
                    )
                for ready in view.get("ready_steps", []):
                    if not isinstance(ready, Mapping):
                        continue
                    actions.append(
                        self._action(
                            action_id=f"execute-run-step:{run['run_id']}:{ready['step_id']}",
                            kind=NextActionKind.EXECUTE_RUN_STEP,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=41,
                            rationale="implementation run has a ready step",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            packet_ids=(str(run["packet_id"]),),
                            run_ids=(str(run["run_id"]),),
                            step_ids=(str(ready["step_id"]),),
                        )
                    )
                if str(run["status"]) == "completed":
                    if str(packet["status"]) != "implemented":
                        actions.append(
                            self._action(
                                action_id=f"close-packet-after-run:{run['run_id']}",
                                kind=NextActionKind.CLOSE_PACKET_AFTER_RUN,
                                execution_class=ActionExecutionClass.ORCHESTRATION,
                                priority=23,
                                rationale="run is complete but packet closure evidence is not recorded",
                                requirement_ids=tuple(
                                    str(item)
                                    for item in change.get("requirement_ids", [])
                                ),
                                change_ids=(change_id,),
                                packet_ids=(str(run["packet_id"]),),
                                run_ids=(str(run["run_id"]),),
                            )
                        )
            for packet in change.get("packets", []):
                if not isinstance(packet, Mapping):
                    continue
                packet_id = str(packet["packet_id"])
                if str(packet["status"]) in PACKET_INACTIVE_STATUS_VALUES:
                    continue
                if packet_id not in runs_by_packet:
                    actions.append(
                        self._action(
                            action_id=f"start-run:{change_id}:{packet_id}",
                            kind=NextActionKind.START_IMPLEMENTATION_RUN,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=39,
                            rationale="packet has no implementation run",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            packet_ids=(packet_id,),
                        )
                    )
            if str(change["status"]) == "accepted":
                actions.append(
                    self._action(
                        action_id=f"projection:{change_id}",
                        kind=NextActionKind.CREATE_LIFECYCLE_PROJECTION,
                        execution_class=ActionExecutionClass.DETERMINISTIC,
                        priority=60,
                        rationale="accepted change can be summarized through a ledger projection",
                        requirement_ids=tuple(
                            str(item) for item in change.get("requirement_ids", [])
                        ),
                        change_ids=(change_id,),
                    )
                )
        return actions

    def _assurance_actions(self, project_id: str) -> list[NextAction]:
        actions: list[NextAction] = []
        if self._change_control is None:
            return actions
        for change in self._change_control.list_changes(project_id):
            change_id = str(change["change_id"])
            findings = self._assurance.findings_for_change(project_id, change_id)
            campaigns = self._assurance.campaigns_for_change(project_id, change_id)
            unresolved_findings = []
            for finding in findings:
                disposition = str(finding["disposition"])
                finding_id = str(finding["finding_id"])
                if disposition in {"open", "confirmed", "deferred"}:
                    unresolved_findings.append(finding_id)
                    kind = (
                        NextActionKind.TRIAGE_FINDING
                        if disposition == "open"
                        else NextActionKind.RESOLVE_FINDING
                    )
                    actions.append(
                        self._action(
                            action_id=f"{kind.value}:{change_id}:{finding_id}",
                            kind=kind,
                            execution_class=ActionExecutionClass.ORCHESTRATION,
                            priority=_finding_priority(
                                str(finding.get("severity") or "info"),
                                disposition,
                            ),
                            rationale=(
                                f"{str(finding.get('severity') or 'info')} finding "
                                f"disposition is {disposition}"
                            ),
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            finding_ids=(finding_id,),
                        )
                    )
            qualified: list[Mapping[str, object]] = []
            for campaign in campaigns:
                status = str(campaign["status"])
                campaign_id = str(campaign["campaign_id"])
                if self._campaign_authority is None:
                    if status in {"planned", "partial"}:
                        actions.append(
                            self._action(
                                action_id=f"run-campaign:{change_id}:{campaign_id}",
                                kind=NextActionKind.RUN_VERIFICATION_CAMPAIGN,
                                execution_class=ActionExecutionClass.ORCHESTRATION,
                                priority=24,
                                rationale=f"campaign state is {status}",
                                requirement_ids=tuple(
                                    str(item)
                                    for item in change.get("requirement_ids", [])
                                ),
                                change_ids=(change_id,),
                                campaign_ids=(campaign_id,),
                            )
                        )
                    elif status == "failed":
                        actions.append(
                            self._action(
                                action_id=f"repair-campaign:{change_id}:{campaign_id}",
                                kind=NextActionKind.REPAIR_FAILED_CAMPAIGN,
                                execution_class=ActionExecutionClass.ORCHESTRATION,
                                priority=9,
                                rationale="campaign has failed evidence",
                                requirement_ids=tuple(
                                    str(item)
                                    for item in change.get("requirement_ids", [])
                                ),
                                change_ids=(change_id,),
                                campaign_ids=(campaign_id,),
                            )
                        )
                    continue
                projection = self._campaign_authority.inspect(
                    project_id, campaign_id=campaign_id, view="summary"
                )
                summary = projection.get("campaign")
                gate = projection.get("lifecycle_gate")
                if (
                    not isinstance(summary, Mapping)
                    or str(summary.get("qualification") or "") != "current"
                    or not isinstance(gate, Mapping)
                ):
                    continue
                if str(summary.get("status") or "") != "cancelled":
                    qualified.append(projection)
                if str(gate.get("state") or "") in {"accepted", "inactive"}:
                    continue
                route = gate.get("next_action")
                route = dict(route) if isinstance(route, Mapping) else {}
                decision = gate.get("decision_required")
                decision_kind = (
                    str(decision.get("kind") or "")
                    if isinstance(decision, Mapping)
                    else ""
                )
                failed = decision_kind == "product_failure_route"
                gate_state = str(gate.get("state") or "semantic_decision")
                execution_class = {
                    "mechanical_progress": ActionExecutionClass.DETERMINISTIC,
                    "semantic_decision": ActionExecutionClass.GOVERNED_DECISION,
                }.get(gate_state, ActionExecutionClass.ORCHESTRATION)
                actions.append(
                    self._action(
                        action_id=(
                            f"repair-campaign:{change_id}:{campaign_id}"
                            if failed
                            else f"campaign-gate:{change_id}:{campaign_id}:"
                            f"{route.get('operation') or gate_state}"
                        ),
                        kind=(
                            NextActionKind.REPAIR_FAILED_CAMPAIGN
                            if failed
                            else NextActionKind.RUN_VERIFICATION_CAMPAIGN
                        ),
                        execution_class=execution_class,
                        priority=9 if failed else 24,
                        rationale=(
                            str(gate.get("semantic_effect") or "")
                            or f"qualified campaign gate is {gate_state}"
                        ),
                        requirement_ids=tuple(
                            str(item) for item in change.get("requirement_ids", [])
                        ),
                        change_ids=(change_id,),
                        campaign_ids=(campaign_id,),
                        tool=str(route.get("tool") or "fow_campaign_inspect"),
                        operation=str(route.get("operation") or "summary"),
                        arguments=dict(route.get("arguments") or {}),
                        state=gate_state,
                        decision_class=execution_class.value,
                    )
                )
            if str(change["status"]) == "implemented" and not unresolved_findings:
                if self._campaign_authority is not None and not qualified:
                    actions.append(
                        self._action(
                            action_id=f"campaign-start:{change_id}",
                            kind=NextActionKind.RUN_VERIFICATION_CAMPAIGN,
                            execution_class=ActionExecutionClass.GOVERNED_DECISION,
                            priority=24,
                            rationale="implemented change has no qualified verification campaign",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                            tool="fow_campaign_author",
                            operation="start",
                            arguments={"scope": {"change_id": change_id}},
                            state="semantic_decision",
                            decision_class=ActionExecutionClass.GOVERNED_DECISION.value,
                        )
                    )
                elif (
                    self._campaign_authority is None
                    and campaigns
                    and all(
                        str(campaign["status"]) in {"passed", "accepted_exception"}
                        for campaign in campaigns
                    )
                ) or (
                    qualified
                    and all(_qualified_campaign_is_accepted(item) for item in qualified)
                ):
                    actions.append(
                        self._action(
                            action_id=f"accept-change:{change_id}",
                            kind=NextActionKind.REQUEST_CHANGE_ACCEPTANCE,
                            execution_class=ActionExecutionClass.GOVERNED_DECISION,
                            priority=34,
                            rationale="change is implemented and assurance evidence is green",
                            requirement_ids=tuple(
                                str(item) for item in change.get("requirement_ids", [])
                            ),
                            change_ids=(change_id,),
                        )
                    )
        return actions

    @staticmethod
    def _packet_dependencies_satisfied(
        packet: Mapping[str, object],
        packets: Mapping[str, Mapping[str, object]],
    ) -> bool:
        for dependency_id in tuple(
            str(item) for item in packet.get("dependency_packet_ids", [])
        ):
            dependency = packets[dependency_id]
            status = str(dependency["status"])
            if status == "implemented":
                continue
            if status == "superseded" and str(
                dependency.get("successor_packet_id") or ""
            ):
                continue
            if status == "cancelled" and str(dependency.get("disposition") or ""):
                continue
            return False
        return True

    def _select_scope(
        self,
        matrix: list[Mapping[str, Any]],
        scope: PhaseAuditScope,
    ) -> list[Mapping[str, Any]]:
        if not scope.requirement_ids:
            return matrix
        rows_by_id = {str(row["requirement_id"]): row for row in matrix}
        missing = sorted(set(scope.requirement_ids).difference(rows_by_id))
        if missing:
            raise ValueError(
                f"phase audit scope has unknown requirements: {', '.join(missing)}"
            )
        return [rows_by_id[requirement_id] for requirement_id in scope.requirement_ids]

    @staticmethod
    def _snapshot_from_row(row: Mapping[str, Any]) -> PhaseRequirementSnapshot:
        return PhaseRequirementSnapshot(
            requirement_id=str(row["requirement_id"]),
            revision=int(row["current_revision"]),
            lifecycle_status=str(row["lifecycle_status"]),
            verification=dict(row.get("verification") or {}),
            evidence_ids=tuple(
                int(item["evidence_id"]) for item in row.get("evidence", [])
            ),
        )

    def _derive_deltas(
        self,
        current: Mapping[str, PhaseRequirementSnapshot],
        previous: Mapping[str, Mapping[str, Any]],
    ) -> tuple[PhaseRequirementDelta, ...]:
        deltas: list[PhaseRequirementDelta] = []
        for requirement_id in sorted(set(current).union(previous)):
            previous_snapshot = previous.get(requirement_id)
            current_snapshot = current.get(requirement_id)
            if current_snapshot is None:
                deltas.append(
                    PhaseRequirementDelta(
                        requirement_id=requirement_id,
                        change_types=(PhaseChangeType.REMOVED,),
                    )
                )
                continue
            change_types: set[PhaseChangeType] = set()
            previous_evidence = set()
            if previous_snapshot is None:
                change_types.add(PhaseChangeType.ADDED)
            else:
                if int(previous_snapshot["revision"]) != current_snapshot.revision:
                    change_types.add(PhaseChangeType.CHANGED)
                previous_evidence = {
                    int(value) for value in previous_snapshot.get("evidence_ids", [])
                }
            lifecycle_status = LifecycleStatus(current_snapshot.lifecycle_status)
            if lifecycle_status == LifecycleStatus.REMOVED:
                change_types.add(PhaseChangeType.REMOVED)
            elif lifecycle_status == LifecycleStatus.IMPLEMENTED:
                change_types.add(PhaseChangeType.IMPLEMENTED)
            elif lifecycle_status == LifecycleStatus.PARTIAL:
                change_types.add(PhaseChangeType.PARTIALLY_IMPLEMENTED)
            outcomes = set(
                value for value in current_snapshot.verification.values() if value
            )
            if "passed" not in outcomes:
                change_types.add(PhaseChangeType.UNVERIFIED)
            if "failed" in outcomes:
                change_types.add(PhaseChangeType.BLOCKED)
            evidence_added_ids = tuple(
                sorted(set(current_snapshot.evidence_ids).difference(previous_evidence))
            )
            if change_types or evidence_added_ids:
                deltas.append(
                    PhaseRequirementDelta(
                        requirement_id=requirement_id,
                        change_types=tuple(
                            item for item in _PHASE_CHANGE_ORDER if item in change_types
                        )
                        or (PhaseChangeType.CHANGED,),
                        evidence_added_ids=evidence_added_ids,
                    )
                )
        return tuple(deltas)

    def _action(
        self,
        *,
        action_id: str,
        kind: NextActionKind,
        execution_class: ActionExecutionClass,
        priority: int,
        rationale: str,
        requirement_ids: tuple[str, ...] = (),
        goal_node_ids: tuple[str, ...] = (),
        candidate_ids: tuple[str, ...] = (),
        milestone_ids: tuple[str, ...] = (),
        change_ids: tuple[str, ...] = (),
        packet_ids: tuple[str, ...] = (),
        finding_ids: tuple[str, ...] = (),
        campaign_ids: tuple[str, ...] = (),
        run_ids: tuple[str, ...] = (),
        step_ids: tuple[str, ...] = (),
        audit_ids: tuple[int, ...] = (),
        tool: str = "",
        operation: str = "",
        arguments: Mapping[str, object] | None = None,
        required_inputs: tuple[str, ...] = (),
        state: str = "pending",
        decision_class: str = "",
    ) -> NextAction:
        automatic_eligible = (
            execution_class == ActionExecutionClass.DETERMINISTIC
            and self._policy.allows_automatic(kind)
        )
        return NextAction(
            action_id=action_id,
            kind=kind,
            execution_class=execution_class,
            priority=priority,
            rationale=rationale,
            requirement_ids=requirement_ids,
            goal_node_ids=goal_node_ids,
            candidate_ids=candidate_ids,
            milestone_ids=milestone_ids,
            change_ids=change_ids,
            packet_ids=packet_ids,
            finding_ids=finding_ids,
            campaign_ids=campaign_ids,
            run_ids=run_ids,
            step_ids=step_ids,
            audit_ids=audit_ids,
            automatic_eligible=automatic_eligible,
            tool=tool,
            operation=operation,
            arguments=dict(arguments or {}),
            required_inputs=required_inputs,
            state=state,
            decision_class=decision_class,
        )

    @staticmethod
    def _deduplicate(actions: Iterable[NextAction]) -> tuple[NextAction, ...]:
        by_id: dict[str, NextAction] = {}
        for action in actions:
            by_id.setdefault(action.action_id, action)
        return tuple(by_id.values())


def _packet_by_id(change: Mapping[str, object], packet_id: str) -> Mapping[str, object]:
    for packet in change.get("packets", []):
        if isinstance(packet, Mapping) and packet.get("packet_id") == packet_id:
            return packet
    raise ValueError(f"unknown packet in change: {packet_id}")


def _finding_priority(severity: str, disposition: str) -> int:
    severity_base = {
        "critical": 3,
        "high": 6,
        "medium": 16,
        "low": 27,
        "info": 36,
    }.get(str(severity or "info").strip().lower(), 36)
    disposition_offset = {
        "confirmed": 0,
        "open": 1,
        "deferred": 8,
    }.get(str(disposition or "open").strip().lower(), 8)
    return severity_base + disposition_offset


def _qualified_campaign_is_accepted(
    projection: Mapping[str, object],
) -> bool:
    campaign = projection.get("campaign")
    gate = projection.get("lifecycle_gate")
    if not isinstance(campaign, Mapping) or not isinstance(gate, Mapping):
        return False
    status = str(campaign.get("status") or "")
    gate_state = str(gate.get("state") or "")
    return gate_state == "accepted" or (
        status == "accepted_exception" and gate_state == "inactive"
    )
