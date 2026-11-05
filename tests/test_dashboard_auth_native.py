"""Native-boundary mechanics with fake calls, never native password acceptance."""
from __future__ import annotations

import ctypes as c
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from flow_of_work_mcp import dashboard_auth_native as native
from flow_of_work_mcp import dashboard_auth_worker as worker
from flow_of_work_mcp.adapters.native import dashboard_auth_linux as linux
from flow_of_work_mcp.adapters.native import dashboard_auth_macos as macos
from flow_of_work_mcp.adapters.native import dashboard_auth_windows as windows

OWNER = {'kind': 'uid', 'value': '501'}
SID = 'S-1-5-21-1-2-3-1001'


@pytest.mark.parametrize('identity', [
    {'kind': 'uid', 'value': '0501'}, {'kind': 'uid', 'value': 501},
    {'kind': 'uid', 'value': '-1'}, {'kind': 'uid', 'value': '4294967296'},
    {'kind': 'sid', 'value': 'S-1-05-21-1'}, {'kind': 'uid', 'value': '501', 'local': True},
])
def test_identity_protocol_rejects_noncanonical_values(identity):
    with pytest.raises(ValueError):
        native.canonical_identity(identity)


def test_facade_never_accepts_foreign_or_nonlocal_native_identity(monkeypatch):
    monkeypatch.setattr(native, 'current_identity', lambda: OWNER)
    backend = SimpleNamespace(verify=lambda *_: {'kind': 'uid', 'value': '502', 'local': True})
    monkeypatch.setattr(native, '_backend', lambda: backend)
    assert native.verify(OWNER, 'fake-owner', 'not-a-real-password')['outcome'] == 'denied'
    backend.verify = lambda *_: {**OWNER, 'local': False}
    assert native.verify(OWNER, 'fake-owner', 'not-a-real-password')['outcome'] == 'denied'


def test_capability_does_not_submit_a_password_and_masks_exceptions(monkeypatch):
    monkeypatch.setattr(native, 'current_identity', lambda: OWNER)
    seen = []
    monkeypatch.setattr(native, '_backend', lambda: SimpleNamespace(capability=lambda owner: seen.append(owner)))
    assert native.capability(OWNER) == {'availability': 'ready', 'reason': None}
    assert seen == [OWNER]
    monkeypatch.setattr(native, '_backend', lambda: (_ for _ in ()).throw(OSError('private path or secret')))
    result = native.capability(OWNER)
    assert result == {'availability': 'unavailable', 'reason': 'native_library_unavailable'}
    assert 'private' not in json.dumps(result)


def test_held_posix_file_owner_does_not_follow_replaced_path(tmp_path, monkeypatch):
    monkeypatch.setattr(native, 'platform_name', lambda: 'linux')
    path = tmp_path / 'owned'
    path.write_text('first')
    descriptor = os.open(path, os.O_RDONLY)
    try:
        path.rename(tmp_path / 'retained')
        path.write_text('replacement')
        assert native.file_owner_handle(descriptor) == {'kind': 'uid', 'value': str(os.fstat(descriptor).st_uid)}
        assert os.read(descriptor, 5) == b'first'
    finally:
        os.close(descriptor)


def test_auth_worker_strict_request_and_safe_reply(monkeypatch):
    monkeypatch.setattr(native, 'platform_name', lambda: 'macos')
    monkeypatch.setattr(native, 'verify', lambda *_: {'outcome': 'denied', 'identity': None, 'reason': 'credentials_denied'})
    request = {'contract': native.CONTRACT, 'platform': 'macos', 'owner': OWNER,
               'username': 'fake-owner', 'password': 'sensitive-test-marker'}
    result = worker.process(json.dumps(request).encode())
    assert result == {'contract': native.CONTRACT, 'outcome': 'denied', 'identity': None, 'reason': 'credentials_denied'}
    assert 'sensitive-test-marker' not in json.dumps(result)
    for raw in [b'', b'{}{}', b'{"contract":1,"contract":2}', b'\xff', b'x' * (native.MAX_REQUEST_BYTES + 1)]:
        assert worker.process(raw)['reason'] == 'protocol_invalid'
    for change in [{'extra': True}, {'platform': 'windows'}, {'password': ''}, {'password': 'a\x00b'}]:
        assert worker.process(json.dumps({**request, **change}).encode())['reason'] == 'protocol_invalid'


