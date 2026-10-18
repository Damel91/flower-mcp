"""Presentation regressions for complete, readable lifecycle references.

These tests use supplied records only: rendering cannot acquire lifecycle or
execution authority, schedule work, or mutate the application envelope.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

import pytest
from markdown_it import MarkdownIt

from flow_of_work_mcp import markdown_adapter
from flow_of_work_mcp.model_facing import model_facing_tool, project_markdown
from flow_of_work_mcp.application.roadmap_markdown import render_roadmap


def _fences(markdown: str) -> list[tuple[str, str]]:
    """Read complete Markdown fences, including collision-safe delimiters."""
    blocks: list[tuple[str, str]] = []
    opened: tuple[str, str] | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        if opened is None:
            match = re.fullmatch(r" {0,3}(`{3,}|~{3,})([^\n]*)", line)
            if match:
                opened = (match.group(1), match.group(2).strip())
                body = []
        else:
            delimiter, language = opened
            if re.fullmatch(r" {0,3}" + re.escape(delimiter[0]) + "{" + str(len(delimiter)) + r",}[ \t]*", line):
                blocks.append((language, "\n".join(body)))
                opened = None
            else:
                body.append(line)
    assert opened is None, "The presentation left an unterminated code fence."
    return blocks


def _json_blocks(markdown: str) -> list[object]:
    return [json.loads(body) for language, body in _fences(markdown) if language == "json"]


def _outside_fences(markdown: str) -> str:
    visible: list[str] = []
    delimiter = ""
    for line in markdown.splitlines():
        if not delimiter:
            match = re.fullmatch(r" {0,3}(`{3,}|~{3,})([^\n]*)", line)
            if match:
                delimiter = match.group(1)
            else:
                visible.append(line)
        elif re.fullmatch(r" {0,3}" + re.escape(delimiter[0]) + "{" + str(len(delimiter)) + r",}[ \t]*", line):
            delimiter = ""
    return "\n".join(visible)


def _plain(markdown: str) -> str:
    """Decode Markdown punctuation escapes without changing data whitespace."""
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", markdown)


def _wrapped(raw: dict[str, object], *, tool: str = "fow_bootstrap", operation: str = "state", budget: int = 512_000):
    def response(operation: str = operation) -> dict[str, object]:
        return raw

    wrapped = model_facing_tool(response, tool_name=tool, output_budget=budget)
    return wrapped(operation=operation)


def _complete_roadmap_envelope():
    basis = {
        "project_id": "synthetic-reference", "bootstrap_id": "BOOT-001",
        "milestones": [{"milestone_id": "MILE-001", "name": "Visible result", "requirement_ids": ["REQ-001"]}],
        "requirements": [{"requirement_id": "REQ-001", "title": "Visible behavior", "statement": "CANONICAL_SENTINEL"}],
        "goals": [], "goal_edges": [], "answers": {}, "correspondence": {},
    }
    draft = {"authority": "outside_selected_scope", "unassigned_answers": {"future": {"answer": "DRAFT_SENTINEL"}},
             "outside_scope_answers": {}, "outside_scope_correspondence": {}}
    roadmap = {
        "contract_version": "flow.guided_roadmap.v1", "project_id": basis["project_id"],
        "bootstrap_id": basis["bootstrap_id"], "milestone_ids": ["MILE-001"],
        "roadmap_fingerprint": "issued-fingerprint", "confirmable": True, "confirmed": False,
        "gaps": [], "canonical_scope": basis, "draft_context": draft,
        "semantic_completeness": "host_judgment_and_human_confirmation", "human_acceptance": False,
    }
    roadmap["markdown"] = render_roadmap(basis, fingerprint=roadmap["roadmap_fingerprint"], draft_context=draft, gaps=[])
    return {"tool": "fow_bootstrap", "status": "success", "reason": "", "result": {"bootstrap": roadmap}}


def test_complete_roadmap_is_presented_once_without_changing_machine_authority():
    raw = _complete_roadmap_envelope()
    raw["result"]["bootstrap"]["future_summary"] = "UNKNOWN_SUMMARY_SENTINEL"
    before = deepcopy(raw)
    response = _wrapped(raw, operation="roadmap")
    text = response.content[0].text

    assert raw == before and response.structuredContent == {"result": before}
    assert before["result"]["bootstrap"]["markdown"] in text
    assert text.count("CANONICAL_SENTINEL") == text.count("DRAFT_SENTINEL") == 1
    assert "UNKNOWN_SUMMARY_SENTINEL" in text
    for field in ("Confirmable", "Confirmed", "Human Acceptance", "Gaps", "Roadmap Fingerprint"):
        assert field in text
    assert "Canonical Scope" in text and "Draft Context" in text and "complete roadmap below" in text


@pytest.mark.parametrize("defect", [
    "contract", "missing-summary", "wrong-boolean", "wrong-milestone-list", "wrong-gap-list",
    "missing-body", "empty-body", "headers-only-body", "truncated-body", "changed-body",
    "unknown-canonical-key", "missing-canonical-key", "wrong-record-list", "wrong-mapping",
    "identity-mismatch", "unknown-draft-group", "wrong-draft-group", "wrong-draft-authority", "missing-goal-identity",
])
def test_incomplete_or_unmatched_roadmaps_keep_the_complete_generic_projection(defect):
    raw = _complete_roadmap_envelope()
    roadmap = raw["result"]["bootstrap"]
    if defect == "contract":
        roadmap["contract_version"] = "flow.future-roadmap.v2"
    elif defect == "missing-summary":
        del roadmap["confirmable"]
    elif defect == "wrong-boolean":
        roadmap["confirmed"] = "false"
    elif defect == "wrong-milestone-list":
        roadmap["milestone_ids"] = "MILE-001"
    elif defect == "wrong-gap-list":
        roadmap["gaps"] = {"reason": "untyped gap"}
    elif defect == "missing-body":
        del roadmap["markdown"]
    elif defect == "empty-body":
        roadmap["markdown"] = ""
    elif defect == "headers-only-body":
        roadmap["markdown"] = "\n".join(line for line in roadmap["markdown"].splitlines() if line.startswith("#")) + "\n"
    elif defect == "truncated-body":
        roadmap["markdown"] = roadmap["markdown"].split("## Draft intake", 1)[0]
    elif defect == "changed-body":
        roadmap["markdown"] = roadmap["markdown"].replace("CANONICAL_SENTINEL", "DIFFERENT_SENTINEL")
    elif defect == "unknown-canonical-key":
        roadmap["canonical_scope"]["future_context"] = "UNKNOWN_CANONICAL_SENTINEL"
    elif defect == "missing-canonical-key":
        del roadmap["canonical_scope"]["goal_edges"]
    elif defect == "wrong-record-list":
        roadmap["canonical_scope"]["goals"] = ["not a Goal record"]
    elif defect == "wrong-mapping":
        roadmap["canonical_scope"]["answers"] = ["not an answer mapping"]
    elif defect == "identity-mismatch":
        roadmap["canonical_scope"]["project_id"] = "other-project"
    elif defect == "unknown-draft-group":
        roadmap["draft_context"]["future_context"] = {"fact": "UNKNOWN_DRAFT_SENTINEL"}
    elif defect == "wrong-draft-group":
        roadmap["draft_context"]["outside_scope_answers"] = []
    elif defect == "wrong-draft-authority":
        roadmap["draft_context"]["authority"] = "governing"
    elif defect == "missing-goal-identity":
        roadmap["canonical_scope"]["goals"] = [{"title": "Incomplete Goal"}]
    before = deepcopy(raw)
    response = _wrapped(raw, operation="roadmap")
    text = response.content[0].text

    assert raw == before and response.structuredContent == {"result": before}
    assert "CANONICAL_SENTINEL" in text and "DRAFT_SENTINEL" in text
    assert "Presented in the complete roadmap below" not in text
    if "unknown-" in defect:
        assert ("UNKNOWN_CANONICAL_SENTINEL" if "canonical" in defect else "UNKNOWN_DRAFT_SENTINEL") in text


@pytest.mark.parametrize("status,operation", [("blocked", "roadmap"), ("success", "state")])
def test_roadmap_dedup_does_not_apply_to_other_operation_or_error(status, operation):
    raw = _complete_roadmap_envelope()
    raw["status"] = status
    text = _wrapped(raw, operation=operation).content[0].text
    assert text.count("CANONICAL_SENTINEL") == text.count("DRAFT_SENTINEL") == 2


def test_nested_records_keep_complete_values_and_sibling_order():
    value = {
        "scenarios": [
            {"name": "FIRST_SCENARIO", "participants": ["First user", "Support"],
             "steps": [{"action": "FIRST_ACTION", "effects": ["FIRST_EFFECT", "SECOND_EFFECT"]}]},
            {"name": "SECOND_SCENARIO", "participants": ["Other user"],
             "steps": [{"action": "SECOND_ACTION", "effects": ["THIRD_EFFECT"]}]},
        ],
        "obligations": {"verification": ["CHECK_FIRST", "CHECK_SECOND"]},
    }
    before = deepcopy(value)
    text = markdown_adapter.render_structured(value)

    assert value == before
    assert text.index("FIRST_SCENARIO") < text.index("FIRST_ACTION") < text.index("FIRST_EFFECT")
    assert text.index("SECOND_EFFECT") < text.index("SECOND_SCENARIO") < text.index("THIRD_EFFECT")
    assert text.index("CHECK_FIRST") < text.index("CHECK_SECOND")
    assert all(sentinel in text for sentinel in ("First user", "Support", "Other user"))
    assert '"participants"' not in text and '"effects"' not in text
    assert "{'action':" not in text
    assert _json_blocks(text) == []


def test_scalar_following_child_stays_associated_with_parent():
    text = markdown_adapter.render_structured({
        "parent": {
            "before": "PARENT_FIRST",
            "children": [{"name": "CHILD_FIRST", "detail": "CHILD_DETAIL"}],
            "after": "PARENT_LAST",
        },
        "sibling": {"note": "SIBLING_NOTE"},
    })

    assert text.index("PARENT_FIRST") < text.index("CHILD_FIRST") < text.index("PARENT_LAST")
    assert text.index("PARENT_LAST") < text.index("SIBLING_NOTE")
    # The trailing parent field needs its own structural boundary, rather than
    # looking like another property of the last child record.
    child_end = text.index("CHILD_DETAIL") + len("CHILD_DETAIL")
    parent_last = text.index("PARENT_LAST")
    between = text[child_end:parent_last]
    assert "After" in between or "after" in between


def test_nested_scalar_table_keeps_every_row_inside_its_parent_list():
    text = markdown_adapter.render_structured({"parent": {
        "name": "PARENT_CONTEXT",
        "child": {"name": "CHILD_CONTEXT", "entries": [
            {"key": "FIRST_TABLE_ROW", "state": "current"},
            {"key": "SECOND_TABLE_ROW", "state": "pending"},
        ]},
        "after": "PARENT_TRAILING_CONTEXT",
    }})
    table_lines = [line for line in text.splitlines() if line.lstrip().startswith("|")]

    assert len(table_lines) == 4
    indents = [len(line) - len(line.lstrip()) for line in table_lines]
    assert indents[0] > 0
    assert len(set(indents)) == 1, "Table separator/data rows must not escape the containing list."
    assert text.index("CHILD_CONTEXT") < text.index("FIRST_TABLE_ROW") < text.index("PARENT_TRAILING_CONTEXT")


def test_successful_multiline_prose_keeps_markdown_and_physical_lines():
    prose = "Opening **statement**.\n\n- First activity\n- Second activity\n\n[Reference](https://example.test/spec)"
    text = project_markdown("fow_get_requirement", {
        "status": "success", "result": {"requirement": {"statement": prose}},
    })

    assert "Opening **statement**." in text
    assert "First activity" in text and "Second activity" in text
    assert "\n" in text[text.index("First activity"):text.index("Second activity")]
    assert "Opening **statement**. / " not in text
    assert "[Reference](https://example.test/spec)" in text
    assert not any(prose in body for _language, body in _fences(text))


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_physical_newlines_are_preserved_without_mutating_source(newline):
    raw = {"status": "success", "result": {"statement": newline.join([
        "First **paragraph**.", "", "- Second paragraph activity", "- Third paragraph activity",
    ])}}
    before = deepcopy(raw)
    result = _wrapped(raw)
    text = result.content[0].text

    assert result.structuredContent == {"result": before}
    assert raw == before
    assert "First **paragraph**." in text
    assert "First **paragraph**. / " not in text
    assert "\n" in text[text.index("Second paragraph activity"):text.index("Third paragraph activity")]


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize("prose,expected_html", [
    ("```python\nSTARTING_FENCE_BODY\n```", '<pre><code class="language-python">STARTING_FENCE_BODY\n</code></pre>'),
    ("## STARTING_HEADING\n\nHeading paragraph.", "<h2>STARTING_HEADING</h2>"),
    ("1. FIRST_ORDERED_ITEM\n2. SECOND_ORDERED_ITEM", "<ol>"),
])
def test_leading_markdown_constructs_parse_as_markdown_inside_values(as_list, prose, expected_html):
    value = {"statement": [prose] if as_list else prose}
    before = deepcopy(value)
    text = markdown_adapter.render_structured(value)
    html = MarkdownIt("commonmark").render(text)

    assert value == before
    assert expected_html in html
    if "FIRST_ORDERED_ITEM" in prose:
        assert html.index("FIRST_ORDERED_ITEM") < html.index("SECOND_ORDERED_ITEM")
        assert "<li>FIRST_ORDERED_ITEM</li>" in html


def test_shallow_scalar_tables_preserve_pipes_backslashes_and_unicode():
    text = markdown_adapter.render_structured({"evidence": [
        {"source": r"C:\fixture\α | β", "status": "current", "count": 0},
        {"source": "Second source", "status": "pending", "count": 2},
    ]})

    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert rows, "Comparable scalar records should remain a readable table."
    decoded = _plain(text)
    assert r"C:\fixture\α | β" in decoded
    assert "Second source" in decoded and "current" in decoded
    assert r"\| β" in text
    assert not any('"source"' in line for line in rows)


def test_literal_backslash_before_pipe_survives_a_markdown_table():
    value = r"literal \| remains a backslash and a pipe"
    text = markdown_adapter.render_structured({"rows": [{"source": value, "state": "current"}]})

    assert value in _plain(text)
    assert re.search(r"\\{3}\|", text), "A literal backslash plus a table pipe needs separate Markdown escapes."


def test_headers_that_normalize_to_the_same_label_do_not_create_ambiguous_columns():
    text = markdown_adapter.render_structured({"records": [
        {"source_name": "UNDERSCORE_VALUE", "source name": "SPACE_VALUE"},
        {"source_name": "SECOND_UNDERSCORE_VALUE", "source name": "SECOND_SPACE_VALUE"},
    ]})

    assert all(value in text for value in ("UNDERSCORE_VALUE", "SPACE_VALUE", "SECOND_UNDERSCORE_VALUE", "SECOND_SPACE_VALUE"))
    assert not any(line.lstrip().startswith("|") for line in text.splitlines())


def test_multiline_header_is_one_safe_label_without_changing_input():
    value = {"records": [{"first\r\nsecond": "HEADER_VALUE", "plain": "OTHER_VALUE"}]}
    before = deepcopy(value)
    text = markdown_adapter.render_structured(value)

    assert value == before
    assert "\r" not in text
    assert "HEADER_VALUE" in text and "OTHER_VALUE" in text
    assert "First Second" in text
    assert not any(line.lstrip().startswith("|") for line in text.splitlines())


def test_multiline_or_nested_cells_do_not_become_a_serialized_table():
    text = markdown_adapter.render_structured({"evidence": [
        {"source": "SOURCE_ALPHA", "details": {"checks": ["CHECK_A", "CHECK_B"]},
         "summary": "First physical line\nSecond physical line"},
        {"source": "SOURCE_BETA", "details": {"checks": ["CHECK_C"]},
         "summary": "Other physical line\nLast physical line"},
    ]})

    assert all(value in text for value in ("SOURCE_ALPHA", "SOURCE_BETA", "CHECK_A", "CHECK_B", "CHECK_C"))
    assert '"checks"' not in text and "{'checks':" not in text
    assert not any("SOURCE_ALPHA" in line and line.startswith("|") for line in text.splitlines())
    assert "First physical line / Second physical line" not in text
    assert text.index("SOURCE_ALPHA") < text.index("CHECK_B") < text.index("SOURCE_BETA")


def test_empty_null_false_zero_and_empty_text_are_visible_and_distinct():
    text = markdown_adapter.render_structured({
        "required_fields": [], "empty_mapping": {}, "unknown_reference": None,
        "empty_text": "", "verified": False, "attempt_count": 0,
    })
    lowered = text.lower()

    for label in ("required fields", "empty mapping", "unknown reference", "empty text", "verified", "attempt count"):
        assert label in lowered
    assert re.search(r"\bnull\b", lowered), "Explicit null must not look like an omitted or empty string."
    assert "empty" in lowered
    assert re.search(r"\b(false|no)\b", lowered)
    assert re.search(r"\b0\b", text)
    assert "[]" not in text and "{}" not in text


def test_nested_arrays_and_deep_records_preserve_grouping_and_all_items():
    deep: object = {"leaf": "DEEPEST_VALUE"}
    for number in reversed(range(12)):
        deep = {f"layer_{number}": deep}
    text = markdown_adapter.render_structured({
        "groups": [["GROUP_A_FIRST", "GROUP_A_SECOND"], ["GROUP_B_FIRST", ["GROUP_B_NESTED"]]],
        "deep": deep,
    })

    assert text.index("GROUP_A_FIRST") < text.index("GROUP_A_SECOND") < text.index("GROUP_B_FIRST") < text.index("GROUP_B_NESTED")
    assert "DEEPEST_VALUE" in text
    assert all(f"Layer {number}" in text or f"layer {number}" in text for number in range(12))
    assert not re.search(r"^#{7,}\s", text, re.M)
    assert '["GROUP_' not in text and "['GROUP_" not in text
    assert "..." not in text and "…" not in text


def test_wrapper_keeps_exact_application_envelope_and_input_unchanged():
    raw = {"tool": "fow_bootstrap", "status": "success", "result": {
        "bootstrap": {"status": "active", "selected_facts": {"scenario": {
            "answer": "**Stakeholder intent**\n\n- Observable behavior", "revision": 2,
        }}, "blockers": [], "human_acceptance": False},
    }, "audit_reference": {"event_seq": 12}}
    before = deepcopy(raw)
    before_bytes = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()

    result = _wrapped(raw)

    assert result.structuredContent == {"result": before}
    assert raw == before
    assert json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode() == before_bytes
    assert result.isError is False
    assert len(result.content) == 1
    assert "Observable behavior" in result.content[0].text
    assert '"selected_facts"' not in result.content[0].text


def test_exact_calls_and_named_recovery_maps_keep_copyable_json():
    call = {"tool": "fow_bootstrap", "arguments": {"operation": "state", "project_id": "test-project"}}
    partial_call = {"tool": "fow_bindings", "arguments": {"operation": "import"},
                    "required_inputs": ["actor", "association_receipt"],
                    "policy": "Select a currently authorized route."}
    recovery = {"state": call, "bindings": partial_call}
    raw = {"status": "success", "result": {
        "next_tool_call": call, "continuation": partial_call, "recovery_calls": recovery,
    }}
    before = deepcopy(raw)
    text = project_markdown("fow_bootstrap", raw, arguments={"operation": "state"})
    blocks = _json_blocks(text)

    assert call in blocks and partial_call in blocks and recovery in blocks
    assert raw == before
    assert "association_receipt" in text and "Select a currently authorized route." in text


@pytest.mark.parametrize("value", [
    {"continuation_choice": "review", "progress_revision": "current", "human_acceptance": False},
    {"tool": "fow_bootstrap"},
    {"arguments": {"operation": "state"}},
    {"tool": "", "arguments": {}},
    {"tool": ["fow_bootstrap"], "arguments": {}},
    {"tool": "fow_bootstrap", "arguments": []},
    {"tool_name": "fow_bootstrap", "payload": {"operation": "state"}},
    "host_observe",
    [],
])
def test_ordinary_or_malformed_continuation_is_readable_data_not_a_call(value):
    raw = {"status": "success", "result": {"continuation": value}}
    before = deepcopy(raw)
    text = project_markdown("fow_bootstrap", raw, arguments={"operation": "state"})

    assert _json_blocks(text) == []
    assert raw == before
    if isinstance(value, dict) and "continuation_choice" in value:
        assert "review" in text and "current" in text
    if isinstance(value, str):
        assert value in text


@pytest.mark.parametrize("key", ["next_gate_call", "continuations", "recovery_calls"])
def test_complete_call_collections_only_are_json_references(key):
    call = {"tool": "fow_capabilities", "arguments": {"view": "summary"}}
    values = ([call, deepcopy(call)], {"first": call, "second": deepcopy(call)})
    for value in values:
        text = project_markdown("fow_bootstrap", {"status": "success", "result": {key: value}}, arguments={"operation": "state"})
        assert value in _json_blocks(text)

    mixed = {"first": call, "second": {"state": "unknown"}}
    text = project_markdown("fow_bootstrap", {"status": "success", "result": {key: mixed}}, arguments={"operation": "state"})
    assert _json_blocks(text) == []
    assert "unknown" in text and "fow_capabilities" in text


def test_markdown_artifacts_are_native_markdown_while_logs_remain_safely_fenced():
    artifact = "# Exported reference\n\n## Observable behavior\n\n- Preserve **this requirement**.\n\n```python\nprint('example')\n```\n"
    log = "line one\n```\n~~~\n````\n~~~~\nline last"
    rendered = markdown_adapter.render_markdown(
        title="References", document={}, status="success", output_budget=None,
        artifacts=[
            markdown_adapter.MarkdownArtifact("Plan", artifact, "markdown"),
            markdown_adapter.MarkdownArtifact("Worker log", log, "text"),
        ],
    )

    visible = _outside_fences(rendered)
    assert "# Exported reference" in visible and "## Observable behavior" in visible
    assert "Preserve **this requirement**." in visible
    assert artifact in rendered
    assert any(language == "text" and body == log for language, body in _fences(rendered))
    assert "line last" not in visible


def test_source_artifact_does_not_gain_markdown_authority():
    source = "# SOURCE_IS_DATA\n\n<script>example()</script>\n```\nraw bytes"
    text = project_markdown("fow_import_srs", {
        "status": "success", "result": {"source": source, "language": "text"},
    })

    assert "SOURCE_IS_DATA" not in _outside_fences(text)
    assert any(body == source for _language, body in _fences(text))


@pytest.mark.parametrize("kind_field", ["artifact_kind", "kind"])
@pytest.mark.parametrize("body_field", ["content", "text"])
def test_known_artifact_kind_renders_markdown_without_media_type(kind_field, body_field):
    artifact = "# Standalone reference\n\n## Supplied obligations\n\n- NATIVE_ARTIFACT_OBLIGATION\n"
    raw = {"status": "success", "result": {"artifacts": [
        {kind_field: "implementation_plan", body_field: artifact},
    ]}}
    before = deepcopy(raw)
    result = _wrapped(raw, tool="fow_get_artifacts", operation="")

    assert result.structuredContent == {"result": before}
    assert raw == before
    assert artifact in result.content[0].text
    assert "NATIVE_ARTIFACT_OBLIGATION" in _outside_fences(result.content[0].text)


def test_nonstring_artifact_kind_is_ordinary_data_without_type_errors():
    raw = {"status": "success", "result": {
        "kind": {"category": "ordinary_metadata"},
        "content": "# CONTENT_IS_DATA\n\nThis content has no Markdown media declaration.",
    }}
    before = deepcopy(raw)
    result = _wrapped(raw, tool="fow_get_artifacts", operation="")
    text = result.content[0].text

    assert raw == before and result.structuredContent == {"result": before}
    assert "ordinary_metadata" in text
    assert "CONTENT_IS_DATA" not in _outside_fences(text)
    assert any("CONTENT_IS_DATA" in body for _language, body in _fences(text))


def test_error_diagnostics_remain_readable_without_claiming_effects_or_replay():
    call = {"tool": "fow_capabilities", "arguments": {"view": "summary"}}
    raw = {"status": "rejected", "reason": "invalid_input", "result": {
        "effect_state": "unknown", "operation_state": "unknown",
        "diagnostics": [{"code": "invalid_input", "field": "canonical_references",
                         "message": "Provide all reference lists.\nAn empty list must be explicit.",
                         "received_value": {"requirement_ids": []},
                         "accepted_values": ["requirement_ids", "goal_node_ids", "milestone_ids"]}],
        "next_tool_call": call,
    }}
    before = deepcopy(raw)
    result = _wrapped(raw)
    text = result.content[0].text

    assert result.structuredContent == {"result": before}
    assert raw == before
    assert "unknown" in text and "invalid_input" in text
    assert "Provide all reference lists." in text and "An empty list must be explicit." in text
    assert all(field in _plain(text).replace(" ", "_").lower() for field in ("requirement_ids", "goal_node_ids", "milestone_ids"))
    assert _json_blocks(text) == [call]


def test_output_budget_uses_explicit_boundary_but_keeps_machine_result_complete():
    prose = "Complete supplied lifecycle fact. " * 200
    raw = {"status": "success", "result": {"description": prose}}
    result = _wrapped(raw, budget=1_024)
    text = result.content[0].text

    assert "model_facing_output_budget_exceeded" in text
    assert prose not in text
    assert result.structuredContent == {"result": raw}


def test_offline_markdown_reference_remains_complete_despite_ordinary_budget():
    artifact = "# Complete offline plan\n\n" + ("- Follow this supplied unit obligation.\n" * 200) + "\n## Final obligation\n\nFINAL_OFFLINE_CHECK\n"
    raw = {"status": "success", "result": {"media_type": "text/markdown", "content": artifact}}
    result = _wrapped(raw, tool="fow_get_artifacts", operation="", budget=1_024)

    assert result.structuredContent == {"result": raw}
    assert artifact in result.content[0].text
    assert "FINAL_OFFLINE_CHECK" in _outside_fences(result.content[0].text)
    assert "model_facing_output_budget_exceeded" not in result.content[0].text


def test_lens_catalog_keeps_compact_summary_and_complete_machine_membership():
    members = [{"tool": "fow_change", "operation": f"MACHINE_MEMBER_{number}"} for number in range(24)]
    catalog = {
        "project_context": None, "selection_state": "none", "selection_reason": "not_selected",
        "catalog_revision": "catalog:fixture", "interaction_revision": "flow.interaction-catalog." + "a" * 64,
        "operation_count": 181, "lens_count": 1,
        "lenses": [{"area": "changes", "selected": False, "availability": "available",
                    "prerequisites": [], "reason": "", "primary_operations": members,
                    "companion_operations": []}],
        "core_operations": [{"tool": "fow_interaction", "operation": "discover"}],
    }
    raw = {"status": "success", "result": catalog}
    result = _wrapped(raw, tool="fow_interaction", operation="catalog")

    assert result.structuredContent == {"result": raw}
    text = result.content[0].text
    assert "181 operations" in text and "24" in text
    assert "MACHINE_MEMBER_" not in text
    assert "grants no execution permission" in text
