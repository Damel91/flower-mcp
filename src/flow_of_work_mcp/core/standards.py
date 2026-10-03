"""Built-in SRS standard profiles and deterministic registry."""
from __future__ import annotations

from flow_of_work_mcp.core.domain.srs import SectionRule, SrsStandardProfile


FLOW_OF_WORK_SRS_MARKDOWN_V1 = SrsStandardProfile(
    profile_id="fow-srs-markdown-v1",
    version="1.0",
    required_sections=(
        SectionRule("scope", "Scope", min_body_chars=20),
        SectionRule(
            "functional_requirements",
            "Functional Requirements",
            identifier_prefixes=("FR-",),
            min_identifiers=1,
        ),
        SectionRule(
            "non_functional_requirements",
            "Non-Functional Requirements",
            identifier_prefixes=("NFR-",),
            min_identifiers=1,
        ),
        SectionRule("use_cases", "Use Cases", identifier_prefixes=("UC-",), min_identifiers=1),
        SectionRule("sequences", "Sequences", identifier_prefixes=("SQ-",), min_identifiers=1),
        SectionRule(
            "acceptance_criteria",
            "Acceptance Criteria",
            identifier_prefixes=("AC-",),
            min_identifiers=1,
        ),
    ),
    generated_artifacts=(
        "srs",
        "requirements_catalogue",
        "use_case_specification",
        "sequence_specification",
        "traceability_matrix",
        "milestone_audit",
        "phase_audit",
    ),
)


class StandardProfileRegistry:
    """Explicit profile lookup; clients never select a standard by prose."""

    def __init__(self, profiles: tuple[SrsStandardProfile, ...] | None = None) -> None:
        profiles = profiles or (FLOW_OF_WORK_SRS_MARKDOWN_V1,)
        self._profiles = {profile.profile_id: profile for profile in profiles}
        if len(self._profiles) != len(profiles):
            raise ValueError("standard profile IDs must be unique")

    def get(self, profile_id: str) -> SrsStandardProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown standard profile: {profile_id}") from exc

    def list_profiles(self) -> tuple[SrsStandardProfile, ...]:
        return tuple(self._profiles.values())
