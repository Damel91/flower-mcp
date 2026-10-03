"""First-class campaign, oracle, obligation and attestation value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence

from flow_of_work_mcp.core.domain.assurance import (
    validate_campaign_id,
    validate_case_id,
    validate_finding_id,
)
from flow_of_work_mcp.core.domain.change_control import (
    validate_change_id,
    validate_packet_id,
)
from flow_of_work_mcp.core.domain.identifiers import (
    required_text,
    validate_requirement_id,
)
from flow_of_work_mcp.core.domain.oracle_ir import OracleIRSnapshot


CAMPAIGN_PLAN_CONTRACT_VERSION = "flow.campaign.plan.v1"
ORACLE_SNAPSHOT_CONTRACT_VERSION = "flow.oracle.snapshot.v1"
LEGACY_TEST_PROVIDER_COMMAND_VERSION = "flow.test_provider.command.v1"
LEGACY_TEST_PROVIDER_RECEIPT_VERSION = "flow.test_provider.receipt.v1"
TEST_PROVIDER_COMMAND_VERSION = "flow.test_provider.command.v2"
TEST_PROVIDER_RECEIPT_VERSION = "flow.test_provider.receipt.v2"

_OBLIGATION_ID_RE = re.compile(r"^OBL-[0-9]{6}$")
_ORACLE_ID_RE = re.compile(r"^ORACLE-[0-9]{6}$")
_ATTESTATION_ID_RE = re.compile(r"^ATTEST-[0-9]{6}$")
_TEST_COMMAND_ID_RE = re.compile(r"^TCMD-[0-9]{6}$")
_TEST_RECEIPT_ID_RE = re.compile(r"^TRCPT-[0-9]{6}$")


class CampaignConstructibility(StrEnum):
    DRAFT = "draft"
    NEEDS_SCOPE = "needs_scope"
    NEEDS_OBLIGATIONS = "needs_obligations"
    NEEDS_CASES = "needs_cases"
    NEEDS_ORACLE = "needs_oracle"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    READY_TO_RUN = "ready_to_run"
    RUNNING = "running"
    PARTIAL = "partial"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignObligationKind(StrEnum):
    PRIMARY_BEHAVIOR = "primary_behavior"
    SEQUENCE_COMPLETION = "sequence_completion"
    INVARIANT_PRESERVATION = "invariant_preservation"
    FAILURE_TRANSITION = "failure_transition"
    BOUNDARY_RANGE = "boundary_range"
    REGRESSION = "regression"
    PERSISTENCE = "persistence"
    SCOPE_ISOLATION = "scope_isolation"
    IMPACT_RELATION = "impact_relation"


class CampaignObligationDecision(StrEnum):
    UNCLASSIFIED = "unclassified"
    REQUIRED = "required"
    OUT_OF_SCOPE = "out_of_scope"
    DUPLICATE = "duplicate"
    INVESTIGATE = "investigate"
    WAIVED = "waived"


class TestProviderMaterializationMode(StrEnum):
    ORCHESTRATOR_SOURCE = "orchestrator_source"
    DETERMINISTIC_ORACLE_IR = "deterministic_oracle_ir"


class OracleAnswerAuthority(StrEnum):
    GROUNDED_FACT = "grounded_fact"
    ACCEPTED_DECISION = "accepted_decision"
    DERIVED_HYPOTHESIS = "derived_hypothesis"
    UNKNOWN = "unknown"
    WAIVED = "waived"


class MaterializationAttestationState(StrEnum):
    UNATTESTED = "unattested"
    PENDING_TECHNICAL_VALIDATION = "pending_technical_validation"
    ATTESTED_CURRENT = "attested_current"
    INVALIDATED = "invalidated"
    REJECTED = "rejected"


class CampaignEvidenceDisposition(StrEnum):
    DIAGNOSTIC_ONLY = "diagnostic_only"
    TEST_INVALID = "test_invalid"
    PRODUCT_FAILED = "product_failed"
    ENVIRONMENT_FAILED = "environment_failed"
    FLAKY = "flaky"
    INCOMPLETE = "incomplete"
    PASSED = "passed"


def deterministic_materialization_retry_eligible(
    attestation: Mapping[str, object] | None,
) -> bool:
    """Return whether a current deterministic intent may append a retry."""

    if not isinstance(attestation, Mapping):
        return False
    if (
        str(attestation.get("materialization_mode") or "")
        != TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value
        or str(attestation.get("state") or "")
        != MaterializationAttestationState.INVALIDATED.value
    ):
        return False
    basis = attestation.get("basis")
    return bool(
        isinstance(basis, Mapping)
        and basis.get("authority_current") is True
        and basis.get("exact_authority_binding") is True
        and "invalidation" not in basis
        and "effective_invalidation" not in basis
    )


def deterministic_materialization_failure_receipt(
    receipt: Mapping[str, object] | None,
    *,
    reconciled_attestation_state: str = "",
) -> bool:
    """Recognize a provider-reported technical failure for Oracle-IR output."""

    effective_state = str(reconciled_attestation_state or "").strip()
    if not effective_state and isinstance(receipt, Mapping):
        effective_state = str(receipt.get("attestation_state") or "").strip()
    return bool(
        isinstance(receipt, Mapping)
        and str(receipt.get("materialization_mode") or "")
        == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR.value
        and effective_state == MaterializationAttestationState.INVALIDATED.value
        and str(receipt.get("technical_state") or "").strip()
    )


class TestProviderOperation(StrEnum):
    MATERIALIZE = "materialize"
    EDIT = "edit"
    VALIDATE = "validate"
    RUN = "run"
    PROMOTE = "promote"
    DISCARD = "discard"
    REPORT = "report"


@dataclass(frozen=True)
class CampaignScopeDraft:
    change_id: str
    milestone_id: str = ""
    requirement_ids: tuple[str, ...] = ()
    goal_ids: tuple[str, ...] = ()
    packet_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    environment_assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", validate_change_id(self.change_id))
        object.__setattr__(self, "milestone_id", str(self.milestone_id or "").strip())
        object.__setattr__(
            self,
            "requirement_ids",
            _unique(
                tuple(validate_requirement_id(item) for item in self.requirement_ids)
            ),
        )
        object.__setattr__(self, "goal_ids", _unique_texts(self.goal_ids, "goal_ids"))
        object.__setattr__(
            self,
            "packet_ids",
            _unique(tuple(validate_packet_id(item) for item in self.packet_ids)),
        )
        object.__setattr__(
            self,
            "finding_ids",
            _unique(tuple(validate_finding_id(item) for item in self.finding_ids)),
        )
        object.__setattr__(
            self,
            "invariants",
            _unique_texts(self.invariants, "invariants"),
        )
        object.__setattr__(
            self,
            "environment_assumptions",
            _unique_texts(self.environment_assumptions, "environment_assumptions"),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "milestone_id": self.milestone_id,
            "requirement_ids": list(self.requirement_ids),
            "goal_ids": list(self.goal_ids),
            "packet_ids": list(self.packet_ids),
            "finding_ids": list(self.finding_ids),
            "invariants": list(self.invariants),
            "environment_assumptions": list(self.environment_assumptions),
        }


@dataclass(frozen=True)
class CampaignCaseSemanticDraft:
    title: str
    purpose: str
    case_kind: str
    action: str
    expected_outcome: str
    observation_point: str
    required: bool = True
    prohibited_outcome: str = ""
    setup: str = ""
    cleanup: str = ""
    execution_class: str = "deterministic"
    obligation_ids: tuple[str, ...] = ()
    oracle_kind: str = "behavior"

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")
        for field_name in (
            "title",
            "purpose",
            "case_kind",
            "action",
            "expected_outcome",
            "observation_point",
            "execution_class",
            "oracle_kind",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(str(getattr(self, field_name)), field_name),
            )
        for field_name in ("prohibited_outcome", "setup", "cleanup"):
            object.__setattr__(
                self,
                field_name,
                normalize_semantic_text(str(getattr(self, field_name) or "")),
            )
        object.__setattr__(
            self,
            "obligation_ids",
            _unique(
                tuple(validate_obligation_id(item) for item in self.obligation_ids)
            ),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "purpose": self.purpose,
            "case_kind": self.case_kind,
            "action": self.action,
            "expected_outcome": self.expected_outcome,
            "prohibited_outcome": self.prohibited_outcome,
            "observation_point": self.observation_point,
            "setup": self.setup,
            "cleanup": self.cleanup,
            "execution_class": self.execution_class,
            "required": self.required,
            "obligation_ids": list(self.obligation_ids),
            "oracle_kind": self.oracle_kind,
        }


@dataclass(frozen=True)
class BehavioralOracleDraft:
    oracle_kind: str
    subject_bindings: tuple[str, ...]
    authority_reference: str
    semantic_fields: Mapping[str, object] = field(default_factory=dict)
    goal_bindings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "oracle_kind", required_text(self.oracle_kind, "oracle_kind")
        )
        object.__setattr__(
            self,
            "subject_bindings",
            _unique_texts(self.subject_bindings, "subject_bindings"),
        )
        if not self.subject_bindings:
            raise ValueError("oracle requires at least one subject binding")
        object.__setattr__(
            self,
            "authority_reference",
            required_text(self.authority_reference, "authority_reference"),
        )
        object.__setattr__(
            self, "goal_bindings", _unique_texts(self.goal_bindings, "goal_bindings")
        )
        object.__setattr__(
            self,
            "semantic_fields",
            canonical_semantic_value(dict(self.semantic_fields or {})),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "contract_version": ORACLE_SNAPSHOT_CONTRACT_VERSION,
            "oracle_kind": normalize_semantic_text(self.oracle_kind),
            "subject_bindings": list(self.subject_bindings),
            "goal_bindings": list(self.goal_bindings),
            "authority_reference": normalize_semantic_text(self.authority_reference),
            "semantic_fields": dict(self.semantic_fields),
        }


@dataclass(frozen=True)
class TestProviderCommand:
    flow_session_ref: str
    campaign_id: str
    case_id: str
    operation: TestProviderOperation
    oracle_id: str
    oracle_revision: int
    oracle_fingerprint: str
    attestation_intent_ref: str
    source_manifest_digest: str
    semantic_input: Mapping[str, object]
    delivery_fingerprint: str
    command_id: str = ""
    materialization_mode: TestProviderMaterializationMode = (
        TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
    )
    authority_input_fingerprint: str = ""
    oracle_ir: Mapping[str, object] = field(default_factory=dict)
    requested_capability: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = TEST_PROVIDER_COMMAND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "flow_session_ref",
            required_text(self.flow_session_ref, "flow_session_ref"),
        )
        object.__setattr__(self, "campaign_id", validate_campaign_id(self.campaign_id))
        object.__setattr__(self, "case_id", validate_case_id(self.case_id))
        object.__setattr__(self, "operation", TestProviderOperation(self.operation))
        mode = TestProviderMaterializationMode(self.materialization_mode)
        object.__setattr__(self, "materialization_mode", mode)
        object.__setattr__(self, "oracle_id", validate_oracle_id(self.oracle_id))
        if isinstance(self.oracle_revision, bool) or self.oracle_revision <= 0:
            raise ValueError("oracle_revision must be positive")
        for field_name in (
            "oracle_fingerprint",
            "attestation_intent_ref",
            "delivery_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(str(getattr(self, field_name)), field_name),
            )
        if self.command_id:
            object.__setattr__(
                self, "command_id", validate_test_command_id(self.command_id)
            )
        if self.contract_version not in {
            TEST_PROVIDER_COMMAND_VERSION,
            LEGACY_TEST_PROVIDER_COMMAND_VERSION,
        }:
            raise ValueError("unsupported test provider command contract")
        semantic_input = canonical_test_provider_input(self.semantic_input)
        if len(exact_canonical_json(semantic_input).encode("utf-8")) > 512_000:
            raise ValueError("test provider semantic input exceeds 512000 bytes")
        object.__setattr__(self, "semantic_input", semantic_input)
        source_digest = str(self.source_manifest_digest or "").strip()
        oracle_ir = dict(self.oracle_ir or {})
        requested_capability = dict(self.requested_capability or {})
        if self.contract_version == LEGACY_TEST_PROVIDER_COMMAND_VERSION:
            if mode != TestProviderMaterializationMode.ORCHESTRATOR_SOURCE:
                raise ValueError("historical command v1 supports source authority only")
            source_digest = required_text(source_digest, "source_manifest_digest")
            if oracle_ir or requested_capability:
                raise ValueError("historical command v1 cannot contain Oracle IR")
        elif mode == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE:
            source_digest = required_text(source_digest, "source_manifest_digest")
            if oracle_ir or requested_capability:
                raise ValueError(
                    "source materialization cannot contain Oracle IR authority"
                )
        else:
            if source_digest:
                raise ValueError(
                    "Oracle IR materialization cannot contain a source digest"
                )
            snapshot = OracleIRSnapshot.from_payload(oracle_ir)
            if (
                snapshot.oracle_id,
                snapshot.oracle_revision,
                snapshot.oracle_fingerprint,
            ) != (self.oracle_id, self.oracle_revision, self.oracle_fingerprint):
                raise ValueError("Oracle IR authority does not match command oracle")
            oracle_ir = snapshot.as_payload()
            requested_capability = canonical_materializer_capability(
                requested_capability,
                require_versions=True,
            )
            allowed_ir_semantic_fields = {
                "harness",
                "promotion_evidence_id",
                "provider_test_ref",
                "reason",
                "regression_obligation",
            }
            unknown_ir_semantic_fields = set(semantic_input).difference(
                allowed_ir_semantic_fields
            )
            if unknown_ir_semantic_fields:
                raise ValueError(
                    "Oracle IR semantic input field is unsupported: "
                    f"{sorted(unknown_ir_semantic_fields)[0]}"
                )
        object.__setattr__(self, "source_manifest_digest", source_digest)
        object.__setattr__(self, "oracle_ir", oracle_ir)
        object.__setattr__(self, "requested_capability", requested_capability)
        expected_authority_fingerprint = (
            source_digest
            if mode == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
            else str(oracle_ir["canonical_ir_fingerprint"])
        )
        supplied_authority_fingerprint = str(
            self.authority_input_fingerprint or expected_authority_fingerprint
        ).strip()
        if supplied_authority_fingerprint != expected_authority_fingerprint:
            raise ValueError("authority input fingerprint mismatch")
        object.__setattr__(
            self, "authority_input_fingerprint", supplied_authority_fingerprint
        )

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "flow_session_ref": self.flow_session_ref,
            "campaign_ref": self.campaign_id,
            "case_ref": self.case_id,
            "operation": self.operation.value,
            "oracle": {
                "oracle_ref": self.oracle_id,
                "revision": self.oracle_revision,
                "fingerprint": self.oracle_fingerprint,
            },
            "attestation_intent_ref": self.attestation_intent_ref,
            "semantic_input": dict(self.semantic_input),
            "delivery_fingerprint": self.delivery_fingerprint,
        }
        if self.contract_version == LEGACY_TEST_PROVIDER_COMMAND_VERSION:
            payload["source_manifest_digest"] = self.source_manifest_digest
        else:
            payload["materialization_mode"] = self.materialization_mode.value
            payload["authority_input_fingerprint"] = self.authority_input_fingerprint
            if (
                self.materialization_mode
                == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
            ):
                source_files = payload["semantic_input"].pop("source_files", None)
                authority_input: dict[str, object] = {
                    "source_manifest_digest": self.source_manifest_digest,
                }
                if source_files is not None:
                    authority_input["source_files"] = source_files
                payload["authority_input"] = authority_input
            else:
                payload["authority_input"] = {
                    "oracle_ir": dict(self.oracle_ir),
                    "requested_capability": dict(self.requested_capability),
                }
        if self.command_id:
            payload["command_ref"] = self.command_id
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "TestProviderCommand":
        contract_version = str(payload.get("contract_version") or "")
        if contract_version not in {
            TEST_PROVIDER_COMMAND_VERSION,
            LEGACY_TEST_PROVIDER_COMMAND_VERSION,
        }:
            raise ValueError("unsupported test provider command contract")
        oracle = _required_mapping(payload.get("oracle"), "oracle")
        semantic_input = dict(
            _required_mapping(payload.get("semantic_input"), "semantic_input")
        )
        source_digest = str(payload.get("source_manifest_digest") or "")
        mode = TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
        authority_input_fingerprint = ""
        oracle_ir: Mapping[str, object] = {}
        requested_capability: Mapping[str, object] = {}
        if contract_version == TEST_PROVIDER_COMMAND_VERSION:
            allowed_fields = {
                "contract_version",
                "flow_session_ref",
                "campaign_ref",
                "case_ref",
                "operation",
                "oracle",
                "attestation_intent_ref",
                "materialization_mode",
                "authority_input_fingerprint",
                "authority_input",
                "semantic_input",
                "delivery_fingerprint",
                "command_ref",
            }
            unknown = sorted(set(payload) - allowed_fields)
            if unknown:
                raise ValueError(f"command v2 field is unknown: {unknown[0]}")
            if "source_manifest_digest" in payload:
                raise ValueError("command v2 cannot contain a legacy source digest")
            mode = TestProviderMaterializationMode(
                str(payload.get("materialization_mode") or "")
            )
            authority_input = _required_mapping(
                payload.get("authority_input"), "authority_input"
            )
            authority_input_fingerprint = str(
                payload.get("authority_input_fingerprint") or ""
            )
            if mode == TestProviderMaterializationMode.ORCHESTRATOR_SOURCE:
                if "source_files" in semantic_input:
                    raise ValueError(
                        "command v2 source files must have one authority location"
                    )
                unknown = sorted(
                    set(authority_input) - {"source_manifest_digest", "source_files"}
                )
                if unknown:
                    raise ValueError(f"source authority field is unknown: {unknown[0]}")
                source_digest = str(authority_input.get("source_manifest_digest") or "")
                if "source_files" in authority_input:
                    semantic_input["source_files"] = authority_input["source_files"]
            else:
                if set(authority_input) != {"oracle_ir", "requested_capability"}:
                    raise ValueError("Oracle IR authority input is malformed")
                oracle_ir = _required_mapping(
                    authority_input.get("oracle_ir"), "authority_input.oracle_ir"
                )
                requested_capability = _required_mapping(
                    authority_input.get("requested_capability"),
                    "authority_input.requested_capability",
                )
        return cls(
            flow_session_ref=str(payload.get("flow_session_ref") or ""),
            campaign_id=str(payload.get("campaign_ref") or ""),
            case_id=str(payload.get("case_ref") or ""),
            operation=TestProviderOperation(str(payload.get("operation") or "")),
            oracle_id=str(oracle.get("oracle_ref") or ""),
            oracle_revision=_required_int(
                oracle.get("revision"), "oracle.revision", minimum=1
            ),
            oracle_fingerprint=str(oracle.get("fingerprint") or ""),
            attestation_intent_ref=str(payload.get("attestation_intent_ref") or ""),
            source_manifest_digest=source_digest,
            semantic_input=semantic_input,
            delivery_fingerprint=str(payload.get("delivery_fingerprint") or ""),
            command_id=str(payload.get("command_ref") or ""),
            materialization_mode=mode,
            authority_input_fingerprint=authority_input_fingerprint,
            oracle_ir=oracle_ir,
            requested_capability=requested_capability,
            contract_version=contract_version,
        )


@dataclass(frozen=True)
class TestProviderReceipt:
    """Provider-neutral technical evidence returned for one durable command."""

    command_id: str
    provider_event_seq: int
    technical_state: str
    evidence_disposition: CampaignEvidenceDisposition
    attestation_state: MaterializationAttestationState
    oracle_id: str
    oracle_revision: int
    oracle_fingerprint: str
    source_manifest_digest: str
    materialization_ref: str
    materialization_revision: int
    representation_fingerprint: str
    evidence_reference: str
    current: bool
    complete: bool
    integrity_preserved: bool
    next_action: str
    provider_test_ref: str = ""
    diagnostics: tuple[str, ...] = ()
    representation_lineage: tuple[Mapping[str, object], ...] = ()
    materialization_mode: TestProviderMaterializationMode = (
        TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
    )
    authority_input_fingerprint: str = ""
    materialization_evidence: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = TEST_PROVIDER_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "command_id", validate_test_command_id(self.command_id)
        )
        if isinstance(self.provider_event_seq, bool) or self.provider_event_seq < 0:
            raise ValueError("provider_event_seq must be non-negative")
        object.__setattr__(
            self,
            "technical_state",
            required_text(self.technical_state, "technical_state"),
        )
        object.__setattr__(
            self,
            "evidence_disposition",
            CampaignEvidenceDisposition(self.evidence_disposition),
        )
        object.__setattr__(
            self,
            "attestation_state",
            MaterializationAttestationState(self.attestation_state),
        )
        mode = TestProviderMaterializationMode(self.materialization_mode)
        object.__setattr__(self, "materialization_mode", mode)
        object.__setattr__(self, "oracle_id", validate_oracle_id(self.oracle_id))
        if isinstance(self.oracle_revision, bool) or self.oracle_revision <= 0:
            raise ValueError("oracle_revision must be positive")
        if (
            isinstance(self.materialization_revision, bool)
            or self.materialization_revision < 0
        ):
            raise ValueError("materialization_revision must be non-negative")
        for field_name in ("current", "complete", "integrity_preserved"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        for field_name in (
            "oracle_fingerprint",
            "source_manifest_digest",
            "materialization_ref",
            "representation_fingerprint",
            "evidence_reference",
            "next_action",
        ):
            object.__setattr__(
                self,
                field_name,
                required_text(str(getattr(self, field_name)), field_name),
            )
        object.__setattr__(
            self, "provider_test_ref", str(self.provider_test_ref or "").strip()
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_texts(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self,
            "representation_lineage",
            tuple(
                _representation_lineage_item(item)
                for item in self.representation_lineage
            ),
        )
        if self.contract_version not in {
            TEST_PROVIDER_RECEIPT_VERSION,
            LEGACY_TEST_PROVIDER_RECEIPT_VERSION,
        }:
            raise ValueError("unsupported test provider receipt contract")
        if (
            self.contract_version == LEGACY_TEST_PROVIDER_RECEIPT_VERSION
            and mode != TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
        ):
            raise ValueError("historical receipt v1 supports source authority only")
        legacy_source_input = (
            self.source_manifest_digest
            if self.contract_version == LEGACY_TEST_PROVIDER_RECEIPT_VERSION
            else ""
        )
        authority_input_fingerprint = str(
            self.authority_input_fingerprint or legacy_source_input
        ).strip()
        if not authority_input_fingerprint:
            raise ValueError("authority_input_fingerprint is required")
        if (
            legacy_source_input
            and authority_input_fingerprint != legacy_source_input
        ):
            raise ValueError("receipt source authority fingerprint mismatch")
        object.__setattr__(
            self, "authority_input_fingerprint", authority_input_fingerprint
        )
        evidence = canonical_test_provider_input(self.materialization_evidence)
        if len(exact_canonical_json(evidence).encode("utf-8")) > 512_000:
            raise ValueError("materialization evidence exceeds 512000 bytes")
        if (
            mode == TestProviderMaterializationMode.DETERMINISTIC_ORACLE_IR
            and not evidence
        ):
            raise ValueError("Oracle IR receipt requires materialization evidence")
        object.__setattr__(self, "materialization_evidence", evidence)

    @property
    def fingerprint(self) -> str:
        return semantic_fingerprint(self.as_payload())

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "command_ref": self.command_id,
            "provider_event_seq": self.provider_event_seq,
            "technical_state": self.technical_state,
            "evidence_disposition": self.evidence_disposition.value,
            "attestation_state": self.attestation_state.value,
            "oracle": {
                "oracle_ref": self.oracle_id,
                "revision": self.oracle_revision,
                "fingerprint": self.oracle_fingerprint,
            },
            "materialization": {
                "ref": self.materialization_ref,
                "revision": self.materialization_revision,
                "representation_fingerprint": self.representation_fingerprint,
                "representation_lineage": [
                    dict(item) for item in self.representation_lineage
                ],
            },
            "evidence_reference": self.evidence_reference,
            "provider_test_ref": self.provider_test_ref,
            "current": self.current,
            "complete": self.complete,
            "integrity_preserved": self.integrity_preserved,
            "diagnostics": list(self.diagnostics),
            "next_action": self.next_action,
        }
        if self.contract_version == LEGACY_TEST_PROVIDER_RECEIPT_VERSION:
            payload["source_manifest_digest"] = self.source_manifest_digest
        else:
            payload["materialization_mode"] = self.materialization_mode.value
            payload["authority_input_fingerprint"] = self.authority_input_fingerprint
            payload["produced_source_manifest_digest"] = self.source_manifest_digest
            payload["materialization_evidence"] = dict(self.materialization_evidence)
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "TestProviderReceipt":
        contract_version = str(payload.get("contract_version") or "")
        if contract_version not in {
            TEST_PROVIDER_RECEIPT_VERSION,
            LEGACY_TEST_PROVIDER_RECEIPT_VERSION,
        }:
            raise ValueError("unsupported test provider receipt contract")
        oracle = _required_mapping(payload.get("oracle"), "oracle")
        materialization = _required_mapping(
            payload.get("materialization"), "materialization"
        )
        lineage = materialization.get("representation_lineage") or []
        if not isinstance(lineage, list) or not all(
            isinstance(item, Mapping) for item in lineage
        ):
            raise ValueError("representation_lineage must be a list of objects")
        diagnostics = payload.get("diagnostics") or []
        if not isinstance(diagnostics, list) or not all(
            isinstance(item, str) for item in diagnostics
        ):
            raise ValueError("diagnostics must be a list of strings")
        mode = TestProviderMaterializationMode.ORCHESTRATOR_SOURCE
        authority_input_fingerprint = ""
        materialization_evidence: Mapping[str, object] = {}
        source_digest = str(payload.get("source_manifest_digest") or "")
        if contract_version == TEST_PROVIDER_RECEIPT_VERSION:
            allowed_fields = {
                "contract_version",
                "command_ref",
                "provider_event_seq",
                "technical_state",
                "evidence_disposition",
                "attestation_state",
                "oracle",
                "materialization_mode",
                "authority_input_fingerprint",
                "produced_source_manifest_digest",
                "materialization",
                "materialization_evidence",
                "evidence_reference",
                "provider_test_ref",
                "current",
                "complete",
                "integrity_preserved",
                "diagnostics",
                "next_action",
            }
            unknown = sorted(set(payload) - allowed_fields)
            if unknown:
                raise ValueError(f"receipt v2 field is unknown: {unknown[0]}")
            if "source_manifest_digest" in payload:
                raise ValueError("receipt v2 cannot contain a legacy source digest")
            mode = TestProviderMaterializationMode(
                str(payload.get("materialization_mode") or "")
            )
            authority_input_fingerprint = str(
                payload.get("authority_input_fingerprint") or ""
            )
            source_digest = str(payload.get("produced_source_manifest_digest") or "")
            materialization_evidence = _required_mapping(
                payload.get("materialization_evidence"), "materialization_evidence"
            )
        return cls(
            command_id=str(payload.get("command_ref") or ""),
            provider_event_seq=_required_int(
                payload.get("provider_event_seq"), "provider_event_seq", minimum=0
            ),
            technical_state=str(payload.get("technical_state") or ""),
            evidence_disposition=CampaignEvidenceDisposition(
                str(payload.get("evidence_disposition") or "")
            ),
            attestation_state=MaterializationAttestationState(
                str(payload.get("attestation_state") or "")
            ),
            oracle_id=str(oracle.get("oracle_ref") or ""),
            oracle_revision=_required_int(
                oracle.get("revision"), "oracle.revision", minimum=1
            ),
            oracle_fingerprint=str(oracle.get("fingerprint") or ""),
            source_manifest_digest=source_digest,
            materialization_ref=str(materialization.get("ref") or ""),
            materialization_revision=_required_int(
                materialization.get("revision"),
                "materialization.revision",
                minimum=0,
            ),
            representation_fingerprint=str(
                materialization.get("representation_fingerprint") or ""
            ),
            representation_lineage=tuple(dict(item) for item in lineage),
            evidence_reference=str(payload.get("evidence_reference") or ""),
            provider_test_ref=str(payload.get("provider_test_ref") or ""),
            current=_required_bool(payload.get("current"), "current"),
            complete=_required_bool(payload.get("complete"), "complete"),
            integrity_preserved=_required_bool(
                payload.get("integrity_preserved"), "integrity_preserved"
            ),
            diagnostics=tuple(diagnostics),
            next_action=str(payload.get("next_action") or ""),
            materialization_mode=mode,
            authority_input_fingerprint=authority_input_fingerprint,
            materialization_evidence=materialization_evidence,
            contract_version=contract_version,
        )


def canonical_materializer_capability(
    value: Mapping[str, object],
    *,
    require_versions: bool = False,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("requested_capability must be an object")
    version_fields = {
        "oracle_ir_contract_version",
        "operator_profile",
        "materializer_version",
        "adapter_version",
    }
    allowed = {
        "language",
        "framework",
        "artifact_scope_preference",
        *version_fields,
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"requested_capability field is invalid: {unknown[0]}")
    language = value.get("language")
    framework = value.get("framework")
    if not isinstance(language, str):
        raise ValueError("language must be text")
    if not isinstance(framework, str):
        raise ValueError("framework must be text")
    capability = {
        "language": required_text(language, "language"),
        "framework": required_text(framework, "framework"),
    }
    raw_artifact_scope = value.get("artifact_scope_preference", "")
    if not isinstance(raw_artifact_scope, str):
        raise ValueError("artifact_scope_preference must be text")
    artifact_scope = raw_artifact_scope.strip()
    if artifact_scope:
        normalized_scope = artifact_scope.replace("\\", "/")
        if (
            normalized_scope.startswith("/")
            or ".." in normalized_scope.split("/")
            or len(normalized_scope) > 512
        ):
            raise ValueError("artifact_scope_preference must be a safe relative scope")
        capability["artifact_scope_preference"] = normalized_scope
    for field_name in sorted(version_fields):
        raw_value = value.get(field_name)
        if raw_value is None and not require_versions:
            continue
        if not isinstance(raw_value, str):
            raise ValueError(f"{field_name} must be text")
        capability[field_name] = required_text(raw_value, field_name)
    return capability


def canonical_semantic_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): canonical_semantic_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, tuple | list):
        return [canonical_semantic_value(item) for item in value]
    if isinstance(value, str):
        return normalize_semantic_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    raise ValueError(f"unsupported semantic value: {type(value).__name__}")


def canonical_test_provider_input(value: Mapping[str, object]) -> dict[str, object]:
    """Canonicalize semantic fields without modifying authored source bytes."""

    raw = dict(value or {})
    source_files = raw.pop("source_files", None)
    result = canonical_semantic_value(raw)
    if not isinstance(result, dict):  # pragma: no cover - mapping input guarantees this
        raise ValueError("test provider semantic input must be an object")
    if source_files is not None:
        if not isinstance(source_files, Mapping) or not source_files:
            raise ValueError("test provider source_files must be a non-empty object")
        exact_sources: dict[str, str] = {}
        for path, source in source_files.items():
            relative_path = str(path or "").strip().replace("\\", "/")
            if (
                not relative_path
                or relative_path.startswith("/")
                or ".." in relative_path.split("/")
                or not isinstance(source, str)
            ):
                raise ValueError("test provider source_files are invalid")
            exact_sources[relative_path] = source
        result["source_files"] = dict(sorted(exact_sources.items()))
    return result


TEST_HARNESS_DISPOSITIONS = ("repository", "project_integration")
TEST_HARNESS_PARTICIPANT_FIELDS = (
    "participant_ref",
    "repository",
    "runtime_participant",
    "role",
)


def canonical_test_harness(value: Mapping[str, object] | None) -> dict[str, object]:
    raw = dict(value or {"disposition": "repository", "participants": []})
    unknown = sorted(set(raw).difference({"disposition", "participants"}))
    if unknown:
        raise ValueError(f"test harness field is invalid: {unknown[0]}")
    disposition = required_text(
        str(raw.get("disposition") or ""), "harness.disposition"
    )
    if disposition not in TEST_HARNESS_DISPOSITIONS:
        raise ValueError("test harness disposition is invalid")
    rows = raw.get("participants") or []
    if not isinstance(rows, list):
        raise ValueError("test harness participants must be a list")
    participants: list[dict[str, object]] = []
    allowed = set(TEST_HARNESS_PARTICIPANT_FIELDS)
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("test harness participant must be an object")
        extra = sorted(set(row).difference(allowed))
        if extra:
            raise ValueError(f"test harness participant field is invalid: {extra[0]}")
        repository = row.get("repository")
        if isinstance(repository, bool) or not isinstance(repository, (str, int)):
            raise ValueError("test harness participant repository is invalid")
        participants.append(
            {
                "participant_ref": required_text(
                    str(row.get("participant_ref") or ""),
                    "harness.participant_ref",
                ),
                "repository": repository,
                "runtime_participant": required_text(
                    str(row.get("runtime_participant") or ""),
                    "harness.runtime_participant",
                ),
                "role": required_text(str(row.get("role") or ""), "harness.role"),
            }
        )
    if disposition == "repository" and participants:
        raise ValueError("repository harness cannot declare participants")
    if disposition == "project_integration" and len(participants) < 2:
        raise ValueError("project integration harness requires two participants")
    return {
        "disposition": disposition,
        "participants": participants,
    }


def _representation_lineage_item(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("representation lineage entries must be objects")
    source_digest = required_text(
        str(value.get("source_manifest_digest") or ""),
        "source_manifest_digest",
    )
    complete = value.get("complete")
    integrity_preserved = value.get("integrity_preserved")
    if not isinstance(complete, bool) or not isinstance(integrity_preserved, bool):
        raise ValueError(
            "representation lineage completeness and integrity must be boolean"
        )
    return {
        **canonical_semantic_value(dict(value)),
        "source_manifest_digest": source_digest,
        "complete": complete,
        "integrity_preserved": integrity_preserved,
    }


def _required_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_int(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer >= {minimum}")
    return value


def _required_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def normalize_semantic_text(value: str) -> str:
    return " ".join(str(value or "").split())


def canonical_json(value: object) -> str:
    return json.dumps(
        canonical_semantic_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def exact_canonical_json(value: object) -> str:
    """Stable JSON for transport payloads whose string bytes are authoritative."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def exact_fingerprint(value: object) -> str:
    return sha256(exact_canonical_json(value).encode("utf-8")).hexdigest()


