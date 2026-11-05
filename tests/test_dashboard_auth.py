"""Browser authority and worker resource boundaries; never OS password acceptance."""
from pathlib import Path
import os
import subprocess
import sys
from threading import Event, Thread
import time

import pytest

from flow_of_work_mcp import dashboard_auth as module
from flow_of_work_mcp.dashboard_auth import DashboardAuth, DashboardAuthError, NativeWorker, OwnerBinding


class Binding:
    owner = {'kind': 'uid', 'value': '12345'}

    def __init__(self):
        self.changed = False

    def check(self):
        if self.changed:
            raise ValueError('private path must never escape')


class Verifier:
    def __init__(self):
        self.calls = 0
        self.capability_calls = 0
        self.outcome = 'verified'
        self.entered = self.release = None

    def capability(self, owner):
        self.capability_calls += 1
        return {'availability': 'ready', 'reason': None}

    def __call__(self, owner, username, password):
        self.calls += 1
        if self.entered:
            self.entered.set()
            assert self.release.wait(3)
        return {'outcome': self.outcome, 'identity': {**owner, 'local': True}
                if self.outcome == 'verified' else None,
                'reason': None if self.outcome == 'verified' else 'credentials_denied'}


def authority(tmp_path, *, port=18760):
    binding, verifier, now = Binding(), Verifier(), [100.0]
    auth = DashboardAuth(tmp_path/'config.yaml', tmp_path/'ledger.sqlite3', port=port,
                         binding=binding, verifier=verifier, clock=lambda: now[0])
    return auth, binding, verifier, now


def login(auth, cookie=None):
    csrf = auth.inspect(cookie)['csrf_token']
    return auth.login(cookie, csrf, 'test-owner', 'synthetic-only-never-an-OS-password')


def test_private_authority_requires_real_verifier_result_and_owner_binding(tmp_path):
    auth, binding, verifier, _ = authority(tmp_path)
    assert not auth.inspect()['authenticated']
    with pytest.raises(DashboardAuthError, match='session_required'):
        auth.authorize(None)
    token, result = login(auth)
    assert auth.authorize(token) == result['csrf_token']
    binding.changed = True
    with pytest.raises(DashboardAuthError, match='owner_changed'):
        auth.authorize(token)
    assert not auth.inspect(token)['authenticated']


def test_denied_and_foreign_identity_never_issue_session(tmp_path):
    auth, _, verifier, _ = authority(tmp_path)
    verifier.outcome = 'denied'
    with pytest.raises(DashboardAuthError, match='login_denied'):
        login(auth)
    verifier.outcome = 'unsupported'
    with pytest.raises(DashboardAuthError, match='auth_unavailable'):
        login(auth)
    assert not auth.inspect()['authenticated']


def test_session_cookie_names_and_logout_are_instance_specific(tmp_path):
    first, _, _, _ = authority(tmp_path, port=18760)
    second, _, _, _ = authority(tmp_path, port=18761)
    assert first.cookie_name != second.cookie_name
    one, a = login(first)
    two, b = login(second)
    with pytest.raises(DashboardAuthError):
        second.authorize(one)
    first.logout(one, a['csrf_token'])
    assert second.authorize(two) == b['csrf_token']
    assert not first.inspect(one)['authenticated']


def test_time_does_not_expire_browser_access_but_restart_and_logout_revoke_it(tmp_path):
    auth, _, _, now = authority(tmp_path)
    token, result = login(auth)
    now[0] += 365 * 86400
    assert auth.authorize(token) == result['csrf_token']
    restarted, _, _, _ = authority(tmp_path)
    assert not restarted.inspect(token)['authenticated']
    auth.logout(token, result['csrf_token'])
    with pytest.raises(DashboardAuthError):
        auth.authorize(token)


def test_failed_csrf_and_empty_password_do_not_reach_native_verification(tmp_path):
    auth, _, verifier, _ = authority(tmp_path)
    with pytest.raises(DashboardAuthError, match='csrf_invalid'):
        auth.login(None, 'wrong', 'owner', 'synthetic')
    with pytest.raises(DashboardAuthError, match='login_denied'):
        auth.login(None, auth.inspect()['csrf_token'], 'owner', '')
    assert verifier.calls == 0


def test_attempt_budget_and_capability_cache_are_bounded(tmp_path):
    auth, _, verifier, now = authority(tmp_path)
    for _ in range(5):
        login(auth)
    assert verifier.capability_calls == 1
    with pytest.raises(DashboardAuthError, match='rate_limited'):
        login(auth)
    assert verifier.calls == 5
    now[0] += 61
    login(auth)
    assert verifier.calls == 6


