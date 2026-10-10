import json
from pathlib import Path

import pytest

pytest.importorskip("runtime_llama", reason="optional inference extra not installed")

from flow_of_work_mcp.adapters.model_runtime import (
    RuntimeLlamaGatewayConfig,
    RuntimeLlamaModelGateway,
)
from flow_of_work_mcp.core.errors import (
    ModelBackendError,
    ModelCancelledError,
    ModelIdleTimeoutError,
    ModelRunawayError,
)
from flow_of_work_mcp.core.ports.model_gateway import ModelRequest
from runtime_llama import (
    LLMBackendError,
    LLMCancelledError,
    LLMTransportAttempt,
    LLMCallResult,
    LLMRunawayError,
    LLMTimeoutError,
    LLMUsageStats,
)


class _Adapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.close_count = 0

    def invoke_with_ctx(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.error is not None:
            raise self.error
        return self.result

    def close(self):
        self.close_count += 1


def _request(*, role_id="intent_grounder", schema=True, cap=256):
    return ModelRequest(
        role_id=role_id,
        messages=(
            {"role": "system", "content": "Return a bounded result."},
            {"role": "user", "content": "Ground this intent."},
        ),
        output_schema={"type": "object"} if schema else None,
        max_output_tokens=cap,
        request_id="request-1",
    )


def test_bridge_maps_roles_to_one_physical_profile_and_projects_result():
    profiles = []
    adapters = []

    def build(profile):
        profiles.append(profile)
        adapter = _Adapter(
            LLMCallResult(
                text=json.dumps({"grounded": True}),
                usage=LLMUsageStats(
                    prompt_tokens=10,
                    completion_tokens=7,
                    total_tokens=17,
                    reasoning_tokens=2,
                    visible_output_tokens=5,
                    derived_fields=("visible_output_tokens",),
                ),
                role_id=profile.role_id,
                model=profile.model,
                reasoning_text="bounded reasoning",
                terminal_reason="completed",
            )
        )
        adapters.append(adapter)
        return adapter

    gateway = RuntimeLlamaModelGateway(
        RuntimeLlamaGatewayConfig(
            model="local-model",
            base_url="http://llama.test:8080",
            context_length=32768,
            stream_idle_timeout_sec=60,
        ),
        adapter_builder=build,
    )

    first = gateway.invoke(_request())
    second = gateway.invoke(_request(role_id="document_validator", cap=128))

    assert [profile.role_id for profile in profiles] == [
        "intent_grounder",
        "document_validator",
    ]
    assert profiles[0].model_config.physical_identity == profiles[1].model_config.physical_identity
    assert profiles[0].model_config.verify_ssl is True
    assert profiles[0].role.reasoning == "auto"
    assert profiles[0].role.context_ceiling == 32768
    assert profiles[0].generation.temperature == 0.1
    assert adapters[0].calls == [
        (
            [
                {"role": "system", "content": "Return a bounded result."},
                {"role": "user", "content": "Ground this intent."},
            ],
            {
                "num_ctx": 32768,
                "num_predict": 256,
                "output_format": "json",
                "timeout": 60,
                "cancellation_probe": None,
            },
        )
    ]
    assert first.structured_output == {"grounded": True}
    assert first.reasoning_text == "bounded reasoning"
    assert first.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 7,
        "total_tokens": 17,
        "reasoning_tokens": 2,
        "visible_output_tokens": 5,
    }
    assert first.usage_derived_fields == ("visible_output_tokens",)
    assert second.model == "local-model"
    gateway.close()
    assert [adapter.close_count for adapter in adapters] == [1, 1]


def test_bridge_returns_none_for_invalid_structured_output():
    gateway = RuntimeLlamaModelGateway(
        RuntimeLlamaGatewayConfig(model="local-model"),
        adapter_builder=lambda _profile: _Adapter(
            LLMCallResult(text="not-json", model="local-model")
        ),
    )
    assert gateway.invoke(_request()).structured_output is None


