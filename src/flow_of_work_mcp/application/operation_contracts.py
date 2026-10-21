"""Single runtime registry for multiplexed public operation contracts."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field, replace
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
from flow_of_work_mcp.core.domain.enums import LifecycleStatus, VerificationKind, VerificationOutcome
from flow_of_work_mcp.application.tool_help import (
    FIELD_HELP, FIELD_OVERRIDES, TOOL_EFFECTS, TOOL_GUIDANCE,
)


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
            "field_descriptions": {
                name: parameter_help(self.tool, name,
                    selected_operation=self.operation if self.tool == "fow_bootstrap" else "")["description"]
                for name in dict.fromkeys(
                    path.split(".", 1)[0] for path in (*self.required, *self.optional)
                )
            },
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
        "catalog",
        "state",
        "state_details",
        "view",
        "get_change",
        "get_finding",
        "get_run",
        "get_handover",
        "resume_context",
        "ledger_projection",
        "project_state_snapshot",
        "project_progress",
        "guidance",
        "roadmap",
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
        "provider_validation",
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
    if tool == "fow_external_work" and operation == "negotiate_provider":
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
        "fow_architecture", "project_bootstrap",
        'Define and select the project technical architecture: components, interfaces and engineering decisions. Inspect current authority, propose a complete revision, then explicitly adopt it.',
    ),
    ToolDescriptor(
        "fow_external_work", "packet_lifecycle",
        'Hand a complete revision-bound packet to an external coding agent, export its executable Markdown plan, derive dependency-ordered TODOs and reconcile declared outcomes. Optional provider execution is a separate explicitly selected route.',
    ),
    ToolDescriptor(
        "fow_bindings", "project_bootstrap",
        'Associate an existing lifecycle project with a coding host or optional configured provider through portable versioned JSON receipts. Inspect/export current associations or explicitly import and replace one.',
    ),
    ToolDescriptor(
        "fow_semantic", "requirements",
        'Prepare bounded semantic assignments for an external host or configured internal model, validate their submitted results and separately adopt their audit evidence. Supported roles are SRS semantic validation and intention grounding.',
    ),
    ToolDescriptor(
        "fow_capabilities",
        "project_bootstrap",
        'Discover what Flower can do and how to call it: bounded tool summary, progressive workflow recipes, exact operation inputs/examples or the diagnostic catalog.',
    ),
    ToolDescriptor(
        "fow_create_project",
        "project_bootstrap",
        'Register a uniquely identified local lifecycle project before recording its requirements, goals and implementation work. This creates lifecycle authority rather than repository scaffolding.',
    ),
    ToolDescriptor(
        "fow_interaction",
        "project_bootstrap",
        'Connect this conversation to its durable lifecycle project, discover available work and select one bounded work surface using the issued choices and frame.',
    ),
    ToolDescriptor(
        "fow_register_requirement",
        "requirements",
        'Record one observable software requirement and its source in the selected lifecycle project. Use the returned requirement ID for goals, milestone scope and verification.',
    ),
    ToolDescriptor(
        "fow_get_requirement",
        "requirements",
        'Retrieve one existing requirement, its current canonical state and retained revision history.',
    ),
    ToolDescriptor(
        "fow_revise_requirement",
        "requirements",
        'Change the statement or classification of an existing requirement by appending a canonical revision. Keep intent changes explicit so downstream evidence can be reconciled.',
    ),
    ToolDescriptor(
        "fow_set_requirement_lifecycle",
        "requirements",
        'Move an existing requirement to a policy-permitted lifecycle state with its reason and any required approval reference.',
    ),
    ToolDescriptor(
        "fow_record_verification",
        "assurance",
        'Record evidence actually obtained for a requirement, including verification method, outcome, reference and declared metadata. This records a result rather than running a test.',
    ),
    ToolDescriptor(
        "fow_traceability",
        "assurance",
        'Inspect how current requirements, milestone scope and recorded verification evidence correspond. Read bounded pages or retrieve one original evidence body with audit detail.',
    ),
    ToolDescriptor(
        "fow_goal",
        "goal_graph",
        'Describe intended software behavior as use cases, ordered sequences and behavioral expectations, then link and inspect those goal nodes or derive requirement candidates.',
    ),
    ToolDescriptor(
        "fow_validate_srs",
        "requirements",
        'Check a local Markdown software-requirements document structurally against a supported profile in a durable job. Semantic assignment validation is exposed separately by fow_semantic.',
    ),
    ToolDescriptor(
        "fow_import_srs",
        "requirements",
        'Import an eligible local Markdown SRS as the initial canonical requirement baseline, preserving validated source provenance. Existing baseline changes use fow_revise_srs_baseline.',
    ),
    ToolDescriptor(
        "fow_revise_srs_baseline",
        "requirements",
        'Apply a source-proven revision to the current SRS baseline, classifying changes and retaining approval requirements and immutable history.',
    ),
    ToolDescriptor(
        "fow_promote_milestone",
        "milestones",
        'Create planned milestone scope from canonical requirements, dependencies and entry/exit/risk policies. Actual result acceptance uses fow_accept_milestone.',
    ),
    ToolDescriptor(
        "fow_accept_milestone",
        "milestones",
        'Record governed acceptance of an eligible milestone using actual acceptance evidence after its required verification and campaign gates.',
    ),
    ToolDescriptor(
        "fow_audit_phase",
        "assurance",
        'Compare current requirement traceability with the previous snapshot of a named scope and retain the resulting phase audit as a durable local job.',
    ),
    ToolDescriptor(
        "fow_what_next",
        "changes",
        'Find the next bounded lifecycle action from current packet gates, dependencies, requirements and evidence. Reading this projection does not execute the suggested work.',
    ),
    ToolDescriptor(
        "fow_generate_artifacts",
        "handover",
        'Render and retain project lifecycle documents using an existing artifact profile in a durable local job. The host publishes or saves returned artifacts separately.',
    ),
    ToolDescriptor(
        "fow_get_artifacts",
        "handover",
        'Retrieve retained artifact generations and optionally their document contents, filtered by generation or artifact kind.',
    ),
    ToolDescriptor(
        "fow_ground_intent",
        "changes",
        'Run the configured internal intention-grounding workflow to compare selected goals with implementation evidence. For an external host assignment use fow_semantic.',
    ),
    ToolDescriptor("fow_get_job", "handover", 'Retrieve the status, result or failure of one previously scheduled durable job without starting or retrying it.'),
    ToolDescriptor("fow_list_jobs", "handover", 'List the durable jobs already recorded for one lifecycle project without scheduling additional work.'),
    ToolDescriptor(
        "fow_bootstrap",
        "project_bootstrap",
        'Turn stakeholder scenarios into recorded lifecycle intent and an explicitly confirmed roadmap, then track correspondence, progress choices and completion of that bootstrap cycle.',
    ),
    ToolDescriptor(
        "fow_change",
        "changes",
        'Record a governed change and manage its packet readiness, engineering questions, evidence reconciliation, dependencies and risk dispositions. Author the executable packet plan with fow_packet_author.',
    ),
    ToolDescriptor(
        "fow_assurance",
        "assurance",
        'Record and inspect software assurance findings, reassess them against current intent, associate corrective packets and request guarded change acceptance using actual evidence.',
    ),
    ToolDescriptor(
        "fow_run",
        "changes",
        'Track who performs the implementation work: record a run, ordered dependent steps and their started/completed/blocked/cancelled states. The coding agent performs those actions outside Flower.',
    ),
    ToolDescriptor(
        "fow_handover",
        "handover",
        'Read coherent project progress and lifecycle context or retain a durable handover snapshot that another agent can inspect and resume.',
    ),
    ToolDescriptor(
        "fow_packet_author",
        "packet_lifecycle",
        'Define the bounded implementation work in a packet: complete instructions, stable plan units, dependencies, producer/consumer contracts and checks. Resolve engineering questions through ordinary authoring before execution.',
    ),
    ToolDescriptor(
        "fow_packet_advance",
        "packet_lifecycle",
        'Move an existing packet through its ordinary lifecycle gates and admitted provider delivery, or only synchronize authoring deltas without starting execution. Semantic decisions answer the exact current gate.',
    ),
    ToolDescriptor(
        "fow_packet_inspect",
        "packet_lifecycle",
        'Inspect a packet scope, executable units, current gates, requirements, working sheet or retained history without advancing or executing it.',
    ),
    ToolDescriptor(
        "fow_campaign_author",
        "campaigns",
        'Define and revise a verification campaign: scope, cases, obligations, behavioral Oracles, source attestations and explicit materialization or promotion authority.',
    ),
    ToolDescriptor(
        "fow_campaign_advance",
        "campaigns",
        'Perform bounded deterministic progression of an existing verification campaign until the next semantic, evidence or provider boundary requires attention.',
    ),
    ToolDescriptor(
        "fow_campaign_inspect",
        "campaigns",
        'Inspect one campaign scope, cases, obligations, Oracle contracts, attestations, evidence, residuals or history without progressing it.',
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
_ARCHITECTURE_REFS_GUIDANCE = {
    "shape": [{"revision": 1, "kind": "decision", "entity_id": "loop-owner"}],
    "authority": "Select at most128 unique component/interface/decision references from one adopted project architecture revision. Omission preserves existing references; explicit [] clears them through an ordinary spec revision. Proposals/mixed revisions are rejected; selected closure joins export/currentness and relevant drift requires ordinary re-pin/review.",
}


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
    "state": _c("fow_bootstrap", "state", _P + ("bootstrap_id",),
        guidance={"presentation": "Guided cycles return a compact operational continuation. Read state_details for complete state/recent audit, or guidance for full canonical context and the current next_gate template."}),
    "state_details": _c("fow_bootstrap", "state_details", _P + ("bootstrap_id",),
        guidance={"detail": "Explicit full state and recent ten-event audit window. No operational guidance is computed. Use state for a compact guided continuation and guidance for full canonical context."}),
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
    "guidance": _c("fow_bootstrap", "guidance", _P, ("bootstrap_id",),
        guidance={"discovery": "Omit bootstrap_id to read the active cycle of any mode, otherwise the latest guided cycle or an explicit start route. An explicit ID reads that owned guided cycle. This never creates, resumes or confirms work.",
                  "continuation": "continuation_routes distinguish current-work recovery, active-roadmap extension and a new guided cycle. Use existing scope authorization or obtain missing intent confirmation; never invent approval or amend a terminal cycle.",
                  "questions": "Guidance exposes governing intent/correspondence gaps. Technical investigation and packet engineering questions remain engineer-owned; they do not automatically require a stakeholder question."}),
    "record_answer": _c("fow_bootstrap", "record_answer", _P + ("bootstrap_id", "request_id") + tuple("answer." + key for key in bootstrap_input_schema("answer")["required"]),
        enums={"answer.kind": tuple(bootstrap_input_schema("answer")["properties"]["kind"]["enum"])},
        guidance={"input_schema": {"answer": bootstrap_input_schema("answer")}, "provenance": "Record selected governing answers, not the whole dialogue. Whitespace-only text is invalid. Use the returned answer revision for correspondence."}),
    "record_correspondence": _c("fow_bootstrap", "record_correspondence", _P + ("bootstrap_id", "request_id", "correspondence.answer_key", "correspondence.answer_revision", "correspondence.disposition", "correspondence.rationale") + tuple("correspondence.canonical_references." + key for key in bootstrap_input_schema("correspondence")["properties"]["canonical_references"]["required"]),
        enums={"correspondence.disposition": tuple(bootstrap_input_schema("correspondence")["properties"]["disposition"]["enum"])},
        guidance={"input_schema": {"correspondence": bootstrap_input_schema("correspondence")}, "currentness": "Use the current recorded answer revision and existing canonical IDs. Supply all three reference lists; at least one list must contain a current canonical reference. Replace example IDs with IDs returned by canonical authoring. This records correspondence, not semantic truth or acceptance."}),
    "roadmap": _c("fow_bootstrap", "roadmap", _P + ("bootstrap_id", "milestone_ids"),
        guidance={"continuation": "Extend only an active guided cycle through ordinary canonical authoring and explicit milestone_ids, then confirm_roadmap against its current fingerprint and actual confirmation. Completed preparation is historical; use a new guided cycle for newly authorized scope."}),
    "confirm_roadmap": _c("fow_bootstrap", "confirm_roadmap", _P + ("bootstrap_id", "milestone_ids", "roadmap_fingerprint", "confirmation_reference", "request_id")),
    "record_continuation": _c("fow_bootstrap", "record_continuation", _P + ("bootstrap_id", "continuation_choice", "continuation_reference", "roadmap_fingerprint", "progress_revision", "reason", "request_id"), enums={"continuation_choice": ("continue", "review")}),
})

# Applicability is explanatory authority, not another gate or mode dispatcher.
for _name in ("record_intake", "confirm_intake", "derive_behavior", "record_answer",
              "record_correspondence", "roadmap", "confirm_roadmap", "record_continuation"):
    _contract = _BOOTSTRAP[_name]
    _path_help = (
        "code_import only, after confirmed intake; requires a configured bootstrap-behavior provider and internal model. It is not a guided_engineering step."
        if _name == "derive_behavior" else
        "requirements_import, requirements_creation or code_import intake path. guided_engineering uses record_answer and ordinary canonical authoring instead."
        if _name in {"record_intake", "confirm_intake"} else
        "guided_engineering only. Author requirements, use cases and milestones through their ordinary canonical operations, then correspondence and roadmap confirmation. No derive_behavior step or internal model is required."
    )
    _BOOTSTRAP[_name] = replace(_contract, guidance=MappingProxyType({
        **_contract.guidance, "workflow_path": _path_help,
    }))


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
            "active_provider",
            "navigation_audit_id",
            "navigation_audit_ids",
            "target_binding_ids",
            "candidate_set_ids",
            "candidate_set_id",
            "context_snapshot_ids",
            "context_snapshot_id",
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
            "provider",
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
            "architecture_refs",
            "completion_criteria",
            "target_policy",
            "target_state",
            "active_provider",
            "navigation_audit_id",
            "navigation_audit_ids",
            "target_binding_ids",
            "candidate_set_ids",
            "candidate_set_id",
            "context_snapshot_ids",
            "context_snapshot_id",
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
        guidance={"architecture_refs": _ARCHITECTURE_REFS_GUIDANCE} if operation == "revise_packet" else {},
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
        "fow_handover", "get_handover", ("project_id", "operation", "handover_id"),
        guidance={"recovery": "Returns the originally persisted snapshot unchanged. New captures include bounded external recovery references; historical snapshots are never silently hydrated with current state."},
    ),
    "resume_context": _c(
        "fow_handover",
        "resume_context",
        ("project_id", "operation"),
        ("change_id", "packet_id", "run_id", "handover_id"),
        guidance={"recovery": "handover_id explicitly compares frozen recovery authority against current state and derives the original change/packet/run focus. Supplied focus IDs must match; a mismatch is rejected. Without handover_id, recover current authority for the supplied focus. Reads never create exports, outcomes or acceptance."},
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
        enums={"category": ("functional", "non_functional")},
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
            "completion criteria into every unit. An empty list is allowed only "
            "with nonempty verifies containing exclusively deferred intents; "
            "do not invent a local check to satisfy authoring."
        ),
        "standalone_validation_declarations": {
            "implements": [1],
            "provides": [{"name": "example-api", "kind": "api", "clauses": ["The API exposes the declared behavior."], "file_path": "src/example.py", "symbol": "example", "signature": "example(value)"}],
            "requires": [{"producer_unit_key": "predecessor-key", "contract_name": "example-api", "use": "Consume this API to implement the unit behavior."}],
            "verifies": [{"criterion": 1, "kind": "unit_check", "statement": "The API exposes the declared behavior."}],
            "contract_kinds": ["symbol", "api", "data_shape", "protocol", "behavioral_boundary"],
            "verification_kinds": ["unit_check", "deterministic_campaign", "live_campaign", "oracle", "explicit_authority"],
            "temporal_rule": "Only unit_check is current local work. Campaign/Oracle/explicit-authority checks remain deferred; exclusively deferred verifies permits empty unit_checks without claiming local verification passed. Planned paths/symbols do not assert source exists. Contract kind is semantic, never an AST type; no symbol_kind or expected_kind field exists. Consumer refers to one declared predecessor contract without copying clauses.",
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
            "architecture_refs",
        ),
        enums={
            "purpose": ("implementation", "remediation"),
            "predecessor_dependency_policy": ("materialized", "context_only"),
            "target_policy": tuple(item.value for item in PacketTargetPolicy),
        },
        guidance={"architecture_refs": _ARCHITECTURE_REFS_GUIDANCE,
                  "change_id": "Use an existing CHANGE-000000 in the selected project. Only a correlated flow.operation-effect.v1 pre_effect_validation receipt certifies that this invocation started no mutation. Match tool=fow_packet_author, operation=start_packet, project_id and request_id in receipt and audit_reference. Generic rejection, rollback, timeout or lost response is unknown; never replay blindly. A new rejection does not erase earlier work under the same request ID."},
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
            "architecture_refs",
            "expected_spec_revision",
            "expected_plan_revision",
        ),
        guidance={"architecture_refs": _ARCHITECTURE_REFS_GUIDANCE},
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
        ("change_id", "expected_spec_revision", "expected_plan_revision", "mode"),
        enums={"mode": ("advance", "sync_only")},
        guidance={
            "mode": "Default advance preserves ordinary lifecycle advancement. Per-call sync_only delivers admitted provider ADD/EDIT/REMOVE and stops before START; it performs no lifecycle repair, plan acceptance or ordinary evidence advancement.",
            "sync_boundary": "provider_synchronized means current authoring deltas are synchronized, not that execution has never started or been accepted. Review and explicitly call mode=advance to start. Continued synchronization next actions retain mode=sync_only.",
            "controls": "Pending, delivering, unknown or explicitly retried rejected START/STOP are held unchanged as provider_control_pending with exact pending_control identity. Inspect gates; sync_only never claims, retries, supersedes or delivers controls. Conflicting control/semantic decisions are rejected before effects.",
            "authority": "Existing selection, negotiation, PVP, currentness, generation and exact ACK/recovery guards still apply. Unknown delta delivery never falls through to START. Mode is not persisted and changes no provider wire or acceptance authority.",
        },
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
        ("change_id", "expected_spec_revision", "expected_plan_revision"),
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
        ("change_id", "expected_spec_revision", "expected_plan_revision"),
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
        ("change_id", "expected_spec_revision", "expected_plan_revision"),
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
        ("change_id", "expected_spec_revision", "expected_plan_revision"),
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
            "change_id",
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
        ("change_id", "decision.policy_ref", "expected_spec_revision", "expected_plan_revision"),
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
        ("change_id", "detail_level", "offset", "limit"),
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
        ("milestone_id", "detail_level", "offset", "limit", "evidence_id"),
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
            "prerequisite_requirement_ids",
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
        "fow_set_requirement_lifecycle": MappingProxyType({
            "lifecycle_status": tuple(item.value for item in LifecycleStatus),
        }),
        "fow_what_next": MappingProxyType({"detail_level": ("standard", "audit")}),
        "fow_traceability": MappingProxyType({"detail_level": ("standard", "audit")}),
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
_SIMPLE["fow_promote_milestone"] = _c(
    "fow_promote_milestone", "call", *_SIMPLE_FIELDS["fow_promote_milestone"],
    guidance={
        "scope": "requirement_ids are realized here. prerequisite_requirement_ids are disjoint requirements realized by lower-ordinal milestones in this project. First/independent milestone uses []; no inferred transitive closure.",
        "predecessors": "Planning can refer to planned predecessors. Membership is not implementation, verification or acceptance. Explicit entry_policy.requires_milestone retains its accepted-predecessor gate; list only actual intended gates.",
        "retry": "Replay every original normalized input and actor, including initial evidence, with the same request_id. Later acceptance does not change that immutable request identity. Historical requests without original proof reject as milestone_request_replay_unverifiable; inspect the existing milestone before proceeding.",
        "effect_receipt": "Only a correlated flow.operation-effect.v1 pre_effect_validation receipt proves no mutation started. Check tool, operation=call, project_id and request_id in receipt and audit_reference. Generic rejection, timeout or lost response is not no-effect proof.",
        "successor_example": {
            "assumption": "REQ-000001 is already realized by MILE-000001; REQ-000002 is the new milestone scope. These are illustrative existing identities, not newly registered authority.",
            "tool": "fow_promote_milestone",
            "arguments": {"project_id": "example-project", "name": "Second milestone",
                "requirement_ids": ["REQ-000002"], "prerequisite_requirement_ids": ["REQ-000001"],
                "entry_policy": {"requires_milestone": []},
                "exit_policy": {"verification": "Verify REQ-000002 at its declared boundaries."},
                "risk_disposition": "Known risks reviewed", "actor": "coding-agent",
                "request_id": "milestone-second-request"},
        },
    },
)
_SIMPLE["fow_traceability"] = _c(
    "fow_traceability", "call", *_SIMPLE_FIELDS["fow_traceability"],
    enums=_SIMPLE_ENUMS["fow_traceability"],
    guidance={"evidence_read": "evidence_id defaults to 0 for ordinary traceability. A positive evidence_id requires detail_level=audit, offset=0, limit=10 and no milestone_id. It returns one original project-scoped verification evidence body with full metadata/provenance. Unknown and foreign IDs return the same rejection; no artifact or evidence is created."},
)

_INTERACTION_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "status": (("interaction_session_ref", "operation"), ()),
    "catalog": (("interaction_session_ref", "operation"), ()),
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
            **({"page_action": ("more", "refine", "stop")} if operation == "discover" else {}),
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
        guidance={"catalog": "Read complete revision-bound Flower lens membership without writes, repairs or provider/model probes. Read structuredContent.result.result; membership is not execution admission. Selection still uses current issued discover/select/switch choices."}
        if operation == "catalog" else None,
    )
    for operation, (required, optional) in _INTERACTION_FIELDS.items()
}

_ARCHITECTURE_GUIDANCE = {
    "definition": {
        "components": [
            {
                "id": "lifecycle", "name": "Lifecycle authority",
                "responsibility": "Own canonical project intent and handoff.",
                "boundaries": ["The host owns code execution."],
                "invariants": ["Keep one canonical project ledger."], "links": [],
            },
            {
                "id": "host", "name": "Coding agent",
                "responsibility": "Investigate, implement and report declared evidence.",
                "boundaries": ["Use Flower authority without copying a semantic store."],
                "invariants": ["Retain issued authority while offline."], "links": [],
            },
        ],
        "interfaces": [{
            "id": "plan-handoff", "name": "Self-contained implementation plan",
            "provider_component_id": "lifecycle", "consumer_component_ids": ["host"],
            "kind": "protocol", "clauses": ["Carry complete producer/consumer contracts and verification obligations."],
            "failure_contract": ["Incomplete or stale authority blocks admission."],
            "compatibility": ["Host evidence retains its declared provenance."], "links": [],
        }],
        "decisions": [{
            "id": "execution-owner", "statement": "The coding agent owns code execution.",
            "rationale": "Keep lifecycle authority and execution responsibility explicit.",
            "component_ids": ["lifecycle", "host"], "interface_ids": ["plan-handoff"],
            "supersedes_decision_id": "", "links": [],
        }],
    },
    "entity_fields": {
        "component": ["id", "name", "responsibility", "boundaries", "invariants", "links"],
        "interface": ["id", "name", "provider_component_id", "consumer_component_ids", "kind", "clauses", "failure_contract", "compatibility", "links"],
        "decision": ["id", "statement", "rationale", "component_ids", "interface_ids", "supersedes_decision_id", "links"],
    },
    "links": [
        {"kind": "requirement", "requirement_id": "current-requirement-id"},
        {"kind": "goal", "goal_node_id": "current-goal-node-id"},
        {"kind": "packet", "change_id": "current-change-id", "packet_id": "current-packet-id"},
        {"kind": "evidence", "evidence_id": 1},
    ],
    "interface_kinds": ["symbol", "api", "data_shape", "protocol", "behavioral_boundary"],
    "field_types": "Collections, boundaries, invariants, clauses, failure_contract, compatibility and subject/consumer IDs are lists; links contain the exact typed objects below. Other entity fields are strings. supersedes_decision_id is an empty string when no predecessor exists. evidence_id is a positive integer. The complete definition example shows every required entity field.",
    "bounds": "At most128 entities,512 total links,256KiB canonical UTF-8,128 items per list and4096 characters per string. IDs match [A-Za-z][A-Za-z0-9_.-]{0,79}, unique within kind. Unknown fields/duplicate identities/dangling endpoints/foreign links fail atomically.",
    "authority": "Proposals are immutable complete definitions and never executable authority. Adoption is an ordinary engineer decision, not product acceptance or verification. Adopted decision bodies are immutable; a changed choice gets a new ID, explicitly supersedes the retained predecessor and cannot form a cycle.",
    "replay": "Mutations require actor/request_id and expected current adopted revision (0 initially). Exact requests replay the historical receipt; changed actor/operation/payload under the same request ID conflicts. A proposal's base must still match the adopted head at adoption.",
    "paging": "inspect revision=0 selects current adopted authority; missing adopted authority stays explicitly absent. kind=history selects revision history. offset defaults0; limit defaults20, maximum100. Read completeness and next_offset before assuming an entire result was returned.",
}
_ARCHITECTURE = {
    "inspect": _c(
        "fow_architecture", "inspect", ("project_id", "operation"),
        ("payload.revision", "payload.kind", "payload.offset", "payload.limit", "request_id"),
        enums={"payload.kind": ("all", "component", "interface", "decision", "history")},
        paging_owner="ledger", guidance=_ARCHITECTURE_GUIDANCE,
    ),
    "propose": _c(
        "fow_architecture", "propose",
        ("project_id", "operation", "actor", "request_id", "payload.expected_revision", "payload.definition"),
        guidance=_ARCHITECTURE_GUIDANCE,
    ),
    "adopt": _c(
        "fow_architecture", "adopt",
        ("project_id", "operation", "actor", "request_id", "payload.expected_revision", "payload.revision", "payload.rationale"),
        guidance=_ARCHITECTURE_GUIDANCE,
    ),
}

_EXTERNAL_WORK_READS = frozenset({"criteria", "validation", "provider_validation", "todo"})
_EXTERNAL_WORK_FIELDS = {
    "set_mode": (("payload.mode", "payload.expected_spec_revision", "payload.expected_plan_revision"), ()),
    "select_executor": (("payload.executor", "payload.expected_spec_revision", "payload.expected_plan_revision"), ("payload.provider_kind",)),
    "negotiate_provider": (("payload.expected_spec_revision", "payload.expected_plan_revision"), ()),
    "upgrade_validation": (("payload.expected_spec_revision", "payload.expected_plan_revision"), ()),
    "criteria": ((), ()),
    "reconcile_criteria": (("payload.expected_spec_revision", "payload.rationale", "payload.criteria"), ("payload.new_statements",)),
    "add_criterion": (("payload.statement", "payload.expected_spec_revision"), ()),
    "edit_criterion": (("payload.number", "payload.statement", "payload.expected_spec_revision"), ()),
    "remove_criterion": (("payload.number", "payload.expected_spec_revision"), ()),
    "validation": ((), ("payload.detail",)),
    "provider_validation": ((), ("payload.detail",)),
    "export_plan": (("payload.expected_spec_revision", "payload.expected_plan_revision"), ("payload.allow_draft",)),
    "todo": ((), ("payload.unit_key",)),
    "report_outcome": (("payload.report_key", "payload.expected_spec_revision", "payload.expected_plan_revision", "payload.authority_fingerprint", "payload.unit_key", "payload.outcome", "payload.summary", "payload.source_revision", "payload.artifacts", "payload.produced_contracts", "payload.verification", "payload.unresolved"), ()),
    "reconcile_outcome": (("payload.report_key", "payload.expected_spec_revision", "payload.expected_plan_revision", "payload.rationale"), ()),
}
_EXTERNAL_WORK = {
    op: _c(
        "fow_external_work", op,
        ("project_id", "change_id", "packet_id", "operation", *required, *(() if op in _EXTERNAL_WORK_READS else ("actor", "request_id"))),
        (*optional, *(("request_id",) if op in _EXTERNAL_WORK_READS else ())),
        enums={
            "operation": (op,),
            **({"payload.detail": ("standard", "full")} if op in {"validation", "provider_validation"} else {}),
            **({"payload.executor": ("external_agent", "provider")} if op == "select_executor" else {}),
            **({"payload.mode": ("external_agent",)} if op == "set_mode" else {}),
        },
        effect_class="provider_probe_and_ledger_mutation" if op == "negotiate_provider" else "",
        guidance={
            "scope": "Standalone external-agent PVP remains independent. A bounded Flow-owned negotiated provider bridge requires exact consumer support; original full cross-server PVP/CC IMPL-67 and actual paired qualification remain deferred.",
            "execution_ownership": "Select one executor for new work before an enriched plan can trigger delivery. executor=provider requires the actual configured adapter provider_kind (codingcastle), distinct from route category packet_execution; external_agent forbids provider_kind. Opposite explicit/legacy external selection, provider history, outcomes, started or completed work reject transfer. An unselected legacy provider default is not explicit selection; no timeout fallback or second writer.",
            "provider_negotiation": "negotiate_provider explicitly probes the selected configured provider and stores exact capability support bound to selection, canonical packet_execution binding, spec/plan revisions and authority fingerprint. No ordinary read probes a provider. Missing/malformed/unavailable support blocks enriched dispatch; route or authority change requires explicit re-negotiation. URLs/credentials/commands are not accepted.",
            "provider_validation": "provider_validation is a pure read of provider-scoped semantic closure, selected authority and current executor/capability admission; it never probes or compiles. Local unit checks and deferred campaign/Oracle/explicit-authority obligations remain separate. Consumer compilation acknowledgements do not prove acceptance or satisfy deferred verification.",
            "authority": (
                "Retain the issued expected_spec_revision, expected_plan_revision and authority_fingerprint from the plan/TODO used for the work, including offline execution. Read current validation/TODO to compare authorities; never replace issued authority with current values to make old evidence appear current. Stale reports remain historical and cannot complete current work."
                if op == "report_outcome" else
                "Use current expected_spec_revision and expected_plan_revision to select an existing current-authority report_key with an explicit rationale. Reconciliation resolves competing reports; it cannot promote stale reports or imply acceptance. This operation has no authority_fingerprint payload field."
                if op == "reconcile_outcome" else
                "Use current specification/plan revisions and authority_fingerprint returned by validation/todo. Stale reports remain history and cannot complete current work."
            ),
            "report_schema": {
                "artifacts": [{"reference": "repository-relative or declared evidence locator", "description": "what was produced", "sha256": "optional content SHA-256"}],
                "produced_contracts": [{"name": "producer declaration name", "artifact_ref": "one reported artifact reference"}],
                "verification": [{"criterion": 1, "kind": "unit_check|deterministic_campaign|live_campaign|oracle|explicit_authority", "statement": "exact declared verification intent", "status": "pass|fail|not_run", "evidence_ref": "declared evidence", "provenance": "host-reported"}],
                "unresolved": ["remaining obligations"],
            } if op == "report_outcome" else {},
            **({"verification_identity": "Copy the exact criterion/kind/statement from this unit's issued plan/TODO declarations used for the work. No approximate matching is accepted. Rejections identify the input field, unit, expected and received declaration and a bounded public recovery call; invalid reports persist no outcome."} if op == "report_outcome" else {}),
            **({"durable_export": "export_plan records an immutable artifact generation and a durable receipt. Nonempty actor and request_id are required. Retry the identical operation, actor and payload with the same request_id to recover the original receipt, including after authority changes; changed request contents under that ID conflict. A new request uses current specification/plan revisions. The aggregate tool schema also serves pure criteria/validation/provider_validation/todo reads, which may omit identity; exact operation help defines the mutation requirements. Flower does not generate request IDs. The host saves returned Markdown with its file tools."} if op == "export_plan" else {}),
            **({"upgrade_recovery": "upgrade_validation initializes stable criterion identities once. An identical original request replays its historical receipt; changed contents under the same request ID conflict. A new request at current revisions for an already upgraded packet remains rejected with packet_validation_already_upgraded and read-only validation/criteria recovery. Stale revision failures take precedence. Read current validation and criteria before deciding whether actual criterion-authority drift requires explicit reconcile_criteria; never repeat initialization to rewrite identities or invent a mapping/rationale."} if op == "upgrade_validation" else {}),
        },
    ) for op, (required, optional) in _EXTERNAL_WORK_FIELDS.items()
}
_BINDINGS = {
    op: _c("fow_bindings", op, (*required, "operation"), optional, guidance={
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
    op: _c("fow_semantic", op, (*required, "operation"), optional,
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
        "fow_architecture": MappingProxyType(_ARCHITECTURE),
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
    return tuple(
        ToolDescriptor(item.name, item.area, tool_description(item.name), item.owner)
        for item in _PUBLIC_TOOLS
    )


def public_tool_catalog() -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "name": item.name,
            "area": item.area,
            "owner": item.owner,
            "description": tool_description(item.name),
        }
        for item in _PUBLIC_TOOLS
    )


def tool_description(name: str) -> str:
    descriptor = _PUBLIC_TOOL_BY_NAME.get(str(name or "").strip())
    if descriptor is None:
        raise KeyError(name)
    name = descriptor.name
    prerequisite, effects = TOOL_GUIDANCE[name]
    routes = operation_names(name)
    if name == "fow_capabilities":
        routing = "Route with view=summary|recipe|operation|docs|full; recipe needs recipe_name, operation needs operation_tool and operation_name."
    elif name in {"fow_packet_inspect", "fow_campaign_inspect"}:
        routing = "Route with view: " + ", ".join(routes) + "."
    elif name == "fow_packet_advance":
        routing = "Route ordinary progression with mode=advance (default) or sync_only. Gate responses use decision.operation: " + ", ".join(route for route in routes if route != "advance") + "."
    elif name == "fow_campaign_advance":
        routing = "Implicit advance operation; transition_budget bounds the call."
    elif routes == ("call",):
        routing = "Single operation; call directly without an operation argument."
    else:
        routing = "Route with operation: " + ", ".join(routes) + "."
    example_route = routes[0]
    help_call = {
        "view": "operation", "operation_tool": name,
        "operation_name": example_route,
    }
    return (
        descriptor.description + "\n" + routing
        + "\nPrerequisites: " + prerequisite
        + "\nEffects: " + effects
        + "\nExact help (replace operation_name with the selected route): fow_capabilities("
        + json.dumps(help_call, ensure_ascii=False, separators=(",", ":")) + ")."
    )


def tool_annotations(name: str) -> Mapping[str, bool]:
    """Conservative tool-wide hints, including effects of mixed routes."""

    values = TOOL_EFFECTS[name]
    return dict(zip(
        ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"),
        values, strict=True,
    ))


def parameter_help(tool: str, name: str, *, selected_operation: str = "") -> Mapping[str, object]:
    """Publish semantic help without adding constraints to accepted inputs.

    Every semantic meaning is explicit. Only route applicability, selector
    values and representative examples are derived from canonical contracts.
    """

    if tool not in _BY_TOOL:
        raise KeyError(f"missing_tool_help:{tool}")
    description = FIELD_OVERRIDES.get((tool, name), FIELD_HELP[name])
    contracts = ((_BY_TOOL[tool][selected_operation],) if selected_operation
                 else tuple(_BY_TOOL[tool].values()))
    selectors = (selected_operation,) if selected_operation else operation_names(tool)
    required = tuple(c.operation for c in contracts if any(
        path.split(".", 1)[0] == name for path in c.required
    ))
    applicable = tuple(c.operation for c in contracts if any(
        path.split(".", 1)[0] == name for path in (*c.required, *c.optional)
    ))
    if name == "operation":
        description += " Canonical values: " + ", ".join(selectors) + "."
    elif name == "view" and tool in {"fow_packet_inspect", "fow_campaign_inspect"}:
        description += " Canonical values: " + ", ".join(operation_names(tool)) + "."
    elif len(contracts) > 1 and name not in {"actor", "request_id", "project_id", "change_id", "packet_id"}:
        if applicable and len(applicable) != len(contracts):
            description += " Applies to: " + ", ".join(applicable) + "."
        if required and len(required) != len(contracts):
            description += " Required by: " + ", ".join(required) + "."
    values = tuple(dict.fromkeys(
        value for c in contracts for value in c.enums.get(name, ())
    ))
    if values and name != "operation":
        description += " Canonical values: " + ", ".join(values) + "."
    if name in {"payload", "decision", "unit", "unit_patch", "work_plan", "answer", "answers", "response", "case", "scope", "oracle", "harness", "assessment", "correspondence", "intake", "contradiction", "host_evidence", "result", "association_receipt"}:
        description += " Exact required/optional dotted fields and guidance: fow_capabilities(view=operation, operation_tool=" + tool + ", operation_name=<selected route>)."
    metadata: dict[str, object] = {"description": description}
    if name in {"operation", "view", "mode", "payload", "decision", "association_receipt", "result", "answer", "correspondence", "unit"}:
        if name == "operation":
            metadata["examples"] = [selectors[0]]
        elif name == "view" and tool in {"fow_packet_inspect", "fow_campaign_inspect"}:
            metadata["examples"] = [operation_names(tool)[0]]
        elif values:
            metadata["examples"] = [values[0]]
        else:
            for contract in contracts:
                example = _example(contract)
                if name in example and example[name] not in (None, {}, ""):
                    metadata["examples"] = [example[name]]
                    break
    return metadata


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


# Flower owns membership. These semantic companion groups are independent of
# the currently observed next action; only registered route identities expand.
_LENS_CONTEXT_PAIRS = (
    ("fow_goal", "view"), ("fow_bootstrap", "guidance"),
    ("fow_traceability", "call"),
)
_LENS_EXTERNAL_PAIRS = tuple(
    ("fow_external_work", operation)
    for operation in ("todo", "reconcile_outcome", "report_outcome", "validation",
                      "provider_validation", "export_plan")
)
_LENS_JOB_PAIRS = (("fow_get_job", "call"), ("fow_list_jobs", "call"))
_LENS_COMPANION_PAIRS = MappingProxyType({
    "requirements": _LENS_JOB_PAIRS,
    "changes": _LENS_EXTERNAL_PAIRS + _LENS_JOB_PAIRS,
    "assurance": (("fow_campaign_author", "start"),
                  ("fow_packet_advance", "advance"),
                  ("fow_packet_author", "start_packet")) + _LENS_JOB_PAIRS,
    "campaigns": _LENS_EXTERNAL_PAIRS,
})


def lens_operation_membership() -> dict[str, object]:
    """Expand and validate the complete immutable registry policy, without I/O."""
    if set(_BY_TOOL) != set(public_tool_names()) or any(
        contract.tool != tool or contract.operation != operation
        for tool, values in _BY_TOOL.items() for operation, contract in values.items()
    ):
        raise ValueError("lens_catalog_registry_invalid")
    contracts = {
        (contract.tool, contract.operation): contract
        for values in _BY_TOOL.values() for contract in values.values()
    }
    if len(contracts) != sum(len(values) for values in _BY_TOOL.values()):
        raise ValueError("lens_catalog_registry_invalid")
    areas = {area.name for area in _WORK_AREAS}
    if len(areas) != len(_WORK_AREAS) or not set(_LENS_COMPANION_PAIRS) <= areas:
        raise ValueError("lens_catalog_registry_invalid")
    core = {pair for pair in contracts if pair[0] == "fow_interaction"} | {
        ("fow_capabilities", "call"), ("fow_create_project", "call"),
        ("fow_handover", "project_state_snapshot"), ("fow_what_next", "call"),
    }
    shared = set(_LENS_CONTEXT_PAIRS) | {
        pair for pair, contract in contracts.items()
        if pair[0] in {"fow_packet_inspect", "fow_campaign_inspect"}
        or (pair[0] == "fow_handover" and contract.risk == OperationRisk.READ)
    }
    declared = shared | core | {
        pair for pairs in _LENS_COMPANION_PAIRS.values() for pair in pairs
    }
    if not declared <= contracts.keys() or any(
        contract.area not in areas for pair, contract in contracts.items()
        if pair not in core
    ):
        raise ValueError("lens_catalog_registry_invalid")

    def refs(pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
        return [{"tool": tool, "operation": operation} for tool, operation in sorted(pairs)]

    lenses = []
    covered = set(core)
    for area in work_area_catalog():
        primary = {pair for pair, contract in contracts.items()
                   if contract.area == area["area"]} - core
        companions = (shared | set(_LENS_COMPANION_PAIRS.get(area["area"], ()))) - core - primary
        covered.update(primary)
        lenses.append({**area, "primary_operations": refs(primary),
                       "companion_operations": refs(companions)})
    if covered != contracts.keys():
        raise ValueError("lens_catalog_registry_invalid")
    return {"core_operations": refs(core), "lenses": lenses}


@lru_cache(maxsize=1)
def registry_version() -> str:
    payload = {
        "tools": list(public_tool_catalog()),
        "areas": list(work_area_catalog()),
        "lens_membership": lens_operation_membership(),
        # The version covers exact help as well as the compact index. A change to
        # input shape, accepted values, guidance, or examples must invalidate a
        # host-side registry cache even when its route classifiers are unchanged.
        "operations": operation_contract_catalog(),
        "field_help": dict(FIELD_HELP),
        "field_overrides": [
            [tool, name, help_text]
            for (tool, name), help_text in sorted(FIELD_OVERRIDES.items())
        ],
        "annotations": {name: tool_annotations(name) for name in public_tool_names()},
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
    for descriptor in public_tool_descriptors():
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
    if contract.tool == "fow_promote_milestone":
        result.update(name="First milestone", requirement_ids=["REQ-000001"],
            prerequisite_requirement_ids=[], entry_policy={"requires_milestone": []},
            exit_policy={"verification": "Replace with declared checks for the requirement realized by this milestone."},
            risk_disposition="Known risks reviewed")
    if contract.tool == "fow_architecture":
        if contract.operation == "inspect":
            result["payload"] = {"revision": 0, "kind": "all", "offset": 0, "limit": 20}
        elif contract.operation == "propose":
            result["payload"].update(
                expected_revision=0,
                definition=deepcopy(_ARCHITECTURE_GUIDANCE["definition"]),
            )
        elif contract.operation == "adopt":
            result["payload"].update(
                expected_revision=0, revision=1,
                rationale="Adopt the investigated lifecycle boundary as engineering authority.",
            )
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
    if contract.tool in {"fow_packet_inspect", "fow_campaign_inspect"}:
        result["view"] = contract.operation
    if contract.tool == "fow_assurance" and contract.operation == "reassess_intent":
        result["assessment"] = {"expected_intent_fingerprint": "from get_finding", "expected_finding_fingerprint": "from get_finding", "classification": "correction_within_intent", "rationale": "Correct implementation within the current recorded behavior.", "technical_decisions": ["Reuse the existing canonical service."], "evidence_refs": ["host-source-review:001"]}
    if contract.tool == "fow_external_work":
        if contract.operation == "set_mode":
            result["payload"]["mode"] = "external_agent"
        elif contract.operation == "select_executor":
            result["payload"]["executor"] = "external_agent"
        elif contract.operation == "provider_validation":
            result["payload"] = {"detail": "full"}
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
    if leaf == "answers":
        return [{
            "question_id": "replace-with-current-audit-question-id",
            "answer_summary": "Replace with the investigated resolution of this question.",
            "evidence_refs": ["replace-with-actual-investigation-evidence"],
        }]
    if leaf == "response":
        return {
            "disposition": "answered",
            "answer_summary": "Replace with the investigated answer and question-specific fields from the current gate.",
            "evidence_refs": ["replace-with-actual-investigation-evidence"],
        }
    if leaf == "claims":
        return [{
            "claim_type": PacketEvidenceClaimType.TARGET.value,
            "claim_key": "replace-with-source-claim-key",
            "subject_ref": "replace-with-source-subject",
            "predicate": "replace-with-observed-relation",
            "object_ref": "replace-with-source-object",
            "evidence_refs": ["replace-with-actual-provider-evidence"],
        }]
    if leaf == "entry_policy":
        return {"requires_milestone": ["replace-with-existing-prerequisite-milestone-id"]}
    if leaf == "exit_policy":
        return {"verification": "Replace with the declared exit checks and acceptance evidence for this milestone."}
    if leaf.endswith("_ids") or leaf in {
        "surfaces",
        "acceptance_evidence",
        "evidence_gaps",
        "participants",
        "normal_steps",
        "expected_effects",
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
        "expected_revision",
        "revision",
        "offset",
        "limit",
        "transition_budget",
        "number",
        "area",
        "selection",
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
