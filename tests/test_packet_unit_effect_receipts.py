import asyncio

import pytest

from flow_of_work_mcp import server


class NoRuntimeAccess:
    def __getattribute__(self, name):
        raise AssertionError(f"Unexpected runtime access: {name}")


def _request(unit):
    return {
        "project_id": "alpha", "change_id": "CHANGE-000001", "packet_id": "PACKET-000001",
        "operation": "add_unit", "actor": "operator", "request_id": "unit-1",
        "unit": {
            "client_unit_key": "entrypoint", "operation_kind": "new_file", "file_path": "main.py",
            "instructions": ["Create the entry point."], "unit_checks": ["Verify the exit status."],
            **unit,
        },
    }


@pytest.mark.parametrize(("override", "field", "guidance"), [
    ({"target_description": "new entry point"}, "unit.target_description", "use file_path"),
    ({"instructions": "Create the entry point."}, "unit.instructions", "separate array item"),
])
def test_add_unit_shape_errors_prove_no_dispatch_in_both_channels(override, field, guidance):
    app = server.create_app(NoRuntimeAccess())
    response = asyncio.run(app.call_tool("fow_packet_author", _request(override)))
    receipt = response.structuredContent["result"]
    assert receipt["status"] == "rejected" and receipt["reason"] == "packet_unit_input_invalid"
    result = receipt["result"]
    assert result["effect_state"] == "none"
    assert result["effect_receipt"]["mutation_started"] is False
    assert result["effect_receipt"]["request_id"] == "unit-1"
    assert result["diagnostics"][0]["field"] == field
    assert result["next_tool_call"]["arguments"]["operation_name"] == "add_unit"
    markdown = response.content[0].text
    assert field in markdown and guidance in markdown
    assert "```json" not in markdown


def test_add_unit_late_failure_preserves_uncertain_effect_and_scope(monkeypatch):
    def fail_after_dispatch(*args, **kwargs):
        raise ValueError("Test failure during packet authoring.")

    monkeypatch.setattr(server, "_execute_packet_command", fail_after_dispatch)
    result = server.handle_packet_author(NoRuntimeAccess(), **_request({}))["result"]
    assert result["effect_state"] == "unknown"
    assert "effect_receipt" not in result
    assert result["original_request"]["request_id"] == "unit-1"
    assert result["next_tool_call"] == {
        "tool": "fow_packet_inspect",
        "arguments": {"project_id": "alpha", "change_id": "CHANGE-000001",
                      "packet_id": "PACKET-000001", "view": "working_sheet"},
    }