def test_bridge_rejects_invalid_physical_profile_at_composition():
    with pytest.raises(ValueError, match="credentials"):
        RuntimeLlamaModelGateway(
            RuntimeLlamaGatewayConfig(
                model="local-model",
                base_url="http://secret@llama.test:8080",
            )
        )


@pytest.mark.parametrize(
    ("runtime_error", "flow_error"),
    [
        (LLMBackendError("backend_failed"), ModelBackendError),
        (LLMTimeoutError("idle"), ModelIdleTimeoutError),
        (LLMCancelledError("cancel"), ModelCancelledError),
        (
            LLMRunawayError("loop", diagnostics={"repeat_count": 4}),
            ModelRunawayError,
        ),
    ],
)
def test_bridge_translates_runtime_errors(runtime_error, flow_error):
    gateway = RuntimeLlamaModelGateway(
        RuntimeLlamaGatewayConfig(model="local-model"),
        adapter_builder=lambda _profile: _Adapter(error=runtime_error),
    )
    with pytest.raises(flow_error) as caught:
        gateway.invoke(_request())
    assert caught.value.__cause__ is runtime_error
    if isinstance(caught.value, ModelRunawayError):
        assert caught.value.diagnostics == {"repeat_count": 4}


def test_runtime_library_is_the_only_model_transport_authority():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src" / "flow_of_work_mcp"
    runtime_importers = []
    forbidden = ("requests.post", "requests.get", "RunawayDetector")
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        import ast
        tree = ast.parse(text)
        if any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('runtime_llama')
               or isinstance(node, ast.Import) and any(alias.name.startswith('runtime_llama') for alias in node.names)
               for node in ast.walk(tree)):
            runtime_importers.append(path.relative_to(source_root).as_posix())
        assert not any(marker in text for marker in forbidden), path

    assert runtime_importers == ["adapters/model_runtime.py"]
    assert not tuple((source_root / "adapters" / "llm").glob("*.py"))


def test_composition_is_network_free_and_same_role_reuses_one_adapter():
    adapters = []
    def build(_profile):
        adapter = _Adapter(LLMCallResult(text='{"ok":true}'))
        adapters.append(adapter)
        return adapter
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=build)
    assert adapters == []
    assert gateway.invoke(_request()).structured_output == {"ok": True}
    assert gateway.invoke(_request(cap=128)).structured_output == {"ok": True}
    assert len(adapters) == 1
    assert [call[1]["num_predict"] for call in adapters[0].calls] == [256, 128]
    gateway.close()
    gateway.close()
    assert adapters[0].close_count == 1
    with pytest.raises(ModelBackendError, match="model_gateway_closed"):
        gateway.invoke(_request())


def test_builder_failure_is_typed_and_does_not_leak_an_active_call():
    def build(_profile):
        raise LLMBackendError("client construction failed")
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=build)
    with pytest.raises(ModelBackendError):
        gateway.invoke(_request())
    gateway.close()


def test_unknown_usage_terminal_and_structured_tool_calls_are_not_invented():
    calls = ({"id": "call-1", "type": "function", "function": {"name": "proposal", "arguments": "{}"}},)
    adapter = _Adapter(LLMCallResult(text="{}", usage=LLMUsageStats(prompt_tokens=9),
                                    terminal_reason="", tool_calls=calls))
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=lambda _: adapter)
    result = gateway.invoke(_request())
    assert result.terminal_reason == "unknown"
    assert result.usage["prompt_tokens"] == 9
    assert result.usage["completion_tokens"] is None
    assert result.usage["total_tokens"] is None
    assert result.usage_derived_fields == ()
    assert result.tool_calls == calls
    gateway.close()


