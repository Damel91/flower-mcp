"""Provider-neutral read-only technical interaction discovery boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class TechnicalInteractionSnapshot:
    contract: str
    provider: str
    provider_context_id: str
    project_context: Mapping[str, object]
    areas: tuple[Mapping[str, object], ...]
    availability: str = "available"


class InteractionProvider(Protocol):
    @property
    def kind(self) -> str: ...

    def discover(
        self,
        provider_context_id: str,
        *,
        interaction_session_ref: str,
    ) -> TechnicalInteractionSnapshot: ...


__all__ = ["InteractionProvider", "TechnicalInteractionSnapshot"]