def test_capability_worker_protocol_has_no_credential_fields(monkeypatch):
    monkeypatch.setattr(native, 'platform_name', lambda: 'macos')
    monkeypatch.setattr(native, 'capability', lambda owner: {'availability': 'ready', 'reason': None})
    monkeypatch.setattr(native, 'verify', lambda *_: pytest.fail('capability must not authenticate'))
    request = {'contract': native.CAPABILITY_CONTRACT, 'platform': 'macos', 'owner': OWNER}
    result = worker.process(json.dumps(request).encode())
    assert result == {'contract': native.CAPABILITY_CONTRACT, 'availability': 'ready', 'reason': None}
    native.validate_capability_reply(result)
    with pytest.raises(ValueError):
        native.validate_capability_request({**request, 'password': 'not allowed'})


@pytest.mark.parametrize('change', [
    {'identity': {**OWNER, 'local': 1}}, {'identity': {**OWNER, 'local': True, 'extra': 1}},
    {'identity': {'kind': 'uid', 'value': '502', 'local': True}}, {'outcome': []}, {'reason': 'private diagnostic'},
])
def test_parent_reply_validator_rejects_forged_or_open_payload(change):
    reply = {'contract': native.CONTRACT, 'outcome': 'verified', 'identity': {**OWNER, 'local': True}, 'reason': None}
    with pytest.raises(ValueError):
        native.validate_reply({**reply, **change}, OWNER)


def test_absolute_isolated_worker_ignores_cwd_and_pythonpath(tmp_path):
    (tmp_path / 'flow_of_work_mcp.py').write_text('raise RuntimeError("untrusted")\n')
    result = subprocess.run([sys.executable, '-I', str(Path(worker.__file__).resolve())], input=b'{}',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(tmp_path)}, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'contract': native.CONTRACT, 'outcome': 'error', 'identity': None, 'reason': 'protocol_invalid'}
    assert len(result.stdout) <= native.MAX_REPLY_BYTES
    assert result.stderr == b''


def test_linux_missing_named_policy_never_reaches_pam_or_other_policy(tmp_path, monkeypatch):
    original_lstat = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda path: SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)
                        if path == tmp_path else original_lstat(path))
    (tmp_path / 'other').write_text('auth required pam_permit.so\naccount required pam_permit.so\n')
    monkeypatch.setattr(linux, 'POLICY', tmp_path / 'flower-mcp')
    monkeypatch.setattr(linux, '_PAM', lambda: pytest.fail('must not use PAM other-policy fallback'))
    with pytest.raises(native.NativeAuthFailure) as error:
        linux.verify(OWNER, 'fake-owner', 'not-real')
    assert error.value.reason == 'native_policy_unavailable'


def test_linux_requires_an_authoritative_local_owner_record(tmp_path, monkeypatch):
    passwd = tmp_path / 'passwd'
    passwd.write_text('fake-owner:x:501:20::/home/fake:/bin/sh\nother:x:502:20::/home/other:/bin/sh\n')
    monkeypatch.setattr(linux, 'PASSWD', passwd)
    assert linux._local_user(OWNER, 'fake-owner') == 'fake-owner'
    with pytest.raises(native.NativeAuthFailure):
        linux._local_user(OWNER, 'other')
    passwd.write_text('directory-alias:x:502:20::/home/fake:/bin/sh\n')
    with pytest.raises(native.NativeAuthFailure):
        linux._local_user(OWNER, 'fake-owner')


@pytest.mark.parametrize('restriction', [0, 1, -1])
def test_linux_inherited_no_new_privileges_is_never_silently_weakened(monkeypatch, restriction):
    calls = []

    class Query:
        def __call__(self, *arguments):
            calls.append(arguments)
            return restriction

    monkeypatch.setattr(linux.c, 'CDLL', lambda *_, **__: SimpleNamespace(prctl=Query()))
    if restriction == 0:
        linux._execution_constraints()
    else:
        with pytest.raises(native.NativeAuthFailure) as error:
            linux._execution_constraints()
        assert error.value.outcome == 'unavailable'
    assert calls == [(39, 0, 0, 0, 0)]


