"""Accepted SRS baseline import without document-driven lifecycle authority."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from flow_of_work_mcp.application.lifecycle_control import LifecycleControlService
from flow_of_work_mcp.application.srs_validation import SrsValidationService
from flow_of_work_mcp.core.domain import (
    BaselineImportPlan,
    ImportedRequirement,
    ImportedSequence,
    ImportedUseCase,
    RequirementDraft,
    SequenceDraft,
    SourceAnchor,
    UseCaseDraft,
    ValidationAuditRecord,
    ValidationDisposition,
)
from flow_of_work_mcp.core.domain.srs import ParsedSection, StructuralValidationAudit
from flow_of_work_mcp.core.ports import BaselineImportRepository


_REQUIREMENT_RE = re.compile(
    r"^\s*[-*]\s+(?P<source_id>(?:FR|NFR)-[A-Za-z0-9][A-Za-z0-9_-]*)\s+(?P<statement>\S.*)$"
)
_USE_CASE_HEADING_RE = re.compile(
    r"^(?P<source_id>UC-[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?:[-:]\s*(?P<title>.+))?$",
    re.IGNORECASE,
)
_SEQUENCE_HEADING_RE = re.compile(
    r"^(?P<source_id>SQ-[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?:[-:]\s*(?P<title>.+))?$",
    re.IGNORECASE,
)


class BaselineImportShapeError(ValueError):
    """The accepted document lacks fields needed for canonical behavior state."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BaselineImportService:
    """Validate, shape-check and atomically import an initial SRS baseline."""

    structural_validation: SrsValidationService
    repository: BaselineImportRepository
    lifecycle: LifecycleControlService

    def import_srs(
        self,
        project_id: str,
        *,
        source_path: str,
        standard_profile: str,
        actor: str,
        request_id: str = "",
    ) -> Mapping[str, object]:
        structural = self.structural_validation.validate(
            source_path,
            standard_profile=standard_profile,
        )
        audit = structural
        audit_request_id = f"{request_id}:baseline-validation" if request_id else ""
        if audit.disposition != ValidationDisposition.ACCEPTED:
            record = self._record_validation(
                project_id,
                source_path=source_path,
                profile_id=standard_profile,
                disposition=audit.disposition,
                finding_codes=tuple(item.code for item in audit.findings),
                actor=actor,
                request_id=audit_request_id,
            )
            return {
                "imported": False,
                "disposition": audit.disposition.value,
                "reason": "validation_not_accepted",
                "validation_audit_id": record.audit_id or 0,
                "audit": audit.to_dict(),
            }

        try:
            plan = self._plan_from_structural(project_id, structural)
        except BaselineImportShapeError as exc:
            record = self._record_validation(
                project_id,
                source_path=source_path,
                profile_id=standard_profile,
                disposition=ValidationDisposition.NEEDS_REVIEW,
                finding_codes=tuple(
                    sorted({*(item.code for item in audit.findings), exc.code})
                ),
                actor=actor,
                request_id=audit_request_id,
            )
            return {
                "imported": False,
                "disposition": ValidationDisposition.NEEDS_REVIEW.value,
                "reason": exc.code,
                "validation_audit_id": record.audit_id or 0,
                "audit": audit.to_dict(),
            }

        record = self._record_validation(
            project_id,
            source_path=source_path,
            profile_id=standard_profile,
            disposition=ValidationDisposition.ACCEPTED,
            finding_codes=tuple(sorted({item.code for item in audit.findings})),
            actor=actor,
            request_id=audit_request_id,
        )
        baseline = self.repository.import_baseline(
            plan,
            actor=actor,
            request_id=request_id,
        )
        return {
            "imported": True,
            "disposition": ValidationDisposition.ACCEPTED.value,
            "validation_audit_id": record.audit_id or 0,
            "audit": audit.to_dict(),
            "baseline": dict(baseline),
        }

    def revise_srs(
        self,
        project_id: str,
        *,
        previous_baseline_id: str,
        source_path: str,
        standard_profile: str,
        actor: str,
        governed_approval_reference: str = "",
        request_id: str = "",
    ) -> Mapping[str, object]:
        """Validate and classify one successor baseline before any mutation."""

        structural = self.structural_validation.validate(
            source_path,
            standard_profile=standard_profile,
        )
        audit = structural
        audit_request_id = f"{request_id}:baseline-revision-validation" if request_id else ""
        if audit.disposition != ValidationDisposition.ACCEPTED:
            record = self._record_validation(
                project_id,
                source_path=source_path,
                profile_id=standard_profile,
                disposition=audit.disposition,
                finding_codes=tuple(item.code for item in audit.findings),
                actor=actor,
                request_id=audit_request_id,
            )
            return {
                "revised": False,
                "disposition": audit.disposition.value,
                "reason": "validation_not_accepted",
                "validation_audit_id": record.audit_id or 0,
                "audit": audit.to_dict(),
            }
        try:
            plan = self._plan_from_structural(project_id, structural)
        except BaselineImportShapeError as exc:
            record = self._record_validation(
                project_id,
                source_path=source_path,
                profile_id=standard_profile,
                disposition=ValidationDisposition.NEEDS_REVIEW,
                finding_codes=tuple(sorted({*(item.code for item in audit.findings), exc.code})),
                actor=actor,
                request_id=audit_request_id,
            )
            return {
                "revised": False,
                "disposition": ValidationDisposition.NEEDS_REVIEW.value,
                "reason": exc.code,
                "validation_audit_id": record.audit_id or 0,
                "audit": audit.to_dict(),
            }

        record = self._record_validation(
            project_id,
            source_path=source_path,
            profile_id=standard_profile,
            disposition=ValidationDisposition.ACCEPTED,
            finding_codes=tuple(sorted({item.code for item in audit.findings})),
            actor=actor,
            request_id=audit_request_id,
        )
        revision = self.repository.revise_baseline(
            plan,
            previous_baseline_id=previous_baseline_id,
            actor=actor,
            governed_approval_reference=governed_approval_reference,
            request_id=request_id,
        )
        return {
            **dict(revision),
            "validation_audit_id": record.audit_id or 0,
            "audit": audit.to_dict(),
        }

    def _record_validation(
        self,
        project_id: str,
        *,
        source_path: str,
        profile_id: str,
        disposition: ValidationDisposition,
        finding_codes: tuple[str, ...],
        actor: str,
        request_id: str,
    ) -> ValidationAuditRecord:
        return self.lifecycle.record_validation(
            project_id,
            ValidationAuditRecord(
                source_ref=source_path,
                disposition=disposition,
                finding_codes=finding_codes,
                profile_id=profile_id,
            ),
            actor=actor,
            request_id=request_id,
        )

    def _plan_from_structural(
        self,
        project_id: str,
        audit: StructuralValidationAudit,
    ) -> BaselineImportPlan:
        sections = tuple(audit.sections)
        requirements = tuple(self._requirements_from_sections(sections))
        use_cases = tuple(self._use_cases_from_sections(sections))
        sequences = tuple(self._sequences_from_sections(sections))
        if not requirements:
            raise BaselineImportShapeError("baseline_requirements_unparseable")
        if not use_cases or not sequences:
            raise BaselineImportShapeError("baseline_behavior_shape_incomplete")
        known_use_cases = {item.source_id for item in use_cases}
        if any(
            item.related_use_case_source_id
            and item.related_use_case_source_id not in known_use_cases
            for item in sequences
        ):
            raise BaselineImportShapeError("baseline_sequence_use_case_reference_invalid")
        return BaselineImportPlan(
            project_id=project_id,
            source_path=audit.source_path,
            content_sha256=audit.content_sha256,
            profile_id=audit.profile_id,
            profile_version=audit.profile_version,
            requirements=requirements,
            use_cases=use_cases,
            sequences=sequences,
        )

    @staticmethod
    def _requirements_from_sections(
        sections: tuple[ParsedSection, ...]):
        by_heading = {section.normalized_heading: section for section in sections}
        for heading, category, expected_prefix in (
            ("functional requirements", "functional", "FR-"),
            ("non-functional requirements", "non_functional", "NFR-"),
        ):
            section = by_heading.get(heading)
            if section is None:
                continue
            for offset, line in enumerate(section.body.splitlines(), start=section.anchor.line_start + 1):
                match = _REQUIREMENT_RE.match(line)
                if match is None:
                    continue
                source_id = match.group("source_id").upper()
                if not source_id.startswith(expected_prefix):
                    raise BaselineImportShapeError("baseline_requirement_category_mismatch")
                yield ImportedRequirement(
                    source_id=source_id,
                    draft=RequirementDraft(
                        title=source_id,
                        statement=match.group("statement").strip(),
                        category=category,
                        rationale="Imported from an accepted SRS baseline.",
                        source_anchor=(
                            f"{section.anchor.source_path}:{offset}-{offset}"
                        ),
                    ),
                    source_anchor=SourceAnchor(
                        source_path=section.anchor.source_path,
                        line_start=offset,
                        line_end=offset,
                        label=source_id,
                    ),
                )

    @staticmethod
    def _use_cases_from_sections(sections: tuple[ParsedSection, ...]):
        for section in sections:
            match = _USE_CASE_HEADING_RE.fullmatch(section.heading.strip())
            if match is None:
                continue
            source_id = match.group("source_id").upper()
            title = (match.group("title") or "").strip()
            if not title:
                raise BaselineImportShapeError("baseline_use_case_title_missing")
            actor = BaselineImportService._required_field(section, "Actor")
            objective = BaselineImportService._required_field(section, "Objective")
            outcome = BaselineImportService._required_field(
                section, "Observable Outcome", "Outcome"
            )
            yield ImportedUseCase(
                source_id=source_id,
                draft=UseCaseDraft(
                    title=title,
                    actor=actor,
                    objective=objective,
                    observable_outcome=outcome,
                    preconditions=BaselineImportService._optional_list(section, "Preconditions"),
                    postconditions=BaselineImportService._optional_list(section, "Postconditions"),
                    invariants=BaselineImportService._optional_list(section, "Invariants"),
                    source_anchor=section.anchor,
                ),
            )

    @staticmethod
    def _sequences_from_sections(sections: tuple[ParsedSection, ...]):
        for section in sections:
            match = _SEQUENCE_HEADING_RE.fullmatch(section.heading.strip())
            if match is None:
                continue
            source_id = match.group("source_id").upper()
            title = (match.group("title") or "").strip()
            if not title:
                raise BaselineImportShapeError("baseline_sequence_title_missing")
            yield ImportedSequence(
                source_id=source_id,
                draft=SequenceDraft(
                    title=title,
                    participants=BaselineImportService._required_list(section, "Participants"),
                    normal_steps=BaselineImportService._required_list(
                        section, "Normal Steps", "Normal"
                    ),
                    expected_effects=BaselineImportService._required_list(
                        section, "Expected Effects", "Expected"
                    ),
                    alternate_steps=BaselineImportService._optional_list(
                        section, "Alternate Steps", "Alternate"
                    ),
                    failure_steps=BaselineImportService._optional_list(
                        section, "Failure Steps", "Failure"
                    ),
                    source_anchor=section.anchor,
                ),
                related_use_case_source_id=BaselineImportService._optional_field(
                    section, "Use Case"
                ).upper(),
            )

    @staticmethod
    def _required_field(section: ParsedSection, *labels: str) -> str:
        value = BaselineImportService._optional_field(section, *labels)
        if not value:
            raise BaselineImportShapeError("baseline_behavior_shape_incomplete")
        return value

    @staticmethod
    def _required_list(section: ParsedSection, *labels: str) -> tuple[str, ...]:
        value = BaselineImportService._optional_list(section, *labels)
        if not value:
            raise BaselineImportShapeError("baseline_behavior_shape_incomplete")
        return value

    @staticmethod
    def _optional_list(section: ParsedSection, *labels: str) -> tuple[str, ...]:
        value = BaselineImportService._optional_field(section, *labels)
        if not value:
            return ()
        return tuple(item.strip() for item in re.split(r"[;|]", value) if item.strip())

    @staticmethod
    def _optional_field(section: ParsedSection, *labels: str) -> str:
        allowed = {label.casefold() for label in labels}
        for raw_line in section.body.splitlines():
            line = raw_line.strip().lstrip("-* ").replace("**", "")
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            if label.strip().casefold() in allowed:
                return value.strip()
        return ""
