"""Owner-bound browser authority; native passwords never enter the lifecycle ledger."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
from threading import RLock, Thread
import time

NATIVE_TIMEOUT = 10.0
CLEANUP_TIMEOUT = 2.0


class DashboardAuthError(ValueError):
    def __init__(self, reason: str, status: int = 503):
        super().__init__(reason)
        self.reason, self.status = reason, status


def _native():
    from flow_of_work_mcp import dashboard_auth_native
    return dashboard_auth_native


@dataclass(frozen=True)
class _Resource:
    path: str
    device: int
    inode: int
    owner_kind: str
    owner_value: str


def _resource(path: Path) -> _Resource:
    path = Path(os.path.abspath(path))
    try:
        if path.resolve(strict=True) != path:
            raise DashboardAuthError('dashboard_owner_changed', 403)
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or getattr(before, 'st_file_attributes', 0) & 0x400):
            raise DashboardAuthError('dashboard_owner_changed', 403)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                     | getattr(os, 'O_NONBLOCK', 0))
        try:
            opened = os.fstat(fd)
            owner = _native().file_owner_handle(fd)
            after = path.lstat()
            stamp = lambda value: (value.st_dev, value.st_ino, value.st_uid,
                                    stat.S_IFMT(value.st_mode), value.st_nlink)
            if stamp(before) != stamp(opened) or stamp(opened) != stamp(after):
                raise DashboardAuthError('dashboard_owner_changed', 403)
            if owner['kind'] == 'uid' and owner['value'] != str(opened.st_uid):
                raise DashboardAuthError('dashboard_owner_changed', 403)
            return _Resource(str(path), opened.st_dev, opened.st_ino,
                             owner['kind'], owner['value'])
        finally:
            os.close(fd)
    except DashboardAuthError:
        raise
    except Exception:
        raise DashboardAuthError('dashboard_auth_unavailable') from None


class OwnerBinding:
    def __init__(self, config_path: Path, database_path: Path):
        self.paths = (Path(config_path).absolute(), Path(database_path).absolute())
        self.resources = tuple(_resource(path) for path in self.paths)
        first, second = self.resources
        self.owner = {'kind': first.owner_kind, 'value': first.owner_value}
        if (first.owner_kind, first.owner_value) != (second.owner_kind, second.owner_value):
            raise DashboardAuthError('dashboard_owner_changed', 403)
        if self.owner != _native().current_identity() or self.owner in (
            {'kind': 'uid', 'value': '0'}, {'kind': 'sid', 'value': 'S-1-5-18'},
            {'kind': 'sid', 'value': 'S-1-5-19'}, {'kind': 'sid', 'value': 'S-1-5-20'},
        ):
            raise DashboardAuthError('dashboard_owner_changed', 403)

    def check(self):
        if (tuple(_resource(path) for path in self.paths) != self.resources
                or _native().current_identity() != self.owner):
            raise DashboardAuthError('dashboard_owner_changed', 403)


class NativeWorker:
    """One bounded package-owned scope, including metadata discovery, never argv secrets."""
    def __init__(self):
        self._lock = RLock()
        self._process = self._reader = self._writer = None
        self._closed = False

    @staticmethod
    def _kill_scope(process):
        try:
            if os.name != 'nt':
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass

    def _release_finished(self):
        process = self._process
        if process is None:
            return True
        if process.poll() is None or any(thread is not None and thread.is_alive()
                                        for thread in (self._reader, self._writer)):
            return False
        # A stream is closed only after its owning reader/writer has stopped.
        process.stdout.close()
        process.stdin.close()
        self._process = self._reader = self._writer = None
        return True

    def _settle(self, process, reader, writer):
        if process is None:
            return
        deadline = time.monotonic() + CLEANUP_TIMEOUT
        threads = tuple(thread for thread in (reader, writer)
                        if thread is not None and thread.ident is not None)
        if process.poll() is None or any(thread.is_alive() for thread in threads):
            self._kill_scope(process)
        try:
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        with self._lock:
            # Unsettled scopes retain their slot. Never close a stream while
            # its reader/writer is active, including a partial thread startup.
            self._release_finished()

    def _run(self, request, validate):
        payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
        if len(payload) > 20 * 1024:
            raise DashboardAuthError('dashboard_login_denied', 401)
        deadline = time.monotonic() + NATIVE_TIMEOUT
        output, overflow = bytearray(), []
        process = reader = writer = None
        try:
            with self._lock:
                if self._closed or not self._release_finished():
                    raise DashboardAuthError('dashboard_auth_busy', 429)
                environment = {k: v for k, v in os.environ.items()
                               if k not in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'}}
                process = subprocess.Popen([sys.executable, '-I',
                    str(Path(__file__).with_name('dashboard_auth_worker.py').absolute())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=environment, close_fds=True, start_new_session=os.name != 'nt')
                self._process = process

                def read_reply():
                    try:
                        output.extend(process.stdout.read(8193))
                        if len(output) > 8192:
                            overflow.append(True)
                            self._kill_scope(process)
                    except OSError:
                        overflow.append(True)

                def write_request():
                    try:
                        process.stdin.write(payload)
                        process.stdin.close()
                    except OSError:
                        pass

                reader = self._reader = Thread(target=read_reply, daemon=True)
                writer = self._writer = Thread(target=write_request, daemon=True)
                reader.start()
                writer.start()
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            reader.join(timeout=max(0, deadline - time.monotonic()))
            writer.join(timeout=max(0, deadline - time.monotonic()))
            if process.returncode != 0 or overflow or reader.is_alive() or writer.is_alive():
                raise DashboardAuthError('dashboard_auth_unavailable')
            return validate(json.loads(output.decode('utf-8')))
        except DashboardAuthError:
            raise
        except Exception:
            raise DashboardAuthError('dashboard_auth_unavailable') from None
        finally:
            self._settle(process, reader, writer)

    def __call__(self, owner, username, password):
        native = _native()
        return self._run({'contract': native.CONTRACT, 'platform': native.platform_name(),
            'owner': owner, 'username': username, 'password': password},
            lambda reply: native.validate_reply(reply, owner))

    def capability(self, owner):
        native = _native()
        return self._run({'contract': native.CAPABILITY_CONTRACT,
            'platform': native.platform_name(), 'owner': owner}, native.validate_capability_reply)

    def close(self):
        with self._lock:
            self._closed = True
            process, reader, writer = self._process, self._reader, self._writer
        self._settle(process, reader, writer)


@dataclass(frozen=True)
class _Session:
    csrf: str
    order: int
    browser: str
    username: str


class DashboardAuth:
    def __init__(self, config_path: Path, database_path: Path, *, port: int,
                 binding=None, verifier=None, clock=time.monotonic):
        self._lock = RLock()
        self._clock = clock
        self._sessions = {}
        self._retired = {}
        self._attempts = deque()
        self._active = False
        self._closed = False
        self._epoch = 0
        self._order = 0
        self._prelogin_csrf = secrets.token_urlsafe(32)
        self.instance_id = secrets.token_hex(16)
        self._initial_error = None
        self._capability_cache = None
        self._verifier = verifier if verifier is not None else NativeWorker()
        key = json.dumps([str(Path(config_path).absolute()),
                          str(Path(database_path).absolute()), port], separators=(',', ':'))
        self.cookie_name = 'flower_owner_' + hashlib.sha256(key.encode()).hexdigest()[:24]
        try:
            self._binding = binding if binding is not None else OwnerBinding(config_path, database_path)
        except Exception:
            self._binding = None
            self._initial_error = 'dashboard_auth_unavailable'

    @staticmethod
    def _digest(cookie):
        if not isinstance(cookie, str) or not 1 <= len(cookie) <= 256:
            return None
        return hashlib.sha256(cookie.encode()).hexdigest()

    def _check(self):
        if self._closed or self._binding is None:
            raise DashboardAuthError(self._initial_error or 'dashboard_auth_unavailable')
        try:
            self._binding.check()
        except Exception:
            with self._lock:
                self._sessions.clear()
                self._retired.clear()
                self._epoch += 1
            raise DashboardAuthError('dashboard_owner_changed', 403) from None

    def inspect(self, cookie=None):
        try:
            self._check()
        except DashboardAuthError as exc:
            return {'authenticated': False, 'availability': 'unavailable',
                    'reason': exc.reason, 'csrf_token': self._prelogin_csrf,
                    'instance_id': self.instance_id}
        with self._lock:
            session = self._sessions.get(self._digest(cookie))
            if session:
                return {'authenticated': True, 'availability': 'ready', 'reason': None,
                        'csrf_token': session.csrf, 'instance_id': self.instance_id}
        now = self._clock()
        with self._lock:
            cached = self._capability_cache
        if cached and now < cached[0]:
            availability, reason = cached[1:]
        else:
            try:
                capability = self._verifier.capability(dict(self._binding.owner))
                availability, reason = capability['availability'], capability['reason']
                if (availability not in {'ready', 'unavailable'}
                        or reason is not None and reason not in _native().REASONS):
                    raise ValueError('invalid capability')
            except DashboardAuthError as exc:
                availability, reason = 'unavailable', exc.reason
            except Exception:
                availability, reason = 'unavailable', 'dashboard_auth_unavailable'
            with self._lock:
                ttl = 30 if availability == 'ready' else 2
                self._capability_cache = (self._clock() + ttl, availability, reason)
        return {'authenticated': False, 'availability': availability, 'reason': reason,
                'csrf_token': self._prelogin_csrf, 'instance_id': self.instance_id}

    def authorize(self, cookie):
        self._check()
        with self._lock:
            session = self._sessions.get(self._digest(cookie))
            if session is None:
                raise DashboardAuthError('dashboard_session_required', 401)
            return session.csrf

    def login(self, cookie, csrf, username, password):
        return self._authenticate(cookie, csrf, username, password, confirm=False)

    def confirm_password(self, cookie, csrf, password):
        self._authenticate(cookie, csrf, None, password, confirm=True)

    def _authenticate(self, cookie, csrf, username, password, *, confirm):
        self._check()
        with self._lock:
            old_key = self._digest(cookie)
            prior = self._sessions.get(old_key)
            if confirm:
                if prior is None:
                    raise DashboardAuthError('dashboard_session_required', 401)
                username = prior.username
                if not isinstance(password, str) or not password:
                    raise DashboardAuthError('dashboard_delete_password_required', 400)
            denied = (DashboardAuthError('dashboard_delete_password_denied', 403) if confirm
                      else DashboardAuthError('dashboard_login_denied', 401))
            try:
                _native().validate_credentials(username, password)
            except ValueError:
                raise denied from None
            expected = prior.csrf if prior else self._prelogin_csrf
            if not hmac.compare_digest(csrf, expected):
                raise DashboardAuthError('dashboard_csrf_invalid', 403)
            if self._active:
                raise DashboardAuthError('dashboard_auth_busy', 429)
            now = self._clock()
            while self._attempts and now - self._attempts[0] >= 60:
                self._attempts.popleft()
            if len(self._attempts) >= 5:
                raise DashboardAuthError('dashboard_auth_rate_limited', 429)
            self._attempts.append(now)
            self._active = True
            epoch = self._epoch
        try:
            result = self._verifier(dict(self._binding.owner), username, password)
            if result.get('outcome') == 'denied':
                raise denied
            expected_identity = {**self._binding.owner, 'local': True}
            if (result.get('outcome') != 'verified' or result.get('identity') != expected_identity
                    or result.get('reason') is not None):
                raise DashboardAuthError('dashboard_auth_unavailable')
            self._check()
            with self._lock:
                if self._closed or epoch != self._epoch or prior is not None and self._sessions.get(old_key) is not prior:
                    raise DashboardAuthError('dashboard_session_changed', 401)
                if confirm:
                    return None
                if prior is not None:
                    del self._sessions[old_key]
                    self._retired[old_key] = prior
                    while len(self._retired) > 128:
                        del self._retired[next(iter(self._retired))]
                evicted = len(self._sessions) >= 32
                if evicted:
                    oldest = min(self._sessions, key=lambda key: self._sessions[key].order)
                    del self._sessions[oldest]
                token, session_csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                self._order += 1
                self._sessions[self._digest(token)] = _Session(session_csrf, self._order,
                    prior.browser if prior is not None else secrets.token_hex(16), username)
                return token, {'authenticated': True, 'csrf_token': session_csrf,
                               'evicted_session': evicted}
        except DashboardAuthError:
            raise
        except Exception:
            raise DashboardAuthError('dashboard_auth_unavailable') from None
        finally:
            with self._lock:
                self._active = False

    def logout(self, cookie, csrf):
        self._check()
        with self._lock:
            key = self._digest(cookie)
            session = self._sessions.get(key) or self._retired.get(key)
            if session is None:
                raise DashboardAuthError('dashboard_session_required', 401)
            if not hmac.compare_digest(csrf, session.csrf):
                raise DashboardAuthError('dashboard_csrf_invalid', 403)
            # A prior cookie may arrive after a concurrent successful re-login
            # has rotated it. Revoke that browser lineage, not another browser.
            for store in (self._sessions, self._retired):
                for digest in [digest for digest, value in store.items()
                               if value.browser == session.browser]:
                    del store[digest]

    def close(self):
        with self._lock:
            self._closed = True
            self._epoch += 1
            self._sessions.clear()
            self._retired.clear()
        if isinstance(self._verifier, NativeWorker):
            self._verifier.close()
