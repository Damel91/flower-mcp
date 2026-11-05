from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from flow_of_work_mcp import client_registration, profile_settings
from flow_of_work_mcp.cli import main
from flow_of_work_mcp.config import load_config_with_revision
from flow_of_work_mcp.managed_service_security import write_owned
from flow_of_work_mcp.profile_settings import DashboardSettings, SettingsError, apply_profile_settings
from flow_of_work_mcp.runtime_ownership import acquire_runtime_ownership


@pytest.fixture
def profile(tmp_path):
    if os.name == 'posix' and os.geteuid() == 0:
        pytest.skip('Settings require a normal local owner account.')
    root = tmp_path.resolve() / 'profiles' / 'existing'
    path = root / 'flower.yaml'
    db = root / 'ledger.sqlite3'
    data = {
        'schema_version': 1,
        'runtime': {'database_path': 'ledger.sqlite3', 'import_root': 'imports', 'job_workers': 1},
        'logging': {'logs_path': 'logs', 'level': 'INFO', 'enable_console': False},
        'model': {'enabled': False, 'context_length': 1024},
        'providers': {
            'implementation_graph': {
                'enabled': True, 'url': 'https://example.invalid/mcp', 'surfaces': ['repo'],
                'bindings': [{'project_id': 'example', 'scope_id': 'repository', 'surfaces': ['repo']}],
            },
        },
        'packet_provider': {'mode': 'agnostic'},
    }
    payload = ('# original retained comment\n' + yaml.safe_dump(data, sort_keys=False)).encode()
    write_owned(path, payload)
    # Not a SQLite database: settings must not open or initialize the ledger.
    write_owned(db, b'opaque ledger bytes')
    return path, db, payload


def _request(snapshot, changes):
    return {'revision': snapshot['revision'], 'draft_id': snapshot['draft']['id'] if snapshot['draft'] else None,
            'changes': changes}


def _save(settings, changes):
    return settings.save(_request(settings.snapshot(), changes))


def _expect(code, action):
    with pytest.raises(SettingsError) as error:
        action()
    assert error.value.code == code


def test_snapshot_uses_exact_loaded_revision_and_typed_fields_without_writes(profile):
    path, db, payload = profile
    path.write_bytes(payload.replace(b'\n', b'\r\n'))
    config, revision = load_config_with_revision(path)
    assert revision == hashlib.sha256(path.read_bytes()).hexdigest()
    settings = DashboardSettings(path, config.runtime.database_path, loaded_revision=revision)
    view = settings.snapshot()
    fields = {row['key']: row for row in view['fields']}
    assert view['database_path'] == str(db) and view['config_path'] == str(path)
    assert fields['runtime.import_root']['value'] == str(path.parent / 'imports')
    assert fields['runtime.import_root']['section'] == 'basic'
    assert fields['model.enabled']['value'] is False
    assert fields['model.api_key_env']['nullable'] is True
    assert fields['model.api_key_env']['value'] is None
    assert fields['logging.level']['options'] == ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
    assert fields['model.backend']['readonly'] is True
    assert 'runtime.database_path' not in fields
    assert view['revision'] == revision and view['draft'] is None
    assert view['loaded_revision'] == revision
    assert not settings._directory.exists()


def test_save_replace_and_discard_are_revision_bound_without_yaml_or_db_writes(profile):
    path, db, payload = profile
    settings = DashboardSettings(path, db)
    before = settings.snapshot()
    first = _save(settings, {'logging.level': 'DEBUG'})
    assert first['draft']['state'] == 'pending'
    assert first['revision'] == before['revision']
    assert first['fields'] == before['fields']
    assert _save(settings, {'logging.level': 'DEBUG'})['draft'] == first['draft']
    _expect('settings_draft_changed', lambda: settings.save(_request(before, {'logging.level': 'WARNING'})))
    second = settings.save(_request(first, {'model.context_length': None}))
    assert second['draft']['id'] != first['draft']['id']
    assert second['draft']['changes'] == {'model.context_length': None}
    _expect('settings_draft_changed', lambda: settings.save(_request(first, {})))
    assert settings.save(_request(second, {}))['draft'] is None
    assert path.read_bytes() == payload and db.read_bytes() == b'opaque ledger bytes'


