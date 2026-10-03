"""Value objects for durable capability-lens selection."""
from __future__ import annotations

from dataclasses import dataclass

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id


@dataclass(frozen=True)
class CapabilityLensBinding:
    interaction_session_ref: str
    project_id: str
    project_context_revision: int
    producing_provider: str
    selected_area: str
    revision: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interaction_session_ref",
            required_text(self.interaction_session_ref, "interaction_session_ref"),
        )
        object.__setattr__(self, "project_id", validate_project_id(self.project_id))
        for field_name in ("project_context_revision", "revision"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        object.__setattr__(
            self,
            "producing_provider",
            required_text(self.producing_provider, "producing_provider"),
        )
        object.__setattr__(
            self, "selected_area", required_text(self.selected_area, "selected_area")
        )


__all__ = ["CapabilityLensBinding"]
