"""Deterministic governed-change and implementation-packet policy."""
from __future__ import annotations

from typing import Callable, Mapping

from flow_of_work_mcp.core.domain.change_control import (
    GovernedChangeDraft,
    ImplementationPacketDraft,
    PACKET_INACTIVE_STATUS_VALUES,
    PACKET_TERMINAL_STATUS_VALUES,
    PacketReadinessState,
    PacketStatus,
    PacketTransition,
)
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import ChangeControlBlockedError
from flow_of_work_mcp.core.ports import ChangeControlRepository


class ChangeControlService:
    """Applies closure predicates before mutating packet state."""

    def __init__(self, repository: ChangeControlRepository, *,
                 external_packet_closure: Callable[[str, str, str], Mapping[str, object] | None] | None = None) -> None:
        self._repository = repository
        self._external_packet_closure = external_packet_closure

    def create_change(
        self,
        project_id: str,
        draft: GovernedChangeDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.create_change(
            project_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def get_change(self, project_id: str, change_id: str) -> Mapping[str, object]:
        return self._repository.change_state(project_id, change_id)

    def packet_change_id(self, project_id: str, packet_id: str) -> str:
        return self._repository.packet_change_id(project_id, packet_id)

    def add_packet(
        self,
        project_id: str,
        change_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.add_packet(
            project_id,
            change_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def revise_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        draft: ImplementationPacketDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        state = self._repository.change_state(project_id, change_id)
        packet = _packet_by_id(state, packet_id)
        packet_status = str(packet["status"])
        if packet_status in PACKET_INACTIVE_STATUS_VALUES:
            raise ChangeControlBlockedError(
                (
                    "packet_terminal_state"
                    if packet_status in PACKET_TERMINAL_STATUS_VALUES
                    else "packet_quiescent_state"
                ),
                details={"packet_id": packet_id, "status": packet_status},
            )
        return self._repository.revise_packet(
            project_id,
            change_id,
            packet_id,
            draft,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def refine_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        title: str = "",
        objective: str = "",
        rationale: str = "",
        requirement_ids: tuple[str, ...] | None = None,
        goal_ids: tuple[str, ...] | None = None,
        in_scope: tuple[str, ...] | None = None,
        out_of_scope: tuple[str, ...] | None = None,
        invariants: tuple[str, ...] | None = None,
        unresolved_questions: tuple[str, ...] | None = None,
        completion_criteria: tuple[str, ...] | None = None,
        target_policy: str = "",
        readiness_state: str = "",
        navigation_audit_ids: tuple[str, ...] | None = None,
        target_binding_ids: tuple[str, ...] | None = None,
        candidate_set_ids: tuple[str, ...] | None = None,
        context_snapshot_ids: tuple[str, ...] | None = None,
        readiness_blockers: tuple[str, ...] | None = None,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Revise a packet without losing target-discovery state by omission."""

        state = self._repository.change_state(project_id, change_id)
        packet = _packet_by_id(state, packet_id)
        draft = ImplementationPacketDraft(
            title=str(title or "").strip() or str(packet["title"]),
            completion_criteria=(
                completion_criteria
                if completion_criteria is not None
                else _packet_tuple(packet, "completion_criteria")
            ),
            objective=str(objective or "").strip() or str(packet.get("objective") or ""),
            rationale=str(rationale or "").strip() or str(packet.get("rationale") or ""),
            requirement_ids=(
                requirement_ids
                if requirement_ids is not None
                else _packet_tuple(packet, "requirement_ids")
            ),
            goal_ids=goal_ids if goal_ids is not None else _packet_tuple(packet, "goal_ids"),
            in_scope=in_scope if in_scope is not None else _packet_tuple(packet, "in_scope"),
            out_of_scope=(
                out_of_scope if out_of_scope is not None else _packet_tuple(packet, "out_of_scope")
            ),
            invariants=(
                invariants if invariants is not None else _packet_tuple(packet, "invariants")
            ),
            unresolved_questions=(
                unresolved_questions
                if unresolved_questions is not None
                else _packet_tuple(packet, "unresolved_questions")
            ),
            navigation_audit_ids=(
                navigation_audit_ids
                if navigation_audit_ids is not None
                else _packet_tuple(packet, "navigation_audit_ids")
            ),
            target_binding_ids=(
                target_binding_ids
                if target_binding_ids is not None
                else _packet_tuple(packet, "target_binding_ids")
            ),
            candidate_set_ids=(
                candidate_set_ids
                if candidate_set_ids is not None
                else _packet_tuple(packet, "candidate_set_ids")
            ),
            context_snapshot_ids=(
                context_snapshot_ids
                if context_snapshot_ids is not None
                else _packet_tuple(packet, "context_snapshot_ids")
            ),
            target_policy=str(target_policy or "").strip()
            or str(packet.get("target_policy") or "documental_only"),
            readiness_state=str(readiness_state or "").strip()
            or str(packet.get("readiness_state") or ""),
            readiness_blockers=(
                readiness_blockers
                if readiness_blockers is not None
                else _packet_tuple(packet, "readiness_blockers")
            ),
        )
        return self.revise_packet(
            project_id,
            change_id,
            packet_id,
            draft,
            actor=actor,
            request_id=request_id,
        )

    def link_dependency(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        depends_on_packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.link_packet_dependency(
            project_id,
            change_id,
            packet_id,
            depends_on_packet_id,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def link_change_milestone(
        self,
        project_id: str,
        change_id: str,
        milestone_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.link_change_milestone(
            project_id,
            change_id,
            milestone_id,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def set_packet_target_state(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        target_policy: str = "",
        readiness_state: str = "",
        navigation_audit_ids: tuple[str, ...] = (),
        target_binding_ids: tuple[str, ...] = (),
        candidate_set_ids: tuple[str, ...] = (),
        context_snapshot_ids: tuple[str, ...] = (),
        readiness_blockers: tuple[str, ...] = (),
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.set_packet_target_state(
            project_id,
            change_id,
            packet_id,
            target_policy=target_policy,
            readiness_state=readiness_state,
            navigation_audit_ids=navigation_audit_ids,
            target_binding_ids=target_binding_ids,
            candidate_set_ids=candidate_set_ids,
            context_snapshot_ids=context_snapshot_ids,
            readiness_blockers=readiness_blockers,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def evaluate_packet_readiness(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        return self._repository.evaluate_packet_readiness(
            project_id,
            change_id,
            packet_id,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def transition_packet(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        transition: PacketTransition,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        with self._repository.atomic():
            return self._transition_packet(project_id, change_id, packet_id, transition,
                                           actor=actor, request_id=request_id)

    def _transition_packet(self, project_id: str, change_id: str, packet_id: str,
                           transition: PacketTransition, *, actor: str,
                           request_id: str = "") -> Mapping[str, object]:
        state = self._repository.change_state(project_id, change_id)
        packet = _packet_by_id(state, packet_id)
        current_status = str(packet["status"])
        if transition.status == PacketStatus.IDLE:
            if current_status in PACKET_TERMINAL_STATUS_VALUES:
                raise ChangeControlBlockedError(
                    "packet_terminal_state",
                    details={"packet_id": packet_id, "status": current_status},
                )
            if not transition.disposition:
                raise ChangeControlBlockedError(
                    "idle_requires_disposition",
                    details={"packet_id": packet_id},
                )
            if transition.criterion_results:
                raise ChangeControlBlockedError(
                    "idle_cannot_record_completion",
                    details={"packet_id": packet_id},
                )
            if transition.successor_packet_id:
                raise ChangeControlBlockedError(
                    "idle_cannot_set_successor",
                    details={"packet_id": packet_id},
                )
        elif current_status == PacketStatus.IDLE.value and transition.status not in {
            PacketStatus.PLANNED,
            PacketStatus.IMPLEMENTED,
            PacketStatus.SUPERSEDED,
            PacketStatus.CANCELLED,
        }:
            raise ChangeControlBlockedError(
                "idle_packet_requires_explicit_resume_or_disposition",
                details={
                    "packet_id": packet_id,
                    "requested_status": transition.status.value,
                },
            )
        if transition.status == PacketStatus.IMPLEMENTED:
            self._assert_can_implement(project_id, change_id, packet_id, transition)
        elif transition.status == PacketStatus.SCAFFOLDED and transition.criterion_results:
            raise ChangeControlBlockedError(
                "scaffolded_cannot_record_completion",
                details={"packet_id": packet_id},
            )
        elif transition.status == PacketStatus.SUPERSEDED and not transition.successor_packet_id:
            raise ChangeControlBlockedError(
                "superseded_requires_successor",
                details={"packet_id": packet_id},
            )
        elif transition.status == PacketStatus.CANCELLED and not transition.disposition:
            raise ChangeControlBlockedError(
                "cancelled_requires_disposition",
                details={"packet_id": packet_id},
            )
        return self._repository.transition_packet(
            project_id,
            change_id,
            packet_id,
            transition,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def _assert_can_implement(
        self,
        project_id: str,
        change_id: str,
        packet_id: str,
        transition: PacketTransition,
    ) -> None:
        state = self._repository.change_state(project_id, change_id)
        packet = _packet_by_id(state, packet_id)
        if str(packet["status"]) == PacketStatus.SCAFFOLDED.value:
            raise ChangeControlBlockedError(
                "scaffolded_cannot_close_packet",
                details={"packet_id": packet_id},
            )
        external_closure = (self._external_packet_closure(project_id, change_id, packet_id)
                            if self._external_packet_closure is not None else None)
        if external_closure is not None and not external_closure.get("complete"):
            raise ChangeControlBlockedError("external_packet_implementation_incomplete", details=dict(external_closure))
        if external_closure is None and str(packet.get("readiness_state") or "") != PacketReadinessState.EXECUTION_READY.value:
            raise ChangeControlBlockedError(
                "packet_not_execution_ready",
                details={
                    "packet_id": packet_id,
                    "readiness_state": str(packet.get("readiness_state") or ""),
                    "readiness_blockers": list(packet.get("readiness_blockers", [])),
                },
            )
        if transition.blocking_reasons:
            raise ChangeControlBlockedError(
                "packet_has_unresolved_blockers",
                details={
                    "packet_id": packet_id,
                    "blocking_reasons": list(transition.blocking_reasons),
                },
            )
        criteria = tuple(str(item) for item in packet.get("completion_criteria", []))
        known_results = dict(packet.get("criterion_results", {}))
        known_results.update(dict(transition.criterion_results))
        missing = [item for item in criteria if not known_results.get(item)]
        if missing:
            raise ChangeControlBlockedError(
                "packet_completion_criteria_missing",
                details={"packet_id": packet_id, "missing_criteria": missing},
            )
        packets = {str(item["packet_id"]): item for item in state.get("packets", [])}
        dependency_ids = tuple(str(item) for item in packet.get("dependency_packet_ids", []))
        blocked_dependencies = []
        for dependency_id in dependency_ids:
            dependency = packets[dependency_id]
            status = str(dependency["status"])
            if status == PacketStatus.IMPLEMENTED.value:
                continue
            if status == PacketStatus.SUPERSEDED.value and str(dependency.get("successor_packet_id") or ""):
                continue
            if status == PacketStatus.CANCELLED.value and str(dependency.get("disposition") or ""):
                continue
            blocked_dependencies.append({"packet_id": dependency_id, "status": status})
        if blocked_dependencies:
            raise ChangeControlBlockedError(
                "packet_dependencies_unresolved",
                details={"packet_id": packet_id, "dependencies": blocked_dependencies},
            )


def _packet_by_id(state: Mapping[str, object], packet_id: str) -> Mapping[str, object]:
    for packet in state.get("packets", []):
        if isinstance(packet, Mapping) and packet.get("packet_id") == packet_id:
            return packet
    raise ValueError(f"unknown packet in change: {packet_id}")


def _packet_tuple(packet: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = packet.get(key, ())
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value or ())
