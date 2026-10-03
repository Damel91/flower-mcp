"""Progressive stakeholder guidance over canonical Flow authorities.

Dialogue is host-owned. Flower persists selected facts, their correspondence and
human checkpoints; it neither interviews autonomously nor invents requirements.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

from flow_of_work_mcp.core.errors import BootstrapBlockedError, ChangeControlBlockedError
from flow_of_work_mcp.application.bootstrap_input_contracts import (
    ANSWER_SCHEMA, CORRESPONDENCE_SCHEMA, REFERENCES_SCHEMA,
)


ROLE_GUIDANCE = """Act as the software engineer working with the stakeholder.
Start with scenarios: what should the software do and show? Investigate technical
questions yourself. Architecture, implementation and reuse decisions belong to
the engineer by default; involve the stakeholder in architecture when they
explicitly request that participation. Ask only unresolved intent clarifications
needed for the next semantic decision, using examples or consequences when the
stakeholder lacks information.
Keep private exploration private; record selected governing answers with their
intent, observation or proposal provenance. Author requirements, use cases and
milestones through their ordinary canonical operations, then record explicit
correspondence. When implementation behavior appears inconsistent, reread the
current canonical requirement, Goal, scenario, milestone, change and packet
intent. Record an explicit intent reassessment, then correct implementation
through an ordinary finding-linked remediation packet and regression evidence
when the correction stays within intent. Do not revise agreed intent to justify
an incorrect implementation. If newly requested behavior differs from the
agreement, clarify that requested intent, revise the ordinary Goal, scenario or
requirement authority and renew the affected roadmap confirmation before proceeding.

