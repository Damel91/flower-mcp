"""Bounded single-packet lifecycle projection for orchestrators."""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from typing import Mapping

from flow_of_work_mcp.application.packet_construction import PacketConstructionService
from flow_of_work_mcp.application.packet_guards import (
    PacketGuardService,
)
from flow_of_work_mcp.application.packet_next_action import (
    PacketNextActionProjectionService,
)
from flow_of_work_mcp.application.packet_work_plan import PacketWorkPlanService
from flow_of_work_mcp.core.ports import (
    AssuranceRepository,
    ChangeControlRepository,
)


class PacketLifecycleProjectionService:
    """Build a bounded projection without exposing the complete change aggregate."""

    def __init__(
        self,
        *,
        changes: ChangeControlRepository,
        assurance: AssuranceRepository,
        work_plans: PacketWorkPlanService,
        construction: PacketConstructionService,
        guards: PacketGuardService,
        next_actions: PacketNextActionProjectionService,
        reviews,
        reconciliation,
        packet_provider_overlay,
        external_work=None,
        consistent_reads=None,
    ) -> None:
        self._changes = changes
        self._assurance = assurance
        self._work_plans = work_plans
        self._construction = construction
        self._guards = guards
        self._next_actions = next_actions
        self._reviews = reviews
        self._reconciliation = reconciliation
        self._packet_provider_overlay = packet_provider_overlay
        self._external_work = external_work
        self._consistent_reads = consistent_reads

    def get_packet(
        self, project_id: str, change_id: str, packet_id: str, *,
        detail_level: str = "standard", view: str = "summary",
        offset: int = 0, limit: int = 20,
    ) -> Mapping[str, object]:
        context = self._consistent_reads.consistent_read() if self._consistent_reads is not None else nullcontext()
        with context:
            return self._get_packet(project_id, change_id, packet_id, detail_level=detail_level,
                                    view=view, offset=offset, limit=limit)

    def _get_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        detail_level: str = "standard",
        view: str = "summary",
        offset: int = 0,
        limit: int = 20,
    ) -> Mapping[str, object]:
        detail = str(detail_level or "standard").strip().lower()
        if detail not in {"standard", "verbose"}:
            raise ValueError("detail_level must be standard or verbose")
        view = str(view or "summary").strip().lower()
        if view not in {
            "summary",
            "units",
            "gates",
            "working_sheet",
            "history",
            "requirements",
        }:
            raise ValueError(
                "view must be summary, units, gates, working_sheet, history or requirements"
            )
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 100))
        change = self._changes.change_state(project_id, change_id)
        packet = _packet_by_id(change, packet_id)
        work_plan_result = self._work_plans.get_plan(
            project_id,
            change_id,
            packet_id,
            detail_level=(
                "verbose" if detail == "verbose" or view == "history" else "standard"
            ),
        )
        work_plan = work_plan_result.get("plan")
        construction_audit = self._construction.audit_for_packet(
            project_id,
            change_id,
            packet_id,
        )
        findings = _linked_findings(
            self._assurance.findings_for_change(project_id, change_id), packet_id
        )
        spec_revision = int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        )
        provider_plan = work_plan
        if detail != "verbose":
            provider_plan = self._work_plans.get_plan(
                project_id,
                change_id,
                packet_id,
                detail_level="verbose",
            ).get("plan")
        external_mode = self._external_work is not None and self._external_work.mode_for_packet(
            project_id, packet_id
        ) == "external_agent"
        if external_mode:
            provider_projection = {"technical": {"state": "not_applicable"},
                                   "consumption_mode": "external_agent"}
        else:
            provider_projection = self._packet_provider_overlay.projection(
                project_id, change_id, packet_id, packet=packet,
                work_plan=(provider_plan if isinstance(provider_plan, Mapping) else None),
            )
        provider_binding = _mapping(
            _mapping(provider_projection.get("technical")).get("binding")
        )
        workspace_review = self._reviews.latest_workspace_review(
            project_id,
            change_id,
            packet_id,
            spec_revision,
            provider_kind=str(provider_binding.get("provider_kind") or ""),
            provider_packet_ref=str(
                provider_binding.get("provider_packet_ref") or ""
            ),
            provider_packet_revision=int(
                provider_binding.get("provider_packet_revision") or 0
            ),
            binding_epoch=int(provider_binding.get("binding_epoch") or 0),
            event_seq=int(provider_binding.get("event_seq") or 0),
            provider_job_ref=str(provider_binding.get("provider_job_ref") or ""),
        )
        provider_receipts = self._changes.packet_provider_receipts(
            project_id, change_id, packet_id, limit=100
        )
        provider_outbox = self._changes.packet_provider_outbox_entries(
            project_id, change_id, packet_id, limit=100
        )
        guard = self._guards.evaluate(project_id, change_id, packet_id)
        next_action = self._next_actions.project(
            guard,
            project_id=project_id,
            change_id=change_id,
            packet_id=packet_id,
            spec_revision=int(
                packet.get("spec_revision")
                or packet.get("current_revision")
                or 0
            ),
            plan_revision=(
                int(work_plan.get("plan_revision") or 0)
                if isinstance(work_plan, Mapping)
                else 0
            ),
        )
        reconciliation = (
            self._reconciliation.packet_reconciliation_for_packet(
                project_id, change_id, packet_id
            )
            or {}
        )
        gate = _lifecycle_gate(
            packet=packet,
            work_plan=work_plan,
            construction=construction_audit,
            reconciliation=reconciliation,
            guard=guard,
            next_action=next_action,
        )
        result: dict[str, object] = {
            "scope": {
                "project_id": project_id,
                "change_id": change_id,
                "packet_id": packet_id,
            },
            "packet": _packet_projection(packet, detail),
            "execution": _execution_projection(provider_projection),
            "workspace_review": _workspace_review_projection(workspace_review),
            "lifecycle_states": {
                "packet": str(packet.get("status") or ""),
                "execution": str(
                    _mapping(provider_projection.get("technical")).get("state")
                    or "provider_pending"
                ),
                "workspace": _workspace_state(provider_projection, workspace_review),
                "validation": "not_recorded",
                "apply_readiness": "not_evaluated",
            },
            "next_action": next_action,
            "gate": gate,
            "engineering_questions": _construction_projection(
                construction_audit,
                detail,
            ),
            "summary": {
                "work_plan_status": (
                    str(work_plan.get("status") or "")
                    if isinstance(work_plan, Mapping)
                    else "missing"
                ),
                "unit_count": (
                    len(work_plan.get("units", []))
                    if isinstance(work_plan, Mapping)
                    else 0
                ),
                "finding_count": len(findings),
                "provider_receipt_count": len(provider_receipts),
                "target_count": len(packet.get("target_binding_ids", [])),
            },
            "view": view,
            "detail_level": detail,
        }
        result["packet_provider"] = provider_projection
        if external_mode:
            result["consumption_mode"] = "external_agent"
            result["external_work"] = self._external_work.todo(project_id, change_id, packet_id)
            result["execution"] = {"status": "not_applicable", "consumption_mode": "external_agent",
                                   "provenance": "host_supplied", "acceptance": "not_inferred"}
            result["lifecycle_states"].update({"execution": "external_agent", "workspace": "host_owned",
                                               "validation": guard.state, "apply_readiness": "host_owned"})
        result["lifecycle_states"]["provider"] = str(
            _mapping(provider_projection.get("technical")).get(
                "state", "provider_pending"
            )
        )
        if view == "units":
            units = (
                list(work_plan.get("units", []))
                if isinstance(work_plan, Mapping)
                else []
            )
            result["units"] = units[offset : offset + limit]
            result["pagination"] = _pagination(len(units), offset, limit)
        elif view == "gates":
            result["guards"] = guard.as_payload()
        elif view == "working_sheet":
            result["working_sheet"] = _working_sheet(
                packet=packet,
                work_plan=work_plan,
                construction=construction_audit,
                reconciliation=reconciliation,
                gate=gate,
                offset=offset,
                limit=limit,
            )
        elif view == "history":
            events = _history_events(work_plan, provider_receipts, provider_outbox)
            result["events"] = events[offset : offset + limit]
            result["pagination"] = _pagination(len(events), offset, limit)
        elif view == "requirements":
            requirement_ids = [
                str(item) for item in packet.get("requirement_ids", []) if str(item)
            ]
            result["requirements"] = requirement_ids[offset : offset + limit]
            result["pagination"] = _pagination(
                len(requirement_ids), offset, limit
            )
        if detail == "verbose":
            result["relationships"] = {
                "predecessor_packet_ids": list(packet.get("dependency_packet_ids", [])),
                "dependent_packet_ids": list(packet.get("dependent_packet_ids", [])),
                "successor_packet_id": str(packet.get("successor_packet_id") or ""),
                "findings": findings,
            }
            result["active_targets"] = {
                "navigation_audit_ids": list(packet.get("navigation_audit_ids", [])),
                "target_binding_ids": list(packet.get("target_binding_ids", [])),
                "candidate_set_ids": list(packet.get("candidate_set_ids", [])),
                "context_snapshot_ids": list(packet.get("context_snapshot_ids", [])),
            }
        return result


