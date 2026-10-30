#!/usr/bin/env python3
"""Read-only assessment of the pinned070 malformed architecture path.

Never imports Flower or dispatches a mutation. The original result stays unknown;
original execution/artifact/ledger association is explicitly owner-declared.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import zipfile

# Load only the pinned sibling, including under python -I (which deliberately
# excludes the script directory). Never search cwd/PYTHONPATH for recovery code.
_spec = importlib.util.spec_from_file_location('_flower_rejection_package_audit',
    Path(__file__).resolve().with_name('audit_packet_start_rejection.py'))
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
AuditRefused = _shared.AuditRefused
_canonical, _nonfinite, _object = _shared._canonical, _shared._nonfinite, _shared._object
_package_evidence, _PROJECT_ID, _sha = _shared._package_evidence, _shared._PROJECT_ID, _shared._sha

CONTRACT = 'flow.architecture-source-audit.v1'
SOURCE_COMMIT = 'ae96517e34f8c0b622249f22667f8f3471128dc4'
WHEEL_SHA256 = '60d48ddc702b662e53115698bbf2c603b124461980571e2f9251abeb950ee0d0'


def _request_evidence(path, expected_sha, project_id, request_id):
    data = path.read_bytes()
    if _sha(data) != expected_sha:
        raise AuditRefused('retained_request_digest_mismatch')
    request = json.loads(data, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(request, dict) or set(request) != {'tool', 'arguments'}:
        raise AuditRefused('unsupported_request_shape')
    args = request['arguments']
    if request['tool'] != 'fow_architecture' or not isinstance(args, dict):
        raise AuditRefused('unsupported_tool')
    if set(args) != {'project_id', 'operation', 'payload', 'actor', 'request_id'} or args['operation'] != 'propose':
        raise AuditRefused('unsupported_operation_or_fields')
    if (not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id)
            or not isinstance(request_id, str) or not request_id.strip() or request_id != request_id.strip()
            or args['project_id'] != project_id or args['request_id'] != request_id):
        raise AuditRefused('original_request_identity_mismatch')
    if not isinstance(args['actor'], str) or not args['actor'].strip():
        raise AuditRefused('unsupported_actor')
    payload = args['payload']
    if not isinstance(payload, dict) or set(payload) != {'definition', 'expected_revision'}:
        raise AuditRefused('unsupported_payload')
    expected = payload['expected_revision']
    if isinstance(expected, bool) or not isinstance(expected, int) or not 0 <= expected <= 2**63 - 1:
        raise AuditRefused('unsupported_expected_revision')
    definition = payload['definition']
    if (not isinstance(definition, dict) or set(definition) != {'components', 'interfaces', 'decisions'}
            or any(not isinstance(value, list) for value in definition.values())):
        raise AuditRefused('unsupported_definition')
    if not any(isinstance(item, dict) and isinstance(item.get('boundaries'), str)
               for item in definition['components']):
        raise AuditRefused('unsupported_rejection_path')
    return args, _sha(data)


def _ledger_evidence(database, project_id, request_id):
    database = database.resolve(strict=True)
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only = ON')
        connection.execute('BEGIN')
        if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] != 55:
            raise AuditRefused('unsupported_database_schema')
        if connection.execute('SELECT 1 FROM projects WHERE project_id=?', (project_id,)).fetchone() is None:
            raise AuditRefused('original_project_not_found')
        matches = {}
        prefix = request_id + ':'
        for table, key in (('architecture_requests', 'architecture_request_matches'),
                           ('requirement_events', 'requirement_event_request_matches')):
            matches[key] = connection.execute(
                f'SELECT COUNT(*) FROM {table} WHERE project_id=? AND '
                '(request_id=? OR substr(request_id,1,?)=?)',
                (project_id, request_id, len(prefix), prefix)).fetchone()[0]
        if any(matches.values()):
            raise AuditRefused('original_request_has_durable_history')
        return {'project_id': project_id, 'database_locator_sha256': _sha(str(database).encode()),
                **matches, 'read_only': True}
    finally:
        connection.rollback()
        connection.close()


def assess(*, wheel: Path, package_root: Path, request_json: Path,
           expected_request_sha256: str, project_id: str, request_id: str,
           database: Path, association_reference: str) -> dict:
    try:
        if not isinstance(association_reference, str) or not association_reference.strip():
            raise AuditRefused('missing_owner_association_reference')
        args, raw_sha = _request_evidence(request_json, expected_request_sha256, project_id, request_id)
        inventory = _package_evidence(wheel, package_root, expected_digest=WHEEL_SHA256)
        ledger = _ledger_evidence(database, project_id, request_id)
        return {'contract_version': CONTRACT, 'status': 'assessed',
                'basis': 'retrospective_source_audit',
                'original_request': {'tool': 'fow_architecture', 'operation': 'propose',
                    'project_id': project_id, 'request_id': request_id, 'arguments_sha256': _sha(_canonical(args))},
                'retained_request_sha256': raw_sha, 'original_effect_state': 'unknown',
                'historical_result_rewritten': False,
                'recovery_resolution': {'effect_state': 'none', 'mutation_started': False},
                'producer': {'distribution_version': '0.7.0', 'source_commit': SOURCE_COMMIT,
                    'wheel_sha256': WHEEL_SHA256, 'package_files_sha256': inventory},
                'ledger': ledger,
                'provenance': {'original_execution_association': 'owner_declared',
                               'association_reference': association_reference},
                'limits': ['Retrospective assessment, not an originally emitted receipt.',
                           'Original execution/artifact/ledger association is owner-declared.',
                           'Current absence corroborates the pinned source proof only.',
                           'No conclusion about other requests or uncertain transport outcomes.']}
    except AuditRefused as exc:
        reason = str(exc)
    except (OSError, ValueError, TypeError, sqlite3.Error, zipfile.BadZipFile):
        reason = 'audit_input_or_storage_unverifiable'
    return {'contract_version': CONTRACT, 'status': 'refused', 'effect_state': 'unknown', 'reason': reason}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('wheel', 'package-root', 'request-json', 'database'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('expected-request-sha256', 'project-id', 'request-id', 'association-reference'):
        parser.add_argument('--' + name, required=True)
    result = assess(**vars(parser.parse_args(argv)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result['status'] == 'assessed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
