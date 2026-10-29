"""Deterministic Flow MCP operation-surface and prompt-cost probe."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
from pathlib import Path
from typing import Any

from flow_of_work_mcp.application.lifecycle_recipes import all_recipes
from flow_of_work_mcp.application.operation_contracts import (
    operation_contract_index,
    public_tool_catalog,
    registry_version,
    work_area_catalog,
)
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.server import SERVER_INSTRUCTIONS, create_app


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "local_orchestrator_projection"
    / "flow_pre_loip.json"
)


def _normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<timestamp>"
                if key.endswith("_at") or key == "timestamp"
                else _normalized(item)
            )
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


async def build_inventory() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="fow-loip-") as temp:
        runtime = build_runtime(
            database_path=Path(temp) / "flow.sqlite3",
            import_root=temp,
        )
        try:
            app = create_app(runtime)
            tools = sorted(await app.list_tools(), key=lambda item: item.name)
            public_tools = {
                item.name: {
                    "description": item.description or "",
                    "input_schema": item.inputSchema or {},
                    "output_schema": item.outputSchema or {},
                }
                for item in tools
            }
            receipts: dict[str, Any] = {}
            calls = (
                ("fow_capabilities", {}),
                (
                    "fow_create_project",
                    {
                        "project_id": "baseline-project",
                        "name": "Baseline Project",
                        "actor": "loip-probe",
                        "request_id": "loip-baseline-create",
                    },
                ),
                ("fow_what_next", {"project_id": "baseline-project"}),
                (
                    "fow_packet_inspect",
                    {"project_id": "baseline-project", "packet_id": "PACKET-999999"},
                ),
                ("fow_campaign_inspect", {"project_id": "baseline-project"}),
                ("fow_list_jobs", {"project_id": "baseline-project"}),
            )
            for name, arguments in calls:
                try:
                    response = await app.call_tool(name, arguments)
                    structured = response.structuredContent or {}
                    receipts[name] = _normalized(structured.get("result", structured))
                except Exception as exc:
                    # FastMCP ToolError is itself a contract state.
                    receipts[name] = {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
        finally:
            runtime.close()

    contract = {
        "public_tools": public_tools,
        "registry_version": registry_version(),
        "catalog": list(public_tool_catalog()),
        "areas": list(work_area_catalog()),
        "operation_contracts": operation_contract_index(),
        "recipes": all_recipes(),
        "server_instructions": SERVER_INSTRUCTIONS,
    }
    encoded = json.dumps(
        contract, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )
    return {
        "fixture_version": 1,
        "measurement_method": "canonical-json chars; conservative ceil(chars/4) tokens",
        "measurements": {
            "canonical_chars": len(encoded),
            "estimated_tokens": math.ceil(len(encoded) / 4),
            "public_tool_count": len(public_tools),
            "multiplexed_operation_count": len(contract["operation_contracts"]),
            "recipe_count": len(contract["recipes"]),
        },
        "contract": contract,
        "representative_receipts": receipts,
    }


def render_inventory() -> str:
    return (
        json.dumps(
            asyncio.run(build_inventory()), indent=2, sort_keys=True, ensure_ascii=True
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = render_inventory()
    if args.write:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