def _packet_by_id(change: Mapping[str, object], packet_id: str) -> Mapping[str, object]:
    for packet in change.get("packets", []):
        if isinstance(packet, Mapping) and str(packet.get("packet_id") or "") == packet_id:
            return packet
    raise ValueError(f"unknown packet in change: {packet_id}")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _packet_projection(packet: Mapping[str, object], detail: str) -> Mapping[str, object]:
    base = {
        "packet_id": str(packet.get("packet_id") or ""),
        "title": str(packet.get("title") or ""),
        "purpose": str(packet.get("purpose") or "implementation"),
        "status": str(packet.get("status") or ""),
        "readiness_state": str(packet.get("readiness_state") or ""),
        "target_policy": str(packet.get("target_policy") or ""),
        "current_revision": int(packet.get("current_revision") or 0),
        "spec_revision": int(packet.get("spec_revision") or packet.get("current_revision") or 0),
        "state_revision": int(packet.get("state_revision") or 1),
        "objective": str(packet.get("objective") or ""),
        "completion_criteria": list(packet.get("completion_criteria", [])),
        "readiness_blockers": list(packet.get("readiness_blockers", [])),
        "blocking_reasons": list(packet.get("blocking_reasons", [])),
        "disposition": str(packet.get("disposition") or ""),
        "requirement_scope": {
            "count": len(packet.get("requirement_ids", [])),
            "sample": [
                str(item) for item in packet.get("requirement_ids", [])[:5]
            ],
            "truncated": len(packet.get("requirement_ids", [])) > 5,
        },
    }
    if detail == "verbose":
        base.update(
            {
                "rationale": str(packet.get("rationale") or ""),
                "goal_ids": list(packet.get("goal_ids", [])),
                "in_scope": list(packet.get("in_scope", [])),
                "out_of_scope": list(packet.get("out_of_scope", [])),
                "invariants": list(packet.get("invariants", [])),
                "unresolved_questions": list(packet.get("unresolved_questions", [])),
            }
        )
    return base


