"""Value objects for milestones, phase audits, policy and derived next work."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_requirement_id
from flow_of_work_mcp.core.domain.srs import ValidationDisposition


class PhaseChangeType(StrEnum):
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"


class NextActionKind(StrEnum):
    CREATE_MILESTONE_CHANGE = "create_milestone_change"
    IMPLEMENT_REQUIREMENT = "implement_requirement"
    IMPLEMENT_PACKET = "implement_packet"
    RESOLVE_PACKET_BLOCKER = "resolve_packet_blocker"
    RESOLVE_CHANGE_PACKET_GRAPH = "resolve_change_packet_graph"
    TRIAGE_FINDING = "triage_finding"
    RESOLVE_FINDING = "resolve_finding"
    RUN_VERIFICATION_CAMPAIGN = "run_verification_campaign"
    REPAIR_FAILED_CAMPAIGN = "repair_failed_campaign"
    REQUEST_CHANGE_ACCEPTANCE = "request_change_acceptance"
    START_IMPLEMENTATION_RUN = "start_implementation_run"
    EXECUTE_RUN_STEP = "execute_run_step"
    RESOLVE_RUN_BLOCKER = "resolve_run_blocker"
    CLOSE_PACKET_AFTER_RUN = "close_packet_after_run"
    CREATE_LIFECYCLE_PROJECTION = "create_lifecycle_projection"
    RESOLVE_PARTIAL_REQUIREMENT = "resolve_partial_requirement"
    REPAIR_FAILED_VERIFICATION = "repair_failed_verification"
    COLLECT_VERIFICATION_EVIDENCE = "collect_verification_evidence"
    RUN_PHASE_AUDIT = "run_phase_audit"
    RESOLVE_GROUNDING_DIVERGENCE = "resolve_grounding_divergence"
    REVIEW_REQUIREMENT_CANDIDATE = "review_requirement_candidate"
    RESOLVE_VALIDATION_FINDINGS = "resolve_validation_findings"
    REVIEW_MILESTONE_RISK = "review_milestone_risk"


class ActionExecutionClass(StrEnum):
    DETERMINISTIC = "deterministic"
    ORCHESTRATION = "orchestration"
    GOVERNED_DECISION = "governed_decision"


@dataclass(frozen=True)
class MilestoneDraft:
    name: str
    requirement_ids: tuple[str, ...]
    dependency_closure_ids: tuple[str, ...]
    entry_policy: Mapping[str, object]
    exit_policy: Mapping[str, object]
    risk_disposition: str
    acceptance_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", required_text(self.name, "name"))
        object.__setattr__(
            self,
            "risk_disposition",
            required_text(self.risk_disposition, "risk_disposition"),
        )
        if not self.requirement_ids:
            raise ValueError("milestone requires at least one requirement")
        requirement_ids = tuple(validate_requirement_id(item) for item in self.requirement_ids)
        closure_ids = tuple(validate_requirement_id(item) for item in self.dependency_closure_ids)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("milestone requirement IDs must be unique")
        if len(set(closure_ids)) != len(closure_ids):
            raise ValueError("milestone dependency closure IDs must be unique")
        if not set(requirement_ids).issubset(set(closure_ids)):
            raise ValueError("milestone dependency closure must include its requirement IDs")
        if len(set(self.acceptance_evidence)) != len(self.acceptance_evidence):
            raise ValueError("milestone acceptance evidence must be unique")
        object.__setattr__(self, "requirement_ids", requirement_ids)
        object.__setattr__(self, "dependency_closure_ids", closure_ids)


@dataclass(frozen=True)
class PhaseAuditScope:
    scope_id: str
    requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", required_text(self.scope_id, "scope_id"))
        requirement_ids = tuple(validate_requirement_id(item) for item in self.requirement_ids)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("phase audit scope requirement IDs must be unique")
        object.__setattr__(self, "requirement_ids", requirement_ids)


@dataclass(frozen=True)
class PhaseRequirementSnapshot:
    requirement_id: str
    revision: int
    lifecycle_status: str
    verification: Mapping[str, str | None]
    evidence_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", validate_requirement_id(self.requirement_id))
        if self.revision <= 0:
            raise ValueError("phase snapshot revision must be positive")
        object.__setattr__(
            self,
            "lifecycle_status",
            required_text(self.lifecycle_status, "lifecycle_status"),
        )
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("phase snapshot evidence IDs must be unique")


@dataclass(frozen=True)
class PhaseRequirementDelta:
    requirement_id: str
    change_types: tuple[PhaseChangeType, ...]
    evidence_added_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", validate_requirement_id(self.requirement_id))
        if not self.change_types:
            raise ValueError("phase requirement delta requires at least one change type")
        if len(set(self.change_types)) != len(self.change_types):
            raise ValueError("phase requirement delta change types must be unique")
        if len(set(self.evidence_added_ids)) != len(self.evidence_added_ids):
            raise ValueError("phase evidence delta IDs must be unique")


@dataclass(frozen=True)
class PhaseAudit:
    project_id: str
    scope: PhaseAuditScope
    previous_audit_id: int | None
    snapshots: tuple[PhaseRequirementSnapshot, ...]
    deltas: tuple[PhaseRequirementDelta, ...]
    policy_version: str
    audit_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", required_text(self.project_id, "project_id"))
        object.__setattr__(self, "policy_version", required_text(self.policy_version, "policy_version"))
        if self.audit_id is not None and self.audit_id <= 0:
            raise ValueError("phase audit ID must be positive")
        if self.previous_audit_id is not None and self.previous_audit_id <= 0:
            raise ValueError("previous phase audit ID must be positive")


@dataclass(frozen=True)
class ValidationAuditRecord:
    source_ref: str
    disposition: ValidationDisposition
    finding_codes: tuple[str, ...]
    profile_id: str = ""
    audit_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", required_text(self.source_ref, "source_ref"))
        if len(set(self.finding_codes)) != len(self.finding_codes):
            raise ValueError("validation finding codes must be unique")
        if self.audit_id is not None and self.audit_id <= 0:
            raise ValueError("validation audit ID must be positive")


@dataclass(frozen=True)
class LifecyclePolicy:
    """Declared policy used to label, never silently execute, next actions."""

    version: str = "lifecycle-policy-v1"
    automatic_mode: bool = False
    auto_authorized_actions: tuple[NextActionKind, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", required_text(self.version, "version"))
        action_kinds = tuple(NextActionKind(item) for item in self.auto_authorized_actions)
        if len(set(action_kinds)) != len(action_kinds):
            raise ValueError("policy auto-authorized actions must be unique")
        object.__setattr__(self, "auto_authorized_actions", action_kinds)

    def allows_automatic(self, action_kind: NextActionKind) -> bool:
        return self.automatic_mode and action_kind in self.auto_authorized_actions


@dataclass(frozen=True)
class NextAction:
    action_id: str
    kind: NextActionKind
    execution_class: ActionExecutionClass
    priority: int
    rationale: str
    requirement_ids: tuple[str, ...] = ()
    goal_node_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    milestone_ids: tuple[str, ...] = ()
    change_ids: tuple[str, ...] = ()
    packet_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    campaign_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    step_ids: tuple[str, ...] = ()
    audit_ids: tuple[int, ...] = ()
    automatic_eligible: bool = False
    tool: str = ""
    operation: str = ""
    arguments: Mapping[str, object] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()
    state: str = "pending"
    decision_class: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", required_text(self.action_id, "action_id"))
        object.__setattr__(self, "rationale", required_text(self.rationale, "rationale"))
        if self.priority < 0:
            raise ValueError("next action priority cannot be negative")
        if len(set(self.requirement_ids)) != len(self.requirement_ids):
            raise ValueError("next action requirement IDs must be unique")
        if len(set(self.goal_node_ids)) != len(self.goal_node_ids):
            raise ValueError("next action goal node IDs must be unique")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("next action candidate IDs must be unique")
        if len(set(self.milestone_ids)) != len(self.milestone_ids):
            raise ValueError("next action milestone IDs must be unique")
        if len(set(self.change_ids)) != len(self.change_ids):
            raise ValueError("next action change IDs must be unique")
        if len(set(self.packet_ids)) != len(self.packet_ids):
            raise ValueError("next action packet IDs must be unique")
        if len(set(self.finding_ids)) != len(self.finding_ids):
            raise ValueError("next action finding IDs must be unique")
        if len(set(self.campaign_ids)) != len(self.campaign_ids):
            raise ValueError("next action campaign IDs must be unique")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("next action run IDs must be unique")
        if len(set(self.step_ids)) != len(self.step_ids):
            raise ValueError("next action step IDs must be unique")
        if len(set(self.audit_ids)) != len(self.audit_ids):
            raise ValueError("next action audit IDs must be unique")
        object.__setattr__(self, "tool", str(self.tool or "").strip())
        object.__setattr__(self, "operation", str(self.operation or "").strip())
        object.__setattr__(self, "arguments", dict(self.arguments or {}))
        object.__setattr__(
            self,
            "required_inputs",
            tuple(required_text(item, "required_inputs") for item in self.required_inputs),
        )
        object.__setattr__(self, "state", required_text(self.state, "state"))
        object.__setattr__(
            self, "decision_class", str(self.decision_class or "").strip()
        )
