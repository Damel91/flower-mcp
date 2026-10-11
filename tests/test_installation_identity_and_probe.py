from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from flow_of_work_mcp import cli, installation_identity, mcp_probe


def test_installed_identity_uses_distribution_metadata_and_reports_absence(monkeypatch):
    looked_up = []

    def version(name):
        looked_up.append(name)
        return "9.8.7"

    monkeypatch.setattr(installation_identity.metadata, "version", version)
    assert installation_identity.installed_distribution_identity() == {
        "product": "Flower MCP",
        "distribution_name": "flow-of-work-mcp",
        "distribution_version": "9.8.7",
        "version_available": True,
        "version_source": "importlib.metadata",
    }
    assert looked_up == ["flow-of-work-mcp"]

    def absent(_name):
        raise installation_identity.metadata.PackageNotFoundError

    monkeypatch.setattr(installation_identity.metadata, "version", absent)
    missing = installation_identity.installed_distribution_identity()
    assert missing["distribution_version"] is None
    assert missing["version_available"] is False


def test_doctor_identity_is_read_only_without_http_or_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mcp_probe, "main", lambda *_args: pytest.fail("doctor invoked HTTP probe"))
    monkeypatch.setattr(installation_identity.metadata, "version", lambda _name: "9.8.7")
    state = tmp_path / "absent-state"
    cli.main(["doctor", "--profile-root", str(state)])
    result = json.loads(capsys.readouterr().out)
    assert result["distribution"]["distribution_version"] == "9.8.7"
    assert result["runtime_probed"] is False
    assert not state.exists()


def test_cli_forwards_probe_arguments_verbatim(monkeypatch):
    received = []
    monkeypatch.setattr(mcp_probe, "main", lambda values: received.append(values))
    arguments = ["--endpoint", "http://test.invalid/mcp", "call", "fow_traceability", '{"project_id":"with spaces"}']
    cli.main(["probe", *arguments])
    assert received == [arguments]


@pytest.mark.parametrize("configured", [None, "", "  "])
def test_probe_requires_selected_endpoint_before_any_connection(configured, monkeypatch, capsys):
    if configured is None:
        monkeypatch.delenv("FLOW_OF_WORK_MCP_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("FLOW_OF_WORK_MCP_ENDPOINT", configured)
    monkeypatch.setattr(mcp_probe, "_probe", lambda _args: pytest.fail("unselected endpoint contacted"))
    with pytest.raises(SystemExit) as failure:
        mcp_probe.main(["ping"])
    assert failure.value.code == 2
    assert "--endpoint or FLOW_OF_WORK_MCP_ENDPOINT is required" in capsys.readouterr().err


def test_probe_environment_endpoint_is_read_at_invocation_and_cli_takes_precedence(monkeypatch, capsys):
    received = []

    async def probe(args):
        received.append(args.endpoint)
        return {"status": "ok"}

    monkeypatch.setattr(mcp_probe, "_probe", probe)
    monkeypatch.setenv("FLOW_OF_WORK_MCP_ENDPOINT", "http://first.invalid/mcp")
    mcp_probe.main(["ping"])
    monkeypatch.setenv("FLOW_OF_WORK_MCP_ENDPOINT", "http://second.invalid/mcp")
    mcp_probe.main(["ping"])
    mcp_probe.main(["--endpoint", "http://explicit.invalid/mcp", "ping"])
    assert received == ["http://first.invalid/mcp", "http://second.invalid/mcp", "http://explicit.invalid/mcp"]
    capsys.readouterr()


def _args(command="ping", **values):
    return argparse.Namespace(
        endpoint="http://probe.invalid/mcp", command=command,
        tool="fow_traceability", arguments='{"project_id":"alpha"}',
        content_only=values.get("content_only", False),
        structured_only=values.get("structured_only", False),
        channel_summary=values.get("channel_summary", False),
    )


def _install_session(monkeypatch, *, capability_result=None, tool_result=None, failure=None):
    calls = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            return {"serverInfo": {"name": "Flower MCP", "version": "sdk-version"}, "protocolVersion": "2025-06-18"}

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="fow_capabilities")])

        async def call_tool(self, tool, arguments):
            calls.append((tool, arguments))
            if failure is not None:
                raise failure
            return capability_result if tool == "fow_capabilities" else tool_result

    @asynccontextmanager
    async def transport(_endpoint):
        yield object(), object()

    monkeypatch.setattr(mcp_probe, "ClientSession", lambda *_args: Session())
    monkeypatch.setattr(mcp_probe, "streamablehttp_client", transport)
    return calls