def _linked_findings(
    findings: list[Mapping[str, object]], packet_id: str
) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    for finding in findings:
        if not any(
            isinstance(link, Mapping) and str(link.get("packet_id") or "") == packet_id
            for link in finding.get("fixing_packets", [])
        ):
            continue
        result.append(
            {
                "finding_id": str(finding.get("finding_id") or ""),
                "title": str(finding.get("title") or ""),
                "severity": str(finding.get("severity") or ""),
                "disposition": str(finding.get("disposition") or ""),
                "expected_correction": str(finding.get("expected_correction") or ""),
            }
        )
    return result


def _construction_projection(
    audit: Mapping[str, object] | None,
    detail: str,
) -> Mapping[str, object]:
    if audit is None:
        return {
            "state": "not_started",
            "questions": [],
            "open_required_question_ids": [],
        }
    questions = [
        item
        for item in audit.get("questions", [])
        if isinstance(item, Mapping)
    ]
    visible = (
        questions
        if detail == "verbose"
        else [
            item
            for item in questions
            if bool(item.get("required"))
            and str(item.get("status") or "") in {"open", "blocked"}
        ]
    )
    projected: list[Mapping[str, object]] = []
    for item in visible:
        question = {
            "question_id": str(item.get("question_id") or ""),
            "category": str(item.get("category") or ""),
            "prompt": str(item.get("prompt") or ""),
            "required": bool(item.get("required")),
            "status": str(item.get("status") or ""),
        }
        if detail == "verbose":
            question["answer_summary"] = str(item.get("answer_summary") or "")
            question["blocker_reason"] = str(item.get("blocker_reason") or "")
            question["waiver_rationale"] = str(item.get("waiver_rationale") or "")
        projected.append(question)
    return {
        "construction_audit_id": str(audit.get("construction_audit_id") or ""),
        "state": str(audit.get("state") or ""),
        "questions": projected,
        "open_required_question_ids": [
            str(item.get("question_id") or "")
            for item in questions
            if bool(item.get("required"))
            and str(item.get("status") or "") in {"open", "blocked"}
        ],
    }


