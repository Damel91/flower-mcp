"""Provider-neutral model gateway test double."""
from __future__ import annotations

from collections.abc import Callable

from flow_of_work_mcp.core.ports.model_gateway import ModelRequest, ModelResult


class CallableModelGateway:
    def __init__(self, invoke: Callable[[ModelRequest], ModelResult]) -> None:
        self._invoke = invoke

    def invoke(self, request: ModelRequest) -> ModelResult:
        return self._invoke(request)
