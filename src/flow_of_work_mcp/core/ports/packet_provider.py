"""Provider-neutral port for one durable technical packet surface."""
from __future__ import annotations

from typing import Mapping, Protocol

from flow_of_work_mcp.core.domain.packet_provider import (
    PacketProviderCommand,
    PacketProviderReceipt,
)


class PacketProvider(Protocol):
    @property
    def kind(self) -> str: ...

    def session_for_project(self, project_id: str) -> str: ...

    def execute(self, command: PacketProviderCommand) -> PacketProviderReceipt: ...

    def execute_bound(self, command: PacketProviderCommand, *, binding_identity: Mapping[str, object]) -> PacketProviderReceipt:
        """Dispatch v3 on the immutable route captured by Flower admission."""
        ...

    def validation_capabilities(self, project_id: str) -> Mapping[str, object]: ...

    def binding_identity(self, project_id: str) -> Mapping[str, object]: ...


__all__ = ["PacketProvider"]
