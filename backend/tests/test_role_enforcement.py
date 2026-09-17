"""Regression tests: non-admin roles must actually be blocked by the API.

A helper user must NOT be able to manage users/roles, create servers, or
moderate players — even though the UI once exposed those actions. Each test
asserts the HTTP status code so a silently-widened guard fails loudly.
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-0123456789")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(__file__).parent / "_tmp_servers"))
os.environ.setdefault("STATS_DB_PATH", str(Path(__file__).parent / "_tmp_stats.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

import pytest  # noqa: E402

from tests.test_auth_users_api import engine, db_session, client, _login  # noqa: E402,F401


@pytest.fixture()
def helper_headers(client, db_session):
    """Create (once) and log in a helper user; return auth headers."""
    from auth import get_password_hash
    from models import User

    if not db_session.query(User).filter(User.username == "helper_probe").first():
        # create through the API as admin so the test also covers user creation
        admin_h = _login(client, "admin", "AdminPass123")
        r = client.post(
            "/api/users",
            json={
                "username": "helper_probe",
                "email": "helper_probe@localhost",
                "password": "HelperPass123",
                "role": "helper",
            },
            headers=admin_h,
        )
        assert r.status_code in (200, 201), f"setup: create helper failed: {r.status_code} {r.text}"
    return _login(client, "helper_probe", "HelperPass123")


def _admin_headers(client):
    return _login(client, "admin", "AdminPass123")


def test_helper_cannot_list_users(client, helper_headers):
    r = client.get("/api/users", headers=helper_headers)
    assert r.status_code == 403, f"helper listed users: {r.status_code} {r.text}"


def test_helper_cannot_create_user(client, helper_headers):
    r = client.post(
        "/api/users",
        json={"username": "evil", "email": "evil@localhost", "password": "EvilPass123", "role": "user"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper created user: {r.status_code} {r.text}"


def test_helper_cannot_list_roles(client, helper_headers):
    r = client.get("/api/users/roles", headers=helper_headers)
    assert r.status_code == 403, f"helper listed roles: {r.status_code} {r.text}"


def test_helper_cannot_kick_player(client, helper_headers):
    r = client.post(
        "/api/players/DAWG/kick",
        json={"player_name": "victim", "action_type": "kick"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper kicked player: {r.status_code} {r.text}"


def test_helper_cannot_create_schedule(client, helper_headers):
    r = client.post(
        "/api/servers/DAWG/schedules",
        json={"name": "evil", "task_type": "command", "cron_expression": "0 2 * * *", "command": "stop"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper created schedule: {r.status_code} {r.text}"


def test_role_assignment_persists(client, db_session):
    """The Users-page role edit must actually stick (else 'helper' may be admin)."""
    from models import User

    admin_h = _admin_headers(client)
    helper = db_session.query(User).filter(User.username == "helper_probe").first()
    # admin demotes/raises role and it must persist + be visible in the list
    r = client.put(f"/api/users/{helper.id}", json={"role": "user"}, headers=admin_h)
    assert r.status_code == 200, f"role change failed: {r.status_code} {r.text}"
    db_session.expire_all()
    assert db_session.query(User).filter(User.username == "helper_probe").first().role == "user"
    r = client.put(f"/api/users/{helper.id}", json={"role": "helper"}, headers=admin_h)
    assert r.status_code == 200, f"role restore failed: {r.status_code} {r.text}"
    db_session.expire_all()
    assert db_session.query(User).filter(User.username == "helper_probe").first().role == "helper"


def test_helper_cannot_create_server(client, helper_headers):
    r = client.post(
        "/api/servers",
        json={"name": "evil-server", "type": "vanilla", "version": "1.21.1"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper created server: {r.status_code} {r.text}"


def test_helper_cannot_stop_server_without_grant(client, helper_headers):
    r = client.post("/api/servers/DAWG/stop", headers=helper_headers)
    # 403 = blocked by permission gate (correct). Anything else (e.g. 404/503
    # from Docker) would mean the gate let the request through.
    assert r.status_code == 403, f"helper stopped server w/o grant: {r.status_code} {r.text}"


def test_helper_with_manage_grant_passes_gate(client, helper_headers, db_session):
    from models import User

    admin_h = _admin_headers(client)
    helper = db_session.query(User).filter(User.username == "helper_probe").first()
    r = client.post(
        "/api/permissions",
        json={"user_id": helper.id, "server_name": "DAWG", "permission": "manage"},
        headers=admin_h,
    )
    assert r.status_code == 200, f"setup: grant failed: {r.status_code} {r.text}"
    r = client.post("/api/servers/DAWG/stop", headers=helper_headers)
    # Must NOT be 403 anymore (Docker itself will 404/503 in this sandbox —
    # that proves the permission gate passed).
    assert r.status_code != 403, f"manage grant still blocked: {r.status_code} {r.text}"


def test_helper_can_list_servers(client, helper_headers):
    r = client.get("/api/servers", headers=helper_headers)
    assert r.status_code == 200, f"helper cannot list servers: {r.status_code} {r.text}"


def test_admin_can_list_users(client):
    r = client.get("/api/users", headers=_admin_headers(client))
    assert r.status_code == 200, f"admin blocked: {r.status_code} {r.text}"


# ── Per-server grant enforcement (mods / plugins / worlds / config) ──────────

def test_helper_cannot_upload_mod_without_grant(client, helper_headers):
    r = client.post(
        "/api/mods/NOWHERE/upload",
        files={"file": ("evil.jar", b"PK\x03\x04evil", "application/java-archive")},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper uploaded mod: {r.status_code} {r.text}"


def test_helper_cannot_install_mod_without_grant(client, helper_headers):
    r = client.post(
        "/api/mods/NOWHERE/install",
        json={"url": "https://example.com/evil.jar", "filename": "evil.jar"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper installed mod: {r.status_code} {r.text}"


def test_helper_cannot_upload_plugin_without_grant(client, helper_headers):
    r = client.post(
        "/api/plugins/NOWHERE/upload",
        files={"file": ("evil.jar", b"PK\x03\x04evil", "application/java-archive")},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper uploaded plugin: {r.status_code} {r.text}"


def test_helper_cannot_install_plugin_without_grant(client, helper_headers):
    r = client.post(
        "/api/plugins/NOWHERE/install",
        json={"url": "https://example.com/evil.jar", "filename": "evil.jar", "source": "url"},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper installed plugin: {r.status_code} {r.text}"


def test_helper_cannot_upload_world_without_grant(client, helper_headers):
    r = client.post(
        "/api/worlds/NOWHERE/upload?world=evilworld",
        files={"file": ("world.zip", b"PK\x03\x04evil", "application/zip")},
        headers=helper_headers,
    )
    assert r.status_code == 403, f"helper uploaded world: {r.status_code} {r.text}"


def test_helper_cannot_download_world_without_grant(client, helper_headers):
    r = client.get("/api/worlds/NOWHERE/download?world=world", headers=helper_headers)
    assert r.status_code == 403, f"helper downloaded world: {r.status_code} {r.text}"


def test_helper_cannot_read_config_bundle_without_grant(client, helper_headers):
    r = client.get("/api/servers/NOWHERE/config-bundle", headers=helper_headers)
    assert r.status_code == 403, f"helper read config bundle: {r.status_code} {r.text}"


def test_grant_defaults_to_view_and_view_cannot_operate(client, helper_headers, db_session):
    """Omitting `permission` must grant least-privilege view, which must not
    pass the operate gate (but must pass the view gate)."""
    from models import User

    admin_h = _admin_headers(client)
    helper = db_session.query(User).filter(User.username == "helper_probe").first()
    r = client.post(
        "/api/permissions",
        json={"user_id": helper.id, "server_name": "DAWG_VIEW"},
        headers=admin_h,
    )
    assert r.status_code == 200, f"setup: grant failed: {r.status_code} {r.text}"
    r = client.get("/api/permissions/servers/DAWG_VIEW", headers=admin_h)
    assert r.status_code == 200, f"setup: list grants failed: {r.status_code} {r.text}"
    rows = r.json().get("permissions", [])
    mine = [p for p in rows if p.get("user_id") == helper.id]
    assert mine and mine[0].get("permission") == "view", f"grant default not view: {rows}"
    r = client.post("/api/servers/DAWG_VIEW/stop", headers=helper_headers)
    assert r.status_code == 403, f"view grant operated server: {r.status_code} {r.text}"
    r = client.get("/api/servers/DAWG_VIEW/stats", headers=helper_headers)
    # Gate must pass (Docker itself 404s/503s in this sandbox — that proves it).
    assert r.status_code != 403, f"view grant blocked from stats: {r.status_code} {r.text}"


def test_my_servers_shape(client, helper_headers):
    r = client.get("/api/permissions/my-servers", headers=helper_headers)
    assert r.status_code == 200, f"my-servers failed: {r.status_code} {r.text}"
    body = r.json()
    assert "permissions" in body, f"unexpected my-servers shape: {body}"


def test_notifications_require_login(client):
    """Anonymous notification reads must be 401, not an AttributeError 500."""
    r = client.get("/api/realtime/notifications")
    assert r.status_code == 401, f"anonymous notifications: {r.status_code} {r.text}"