def _fake_pam(*, authentication=0, account=0, prompts=1, ending=0):
    pam = object.__new__(linux._PAM)
    memory = c.CDLL(None)
    memory.calloc.argtypes, memory.calloc.restype = [c.c_size_t, c.c_size_t], c.c_void_p
    memory.free.argtypes, memory.free.restype = [c.c_void_p], None
    pam.memory = memory
    state = {'ended': []}
    actual = c.create_string_buffer(b'fake-owner')

    def start(service, user, conversation, output):
        assert service == b'flower-mcp'
        state['conversation'] = c.cast(conversation, c.POINTER(linux._Conversation)).contents.function
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.c_void_p(42)
        return 0

    def authenticate(handle, flags):
        assert flags == linux.PAM_DISALLOW_NULL_AUTHTOK
        for _ in range(prompts):
            message = linux._Message(1, b'Password:')
            messages = (c.POINTER(linux._Message) * 1)(c.pointer(message))
            responses = c.POINTER(linux._Response)()
            result = state['conversation'](1, messages, c.byref(responses), None)
            if result:
                return result
            assert c.string_at(responses[0].response) == b'not-real'
            memory.free(responses[0].response)
            memory.free(c.cast(responses, c.c_void_p))
        return authentication

    def item(handle, kind, output):
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.cast(actual, c.c_void_p)
        return 0

    def end(handle, status):
        state['ended'].append(status)
        return ending

    pam.lib = SimpleNamespace(pam_start=start, pam_authenticate=authenticate,
        pam_acct_mgmt=lambda *_: account, pam_get_item=item, pam_end=end)
    return pam, state


@pytest.mark.parametrize('authentication,account,prompts,ending,outcome', [
    (0, 0, 1, 0, 'verified'), (7, 0, 1, 0, 'denied'), (0, 13, 1, 0, 'denied'),
    (0, 0, 2, 0, 'unsupported'), (0, 0, 0, 0, 'unavailable'), (0, 0, 1, 4, 'unavailable'),
])
def test_linux_pam_conversation_account_policy_and_cleanup(authentication, account, prompts, ending, outcome):
    pam, state = _fake_pam(authentication=authentication, account=account, prompts=prompts, ending=ending)
    if outcome == 'verified':
        assert pam.authenticate('fake-owner', 'not-real') == 'fake-owner'
    else:
        with pytest.raises(native.NativeAuthFailure) as error:
            pam.authenticate('fake-owner', 'not-real')
        assert error.value.outcome == outcome
    assert len(state['ended']) == 1


def test_mac_native_algorithm_rechecks_record_identity_and_releases_on_failure(monkeypatch):
    events = []

    class FakeOD:
        def __enter__(self): return self
        def __exit__(self, *_): events.append('released')
        def node(self): return 1
        def record(self, *_): return 2
        def identity(self, *_): return ('501', 'first' if 'password' not in events else 'changed')
        def allowed(self, *_): events.append('allowed')
        def password(self, *_): events.append('password')

    monkeypatch.setattr(macos, '_OD', FakeOD)
    with pytest.raises(native.NativeAuthFailure) as error:
        macos.verify(OWNER, 'fake-owner', 'not-real')
    assert error.value.reason == 'owner_mismatch'
    assert events == ['allowed', 'password', 'released']


def test_mac_owned_objects_and_errors_are_released():
    native_od = object.__new__(macos._OD)
    released = []
    native_od.objects = [10, 11]
    native_od.cf = SimpleNamespace(CFRelease=lambda value: released.append(value.value if hasattr(value, 'value') else value), CFErrorGetCode=lambda _: 5301)
    assert native_od._error(c.c_void_p(12)) == 5301
    native_od.__exit__(None, None, None)
    assert released == [12, 11, 10]


