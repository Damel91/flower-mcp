"""Private single-RPC MCP transport process; no Flow runtime or ledger imports.

Run this file directly with the parent's interpreter. The parent owns the hard
process deadline; the async scope preserves cooperative MCP session cleanup.
Only a completely settled invocation emits the private stdout envelope.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
import json
import math
import sys
import time


PROTOCOL_VERSION = "flower.provider_rpc.v1"
TIMEOUT_REASON = "implementation_provider_timeout"
TRANSPORT_UNAVAILABLE_REASON = "implementation_provider_transport_unavailable"
CAPABILITY_UNAVAILABLE_REASON = "implementation_snapshot_capability_unavailable"
CONTRACT_INVALID_REASON = "implementation_provider_contract_invalid"
ERROR_REASONS = {
    "unavailable": frozenset({TIMEOUT_REASON, TRANSPORT_UNAVAILABLE_REASON, CAPABILITY_UNAVAILABLE_REASON}),
    "contract": frozenset({CONTRACT_INVALID_REASON}),
}


class ProviderResponseContractError(Exception):
    """The private worker could not decode the existing structured contract."""


def strict_json_loads(value: bytes | str) -> object:
    def object_from_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def reject_constant(_value):
        raise ValueError("non-finite JSON constant")

    return json.loads(value, object_pairs_hook=object_from_pairs, parse_constant=reject_constant)


def _decode_mcp_result(response: object) -> dict[str, object]:
    structured = getattr(response, "structuredContent", None)
    if isinstance(structured, Mapping):
        return dict(structured)
    model_dump = getattr(structured, "model_dump", None)
    if callable(model_dump):
        value = model_dump()
        if isinstance(value, Mapping):
            return dict(value)
    raise ProviderResponseContractError("provider MCP response lacks structured content")


def _is_timeout(error: BaseException) -> bool:
    from httpx import TimeoutException
    from mcp.shared.exceptions import McpError

    if isinstance(error, BaseExceptionGroup):
        return any(_is_timeout(item) for item in error.exceptions)
    return (isinstance(error, (TimeoutError, TimeoutException))
            or isinstance(error, McpError) and error.error.code == 408)


def _error(status: str, reason: str) -> dict[str, object]:
    return {"version": PROTOCOL_VERSION, "status": status, "reason": reason}


async def _call_tool(request: Mapping[str, object]) -> dict[str, object]:
    try:
        import anyio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        return _error("unavailable", TRANSPORT_UNAVAILABLE_REASON)

    remaining = float(request["deadline_monotonic"]) - time.monotonic()
    if remaining <= 0:
        return _error("unavailable", TIMEOUT_REASON)
    scope = None
    try:
        with anyio.fail_after(remaining) as scope:
            async with streamablehttp_client(
                request["endpoint"], timeout=remaining, sse_read_timeout=remaining,
            ) as (read, write, _get_session_id):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=remaining)) as session:
                    await session.initialize()
                    response = await session.call_tool(
                        request["tool_name"], arguments=request["arguments"], meta=request["meta"],
                    )
    except Exception as exc:  # noqa: BLE001 - only whitelisted reasons leave the worker
        reason = TIMEOUT_REASON if scope is not None and scope.cancel_called or _is_timeout(exc) else TRANSPORT_UNAVAILABLE_REASON
        return _error("unavailable", reason)
    if bool(getattr(response, "isError", False)):
        return _error("unavailable", CAPABILITY_UNAVAILABLE_REASON)
    try:
        result = _decode_mcp_result(response)
    except ProviderResponseContractError:
        return _error("contract", CONTRACT_INVALID_REASON)
    return {"version": PROTOCOL_VERSION, "status": "ok", "result": result}


def _request(value: object) -> Mapping[str, object]:
    if (not isinstance(value, dict)
            or set(value) != {"version", "endpoint", "timeout_seconds", "deadline_monotonic", "tool_name", "arguments", "meta"}
            or value["version"] != PROTOCOL_VERSION
            or not isinstance(value["endpoint"], str) or not value["endpoint"].startswith(("http://", "https://"))
            or not isinstance(value["tool_name"], str) or not value["tool_name"]
            or not isinstance(value["arguments"], dict)
            or value["meta"] is not None and not isinstance(value["meta"], dict)):
        raise ValueError("invalid private provider request")
    for name in ("timeout_seconds", "deadline_monotonic"):
        number = value[name]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number <= 0:
            raise ValueError("invalid private provider budget")
    return value


def main() -> None:
    try:
        request = _request(strict_json_loads(sys.stdin.buffer.read()))
        # Emission follows SDK context exits AND asyncio's executor shutdown.
        response = asyncio.run(_call_tool(request))
        output = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except Exception:  # noqa: BLE001 - private details must not enter stdout
        output = json.dumps(_error("unavailable", TRANSPORT_UNAVAILABLE_REASON)).encode("utf-8")
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
