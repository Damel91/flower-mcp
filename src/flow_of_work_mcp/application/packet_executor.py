"""New-work ownership and explicit, durable provider-contract negotiation."""
from __future__ import annotations

import re
from typing import Callable, Mapping

from flow_of_work_mcp.core.domain.change_control import PACKET_INACTIVE_STATUS_VALUES
from flow_of_work_mcp.core.domain.external_work import fields, fingerprint, number, text
from flow_of_work_mcp.core.domain.provider_binding import ImplementationProviderKind
from flow_of_work_mcp.core.domain.provider_validation import (
    COMMAND_VERSION, build_context, context_for_unit, validate_ack, validate_capability,
)
from flow_of_work_mcp.core.errors import (
    ChangeControlBlockedError, ImplementationProviderError, ImplementationProviderUnavailableError,
)


class PacketExecutorService:
    def __init__(self, ledger, *, provider=None,
                 semantic_projection: Callable[[str, str, str], Mapping[str, object]]) -> None:
        self._ledger = ledger
        self._provider = provider
        self._semantic_projection = semantic_projection

    def _packet(self, project_id, change_id, packet_id):
        packet = next((p for p in self._ledger.change_state(project_id, change_id)['packets'] if p['packet_id'] == packet_id), None)
        if packet is None:
            raise ChangeControlBlockedError('packet_not_found')
        return packet

    @staticmethod
    def _selection_fingerprint(selection):
        return fingerprint({k: selection[k] for k in ('project_id', 'change_id', 'packet_id', 'selection_revision', 'executor', 'provider_kind')})

    def _binding_identity(self, project_id):
        binding = self._ledger.resolve_provider_binding(project_id, ImplementationProviderKind.PACKET_EXECUTION)
        if binding is None:
            raise ChangeControlBlockedError('provider_validation_durable_binding_required')
        return {'provider_kind': 'packet_execution', 'provider_id': binding.provider_id,
                'provider_context_id': binding.provider_context_id, 'binding_revision': binding.revision}

    def _generation(self, project_id, change_id, packet_id, provider_kind):
        binding = self._ledger.packet_provider_binding(project_id, change_id, packet_id, provider_kind=provider_kind)
        return int((binding or {}).get('flow_binding_generation') or 0)

    def _expect(self, project_id, change_id, packet_id, payload):
        packet = self._packet(project_id, change_id, packet_id)
        plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id)
        if number(payload.get('expected_spec_revision'), 'expected_spec_revision') != packet['spec_revision']:
            raise ChangeControlBlockedError('stale_packet_revision')
        expected = payload.get('expected_plan_revision')
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ValueError('expected_plan_revision must be a nonnegative integer')
        if expected != int((plan or {}).get('plan_revision') or 0):
            raise ChangeControlBlockedError('stale_work_plan_revision')
        return packet, plan

    def call(self, project_id, change_id, packet_id, operation, *, payload=None, actor='', request_id=''):
        payload = dict(payload or {})
        actor, request_id = text(actor, 'actor'), text(request_id, 'request_id')
        if operation not in {'select_executor', 'negotiate_provider'}:
            raise ValueError('unsupported packet executor operation')
        request_fingerprint = fingerprint({'change_id': change_id, 'packet_id': packet_id,
            'operation': operation, 'payload': payload, 'actor': actor})
        with self._ledger.atomic():
            replay = self._ledger.executor_request_replay(project_id, request_id, request_fingerprint)
            if replay is not None:
                return replay
            if operation == 'select_executor':
                fields(payload, {'executor', 'provider_kind', 'expected_spec_revision', 'expected_plan_revision'}, operation)
                result = self._select(project_id, change_id, packet_id, payload, actor)
                self._ledger.record_executor_request(project_id, request_id, request_fingerprint, result, actor=actor, operation=operation)
                return result
            fields(payload, {'expected_spec_revision', 'expected_plan_revision'}, operation)
            packet, plan = self._expect(project_id, change_id, packet_id, payload)
            selection = self._ledger.packet_executor_state(project_id, change_id, packet_id)['selection']
            if not selection or selection['executor'] != 'provider':
                raise ChangeControlBlockedError('provider_executor_not_selected')
            if packet['status'] in PACKET_INACTIVE_STATUS_VALUES:
                raise ChangeControlBlockedError('provider_packet_inactive')
            projection = self._semantic_projection(project_id, change_id, packet_id)
            if projection['status'] != 'closed':
                raise ChangeControlBlockedError((projection.get('next_gap') or {}).get('code', 'provider_validation_open'))
            if projection.get('execution_admission'):
                raise ChangeControlBlockedError(projection['execution_admission']['reason'], details=projection['execution_admission'].get('details', {}))
            # Bound the whole export before probing or authorizing transport.
            try:
                build_context(projection)
            except ValueError as exc:
                raise ChangeControlBlockedError('provider_validation_context_invalid', details={'validation_error': str(exc)}) from exc
            try:
                binding_identity = self._binding_identity(project_id)
                binding_reason = ''
            except ChangeControlBlockedError as exc:
                binding_identity, binding_reason = {}, exc.reason
            generation = self._generation(project_id, change_id, packet_id, selection['provider_kind'])
            self._assert_original_route(project_id, change_id, packet_id, binding_identity)
            self._assert_original_generation(project_id, change_id, packet_id, generation)
            basis = {'provider_kind': selection['provider_kind'], 'binding_identity': binding_identity,
                'flow_binding_generation': generation, 'selection_revision': selection['selection_revision'],
                'selection_fingerprint': self._selection_fingerprint(selection),
                'spec_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
                'authority_fingerprint': projection['authority_fingerprint']}
        # Network discovery is explicit and outside the ledger transaction.
        capability, supported, reason = {}, False, binding_reason
        if not reason:
            try:
                if self._provider is None or self._provider.kind != selection['provider_kind']:
                    raise ImplementationProviderUnavailableError('packet_provider_required_but_unavailable')
                discover = getattr(self._provider, 'validation_capabilities', None)
                identity = getattr(self._provider, 'binding_identity', None)
                if not callable(discover) or not callable(identity):
                    reason = 'provider_validation_projection_unsupported'
                elif dict(identity(project_id)) != binding_identity:
                    reason = 'provider_validation_binding_changed'
                else:
                    capability = dict(discover(project_id))
                    validate_capability(capability)
                    supported, reason = True, ''
            except (TypeError, ValueError):
                # Retain a bounded negative observation, never arbitrary malformed
                # provider data as an authoritative capability or executable input.
                capability = {}
                reason = 'provider_validation_projection_unsupported'
            except ImplementationProviderError as exc:
                # Provider errors are observations, not trusted storage input.
                # Retain ordinary bounded reason codes without persisting remote
                # prose or an arbitrarily large rejection payload.
                observed_reason = getattr(exc, 'terminal_reason', '')
                reason = (observed_reason if isinstance(observed_reason, str)
                          and re.fullmatch(r'[a-z][a-z0-9_]{0,127}', observed_reason)
                          else 'provider_validation_unavailable')
        with self._ledger.atomic():
            replay = self._ledger.executor_request_replay(project_id, request_id, request_fingerprint)
            if replay is not None:
                return replay
            self._expect(project_id, change_id, packet_id, payload)
            current = self._semantic_projection(project_id, change_id, packet_id)
            try:
                current_identity = self._binding_identity(project_id)
            except ChangeControlBlockedError:
                current_identity = {}
            current_generation = self._generation(project_id, change_id, packet_id, selection['provider_kind'])
            if (current['authority_fingerprint'] != basis['authority_fingerprint'] or current_identity != binding_identity
                    or current_generation != generation):
                raise ChangeControlBlockedError('provider_negotiation_authority_changed')
            observed = self._ledger.record_provider_capability(project_id, change_id, packet_id,
                {**basis, 'capability': capability, 'supported': supported, 'reason': reason}, actor=actor)
            result = {'status': 'success' if supported else 'blocked', 'reason': reason,
                'capability': observed, 'acceptance': 'not_inferred', 'paired_qualification': 'pending'}
            self._ledger.record_executor_request(project_id, request_id, request_fingerprint, result, actor=actor, operation=operation)
            return result

    def _select(self, project_id, change_id, packet_id, payload, actor):
        packet, plan = self._expect(project_id, change_id, packet_id, payload)
        executor = payload.get('executor')
        if executor not in {'external_agent', 'provider'}:
            raise ValueError('executor must explicitly be external_agent or provider')
        provider_kind = str(payload.get('provider_kind') or '')
        if executor == 'external_agent' and provider_kind:
            raise ValueError('external_agent selection must not specify provider_kind')
        if executor == 'provider':
            provider_kind = text(payload.get('provider_kind'), 'provider_kind')
            if self._provider is not None and provider_kind != self._provider.kind:
                raise ChangeControlBlockedError('provider_executor_kind_mismatch')
            if provider_kind != 'codingcastle':
                raise ChangeControlBlockedError('provider_executor_kind_unsupported')
        state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
        existing = state['selection']
        if existing:
            if existing['executor'] != executor or existing['provider_kind'] != provider_kind:
                raise ChangeControlBlockedError('executor_transfer_not_supported')
            return {'status': 'success', 'consumption_mode': executor, 'selection': existing, 'replayed_selection': True}
        external = self._ledger.external_work_state(project_id, change_id, packet_id)
        if external['consumption_mode'] == 'external_agent' and executor != 'external_agent':
            raise ChangeControlBlockedError('executor_transfer_not_supported')
        runs = self._ledger.runs_for_change(project_id, change_id)
        started = any(r['packet_id'] == packet_id and (r['status'] != 'planned' or any(s['status'] != 'pending' for s in r.get('steps', []))) for r in runs)
        if (packet['status'] in PACKET_INACTIVE_STATUS_VALUES or external['reports'] or started
                or self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id)
                or self._ledger.packet_provider_receipts(project_id, change_id, packet_id)):
            raise ChangeControlBlockedError('executor_transfer_not_supported')
        projection = self._semantic_projection(project_id, change_id, packet_id)
        selection = self._ledger.record_executor_selection(project_id, change_id, packet_id,
            {'executor': executor, 'provider_kind': provider_kind, 'spec_revision': packet['spec_revision'],
             'plan_revision': int((plan or {}).get('plan_revision') or 0),
             'authority_fingerprint': projection['authority_fingerprint']}, actor=actor)
        return {'status': 'success', 'consumption_mode': executor, 'selection': selection, 'replayed_selection': False}

    def inspect(self, project_id, change_id, packet_id):
        with self._ledger.consistent_read():
            self._packet(project_id, change_id, packet_id)
            state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
            return {**state, 'consumption_mode': self._ledger.external_work_state(project_id, change_id, packet_id)['consumption_mode'],
                    'admitted_route': next(iter(self._ledger.packet_provider_admissions(project_id, change_id, packet_id, limit=1)), None),
                    'executor_transfer': 'not_supported', 'paired_qualification': 'pending'}

    def requires_validation(self, project_id, change_id, packet_id):
        """Pure selection/declaration inspection, including architecture-only work."""
        with self._ledger.consistent_read():
            packet = self._packet(project_id, change_id, packet_id)
            selection = self._ledger.packet_executor_state(project_id, change_id, packet_id)['selection']
            plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id) or {}
            return bool(selection and selection['executor'] == 'provider' or
                        packet.get('architecture_refs') or
                        any(u.get(f) for u in plan.get('units', [])
                            for f in ('implements', 'provides', 'requires', 'verifies')))

    def validation_projection(self, project_id, change_id, packet_id):
        """Return current semantic authority without discovery or admission effects."""
        with self._ledger.consistent_read():
            return self._semantic_projection(project_id, change_id, packet_id)

    def content_identity(self, project_id, change_id, packet_id, unit_key):
        if not self.requires_validation(project_id, change_id, packet_id):
            return ''
        projection = self.validation_projection(project_id, change_id, packet_id)
        if projection['status'] != 'closed':
            return projection['authority_fingerprint']
        try:
            return build_context(projection, unit_key=unit_key)['context_sha256']
        except ValueError:
            return projection['authority_fingerprint']

    def _assert_original_generation(self, project_id, change_id, packet_id, generation):
        admissions = self._ledger.packet_provider_admissions(project_id, change_id, packet_id, limit=1)
        if admissions:
            original = self._ledger.packet_provider_capability(project_id, admissions[0]['capability_identity'])
            original_generation = original['flow_binding_generation']
            if generation != original_generation and not (original_generation == 0 and generation == 1):
                raise ChangeControlBlockedError('provider_execution_generation_changed')
            return
        generations = {int(e.get('flow_binding_generation') or 0) for e in self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id)
                       if (e.get('command') or {}).get('contract_version') == COMMAND_VERSION}
        if generations and generation not in generations and not (generations == {0} and generation == 1):
            raise ChangeControlBlockedError('provider_execution_generation_changed')

    def _assert_original_route(self, project_id, change_id, packet_id, identity):
        admissions = self._ledger.packet_provider_admissions(project_id, change_id, packet_id, limit=1)
        if admissions and admissions[0]['binding_identity'] != identity:
            raise ChangeControlBlockedError('provider_execution_route_changed')
        if not admissions and any((e.get('command') or {}).get('contract_version') == COMMAND_VERSION
                                  for e in self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id)):
            raise ChangeControlBlockedError('provider_admission_receipt_missing')

    def _admitted_capability(self, project_id, change_id, packet_id, entry):
        admission = self._ledger.packet_provider_admission(project_id, entry['outbox_id'])
        if admission is None:
            raise ChangeControlBlockedError('provider_admission_receipt_missing')
        identity = self._binding_identity(project_id)
        self._assert_original_route(project_id, change_id, packet_id, identity)
        if admission['binding_identity'] != identity:
            raise ChangeControlBlockedError('provider_execution_route_changed')
        capability = self._ledger.packet_provider_capability(project_id, admission['capability_identity'])
        selection = self._ledger.packet_executor_state(project_id, change_id, packet_id)['selection']
        context = entry['command']['validation_context']
        if (not selection or selection['executor'] != 'provider' or not capability['supported']
                or capability['selection_fingerprint'] != self._selection_fingerprint(selection)
                or capability['binding_identity'] != identity or admission['context_sha256'] != context['context_sha256']
                or any(capability[k] != context[k] for k in ('spec_revision', 'plan_revision', 'authority_fingerprint'))):
            raise ChangeControlBlockedError('provider_admission_receipt_mismatch')
        self._assert_original_generation(project_id, change_id, packet_id,
            self._generation(project_id, change_id, packet_id, selection['provider_kind']))
        validate_capability(capability['capability'])
        return capability

    def _capability(self, project_id, change_id, packet_id, projection):
        state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
        selection = state['selection']
        if not selection or selection['executor'] != 'provider':
            raise ChangeControlBlockedError('provider_executor_not_selected')
        identity = self._binding_identity(project_id)
        self._assert_original_route(project_id, change_id, packet_id, identity)
        generation = self._generation(project_id, change_id, packet_id, selection['provider_kind'])
        self._assert_original_generation(project_id, change_id, packet_id, generation)
        capability = next((c for c in reversed(state['capabilities']) if
            c['binding_identity'] == identity and c['selection_fingerprint'] == self._selection_fingerprint(selection)
            and c['spec_revision'] == projection['spec_revision'] and c['plan_revision'] == projection['plan_revision']
            and c['authority_fingerprint'] == projection['authority_fingerprint']
            and (c['flow_binding_generation'] == generation or c['flow_binding_generation'] == 0 and generation == 1)), None)
        if capability is None:
            raise ChangeControlBlockedError('provider_validation_negotiation_required')
        if not capability['supported']:
            raise ChangeControlBlockedError(capability['reason'] or 'provider_validation_projection_unsupported')
        validate_capability(capability['capability'])
        return capability

    def admission(self, project_id, change_id, packet_id):
        with self._ledger.consistent_read():
            projection = None
            try:
                self._packet(project_id, change_id, packet_id)
                state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
                if not state['selection'] or state['selection']['executor'] != 'provider':
                    raise ChangeControlBlockedError('provider_executor_not_selected')
                projection = self._semantic_projection(project_id, change_id, packet_id)
                if projection['status'] != 'closed':
                    raise ChangeControlBlockedError((projection.get('next_gap') or {}).get('code', 'provider_validation_open'))
                if projection.get('execution_admission'):
                    raise ChangeControlBlockedError(projection['execution_admission']['reason'], details=projection['execution_admission'].get('details', {}))
                if self._packet(project_id, change_id, packet_id)['status'] in PACKET_INACTIVE_STATUS_VALUES:
                    raise ChangeControlBlockedError('provider_packet_inactive')
                build_context(projection)
                capability = self._capability(project_id, change_id, packet_id, projection)
                return {'allowed': True, 'reason': '', 'next_operation': '', 'capability': capability}
            except ChangeControlBlockedError as exc:
                upstream = (projection or {}).get('upstream_gate')
                operation = ('executor_select' if exc.reason == 'provider_executor_not_selected' else
                             'provider_negotiate' if exc.reason.startswith('provider_validation_') else 'provider_validation')
                return {'allowed': False, 'reason': exc.reason,
                        'next_operation': upstream['next_operation'] if upstream else operation,
                        'details': dict(exc.details), **({'upstream_gate': upstream} if upstream else {})}
            except ValueError as exc:
                return {'allowed': False, 'reason': 'provider_validation_context_invalid',
                        'next_operation': 'provider_validation', 'details': {'validation_error': str(exc)}}

    @staticmethod
    def upstream_action(admission, **identity):
        """Use the ordinary route contract for an upstream canonical gate."""
        if not admission.get('upstream_gate'):
            return None
        from flow_of_work_mcp.application.packet_guards import PacketGuardDecision
        from flow_of_work_mcp.application.packet_next_action import PacketNextActionProjectionService
        return PacketNextActionProjectionService().project(
            PacketGuardDecision.from_payload(admission['upstream_gate']), **identity)

    def validation_context(self, project_id, change_id, packet_id, *, unit_key=''):
        with self._ledger.consistent_read():
            admitted = self.admission(project_id, change_id, packet_id)
            if not admitted['allowed']:
                raise ChangeControlBlockedError(admitted['reason'], details=admitted.get('details', {}))
            return build_context(self._semantic_projection(project_id, change_id, packet_id), unit_key=unit_key)

    def frozen_context(self, project_id, change_id, packet_id, *, unit_key=''):
        with self._ledger.consistent_read():
            entries = self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id)
            entry = next((e for e in reversed(entries) if (e.get('command') or {}).get('contract_version') == COMMAND_VERSION
                          and e['state'] in {'delivered', 'delivering', 'unknown'}), None)
            if entry is None:
                raise ChangeControlBlockedError('provider_admitted_context_missing')
            context = context_for_unit(entry['command']['validation_context'], unit_key)
            self._admitted_capability(project_id, change_id, packet_id, entry)
            return context

    def admit_command(self, project_id, change_id, packet_id, command, *, recovering=False):
        with self._ledger.consistent_read():
            self._packet(project_id, change_id, packet_id)
            state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
            external = self._ledger.external_work_state(project_id, change_id, packet_id)
            if external['consumption_mode'] == 'external_agent':
                raise ChangeControlBlockedError('external_agent_mode_provider_execution_prohibited')
            plan = self._ledger.packet_work_plan_state(project_id, change_id, packet_id) or {}
            enriched = bool(self._packet(project_id, change_id, packet_id).get('architecture_refs')) or any(
                u.get(f) for u in plan.get('units', []) for f in ('implements', 'provides', 'requires', 'verifies'))
            selected = state['selection'] and state['selection']['executor'] == 'provider'
            if not selected and not enriched and command.contract_version != COMMAND_VERSION:
                return
            if not selected:
                raise ChangeControlBlockedError('provider_executor_not_selected')
            if command.contract_version != COMMAND_VERSION:
                raise ChangeControlBlockedError('provider_validation_context_required')
            operation = str(command.operation)
            if operation not in {'stop', 'status'} and not recovering:
                binding = self._ledger.packet_provider_binding(project_id, change_id, packet_id, provider_kind=state['selection']['provider_kind'])
                if ((binding or {}).get('provider_state') in {'completed', 'partial'}
                        or (binding or {}).get('run_phase') in {'completed', 'completion', 'partial'}):
                    raise ChangeControlBlockedError('provider_completed_work_replay_prohibited')
                correlated_unit = next((u for u in (binding or {}).get('unit_correlations', [])
                                        if u['flow_unit_ref'] == command.flow_unit_ref), None)
                if (correlated_unit or {}).get('unit_state') in {'completed', 'complete', 'implemented', 'verified'}:
                    raise ChangeControlBlockedError('provider_completed_unit_replay_prohibited')
                pending = self._ledger.packet_provider_recoverable_commands(project_id, change_id=change_id, packet_id=packet_id)
                if any(e['delivery_fingerprint'] != command.delivery_fingerprint for e in pending):
                    raise ChangeControlBlockedError('provider_existing_delivery_unresolved')
            frozen_capability = None
            if recovering:
                admission = self._ledger.packet_provider_command_admission(project_id, change_id, packet_id, command.delivery_fingerprint)
                if admission is None:
                    raise ChangeControlBlockedError('provider_admission_receipt_missing')
                stored = self._ledger.packet_provider_outbox_entry(project_id, admission['outbox_id'])
                if stored['command'] != command.as_payload() or stored['state'] not in {'unknown', 'delivering'}:
                    raise ChangeControlBlockedError('provider_recovery_command_mismatch')
                expected = stored['command']['validation_context']
                frozen_capability = self._admitted_capability(project_id, change_id, packet_id, stored)
            elif operation in {'stop', 'status'}:
                expected = self.frozen_context(project_id, change_id, packet_id, unit_key=command.flow_unit_ref)
                entries = self._ledger.packet_provider_outbox_entries(project_id, change_id, packet_id)
                entry = next(e for e in reversed(entries) if (e.get('command') or {}).get('contract_version') == COMMAND_VERSION
                             and e['state'] in {'delivered', 'delivering', 'unknown'})
                frozen_capability = self._admitted_capability(project_id, change_id, packet_id, entry)
            else:
                expected = self.validation_context(project_id, change_id, packet_id, unit_key=command.flow_unit_ref)
            if dict(command.validation_context) != expected:
                raise ChangeControlBlockedError('provider_validation_context_stale')
            if not recovering and operation not in {'stop', 'status'}:
                self._validate_coding_input(project_id, change_id, packet_id, command, plan, state['selection'])
            if operation == 'start' and not recovering:
                self._assert_unit_acknowledgements(project_id, change_id, packet_id, expected, for_start=True)
            return frozen_capability or self._capability(project_id, change_id, packet_id, expected)

    def record_admission(self, project_id, change_id, packet_id, *, entry, capability, command, actor):
        return self._ledger.record_packet_provider_admission(project_id, change_id, packet_id,
            outbox_id=entry['outbox_id'], capability=capability, command=command, actor=actor)

    def _validate_coding_input(self, project_id, change_id, packet_id, command, plan, selection):
        """A closed semantic envelope cannot authorize unrelated technical input."""
        operation, key = str(command.operation), command.flow_unit_ref
        semantic = dict(command.semantic_input)
        if operation == 'start':
            return
        if operation == 'add' and not key and not semantic:
            return  # Canonical provider draft/target observation, no coding unit.
        unit = next((u for u in plan.get('units', []) if u['client_unit_key'] == key), None)
        if operation == 'remove':
            binding = self._ledger.packet_provider_binding(project_id, change_id, packet_id, provider_kind=selection['provider_kind'])
            correlation = next((u for u in (binding or {}).get('unit_correlations', []) if u['flow_unit_ref'] == key
                                and u['unit_state'] not in {'removed', 'deleted', 'abandoned'}), None)
            if semantic or not key or correlation is None or unit is not None:
                raise ChangeControlBlockedError('provider_validation_remove_correlation_required')
            return
        if unit is None or operation not in {'add', 'edit'}:
            raise ChangeControlBlockedError('provider_validation_canonical_unit_required')
        # Reuse the overlay's sole canonical technical projection; PVP stays in
        # its typed envelope and is compiled only by the advertising consumer.
        from flow_of_work_mcp.application.packet_provider_overlay import _provider_unit, _target_decision
        field = 'unit' if operation == 'add' else 'changes'
        expected = _provider_unit(unit, future=unit['operation_kind'] == 'new_file')
        if set(semantic) - {field, 'target'} or semantic.get(field) != expected:
            raise ChangeControlBlockedError('provider_validation_canonical_unit_mismatch')
        if 'target' in semantic:
            if unit['operation_kind'] == 'new_file':
                raise ChangeControlBlockedError('provider_validation_canonical_unit_mismatch')
            try:
                _target_decision(semantic['target'])
            except ValueError as exc:
                raise ChangeControlBlockedError('provider_validation_target_invalid') from exc

    @staticmethod
    def validate_receipt(command, receipt):
        if command.contract_version == COMMAND_VERSION:
            from flow_of_work_mcp.core.domain.provider_validation import RECEIPT_VERSION
            if receipt.contract_version != RECEIPT_VERSION:
                raise ValueError('provider validation receipt version mismatch')
            validate_ack(receipt.validation_ack, command.validation_context)

    def _assert_unit_acknowledgements(self, project_id, change_id, packet_id, context, *, for_start=False):
        selection = self._ledger.packet_executor_state(project_id, change_id, packet_id)['selection']
        binding = self._ledger.packet_provider_binding(project_id, change_id, packet_id, provider_kind=selection['provider_kind'])
        correlations = {u['flow_unit_ref']: u for u in (binding or {}).get('unit_correlations', [])}
        for unit in context['units']:
            expected = context_for_unit(context, unit['unit_key'])
            correlation = correlations.get(unit['unit_key'])
            if not correlation or correlation['unit_state'] in {'removed', 'deleted', 'abandoned'}:
                raise ChangeControlBlockedError('provider_validation_unit_acknowledgement_required', details={'unit_key': unit['unit_key']})
            if for_start and correlation['unit_state'] in {'completed', 'complete', 'implemented', 'verified'}:
                raise ChangeControlBlockedError('provider_completed_unit_replay_prohibited')
            entry = self._ledger.packet_provider_ack_entry(project_id, change_id, packet_id,
                unit_key=unit['unit_key'], context_sha256=expected['context_sha256'])
            receipt = self._ledger.packet_provider_receipt(project_id, entry['receipt_id']) if entry and entry.get('receipt_id') else None
            try:
                validate_ack((receipt or {}).get('receipt', {}).get('validation_ack'), expected)
            except ValueError as exc:
                raise ChangeControlBlockedError('provider_validation_unit_acknowledgement_required', details={'unit_key': unit['unit_key']}) from exc

    def implementation_closure(self, project_id, change_id, packet_id):
        with self._ledger.consistent_read():
            state = self._ledger.packet_executor_state(project_id, change_id, packet_id)
            packet = self._packet(project_id, change_id, packet_id)
            if not state['selection']:
                return {'complete': packet['status'] == 'implemented', 'reason': 'legacy_canonical_packet_status',
                        'report_refs': {}, 'provenance': 'legacy_canonical_status', 'acceptance': 'not_inferred'}
            try:
                projection = self._semantic_projection(project_id, change_id, packet_id)
                if projection['status'] != 'closed':
                    raise ChangeControlBlockedError((projection.get('next_gap') or {}).get('code', 'provider_validation_open'))
                admission = projection.get('execution_admission')
                if admission and not (packet['status'] == 'implemented' and admission['reason'] == 'external_packet_inactive'):
                    raise ChangeControlBlockedError(admission['reason'])
                context = build_context(projection)
                self._capability(project_id, change_id, packet_id, context)
                self._assert_unit_acknowledgements(project_id, change_id, packet_id, context)
                binding = self._ledger.packet_provider_binding(project_id, change_id, packet_id, provider_kind=state['selection']['provider_kind'])
                complete = bool(binding and (binding['provider_state'] == 'completed' or binding.get('run_phase') in {'completed', 'completion'}))
                return {'complete': complete, 'reason': '' if complete else 'provider_implementation_pending',
                    'authority_fingerprint': context['authority_fingerprint'], 'report_refs': {packet_id: (binding or {}).get('last_receipt_id', '')},
                    'provenance': 'provider_declared_technical_completion', 'acceptance': 'not_inferred'}
            except ChangeControlBlockedError as exc:
                return {'complete': False, 'reason': exc.reason, 'report_refs': {}, 'acceptance': 'not_inferred'}
