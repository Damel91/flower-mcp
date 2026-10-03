"""Canonical packet creation and derivable lifecycle repair."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from flow_of_work_mcp.application.assurance import AssuranceService
from flow_of_work_mcp.application.change_control import ChangeControlService
from flow_of_work_mcp.application.navigation_audit import NavigationAuditService
from flow_of_work_mcp.application.packet_construction import PacketConstructionService
from flow_of_work_mcp.application.packet_reconciliation import PacketReconciliationService
from flow_of_work_mcp.core.domain.assurance import RemediationRelationshipsDraft
from flow_of_work_mcp.core.domain.change_control import (
    ImplementationPacketDraft,
    PACKET_INACTIVE_STATUS_VALUES,
    PacketPurpose,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.domain.navigation_audit import NavigationAuditBlockDraft
from flow_of_work_mcp.core.domain.packet_construction import PacketConstructionAuditDraft
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError,
    RequirementConflictError,
)


class PacketLifecycleService:
    """Own the only behaviorally live packet-creation boundary."""

    def __init__(
        self,
        *,
        ledger,
        changes: ChangeControlService,
        assurance: AssuranceService,
        navigation: NavigationAuditService,
        construction: PacketConstructionService,
        reconciliation: PacketReconciliationService,
        packet_provider_overlay=None,
    ) -> None:
        self._ledger = ledger
        self._changes = changes
        self._assurance = assurance
        self._navigation = navigation
        self._construction = construction
        self._reconciliation = reconciliation
        self._provider_managed_targets = bool(
            packet_provider_overlay is not None
            and packet_provider_overlay.provider_managed_targets
        )

    def create_packet(
        self,
        project_id: str,
        *,
        change_id: str,
        packet: ImplementationPacketDraft,
        purpose: PacketPurpose | str = PacketPurpose.IMPLEMENTATION,
        actor: str,
        request_id: str,
        milestone_id: str = "",
        active_provider: str = "",
        source_revision: str = "",
        finding_ids: tuple[str, ...] = (),
        predecessor_packet_id: str = "",
        predecessor_dependency_policy: str = "materialized",
        required_regression_evidence: str = "",
        required_campaign_ids: tuple[str, ...] = (),
    ) -> Mapping[str, object]:
        purpose = PacketPurpose(purpose)
        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        if not packet.objective:
            raise ValueError("packet creation requires implementation intent")
        if purpose == PacketPurpose.REMEDIATION:
            if not finding_ids:
                raise ValueError("remediation packet requires finding_ids")
            if not required_regression_evidence:
                raise ValueError(
                    "remediation packet requires required_regression_evidence"
                )
        elif any(
            (
                finding_ids,
                predecessor_packet_id,
                predecessor_dependency_policy if predecessor_dependency_policy != "materialized" else "",
                required_regression_evidence,
                required_campaign_ids,
            )
        ):
            raise ValueError(
                "remediation relationships require purpose=remediation"
            )

        with self._ledger.atomic():
            if purpose == PacketPurpose.REMEDIATION and predecessor_packet_id:
                predecessor = _packet(
                    self._changes.get_change(project_id, change_id),
                    predecessor_packet_id,
                )
                packet = _inherit_remediation_scope(packet, predecessor)

            # Packet creation is one lifecycle transition. Seed the row with
            # the same conservative state that the canonical substrate will
            # publish so packet_added never advertises provisional readiness.
            packet = replace(
                packet,
                readiness_state=(
                    "needs_targets"
                    if packet.target_policy.value == "code_targets_required"
                    else "draft"
                ),
            )
            change = self._changes.add_packet(
                project_id,
                change_id,
                packet,
                actor=actor,
                request_id=f"{request_id}:packet",
            )
            packet_id = _packet_id_for_request(change, f"{request_id}:packet")
            if purpose == PacketPurpose.REMEDIATION:
                self._assurance.link_remediation_relationships(
                    project_id,
                    RemediationRelationshipsDraft(
                        change_id=change_id,
                        packet_id=packet_id,
                        finding_ids=finding_ids,
                        required_regression_evidence=required_regression_evidence,
                        predecessor_packet_id=predecessor_packet_id,
                        predecessor_dependency_policy=predecessor_dependency_policy,
                        required_campaign_ids=required_campaign_ids,
                    ),
                    actor=actor,
                    request_id=f"{request_id}:relationships",
                )
            persisted = _packet(
                self._changes.get_change(project_id, change_id), packet_id
            )
            if str(persisted.get("purpose") or "implementation") != purpose.value:
                raise RequirementConflictError(
                    "packet purpose conflicts with durable creation history"
                )
            lifecycle = self._initialize_substrate(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                packet=packet,
                milestone_id=milestone_id,
                active_provider=active_provider,
                source_revision=source_revision,
                actor=actor,
                request_id=request_id,
            )
        return {
            "project_id": project_id,
            "change_id": change_id,
            "packet_id": packet_id,
            "purpose": purpose.value,
            **lifecycle,
        }

    def ensure_packet_lifecycle(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        """Repair only substrate that is uniquely derivable from packet facts."""

        actor = required_text(actor, "actor")
        request_id = required_text(request_id, "request_id")
        with self._ledger.atomic():
            packet = _packet(self._changes.get_change(project_id, change_id), packet_id)
            if str(packet.get("status") or "") in PACKET_INACTIVE_STATUS_VALUES:
                return {"repaired": False, "reason": "packet_inactive"}
            repaired: list[str] = []
            navigation_audit_id = ""
            if (
                str(packet.get("target_policy") or "")
                == "code_targets_required"
                and not self._provider_managed_targets
            ):
                blocks = self._navigation.list_blocks(project_id)
                navigation_ids = tuple(
                    str(item)
                    for item in packet.get("navigation_audit_ids", [])
                    if str(item)
                )
                if len(navigation_ids) > 1:
                    raise ChangeControlBlockedError(
                        "packet_bootstrap_state_ambiguous",
                        details={"navigation_audit_count": len(navigation_ids)},
                    )
                target_state_needs_repair = False
                if navigation_ids:
                    referenced = next(
                        (
                            item
                            for item in blocks
                            if str(item.get("navigation_audit_id") or "")
                            == navigation_ids[0]
                        ),
                        None,
                    )
                    if referenced is not None:
                        if (
                            str(referenced.get("change_id") or "") != change_id
                            or str(referenced.get("packet_id") or "") != packet_id
                        ):
                            raise ChangeControlBlockedError(
                                "packet_navigation_ownership_mismatch",
                                details={
                                    "navigation_audit_id": navigation_ids[0]
                                },
                            )
                        navigation_audit_id = navigation_ids[0]
                    else:
                        target_state_needs_repair = True
                else:
                    target_state_needs_repair = True
                if target_state_needs_repair:
                    matching = [
                        item
                        for item in blocks
                        if str(item.get("change_id") or "") == change_id
                        and str(item.get("packet_id") or "") == packet_id
                    ]
                    if len(matching) > 1:
                        raise ChangeControlBlockedError(
                            "packet_bootstrap_state_ambiguous",
                            details={"navigation_audit_count": len(matching)},
                        )
                    if matching:
                        navigation_audit_id = str(
                            matching[0]["navigation_audit_id"]
                        )
                    else:
                        opened = self._navigation.open_block(
                            project_id,
                            NavigationAuditBlockDraft(
                                change_id=change_id,
                                packet_id=packet_id,
                            ),
                            actor=actor,
                            request_id=f"{request_id}:navigation",
                        )
                        navigation_audit_id = str(opened["navigation_audit_id"])
                    self._changes.set_packet_target_state(
                        project_id,
                        change_id,
                        packet_id,
                        target_policy="code_targets_required",
                        readiness_state="needs_targets",
                        navigation_audit_ids=(navigation_audit_id,),
                        target_binding_ids=tuple(
                            str(item)
                            for item in packet.get("target_binding_ids", [])
                        ),
                        candidate_set_ids=tuple(
                            str(item)
                            for item in packet.get("candidate_set_ids", [])
                        ),
                        context_snapshot_ids=tuple(
                            str(item)
                            for item in packet.get("context_snapshot_ids", [])
                        ),
                        readiness_blockers=("accepted_target_binding_missing",),
                        actor=actor,
                        request_id=f"{request_id}:target-state",
                    )
                    repaired.append("navigation_state")

            construction = self._construction.audit_for_packet(
                project_id, change_id, packet_id
            )
            if construction is None:
                construction = self._construction.start_audit(
                    project_id,
                    PacketConstructionAuditDraft(
                        change_id=change_id,
                        packet_id=packet_id,
                    ),
                    actor=actor,
                    request_id=f"{request_id}:construction",
                )
                repaired.append("construction_state")
            else:
                previous_question_revision = int(
                    construction.get("question_plan_revision") or 0
                )
                construction = self._construction.start_audit(
                    project_id,
                    PacketConstructionAuditDraft(
                        milestone_id=str(construction.get("milestone_id") or ""),
                        change_id=change_id,
                        packet_id=packet_id,
                        profile=str(construction.get("profile") or "balanced"),
                    ),
                    actor=actor,
                    request_id=f"{request_id}:construction-refresh",
                )
                if int(construction.get("question_plan_revision") or 0) != (
                    previous_question_revision
                ):
                    repaired.append("construction_questions")
            if (
                str(packet.get("target_policy") or "")
                == "code_targets_required"
                and not self._provider_managed_targets
                and self._reconciliation.get(
                    project_id, change_id=change_id, packet_id=packet_id
                )
                is None
            ):
                self._reconciliation.initialize(
                    project_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    actor=actor,
                    request_id=f"{request_id}:reconciliation",
                )
                repaired.append("reconciliation_state")
            self._changes.evaluate_packet_readiness(
                project_id,
                change_id,
                packet_id,
                actor=actor,
                request_id=f"{request_id}:readiness",
            )
            plan = self._ledger.packet_work_plan_state(
                project_id, change_id, packet_id
            )
            work_plan_id = str((plan or {}).get("work_plan_id") or "")
            if work_plan_id and repaired:
                self._ledger.finalize_packet_authoring_revision(
                    project_id,
                    work_plan_id,
                    int(plan["plan_revision"]),
                    construction_audit_id=str(
                        construction.get("construction_audit_id") or ""
                    ),
                )
        return {
            "repaired": bool(repaired),
            "repaired_components": repaired,
            "navigation_audit_id": navigation_audit_id,
        }

    def _initialize_substrate(
        self,
        project_id: str,
        *,
        change_id: str,
        packet_id: str,
        packet: ImplementationPacketDraft,
        milestone_id: str,
        active_provider: str,
        source_revision: str,
        actor: str,
        request_id: str,
    ) -> Mapping[str, object]:
        navigation_audit_id = ""
        reconciliation_scope_id = ""
        if (
            packet.target_policy.value == "code_targets_required"
            and not self._provider_managed_targets
        ):
            reconciliation = self._reconciliation.initialize(
                project_id,
                change_id=change_id,
                packet_id=packet_id,
                actor=actor,
                request_id=f"{request_id}:reconciliation",
            )
            reconciliation_scope_id = str(
                reconciliation["reconciliation_scope_id"]
            )
            navigation = self._navigation.open_block(
                project_id,
                NavigationAuditBlockDraft(
                    milestone_id=milestone_id,
                    change_id=change_id,
                    packet_id=packet_id,
                    active_provider=active_provider,
                    source_revision=source_revision,
                ),
                actor=actor,
                request_id=f"{request_id}:navigation",
            )
            navigation_audit_id = str(navigation["navigation_audit_id"])
            self._changes.set_packet_target_state(
                project_id,
                change_id,
                packet_id,
                target_policy="code_targets_required",
                readiness_state="needs_targets",
                navigation_audit_ids=(navigation_audit_id,),
                readiness_blockers=("accepted_target_binding_missing",),
                actor=actor,
                request_id=f"{request_id}:target-state",
            )
        construction = self._construction.start_audit(
            project_id,
            PacketConstructionAuditDraft(
                milestone_id=milestone_id,
                change_id=change_id,
                packet_id=packet_id,
                profile="balanced",
            ),
            actor=actor,
            request_id=f"{request_id}:construction",
        )
        change = self._changes.evaluate_packet_readiness(
            project_id,
            change_id,
            packet_id,
            actor=actor,
            request_id=f"{request_id}:readiness",
        )
        current = _packet(change, packet_id)
        return {
            "readiness": str(current.get("readiness_state") or ""),
            "navigation_audit_id": navigation_audit_id,
            "construction_audit_id": str(
                construction["construction_audit_id"]
            ),
            "reconciliation_scope_id": reconciliation_scope_id,
        }


def _packet(change: Mapping[str, object], packet_id: str) -> Mapping[str, object]:
    for item in change.get("packets", []):
        if isinstance(item, Mapping) and str(item.get("packet_id") or "") == packet_id:
            return item
    raise ValueError(f"unknown packet in change: {packet_id}")


def _packet_id_for_request(change: Mapping[str, object], request_id: str) -> str:
    for event in change.get("events", []):
        if (
            isinstance(event, Mapping)
            and str(event.get("event_type") or "") == "packet_added"
            and str(event.get("request_id") or "") == request_id
        ):
            return required_text(event.get("packet_id"), "packet_id")
    raise RuntimeError("canonical packet creation did not emit packet_added")


def _inherit_remediation_scope(
    packet: ImplementationPacketDraft,
    predecessor: Mapping[str, object],
) -> ImplementationPacketDraft:
    """Reuse predecessor authority only where the successor omitted it."""

    return replace(
        packet,
        requirement_ids=(
            packet.requirement_ids
            or _string_tuple(predecessor.get("requirement_ids"))
        ),
        goal_ids=packet.goal_ids or _string_tuple(predecessor.get("goal_ids")),
        in_scope=packet.in_scope or _string_tuple(predecessor.get("in_scope")),
        out_of_scope=(
            packet.out_of_scope
            or _string_tuple(predecessor.get("out_of_scope"))
        ),
        invariants=(
            packet.invariants
            or _string_tuple(predecessor.get("invariants"))
        ),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())
