import pytest

from flow_of_work_mcp import ChangeControlService, ImplementationPacketDraft, PacketWorkPlanDraft, WorkPlanUnit
from flow_of_work_mcp.application.external_work import ExternalWorkService
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, InputValidationError, RequirementConflictError
from tests.test_external_work import fixture


@pytest.mark.parametrize('mode_first', [True, False])
def test_strict_classification_is_spec_bound_replayable_and_does_not_change_provider_basis(tmp_path, mode_first):
    ledger, service, historic_ids, _ = fixture(tmp_path)
    changes = ChangeControlService(ledger)
    architecture = ledger.change_state(*historic_ids[:2])['packets'][0]['architecture_refs']
    packet = changes.add_packet(*historic_ids[:2], ImplementationPacketDraft(
        title='Strict handoff', objective='Expose and verify a stable output.', rationale='Verify the same producer separately.',
        completion_criteria=('The result is always 3.', 'A read-only check confirms the emitted result.'),
        in_scope=('src/output.py',), invariants=('The output remains deterministic.',),
        architecture_refs=tuple(architecture)), actor='host')['packets'][-1]
    ids = (*historic_ids[:2], packet['packet_id'])
    revs = {'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0}

    def write(operation, request_id, payload):
        return service.call(*ids, operation, actor='host', request_id=request_id, payload=payload)

    if mode_first:
        write('set_mode', 'strict-mode', {**revs, 'mode': 'external_agent'})
    assert write('upgrade_validation', 'strict-upgrade', revs)['validation_version'] == 2
    if not mode_first:
        assert 'criterion_dispositions' not in service.call(*ids, 'criteria')

    unit = WorkPlanUnit(client_unit_key='output', operation_kind='new_file', file_path='src/output.py',
        instructions=('Return the exact output.',), unit_checks=('Output is exactly 3.',), implements=(1,), verifies=(
            {'criterion': 1, 'kind': 'unit_check', 'statement': 'Output is exactly 3.'},
            {'criterion': 2, 'kind': 'unit_check', 'statement': 'Read the emitted output without modifying it.'},))
    proposed = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'], (unit,)),
        actor='host', request_id='strict-proposal')
    revs = {'expected_spec_revision': proposed['packet_revision'], 'expected_plan_revision': proposed['plan_revision']}
    if not mode_first:
        with pytest.raises(ChangeControlBlockedError, match='external_mode_not_selected'):
            write('export_plan', 'unselected-export', revs)
        assert write('export_plan', 'unselected-draft', {**revs, 'allow_draft': True})['draft']
        write('set_mode', 'strict-mode', {**revs, 'mode': 'external_agent'})
    assert service.call(*ids, 'criteria')['criterion_dispositions'] == []

    def accept():
        return ledger.transition_packet_work_plan(ids[0], proposed['work_plan_id'], proposed['plan_revision'], status='accepted',
            expected_packet_revision=proposed['packet_revision'], expected_current_plan_revision=proposed['plan_revision'],
            rationale='The responsibilities and checks are reviewed.', actor='host', request_id='strict-accept',
            acceptance_check=service.assert_plan_criterion_responsibility)

    with pytest.raises(ChangeControlBlockedError, match='packet_criterion_responsibility_unresolved') as missing:
        accept()
    assert missing.value.details['gap']['code'] == 'criterion_disposition_missing'
    assert ledger.packet_work_plan_state(*ids)['status'] == 'proposed'
    blocked = service.todo(*ids)
    assert not blocked['execution_allowed']
    assert blocked['next_gate']['repair']['operation']['operation'] == 'classify_criteria'
    with pytest.raises(ChangeControlBlockedError, match='criterion_disposition_missing') as export:
        write('export_plan', 'strict-export', revs)
    assert export.value.details['diagnostics'][0]['criterion'] == 1
    assert export.value.details['next_tool_call']['arguments']['packet_id'] == ids[2]
    assert all(row['implementation_state'] == 'pending' for row in service.criterion_progress(*ids)['criteria'])

    provider = service.provider_validation(*ids)
    declarations = [{'number': 1, 'disposition': 'implementation'},
                    {'number': 2, 'disposition': 'verification_only', 'target': {'kind': 'criterion', 'criterion': 1}}]
    with pytest.raises(InputValidationError, match='Classify every active criterion'):
        write('classify_criteria', 'strict-classification', {**revs, 'dispositions': declarations[:1]})
    with pytest.raises(ChangeControlBlockedError, match='stale_work_plan_revision'):
        write('classify_criteria', 'strict-classification', {**revs, 'expected_plan_revision': 0, 'dispositions': declarations})
    assert service.call(*ids, 'criteria')['criterion_dispositions'] == []
    classification = {**revs, 'dispositions': list(reversed(declarations))}
    receipt = write('classify_criteria', 'strict-classification', classification)
    assert receipt['dispositions'] == service.call(*ids, 'criteria')['criterion_dispositions'] == declarations
    assert service.provider_validation(*ids)['authority_fingerprint'] == provider['authority_fingerprint']
    assert 'criterion_dispositions' not in provider['authority_context']

    assert accept()['status'] == 'accepted'
    assert service.todo(*ids, unit_key='output')['execution_allowed']
    assert [row['implementation_state'] for row in service.criterion_progress(*ids)['criteria']] == ['pending', 'not_applicable']
    with pytest.raises(ChangeControlBlockedError, match='criterion_responsibility_plan_already_accepted'):
        write('classify_criteria', 'changed-on-accepted-plan', classification)
    with pytest.raises(RequirementConflictError, match='external_work_request_conflict'):
        write('classify_criteria', 'strict-classification', {**classification, 'dispositions': declarations})
    changes.refine_packet(*ids, invariants=('A material specification edit.',), actor='host')
    assert service.call(*ids, 'criteria')['criterion_dispositions'] == []
    with pytest.raises(ChangeControlBlockedError, match='stale_packet_revision'):
        write('classify_criteria', 'new-on-stale-spec', classification)
    assert write('classify_criteria', 'strict-classification', classification) == receipt

    reopened = type(ledger)(ledger.database_path)
    assert ExternalWorkService(reopened).call(*ids, 'classify_criteria', actor='host',
        request_id='strict-classification', payload=classification) == receipt