def test_windows_local_info24_false_ignores_unusable_other_fields():
    api = object.__new__(windows._Windows)
    first = windows._User23('fake-owner', None, None, 0, 123)
    second = windows._User24(0, 0xFFFFFFFF, None, None, None)
    calls, freed = [], []

    def get_info(server, username, level, output):
        assert server is None
        calls.append(level)
        value = first if level == 23 else second
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.cast(c.pointer(value), c.c_void_p)
        return 0

    api.net = SimpleNamespace(NetUserGetInfo=get_info, NetApiBufferFree=lambda pointer: freed.append(pointer.value) or 0)
    api.require_local_sam = lambda: None
    api.sid = lambda value: SID
    assert api.local_user('fake-owner')['sid'] == SID
    assert calls == [23, 24] and len(freed) == 2
    second.internet_identity = 1
    with pytest.raises(native.NativeAuthFailure) as error:
        api.local_user('fake-owner')
    assert error.value.outcome == 'unsupported' and len(freed) == 4


@pytest.mark.parametrize('role,outcome', [(0, 'ready'), (1, 'ready'), (2, 'ready'), (3, 'ready'),
                                         (4, 'unsupported'), (5, 'unsupported'), (99, 'unavailable')])
def test_windows_local_sam_gate_refuses_domain_controllers_before_lookup(role, outcome):
    api = object.__new__(windows._Windows)
    value = c.c_int32(role)
    freed = []

    def role_info(server, level, output):
        assert server is None and level == 1
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.cast(c.pointer(value), c.c_void_p)
        return 0

    api.net = SimpleNamespace(DsRoleGetPrimaryDomainInformation=role_info,
                             DsRoleFreeMemory=lambda pointer: freed.append(pointer.value))
    if outcome == 'ready':
        api.require_local_sam()
    else:
        with pytest.raises(native.NativeAuthFailure) as error:
            api.local_user('fake-owner')
        assert error.value.outcome == outcome
    assert len(freed) == 1


def test_windows_elevated_execution_is_rejected_before_identity_and_handle_closed():
    api = object.__new__(windows._Windows)
    closed = []

    def opened(process, access, output):
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.c_void_p(42)
        return 1

    def information(token, kind, output, size, needed):
        assert kind == 20
        c.cast(output, c.POINTER(windows._DWORD))[0] = windows._DWORD(1)
        return 1

    api.kernel = SimpleNamespace(GetCurrentProcess=lambda: 1, CloseHandle=lambda handle: closed.append(handle.value) or 1)
    api.security = SimpleNamespace(OpenProcessToken=opened, GetTokenInformation=information)
    with pytest.raises(native.NativeAuthFailure) as error:
        api.current_identity()
    assert error.value.reason == 'execution_identity_unsupported'
    assert closed == [42]


def test_windows_authentication_uses_local_network_logon_and_clears_secret(monkeypatch):
    api = object.__new__(windows._Windows)
    seen, released, closed = {}, [], []

    def converted(value, output):
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.c_void_p(100 if not seen else 101)
        return 1

    def logon(user, domain, secret, kind, provider, output):
        assert (user, domain, kind, provider) == ('fake-owner', '.', 3, 0)
        seen['secret'] = c.cast(secret, c.c_void_p).value
        seen['size'] = len('not-real'.encode('utf-16-le')) + 2
        assert c.string_at(seen['secret'], seen['size']) == 'not-real'.encode('utf-16-le') + b'\0\0'
        c.cast(output, c.POINTER(c.c_void_p))[0] = c.c_void_p(42)
        return 1

    api.security = SimpleNamespace(ConvertStringSidToSidW=converted, LogonUserW=logon, EqualSid=lambda *_: 1)
    def close(handle):
        assert c.string_at(seen['secret'], seen['size']) == bytes(seen['size'])
        closed.append(handle.value)
        return 1

    api.kernel = SimpleNamespace(LocalFree=lambda pointer: released.append(pointer.value) or None,
                                 CloseHandle=close)
    api.token_sid = lambda token: SID
    assert api.authenticate('fake-owner', 'not-real', SID) == SID
    assert len(released) == 2 and closed == [42]
