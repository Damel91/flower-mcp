"""Complete roadmap presentation never changes the supplied authority."""
from copy import deepcopy
import json
import re

from markdown_it import MarkdownIt

from flow_of_work_mcp.application.roadmap_markdown import render_goal, render_roadmap


def roadmap_inputs():
    requirement = {
        "requirement_id": "REQ-000101", "title": "Prerequisite contract",
        "statement": "PRECONDITION_FIRST_LINE\nPRECONDITION_SECOND_LINE with `code` | pipe.",
        "category": "functional", "current_revision": 1, "source_anchor": "spec/prerequisite.md:8",
        "retired": False,
    }
    realized = {**requirement, "requirement_id": "REQ-000102", "title": "Show the agreed result",
                "statement": "RESULT_FIRST_LINE\nRESULT_SECOND_LINE in italiano: città.", "current_revision": 2,
                "source_anchor": "spec/result.md:12"}
    use_case = {
        "goal_node_id": "GOAL-000101", "node_type": "use_case", "title": "Observe the result\nWith full context",
        "payload": {"actor": "STAKEHOLDER_ACTOR", "objective": "SCENARIO_OBJECTIVE",
                    "observable_outcome": "OBSERVABLE_RESULT", "preconditions": ["USE_CASE_PRECONDITION"],
                    "postconditions": ["USE_CASE_POSTCONDITION"], "invariants": ["USE_CASE_INVARIANT"],
                    "technical_decision": {"rationale": "REUSE_CANONICAL_CONTRACT", "options": [[{"value": "NESTED_OPTION"}]]}},
        "source_anchor": {"path": "spec/use-cases.md", "start_line": 8, "end_line": 11, "symbol": "UC-RESULT"},
    }
    sequence = {
        "goal_node_id": "GOAL-000102", "node_type": "sequence", "title": "Observe in order",
        "payload": {"participants": ["SEQUENCE_USER", "SEQUENCE_CLIENT"],
                    "normal_steps": ["STEP_ONE\nSTEP_ONE_CONTINUATION", "STEP_TWO"],
                    "alternate_steps": ["ALTERNATE_STEP"], "failure_steps": ["FAILURE_STEP"],
                    "expected_effects": ["EXPECTED_EFFECT"]}, "source_anchor": None,
    }
    first = {
        "milestone_id": "MILESTONE-000101", "name": "Provide contract",
        "requirement_ids": [requirement["requirement_id"]], "prerequisite_requirement_ids": [],
        "prerequisite_producers": [], "prerequisite_mapping_gaps": [], "prerequisite_authority_gaps": [],
        "entry_policy": {"intent": "BASELINE_CONFIRMED"},
        "exit_policy": {"criteria": [{"number": 1, "statement": "CONTRACT_CRITERION"}],
                        "verification": [{"kind": "unit_check", "statement": "CONTRACT_CHECK"}]},
        "risk_disposition": "PRODUCER_RISK",
    }
    second = {
        "milestone_id": "MILESTONE-000102", "name": "Consume contract",
        "requirement_ids": [realized["requirement_id"]],
        "prerequisite_requirement_ids": [requirement["requirement_id"]],
        "prerequisite_producers": [{"requirement_id": requirement["requirement_id"],
                                    "producer_milestone_id": first["milestone_id"], "authority": "DECLARED_PRODUCER"}],
        "prerequisite_mapping_gaps": [], "prerequisite_authority_gaps": [],
        "entry_policy": {"checks": ["CONSUMER_ENTRY_CHECK"], "decision": {"choice": "REUSE_PRODUCER",
                                                                                 "reason": "EXACT_EXISTING_AUTHORITY"}},
        "exit_policy": {"criteria": ["CONSUMER_CRITERION"], "verification": {"local": ["LOCAL_CHECK"],
                                                                                  "deferred": ["DEFERRED_CAMPAIGN"]},
                        "empty_policy": {}, "zero": 0, "optional": None, "accepted": False},
        "risk_disposition": "CONSUMER_RISK",
    }
    basis = {
        "project_id": "roadmap-synthetic", "bootstrap_id": "BOOT-000101", "milestones": [first, second],
        "requirements": [requirement, realized], "goals": [use_case, sequence],
        "goal_edges": [{"source_goal_id": use_case["goal_node_id"], "target_goal_id": sequence["goal_node_id"],
                        "relation": "described_by"}],
        "answers": {"scenario": {"question": "SELECTED_QUESTION", "answer": "SELECTED_ANSWER\nSELECTED_DETAIL",
                                 "revision": 2, "kind": "intent", "source_reference": "SYNTHETIC_DIALOGUE_REFERENCE"}},
        "correspondence": {"scenario": {"answer_revision": 2, "canonical_references": {
            "requirement_ids": [realized["requirement_id"]], "milestone_ids": [second["milestone_id"]],
            "goal_node_ids": [use_case["goal_node_id"]]}, "disposition": "consistent",
            "rationale": "EXACT_SCOPE_CORRESPONDENCE", "provenance": "host_declared"}},
    }
    draft = {"unassigned_answers": {"future": {"answer": "DRAFT_OUTSIDE_SCOPE", "kind": "proposal"}},
             "outside_scope_correspondence": {}, "outside_scope_answers": {}}
    gaps = [{"reason": "EXPLICIT_GAP", "milestone_id": second["milestone_id"],
             "questions": [{"prompt": "INTENT_QUESTION", "details": ["GAP_DETAIL"]}]}]
    return basis, draft, gaps


