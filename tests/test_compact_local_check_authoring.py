"""Write local checks once without changing canonical plans or execution guards."""
from copy import deepcopy

import pytest

from flow_of_work_mcp.application.operation_contracts import operation_contract
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError
from tests.test_external_work import fixture
from tests.test_plan_authoring_repair import dump
from tests.test_pvp_temporal_authoring import accept, services


FLAG = "unit_checks_from_verifies"


def replace_plan(plans, ids, previous, units, *, request_id="compact-replace"):
    return plans.replace_plan(*ids, {"units": units}, answers=(),
        expected_packet_revision=previous["packet_revision"],
        expected_current_plan_revision=previous["plan_revision"],
        declared_spec_revision=previous["packet_revision"],
        declared_plan_revision=previous["plan_revision"],
        actor="engineer", request_id=request_id)


def compact_unit(unit):
    return {**{key: value for key, value in unit.items() if key != "unit_checks"}, FLAG: True}


def test_compact_replace_canonical_checks_and_normalized_replay(tmp_path):
    ledger, external, ids, _ = fixture(tmp_path)
    plans, _ = services(ledger)
    previous = ledger.packet_work_plan_state(*ids)
    explicit = deepcopy(previous["units"])
    first = explicit[0]["unit_checks"][0]
    second = "Verify that increment does no I/O."
    explicit[0]["unit_checks"].append(second)
    explicit[0]["verifies"].extend([
        {"criterion": 2, "kind": "unit_check", "statement": first},
        {"criterion": 1, "kind": "unit_check", "statement": second},
    ])
    submitted = [compact_unit(explicit[0]), explicit[1]]
    submitted = deepcopy(submitted)
    submitted[0]["verifies"][0]["statement"] = f"  {first}  "
    proposed = replace_plan(plans, ids, previous, submitted)
    actual = proposed["units"][0]
    assert actual["unit_checks"] == [first, second]
    assert actual["verifies"] == explicit[0]["verifies"] and FLAG not in actual
    assert proposed["units"][1] == previous["units"][1]
    revs = accept(plans, ids, proposed, request_id="accept-compact")
    assert external.validation(*ids, detail="full")["validation"]["status"] == "closed"
    exported = external.call(*ids, "export_plan", actor="engineer", request_id="compact-export", payload=revs)
    assert first in exported["content"] and second in exported["content"]
    assert FLAG not in exported["content"] and exported["draft"] is False
    before = dump(ledger)
    # replace_plan identifies the normalized command, including when its syntax differs.
    replay = replace_plan(plans, ids, previous, explicit)
    assert replay["replayed"] and replay["authoring_receipt"] == proposed["authoring_receipt"]
    assert dump(ledger) == before


@pytest.mark.parametrize("patch,match", [
    ({FLAG: 1}, "must be true"),
    ({FLAG: False}, "must be true"),
    ({FLAG: True, "unit_checks": []}, "cannot be combined"),
    ({FLAG: True}, "explicit full verifies"),
    ({FLAG: True, "verifies": []}, "at least one local"),
    ({FLAG: True, "verifies": [{"criterion": 1, "kind": "oracle", "statement": "Deferred."}]}, "at least one local"),
    ({FLAG: True, "verifies": [{"criterion": True, "kind": "unit_check", "statement": "Not a criterion."}]}, "positive integer"),
])
def test_bad_compact_revision_never_writes_or_derives_an_obligation(tmp_path, patch, match):
    ledger, _, ids, revs = fixture(tmp_path)
    plans, _ = services(ledger)
    before = dump(ledger)
    with pytest.raises(ValueError, match=match):
        plans.mutate_plan(*ids, operation="revise_unit", client_unit_key="producer", unit_patch=patch,
            expected_packet_revision=revs["expected_spec_revision"],
            expected_current_plan_revision=revs["expected_plan_revision"],
            actor="engineer", request_id="bad-compact")
    assert dump(ledger) == before


