"""Public installed-package stdio smoke; no private QA or inference required."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def qualify(command: str) -> dict:
    receipts = []
    with tempfile.TemporaryDirectory(prefix="flower-public-smoke-") as directory:
        root = Path(directory)
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"PYTHONPATH", "FLOWER_HOME"}}
        environment["FLOWER_HOME"] = str(root / "profiles")
        parameters = StdioServerParameters(
            command=str(Path(command).resolve()),
            args=["serve", "--profile", "smoke", "--profile-root", str(root / "profiles"), "--transport", "stdio"],
            cwd=str(root), env=environment,
        )

        async def call(session, name, arguments, status="success"):
            response = await session.call_tool(name, arguments)
            assert not response.isError, response
            envelope = response.structuredContent["result"]
            text = "\n".join(block.text for block in response.content if block.type == "text")
            assert text.startswith("#") and "\n" in text
            assert envelope["status"] == status, envelope
            receipts.append({"tool": name, "arguments": arguments, "envelope": envelope, "markdown": text})
            return envelope

        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert {"fow_bootstrap", "fow_capabilities", "fow_external_work"} <= {tool.name for tool in catalog.tools}
                bootstrap_schema = next(tool.inputSchema for tool in catalog.tools if tool.name == "fow_bootstrap")
                await call(session, "fow_capabilities", {"view": "summary"})
                contracts = {}
                for operation in ("start", "record_answer", "record_correspondence"):
                    help_result = await call(session, "fow_capabilities", {
                        "view": "operation", "operation_tool": "fow_bootstrap", "operation_name": operation})
                    contracts[operation] = help_result["result"]["operation_contract"]
                for operation, field in (("record_answer", "answer"), ("record_correspondence", "correspondence")):
                    expected = contracts[operation]["guidance"]["input_schema"][field]
                    assert expected in bootstrap_schema["properties"][field]["anyOf"]
                    assert expected["additionalProperties"] is False
                project = "flower-public-smoke"
                actor = "synthetic-smoke-engineer"
                start = deepcopy(contracts["start"]["example"])
                start.update(project_id=project, project_name="Public smoke fixture", actor=actor,
                             path="guided_engineering", request_id="start")
                assert start["path"] in contracts["start"]["accepted_values"]["path"]
                original = await call(session, "fow_bootstrap", start)
                bootstrap_id = original["result"]["bootstrap"]["bootstrap_id"]
                for patch, cause in (
                    ({"project_name": "Another name", "request_id": "bad-name"}, "bootstrap_project_name_conflict"),
                    ({"request_id": "second-start"}, "bootstrap_already_active"),
                    ({"project_name": "Changed replay"}, "guided_bootstrap_start_request_conflict"),
                ):
                    rejected = await call(session, "fow_bootstrap", {**start, **patch}, status="rejected")
                    assert rejected["reason"] == cause
                    assert rejected["result"]["diagnostics"][0]["resolution"]
                    next_call = rejected["result"]["next_tool_call"]
                    await call(session, next_call["tool"], next_call["arguments"])
                replay = await call(session, "fow_bootstrap", start)
                assert replay["result"]["bootstrap"]["bootstrap_id"] == bootstrap_id
                address = {"project_id": project, "actor": actor}
                requirement = await call(session, "fow_register_requirement", {**address,
                    "title": "Integer successor", "statement": "The API shall return the integer successor.",
                    "category": "functional", "rationale": "Synthetic core qualification only.", "request_id": "requirement"})
                requirement_id = requirement["result"]["requirement_id"]
                goal = await call(session, "fow_goal", {**address, "operation": "add_use_case",
                    "title": "Receive successor", "use_case_actor": "client", "objective": "Get the next integer",
                    "observable_outcome": "Return value + 1", "request_id": "goal"})
                goal_id = goal["result"]["goal"]["goal_node_id"]
                milestone = await call(session, "fow_promote_milestone", {**address,
                    "name": "Successor fixture", "requirement_ids": [requirement_id],
                    "dependency_closure_ids": [requirement_id], "entry_policy": {"scenario": "declared"},
                    "exit_policy": {"checks": "Local and deferred verification remain distinct."},
                    "risk_disposition": "Synthetic scope; no external effects", "request_id": "milestone"})
                answer = deepcopy(contracts["record_answer"]["example"])
                answer.update(**address, bootstrap_id=bootstrap_id, request_id="answer")
                await call(session, "fow_bootstrap", answer)
                correspondence = deepcopy(contracts["record_correspondence"]["example"])
                correspondence.update(**address, bootstrap_id=bootstrap_id, request_id="correspondence")
                correspondence["correspondence"].update(
                    disposition="consistent", rationale="The canonical fixture expresses the recorded scenario.",
                    canonical_references={"requirement_ids": [requirement_id], "goal_node_ids": [goal_id],
                                          "milestone_ids": [milestone["result"]["milestone_id"]]})
                await call(session, "fow_bootstrap", correspondence)
                state = await call(session, "fow_bootstrap", {**address, "operation": "state", "bootstrap_id": bootstrap_id})

        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                restored = await call(session, "fow_bootstrap", {**address, "operation": "state", "bootstrap_id": bootstrap_id})
                assert restored["result"]["bootstrap"] == state["result"]["bootstrap"]
    return {"status": "passed", "public_calls": len(receipts), "restart": "passed",
            "scope": "Synthetic installed-core mechanics, not model usability or acceptance", "receipts": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True, help="absolute installed flower-mcp console path")
    parser.add_argument("--output", type=Path, help="optional retained public receipts")
    args = parser.parse_args()
    result = asyncio.run(asyncio.wait_for(qualify(args.command), timeout=90))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "receipts"}))


if __name__ == "__main__":
    main()