def assert_string_values_visible(value, text):
    if isinstance(value, dict):
        for item in value.values():
            assert_string_values_visible(item, text)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_string_values_visible(item, text)
    elif isinstance(value, str):
        for physical in value.splitlines():
            assert physical in text


def test_complete_roadmap_preserves_every_supplied_context_and_input():
    basis, draft, gaps = roadmap_inputs()
    before = deepcopy((basis, draft, gaps))
    text = render_roadmap(basis, fingerprint="ISSUED_FINGERPRINT", draft_context=draft, gaps=gaps)

    assert (basis, draft, gaps) == before
    for value in (basis, draft, gaps):
        assert_string_values_visible(value, text)
    assert "ISSUED_FINGERPRINT" in text
    assert "Realized Requirement Ids" in text and "Prerequisite Requirement Ids" in text
    assert text.index("MILESTONE-000101: Provide contract") < text.index("MILESTONE-000102: Consume contract")
    assert text.index("Selected stakeholder answers") < text.index("DRAFT_OUTSIDE_SCOPE")
    assert "They do not govern this roadmap" in text
    assert "Unresolved obligations" in text and "INTENT_QUESTION" in text
    assert "does not accept implemented software" in text
    for value in (basis, draft, gaps):
        assert json.dumps(value, ensure_ascii=False) not in text
    assert '"normal_steps"' not in text and "{'choice':" not in text
    assert "**Zero:** 0" in text and "**Optional:** Not provided (null)." in text
    assert "**Accepted:** no" in text and "empty object" in text and "empty list" in text
    assert not re.search(r"^#{7,} ", text, re.MULTILINE)


def test_roadmap_renders_as_readable_document_with_ordered_sequence_and_prose():
    basis, draft, gaps = roadmap_inputs()
    text = render_roadmap(basis, fingerprint="ISSUED_FINGERPRINT", draft_context=draft, gaps=gaps)
    html = MarkdownIt("commonmark", {"html": False}).render(text)
    assert "<h1>Flower engineering roadmap</h1>" in html
    assert "<h2>Milestones in selected order</h2>" in html
    assert "<ol>" in html and "STEP_ONE\nSTEP_ONE_CONTINUATION" in html
    assert html.index("STEP_ONE_CONTINUATION") < html.index("STEP_TWO")
    assert "RESULT_FIRST_LINE\nRESULT_SECOND_LINE" in html
    assert "<pre><code" not in html
    assert "DRAFT_OUTSIDE_SCOPE" in html and "DEFERRED_CAMPAIGN" in html


def test_sorted_mixed_scenario_payload_fields_are_siblings_not_children_of_invariants():
    # SQLite returns sorted payload keys. This ordering puts the Invariants
    # container before later scalar facts, unlike the original hand-built test
    # fixture. Rendering each key separately used to give those facts an
    # Invariants heading owner even though all their text remained present.
    payload = json.loads(json.dumps({
        "observable_outcome": "OBSERVABLE_OUTCOME_SENTINEL",
        "invariants": ["INVARIANT_SENTINEL"],
        "objective": "OBJECTIVE_SENTINEL",
        "actor": "ACTOR_SENTINEL",
    }, sort_keys=True))
    goal = {"goal_node_id":"GOAL-000101", "node_type":"use_case", "title":"Observe agreed intent",
            "payload":payload, "source_anchor":None}
    before = deepcopy(goal)
    text = render_goal(goal)
    tokens = MarkdownIt("commonmark", {"html":False}).parse(text)
    parents = {}
    stack = []
    for index, token in enumerate(tokens):
        if token.nesting == 1:
            stack.append((token.type, index))
        elif token.nesting == -1:
            stack.pop()
        elif token.type == "inline":
            for label in ("ACTOR_SENTINEL", "Invariants", "INVARIANT_SENTINEL",
                          "OBJECTIVE_SENTINEL", "OBSERVABLE_OUTCOME_SENTINEL"):
                if label in token.content:
                    parents[label] = tuple(stack)
    assert goal == before
    assert len(parents) == 5
    for label in ("ACTOR_SENTINEL", "Invariants", "OBJECTIVE_SENTINEL", "OBSERVABLE_OUTCOME_SENTINEL"):
        assert any(kind == "list_item_open" for kind, _index in parents[label]), label
    outer_lists = {next(index for kind, index in reversed(parents[label]) if kind == "bullet_list_open")
                   for label in ("ACTOR_SENTINEL", "Invariants", "OBJECTIVE_SENTINEL", "OBSERVABLE_OUTCOME_SENTINEL")}
    assert len(outer_lists) == 1
    invariants_item = next(index for kind, index in reversed(parents["Invariants"]) if kind == "list_item_open")
    assert ("list_item_open", invariants_item) in parents["INVARIANT_SENTINEL"]
    assert ("list_item_open", invariants_item) not in parents["OBJECTIVE_SENTINEL"]
    assert ("list_item_open", invariants_item) not in parents["OBSERVABLE_OUTCOME_SENTINEL"]
    assert text.index("ACTOR_SENTINEL") < text.index("INVARIANT_SENTINEL") < text.index("OBJECTIVE_SENTINEL")
    assert text.index("OBJECTIVE_SENTINEL") < text.index("OBSERVABLE_OUTCOME_SENTINEL")


