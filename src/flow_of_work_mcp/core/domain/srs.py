"""Value objects for an imported SRS and its deterministic validation audit."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from flow_of_work_mcp.core.domain.identifiers import required_text


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


def normalize_heading(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


@dataclass(frozen=True)
class SourceAnchor:
    source_path: str
    line_start: int
    line_end: int
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", required_text(self.source_path, "source_path"))
        if self.line_start <= 0 or self.line_end < self.line_start:
            raise ValueError("source anchor lines must be positive and ordered")


@dataclass(frozen=True)
class ParsedSection:
    heading: str
    level: int
    body: str
    anchor: SourceAnchor

    @property
    def normalized_heading(self) -> str:
        return normalize_heading(self.heading)


@dataclass(frozen=True)
class ParsedSrs:
    source_path: str
    content_sha256: str
    line_count: int
    sections: tuple[ParsedSection, ...]


@dataclass(frozen=True)
class SectionRule:
    section_id: str
    heading: str
    required: bool = True
    min_body_chars: int = 1
    identifier_prefixes: tuple[str, ...] = ()
    min_identifiers: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", required_text(self.section_id, "section_id"))
        object.__setattr__(self, "heading", required_text(self.heading, "heading"))
        if self.min_body_chars < 0 or self.min_identifiers < 0:
            raise ValueError("section minima cannot be negative")

    @property
    def normalized_heading(self) -> str:
        return normalize_heading(self.heading)


@dataclass(frozen=True)
class SrsStandardProfile:
    profile_id: str
    version: str
    required_sections: tuple[SectionRule, ...]
    generated_artifacts: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", required_text(self.profile_id, "profile_id"))
        object.__setattr__(self, "version", required_text(self.version, "version"))
        if not self.required_sections:
            raise ValueError("standard profile requires at least one section rule")
        ids = [rule.section_id for rule in self.required_sections]
        if len(ids) != len(set(ids)):
            raise ValueError("standard profile section IDs must be unique")


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    severity: FindingSeverity
    message: str
    anchor: SourceAnchor | None = None
    entity_id: str = ""


def finding_to_dict(finding: ValidationFinding) -> Mapping[str, object]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "message": finding.message,
        "entity_id": finding.entity_id,
        "anchor": (
            {
                "source_path": finding.anchor.source_path,
                "line_start": finding.anchor.line_start,
                "line_end": finding.anchor.line_end,
                "label": finding.anchor.label,
            }
            if finding.anchor
            else None
        ),
    }


@dataclass(frozen=True)
class StructuralValidationAudit:
    profile_id: str
    profile_version: str
    source_path: str
    content_sha256: str
    disposition: ValidationDisposition
    findings: tuple[ValidationFinding, ...] = field(default_factory=tuple)
    sections: tuple[ParsedSection, ...] = field(default_factory=tuple)

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == FindingSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == FindingSeverity.WARNING)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "stage": "structural",
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "source_path": self.source_path,
            "content_sha256": self.content_sha256,
            "disposition": self.disposition.value,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [
                finding_to_dict(finding)
                for finding in self.findings
            ],
        }


@dataclass(frozen=True)
class SemanticValidationAudit:
    """Combined structural and bounded semantic SRS validation result."""

    structural_audit: StructuralValidationAudit
    disposition: ValidationDisposition
    findings: tuple[ValidationFinding, ...]
    model: str = ""
    terminal_reason: str = ""
    prompt_version: str = ""
    input_truncated: bool = False
    usage: Mapping[str, int | None] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == FindingSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == FindingSeverity.WARNING)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "stage": "semantic",
            "profile_id": self.structural_audit.profile_id,
            "profile_version": self.structural_audit.profile_version,
            "source_path": self.structural_audit.source_path,
            "content_sha256": self.structural_audit.content_sha256,
            "disposition": self.disposition.value,
            "structural_disposition": self.structural_audit.disposition.value,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "model": self.model,
            "terminal_reason": self.terminal_reason,
            "prompt_version": self.prompt_version,
            "input_truncated": self.input_truncated,
            "usage": dict(self.usage),
            "findings": [finding_to_dict(finding) for finding in self.findings],
        }
