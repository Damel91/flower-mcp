"""The HTTPS ingress has its own route and credential boundary."""
from types import SimpleNamespace

from starlette.testclient import TestClient

from flow_of_work_mcp import dashboard_http, dashboard_maintenance
from tests.test_dashboard_http import fixture, request_csrf


REMOTE = "https://flower.example:8443"


def test_remote_authority_requires_https_and_never_routes_mcp(tmp_path):
    runtime, dashboard, _ = fixture(tmp_path)
    try:
        app = dashboard.remote_dashboard_app(SimpleNamespace(authority="flower.example:8443", port=8443))
        with TestClient(app, base_url=REMOTE, client=("192.0.2.18", 1234)) as remote:
            assert remote.get("/dashboard").status_code == 200
            assert remote.get("/dashboard/assets/app.js").status_code == 200
            assert remote.get("/dashboard/api/projects").status_code == 401
            assert remote.get("/mcp").status_code == remote.post("/mcp").status_code == 404
            assert remote.get("/mcp/").status_code == 404
            assert remote.get("/dashboard", headers={"Host": "attacker.example:8443"}).status_code == 403
            assert remote.get("/dashboard", headers={"Origin": "null"}).status_code == 403
            assert remote.get("/dashboard", headers=[("Host", "flower.example:8443"),
                                                     ("Host", "attacker.example:8443")]).status_code == 403
            assert remote.get("/dashboard", headers=[("Origin", REMOTE), ("Origin", REMOTE)]).status_code == 403
            assert remote.get("http://flower.example:8443/dashboard",
                              headers={"X-Forwarded-Proto": "https"}).status_code == 403
            assert remote.post("/dashboard/api/login", json={}).status_code == 403
    finally:
        dashboard.close()
        runtime.close()


def test_remote_uses_secure_cookie_and_shared_maintenance(tmp_path, monkeypatch):
    runtime, dashboard, mcp = fixture(tmp_path)
    local_auth = dashboard.auth
    auth_class = dashboard_http.DashboardAuth
    monkeypatch.setattr(dashboard_http, "DashboardAuth", lambda config, database, **kwargs: auth_class(
        config, database, binding=local_auth._binding, verifier=local_auth._verifier, **kwargs))
    try:
        app = dashboard.remote_dashboard_app(SimpleNamespace(authority="flower.example:8443", port=8443))
        with TestClient(app, base_url=REMOTE, client=("192.0.2.18", 1234)) as remote, TestClient(
                mcp.streamable_http_app(), base_url="http://127.0.0.1:18760", client=("127.0.0.1", 4567)) as local:
            initial = remote.get("/dashboard/api/auth").json()["result"]
            login = remote.post("/dashboard/api/login", headers={
                "Origin": REMOTE, "X-Flower-CSRF": initial["csrf_token"],
            }, json={"username": "synthetic-owner", "password": "synthetic-fixture-only"})
            assert login.status_code == 200
            cookie = login.headers["set-cookie"]
            assert "_https=" in cookie and "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
            assert "Domain=" not in cookie
            proof = login.json()["result"]["csrf_token"]
            assert remote.get("/dashboard/api/projects").status_code == 401
            assert remote.get("/dashboard/api/projects", headers={"X-Flower-CSRF": proof}).status_code == 200
            assert local.get("/dashboard/api/projects", headers={
                "Cookie": cookie.split(";", 1)[0], "X-Flower-CSRF": proof,
            }).status_code == 401
            request_csrf(local)
            original = dashboard_maintenance.run_dashboard_project_purge
            def during_purge(*args, **kwargs):
                assert dashboard.maintenance.status()["state"] == "maintenance"
                assert local.get("/dashboard/api/projects").status_code == 503
                return original(*args, **kwargs)
            monkeypatch.setattr(dashboard_maintenance, "run_dashboard_project_purge", during_purge)
            endpoint = "/dashboard/api/projects/project-a/deletion/delete"
            headers = {"Origin": REMOTE, "X-Flower-CSRF": proof}
            body = {"confirm_project_id": "project-a", "password": "synthetic-fixture-only"}
            deleted = remote.post(endpoint, json=body, headers=headers)
            assert deleted.status_code == 200
            assert deleted.json()["result"]["deletion"]["deletion_state"] == "scrubbed"
            assert dashboard.maintenance.status()["state"] == "ready"
            assert local.get("/dashboard/api/projects").status_code == 200
    finally:
        dashboard.close()
        runtime.close()
