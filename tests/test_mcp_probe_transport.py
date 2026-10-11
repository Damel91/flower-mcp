from __future__ import annotations

import argparse
import asyncio
import builtins
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest


def _load_probe_module():
    from flow_of_work_mcp import mcp_probe as module
    return module


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=[])


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        endpoint="http://probe.invalid/mcp",
        command="ping",
        structured_only=False,
    )


def test_probe_preserves_received_payload_across_transport_teardown(monkeypatch):
    module = _load_probe_module()

    @asynccontextmanager
    async def stream(_endpoint):
        yield object(), object()
        raise builtins.ExceptionGroup("teardown", [httpx.ConnectError("closed")])

    monkeypatch.setattr(module, "streamablehttp_client", stream)
    monkeypatch.setattr(module, "ClientSession", lambda *_args: _Session())

    assert asyncio.run(module._probe(_args())) == {
        "status": "ok",
        "endpoint": "http://probe.invalid/mcp",
        "tool_count": 0,
        "mcp_initialize": None,
        "distribution": None,
        "distribution_status": "not_advertised",
    }


def test_probe_propagates_transport_failure_before_payload(monkeypatch):
    module = _load_probe_module()

    @asynccontextmanager
    async def stream(_endpoint):
        raise httpx.ConnectError("unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(module, "streamablehttp_client", stream)

    with pytest.raises(httpx.ConnectError, match="unreachable"):
        asyncio.run(module._probe(_args()))
