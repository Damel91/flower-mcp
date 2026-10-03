"""Explicit orchestrator-interaction to Flow Project Context binding."""
from __future__ import annotations

from dataclasses import dataclass

from flow_of_work_mcp.core.domain.identifiers import required_text, validate_project_id


@dataclass(frozen=True)
class ProjectContextBinding:
    interaction_session_ref: str
    project_id: str
    provider_context_id: str = ""
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interaction_session_ref",
            required_text(self.interaction_session_ref, "interaction_session_ref"),
        )
        object.__setattr__(self, "project_id", validate_project_id(self.project_id))
        provider = str(self.provider_context_id or "").strip()
        if len(provider) > 256:
            raise ValueError("provider_context_id exceeds the supported bound")
        object.__setattr__(self, "provider_context_id", provider)
        if isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("project context revision must be positive")


__all__ = ["ProjectContextBinding"]