@pytest.mark.parametrize(('changes', 'code'), [
    ({'runtime.database_path': 'another.sqlite3'}, 'settings_input_invalid'),
    ({'providers.implementation_graph.bindings': []}, 'settings_input_invalid'),
    ({'model.enabled': 1}, 'settings_input_invalid'),
    ({'model.temperature': float('nan')}, 'settings_input_invalid'),
    ({'model.api_key_env': 'sk-secret-value'}, 'settings_input_invalid'),
    ({'model.base_url': 'https://user:password@example.invalid'}, 'settings_input_invalid'),
    ({'packet_provider.endpoint': 'https://example.invalid/mcp?token=secret'}, 'settings_input_invalid'),
    ({'packet_provider.endpoint': 'https://example.invalid/mcp/private-token'}, 'settings_input_invalid'),
    ({'model.enabled': True}, 'settings_validation_failed'),
    ({'packet_provider.mode': 'required'}, 'settings_validation_failed'),
    ({'runtime.job_workers': 0}, 'settings_validation_failed'),
])
def test_disallowed_or_invalid_edits_do_not_replace_profile_or_create_draft(profile, changes, code):
    path, db, payload = profile
    settings = DashboardSettings(path, db)
    _expect(code, lambda: _save(settings, changes))
    assert settings.snapshot()['draft'] is None and path.read_bytes() == payload


def test_legacy_sensitive_endpoints_are_redacted_and_never_returned_from_draft(profile, monkeypatch):
    path, db, payload = profile
    raw = yaml.safe_load(payload)
    raw['model'].update(api_key_env='FLOWER_MODEL_API_KEY', base_url='https://user:password@example.invalid')
    raw['providers']['implementation_graph']['url'] = 'https://example.invalid/mcp?token=provider-secret'
    raw['providers']['packet_evidence'] = {'url': 'https://example.invalid/mcp/path-secret'}
    path.write_text(yaml.safe_dump(raw))
    monkeypatch.setenv('FLOWER_MODEL_API_KEY', 'secret-environment-value')
    settings = DashboardSettings(path, db)
    view = _save(settings, {'logging.level': 'DEBUG'})
    encoded = json.dumps(view)
    assert all(secret not in encoded for secret in ('password', 'provider-secret', 'path-secret', 'secret-environment-value'))
    fields = {field['key']: field for field in view['fields']}
    assert fields['model.api_key_env']['value'] == 'FLOWER_MODEL_API_KEY'
    assert fields['model.base_url']['value'] is None and fields['model.base_url']['readonly']
    assert fields['providers.implementation_graph.url']['readonly']
    assert fields['providers.packet_evidence.url']['value'] is None
    assert fields['providers.packet_evidence.url']['readonly']
    assert view['loaded_revision'] is None
    _expect('settings_input_invalid', lambda: _save(settings, {'model.base_url': 'https://example.invalid'}))


def test_offline_apply_preserves_ledger_and_unedited_mapping_with_exact_backup_and_replay(profile):
    path, db, payload = profile
    _, original_revision = load_config_with_revision(path)
    settings = DashboardSettings(path, db, loaded_revision=original_revision)
    view = _save(settings, {'runtime.import_root': 'other-imports', 'model.context_length': None,
                            'providers.implementation_graph.tool': 'snapshot_v2'})
    key = view['draft']['id']
    with acquire_runtime_ownership(db):
        _expect('settings_ledger_active', lambda: apply_profile_settings(path, key))
    assert path.read_bytes() == payload and not list(settings._directory.glob('*.bak'))
    result = apply_profile_settings(path, key)
    assert result['changed'] and result['state'] == 'applied'
    assert Path(result['backup_path']).read_bytes() == payload
    assert db.read_bytes() == b'opaque ledger bytes'
    original, applied = yaml.safe_load(payload), yaml.safe_load(path.read_bytes())
    original['runtime']['import_root'] = 'other-imports'
    original['model'].pop('context_length')
    original['providers']['implementation_graph']['tool'] = 'snapshot_v2'
    assert applied == original
    assert apply_profile_settings(path, key) == {**result, 'changed': False}
    _expect('settings_configuration_changed', settings.snapshot)
    _, revision = load_config_with_revision(path)
    assert DashboardSettings(path, db, loaded_revision=revision).snapshot()['draft']['state'] == 'applied'