def test_logout_prevents_late_login_result_from_restoring_revoked_browser(tmp_path):
    auth, _, verifier, _ = authority(tmp_path)
    token, result = login(auth)
    verifier.entered, verifier.release = Event(), Event()
    errors = []

    def pending():
        try:
            auth.login(token, result['csrf_token'], 'owner', 'synthetic')
        except DashboardAuthError as exc:
            errors.append(exc.reason)

    thread = Thread(target=pending)
    thread.start()
    assert verifier.entered.wait(2)
    with pytest.raises(DashboardAuthError, match='auth_busy'):
        auth.login(token, result['csrf_token'], 'owner', 'synthetic')
    auth.logout(token, result['csrf_token'])
    verifier.release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert errors == ['dashboard_session_changed']
    assert not auth.inspect(token)['authenticated']


def test_logout_during_delete_password_verification_invalidates_the_result(tmp_path):
    auth, _, verifier, _ = authority(tmp_path)
    token, result = login(auth)
    csrf = result['csrf_token']
    verifier.entered, verifier.release = Event(), Event()
    errors = []

    def pending():
        try:
            auth.confirm_password(token, csrf, 'synthetic-only')
        except DashboardAuthError as exc:
            errors.append(exc.reason)

    thread = Thread(target=pending)
    thread.start()
    try:
        assert verifier.entered.wait(2)
        auth.logout(token, csrf)
    finally:
        verifier.release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert errors == ['dashboard_session_changed']


def test_capacity_revokes_oldest_session_explicitly(tmp_path):
    auth, _, _, now = authority(tmp_path)
    first = None
    for index in range(33):
        now[0] += 61
        token, result = login(auth)
        if index == 0:
            first = token
        assert result['evicted_session'] is (index == 32)
    assert not auth.inspect(first)['authenticated']
    assert auth.inspect(token)['authenticated']


def test_logout_with_rotated_cookie_revokes_late_set_cookie_for_that_browser_only(tmp_path):
    auth, _, _, _ = authority(tmp_path)
    old, before = login(auth)
    other, independent = login(auth)
    rotated, after = auth.login(old, before['csrf_token'], 'owner', 'synthetic')
    auth.logout(old, before['csrf_token'])
    assert not auth.inspect(rotated)['authenticated']
    assert not auth.inspect(old)['authenticated']
    assert auth.authorize(other) == independent['csrf_token']


@pytest.mark.skipif(os.name == 'nt', reason='POSIX nonblocking FIFO replacement')
def test_fifo_replacement_during_owner_open_is_rejected_without_blocking(tmp_path, monkeypatch):
    path = tmp_path.resolve()/'config.yaml'
    path.write_text('owned')
    real_open = os.open

    def replaced(name, flags, *args, **kwargs):
        path.unlink()
        os.mkfifo(path)
        assert flags & os.O_NONBLOCK
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, 'open', replaced)
    with pytest.raises(DashboardAuthError):
        module._resource(path)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX owner inode and nofollow mechanics')
def test_owner_binding_ignores_data_writes_but_rejects_replacement_and_symlinks(tmp_path):
    tmp_path = tmp_path.resolve()
    config, ledger = tmp_path/'config.yaml', tmp_path/'ledger.sqlite3'
    config.write_text('test'); ledger.write_text('test')
    binding = OwnerBinding(config, ledger)
    ledger.write_text('ordinary mutable ledger content')
    binding.check()
    replacement = tmp_path/'replacement.sqlite3'
    replacement.write_text('replacement'); replacement.replace(ledger)
    with pytest.raises(DashboardAuthError):
        binding.check()
    link = tmp_path/'link.yaml'; link.symlink_to(config)
    with pytest.raises(DashboardAuthError):
        OwnerBinding(link, ledger)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX inherited pipe descendant cleanup')
def test_native_worker_deadline_cleans_inherited_pipe_without_blocking_close(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    child = ("import subprocess,sys;sys.stdin.buffer.read();"
             "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],close_fds=False)")
    monkeypatch.setattr(module, 'NATIVE_TIMEOUT', .2)

    def spawn(command, **kwargs):
        assert 'SYNTHETIC_SECRET' not in repr(command)
        assert 'SYNTHETIC_SECRET' not in repr(kwargs['env'])
        return real_popen([sys.executable, '-c', child], **kwargs)

    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    worker = NativeWorker()
    start = time.monotonic()
    with pytest.raises(DashboardAuthError, match='auth_unavailable'):
        worker({'kind': 'uid', 'value': '12345'}, 'owner', 'SYNTHETIC_SECRET')
    assert time.monotonic() - start < 3
    assert worker._process is None
    worker.close()


def test_thread_start_failure_still_terminates_the_owned_native_worker(monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def spawn(command, **kwargs):
        child = real_popen([sys.executable, '-c', 'import time;time.sleep(60)'], **kwargs)
        children.append(child)
        return child

    def fail_start(self):
        raise RuntimeError('thread resources unavailable')

    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    monkeypatch.setattr(module.Thread, 'start', fail_start)
    worker = NativeWorker()
    with pytest.raises(DashboardAuthError, match='auth_unavailable'):
        worker.capability({'kind': 'uid', 'value': '12345'})
    assert children and children[0].poll() is not None
    assert worker._process is None