def _execution_projection(
    provider_projection: Mapping[str, object],
) -> Mapping[str, object]:
    technical = _mapping(provider_projection.get("technical"))
    binding = _mapping(technical.get("binding"))
    last_receipt = _mapping(technical.get("last_receipt"))
    receipt_technical = _mapping(last_receipt.get("technical"))
    status = str(technical.get("state") or "provider_pending")
    continuation_policy = str(
        receipt_technical.get("continuation_policy")
        or ("host_observe" if status == "provider_running" else "return_to_model")
    )
    terminal_receipt: Mapping[str, object] | None = None
    if bool(receipt_technical.get("terminal")):
        terminal_receipt = {
            "receipt_id": str(last_receipt.get("receipt_id") or ""),
            "provider_packet_revision": int(
                last_receipt.get("provider_packet_revision") or 0
            ),
            "provider_state": str(last_receipt.get("provider_state") or ""),
            "run_phase": str(receipt_technical.get("phase") or "idle"),
            "provider_job_ref": str(receipt_technical.get("job_ref") or ""),
            "retry": dict(_mapping(receipt_technical.get("retry"))),
        }
    return {
        "status": status,
        "provider_packet_ref": str(binding.get("provider_packet_ref") or ""),
        "provider_packet_revision": int(
            binding.get("provider_packet_revision") or 0
        ),
        "provider_job_ref": str(binding.get("provider_job_ref") or ""),
        "run_phase": str(binding.get("run_phase") or "idle"),
        "continuation_policy": continuation_policy,
        "retry": dict(_mapping(receipt_technical.get("retry"))),
        "terminal_receipt": terminal_receipt,
    }


def _workspace_state(
    provider_projection: Mapping[str, object],
    review: Mapping[str, object] | None,
) -> str:
    if review is not None:
        return f"review_{str(review.get('disposition') or 'recorded')}"
    technical = _mapping(provider_projection.get("technical"))
    return (
        "candidate_staged"
        if str(technical.get("state") or "") == "provider_technically_complete"
        else "not_staged"
    )