def semantic_fingerprint(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_manifest_digest(files: Mapping[str, str]) -> str:
    normalized: list[dict[str, str]] = []
    for path, content in sorted(files.items()):
        relative_path = str(path or "").strip().replace("\\", "/")
        if (
            not relative_path
            or relative_path.startswith("/")
            or ".." in relative_path.split("/")
        ):
            raise ValueError("source manifest paths must be safe relative paths")
        if not isinstance(content, str):
            raise ValueError("source manifest content must be text")
        normalized.append(
            {
                "path": relative_path,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    if not normalized:
        raise ValueError("source manifest requires at least one file")
    return exact_fingerprint(normalized)


def validate_obligation_id(value: str) -> str:
    return _validate_identifier(value, "obligation_id", _OBLIGATION_ID_RE, "OBL-000000")


def validate_oracle_id(value: str) -> str:
    return _validate_identifier(value, "oracle_id", _ORACLE_ID_RE, "ORACLE-000000")


def validate_attestation_id(value: str) -> str:
    return _validate_identifier(
        value, "attestation_id", _ATTESTATION_ID_RE, "ATTEST-000000"
    )


def validate_test_command_id(value: str) -> str:
    return _validate_identifier(value, "command_id", _TEST_COMMAND_ID_RE, "TCMD-000000")


def validate_test_receipt_id(value: str) -> str:
    return _validate_identifier(
        value, "receipt_id", _TEST_RECEIPT_ID_RE, "TRCPT-000000"
    )


def _validate_identifier(
    value: str, field_name: str, pattern: re.Pattern[str], example: str
) -> str:
    normalized = required_text(value, field_name)
    if not pattern.fullmatch(normalized):
        raise ValueError(f"{field_name} must match {example}")
    return normalized


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(values)
    if len(set(result)) != len(result):
        raise ValueError("values must be unique")
    return result


def _unique_texts(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    return _unique(tuple(required_text(str(item), field_name) for item in values))
