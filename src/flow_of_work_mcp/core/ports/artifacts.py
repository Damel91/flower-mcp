"""Persistence and versioning port for generated lifecycle artifacts."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.artifacts import ArtifactGeneration


class ArtifactRepository(Protocol):
    def packet_artifact_references(self, project_id: str, packet_id: str, *, limit: int = 10) -> list[Mapping[str, object]]: ...
    def record_artifact_generation(
        self,
        generation: ArtifactGeneration,
        *,
        actor: str,
        request_id: str = "",
    ) -> ArtifactGeneration: ...

    def artifact_generations(self, project_id: str) -> list[Mapping[str, object]]: ...


class LedgerVersionReader(Protocol):
    def ledger_version(self, project_id: str) -> int: ...
