"""Standalone plan/PVP projection, artifacts and durable external work reports."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping

from flow_of_work_mcp.application.change_control import ChangeControlService
from flow_of_work_mcp.application.external_plan_markdown import render_plan
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind, ArtifactMapping
from flow_of_work_mcp.core.domain.change_control import PACKET_INACTIVE_STATUS_VALUES
from flow_of_work_mcp.core.domain.external_work import (canonical_json, fields, fingerprint, number, objects, strings, text)
from flow_of_work_mcp.core.domain.packet_validation_projection import derive_packet_validation
from flow_of_work_mcp.core.errors import ChangeControlBlockedError, RequirementConflictError

READ_OPERATIONS = frozenset({'criteria', 'validation', 'todo'})
MUTATION_OPERATIONS = frozenset({'set_mode', 'upgrade_validation', 'add_criterion', 'edit_criterion', 'remove_criterion', 'reconcile_criteria', 'export_plan', 'report_outcome', 'reconcile_outcome'})


class ExternalWorkService:
    def __init__(self, ledger, *, execution_guard: Callable[[str, str], None] | None = None, engineer_projection=None) -> None:
        self._ledger = ledger
        self._changes = ChangeControlService(ledger)
        self._execution_guard = execution_guard
        self._engineer_projection = engineer_projection

    def _assert_execution_allowed(self, snapshot) -> None:
        if snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES:
            raise ChangeControlBlockedError('external_packet_inactive', details={'packet_status': snapshot['packet']['status']})
        if self._execution_guard is not None:
            self._execution_guard(snapshot['project_id'], snapshot['packet_id'])

    def mode_for_packet(self, project_id: str, packet_id: str) -> str:
        with self._ledger.consistent_read():
            for change in self._ledger.list_changes(project_id):
                if any(p['packet_id'] == packet_id for p in change.get('packets', [])):
                    return str(self._ledger.external_work_state(project_id, change['change_id'], packet_id)['consumption_mode'])
        raise ChangeControlBlockedError('packet_not_found')

    def call(self, project_id: str, change_id: str, packet_id: str, operation: str,
             *, actor: str = '', request_id: str = '', payload: Mapping[str, object] | None = None) -> Mapping[str, object]:
        operation = text(operation, 'operation')
        payload = dict(payload or {})
        if operation in READ_OPERATIONS:
            if operation == 'criteria':
                fields(payload, set(), operation)
                with self._ledger.consistent_read():
                    state = self._ledger.external_work_state(project_id, change_id, packet_id)
                    return {'status': 'success', 'criteria': state['criteria'], 'history': state['criterion_history'],
                            'validation_version': state['validation_version']}
            if operation == 'validation':
                fields(payload, {'detail'}, operation)
                return self.validation(project_id, change_id, packet_id, detail=str(payload.get('detail', 'standard')))
            fields(payload, {'unit_key'}, operation)
            return self.todo(project_id, change_id, packet_id, unit_key=str(payload.get('unit_key', '')))
        if operation not in MUTATION_OPERATIONS:
            raise ValueError('unsupported external work operation')
        actor = text(actor, 'actor')
        request_id = text(request_id, 'request_id')
        request_fingerprint = fingerprint({'change_id': change_id, 'packet_id': packet_id, 'operation': operation,
                                          'actor': actor, 'payload': payload})
        with self._ledger.atomic():
            replay = self._ledger.external_work_request_replay(project_id, request_id, request_fingerprint)
            if replay is not None:
                return replay
            snapshot = self._snapshot(project_id, change_id, packet_id)
            if operation == 'report_outcome':
                result = self._report(snapshot, payload, actor)
            elif operation == 'reconcile_outcome':
                result = self._reconcile(snapshot, payload)
            elif operation == 'export_plan':
                result = self._export(snapshot, payload, actor, request_id)
            elif operation == 'set_mode':
                fields(payload, {'mode', 'expected_spec_revision', 'expected_plan_revision'}, operation)
                self._expect(snapshot, payload, plan_required=True)
                if payload.get('mode') != 'external_agent':
                    raise ValueError('mode must explicitly be external_agent')
                # Any admitted provider command/receipt is an ownership boundary,
                # including unknown writes; selecting a lens never erases it.
                if self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id) or self._ledger.packet_provider_receipts(project_id, change_id, packet_id):
                    raise ChangeControlBlockedError('external_mode_provider_effect_present')
                self._ledger.set_external_work_mode(project_id, change_id, packet_id, 'external_agent')
                result = {'status': 'success', 'consumption_mode': 'external_agent'}
            elif operation == 'upgrade_validation':
                fields(payload, {'expected_spec_revision', 'expected_plan_revision'}, operation)
                self._expect(snapshot, payload, plan_required=True)
                self._ledger.upgrade_external_criteria(project_id, change_id, packet_id,
                                                      list(snapshot['packet']['completion_criteria']),
                                                      spec_revision=snapshot['packet']['spec_revision'], actor=actor)
                result = {'status': 'success', 'validation_version': 1,
                          'criteria': self._ledger.external_work_state(project_id, change_id, packet_id)['criteria']}
            elif operation == 'reconcile_criteria':
                result = self._reconcile_criteria(snapshot, payload, actor, request_id)
            else:
                result = self._criterion(snapshot, operation, payload, actor, request_id)
            self._ledger.record_external_work_request(project_id, request_id, request_fingerprint, result,
                                                      actor=actor, operation=operation)
            return result

    def _snapshot(self, project_id: str, change_id: str, packet_id: str, *, _cache=None, _path=()) -> dict[str, object]:
        if packet_id in _path:
            raise ChangeControlBlockedError('packet_dependency_cycle', details={'packet_ids': [*_path, packet_id]})
        cache = {} if _cache is None else _cache
        if packet_id in cache:
            return cache[packet_id]
        change = self._ledger.change_state(project_id, change_id)
        packet = next((p for p in change['packets'] if p['packet_id'] == packet_id), None)
        if packet is None:
            raise ChangeControlBlockedError('packet_not_found')
        milestone_id = str(change.get('milestone_id') or '')
        milestone = None
        if milestone_id:
            linked = next((m for m in self._ledger.milestones(project_id)
                           if m['milestone_id'] == milestone_id), None)
            if linked is not None:
                milestone = {k: linked.get(k) for k in ('milestone_id', 'name', 'requirement_ids',
                    'dependency_closure_ids', 'entry_policy', 'exit_policy', 'risk_disposition')}
        predecessors = [self._snapshot(project_id, change_id, identity, _cache=cache, _path=(*_path, packet_id))
                        for identity in packet.get('dependency_packet_ids', [])]
        plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id)
        external = self._ledger.external_work_state(project_id, change_id, packet_id)
        requirement_ids = set(packet.get('requirement_ids') or change.get('requirement_ids', []))
        requirements = [dict(r) for r in self._ledger.traceability_matrix(project_id) if r['requirement_id'] in requirement_ids]
        for requirement in requirements:
            history = self._ledger.requirement_history(project_id, requirement['requirement_id'])
            semantic_revision = next(r for r in history['revisions'] if r['revision'] == requirement['current_revision'])
            requirement['rationale'] = semantic_revision['rationale']
        graph = self._ledger.goal_graph(project_id)
        goal_ids = set(packet.get('goal_ids', [])) | set(change.get('goal_ids', []))
        # Resolve connected goal references into the artifact rather than leave
        # essential Goal Graph IDs requiring an online lookup.
        pending_goals = set(goal_ids)
        while pending_goals:
            selected_goal = pending_goals.pop()
            for edge in graph.get('edges', []):
                if edge['source_goal_id'] == selected_goal and edge['target_goal_id'] not in goal_ids:
                    goal_ids.add(edge['target_goal_id'])
                    pending_goals.add(edge['target_goal_id'])
        goals = [dict(g) for g in graph.get('nodes', []) if g['goal_node_id'] in goal_ids]
        goal_edges = [dict(e) for e in graph.get('edges', []) if e['source_goal_id'] in goal_ids and e['target_goal_id'] in goal_ids]
        construction = self._ledger.packet_construction_audit_for_packet(project_id, change_id, packet_id) or {}
        answers = [{k: q.get(k) for k in ('question_id', 'question_key', 'prompt', 'status', 'answer_summary',
                    'answer_source', 'answer_temporal_authority', 'evidence_refs', 'policy_ref', 'waiver_rationale')}
                   for q in construction.get('questions', []) if q.get('status') in {'answered', 'waived'}
                   and q.get('question_key') not in {'target_selection', 'impact'}]
        pressure = self._ledger.latest_packet_pressure(project_id, change_id, packet_id)
        pressure_current = pressure and int(pressure['packet_revision']) == int(packet['spec_revision'])
        pressure_context = ({k: pressure[k] for k in ('packet_revision', 'residual_risks', 'challenge_questions', 'accepted_risk_refs', 'source', 'actor')}
                            if pressure_current else None)
        pressure_stale = bool(pressure and not pressure_current and (pressure['residual_risks'] or pressure['accepted_risk_refs']))
        resolved = {}
        for answer in answers:
            for ref in [*answer.get('evidence_refs', []), answer.get('policy_ref')]:
                if ref and answer.get('answer_summary'):
                    resolved[str(ref)] = {'kind': 'accepted_engineering_answer', 'content': answer['answer_summary'], 'provenance': answer.get('answer_source')}
        refs = {v.get('authority_ref') for u in (plan or {}).get('units', []) for v in u.get('verifies', []) if v.get('authority_ref')}
        refs.update('campaign:' + str(c) for c in packet.get('required_campaign_ids', []))
        campaigns = []
        # Only explicit campaign/oracle references enter authority fingerprint.
        for campaign in self._ledger.campaigns_for_change(project_id, change_id):
            campaign_id = str(campaign['campaign_id'])
            state = None
            if 'campaign:' + campaign_id in refs or any(str(ref).startswith('oracle:') for ref in refs):
                state = self._ledger.campaign_authority_state(project_id, campaign_id)
                semantic = {k: state.get(k) for k in ('campaign_id', 'revision', 'fingerprint', 'status', 'qualification', 'constructibility',
                    'scope', 'cases', 'obligations', 'obligation_bindings', 'oracles', 'oracle_bindings')}
                if 'campaign:' + campaign_id in refs:
                    resolved['campaign:' + campaign_id] = semantic
                    campaigns.append(semantic)
                for oracle in state.get('oracles', []):
                    ref = 'oracle:' + str(oracle['oracle_id'])
                    if ref in refs:
                        resolved[ref] = dict(oracle)
        basis_packet = {k: packet.get(k) for k in ('packet_id', 'title', 'objective', 'rationale', 'spec_revision', 'completion_criteria',
                         'requirement_ids', 'goal_ids', 'in_scope', 'out_of_scope', 'invariants', 'unresolved_questions', 'dependency_packet_ids')}
        basis_plan = {k: (plan or {}).get(k) for k in ('work_plan_id', 'plan_revision', 'packet_revision', 'status', 'units')}
        basis_change = {k: change.get(k) for k in ('change_id', 'title', 'rationale', 'requirement_ids', 'goal_ids', 'source_refs', 'baseline_refs', 'milestone_id')}
        semantic_requirements = [{**{k: r.get(k) for k in ('requirement_id', 'current_revision', 'title', 'statement', 'category', 'rationale', 'source_anchor')},
                                  'retired': r['lifecycle_status'] == 'removed'} for r in requirements]
        authority_basis = {'project_id': project_id, 'change_id': change_id, 'change': basis_change, 'packet': basis_packet,
                           'plan': basis_plan, 'criteria': external['criteria'], 'requirements': semantic_requirements,
                           'goals': goals, 'goal_edges': goal_edges, 'accepted_answers': answers, 'accepted_risk_context': pressure_context, 'referenced_authority': resolved,
                           'predecessor_authority': [{'packet_id': predecessor['packet_id'], 'authority_fingerprint': fingerprint(predecessor['authority_basis'])}
                                                     for predecessor in predecessors]}
        if milestone_id:
            authority_basis['milestone'] = milestone
        snapshot = {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id, 'packet': packet, 'change': basis_change,
                'plan': plan, 'external': external, 'requirements': requirements, 'goals': goals, 'milestone': milestone,
                'predecessor_packets': predecessors,
                'construction': construction, 'answers': answers, 'resolved_authorities': resolved,
                'goal_edges': goal_edges, 'pressure_context': pressure_context, 'pressure_stale': pressure_stale,
                'campaigns': campaigns, 'authority_basis': authority_basis,
                'missing_milestone_ids': [milestone_id] if milestone_id and milestone is None else [],
                'missing_requirement_ids': sorted(requirement_ids - {r['requirement_id'] for r in requirements}),
                'missing_goal_ids': sorted(goal_ids - {g['goal_node_id'] for g in goals})}
        snapshot['engineer_gate'] = (self._engineer_projection(project_id, packet_id)
                                     if self._engineer_projection else None)
        remediation = self._ledger.remediation_context(project_id, change_id, packet_id)
        snapshot['remediation_context'] = remediation
        if remediation:
            authority_basis['remediation_lineage'] = remediation
            authority_basis['intent_assessments'] = [
                {'finding_id': row['finding_id'], 'assessment': row['latest_intent_assessment']['assessment']}
                for row in (snapshot.get('engineer_gate') or {}).get('relevant_findings', [])
                if row.get('latest_intent_assessment')
            ]
        if remediation and remediation.get('predecessor_dependency_policy') == 'context_only':
            identity = remediation.get('predecessor_packet_id')
            snapshot['contextual_predecessor'] = self._snapshot(project_id, change_id, identity,
                _cache=cache, _path=(*_path, packet_id))
            authority_basis['contextual_predecessor_authority'] = fingerprint(snapshot['contextual_predecessor']['authority_basis'])
        cache[packet_id] = snapshot
        return snapshot

    def validation(self, project_id: str, change_id: str, packet_id: str, *, detail: str = 'standard') -> Mapping[str, object]:
        if detail not in {'standard', 'full'}:
            raise ValueError('detail must be standard or full')
        with self._ledger.consistent_read():
            snapshot = self._snapshot(project_id, change_id, packet_id)
            projection = self._projection(snapshot)
            gate = self._validation_gate(projection)
            inactive = snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES
            if projection['status'] == 'closed' and snapshot['external']['consumption_mode'] != 'external_agent':
                gate = {'tool': 'fow_external_work', 'operation': 'set_mode', 'reason': 'external_mode_not_selected'}
            plan_executable = not inactive and projection['status'] == 'closed' and snapshot['external']['consumption_mode'] == 'external_agent'
            dependencies = self._packet_dependencies(snapshot)
            admission = None
            try:
                self._assert_execution_allowed(snapshot)
            except ChangeControlBlockedError as exc:
                admission = {'reason': exc.reason, 'details': dict(exc.details),
                    'next_gate': dict(exc.details).get('next_gate')}
            execution_allowed = plan_executable and dependencies['ready'] and admission is None
            return {'status': 'success' if projection['status'] == 'closed' and not inactive and admission is None else 'blocked',
                    'reason': 'external_packet_inactive' if inactive else (admission['reason'] if admission else (projection['next_gap'] or {}).get('code', '')),
                    'validation': projection if detail == 'full' else {k: projection[k] for k in ('contract_version', 'consumer_scope', 'status', 'authority_fingerprint', 'spec_revision', 'plan_revision', 'next_gap')},
                    'next_gate': self._inactive_gate(snapshot) if inactive else ((admission.get('next_gate') or {'tool': 'fow_handover', 'operation': 'project_state_snapshot', 'reason': admission['reason']}) if admission else gate), 'consumption_mode': snapshot['external']['consumption_mode'],
                    'plan_executable': plan_executable, 'execution_allowed': execution_allowed, 'execution_admission': admission,
                    'engineer_gate': snapshot.get('engineer_gate'),
                    'packet_dependencies': dependencies}

    @staticmethod
    def _projection(snapshot) -> dict[str, object]:
        projection = derive_packet_validation(snapshot)
        for kind in ('requirement', 'goal', 'milestone'):
            for identity in snapshot.get('missing_' + kind + '_ids', []):
                projection['gaps'].append({'code': kind + '_authority_missing', 'reference': identity})
        for requirement in snapshot['requirements']:
            if requirement['lifecycle_status'] == 'removed':
                projection['gaps'].append({'code': 'requirement_retired', 'reference': requirement['requirement_id']})
        if snapshot.get('pressure_stale'):
            projection['gaps'].append({'code': 'accepted_risk_context_stale'})
            if projection['status'] != 'historical_unprojected':
                projection['status'] = 'stale'
        pressure = snapshot.get('pressure_context')
        if pressure and pressure['residual_risks'] and not pressure['accepted_risk_refs']:
            projection['gaps'].append({'code': 'residual_risk_authority_missing', 'risks': pressure['residual_risks']})
        for predecessor in snapshot.get('predecessor_packets', []):
            predecessor_projection = ExternalWorkService._projection(predecessor)
            if predecessor_projection['status'] != 'closed' or predecessor['external']['consumption_mode'] != 'external_agent':
                projection['gaps'].append({'code': 'packet_dependency_plan_not_executable', 'packet_id': predecessor['packet_id'],
                    'validation_status': predecessor_projection['status'], 'consumption_mode': predecessor['external']['consumption_mode'],
                    'next_gap': predecessor_projection['next_gap']})
        if projection['gaps'] and projection['status'] == 'closed':
            projection['status'] = 'open'
        projection['next_gap'] = projection['gaps'][0] if projection['gaps'] else None
        return projection

    @staticmethod
    def _local_closure(snapshot, projection, dependencies):
        rows, effective, done, conflicts, evidence_stale = resolve_current_reports(snapshot, projection, packet_dependencies=dependencies)
        scope_complete = projection['status'] == 'closed' and snapshot['external']['consumption_mode'] == 'external_agent'
        scope_complete = scope_complete and snapshot['packet']['status'] not in {'superseded', 'cancelled'}
        keys = {unit['client_unit_key'] for unit in projection['units']}
        implementation_complete = scope_complete and bool(keys) and keys.issubset(done)
        local_verification_complete = scope_complete and all(
            effective.get(unit['client_unit_key']) and unit['client_unit_key'] not in conflicts | evidence_stale
            and not next(row['dependencies_pending'] for row in rows if row['unit_key'] == unit['client_unit_key'])
            and all(any((evidence['criterion'], evidence['kind'], evidence['statement'], evidence['status']) ==
                (intent['criterion'], intent['kind'], intent['statement'], 'pass')
                for evidence in effective[unit['client_unit_key']]['payload']['verification'])
                for intent in unit['verifies'] if intent['kind'] == 'unit_check')
            for unit in projection['units'])
        complete = implementation_complete and local_verification_complete and dependencies['ready']
        reason = ''
        if not scope_complete:
            reason = 'external_mode_not_selected' if snapshot['external']['consumption_mode'] != 'external_agent' else (
                'external_packet_inactive' if snapshot['packet']['status'] in {'superseded', 'cancelled'} else
                (projection['next_gap'] or {}).get('code', 'external_unit_scope_missing'))
        elif not dependencies['ready']:
            reason = 'packet_dependencies_unresolved'
        elif not complete:
            reason = 'external_unit_reports_incomplete'
        return {'scope_complete': scope_complete, 'implementation_complete': implementation_complete,
            'local_verification_complete': local_verification_complete, 'dependencies_complete': dependencies['ready'], 'complete': complete,
            'reason': reason, 'gaps': projection['gaps'],
            'current_reports': {key: effective[key]['report_key'] for key in sorted(effective) if effective[key] and key in done},
            'authority_fingerprint': projection['authority_fingerprint'], 'spec_revision': projection['spec_revision'],
            'plan_revision': projection['plan_revision'], 'provenance': 'host_reported'}

    @staticmethod
    def _packet_dependencies(snapshot):
        if '_resolved_packet_dependencies' in snapshot:
            return snapshot['_resolved_packet_dependencies']
        rows = []
        references = {}
        for predecessor in snapshot.get('predecessor_packets', []):
            dependencies = ExternalWorkService._packet_dependencies(predecessor)
            projection = ExternalWorkService._projection(predecessor)
            closure = ExternalWorkService._local_closure(predecessor, projection, dependencies)
            rows.append({'packet_id': predecessor['packet_id'], 'packet_status': predecessor['packet']['status'], **closure})
            references.update(dependencies['report_refs'])
            references.update({'packet:' + predecessor['packet_id'] + ':unit:' + key: reference
                               for key, reference in closure['current_reports'].items()})
        result = {'ready': all(row['complete'] for row in rows), 'predecessors': rows, 'report_refs': references}
        snapshot['_resolved_packet_dependencies'] = result
        return result

    def implementation_closure(self, project_id: str, change_id: str, packet_id: str):
        with self._ledger.consistent_read():
            snapshot = self._snapshot(project_id, change_id, packet_id)
            if snapshot['external']['consumption_mode'] != 'external_agent':
                return None
            projection = self._projection(snapshot)
            dependencies = self._packet_dependencies(snapshot)
            closure = self._local_closure(snapshot, projection, dependencies)
            closure.update({'guided_authority_current': True, 'packet_dependencies': dependencies})
            if self._execution_guard is not None:
                try:
                    self._execution_guard(project_id, packet_id)
                except ChangeControlBlockedError as exc:
                    closure.update({'complete': False, 'guided_authority_current': False, 'reason': exc.reason})
            return closure

    @staticmethod
    def _validation_gate(projection) -> dict[str, object]:
        gap = projection['next_gap']
        return {'operation': 'validation' if gap else 'todo', 'tool': 'fow_external_work',
                'action_kind': 'semantic_authority_repair' if gap else 'read_work_frontier',
                'reason': gap['code'] if gap else 'validation_closed',
                'obligation': gap or {}, 'authority_fingerprint': projection['authority_fingerprint']}

    @staticmethod
    def _expect(snapshot, payload, *, plan_required: bool = False) -> None:
        expected = number(payload.get('expected_spec_revision'), 'expected_spec_revision')
        if expected != int(snapshot['packet']['spec_revision']):
            raise ChangeControlBlockedError('stale_packet_revision')
        if plan_required:
            value = payload.get('expected_plan_revision')
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('expected_plan_revision must be a nonnegative integer')
            if value != int((snapshot['plan'] or {}).get('plan_revision') or 0):
                raise ChangeControlBlockedError('stale_work_plan_revision')

    def _criterion(self, snapshot, operation, payload, actor, request_id):
        allowed = {'expected_spec_revision'} | ({'statement'} if operation == 'add_criterion' else
                                               {'number'} if operation == 'remove_criterion' else {'number', 'statement'})
        fields(payload, allowed, operation)
        self._expect(snapshot, payload)
        state = snapshot['external']
        if not state['validation_version']:
            raise ChangeControlBlockedError('packet_validation_upgrade_required')
        if state['criterion_statement_fingerprint'] != fingerprint(snapshot['packet']['completion_criteria']):
            raise ChangeControlBlockedError('criterion_authority_stale')
        criteria = [dict(c) for c in state['criteria']]
        if operation == 'add_criterion':
            num = max([c['number'] for c in criteria], default=0) + 1
            item = {'number': num, 'statement': text(payload.get('statement'), 'statement'), 'active': 1}
            criteria.append(item)
        else:
            num = number(payload.get('number'), 'number')
            item = next((c for c in criteria if c['number'] == num and c['active']), None)
            if item is None:
                raise ChangeControlBlockedError('criterion_unknown_or_retired')
            if operation == 'remove_criterion':
                affected = [u['client_unit_key'] for u in (snapshot['plan'] or {}).get('units', [])
                            if num in u.get('implements', []) or any(v['criterion'] == num for v in u.get('verifies', []))]
                if affected:
                    raise ChangeControlBlockedError('criterion_has_unit_references', details={'units': affected})
                item['active'] = 0
            else:
                item['statement'] = text(payload.get('statement'), 'statement')
        statements = tuple(c['statement'] for c in criteria if c['active'])
        self._changes.refine_packet(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'],
                                    completion_criteria=statements, actor=actor, request_id=request_id + ':criterion')
        current = self._snapshot(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])
        self._ledger.write_external_criterion(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'],
                                              num, item['statement'], bool(item['active']),
                                              spec_revision=current['packet']['spec_revision'], actor=actor)
        return {'status': 'success', 'number': num, 'statement': item['statement'], 'active': bool(item['active']),
                'spec_revision': current['packet']['spec_revision']}

    def _reconcile_criteria(self, snapshot, payload, actor, request_id):
        fields(payload, {'expected_spec_revision', 'criteria', 'new_statements', 'rationale'}, 'reconcile_criteria')
        self._expect(snapshot, payload)
        rationale = text(payload.get('rationale'), 'rationale')
        state = snapshot['external']
        if not state['validation_version']:
            raise ChangeControlBlockedError('packet_validation_upgrade_required')
        known = {c['number']: c for c in state['criteria']}
        mapped = []
        # Tombstones grow monotonically. Mapping existing authority cannot impose
        # a smaller bound than the history it must explicitly reconcile.
        for item in objects(payload.get('criteria'), 'criteria', max_items=max(128, len(known))):
            fields(item, {'number', 'statement', 'active'}, 'criterion_mapping')
            num = number(item.get('number'), 'number')
            active = item.get('active')
            if not isinstance(active, bool):
                raise ValueError('criterion active must be boolean')
            if num not in known:
                raise ValueError('criterion mapping must not invent a number')
            if not known[num]['active'] and active:
                raise ValueError('retired criteria cannot be reactivated or reused')
            if not known[num]['active'] and item.get('statement') != known[num]['statement']:
                raise ValueError('retired criterion tombstone statement is immutable')
            mapped.append({'number': num, 'statement': text(item.get('statement'), 'statement'), 'active': int(active)})
        if len({c['number'] for c in mapped}) != len(mapped) or {c['number'] for c in mapped} != set(known):
            raise ValueError('criterion mapping must cover each existing number exactly once')
        retired = {c['number'] for c in mapped if known[c['number']]['active'] and not c['active']}
        affected = [u['client_unit_key'] for u in (snapshot['plan'] or {}).get('units', [])
                    if retired.intersection(u.get('implements', [])) or any(v['criterion'] in retired for v in u.get('verifies', []))]
        if affected:
            raise ChangeControlBlockedError('criterion_has_unit_references', details={'units': affected})
        new_statements = strings(payload.get('new_statements', []), 'new_statements')
        next_number = max(known, default=0) + 1
        mapped.extend({'number': next_number + i, 'statement': statement, 'active': 1} for i, statement in enumerate(new_statements))
        mapped.sort(key=lambda c: c['number'])
        statements = tuple(c['statement'] for c in mapped if c['active'])
        self._changes.refine_packet(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'],
                                    completion_criteria=statements, actor=actor, request_id=request_id + ':criteria')
        current = self._snapshot(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])
        for criterion in mapped:
            old = known.get(criterion['number'])
            if old != criterion:
                self._ledger.write_external_criterion(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'],
                    criterion['number'], criterion['statement'], bool(criterion['active']),
                    spec_revision=current['packet']['spec_revision'], actor=actor)
        # A mapping can restore the existing authoritative values, so synchronize
        # the mirror even if no identity or statement changed.
        self._ledger.synchronize_external_criterion_view(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'], list(statements))
        return {'status': 'success', 'criteria': mapped, 'rationale': rationale, 'spec_revision': current['packet']['spec_revision']}

    def todo(self, project_id: str, change_id: str, packet_id: str, *, unit_key: str = '') -> Mapping[str, object]:
        with self._ledger.consistent_read():
            snapshot = self._snapshot(project_id, change_id, packet_id)
            return self._todo(snapshot, unit_key=unit_key)

    def criterion_progress(self, project_id: str, change_id: str, packet_id: str) -> Mapping[str, object]:
        """Inspect current host claims without admitting execution or acceptance."""
        with self._ledger.consistent_read():
            snapshot = self._snapshot(project_id, change_id, packet_id)
            projection = self._projection(snapshot)
            dependencies = self._packet_dependencies(snapshot)
            rows, effective, done, conflicts, evidence_stale = resolve_current_reports(snapshot, projection, packet_dependencies=dependencies)
            closed = projection['status'] == 'closed' and snapshot['external']['consumption_mode'] == 'external_agent'
            gaps = list(projection['gaps'])
            if snapshot['external']['consumption_mode'] != 'external_agent':
                gaps.append({'code': 'external_mode_not_selected'})
            current_evidence = []
            for row in rows:
                key = row['unit_key']
                report = effective[key]
                if not closed or not report or key in conflicts or key in evidence_stale or row['dependencies_pending']:
                    continue
                for evidence in report['payload']['verification']:
                    current_evidence.append({**evidence, 'unit_key': key, 'report_key': report['report_key'],
                        'source_revision': report['payload']['source_revision'], 'evidence_authority': 'host_reported',
                        'report_outcome': report['payload']['outcome']})
            criteria = []
            deferred = []
            for criterion in projection['criteria']:
                owners = criterion['implementation_units']
                local = [intent for intent in criterion['verification'] if intent['kind'] == 'unit_check']
                evidence = [v for v in current_evidence if v['criterion'] == criterion['number']]
                local_passed = bool(local) and all(any(
                    (v['unit_key'], v['kind'], v['statement'], v['status']) ==
                    (intent['unit_key'], intent['kind'], intent['statement'], 'pass') for v in evidence) for intent in local)
                obligations = []
                for intent in criterion['verification']:
                    if intent['kind'] == 'unit_check':
                        continue
                    claimed = next((v for v in evidence if (v['unit_key'], v['kind'], v['statement']) ==
                                    (intent['unit_key'], intent['kind'], intent['statement'])), None)
                    authority = snapshot['resolved_authorities'].get(intent.get('authority_ref', ''))
                    obligation = {'packet_id': packet_id, **intent, 'statement': intent['statement'],
                        'state': 'verification_pending', 'host_result': claimed,
                        'linked_authority': authority, 'attestation': 'not_inferred',
                        'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision']}
                    obligations.append(obligation)
                    deferred.append(obligation)
                criteria.append({**criterion, 'packet_id': packet_id,
                    'implementation_state': 'complete' if closed and owners and set(owners).issubset(done)
                                            else 'pending' if owners else 'not_applicable',
                    'local_verification_state': 'passed' if local_passed else 'pending' if local else 'not_applicable',
                    'current_evidence': evidence, 'current_reports': [
                        {'unit_key': key, 'report_key': effective[key]['report_key'], 'outcome': effective[key]['payload']['outcome'],
                         'source_revision': effective[key]['payload']['source_revision']}
                        for key in sorted(set(owners) | {v['unit_key'] for v in criterion['verification']})
                        if effective.get(key) and key not in conflicts and key not in evidence_stale],
                    'deferred_obligations': obligations, 'acceptance': 'not_inferred'})
            return {'packet_id': packet_id, 'packet_status': snapshot['packet']['status'],
                'consumption_mode': snapshot['external']['consumption_mode'], 'scope_complete': closed,
                'authority_fingerprint': projection['authority_fingerprint'], 'authority_basis': snapshot['authority_basis'],
                'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
                'criteria': criteria, 'deferred_obligations': deferred, 'gaps': gaps,
                'packet_dependencies': dependencies,
                'execution_allowed': closed and dependencies['ready'] and snapshot['packet']['status'] not in PACKET_INACTIVE_STATUS_VALUES,
                'acceptance': 'not_inferred'}

    @staticmethod
    def _inactive_gate(snapshot):
        return {'action_kind': 'external_obligation', 'external_operation': 'inspect_inactive_history',
                'packet_status': snapshot['packet']['status'], 'inspect_route': {'tool': 'fow_external_work', 'operation': 'criteria'}}

    def _todo(self, snapshot, *, unit_key='') -> Mapping[str, object]:
        projection = self._projection(snapshot)
        if snapshot['external']['consumption_mode'] != 'external_agent':
            return {'status': 'blocked', 'reason': 'external_mode_not_selected', 'next_gate': {'tool': 'fow_external_work', 'operation': 'set_mode'}}
        if projection['status'] != 'closed':
            return {'status': 'blocked', 'reason': projection['next_gap']['code'], 'next_gate': self._validation_gate(projection), 'validation': projection}
        try:
            self._assert_execution_allowed(snapshot)
        except ChangeControlBlockedError as exc:
            return {'status': 'blocked', 'reason': exc.reason, 'next_gate': self._inactive_gate(snapshot) if snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES
                    else (dict(exc.details).get('next_gate') or {'action_kind': 'external_obligation', 'external_operation': 'resolve_guided_authority', 'details': exc.details}),
                    'engineer_gate': snapshot.get('engineer_gate'), 'execution_allowed': False}
        dependencies = self._packet_dependencies(snapshot)
        if not dependencies['ready']:
            first = next(row for row in dependencies['predecessors'] if not row['complete'])
            return {'status': 'blocked', 'reason': 'packet_dependencies_unresolved', 'packet_dependencies': dependencies,
                'authority_fingerprint': projection['authority_fingerprint'], 'spec_revision': projection['spec_revision'],
                'plan_revision': projection['plan_revision'], 'next_gate': {'action_kind': 'external_obligation',
                    'external_operation': 'complete_predecessor_packet', 'packet_id': first['packet_id'],
                    'inspect_route': {'tool': 'fow_external_work', 'operation': 'todo', 'project_id': snapshot['project_id'],
                        'change_id': snapshot['change_id'], 'packet_id': first['packet_id']}}}
        rows, effective, done, conflicts, evidence_stale = resolve_current_reports(snapshot, projection, packet_dependencies=dependencies)
        return self._todo_result(snapshot, projection, rows, effective, done, unit_key=unit_key)

    def _todo_result(self, snapshot, projection, rows, effective, done, *, unit_key=''):
        current = projection['authority_fingerprint']
        if unit_key and not any(row['unit_key'] == unit_key for row in rows):
            raise ValueError('unknown unit_key')
        candidates = [row for row in rows if row['status'] != 'complete']
        selected = next((row for row in candidates if row['unit_key'] == unit_key), None) if unit_key else next((row for row in candidates if row['status'] in {'actionable', 'blocked', 'failed', 'conflict', 'stale'} and not row['dependencies_pending']), None)
        deferred = []
        for u in projection['units']:
            current_report = effective.get(u['client_unit_key']) if u['client_unit_key'] in done else None
            for intent in u['verifies']:
                if intent['kind'] == 'unit_check':
                    continue
                evidence = next((v for v in (current_report or {}).get('payload', {}).get('verification', [])
                                 if (v['criterion'], v['kind'], v['statement']) == (intent['criterion'], intent['kind'], intent['statement'])), None)
                deferred.append({'unit_key': u['client_unit_key'], **intent, 'state': 'host_reported_' + evidence['status'] if evidence else 'verification_pending',
                                 'evidence': evidence, 'attestation': 'not_inferred'})
        if selected:
            operation = 'reconcile_outcome' if selected['status'] == 'conflict' else 'resolve_external_blocker' if selected['status'] in {'blocked', 'failed', 'stale'} and not selected['dependencies_pending'] else 'execute_unit' if selected['status'] == 'actionable' else 'complete_predecessors'
            gate = ({'tool': 'fow_external_work', 'operation': 'reconcile_outcome'} if operation == 'reconcile_outcome' else
                    {'action_kind': 'external_agent_execution' if operation == 'execute_unit' else 'external_obligation', 'external_operation': operation,
                     'report_route': {'tool': 'fow_external_work', 'operation': 'report_outcome'}})
            gate.update({'unit_key': selected['unit_key'], 'reason': selected['status']})
        elif candidates:
            gate = {'action_kind': 'external_obligation', 'external_operation': 'complete_predecessors', 'reason': 'dependencies_pending',
                    'inspect_route': {'tool': 'fow_external_work', 'operation': 'todo'}}
        else:
            gate = {'action_kind': 'verification_or_acceptance', 'external_operation': 'obtain_deferred_verification' if deferred else 'request_human_acceptance',
                    'reason': 'agent_work_complete_acceptance_pending'}
        criterion_traceability = []
        for criterion in projection['criteria']:
            evidence = [dict(v, unit_key=key, report_key=r['report_key'], source_revision=r['payload']['source_revision'], evidence_authority='host_reported')
                        for key, r in effective.items() if r and key in done
                        for v in r['payload']['verification'] if v['criterion'] == criterion['number']]
            criterion_traceability.append({**criterion, 'evidence': evidence, 'acceptance': 'not_inferred'})
        return {'status': 'success', 'consumption_mode': 'external_agent', 'engineer_gate': snapshot.get('engineer_gate'), 'authority_fingerprint': current,
                'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
                'todos': rows, 'current_unit': selected, 'deferred_verification': deferred, 'next_gate': gate,
                'packet_dependencies': self._packet_dependencies(snapshot),
                'acceptance': 'not_inferred', 'historical_reports': [r['report_key'] for r in snapshot['external']['reports']
                    if r['authority_fingerprint'] != current or r['disposition'] == 'stale'
                    or r['spec_revision'] != projection['spec_revision'] or r['plan_revision'] != projection['plan_revision']],
                'criterion_traceability': criterion_traceability}

    def _report(self, snapshot, payload, actor):
        allowed = {'report_key', 'expected_spec_revision', 'expected_plan_revision', 'authority_fingerprint', 'unit_key',
                   'outcome', 'summary', 'source_revision', 'artifacts', 'produced_contracts', 'verification', 'unresolved'}
        fields(payload, allowed, 'outcome')
        value = {key: text(payload.get(key), key) for key in ('report_key', 'authority_fingerprint', 'unit_key', 'outcome', 'summary', 'source_revision')}
        if value['outcome'] not in {'complete', 'blocked', 'failed'}:
            raise ValueError('outcome must be complete, blocked or failed')
        value['expected_spec_revision'] = number(payload.get('expected_spec_revision'), 'expected_spec_revision')
        value['expected_plan_revision'] = number(payload.get('expected_plan_revision'), 'expected_plan_revision')
        plan = self._ledger.packet_work_plan_state(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'], plan_revision=value['expected_plan_revision'])
        if not plan or int(plan['packet_revision']) != value['expected_spec_revision']:
            raise ChangeControlBlockedError('report_plan_authority_unknown')
        unit = next((u for u in plan['units'] if u['client_unit_key'] == value['unit_key']), None)
        if unit is None:
            raise ValueError('report names unknown unit in issued plan')
        value['artifacts'] = []
        for artifact in objects(payload.get('artifacts', []), 'artifacts'):
            fields(artifact, {'reference', 'description', 'sha256'}, 'artifact')
            item = {'reference': text(artifact.get('reference'), 'reference'), 'description': text(artifact.get('description'), 'description')}
            if artifact.get('sha256'):
                digest = text(artifact['sha256'], 'sha256')
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('sha256 must be lowercase hexadecimal SHA-256')
                item['sha256'] = digest
            value['artifacts'].append(item)
        refs = {a['reference'] for a in value['artifacts']}
        value['produced_contracts'] = []
        for contract in objects(payload.get('produced_contracts', []), 'produced_contracts'):
            fields(contract, {'name', 'artifact_ref'}, 'produced_contract')
            item = {'name': text(contract.get('name'), 'name'), 'artifact_ref': text(contract.get('artifact_ref'), 'artifact_ref')}
            if item['name'] not in {c['name'] for c in unit['provides']} or item['artifact_ref'] not in refs:
                raise ValueError('produced contract must name a declared contract and included artifact')
            value['produced_contracts'].append(item)
        if len({c['name'] for c in value['produced_contracts']}) != len(value['produced_contracts']):
            raise ValueError('produced contracts must not duplicate declarations')
        intents = {(v['criterion'], v['kind'], v['statement']) for v in unit['verifies']}
        value['verification'] = []
        for evidence in objects(payload.get('verification', []), 'verification'):
            fields(evidence, {'criterion', 'kind', 'statement', 'status', 'evidence_ref', 'provenance'}, 'verification')
            item = {'criterion': number(evidence.get('criterion')),
                    **{k: text(evidence.get(k), k) for k in ('kind', 'statement', 'status', 'provenance')},
                    'evidence_ref': text(evidence.get('evidence_ref', ''), 'evidence_ref', required=False)}
            if (item['criterion'], item['kind'], item['statement']) not in intents or item['status'] not in {'pass', 'fail', 'not_run'}:
                raise ValueError('verification must identify a declared intent and supported result')
            if item['status'] in {'pass', 'fail'} and not item['evidence_ref']:
                raise ValueError('verification result requires evidence_ref')
            value['verification'].append(item)
        if len({(v['criterion'], v['kind'], v['statement']) for v in value['verification']}) != len(value['verification']):
            raise ValueError('verification results must not repeat an intent')
        value['unresolved'] = list(strings(payload.get('unresolved', []), 'unresolved'))
        if value['outcome'] == 'complete':
            if value['unresolved']:
                raise ValueError('complete outcome cannot retain unresolved unit obligations')
            passed = {(v['criterion'], v['kind'], v['statement']) for v in value['verification'] if v['status'] == 'pass'}
            required = {(v['criterion'], v['kind'], v['statement']) for v in unit['verifies'] if v['kind'] == 'unit_check'}
            if not required.issubset(passed):
                raise ValueError('complete outcome requires every declared unit-local verification to pass')
            if {c['name'] for c in unit['provides']} != {c['name'] for c in value['produced_contracts']}:
                raise ValueError('complete outcome requires artifact references for every produced contract')
        projection = self._projection(snapshot)
        current = value['authority_fingerprint'] == projection['authority_fingerprint'] and value['expected_spec_revision'] == projection['spec_revision'] and value['expected_plan_revision'] == projection['plan_revision']
        existing = next((r for r in snapshot['external']['reports'] if r['report_key'] == value['report_key']), None)
        if existing is not None and (existing['payload'] != value or existing['actor'] != actor):
            raise RequirementConflictError('external_outcome_report_key_conflict')
        identical = existing
        if identical is not None:
            return {'status': 'historical' if identical['disposition'] == 'stale' else 'conflict' if identical['disposition'] == 'conflict' else 'success',
                    'reason': 'stale_authority' if identical['disposition'] == 'stale' else 'outcome_reconciliation_required' if identical['disposition'] == 'conflict' else '',
                    'report_key': value['report_key'], 'disposition': identical['disposition'], 'replayed': True,
                    'acceptance': 'not_inferred', 'provenance': 'external_agent_report'}
        if current:
            self._assert_execution_allowed(snapshot)
        if current and (snapshot['external']['consumption_mode'] != 'external_agent' or projection['status'] != 'closed'):
            raise ChangeControlBlockedError('external_outcome_authority_not_executable')
        dependencies = self._packet_dependencies(snapshot)
        if current and not dependencies['ready']:
            raise ChangeControlBlockedError('packet_dependencies_unresolved', details={'packet_dependencies': dependencies})
        prior = [r for r in snapshot['external']['reports'] if current and r['unit_key'] == value['unit_key']
                 and r['authority_fingerprint'] == value['authority_fingerprint'] and r['report_key'] != value['report_key']
                 and r['disposition'] != 'stale' and r['spec_revision'] == projection['spec_revision']
                 and r['plan_revision'] == projection['plan_revision']]
        disposition = 'stale' if not current else 'conflict' if prior else 'current'
        predecessor_reports = {}
        if current:
            frontier = self._todo(snapshot)
            target = next(t for t in frontier['todos'] if t['unit_key'] == value['unit_key'])
            if value['outcome'] == 'complete' and target['dependencies_pending']:
                raise ChangeControlBlockedError('external_outcome_predecessor_pending')
            predecessor_reports = {**dependencies['report_refs'],
                **{t['unit_key']: t['report_key'] for t in frontier['todos'] if t['unit_key'] in unit['depends_on']}}
        receipt = self._ledger.record_external_outcome(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'], value, disposition=disposition, actor=actor, predecessor_reports=predecessor_reports)
        return {'status': 'historical' if receipt['disposition'] == 'stale' else 'conflict' if receipt['disposition'] == 'conflict' else 'success',
                'reason': 'stale_authority' if receipt['disposition'] == 'stale' else 'outcome_reconciliation_required' if receipt['disposition'] == 'conflict' else '',
                **receipt, 'acceptance': 'not_inferred', 'provenance': 'external_agent_report'}

    def _reconcile(self, snapshot, payload):
        fields(payload, {'report_key', 'expected_spec_revision', 'expected_plan_revision', 'rationale'}, 'reconcile_outcome')
        self._expect(snapshot, payload, plan_required=True)
        key = text(payload.get('report_key'), 'report_key')
        rationale = text(payload.get('rationale'), 'rationale')
        projection = self._projection(snapshot)
        report = next((r for r in snapshot['external']['reports'] if r['report_key'] == key), None)
        if (not report or report['disposition'] == 'stale' or report['authority_fingerprint'] != projection['authority_fingerprint']
            or report['spec_revision'] != projection['spec_revision'] or report['plan_revision'] != projection['plan_revision']
            or projection['status'] != 'closed'):
            raise ChangeControlBlockedError('external_outcome_reconciliation_stale')
        self._ledger.select_external_outcome(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'], report, rationale)
        return {'status': 'success', 'report_key': key, 'reconciled': True, 'acceptance': 'not_inferred'}

    def _export(self, snapshot, payload, actor, request_id):
        fields(payload, {'expected_spec_revision', 'expected_plan_revision', 'allow_draft'}, 'export_plan')
        self._expect(snapshot, payload, plan_required=True)
        allow_draft = payload.get('allow_draft', False)
        if not isinstance(allow_draft, bool):
            raise ValueError('allow_draft must be boolean')
        projection = self._projection(snapshot)
        try:
            self._assert_execution_allowed(snapshot)
        except ChangeControlBlockedError as exc:
            if not allow_draft:
                raise
            projection = {**projection, 'status': 'open', 'gaps': [*projection['gaps'], {'code': exc.reason, **exc.details}]}
        if not allow_draft and projection['status'] != 'closed':
            raise ChangeControlBlockedError(projection['next_gap']['code'])
        content = render_plan(snapshot, projection, project_predecessor=self._projection)
        mappings = (ArtifactMapping('packet', snapshot['packet_id']),
                    *(ArtifactMapping('requirement', r['requirement_id']) for r in snapshot['requirements']),
                    *(ArtifactMapping('goal', g['goal_node_id']) for g in snapshot['goals']))
        if snapshot['milestone']:
            mappings += (ArtifactMapping('milestone', snapshot['milestone']['milestone_id']),)
        artifact = ArtifactDraft(ArtifactKind.IMPLEMENTATION_PLAN, content, mappings)
        generation = ArtifactGeneration(snapshot['project_id'], 'flower-external-plan', '1',
                                        self._ledger.ledger_version(snapshot['project_id']),
                                        datetime.now(timezone.utc).isoformat(), (artifact,))
        stored = self._ledger.record_artifact_generation(generation, actor=actor, request_id=request_id + ':artifact')
        return {'status': 'success', 'generation_id': stored.generation_id, 'artifact_kind': 'implementation_plan',
                'content': artifact.content, 'content_sha256': artifact.content_sha256,
                'authority_fingerprint': projection['authority_fingerprint'], 'draft': projection['status'] != 'closed',
                'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
                'generated_at': stored.generated_at, 'source_ledger_version': stored.source_ledger_version}


def resolve_current_reports(snapshot, projection, *, packet_dependencies=None):
    dependencies = ExternalWorkService._packet_dependencies(snapshot) if packet_dependencies is None else packet_dependencies
    current = projection['authority_fingerprint']
    rows = []
    done = set()
    effective = {}
    conflicts = set()
    for unit in projection['units']:
        key = unit['client_unit_key']
        reports = [r for r in snapshot['external']['reports'] if r['unit_key'] == key and r['authority_fingerprint'] == current and r['disposition'] != 'stale'
                   and r['spec_revision'] == projection['spec_revision'] and r['plan_revision'] == projection['plan_revision']]
        if any(r['disposition'] == 'conflict' and not r['reconciled'] for r in reports):
            conflicts.add(key)
        selection = next((s for s in snapshot['external']['selections'] if s['unit_key'] == key and s['authority_fingerprint'] == current), None)
        report = next((r for r in reports if selection and r['report_key'] == selection['report_key']), None)
        if report is None and not selection:
            report = next((r for r in reports if r['disposition'] == 'current'), None)
        effective[key] = report
        if report and report['payload']['outcome'] == 'complete' and key not in conflicts:
            done.add(key)
    evidence_stale = set()
    for key, report in effective.items():
        if report and (not dependencies['ready'] or {k: v for k, v in report['predecessor_reports'].items() if k.startswith('packet:')} != dependencies['report_refs']):
            evidence_stale.add(key)
        if report and any(not effective.get(dep) or effective[dep]['report_key'] != report['predecessor_reports'].get(dep)
                          for dep in next(u for u in projection['units'] if u['client_unit_key'] == key)['depends_on']):
            evidence_stale.add(key)
    done.difference_update(evidence_stale)
    while True:
        invalid = {u['client_unit_key'] for u in projection['units'] if u['client_unit_key'] in done and not set(u['depends_on']).issubset(done)}
        if not invalid:
            break
        done.difference_update(invalid)
    for unit in projection['units']:
        key = unit['client_unit_key']
        report = effective[key]
        dependencies = [dep for dep in unit['depends_on'] if dep not in done]
        status = 'complete' if key in done else 'conflict' if key in conflicts else 'stale' if key in evidence_stale else 'blocked' if dependencies else 'actionable'
        if report and key not in done and status == 'actionable':
            status = report['payload']['outcome']
        contracts = []
        for use in unit['resolved_requires']:
            producer_report = effective.get(use['producer_unit_key'])
            contracts.append({**use, 'temporal_state': 'host_reported_materialized' if use['producer_unit_key'] in done else 'planned',
                              'producer_report': producer_report['report_key'] if producer_report else '',
                              'provenance': 'external_agent_report' if producer_report else 'accepted_plan'})
        rows.append({'unit_number': unit['unit_number'], 'unit_key': key, 'status': status, 'dependencies_pending': dependencies,
                     'unit': {**unit, 'resolved_requires': contracts}, 'report_key': report['report_key'] if report else ''})
    return rows, effective, done, conflicts, evidence_stale