Present the derived roadmap: 'I have gathered enough information to define this
roadmap. Does it represent what you want, or is there anything else I need to
know?' Record the stakeholder's explicit confirmation of that exact scope.
Complete all milestones in the confirmed spectrum. Bounded coding units organize
execution; they do not require a new stakeholder interruption after each unit.
Resolve technical and evidence gaps through investigation and corrective work
within the confirmed scope. At an indispensable intent decision or a concrete
capability/evidence limit that prevents further autonomous work, show current
progress, residual obligations and the result. Ask whether to continue within
scope or review the result for requirements you may have missed. Cognitive limits
explain a pause; evidence determines progress. Implementation, verification and human
acceptance remain distinct. Flower never certifies semantic truth from dialogue
or host-supplied evidence alone."""


def _plain(value):
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _hash(value) -> str:
    return sha256(json.dumps(_plain(value), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value, field, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be nonempty text of at most {maximum} characters")
    return value.strip()


def _ids(value, field, *, required=False):
    if not isinstance(value, (list, tuple)) or len(value) > 128:
        raise ValueError(f"{field} must be a list of at most128 IDs")
    ids = tuple(_text(item, field, 128) for item in value)
    if len(set(ids)) != len(ids) or (required and not ids):
        raise ValueError(f"{field} must contain unique {'nonempty ' if required else ''}IDs")
    return ids


def _exact(value, fields, name):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValueError(f"{name} requires exactly: {', '.join(sorted(fields))}")


class GuidedBootstrapService:
    def __init__(self, ledger, *, external_work, traceability) -> None:
        self._ledger = ledger
        self._external = external_work
        self._traceability = traceability

    def _state(self, project_id, bootstrap_id):
        state = self._ledger.bootstrap_state(project_id, bootstrap_id)
        if state['path'] != 'guided_engineering':
            raise BootstrapBlockedError('guided_bootstrap_route_required')
        return state

    @staticmethod
    def _guided(state):
        return deepcopy(state['intake'].get('_guided', {}))

    def _entities(self, project_id):
        requirements = {r['requirement_id']: {'retired': r.get('lifecycle_status') == 'removed', **{k: r.get(k) for k in (
            'requirement_id', 'title', 'statement', 'category', 'current_revision', 'source_anchor')}}
                        for r in self._ledger.traceability_matrix(project_id)}
        milestones = {m['milestone_id']: {k: m.get(k) for k in (
            'milestone_id', 'name', 'requirement_ids', 'dependency_closure_ids',
            'entry_policy', 'exit_policy', 'risk_disposition')}
                      for m in self._ledger.milestones(project_id)}
        graph = self._ledger.goal_graph(project_id)
        goals = {g['goal_node_id']: {k: _plain(g.get(k)) for k in (
            'goal_node_id', 'node_type', 'title', 'payload', 'source_anchor')}
                 for g in graph['nodes']}
        return {'requirement_ids': requirements, 'milestone_ids': milestones,
                'goal_node_ids': goals}, graph

    def _reference_values(self, entities, refs):
        _exact(refs, entities, 'canonical_references')
        result = {}
        for kind in entities:
            ids = _ids(refs[kind], kind)
            missing = set(ids) - set(entities[kind])
            if missing:
                raise ValueError(f"unknown project {kind}: {', '.join(sorted(missing))}")
            result[kind] = [entities[kind][ref] for ref in sorted(ids)]
        if not any(result.values()):
            raise ValueError('correspondence requires at least one canonical reference')
        return result

    def _correspondence_gaps(self, guided, entities, *, answer_keys=None):
        gaps = []
        mappings = guided.get('correspondence', {})
        for key, answer in guided.get('answers', {}).items():
            if answer_keys is not None and key not in answer_keys:
                continue
            mapping = mappings.get(key)
            if mapping is None:
                gaps.append({'reason': 'answer_correspondence_missing', 'answer_key': key})
                continue
            try:
                current = self._reference_values(entities, mapping['canonical_references'])
                stale = (mapping['answer_revision'] != answer['revision'] or
                         mapping['canonical_fingerprint'] != _hash(current))
            except ValueError:
                stale = True
            if stale:
                gaps.append({'reason': 'answer_correspondence_stale', 'answer_key': key})
            elif mapping['disposition'] != 'consistent':
                gaps.append({'reason': mapping['disposition'], 'answer_key': key,
                             'rationale': mapping['rationale']})
        return gaps

    @staticmethod
    def _draft_context(guided, relevant_keys):
        """Retain draft intake without granting it selected-scope authority."""
        answers = guided.get('answers', {})
        mappings = guided.get('correspondence', {})
        return {
            'authority': 'outside_selected_scope',
            'unassigned_answers': {key: answer for key, answer in answers.items() if key not in mappings},
            'outside_scope_answers': {key: answer for key, answer in answers.items()
                                     if key in mappings and key not in relevant_keys},
            'outside_scope_correspondence': {key: mapping for key, mapping in mappings.items()
                                             if key not in relevant_keys},
        }

    def _replay(self, project_id, bootstrap_id, operation, mutation, actor, request_id):
        _text(actor, 'actor')
        _text(request_id, 'request_id', 512)
        return self._ledger.guided_bootstrap_replay(project_id, bootstrap_id,
            operation=operation, mutation=mutation, actor=actor.strip(), request_id=request_id.strip())

    def record_answer(self, project_id, bootstrap_id, *, answer, actor, request_id):
        _exact(answer, ANSWER_SCHEMA['required'], 'answer')
        normalized = {k: _text(answer[k], k, ANSWER_SCHEMA['properties'][k]['maxLength']) for k in answer}
        if normalized['kind'] not in ANSWER_SCHEMA['properties']['kind']['enum']:
            raise ValueError('answer kind must be intent, observation or proposal')
        with self._ledger.atomic():
            replay = self._replay(project_id, bootstrap_id, 'record_answer', normalized, actor, request_id)
            if replay is not None:
                return replay
            guided = self._guided(self._state(project_id, bootstrap_id))
            answers = guided.setdefault('answers', {})
            key = normalized['answer_key']
            if key not in answers and len(answers) >= 128:
                raise ValueError('guided intake is bounded to128 selected answers')
            answers[key] = {**normalized, 'revision': answers.get(key, {}).get('revision', 0) + 1}
            return self._ledger.record_guided_bootstrap(project_id, bootstrap_id,
                operation='record_answer', mutation=normalized, guided=guided, actor=actor, request_id=request_id)

    def record_correspondence(self, project_id, bootstrap_id, *, correspondence, actor, request_id):
        _exact(correspondence, CORRESPONDENCE_SCHEMA['required'], 'correspondence')
        key = _text(correspondence['answer_key'], 'answer_key', CORRESPONDENCE_SCHEMA['properties']['answer_key']['maxLength'])
        revision = correspondence['answer_revision']
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError('answer_revision must be a positive integer')
        disposition = correspondence['disposition']
        if not isinstance(disposition, str) or disposition not in CORRESPONDENCE_SCHEMA['properties']['disposition']['enum']:
            raise ValueError('correspondence disposition is invalid')
        normalized = {**dict(correspondence), 'answer_key':key,
                      'rationale':_text(correspondence['rationale'], 'rationale', CORRESPONDENCE_SCHEMA['properties']['rationale']['maxLength'])}
        # Normalize the references before replay comparisons.
        _exact(normalized['canonical_references'], REFERENCES_SCHEMA['required'], 'canonical_references')
        normalized['canonical_references'] = {k:list(_ids(v, k)) for k,v in normalized['canonical_references'].items()}
        with self._ledger.atomic():
            replay = self._replay(project_id, bootstrap_id, 'record_correspondence', normalized, actor, request_id)
            if replay is not None:
                return replay
            guided = self._guided(self._state(project_id, bootstrap_id))
            if guided.get('answers', {}).get(key, {}).get('revision') != revision:
                raise BootstrapBlockedError('guided_answer_revision_stale')
            entities, _ = self._entities(project_id)
            values = self._reference_values(entities, normalized['canonical_references'])
            guided.setdefault('correspondence', {})[key] = {
                **normalized, 'canonical_fingerprint':_hash(values), 'provenance':'host_declared'}
            return self._ledger.record_guided_bootstrap(project_id, bootstrap_id,
                operation='record_correspondence', mutation=normalized, guided=guided, actor=actor, request_id=request_id)

    def roadmap(self, project_id, bootstrap_id, *, milestone_ids):
        selected = _ids(milestone_ids, 'milestone_ids', required=True)
        with self._ledger.consistent_read():
            return self._roadmap(project_id, bootstrap_id, selected)

    def _roadmap(self, project_id, bootstrap_id, selected):
        state = self._state(project_id, bootstrap_id)
        guided = self._guided(state)
        entities, graph = self._entities(project_id)
        unknown = set(selected) - set(entities['milestone_ids'])
        if unknown:
            raise ValueError('unknown project milestones: ' + ', '.join(sorted(unknown)))
        milestones = [entities['milestone_ids'][m] for m in selected]
        requirement_ids = {r for m in milestones for r in m['dependency_closure_ids']}
        requirement_ids.update(r for m in milestones for r in m['requirement_ids'])
        gaps = []
        for m in milestones:
            if not m['requirement_ids'] or not m['entry_policy'] or not m['exit_policy']:
                gaps.append({'reason':'milestone_definition_incomplete', 'milestone_id':m['milestone_id']})
        if not requirement_ids:
            gaps.append({'reason':'roadmap_requirements_missing'})
        requirements = [entities['requirement_ids'][r] for r in sorted(requirement_ids) if r in entities['requirement_ids']]
        if any(r['retired'] for r in requirements):
            gaps.append({'reason':'roadmap_requirement_retired'})
        if len(requirements) != len(requirement_ids):
            gaps.append({'reason':'roadmap_requirement_missing'})
        relevant_goals = set()
        relevant_mappings = {}
        for change in self._ledger.list_changes(project_id):
            for packet in change.get('packets', []):
                if change.get('milestone_id') in selected and packet.get('status') not in {'cancelled', 'superseded'}:
                    if packet.get('unresolved_questions'):
                        gaps.append({'reason':'packet_intent_questions_open', 'packet_id':packet['packet_id'], 'questions':packet['unresolved_questions']})
                    construction = self._ledger.packet_construction_audit_for_packet(project_id, change['change_id'], packet['packet_id']) or {}
                    if int(construction.get('packet_revision', 0)) == int(packet['spec_revision']):
                        semantic_open = [q for q in construction.get('questions', [])
                            if bool(q.get('required'))
                            and q.get('question_key') not in {'target_selection', 'impact'}
                            and q.get('status') in {'open', 'blocked'}]
                        if semantic_open:
                            gaps.append({'reason':'packet_semantic_decisions_open', 'packet_id':packet['packet_id'],
                                         'questions':[{'question_id':q['question_id'], 'prompt':q['prompt']} for q in semantic_open]})
                    relevant_goals.update(packet.get('goal_ids', []))
                    relevant_goals.update(change.get('goal_ids', []))
        # Correspondence links intake to canonical scope. Resolve related Goal
        # context and Goal-only mappings together; disconnected intake remains
        # draft context, including new answers with no correspondence yet.
        while True:
            previous_goals = set(relevant_goals)
            previous_keys = set(relevant_mappings)
            for key, mapping in guided.get('correspondence', {}).items():
                refs = mapping['canonical_references']
                if (set(refs['requirement_ids']) & requirement_ids
                        or set(refs['milestone_ids']) & set(selected)
                        or set(refs['goal_node_ids']) & relevant_goals):
                    relevant_goals.update(refs['goal_node_ids'])
                    relevant_mappings[key] = mapping
            added = {e['target_goal_id'] for e in graph['edges'] if e['source_goal_id'] in relevant_goals}
            added.update(e['source_goal_id'] for e in graph['edges'] if e['target_goal_id'] in relevant_goals)
            relevant_goals.update(added)
            if previous_goals == relevant_goals and previous_keys == set(relevant_mappings):
                break
        relevant_answers = {key: answer for key, answer in guided.get('answers', {}).items()
                            if key in relevant_mappings}
        gaps[:0] = self._correspondence_gaps(guided, entities, answer_keys=relevant_mappings)
        draft_context = self._draft_context(guided, relevant_mappings)
        goals = [entities['goal_node_ids'][g] for g in sorted(relevant_goals) if g in entities['goal_node_ids']]
        edges = [{k:e[k] for k in ('source_goal_id','target_goal_id','relation')}
                 for e in graph['edges'] if e['source_goal_id'] in relevant_goals and e['target_goal_id'] in relevant_goals]
        if not any(g['node_type'] == 'use_case' for g in goals):
            gaps.append({'reason':'roadmap_relevant_use_case_missing'})
        if state['open_contradiction_count']:
            gaps.append({'reason':'bootstrap_contradiction_unresolved'})
        if state['status'] == 'cancelled':
            gaps.append({'reason':'bootstrap_cancelled'})
        basis = {'project_id':project_id, 'bootstrap_id':bootstrap_id,
                 'milestones':milestones, 'requirements':requirements, 'goals':goals, 'goal_edges':edges,
                 'answers':relevant_answers, 'correspondence':relevant_mappings}
        revision = _hash(basis)
        confirmation = guided.get('roadmap_confirmation', {})
        confirmed = (confirmation.get('roadmap_fingerprint') == revision and
                     confirmation.get('milestone_ids') == list(selected) and not gaps)
        parts = ['# Flower engineering roadmap', '',
                 f'Project: {project_id}; bootstrap: {bootstrap_id}',
                 f'Semantic roadmap fingerprint: {revision}', '',
                 'This describes the entire selected milestone spectrum. Human scope confirmation authorizes planning/execution; it does not accept implemented software.', '',
                 '## Scenarios and intent', '']
        for goal in goals:
            parts.extend([f"### {goal['goal_node_id']}: {goal['title']}", '',
                          json.dumps(goal['payload'], ensure_ascii=False, indent=2), ''])
        parts.extend(['## Requirements', ''])
        for r in requirements:
            parts.extend([f"- {r['requirement_id']}: {r['title']}", f"  {r['statement']}"])
        parts.extend(['', '## Milestones in selected order', ''])
        for m in milestones:
            parts.extend([f"### {m['milestone_id']}: {m['name']}", '',
                          json.dumps(m, ensure_ascii=False, indent=2), ''])
        parts.extend(['## Selected stakeholder answers and correspondence', '',
                      json.dumps({'answers':relevant_answers, 'correspondence':relevant_mappings}, ensure_ascii=False, indent=2), '',
                      '## Draft intake outside the selected scope', '',
                      'Unassigned or unrelated answers remain draft context. They do not govern this roadmap or authorize additional work; explicit correspondence and ordinary canonical authority are required to include them.', '',
                      json.dumps(draft_context, ensure_ascii=False, indent=2), '',
                      '## Unresolved obligations', '', json.dumps(gaps, ensure_ascii=False, indent=2), '',
                      'I have gathered enough information to define this roadmap. Does it represent what you want, or is there anything else I need to know?'])
        return {'contract_version':'flow.guided_roadmap.v1', 'project_id':project_id, 'bootstrap_id':bootstrap_id,
                'milestone_ids':list(selected), 'roadmap_fingerprint':revision, 'confirmable':not gaps,
                'confirmed':confirmed, 'gaps':gaps, 'canonical_scope':_plain(basis),
                'draft_context':_plain(draft_context),
                'markdown':'\n'.join(parts), 'semantic_completeness':'host_judgment_and_human_confirmation',
                'human_acceptance':False}

    def confirm_roadmap(self, project_id, bootstrap_id, *, milestone_ids,
                        roadmap_fingerprint, confirmation_reference, actor, request_id):
        selected = _ids(milestone_ids, 'milestone_ids', required=True)
        mutation = {'milestone_ids':list(selected), 'roadmap_fingerprint':_text(roadmap_fingerprint, 'roadmap_fingerprint', 128),
                    'confirmation_reference':_text(confirmation_reference, 'confirmation_reference')}
        with self._ledger.atomic():
            replay = self._replay(project_id, bootstrap_id, 'confirm_roadmap', mutation, actor, request_id)
            if replay is not None:
                return replay
            roadmap = self._roadmap(project_id, bootstrap_id, selected)
            if not roadmap['confirmable']:
                raise BootstrapBlockedError('guided_roadmap_not_confirmable')
            if roadmap['roadmap_fingerprint'] != mutation['roadmap_fingerprint']:
                raise BootstrapBlockedError('guided_roadmap_fingerprint_stale')
            guided = self._guided(self._state(project_id, bootstrap_id))
            guided['roadmap_confirmation'] = mutation
            return self._ledger.record_guided_bootstrap(project_id, bootstrap_id,
                operation='confirm_roadmap', mutation=mutation, guided=guided,
                actor=actor, request_id=request_id, stage='ready_for_completion')

    def execution_guard(self, project_id, packet_id):
        with self._ledger.consistent_read():
            state = self._ledger.latest_guided_bootstrap(project_id)
            if state is None:
                return
            if state['status'] == 'cancelled':
                raise ChangeControlBlockedError('guided_scope_cancelled_requires_new_cycle')
            confirmation = self._guided(state).get('roadmap_confirmation', {})
            if not confirmation:
                raise ChangeControlBlockedError('guided_roadmap_confirmation_required')
            roadmap = self._roadmap(project_id, state['bootstrap_id'], tuple(confirmation['milestone_ids']))
            if not roadmap['confirmed']:
                raise ChangeControlBlockedError('guided_roadmap_confirmation_stale')
            change_id = self._ledger.packet_change_id(project_id, packet_id)
            change = self._ledger.change_state(project_id, change_id)
            packet = next(p for p in change['packets'] if p['packet_id'] == packet_id)
            if change.get('milestone_id') not in confirmation['milestone_ids']:
                raise ChangeControlBlockedError('packet_outside_confirmed_guided_scope')

    def complete(self, project_id, bootstrap_id, *, completion_reference, actor, request_id):
        mutation = {'completion_reference':_text(completion_reference, 'completion_reference')}
        with self._ledger.atomic():
            replay = self._replay(project_id, bootstrap_id, 'complete', mutation, actor, request_id)
            if replay is not None:
                return replay
            state = self._state(project_id, bootstrap_id)
            guided = self._guided(state)
            confirmation = guided.get('roadmap_confirmation', {})
            if not confirmation:
                raise BootstrapBlockedError('guided_roadmap_confirmation_required')
            roadmap = self._roadmap(project_id, bootstrap_id, tuple(confirmation['milestone_ids']))
            if not roadmap['confirmed']:
                raise BootstrapBlockedError('guided_roadmap_confirmation_stale')
            progress = self._traceability.progress(project_id, milestone_ids=tuple(confirmation['milestone_ids']))
            if not progress['scope_complete']:
                raise BootstrapBlockedError('guided_milestone_scope_incompletely_planned')
            packets = []
            for milestone_id in confirmation['milestone_ids']:
                selected = [(c, p) for c in self._ledger.list_changes(project_id)
                            for p in c.get('packets', []) if c.get('milestone_id') == milestone_id
                            and p.get('status') not in {'cancelled', 'superseded'}]
                if not selected:
                    raise BootstrapBlockedError('guided_milestone_external_plan_missing:' + milestone_id)
                for change, packet in selected:
                    validation = self._external.validation(project_id, change['change_id'], packet['packet_id'])
                    plan = self._ledger.packet_work_plan_state(project_id, change['change_id'], packet['packet_id'])
                    if self._external.mode_for_packet(project_id, packet['packet_id']) != 'external_agent' or not plan or plan['status'] != 'accepted' or not validation.get('plan_executable'):
                        raise BootstrapBlockedError('guided_milestone_external_plan_not_executable:' + packet['packet_id'])
                    packets.append({'change_id':change['change_id'], 'packet_id':packet['packet_id'], 'milestone_id':milestone_id})
            handoff = {'roadmap_fingerprint':roadmap['roadmap_fingerprint'], 'milestone_ids':confirmation['milestone_ids'],
                       'packets':packets, 'implementation_claim':'not_inferred', 'human_acceptance':False,
                       'actions':[{'tool':'fow_external_work', 'operation':'todo', 'project_id':project_id, **p} for p in packets]}
            return self._ledger.record_guided_bootstrap(project_id, bootstrap_id,
                operation='complete', mutation=mutation, guided=guided, actor=actor, request_id=request_id,
                stage='ready_for_completion', handoff=handoff, completion_reference=completion_reference)

    def record_continuation(self, project_id, bootstrap_id, *, continuation_choice,
                            continuation_reference, roadmap_fingerprint, progress_revision,
                            reason, actor, request_id):
        if not isinstance(continuation_choice, str) or continuation_choice not in {'continue', 'review'}:
            raise ValueError('continuation_choice must be continue or review')
        mutation = {'continuation_choice':continuation_choice,
                    'continuation_reference':_text(continuation_reference, 'continuation_reference'),
                    'roadmap_fingerprint':_text(roadmap_fingerprint, 'roadmap_fingerprint', 128),
                    'progress_revision':_text(progress_revision, 'progress_revision', 128),
                    'reason':_text(reason, 'reason', 2000)}
        with self._ledger.atomic():
            replay = self._replay(project_id, bootstrap_id, 'record_continuation', mutation, actor, request_id)
            if replay is not None:
                return replay
            state = self._state(project_id, bootstrap_id)
            guided = self._guided(state)
            confirmation = guided.get('roadmap_confirmation', {})
            if not confirmation:
                raise BootstrapBlockedError('guided_roadmap_confirmation_required')
            roadmap = self._roadmap(project_id, bootstrap_id, tuple(confirmation['milestone_ids']))
            if not roadmap['confirmed'] or roadmap['roadmap_fingerprint'] != mutation['roadmap_fingerprint']:
                raise BootstrapBlockedError('guided_roadmap_confirmation_stale')
            progress = self._traceability.progress(project_id, milestone_ids=tuple(confirmation['milestone_ids']))
            if progress['progress_revision'] != mutation['progress_revision']:
                raise BootstrapBlockedError('guided_progress_revision_stale')
            guided['continuation'] = {**mutation, 'human_acceptance':False}
            return self._ledger.record_guided_bootstrap(project_id, bootstrap_id,
                operation='record_continuation', mutation=mutation, guided=guided,
                actor=actor, request_id=request_id, stage=state['stage'])

    def guidance(self, project_id, bootstrap_id):
        with self._ledger.consistent_read():
            state = self._state(project_id, bootstrap_id)
            guided = self._guided(state)
            entities, _ = self._entities(project_id)
            gaps = self._correspondence_gaps(guided, entities)
            roadmap = None
            confirmation = guided.get('roadmap_confirmation', {})
            if confirmation:
                roadmap = self._roadmap(project_id, bootstrap_id, tuple(confirmation['milestone_ids']))
                gaps = list(roadmap['gaps'])
                if not roadmap['confirmed']:
                    gaps.append({'reason':'guided_roadmap_confirmation_stale'})
            if state['open_contradiction_count'] and not any(g['reason'] == 'bootstrap_contradiction_unresolved' for g in gaps):
                gaps.append({'reason':'bootstrap_contradiction_unresolved'})
            common = {'project_id':project_id, 'bootstrap_id':bootstrap_id}
            if state['status'] == 'cancelled':
                next_gate = {'tool':'fow_bootstrap', 'operation':'start', 'project_id':project_id, 'path':'guided_engineering'}
            elif state['status'] == 'completed' and gaps:
                next_gate = {'tool':'fow_bootstrap', 'operation':'start', 'project_id':project_id,
                             'path':'guided_engineering', 'requires':'new cycle for canonical correction/current scope confirmation'}
            elif state['open_contradiction_count']:
                contradiction = next(c for c in state['contradictions'] if c.get('status') == 'open')
                next_gate = {'tool':'fow_bootstrap', 'operation':'record_contradiction', **common,
                             'contradiction':{'contradiction_id':contradiction['contradiction_id'], 'status':'resolved'},
                             'required_inputs':['actor', 'request_id', 'contradiction.resolution'],
                             'requires':'canonical intent reread and host investigation; actual stakeholder clarification only when intended behavior remains unresolved'}
            elif not guided.get('answers'):
                next_gate = {'tool':'fow_bootstrap', 'operation':'record_answer', **common}
            elif not entities['goal_node_ids']:
                next_gate = {'tool':'fow_goal', 'operation':'add_use_case', 'project_id':project_id,
                             'requires':'host formulation of the selected stakeholder scenario'}
            elif not entities['requirement_ids']:
                next_gate = {'tool':'fow_register_requirement', 'project_id':project_id,
                             'requires':'host investigation and formulation of the next canonical requirement'}
            elif gaps and gaps[0]['reason'] in {'answer_correspondence_missing', 'answer_correspondence_stale'}:
                key = gaps[0]['answer_key']
                next_gate = {'tool':'fow_bootstrap', 'operation':'record_correspondence', **common,
                             'correspondence':{'answer_key':key, 'answer_revision':guided['answers'][key]['revision']},
                             'required_inputs':['actor', 'request_id', 'correspondence.canonical_references', 'correspondence.disposition', 'correspondence.rationale']}
            elif gaps and gaps[0]['reason'] in {'requires_intent_change', 'needs_clarification', 'packet_intent_questions_open', 'packet_semantic_decisions_open'}:
                next_gate = {'continuation_policy':'return_to_model', 'action':'reread_intent_and_resolve_affected_gap',
                             'requires':'engineer investigation and ordinary corrective work for implementation mismatch; human clarification or ordinary intent revision only for unresolved intended behavior',
                             'reason':gaps[0], **common}
            elif not entities['milestone_ids']:
                next_gate = {'tool':'fow_capabilities', 'view':'recipe', 'recipe_name':'milestone-planning'}
            elif not confirmation or (roadmap and not roadmap['confirmed']):
                next_gate = {'tool':'fow_bootstrap', 'operation':'roadmap', **common,
                             'requires':'explicit canonical milestone_ids and current correspondence'}
            elif state['status'] != 'completed':
                progress = self._traceability.progress(project_id, milestone_ids=tuple(confirmation['milestone_ids']))
                if not progress['scope_complete']:
                    gaps.extend(progress['gaps'])
                    next_gate = {'tool':'fow_capabilities', 'view':'recipe', 'recipe_name':'standalone-external-plan',
                                 'reason':'prepare accepted executable external plans for every confirmed requirement/milestone'}
                else:
                    next_gate = {'tool':'fow_bootstrap', 'operation':'complete', **common,
                                 'requires':'completion_reference for initial preparation handoff'}
            else:
                next_gate = {'tool':'fow_handover', 'operation':'project_progress', 'project_id':project_id,
                             'milestone_ids':confirmation['milestone_ids']}
            return {'contract_version':'flow.guided_bootstrap.v1', 'bootstrap_id':bootstrap_id,
                    'status':state['status'], 'markdown':ROLE_GUIDANCE, 'selected_facts':guided.get('answers', {}),
                    'correspondence':guided.get('correspondence', {}), 'canonical_context':{'counts':{k:len(v) for k,v in entities.items()},
                        'current_references':{k:[v[ref] for ref in sorted({ref for m in guided.get('correspondence', {}).values() for ref in m['canonical_references'][k]}) if ref in v] for k,v in entities.items()},
                        'detail_reference':{'tool':'fow_bootstrap', 'operation':'state', 'project_id':project_id, 'bootstrap_id':bootstrap_id}},
                    'roadmap':roadmap, 'blockers':gaps, 'next_gate':next_gate,
                    'draft_context':roadmap['draft_context'] if roadmap else self._draft_context(guided, ()),
                    'semantic_truth_verified':False, 'human_acceptance':False}
