#!/usr/bin/env python3
"""Pinned071 read-only scoped assessment; never certifies invocation-wide none."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import zipfile

_spec = importlib.util.spec_from_file_location('_flower_rejection_package_audit',
    Path(__file__).resolve().with_name('audit_packet_start_rejection.py'))
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
AuditRefused = _shared.AuditRefused
_sha, _canonical = _shared._sha, _shared._canonical

CONTRACT = 'flow.packet-revision-source-audit.v1'
SOURCE_COMMIT = 'f77be7f699eae4a89598f36c86711232d6dbf558'
WHEEL_SHA256 = '36151d37b67fc5b10d1325b7c1f42496ae1bdac90a5b54b689f27970e1348ff5'
LAYOUT_HASHES = {'schema_migrations': 'bc984f79f76fde4c00f58433a9a98d2b40d64547c5a2cef60dabb7df08c2a946', 'projects': 'f4bd9bbb71deb24b5c2e3504f87b965f0feed113714b11d3d66b96c0ab9b735e', 'implementation_packets': '8ee6d2c582f51db839bab3e00948bfea9547984750c9de58b27c888ec3f489c5', 'implementation_packet_revisions': '4df62187fbb6f62bcb84d3d93a936c91bd7f93f068e7a3e70e4ca8167e0c65a4', 'change_events': '51899662e6a3c08831c76b626c50be13f27d52dd7603dfbf3e48434dbd7b7b8b'}
_FIELDS = {'project_id', 'change_id', 'packet_id', 'operation', 'actor', 'request_id',
           'title', 'intent', 'rationale', 'completion_criteria', 'requirement_ids', 'goal_ids',
           'in_scope', 'out_of_scope', 'invariants', 'unresolved_questions', 'architecture_refs',
           'expected_spec_revision', 'expected_plan_revision'}
_LISTS = {'completion_criteria', 'requirement_ids', 'goal_ids', 'in_scope', 'out_of_scope',
          'invariants', 'unresolved_questions'}


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result): raise AuditRefused('nonfinite_json_value')
    return result


def _read(path, expected, limit):
    with path.open('rb') as f: data = f.read(limit + 1)
    if len(data) > limit: raise AuditRefused('audit_input_too_large')
    if _sha(data) != expected: raise AuditRefused('retained_input_digest_mismatch')
    return json.loads(data, object_pairs_hook=_shared._object, parse_constant=_shared._nonfinite,
                      parse_float=_finite_float)


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1


def _request(path, digest, project, change, packet, request):
    value = _read(path, digest, 1024 * 1024)
    if not isinstance(value, dict) or set(value) != {'tool', 'arguments'} or value['tool'] != 'fow_packet_author':
        raise AuditRefused('unsupported_request_shape')
    args = value['arguments']
    if not isinstance(args, dict) or set(args) - _FIELDS or args.get('operation') != 'revise_packet':
        raise AuditRefused('unsupported_operation_or_fields')
    if (not isinstance(project, str) or not _shared._PROJECT_ID.fullmatch(project)
        or not isinstance(change, str) or not re.fullmatch(r'CHANGE-[0-9]{6}', change)
        or not isinstance(packet, str) or not re.fullmatch(r'PACKET-[0-9]{6}', packet)
        or not isinstance(request, str) or not request.strip() or request != request.strip()
        or args.get('project_id') != project or args.get('packet_id') != packet
        or args.get('request_id') != request or args.get('change_id', change) != change):
        raise AuditRefused('original_request_identity_mismatch')
    if not isinstance(args.get('actor'), str) or not args['actor'].strip():
        raise AuditRefused('unsupported_actor')
    for name in ('title', 'intent', 'rationale'):
        if name in args and (not isinstance(args[name], str) or len(args[name]) > 4096):
            raise AuditRefused('unsupported_argument_shape')
    for name in _LISTS:
        item = args.get(name)
        if item is not None and (not isinstance(item, list) or len(item) > 128
                or any(not isinstance(x, str) or not x.strip() or len(x) > 4096 for x in item)):
            raise AuditRefused('unsupported_argument_shape')
    for name in ('expected_spec_revision', 'expected_plan_revision'):
        if name in args and args[name] is not None and not _integer(args[name]):
            raise AuditRefused('unsupported_argument_shape')
    refs = args.get('architecture_refs')
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 128 or not all(isinstance(x, dict) for x in refs)
        or not any(set(x) == {'id', 'kind'} and isinstance(x['id'], str) and bool(x['id'].strip())
                   and x['kind'] in ('component', 'interface', 'decision') for x in refs)):
        raise AuditRefused('unsupported_rejection_path')
    return args


def _before_rows(snapshot, columns):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('ledger'), dict):
        raise AuditRefused('unsupported_before_snapshot')
    result = {}
    for table, names in columns.items():
        rows = snapshot['ledger'].get(table)
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(names) for row in rows):
            raise AuditRefused('before_snapshot_layout_mismatch')
        result[table] = [dict(zip(names, row)) for row in rows]
    if (any(not _integer(r['version']) for r in result['schema_migrations'])
            or max((r['version'] for r in result['schema_migrations']), default=0) != 55):
        raise AuditRefused('unsupported_before_schema')
    return result


def _ledger(database, before, project, change, packet, request, actor):
    database = database.resolve(strict=True)
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON'); connection.execute('BEGIN')
        columns = {}
        for table, digest in LAYOUT_HASHES.items():
            columns[table] = [r['name'] for r in connection.execute('PRAGMA table_info(' + table + ')')]
            if _sha(_canonical(columns[table])) != digest: raise AuditRefused('unsupported_column_layout')
        if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] != 55:
            raise AuditRefused('unsupported_database_schema')
        if connection.execute('SELECT 1 FROM projects WHERE project_id=?', (project,)).fetchone() is None:
            raise AuditRefused('original_scope_not_found')
        old = _before_rows(before, columns)
        if not any(r['project_id'] == project for r in old['projects']): raise AuditRefused('original_scope_not_found')
        old_packets = [r for r in old['implementation_packets'] if (r['project_id'],r['change_id'],r['packet_id']) == (project,change,packet)]
        if len(old_packets) != 1: raise AuditRefused('original_scope_not_found')
        current = connection.execute('SELECT * FROM implementation_packets WHERE project_id=? AND change_id=? AND packet_id=?', (project,change,packet)).fetchone()
        if current is None: raise AuditRefused('original_scope_not_found')
        state = dict(current)
        if not all(_integer(state[k]) for k in ('spec_revision','state_revision','current_revision')):
            raise AuditRefused('unsupported_packet_revision_shape')
        prefix = request + ':'
        events = [dict(r) for r in connection.execute('SELECT * FROM change_events WHERE project_id=? AND (request_id=? OR substr(request_id,1,?)=?)', (project,request,len(prefix),prefix))]
        prior_events = [r for r in old['change_events'] if r['project_id'] == project
            and isinstance(r['request_id'], str) and (r['request_id'] == request or r['request_id'].startswith(prefix))]
        if any(r['event_type'] == 'packet_revised' for r in (*events, *prior_events)):
            raise AuditRefused('original_request_has_revision_history')
        if any((r['change_id'],r['packet_id'],r['actor']) != (change,packet,actor) for r in events):
            raise AuditRefused('correlated_event_identity_mismatch')
        candidates = [r for r in events if r['event_type'] == 'packet_readiness_evaluated' and r['request_id'] == request + ':repair:readiness']
        witness = None
        if candidates:
            if len(candidates) != 1: raise AuditRefused('ambiguous_maintenance_witness')
            event = candidates[0]
            if not _integer(event['event_id']) or not event['event_id']:
                raise AuditRefused('unsupported_event_identity')
            if any(r['event_id'] == event['event_id'] or
                   (r['project_id'] == project and r['request_id'] == event['request_id']) for r in old['change_events']):
                raise AuditRefused('maintenance_witness_predates_snapshot')
            revisions = [dict(r) for r in connection.execute('SELECT * FROM implementation_packet_revisions WHERE project_id=? AND change_id=? AND packet_id=? AND actor=? AND created_at=?', (project,change,packet,actor,event['occurred_at']))]
            if len(revisions) != 1: raise AuditRefused('ambiguous_revision_witness')
            revision = revisions[0]
            if (not _integer(revision['revision']) or not _integer(old_packets[0]['current_revision'])
                or revision['revision'] <= old_packets[0]['current_revision']
                or revision['revision'] > state['current_revision']
                or any((r['project_id'],r['change_id'],r['packet_id'],r['revision']) == (project,change,packet,revision['revision']) for r in old['implementation_packet_revisions'])):
                raise AuditRefused('revision_witness_predates_snapshot')
            payload = json.loads(event['payload_json'], object_pairs_hook=_shared._object, parse_constant=_shared._nonfinite)
            expected = {k: revision[k] for k in ('readiness_state','target_policy')}
            expected.update({k: json.loads(revision[k + '_json'], object_pairs_hook=_shared._object, parse_constant=_shared._nonfinite)
                             for k in ('readiness_blockers','navigation_audit_ids','target_binding_ids')})
            if payload != expected: raise AuditRefused('maintenance_payload_mismatch')
            witness = {'event_id': event['event_id'], 'request_id': event['request_id'], 'actor': actor,
                'occurred_at': event['occurred_at'], 'lifecycle_revision': revision['revision'],
                'payload_sha256': _sha(_canonical(payload)), 'revision_row_sha256': _sha(_canonical(revision))}
        return ({'project_id': project, 'change_id': change, 'packet_id': packet,
                 'database_locator_sha256': _sha(str(database).encode()), 'read_only': True,
                 'requested_revision_event_matches': 0},
                {k: state[k] for k in ('spec_revision','state_revision','current_revision')} | {'packet_row_sha256': _sha(_canonical(state))}, witness)
    finally:
        connection.rollback(); connection.close()


def assess(*, wheel: Path, package_root: Path, request_json: Path, expected_request_sha256: str,
           project_id: str, change_id: str, packet_id: str, request_id: str, database: Path,
           before_snapshot_json: Path, expected_before_snapshot_sha256: str, association_reference: str):
    try:
        if not isinstance(association_reference, str) or not association_reference.strip():
            raise AuditRefused('missing_owner_association_reference')
        args = _request(request_json,expected_request_sha256,project_id,change_id,packet_id,request_id)
        before = _read(before_snapshot_json,expected_before_snapshot_sha256,64*1024*1024)
        inventory = _shared._package_evidence(wheel,package_root,expected_digest=WHEEL_SHA256)
        ledger,state,witness = _ledger(database,before,project_id,change_id,packet_id,request_id,args['actor'].strip())
        return {'contract_version': CONTRACT, 'status': 'assessed', 'basis': 'retrospective_source_audit',
            'original_request': {'tool':'fow_packet_author','operation':'revise_packet','project_id':project_id,
                'change_id':change_id,'packet_id':packet_id,'request_id':request_id,'arguments_sha256':_sha(_canonical(args))},
            'retained_request_sha256': expected_request_sha256, 'before_snapshot_sha256': expected_before_snapshot_sha256,
            'original_effect_state': 'unknown', 'historical_result_rewritten': False, 'requested_revision_applied': False,
            'ancillary_effect_state': 'applied' if witness else 'unknown', 'ancillary_effects_complete': False,
            'maintenance_witness': witness, 'current_packet': state,
            'producer': {'distribution_version':'0.7.1','source_commit':SOURCE_COMMIT,'wheel_sha256':WHEEL_SHA256,'package_files_sha256':inventory},
            'ledger': ledger, 'provenance': {'original_execution_association':'owner_declared','association_reference':association_reference},
            'limits': ['Original execution/artifact/snapshot/ledger association is owner-declared.',
                'Requested revision not applied; ancillary effects are not completely attributed.',
                'No invocation-wide no-effect proof or automatic native recovery.',
                'Preserve historical unknown; explicit current-state owner reconciliation is separate.']}
    except AuditRefused as exc: reason = str(exc)
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,zipfile.BadZipFile): reason = 'audit_input_or_storage_unverifiable'
    return {'contract_version':CONTRACT,'status':'refused','effect_state':'unknown','reason':reason}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('wheel','package-root','request-json','database','before-snapshot-json'): p.add_argument('--'+name,required=True,type=Path)
    for name in ('expected-request-sha256','project-id','change-id','packet-id','request-id','expected-before-snapshot-sha256','association-reference'): p.add_argument('--'+name,required=True)
    result=assess(**vars(p.parse_args(argv)));print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2));return 0 if result['status']=='assessed' else 2

if __name__=='__main__': raise SystemExit(main())
