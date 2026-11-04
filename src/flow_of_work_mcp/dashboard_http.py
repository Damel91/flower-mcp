"""Same-instance local browser adapter, independent of MCP transport security."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from importlib.resources import files
from pathlib import Path
import secrets
from threading import Lock
import time

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from flow_of_work_mcp.dashboard_maintenance import DashboardMaintenance, MaintenanceUnavailable
from flow_of_work_mcp.core.errors import ProjectNotFoundError


class DashboardHTTP:
    def __init__(self, runtime, config_path: Path, *, port: int):
        from flow_of_work_mcp.application.dashboard import DashboardProjectionService
        self.projection = DashboardProjectionService(runtime)
        self.maintenance = DashboardMaintenance(runtime, config_path)
        self.port = port
        self._lock = Lock()
        self._activation = secrets.token_urlsafe(32)
        self._activation_until = time.monotonic() + 600
        self._session = ''
        self._csrf = ''
        self._session_until = 0.0
        identity = str(runtime.ledger.database_path) + ':' + str(port)
        self._cookie = 'flower_dashboard_' + hashlib.sha256(identity.encode()).hexdigest()[:12]

    def activation_url(self, host: str) -> str:
        local = '[::1]' if ':' in host else '127.0.0.1'
        return f'http://{local}:{self.port}/dashboard#connect={self._activation}'

    def _security(self, request):
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

    def _authenticated(self, request):
        with self._lock:
            return bool(self._session and time.monotonic() < self._session_until
                        and hmac.compare_digest(request.cookies.get(self._cookie, ''), self._session))

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
            return self._json(status=403, reason='dashboard_local_access_required', message='Dashboard access is restricted to the local computer and origin.')
        name = request.path_params.get('asset', 'index.html')
        types = {'index.html': 'text/html', 'app.css': 'text/css', 'app.js': 'text/javascript'}
        if name not in types:
            return self._json(status=404, reason='dashboard_resource_not_found', message='The dashboard resource does not exist.')
        data = files('flow_of_work_mcp').joinpath('resources', 'dashboard', name).read_bytes()
        return Response(data, media_type=types[name], headers=self._headers())

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
        body = json.loads(b''.join(chunks))
        if not isinstance(body, dict):
            raise ValueError('dashboard_object_required')
        return body

    async def api(self, request):
        if not self._security(request):
            return self._json(status=403, reason='dashboard_local_access_required', message='Use the dashboard on its local origin.')
        path = request.path_params['path'].strip('/').split('/')
        try:
            authenticated = self._authenticated(request)
            if path == ['session']:
                if request.method == 'GET':
                    result = {'authenticated': authenticated}
                    if authenticated:
                        result.update(csrf_token=self._csrf, maintenance=self.maintenance.status())
                    return self._json(result)
                body = await self._body(request)
                if set(body) != {'token'} or not isinstance(body['token'], str):
                    raise ValueError('dashboard_activation_invalid')
                with self._lock:
                    if not self._activation or time.monotonic() >= self._activation_until or not hmac.compare_digest(body['token'], self._activation):
                        return self._json(status=401, reason='dashboard_activation_expired', message='The link was consumed or expired. Reopen your active browser session, or restart Flower for a new local link.')
                    self._activation = ''
                    self._session = secrets.token_urlsafe(32)
                    self._csrf = secrets.token_urlsafe(32)
                    self._session_until = time.monotonic() + 86400
                    session, csrf = self._session, self._csrf
                response = self._json({'authenticated': True, 'csrf_token': csrf, 'maintenance': self.maintenance.status()})
                response.set_cookie(self._cookie, session, httponly=True, samesite='strict', path='/dashboard', max_age=86400)
                return response
            if not authenticated:
                return self._json(status=401, reason='dashboard_session_required', message='Open the local dashboard activation link printed by Flower.')
            if request.method == 'POST':
                if not hmac.compare_digest(request.headers.get('x-flower-csrf', ''), self._csrf):
                    return self._json(status=403, reason='dashboard_csrf_invalid', message='Refresh your operator session before continuing.')
                body = await self._body(request)
                if len(path) == 4 and path[0] == 'projects' and path[2] == 'deletion':
                    result = await run_in_threadpool(self.maintenance.operate, path[1], path[3], body)
                    return self._json(result)
                return self._json(status=404, reason='dashboard_route_not_found', message='Unknown dashboard action.')
            if path == ['status']:
                return self._json(self.maintenance.status())
            offset = int(request.query_params.get('offset', '0'))
            limit = int(request.query_params.get('limit', '25'))
            if path == ['projects']:
                result = await run_in_threadpool(self.maintenance.read, self.projection.projects,
                    search=request.query_params.get('search', ''), offset=offset, limit=limit)
            elif len(path) == 4 and path[0] == 'projects' and path[2] == 'sections':
                result = await run_in_threadpool(self.maintenance.read, self.projection.project,
                    path[1], path[3], offset=offset, limit=limit)
            elif len(path) == 5 and path[0] == 'projects' and path[2] == 'evidence':
                result = await run_in_threadpool(self.maintenance.read, self.projection.evidence, path[1], path[3], path[4])
            else:
                return self._json(status=404, reason='dashboard_route_not_found', message='Unknown dashboard page.')
            return self._json(result)
        except MaintenanceUnavailable as exc:
            return self._json(status=503, reason=str(exc), message='Flower is in maintenance or still has active work. Inspect status and retry after service resumes.')
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
            return self._json(status=500, reason='dashboard_operation_failed', message='The request could not complete. Inspect the current maintenance intent before any destructive retry.')

    def mount(self, mcp):
        mcp.custom_route('/dashboard', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/assets/{asset}', methods=['GET'])(self.static)
        mcp.custom_route('/dashboard/api/{path:path}', methods=['GET', 'POST'])(self.api)
