"""Pure deterministic standalone criterion/producer/consumer closure."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import fingerprint, normalize_declarations

CONTRACT_VERSION = 'flow.external_packet_validation_projection.v1'


def derive_packet_validation(snapshot: Mapping[str, object]) -> dict[str, object]:
    packet = snapshot['packet']
    plan = snapshot.get('plan') or {}
    state = snapshot['external']
    criteria = [dict(c) for c in state['criteria'] if c['active']]
    units = [dict(u) for u in plan.get('units', [])]
    gaps = []

    def gap(code: str, **context: object) -> None:
        gaps.append({'code': code, **context})

    version = int(state['validation_version'])
    if not version:
        gap('packet_validation_upgrade_required')
    elif state['criterion_statement_fingerprint'] != fingerprint(packet.get('completion_criteria', [])):
        gap('criterion_authority_stale')
    for field in ('objective', 'rationale', 'in_scope', 'invariants', 'completion_criteria'):
        if not packet.get(field):
            gap('packet_' + field + '_missing')
    if packet.get('unresolved_questions'):
        gap('packet_unresolved_authority_questions', questions=list(packet['unresolved_questions']))
    if not plan:
        gap('work_plan_missing')
    elif int(plan['packet_revision']) != int(packet['spec_revision']):
        gap('work_plan_stale')
    elif plan['status'] != 'accepted':
        gap('work_plan_not_accepted')
    # Existing host accepted engineering answers remain relevant. Provider-only
    # target/impact questions are not standalone investigation authority.
    construction = snapshot.get('construction') or {}
    engineering_questions = [question for question in construction.get('questions', [])
                             if question.get('question_key') not in {'target_selection', 'impact'}]
    for question in engineering_questions:
        if question.get('required'):
            if question.get('status') not in {'answered', 'waived'}:
                gap('engineering_answer_missing', question_id=question['question_id'])
    if engineering_questions and int(construction.get('packet_revision') or 0) != int(packet['spec_revision']):
        gap('engineering_answers_stale')
    by_key = {u['client_unit_key']: u for u in units}
    if len(by_key) != len(units):
        gap('unit_identity_ambiguous')
    active = {c['number']: c for c in criteria}
    owners = {n: [] for n in active}
    verification = {n: [] for n in active}
    contracts = {}
    closure = {}
    for key, unit in by_key.items():
        if unit.get('mutation_target_binding_id') and not unit.get('target_description') and not unit.get('file_path'):
            gap('portable_target_context_missing', unit_key=key)
        if unit.get('context_target_binding_ids'):
            gap('portable_context_content_missing', unit_key=key)
        declarations = normalize_declarations(unit)
        unit.update(declarations)
        pending = list(unit.get('depends_on', []))
        ancestors = set()
        while pending:
            predecessor = pending.pop()
            if predecessor in ancestors:
                continue
            ancestors.add(predecessor)
            if predecessor == key:
                gap('dependency_cycle', unit_key=key)
            elif predecessor not in by_key:
                gap('dependency_unit_missing', unit_key=key, producer_unit_key=predecessor)
            else:
                pending.extend(by_key[predecessor].get('depends_on', []))
        closure[key] = ancestors
        for criterion in unit['implements']:
            if criterion not in active:
                gap('criterion_unknown_or_retired', unit_key=key, criterion=criterion)
            else:
                owners[criterion].append(key)
        for intent in unit['verifies']:
            criterion = intent['criterion']
            if criterion not in active:
                gap('criterion_unknown_or_retired', unit_key=key, criterion=criterion)
            else:
                verification[criterion].append({'unit_key': key, **intent})
            if intent.get('authority_ref') and intent['authority_ref'] not in snapshot.get('resolved_authorities', {}):
                gap('external_authority_missing', unit_key=key, authority_ref=intent['authority_ref'])
        local = {intent['statement'] for intent in unit['verifies'] if intent['kind'] == 'unit_check'}
        for check in unit.get('unit_checks', []):
            if check not in local:
                gap('unit_check_verification_missing', unit_key=key, statement=check)
        for contract in unit['provides']:
            contracts[(key, contract['name'])] = contract
    for criterion in criteria:
        n = criterion['number']
        if not owners[n] and not verification[n]:
            gap('criterion_owner_missing', criterion=n)
        if not verification[n]:
            gap('verification_intent_missing', criterion=n)
        criterion['implementation_units'] = owners[n]
        criterion['verification'] = verification[n]
    projected_units = []
    for key, unit in by_key.items():
        uses = []
        for use in unit['requires']:
            producer = use['producer_unit_key']
            identity = (producer, use['contract_name'])
            contract = contracts.get(identity)
            if contract is None:
                gap('planned_contract_missing', unit_key=key, **use)
            elif producer not in closure[key]:
                gap('contract_not_in_dependency_closure', unit_key=key, **use)
            else:
                uses.append({**use, 'contract': contract, 'temporal_state': 'planned'})
        projected_units.append({**unit, 'resolved_requires': uses})
    stale = any(g['code'] in {'criterion_authority_stale', 'work_plan_stale', 'engineering_answers_stale'} for g in gaps)
    status = 'historical_unprojected' if not version else 'stale' if stale else 'open' if gaps else 'closed'
    return {'contract_version': CONTRACT_VERSION, 'consumer_scope': 'external_agent', 'status': status,
            'authority_fingerprint': fingerprint(snapshot['authority_basis']),
            'spec_revision': int(packet['spec_revision']), 'plan_revision': int(plan.get('plan_revision') or 0),
            'criteria': criteria, 'units': projected_units, 'gaps': gaps,
            'next_gap': gaps[0] if gaps else None,
            'verification_claim': 'plan_constructibility_only'}
