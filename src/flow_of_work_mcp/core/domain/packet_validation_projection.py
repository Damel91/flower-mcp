"""Pure deterministic standalone criterion/producer/consumer closure."""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import fingerprint, normalize_declarations
from flow_of_work_mcp.core.domain.identifiers import validate_requirement_id

CONTRACT_VERSION = 'flow.external_packet_validation_projection.v1'
CRITERION_RESPONSIBILITY_GAPS = frozenset({
    'criterion_authority_stale', 'criterion_unknown_or_retired', 'criterion_owner_missing',
    'verification_intent_missing', 'external_authority_missing', 'criterion_statement_id_only', 'criterion_disposition_missing',
    'criterion_disposition_invalid', 'criterion_implementation_owner_unexpected',
    'criterion_verification_target_invalid', 'criterion_verification_target_dependency_missing',
    'criterion_external_authority_unaccepted', 'criterion_external_authority_verification_missing',
})


def derive_packet_validation(snapshot: Mapping[str, object], *, consumer_scope: str = 'external_agent',
                             require_accepted_plan: bool = True) -> dict[str, object]:
    if consumer_scope not in {'external_agent', 'provider'}:
        raise ValueError('unsupported packet validation consumer scope')
    packet = snapshot['packet']
    plan = snapshot.get('plan') or {}
    state = snapshot['external']
    criteria = [dict(c) for c in state['criteria'] if c['active']]
    units = [dict(u) for u in plan.get('units', [])]
    gaps = []

    def gap(code: str, **context: object) -> None:
        gaps.append({'code': code, **context})

    version = int(state['validation_version'])
    strict = (version == 2 and consumer_scope == 'external_agent'
              and state.get('consumption_mode') == 'external_agent')
    plan_not_accepted = False
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
    elif plan['status'] != 'accepted' and (require_accepted_plan or not strict or plan['status'] != 'proposed'):
        plan_not_accepted = True
        if not strict:
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
        if consumer_scope == 'external_agent' and unit.get('mutation_target_binding_id') and not unit.get('target_description') and not unit.get('file_path'):
            gap('portable_target_context_missing', unit_key=key)
        if consumer_scope == 'external_agent' and unit.get('context_target_binding_ids'):
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
                gap('external_authority_missing', unit_key=key, authority_ref=intent['authority_ref'],
                    **({'criterion': criterion} if strict else {}))
        local = {intent['statement'] for intent in unit['verifies'] if intent['kind'] == 'unit_check'}
        for index, check in enumerate(unit.get('unit_checks', [])):
            if check not in local:
                expected = sorted(local)
                gap('unit_check_verification_missing', unit_key=key, statement=check,
                    field=f'units.{key}.unit_checks[{index}]', received=check,
                    expected=expected[:10], expected_count=len(expected), expected_truncated=len(expected) > 10)
        for contract in unit['provides']:
            contracts[(key, contract['name'])] = contract
    if strict:
        _check_criterion_responsibility(snapshot, criteria, owners, verification, closure, gap)
        if plan_not_accepted:
            gap('work_plan_not_accepted')
    for criterion in criteria:
        n = criterion['number']
        if not strict and not owners[n] and not verification[n]:
            gap('criterion_owner_missing', criterion=n)
        if not strict and not verification[n]:
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
    return {'contract_version': CONTRACT_VERSION if consumer_scope == 'external_agent' else 'flow.packet_validation_projection.v1',
            **({'validation_version': version} if strict else {}),
            'consumer_scope': consumer_scope, 'status': status,
            'authority_fingerprint': fingerprint(snapshot['authority_basis']),
            'spec_revision': int(packet['spec_revision']), 'plan_revision': int(plan.get('plan_revision') or 0),
            'criteria': criteria, 'units': projected_units, 'gaps': gaps,
            'next_gap': gaps[0] if gaps else None,
            'verification_claim': 'plan_constructibility_only'}


def _criterion_dispositions(state: Mapping[str, object]) -> dict[int, Mapping[str, object] | None]:
    dispositions = {}
    for declaration in state.get('criterion_dispositions', []):
        number = declaration['number']
        dispositions[number] = None if number in dispositions else declaration
    return dispositions


