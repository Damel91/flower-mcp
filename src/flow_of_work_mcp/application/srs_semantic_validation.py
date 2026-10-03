"""Bounded LLM-assisted semantic validation for structurally valid SRS input."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

from flow_of_work_mcp.core.domain.srs import (
    FindingSeverity,
    ParsedSection,
    SemanticValidationAudit,
    SourceAnchor,
    StructuralValidationAudit,
    ValidationDisposition,
    ValidationFinding,
)
from flow_of_work_mcp.core.errors import ModelGatewayError
from flow_of_work_mcp.core.ports import ModelGateway, ModelRequest, ModelResult
from flow_of_work_mcp.core.standards import StandardProfileRegistry


_IDENTIFIER_RE = re.compile(r"\b(?:FR|NFR|UC|SQ|AC)-[A-Za-z0-9][A-Za-z0-9_-]*\b")
_MAX_FINDING_MESSAGE_CHARS = 1000


@dataclass(frozen=True)
class SemanticValidationPolicy:
    prompt_version: str = "srs-semantic-v1"
    max_document_chars: int = 24_000
    max_section_chars: int = 6_000
    max_output_tokens: int = 1_500

    def __post_init__(self) -> None:
        if self.max_document_chars <= 0 or self.max_section_chars <= 0:
            raise ValueError("semantic validation character budgets must be positive")
        if self.max_output_tokens <= 0:
            raise ValueError("semantic validation output budget must be positive")


class SrsSemanticValidationService:
    """Runs a model only on a closed, source-anchored structural candidate set."""

    def __init__(
        self,
        gateway: ModelGateway | None,
        profiles: StandardProfileRegistry,
        policy: SemanticValidationPolicy | None = None,
    ) -> None:
        self._gateway = gateway
        self._profiles = profiles
        self._policy = policy or SemanticValidationPolicy()

    @property
    def prompt_version(self) -> str:
        return self._policy.prompt_version

    def validate(self, structural_audit: StructuralValidationAudit) -> SemanticValidationAudit:
        if structural_audit.disposition == ValidationDisposition.REJECTED:
            return SemanticValidationAudit(
                structural_audit=structural_audit,
                disposition=ValidationDisposition.REJECTED,
                findings=structural_audit.findings,
                prompt_version=self._policy.prompt_version,
            )

        request = self.prepare(structural_audit)
        if self._gateway is None:
            raise ModelGatewayError("semantic_internal_runtime_unconfigured")
        try:
            result = self._gateway.invoke(request)
        except ModelGatewayError:
            result = ModelResult(
                text="",
                structured_output=None,
                model="",
                terminal_reason="model_error",
            )
        return self.validate_result(structural_audit, result)

    def prepare(self, structural_audit: StructuralValidationAudit) -> ModelRequest:
        """Project one closed role contract without invoking inference."""

        if structural_audit.disposition == ValidationDisposition.REJECTED:
            raise ValueError("semantic_structural_input_rejected")
        profile = self._profiles.get(structural_audit.profile_id)
        scope, _, _, _ = self._build_scope(structural_audit, profile)
        return ModelRequest(
            role_id="document_validator",
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Validate the supplied SRS semantic candidate set. Return JSON only: "
                        "{\"findings\":[{\"code\":str,\"severity\":\"error|warning|info\","
                        "\"section_id\":str,\"entity_id\":str,\"message\":str}]}. "
                        "Use only supplied section_id and entity_id values. Do not invent source locations."
                    ),
                },
                {"role": "user", "content": json.dumps(scope, sort_keys=True)},
            ),
            output_schema={
                "type": "object",
                "required": ["findings"],
                "additionalProperties": False,
                "properties": {
                    "findings": {
                        "type": "array",
                        "maxItems": 128,
                        "items": {
                            "type": "object",
                            "required": ["code", "severity", "section_id", "entity_id", "message"],
                            "additionalProperties": False,
                            "properties": {
                                "code": {"type": "string", "maxLength": 128, "pattern": "^SRS-"},
                                "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                                "section_id": {"type": "string"},
                                "entity_id": {"type": "string"},
                                "message": {"type": "string", "minLength": 1, "maxLength": 1000},
                            },
                        },
                    }
                },
            },
            max_output_tokens=self._policy.max_output_tokens,
            request_id=structural_audit.content_sha256,
        )

    def validate_result(
        self,
        structural_audit: StructuralValidationAudit,
        result: ModelResult,
    ) -> SemanticValidationAudit:
        """Evaluate internal or host output using exactly the same validator."""

        profile = self._profiles.get(structural_audit.profile_id)
        _, anchors, entity_ids, input_truncated = self._build_scope(structural_audit, profile)
        local_findings: list[ValidationFinding] = list(structural_audit.findings)
        if input_truncated:
            local_findings.append(
                ValidationFinding(
                    code="SRS-SEMANTIC-INPUT-TRUNCATED",
                    severity=FindingSeverity.WARNING,
                    message="semantic validation received a bounded document projection",
                    anchor=self._document_anchor(structural_audit),
                )
            )
        if result.terminal_reason == "model_error":
            local_findings.append(
                ValidationFinding(
                    code="SRS-SEMANTIC-MODEL-UNAVAILABLE",
                    severity=FindingSeverity.WARNING,
                    message="semantic validation did not return a usable bounded model result",
                    anchor=self._document_anchor(structural_audit),
                )
            )
            return self._audit(
                structural_audit,
                local_findings,
                model="",
                terminal_reason="model_error",
                input_truncated=input_truncated,
                usage={},
            )

        parsed_findings = self._validate_model_findings(
            result.structured_output,
            anchors=anchors,
            entity_ids=entity_ids,
        )
        if parsed_findings is None:
            local_findings.append(
                ValidationFinding(
                    code="SRS-SEMANTIC-OUTPUT-INVALID",
                    severity=FindingSeverity.WARNING,
                    message="semantic validation returned an invalid structured finding set",
                    anchor=self._document_anchor(structural_audit),
                )
            )
        else:
            local_findings.extend(parsed_findings)
        if result.terminal_reason != "completed":
            local_findings.append(
                ValidationFinding(
                    code="SRS-SEMANTIC-INCOMPLETE",
                    severity=FindingSeverity.WARNING,
                    message=(
                        "semantic validation ended without normal completion "
                        f"({result.terminal_reason})"
                    ),
                    anchor=self._document_anchor(structural_audit),
                )
            )
        return self._audit(
            structural_audit,
            local_findings,
            model=result.model,
            terminal_reason=(
                "invalid_structured_output" if parsed_findings is None
                else result.terminal_reason
            ),
            input_truncated=input_truncated,
            usage=result.usage,
        )

    def _build_scope(self, structural_audit, profile):
        sections_by_heading: dict[str, ParsedSection] = {}
        for section in structural_audit.sections:
            sections_by_heading.setdefault(section.normalized_heading, section)
        remaining = self._policy.max_document_chars
        input_truncated = False
        anchors: dict[str, SourceAnchor] = {}
        entity_ids: dict[str, set[str]] = {}
        rendered_sections: list[dict[str, Any]] = []
        for rule in profile.required_sections:
            section = sections_by_heading.get(rule.normalized_heading)
            if section is None:
                continue
            body_limit = min(self._policy.max_section_chars, max(0, remaining))
            body = section.body[:body_limit]
            if len(body) < len(section.body):
                input_truncated = True
            remaining -= len(body)
            anchors[rule.section_id] = section.anchor
            # Only identities visible in the bounded body enter the role
            # contract. Intersect with the full section to exclude a partial
            # identifier created by truncating in the middle of its text.
            entity_ids[rule.section_id] = (
                set(_IDENTIFIER_RE.findall(body))
                & set(_IDENTIFIER_RE.findall(section.body))
            )
            rendered_sections.append(
                {
                    "section_id": rule.section_id,
                    "heading": rule.heading,
                    "line_start": section.anchor.line_start,
                    "line_end": section.anchor.line_end,
                    "allowed_entity_ids": sorted(entity_ids[rule.section_id]),
                    "body": body,
                }
            )
        return (
            {
                "profile_id": profile.profile_id,
                "profile_version": profile.version,
                "source_sha256": structural_audit.content_sha256,
                "input_truncated": input_truncated,
                "sections": rendered_sections,
            },
            anchors,
            entity_ids,
            input_truncated,
        )

    def _validate_model_findings(
        self,
        payload: Mapping[str, Any] | None,
        *,
        anchors: Mapping[str, SourceAnchor],
        entity_ids: Mapping[str, set[str]],
    ) -> tuple[ValidationFinding, ...] | None:
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"findings"}
            or not isinstance(payload.get("findings"), list)
            or len(payload["findings"]) > 128
        ):
            return None
        try:
            if len(json.dumps(payload, allow_nan=False).encode("utf-8")) > 128_000:
                return None
        except (TypeError, ValueError):
            return None
        findings: list[ValidationFinding] = []
        for item in payload["findings"]:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"code", "severity", "section_id", "entity_id", "message"}
                or any(not isinstance(value, str) for value in item.values())
            ):
                return None
            try:
                severity = FindingSeverity(str(item.get("severity") or ""))
            except ValueError:
                return None
            code = str(item.get("code") or "").strip()
            message = str(item.get("message") or "").strip()
            section_id = str(item.get("section_id") or "").strip()
            entity_id = str(item.get("entity_id") or "").strip()
            if (
                not code.startswith("SRS-")
                or len(code) > 128
                or not message
                or len(message) > _MAX_FINDING_MESSAGE_CHARS
                or section_id not in anchors
                or (entity_id and entity_id not in entity_ids.get(section_id, set()))
            ):
                return None
            findings.append(
                ValidationFinding(
                    code=code,
                    severity=severity,
                    message=message,
                    anchor=anchors[section_id],
                    entity_id=entity_id,
                )
            )
        return tuple(findings)

    def _audit(
        self,
        structural_audit: StructuralValidationAudit,
        findings: list[ValidationFinding],
        *,
        model: str,
        terminal_reason: str,
        input_truncated: bool,
        usage: Mapping[str, int | None],
    ) -> SemanticValidationAudit:
        if any(item.severity == FindingSeverity.ERROR for item in findings):
            disposition = ValidationDisposition.REJECTED
        elif any(item.severity == FindingSeverity.WARNING for item in findings):
            disposition = ValidationDisposition.NEEDS_REVIEW
        else:
            disposition = ValidationDisposition.ACCEPTED
        return SemanticValidationAudit(
            structural_audit=structural_audit,
            disposition=disposition,
            findings=tuple(findings),
            model=model,
            terminal_reason=terminal_reason,
            prompt_version=self._policy.prompt_version,
            input_truncated=input_truncated,
            usage=dict(usage),
        )

    @staticmethod
    def _document_anchor(audit: StructuralValidationAudit) -> SourceAnchor:
        return SourceAnchor(
            source_path=audit.source_path,
            line_start=1,
            line_end=max(1, max((section.anchor.line_end for section in audit.sections), default=1)),
            label="document",
        )
