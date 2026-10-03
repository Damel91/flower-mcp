"""Current canonical intent reassessment and affected external-work admission.

Assessments are ordinary host declarations stored in the assurance event history.
This service neither investigates repositories nor certifies semantic truth.
"""
from __future__ import annotations

from typing import Mapping

from flow_of_work_mcp.core.domain.external_work import fingerprint
from flow_of_work_mcp.core.errors import ChangeControlBlockedError


_CLASSIFICATIONS = frozenset({'correction_within_intent', 'intent_change_required', 'needs_clarification'})
_PACKET_FIELDS = ('packet_id', 'title', 'objective', 'rationale', 'spec_revision',
                  'requirement_ids', 'goal_ids', 'in_scope', 'out_of_scope', 'invariants',
                  'completion_criteria', 'unresolved_questions')
_CHANGE_FIELDS = ('change_id', 'title', 'rationale', 'requirement_ids', 'goal_ids',
                  'source_refs', 'baseline_refs', 'milestone_id')
_MILESTONE_FIELDS = ('milestone_id', 'name', 'requirement_ids', 'dependency_closure_ids',
                     'entry_policy', 'exit_policy', 'risk_disposition')


class EngineerGateService:
    def __init__(self, ledger) -> None:
        self._ledger = ledger

    def finding_context(self, project_id: str, finding_id: str) -> Mapping[str, object]:
        with self._ledger.consistent_read():
            finding = self._ledger.finding_state(project_id, finding_id)
            return self._finding_context(project_id, finding)

    def _finding_context(self, project_id, finding):
        change = self._ledger.change_state(project_id, finding['change_id'])
        packet_id = finding.get('packet_id') or (finding['scope_ref'] if finding['scope_kind'] == 'packet' else '')
        packet = next((p for p in change.get('packets', []) if p['packet_id'] == packet_id), None)
        context, gaps = self._intent_context(project_id, change, packet,
            extra_requirements=(finding['scope_ref'],) if finding['scope_kind'] == 'requirement' else (),
            extra_goals=(finding['scope_ref'],) if finding['scope_kind'] in {'goal', 'use_case', 'scenario'} else (),
            milestone_id=finding['scope_ref'] if finding['scope_kind'] == 'milestone' else change.get('milestone_id'))
        if packet_id and packet is None:
            gaps.append({'reason': 'finding_packet_authority_missing', 'packet_id': packet_id})
        changes = list(self._ledger.list_changes(project_id))
        packets = {p['packet_id']: (c, p) for c in changes for p in c.get('packets', [])}
        graph = self._ledger.goal_graph(project_id)
        packet_goals = {key: _goal_closure(set(c.get('goal_ids', [])) | set(p.get('goal_ids', [])), graph.get('edges', []))
                        for key, (c, p) in packets.items()}
        lineage = {key: self._ledger.remediation_context(project_id, c['change_id'], key) or {}
                   for key, (c, _) in packets.items()}
        affected, scope_gaps = _affected(finding, packets, packet_goals, lineage)
        context['finding_scope'] = {'kind': finding['scope_kind'], 'reference': finding['scope_ref'], 'gaps': scope_gaps}
        gaps.extend(scope_gaps)
        if finding['scope_kind'] in {'change', 'requirement', 'goal', 'use_case', 'scenario', 'milestone'}:
            originals = []
            for key in sorted(affected):
                owner, original = packets[key]
                if original.get('purpose') == 'remediation':
                    continue
                semantic, missing = self._intent_context(project_id, owner, original, milestone_id=owner.get('milestone_id'))
                originals.append(semantic)
                gaps.extend(missing)
            context['affected_original_packets'] = originals
        disposition_event = next((e['event_id'] for e in reversed(finding.get('events', []))
                                  if e['event_type'] == 'finding_disposition_set'), None)
        finding_basis = _selected(finding, ('project_id', 'change_id', 'finding_id', 'packet_id', 'finding_kind',
                                         'severity', 'title', 'rationale', 'expected_correction', 'scope_kind', 'scope_ref',
                                         'source_anchor', 'implementation_ref', 'disposition', 'supersedes_finding_id'))
        finding_basis['disposition_event_id'] = disposition_event
        intent_fp, finding_fp = fingerprint(context), fingerprint(finding_basis)
        latest = finding.get('latest_intent_assessment')
        assessment = (latest or {}).get('assessment', {})
        current = bool(latest and not gaps and assessment.get('expected_intent_fingerprint') == intent_fp
                       and assessment.get('expected_finding_fingerprint') == finding_fp)
        return {**finding, 'status': 'success', 'intent_context': context, 'intent_fingerprint': intent_fp,
                'finding_fingerprint': finding_fp, 'assessment_current': current, 'gaps': gaps,
                'assessment_provenance': 'host_declared', 'semantic_truth_verified': False,
                'acceptance_inferred': False}

    def _intent_context(self, project_id, change, packet, *, extra_requirements=(), extra_goals=(), milestone_id=None):
        gaps = []
        requirement_ids = set((packet or {}).get('requirement_ids') or change.get('requirement_ids', []))
        goal_ids = set(change.get('goal_ids', [])) | set((packet or {}).get('goal_ids', []))
        requirement_ids.update(extra_requirements)
        goal_ids.update(extra_goals)
        requirements = []
        for row in self._ledger.traceability_matrix(project_id):
            if row['requirement_id'] not in requirement_ids:
                continue
            semantic = _selected(row, ('requirement_id', 'current_revision', 'title', 'statement', 'category', 'source_anchor'))
            history = self._ledger.requirement_history(project_id, row['requirement_id'])
            revision = next(r for r in history['revisions'] if r['revision'] == row['current_revision'])
            semantic.update(rationale=revision['rationale'], retired=row.get('lifecycle_status') == 'removed')
            requirements.append(semantic)
        requirements.sort(key=lambda r: r['requirement_id'])
        for missing in sorted(requirement_ids - {r['requirement_id'] for r in requirements}):
            gaps.append({'reason': 'intent_requirement_authority_missing', 'requirement_id': missing})
        for row in requirements:
            if row['retired']:
                gaps.append({'reason': 'intent_requirement_retired', 'requirement_id': row['requirement_id']})
        graph = self._ledger.goal_graph(project_id)
        goal_ids = _goal_closure(goal_ids, graph.get('edges', []))
        goals = [_selected(g, ('goal_node_id', 'node_type', 'title', 'payload', 'source_anchor'))
                 for g in graph.get('nodes', []) if g['goal_node_id'] in goal_ids]
        goals.sort(key=lambda g: g['goal_node_id'])
        edges = [_selected(e, ('source_goal_id', 'target_goal_id', 'relation'))
                 for e in graph.get('edges', [])
                 if e['source_goal_id'] in goal_ids and e['target_goal_id'] in goal_ids]
        edges.sort(key=lambda e: (e['source_goal_id'], e['target_goal_id'], str(e.get('relation'))))
        for missing in sorted(goal_ids - {g['goal_node_id'] for g in goals}):
            gaps.append({'reason': 'intent_goal_authority_missing', 'goal_node_id': missing})
        milestone = next((m for m in self._ledger.milestones(project_id) if m['milestone_id'] == milestone_id), None)
        if milestone_id and milestone is None:
            gaps.append({'reason': 'intent_milestone_authority_missing', 'milestone_id': milestone_id})
        answers = []
        risks = None
        if packet:
            construction = self._ledger.packet_construction_audit_for_packet(project_id, change['change_id'], packet['packet_id']) or {}
            if int(construction.get('packet_revision', 0)) == int(packet['spec_revision']):
                answers = [_selected(q, ('question_id', 'question_key', 'prompt', 'status', 'answer_summary',
                                        'answer_source', 'answer_temporal_authority', 'evidence_refs', 'policy_ref', 'waiver_rationale'))
                           for q in construction.get('questions', [])
                           if q.get('status') in {'answered', 'waived'} and q.get('question_key') not in {'target_selection', 'impact'}]
                answers.sort(key=lambda q: q['question_id'])
            pressure = self._ledger.latest_packet_pressure(project_id, change['change_id'], packet['packet_id'])
            if pressure and int(pressure['packet_revision']) == int(packet['spec_revision']):
                risks = _selected(pressure, ('residual_risks', 'accepted_risk_refs', 'challenge_questions', 'source'))
                if pressure.get('residual_risks') and not pressure.get('accepted_risk_refs'):
                    gaps.append({'reason': 'intent_residual_risk_authority_missing', 'packet_id': packet['packet_id'],
                                 'risks': pressure['residual_risks']})
            elif pressure and (pressure.get('residual_risks') or pressure.get('accepted_risk_refs')):
                gaps.append({'reason': 'intent_risk_authority_stale'})
        context = {'change': _selected(change, _CHANGE_FIELDS),
                   'packet': _selected(packet, _PACKET_FIELDS) if packet else None,
                   'requirements': requirements, 'goals': goals, 'goal_edges': edges,
                   'milestone': _selected(milestone, _MILESTONE_FIELDS) if milestone else None,
                   'accepted_engineering_answers': answers, 'accepted_risk_context': risks}
        return context, gaps

    def reassess_intent(self, project_id: str, finding_id: str, assessment: Mapping[str, object],
                        *, actor: str, request_id: str) -> Mapping[str, object]:
        value = _assessment(assessment)
        actor, request_id = _text(actor, 'actor'), _text(request_id, 'request_id')
        with self._ledger.atomic():
            replay = self._ledger.intent_reassessment_replay(project_id, finding_id, value, actor=actor, request_id=request_id)
            if replay is not None:
                return replay
            context = self.finding_context(project_id, finding_id)
            if context['intent_fingerprint'] != value['expected_intent_fingerprint']:
                raise ChangeControlBlockedError('intent_reassessment_authority_stale', details={'intent_fingerprint': context['intent_fingerprint']})
            if context['finding_fingerprint'] != value['expected_finding_fingerprint']:
                raise ChangeControlBlockedError('intent_reassessment_finding_stale', details={'finding_fingerprint': context['finding_fingerprint']})
            if context['gaps'] and value['classification'] == 'correction_within_intent':
                raise ChangeControlBlockedError('intent_reassessment_authority_incomplete', details={'gaps': context['gaps']})
            return self._ledger.record_intent_reassessment(project_id, finding_id, value, actor=actor,
                                                          request_id=request_id, intent_context=context['intent_context'])

    def projection(self, project_id: str, packet_id: str) -> Mapping[str, object]:
        with self._ledger.consistent_read():
            changes = list(self._ledger.list_changes(project_id))
            packets = {p['packet_id']: (c, p) for c in changes for p in c.get('packets', [])}
            if packet_id not in packets:
                raise ChangeControlBlockedError('packet_not_found')
            graph = self._ledger.goal_graph(project_id)
            packet_goals = {key: _goal_closure(set(c.get('goal_ids', [])) | set(p.get('goal_ids', [])), graph.get('edges', []))
                            for key, (c, p) in packets.items()}
            lineage = {key: self._ledger.remediation_context(project_id, c['change_id'], key) or {}
                       for key, (c, _) in packets.items()}
            blockers, relevant = [], []
            for change in changes:
                for finding in self._ledger.findings_for_change(project_id, change['change_id']):
                    linked = next((link for link in finding.get('fixing_packets', []) if link['packet_id'] == packet_id), None)
                    gating = _gating(finding)
                    if not gating and linked is None:
                        continue
                    affected, scope_gaps = _affected(finding, packets, packet_goals, lineage)
                    if packet_id not in affected and linked is None:
                        continue
                    context = self._finding_context(project_id, finding)
                    classification = ((context.get('latest_intent_assessment') or {}).get('assessment') or {}).get('classification')
                    reason = 'semantic_finding_unresolved'
                    corrective = packets[packet_id][1].get('purpose') == 'remediation' and linked is not None
                    admitted = not gating
                    if corrective and gating:
                        if not context['assessment_current']:
                            reason = 'intent_reassessment_required' if not context.get('latest_intent_assessment') else 'intent_reassessment_stale'
                        elif classification != 'correction_within_intent':
                            reason = classification
                        elif not self._regression_declared(project_id, packets[packet_id][0], packets[packet_id][1], linked):
                            reason = 'corrective_regression_obligation_missing'
                        elif not scope_gaps:
                            admitted = True
                    if scope_gaps and gating:
                        reason = 'finding_scope_unresolved'
                    item = {'finding_id': finding['finding_id'], 'finding_kind': finding.get('finding_kind', 'unspecified'),
                            'title': finding['title'], 'rationale': finding['rationale'],
                            'expected_correction': finding['expected_correction'],
                            'latest_intent_assessment': context.get('latest_intent_assessment'),
                            'gating': gating,
                            'disposition': finding['disposition'], 'scope_kind': finding['scope_kind'], 'scope_ref': finding['scope_ref'],
                            'assessment_current': context['assessment_current'], 'classification': classification,
                            'intent_fingerprint': context['intent_fingerprint'], 'finding_fingerprint': context['finding_fingerprint'],
                            'corrective_admitted': corrective and admitted, 'scope_gaps': scope_gaps,
                            'required_regression_evidence': linked.get('required_regression_evidence') if linked else None}
                    relevant.append(item)
                    if not admitted:
                        blockers.append({**item, 'reason': reason})
            gate = None
            if blockers:
                first = blockers[0]
                gate = {'tool': 'fow_assurance', 'operation': 'get_finding',
                        'arguments': {'project_id': project_id, 'finding_id': first['finding_id'], 'operation': 'get_finding'},
                        'required_inputs': ['actor'],
                        'reason': first['reason'], 'obligation': 'Read current canonical intent, reassess it explicitly, and prepare ordinary in-scope corrective work or resolve the finding through its governed disposition.'}
            return {'status': 'blocked' if blockers else 'success', 'execution_allowed': not blockers,
                    'blockers': blockers, 'relevant_findings': relevant, 'next_gate': gate,
                    'provenance': 'host_declared', 'semantic_truth_verified': False, 'acceptance_inferred': False}

    def _regression_declared(self, project_id, change, packet, link):
        statement = link.get('required_regression_evidence')
        if not isinstance(statement, str) or not statement.strip():
            return False
        plan = self._ledger.packet_work_plan_state(project_id, change['change_id'], packet['packet_id'])
        if not plan or plan.get('status') != 'accepted' or int(plan['packet_revision']) != int(packet['spec_revision']):
            return False
        return any(statement in unit.get('unit_checks', []) and any(
            intent.get('kind') == 'unit_check' and intent.get('statement') == statement
            for intent in unit.get('verifies', [])) for unit in plan.get('units', []))

    def execution_guard(self, project_id: str, packet_id: str) -> None:
        result = self.projection(project_id, packet_id)
        if not result['execution_allowed']:
            raise ChangeControlBlockedError('engineer_semantic_findings_open', details=result)