def test_ping_keeps_mcp_initialize_and_full_capabilities_distinct_from_distribution(monkeypatch):
    distribution = {"product": "Flower MCP", "distribution_version": "0.3.0"}
    capability = {
        "content": [{"type": "text", "text": "# Flower\n\nCapabilities\n"}],
        "structuredContent": {"result": {"status": "success", "result": {"distribution": distribution}}},
        "isError": False,
    }
    calls = _install_session(monkeypatch, capability_result=capability)
    result = asyncio.run(mcp_probe._probe(_args()))
    assert result["mcp_initialize"]["serverInfo"]["version"] == "sdk-version"
    assert result["distribution"] == distribution
    assert result["distribution_status"] == "advertised"
    assert result["flower_capabilities"] == capability
    assert calls == [("fow_capabilities", {"view": "summary"})]


def test_ping_preserves_capability_error_without_claiming_identity(monkeypatch):
    error = {"content": [{"type": "text", "text": "# Error\nUnavailable\n"}], "isError": True}
    _install_session(monkeypatch, capability_result=error)
    result = asyncio.run(mcp_probe._probe(_args()))
    assert result["status"] == "capabilities_error"
    assert result["distribution_status"] == "capabilities_error"
    assert result["distribution"] is None
    assert result["flower_capabilities"] == error


def test_ping_does_not_hide_capability_connection_failure_as_teardown(monkeypatch):
    _install_session(monkeypatch, failure=httpx.ConnectError("capabilities disconnected"))
    with pytest.raises(httpx.ConnectError, match="capabilities disconnected"):
        asyncio.run(mcp_probe._probe(_args()))


@pytest.mark.parametrize("is_error", [False, True])
def test_probe_default_call_preserves_full_channels_and_mcp_error(monkeypatch, is_error):
    response = {
        "content": [{"type": "text", "text": "# Evidence\n\nOriginal body\n"}],
        "structuredContent": {"result": {"status": "blocked" if is_error else "success", "result": {"metadata": {"provenance": "host"}}}},
        "isError": is_error,
        "_meta": {"test": "preserved"},
    }
    calls = _install_session(monkeypatch, tool_result=response)
    assert asyncio.run(mcp_probe._probe(_args("call"))) == response
    assert calls == [("fow_traceability", {"project_id": "alpha"})]


def test_probe_content_view_preserves_multiline_markdown(monkeypatch):
    markdown = "# Evidence\n\nOriginal body\n"
    _install_session(monkeypatch, tool_result={"content": [{"type": "text", "text": markdown}]})
    assert asyncio.run(mcp_probe._probe(_args("call", content_only=True))) == markdown


def test_checkout_wrapper_and_installed_module_advertise_same_probe_commands():
    root = Path(__file__).resolve().parents[1]
    wrapper = subprocess.run([sys.executable, str(root / "tools/mcp_probe.py"), "--help"], capture_output=True, text=True, check=True)
    environment = dict(os.environ, PYTHONPATH=str(root / "src"))
    module = subprocess.run([sys.executable, "-m", "flow_of_work_mcp.mcp_probe", "--help"], env=environment, capture_output=True, text=True, check=True)
    assert "FLOW_OF_WORK_MCP_ENDPOINT" in wrapper.stdout
    assert "ping,list,describe,call" in wrapper.stdout
    assert "FLOW_OF_WORK_MCP_ENDPOINT" in module.stdout
    assert "ping,list,describe,call" in module.stdout
