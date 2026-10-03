"""Explicit bounded semantic assignments with shared validation and adoption."""
from __future__ import annotations

from dataclasses import asdict
import json
from typing import Mapping

from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
from flow_of_work_mcp.application.srs_semantic_validation import SrsSemanticValidationService
from flow_of_work_mcp.application.srs_validation import SrsValidationService
from flow_of_work_mcp.application.intention_grounding import IntentionGroundingService
from flow_of_work_mcp.core.domain import ValidationAuditRecord, ValidationDisposition
from flow_of_work_mcp.core.domain.identifiers import required_text
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, ModelGatewayError
from flow_of_work_mcp.core.ports import ModelGateway, ModelRequest, ModelResult
from flow_of_work_mcp.core.ports.semantic_assignments import SemanticAssignmentRepository
from flow_of_work_mcp.core.standards import StandardProfileRegistry


_ROLE = "srs_semantic_validation"


class SemanticAssignmentService:
    def __init__(
        self, *, repository: SemanticAssignmentRepository,
        structural_validation: SrsValidationService, profiles: StandardProfileRegistry,
        lifecycle: LifecycleControlService, gateway: ModelGateway | None = None,
        grounding: IntentionGroundingService | None = None, observed_behavior_available: bool = False,
    ) -> None:
        self._repository = repository
        self._structural = structural_validation
        self._lifecycle = lifecycle
        self._gateway = gateway
        self._role = SrsSemanticValidationService(gateway, profiles)
        self._grounding = grounding
        self._observed_available = observed_behavior_available

    def inventory(self, project_id: str) -> Mapping[str, object]:
        self._repository.ensure_semantic_project(project_id)
        return {
            "project_id": project_id,
            "roles": [
                {"role": _ROLE, "assignment_supported": True,
                 "execution_modes": ["host", "internal"], "host_available": True,
                 "internal_available": self._gateway is not None,
                 "internal_prerequisites": ["configured optional ModelGateway"],
                 "adoption": "canonical validation audit only; no baseline or human acceptance"},
                {"role": "intention_grounding", "assignment_supported": self._grounding is not None,
                 "execution_modes": ["host", "internal"] if self._grounding is not None else [],
                 "host_available": self._grounding is not None,
                 "host_prerequisites": ["selected canonical goals", "flower-host-grounding-evidence-v1 closed declared receipt"],
                 "internal_available": self._grounding is not None and self._grounding.internal_available,
                 "existing_internal_available": self._grounding is not None and self._grounding.internal_available,
                 "existing_internal_tool": "fow_ground_intent",
                 "internal_prerequisites": ["configured optional ModelGateway", "ImplementationGraphProvider"],
                 "evidence_rule": "host evidence/currentness is host_declared; internal evidence is provider_snapshot",
                 "adoption": "canonical grounding audit only; no requirement or human acceptance mutation"},
                {"role": "observed_behavior_drafting", "assignment_supported": False,
                 "execution_modes": [], "host_available": False,
                 "host_reason": "host evidence and code-import intake adoption contract is not implemented",
                 "existing_internal_available": self._observed_available,
                 "existing_internal_tool": "fow_bootstrap(derive_behavior)",
                 "internal_prerequisites": ["configured optional ModelGateway", "BootstrapBehaviorProvider", "confirmed code-import intake"],
                 "evidence_rule": "provider snapshot required; drafting does not accept product authority"},
            ],
            "next_gate": {"tool": "fow_semantic", "operation": "prepare"},
        }

    def prepare(
        self, project_id: str, *, role: str, execution_mode: str,
        source_path: str = "", standard_profile: str = "", actor: str, request_id: str = "",
        goal_node_ids: tuple[str, ...] = (), host_evidence: Mapping[str, object] | None = None,
        source_revision: str = "",
    ) -> Mapping[str, object]:
        self._repository.ensure_semantic_project(project_id)
        if role != _ROLE and not (role == "intention_grounding" and self._grounding is not None):
            return self._blocked("semantic_assignment_role_unsupported", {
                "project_id": project_id, "role": role,
                "inventory": self.inventory(project_id),
            }, "inventory")
        if execution_mode not in {"host", "internal"}:
            raise ValueError("execution_mode must be host or internal")
        if role == "intention_grounding":
            if source_path or standard_profile:
                raise ValueError("grounding does not accept SRS-only arguments")
            try:
                preparation = self._grounding.prepare(project_id, goal_node_ids=goal_node_ids,
                    execution_mode=execution_mode, host_evidence=host_evidence, source_revision=source_revision)
            except ChangeControlBlockedError as exc:
                return self._blocked(exc.reason, {"project_id": project_id, "role": role}, "prepare")
        else:
            if goal_node_ids or host_evidence is not None or source_revision:
                raise ValueError("SRS validation does not accept grounding-only arguments")
            structural = self._structural.validate(source_path, standard_profile=standard_profile)
            if structural.disposition == ValidationDisposition.REJECTED:
                return self._blocked("semantic_structural_input_rejected", {
                    "project_id": project_id, "audit": structural.to_dict(),
                }, "prepare")
            preparation = self._preparation(structural)
        view = self._repository.prepare_semantic_assignment(
            project_id, role=role, execution_mode=execution_mode,
            preparation=preparation, actor=actor, request_id=request_id,
        )
        return self._view(view, current=True)

    def inspect(self, project_id: str, assignment_id: str) -> Mapping[str, object]:
        view = self._repository.semantic_assignment(project_id, assignment_id)
        _, current_reason = self._current_structural(view)
        return self._view(view, current=not current_reason, current_reason=current_reason)

    def submit(
        self, project_id: str, assignment_id: str, *, result: Mapping[str, object],
        executor_ref: str, actor: str, request_id: str = "", source_revision: str = "",
    ) -> Mapping[str, object]:
        view = self._repository.semantic_assignment(project_id, assignment_id)
        if view["execution_mode"] != "host":
            return self._blocked("semantic_execution_mode_mismatch", view, "inspect")
        if view["role"] == "intention_grounding":
            return self._submit_grounding(view, result=result, executor_ref=executor_ref,
                                         actor=actor, request_id=request_id, source_revision=source_revision)
        if source_revision:
            raise ValueError("SRS submission does not accept source_revision")
        structural, reason = self._current_structural(view)
        if reason:
            return self._blocked(reason, view, "prepare")
        executor = required_text(executor_ref, "executor_ref")
        if len(executor) > 1000:
            raise ValueError("executor_ref exceeds 1000 characters")
        if not isinstance(result, Mapping):
            raise ValueError("result must be an object with findings")
        # Reject oversized/non-JSON transport input before durable event storage.
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > 128_000:
            return self._blocked("semantic_output_size_exceeded", view, "submit")
        model_result = ModelResult(
            text="", structured_output=dict(result), model="", terminal_reason="completed",
        )
        audit = self._role.validate_result(structural, model_result)
        usable = audit.terminal_reason == "completed"
        stored = self._repository.record_semantic_submission(
            project_id, assignment_id,
            result={"output": dict(result), "audit": dict(audit.to_dict()),
                    "provenance": {"execution_mode": "host", "executor_ref": executor,
                                   "evidence_authority": "host_declared"}},
            usable=usable, actor=actor, request_id=request_id,
        )
        if not usable:
            return self._blocked("semantic_output_invalid", stored, "submit")
        return self._view(stored, current=True)

    def _submit_grounding(self, view, *, result, executor_ref, actor, request_id, source_revision):
        executor = required_text(executor_ref, "executor_ref")
        if len(executor) > 1000 or not isinstance(source_revision, str) or not source_revision.strip() or len(source_revision) > 1000:
            raise ValueError("host grounding submission requires bounded executor_ref and source_revision")
        if not isinstance(result, Mapping):
            raise ValueError("grounding result must contain assessments")
        if len(json.dumps(result, sort_keys=True, allow_nan=False).encode("utf-8")) > 128000:
            return self._blocked("semantic_output_size_exceeded", view, "submit")
        reason = self._grounding.currentness_reason(view["preparation"])
        if source_revision != view["preparation"]["source_revision"]:
            reason = "semantic_source_stale"
        provenance = {"assignment_id": view["assignment_id"], "execution_mode": "host", "executor_ref": executor,
                      "evidence_authority": "host_declared", "declared_source_revision": source_revision,
                      "source_currentness": "host_declared_changed" if source_revision != view["preparation"]["source_revision"]
                                             else "host_declared_as_of_submission"}
        audit = self._grounding.validate_result(view["preparation"], ModelResult(
            text="", structured_output=dict(result), model="", terminal_reason="completed"), provenance=provenance)
        usable = audit.terminal_reason == "completed" and not reason
        stored = self._repository.record_semantic_submission(view["project_id"], view["assignment_id"],
            result={"output": dict(result), "audit": self._grounding.audit_value(audit), "provenance": provenance,
                    "currentness_reason": reason}, usable=usable, actor=actor, request_id=request_id)
        if not usable:
            return self._blocked(reason or "semantic_output_invalid", stored, "prepare" if reason else "submit")
        return self._view(stored, current=True)

    def adopt(
        self, project_id: str, assignment_id: str, *, actor: str, request_id: str = "",
    ) -> Mapping[str, object]:
        with self._repository.atomic():
            view = self._repository.semantic_assignment(project_id, assignment_id)
            if view["state"] == "adopted":
                return self.inspect(project_id, assignment_id)
            _, reason = self._current_structural(view)
            if reason:
                return self._blocked(reason, view, "prepare")
            if view["state"] != "validated":
                return self._blocked("semantic_result_not_validated", view, "inspect")
            result = view["result"]
            audit = result["audit"]
            if view["role"] == "intention_grounding":
                record = self._grounding.adopt(audit, actor=actor,
                                              request_id=f"semantic:{assignment_id}:grounding-adoption")
                adoption = {"grounding_audit_id": record.audit_id, "disposition": record.disposition.value,
                            "authority_scope": "grounding_audit_only", "evidence_authority": record.evidence_authority}
            else:
                record = self._lifecycle.record_validation(
                    project_id,
                    ValidationAuditRecord(
                        source_ref=str(view["preparation"]["source_path"]),
                        disposition=ValidationDisposition(str(audit["disposition"])),
                        finding_codes=tuple(sorted({str(item["code"]) for item in audit["findings"]})),
                        profile_id=str(view["preparation"]["standard_profile"]),
                    ), actor=actor, request_id=f"semantic:{assignment_id}:validation-adoption")
                adoption = {"validation_audit_id": record.audit_id, "disposition": record.disposition.value,
                            "authority_scope": "validation_audit_only"}
            stored = self._repository.adopt_semantic_assignment(
                project_id, assignment_id,
                adoption=adoption,
                actor=actor, request_id=request_id,
            )
            return self._view(stored, current=True)

    def execute_internal(
        self, project_id: str, assignment_id: str, *, actor: str, request_id: str = "",
    ) -> Mapping[str, object]:
        view = self._repository.semantic_assignment(project_id, assignment_id)
        if view["execution_mode"] != "internal":
            return self._blocked("semantic_execution_mode_mismatch", view, "inspect")
        if view["state"] in {"validated", "adopted"}:
            return self.inspect(project_id, assignment_id)
        if view["state"] != "prepared":
            return self._blocked("semantic_internal_already_attempted", view, "inspect")
        if self._gateway is None:
            return self._blocked("semantic_internal_runtime_unconfigured", view, "inspect")
        structural, reason = self._current_structural(view)
        if reason:
            return self._blocked(reason, view, "prepare")
        admitted = self._repository.begin_semantic_internal(
            project_id, assignment_id, actor=actor, request_id=request_id,
        )
        request_fields = admitted["preparation"]["request"]
        request = ModelRequest(
            role_id=str(request_fields["role_id"]),
            messages=tuple(request_fields["messages"]),
            output_schema=request_fields["output_schema"],
            max_output_tokens=int(request_fields["max_output_tokens"]),
            request_id=str(request_fields["request_id"]),
        )
        try:
            result = self._gateway.invoke(request)
        except ModelGatewayError:
            result = ModelResult(text="", structured_output=None, model="", terminal_reason="model_error")
        provenance = {"execution_mode": "internal", "model": result.model,
                      "terminal_reason": result.terminal_reason, "evidence_authority": "internal_model_proposal"}
        if view["role"] == "intention_grounding":
            provenance.update({"assignment_id": view["assignment_id"], "evidence_authority": "provider_snapshot",
                               "source_currentness": "provider_snapshot_as_of_preparation"})
            audit = self._grounding.validate_result(structural, result, provenance=provenance)
            audit_value = self._grounding.audit_value(audit)
        else:
            audit = self._role.validate_result(structural, result)
            audit_value = dict(audit.to_dict())
        # A source change during inference cannot be adopted as current work.
        _, current_reason = self._current_structural(admitted)
        usable = audit.terminal_reason == "completed" and not current_reason
        stored = self._repository.record_semantic_submission(
            project_id, assignment_id,
            result={"output": self._bounded_internal_output(result.structured_output), "audit": audit_value,
                    "provenance": provenance,
                    "currentness_reason": current_reason},
            usable=usable, actor=actor, request_id=request_id, internal=True,
        )
        if not usable:
            return self._blocked(current_reason or "semantic_internal_result_unusable", stored, "inspect")
        return self._view(stored, current=True)

    def _preparation(self, structural) -> Mapping[str, object]:
        request = self._role.prepare(structural)
        scope = json.loads(request.messages[1]["content"])
        sections = []
        for section in scope["sections"]:
            sections.append(
                f"## {section['heading']}\n\n"
                f"Section ID: `{section['section_id']}`. Allowed entity IDs: "
                f"{', '.join(section['allowed_entity_ids']) or '(none)'}.\n\n{section['body']}"
            )
        return {
            "source_path": structural.source_path,
            "source_sha256": structural.content_sha256,
            "standard_profile": structural.profile_id,
            "profile_version": structural.profile_version,
            "prompt_version": self._role.prompt_version,
            "input_truncated": scope["input_truncated"],
            "request": json.loads(json.dumps(asdict(request), sort_keys=True)),
            "task_markdown": "# SRS semantic validation assignment\n\n"
                + request.messages[0]["content"]
                + "\n\nSubmit a structured result; submission and validation do not adopt it. "
                  "Adoption records a validation audit and does not constitute human acceptance.\n\n"
                + ("The source projection is truncated to the role budget. A clean result "
                   "still requires review; omitted source has not been semantically checked.\n\n"
                   if scope["input_truncated"] else "")
                + "\n\n".join(sections),
        }

    def _current_structural(self, view):
        if view["role"] == "intention_grounding":
            reason = self._grounding.currentness_reason(view["preparation"])
            # A later host declaration of changed source supersedes the prior
            # unchanged-source assertion, while preserving the original result.
            submissions = [event for event in view.get("events", []) if event["operation"] == "submit"]
            if not reason and submissions and submissions[-1]["payload"].get("currentness_reason") == "semantic_source_stale":
                reason = "semantic_source_stale"
            return view["preparation"], reason
        preparation = view["preparation"]
        try:
            structural = self._structural.validate(
                str(preparation["source_path"]),
                standard_profile=str(preparation["standard_profile"]),
            )
        except (ValueError, OSError):
            return None, "semantic_source_unavailable"
        if structural.content_sha256 != preparation["source_sha256"]:
            return None, "semantic_source_stale"
        if structural.profile_version != preparation["profile_version"]:
            return None, "semantic_profile_stale"
        if self._role.prompt_version != preparation["prompt_version"]:
            return None, "semantic_prompt_stale"
        if structural.disposition == ValidationDisposition.REJECTED:
            return None, "semantic_contract_stale"
        current = self._preparation(structural)
        if current != preparation:
            return None, "semantic_contract_stale"
        return structural, ""

    @staticmethod
    def _bounded_internal_output(output):
        if isinstance(output, Mapping):
            try:
                encoded = json.dumps(output, sort_keys=True, allow_nan=False)
                if len(encoded.encode("utf-8")) <= 128_000:
                    return dict(output)
            except (TypeError, ValueError):
                pass
        # Explicit failure diagnostics retain the receipt without storing an
        # unbounded or non-JSON model response. This never becomes a usable result.
        return {"invalid_output_omitted": True}

    @staticmethod
    def _view(view, *, current: bool, current_reason: str = ""):
        operation = {
            "prepared": "submit" if view["execution_mode"] == "host" else "execute_internal",
            "validated": "adopt", "adopted": "inspect",
            "internal_running": "inspect", "internal_failed": "prepare",
            "internal_interrupted": "prepare",
        }[view["state"]]
        if not current:
            operation = "prepare"
        provenance = SemanticAssignmentService._latest_provenance(view)
        grounding = ({"evidence_authority": view["preparation"]["evidence_authority"],
                      "source_currentness": provenance.get("source_currentness", "not_independently_verified"),
                      "external_source_verified": False} if view["role"] == "intention_grounding" else {})
        return {**dict(view), **grounding, "current": current, "currentness_reason": current_reason,
                "semantic_truth_verified": False, "human_acceptance": False,
                "next_gate": {"tool": "fow_semantic", "operation": operation,
                              "assignment_id": view["assignment_id"]}}

    @staticmethod
    def _blocked(reason: str, view, operation: str):
        corrections = {
            "semantic_internal_runtime_unconfigured":
                "Configure the optional inference runtime before explicit internal execution, "
                "or prepare a new host-mode assignment. The original mode is unchanged.",
            "semantic_assignment_role_unsupported":
                "Inspect the role inventory. Host observed drafting has no source-evidence/adoption contract.",
            "semantic_grounding_provider_unconfigured":
                "Internal grounding preparation requires an implementation provider. Use a new explicit "
                "host assignment with closed agent-supplied evidence when intended.",
            "semantic_grounding_input_budget_exceeded":
                "Narrow the declared goal/evidence scope to the bounded grounding context contract.",
            "semantic_structural_input_rejected":
                "Correct the structural SRS findings before preparing semantic work.",
            "semantic_execution_mode_mismatch":
                "Use submit for a host assignment or execute_internal for an internal assignment. "
                "An execution-mode change requires an explicit new preparation.",
            "semantic_output_invalid":
                "Correct the structured result using the prepared schema and supplied identities, "
                "then submit with a new request_id. No invalid result can be adopted.",
            "semantic_output_size_exceeded":
                "Submit the exact prepared role schema within its 128000-byte output budget.",
            "semantic_result_not_validated":
                "Inspect the assignment and supply a usable result before adoption.",
            "semantic_internal_already_attempted":
                "Inspect the durable prior execution outcome. Do not replay inference; prepare a new "
                "assignment only after explicitly resolving the failed or interrupted boundary.",
            "semantic_internal_result_unusable":
                "Inspect the retained execution diagnostics. A failed internal invocation does not "
                "create a host result or close the obligation.",
        }
        correction = corrections.get(reason)
        if correction is None and reason in {
            "semantic_source_unavailable", "semantic_source_stale", "semantic_profile_stale",
            "semantic_prompt_stale", "semantic_contract_stale", "semantic_flow_authority_stale",
        }:
            correction = "Restore or inspect the current source and role contract, then prepare a new " \
                         "assignment for changed authority. The prior result is historical."
        preparation = view.get("preparation", {})
        grounding = ({"evidence_authority": preparation["evidence_authority"],
                      "source_currentness": SemanticAssignmentService._latest_provenance(view).get("source_currentness", "not_independently_verified"),
                      "external_source_verified": False}
                     if view.get("role") == "intention_grounding" and preparation else {})
        return {**dict(view), **grounding, "state": "blocked", "durable_state": view.get("state", ""),
                "reason": reason, "semantic_truth_verified": False, "human_acceptance": False,
                "corrective_action": correction,
                "next_gate": {"tool": "fow_semantic", "operation": operation}}

    @staticmethod
    def _latest_provenance(view):
        submissions = [event for event in view.get("events", [])
                       if event["operation"] in {"submit", "internal_result"}]
        return (submissions[-1]["payload"].get("provenance", {}) if submissions
                else view.get("result", {}).get("provenance", {}))
