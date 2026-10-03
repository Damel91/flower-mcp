"""Deterministic structural SRS validation against an explicit standard profile."""
from __future__ import annotations

import re
from pathlib import Path

from flow_of_work_mcp.core.domain.srs import (
    FindingSeverity,
    ParsedSection,
    SectionRule,
    SourceAnchor,
    StructuralValidationAudit,
    ValidationDisposition,
    ValidationFinding,
)
from flow_of_work_mcp.core.ports.srs_document import SrsDocumentParser
from flow_of_work_mcp.core.standards import StandardProfileRegistry


class SrsValidationService:
    """Validates form and identifiers; semantic review is a later LLM slice."""

    def __init__(self, parser: SrsDocumentParser, profiles: StandardProfileRegistry) -> None:
        self._parser = parser
        self._profiles = profiles

    def validate(self, source_path: str | Path, *, standard_profile: str) -> StructuralValidationAudit:
        profile = self._profiles.get(standard_profile)
        parsed = self._parser.parse(source_path)
        document_anchor = SourceAnchor(
            source_path=parsed.source_path,
            line_start=1,
            line_end=max(1, parsed.line_count),
            label="document",
        )
        findings: list[ValidationFinding] = []
        sections_by_heading: dict[str, list[ParsedSection]] = {}
        for section in parsed.sections:
            sections_by_heading.setdefault(section.normalized_heading, []).append(section)

        if not parsed.sections:
            findings.append(
                ValidationFinding(
                    code="SRS-HEADINGS-MISSING",
                    severity=FindingSeverity.ERROR,
                    message="document contains no parseable Markdown headings",
                    anchor=document_anchor,
                )
            )

        identifiers: dict[str, SourceAnchor] = {}
        for rule in profile.required_sections:
            findings.extend(
                self._validate_section(
                    rule,
                    sections_by_heading.get(rule.normalized_heading, []),
                    identifiers,
                    document_anchor,
                )
            )

        disposition = (
            ValidationDisposition.REJECTED
            if any(item.severity == FindingSeverity.ERROR for item in findings)
            else ValidationDisposition.ACCEPTED
        )
        return StructuralValidationAudit(
            profile_id=profile.profile_id,
            profile_version=profile.version,
            source_path=parsed.source_path,
            content_sha256=parsed.content_sha256,
            disposition=disposition,
            findings=tuple(findings),
            sections=parsed.sections,
        )

    @staticmethod
    def _validate_section(
        rule: SectionRule,
        matches: list[ParsedSection],
        identifiers: dict[str, SourceAnchor],
        document_anchor: SourceAnchor,
    ) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        if not matches:
            if rule.required:
                findings.append(
                    ValidationFinding(
                        code="SRS-SECTION-MISSING",
                        severity=FindingSeverity.ERROR,
                        message=f"missing required section '{rule.heading}'",
                        anchor=document_anchor,
                        entity_id=rule.section_id,
                    )
                )
            return findings
        if len(matches) > 1:
            for section in matches[1:]:
                findings.append(
                    ValidationFinding(
                        code="SRS-SECTION-DUPLICATE",
                        severity=FindingSeverity.ERROR,
                        message=f"duplicate required section '{rule.heading}'",
                        anchor=section.anchor,
                        entity_id=rule.section_id,
                    )
                )
        section = matches[0]
        if len(section.body.strip()) < rule.min_body_chars:
            findings.append(
                ValidationFinding(
                    code="SRS-SECTION-EMPTY",
                    severity=FindingSeverity.ERROR,
                    message=f"section '{rule.heading}' has insufficient body content",
                    anchor=section.anchor,
                    entity_id=rule.section_id,
                )
            )
        found = []
        for prefix in rule.identifier_prefixes:
            found.extend(re.findall(rf"\b{re.escape(prefix)}[A-Za-z0-9][A-Za-z0-9_-]*\b", section.body))
        for identifier in found:
            if identifier in identifiers:
                findings.append(
                    ValidationFinding(
                        code="SRS-IDENTIFIER-DUPLICATE",
                        severity=FindingSeverity.ERROR,
                        message=f"duplicate identifier '{identifier}'",
                        anchor=section.anchor,
                        entity_id=identifier,
                    )
                )
            else:
                identifiers[identifier] = section.anchor
        if len(found) < rule.min_identifiers:
            findings.append(
                ValidationFinding(
                    code="SRS-IDENTIFIER-MISSING",
                    severity=FindingSeverity.ERROR,
                    message=(
                        f"section '{rule.heading}' requires at least "
                        f"{rule.min_identifiers} identifier(s) with prefixes "
                        f"{', '.join(rule.identifier_prefixes)}"
                    ),
                    anchor=section.anchor,
                    entity_id=rule.section_id,
                )
            )
        return findings
