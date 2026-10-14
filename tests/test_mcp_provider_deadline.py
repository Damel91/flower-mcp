"""The configured provider deadline owns the complete RPC child lifetime."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import errno
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from flow_of_work_mcp.adapters.implementation_intelligence import mcp_provider as provider_module
from flow_of_work_mcp.adapters.implementation_intelligence.mcp_provider import (
    StreamableHttpMcpClient, StreamableHttpMcpClientConfig,
)
from flow_of_work_mcp.core.errors import (
    ImplementationProviderContractError, ImplementationProviderUnavailableError,
)


VERSION = "flower.provider_rpc.v1"


def _install_worker(monkeypatch, tmp_path: Path, body: str) -> Path:
    """Replace only the fixed script seam; retain real process/pipe containment."""
    path = tmp_path / "controlled_transport_worker.py"
    path.write_text("import asyncio, atexit, json, sys, time\n"
                    "sys.stdin.reconfigure(encoding='utf-8')\nsys.stdout.reconfigure(encoding='utf-8')\n" + body,
                    encoding="utf-8")
    monkeypatch.setattr(provider_module, "_TRANSPORT_WORKER", path)
    return path


def _capture_children(monkeypatch):
    children = []
    launches = []
    original = subprocess.Popen
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        launches.append((args, kwargs))
        return child
    monkeypatch.setattr(provider_module.subprocess, "Popen", spawn)
    return children, launches


def _assert_settled(children):
    assert children and all(child.poll() is not None for child in children)
    for child in children:
        for name in ("stdin", "stdout", "stderr"):
            pipe = getattr(child, name, None)
            assert pipe is None or pipe.closed
        for name in ("_stdout_thread", "_stderr_thread"):
            reader = getattr(child, name, None)
            assert reader is None or not reader.is_alive()
    assert not [thread for thread in threading.enumerate() if thread.name == "fow-provider-deadline"]


def _client(timeout=0.5):
    return StreamableHttpMcpClient(StreamableHttpMcpClientConfig(
        endpoint="http://provider.invalid/private-endpoint", timeout_seconds=timeout))


@pytest.mark.parametrize("timeout", [True, False, float("nan"), float("inf"), -float("inf"), 0, -1, "1", None])
def test_direct_timeout_config_rejects_non_finite_or_non_numeric_values(timeout):
    with pytest.raises(ValueError):
        StreamableHttpMcpClientConfig(endpoint="http://provider.invalid/mcp", timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [1, 0.1])
def test_direct_timeout_config_retains_positive_numeric_values(timeout):
    assert StreamableHttpMcpClientConfig(endpoint="http://provider.invalid/mcp", timeout_seconds=timeout).timeout_seconds == timeout


def test_real_child_success_preserves_arguments_metadata_and_multiline_result(monkeypatch, tmp_path):
    script = _install_worker(monkeypatch, tmp_path, '''
request = json.load(sys.stdin)
assert set(request) == {"version", "endpoint", "timeout_seconds", "deadline_monotonic", "tool_name", "arguments", "meta"}
assert request["version"] == "flower.provider_rpc.v1"
assert request["deadline_monotonic"] > time.monotonic()
print(json.dumps({"version": request["version"], "status": "ok", "result": {
    "tool": request["tool_name"], "arguments": request["arguments"], "meta": request["meta"], "markdown": "# Context\\n\\nFirst line.\\nSecond line."}}, allow_nan=False))
''')
    children, launches = _capture_children(monkeypatch)
    arguments = {"instructions": ["Keep λ and multiline\nMarkdown."], "private": "fixture-argument-secret"}
    metadata = {"flow.packet_validation_context.v1": {"context_sha256": "a" * 64}}
    result = _client(3).call_tool("fixture_tool", arguments, meta=metadata)
    assert result == {"tool": "fixture_tool", "arguments": arguments, "meta": metadata,
                      "markdown": "# Context\n\nFirst line.\nSecond line."}
    argv = list(launches[0][0][0])
    assert argv[0] == sys.executable and argv[-1] == str(script)
    assert "-B" in argv and ("-I" in argv) is bool(sys.flags.isolated)
    assert "fixture-argument-secret" not in str(argv) and "private-endpoint" not in str(argv)
    assert not launches[0][1].get("shell", False)
    assert launches[0][1].get("stderr") == subprocess.DEVNULL
    _assert_settled(children)


@pytest.mark.parametrize("body", [
    "json.load(sys.stdin)\nwhile True: pass\n",
    "json.load(sys.stdin)\ntime.sleep(10)\n",
    "json.load(sys.stdin)\nasync def run():\n    asyncio.get_running_loop().run_in_executor(None, time.sleep, 10)\nasyncio.run(run())\n",
    "time.sleep(10)\n",  # Deliberately never reads the large request pipe.
])
def test_deadline_reaps_cpu_blocked_dns_shutdown_and_nonreading_children(monkeypatch, tmp_path, body):
    _install_worker(monkeypatch, tmp_path, body)
    children, _launches = _capture_children(monkeypatch)
    started = time.monotonic()
    with pytest.raises(ImplementationProviderUnavailableError) as error:
        _client().call_tool("fixture_tool", {"large_json": "x" * 1_000_000})
    assert error.value.terminal_reason == "implementation_provider_timeout"
    assert time.monotonic() - started < 2.5
    _assert_settled(children)


def test_valid_reply_before_hung_exit_is_not_adopted_after_deadline(monkeypatch, tmp_path):
    marker = tmp_path / "effect.json"
    _install_worker(monkeypatch, tmp_path, f'''
request = json.load(sys.stdin)
with open({str(marker)!r}, "w", encoding="utf-8") as stream:
    json.dump({{"effect": "persisted", "reply": "valid-before-expiry"}}, stream)
print(json.dumps({{"version": request["version"], "status": "ok", "result": {{"ack": "valid-before-expiry"}}}}), flush=True)
time.sleep(10)
''')
    children, _launches = _capture_children(monkeypatch)
    with pytest.raises(ImplementationProviderUnavailableError) as error:
        _client().call_tool("fixture_tool", {})
    assert error.value.terminal_reason == "implementation_provider_timeout"
    persisted = marker.read_bytes()
    _assert_settled(children)
    time.sleep(0.05)
    assert marker.read_bytes() == persisted


def test_deadline_is_captured_before_process_launch(monkeypatch, tmp_path):
    _install_worker(monkeypatch, tmp_path, 'print("not valid IPC")\n')
    original = subprocess.Popen
    children = []
    def slow_spawn(*args, **kwargs):
        time.sleep(0.15)
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(provider_module.subprocess, "Popen", slow_spawn)
    with pytest.raises(ImplementationProviderUnavailableError) as error:
        _client(0.1).call_tool("fixture_tool", {})
    assert error.value.terminal_reason == "implementation_provider_timeout"
    _assert_settled(children)


@pytest.mark.parametrize("exception", [KeyboardInterrupt("fixture cancellation"), asyncio.CancelledError("fixture cancellation")])
def test_external_cancellation_propagates_identically_after_owned_child_cleanup(monkeypatch, tmp_path, exception):
    _install_worker(monkeypatch, tmp_path, "time.sleep(10)\n")
    original = subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        communicate = child.communicate
        calls = 0
        def interrupted(*positional, **named):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exception
            return communicate(*positional, **named)
        child.communicate = interrupted
        return child
    monkeypatch.setattr(provider_module.subprocess, "Popen", spawn)
    with pytest.raises(type(exception)) as error:
        _client(3).call_tool("fixture_tool", {})
    assert error.value is exception
    _assert_settled(children)


def test_interruption_during_watchdog_start_still_reaps_spawned_child(monkeypatch, tmp_path):
    _install_worker(monkeypatch, tmp_path, "time.sleep(10)\n")
    children, _launches = _capture_children(monkeypatch)
    original = provider_module.Thread
    interrupt = KeyboardInterrupt("interrupted after spawn before watcher start")
    def watcher(*args, **kwargs):
        thread = original(*args, **kwargs)
        def interrupted_start():
            raise interrupt
        thread.start = interrupted_start
        return thread
    monkeypatch.setattr(provider_module, "Thread", watcher)
    with pytest.raises(KeyboardInterrupt) as error:
        _client(3).call_tool("fixture_tool", {})
    assert error.value is interrupt
    _assert_settled(children)


@pytest.mark.parametrize("cleanup_errno,interrupt_type", [
    (errno.EINVAL, None), (errno.EINVAL, KeyboardInterrupt),
    (errno.EIO, KeyboardInterrupt), (errno.EIO, asyncio.CancelledError),
])
def test_windows_dead_stdin_close_preserves_success_or_original_cancellation(monkeypatch, tmp_path, cleanup_errno, interrupt_type):
    _install_worker(monkeypatch, tmp_path, '''
request = json.load(sys.stdin)
print(json.dumps({"version": request["version"], "status": "ok", "result": {"ack": "original"}}))
''')
    original_spawn = subprocess.Popen
    children, handled = [], []
    interrupt = interrupt_type("caller canceled after completed communicate") if interrupt_type else None
    def spawn(*args, **kwargs):
        child = original_spawn(*args, **kwargs)
        children.append(child)
        close = child.stdin.close
        close_stdout = child.stdout.close
        communicate = child.communicate
        first = True
        completed = False
        def windows_close():
            close()
            if completed and child.poll() is not None:
                handled.append("dead_stdin_error")
                raise OSError(cleanup_errno, "fixture private dead Windows stdin handle")
        def stdout_close():
            close_stdout()
            if completed:
                handled.append("stdout_attempted_after_stdin")
        def completed_then_interrupted(*positional, **named):
            nonlocal first, completed
            result = communicate(*positional, **named)
            completed = True
            if first:
                first = False
                if interrupt is not None:
                    raise interrupt
            return result
        child.stdin.close = windows_close
        child.stdout.close = stdout_close
        child.communicate = completed_then_interrupted
        return child
    monkeypatch.setattr(provider_module.subprocess, "Popen", spawn)
    # Create all path fixtures before selecting this narrow cleanup branch.
    monkeypatch.setattr(provider_module.sys, "platform", "win32")
    if interrupt is not None:
        with pytest.raises(interrupt_type) as error:
            _client(3).call_tool("fixture_tool", {})
        assert error.value is interrupt
        assert "private" not in str(getattr(error.value, "__notes__", []))
    else:
        assert _client(3).call_tool("fixture_tool", {}) == {"ack": "original"}
    assert "dead_stdin_error" in handled
    assert handled.index("dead_stdin_error") < len(handled) - 1
    assert handled[-1] == "stdout_attempted_after_stdin"
    _assert_settled(children)


@pytest.mark.parametrize("payload", [
    "not JSON",
    '{"version":"flower.provider_rpc.v1","status":"ok","result":[],"extra":true}',
    '{"version":"flower.provider_rpc.v1","status":"ok","result":{"x":NaN}}',
    '{"version":"flower.provider_rpc.v1","status":"ok","result":{"x":Infinity}}',
    '{"version":"flower.provider_rpc.v1","status":"ok","result":{},"result":{"duplicate":true}}',
    '{"version":"wrong","status":"ok","result":{}}',
    '{"version":"flower.provider_rpc.v1","status":"ok","result":[]}',
    '{"version":"flower.provider_rpc.v1","status":"contract","reason":"implementation_provider_timeout"}',
    '{"version":"flower.provider_rpc.v1","status":"unavailable","reason":"implementation_provider_contract_invalid"}',
    '{"version":"flower.provider_rpc.v1","status":"unavailable","reason":"private endpoint credentials"}',
])
def test_malformed_or_cross_status_ipc_fails_closed_without_private_details(monkeypatch, tmp_path, payload):
    _install_worker(monkeypatch, tmp_path,
        "json.load(sys.stdin)\nsys.stderr.write('fixture-private-credentials')\nprint(" + repr(payload) + ")\n")
    children, _launches = _capture_children(monkeypatch)
    with pytest.raises((ImplementationProviderUnavailableError, ImplementationProviderContractError)) as error:
        _client(3).call_tool("fixture_tool", {})
    assert "private" not in str(error.value) and "credentials" not in str(error.value)
    _assert_settled(children)


@pytest.mark.parametrize("status,reason,error_type", [
    ("unavailable", "implementation_provider_timeout", ImplementationProviderUnavailableError),
    ("unavailable", "implementation_provider_transport_unavailable", ImplementationProviderUnavailableError),
    ("unavailable", "implementation_snapshot_capability_unavailable", ImplementationProviderUnavailableError),
    ("contract", "implementation_provider_contract_invalid", ImplementationProviderContractError),
])
def test_worker_error_envelopes_reconstruct_only_the_declared_domain_errors(monkeypatch, tmp_path, status, reason, error_type):
    frame = json.dumps({"version": VERSION, "status": status, "reason": reason})
    _install_worker(monkeypatch, tmp_path, "json.load(sys.stdin)\nprint(" + repr(frame) + ")\n")
    children, _launches = _capture_children(monkeypatch)
    with pytest.raises(error_type) as error:
        _client(3).call_tool("fixture_tool", {})
    assert error.value.terminal_reason == reason
    _assert_settled(children)


def test_non_finite_request_values_fail_before_child_dispatch(monkeypatch, tmp_path):
    _install_worker(monkeypatch, tmp_path, "raise AssertionError('must not dispatch invalid JSON')\n")
    children, _launches = _capture_children(monkeypatch)
    with pytest.raises((ValueError, ImplementationProviderContractError, ImplementationProviderUnavailableError)):
        _client(3).call_tool("fixture_tool", {"value": float("nan")})
    assert children == []


def _worker_request(timeout):
    return {"version": VERSION, "endpoint": "http://provider.invalid/mcp", "timeout_seconds": timeout,
            "deadline_monotonic": time.monotonic() + timeout, "tool_name": "fixture_tool",
            "arguments": {"value": 1}, "meta": {"fixture": "metadata"}}


def _run_fake_sdk_worker(monkeypatch, stage, *, timeout=0.15, sdk_error=None):
    from flow_of_work_mcp.adapters.implementation_intelligence import mcp_transport_worker as worker
    import mcp
    import mcp.client.streamable_http as stream_module
    events = []
    @asynccontextmanager
    async def stream(*_args, **_kwargs):
        events.append("connect")
        if stage == "connect":
            await asyncio.sleep(1)
        try:
            yield object(), object(), lambda: "fixture-session"
        finally:
            try:
                if stage == "stream_exit":
                    await asyncio.sleep(1)
            finally:
                events.append("stream_closed")
    class Session:
        def __init__(self, *_args, **_kwargs):
            pass
        async def __aenter__(self):
            if stage == "session_entry":
                await asyncio.sleep(1)
            return self
        async def __aexit__(self, *_args):
            try:
                if stage == "session_exit":
                    await asyncio.sleep(1)
            finally:
                events.append("session_closed")
        async def initialize(self):
            events.append("initialize")
            if stage == "initialize":
                await asyncio.sleep(1)
            if stage == "cumulative":
                await asyncio.sleep(0.09)
        async def list_tools(self):
            events.append("list_tools")
            if stage == "implicit_list":
                await asyncio.sleep(1)
            return SimpleNamespace(tools=[])
        async def call_tool(self, *_args, **_kwargs):
            events.append("effect")
            if sdk_error is not None:
                raise sdk_error
            if stage == "tool":
                await asyncio.sleep(1)
            if stage == "cumulative":
                await asyncio.sleep(0.09)
            # Model the SDK's post-effect implicit output-schema discovery.
            await self.list_tools()
            return SimpleNamespace(isError=False, structuredContent={"receipt": "original"}, content=[])
    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(stream_module, "streamablehttp_client", stream)
    request = _worker_request(timeout)
    output = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(request).encode("utf-8")), encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(output, encoding="utf-8"))
    try:
        worker.main()
    except SystemExit as error:
        assert error.code in {None, 0}
    return json.loads(output.getvalue()), events


@pytest.mark.parametrize("stage", ["connect", "session_entry", "initialize", "tool", "implicit_list", "session_exit", "stream_exit", "cumulative"])
def test_worker_sdk_stages_and_cleanup_share_one_cumulative_budget(monkeypatch, stage):
    frame, events = _run_fake_sdk_worker(monkeypatch, stage)
    assert frame == {"version": VERSION, "status": "unavailable", "reason": "implementation_provider_timeout"}
    if stage in {"tool", "implicit_list", "session_exit", "stream_exit", "cumulative"}:
        assert "effect" in events
    if stage != "connect":
        assert "stream_closed" in events


@pytest.mark.parametrize("sdk_error", [TimeoutError("fixture private"), httpx.ReadTimeout("fixture private"),
    McpError(ErrorData(code=408, message="fixture private")),
    ExceptionGroup("fixture private", [ValueError("fixture private"), TimeoutError("fixture private")])])
def test_worker_recognizes_timeout_errors_without_exposing_sdk_details(monkeypatch, sdk_error):
    frame, _events = _run_fake_sdk_worker(monkeypatch, "error", sdk_error=sdk_error, timeout=3)
    assert frame == {"version": VERSION, "status": "unavailable", "reason": "implementation_provider_timeout"}


def test_worker_success_waits_for_cooperative_cleanup(monkeypatch):
    frame, events = _run_fake_sdk_worker(monkeypatch, "success", timeout=3)
    assert frame == {"version": VERSION, "status": "ok", "result": {"receipt": "original"}}
    assert events[-2:] == ["session_closed", "stream_closed"]
