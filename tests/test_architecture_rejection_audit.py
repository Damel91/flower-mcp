"""Separate historical assessment never executes or rewrites an invocation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('architecture_rejection_audit', TOOLS / 'audit_architecture_rejection.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
sys.path.remove(str(TOOLS))


def sha(value): return hashlib.sha256(value).hexdigest()


@pytest.fixture
def owned(tmp_path, monkeypatch):
    package = tmp_path / 'package'
    package.mkdir()
    (package / 'server.py').write_text('raise RuntimeError("MUST NEVER IMPORT")\n')
    wheel = tmp_path / 'fixture.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.write(package / 'server.py', 'flow_of_work_mcp/server.py')
    monkeypatch.setattr(audit, 'WHEEL_SHA256', sha(wheel.read_bytes()))
    request = tmp_path / 'retained.json'
    request.write_text(json.dumps({'tool': 'fow_architecture', 'arguments': {
        'project_id': 'owned', 'operation': 'propose', 'request_id': 'original', 'actor': 'engineer',
        'payload': {'expected_revision': 0, 'definition': {'components': [{'boundaries': 'invalid'}],
                                                       'interfaces': [], 'decisions': []}}}}))
    database = tmp_path / 'owned.sqlite'
    with sqlite3.connect(database) as connection:
        connection.executescript('''CREATE TABLE schema_migrations(version INTEGER);
            INSERT INTO schema_migrations VALUES(55);
            CREATE TABLE projects(project_id TEXT); INSERT INTO projects VALUES('owned');
            CREATE TABLE architecture_requests(project_id TEXT, request_id TEXT);
            CREATE TABLE requirement_events(project_id TEXT, request_id TEXT);
            INSERT INTO architecture_requests VALUES('owned','previous-applied');''')
    return dict(wheel=wheel, package_root=package, request_json=request,
                expected_request_sha256=sha(request.read_bytes()), project_id='owned', request_id='original',
                database=database, association_reference='owner:retained-invocation')


def dump(database):
    with sqlite3.connect(database) as connection: return tuple(connection.iterdump())


def refused(result, reason):
    assert result == {'contract_version': audit.CONTRACT, 'status': 'refused',
                      'effect_state': 'unknown', 'reason': reason}


def test_assessment_preserves_every_byte_and_does_not_import_original_code(owned):
    before = {p: p.read_bytes() for p in owned['database'].parent.rglob('*') if p.is_file()}
    result = audit.assess(**owned)
    assert result['status'] == 'assessed'
    assert result['original_effect_state'] == 'unknown' and result['historical_result_rewritten'] is False
    assert result['basis'] == 'retrospective_source_audit' and 'effect_receipt' not in result
    assert result['recovery_resolution'] == {'effect_state': 'none', 'mutation_started': False}
    assert result['provenance']['original_execution_association'] == 'owner_declared'
    assert result['ledger']['architecture_request_matches'] == result['ledger']['requirement_event_request_matches'] == 0
    assert {p: p.read_bytes() for p in owned['database'].parent.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('table,key', [('architecture_requests','original'),
    ('architecture_requests','original:derived'), ('requirement_events','original'),
    ('requirement_events','original:derived:deeper')])
def test_any_original_or_derived_history_refuses_without_mutation(owned, table, key):
    with sqlite3.connect(owned['database']) as connection:
        connection.execute(f'INSERT INTO {table} VALUES (?,?)', ('owned', key))
    before = dump(owned['database'])
    refused(audit.assess(**owned), 'original_request_has_durable_history')
    assert dump(owned['database']) == before


@pytest.mark.parametrize('case,reason', [('valid_boundaries','unsupported_rejection_path'),
    ('actor','unsupported_actor'), ('operation','unsupported_operation_or_fields'),
    ('foreign','original_request_identity_mismatch'), ('extra','unsupported_operation_or_fields'),
    ('revision','unsupported_expected_revision'), ('definition','unsupported_definition'),
    ('payload','unsupported_payload')])
def test_unsupported_request_is_not_proved_by_absence(owned, case, reason):
    data = json.loads(owned['request_json'].read_bytes())
    args = data['arguments']
    if case == 'valid_boundaries': args['payload']['definition']['components'][0]['boundaries'] = ['valid']
    elif case == 'actor': args['actor'] = ''
    elif case == 'operation': args['operation'] = 'adopt'
    elif case == 'foreign': args['project_id'] = 'other'
    elif case == 'extra': args['extra'] = 1
    elif case == 'revision': args['payload']['expected_revision'] = True
    elif case == 'definition': args['payload']['definition']['interfaces'] = 'bad'
    else: args['payload']['extra'] = 1
    owned['request_json'].write_text(json.dumps(data))
    owned['expected_request_sha256'] = sha(owned['request_json'].read_bytes())
    refused(audit.assess(**owned), reason)


@pytest.mark.parametrize('case,reason', [('input_digest','retained_request_digest_mismatch'),
    ('wheel','unsupported_wheel_digest'), ('package','installed_package_bytes_mismatch'),
    ('missing_package','installed_package_inventory_mismatch'), ('owner','missing_owner_association_reference'),
    ('schema','unsupported_database_schema'), ('project','original_project_not_found'),
    ('missing_db','audit_input_or_storage_unverifiable')])
def test_unverifiable_premise_refuses(owned, case, reason):
    if case == 'input_digest': owned['expected_request_sha256'] = '0' * 64
    elif case == 'wheel': owned['wheel'].write_bytes(b'wrong wheel')
    elif case == 'package': (owned['package_root'] / 'server.py').write_text('changed')
    elif case == 'missing_package': (owned['package_root'] / 'server.py').unlink()
    elif case == 'owner': owned['association_reference'] = ''
    elif case == 'missing_db': owned['database'] = owned['database'].parent / 'absent.sqlite'
    else:
        with sqlite3.connect(owned['database']) as connection:
            connection.execute('UPDATE schema_migrations SET version=54' if case == 'schema' else 'DELETE FROM projects')
    refused(audit.assess(**owned), reason)
    if case == 'missing_db': assert not owned['database'].exists()


@pytest.mark.parametrize('contents,reason', [('{"tool":1,"tool":2}', 'duplicate_json_key'),
                                           ('{"invalid":NaN}', 'nonfinite_json_value')])
def test_ambiguous_json_refuses(owned, contents, reason):
    owned['request_json'].write_text(contents)
    owned['expected_request_sha256'] = sha(owned['request_json'].read_bytes())
    refused(audit.assess(**owned), reason)


def test_isolated_cli_loads_only_its_sibling_and_refuses_unknown_artifact(owned):
    args = [sys.executable, '-I', str(TOOLS / 'audit_architecture_rejection.py')]
    for key, value in owned.items(): args.extend(['--' + key.replace('_', '-'), str(value)])
    result = subprocess.run(args, capture_output=True, text=True, cwd=owned['database'].parent)
    assert result.returncode == 2 and result.stderr == ''
    refused(json.loads(result.stdout), 'unsupported_wheel_digest')
