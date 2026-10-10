"""Provider-neutral, bounded model-invocation port.

An external adapter implements this port. No domain or application service may
import an HTTP SDK, a local runtime or a provider-specific package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ModelRequest:
    role_id: str
    messages: tuple[Mapping[str, str], ...]
    output_schema: Mapping[str, Any] | None = None
    max_output_tokens: int | None = None
    request_id: str = ""


@dataclass(frozen=True)
class ModelResult:
    text: str
    structured_output: Mapping[str, Any] | None
    model: str
    terminal_reason: str
    reasoning_text: str = ""
    usage: Mapping[str, int | None] = field(default_factory=dict)
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    usage_derived_fields: tuple[str, ...] = ()
    transport: Mapping[str, object] = field(default_factory=dict)


class ModelGateway(Protocol):
    def invoke(
        self, request: ModelRequest, *,
        cancellation_probe: Callable[[], bool] | None = None,
        thinking_diagnostics: Mapping[str, object] | None = None,
        thinking_sink: Callable[[object], None] | None = None,
    ) -> ModelResult:
        """Run one bounded role invocation or raise a typed adapter error."""