def test_same_inode_yaml_edit_blocks_running_snapshot_and_stales_offline_draft(profile):
    path, db, payload = profile
    _, revision = load_config_with_revision(path)
    running = DashboardSettings(path, db, loaded_revision=revision)
    before = running.snapshot()
    staged = _save(running, {'logging.level': 'DEBUG'})
    inode = path.stat().st_ino
    edited = payload + b'# changed outside Flower\n'
    path.write_bytes(edited)
    assert path.stat().st_ino == inode
    _expect('settings_configuration_changed', running.snapshot)
    _expect('settings_configuration_changed', lambda: running.save(_request(before, {})))
    assert DashboardSettings(path, db).snapshot()['draft']['state'] == 'stale'
    _expect('settings_configuration_changed', lambda: apply_profile_settings(path, staged['draft']['id']))
    assert path.read_bytes() == edited


def test_yaml_aliases_cannot_change_unselected_provider_and_duplicate_keys_fail_closed(profile):
    path, db, payload = profile
    raw = yaml.safe_load(payload)
    raw['providers']['implementation_graph']['tool'] = 'original_snapshot'
    raw['providers']['packet_evidence'] = raw['providers']['implementation_graph']
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    assert '&id' in path.read_text()
    settings = DashboardSettings(path, db)
    draft = _save(settings, {'providers.implementation_graph.tool': 'new_graph_tool'})['draft']
    apply_profile_settings(path, draft['id'])
    parsed = yaml.safe_load(path.read_bytes())
    assert parsed['providers']['implementation_graph']['tool'] == 'new_graph_tool'
    assert parsed['providers']['packet_evidence']['tool'] == 'original_snapshot'
    before = path.read_bytes() + b'schema_version: 1\n'
    path.write_bytes(before)
    _expect('settings_configuration_invalid', settings.snapshot)
    assert path.read_bytes() == before


def test_changed_database_identity_cannot_apply_a_draft(profile):
    path, db, payload = profile
    settings = DashboardSettings(path, db)
    key = _save(settings, {'logging.level': 'DEBUG'})['draft']['id']
    replacement = db.with_suffix('.replacement')
    write_owned(replacement, db.read_bytes())
    os.replace(replacement, db)
    assert settings.snapshot()['draft']['state'] == 'stale'
    _expect('settings_configuration_changed', lambda: apply_profile_settings(path, key))
    assert path.read_bytes() == payload


def test_alias_config_rejected_and_cross_profile_draft_does_not_apply(profile):
    path, db, payload = profile
    key = _save(DashboardSettings(path, db), {'logging.level': 'DEBUG'})['draft']['id']
    alias = path.with_suffix('.link.yaml')
    try:
        alias.symlink_to(path)
    except OSError:
        pytest.skip('Creating symbolic links is not available to this test account.')
    _expect('settings_owner_unsafe', lambda: DashboardSettings(alias, db).snapshot())
    _expect('settings_owner_unsafe', lambda: apply_profile_settings(alias, key))
    other = path.with_suffix('.other.yaml')
    write_owned(other, payload)
    _expect('settings_draft_missing', lambda: apply_profile_settings(other, key))
    assert other.read_bytes() == path.read_bytes() == payload


