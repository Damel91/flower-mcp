"""Provider-neutral port for campaign test materialization and evidence."""

from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.campaign_authority import (
    TestProviderCommand,
    TestProviderMaterializationMode,
    TestProviderReceipt,
)


class TestProvider(Protocol):
    @property
    def kind(self) -> str: ...

    def session_for_project(self, project_id: str) -> str: ...

    def supports_materialization_mode(
        self,
        mode: TestProviderMaterializationMode,
        capability: Mapping[str, object],
    ) -> bool: ...

    def resolve_materialization_capability(
        self,
        project_id: str,
        capability: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def execute(self, command: TestProviderCommand) -> TestProviderReceipt: ...


__all__ = ["TestProvider"]
