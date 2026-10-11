"""Actual predecessor schema/data migration, with isolated transaction fault tests.

The old implementation is read from this repository's Git history and executes
in a fresh subprocess. Source archives without Git cannot qualify this path.
No shared ledger, runtime profile or server is opened by these tests.
"""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile

import pytest

from flow_of_work_mcp import SQLiteRequirementLedger
from flow_of_work_mcp.application.external_work import ExternalWorkService


_SCHEMA_PATH = 'src/flow_of_work_mcp/adapters/sqlite/schema.py'
_NEW_TABLES = ('architecture_revisions', 'architecture_adoptions', 'architecture_requests',
               'packet_executor_selections', 'packet_provider_capabilities', 'packet_executor_requests',
               'packet_provider_admissions')


def _tables(path):
    with closing(sqlite3.connect(path)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')] for table in tables}


def _rows(path, schema):
    with closing(sqlite3.connect(path)) as connection:
        return {table: sorted(connection.execute('SELECT ' + ','.join('"' + name + '"' for name in columns)
                                                 + ' FROM "' + table + '"').fetchall(), key=repr)
                for table, columns in schema.items() if table != 'schema_migrations'}


@pytest.fixture(scope='module')
def old_ledger(tmp_path_factory):
    repository = Path(__file__).resolve().parents[1]
    if not (repository / '.git').exists() or shutil.which('git') is None:
        pytest.skip('Actual schema52 predecessor qualification requires repository Git history.')
    history = subprocess.run(['git', 'log', '-n', '30', '--format=%H', '--', _SCHEMA_PATH], cwd=repository,
                             text=True, capture_output=True, check=True).stdout.splitlines()
    predecessor = next((revision for revision in history
                        if 'CURRENT_SCHEMA_VERSION = 52' in subprocess.run(['git', 'show', f'{revision}:{_SCHEMA_PATH}'],
                            cwd=repository, text=True, capture_output=True, check=True).stdout), None)
    if predecessor is None:
        pytest.skip('No actual schema52 predecessor is available in this checkout history.')
    temporary = tmp_path_factory.mktemp('actual-schema52')
    archived = subprocess.run(['git', 'archive', predecessor, 'src/flow_of_work_mcp'], cwd=repository,
                              capture_output=True, check=True).stdout
    source = temporary / 'predecessor'
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts
            if member.isdir():
                continue
            assert member.isfile(), 'Unexpected nonregular predecessor source'
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    path = temporary / 'predecessor.sqlite'
    # This script imports only archived source. Its records are explicit synthetic
    # host declarations, rather than an assertion that implementation ran.
    script = r'''
import json, sqlite3, sys
from flow_of_work_mcp import SQLiteRequirementLedger, ChangeControlService, GovernedChangeDraft, ImplementationPacketDraft, PacketWorkPlanDraft, WorkPlanUnit, HandoverDraft
from flow_of_work_mcp.application.external_work import ExternalWorkService
ledger = SQLiteRequirementLedger(sys.argv[1])
ledger.create_project('alpha', 'Synthetic predecessor migration', actor='operator')
req = ledger.add_requirement('alpha', title='Preserve lifecycle', statement='The server shall preserve lifecycle authority.', category='functional', rationale='Original accepted intent.', actor='stakeholder')
ledger.record_verification('alpha', req['requirement_id'], kind='tested_deterministically', outcome='passed', reference='host:predecessor-fixture', actor='external-agent', metadata={'provenance':'host-reported', 'text':'Originale\nè evidenza sintetica.'})
changes = ChangeControlService(ledger)
change = changes.create_change('alpha', GovernedChangeDraft(title='Preserve state', rationale='Migration fixture.', requirement_ids=(req['requirement_id'],)), actor='engineer')
packet = changes.add_packet('alpha', change['change_id'], ImplementationPacketDraft(title='Bounded protocol', objective='Preserve a declared protocol.', rationale='No duplicate store.', in_scope=('src/protocol.py',), invariants=('A single lifecycle writer.',), completion_criteria=('Protocol is declared.',)), actor='engineer')['packets'][0]
packet = changes.refine_packet('alpha', change['change_id'], packet['packet_id'], objective='Preserve an explicit declared protocol after investigation.', actor='engineer')['packets'][0]
external = ExternalWorkService(ledger)
ids = ('alpha', change['change_id'], packet['packet_id'])
external.call(*ids, 'upgrade_validation', actor='engineer', request_id='criteria', payload={'expected_spec_revision':packet['spec_revision'], 'expected_plan_revision':0})
unit = WorkPlanUnit(client_unit_key='protocol', operation_kind='new_file', file_path='src/protocol.py', instructions=('Implement the declared protocol.',), unit_checks=('Protocol check passes.',), implements=(1,), provides=({'name':'protocol', 'kind':'api', 'clauses':['Return the declared value.']},), verifies=({'criterion':1, 'kind':'unit_check', 'statement':'Protocol check passes.'},))
plan = ledger.create_packet_work_plan('alpha', PacketWorkPlanDraft(change['change_id'], packet['packet_id'], packet['spec_revision'], (unit,)), actor='engineer', request_id='plan')
ledger.transition_packet_work_plan('alpha', plan['work_plan_id'], plan['plan_revision'], status='accepted', expected_packet_revision=plan['packet_revision'], expected_current_plan_revision=plan['plan_revision'], rationale='Complete bounded plan.', actor='engineer', request_id='plan-adopt')
revisions = {'expected_spec_revision':plan['packet_revision'], 'expected_plan_revision':plan['plan_revision']}
external.call(*ids, 'set_mode', actor='engineer', request_id='external-mode', payload={'mode':'external_agent', **revisions})
artifact = external.call(*ids, 'export_plan', actor='engineer', request_id='offline-plan', payload=revisions)
payload = {'report_key':'synthetic-complete', **revisions, 'authority_fingerprint':artifact['authority_fingerprint'], 'unit_key':'protocol', 'outcome':'complete', 'summary':'Synthetic predecessor host declaration.', 'source_revision':'fixture-revision', 'artifacts':[{'reference':'src/protocol.py','description':'Declared synthetic output'}], 'produced_contracts':[{'name':'protocol','artifact_ref':'src/protocol.py'}], 'verification':[{'criterion':1,'kind':'unit_check','statement':'Protocol check passes.','status':'pass','evidence_ref':'host:synthetic-log','provenance':'host-reported'}], 'unresolved':[]}
external.call(*ids, 'report_outcome', actor='external-agent', request_id='report', payload=payload)
hand = ledger.create_handover('alpha', HandoverDraft(change_id=change['change_id'], packet_id=packet['packet_id']), actor='engineer', request_id='frozen-hand')
with sqlite3.connect(sys.argv[1]) as connection:
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
assert version == 52
print(json.dumps({'predecessor_schema':version, 'ids':ids, 'handover_id':hand['handover_id'], 'authority_fingerprint':artifact['authority_fingerprint'], 'requirement_clock':ledger.ledger_version('alpha')}))
'''
    environment = {**os.environ, 'PYTHONPATH': str(source / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', script, str(path)], cwd=temporary,
                            env=environment, text=True, capture_output=True, check=True)
    metadata = json.loads(result.stdout)
    metadata['predecessor_revision'] = predecessor
    schema = _tables(path)
    assert 'architecture_refs_json' not in schema['implementation_packets']
    assert 'architecture_refs_json' not in schema['implementation_packet_revisions']
    assert not any(table in schema for table in _NEW_TABLES)
    return path, metadata, schema, _rows(path, schema)


def test_actual_schema52_upgrade_preserves_records_clocks_legacy_authority_and_reopen(tmp_path, old_ledger):
    original, metadata, schema, before = old_ledger
    target = tmp_path / 'upgrade.sqlite'
    shutil.copyfile(original, target)
    ledger = SQLiteRequirementLedger(target)
    assert _rows(target, schema) == before
    assert ledger.ledger_version('alpha') == metadata['requirement_clock']
    assert ledger.architecture_revision('alpha')['state'] == 'absent'
    assert ledger.resolve_architecture_refs('alpha', []) is None
    assert ledger.packet_executor_state(*metadata['ids']) == {'selection': None, 'capabilities': []}
    packet = ledger.change_state('alpha', metadata['ids'][1])['packets'][0]
    assert 'architecture_refs' not in packet
    todo = ExternalWorkService(ledger).todo(*metadata['ids'])
    assert todo['authority_fingerprint'] == metadata['authority_fingerprint']
    assert todo['current_unit'] is None
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 55
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        for table in _NEW_TABLES:
            assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        for table in ('implementation_packets', 'implementation_packet_revisions'):
            assert {row[0] for row in connection.execute(f'SELECT architecture_refs_json FROM {table}')} == {'[]'}
    after_schema, after_rows = _tables(target), _rows(target, _tables(target))
    SQLiteRequirementLedger(target)
    assert _tables(target) == after_schema and _rows(target, after_schema) == after_rows


def test_recorded_schema54_gains_only_empty_admissions_and_preserves_authority(tmp_path, old_ledger):
    original, metadata, _, _ = old_ledger
    target = tmp_path / 'recorded54.sqlite'
    shutil.copyfile(original, target)

    class Recorded54Ledger(SQLiteRequirementLedger):
        def migrate_packet_provider_admissions(self):
            # Execute the unchanged53/54 migrations and stop before the new55
            # checkpoint, reproducing the already-recorded integration prototype.
            pass

    previous = Recorded54Ledger(target)
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 54
    schema = _tables(target)
    before = _rows(target, schema)
    assert 'packet_provider_admissions' not in schema
    assert ExternalWorkService(previous).todo(*metadata['ids'])['authority_fingerprint'] == metadata['authority_fingerprint']
    upgraded = SQLiteRequirementLedger(target)
    assert _rows(target, schema) == before
    assert upgraded.ledger_version('alpha') == metadata['requirement_clock']
    assert ExternalWorkService(upgraded).todo(*metadata['ids'])['authority_fingerprint'] == metadata['authority_fingerprint']
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 55
        assert connection.execute('SELECT COUNT(*) FROM packet_provider_admissions').fetchone()[0] == 0
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('failed_version', [53, 54, 55])
def test_new_migration_failure_rolls_back_its_ddl_and_resumes_safely(tmp_path, old_ledger, failed_version):
    original, metadata, schema, before = old_ledger
    target = tmp_path / f'rollback-{failed_version}.sqlite'
    shutil.copyfile(original, target)
    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if 'INSERT OR IGNORE INTO schema_migrations' in sql and f'VALUES({failed_version},' in sql:
                raise RuntimeError('injected migration checkpoint failure')
            return super().execute(sql, parameters)
    class FailingLedger(SQLiteRequirementLedger):
        def _connect(self):
            connection = sqlite3.connect(self.database_path, factory=FailingConnection)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=5000')
            return connection
    with pytest.raises(RuntimeError, match='injected migration'):
        FailingLedger(target)
    assert _rows(target, schema) == before
    remaining = _tables(target)
    rolled_back_tables = _NEW_TABLES[:3] if failed_version == 53 else (
        _NEW_TABLES[3:6] if failed_version == 54 else _NEW_TABLES[6:])
    assert not any(table in remaining for table in rolled_back_tables)
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == failed_version - 1
    if failed_version == 53:
        assert 'architecture_refs_json' not in remaining['implementation_packets']
        assert 'architecture_refs_json' not in remaining['implementation_packet_revisions']
    recovered = SQLiteRequirementLedger(target)
    assert _rows(target, schema) == before
    assert recovered.ledger_version('alpha') == metadata['requirement_clock']
    assert ExternalWorkService(recovered).todo(*metadata['ids'])['authority_fingerprint'] == metadata['authority_fingerprint']
