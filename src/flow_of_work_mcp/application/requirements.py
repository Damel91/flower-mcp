"""Application service for deterministic requirement lifecycle operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from flow_of_work_mcp.core.domain import (
    LifecycleStatus,
    RequirementDraft,
    VerificationDraft,
)
from flow_of_work_mcp.core.domain.identifiers import required_text, validate_requirement_id
from flow_of_work_mcp.core.errors import RequirementMutationBlockedError
from flow_of_work_mcp.core.ports import RequirementLedger


@dataclass(frozen=True)
class RequirementLifecyclePolicy:
    """Small deterministic policy for direct versus governed requirement changes."""

    version: str = "requirement-lifecycle-policy-v1"

    _DIRECT_TRANSITIONS = frozenset(
        {
            (LifecycleStatus.PLANNED, LifecycleStatus.PARTIAL),
            (LifecycleStatus.PLANNED, LifecycleStatus.IMPLEMENTED),
            (LifecycleStatus.PARTIAL, LifecycleStatus.PLANNED),
            (LifecycleStatus.PARTIAL, LifecycleStatus.IMPLEMENTED),
            (LifecycleStatus.IMPLEMENTED, LifecycleStatus.PARTIAL),
        }
    )

    def classify(
        self,
        current: LifecycleStatus,
        target: LifecycleStatus,
        *,
        governed_approval_reference: str,
    ) -> str:
        if current == target:
            raise ValueError("lifecycle transition cannot be a no-op")
        reference = str(governed_approval_reference or "").strip()
        if target == LifecycleStatus.REMOVED or current == LifecycleStatus.REMOVED:
            if target == LifecycleStatus.REMOVED or target == LifecycleStatus.PLANNED:
                if not reference:
                    raise RequirementMutationBlockedError("governed_approval_required")
                return "governed"
            raise ValueError("removed requirements may only be reinstated as planned")
        if (current, target) not in self._DIRECT_TRANSITIONS:
            raise ValueError("unsupported lifecycle transition")
        return "deterministic"


class RequirementService:
    """The only application entry point for requirement mutations.

    MCP handlers and future SRS/LLM workflows use this service. The service
    owns no SQL and no model configuration; it enforces the domain-shaped input
    contract before delegating a transaction to the ledger port.
    """

    def __init__(
        self,
        ledger: RequirementLedger,
        policy: RequirementLifecyclePolicy | None = None,
    ) -> None:
        self._ledger = ledger
        self._policy = policy or RequirementLifecyclePolicy()

    def create_project(self, project_id: str, name: str, *, actor: str) -> Mapping[str, Any]:
        return self._ledger.create_project(project_id, name, actor=required_text(actor, "actor"))

    def register(
        self,
        project_id: str,
        draft: RequirementDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        actor = required_text(actor, "actor")
        return self._ledger.add_requirement(
            project_id,
            title=draft.title,
            statement=draft.statement,
            category=draft.category,
            rationale=draft.rationale,
            source_anchor=draft.source_anchor,
            actor=actor,
            request_id=str(request_id or ""),
        )

    def revise(
        self,
        project_id: str,
        requirement_id: str,
        draft: RequirementDraft,
        *,
        actor: str,
        rationale: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._ledger.revise_requirement(
            project_id,
            validate_requirement_id(requirement_id),
            title=draft.title,
            statement=draft.statement,
            category=draft.category,
            source_anchor=draft.source_anchor,
            actor=required_text(actor, "actor"),
            rationale=required_text(rationale, "rationale"),
            request_id=str(request_id or ""),
        )

    def set_lifecycle(
        self,
        project_id: str,
        requirement_id: str,
        status: LifecycleStatus,
        *,
        actor: str,
        reason: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, Any]:
        requirement_id = validate_requirement_id(requirement_id)
        target = LifecycleStatus(status)
        history = self._ledger.requirement_history(project_id, requirement_id)
        request_event = next(
            (
                event
                for event in reversed(history["events"])
                if request_id
                and event["event_type"] == "lifecycle_status_changed"
                and event["request_id"] == str(request_id)
            ),
            None,
        )
        if request_event is not None:
            transition_authority = (
                "governed"
                if request_event["payload"].get("governance_reference")
                else "deterministic"
            )
        else:
            transition_authority = self._policy.classify(
                LifecycleStatus(str(history["requirement"]["lifecycle_status"])),
                target,
                governed_approval_reference=governed_approval_reference,
            )
        result = self._ledger.set_lifecycle_status(
            project_id,
            requirement_id,
            status=target,
            actor=required_text(actor, "actor"),
            reason=required_text(reason, "reason"),
            governance_reference=str(governed_approval_reference or ""),
            request_id=str(request_id or ""),
        )
        value = dict(result)
        value["transition_authority"] = transition_authority
        value["policy_version"] = self._policy.version
        return value

    def record_verification(
        self,
        project_id: str,
        requirement_id: str,
        verification: VerificationDraft,
        *,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, Any]:
        return self._ledger.record_verification(
            project_id,
            validate_requirement_id(requirement_id),
            kind=verification.kind,
            outcome=verification.outcome,
            reference=verification.reference,
            metadata=verification.metadata,
            actor=required_text(actor, "actor"),
            request_id=str(request_id or ""),
        )

    def traceability(self, project_id: str) -> list[Mapping[str, Any]]:
        return self._ledger.traceability_matrix(project_id)

    def history(self, project_id: str, requirement_id: str) -> Mapping[str, Any]:
        return self._ledger.requirement_history(
            project_id,
            validate_requirement_id(requirement_id),
        )