def _selected(value, keys):
    return {key: value.get(key) for key in keys}


def _goal_closure(ids, edges):
    result = set(ids)
    pending = list(ids)
    while pending:
        selected = pending.pop()
        for edge in edges:
            if edge['source_goal_id'] == selected and edge['target_goal_id'] not in result:
                result.add(edge['target_goal_id'])
                pending.append(edge['target_goal_id'])
    return result


def _gating(finding):
    kind = finding.get('finding_kind', 'unspecified')
    return (kind == 'semantic' and finding['disposition'] in {'open', 'confirmed'}) or (
        kind == 'unspecified' and finding['severity'] in {'high', 'critical'} and finding['disposition'] == 'confirmed')


def _affected(finding, packets, packet_goals, lineage):
    kind, ref = finding['scope_kind'], finding['scope_ref']
    owner = finding['change_id']
    gaps = []
    if kind == 'packet':
        affected = {ref} if ref in packets and packets[ref][0]['change_id'] == owner else set()
        if not affected or (finding.get('packet_id') and finding['packet_id'] != ref):
            gaps.append({'reason': 'finding_packet_scope_inconsistent'})
    elif kind == 'change':
        affected = {key for key, (change, _) in packets.items() if change['change_id'] == ref} if ref == owner else set()
        if ref != owner:
            gaps.append({'reason': 'finding_change_scope_inconsistent'})
    elif kind == 'requirement':
        affected = {key for key, (change, packet) in packets.items()
                    if ref in (packet.get('requirement_ids') or change.get('requirement_ids', []))}
    elif kind in {'goal', 'use_case', 'scenario'}:
        affected = {key for key in packets if ref in packet_goals[key]}
    elif kind == 'milestone':
        affected = {key for key, (change, _) in packets.items() if change.get('milestone_id') == ref}
    else:
        primary = finding.get('packet_id')
        affected = {primary} if primary in packets and packets[primary][0]['change_id'] == owner else set()
        if not affected:
            gaps.append({'reason': 'finding_scope_identity_unresolved'})
    if not affected and not gaps:
        gaps.append({'reason': 'finding_scope_identity_unresolved'})
    if gaps:
        primary = finding.get('packet_id')
        if primary in packets and packets[primary][0]['change_id'] == owner:
            affected.add(primary)
        elif not affected:
            affected.update(key for key, (change, _) in packets.items() if change['change_id'] == owner)
    while True:
        downstream = {key for key, (_, packet) in packets.items()
                      if set(packet.get('dependency_packet_ids', [])) & affected
                      or lineage.get(key, {}).get('predecessor_packet_id') in affected}
        added = downstream - affected
        if not added:
            break
        affected.update(added)
    return affected, gaps


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ValueError(field + ' must be nonempty text of at most 8000 characters')
    return value.strip()


def _assessment(value):
    required = {'expected_intent_fingerprint', 'expected_finding_fingerprint', 'classification', 'rationale'}
    optional = {'technical_decisions', 'evidence_refs'}
    if not isinstance(value, Mapping) or not required.issubset(value) or set(value) - required - optional:
        raise ValueError('assessment requires exact declared reassessment fields')
    result = {field: _text(value[field], field) for field in required}
    if result['classification'] not in _CLASSIFICATIONS:
        raise ValueError('unsupported intent reassessment classification')
    for field in ('expected_intent_fingerprint', 'expected_finding_fingerprint'):
        digest = result[field]
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError(field + ' must be a lowercase SHA-256 fingerprint')
    for field in optional:
        items = value.get(field, [])
        if not isinstance(items, (tuple, list)) or len(items) > 128:
            raise ValueError(field + ' must be a bounded string list')
        normalized = [_text(item, field) for item in items]
        if len(set(normalized)) != len(normalized):
            raise ValueError(field + ' must not repeat entries')
        result[field] = normalized
    return result