def test_sequence_markdown_blocks_stay_inside_their_ordered_step():
    basis, draft, gaps = roadmap_inputs()
    sequence = basis["goals"][1]
    sequence["payload"]["normal_steps"] = [
        "```python\nfirst_example()\n```",
        "### SECOND_STEP_HEADING\n\nSECOND_STEP_PARAGRAPH\n\n- SECOND_STEP_ITEM",
        "THIRD_STEP_PARAGRAPH\n\n- THIRD_STEP_ITEM\n- THIRD_STEP_OTHER_ITEM",
        "LAST_STEP_SENTINEL",
    ]
    text = render_roadmap(basis, fingerprint="BLOCKS", draft_context=draft, gaps=gaps)
    tokens = MarkdownIt("commonmark", {"html":False}).parse(text)
    normal_label = next(index for index, token in enumerate(tokens)
                        if token.type == "inline" and any(child.type == "text" and child.content == "Normal Steps:"
                                                          for child in token.children or []))
    sequence_tokens = tokens[normal_label + 1:]
    first_list = next(index for index, token in enumerate(sequence_tokens) if token.type == "ordered_list_open")
    sequence_tokens = sequence_tokens[first_list:]
    list_level = sequence_tokens[0].level
    last = next(index for index, token in enumerate(sequence_tokens)
                if token.type == "ordered_list_close" and token.level == list_level)
    sequence_tokens = sequence_tokens[:last + 1]
    # One ordered list with four sibling step items. Nested bullet items must
    # not be mistaken for a fifth step or escape into a separate document.
    step_items = [token for token in sequence_tokens if token.type == "list_item_open"
                  and token.level == list_level + 1]
    assert len(step_items) == 4
    fence = next(token for token in sequence_tokens if token.type == "fence")
    heading = next(token for token in sequence_tokens if token.type == "heading_open")
    assert fence.content == "first_example()\n" and fence.level > list_level
    assert heading.level > list_level
    content = "\n".join(token.content for token in sequence_tokens)
    for sentinel in ("SECOND_STEP_HEADING", "SECOND_STEP_PARAGRAPH", "SECOND_STEP_ITEM",
                     "THIRD_STEP_PARAGRAPH", "THIRD_STEP_ITEM", "THIRD_STEP_OTHER_ITEM", "LAST_STEP_SENTINEL"):
        assert sentinel in content


def test_empty_roadmap_context_and_deep_policy_are_explicit_and_complete():
    basis, draft, _gaps = roadmap_inputs()
    nested = "DEEP_POLICY_SENTINEL"
    for number in range(12):
        nested = {f"level_{number}": [nested]}
    basis["milestones"][0]["exit_policy"]["deep_policy"] = nested
    text = render_roadmap(basis, fingerprint="CURRENT", draft_context=draft, gaps=[])
    assert "DEEP_POLICY_SENTINEL" in text and "Level 11" in text
    assert "model_facing_output_budget_exceeded" not in text
    assert not re.search(r"^#{7,} ", text, re.MULTILINE)
    for key in ("goals", "requirements", "milestones", "goal_edges"):
        basis[key] = []
    basis["answers"] = basis["correspondence"] = {}
    empty = render_roadmap(basis, fingerprint="EMPTY", draft_context={}, gaps=[])
    assert "No scenarios recorded" in empty and "No requirements recorded" in empty
    assert "No milestones recorded" in empty and "absence is not semantic completeness" in empty
    assert "No fields recorded (empty object)" in empty and "No items recorded (empty list)" in empty
