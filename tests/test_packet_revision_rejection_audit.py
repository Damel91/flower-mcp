"""Historical071 proof distinguishes requested refinement from prior repair."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from flow_of_work_mcp import GovernedChangeDraft, ImplementationPacketDraft, RequirementDraft
from flow_of_work_mcp.mcp_runtime import build_runtime

TOOL = Path(__file__).resolve().parents[1] / 'tools/audit_packet_revision_rejection.py'
spec = importlib.util.spec_from_file_location('packet_revision_audit', TOOL)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def sha(data): return hashlib.sha256(data).hexdigest()


def snapshot(database):
    with sqlite3.connect(database) as c:
        return {'ledger': {table: [list(row) for row in c.execute('SELECT * FROM ' + table)]
                           for table in audit.LAYOUT_HASHES}}


def dump(database):
    with sqlite3.connect(database) as c: return tuple(c.iterdump())


@pytest.fixture
def owned(tmp_path, monkeypatch):
    runtime = build_runtime(database_path=tmp_path / 'owned.sqlite3', import_root=tmp_path)
    runtime.requirements.create_project('owned', 'Owned source assessment', actor='engineer')
    req = runtime.requirements.register('owned', RequirementDraft(title='Owned state', statement='The software shall retain state.',
        category='functional', rationale='Scope'), actor='engineer')
    change = runtime.changes.create_change('owned', GovernedChangeDraft(title='Owned scope', rationale='Inspect source',
        requirement_ids=(req['requirement_id'],)), actor='engineer')
    packet = runtime.changes.add_packet('owned', change['change_id'], ImplementationPacketDraft(title='Owned packet',
        objective='Inspect source', completion_criteria=('State retained',), target_policy='documental_only'), actor='engineer')['packets'][0]
    database = runtime.ledger.database_path
    before = tmp_path / 'before.json';before.write_text(json.dumps(snapshot(database)))
    request = tmp_path / 'request.json';request.write_text(json.dumps({'tool':'fow_packet_author','arguments':{
        'operation':'revise_packet','project_id':'owned','packet_id':packet['packet_id'],'actor':'engineer','request_id':'original',
        'expected_spec_revision':packet['spec_revision'],'expected_plan_revision':0,
        'architecture_refs':[{'id':'Core','kind':'component'}]}}))
    package = tmp_path / 'package';package.mkdir();(package/'server.py').write_text('raise RuntimeError("MUST NEVER IMPORT ORIGINAL")\n')
    wheel = tmp_path / 'fixture.whl'
    with zipfile.ZipFile(wheel,'w') as z:z.write(package/'server.py','flow_of_work_mcp/server.py')
    monkeypatch.setattr(audit,'WHEEL_SHA256',sha(wheel.read_bytes()))
    args = dict(wheel=wheel,package_root=package,request_json=request,expected_request_sha256=sha(request.read_bytes()),
        project_id='owned',change_id=change['change_id'],packet_id=packet['packet_id'],request_id='original',database=database,
        before_snapshot_json=before,expected_before_snapshot_sha256=sha(before.read_bytes()),association_reference='owner:retained-fixture')
    yield args, runtime
    runtime.close()


def add_witness(owned):
    args, runtime = owned
    runtime.changes.evaluate_packet_readiness('owned',args['change_id'],args['packet_id'],
        actor='engineer',request_id='original:repair:readiness')
    return args


def refused(result, reason):
    assert result == {'contract_version':audit.CONTRACT,'status':'refused','effect_state':'unknown','reason':reason}


def test_no_witness_never_becomes_none_or_applied(owned):
    args,_ = owned;before=dump(args['database']);result=audit.assess(**args)
    assert result['status']=='assessed' and result['requested_revision_applied'] is False
    assert result['original_effect_state']==result['ancillary_effect_state']=='unknown'
    assert result['maintenance_witness'] is None and result['ancillary_effects_complete'] is False
    assert not {'effect_receipt','recovery_resolution','effect_state'} & result.keys()
    assert dump(args['database'])==before


def test_exact_new_readiness_event_and_revision_prove_only_observed_maintenance(owned):
    args=add_witness(owned);before=dump(args['database']);result=audit.assess(**args)
    assert result['status']=='assessed',result
    assert result['ancillary_effect_state']=='applied' and result['requested_revision_applied'] is False
    assert result['original_effect_state']=='unknown' and result['historical_result_rewritten'] is False
    assert result['ancillary_effects_complete'] is False
    assert result['maintenance_witness']['request_id']=='original:repair:readiness'
    assert result['maintenance_witness']['lifecycle_revision']==result['current_packet']['current_revision']
    assert result['producer']['source_commit']==audit.SOURCE_COMMIT
    assert result['provenance']['original_execution_association']=='owner_declared'
    assert not {'effect_receipt','recovery_resolution','effect_state'} & result.keys()
    assert dump(args['database'])==before


@pytest.mark.parametrize('case,reason', [
    ('actor','correlated_event_identity_mismatch'),('packet','correlated_event_identity_mismatch'),
    ('semantic','original_request_has_revision_history'),('payload','maintenance_payload_mismatch'),
    ('missing_row','ambiguous_revision_witness'),('ambiguous_row','ambiguous_revision_witness'),
    ('past_event','maintenance_witness_predates_snapshot'),('row_payload','maintenance_payload_mismatch'),
    ('schema','unsupported_database_schema'),('layout','unsupported_column_layout'),
    ('before_layout','before_snapshot_layout_mismatch'),('before_schema','unsupported_before_schema')])
def test_inconsistent_or_ambiguous_witness_refuses_without_writes(owned,case,reason):
    args=add_witness(owned)
    with sqlite3.connect(args['database']) as c:
        if case=='actor':c.execute("UPDATE change_events SET actor='other' WHERE request_id='original:repair:readiness'")
        elif case=='packet':c.execute("UPDATE change_events SET packet_id='PACKET-999999' WHERE request_id='original:repair:readiness'")
        elif case=='semantic':c.execute("UPDATE change_events SET event_type='packet_revised',request_id='original' WHERE request_id='original:repair:readiness'")
        elif case=='payload':c.execute("UPDATE change_events SET payload_json='{}' WHERE request_id='original:repair:readiness'")
        elif case=='missing_row':c.execute("DELETE FROM implementation_packet_revisions WHERE revision>1")
        elif case=='ambiguous_row':
            c.row_factory=sqlite3.Row;row=dict(c.execute('SELECT * FROM implementation_packet_revisions ORDER BY revision DESC LIMIT 1').fetchone());row['revision']+=1
            c.execute('INSERT INTO implementation_packet_revisions ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        elif case=='row_payload':c.execute("UPDATE implementation_packet_revisions SET readiness_state='different' WHERE revision>1")
        elif case=='schema':c.execute('DELETE FROM schema_migrations WHERE version=55')
        elif case=='layout':c.execute('ALTER TABLE change_events ADD COLUMN unexpected TEXT')
    if case.startswith('before_') or case=='past_event':
        data=snapshot(args['database']) if case=='past_event' else json.loads(args['before_snapshot_json'].read_text())
        if case=='before_layout':data['ledger']['implementation_packets'][0].pop()
        if case=='before_schema':data['ledger']['schema_migrations']=[]
        args['before_snapshot_json'].write_text(json.dumps(data));args['expected_before_snapshot_sha256']=sha(args['before_snapshot_json'].read_bytes())
    before=dump(args['database']);refused(audit.assess(**args),reason);assert dump(args['database'])==before


@pytest.mark.parametrize('case,reason', [('request_digest','retained_input_digest_mismatch'),
    ('before_digest','retained_input_digest_mismatch'),('artifact','unsupported_wheel_digest'),
    ('package','installed_package_bytes_mismatch'),('owner','missing_owner_association_reference'),
    ('identity','original_request_identity_mismatch'),('valid_refs','unsupported_rejection_path')])
def test_unproved_inputs_refuse(owned,case,reason):
    args,_=owned
    if case=='request_digest':args['expected_request_sha256']='0'*64
    elif case=='before_digest':args['expected_before_snapshot_sha256']='0'*64
    elif case=='artifact':args['wheel'].write_bytes(b'other')
    elif case=='package':(args['package_root']/'server.py').write_text('modified')
    elif case=='owner':args['association_reference']=''
    else:
        data=json.loads(args['request_json'].read_text())
        if case=='identity':data['arguments']['packet_id']='PACKET-999999'
        else:data['arguments']['architecture_refs']=[{'revision':1,'kind':'component','entity_id':'Core'}]
        args['request_json'].write_text(json.dumps(data));args['expected_request_sha256']=sha(args['request_json'].read_bytes())
    refused(audit.assess(**args),reason)


@pytest.mark.parametrize('raw,reason',[('{"ledger":{},"ledger":{}}','duplicate_json_key'),('{"ledger":NaN}','nonfinite_json_value')])
def test_ambiguous_before_json_is_not_evidence(owned,raw,reason):
    args,_=owned;args['before_snapshot_json'].write_text(raw);args['expected_before_snapshot_sha256']=sha(args['before_snapshot_json'].read_bytes())
    refused(audit.assess(**args),reason)


def test_isolated_cli_never_imports_flower_or_searches_cwd(owned):
    args,_=owned;command=[sys.executable,'-I',str(TOOL)]
    for key,value in args.items():command.extend(['--'+key.replace('_','-'),str(value)])
    result=subprocess.run(command,capture_output=True,text=True,cwd=args['database'].parent)
    assert result.returncode==2 and result.stderr==''
    refused(json.loads(result.stdout),'unsupported_wheel_digest')


def test_current_project_must_exist_even_with_orphan_packet(owned):
    args,_=owned
    with sqlite3.connect(args['database']) as c:c.execute("DELETE FROM projects WHERE project_id='owned'")
    refused(audit.assess(**args),'original_scope_not_found')


def test_overflow_json_float_in_ignored_snapshot_metadata_refuses(owned):
    args,_=owned
    value=args['before_snapshot_json'].read_text().rstrip()
    args['before_snapshot_json'].write_text(value[:-1]+',"ignored":1e400}')
    args['expected_before_snapshot_sha256']=sha(args['before_snapshot_json'].read_bytes())
    refused(audit.assess(**args),'nonfinite_json_value')


def test_before_semantic_history_cannot_be_erased_by_current_absence(owned):
    args,_=owned;data=json.loads(args['before_snapshot_json'].read_text())
    with sqlite3.connect(args['database']) as c:
        columns=[r[1] for r in c.execute('PRAGMA table_info(change_events)')]
    row=dict(zip(columns,data['ledger']['change_events'][0]));row.update(event_id=999,packet_id=args['packet_id'],
        event_type='packet_revised',request_id='original')
    data['ledger']['change_events'].append([row[k] for k in columns])
    args['before_snapshot_json'].write_text(json.dumps(data));args['expected_before_snapshot_sha256']=sha(args['before_snapshot_json'].read_bytes())
    refused(audit.assess(**args),'original_request_has_revision_history')


def test_foreign_project_reusing_request_identity_is_not_this_witness(owned):
    args,runtime=owned
    runtime.requirements.create_project('other','Other project',actor='engineer')
    req=runtime.requirements.register('other',RequirementDraft(title='Other',statement='The other project shall work.',
        category='functional',rationale='Separate authority'),actor='engineer')
    change=runtime.changes.create_change('other',GovernedChangeDraft(title='Other',rationale='Separate authority',
        requirement_ids=(req['requirement_id'],)),actor='engineer')
    packet=runtime.changes.add_packet('other',change['change_id'],ImplementationPacketDraft(title='Other',
        objective='Other scope',completion_criteria=('Works',),target_policy='documental_only'),actor='engineer')['packets'][0]
    runtime.changes.evaluate_packet_readiness('other',change['change_id'],packet['packet_id'],actor='engineer',request_id='original:repair:readiness')
    args['before_snapshot_json'].write_text(json.dumps(snapshot(args['database'])))
    args['expected_before_snapshot_sha256']=sha(args['before_snapshot_json'].read_bytes())
    add_witness(owned)
    assert audit.assess(**args)['ancillary_effect_state']=='applied'