def test_revise_replaces_both_arrays_and_replay_uses_raw_identity(tmp_path):
    ledger, external, ids, revs = fixture(tmp_path)
    plans, _ = services(ledger)
    previous = ledger.packet_work_plan_state(*ids)
    verifies = deepcopy(previous["units"][0]["verifies"])
    verifies[0]["statement"] = "Check the exact public increment signature and result."
    arguments = {"operation": "revise_unit", "client_unit_key": "producer",
        "unit_patch": {FLAG: True, "verifies": verifies},
        "expected_packet_revision": revs["expected_spec_revision"],
        "expected_current_plan_revision": revs["expected_plan_revision"],
        "actor": "engineer", "request_id": "compact-patch"}
    proposed = plans.mutate_plan(*ids, **arguments)
    assert proposed["units"][0]["unit_checks"] == [verifies[0]["statement"]]
    assert proposed["units"][0]["verifies"] == verifies and FLAG not in proposed["units"][0]
    assert proposed["units"][1] == previous["units"][1]
    assert external.validation(*ids)["execution_allowed"] is False
    before = dump(ledger)
    with pytest.raises(ChangeControlBlockedError, match="stale_current_work_plan_revision"):
        plans.mutate_plan(*ids, **{**arguments, "request_id": "different-key"})
    with pytest.raises(RequirementConflictError, match="replay payload"):
        plans.mutate_plan(*ids, **{**arguments, "unit_patch": {
            "unit_checks": [verifies[0]["statement"]], "verifies": verifies}})
    assert plans.mutate_plan(*ids, **arguments)["replayed"] is True
    assert dump(ledger) == before


def test_complete_add_requires_explicit_mode_and_keeps_target_guard(tmp_path):
    ledger, _, ids, _ = fixture(tmp_path)
    _, author = services(ledger)
    unit = {"client_unit_key": "document-check", "operation_kind": "new_file", "file_path": "docs/check.md",
        "instructions": ["Document the expected result."], FLAG: True,
        "verifies": [{"criterion": 1, "kind": "unit_check", "statement": "Example yields the next number."}]}
    args = {"unit": unit, "actor": "engineer", "request_id": "compact-add"}
    ledger.set_external_work_mode(*ids, "provider")
    before = dump(ledger)
    with pytest.raises(ChangeControlBlockedError, match="compact_local_checks_require_external_agent_mode"):
        author.add_unit(*ids, **args)
    assert dump(ledger) == before
    ledger.set_external_work_mode(*ids, "external_agent")
    before = dump(ledger)
    with pytest.raises(ValueError, match="server-owned"):
        author.add_unit(*ids, **{**args, "unit": {**unit, "mutation_target_binding_id": "invented"}})
    assert dump(ledger) == before
    result = author.add_unit(*ids, **args)
    intent = ledger.packet_unit_authoring_intent(*ids, unit["client_unit_key"])
    assert result["state"] == "unit_added" and FLAG not in intent["unit"]
    assert intent["unit"]["unit_checks"] == [unit["verifies"][0]["statement"]]
    before = dump(ledger)
    assert author.add_unit(*ids, **args)["replayed"] is True
    assert dump(ledger) == before


def test_compact_does_not_supply_missing_criterion_or_change_legacy_provider_form(tmp_path):
    ledger, external, ids, _ = fixture(tmp_path)
    plans, _ = services(ledger)
    previous = ledger.packet_work_plan_state(*ids)
    units = deepcopy(previous["units"])
    units[0] = compact_unit(units[0])
    units[0].update(implements=[], verifies=[{"criterion": 2, "kind": "unit_check", "statement": "Check successor behavior."}])
    ledger.set_external_work_mode(*ids, "provider")
    before = dump(ledger)
    with pytest.raises(ChangeControlBlockedError, match="compact_local_checks_require_external_agent_mode"):
        replace_plan(plans, ids, previous, units)
    assert dump(ledger) == before
    # Provider plans still accept the explicit legacy spelling.
    replace_plan(plans, ids, previous, previous["units"], request_id="explicit-provider")
    ledger.set_external_work_mode(*ids, "external_agent")
    proposed = replace_plan(plans, ids, ledger.packet_work_plan_state(*ids), units)
    accept(plans, ids, proposed, request_id="accept-incomplete-criterion")
    result = external.validation(*ids, detail="full")
    assert not result["execution_allowed"]
    assert any(gap["code"] == "criterion_owner_missing" and gap["criterion"] == 1
               for gap in result["validation"]["gaps"])


@pytest.mark.parametrize("operation", ["add_unit", "replace_plan", "revise_unit"])
def test_compact_authoring_is_discoverable_without_changing_legacy_examples(operation):
    guidance = operation_contract("fow_packet_author", operation)["guidance"]
    unit = guidance["work_plan"]["unit"] if operation == "replace_plan" else guidance["unit"]
    assert unit["compact_local_checks"]["example"][FLAG] is True
    assert "external_agent" in unit["compact_local_checks"]["scope"]
    assert "unit_checks" not in unit["compact_local_checks"]["example"]