def _check_criterion_responsibility(snapshot, criteria, owners, verification, closure, gap) -> None:
    dispositions = _criterion_dispositions(snapshot['external'])
    construction = snapshot.get('construction') or {}
    stale_answers = bool(construction) and int(construction.get('packet_revision') or 0) != int(snapshot['packet']['spec_revision'])
    for criterion in criteria:
        number = criterion['number']
        try:
            validate_requirement_id(criterion['statement'])
        except ValueError:
            pass
        else:
            gap('criterion_statement_id_only', criterion=number, field=f'criteria.{number}.statement')
        declaration = dispositions.get(number)
        if not verification[number]:
            gap('verification_intent_missing', criterion=number)
        if number not in dispositions:
            gap('criterion_disposition_missing', criterion=number, field=f'criteria.{number}.disposition')
            continue
        if declaration is None or declaration.get('disposition') not in {
            'implementation', 'verification_only', 'external_authority',
        }:
            gap('criterion_disposition_invalid', criterion=number, field=f'criteria.{number}.disposition')
            continue
        disposition = declaration['disposition']
        criterion['disposition'] = disposition
        target = declaration.get('target')
        if isinstance(target, Mapping):
            criterion['target'] = dict(target)
        if disposition == 'implementation':
            if not owners[number]:
                gap('criterion_owner_missing', criterion=number, disposition=disposition)
            continue
        if owners[number]:
            gap('criterion_implementation_owner_unexpected', criterion=number, disposition=disposition)
        if disposition == 'verification_only':
            _check_verification_target(snapshot, number, target, dispositions, owners, verification[number], closure, gap)
        else:
            reference = target.get('ref') if isinstance(target, Mapping) and target.get('kind') == 'authority' else None
            authority = snapshot.get('resolved_authorities', {}).get(reference) if isinstance(reference, str) else None
            accepted_answer = isinstance(authority, Mapping) and authority.get('kind') == 'accepted_engineering_answer'
            if not accepted_answer or stale_answers:
                gap('criterion_external_authority_unaccepted', criterion=number, field=f'criteria.{number}.target',
                    authority_state='stale' if accepted_answer else 'unaccepted')
            if not reference or not any(row['kind'] == 'explicit_authority' and row.get('authority_ref') == reference
                                        for row in verification[number]):
                gap('criterion_external_authority_verification_missing', criterion=number)


def _check_verification_target(snapshot, number, target, dispositions, owners, intents, closure, gap) -> None:
    field = f'criteria.{number}.target'
    kind = target.get('kind') if isinstance(target, Mapping) else None
    if kind == 'baseline' and target.get('ref') in (snapshot.get('change') or {}).get('baseline_refs', []):
        return
    if kind != 'criterion' or type(target.get('criterion')) is not int or target['criterion'] <= 0:
        gap('criterion_verification_target_invalid', criterion=number, field=field)
        return
    target_number = target['criterion']
    target_packet = target.get('packet_id')
    packet = snapshot['packet']
    if target_packet is None or target_packet == snapshot.get('packet_id', packet.get('packet_id')):
        declaration = dispositions.get(target_number) or {}
        producers = owners.get(target_number, [])
        if target_number == number or declaration.get('disposition') != 'implementation' or not producers:
            gap('criterion_verification_target_invalid', criterion=number, field=field, target_criterion=target_number)
            return
        for verifier in dict.fromkeys(row['unit_key'] for row in intents):
            if verifier not in producers and not closure[verifier].intersection(producers):
                gap('criterion_verification_target_dependency_missing', criterion=number, field=field,
                    unit_key=verifier, target_criterion=target_number, producer_unit_keys=producers[:10],
                    producer_unit_count=len(producers))
    elif not _predecessor_criterion_has_owner(snapshot, target_packet, target_number):
        gap('criterion_verification_target_invalid', criterion=number, field=field,
            target_packet_id=target_packet, target_criterion=target_number)


def _predecessor_criterion_has_owner(snapshot, packet_id, number) -> bool:
    if packet_id not in snapshot['packet'].get('dependency_packet_ids', []):
        return False
    predecessor = next((item for item in snapshot.get('predecessor_packets', []) if item['packet_id'] == packet_id), None)
    if predecessor is None:
        return False
    packet = predecessor['packet']
    plan = predecessor.get('plan') or {}
    state = predecessor['external']
    if (packet.get('status') in {'cancelled', 'superseded'} or plan.get('status') != 'accepted'
            or plan.get('packet_revision') != packet['spec_revision']
            or state['criterion_statement_fingerprint'] != fingerprint(packet['completion_criteria'])):
        return False
    if not any(criterion['number'] == number and criterion['active'] for criterion in state['criteria']):
        return False
    if int(state['validation_version']) == 2:
        declaration = _criterion_dispositions(state).get(number) or {}
        if declaration.get('disposition') != 'implementation':
            return False
    return any(number in unit.get('implements', []) for unit in plan.get('units', []))