def test_unresolved_verification_authority_blocks_strict_plan_acceptance(tmp_path):
    ledger, service, historic_ids, _ = fixture(tmp_path)
    changes = ChangeControlService(ledger)
    architecture = ledger.change_state(*historic_ids[:2])['packets'][0]['architecture_refs']
    packet = changes.add_packet(*historic_ids[:2], ImplementationPacketDraft(
        title='Strict authority check', objective='Expose a stable output.', rationale='Verify it against bounded authority.',
        completion_criteria=('The result is always 3.',), in_scope=('src/output.py',),
        invariants=('The output remains deterministic.',), architecture_refs=tuple(architecture),
    ), actor='host')['packets'][-1]
    ids = (*historic_ids[:2], packet['packet_id'])
    revs = {'expected_spec_revision': packet['spec_revision'], 'expected_plan_revision': 0}
    service.call(*ids, 'set_mode', actor='host', request_id='authority-mode', payload={**revs, 'mode': 'external_agent'})
    service.call(*ids, 'upgrade_validation', actor='host', request_id='authority-upgrade', payload=revs)
    unit = WorkPlanUnit(client_unit_key='output', operation_kind='new_file', file_path='src/output.py',
        instructions=('Return the exact output.',), unit_checks=('Output is exactly 3.',), implements=(1,), verifies=(
            {'criterion': 1, 'kind': 'unit_check', 'statement': 'Output is exactly 3.'},
            {'criterion': 1, 'kind': 'explicit_authority', 'statement': 'Compare against the approved rule.',
             'authority_ref': 'decision:absent'},
        ))
    plan = ledger.create_packet_work_plan(ids[0], PacketWorkPlanDraft(ids[1], ids[2], packet['spec_revision'], (unit,)),
        actor='host', request_id='authority-proposal')
    service.call(*ids, 'classify_criteria', actor='host', request_id='authority-classification', payload={
        'expected_spec_revision': plan['packet_revision'], 'expected_plan_revision': plan['plan_revision'],
        'dispositions': [{'number': 1, 'disposition': 'implementation'}],
    })

    with pytest.raises(ChangeControlBlockedError, match='packet_criterion_responsibility_unresolved') as blocked:
        ledger.transition_packet_work_plan(ids[0], plan['work_plan_id'], plan['plan_revision'], status='accepted',
            expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'],
            rationale='Verify the planned authority.', actor='host', request_id='authority-accept',
            acceptance_check=service.assert_plan_criterion_responsibility)
    gap = {'code': 'external_authority_missing', 'criterion': 1, 'unit_key': 'output', 'authority_ref': 'decision:absent'}
    assert blocked.value.details['gap'] == gap
    assert ledger.packet_work_plan_state(*ids)['status'] == 'proposed'
    todo = service.todo(*ids)
    assert todo['execution_allowed'] is False
    assert todo['next_gate']['repair']['obligation'] == gap
    assert todo['next_gate']['repair']['operation']['operation'] == 'revise_unit'
