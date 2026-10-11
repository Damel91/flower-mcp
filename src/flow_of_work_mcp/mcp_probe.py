#!/usr/bin/env python3
"""Inspect an explicitly selected streamable-HTTP MCP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


_MISSING = object()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("FLOW_OF_WORK_MCP_ENDPOINT"),
        help="HTTP MCP endpoint; required unless FLOW_OF_WORK_MCP_ENDPOINT is set",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    view = parser.add_mutually_exclusive_group()
    view.add_argument(
        "--content-only",
        action="store_true",
        help="for tool calls, print only model-facing text content",
    )
    view.add_argument(
        "--structured-only",
        action="store_true",
        help="for tool calls, print only the machine-facing structured channel",
    )
    view.add_argument(
        "--channel-summary",
        action="store_true",
        help="for tool calls, print channel presence and decoded size metrics",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "ping",
        help="read MCP initialize identity, tool count and advertised Flower identity",
    )
    commands.add_parser("list", help="print the exposed tool catalog")
    describe = commands.add_parser("describe", help="print one exposed tool schema")
    describe.add_argument("tool")
    call = commands.add_parser("call", help="call one tool with a JSON object")
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="{}")
    return parser


def _json_model(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    return value


def _transport_teardown_only(error: BaseException) -> bool:
    """Recognize failures emitted while closing an already answered session."""
    nested = getattr(error, "exceptions", ())
    if nested:
        return all(_transport_teardown_only(item) for item in nested)
    return isinstance(
        error,
        (anyio.BrokenResourceError, anyio.ClosedResourceError, httpx.ConnectError),
    )


def _content_view(payload: dict[str, Any]) -> str | list[Any]:
    blocks = list(payload.get("content") or [])
    texts = [
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if len(texts) == 1:
        return texts[0]
    return texts


def _channel_summary(payload: dict[str, Any]) -> dict[str, Any]:
    blocks = list(payload.get("content") or [])
    text = "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    structured = payload.get("structuredContent")
    structured_text = (
        json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
        if structured is not None
        else ""
    )
    return {
        "is_error": bool(payload.get("isError", False)),
        "content_blocks": len(blocks),
        "text_characters": len(text),
        "text_lines": len(text.splitlines()),
        "structured_present": structured is not None,
        "structured_characters": len(structured_text),
    }


async def _probe(args: argparse.Namespace) -> Any:
    payload: Any = _MISSING
    answered = False
    try:
        async with streamablehttp_client(args.endpoint) as streams:
            read_stream, write_stream = streams[:2]
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                if args.command == "ping":
                    catalog = await session.list_tools()
                    payload = {
                        "status": "ok",
                        "endpoint": args.endpoint,
                        "tool_count": len(catalog.tools),
                        "mcp_initialize": _json_model(initialized),
                        "distribution": None,
                        "distribution_status": "not_advertised",
                    }
                    if any(tool.name == "fow_capabilities" for tool in catalog.tools):
                        capabilities = _json_model(
                            await session.call_tool("fow_capabilities", {"view": "summary"})
                        )
                        payload["flower_capabilities"] = capabilities
                        structured = capabilities.get("structuredContent") or {}
                        application = structured.get("result") or {}
                        if capabilities.get("isError") or application.get("status") != "success":
                            payload["status"] = "capabilities_error"
                            payload["distribution_status"] = "capabilities_error"
                        else:
                            distribution = (application.get("result") or {}).get("distribution")
                            if isinstance(distribution, dict):
                                payload["distribution"] = distribution
                                payload["distribution_status"] = "advertised"
                elif args.command == "list":
                    catalog = await session.list_tools()
                    payload = [_json_model(tool) for tool in catalog.tools]
                elif args.command == "describe":
                    catalog = await session.list_tools()
                    match = next(
                        (tool for tool in catalog.tools if tool.name == args.tool),
                        None,
                    )
                    if match is None:
                        raise ValueError(f"unknown MCP tool: {args.tool}")
                    payload = _json_model(match)
                else:
                    arguments = json.loads(args.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be a JSON object")
                    result = await session.call_tool(args.tool, arguments)
                    payload = _json_model(result)
                    if isinstance(payload, dict):
                        if args.content_only:
                            payload = _content_view(payload)
                        elif args.structured_only:
                            payload = payload.get("structuredContent", payload)
                        elif args.channel_summary:
                            payload = _channel_summary(payload)
                answered = True
    except Exception as error:
        if not answered or not _transport_teardown_only(error):
            raise
    if payload is _MISSING:
        raise RuntimeError("MCP probe completed without a response payload")
    return payload


async def _main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.endpoint or not args.endpoint.strip():
        parser.error("--endpoint or FLOW_OF_WORK_MCP_ENDPOINT is required; select the intended HTTP MCP instance")
    async with asyncio.timeout(args.timeout):
        payload = await _probe(args)
    if args.content_only and args.command == "call" and isinstance(payload, str):
        print(payload, end="" if payload.endswith("\n") else "\n")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_main(argv))


if __name__ == "__main__":
    main()
