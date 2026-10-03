"""Flow's provider-neutral bridge to the external LM Studio runtime library."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from lmstudio_agent_runtime import (
    AdapterProfile,
    LLMAdapter,
    LLMBackendError,
    LLMRunawayError,
    LLMTimeoutError,
    build_adapter,
)

from flow_of_work_mcp.core.errors import (
    ModelBackendError,
    ModelIdleTimeoutError,
    ModelRunawayError,
)
from flow_of_work_mcp.core.ports.model_gateway import ModelRequest, ModelResult


@dataclass(frozen=True)
class LMStudioRuntimeGatewayConfig:
    """Consumer-owned mapping inputs; no transport policy lives here."""

    model: str
    base_url: str = "http://127.0.0.1:1234"
    context_length: int | None = None
    auto_load: bool = True
    stream_idle_timeout_sec: float = 30.0
    api_key_env: str | None = None
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if not str(self.model or "").strip():
            raise ValueError("model must be a non-empty string")
        if not str(self.base_url or "").strip():
            raise ValueError("base_url must be a non-empty string")
        if self.context_length is not None and self.context_length <= 0:
            raise ValueError("context_length must be positive when configured")
        if self.stream_idle_timeout_sec <= 0:
            raise ValueError("stream_idle_timeout_sec must be positive")


class LMStudioRuntimeModelGateway:
    """Translate Flow requests at the sole allowed runtime-library boundary."""

    def __init__(
        self,
        config: LMStudioRuntimeGatewayConfig,
        *,
        adapter_builder: Callable[[AdapterProfile], LLMAdapter] = build_adapter,
    ) -> None:
        self._config = config
        self._adapter_builder = adapter_builder
        # Validate the library-owned physical/logical profile during runtime
        # composition, before Flow opens its ledger or contacts the backend.
        self._profile("flow_runtime_validation")

    def invoke(self, request: ModelRequest) -> ModelResult:
        profile = self._profile(request.role_id)
        adapter = self._adapter_builder(profile)
        output_format = "json" if request.output_schema is not None else "text"
        try:
            result = adapter.invoke_with_ctx(
                list(request.messages),
                num_ctx=self._config.context_length,
                num_predict=request.max_output_tokens,
                output_format=output_format,
                timeout=self._config.stream_idle_timeout_sec,
            )
        except LLMTimeoutError as exc:
            raise ModelIdleTimeoutError(str(exc)) from exc
        except LLMRunawayError as exc:
            diagnostics = exc.diagnostics if isinstance(exc.diagnostics, Mapping) else None
            raise ModelRunawayError(str(exc), diagnostics=diagnostics) from exc
        except LLMBackendError as exc:
            raise ModelBackendError(str(exc)) from exc

        return ModelResult(
            text=result.text,
            structured_output=self._structured_output(
                result.text,
                request.output_schema,
            ),
            model=result.model or self._config.model,
            terminal_reason=result.terminal_reason or "completed",
            reasoning_text=result.reasoning_text,
            usage=self._usage(result.usage),
        )

    def _profile(self, role_id: str) -> AdapterProfile:
        return AdapterProfile.from_config(
            role_id,
            {
                "adapter_type": "llm",
                "backend": "lmstudio",
                "model": self._config.model,
                "base_url": self._config.base_url,
                "model_context_length": self._config.context_length,
                "context_ceiling": self._config.context_length,
                "lmstudio_auto_load": self._config.auto_load,
                "stream_idle_timeout_sec": self._config.stream_idle_timeout_sec,
                "sdk_idle_timeout_sec": self._config.stream_idle_timeout_sec,
                "api_key_env": self._config.api_key_env,
                "temperature": self._config.temperature,
            },
            {},
        )

    @staticmethod
    def _structured_output(
        text: str,
        output_schema: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        if output_schema is None:
            return None
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return None
        return dict(decoded) if isinstance(decoded, Mapping) else None

    @staticmethod
    def _usage(usage: Any) -> Mapping[str, int | None]:
        if usage is None:
            return {}
        return {
            key: getattr(usage, key, None)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "reasoning_tokens",
                "visible_output_tokens",
            )
        }
