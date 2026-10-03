"""Provider-neutral port for one durable technical packet surface."""
from __future__ import annotations

from typing import Protocol

from flow_of_work_mcp.core.domain.packet_provider import (
    PacketProviderCommand,
    PacketProviderReceipt,
)


class PacketProvider(Protocol):
    @property
    def kind(self) -> str: ...

    def session_for_project(self, project_id: str) -> str: ...

    def execute(self, command: PacketProviderCommand) -> PacketProviderReceipt: ...


__all__ = ["PacketProvider"]
