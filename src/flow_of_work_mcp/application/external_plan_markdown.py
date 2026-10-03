"""Readable standalone authority and work projections; never protocol state."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from flow_of_work_mcp.markdown_adapter import safe_heading, safe_inline


def _text(value: object) -> str:
    """Keep physical prose lines while applying the mechanical inline safety."""
    if value is None:
        return 'not recorded'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    return '\n'.join(safe_inline(line) for line in str(value).splitlines())


def _label(key: object) -> str:
    return safe_heading(str(key).replace('_', ' ')).capitalize()


def _section(lines: list[str], title: str, level: int = 2) -> None:
    lines.extend(['', '#' * min(level, 6) + ' ' + safe_heading(title), ''])


def _list(lines: list[str], values: Sequence[object], *, ordered: bool = False) -> None:
    if not values:
        lines.append('None recorded.')
    for index, value in enumerate(values, 1):
        prefix = f'{index}. ' if ordered else '- '
        physical = _text(value).splitlines() or ['']
        lines.append(prefix + physical[0])
        lines.extend('   ' + line for line in physical[1:])


def _record(lines: list[str], value: object, *, level: int = 3) -> None:
    """Render supplied semantic fields as labeled prose, never serialized objects."""
    if isinstance(value, Mapping):
        # Parent facts must precede child headings. Otherwise a later parent
        # policy/rationale would appear to belong to the preceding child.
        for key, item in value.items():
            if not isinstance(item, (Mapping, list, tuple)):
                physical = _text(item).splitlines() or ['']
                lines.append(f'- **{_label(key)}:** {physical[0]}')
                lines.extend('  ' + line for line in physical[1:])
        for key, item in value.items():
            if isinstance(item, Mapping):
                _section(lines, _label(key), level)
                _record(lines, item, level=level + 1)
            elif isinstance(item, (list, tuple)):
                _section(lines, _label(key), level)
                if not item:
                    lines.append('None recorded.')
                    continue
                if all(not isinstance(child, (Mapping, list, tuple)) for child in item):
                    _list(lines, item, ordered=str(key) in {'normal_steps', 'alternate_steps', 'failure_steps', 'instructions'})
                    continue
                for index, child in enumerate(item, 1):
                    if isinstance(child, Mapping):
                        _section(lines, f'{_label(key)} {index}', level + 1)
                        _record(lines, child, level=level + 2)
                    else:
                        _list(lines, [child])
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value, 1):
            if isinstance(child, Mapping):
                _section(lines, f'Item {index}', level)
                _record(lines, child, level=level + 1)
            else:
                _list(lines, [child])
    else:
        lines.append(_text(value))


def _table(lines: list[str], headings: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    def cell(value: object) -> str:
        return safe_inline(_text(value)).replace('|', '\\|')
    lines.append('| ' + ' | '.join(headings) + ' |')
    lines.append('| ' + ' | '.join('---' for _ in headings) + ' |')
    lines.extend('| ' + ' | '.join(cell(value) for value in row) + ' |' for row in rows)


def _embed_reference(lines: list[str], reference: str) -> None:
    """Nest a complete reference without emitting invalid deep Markdown headings."""
    for line in reference.splitlines():
        heading = len(line) - len(line.lstrip('#'))
        if heading and line[heading:heading + 1] == ' ':
            line = '#' * min(heading + 2, 6) + line[heading:]
        lines.append(line)


def render_unit(lines: list[str], unit: Mapping[str, Any], *, level: int = 3) -> None:
    key = unit.get('client_unit_key') or unit.get('unit_key') or 'identity not recorded'
    _section(lines, f"Unit {unit.get('unit_number', '?')}: {key}", level)
    for label, value in (
        ('Operation', unit.get('operation_kind')),
        ('Target', unit.get('file_path') or unit.get('target_description') or 'Essential portable target context unavailable.'),
        ('Repository/member scope', unit.get('member_label') or 'Repository access supplied by the host'),
        ('Depends on', ', '.join(map(str, unit.get('depends_on', []))) or 'none'),
        ('Implements criteria', ', '.join(map(str, unit.get('implements', []))) or 'none declared'),
    ):
        lines.append(f'- **{label}:** {_text(value)}')
    _section(lines, 'Ordered actions', level + 1)
    _list(lines, unit.get('instructions', []), ordered=True)
    for label, values in (
        ('Constraints', unit.get('constraints', [])), ('Exclusions', unit.get('out_of_scope', [])),
        ('Unit-local checks', unit.get('unit_checks', [])),
    ):
        _section(lines, label, level + 1)
        _list(lines, values)
    _section(lines, 'Planned producer contracts', level + 1)
    if not unit.get('provides'):
        lines.append('None declared.')
    for contract in unit.get('provides', []):
        lines.append(f"- **{_text(contract['name'])} ({_text(contract['kind'])}):** planned required output; materialization is not yet proven.")
        _list(lines, contract.get('clauses', []))
        if contract.get('file_path'):
            lines.append('  - Future path: ' + _text(contract['file_path']))
        if contract.get('symbol') or contract.get('signature'):
            lines.append('  - Planned technical shape: ' + _text(contract.get('symbol', '')) + ' ' + _text(contract.get('signature', '')))
    _section(lines, 'Predecessor contracts consumed', level + 1)
    uses = unit.get('resolved_requires') or unit.get('requires', [])
    if not uses:
        lines.append('None declared.')
    for use in uses:
        lines.append(f"- **Requires {_text(use['producer_unit_key'])}.{_text(use['contract_name'])}:** {_text(use['use'])}")
        for clause in use.get('contract', {}).get('clauses', []):
            lines.append('  - Canonical producer clause: ' + _text(clause))
        lines.append('  - Temporal state: ' + _text(use.get('temporal_state', 'planned')))
        if use.get('producer_report'):
            lines.append('  - Producer report: ' + _text(use['producer_report']))
        if use.get('provenance'):
            lines.append('  - Provenance: ' + _text(use['provenance']))
    _section(lines, 'Verification obligations', level + 1)
    if not unit.get('verifies'):
        lines.append('None declared; absence is not verification success.')
    for verification in unit.get('verifies', []):
        temporal = 'unit-local' if verification['kind'] == 'unit_check' else 'deferred control-plane verification; not a current coding instruction'
        lines.append(f"- Criterion {verification['criterion']} / {_text(verification['kind'])} / {temporal}: {_text(verification['statement'])}")
        if verification.get('authority_ref'):
            lines.append('  - Authority: ' + _text(verification['authority_ref']))


def _ordered_units(units: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    pending, ordered = list(units), []
    while pending:
        ready = next((unit for unit in pending if set(unit.get('depends_on', [])).issubset({item['client_unit_key'] for item in ordered})), None)
        if ready is None:  # A draft retains every declaration and its explicit gap.
            ordered.extend(pending)
            break
        ordered.append(ready)
        pending.remove(ready)
    return ordered


def render_plan(
    snapshot: Mapping[str, Any], projection: Mapping[str, Any], *,
    project_predecessor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    _include_predecessors: bool = True,
) -> str:
    """Render the complete coherent authority supplied by ExternalWorkService."""
    packet = snapshot['packet']
    lines = ['# Flower MCP implementation plan', '', 'Immutable reference; edits to this document do not change Flower authority.', '']
    _record(lines, {
        'project': snapshot['project_id'], 'change': snapshot['change_id'],
        'packet': f"{snapshot['packet_id']} — {packet['title']}",
        'packet_specification_revision': projection['spec_revision'], 'plan_revision': projection['plan_revision'],
        'authority_fingerprint': projection['authority_fingerprint'], 'projection_contract': projection['contract_version'],
        'consumer_scope': projection['consumer_scope'], 'validation': projection['status'],
        'repository_source_revision': packet.get('source_revision') or 'not declared; inspect the supplied repository before effects',
    })
    _section(lines, 'Intent and scope')
    lines.extend([_text(packet['objective']), '', _text(packet.get('rationale', ''))])
    _section(lines, 'Governing change', 3)
    _record(lines, snapshot['change'], level=4)
    if snapshot.get('milestone'):
        _section(lines, 'Governing milestone', 3)
        lines.append('Entry, exit and risk policies are milestone context and deferred lifecycle authority. They do not add unit instructions or attest verification/acceptance.')
        _record(lines, snapshot['milestone'], level=4)
    for title, field in (
        ('In scope', 'in_scope'), ('Exclusions', 'out_of_scope'),
        ('Accepted invariants', 'invariants'), ('Unresolved authority', 'unresolved_questions'),
    ):
        _section(lines, title, 3)
        _list(lines, packet.get(field, []))
    _section(lines, 'Requirements')
    for requirement in snapshot.get('requirements', []):
        _section(lines, f"{requirement['requirement_id']}: {requirement.get('title', '')}", 3)
        lines.extend([_text(requirement.get('statement', '')), ''])
        _record(lines, {key: value for key, value in requirement.items() if key not in {'statement', 'title'}}, level=4)
    _section(lines, 'Goals and scenarios')
    for goal in snapshot.get('goals', []):
        _section(lines, f"{goal['goal_node_id']}: {goal.get('title', '')}", 3)
        _record(lines, {key: value for key, value in goal.items() if key != 'title'}, level=4)
    if snapshot.get('goal_edges'):
        _section(lines, 'Included Goal Graph relations', 3)
        _table(lines, ['Source', 'Relation', 'Target'], [
            [edge['source_goal_id'], edge['relation'], edge['target_goal_id']] for edge in snapshot['goal_edges']
        ])
    _section(lines, 'Accepted engineering decisions')
    if not snapshot.get('answers'):
        lines.append('No separate architecture decision is recorded. Accepted scope, invariants and unit declarations are the available authority.')
    for answer in snapshot.get('answers', []):
        _section(lines, answer.get('prompt') or answer['question_key'], 3)
        _record(lines, answer, level=4)
    if snapshot.get('pressure_context'):
        _section(lines, 'Recorded current risk disposition', 3)
        _record(lines, snapshot['pressure_context'], level=4)
    if snapshot.get('pressure_stale'):
        lines.append('Historical risk decisions are stale against this packet revision; they do not grant current authority.')
    for reference, authority in snapshot.get('resolved_authorities', {}).items():
        _section(lines, 'Referenced authority: ' + reference, 3)
        _record(lines, authority, level=4)
    for key, title in (('engineer_gate', 'Current engineer gate'), ('remediation_context', 'Corrective lineage and reassessment context')):
        if snapshot.get(key):
            _section(lines, title)
            if key == 'remediation_context':
                lines.append('Context-only predecessors preserve historical intent and lineage. They do not promise materialization, add execution dependencies or authorize consuming undeclared future contracts.')
            _record(lines, snapshot[key], level=3)
    contextual = snapshot.get('contextual_predecessor')
    if contextual:
        _section(lines, 'Historical context-only predecessor authority')
        lines.append('The following original plan is historical intent and corrective lineage only. It is not executable work in this handoff, and unfinished original units are not prerequisites for this corrective packet. Its declared future outputs are not materialized evidence. Follow only the current corrective packet instructions; explicit materialized dependencies remain governed separately.')
        reference = render_plan(contextual, project_predecessor(contextual), project_predecessor=project_predecessor)
        _embed_reference(lines, reference)
    _section(lines, 'Stable completion criteria')
    for criterion in projection.get('criteria', []):
        lines.append(f"- Criterion {criterion['number']}: {_text(criterion['statement'])}")
        owners = criterion.get('implementation_units', [])
        lines.append('  - Implementation ownership: ' + (', '.join(map(str, owners)) or ('verification-only' if criterion.get('verification') else 'unresolved')))
    predecessors = snapshot.get('predecessor_packets', [])
    if predecessors:
        _section(lines, 'Canonical predecessor packet boundary')
        lines.extend(['Depends on packets: ' + ', '.join(packet.get('dependency_packet_ids', [])), '',
            'Complete each predecessor plan and every unit-local check before this packet. Deferred campaigns, Oracles and human acceptance remain separate obligations. Future outputs are planned declarations until the host materializes and checks them.', '',
            'Typed requires references producer units within one accepted packet plan. Shared formal producer/consumer protocols belong in the same packet. Cross-packet instructions refer to included declarations as context; canonical packet dependencies supply ordering without a typed cross-packet contract edge.', '',
            "Flower may remain offline while you execute the included plans in this order. Retain each packet's original revisions/fingerprint and reconcile predecessor unit reports before consumer reports. Ordinary predecessor report arrival does not change this semantic authority. Changed or conflicting predecessor evidence requires reconciliation."])
        if _include_predecessors:
            ordered_predecessors: list[Mapping[str, Any]] = []
            included: set[str] = set()
            def include(predecessor: Mapping[str, Any]) -> None:
                if predecessor['packet_id'] in included:
                    return
                for earlier in predecessor.get('predecessor_packets', []):
                    include(earlier)
                included.add(predecessor['packet_id'])
                ordered_predecessors.append(predecessor)
            for predecessor in predecessors:
                include(predecessor)
            for predecessor in ordered_predecessors:
                _section(lines, 'Predecessor packet ' + predecessor['packet_id'], 3)
                reference = render_plan(predecessor, project_predecessor(predecessor), project_predecessor=project_predecessor, _include_predecessors=False)
                _embed_reference(lines, reference)
    _section(lines, 'Ordered work units')
    for unit in _ordered_units(projection.get('units', [])):
        render_unit(lines, unit)
    _section(lines, 'Unresolved projection obligations')
    if projection.get('gaps'):
        lines.append('DRAFT / NOT EXECUTABLE: close the following semantic obligations before execution.')
        _record(lines, projection['gaps'], level=3)
    else:
        lines.append('Semantic plan closure is current. Implementation, verification and human acceptance are still separate obligations.')
    _section(lines, 'Offline execution and reconciliation')
    lines.extend([
        'Execute with your own repository, coding, build and test tools. Flower can remain offline. Do not treat future paths/symbols as existing evidence. Finish a producer and its local checks before consuming its declared output.', '',
        'Retain this original authority fingerprint and revisions. On reconnection, use fow_external_work report_outcome for each unit in dependency order. A report contains report_key, expected_spec_revision, expected_plan_revision, authority_fingerprint, unit_key, outcome, summary, source_revision, artifacts, produced_contracts, verification and unresolved.', '',
        'Artifacts: reference, description, optional sha256. Produced contracts: name and included artifact_ref. Verification: exact declared criterion, kind and statement; status pass/fail/not_run; evidence_ref and provenance. A complete report requires every local check to pass, every produced contract to reference an artifact, and no unresolved unit obligations. Deferred campaign/Oracle checks remain deferred.', '',
        'Use the same report_key/request_id to recover a lost response. Conflicting reports require explicit reconcile_outcome with rationale. Old authority reports remain historical; changed plans require current reconciliation and never imply code replay. Host evidence remains host-reported. No agent report grants human acceptance.',
    ])
    return '\n'.join(lines).rstrip() + '\n'


def render_external_result(result: Mapping[str, Any], *, inspection: bool = False) -> str:
    """Select human work sections from an existing public structured result."""
    nested = result.get('packet')
    if inspection and isinstance(nested, Mapping) and (nested.get('consumption_mode') == 'external_agent' or 'external_work' in nested):
        # Canonical fow_packet_inspect wraps its aggregate in result.packet.
        # That aggregate itself contains the semantic packet and working sheet.
        lines = [render_external_result(nested, inspection=True)]
        residual = {key: value for key, value in result.items() if key != 'packet'}
        if residual:
            _section(lines, 'Receipt details')
            _record(lines, residual)
        return '\n'.join(lines).strip() + '\n'
    lines: list[str] = []
    _section(lines, 'Current authority')
    identity_fields = ('status', 'reason', 'project_id', 'change_id', 'packet_id', 'consumption_mode',
                       'authority_fingerprint', 'spec_revision', 'plan_revision', 'plan_executable', 'execution_allowed', 'acceptance')
    _record(lines, {key: result[key] for key in identity_fields if key in result})
    lines.append('Agent completion, local verification, deferred verification and human acceptance are separate. Host reports do not provide provider attestation.')
    handled = set(identity_fields)
    if inspection:
        for key, title in (('packet', 'Packet scope'), ('working_sheet', 'Packet working sheet'), ('engineering_questions', 'Engineering questions'), ('summary', 'Inspection summary')):
            value = result.get(key)
            if value:
                _section(lines, title)
                if isinstance(value, Mapping) and key == 'packet':
                    diagnostic_fields = {'readiness_state', 'readiness_blockers', 'blocking_reasons', 'target_policy'}
                    _record(lines, {k: v for k, v in value.items() if k not in diagnostic_fields})
                    diagnostics = {k: v for k, v in value.items() if k in diagnostic_fields}
                    if diagnostics:
                        _section(lines, 'Inherited provider diagnostics', 3)
                        lines.append('These recorded provider/navigation/target/evidence readiness fields belong to the inherited provider substrate. They are not external execution gates or current CodingCastle tasks. The current external frontier and engineer admission gate govern standalone readiness.')
                        _record(lines, diagnostics, level=4)
                elif isinstance(value, Mapping) and key == 'working_sheet':
                    _record(lines, {k: v for k, v in value.items() if k not in {'units', 'current_gate'}})
                    for unit in value.get('units', []):
                        render_unit(lines, unit)
                    if value.get('current_gate'):
                        _section(lines, 'Working-sheet gate')
                        _record(lines, value['current_gate'])
                else:
                    _record(lines, value)
                handled.add(key)
        if isinstance(result.get('external_work'), Mapping):
            _section(lines, 'External work frontier')
            lines.append(render_external_result(result['external_work']))
            handled.add('external_work')
    todos = result.get('todos')
    if isinstance(todos, list):
        _section(lines, 'Work queue')
        _table(lines, ['Unit', 'Key', 'Status', 'Pending dependencies', 'Report'], [
            [row.get('unit_number'), row['unit_key'], row['status'], ', '.join(row.get('dependencies_pending', [])) or 'none', row.get('report_key') or 'none'] for row in todos
        ])
        handled.add('todos')
    if 'current_unit' in result:
        _section(lines, 'Current work')
        current = result['current_unit']
        if isinstance(current, Mapping):
            _record(lines, {key: value for key, value in current.items() if key != 'unit'})
            if isinstance(current.get('unit'), Mapping):
                render_unit(lines, current['unit'])
        else:
            lines.append('No current coding unit selected. Read the next gate and remaining verification obligations; this is not human acceptance.')
        handled.add('current_unit')
    validation = result.get('validation')
    if isinstance(validation, Mapping):
        _section(lines, 'Packet validation projection')
        _record(lines, {key: value for key, value in validation.items() if key not in {'criteria', 'units'}})
        if validation.get('criteria'):
            _section(lines, 'Criterion coverage')
            for criterion in validation['criteria']:
                _section(lines, f"Criterion {criterion['number']}", 3)
                lines.extend([_text(criterion['statement']), ''])
                owners = criterion.get('implementation_units', [])
                lines.append('Implementation units: ' + (', '.join(map(str, owners)) or ('verification-only' if criterion.get('verification') else 'unresolved')))
                _section(lines, 'Declared verification', 4)
                _record(lines, criterion.get('verification', []), level=5)
        for unit in _ordered_units(validation.get('units', [])):
            render_unit(lines, unit)
        handled.add('validation')
    for unit in result.get('units', []):
        render_unit(lines, unit)
    handled.add('units')
    for key, title in (
        ('packet_dependencies', 'Canonical predecessor readiness'), ('deferred_verification', 'Deferred verification'),
        ('criterion_traceability', 'Criterion evidence'), ('historical_reports', 'Historical reports'),
        ('engineer_gate', 'Current engineer gate'), ('remediation_context', 'Corrective lineage and reassessment context'),
    ):
        if key in result:
            _section(lines, title)
            _record(lines, result[key])
            handled.add(key)
    for key in ('next_gate', 'gate', 'next_action'):
        if key in result:
            _section(lines, 'Next authorized operation' if key == 'next_gate' else _label(key))
            _record(lines, result[key])
            handled.add(key)
    residual = {key: value for key, value in result.items() if key not in handled}
    if residual:
        _section(lines, 'Receipt details')
        _record(lines, residual)
    return '\n'.join(lines).strip() + '\n'


def render_assurance_result(result: Mapping[str, Any]) -> str:
    """Make the selected finding's supplied intent and reassessment inspectable."""
    finding = result.get('assurance', result)
    if not isinstance(finding, Mapping):
        finding = {'receipt': finding}
    lines: list[str] = []
    _section(lines, 'Current finding and authority')
    special = {'intent_context', 'latest_intent_assessment', 'intent_assessment', 'assessment', 'next_gate'}
    _record(lines, {key: value for key, value in finding.items() if key not in special})
    for key, title in (
        ('intent_context', 'Canonical intent context'),
        ('latest_intent_assessment', 'Latest intent reassessment'),
        ('intent_assessment', 'Intent reassessment receipt'),
        ('assessment', 'Declared reassessment'),
        ('next_gate', 'Next authorized operation'),
    ):
        if key in finding:
            _section(lines, title)
            _record(lines, finding[key])
    lines.extend(['', 'A correction within accepted intent is engineering authority. An intent change or indispensable clarification requires the corresponding human intent decision. Reassessment does not resolve a finding or accept implementation.'])
    if finding is not result:
        _record(lines, {key: value for key, value in result.items() if key != 'assurance'})
    return '\n'.join(lines).strip() + '\n'
