"""Derived milestone-scoped traceability projections."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.ports import (
    AssuranceRepository,
    ChangeControlRepository,
    ExecutionRunRepository,
    GroundingAuditRepository,
    LifecycleControlRepository,
    NavigationAuditRepository,
    PacketConstructionRepository,
    PacketPressureRepository,
    RequirementLedger,
)
from flow_of_work_mcp.core.ports.artifacts import LedgerVersionReader
from flow_of_work_mcp.application.grounding_readiness import (
    live_grounding_readiness,
)
from flow_of_work_mcp.core.domain import PACKET_INACTIVE_STATUS_VALUES, PacketStatus
from flow_of_work_mcp.core.domain.external_work import fingerprint


class MilestoneTraceabilityProjectionService:
    """Build read-only lifecycle projections from canonical ledger state."""

    def __init__(
        self,
        *,
        requirements: RequirementLedger,
        lifecycle: LifecycleControlRepository,
        changes: ChangeControlRepository,
        navigation: NavigationAuditRepository,
        assurance: AssuranceRepository,
        execution_runs: ExecutionRunRepository,
        ledger_versions: LedgerVersionReader,
        grounding_audits: GroundingAuditRepository,
        construction: PacketConstructionRepository | None = None,
        pressure: PacketPressureRepository | None = None,
        external_work=None,
    ) -> None:
        self._requirements = requirements
        self._lifecycle = lifecycle
        self._changes = changes
        self._navigation = navigation
        self._assurance = assurance
        self._runs = execution_runs
        self._ledger_versions = ledger_versions
        self._grounding_audits = grounding_audits
        self._construction = construction
        self._pressure = pressure
        self._external_work = external_work

    def progress(self, project_id: str, *, milestone_ids: tuple[str, ...]) -> Mapping[str, object]:
        """Count declared criterion scope; host reports never grant acceptance."""
        if not isinstance(milestone_ids, (tuple, list)) or not 1 <= len(milestone_ids) <= 128:
            raise ValueError('milestone_ids must explicitly select 1..128 canonical milestones')
        if any(not isinstance(identity, str) or not identity.strip() or identity != identity.strip() for identity in milestone_ids):
            raise ValueError('milestone_ids must contain canonical nonempty identities')
        if len(set(milestone_ids)) != len(milestone_ids):
            raise ValueError('milestone_ids must be unique')
        selected = tuple(sorted(milestone_ids))
        with self._requirements.consistent_read():
            return self._progress(project_id, selected)

    def _progress(self, project_id: str, selected: tuple[str, ...]) -> Mapping[str, object]:
        milestones_by_id = {str(m['milestone_id']): m for m in self._lifecycle.milestones(project_id)}
        missing = set(selected) - milestones_by_id.keys()
        if missing:
            raise ValueError('unknown milestone_ids: ' + ', '.join(sorted(missing)))
        requirements = {str(r['requirement_id']): r for r in self._requirements.traceability_matrix(project_id)}
        changes = self._changes.list_changes(project_id)
        criteria_by_identity = {}
        packet_basis = {}
        milestone_basis = []
        all_gaps = []
        milestone_rows = []
        for identity in selected:
            milestone = milestones_by_id[identity]
            requirement_ids = set(milestone.get('requirement_ids', [])) | set(milestone.get('dependency_closure_ids', []))
            gaps = []
            milestone_basis.append({k: milestone.get(k) for k in ('milestone_id', 'name', 'requirement_ids',
                'dependency_closure_ids', 'entry_policy', 'exit_policy', 'risk_disposition')})
            semantic_requirements = []
            for requirement_id in sorted(requirement_ids):
                requirement = requirements.get(requirement_id)
                if requirement is None:
                    gaps.append({'code': 'milestone_requirement_missing', 'requirement_id': requirement_id})
                    semantic_requirements.append({'requirement_id': requirement_id, 'missing': True})
                    continue
                history = self._requirements.requirement_history(project_id, requirement_id)
                revision = next(r for r in history['revisions'] if r['revision'] == requirement['current_revision'])
                retired = requirement['lifecycle_status'] == 'removed'
                semantic_requirements.append({**{k: requirement.get(k) for k in ('requirement_id', 'current_revision',
                    'title', 'statement', 'category', 'source_anchor')}, 'rationale': revision['rationale'], 'retired': retired})
                if retired:
                    gaps.append({'code': 'milestone_requirement_retired', 'requirement_id': requirement_id})
            milestone_basis[-1]['requirements'] = semantic_requirements
            linked_changes = [change for change in changes if str(change.get('milestone_id') or '') == identity]
            packet_rows = []
            scoped_criteria = {}
            covered = set()
            for change in linked_changes:
                for packet in change.get('packets', []):
                    if packet['status'] in {'superseded', 'cancelled'}:
                        continue
                    packet_id = str(packet['packet_id'])
                    covered.update(packet.get('requirement_ids') or change.get('requirement_ids', []))
                    if self._external_work is None:
                        gaps.append({'code': 'external_work_unavailable', 'packet_id': packet_id})
                        continue
                    detail = self._external_work.criterion_progress(project_id, str(change['change_id']), packet_id)
                    packet_basis[packet_id] = detail['authority_basis']
                    packet_rows.append({k: detail[k] for k in ('packet_id', 'packet_status', 'consumption_mode',
                        'spec_revision', 'plan_revision', 'authority_fingerprint', 'scope_complete', 'gaps')})
                    if not detail['scope_complete']:
                        gaps.extend({'packet_id': packet_id, **gap} for gap in detail['gaps'])
                    for criterion in detail['criteria']:
                        key = (packet_id, criterion['number'])
                        scoped_criteria[key] = criterion
                        criteria_by_identity[key] = criterion
            for requirement_id in sorted(requirement_ids - covered):
                gaps.append({'code': 'milestone_requirement_unplanned', 'requirement_id': requirement_id})
            if not scoped_criteria:
                gaps.append({'code': 'milestone_criterion_scope_unplanned'})
            scope_complete = not gaps
            criteria = [scoped_criteria[key] for key in sorted(scoped_criteria)]
            deferred = [obligation for criterion in criteria for obligation in criterion['deferred_obligations']]
            implementation = _progress_counter(criteria, 'implementation_state', 'complete', scope_complete)
            verification = _progress_counter(criteria, 'local_verification_state', 'passed', scope_complete)
            accepted = _milestone_acceptance_projection(milestone)
            milestone_rows.append({'milestone_id': identity, 'name': milestone['name'], 'status': milestone['status'],
                'acceptance': accepted, 'scope_complete': scope_complete, 'gaps': gaps,
                'active_criteria': len(criteria), 'implementation': implementation, 'local_verification': verification,
                'criteria': criteria, 'packets': packet_rows, 'deferred_obligations': deferred,
                'implementation_complete': scope_complete and implementation['completed'] == implementation['total'],
                'local_verification_complete': scope_complete and verification['completed'] == verification['total'],
                'fully_completed': scope_complete and implementation['completed'] == implementation['total']
                    and verification['completed'] == verification['total'] and not any(d['state'] != 'verified' for d in deferred)
                    and accepted['state'] == 'accepted'})
            all_gaps.extend({'milestone_id': identity, **gap} for gap in gaps)
        criteria = [criteria_by_identity[key] for key in sorted(criteria_by_identity)]
        complete = not all_gaps
        implementation = _progress_counter(criteria, 'implementation_state', 'complete', complete)
        verification = _progress_counter(criteria, 'local_verification_state', 'passed', complete)
        result = {'contract_version': 'flow.milestone_progress.v1', 'project_id': project_id,
            'milestone_ids': list(selected), 'scope_revision': fingerprint({'milestones': milestone_basis, 'packets': packet_basis}),
            'scope_complete': complete, 'gaps': all_gaps, 'active_criteria': len(criteria),
            'implementation': implementation, 'local_verification': verification,
            'deferred_obligations': [d for criterion in criteria for d in criterion['deferred_obligations']],
            'criteria': criteria, 'milestones': milestone_rows,
            'implementation_complete': complete and implementation['completed'] == implementation['total'],
            'local_verification_complete': complete and verification['completed'] == verification['total'],
            'fully_completed': all(row['fully_completed'] for row in milestone_rows), 'acceptance': 'not_inferred'}
        result['progress_revision'] = fingerprint(result)
        return result

    def projection(self, project_id: str, *, milestone_id: str = "") -> Mapping[str, object]:
        requirements = self._requirements.traceability_matrix(project_id)
        grounding_audits = self._grounding_audits.grounding_audits(project_id)
        requirements_by_id = {str(item["requirement_id"]): item for item in requirements}
        milestones = self._lifecycle.milestones(project_id)
        if milestone_id:
            milestones = [
                milestone
                for milestone in milestones
                if str(milestone["milestone_id"]) == milestone_id
            ]
            if not milestones:
                raise ValueError(f"unknown milestone in project {project_id}: {milestone_id}")

        changes = self._changes.list_changes(project_id)
        navigation_blocks = self._navigation.list_navigation_audits(project_id)
        rows: list[Mapping[str, object]] = []
        scoped_requirement_ids: set[str] = set()
        for milestone in milestones:
            for requirement_id in milestone.get("requirement_ids", []):
                requirement_id = str(requirement_id)
                scoped_requirement_ids.add(requirement_id)
                rows.append(
                    self._row(
                        project_id,
                        requirement=requirements_by_id.get(requirement_id, {"requirement_id": requirement_id}),
                        milestone=milestone,
                        changes=changes,
                        navigation_blocks=navigation_blocks,
                        grounding_audits=grounding_audits,
                    )
                )

        if not milestone_id:
            for requirement in requirements:
                requirement_id = str(requirement["requirement_id"])
                if requirement_id in scoped_requirement_ids:
                    continue
                rows.append(
                    self._row(
                        project_id,
                        requirement=requirement,
                        milestone=None,
                        changes=changes,
                        navigation_blocks=navigation_blocks,
                        grounding_audits=grounding_audits,
                    )
                )

        return {
            "project_id": project_id,
            "projection_kind": "milestone_traceability",
            "profile_version": "milestone-traceability-v1",
            "scope": "milestone" if milestone_id else "project",
            "milestone_id": milestone_id,
            "source_ledger_version": self._ledger_versions.ledger_version(project_id),
            "milestones": [
                {
                    "milestone_id": str(milestone["milestone_id"]),
                    "name": str(milestone["name"]),
                    "status": str(milestone["status"]),
                    "requirement_ids": [str(item) for item in milestone.get("requirement_ids", [])],
                }
                for milestone in milestones
            ],
            "rows": rows,
            "gaps": _dedupe_gaps(row for row in rows),
        }

    def _row(
        self,
        project_id: str,
        *,
        requirement: Mapping[str, object],
        milestone: Mapping[str, object] | None,
        changes: list[Mapping[str, object]],
        navigation_blocks: list[Mapping[str, object]],
        grounding_audits: list[Mapping[str, object]],
    ) -> Mapping[str, object]:
        requirement_id = str(requirement["requirement_id"])
        milestone_id = "" if milestone is None else str(milestone["milestone_id"])
        linked_changes = [
            change
            for change in changes
            if requirement_id in {str(item) for item in change.get("requirement_ids", [])}
            and (not milestone_id or str(change.get("milestone_id") or "") == milestone_id)
        ]
        packets = [
            packet
            for change in linked_changes
            for packet in change.get("packets", [])
            if isinstance(packet, Mapping)
        ]
        packet_ids = [str(packet["packet_id"]) for packet in packets]
        packet_runs = [
            run
            for change in linked_changes
            for run in self._runs.runs_for_change(project_id, str(change["change_id"]))
            if str(run.get("packet_id") or "") in packet_ids
        ]
        findings = [
            finding
            for change in linked_changes
            for finding in self._assurance.findings_for_change(project_id, str(change["change_id"]))
        ]
        campaigns = [
            campaign
            for change in linked_changes
            for campaign in self._assurance.campaigns_for_change(project_id, str(change["change_id"]))
        ]
        coverage = _coverage_projection(
            requirement_id,
            requirement,
            campaigns,
            grounding_audits=grounding_audits,
        )
        navs = [
            block
            for block in navigation_blocks
            if str(block.get("packet_id") or "") in packet_ids
        ]
        packet_summaries = [self._packet_summary(project_id, packet) for packet in packets]
        external_packets = {summary['packet_id']: summary['external_work'] for summary in packet_summaries if 'external_work' in summary}
        gaps = self._gaps(
            milestone=milestone,
            changes=linked_changes,
            packets=packets,
            navigation_blocks=navs,
            runs=packet_runs,
            findings=findings,
            campaigns=campaigns,
            external_packets=external_packets,
        )
        return {
            "requirement_id": requirement_id,
            "lifecycle_status": str(requirement.get("lifecycle_status") or ""),
            "verification": dict(requirement.get("verification") or {}),
            "milestone_acceptance": _milestone_acceptance_projection(milestone),
            "tested_deterministically": coverage["tested_deterministically"],
            "tested_live": coverage["tested_live"],
            "live_campaign_readiness": coverage["live_campaign_readiness"],
            "coverage_state": coverage["coverage_state"],
            "coverage_gaps": coverage["coverage_gaps"],
            "coverage_diagnostics": coverage["coverage_diagnostics"],
            "accepted_campaign_ids": coverage["accepted_campaign_ids"],
            "covered_use_case_goal_node_ids": coverage["covered_use_case_goal_node_ids"],
            "covered_sequence_goal_node_ids": coverage["covered_sequence_goal_node_ids"],
            "milestone_id": milestone_id,
            "change_ids": [str(change["change_id"]) for change in linked_changes],
            "packets": packet_summaries,
            "navigation_audits": [_navigation_summary(block) for block in navs],
            "runs": [_run_summary(run) for run in packet_runs],
            "findings": [_finding_summary(finding) for finding in findings],
            "campaigns": [_campaign_summary(campaign) for campaign in campaigns],
            "acceptance_blockers": gaps,
            "readiness_projection": _readiness_projection(packet_summaries, gaps),
            "evidence": _evidence_refs(requirement, findings, campaigns),
        }

    @staticmethod
    def _gaps(
        *,
        milestone: Mapping[str, object] | None,
        changes: list[Mapping[str, object]],
        packets: list[Mapping[str, object]],
        navigation_blocks: list[Mapping[str, object]],
        runs: list[Mapping[str, object]],
        findings: list[Mapping[str, object]],
        campaigns: list[Mapping[str, object]],
        external_packets: Mapping[str, Mapping[str, object]] | None = None,
    ) -> list[str]:
        gaps: list[str] = []
        if milestone is None:
            gaps.append("no_milestone_scope")
        if not packets:
            gaps.append("no_packet_for_requirement")
        for packet in packets:
            packet_status = str(packet.get("status") or "")
            if packet_status == PacketStatus.IDLE.value:
                gaps.append("packet_idle")
            if packet_status in PACKET_INACTIVE_STATUS_VALUES:
                continue
            external = (external_packets or {}).get(str(packet['packet_id']))
            if external is not None:
                if external.get('status') != 'success':
                    gaps.append('packet_not_external_execution_ready')
                continue
            if str(packet.get("readiness_state") or "") != "execution_ready":
                gaps.append("packet_not_execution_ready")
            if str(packet.get("target_policy") or "") == "code_targets_required":
                accepted = [
                    block
                    for block in navigation_blocks
                    if str(block.get("packet_id") or "") == str(packet["packet_id"])
                    and str(block.get("state") or "") == "accepted_for_packet"
                ]
                if not accepted:
                    gaps.append("navigation_audit_unresolved")
        if any(str(run.get("status") or "") not in {"completed", "cancelled"} for run in runs):
            gaps.append("run_incomplete")
        if any(
            str(finding.get("disposition") or "") in {"open", "confirmed", "deferred"}
            for finding in findings
        ):
            gaps.append("finding_unresolved")
        if changes and not campaigns:
            gaps.append("campaign_missing")
        if any(str(campaign.get("status") or "") not in {"passed", "accepted_exception"} for campaign in campaigns):
            gaps.append("campaign_not_accepted")
        if milestone is not None and not milestone.get("acceptance_evidence"):
            gaps.append("acceptance_evidence_missing")
        elif milestone is not None and str(milestone.get('status') or '') != 'accepted':
            gaps.append('milestone_not_accepted')
        return sorted(set(gaps))


    def _packet_summary(self, project_id: str, packet: Mapping[str, object]) -> Mapping[str, object]:
        change_id = str(packet.get("change_id") or "")
        packet_id = str(packet["packet_id"])
        construction = (
            self._construction.packet_construction_audit_for_packet(project_id, change_id, packet_id)
            if self._construction is not None and change_id
            else None
        )
        pressure = (
            self._pressure.latest_packet_pressure(project_id, change_id, packet_id)
            if self._pressure is not None and change_id
            else None
        )
        external = {}
        if self._external_work is not None and change_id and self._external_work.mode_for_packet(project_id, packet_id) == "external_agent":
            external = {"external_work": dict(self._external_work.todo(project_id, change_id, packet_id))}
        return {
            **external,
            "packet_id": packet_id,
            "status": str(packet["status"]),
            "readiness_state": str(packet.get("readiness_state") or ""),
            "target_policy": str(packet.get("target_policy") or ""),
            "readiness_blockers": [str(item) for item in packet.get("readiness_blockers", [])],
            "construction_audit_id": (
                "" if construction is None else str(construction.get("construction_audit_id") or "")
            ),
            "construction_audit_state": (
                "" if construction is None else str(construction.get("state") or "")
            ),
            "pressure_id": "" if pressure is None else str(pressure.get("pressure_id") or ""),
            "semantic_confidence": (
                "" if pressure is None else str(pressure.get("semantic_confidence") or "")
            ),
            "improvement_pressure": (
                "" if pressure is None else str(pressure.get("improvement_pressure") or "")
            ),
            "residual_risk_count": (
                0 if pressure is None else len(list(pressure.get("residual_risks", [])))
            ),
            "accepted_risk_count": (
                0 if pressure is None else len(list(pressure.get("accepted_risk_refs", [])))
            ),
        }


def _navigation_summary(block: Mapping[str, object]) -> Mapping[str, object]:
    provider_candidate_set_ids: list[str] = []
    for candidate_set in block.get("candidate_sets", []):
        if not isinstance(candidate_set, Mapping):
            continue
        metadata = candidate_set.get("metadata") if isinstance(candidate_set, Mapping) else {}
        if isinstance(metadata, Mapping):
            provider_id = str(
                metadata.get("provider_candidate_set_id")
                or metadata.get("candidate_target_set_id")
                or metadata.get("provider_origin_id")
                or ""
            ).strip()
            if provider_id:
                provider_candidate_set_ids.append(provider_id)
    return {
        "navigation_audit_id": str(block["navigation_audit_id"]),
        "packet_id": str(block.get("packet_id") or ""),
        "state": str(block.get("state") or ""),
        "candidate_set_ids": [
            str(item["candidate_set_id"])
            for item in block.get("candidate_sets", [])
            if isinstance(item, Mapping)
        ],
        "target_binding_ids": [
            str(item["binding_id"])
            for item in block.get("target_bindings", [])
            if isinstance(item, Mapping)
        ],
        "provider_candidate_set_ids": sorted(set(provider_candidate_set_ids)),
        "provider_snapshot_ids": [
            str(item["snapshot_id"])
            for item in block.get("provider_navigation_snapshots", [])
            if isinstance(item, Mapping)
        ],
    }


def _run_summary(run: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "run_id": str(run["run_id"]),
        "packet_id": str(run.get("packet_id") or ""),
        "status": str(run.get("status") or ""),
    }


def _finding_summary(finding: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "finding_id": str(finding["finding_id"]),
        "disposition": str(finding.get("disposition") or ""),
    }


def _campaign_summary(campaign: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "campaign_id": str(campaign["campaign_id"]),
        "status": str(campaign.get("status") or ""),
        "cases": [
            {
                "case_id": str(case.get("case_id") or ""),
                "case_kind": str(case.get("case_kind") or ""),
                "normalized_case_kind": str(case.get("normalized_case_kind") or ""),
                "result": str(case.get("result") or ""),
                "covered_requirement_ids": [
                    str(item) for item in case.get("covered_requirement_ids", [])
                ],
                "covered_use_case_goal_node_ids": [
                    str(item) for item in case.get("covered_use_case_goal_node_ids", [])
                ],
                "covered_sequence_goal_node_ids": [
                    str(item) for item in case.get("covered_sequence_goal_node_ids", [])
                ],
            }
            for case in campaign.get("cases", [])
            if isinstance(case, Mapping)
        ],
    }


def _milestone_acceptance_projection(
    milestone: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if milestone is None:
        return {"state": "not_scoped", "evidence": []}
    evidence = [str(item) for item in milestone.get("acceptance_evidence", [])]
    return {
        "state": "accepted" if evidence and milestone.get('status') == 'accepted' else "pending" if evidence else "missing",
        "evidence": evidence,
    }


def _progress_counter(criteria, field: str, complete_state: str, scope_complete: bool):
    applicable = [criterion for criterion in criteria if criterion[field] != 'not_applicable']
    completed = sum(criterion[field] == complete_state for criterion in applicable)
    percent = None
    if scope_complete and applicable:
        percent = 100 if completed == len(applicable) else min(99.99, round(100 * completed / len(applicable), 2))
    return {'completed': completed, 'total': len(applicable),
        'percent': percent,
        'not_applicable': len(criteria) - len(applicable), 'provenance': 'host_reported',
        'label': 'Host-reported implementation' if field == 'implementation_state' else 'Host-reported local verification'}


def _coverage_projection(
    requirement_id: str,
    requirement: Mapping[str, object],
    campaigns: list[Mapping[str, object]],
    *,
    grounding_audits: list[Mapping[str, object]],
) -> Mapping[str, object]:
    verification = dict(requirement.get("verification") or {})
    tested_deterministically = str(verification.get("tested_deterministically") or "")
    tested_live = str(verification.get("tested_live") or "")
    accepted_campaign_ids: set[str] = set()
    covered_use_case_ids: set[str] = set()
    covered_sequence_ids: set[str] = set()
    coverage_gaps: set[str] = set()
    diagnostics: list[Mapping[str, object]] = []
    grounding_projections: list[Mapping[str, object]] = []
    covering_cases = []
    for campaign in campaigns:
        campaign_id = str(campaign.get("campaign_id") or "")
        accepted = str(campaign.get("status") or "") in {"passed", "accepted_exception"}
        for event in campaign.get("events", []):
            if not isinstance(event, Mapping):
                continue
            if str(event.get("event_type") or "") == "coverage_diagnostic_recorded":
                payload = event.get("payload")
                if isinstance(payload, Mapping):
                    diagnostics.append(dict(payload))
        for case in campaign.get("cases", []):
            if not isinstance(case, Mapping):
                continue
            covered_requirements = {str(item) for item in case.get("covered_requirement_ids", [])}
            if requirement_id not in covered_requirements:
                continue
            covering_cases.append(case)
            if accepted:
                accepted_campaign_ids.add(campaign_id)
            normalized = str(case.get("normalized_case_kind") or "")
            result = str(case.get("result") or "")
            use_case_ids = [str(item) for item in case.get("covered_use_case_goal_node_ids", [])]
            sequence_ids = [str(item) for item in case.get("covered_sequence_goal_node_ids", [])]
            covered_use_case_ids.update(use_case_ids)
            covered_sequence_ids.update(sequence_ids)
            if normalized == "tool_smoke":
                coverage_gaps.add("tool_smoke_only")
            if normalized == "live_sequence":
                if not use_case_ids:
                    coverage_gaps.add("use_case_coverage_missing")
                if not sequence_ids:
                    coverage_gaps.add("sequence_coverage_missing")
                if use_case_ids and sequence_ids:
                    grounding = live_grounding_readiness(
                        project_id="",
                        goal_node_ids=tuple(use_case_ids + sequence_ids),
                        audits=grounding_audits,
                    )
                    grounding_projections.append(grounding)
                    for gap in grounding.get("gaps", []):
                        coverage_gaps.add(str(gap))
                if result != "passed":
                    coverage_gaps.add("live_campaign_ready_not_executed")
    if campaigns and not covering_cases:
        coverage_gaps.add("campaign_coverage_missing")
    grounding_projection = _select_grounding_projection(grounding_projections)
    grounding_ready = bool(grounding_projection.get("ready")) if grounding_projection else False
    if tested_live == "passed" and grounding_ready:
        readiness = "already_live_tested"
        coverage_state = "live_verified"
        coverage_gaps.discard("live_campaign_ready_not_executed")
    elif tested_live == "passed":
        readiness = str(
            grounding_projection.get("state")
            if grounding_projection
            else "needs_implementation_projection"
        )
        coverage_state = "live_verified_projection_gap"
        coverage_gaps.add("implementation_grounding_missing")
    elif any(
        str(case.get("normalized_case_kind") or "") == "live_sequence"
        for case in covering_cases
    ):
        readiness = (
            "ready_for_live_campaign"
            if grounding_ready
            else str(
                grounding_projection.get("state")
                if grounding_projection
                else "needs_implementation_projection"
            )
        )
        coverage_state = "live_scope_declared"
    elif covering_cases:
        readiness = "needs_live_sequence_coverage"
        coverage_state = "deterministic_or_smoke_only"
    else:
        readiness = "needs_campaign_scope"
        coverage_state = "missing"
    return {
        "tested_deterministically": tested_deterministically,
        "tested_live": tested_live,
        "live_campaign_readiness": {
            "ready": readiness == "ready_for_live_campaign",
            "state": readiness,
            "grounding": grounding_projection,
        },
        "coverage_state": coverage_state,
        "coverage_gaps": sorted(coverage_gaps),
        "coverage_diagnostics": diagnostics,
        "accepted_campaign_ids": sorted(accepted_campaign_ids),
        "covered_use_case_goal_node_ids": sorted(covered_use_case_ids),
        "covered_sequence_goal_node_ids": sorted(covered_sequence_ids),
    }


def _select_grounding_projection(
    projections: list[Mapping[str, object]],
) -> Mapping[str, object]:
    if not projections:
        return {}
    for projection in projections:
        if projection.get("ready"):
            return projection
    return projections[-1]


def _evidence_refs(
    requirement: Mapping[str, object],
    findings: list[Mapping[str, object]],
    campaigns: list[Mapping[str, object]],
) -> list[str]:
    refs: list[str] = []
    for item in requirement.get("evidence", []):
        if isinstance(item, Mapping):
            reference = str(item.get("reference") or "")
            if reference:
                refs.append(reference)
    for finding in findings:
        refs.extend(str(item) for item in finding.get("evidence_refs", []))
    for campaign in campaigns:
        for case in campaign.get("cases", []):
            if isinstance(case, Mapping):
                reference = str(case.get("evidence_reference") or "")
                if reference:
                    refs.append(reference)
    return sorted(set(refs))


def _readiness_projection(
    packets: list[Mapping[str, object]],
    gaps: list[str],
) -> Mapping[str, object]:
    packet_readiness_blockers = [
        gap
        for gap in gaps
        if gap in {"packet_not_execution_ready", "packet_not_external_execution_ready", "navigation_audit_unresolved"}
    ]
    acceptance_blockers = [gap for gap in gaps if gap not in set(packet_readiness_blockers)]
    active_packets = [
        packet
        for packet in packets
        if str(packet.get("status") or "") not in PACKET_INACTIVE_STATUS_VALUES
    ]
    execution_ready_packets = [
        str(packet.get("packet_id") or "")
        for packet in active_packets
        if (packet.get('external_work', {}).get('status') == 'success' if 'external_work' in packet
            else str(packet.get("readiness_state") or "") == "execution_ready")
    ]
    return {
        "execution_ready_packet_ids": execution_ready_packets,
        "all_packets_execution_ready": bool(active_packets)
        and len(execution_ready_packets) == len(active_packets),
        "packet_readiness_blockers": sorted(set(packet_readiness_blockers)),
        "acceptance_blockers": sorted(set(acceptance_blockers)),
        "note": (
            "packet execution readiness is distinct from milestone/project acceptance"
            if execution_ready_packets and acceptance_blockers
            else ""
        ),
    }


def _dedupe_gaps(rows: object) -> list[Mapping[str, object]]:
    gaps: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for gap in row.get("acceptance_blockers", []):
            gaps.setdefault(str(gap), set()).add(str(row["requirement_id"]))
    return [
        {"reason": reason, "requirement_ids": sorted(requirement_ids)}
        for reason, requirement_ids in sorted(gaps.items())
    ]