def test_cancellation_and_thinking_are_transient_bounded_options():
    from dataclasses import asdict
    from threading import Event
    cancel = Event()
    cancel.set()
    class Adapter(_Adapter):
        def invoke_with_ctx(self, messages, **kwargs):
            super().invoke_with_ctx(messages, **kwargs)
            if kwargs["cancellation_probe"] is not None and kwargs["cancellation_probe"]():
                raise LLMCancelledError()
            return self.result
    adapter = Adapter(LLMCallResult(text='{}'))
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=lambda _: adapter)
    request = _request()
    with pytest.raises(ModelCancelledError):
        gateway.invoke(request, cancellation_probe=cancel.is_set)
    assert "cancellation" not in json.dumps(asdict(request))
    sink = []
    result = gateway.invoke(request, thinking_diagnostics={"enabled": True, "max_chars": 128},
                            thinking_sink=sink.append)
    options = adapter.calls[-1][1]
    assert options["thinking_diagnostics"].enabled is True
    assert options["thinking_diagnostics"].max_chars == 128
    assert options["thinking_sink"] == sink.append
    assert "thinking" not in json.dumps(asdict(result))
    gateway.invoke(request, thinking_diagnostics={"enabled": True})
    assert adapter.calls[-1][1]["thinking_diagnostics"].max_chars == 4096
    with pytest.raises(ValueError, match="1..4096"):
        gateway.invoke(request, thinking_diagnostics={"enabled": True, "max_chars": 4097})
    gateway.invoke(request)
    assert "thinking_diagnostics" not in adapter.calls[-1][1]
    assert "thinking_sink" not in adapter.calls[-1][1]
    gateway.close()


def test_content_free_transport_retains_failure_detail_and_success_metadata():
    attempt = LLMTransportAttempt(terminal_reason="early_eof", event_count=2, event_kinds=("text",))
    adapter = _Adapter(error=LLMBackendError("incomplete stream", diagnostics=attempt))
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=lambda _: adapter)
    with pytest.raises(ModelBackendError) as error:
        gateway.invoke(_request())
    assert error.value.terminal_reason == "backend_error"
    assert error.value.transport["terminal_reason"] == "early_eof"
    adapter.error = None
    adapter.result = LLMCallResult(text="{}", transport=attempt)
    assert gateway.invoke(_request()).transport == attempt.to_dict()
    gateway.close()


def test_parallel_calls_share_adapter_and_close_drains_before_disposing():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock, Thread
    started, release, closed = Event(), Event(), Event()
    entered = 0
    count_lock = Lock()
    class Adapter(_Adapter):
        def invoke_with_ctx(self, messages, **kwargs):
            nonlocal entered
            with count_lock:
                entered += 1
                if entered == 2:
                    started.set()
            assert release.wait(5)
            return LLMCallResult(text="{}")
        def close(self):
            assert release.is_set()
            super().close()
            closed.set()
    adapter = Adapter()
    built = []
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"),
                                      adapter_builder=lambda profile: built.append(profile) or adapter)
    errors = []
    def close():
        try:
            gateway.close()
        except BaseException as error:
            errors.append(error)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(gateway.invoke, _request()) for _ in range(2)]
        closer = None
        try:
            assert started.wait(5), "generation was serialized or adapter creation raced"
            assert len(built) == 1
            closer = Thread(target=close)
            closer.start()
            with gateway._condition:
                assert gateway._condition.wait_for(lambda: gateway._closing, timeout=5)
            with pytest.raises(ModelBackendError, match="model_gateway_closed"):
                gateway.invoke(_request())
            assert not closed.is_set()
        finally:
            release.set()
            if closer is not None:
                closer.join(5)
        assert all(future.result(timeout=5).terminal_reason == "completed" for future in futures)
        assert closer is not None and not closer.is_alive()
    assert errors == []
    assert closed.is_set()
    assert adapter.close_count == 1


def test_failed_close_retains_unclosed_adapters_and_never_reopens():
    class Adapter(_Adapter):
        fail = True
        def close(self):
            if self.fail:
                raise RuntimeError("client close failed")
            super().close()
    adapter = Adapter(LLMCallResult(text="{}"))
    gateway = RuntimeLlamaModelGateway(RuntimeLlamaGatewayConfig(model="model"), adapter_builder=lambda _: adapter)
    gateway.invoke(_request())
    with pytest.raises(RuntimeError, match="client close failed"):
        gateway.close()
    with pytest.raises(ModelBackendError, match="model_gateway_closed"):
        gateway.invoke(_request())
    assert adapter.close_count == 0
    adapter.fail = False
    gateway.close()
    gateway.close()
    assert adapter.close_count == 1
