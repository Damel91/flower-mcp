"""Standalone plan/PVP projection, artifacts and durable external work reports."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
from typing import Callable, Mapping

from flow_of_work_mcp.application.change_control import ChangeControlService
from flow_of_work_mcp.application.deferred_campaign_verification import (
    CAMPAIGN_VERIFICATION_KINDS, campaign_plan_basis, deferred_campaign_proof,
)
from flow_of_work_mcp.application.external_plan_markdown import render_plan
from flow_of_work_mcp.application.engineering_cycle import (
    engineering_cycle_version, normalize_observed_repository_source, repository_review_projection,
)
from flow_of_work_mcp.application.packet_next_action import packet_technical_disposition_route
from flow_of_work_mcp.core.domain.artifacts import ArtifactDraft, ArtifactGeneration, ArtifactKind, ArtifactMapping
from flow_of_work_mcp.core.domain.architecture import architecture_authority_context
from flow_of_work_mcp.core.domain.campaign_host import required_host_cases
from flow_of_work_mcp.core.domain.change_control import PACKET_INACTIVE_STATUS_VALUES, validate_packet_id
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.core.domain.lifecycle_control import milestone_prerequisite_gaps
from flow_of_work_mcp.core.domain.external_work import (fields, fingerprint, number, objects, strings, text)
from flow_of_work_mcp.core.domain.packet_validation_projection import CRITERION_RESPONSIBILITY_GAPS, derive_packet_validation
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError, ChangeNotFoundError, InputValidationError, PacketValidationAlreadyUpgradedError, RequirementConflictError,
)

READ_OPERATIONS = frozenset({'criteria', 'validation', 'provider_validation', 'todo'})
MUTATION_OPERATIONS = frozenset({'set_mode', 'upgrade_validation', 'classify_criteria', 'add_criterion', 'edit_criterion', 'remove_criterion', 'reconcile_criteria', 'export_plan', 'report_outcome', 'reconcile_outcome'})
_RECOVERY_REQUIRED = 'historical_outcome_recovery_required'


def _authority_pin(value):
    return {key: value[key] for key in ('spec_revision', 'plan_revision', 'authority_fingerprint')}


def _report_matches_authority(report, projection):
    return report['disposition'] != 'stale' and _authority_pin(report) == _authority_pin(projection)


def _historical_materializations(snapshot, projection):
    # Unchanged revisions identify the same accepted unit declarations. A new
    # accepted specification/plan must not inherit work from a reused unit key.
    return {report['unit_key']: report for report in snapshot['external']['reports']
            if report['payload']['outcome'] == 'complete'
            and report['spec_revision'] == projection['spec_revision']
            and report['plan_revision'] == projection['plan_revision']
            and not _report_matches_authority(report, projection)}


def _recovery_frontier(rows):
    return next((row for row in rows if row['status'] == 'recovery_required' and not row['dependencies_pending']), None)


def _verification_error(snapshot, unit, *, field, received, expected, message, criterion=None):
    """Return a bounded diagnostic while preserving the exact declaration gate."""
    expected = list(expected)
    details = {
        'unit_key': unit['client_unit_key'],
        'expected': expected[:10],
        'expected_count': len(expected),
        'expected_truncated': len(expected) > 10,
        'received': received,
        'next_tool_call': {
            'tool': 'fow_external_work',
            'arguments': {'project_id': snapshot['project_id'], 'change_id': snapshot['change_id'],
                          'packet_id': snapshot['packet_id'], 'operation': 'todo',
                          'payload': {'unit_key': unit['client_unit_key']}},
        },
    }
    if criterion is not None:
        details['criterion'] = criterion
    return InputValidationError(message, field=field, received_value=received, details=details)


class ExternalWorkService:
    def __init__(self, ledger, *, execution_guard: Callable[[str, str], None] | None = None,
                 engineer_projection=None, packet_executor=None, non_external_guard=None) -> None:
        self._ledger = ledger
        self._changes = ChangeControlService(ledger)
        self._execution_guard = execution_guard
        self._engineer_projection = engineer_projection
        self._packet_executor = packet_executor
        self._non_external_guard = non_external_guard

    def _assert_execution_allowed(self, snapshot) -> None:
        gaps = milestone_prerequisite_gaps(snapshot.get('milestone'))
        if gaps:
            raise ChangeControlBlockedError(gaps[0]['code'], details={'gaps': gaps})
        if snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES:
            raise ChangeControlBlockedError('external_packet_inactive', details={'packet_status': snapshot['packet']['status']})
        if self._execution_guard is not None:
            self._execution_guard(snapshot['project_id'], snapshot['packet_id'])

    def mode_for_packet(self, project_id: str, packet_id: str) -> str:
        with self._ledger.consistent_read():
            normalized_project = validate_project_id(project_id)
            try:
                normalized_packet = validate_packet_id(packet_id)
            except ValueError:
                # Preserve the original project-before-packet error precedence
                # without hydrating the project's changes or event history.
                self._ledger.ledger_version(normalized_project)
                raise ChangeControlBlockedError('packet_not_found') from None
            if normalized_packet != packet_id:
                self._ledger.ledger_version(normalized_project)
                raise ChangeControlBlockedError('packet_not_found')
            try:
                change_id = self._ledger.packet_change_id(normalized_project, packet_id)
            except ValueError:
                raise ChangeControlBlockedError('packet_not_found') from None
            return str(self._ledger.external_work_state(project_id, change_id, packet_id)['consumption_mode'])

    def executor_state(self, project_id: str, change_id: str, packet_id: str):
        return self._packet_executor.inspect(project_id, change_id, packet_id) if self._packet_executor else None

    def provider_admission(self, project_id: str, change_id: str, packet_id: str):
        if self._packet_executor is None:
            return {'allowed': False, 'reason': 'packet_executor_unavailable', 'next_operation': 'executor_select'}
        return self._packet_executor.admission(project_id, change_id, packet_id)

    def assert_plan_criterion_responsibility(self, project_id: str, change_id: str, packet_id: str, plan_revision: int) -> None:
        if self._ledger.external_work_validation_policy(project_id, change_id, packet_id) != (2, 'external_agent'):
            return
        snapshot = self._snapshot(project_id, change_id, packet_id)
        plan = snapshot['plan'] or {}
        if plan.get('plan_revision') != plan_revision or plan.get('status') != 'proposed':
            gaps = [{'code': 'criterion_responsibility_plan_not_current'}]
        else:
            projection = derive_packet_validation(snapshot, require_accepted_plan=False)
            gaps = [gap for gap in projection['gaps'] if gap['code'] in CRITERION_RESPONSIBILITY_GAPS]
        if gaps:
            raise ChangeControlBlockedError('packet_criterion_responsibility_unresolved', details={
                'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id,
                'plan_revision': plan_revision, 'gap': gaps[0], 'gap_count': len(gaps),
            })

    def call(self, project_id: str, change_id: str, packet_id: str, operation: str,
             *, actor: str = '', request_id: str = '', payload: Mapping[str, object] | None = None) -> Mapping[str, object]:
        operation = text(operation, 'operation')
        payload = dict(payload or {})
        if operation in {'select_executor', 'negotiate_provider'}:
            if self._packet_executor is None:
                raise ChangeControlBlockedError('packet_executor_unavailable')
            return self._packet_executor.call(project_id, change_id, packet_id, operation,
                payload=payload, actor=actor, request_id=request_id)
        if operation in READ_OPERATIONS:
            if operation == 'provider_validation':
                fields(payload, {'detail'}, operation)
                detail = payload.get('detail', 'standard')
                if detail not in {'standard', 'full'}:
                    raise ValueError('detail must be standard or full')
                with self._ledger.consistent_read():
                    projection = self.provider_validation(project_id, change_id, packet_id)
                    admission = (self._packet_executor.admission(project_id, change_id, packet_id)
                                 if self._packet_executor else {'allowed': False, 'reason': 'packet_executor_unavailable', 'next_operation': 'executor_select'})
                    upstream_action = (self._packet_executor.upstream_action(admission,
                        project_id=project_id, change_id=change_id, packet_id=packet_id,
                        spec_revision=projection['spec_revision'], plan_revision=projection['plan_revision'])
                        if self._packet_executor else None)
                    return {'status': 'success' if admission['allowed'] else 'blocked',
                        'reason': admission.get('reason', ''),
                        'validation': projection if detail == 'full' else {k: projection[k] for k in (
                            'contract_version', 'consumer_scope', 'status', 'authority_fingerprint', 'spec_revision', 'plan_revision', 'next_gap')},
                        'executor': self._packet_executor.inspect(project_id, change_id, packet_id) if self._packet_executor else None,
                        'execution_admission': admission,
                        'next_gate': upstream_action or {'tool': 'fow_external_work', 'operation': {
                            'executor_select': 'select_executor', 'provider_negotiate': 'negotiate_provider',
                            'provider_validation': 'provider_validation',
                        }.get(admission.get('next_operation'), 'provider_validation')}}
            if operation == 'criteria':
                fields(payload, set(), operation)
                with self._ledger.consistent_read():
                    state = self._ledger.external_work_state(project_id, change_id, packet_id)
                    return {'status': 'success', 'criteria': state['criteria'], 'history': state['criterion_history'],
                            'validation_version': state['validation_version'],
                            **({'criterion_dispositions': state['criterion_dispositions']}
                               if 'criterion_dispositions' in state else {})}
            if operation == 'validation':
                fields(payload, {'detail', 'history_offset', 'observed_source'}, operation)
                return self.validation(project_id, change_id, packet_id, detail=str(payload.get('detail', 'standard')),
                                       history_offset=payload.get('history_offset', 0),
                                       observed_source=payload.get('observed_source'))
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
                if operation == 'report_outcome':
                    return self._replayed_outcome(project_id, change_id, packet_id, replay, payload)
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
                if self._packet_executor is not None and snapshot['external']['consumption_mode'] != 'external_agent':
                    self._packet_executor.call(project_id, change_id, packet_id, 'select_executor',
                        payload={'executor': 'external_agent',
                                 'expected_spec_revision': payload['expected_spec_revision'],
                                 'expected_plan_revision': payload['expected_plan_revision']},
                        actor=actor, request_id=request_id)
                self._ledger.set_external_work_mode(project_id, change_id, packet_id, 'external_agent')
                result = {'status': 'success', 'consumption_mode': 'external_agent'}
            elif operation == 'upgrade_validation':
                fields(payload, {'expected_spec_revision', 'expected_plan_revision'}, operation)
                self._expect(snapshot, payload, plan_required=True)
                if snapshot['external']['validation_version']:
                    address = {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id}
                    criterion_stale = snapshot['external']['criterion_statement_fingerprint'] != fingerprint(snapshot['packet']['completion_criteria'])
                    recovery_calls = {'criteria': {
                        'tool': 'fow_external_work', 'arguments': {**address, 'operation': 'criteria'},
                    }}
                    if criterion_stale:
                        recovery_calls['reconcile_criteria_help'] = {
                            'tool': 'fow_capabilities', 'arguments': {'view': 'operation',
                                'operation_tool': 'fow_external_work', 'operation_name': 'reconcile_criteria'},
                        }
                    raise PacketValidationAlreadyUpgradedError(details={
                        'operation': operation, **address,
                        'validation_version': snapshot['external']['validation_version'],
                        'current_authority': {
                            'expected_spec_revision': snapshot['packet']['spec_revision'],
                            'expected_plan_revision': (snapshot['plan'] or {}).get('plan_revision', 0),
                        },
                        'criterion_authority_stale': criterion_stale,
                        'next_tool_call': {'tool': 'fow_external_work', 'arguments': {
                            **address, 'operation': 'validation', 'payload': {'detail': 'full'},
                        }},
                        'recovery_calls': recovery_calls,
                    })
                version = 2 if snapshot['packet']['purpose'] == 'implementation' else 1
                self._ledger.upgrade_external_criteria(project_id, change_id, packet_id,
                                                      list(snapshot['packet']['completion_criteria']),
                                                      spec_revision=snapshot['packet']['spec_revision'], actor=actor,
                                                      validation_version=version)
                result = {'status': 'success', 'validation_version': version,
                          'criteria': self._ledger.external_work_state(project_id, change_id, packet_id)['criteria']}
            elif operation == 'classify_criteria':
                result = self._classify_criteria(snapshot, payload)
            elif operation == 'reconcile_criteria':
                result = self._reconcile_criteria(snapshot, payload, actor, request_id)
            else:
                result = self._criterion(snapshot, operation, payload, actor, request_id)
            self._ledger.record_external_work_request(project_id, request_id, request_fingerprint, result,
                                                      actor=actor, operation=operation)
            if operation == 'report_outcome' and result['replayed']:
                return self._outcome_replay_view(snapshot, self._projection(snapshot), result, payload)
            return result

    def _snapshot(self, project_id: str, change_id: str, packet_id: str, *, _cache=None, _path=(), _change=None,
                  observed_source: Mapping[str, str] | None = None) -> dict[str, object]:
        if packet_id in _path:
            raise ChangeControlBlockedError('packet_dependency_cycle', details={'packet_ids': [*_path, packet_id]})
        cache = {} if _cache is None else _cache
        if packet_id in cache:
            return cache[packet_id]
        change = self._ledger.change_state(project_id, change_id) if _change is None else _change
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
                    'prerequisite_requirement_ids', 'prerequisite_producers', 'prerequisite_mapping_gaps', 'prerequisite_authority_gaps',
                    'entry_policy', 'exit_policy', 'risk_disposition')}
        predecessors = [self._snapshot(project_id, change_id, identity, _cache=cache, _path=(*_path, packet_id), _change=change)
                        for identity in packet.get('dependency_packet_ids', [])]
        plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id)
        external = self._ledger.external_work_state(project_id, change_id, packet_id)
        requirement_ids = set(packet.get('requirement_ids') or change.get('requirement_ids', []))
        requirement_matrix = self._ledger.traceability_matrix(project_id)
        requirements = [dict(r) for r in requirement_matrix if r['requirement_id'] in requirement_ids]
        for requirement in requirements:
            history = self._ledger.requirement_history(project_id, requirement['requirement_id'])
            semantic_revision = next(r for r in history['revisions'] if r['revision'] == requirement['current_revision'])
            requirement['rationale'] = semantic_revision['rationale']
        if milestone:
            prerequisite_ids = set(milestone['prerequisite_requirement_ids'])
            prerequisite_requirements = []
            for row in requirement_matrix:
                if row['requirement_id'] in prerequisite_ids:
                    history = self._ledger.requirement_history(project_id, row['requirement_id'])
                    semantic = next(r for r in history['revisions'] if r['revision'] == row['current_revision'])
                    prerequisite_requirements.append({**{k: row.get(k) for k in
                        ('requirement_id', 'current_revision', 'title', 'statement', 'category', 'source_anchor')},
                        'rationale': semantic['rationale'], 'retired': row['lifecycle_status'] == 'removed'})
            milestone['prerequisite_requirements'] = prerequisite_requirements
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
        intents = [v for u in (plan or {}).get('units', []) for v in u.get('verifies', []) if v.get('authority_ref')]
        required_refs = {'campaign:' + str(c) for c in packet.get('required_campaign_ids', [])}
        refs = {v['authority_ref'] for v in intents} | required_refs
        deferred_refs = {v['authority_ref'] for v in intents if v['kind'] in CAMPAIGN_VERIFICATION_KINDS}
        other_refs = {v['authority_ref'] for v in intents if v['kind'] not in CAMPAIGN_VERIFICATION_KINDS} | required_refs
        deferred_campaigns = {}
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
                    ref = 'campaign:' + campaign_id
                    resolved[ref] = semantic
                    campaigns.append(semantic)
                    if (external['consumption_mode'] == 'external_agent' and ref in deferred_refs
                            and required_host_cases(state)):
                        deferred_campaigns[ref] = state
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
        referenced_basis = {
            ref: campaign_plan_basis(value) if ref in deferred_campaigns and ref not in other_refs else value
            for ref, value in resolved.items()
        }
        authority_basis = {'project_id': project_id, 'change_id': change_id, 'change': basis_change, 'packet': basis_packet,
                           'plan': basis_plan, 'criteria': external['criteria'], 'requirements': semantic_requirements,
                           'goals': goals, 'goal_edges': goal_edges, 'accepted_answers': answers, 'accepted_risk_context': pressure_context, 'referenced_authority': referenced_basis,
                           'predecessor_authority': [{'packet_id': predecessor['packet_id'], 'authority_fingerprint': fingerprint(predecessor['authority_basis'])}
                                                     for predecessor in predecessors]}
        if 'criterion_dispositions' in external:
            authority_basis['criterion_dispositions'] = external['criterion_dispositions']
        architecture = self._ledger.resolve_architecture_refs(project_id, packet.get('architecture_refs', []))
        if architecture is not None:
            basis_packet['architecture_refs'] = packet['architecture_refs']
            authority_basis['architecture'] = architecture_authority_context(architecture)
        if milestone_id:
            authority_basis['milestone'] = milestone
        snapshot = {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id, 'packet': packet, 'change': basis_change,
                'plan': plan, 'external': external, 'requirements': requirements, 'goals': goals, 'milestone': milestone,
                'predecessor_packets': predecessors,
                'construction': construction, 'answers': answers, 'resolved_authorities': resolved,
                'deferred_campaigns': deferred_campaigns,
                'goal_edges': goal_edges, 'pressure_context': pressure_context, 'pressure_stale': pressure_stale,
                'campaigns': campaigns, 'authority_basis': authority_basis,
                'architecture': architecture,
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
                _cache=cache, _path=(*_path, packet_id), _change=change)
            authority_basis['contextual_predecessor_authority'] = fingerprint(snapshot['contextual_predecessor']['authority_basis'])
        contextual = snapshot.get('contextual_predecessor') or {}
        if ('criterion_dispositions' in authority_basis or referenced_basis != resolved
                or 'provider_authority_basis' in contextual
                or any('provider_authority_basis' in predecessor for predecessor in predecessors)):
            provider_basis = {key: value for key, value in authority_basis.items() if key != 'criterion_dispositions'}
            provider_basis['referenced_authority'] = resolved
            provider_basis['predecessor_authority'] = [
                {'packet_id': predecessor['packet_id'], 'authority_fingerprint': fingerprint(
                    predecessor.get('provider_authority_basis', predecessor['authority_basis']))}
                for predecessor in predecessors]
            if 'provider_authority_basis' in contextual:
                provider_basis['contextual_predecessor_authority'] = fingerprint(contextual['provider_authority_basis'])
            snapshot['provider_authority_basis'] = provider_basis
        audit_key = ('repository_review_audits', project_id)
        if audit_key not in cache:
            cache[audit_key] = self._ledger.read_projection('engineering_cycle_audits', (project_id,),
                lambda: self._ledger.all_phase_audits(project_id))
        snapshot['engineering_cycle_version'] = (plan or {}).get('engineering_cycle_version')
        snapshot['repository_review'] = repository_review_projection(snapshot, cache[audit_key],
                                                                     observed_source=observed_source)
        cache[packet_id] = snapshot
        return snapshot

    def validation(self, project_id: str, change_id: str, packet_id: str, *, detail: str = 'standard',
                   history_offset=0, observed_source=None) -> Mapping[str, object]:
        if detail not in {'standard', 'full'}:
            raise ValueError('detail must be standard or full')
        if isinstance(history_offset, bool) or not isinstance(history_offset, int) or history_offset < 0:
            raise InputValidationError('history_offset must be a nonnegative integer', field='payload.history_offset',
                                       received_value=history_offset)
        if history_offset and detail != 'full':
            raise InputValidationError('history_offset requires detail=full', field='payload.history_offset',
                                       received_value=history_offset)
        source_observation = normalize_observed_repository_source(observed_source)
        with self._ledger.consistent_read():
            # Original reports remain readable even when current authority cannot
            # be resolved. This path never supplies executable admission.
            raw = self._ledger.external_work_state(project_id, change_id, packet_id) if detail == 'full' else None
            try:
                observation = {'observed_source': source_observation} if source_observation is not None else {}
                snapshot = self._snapshot(project_id, change_id, packet_id, **observation)
            except (ChangeControlBlockedError, ValueError) as exc:
                if detail != 'full':
                    raise
                plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id)
                version = engineering_cycle_version(plan)
                return {'status': 'blocked', 'reason': getattr(exc, 'reason', 'current_authority_unresolved'),
                        'diagnostic': {'cause': str(exc), 'scope': {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id},
                                       'resolution': 'Inspect original report provenance and resolve the named canonical authority; reading history does not authorize execution.'},
                        'execution_allowed': False, 'execution_readiness': 'not_evaluated',
                        'repository_review': {'contract_version': 'flow.repository-review-projection.v1',
                                              'state': 'authority_blocked', 'engineering_cycle_version': version,
                                              'required': version == 1 and raw['consumption_mode'] == 'external_agent',
                                              'complete': False, 'scope_id': '', 'requirement_ids': [],
                                              'basis_fingerprint': None, 'latest_audit_id': None, 'source': None,
                                              'source_applicability': {'state': 'not_evaluated'},
                                              'coverage': [], 'retrospective_recorded': False,
                                              'semantic_truth_verified': False, 'human_acceptance': False,
                                              'next_gate': self._history_route(project_id, change_id, packet_id)},
                        **self._report_history(raw['reports'], history_offset=history_offset),
                        'next_gate': self._history_route(project_id, change_id, packet_id), 'acceptance': 'not_inferred'}
            projection = self._projection(snapshot)
            pvp_gate = self._validation_gate(projection, snapshot)
            gate = pvp_gate
            inactive = snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES
            current_plan_gate = None if inactive else self._current_plan_gate(snapshot, projection, pvp_gate)
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
            recovery = self._pending_historical_gate(snapshot, projection, dependencies) if execution_allowed else None
            if recovery is not None:
                execution_allowed = False
                admission = {'reason': _RECOVERY_REQUIRED, 'details': {}, 'next_gate': recovery}
            if current_plan_gate is not None:
                gate = current_plan_gate
            displayed_reason = (gate.get('reason') if current_plan_gate is not None
                                else (projection['next_gap'] or {}).get('code', ''))
            return {'status': 'success' if (projection['status'] == 'closed' and not inactive
                                           and admission is None and current_plan_gate is None) else 'blocked',
                    'reason': 'external_packet_inactive' if inactive else (admission['reason'] if admission else displayed_reason),
                    'validation': projection if detail == 'full' else {k: projection[k] for k in ('contract_version', 'consumer_scope', 'status', 'authority_fingerprint', 'spec_revision', 'plan_revision', 'next_gap')},
                    'next_gate': self._inactive_gate(snapshot) if inactive else ((admission.get('next_gate') or {'tool': 'fow_handover', 'operation': 'project_state_snapshot', 'reason': admission['reason']}) if admission else gate), 'consumption_mode': snapshot['external']['consumption_mode'],
                    'plan_executable': plan_executable, 'execution_allowed': execution_allowed, 'execution_admission': admission,
                    'gate_context': self._gate_context(snapshot, projection, execution_allowed=execution_allowed,
                        admission_state='blocked' if admission else 'passed', admission=admission, validation_gate=pvp_gate),
                    'engineer_gate': snapshot.get('engineer_gate'),
                    'packet_dependencies': dependencies, 'repository_review': snapshot['repository_review'],
                    **(self._report_history(raw['reports'], snapshot=snapshot, projection=projection, history_offset=history_offset)
                       if detail == 'full' else {})}

    def _current_plan_gate(self, snapshot, projection, pvp_gate):
        from flow_of_work_mcp.application.packet_guards import PacketGuardBlocker, PacketGuardDecision
        from flow_of_work_mcp.application.packet_next_action import PacketNextActionProjectionService

        plan = snapshot.get('plan') or {}
        if snapshot['external']['consumption_mode'] != 'external_agent':
            if self._non_external_guard is None:
                return None
            # The non-external guard uses provider admission, which reads the
            # semantic projection directly. The external branch calls validation.
            decision = self._non_external_guard(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])
            if decision.next_operation not in {'executor_select', 'architecture_required', 'external_select_mode'}:
                return None
        elif plan.get('status') == 'proposed':
            repair = pvp_gate.get('repair') or {}
            if (repair.get('operation') or {}).get('operation') == 'classify_criteria':
                gap = repair['obligation']['code']
                decision = PacketGuardDecision(
                    'external_validation_open', False, False, False,
                    (PacketGuardBlocker(gap, 'packet_validation', 'external_classify_criteria'),),
                    (), (), 'external_classify_criteria',
                )
            elif not repair and (projection.get('next_gap') or {}).get('code') == 'work_plan_not_accepted':
                decision = PacketGuardDecision(
                    'needs_instructions', False, False, False, (),
                    ('accept_work_plan',), (), 'accept_work_plan',
                )
            else:
                return None
        else:
            return None
        return PacketNextActionProjectionService().project(
            decision, project_id=snapshot['project_id'], change_id=snapshot['change_id'],
            packet_id=snapshot['packet_id'], spec_revision=projection['spec_revision'],
            plan_revision=projection['plan_revision'],
        )

    @staticmethod
    def _gate_context(snapshot, projection, *, execution_allowed=False,
                      admission_state='not_evaluated', admission=None, validation_gate=None):
        """Describe observed gates only; never re-evaluate guards or grant admission."""
        gate = validation_gate if validation_gate is not None else ExternalWorkService._validation_gate(projection, snapshot)
        gap = gate.get('repair', {}).get('obligation') or projection['next_gap']
        diagnostic = None
        if gap:
            diagnostic = deepcopy(gap)
            diagnostic.update(
                message='The recorded plan or canonical authority has an unresolved obligation.',
                resolution=gate.get('repair', {}).get('guidance') or
                    'Inspect the named current canonical authority and resolve this obligation through ordinary engineering mutations and validation. Do not invent evidence or waive obligations.')
            if gap['code'] == 'unit_check_verification_missing':
                diagnostic.update(
                    declaration_match=False,
                    expected_source='same-unit verifies[kind=unit_check].statement',
                    expected_count_meaning='Distinct declared comparison candidates; not test executions, passed checks or semantic endorsement.',
                    rule='Exact statement equality after canonical text normalization in the same unit; criterion prose and implements do not determine the mapping.',
                    message='This unit_checks statement has no exactly matching same-unit kind=unit_check verification declaration. The received and expected strings below are original declarations, not execution results.')
        engineer = snapshot.get('engineer_gate') or {}
        flag = engineer.get('execution_allowed')
        return {
            'contract_version': 'flow.external-work-gates.v1',
            'execution_allowed': execution_allowed,
            'validation': {'state': projection['status'], 'next_gap': deepcopy(projection['next_gap']),
                           'next_gate': deepcopy(gate), 'diagnostic': diagnostic},
            'admission': {'state': admission_state, 'reason': (admission or {}).get('reason', ''),
                          'next_gate': deepcopy((admission or {}).get('next_gate')),
                          'inspection_route': ExternalWorkService._history_route(
                              snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])},
            'engineer_gate': {'scope': 'semantic_findings_only',
                              'state': 'passed' if flag is True else 'blocked' if flag is False else 'not_evaluated',
                              'establishes_global_admission': False},
        }

    @staticmethod
    def _history_route(project_id, change_id, packet_id):
        return {'tool': 'fow_external_work', 'operation': 'validation',
                'arguments': {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id,
                              'operation': 'validation', 'payload': {'detail': 'full'}},
                'reason': 'read_original_report_provenance_without_execution'}

    @staticmethod
    def _recovery_gate(snapshot, projection, row):
        address = {key: snapshot[key] for key in ('project_id', 'change_id', 'packet_id')}
        return {
            'action_kind': 'external_obligation',
            'external_operation': 'inspect_historical_outcome',
            'reason': _RECOVERY_REQUIRED,
            'unit_key': row['unit_key'],
            'current_authority': _authority_pin(projection),
            'original_report': row['historical_outcome'],
            'effect_policy': 'inspection_and_review_only',
            'inspect_route': ExternalWorkService._history_route(**address),
            'repository_review_route': snapshot['repository_review'].get('next_gate'),
            'settlement_route': {'tool': 'fow_external_work', 'operation': 'report_outcome',
                                 'arguments': {**address, 'operation': 'report_outcome'}},
            'guidance': ('Compare the original issued unit, source and effects against current authority before further effects. '
                         'After bounded inspection, record an independently verified current outcome with a new report key. '
                         'If the work itself changed, reassess and revise the affected plan through ordinary authority. '
                         'Retain the original report and do not re-run effects or substitute pins on old evidence.'),
        }

    @staticmethod
    def _pending_historical_gate(snapshot, projection, dependencies):
        if not _historical_materializations(snapshot, projection):
            return None
        rows, *_ = resolve_current_reports(snapshot, projection, packet_dependencies=dependencies)
        recovery = _recovery_frontier(rows)
        return ExternalWorkService._recovery_gate(snapshot, projection, recovery) if recovery else None

    @staticmethod
    def _report_history(reports, *, snapshot=None, projection=None, history_offset=0):
        result = []
        for report in reports[history_offset:history_offset + 20]:
            if snapshot is None or projection is None:
                state, reason = 'not_evaluated', 'current_authority_unresolved'
            else:
                state = 'current_authority' if _report_matches_authority(report, projection) else 'historical_on_original_pin'
                reason = ('current_report_conflict' if report['disposition'] == 'conflict' else 'matches_current_authority') if state == 'current_authority' else 'issued_authority_differs_or_report_was_stale'
            result.append({k: report.get(k) for k in ('report_identity', 'report_key', 'unit_key', 'spec_revision', 'plan_revision', 'authority_fingerprint', 'disposition', 'actor', 'occurred_at')})
            result[-1].update(source_revision=report['payload']['source_revision'], outcome=report['payload']['outcome'],
                              summary=report['payload']['summary'], provenance='host_reported',
                              currentness=state, currentness_reason=reason,
                              compatibility='not_assessed_by_history_read', semantic_truth_verified=False, human_acceptance=False)
        end = history_offset + len(result)
        return {'report_history': result, 'report_history_page': {'offset': history_offset, 'limit': 20, 'total': len(reports),
                'truncated': end < len(reports), 'next_offset': end if end < len(reports) else None},
                'history_rule': 'Original pins and provenance are preserved. Missing current reports do not prove missing implementation.'}

    def _replayed_outcome(self, project_id, change_id, packet_id, receipt, payload):
        address = {'project_id': project_id, 'change_id': change_id, 'packet_id': packet_id}
        try:
            snapshot = self._snapshot(**address)
            projection = self._projection(snapshot)
        except (ChangeControlBlockedError, ChangeNotFoundError, ValueError):
            # An exact retry can recover its immutable receipt even if the
            # current packet authority cannot be composed. Offer inspection.
            snapshot, projection = address, None
        return self._outcome_replay_view(snapshot, projection, receipt, payload, exact_request=True)

    def _outcome_replay_view(self, snapshot, projection, receipt, payload, *, exact_request=False):
        report = next((row for row in (snapshot.get('external') or {}).get('reports', [])
                       if row['report_key'] == receipt['report_key']), None)
        evaluated = projection is not None and report is not None
        matches = evaluated and _report_matches_authority(report, projection)
        address = {key: snapshot[key] for key in ('project_id', 'change_id', 'packet_id')}
        if matches:
            cached_gate = receipt.get('next_gate') or {}
            if cached_gate.get('external_operation') != 'execute_unit' or self._todo(snapshot).get('next_gate') == cached_gate:
                # Preserve the established exact replay when the pin and the
                # recorded effects gate still agree with current authority.
                return receipt
            state, reason = 'current_authority', 'current_execution_gate_changed'
            status, disposition = receipt['status'], receipt['disposition']
            route = {'tool': 'fow_external_work', 'operation': 'todo',
                     'arguments': {**address, 'operation': 'todo'}, 'reason': reason}
        else:
            state, reason = (('historical_on_original_pin', 'stale_authority') if evaluated else
                             ('not_evaluated', 'current_authority_unresolved'))
            status, disposition = ('historical', 'stale') if evaluated else ('blocked', 'not_evaluated')
            route = self._history_route(**address)
        issued = (_authority_pin(report) if report is not None else
                  {'spec_revision': payload.get('expected_spec_revision'),
                   'plan_revision': payload.get('expected_plan_revision'),
                   'authority_fingerprint': payload.get('authority_fingerprint')})
        return {**{key: value for key, value in receipt.items() if key not in {'next_gate', 'repository_review'}},
                'status': status, 'reason': reason, 'disposition': disposition, 'replayed': True,
                'execution_allowed': False, 'next_gate': route,
                'receipt_applicability': {
                    'state': state,
                    'recorded_disposition': receipt['disposition'], 'issued_authority': issued,
                    'current_authority': _authority_pin(projection) if projection is not None else None,
                    'reason': reason,
                },
                **({'recorded_receipt': receipt} if exact_request else {})}

    @staticmethod
    def _projection(snapshot, *, consumer_scope='external_agent', _cache=None) -> dict[str, object]:
        # Snapshot identity and consumer are local to this invocation. Never
        # attach validation results to snapshots also used by mutation flows.
        cache = {} if _cache is None else _cache
        identity = (id(snapshot), consumer_scope)
        if identity in cache:
            return deepcopy(cache[identity])
        projection_input = snapshot
        if consumer_scope == 'provider' and 'provider_authority_basis' in snapshot:
            projection_input = {**snapshot, 'authority_basis': snapshot['provider_authority_basis']}
        projection = derive_packet_validation(projection_input, consumer_scope=consumer_scope)
        architecture = snapshot.get('architecture')
        if architecture:
            projection['gaps'].extend(architecture.get('gaps', []))
            if architecture.get('applicability', {}).get('status') == 'stale' and projection['status'] != 'historical_unprojected':
                projection['status'] = 'stale'
        for kind in ('requirement', 'goal', 'milestone'):
            for identity in snapshot.get('missing_' + kind + '_ids', []):
                projection['gaps'].append({'code': kind + '_authority_missing', 'reference': identity})
        projection['gaps'].extend(milestone_prerequisite_gaps(snapshot.get('milestone')))
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
        for predecessor in (snapshot.get('predecessor_packets', []) if consumer_scope == 'external_agent' else []):
            predecessor_projection = ExternalWorkService._projection(predecessor, _cache=cache)
            if predecessor_projection['status'] != 'closed' or predecessor['external']['consumption_mode'] != 'external_agent':
                projection['gaps'].append({'code': 'packet_dependency_plan_not_executable', 'packet_id': predecessor['packet_id'],
                    'validation_status': predecessor_projection['status'], 'consumption_mode': predecessor['external']['consumption_mode'],
                    'next_gap': predecessor_projection['next_gap']})
        if projection['gaps'] and projection['status'] == 'closed':
            projection['status'] = 'open'
        projection['next_gap'] = projection['gaps'][0] if projection['gaps'] else None
        cache[identity] = deepcopy(projection)
        return deepcopy(projection)

    def provider_validation(self, project_id: str, change_id: str, packet_id: str) -> dict[str, object]:
        """One pure semantic snapshot; provider target/materialization truth stays separate."""
        with self._ledger.consistent_read():
            snapshot = self._snapshot(project_id, change_id, packet_id)
            projection = self._projection(snapshot, consumer_scope='provider')
            basis = snapshot.get('provider_authority_basis', snapshot['authority_basis'])
            projection['authority_context'] = {key: value for key, value in basis.items()
                                               if key not in {'plan', 'criteria'}}
            admission = None
            try:
                self._assert_execution_allowed(snapshot)
            except ChangeControlBlockedError as exc:
                admission = {'reason': exc.reason, 'details': dict(exc.details)}
            if admission is None:
                blocked = []
                for predecessor in snapshot.get('predecessor_packets', []):
                    if predecessor['external']['consumption_mode'] == 'external_agent':
                        closure = self._local_closure(predecessor, self._projection(predecessor), self._packet_dependencies(predecessor))
                    elif self._packet_executor is not None:
                        closure = self._packet_executor.implementation_closure(project_id, change_id, predecessor['packet_id'])
                    else:
                        closure = {'complete': predecessor['packet']['status'] == 'implemented', 'reason': 'canonical_packet_not_implemented'}
                    if not closure['complete']:
                        blocked.append({'packet_id': predecessor['packet_id'], 'reason': closure.get('reason', '')})
                if blocked:
                    admission = {'reason': 'packet_dependencies_unresolved', 'details': {'dependencies': blocked}}
            projection['execution_admission'] = admission
            from flow_of_work_mcp.application.packet_guards import PacketGuardEvaluator
            upstream = PacketGuardEvaluator.evaluate_upstream({
                'packet': snapshot['packet'], 'work_plan': snapshot['plan'] or {},
                'construction': snapshot['construction'], 'pressure': snapshot['pressure_context'] or {},
                'reconciliation': self._ledger.packet_reconciliation_for_packet(project_id, change_id, packet_id) or {},
            })
            projection['upstream_gate'] = upstream.as_payload() if upstream is not None else None
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
        review = snapshot['repository_review']
        reconciliation_complete = not review['required'] or review['complete']
        complete = implementation_complete and local_verification_complete and dependencies['ready'] and reconciliation_complete
        reason = ''
        if not scope_complete:
            reason = 'external_mode_not_selected' if snapshot['external']['consumption_mode'] != 'external_agent' else (
                'external_packet_inactive' if snapshot['packet']['status'] in {'superseded', 'cancelled'} else
                (projection['next_gap'] or {}).get('code', 'external_unit_scope_missing'))
        elif not dependencies['ready']:
            reason = 'packet_dependencies_unresolved'
        elif implementation_complete and local_verification_complete and not reconciliation_complete:
            reason = 'repository_review_required'
        elif not complete:
            reason = _RECOVERY_REQUIRED if _recovery_frontier(rows) else 'external_unit_reports_incomplete'
        return {'scope_complete': scope_complete, 'implementation_complete': implementation_complete,
            'local_verification_complete': local_verification_complete, 'dependencies_complete': dependencies['ready'], 'complete': complete,
            'reconciliation_complete': reconciliation_complete, 'repository_review': review,
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
    def _validation_gate(projection, snapshot) -> dict[str, object]:
        gap = projection['next_gap']
        gate = {'operation': 'validation' if gap else 'todo', 'tool': 'fow_external_work',
                'action_kind': 'semantic_authority_repair' if gap else 'read_work_frontier',
                'reason': gap['code'] if gap else 'validation_closed',
                'obligation': gap or {}, 'authority_fingerprint': projection['authority_fingerprint']}
        repair_codes = {
            'unit_check_verification_missing', 'criterion_owner_missing',
            'verification_intent_missing', 'planned_contract_missing',
            'contract_not_in_dependency_closure',
        }
        strict = 'criterion_dispositions' in snapshot['external']
        if strict:
            repair_codes.update(CRITERION_RESPONSIBILITY_GAPS)
        if not gap or snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES:
            return gate
        plan = snapshot.get('plan')
        if (gap['code'] == 'packet_validation_upgrade_required'
                and snapshot['external']['consumption_mode'] == 'external_agent'
                and (not plan or plan['status'] == 'proposed')):
            gate['repair'] = ExternalWorkService._criterion_authoring_repair(snapshot, projection, gap)
            return gate
        # Acceptance is ordered before declaration gaps in the projection. Help
        # repair those facts without changing that order or accepting the plan.
        selected = (next((item for item in projection['gaps'] if item['code'] in repair_codes), None)
                    if gap['code'] == 'work_plan_not_accepted' else gap)
        if strict and gap['code'] in {'work_plan_missing', 'verification_intent_missing'}:
            selected = next((item for item in projection['gaps'] if item['code'] in {
                'criterion_statement_id_only', 'criterion_disposition_missing', 'criterion_disposition_invalid',
            }), selected)
        if not selected or selected['code'] not in repair_codes:
            return gate
        if strict and selected['code'] in CRITERION_RESPONSIBILITY_GAPS:
            gate['repair'] = ExternalWorkService._criterion_authoring_repair(snapshot, projection, selected)
            return gate
        arguments = {key: snapshot[key] for key in ('project_id', 'change_id', 'packet_id')}
        arguments.update(operation='revise_unit', expected_spec_revision=projection['spec_revision'],
                         expected_plan_revision=projection['plan_revision'])
        # A missing contract does not identify which declaration is wrong.
        key = selected.get('unit_key') if selected['code'] != 'planned_contract_missing' else None
        known_keys = {unit['client_unit_key'] for unit in projection['units']}
        if key in known_keys:
            arguments['client_unit_key'] = key
        guidance = {
            'unit_check_verification_missing': 'Investigate which active criterion this local check verifies. Declare its exact statement in same-unit verifies with kind=unit_check, or ordinarily correct an erroneous obligation against confirmed intent. Criterion prose and implements do not determine this mapping; never remove or defer checks merely to close PVP.',
            'criterion_owner_missing': 'Inspect the active criterion and current units. Choose its legitimate implementation or verification owner through engineering investigation; Flower does not select an owner or invent a criterion mapping.',
            'verification_intent_missing': 'Inspect the active criterion and choose the responsible unit and appropriate verification kind/statement. Preserve the actual unit boundary and deferred obligations; Flower does not invent a verification intent.',
            'planned_contract_missing': 'Inspect both producer provides and consumer requires. Decide whether the producer declaration is incomplete or the consumer reference is wrong before selecting a unit. Planned outputs are promises, not evidence that files exist.',
            'contract_not_in_dependency_closure': 'Inspect the consumer requires and intended predecessor contract. Correct an erroneous reference with revise_unit, or explicitly use set_dependencies with the complete investigated depends_on list. No dependency edge is added automatically.',
        }[selected['code']]
        gate['repair'] = {
            'contract_version': 'flow.plan-authoring-repair.v1', 'ready_to_call': False,
            'execution_allowed': False, 'authoring_scope': 'confirmed_intent_only',
            'obligation': deepcopy(selected),
            'operation': {'tool': 'fow_packet_author', 'operation': 'revise_unit', 'arguments': arguments},
            'required_input': ([] if 'client_unit_key' in arguments else ['client_unit_key'])
                              + ['unit_patch', 'actor', 'request_id'],
            'help_route': {'tool': 'fow_capabilities', 'arguments': {'view': 'operation',
                'operation_tool': 'fow_packet_author', 'operation_name': 'revise_unit'}},
            'inspection_route': ExternalWorkService._history_route(
                snapshot['project_id'], snapshot['change_id'], snapshot['packet_id']),
            'guidance': guidance + ' Continue technical preparation within confirmed intent while affected repository effects remain held. Array patches replace whole arrays: preserve applicable existing declarations. Use returned current revisions, review and ordinarily accept the proposed plan, then revalidate. Missing product intent requires clarification; no hint waives approval or authorizes execution.',
        }
        return gate

    @staticmethod
    def _criterion_authoring_repair(snapshot, projection, gap):
        address = {key: snapshot[key] for key in ('project_id', 'change_id', 'packet_id')}
        revisions = {'expected_spec_revision': projection['spec_revision'], 'expected_plan_revision': projection['plan_revision']}
        code = gap['code']
        tool = 'fow_external_work'
        payload = {'expected_spec_revision': projection['spec_revision']}
        required = ['actor', 'request_id']
        if code == 'packet_validation_upgrade_required':
            operation = 'upgrade_validation'
            payload = revisions
            guidance = ('Initialize stable criterion numbers from the current packet completion criteria. '
                        'Plan revision 0 means no plan exists. Read the returned criteria before drafting or correcting units, '
                        'then classify their responsibilities against the proposed plan.')
        elif code == 'criterion_statement_id_only':
            operation = 'edit_criterion'
            payload['number'] = gap['criterion']
            required.append('payload.statement')
            guidance = 'Replace the bare requirement ID with an observable completion criterion grounded in that requirement. Read the new specification revision and classify all current criteria again.'
        elif code == 'criterion_authority_stale':
            operation = 'reconcile_criteria'
            required.extend(['payload.criteria', 'payload.rationale'])
            guidance = 'Compare stable criterion identities with current packet completion criteria. Reconcile actual drift, then classify the resulting current specification.'
        elif code in {'criterion_disposition_missing', 'criterion_disposition_invalid',
                      'criterion_verification_target_invalid', 'criterion_external_authority_unaccepted'}:
            operation = 'classify_criteria'
            payload = revisions
            required.append('payload.dispositions')
            guidance = 'Investigate the intended responsibility and record one disposition per active criterion. A verification target needs an exact recorded baseline or a producing criterion. An external-authority target needs an existing accepted scoped engineering answer. Revise an already accepted plan before changing the classification.'
        else:
            tool = 'fow_packet_author'
            operation = 'set_dependencies' if code == 'criterion_verification_target_dependency_missing' else 'revise_unit'
            arguments = {**address, **revisions, 'operation': operation}
            if gap.get('unit_key'):
                arguments['client_unit_key'] = gap['unit_key']
            else:
                required.append('client_unit_key')
            required.append('depends_on' if operation == 'set_dependencies' else 'unit_patch')
            guidance = {
                'criterion_owner_missing': 'Assign a unit that actually implements this criterion and preserve its verification obligations.',
                'criterion_implementation_owner_unexpected': 'Inspect the disposition and the implementation assignment. Correct the actual mismatch and retain valid verification obligations.',
                'criterion_unknown_or_retired': 'Inspect the unit declarations and active criterion identities. Correct the invalid reference without guessing its replacement.',
                'verification_intent_missing': 'Declare a responsible verifier and the bounded check that verifies this criterion.',
                'criterion_verification_target_dependency_missing': 'Make the verifier depend on its intended producing unit, preserving its other dependency edges, or correct the declared target if it was wrong.',
                'criterion_external_authority_verification_missing': 'Declare explicit_authority verification for the same accepted authority reference as the criterion target.',
                'external_authority_missing': 'Inspect the referenced verification authority. Select a supported current reference or correct the declaration while preserving the criterion verification obligation.',
            }[code]
        if tool == 'fow_external_work':
            arguments = {**address, 'operation': operation, 'payload': payload}
        inspect_operation = 'validation' if code == 'packet_validation_upgrade_required' else 'criteria'
        return {'contract_version': 'flow.plan-authoring-repair.v1', 'ready_to_call': False,
                'execution_allowed': False, 'authoring_scope': 'confirmed_intent_only', 'obligation': deepcopy(gap),
                'operation': {'tool': tool, 'operation': operation, 'arguments': arguments}, 'required_input': required,
                'help_route': {'tool': 'fow_capabilities', 'arguments': {'view': 'operation',
                    'operation_tool': tool, 'operation_name': operation}},
                'inspection_route': {'tool': 'fow_external_work', 'operation': inspect_operation,
                    'arguments': {**address, 'operation': inspect_operation}},
                'guidance': guidance + ' Keep repository execution held until review, ordinary plan acceptance and revalidation.'}

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

    def _classify_criteria(self, snapshot, payload):
        operation = 'classify_criteria'
        fields(payload, {'expected_spec_revision', 'expected_plan_revision', 'dispositions'}, operation)
        self._expect(snapshot, payload, plan_required=True)
        state = snapshot['external']
        if 'criterion_dispositions' not in state:
            raise ChangeControlBlockedError('criterion_responsibility_policy_not_active')
        packet = snapshot['packet']
        if packet['status'] in PACKET_INACTIVE_STATUS_VALUES:
            raise ChangeControlBlockedError('external_packet_inactive', details={'packet_status': packet['status']})
        plan = snapshot['plan'] or {}
        if plan.get('status') == 'accepted' and plan.get('packet_revision') == packet['spec_revision']:
            raise ChangeControlBlockedError('criterion_responsibility_plan_already_accepted')
        if state['criterion_statement_fingerprint'] != fingerprint(packet['completion_criteria']):
            raise ChangeControlBlockedError('criterion_authority_stale')
        active = {criterion['number'] for criterion in state['criteria'] if criterion['active']}
        declarations = {}
        for entry in objects(payload.get('dispositions'), 'dispositions', max_items=len(active)):
            fields(entry, {'number', 'disposition', 'target'}, 'disposition')
            identity = number(entry.get('number'), 'number')
            if identity not in active or identity in declarations:
                raise InputValidationError('Use each active criterion number exactly once.', field='payload.dispositions',
                                           received_value=identity)
            disposition = text(entry.get('disposition'), 'disposition')
            declaration = {'number': identity, 'disposition': disposition}
            if disposition == 'implementation':
                if 'target' in entry:
                    raise ValueError('implementation disposition must omit target')
            elif disposition in {'verification_only', 'external_authority'}:
                declaration['target'] = self._criterion_target(entry.get('target'), disposition)
            else:
                raise ValueError('disposition must be implementation, verification_only, or external_authority')
            declarations[identity] = declaration
        if missing := sorted(active - declarations.keys()):
            raise InputValidationError('Classify every active criterion in this specification.', field='payload.dispositions',
                                       received_value=len(declarations),
                                       details={'missing_criteria': missing[:10], 'missing_count': len(missing)})
        return {'status': 'success', 'change_id': snapshot['change_id'], 'packet_id': snapshot['packet_id'],
                'spec_revision': packet['spec_revision'], 'dispositions': [declarations[key] for key in sorted(declarations)]}

    @staticmethod
    def _criterion_target(target, disposition):
        if not isinstance(target, Mapping):
            raise ValueError('criterion disposition requires a target object')
        kind = text(target.get('kind'), 'target.kind')
        if (disposition, kind) in {('verification_only', 'baseline'), ('external_authority', 'authority')}:
            fields(target, {'kind', 'ref'}, 'target')
            return {'kind': kind, 'ref': text(target.get('ref'), 'target.ref')}
        if disposition == 'verification_only' and kind == 'criterion':
            fields(target, {'kind', 'criterion', 'packet_id'}, 'target')
            result = {'kind': kind, 'criterion': number(target.get('criterion'), 'target.criterion')}
            if 'packet_id' in target:
                result['packet_id'] = validate_packet_id(text(target['packet_id'], 'target.packet_id'))
            return result
        raise ValueError('verification_only targets baseline or criterion; external_authority targets authority')

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
            result = dict(self._todo(snapshot, unit_key=unit_key))
            result.setdefault('repository_review', snapshot['repository_review'])
            if result.get('status') == 'blocked':
                result['history_route'] = self._history_route(project_id, change_id, packet_id)
            return result

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
            strict = 'criterion_dispositions' in snapshot['external']
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
                    if closed and intent['unit_key'] in done:
                        obligation.update(deferred_campaign_proof(
                            snapshot, criterion, intent, effective[intent['unit_key']], self._ledger.grounding_audits,
                        ))
                    obligations.append(obligation)
                    deferred.append(obligation)
                implementation_expected = owners or (strict and criterion.get('disposition') not in
                                                       {'verification_only', 'external_authority'})
                criteria.append({**criterion, 'packet_id': packet_id,
                    'implementation_state': 'complete' if closed and owners and set(owners).issubset(done)
                                            else 'pending' if implementation_expected else 'not_applicable',
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
                'execution_allowed': closed and dependencies['ready'] and not _recovery_frontier(rows)
                                     and snapshot['packet']['status'] not in PACKET_INACTIVE_STATUS_VALUES,
                'acceptance': 'not_inferred'}

    @staticmethod
    def _inactive_gate(snapshot):
        return {'action_kind': 'external_obligation', 'external_operation': 'inspect_inactive_history',
                'packet_status': snapshot['packet']['status'], 'inspect_route': {'tool': 'fow_external_work', 'operation': 'criteria'}}

    def _todo(self, snapshot, *, unit_key='') -> Mapping[str, object]:
        projection = self._projection(snapshot)
        if snapshot['external']['consumption_mode'] != 'external_agent':
            return {'status': 'blocked', 'reason': 'external_mode_not_selected',
                    'gate_context': self._gate_context(snapshot, projection),
                    'next_gate': {'tool': 'fow_external_work', 'operation': 'set_mode'}}
        if projection['status'] != 'closed':
            return {'status': 'blocked', 'reason': projection['next_gap']['code'], 'execution_allowed': False,
                    'next_gate': self._validation_gate(projection, snapshot), 'validation': projection,
                    'gate_context': self._gate_context(snapshot, projection)}
        try:
            self._assert_execution_allowed(snapshot)
        except ChangeControlBlockedError as exc:
            return {'status': 'blocked', 'reason': exc.reason, 'next_gate': self._inactive_gate(snapshot) if snapshot['packet']['status'] in PACKET_INACTIVE_STATUS_VALUES
                    else (dict(exc.details).get('next_gate') or {'action_kind': 'external_obligation', 'external_operation': 'resolve_guided_authority', 'details': exc.details}),
                    'engineer_gate': snapshot.get('engineer_gate'), 'execution_allowed': False,
                    'gate_context': self._gate_context(snapshot, projection, admission_state='blocked',
                        admission={'reason': exc.reason, 'next_gate': dict(exc.details).get('next_gate')}),
                    'repository_review': snapshot['repository_review'],
                    'history_route': self._history_route(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])}
        dependencies = self._packet_dependencies(snapshot)
        if not dependencies['ready']:
            first = next(row for row in dependencies['predecessors'] if not row['complete'])
            return {'status': 'blocked', 'reason': 'packet_dependencies_unresolved', 'packet_dependencies': dependencies,
                'gate_context': self._gate_context(snapshot, projection, admission_state='passed'),
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
        if unit_key:
            selected = next((row for row in candidates if row['unit_key'] == unit_key), None)
        else:
            selected = _recovery_frontier(candidates) or next((row for row in candidates
                if row['status'] in {'actionable', 'blocked', 'failed', 'conflict', 'stale'} and not row['dependencies_pending']), None)
        deferred = []
        criteria = {criterion['number']: criterion for criterion in projection['criteria']}
        for u in projection['units']:
            current_report = effective.get(u['client_unit_key']) if u['client_unit_key'] in done else None
            for intent in u['verifies']:
                if intent['kind'] == 'unit_check':
                    continue
                evidence = next((v for v in (current_report or {}).get('payload', {}).get('verification', [])
                                 if (v['criterion'], v['kind'], v['statement']) == (intent['criterion'], intent['kind'], intent['statement'])), None)
                obligation = {'unit_key': u['client_unit_key'], **intent,
                              'state': 'host_reported_' + evidence['status'] if evidence else 'verification_pending',
                              'evidence': evidence, 'attestation': 'not_inferred'}
                if current_report is not None:
                    obligation.update(deferred_campaign_proof(
                        snapshot, criteria[intent['criterion']], intent, current_report, self._ledger.grounding_audits,
                    ))
                deferred.append(obligation)
        recovery = bool(selected and selected['status'] == 'recovery_required' and not selected['dependencies_pending'])
        execution = {}
        if recovery:
            gate = self._recovery_gate(snapshot, projection, selected)
            execution = {'reason': _RECOVERY_REQUIRED, 'execution_allowed': False}
        elif selected:
            operation = 'reconcile_outcome' if selected['status'] == 'conflict' else 'resolve_external_blocker' if selected['status'] in {'blocked', 'failed', 'stale'} and not selected['dependencies_pending'] else 'execute_unit' if selected['status'] == 'actionable' else 'complete_predecessors'
            gate = ({'tool': 'fow_external_work', 'operation': 'reconcile_outcome'} if operation == 'reconcile_outcome' else
                    {'action_kind': 'external_agent_execution' if operation == 'execute_unit' else 'external_obligation', 'external_operation': operation,
                     'report_route': {'tool': 'fow_external_work', 'operation': 'report_outcome'}})
            gate.update({'unit_key': selected['unit_key'], 'reason': selected['status']})
            if unit_key and operation == 'execute_unit':
                execution = {'execution_allowed': True}
        elif candidates:
            gate = {'action_kind': 'external_obligation', 'external_operation': 'complete_predecessors', 'reason': 'dependencies_pending',
                    'inspect_route': {'tool': 'fow_external_work', 'operation': 'todo'}}
        else:
            review = snapshot['repository_review']
            if review['required'] and not review['complete']:
                gate = {**review['next_gate'], 'reason': 'repository_review_required'}
            elif any(obligation['state'] != 'verified' for obligation in deferred):
                gate = {'action_kind': 'verification_or_acceptance', 'external_operation': 'obtain_deferred_verification',
                        'reason': 'agent_work_complete_acceptance_pending'}
            else:
                gate = {
                    'action_kind': 'external_packet_disposition',
                    'external_operation': 'record_technical_disposition',
                    'reason': 'external_work_complete',
                    **packet_technical_disposition_route(
                        snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'],
                        tuple(snapshot['packet']['completion_criteria']),
                    ),
                }
        criterion_traceability = []
        for criterion in projection['criteria']:
            evidence = [dict(v, unit_key=key, report_key=r['report_key'], source_revision=r['payload']['source_revision'], evidence_authority='host_reported')
                        for key, r in effective.items() if r and key in done
                        for v in r['payload']['verification'] if v['criterion'] == criterion['number']]
            criterion_traceability.append({**criterion, 'evidence': evidence, 'acceptance': 'not_inferred'})
        return {'status': 'success', 'consumption_mode': 'external_agent', 'engineer_gate': snapshot.get('engineer_gate'), 'authority_fingerprint': current,
                'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
                'todos': rows, 'current_unit': selected, 'deferred_verification': deferred, 'next_gate': gate,
                'packet_dependencies': self._packet_dependencies(snapshot), 'repository_review': snapshot['repository_review'],
                'acceptance': 'not_inferred', 'historical_reports': [r['report_key'] for r in snapshot['external']['reports']
                    if not _report_matches_authority(r, projection)],
                **execution,
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
        for index, evidence in enumerate(objects(payload.get('verification', []), 'verification')):
            fields(evidence, {'criterion', 'kind', 'statement', 'status', 'evidence_ref', 'provenance'}, 'verification')
            item = {'criterion': number(evidence.get('criterion')),
                    **{k: text(evidence.get(k), k) for k in ('kind', 'statement', 'status', 'provenance')},
                    'evidence_ref': text(evidence.get('evidence_ref', ''), 'evidence_ref', required=False)}
            field = f'payload.verification[{index}]'
            declared = list(unit['verifies'])
            if item['criterion'] not in {v['criterion'] for v in declared}:
                raise _verification_error(snapshot, unit, field=field + '.criterion', received=item['criterion'],
                    expected=sorted({v['criterion'] for v in declared}), criterion=item['criterion'],
                    message='verification criterion must be declared by this unit')
            same_criterion = [v for v in declared if v['criterion'] == item['criterion']]
            if item['kind'] not in {v['kind'] for v in same_criterion}:
                raise _verification_error(snapshot, unit, field=field + '.kind', received=item['kind'],
                    expected=sorted({v['kind'] for v in same_criterion}), criterion=item['criterion'],
                    message='verification kind must be declared for this unit and criterion')
            if (item['criterion'], item['kind'], item['statement']) not in intents:
                raise _verification_error(snapshot, unit, field=field + '.statement', received=item['statement'],
                    expected=[v['statement'] for v in same_criterion if v['kind'] == item['kind']],
                    criterion=item['criterion'], message='verification statement must exactly match the declared intent')
            if item['status'] not in {'pass', 'fail', 'not_run'}:
                raise _verification_error(snapshot, unit, field=field + '.status', received=item['status'],
                    expected=['pass', 'fail', 'not_run'], criterion=item['criterion'],
                    message='verification status must be pass, fail or not_run')
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
                missing = [{'criterion': criterion, 'kind': kind, 'statement': statement, 'status': 'pass'}
                           for criterion, kind, statement in sorted(required - passed)]
                raise _verification_error(snapshot, unit, field='payload.verification', received=value['verification'],
                    expected=missing, message='complete outcome requires every declared unit-local verification to pass')
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
        result = {'status': 'historical' if receipt['disposition'] == 'stale' else 'conflict' if receipt['disposition'] == 'conflict' else 'success',
                'reason': 'stale_authority' if receipt['disposition'] == 'stale' else 'outcome_reconciliation_required' if receipt['disposition'] == 'conflict' else '',
                **receipt, 'acceptance': 'not_inferred', 'provenance': 'external_agent_report'}
        if current:
            updated = self._snapshot(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])
            frontier = self._todo(updated)
            result.update(repository_review=updated['repository_review'], next_gate=frontier.get('next_gate'))
        else:
            result['next_gate'] = self._history_route(snapshot['project_id'], snapshot['change_id'], snapshot['packet_id'])
        return result

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
        prerequisite_gaps = milestone_prerequisite_gaps(snapshot.get('milestone'))
        if prerequisite_gaps:
            raise ChangeControlBlockedError(prerequisite_gaps[0]['code'], details={'gaps': prerequisite_gaps})
        allow_draft = payload.get('allow_draft', False)
        if not isinstance(allow_draft, bool):
            raise ValueError('allow_draft must be boolean')
        projection = self._projection(snapshot)
        try:
            if (snapshot['external']['validation_version'] == 2
                    and snapshot['external']['consumption_mode'] != 'external_agent'):
                raise ChangeControlBlockedError('external_mode_not_selected', details={'next_gate': {
                    'tool': 'fow_external_work', 'operation': 'set_mode'}})
            self._assert_execution_allowed(snapshot)
            if projection['status'] == 'closed' and snapshot['external']['consumption_mode'] == 'external_agent':
                dependencies = self._packet_dependencies(snapshot)
                if dependencies['ready']:
                    recovery = self._pending_historical_gate(snapshot, projection, dependencies)
                    if recovery is not None:
                        raise ChangeControlBlockedError(_RECOVERY_REQUIRED, details={'next_gate': recovery})
        except ChangeControlBlockedError as exc:
            if not allow_draft:
                raise
            projection = {**projection, 'status': 'open', 'gaps': [*projection['gaps'], {'code': exc.reason, **exc.details}]}
        if not allow_draft and projection['status'] != 'closed':
            responsibility = (next((gap for gap in projection['gaps'] if gap['code'] in CRITERION_RESPONSIBILITY_GAPS), None)
                              if 'criterion_dispositions' in snapshot['external'] else None)
            details = None
            if responsibility:
                address = {key: snapshot[key] for key in ('project_id', 'change_id', 'packet_id')}
                details = {'diagnostics': [responsibility], 'next_tool_call': {'tool': 'fow_external_work',
                    'arguments': {**address, 'operation': 'validation', 'payload': {'detail': 'full'}}}}
            raise ChangeControlBlockedError(projection['next_gap']['code'], details=details)
        content = render_plan(snapshot, projection, project_predecessor=self._projection)
        mappings = (ArtifactMapping('packet', snapshot['packet_id']),
                    *(ArtifactMapping('requirement', r['requirement_id']) for r in snapshot['requirements']),
                    *(ArtifactMapping('requirement', r['requirement_id'])
                      for r in (snapshot.get('milestone') or {}).get('prerequisite_requirements', [])
                      if r['requirement_id'] not in {item['requirement_id'] for item in snapshot['requirements']}),
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
    historical = _historical_materializations(snapshot, projection)
    rows = []
    done = set()
    effective = {}
    conflicts = set()
    for unit in projection['units']:
        key = unit['client_unit_key']
        reports = [r for r in snapshot['external']['reports']
                   if r['unit_key'] == key and _report_matches_authority(r, projection)]
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
        original = historical.get(key) if report is None and key not in conflicts else None
        if original is not None:
            status = 'recovery_required'
        contracts = []
        for use in unit['resolved_requires']:
            producer_report = effective.get(use['producer_unit_key'])
            contracts.append({**use, 'temporal_state': 'host_reported_materialized' if use['producer_unit_key'] in done else 'planned',
                              'producer_report': producer_report['report_key'] if producer_report else '',
                              'provenance': 'external_agent_report' if producer_report else 'accepted_plan'})
        rows.append({'unit_number': unit['unit_number'], 'unit_key': key, 'status': status, 'dependencies_pending': dependencies,
                     'unit': {**unit, 'resolved_requires': contracts}, 'report_key': report['report_key'] if report else '',
                     **({'historical_outcome': {**_authority_pin(original), 'report_identity': original.get('report_identity'),
                                                'report_key': original['report_key'],
                                                'source_revision': original['payload']['source_revision'],
                                                'recorded_disposition': original['disposition'],
                                                'provenance': 'external_agent_report'}} if original else {})})
    return rows, effective, done, conflicts, evidence_stale