def _workspace_review_projection(
    review: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if review is None:
        return {"state": "not_recorded"}
    return {
        "state": "recorded",
        "workspace_review_id": str(review.get("workspace_review_id") or ""),
        "provider_kind": str(review.get("provider_kind") or ""),
        "provider_packet_ref": str(review.get("provider_packet_ref") or ""),
        "provider_packet_revision": int(
            review.get("provider_packet_revision") or 0
        ),
        "binding_epoch": int(review.get("binding_epoch") or 0),
        "event_seq": int(review.get("event_seq") or 0),
        "provider_job_ref": str(review.get("provider_job_ref") or ""),
        "provider_revision": str(review.get("provider_revision") or ""),
        "workspace_candidate_id": str(review.get("workspace_candidate_id") or ""),
        "candidate_revision": str(review.get("candidate_revision") or ""),
        "provider_review_ref": str(review.get("provider_review_ref") or ""),
        "completeness": str(review.get("completeness") or "partial"),
        "disposition": str(review.get("disposition") or ""),
        "reviewed_target_count": len(review.get("reviewed_target_refs", [])),
        "evidence_count": len(review.get("evidence_refs", [])),
        "existing_finding_ids": list(review.get("existing_finding_ids", [])),
        "finding_ids": list(review.get("normalized_finding_ids", [])),
    }


def _history_events(
    work_plan: object,
    receipts: list[Mapping[str, object]],
    outbox: list[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    events: list[Mapping[str, object]] = []
    if isinstance(work_plan, Mapping):
        for event in work_plan.get("events", []):
            if isinstance(event, Mapping):
                events.append(
                    {
                        "kind": "work_plan",
                        "event_type": str(event.get("event_type") or ""),
                        "occurred_at": str(event.get("occurred_at") or ""),
                        "request_id": str(event.get("request_id") or ""),
                    }
                )
    events.extend(
        {
            "kind": "packet_provider_command",
            "operation": str(item.get("operation") or ""),
            "state": str(item.get("state") or ""),
            "flow_unit_ref": str(item.get("flow_unit_ref") or ""),
            "occurred_at": str(item.get("updated_at") or item.get("created_at") or ""),
            "request_id": str(item.get("request_id") or ""),
        }
        for item in outbox
    )
    events.extend(
        {
            "kind": "packet_provider_receipt",
            "provider_packet_ref": str(item.get("provider_packet_ref") or ""),
            "provider_packet_revision": int(
                item.get("provider_packet_revision") or 0
            ),
            "provider_state": str(item.get("provider_state") or ""),
            "event_seq": int(item.get("event_seq") or 0),
            "occurred_at": str(item.get("observed_at") or ""),
            "request_id": str(item.get("request_id") or ""),
        }
        for item in receipts
    )
    events.sort(key=lambda item: str(item.get("occurred_at") or ""))
    return events


def _pagination(total: int, offset: int, limit: int) -> Mapping[str, object]:
    returned = max(0, min(limit, total - offset))
    next_offset = offset + returned
    return {
        "total": total,
        "returned": returned,
        "offset": offset,
        "limit": limit,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
    }


def _lifecycle_gate(
    *,
    packet: Mapping[str, object],
    work_plan: object,
    construction: Mapping[str, object] | None,
    reconciliation: Mapping[str, object],
    guard,
    next_action: Mapping[str, object],
) -> Mapping[str, object]:
    plan = work_plan if isinstance(work_plan, Mapping) else {}
    audit = construction if isinstance(construction, Mapping) else {}
    open_questions = [
        item
        for item in audit.get("questions", [])
        if isinstance(item, Mapping)
        and bool(item.get("required"))
        and str(item.get("status") or "") in {"open", "blocked"}
    ]
    current_question = open_questions[0] if open_questions else {}
    residual = _current_residual(reconciliation)
    decision_required, allowed_responses, semantic_effect = _gate_decision(
        guard.next_operation,
        current_question=current_question,
        residual=residual,
        has_units=bool(plan.get("units")),
        has_reconciliation_scope=bool(
            reconciliation.get("reconciliation_scope_id")
        ),
    )
    state = "semantic_decision"
    if str(next_action.get("decision_class") or "") == "mechanical":
        state = "mechanical_progress"
    if guard.next_operation == "packet_inactive":
        state = "inactive"
    if guard.next_operation == "resolve_reconciliation_residual":
        state = "reconciliation_residual"
    if guard.state == "provider_boundary" or str(next_action.get("tool") or "") == "external_provider":
        state = "provider_boundary"
    dependency_payload = {
        "packet_id": str(packet.get("packet_id") or ""),
        "spec_revision": int(
            packet.get("spec_revision") or packet.get("current_revision") or 0
        ),
        "plan_revision": int(plan.get("plan_revision") or 0),
        "next_operation": str(guard.next_operation),
        "question_dependency": str(
            current_question.get("dependency_fingerprint") or ""
        ),
        "reconciliation_applicability": str(
            reconciliation.get("applicability") or "not_applicable"
        ),
        "reconciliation_fingerprint": str(
            (reconciliation.get("latest_run") or {}).get("packet_fingerprint")
            if isinstance(reconciliation.get("latest_run"), Mapping)
            else ""
        ),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            dependency_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    action = dict(next_action)
    action["required_inputs"] = list(action.get("required_inputs", []))
    if guard.next_operation == "retry_or_remediate" and guard.semantic_decisions:
        arguments = dict(action.get("arguments") or {})
        arguments["finding_ids"] = list(guard.semantic_decisions[:20])
        action["arguments"] = arguments
    return {
        "contract": "flow.lifecycle_gate.v1",
        "subject": "packet",
        "state": state,
        "lifecycle_state": str(guard.state),
        "dependency_fingerprint": fingerprint,
        "known_facts": _known_facts(
            packet=packet,
            plan=plan,
            reconciliation=reconciliation,
            residual=residual,
        ),
        "decision_required": decision_required,
        "allowed_responses": allowed_responses,
        "semantic_effect": semantic_effect,
        "next_action": action,
    }


def _known_facts(
    *,
    packet: Mapping[str, object],
    plan: Mapping[str, object],
    reconciliation: Mapping[str, object],
    residual: Mapping[str, object],
) -> list[Mapping[str, object]]:
    facts: list[Mapping[str, object]] = [
        {
            "label": str(packet.get("title") or packet.get("packet_id") or "packet"),
            "fact": str(packet.get("objective") or "packet intent is not yet complete"),
            "source": "flow packet ledger",
            "freshness": "current",
        },
        {
            "label": "packet purpose",
            "fact": str(packet.get("purpose") or "implementation"),
            "source": "flow packet ledger",
            "freshness": "current",
        },
        {
            "label": "work plan",
            "fact": (
                f"{str(plan.get('status') or 'missing')}; "
                f"{len(plan.get('units', []))} authored units"
            ),
            "source": "flow work-plan ledger",
            "freshness": "current",
        },
    ]
    applicability = str(reconciliation.get("applicability") or "not_applicable")
    reason = str(reconciliation.get("applicability_reason") or "")
    facts.append(
        {
            "label": "packet evidence",
            "fact": applicability + (f": {reason}" if reason else ""),
            "source": "flow reconciliation policy",
            "freshness": "current",
        }
    )
    if residual:
        facts.append(
            {
                "label": str(residual.get("claim_key") or "evidence residual"),
                "fact": (
                    f"{str(residual.get('classification') or 'unresolved')}; "
                    f"closure: {str(residual.get('closure_condition') or 'new evidence required')}"
                ),
                "source": "current reconciliation run",
                "freshness": "current",
            }
        )
    return facts[:8]


def _gate_decision(
    operation: str,
    *,
    current_question: Mapping[str, object],
    residual: Mapping[str, object],
    has_units: bool,
    has_reconciliation_scope: bool,
) -> tuple[Mapping[str, object] | None, list[object], str]:
    if operation.startswith("external_"):
        return (
            {"kind": "external_agent_obligation", "question": "Inspect the standalone validation or TODO frontier and fulfill its explicit obligation."},
            ["inspect_current_frontier"],
            "Returns host work or an authority decision. Flower performs no repository execution and infers no acceptance.",
        )
    if operation == "packet_inactive":
        return (
            None,
            [],
            "Preserves read-only packet history; no lifecycle transition is scheduled.",
        )
    if operation == "packet_author":
        return (
            {
                "kind": "unit_authoring",
                "question": "What is the next bounded implementation unit?",
            },
            ["add_unit", *(("finish_authoring",) if has_units else ())],
            "Adds one immutable complete work-plan revision or submits the current plan for acceptance.",
        )
    if operation == "accept_work_plan":
        return (
            {
                "kind": "plan_disposition",
                "question": "Is the current proposed work plan ready to accept?",
            },
            ["accept_work_plan", "reject_work_plan"],
            "Accepts or rejects the current plan revision without changing its units.",
        )
    if operation == "answer_engineering_questions":
        category = str(current_question.get("category") or "")
        claim_translation_available = (
            has_reconciliation_scope
            and category in {"target_selection", "impact"}
        )
        optional_fields = ["evidence_refs", "rationale"]
        if claim_translation_available:
            optional_fields = [
                "classification",
                "subject_ref",
                "predicate",
                "object_ref",
                *optional_fields,
            ]
            required_fields = ["answer_summary", "temporal_authority"]
        else:
            required_fields = ["answer_summary"]
        return (
            {
                "kind": "engineering_question",
                "category": category,
                "question": str(
                    current_question.get("prompt")
                    or "Provide the current engineering decision."
                ),
            },
            [
                {
                    "kind": "typed_input",
                    "fields": required_fields,
                    "optional_fields": optional_fields,
                    **(
                        {
                            "accepted_values": {
                                "temporal_authority": [
                                    "current_fact",
                                    "future_instruction",
                                    "completion_evidence",
                                ]
                            }
                        }
                        if claim_translation_available
                        else {}
                    ),
                }
            ],
            (
                "Records one temporally bounded engineering decision; only a "
                "current_fact may translate its structured target or impact assertion "
                "into a current reconciliation claim."
                if claim_translation_available
                else "Records one current engineering decision without creating Flow-owned reconciliation claims."
            ),
        )
    if operation == "resolve_reconciliation_residual":
        proposal_responses = (
            ["accepted", "rejected"]
            if str(residual.get("classification") or "") == "proposed"
            else []
        )
        return (
            {
                "kind": "reconciliation_residual",
                "question": str(
                    residual.get("closure_condition")
                    or "How should the current evidence residual be handled?"
                ),
            },
            [*proposal_responses, "waived", "escalated", "investigate"],
            "Accepts or rejects a current proposal, records another authority disposition, or leaves investigation open for successor evidence.",
        )
    if operation == "decide_residual_risk":
        return (
            {
                "kind": "residual_risk",
                "question": "Should the current bounded residual risk be accepted?",
            },
            ["accept_residual_risk"],
            "Records an explicit accepted-risk reference; it does not change implementation evidence.",
        )
    if operation == "review_workspace":
        return (
            {
                "kind": "workspace_review",
                "question": "What is the disposition of the current workspace candidate?",
            },
            ["approved", "findings", "rejected"],
            "Records the workspace review receipt and any normalized findings.",
        )
    if operation == "retry_or_remediate":
        return (
            {
                "kind": "remediation_packet",
                "question": "Define the bounded remediation packet for the current findings.",
            },
            ["start_packet"],
            "Creates an ordinary remediation-purpose packet linked to the current findings.",
        )
    if operation == "record_verification":
        return (
            {
                "kind": "verification_campaign",
                "question": "Which verification campaign will prove this packet complete?",
            },
            ["start_campaign"],
            "Creates verification scope; it does not claim that testing has passed.",
        )
    if operation == "consume_verification":
        return (
            None,
            [],
            "Consumes the current completed packet-targeted campaign and closes the packet mechanically.",
        )
    return None, [], "Performs the next deterministic lifecycle transition without adding semantic facts."


def _current_residual(reconciliation: Mapping[str, object]) -> Mapping[str, object]:
    run = reconciliation.get("latest_run")
    if not isinstance(run, Mapping):
        return {}
    for item in run.get("items", []):
        if (
            isinstance(item, Mapping)
            and bool(item.get("blocking"))
            and str(item.get("disposition") or "")
            in {"open", "rejected", "escalated"}
        ):
            return item
    return {}


def _working_sheet(
    *,
    packet: Mapping[str, object],
    work_plan: object,
    construction: Mapping[str, object] | None,
    reconciliation: Mapping[str, object],
    gate: Mapping[str, object],
    offset: int,
    limit: int,
) -> Mapping[str, object]:
    plan = work_plan if isinstance(work_plan, Mapping) else {}
    audit = construction if isinstance(construction, Mapping) else {}
    units = [item for item in plan.get("units", []) if isinstance(item, Mapping)]
    decisions = [
        {
            "category": str(item.get("category") or ""),
            "question": str(item.get("prompt") or ""),
            "disposition": str(item.get("status") or ""),
            "answer": str(
                item.get("answer_summary")
                or item.get("waiver_rationale")
                or item.get("blocker_reason")
                or ""
            ),
        }
        for item in audit.get("questions", [])
        if isinstance(item, Mapping)
        and str(item.get("status") or "") in {"answered", "waived", "blocked"}
    ]
    residuals = [
        {
            "claim": str(item.get("claim_key") or ""),
            "classification": str(item.get("classification") or ""),
            "closure_condition": str(item.get("closure_condition") or ""),
        }
        for item in (reconciliation.get("latest_run") or {}).get("items", [])
        if isinstance(item, Mapping)
        and bool(item.get("blocking"))
        and str(item.get("disposition") or "")
        in {"open", "rejected", "escalated"}
    ] if isinstance(reconciliation.get("latest_run"), Mapping) else []
    return {
        "contract": "flow.packet_working_sheet.v1",
        "packet": {
            "title": str(packet.get("title") or ""),
            "intent": str(packet.get("objective") or ""),
            "purpose": str(packet.get("purpose") or "implementation"),
            "completion_criteria": list(packet.get("completion_criteria", [])),
            "spec_revision": int(
                packet.get("spec_revision") or packet.get("current_revision") or 0
            ),
            "plan_revision": int(plan.get("plan_revision") or 0),
            "plan_status": str(plan.get("status") or "missing"),
        },
        "units": units[offset : offset + limit],
        "unit_pagination": _pagination(len(units), offset, limit),
        "accepted_decisions": decisions[:20],
        "accepted_decisions_truncated": len(decisions) > 20,
        "evidence": {
            "applicability": str(
                reconciliation.get("applicability") or "not_applicable"
            ),
            "reason": str(reconciliation.get("applicability_reason") or ""),
            "gaps": residuals[:20],
            "gaps_truncated": len(residuals) > 20,
        },
        "current_gate": dict(gate),
    }
