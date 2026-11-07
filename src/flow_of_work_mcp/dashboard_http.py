"""Owner dashboard HTTP adapter with separate local and HTTPS ingress."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shutil
import stat
import tempfile
from asyncio import timeout
from contextlib import asynccontextmanager, contextmanager
from copy import copy
from functools import partial
from importlib.resources import files
from pathlib import Path
from threading import Lock

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from flow_of_work_mcp import managed_service_security as secure
from flow_of_work_mcp.dashboard_maintenance import DashboardMaintenance, MaintenanceUnavailable
from flow_of_work_mcp.core.errors import ProjectNotFoundError, RequirementConflictError
from flow_of_work_mcp.core.domain.identifiers import validate_project_id
from flow_of_work_mcp.dashboard_auth import DashboardAuth, DashboardAuthError
from flow_of_work_mcp.dashboard_network import DashboardNetworkError, DashboardNetworkSettings
from flow_of_work_mcp.profile_settings import DashboardSettings, SettingsError
from flow_of_work_mcp.ledger_archive import (
    ArchiveError, MAX_ARCHIVE_BYTES, assert_private_archive_directory, create_archive,
)
from flow_of_work_mcp.ledger_recovery import inspect_or_restore
from flow_of_work_mcp.dashboard_backups import DashboardBackups
from flow_of_work_mcp.managed_service import ServiceError
from flow_of_work_mcp.profiles import ProfileError, profile_config_path, profile_root
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError


_BACKUP_ID = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}')
_CHUNK_SIZE = 1024 * 1024
_RESTORE_UPLOAD_TIMEOUT = 300
_LOG = logging.getLogger(__name__)


def _archive_busy():
    return ArchiveError('dashboard_archive_busy',
        'Another archive operation or its cleanup has not settled. Try again after it completes.', 409)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate dashboard field')
        value[key] = item
    return value


def _invalid_constant(_):
    raise ValueError('invalid JSON constant')


class _ArchiveLifetime:
    """Keep the private workspace and handle until the last worker settles."""

    def __init__(self, gate):
        self.gate = gate
        self.lock = Lock()
        self.running = False
        self.closed = False
        self.directory = None
        self.directory_identity = None
        self.stream = None

    def run(self, operation, *args):
        with self.lock:
            if self.closed or self.running:
                raise RuntimeError('archive worker not available')
            self.running = True
        try:
            return operation(*args)
        finally:
            with self.lock:
                self.running = False
                cleanup = self.closed
            if cleanup:
                self._dispose()

    def temporary_archive(self):
        self.directory = Path(tempfile.mkdtemp(prefix='flower-archive-')).resolve()
        info = self.directory.lstat()
        self.directory_identity = (info.st_dev, info.st_ino)
        if os.name == 'nt':
            secure._windows_protect(self.directory, directory=True)
        secure.ensure_directory(self.directory)
        return self.directory / 'archive.flower.zip'

    def open_upload(self):
        path = self.temporary_archive()
        assert_private_archive_directory(path.parent)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        try:
            self.stream = os.fdopen(descriptor, 'wb')
        except BaseException:
            os.close(descriptor)
            raise
        return path

    def assert_open(self):
        with self.lock:
            if self.closed:
                raise ArchiveError('archive_restore_interrupted', 'The upload was interrupted.')

    def attach(self, stream, *, expected=None):
        self.stream = stream
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
            raise RuntimeError('archive is not a regular nonempty file')
        if expected is not None and (info.st_dev, info.st_ino) != expected:
            raise RuntimeError('archive identity changed before streaming')
        if info.st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError('archive_size_exceeded', 'The archive exceeds the supported size.', 413)
        return info.st_size

    def read(self):
        return self.stream.read(_CHUNK_SIZE)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            cleanup = not self.running
        if cleanup:
            self._dispose()

    def _dispose(self):
        try:
            try:
                if self.stream is not None:
                    self.stream.close()
            finally:
                if self.directory is not None:
                    try:
                        info = self.directory.lstat()
                        if (not stat.S_ISDIR(info.st_mode) or not info.st_ino
                                or (info.st_dev, info.st_ino) != self.directory_identity):
                            raise OSError('archive workspace identity changed')
                        shutil.rmtree(self.directory)
                    except FileNotFoundError:
                        pass
        except OSError:
            # Do not allow repeated downloads to accumulate private residue
            # after an unsettled cleanup. No private path enters the log.
            _LOG.warning('dashboard_archive_cleanup_failed')
        else:
            self.gate.release()


class _ArchiveResponse(Response):
    """Defer all file acquisition until ASGI owns the response lifetime."""

    def __init__(self, adapter, cookie, csrf, *, project_id=None, backup_id=None):
        super().__init__()
        self.adapter, self.cookie, self.csrf = adapter, cookie, csrf
        self.project_id, self.backup_id = project_id, backup_id

    async def __call__(self, scope, receive, send):
        await self.adapter._send_archive(scope, receive, send, self.cookie, self.csrf,
                                         self.project_id, self.backup_id)


class DashboardHTTP:
    def __init__(self, runtime, config_path: Path, *, port: int, host: str = '127.0.0.1',
                 loaded_config_revision: str | None = None, network_active: dict | None = None,
                 network_urls=None):
        from flow_of_work_mcp.application.dashboard import DashboardProjectionService
        from flow_of_work_mcp.managed_upgrade import UpgradeController
        self.projection = DashboardProjectionService(runtime)
        self.requirements = runtime.requirements
        self.maintenance = DashboardMaintenance(runtime, config_path)
        self.host, self.port = host, port
        self._remote_tls = None
        self.auth = DashboardAuth(config_path, runtime.ledger.database_path, port=port)
        self.settings = DashboardSettings(config_path, runtime.ledger.database_path,
                                          loaded_revision=loaded_config_revision)
        self.network = DashboardNetworkSettings(config_path)
        self._network_active = (dict(network_active) if network_active is not None
                                else {'mode': 'local', 'port': None, 'cli_override': False})
        self._network_urls = network_urls
        self.database_path = runtime.ledger.database_path
        self.backups = DashboardBackups(self.database_path)
        self._archive_gate = Lock()
        self.upgrade = UpgradeController(self.maintenance.config_path, self.host, self.port, self.auth.instance_id)

    def local_url(self, host: str) -> str:
        local = '[::1]' if ':' in host else '127.0.0.1'
        return f'http://{local}:{self.port}/dashboard'

    def _allows_https_authority(self, request, authority):
        tls = self._remote_tls
        if getattr(tls, 'bind', None) != '0.0.0.0':
            return authority == tls.authority
        server = request.scope.get('server')
        if server is None:
            return False
        address, port = server
        if port != tls.port or address not in tls.names:
            return False
        suffix = '' if port == 443 else f':{port}'
        return authority == address + suffix or any(
            authority == name + suffix for name in tls.hostnames
        )

    def _security(self, request):
        if self._remote_tls is not None:
            hosts = request.headers.getlist('host')
            origins = request.headers.getlist('origin')
            if (request.scope.get('scheme') != 'https' or len(hosts) != 1 or len(origins) > 1
                    or not self._allows_https_authority(request, hosts[0].lower())):
                return False
            expected = f'https://{hosts[0].lower()}'
            if origins and origins[0] != expected:
                return False
            return request.method != 'POST' or origins == [expected]
        try:
            if request.client is None or not ipaddress.ip_address(request.client.host).is_loopback:
                return False
        except ValueError:
            return False
        host = request.headers.get('host', '').lower()
        hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}', f'[::1]:{self.port}'}
        if self.port == 80:
            hosts.update({'127.0.0.1', 'localhost', '[::1]'})
        if host not in hosts:
            return False
        origin = request.headers.get('origin')
        expected = f'{request.url.scheme}://{host}'
        if origin is not None and origin != expected:
            return False
        return request.method != 'POST' or origin == expected

    def _access_denied(self):
        if self._remote_tls is not None:
            return self._json(status=403, reason='dashboard_remote_access_required',
                              message='Use the configured Flower HTTPS address.')
        return self._json(status=403, reason='dashboard_local_access_required',
                          message='Use the dashboard on its local origin.')

    @staticmethod
    def _headers():
        return {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}

    def _json(self, result=None, *, status=200, reason='', message=''):
        content = {'status': 'success', 'result': result}
        if status >= 400:
            content = {'status': 'blocked' if status < 500 else 'failed', 'reason': reason, 'message': message}
        return JSONResponse(content, status_code=status, headers=self._headers())

    async def static(self, request):
        if not self._security(request):
            return self._access_denied()
        name = request.path_params.get('asset', 'index.html')
        types = {'index.html': 'text/html', 'app.css': 'text/css', 'app.js': 'text/javascript'}
        if name not in types:
            return self._json(status=404, reason='dashboard_resource_not_found', message='The dashboard resource does not exist.')
        data = files('flow_of_work_mcp').joinpath('resources', 'dashboard', name).read_bytes()
        return Response(data, media_type=types[name], headers=self._headers())

    async def _redirect_to_dashboard(self, request):
        if not self._security(request):
            return self._access_denied()
        return RedirectResponse('/dashboard', headers=self._headers())

    async def _body(self, request):
        if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/json':
            raise ValueError('dashboard_json_required')
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 16384:
                raise ValueError('dashboard_body_too_large')
            chunks.append(chunk)
        body = json.loads(b''.join(chunks), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        if not isinstance(body, dict):
            raise ValueError('dashboard_object_required')
        return body

    def _create_project(self, body, cookie, csrf):
        if set(body) != {'project_id', 'name'} or any(not isinstance(value, str) for value in body.values()):
            raise ValueError('dashboard_project_fields_invalid')
        name = body['name'].strip()
        if not name or len(name) > 256 or '\0' in name:
            raise ValueError('dashboard_project_name_invalid')
        name.encode('utf-8')
        with self.maintenance.admission():
            self._reauthorize(cookie, csrf)
            return dict(self.requirements.create_project(body['project_id'], name, actor='dashboard-owner'))

    def _save_settings(self, body, cookie, csrf):
        with self.maintenance.admission():
            self._reauthorize(cookie, csrf)
            return self.settings.save(body)

    def _network_view(self, cookie, csrf, body=None):
        with self.maintenance.admission():
            self.auth.authorize(cookie, csrf, write=body is not None)
            self._assert_runtime_lease()
            saved = (self.network.snapshot() if body is None else
                     self.network.save(body, mcp_host=self.host, mcp_port=self.port))
            active = dict(self._network_active)
            if self._network_urls is not None:
                active['urls'] = list(self._network_urls())
            return {**saved, 'active': active}

    def _reauthorize(self, cookie, csrf):
        self.auth.authorize(cookie, csrf, write=True)

    def _upgrade_status(self, cookie, csrf):
        self._reauthorize(cookie, csrf)
        self._assert_runtime_lease()
        return self.upgrade.status()

    def _upgrade_operation(self, action, body, cookie, csrf):
        expected = {'version'} if action == 'preview' else {'id', 'password'}
        if set(body) != expected or any(not isinstance(value, str) for value in body.values()):
            raise ValueError('upgrade_fields_invalid')
        with self.maintenance.admission():
            self._reauthorize(cookie, csrf)
            self._assert_runtime_lease()
            if action == 'preview':
                return self.upgrade.preview(body['version'])
            password = body.pop('password')
            try:
                self.auth.confirm_password(cookie, csrf, password)
            except DashboardAuthError as exc:
                if exc.reason in {'dashboard_delete_password_required', 'dashboard_delete_password_denied'}:
                    reason = exc.reason.replace('delete_password', 'upgrade_password')
                    raise DashboardAuthError(reason, exc.status) from None
                raise
            finally:
                del password
            self._reauthorize(cookie, csrf)
            self._assert_runtime_lease()
            return self.upgrade.apply(body['id'])

    def _backup_operation(self, operation, cookie, csrf, *, backup_id=None, password=None):
        with self.maintenance.admission():
            self._reauthorize(cookie, csrf)
            self._assert_runtime_lease()
            if operation == 'list':
                return self.backups.list()
            if not self._archive_gate.acquire(blocking=False):
                raise _archive_busy()
            try:
                if operation == 'create':
                    return self.backups.create()
                self.auth.confirm_password(cookie, csrf, password)
                self._reauthorize(cookie, csrf)
                self._assert_runtime_lease()
                return self.backups.delete(backup_id)
            finally:
                self._archive_gate.release()

    def _assert_runtime_lease(self):
        lease = self.maintenance.runtime.runtime_ownership
        if lease is None:
            raise MaintenanceUnavailable('server_maintenance')
        try:
            lease.assert_resource(self.database_path)
        except RuntimeOwnershipError:
            raise MaintenanceUnavailable('server_maintenance') from None

    def _open_archive(self, lifetime, cookie, csrf, project_id, backup_id):
        with self.maintenance.admission():
            self._reauthorize(cookie, csrf)
            self._assert_runtime_lease()
            if backup_id is not None:
                size = lifetime.attach(self.backups.open(backup_id))
            else:
                path = lifetime.temporary_archive()
                create_archive(self.database_path, path, project_id=project_id)
                info = secure._private(path, directory=False)
                flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
                stream = os.fdopen(os.open(path, flags), 'rb')
                size = lifetime.attach(stream, expected=(info.st_dev, info.st_ino))
            self._assert_runtime_lease()
            self._reauthorize(cookie, csrf)
            return size

    async def _send_archive(self, scope, receive, send, cookie, csrf, project_id, backup_id):
        if not self._archive_gate.acquire(blocking=False):
            await self._archive_error(_archive_busy())(scope, receive, send)
            return
        lifetime = _ArchiveLifetime(self._archive_gate)
        try:
            try:
                size = await run_in_threadpool(lifetime.run, self._open_archive, lifetime,
                                               cookie, csrf, project_id, backup_id)
            except DashboardAuthError as exc:
                await self._auth_error(exc)(scope, receive, send)
                return
            except MaintenanceUnavailable as exc:
                await self._maintenance_error(exc)(scope, receive, send)
                return
            except ArchiveError as exc:
                await self._archive_error(exc)(scope, receive, send)
                return
            except Exception:
                await self._json(status=500, reason='dashboard_archive_failed',
                    message='The archive could not be prepared. No download was published.')(scope, receive, send)
                return

            async def chunks():
                remaining = size
                while remaining:
                    block = await run_in_threadpool(lifetime.run, lifetime.read)
                    if not block or len(block) > remaining:
                        raise RuntimeError('archive size changed during download')
                    remaining -= len(block)
                    yield block

            filename = 'flower-backup.flower.zip' if project_id is None else 'flower-project.flower.zip'
            response = StreamingResponse(chunks(), media_type='application/zip', headers={
                **self._headers(), 'Content-Length': str(size),
                'Content-Disposition': f'attachment; filename="{filename}"',
            })
            try:
                await response(scope, receive, send)
            except ClientDisconnect:
                pass
        finally:
            lifetime.close()

    def _restore_destination(self, profile_name):
        config = self.maintenance.config_path
        profiles = config.parent.parent
        managed_root = profiles.parent if config.name == 'flower.yaml' and profiles.name == 'profiles' else None
        try:
            root = profile_root(managed_root)
        except ProfileError as exc:
            raise ArchiveError('archive_workspace_unsafe', 'The server profile root is invalid.', 409) from exc
        try:
            destination = profile_config_path(root, profile_name).parent
        except ProfileError as exc:
            raise ArchiveError('archive_profile_name_invalid', 'Choose a valid new Flower profile name.') from exc
        if os.path.lexists(destination):
            raise ArchiveError('archive_destination_exists', 'A directory already uses this profile name.', 409)
        return destination

    def _restore_archive(self, lifetime, archive, destination, profile_name, cookie, csrf):
        self._reauthorize(cookie, csrf)
        self._assert_runtime_lease()
        secure.ensure_directory(destination.parent, private=False)

        @contextmanager
        def publication_guard():
            with self.maintenance.admission():
                self._reauthorize(cookie, csrf)
                self._assert_runtime_lease()
                lifetime.assert_open()
                yield

        try:
            manifest = inspect_or_restore(archive, restore_dir=destination, publication_guard=publication_guard)
        except ArchiveError as exc:
            if exc.code == 'archive_destination_exists':
                raise ArchiveError(exc.code, str(exc), 409) from exc
            raise
        return {'profile_name': profile_name, 'kind': manifest['kind'], 'project_id': manifest['project_id']}

    async def _receive_restore(self, request, profile_name, cookie, csrf):
        types = request.headers.getlist('content-type')
        if len(types) != 1 or types[0].split(';', 1)[0].strip().lower() != 'application/zip':
            raise ArchiveError('archive_restore_media_type', 'Upload a Flower ZIP archive.', 415)
        lengths = request.headers.getlist('content-length')
        declared_size = None
        if lengths:
            if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,20}', lengths[0]):
                raise ArchiveError('archive_invalid', 'The upload length is invalid.')
            declared_size = int(lengths[0])
            if declared_size > MAX_ARCHIVE_BYTES:
                raise ArchiveError('archive_size_exceeded', 'The archive exceeds the supported size.', 413)
        if not self._archive_gate.acquire(blocking=False):
            raise _archive_busy()
        lifetime = _ArchiveLifetime(self._archive_gate)
        try:
            destination = await run_in_threadpool(self._restore_destination, profile_name)
            archive = await run_in_threadpool(lifetime.run, lifetime.open_upload)
            size = 0
            try:
                async with timeout(_RESTORE_UPLOAD_TIMEOUT):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_ARCHIVE_BYTES:
                            raise ArchiveError('archive_size_exceeded', 'The archive exceeds the supported size.', 413)
                        if chunk:
                            await run_in_threadpool(lifetime.run, lifetime.stream.write, chunk)
            except TimeoutError as exc:
                raise ArchiveError('archive_restore_timeout', 'The archive upload took too long.', 408) from exc
            if not size or (declared_size is not None and declared_size != size):
                raise ArchiveError('archive_invalid', 'The upload is empty or incomplete.')
            await run_in_threadpool(lifetime.run, lifetime.stream.close)
            return await run_in_threadpool(lifetime.run, self._restore_archive,
                                            lifetime, archive, destination, profile_name, cookie, csrf)
        except ClientDisconnect as exc:
            raise ArchiveError('archive_restore_interrupted', 'The upload was interrupted.') from exc
        except secure.ServiceSecurityError as exc:
            raise ArchiveError('archive_workspace_unsafe', 'The server cannot stage or restore the archive safely.', 409) from exc
        except OSError as exc:
            raise ArchiveError('archive_io_failure', 'The server could not stage the archive or write the new profile.', 500) from exc
        finally:
            lifetime.close()

    async def api(self, request):
        if not self._security(request):
            return self._access_denied()
        path = request.path_params['path'].strip('/').split('/')
        try:
            cookie = request.cookies.get(self.auth.cookie_name)
            submitted_csrf = request.headers.get('x-flower-csrf', '')
            if path == ['auth'] and request.method == 'GET':
                return self._json(await run_in_threadpool(self.auth.inspect, cookie, submitted_csrf))
            if path == ['login'] and request.method == 'POST':
                body = await self._body(request)
                if set(body) != {'username', 'password'}:
                    raise ValueError('login_fields')
                token, result = await run_in_threadpool(self.auth.login, cookie, submitted_csrf,
                                                        body['username'], body['password'])
                response = self._json(result)
                response.set_cookie(self.auth.cookie_name, token, httponly=True,
                    samesite='strict', path='/dashboard', secure=request.url.scheme == 'https')
                return response
            if path == ['logout'] and request.method == 'POST':
                if await self._body(request) != {}:
                    raise ValueError('logout_fields')
                await run_in_threadpool(self.auth.logout, cookie, submitted_csrf)
                response = self._json({'authenticated': False})
                response.delete_cookie(self.auth.cookie_name, path='/dashboard',
                    httponly=True, samesite='strict', secure=request.url.scheme == 'https')
                return response
            network_route = path == ['network']
            read_route = (path in (['status'], ['projects'], ['settings'], ['backups'], ['upgrade']) or network_route
                or len(path) == 4 and path[0] == 'projects' and path[2] == 'sections'
                or len(path) == 5 and path[0] == 'projects' and path[2] == 'evidence')
            admin_route = len(path) == 4 and path[0] == 'projects' and path[2:] == ['deletion', 'delete']
            create_route = path == ['projects']
            settings_route = path == ['settings', 'draft']
            upgrade_action = path in (['upgrade', 'preview'], ['upgrade', 'apply'])
            archive_route = path == ['archive']
            restore_route = len(path) == 2 and path[0] == 'restore'
            backups_route = path == ['backups']
            backup_action = (len(path) == 3 and path[0] == 'backups'
                             and path[2] in ('download', 'delete'))
            if not (request.method == 'GET' and read_route
                    or request.method == 'POST' and (admin_route or create_route or settings_route or upgrade_action
                                                      or archive_route or restore_route or backups_route or backup_action or network_route)):
                return self._json(status=404, reason='dashboard_route_not_found', message='Unknown dashboard route.')
            csrf = await run_in_threadpool(self.auth.authorize, cookie, submitted_csrf,
                                           write=request.method == 'POST')
            if request.method == 'POST':
                if restore_route:
                    result = await self._receive_restore(request, path[1], cookie, submitted_csrf)
                    return self._json(result, status=201)
                body = await self._body(request)
                if create_route:
                    try:
                        project = await run_in_threadpool(self._create_project, body, cookie, submitted_csrf)
                    except RequirementConflictError:
                        return self._json(status=409, reason='dashboard_project_conflict',
                            message='A project already uses this identifier. Open it from the catalog or choose another identifier.')
                    return self._json(project, status=201)
                if settings_route:
                    result = await run_in_threadpool(self._save_settings, body, cookie, submitted_csrf)
                    return self._json(result)
                if network_route:
                    return self._json(await run_in_threadpool(self._network_view, cookie, csrf, body))
                if upgrade_action:
                    result = await run_in_threadpool(self._upgrade_operation, path[1], body, cookie, submitted_csrf)
                    return self._json(result, status=202 if path[1] == 'apply' else 200)
                if archive_route:
                    if set(body) != {'project_id'} or (
                        body['project_id'] is not None and not isinstance(body['project_id'], str)
                    ):
                        raise ValueError('archive_fields_invalid')
                    project_id = body['project_id']
                    if project_id is not None:
                        project_id = validate_project_id(project_id)
                    return _ArchiveResponse(self, cookie, submitted_csrf, project_id=project_id)
                if backups_route:
                    if body:
                        raise ValueError('backup_fields_invalid')
                    result = await run_in_threadpool(self._backup_operation, 'create', cookie, submitted_csrf)
                    return self._json(result, status=201)
                if backup_action:
                    if not _BACKUP_ID.fullmatch(path[1]):
                        raise ValueError('backup_id_invalid')
                    if path[2] == 'download':
                        if body:
                            raise ValueError('backup_fields_invalid')
                        return _ArchiveResponse(self, cookie, submitted_csrf, backup_id=path[1])
                    if set(body) != {'password'} or not isinstance(body['password'], str):
                        raise ValueError('backup_fields_invalid')
                    result = await run_in_threadpool(self._backup_operation, 'delete', cookie, submitted_csrf,
                                                     backup_id=path[1], password=body['password'])
                    return self._json(result)
                authorize_delete = partial(self.auth.confirm_password, cookie, submitted_csrf,
                                           body.pop('password', None))
                result = await run_in_threadpool(self.maintenance.operate, path[1], path[3], body,
                                                 authorize_delete=authorize_delete,
                                                 recheck_session=partial(self._reauthorize, cookie, submitted_csrf))
                return self._json(result)
            if path == ['status']:
                return self._json({**self.maintenance.status(), 'csrf_token': csrf})
            if path == ['settings']:
                return self._json(await run_in_threadpool(self.maintenance.read, self.settings.snapshot))
            if network_route:
                return self._json(await run_in_threadpool(self._network_view, cookie, csrf))
            if path == ['upgrade']:
                return self._json(await run_in_threadpool(self._upgrade_status, cookie, csrf))
            if backups_route:
                return self._json(await run_in_threadpool(self._backup_operation, 'list', cookie, csrf))
            offset = int(request.query_params.get('offset', '0'))
            limit = int(request.query_params.get('limit', '25'))
            if path == ['projects']:
                result = await run_in_threadpool(self.maintenance.read, self.projection.projects,
                    search=request.query_params.get('search', ''), offset=offset, limit=limit)
            elif len(path) == 4 and path[0] == 'projects' and path[2] == 'sections':
                result = await run_in_threadpool(self.maintenance.read, self.projection.project,
                    path[1], path[3], offset=offset, limit=limit,
                    channel=request.query_params.get('channel', 'campaign'),
                    scope_id=request.query_params.get('scope_id', ''))
            elif len(path) == 5 and path[0] == 'projects' and path[2] == 'evidence':
                result = await run_in_threadpool(self.maintenance.read, self.projection.evidence, path[1], path[3], path[4])
            else:
                return self._json(status=404, reason='dashboard_route_not_found', message='Unknown dashboard page.')
            return self._json(result)
        except DashboardAuthError as exc:
            return self._auth_error(exc)
        except (SettingsError, DashboardNetworkError) as exc:
            return self._json(status=exc.status, reason=exc.code, message=str(exc))
        except ArchiveError as exc:
            return self._archive_error(exc)
        except ServiceError as exc:
            return self._json(status=409, reason=exc.code, message=str(exc))
        except MaintenanceUnavailable as exc:
            return self._maintenance_error(exc)
        except ProjectNotFoundError:
            return self._json(status=404, reason='dashboard_project_not_found', message='The selected project is no longer available. Return to the project list and refresh it.')
        except ValueError as exc:
            # Render only the fixed adapter/application size rejection, never arbitrary exception text.
            if exc.args == ('dashboard evidence exceeds the 2 MiB read limit',):
                return self._json(status=413, reason='dashboard_evidence_too_large', message='The retained document exceeds the 2 MiB browser limit. Retrieve it through the existing Flower artifact workflow.')
            return self._json(status=400, reason='dashboard_input_invalid', message='Inspect the selected project, bounds and required action fields.')
        except (TypeError, KeyError):
            return self._json(status=400, reason='dashboard_input_invalid', message='Inspect the selected project, bounds and required action fields.')
        except Exception:
            if path[0] == 'restore':
                return self._json(status=500, reason='archive_io_failure',
                    message='The restore outcome could not be confirmed. Inspect the new profile before retrying.')
            if path == ['projects'] and request.method == 'POST':
                return self._json(status=500, reason='dashboard_operation_failed',
                    message='Project creation could not be confirmed. Inspect the chosen identifier in the catalog before another attempt.')
            if path[0] == 'backups':
                return self._json(status=500, reason='dashboard_backup_failed',
                    message='The retained backup operation could not be confirmed. Inspect the backup list before retrying.')
            if path[0] == 'upgrade':
                return self._json(status=500, reason='dashboard_upgrade_uncertain',
                    message='The upgrade outcome could not be confirmed. Inspect the upgrade receipt before retrying.')
            if len(path) == 4 and path[0] == 'projects' and path[2:] == ['deletion', 'delete']:
                return self._json(status=500, reason='dashboard_operation_failed',
                    message='The deletion outcome could not be confirmed. Refresh the project list before trying again.')
            return self._json(status=500, reason='dashboard_operation_failed', message='The request could not complete.')

    def _auth_error(self, exc):
        messages = {
            'dashboard_delete_password_required': 'Enter the local owner password to confirm deletion.',
            'dashboard_delete_password_denied': 'The local owner password was not accepted.',
            'dashboard_upgrade_password_required': 'Enter the local owner password to confirm the upgrade.',
            'dashboard_upgrade_password_denied': 'The local owner password was not accepted.',
            'dashboard_login_denied': 'The local owner credentials were not accepted.',
            'dashboard_session_required': 'Sign in with the local account that owns the Flower data.',
            'dashboard_session_changed': 'The browser session changed. Sign in again without replaying an uncertain action.',
            'dashboard_owner_changed': 'The selected data owner changed or cannot be validated. Inspect the local configuration.',
            'dashboard_csrf_invalid': 'Refresh the browser request state before trying again.',
            'dashboard_auth_busy': 'Another native verification is active. Try again shortly.',
            'dashboard_auth_rate_limited': 'Too many verification attempts. Wait before trying again.',
            'dashboard_auth_unavailable': 'Native local-account verification is unavailable. Inspect the platform prerequisites.',
        }
        response = self._json(status=exc.status, reason=exc.reason,
                              message=messages.get(exc.reason, messages['dashboard_auth_unavailable']))
        if exc.status == 429:
            response.headers['Retry-After'] = '60' if exc.reason == 'dashboard_auth_rate_limited' else '2'
        return response

    def _maintenance_error(self, exc):
        return self._json(status=503, reason=str(exc), message='Flower is in maintenance or still has active work. Inspect status and retry after service resumes.')

    def _archive_error(self, exc):
        return self._json(status=getattr(exc, 'status', None) or 409, reason=exc.code, message=str(exc))

    def remote_dashboard_app(self, tls):
        # The two listeners share all runtime mutation gates. Authentication
        # and its cookie remain separate for each ingress.
        remote = copy(self)
        remote._remote_tls = tls
        remote.auth = DashboardAuth(self.maintenance.config_path, self.database_path, port=tls.port)
        remote.auth.cookie_name += '_https'

        @asynccontextmanager
        async def lifespan(app):
            try:
                yield
            finally:
                remote.close()

        app = Starlette(routes=[
            Route('/', remote._redirect_to_dashboard, methods=['GET']),
            Route('/dashboard', remote.static, methods=['GET']),
            Route('/dashboard/', remote.static, methods=['GET']),
            Route('/dashboard/assets/{asset}', remote.static, methods=['GET']),
            Route('/dashboard/api/{path:path}', remote.api, methods=['GET', 'POST']),
        ], lifespan=lifespan)
        app.router.redirect_slashes = False
        return app

    def mount(self, mcp):
        mcp.custom_route('/dashboard', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/assets/{asset}', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/api/{path:path}', methods=['GET', 'POST'])(self.api)

    def close(self):
        self.auth.close()