@pytest.mark.skipif(os.name == 'nt', reason='Uses the existing POSIX compare-before-replace helper.')
def test_apply_never_overwrites_concurrent_external_edit(profile, monkeypatch):
    path, db, payload = profile
    settings = DashboardSettings(path, db)
    key = _save(settings, {'logging.level': 'DEBUG'})['draft']['id']
    replace = client_registration._replace_config
    edited = payload + b'# concurrent external edit\n'

    def intervening_edit(*args):
        path.write_bytes(edited)
        return replace(*args)

    monkeypatch.setattr(client_registration, '_replace_config', intervening_edit)
    _expect('settings_configuration_changed', lambda: apply_profile_settings(path, key))
    assert path.read_bytes() == edited
    assert (settings._directory / f'{key}.yaml.bak').read_bytes() == payload


@pytest.mark.skipif(os.name == 'nt', reason='Uses the existing POSIX compare-before-replace helper.')
def test_uncertain_publish_is_inspected_by_exact_replay(profile, monkeypatch):
    path, db, payload = profile
    settings = DashboardSettings(path, db)
    key = _save(settings, {'logging.level': 'DEBUG'})['draft']['id']
    replace = client_registration._replace_config

    def lost_settlement(*args):
        replace(*args)
        raise OSError('internal I/O details must not leak')

    monkeypatch.setattr(client_registration, '_replace_config', lost_settlement)
    _expect('settings_apply_unconfirmed', lambda: apply_profile_settings(path, key))
    assert settings.snapshot()['draft']['state'] == 'applied'
    assert apply_profile_settings(path, key)['changed'] is False
    assert (settings._directory / f'{key}.yaml.bak').read_bytes() == payload


def test_cli_selects_existing_profile_without_constructing_runtime(profile, capsys):
    path, db, _ = profile
    key = _save(DashboardSettings(path, db), {'logging.enable_console': True})['draft']['id']
    main(['settings', 'apply', '--profile', 'existing', '--profile-root', str(path.parents[2]), '--draft-id', key])
    assert json.loads(capsys.readouterr().out)['state'] == 'applied'
    assert yaml.safe_load(path.read_bytes())['logging']['enable_console'] is True
    assert db.read_bytes() == b'opaque ledger bytes'


@pytest.mark.skipif(sys.platform != 'darwin', reason='Uses the local Darwin extended-ACL fixture.')
def test_posix_acl_preflight_blocks_new_draft_but_allows_discard(profile):
    import pwd

    path, db, payload = profile
    settings = DashboardSettings(path, db)
    before = _save(settings, {'logging.level': 'DEBUG'})
    owner = pwd.getpwuid(os.geteuid()).pw_name
    result = subprocess.run(['/bin/chmod', '+a', f'user:{owner} allow read', str(path)],
                            check=False, capture_output=True)
    if result.returncode:
        pytest.skip('The test filesystem does not support the extended-ACL fixture.')
    _expect('settings_metadata_unsupported', lambda: _save(settings, {'logging.level': 'WARNING'}))
    assert settings.snapshot()['draft'] == before['draft']
    assert settings.save(_request(before, {}))['draft'] is None
    assert path.read_bytes() == payload


def test_windows_staging_rechecks_before_native_call_and_retains_uncertain_files(profile, monkeypatch):
    # This verifies wrapper sequencing with local bytes, not native Windows ACL behavior.
    path, _, payload = profile
    recovery = path.with_suffix('.windows-original')
    calls = []
    monkeypatch.setattr(profile_settings.secure, '_windows_protect', lambda *args, **kwargs: None)

    def publish(selected, staged, original):
        calls.append((selected, staged, original))
        assert staged.read_bytes() == b'target config'
        os.replace(selected, original)
        raise OSError('uncertain native rename')

    monkeypatch.setattr(profile_settings, '_native_replace_windows', publish)

    def changed():
        raise SettingsError('settings_configuration_changed', 'profile changed', 409)

    _expect('settings_configuration_changed', lambda: profile_settings._replace_windows(path, b'target config', recovery, changed))
    assert not calls and not list(path.parent.glob('.profile-replace-*'))
    assert path.read_bytes() == payload

    with pytest.raises(OSError, match='uncertain native rename'):
        profile_settings._replace_windows(path, b'target config', recovery, lambda: None)
    assert recovery.read_bytes() == payload
    assert calls[0][1].read_bytes() == b'target config'
