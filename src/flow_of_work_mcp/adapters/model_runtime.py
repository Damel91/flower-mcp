"""Flow's sole optional inference bridge to runtime-llama."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from threading import Condition
from typing import Any

from runtime_llama import (
    AdapterProfile,
    LLMAdapter,
    LLMBackendError,
    LLMCancelledError,
    LLMRunawayError,
    LLMTimeoutError,
    LLMTransportAttempt,
    ThinkingDiagnosticsConfig,
    build_adapter,
)

from flow_of_work_mcp.core.errors import (
    ModelBackendError,
    ModelCancelledError,
    ModelIdleTimeoutError,
    ModelRunawayError,
)
from flow_of_work_mcp.core.ports.model_gateway import ModelRequest, ModelResult


@dataclass(frozen=True)
class RuntimeLlamaGatewayConfig:
    """Consumer-owned limits; processes and model loading remain server-owned."""

    model: str
    base_url: str = "http://127.0.0.1:8080"
    context_length: int | None = None
    stream_idle_timeout_sec: float = 30.0
    api_key_env: str | None = None
    temperature: float = 0.1
    verify_ssl: bool = True
    reasoning: str = "auto"


class RuntimeLlamaModelGateway:
    """Reuse immutable role adapters and own their complete bounded lifetime."""

    def __init__(
        self,
        config: RuntimeLlamaGatewayConfig,
        *,
        adapter_builder: Callable[[AdapterProfile], LLMAdapter] = build_adapter,
    ) -> None:
        self._config = config
        self._adapter_builder = adapter_builder
        self._condition = Condition()
        self._adapters: dict[str, LLMAdapter] = {}
        self._active_calls = 0
        self._closing = False
        self._closed = False
        self._close_running = False
        # Validate without creating an HTTP client or contacting a model, before
        # the factory opens the ledger. The library owns profile validation.
        self._profile("flow_runtime_validation")

    def invoke(
        self,
        request: ModelRequest,
        *,
        cancellation_probe: Callable[[], bool] | None = None,
        thinking_diagnostics: Mapping[str, object] | None = None,
        thinking_sink: Callable[[object], None] | None = None,
    ) -> ModelResult:
        # Transient options never enter the serialized role request or durable
        # semantic result. Thinking capture is disabled by default.
        options: dict[str, Any] = {"cancellation_probe": cancellation_probe}
        if thinking_diagnostics is not None:
            diagnostic = ThinkingDiagnosticsConfig.from_value({"max_chars": 4096, **dict(thinking_diagnostics)})
            if diagnostic.max_chars > 4096:
                raise ValueError("thinking diagnostics max_chars must be in 1..4096")
            options["thinking_diagnostics"] = diagnostic
        if thinking_sink is not None:
            options["thinking_sink"] = thinking_sink
        admitted = False
        try:
            with self._condition:
                if self._closing:
                    raise ModelBackendError("model_gateway_closed")
                adapter = self._adapters.get(request.role_id)
                if adapter is None:
                    adapter = self._adapter_builder(self._profile(request.role_id))
                    self._adapters[request.role_id] = adapter
                self._active_calls += 1
                admitted = True
            result = adapter.invoke_with_ctx(
                list(request.messages),
                num_ctx=self._config.context_length,
                num_predict=request.max_output_tokens,
                output_format="json" if request.output_schema is not None else "text",
                timeout=self._config.stream_idle_timeout_sec,
                **options,
            )
            return ModelResult(
                text=result.text,
                structured_output=self._structured_output(result.text, request.output_schema),
                model=result.model or self._config.model,
                terminal_reason=result.terminal_reason or "unknown",
                reasoning_text=result.reasoning_text,
                usage=self._usage(result.usage),
                tool_calls=tuple(dict(call) for call in result.tool_calls),
                usage_derived_fields=tuple(result.usage.derived_fields) if result.usage is not None else (),
                transport=self._transport(result.transport),
            )
        except LLMTimeoutError as exc:
            raise ModelIdleTimeoutError(str(exc), transport=self._transport(exc.diagnostics)) from exc
        except LLMCancelledError as exc:
            raise ModelCancelledError(str(exc), transport=self._transport(exc.diagnostics)) from exc
        except LLMRunawayError as exc:
            diagnostics = exc.diagnostics if isinstance(exc.diagnostics, Mapping) else None
            raise ModelRunawayError(str(exc), diagnostics=diagnostics) from exc
        except LLMBackendError as exc:
            raise ModelBackendError(str(exc), transport=self._transport(exc.diagnostics)) from exc
        finally:
            if admitted:
                with self._condition:
                    self._active_calls -= 1
                    self._condition.notify_all()

    def close(self) -> None:
        """Reject new calls, drain active ones, then close owned adapters.

        A failed close retains unclosed adapters for an explicit cleanup retry;
        it never reopens the gateway or reports a complete shutdown.
        """
        with self._condition:
            self._closing = True
            self._condition.notify_all()
            while self._close_running:
                self._condition.wait()
            if self._closed:
                return
            self._close_running = True
        try:
            with self._condition:
                while self._active_calls:
                    self._condition.wait()
                pending = tuple(self._adapters.items())
            for role_id, adapter in pending:
                adapter.close()
                with self._condition:
                    del self._adapters[role_id]
            with self._condition:
                self._closed = True
        finally:
            with self._condition:
                self._close_running = False
                self._condition.notify_all()

    def _profile(self, role_id: str) -> AdapterProfile:
        return AdapterProfile.from_config(
            role_id,
            {
                "adapter_type": "llm",
                "backend": "llamacpp",
                "model": self._config.model,
                "base_url": self._config.base_url,
                "model_context_length": self._config.context_length,
                "context_ceiling": self._config.context_length,
                "stream_idle_timeout_sec": self._config.stream_idle_timeout_sec,
                "api_key_env": self._config.api_key_env,
                "temperature": self._config.temperature,
                "verify_ssl": self._config.verify_ssl,
                "reasoning": self._config.reasoning,
            },
            {},
        )

    @staticmethod
    def _structured_output(
        text: str, output_schema: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        if output_schema is None:
            return None
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return None
        return dict(decoded) if isinstance(decoded, Mapping) else None

    @staticmethod
    def _transport(attempt: Any) -> Mapping[str, object]:
        # The upstream type is explicitly content-free and bounded; never copy
        # arbitrary exception strings, HTTP payloads or diagnostic thinking.
        return attempt.to_dict() if isinstance(attempt, LLMTransportAttempt) else {}

    @staticmethod
    def _usage(usage: Any) -> Mapping[str, int | None]:
        if usage is None:
            return {}
        return {
            key: getattr(usage, key, None)
            for key in (
                "prompt_tokens", "completion_tokens", "total_tokens",
                "reasoning_tokens", "visible_output_tokens",
            )
        }
