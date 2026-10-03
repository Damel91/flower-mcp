"""Single runtime registry for multiplexed public operation contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

from flow_of_work_mcp.core.domain.assurance import (
    FindingDisposition,
    ReviewFindingSeverity,
)
from flow_of_work_mcp.core.domain.campaign_authority import (
    CampaignObligationDecision,
    OracleAnswerAuthority,
    TEST_HARNESS_DISPOSITIONS,
    TEST_HARNESS_PARTICIPANT_FIELDS,
)
from flow_of_work_mcp.core.domain.change_control import (
    PacketReadinessState,
    PacketStatus,
    PacketTargetPolicy,
)
from flow_of_work_mcp.core.domain.packet_reconciliation import (
    PacketEvidenceClaimType,
    ReconciliationItemDisposition,
)
from flow_of_work_mcp.core.domain.packet_construction import (
    PacketAnswerTemporalAuthority,
)
from flow_of_work_mcp.core.domain.packet_review import (
    WorkspaceReviewCompleteness,
    WorkspaceReviewDisposition,
)
from flow_of_work_mcp.core.domain.provider_surfaces import (
    CODINGCASTLE_PROVIDER_SURFACES,
)
from flow_of_work_mcp.core.domain.bootstrap import BootstrapPath
from flow_of_work_mcp.application.bootstrap_input_contracts import bootstrap_input_schema
from flow_of_work_mcp.core.domain.enums import VerificationKind, VerificationOutcome


class ContinuationPolicy(str, Enum):
    INTERNAL_UNTIL_QUIESCENT = "internal_until_quiescent"
    HOST_OBSERVE = "host_observe"
    RETURN_TO_MODEL = "return_to_model"


class OperationRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    PROCESS = "process"


@dataclass(frozen=True)
class ToolDescriptor:
    """Canonical public-tool identity and model-facing description."""

    name: str
    area: str
    description: str
    owner: str = "flow"


@dataclass(frozen=True)
class WorkAreaDescriptor:
    """One independently discoverable Flower lifecycle area."""

    name: str
    label: str
    purpose: str


@dataclass(frozen=True)
class OperationContract:
    tool: str
    operation: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    enums: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    owner: str = ""
    area: str = ""
    risk: OperationRisk = OperationRisk.READ
    decision_class: str = "inspection"
    effect_class: str = "none"
    continuation_policy: ContinuationPolicy = ContinuationPolicy.RETURN_TO_MODEL
    semantic_inputs: tuple[str, ...] = ()
    injected_inputs: tuple[str, ...] = ()
    admission: str = "handler"
    receipt: str = "flow.mcp-envelope.v1"
    paging_owner: str = "none"
    guidance: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def as_payload(self) -> dict[str, object]:
        payload = {
            "tool": self.tool,
            "operation": self.operation,
            "required_fields": list(self.required),
            "optional_fields": list(self.optional),
            "accepted_values": {
                field: list(values) for field, values in self.enums.items()
            },
            "example": _example(self),
            **({"owner": self.owner} if self.owner else {}),
            "area": self.area,
            "risk": self.risk.value,
            "decision_class": self.decision_class,
            "effect_class": self.effect_class,
            "continuation_policy": self.continuation_policy.value,
            "semantic_inputs": list(self.semantic_inputs),
            "injected_inputs": list(self.injected_inputs),
            "admission": self.admission,
            "receipt": self.receipt,
            "paging_owner": self.paging_owner,
        }
        if self.guidance:
            payload["guidance"] = dict(self.guidance)
        return payload

    def as_index_payload(self) -> dict[str, object]:
        """Return bounded route metadata; exact input help is requested separately."""

        payload = {
            "tool": self.tool,
            "operation": self.operation,
            "area": self.area,
            "risk": self.risk.value,
            "decision_class": self.decision_class,
            "effect_class": self.effect_class,
            "continuation_policy": self.continuation_policy.value,
        }
        if self.owner and self.owner != "flow":
            payload["owner"] = self.owner
        if self.admission != "handler":
            payload["admission"] = self.admission
        if self.receipt != "flow.mcp-envelope.v1":
            payload["receipt"] = self.receipt
        if self.paging_owner != "none":
            payload["paging_owner"] = self.paging_owner
        return payload


def _c(
    tool: str,
    operation: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    *,
    enums: Mapping[str, tuple[str, ...]] | None = None,
    owner: str = "",
    area: str = "",
    risk: OperationRisk | None = None,
    decision_class: str = "",
    effect_class: str = "",
    continuation_policy: ContinuationPolicy | None = None,
    injected_inputs: tuple[str, ...] | None = None,
    paging_owner: str = "",
    guidance: Mapping[str, object] | None = None,
) -> OperationContract:
    metadata = _operation_metadata(tool, operation)
    injected = (
        injected_inputs
        if injected_inputs is not None
        else tuple(
            field
            for field in (*required, *optional)
            if field
            in {
                "project_id",
                "actor",
                "request_id",
                "operation",
                "expected_spec_revision",
                "expected_plan_revision",
            }
        )
    )
    semantic = tuple(
        field for field in (*required, *optional) if field not in set(injected)
    )
    return OperationContract(
        tool=tool,
        operation=operation,
        required=required,
        optional=optional,
        enums=MappingProxyType(dict(enums or {})),
        owner=owner or str(metadata["owner"]),
        area=area or str(metadata["area"]),
        risk=risk or metadata["risk"],
        decision_class=decision_class or str(metadata["decision_class"]),
        effect_class=effect_class or str(metadata["effect_class"]),
        continuation_policy=(continuation_policy or metadata["continuation_policy"]),
        semantic_inputs=semantic,
        injected_inputs=injected,
        paging_owner=paging_owner or str(metadata["paging_owner"]),
        guidance=MappingProxyType(dict(guidance or {})),
    )


def _operation_metadata(tool: str, operation: str) -> Mapping[str, object]:
    area = _TOOL_AREAS.get(tool, "diagnostics")
    read_only_simple = tool in {
        "fow_capabilities",
        "fow_get_requirement",
        "fow_traceability",
        "fow_what_next",
        "fow_get_artifacts",
        "fow_get_job",
        "fow_list_jobs",
    }
    read_operation = (operation == "call" and read_only_simple) or operation in {
        "status",
        "state",
        "view",
        "get_change",
        "get_finding",
        "get_run",
        "get_handover",
        "resume_context",
        "ledger_projection",
        "project_state_snapshot",
        "get_packet_construction_audit",
        "get_packet_reconciliation",
        "get_packet_pressure",
        "provider_binding_state",
        "list_provider_bindings",
        "task_view",
        "summary",
        "units",
        "gates",
        "working_sheet",
        "history",
        "requirements",
        "cases",
        "obligations",
        "oracles",
        "constructibility",
        "oracle_ir",
        "attestation",
        "evidence",
        "residuals",
        "discover",
        "frame",
        "resolve",
        "goal_hook",
        "inspect",
        "export",
        "inventory",
        "criteria",
        "validation",
        "todo",
    }
    provider_operation = operation in {
        "retry_provider_rejection",
        "authorize_materialization",
        "authorize_promotion",
        "attest_source",
    }
    if tool == "fow_semantic" and operation == "execute_internal":
        provider_operation = True
    asynchronous = tool in {
        "fow_validate_srs",
        "fow_generate_artifacts",
        "fow_audit_phase",
        "fow_ground_intent",
    }
    internal = (tool, operation) in {
        ("fow_packet_advance", "advance"),
        ("fow_campaign_advance", "advance"),
    }
    destructive = (tool, operation) in {
        ("fow_bootstrap", "cancel"),
        ("fow_campaign_author", "cancel"),
        ("fow_campaign_author", "remove_case"),
        ("fow_packet_author", "remove_unit"),
        ("fow_run", "cancel_run"),
        ("fow_run", "cancel_step"),
    }
    mechanical = asynchronous or internal
    risk = (
        OperationRisk.READ
        if read_operation
        else OperationRisk.DESTRUCTIVE
        if destructive
        else OperationRisk.PROCESS
        if asynchronous or internal or provider_operation
        else OperationRisk.WRITE
    )
    interaction_projection_write = tool == "fow_interaction" and not read_operation
    return {
        "owner": _TOOL_OWNERS.get(tool, "flow"),
        "area": area,
        "risk": risk,
        "decision_class": (
            "inspection"
            if read_operation
            else "mechanical"
            if mechanical
            else "semantic"
        ),
        "effect_class": (
            "none"
            if read_operation
            else "projection_state"
            if interaction_projection_write
            else "async_job"
            if asynchronous
            else "provider_command"
            if provider_operation
            else "ledger_mutation"
        ),
        "continuation_policy": (
            ContinuationPolicy.HOST_OBSERVE
            if asynchronous
            else ContinuationPolicy.INTERNAL_UNTIL_QUIESCENT
            if internal
            else ContinuationPolicy.RETURN_TO_MODEL
        ),
        "paging_owner": (
            "ledger"
            if operation
            in {
                "summary",
                "units",
                "working_sheet",
                "history",
                "requirements",
                "cases",
                "obligations",
                "oracles",
                "evidence",
                "residuals",
            }
            else "none"
        ),
    }


_PUBLIC_TOOLS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor(
        "fow_external_work", "packet_lifecycle",
        "Select external-agent mode, close standalone plan validation, export complete Markdown, read TODOs and reconcile host-reported outcomes. Reads never execute code; completion, verification and human acceptance remain distinct.",
    ),
    ToolDescriptor(
        "fow_bindings", "project_bootstrap",
        "Inspect, export or explicitly import versioned host/provider association receipts. Receipts cannot configure endpoints, credentials or executable commands; replacement requires a reason.",
    ),
    ToolDescriptor(
        "fow_semantic", "requirements",
        "Inventory optional semantic roles and prepare, inspect, submit, validate, adopt or explicitly execute bounded SRS/grounding assignments. Host execution needs no internal model; unsupported roles disclose prerequisites.",
    ),
    ToolDescriptor(
        "fow_capabilities",
        "project_bootstrap",
        "Discover a bounded workflow summary, one named recipe, or the full diagnostic catalog.",
    ),
    ToolDescriptor(
        "fow_create_project",
        "project_bootstrap",
        "Create an isolated canonical lifecycle project.",
    ),
    ToolDescriptor(
        "fow_interaction",
        "project_bootstrap",
        "Select a durable Project Context and discover the current bounded work surface.",
    ),
    ToolDescriptor(
        "fow_register_requirement",
        "requirements",
        "Register one canonical requirement.",
    ),
    ToolDescriptor(
        "fow_get_requirement",
        "requirements",
        "Read one canonical requirement and immutable history.",
    ),
    ToolDescriptor(
        "fow_revise_requirement",
        "requirements",
        "Append one immutable canonical requirement revision.",
    ),
    ToolDescriptor(
        "fow_set_requirement_lifecycle",
        "requirements",
        "Apply one policy-checked requirement lifecycle transition.",
    ),
    ToolDescriptor(
        "fow_record_verification",
        "assurance",
        "Append declared deterministic/live evidence.",
    ),
    ToolDescriptor(
        "fow_traceability",
        "assurance",
        "Read a bounded, paginated project traceability projection.",
    ),
    ToolDescriptor(
        "fow_goal",
        "goal_graph",
        "Author and inspect use cases, sequences and expectations.",
    ),
    ToolDescriptor(
        "fow_validate_srs",
        "requirements",
        "Start durable structural validation; use fow_semantic for semantics.",
    ),
    ToolDescriptor(
        "fow_import_srs",
        "requirements",
        "Validate and atomically import one accepted initial SRS baseline.",
    ),
    ToolDescriptor(
        "fow_revise_srs_baseline",
        "requirements",
        "Classify and append one source-proven SRS baseline revision.",
    ),
    ToolDescriptor(
        "fow_promote_milestone",
        "milestones",
        "Plan milestone scope; acceptance_evidence is reserved for acceptance.",
    ),
    ToolDescriptor(
        "fow_accept_milestone",
        "milestones",
        "Append governed acceptance evidence after validation/campaign acceptance.",
    ),
    ToolDescriptor(
        "fow_audit_phase",
        "assurance",
        "Start a durable phase-audit job for a named scope.",
    ),
    ToolDescriptor(
        "fow_what_next",
        "changes",
        "Derive bounded, paginated next work from durable project state.",
    ),
    ToolDescriptor(
        "fow_generate_artifacts",
        "handover",
        "Start durable profile-based artifact generation.",
    ),
    ToolDescriptor(
        "fow_get_artifacts",
        "handover",
        "Read stored artifact metadata/content.",
    ),
    ToolDescriptor(
        "fow_ground_intent",
        "changes",
        "Ground intent internally; requires model and source provider.",
    ),
    ToolDescriptor("fow_get_job", "handover", "Read one durable job state."),
    ToolDescriptor("fow_list_jobs", "handover", "List durable jobs for a project."),
    ToolDescriptor(
        "fow_bootstrap",
        "project_bootstrap",
        "Guide intent, confirm scope and close bootstrap.",
    ),
    ToolDescriptor(
        "fow_change",
        "changes",
        "Govern changes and evidence; author work with fow_packet_*.",
    ),
    ToolDescriptor(
        "fow_assurance",
        "assurance",
        "Record findings, reassess intent, link fixes and govern acceptance.",
    ),
    ToolDescriptor(
        "fow_run",
        "changes",
        "Manage implementation runs, run steps and derived task views.",
    ),
    ToolDescriptor(
        "fow_handover",
        "handover",
        "Read coherent state and bounded history; create durable handover.",
    ),
    ToolDescriptor(
        "fow_packet_author",
        "packet_lifecycle",
        "Author canonical packets and plans using stable lifecycle identities.",
    ),
    ToolDescriptor(
        "fow_packet_advance",
        "packet_lifecycle",
        "Advance deterministic packet gates to a decision or async boundary.",
    ),
    ToolDescriptor(
        "fow_packet_inspect",
        "packet_lifecycle",
        "Read bounded packet scope, units, gates or history.",
    ),
    ToolDescriptor(
        "fow_campaign_author",
        "campaigns",
        "Create or incrementally revise one qualified campaign, obligation, oracle or materialization authority.",
    ),
    ToolDescriptor(
        "fow_campaign_advance",
        "campaigns",
        "Perform deterministic campaign work until one semantic, provider or evidence boundary.",
    ),
    ToolDescriptor(
        "fow_campaign_inspect",
        "campaigns",
        "Inspect one bounded campaign summary, working sheet, semantic component or history page.",
    ),
)

_WORK_AREAS: tuple[WorkAreaDescriptor, ...] = (
    WorkAreaDescriptor(
        "project_bootstrap", "Project bootstrap", "Open or bind the lifecycle project."
    ),
    WorkAreaDescriptor(
        "requirements", "Requirements", "Author, revise and trace requirements."
    ),
    WorkAreaDescriptor(
        "goal_graph", "Goal Graph", "Capture use cases, sequences and behavior."
    ),
    WorkAreaDescriptor(
        "milestones", "Milestones", "Plan and accept governed milestones."
    ),
    WorkAreaDescriptor(
        "changes", "Changes", "Govern implementation changes and execution runs."
    ),
    WorkAreaDescriptor(
        "packet_lifecycle",
        "Packet lifecycle",
        "Author, inspect and advance one packet.",
    ),
    WorkAreaDescriptor(
        "assurance", "Assurance", "Record findings, evidence and acceptance decisions."
    ),
    WorkAreaDescriptor(
        "handover", "Handover", "Recover and transfer durable project state."
    ),
    WorkAreaDescriptor(
        "campaigns", "Campaigns", "Author and advance qualified test campaigns."
    ),
)

_PUBLIC_TOOL_BY_NAME: Mapping[str, ToolDescriptor] = MappingProxyType(
    {item.name: item for item in _PUBLIC_TOOLS}
)
_TOOL_AREAS: Mapping[str, str] = MappingProxyType(
    {item.name: item.area for item in _PUBLIC_TOOLS}
)
_TOOL_OWNERS: Mapping[str, str] = MappingProxyType(
    {item.name: item.owner for item in _PUBLIC_TOOLS}
)


_P = ("project_id", "operation", "actor")
_R = ("request_id",)
_PACKET = ("change_id", "packet_id")


_BOOTSTRAP = {
    "bind_implementation_provider": _c(
        "fow_bootstrap",
        "bind_implementation_provider",
        _P + ("provider_kind", "provider_scope_id"),
        ("provider_context_id", "surfaces", "replacement_reason", "request_id"),
    ),
    "provider_binding_state": _c(
        "fow_bootstrap", "provider_binding_state", _P + ("provider_kind",)
    ),
    "list_provider_bindings": _c("fow_bootstrap", "list_provider_bindings", _P),
    "start": _c(
        "fow_bootstrap",
        "start",
        _P + ("project_name", "path"),
        _R,
        enums={"path": tuple(item.value for item in BootstrapPath)},
        guidance={"existing_project": "Use the exact registered project name. Inspect an active bootstrap instead of starting another; a replay request must retain its original actor, name and path."},
    ),
    "resume": _c("fow_bootstrap", "resume", _P + ("bootstrap_id",), _R),
    "state": _c("fow_bootstrap", "state", _P + ("bootstrap_id",)),
    "record_intake": _c(
        "fow_bootstrap", "record_intake", _P + ("bootstrap_id", "intake"), _R
    ),
    "record_contradiction": _c(
        "fow_bootstrap",
        "record_contradiction",
        _P + ("bootstrap_id", "contradiction"),
        _R,
    ),
    "confirm_intake": _c(
        "fow_bootstrap",
        "confirm_intake",
        _P + ("bootstrap_id", "confirmation_reference"),
        _R,
    ),
    "derive_behavior": _c(
        "fow_bootstrap", "derive_behavior", _P + ("bootstrap_id",), _R
    ),
    "complete": _c(
        "fow_bootstrap", "complete", _P + ("bootstrap_id", "completion_reference"), _R
    ),
    "cancel": _c("fow_bootstrap", "cancel", _P + ("bootstrap_id", "reason"), _R),
}

_BOOTSTRAP.update({
    "guidance": _c("fow_bootstrap", "guidance", _P + ("bootstrap_id",)),
    "record_answer": _c("fow_bootstrap", "record_answer", _P + ("bootstrap_id", "request_id") + tuple("answer." + key for key in bootstrap_input_schema("answer")["required"]),
        enums={"answer.kind": tuple(bootstrap_input_schema("answer")["properties"]["kind"]["enum"])},
        guidance={"input_schema": {"answer": bootstrap_input_schema("answer")}, "provenance": "Record selected governing answers, not the whole dialogue. Whitespace-only text is invalid. Use the returned answer revision for correspondence."}),
    "record_correspondence": _c("fow_bootstrap", "record_correspondence", _P + ("bootstrap_id", "request_id", "correspondence.answer_key", "correspondence.answer_revision", "correspondence.disposition", "correspondence.rationale") + tuple("correspondence.canonical_references." + key for key in bootstrap_input_schema("correspondence")["properties"]["canonical_references"]["required"]),
        enums={"correspondence.disposition": tuple(bootstrap_input_schema("correspondence")["properties"]["disposition"]["enum"])},
        guidance={"input_schema": {"correspondence": bootstrap_input_schema("correspondence")}, "currentness": "Use the current recorded answer revision and existing canonical IDs. Supply all three reference lists; at least one list must contain a current canonical reference. Replace example IDs with IDs returned by canonical authoring. This records correspondence, not semantic truth or acceptance."}),
    "roadmap": _c("fow_bootstrap", "roadmap", _P + ("bootstrap_id", "milestone_ids")),
    "confirm_roadmap": _c("fow_bootstrap", "confirm_roadmap", _P + ("bootstrap_id", "milestone_ids", "roadmap_fingerprint", "confirmation_reference", "request_id")),
    "record_continuation": _c("fow_bootstrap", "record_continuation", _P + ("bootstrap_id", "continuation_choice", "continuation_reference", "roadmap_fingerprint", "progress_revision", "reason", "request_id"), enums={"continuation_choice": ("continue", "review")}),
})


_CHANGE_OWNER = {
    "create_change": "change_control",
    "get_change": "change_control",
    "link_change_milestone": "change_control",
    "set_packet_target_state": "change_control",
    "evaluate_packet_readiness": "change_control",
    "start_packet_construction_audit": "packet_construction",
    "get_packet_construction_audit": "packet_construction",
    "initialize_packet_reconciliation": "packet_reconciliation",
    "get_packet_reconciliation": "packet_reconciliation",
    "declare_packet_evidence_claim": "packet_reconciliation",
    "supersede_packet_evidence_claim": "packet_reconciliation",
    "import_packet_evidence_snapshot": "packet_reconciliation",
    "collect_packet_evidence_snapshot": "packet_reconciliation",
    "reconcile_packet_evidence": "packet_reconciliation",
    "disposition_packet_evidence_residual": "packet_reconciliation",
    "answer_packet_question": "packet_construction",
    "waive_packet_question": "packet_construction",
    "block_packet_question": "packet_construction",
    "derive_packet_pressure": "packet_pressure",
    "get_packet_pressure": "packet_pressure",
    "accept_residual_risk": "packet_pressure",
    "revise_packet": "change_control",
    "link_dependency": "change_control",
    "transition_packet": "change_control",
}

_CHANGE_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "create_change": (
        (_P + ("title", "rationale", "requirement_ids")),
        ("source_refs", "baseline_refs", "milestone_id", "request_id"),
    ),
    "get_change": ((_P + ("change_id",)), ()),
    "link_change_milestone": ((_P + ("change_id", "milestone_id")), _R),
    "set_packet_target_state": (
        (_P + _PACKET),
        (
            "target_policy",
            "target_state",
            "navigation_audit_ids",
            "target_binding_ids",
            "candidate_set_ids",
            "context_snapshot_ids",
            "blocking_reasons",
            "request_id",
        ),
    ),
    "evaluate_packet_readiness": ((_P + _PACKET), _R),
    "start_packet_construction_audit": (
        (_P + _PACKET),
        ("milestone_id", "profile", "request_id"),
    ),
    "get_packet_construction_audit": (
        _P,
        ("construction_audit_id", "change_id", "packet_id"),
    ),
    "initialize_packet_reconciliation": (
        (_P + _PACKET),
        ("reconciliation_profile", "request_id"),
    ),
    "get_packet_reconciliation": (
        _P,
        ("reconciliation_scope_id", "change_id", "packet_id"),
    ),
    "declare_packet_evidence_claim": (
        (
            _P
            + (
                "reconciliation_scope_id",
                "claim_type",
                "claim_key",
                "subject_ref",
                "predicate",
                "object_ref",
            )
        ),
        (
            "assertion",
            "evidence_refs",
            "claim_required",
            "claim_dynamic",
            "claim_contradicted",
            "request_id",
        ),
    ),
    "supersede_packet_evidence_claim": ((_P + ("claim_id", "rationale")), _R),
    "import_packet_evidence_snapshot": (
        (
            _P
            + (
                "reconciliation_scope_id",
                "packet_id",
                "provider_id",
                "provider_scope_id",
                "provider_snapshot_id",
                "selection_ref",
                "source_revision",
                "fingerprint",
                "completeness",
                "claims",
            )
        ),
        (
            "workspace_revision",
            "surfaces",
            "contract_version",
            "truncated",
            "diagnostics",
            "request_id",
        ),
    ),
    "collect_packet_evidence_snapshot": (
        (_P + ("reconciliation_scope_id",)),
        ("max_claims", "max_depth", "request_id"),
    ),
    "reconcile_packet_evidence": (
        (_P + ("reconciliation_scope_id", "snapshot_id")),
        _R,
    ),
    "disposition_packet_evidence_residual": (
        (_P + ("reconciliation_item_id", "reconciliation_disposition", "rationale")),
        ("policy_ref", "request_id"),
    ),
    "answer_packet_question": (
        (_P + ("construction_audit_id", "question_id")),
        (
            "answer_summary",
            "summary",
            "evidence_refs",
            "linked_navigation_refs",
            "request_id",
        ),
    ),
    "waive_packet_question": (
        (_P + ("construction_audit_id", "question_id", "policy_ref")),
        ("waiver_rationale", "rationale", "request_id"),
    ),
    "block_packet_question": (
        (_P + ("construction_audit_id", "question_id")),
        ("blocking_reasons", "rationale", "answer_summary", "summary", "request_id"),
    ),
    "derive_packet_pressure": ((_P + _PACKET), ("profile", "request_id")),
    "get_packet_pressure": (_P, ("pressure_id", "change_id", "packet_id")),
    "accept_residual_risk": ((_P + ("pressure_id", "accepted_risk_ref")), _R),
    "revise_packet": (
        (_P + _PACKET),
        (
            "title",
            "intent",
            "rationale",
            "requirement_ids",
            "goal_ids",
            "in_scope",
            "out_of_scope",
            "invariants",
            "unresolved_questions",
            "completion_criteria",
            "target_policy",
            "target_state",
            "navigation_audit_ids",
            "target_binding_ids",
            "candidate_set_ids",
            "context_snapshot_ids",
            "blocking_reasons",
            "request_id",
        ),
    ),
    "link_dependency": ((_P + _PACKET + ("depends_on_packet_id",)), _R),
    "transition_packet": (
        (_P + _PACKET + ("packet_status",)),
        (
            "criterion_results",
            "blocking_reasons",
            "disposition",
            "successor_packet_id",
            "request_id",
        ),
    ),
}

_CHANGE_ENUMS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "set_packet_target_state": {
        "target_policy": tuple(item.value for item in PacketTargetPolicy),
        "target_state": tuple(item.value for item in PacketReadinessState),
    },
    "declare_packet_evidence_claim": {
        "claim_type": tuple(item.value for item in PacketEvidenceClaimType),
    },
    "disposition_packet_evidence_residual": {
        "reconciliation_disposition": tuple(
            item.value
            for item in ReconciliationItemDisposition
            if item != ReconciliationItemDisposition.OPEN
        ),
    },
    "revise_packet": {
        "target_policy": tuple(item.value for item in PacketTargetPolicy),
        "target_state": tuple(item.value for item in PacketReadinessState),
    },
    "transition_packet": {
        "packet_status": tuple(item.value for item in PacketStatus),
    },
}

_CHANGE = {
    operation: _c(
        "fow_change",
        operation,
        required,
        optional,
        enums=_CHANGE_ENUMS.get(operation),
        owner=_CHANGE_OWNER[operation],
    )
    for operation, (required, optional) in _CHANGE_FIELDS.items()
}

_ASSURANCE_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "record_finding": (
        (
            _P
            + (
                "change_id",
                "severity",
                "title",
                "rationale",
                "expected_correction",
                "scope_kind",
                "scope_ref",
            )
        ),
        ("packet_id", "source_anchor", "implementation_ref", "request_id", "finding_kind"),
    ),
    "get_finding": ((_P + ("finding_id",)), ()),
    "reassess_intent": ((_P + ("finding_id", "assessment", "request_id")), ()),
    "set_finding_disposition": (
        (_P + ("finding_id", "disposition", "rationale")),
        (
            "evidence_refs",
            "disposition_reference",
            "supersedes_finding_id",
            "request_id",
        ),
    ),
    "link_fixing_packet": (
        (_P + ("finding_id", "packet_id", "expected_correction")),
        ("required_regression_evidence", "required_campaign_ids", "request_id"),
    ),
    "request_change_acceptance": ((_P + ("change_id", "acceptance_reference")), _R),
}

_ASSURANCE_ENUMS = {
    "record_finding": {
        "severity": tuple(item.value for item in ReviewFindingSeverity),
        "finding_kind": ("semantic", "engineering", "informational", "unspecified"),
    },
    "set_finding_disposition": {
        "disposition": tuple(item.value for item in FindingDisposition),
    },
}

_ASSURANCE = {
    operation: _c(
        "fow_assurance",
        operation,
        required,
        optional,
        enums=_ASSURANCE_ENUMS.get(operation),
        guidance={
            "engineer_gate": "Technical investigation/architecture/reuse are engineer-owned. Semantic mismatch requires current canonical reread and a linked ordinary corrective with explicit regression; human clarification concerns intended behavior or requested scope change.",
            "assessment_schema": {"expected_intent_fingerprint": "from get_finding", "expected_finding_fingerprint": "from get_finding", "classification": "correction_within_intent|intent_change_required|needs_clarification", "rationale": "bounded host judgment after canonical reread", "technical_decisions": ["selected technical realization"], "evidence_refs": ["declared source evidence"]} if operation == "reassess_intent" else {},
            "provenance": "Host-declared reassessment is not provider-audited semantic truth or human acceptance. Exact request replay returns original history before currentness.",
        },
    )
    for operation, (required, optional) in _ASSURANCE_FIELDS.items()
}

_RUN_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "create_run": (
        (_P + ("change_id", "packet_id", "objective")),
        ("orchestrator_ref", "external_ref", "source_ref", "request_id"),
    ),
    "get_run": ((_P + ("run_id",)), ()),
    "add_step": (
        (_P + ("run_id", "title", "action")),
        ("target_refs", "evidence_refs", "step_required", "request_id"),
    ),
    "link_step_dependency": ((_P + ("run_id", "step_id", "depends_on_step_id")), _R),
    "start_step": ((_P + ("run_id", "step_id")), _R),
    "complete_step": ((_P + ("run_id", "step_id", "evidence_refs")), _R),
    "block_step": (
        (_P + ("run_id", "step_id", "blocking_reason", "next_expected_action")),
        _R,
    ),
    "cancel_step": ((_P + ("run_id", "step_id", "reason")), _R),
    "complete_run": ((_P + ("run_id", "completion_reference")), _R),
    "cancel_run": ((_P + ("run_id", "reason")), _R),
    "task_view": ((_P + ("run_id",)), ()),
}
_RUN = {
    operation: _c("fow_run", operation, required, optional)
    for operation, (required, optional) in _RUN_FIELDS.items()
}

_HANDOVER = {
    "create_handover": _c(
        "fow_handover",
        "create_handover",
        ("project_id", "operation", "change_id", "packet_id", "run_id", "actor"),
        ("profile_version", "request_id"),
    ),
    "get_handover": _c(
        "fow_handover", "get_handover", ("project_id", "operation", "handover_id")
    ),
    "resume_context": _c(
        "fow_handover",
        "resume_context",
        ("project_id", "operation"),
        ("change_id", "packet_id", "run_id"),
    ),
    "ledger_projection": _c(
        "fow_handover",
        "ledger_projection",
        ("project_id", "operation"),
        ("projection_kind",),
    ),
    "project_state_snapshot": _c(
        "fow_handover",
        "project_state_snapshot",
        ("project_id", "operation"),
        ("focus_kind", "focus_ref", "limit"),
        enums={
            "focus_kind": (
                "project",
                "milestone",
                "use_case",
                "sequence",
                "packet",
                "gate",
            )
        },
    ),
}
_HANDOVER["project_progress"] = _c("fow_handover", "project_progress", ("project_id", "operation", "milestone_ids"))


_GOAL = {
    "view": _c(
        "fow_goal",
        "view",
        ("project_id", "operation"),
        ("view", "detail_level", "offset", "limit"),
        enums={
            "view": ("summary", "nodes", "edges", "candidates"),
            "detail_level": ("standard", "audit"),
        },
    ),
    "add_use_case": _c(
        "fow_goal",
        "add_use_case",
        (
            "project_id",
            "operation",
            "actor",
            "title",
            "use_case_actor",
            "objective",
            "observable_outcome",
        ),
        (
            "preconditions",
            "postconditions",
            "invariants",
            "source_anchor",
            "request_id",
        ),
    ),
    "add_sequence": _c(
        "fow_goal",
        "add_sequence",
        (
            "project_id",
            "operation",
            "actor",
            "title",
            "participants",
            "normal_steps",
            "expected_effects",
        ),
        ("alternate_steps", "failure_steps", "source_anchor", "request_id"),
    ),
    "add_behavioral_expectation": _c(
        "fow_goal",
        "add_behavioral_expectation",
        (
            "project_id",
            "operation",
            "actor",
            "title",
            "statement",
            "category",
            "observable_outcome",
        ),
        ("source_anchor", "request_id"),
    ),
    "link": _c(
        "fow_goal",
        "link",
        (
            "project_id",
            "operation",
            "actor",
            "source_goal_id",
            "target_goal_id",
            "relation",
        ),
        ("request_id",),
    ),
    "derive_requirement_candidates": _c(
        "fow_goal",
        "derive_requirement_candidates",
        ("project_id", "operation", "actor"),
        ("request_id",),
    ),
}

_PACKET_UNIT_GUIDANCE: Mapping[str, object] = MappingProxyType(
    {
        "required_fields": (
            "client_unit_key",
            "operation_kind",
            "instructions",
            "unit_checks",
        ),
        "optional_fields": (
            "target_description",
            "member_label",
            "file_path",
            "constraints",
            "out_of_scope",
            "depends_on",
            "replaces",
            "surface",
            "implements",
            "provides",
            "requires",
            "verifies",
        ),
        "operation_kinds": (
            "modify_existing",
            "delete_existing",
            "new_file",
            "extract_move",
            "insert_in_file",
            "replace_region",
        ),
        "surfaces": CODINGCASTLE_PROVIDER_SURFACES,
        "target_rule": (
            "Existing-code units describe one semantic target; provider-backed "
            "selection retains exact technical identity."
        ),
        "future_destination_rule": (
            "new_file and extract_move require a repository-relative file_path; "
            "new_file cannot declare target_description."
        ),
        "member_rule": (
            "Omit member_label when one owned provider member is unambiguous; "
            "never infer it from a path or project identifier."
        ),
        "surface_rule": (
            "Use repo for product source, workspace for staged product output, "
            "docs for documentation, test_repo for versioned repository tests, "
            "and cc_test only for CodingCastle-managed harness tests. Preserve "
            "the provider surface exactly; Flower does not infer it from a path."
        ),
        "instruction_rule": (
            "Instructions state ordered work to perform; an objective, identifier, "
            "or expected outcome never substitutes for those actions."
        ),
        "unit_check_rule": (
            "Keep unit_checks local to this unit instead of copying packet-wide "
            "completion criteria into every unit."
        ),
        "standalone_validation_declarations": {
            "implements": [1],
            "provides": [{"name": "example-api", "kind": "api", "clauses": ["The API exposes the declared behavior."], "file_path": "src/example.py", "symbol": "example", "signature": "example(value)"}],
            "requires": [{"producer_unit_key": "predecessor-key", "contract_name": "example-api", "use": "Consume this API to implement the unit behavior."}],
            "verifies": [{"criterion": 1, "kind": "unit_check", "statement": "The API exposes the declared behavior."}],
            "contract_kinds": ["symbol", "api", "data_shape", "protocol", "behavioral_boundary"],
            "verification_kinds": ["unit_check", "deterministic_campaign", "live_campaign", "oracle", "explicit_authority"],
            "temporal_rule": "Only unit_check is current local work. Campaign/Oracle/explicit-authority checks remain deferred. Planned paths/symbols do not assert source exists. Consumer refers to one declared predecessor contract without copying clauses.",
        },
        "deletion_rule": (
            "delete_existing selects exactly one current parser symbol; Flower emits "
            "no byte range and the provider performs deterministic deletion."
        ),
        "invalid_patterns": (
            "instructions containing only the packet objective",
            "instructions containing only identifiers or symbol names",
            "caller-supplied provider graph, binding, or chunk identities",
            "packet-wide checks duplicated as unit checks",
        ),
    }
)

_WORKSPACE_REVIEW_GUIDANCE: Mapping[str, object] = MappingProxyType(
    {
        "finding_item": {
            "required_fields": (
                "provider_finding_ref",
                "severity",
                "title",
                "rationale",
                "expected_correction",
                "scope_kind",
                "scope_ref",
            ),
            "optional_fields": ("source_anchor",),
            "accepted_values": {
                "severity": tuple(item.value for item in ReviewFindingSeverity),
            },
            "example": {
                "provider_finding_ref": "provider-finding-reference",
                "severity": ReviewFindingSeverity.HIGH.value,
                "title": "Bounded finding title",
                "rationale": "Current evidence demonstrates the finding.",
                "expected_correction": "Correct the bounded behavior.",
                "scope_kind": "workspace_candidate",
                "scope_ref": "candidate-relative-scope",
                "source_anchor": "optional-source-anchor",
            },
        },
        "disposition_rules": {
            WorkspaceReviewDisposition.APPROVED.value: (
                "requires completeness=complete and forbids findings or "
                "existing_finding_ids"
            ),
            WorkspaceReviewDisposition.FINDINGS.value: (
                "requires at least one findings item or existing_finding_ids value"
            ),
            WorkspaceReviewDisposition.REJECTED.value: (
                "requires at least one findings item or existing_finding_ids value"
            ),
        },
    }
)

_CAMPAIGN_SOURCE_ATTESTATION_GUIDANCE: Mapping[str, object] = MappingProxyType(
    {
        "harness": {
            "required_fields": ("disposition", "participants"),
            "accepted_values": {
                "disposition": TEST_HARNESS_DISPOSITIONS,
            },
            "participant": {
                "required_fields": TEST_HARNESS_PARTICIPANT_FIELDS,
                "optional_fields": (),
                "repository_type": "text or integer provider repository selector",
            },
            "rules": {
                "repository": "participants must be empty",
                "project_integration": "at least two participants are required",
            },
            "example": {
                "disposition": "repository",
                "participants": [],
            },
        },
        "requested_capability": {
            "optional": True,
            "required_fields_when_present": ("language", "framework"),
            "purpose": (
                "Select an unambiguous technical route for authored source; "
                "this does not grant Oracle or source-authoring authority."
            ),
            "example": {"language": "python", "framework": "pytest"},
        },
    }
)

_PACKET_AUTHOR = {
    "start_packet": _c(
        "fow_packet_author",
        "start_packet",
        (
            "project_id",
            "change_id",
            "operation",
            "title",
            "intent",
            "completion_criteria",
            "purpose",
            "actor",
            "request_id",
        ),
        (
            "rationale",
            "milestone_id",
            "requirement_ids",
            "goal_ids",
            "in_scope",
            "out_of_scope",
            "invariants",
            "unresolved_questions",
            "target_policy",
            "active_provider",
            "source_revision",
            "finding_ids",
            "predecessor_packet_id",
            "predecessor_dependency_policy",
            "required_regression_evidence",
            "required_campaign_ids",
        ),
        enums={
            "purpose": ("implementation", "remediation"),
            "predecessor_dependency_policy": ("materialized", "context_only"),
            "target_policy": tuple(item.value for item in PacketTargetPolicy),
        },
    ),
    "revise_packet": _c(
        "fow_packet_author",
        "revise_packet",
        (
            "project_id",
            "packet_id",
            "operation",
            "actor",
            "request_id",
        ),
        (
            "title",
            "intent",
            "rationale",
            "completion_criteria",
            "requirement_ids",
            "goal_ids",
            "in_scope",
            "out_of_scope",
            "invariants",
            "unresolved_questions",
            "expected_spec_revision",
            "expected_plan_revision",
        ),
    ),
    "replace_plan": _c(
        "fow_packet_author",
        "replace_plan",
        ("project_id", "packet_id", "operation", "work_plan", "actor", "request_id"),
        ("answers", "expected_spec_revision", "expected_plan_revision"),
    ),
    "resolve_questions": _c(
        "fow_packet_author",
        "resolve_questions",
        ("project_id", "packet_id", "operation", "answers", "actor", "request_id"),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "answer_gate": _c(
        "fow_packet_author",
        "answer_gate",
        (
            "project_id",
            "packet_id",
            "operation",
            "response",
            "gate_fingerprint",
            "actor",
            "request_id",
        ),
        ("expected_spec_revision", "expected_plan_revision"),
        enums={
            "response.disposition": ("answered", "waived", "blocked"),
            "response.temporal_authority": tuple(
                item.value for item in PacketAnswerTemporalAuthority
            ),
        },
    ),
    "add_unit": _c(
        "fow_packet_author",
        "add_unit",
        ("project_id", "packet_id", "operation", "actor", "request_id"),
        (
            "unit",
            "client_unit_key",
            "target_selection",
            "expected_spec_revision",
            "expected_plan_revision",
        ),
        enums={
            "unit.operation_kind": tuple(
                str(value) for value in _PACKET_UNIT_GUIDANCE["operation_kinds"]
            ),
            "unit.surface": tuple(
                str(value) for value in _PACKET_UNIT_GUIDANCE["surfaces"]
            ),
        },
        guidance={"unit": dict(_PACKET_UNIT_GUIDANCE)},
    ),
    "revise_unit": _c(
        "fow_packet_author",
        "revise_unit",
        (
            "project_id",
            "packet_id",
            "operation",
            "client_unit_key",
            "unit_patch",
            "actor",
            "request_id",
            "expected_plan_revision",
        ),
        ("expected_spec_revision",),
    ),
    "remove_unit": _c(
        "fow_packet_author",
        "remove_unit",
        (
            "project_id",
            "packet_id",
            "operation",
            "client_unit_key",
            "actor",
            "request_id",
            "expected_plan_revision",
        ),
        ("expected_spec_revision",),
    ),
    "rebind_unit": _c(
        "fow_packet_author",
        "rebind_unit",
        (
            "project_id",
            "packet_id",
            "operation",
            "client_unit_key",
            "unit_patch",
            "actor",
            "request_id",
            "expected_plan_revision",
        ),
        ("expected_spec_revision",),
    ),
    "set_dependencies": _c(
        "fow_packet_author",
        "set_dependencies",
        (
            "project_id",
            "packet_id",
            "operation",
            "client_unit_key",
            "depends_on",
            "actor",
            "request_id",
            "expected_plan_revision",
        ),
        ("expected_spec_revision",),
    ),
}

_PACKET_ADVANCE = {
    "advance": _c(
        "fow_packet_advance",
        "advance",
        ("project_id", "packet_id", "actor", "request_id"),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "accept_work_plan": _c(
        "fow_packet_advance",
        "accept_work_plan",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.rationale",
            "actor",
            "request_id",
        ),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "reject_work_plan": _c(
        "fow_packet_advance",
        "reject_work_plan",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.rationale",
            "actor",
            "request_id",
        ),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "accept_residual_risk": _c(
        "fow_packet_advance",
        "accept_residual_risk",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.accepted_risk_ref",
            "actor",
            "request_id",
        ),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "retry_provider_rejection": _c(
        "fow_packet_advance",
        "retry_provider_rejection",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.rationale",
            "actor",
            "request_id",
        ),
        ("expected_spec_revision", "expected_plan_revision"),
    ),
    "record_workspace_review": _c(
        "fow_packet_advance",
        "record_workspace_review",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.review.provider_revision",
            "decision.review.workspace_candidate_id",
            "decision.review.candidate_revision",
            "decision.review.provider_review_ref",
            "decision.review.completeness",
            "decision.review.disposition",
            "decision.review.reviewed_target_refs",
            "decision.review.evidence_refs",
            "actor",
            "request_id",
        ),
        (
            "decision.review.findings",
            "decision.review.existing_finding_ids",
            "expected_spec_revision",
            "expected_plan_revision",
        ),
        enums={
            "decision.review.completeness": tuple(
                item.value for item in WorkspaceReviewCompleteness
            ),
            "decision.review.disposition": tuple(
                item.value for item in WorkspaceReviewDisposition
            ),
            "decision.review.findings[].severity": tuple(
                item.value for item in ReviewFindingSeverity
            ),
        },
        guidance={"workspace_review": dict(_WORKSPACE_REVIEW_GUIDANCE)},
    ),
    "resolve_reconciliation_residual": _c(
        "fow_packet_advance",
        "resolve_reconciliation_residual",
        (
            "project_id",
            "packet_id",
            "decision.operation",
            "decision.disposition",
            "decision.rationale",
            "actor",
            "request_id",
        ),
        ("decision.policy_ref", "expected_spec_revision", "expected_plan_revision"),
        enums={
            "decision.disposition": (
                "accepted",
                "rejected",
                "waived",
                "escalated",
                "investigate",
            )
        },
    ),
}

_PACKET_INSPECT = {
    view: _c(
        "fow_packet_inspect",
        view,
        ("project_id", "packet_id", "view"),
        ("detail_level", "offset", "limit"),
        enums={"detail_level": ("standard", "audit")},
    )
    for view in (
        "summary",
        "units",
        "gates",
        "working_sheet",
        "history",
        "requirements",
    )
}

_CAMPAIGN_AUTHOR = {
    "start": _c(
        "fow_campaign_author",
        "start",
        _P + ("request_id", "title", "scope.change_id"),
        (
            "scope.milestone_id",
            "scope.requirement_ids",
            "scope.goal_ids",
            "scope.packet_ids",
            "scope.finding_ids",
            "scope.invariants",
            "scope.environment_assumptions",
            "case",
        ),
    ),
    "edit_scope": _c(
        "fow_campaign_author",
        "edit_scope",
        _P + ("request_id", "campaign_id", "title", "scope.change_id"),
        (
            "scope.milestone_id",
            "scope.requirement_ids",
            "scope.goal_ids",
            "scope.packet_ids",
            "scope.finding_ids",
            "scope.invariants",
            "scope.environment_assumptions",
            "expected_fingerprint",
        ),
    ),
    "add_case": _c(
        "fow_campaign_author",
        "add_case",
        _P
        + (
            "request_id",
            "campaign_id",
            "case.title",
            "case.purpose",
            "case.case_kind",
            "case.action",
            "case.expected_outcome",
            "case.observation_point",
        ),
        (
            "case.prohibited_outcome",
            "case.setup",
            "case.cleanup",
            "case.execution_class",
            "case.required",
            "case.obligation_ids",
            "case.oracle_kind",
            "expected_fingerprint",
        ),
    ),
    "edit_case": _c(
        "fow_campaign_author",
        "edit_case",
        _P
        + (
            "request_id",
            "campaign_id",
            "case_id",
            "case.title",
            "case.purpose",
            "case.case_kind",
            "case.action",
            "case.expected_outcome",
            "case.observation_point",
        ),
        (
            "case.prohibited_outcome",
            "case.setup",
            "case.cleanup",
            "case.execution_class",
            "case.required",
            "case.obligation_ids",
            "case.oracle_kind",
            "expected_fingerprint",
        ),
    ),
    "remove_case": _c(
        "fow_campaign_author",
        "remove_case",
        _P + ("request_id", "campaign_id", "case_id", "rationale"),
        ("expected_fingerprint",),
    ),
    "reorder_cases": _c(
        "fow_campaign_author",
        "reorder_cases",
        _P + ("request_id", "campaign_id", "case_order"),
        ("expected_fingerprint",),
    ),
    "decide_obligation": _c(
        "fow_campaign_author",
        "decide_obligation",
        _P + ("request_id", "campaign_id", "obligation_id", "decision", "rationale"),
        enums={
            "decision": tuple(
                item.value
                for item in CampaignObligationDecision
                if item != CampaignObligationDecision.UNCLASSIFIED
            )
        },
    ),
    "bind_obligation": _c(
        "fow_campaign_author",
        "bind_obligation",
        _P
        + ("request_id", "campaign_id", "case_id", "obligation_id", "coverage_intent"),
    ),
    "author_oracle": _c(
        "fow_campaign_author",
        "author_oracle",
        _P
        + (
            "request_id",
            "campaign_id",
            "case_id",
            "oracle.oracle_kind",
            "oracle.subject_bindings",
            "oracle.authority_reference",
            "oracle.semantic_fields",
        ),
        ("oracle.goal_bindings", "oracle_id"),
    ),
    "answer_question": _c(
        "fow_campaign_author",
        "answer_question",
        _P
        + (
            "request_id",
            "campaign_id",
            "oracle_id",
            "question_id",
            "answer",
            "answer_authority",
            "provenance",
        ),
        ("waiver_scope",),
        enums={"answer_authority": tuple(item.value for item in OracleAnswerAuthority)},
    ),
    "attest_source": _c(
        "fow_campaign_author",
        "attest_source",
        _P
        + (
            "request_id",
            "campaign_id",
            "case_id",
            "source_files",
            "authority_reference",
        ),
        (
            "harness",
            "requested_capability.language",
            "requested_capability.framework",
        ),
        enums={"harness.disposition": TEST_HARNESS_DISPOSITIONS},
        guidance={
            "source_attestation": dict(_CAMPAIGN_SOURCE_ATTESTATION_GUIDANCE)
        },
    ),
    "authorize_materialization": _c(
        "fow_campaign_author",
        "authorize_materialization",
        _P
        + (
            "request_id",
            "campaign_id",
            "case_id",
            "requested_capability.language",
            "requested_capability.framework",
            "authority_reference",
        ),
        ("requested_capability.artifact_scope_preference",),
    ),
    "retry_provider_rejection": _c(
        "fow_campaign_author",
        "retry_provider_rejection",
        _P
        + (
            "request_id",
            "campaign_id",
            "provider_command_id",
            "rationale",
        ),
    ),
    "authorize_promotion": _c(
        "fow_campaign_author",
        "authorize_promotion",
        _P
        + (
            "request_id",
            "campaign_id",
            "case_id",
            "evidence_id",
            "authority_reference",
        ),
        ("regression_obligation",),
    ),
    "accept_exception": _c(
        "fow_campaign_author",
        "accept_exception",
        _P
        + (
            "request_id",
            "campaign_id",
            "exception_obligation_ids",
            "evidence_gaps",
            "risk_authority",
            "disposition_reference",
        ),
    ),
    "cancel": _c(
        "fow_campaign_author",
        "cancel",
        _P + ("request_id", "campaign_id", "disposition_reference"),
    ),
}

_CAMPAIGN_ADVANCE = {
    "advance": _c(
        "fow_campaign_advance",
        "advance",
        ("project_id", "actor", "request_id"),
        ("campaign_id", "change_id", "transition_budget"),
    )
}

_CAMPAIGN_INSPECT = {
    view: _c(
        "fow_campaign_inspect",
        view,
        ("project_id", "view"),
        ("campaign_id", "change_id", "offset", "limit"),
    )
    for view in (
        "summary",
        "working_sheet",
        "cases",
        "obligations",
        "oracles",
        "constructibility",
        "oracle_ir",
        "attestation",
        "evidence",
        "residuals",
        "history",
    )
}


_SIMPLE_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "fow_capabilities": (
        (),
        ("view", "recipe_name", "operation_tool", "operation_name"),
    ),
    "fow_create_project": (("project_id", "name", "actor"), ("request_id",)),
    "fow_register_requirement": (
        ("project_id", "title", "statement", "category", "rationale", "actor"),
        ("source_anchor", "request_id"),
    ),
    "fow_get_requirement": (("project_id", "requirement_id"), ()),
    "fow_revise_requirement": (
        (
            "project_id",
            "requirement_id",
            "title",
            "statement",
            "category",
            "rationale",
            "actor",
        ),
        ("source_anchor", "request_id"),
    ),
    "fow_set_requirement_lifecycle": (
        ("project_id", "requirement_id", "lifecycle_status", "reason", "actor"),
        ("governed_approval_reference", "request_id"),
    ),
    "fow_record_verification": (
        (
            "project_id",
            "requirement_id",
            "verification_kind",
            "outcome",
            "reference",
            "actor",
        ),
        ("metadata", "request_id"),
    ),
    "fow_traceability": (
        ("project_id",),
        ("milestone_id", "detail_level", "offset", "limit"),
    ),
    "fow_validate_srs": (
        ("project_id", "source_path", "standard_profile", "actor"),
        ("request_id",),
    ),
    "fow_import_srs": (
        ("project_id", "source_path", "standard_profile", "actor"),
        ("request_id",),
    ),
    "fow_revise_srs_baseline": (
        (
            "project_id",
            "previous_baseline_id",
            "source_path",
            "standard_profile",
            "actor",
        ),
        ("governed_approval_reference", "request_id"),
    ),
    "fow_promote_milestone": (
        (
            "project_id",
            "name",
            "requirement_ids",
            "dependency_closure_ids",
            "entry_policy",
            "exit_policy",
            "risk_disposition",
            "actor",
        ),
        ("acceptance_evidence", "request_id"),
    ),
    "fow_accept_milestone": (
        ("project_id", "milestone_id", "acceptance_evidence", "actor"),
        ("request_id",),
    ),
    "fow_audit_phase": (
        ("project_id", "scope_id", "actor"),
        ("requirement_ids", "request_id"),
    ),
    "fow_what_next": (
        ("project_id",),
        ("milestone_id", "scope_id", "detail_level", "offset", "limit"),
    ),
    "fow_generate_artifacts": (("project_id", "profile_id", "actor"), ("request_id",)),
    "fow_get_artifacts": (
        ("project_id",),
        ("generation_id", "artifact_kind", "include_content"),
    ),
    "fow_ground_intent": (
        ("project_id", "goal_node_ids", "actor"),
        ("source_revision", "request_id"),
    ),
    "fow_get_job": (("project_id", "job_id"), ()),
    "fow_list_jobs": (("project_id",), ()),
}

_SIMPLE_ENUMS: Mapping[str, Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "fow_capabilities": MappingProxyType(
            {"view": ("summary", "recipe", "operation", "docs", "full")}
        ),
        "fow_record_verification": MappingProxyType(
            {
                "verification_kind": tuple(item.value for item in VerificationKind),
                "outcome": tuple(item.value for item in VerificationOutcome),
            }
        ),
    }
)


_SIMPLE = {
    tool: _c(
        tool,
        "call",
        required,
        optional,
        enums=_SIMPLE_ENUMS.get(tool),
        injected_inputs=("actor", "request_id")
        if tool == "fow_create_project"
        else None,
    )
    for tool, (required, optional) in _SIMPLE_FIELDS.items()
}

_INTERACTION_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "status": (("interaction_session_ref", "operation"), ()),
    "discover": (
        ("interaction_session_ref", "operation"),
        ("query", "limit", "page_action"),
    ),
    "open": (("interaction_session_ref", "operation"), ()),
    "select_project": (
        ("interaction_session_ref", "operation"),
        ("project_id", "project_selection", "actor", "request_id"),
    ),
    "switch_project": (
        ("interaction_session_ref", "operation"),
        ("project_id", "project_selection", "actor", "request_id"),
    ),
    "clear_project": (
        ("interaction_session_ref", "operation"),
        ("actor", "request_id"),
    ),
    "select": (
        ("interaction_session_ref", "operation", "area"),
        ("actor", "request_id"),
    ),
    "switch": (
        ("interaction_session_ref", "operation", "area"),
        ("actor", "request_id"),
    ),
    "clear": (("interaction_session_ref", "operation"), ("actor", "request_id")),
    "frame": (("interaction_session_ref", "operation"), ()),
    "resolve": (("interaction_session_ref", "operation", "frame_ref", "selection"), ()),
    "goal_hook": (
        ("interaction_session_ref", "operation", "trigger"),
        (
            "previous_anchor_fingerprint",
            "trigger_ref",
            "breath_available",
        ),
    ),
}

# The public MCP schema and exact operation help derive from the same registry
# keys.  Keeping this enum here avoids a second interaction-operation list.
InteractionOperation = StrEnum(
    "InteractionOperation",
    {operation.upper(): operation for operation in _INTERACTION_FIELDS},
    module=__name__,
)

_INTERACTION = {
    operation: _c(
        "fow_interaction",
        operation,
        required,
        optional,
        enums={
            "operation": (operation,),
            **(
                {
                    "trigger": (
                        "goal_started",
                        "goal_resumed",
                        "lens_changed",
                        "bounded_work_completed",
                        "asynchronous_wake",
                        "breath_resumed",
                        "context_reconstructed",
                        "structural_no_progress",
                    )
                }
                if operation == "goal_hook"
                else {}
            ),
        },
        area="project_bootstrap"
        if "project" in operation or operation in {"status", "open"}
        else "interaction",
        injected_inputs=tuple(
            field
            for field in (*required, *optional)
            if field
            in {
                "interaction_session_ref",
                "operation",
                "actor",
                "request_id",
                "frame_ref",
                "trigger",
                "previous_anchor_fingerprint",
                "trigger_ref",
                "breath_available",
            }
        ),
        paging_owner="interaction_projection" if operation == "discover" else "none",
    )
    for operation, (required, optional) in _INTERACTION_FIELDS.items()
}

_EXTERNAL_WORK_FIELDS = {
    "set_mode": (("payload.mode", "payload.expected_spec_revision", "payload.expected_plan_revision"), ()),
    "upgrade_validation": (("payload.expected_spec_revision", "payload.expected_plan_revision"), ()),
    "criteria": ((), ()),
    "reconcile_criteria": (("payload.expected_spec_revision", "payload.rationale", "payload.criteria"), ("payload.new_statements",)),
    "add_criterion": (("payload.statement", "payload.expected_spec_revision"), ()),
    "edit_criterion": (("payload.number", "payload.statement", "payload.expected_spec_revision"), ()),
    "remove_criterion": (("payload.number", "payload.expected_spec_revision"), ()),
    "validation": ((), ("payload.detail",)),
    "export_plan": (("payload.expected_spec_revision", "payload.expected_plan_revision"), ("payload.allow_draft",)),
    "todo": ((), ("payload.unit_key",)),
    "report_outcome": (("payload.report_key", "payload.expected_spec_revision", "payload.expected_plan_revision", "payload.authority_fingerprint", "payload.unit_key", "payload.outcome", "payload.summary", "payload.source_revision", "payload.artifacts", "payload.produced_contracts", "payload.verification", "payload.unresolved"), ()),
    "reconcile_outcome": (("payload.report_key", "payload.expected_spec_revision", "payload.expected_plan_revision", "payload.rationale"), ()),
}
_EXTERNAL_WORK = {
    op: _c(
        "fow_external_work", op,
        ("project_id", "change_id", "packet_id", *required, *(() if op in {"criteria", "validation", "todo"} else ("actor", "request_id"))),
        (*optional, *(("request_id",) if op in {"criteria", "validation", "todo"} else ())),
        guidance={
            "scope": "Flower-to-external-agent handoff only; full cross-server PVP is deferred.",
            "authority": "Use current specification/plan revisions and authority_fingerprint returned by validation/todo. Stale reports remain history and cannot complete current work.",
            "report_schema": {
                "artifacts": [{"reference": "repository-relative or declared evidence locator", "description": "what was produced", "sha256": "optional content SHA-256"}],
                "produced_contracts": [{"name": "producer declaration name", "artifact_ref": "one reported artifact reference"}],
                "verification": [{"criterion": 1, "kind": "unit_check|deterministic_campaign|live_campaign|oracle|explicit_authority", "statement": "exact declared verification intent", "status": "pass|fail|not_run", "evidence_ref": "declared evidence", "provenance": "host-reported"}],
                "unresolved": ["remaining obligations"],
            } if op == "report_outcome" else {},
        },
    ) for op, (required, optional) in _EXTERNAL_WORK_FIELDS.items()
}
_BINDINGS = {
    op: _c("fow_bindings", op, required, optional, guidance={
        "receipt": {"contract": "flow.project-association.v1", "project_id": "selected lifecycle project", "association": {"kind": "host", "host_id": "host identity", "repository_locator": "deployment path, not audited source identity"}},
        "provider_association": {"kind": "implementation_provider", "provider_kind": "implementation_graph|bootstrap_behavior|packet_evidence|packet_execution|test_execution", "route_id": "configured-mcp/{provider_kind}", "scope_id": "authorized scope", "provider_context_id": "provider context", "surfaces": ["repo"], "repository": None},
        "authority": "Only already configured routes may bind. Unknown receipt fields are rejected. Changed association requires replacement_reason; exact replay creates no duplicate event.",
    }) for op, required, optional in (
        ("inspect", ("project_id",), ()),
        ("export", ("project_id", "association_kind"), ("host_id", "provider_kind")),
        ("import", ("project_id", "association_receipt", "actor"), ("replacement_reason", "request_id")),
    )
}
_SEMANTIC = {
    op: _c("fow_semantic", op, required, optional,
           enums={"execution_mode": ("host", "internal"), "role": ("srs_semantic_validation", "intention_grounding")} if op == "prepare" else {}, guidance={
        "role": "SRS and intention_grounding support host/internal using shared contracts. SRS requires source_path/standard_profile. Grounding requires goal_node_ids and host mode requires the exact flower-host-grounding-evidence-v1 receipt. Host observed-behavior drafting remains unsupported.",
        "result_schema": {"findings": [{"code": "string", "severity": "error|warning|info", "section_id": "prepared allowed section", "entity_id": "prepared allowed entity", "message": "string, max 1000 characters"}]},
        "limits": "At most 128 findings/128000 encoded bytes; every finding field required; unknown fields and invented identities rejected.",
        "adoption": "Submit validates only; adopt records canonical validation/grounding audit with declared execution/evidence provenance. Neither imports a baseline nor accepts intent or a milestone. execute_internal is an explicit bounded invocation on an internal-mode assignment.",
    }) for op, required, optional in (
        ("inventory", ("project_id",), ()),
        ("prepare", ("project_id", "role", "execution_mode", "actor"), ("source_path", "standard_profile", "goal_node_ids", "host_evidence", "source_revision", "request_id")),
        ("inspect", ("project_id", "assignment_id"), ()),
        ("submit", ("project_id", "assignment_id", "result", "executor_ref", "actor"), ("source_revision", "request_id",)),
        ("adopt", ("project_id", "assignment_id", "actor"), ("request_id",)),
        ("execute_internal", ("project_id", "assignment_id", "actor"), ("request_id",)),
    )
}

_BY_TOOL: Mapping[str, Mapping[str, OperationContract]] = MappingProxyType(
    {
        **{
            tool: MappingProxyType({"call": contract})
            for tool, contract in _SIMPLE.items()
        },
        "fow_interaction": MappingProxyType(_INTERACTION),
        "fow_bootstrap": MappingProxyType(_BOOTSTRAP),
        "fow_change": MappingProxyType(_CHANGE),
        "fow_assurance": MappingProxyType(_ASSURANCE),
        "fow_run": MappingProxyType(_RUN),
        "fow_handover": MappingProxyType(_HANDOVER),
        "fow_goal": MappingProxyType(_GOAL),
        "fow_packet_author": MappingProxyType(_PACKET_AUTHOR),
        "fow_packet_advance": MappingProxyType(_PACKET_ADVANCE),
        "fow_packet_inspect": MappingProxyType(_PACKET_INSPECT),
        "fow_campaign_author": MappingProxyType(_CAMPAIGN_AUTHOR),
        "fow_campaign_advance": MappingProxyType(_CAMPAIGN_ADVANCE),
        "fow_campaign_inspect": MappingProxyType(_CAMPAIGN_INSPECT),
        "fow_external_work": MappingProxyType(_EXTERNAL_WORK),
        "fow_bindings": MappingProxyType(_BINDINGS),
        "fow_semantic": MappingProxyType(_SEMANTIC),
    }
)


def operation_contract(tool: str, operation: str) -> Mapping[str, object]:
    tool_name = str(tool or "").strip()
    operation_name = str(operation or "").strip()
    if tool_name not in _BY_TOOL:
        raise ValueError(
            "operation_tool must identify one of: " + ", ".join(sorted(_BY_TOOL))
        )
    contracts = _BY_TOOL[tool_name]
    if operation_name not in contracts:
        raise ValueError(
            f"operation_name for {tool_name} must identify one of: "
            + ", ".join(sorted(contracts))
        )
    return contracts[operation_name].as_payload()


def operation_contract_catalog() -> list[Mapping[str, object]]:
    return [
        contracts[operation].as_payload()
        for tool in sorted(_BY_TOOL)
        for operation in sorted(_BY_TOOL[tool])
        for contracts in (_BY_TOOL[tool],)
    ]


def operation_contract_index() -> list[Mapping[str, object]]:
    """Return every route without duplicating exact per-operation input help."""

    return [
        contracts[operation].as_index_payload()
        for tool in sorted(_BY_TOOL)
        for operation in sorted(_BY_TOOL[tool])
        for contracts in (_BY_TOOL[tool],)
    ]


def operation_names(tool: str) -> tuple[str, ...]:
    return tuple(_BY_TOOL.get(str(tool or "").strip(), {}))


def operation_tools() -> tuple[str, ...]:
    return tuple(sorted(_BY_TOOL))


def public_tool_names() -> tuple[str, ...]:
    return tuple(item.name for item in _PUBLIC_TOOLS)


def public_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return _PUBLIC_TOOLS


def public_tool_catalog() -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "name": item.name,
            "area": item.area,
            "owner": item.owner,
            "description": item.description,
        }
        for item in _PUBLIC_TOOLS
    )


def tool_description(name: str) -> str:
    descriptor = _PUBLIC_TOOL_BY_NAME.get(str(name or "").strip())
    if descriptor is None:
        raise KeyError(name)
    return descriptor.description


def work_area_catalog() -> tuple[Mapping[str, str], ...]:
    return tuple(
        {"area": item.name, "label": item.label, "purpose": item.purpose}
        for item in _WORK_AREAS
    )


def operation_descriptors_for_area(area: str) -> tuple[Mapping[str, object], ...]:
    selected = str(area or "").strip()
    return tuple(
        contract.as_payload()
        for contracts in _BY_TOOL.values()
        for contract in contracts.values()
        if contract.area == selected
    )


@lru_cache(maxsize=1)
def registry_version() -> str:
    payload = {
        "tools": list(public_tool_catalog()),
        "areas": list(work_area_catalog()),
        # The version covers exact help as well as the compact index. A change to
        # input shape, accepted values, guidance, or examples must invalidate a
        # host-side registry cache even when its route classifiers are unchanged.
        "operations": operation_contract_catalog(),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "flow.operations." + hashlib.sha256(encoded).hexdigest()[:16]


def render_tool_reference() -> str:
    lines = [
        "Flower tool identity, areas, operations, risk and continuation come from the canonical operation registry.",
        "Request exact operation help for input shape; the current interaction frame owns executable next actions.",
        "",
    ]
    for descriptor in _PUBLIC_TOOLS:
        operations = ", ".join(operation_names(descriptor.name))
        lines.append(
            f"- {descriptor.name} [{descriptor.area}]: "
            f"{descriptor.description} Operations: {operations}."
        )
    return "\n".join(lines)


def change_operation_ownership() -> Mapping[str, str]:
    return MappingProxyType(dict(_CHANGE_OWNER))


def accepted_values_for_error(message: str) -> tuple[str, ...]:
    enum_types = {
        "ReviewFindingSeverity": ("info", "low", "medium", "high", "critical"),
        "FindingDisposition": (
            "open",
            "confirmed",
            "resolved",
            "accepted_exception",
            "deferred",
            "superseded",
            "cancelled",
        ),
        "CampaignObligationDecision": tuple(
            item.value
            for item in CampaignObligationDecision
            if item != CampaignObligationDecision.UNCLASSIFIED
        ),
        "OracleAnswerAuthority": tuple(item.value for item in OracleAnswerAuthority),
        "WorkspaceReviewDisposition": ("approved", "findings", "rejected"),
        "BootstrapPath": tuple(item.value for item in BootstrapPath),
        "PacketAnswerTemporalAuthority": tuple(
            item.value for item in PacketAnswerTemporalAuthority
        ),
    }
    for type_name, values in enum_types.items():
        if type_name in str(message):
            return values
    return ()


def _example(contract: OperationContract) -> Mapping[str, object]:
    result: dict[str, object] = {}
    for field_path in contract.required:
        _set_path(
            result,
            field_path,
            _sample_value(
                field_path,
                contract.operation,
                contract.enums.get(field_path, ()),
            ),
        )
    if contract.tool == "fow_packet_author" and contract.operation == "add_unit":
        result["unit"] = {
            "client_unit_key": "supporting-module",
            "operation_kind": "new_file",
            "file_path": "src/supporting_module.py",
            "instructions": [
                "Create the bounded supporting module.",
                "Export the contract required by its declared consumers.",
            ],
            "unit_checks": ["The required public contract is exported."],
        }
    if contract.tool == "fow_bootstrap":
        if contract.operation == "record_answer":
            result["answer"] = {"answer_key": "successor-scenario", "question": "What should the software do?", "answer": "Return the integer successor through the declared API.", "kind": "intent", "source_reference": "stakeholder:scenario-1"}
        elif contract.operation == "record_correspondence":
            result["correspondence"] = {"answer_key": "successor-scenario", "answer_revision": 1,
                "canonical_references": {"requirement_ids": ["current-requirement-id"], "goal_node_ids": [], "milestone_ids": []},
                "disposition": "consistent", "rationale": "The current canonical requirement expresses the recorded scenario."}
    if contract.tool == "fow_bindings":
        if contract.operation == "import":
            result["association_receipt"] = {
                "contract": "flow.project-association.v1", "project_id": result["project_id"],
                "association": {"kind": "host", "host_id": "coding-agent", "repository_locator": "./repository"},
            }
        elif contract.operation == "export":
            result.update(association_kind="host", host_id="coding-agent")
    if contract.tool == "fow_semantic":
        if contract.operation == "prepare":
            result.update(role="srs_semantic_validation", execution_mode="host", source_path="example-srs.md", standard_profile="fow-srs-markdown-v1")
        elif contract.operation == "submit":
            result["result"] = {"findings": []}
    if contract.tool == "fow_assurance" and contract.operation == "reassess_intent":
        result["assessment"] = {"expected_intent_fingerprint": "from get_finding", "expected_finding_fingerprint": "from get_finding", "classification": "correction_within_intent", "rationale": "Correct implementation within the current recorded behavior.", "technical_decisions": ["Reuse the existing canonical service."], "evidence_refs": ["host-source-review:001"]}
    if contract.tool == "fow_external_work":
        if contract.operation == "set_mode":
            result["payload"]["mode"] = "external_agent"
        elif contract.operation == "reconcile_criteria":
            result["payload"]["criteria"] = [{"number": 1, "statement": "Accepted completion criterion", "active": True}]
        elif contract.operation == "report_outcome":
            result["payload"].update(
                outcome="complete", artifacts=[{"reference": "src/example.py", "description": "implemented declared contract"}],
                produced_contracts=[{"name": "example-api", "artifact_ref": "src/example.py"}],
                verification=[{"criterion": 1, "kind": "unit_check", "statement": "The declared contract is exported.", "status": "pass", "evidence_ref": "tests/example-result", "provenance": "host-reported"}],
                unresolved=[],
            )
    return result


def _sample_value(
    field: str,
    operation: str,
    accepted_values: tuple[str, ...] = (),
) -> object:
    leaf = field.rsplit(".", 1)[-1]
    if accepted_values:
        return accepted_values[0]
    if leaf == "operation":
        return operation
    if leaf.endswith("_ids") or leaf in {
        "surfaces",
        "answers",
        "depends_on",
        "evidence_refs",
        "completion_criteria",
        "selected_candidates",
        "reviewed_target_refs",
        "target_finding_ids",
        "case_order",
        "provenance",
        "subject_bindings",
        "goal_bindings",
    }:
        return ["example-ref"]
    if leaf in {
        "work_plan",
        "packet",
        "unit",
        "unit_patch",
        "intake",
        "contradiction",
        "provider_result",
        "completeness",
        "claims",
        "assertion",
        "case",
        "answer",
        "semantic_fields",
        "source_files",
        "harness",
    }:
        return {}
    if leaf in {
        "case_required",
        "claim_required",
        "claim_dynamic",
        "claim_contradicted",
        "required",
        "regression_obligation",
    }:
        return True
    if leaf in {
        "expected_spec_revision",
        "expected_plan_revision",
        "offset",
        "limit",
        "transition_budget",
        "number",
    }:
        return 1
    if leaf == "disposition" and field == "decision.review.disposition":
        return "approved"
    return f"example-{leaf.replace('_', '-')}"


def _set_path(target: dict[str, object], path: str, value: object) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        nested = current.setdefault(part, {})
        if not isinstance(nested, dict):
            raise RuntimeError(f"operation example path collision: {path}")
        current = nested
    current[parts[-1]] = value
