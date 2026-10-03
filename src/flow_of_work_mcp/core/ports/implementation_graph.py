"""Provider boundary for a repository implementation graph."""
from __future__ import annotations

from typing import Protocol

from flow_of_work_mcp.core.domain.grounding import (
    ImplementationGraphSnapshot,
    ImplementationSnapshotRequest,
)


class ImplementationGraphProvider(Protocol):
    """Return a versioned, project-scoped snapshot for a closed goal scope."""

    def snapshot(self, request: ImplementationSnapshotRequest) -> ImplementationGraphSnapshot:
        """Supply implementation identities, relationships and evidence anchors."""
