"""Integration tests for auth, permissions, and user management.

Runs against the real FastAPI app with dependency-overridden DB session and
temp SQLite storage, so it needs no Docker or running services.

    pytest backend/tests/test_auth_users_api.py -v
"""
import os
import sys
from pathlib import Path

# Ensure backend modules are importable when pytest runs from repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Isolate storage before importing app modules.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production-0123456789")
os.environ.setdefault("SERVERS_CONTAINER_ROOT", str(Path(__file__).parent / "_tmp_servers"))
os.environ.setdefault("STATS_DB_PATH", str(Path(__file__).parent / "_tmp_stats.db"))
os.environ.setdefault("STATS_COLLECTOR_ENABLED", "0")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models import User, Role


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db_session(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    session = TestingSession()
    # Seed the permission catalog + system roles exactly like
    # UserService.initialize_default_permissions_and_roles does in production,
    # otherwise role-permission checks behave differently than real deployments.
    from user_service import DEFAULT_PERMISSIONS, DEFAULT_ROLES
    from models import Permission

    for perm_name, perm_data in DEFAULT_PERMISSIONS.items():
        if not session.query(Permission).filter(Permission.name == perm_name).first():
            session.add(Permission(
                name=perm_name,
                description=perm_data["description"],
                category=perm_data["category"],
            ))
    for role_name, role_data in DEFAULT_ROLES.items():
        existing = session.query(Role).filter(Role.name == role_name).first()
        if not existing:
            session.add(Role(
                name=role_name,
                description=role_data["description"],
                permissions=list(role_data["permissions"]),
                is_system=True,
            ))
        elif existing.is_system:
            existing.permissions = list(role_data["permissions"])
    if not session.query(User).filter(User.username == "admin").first():
        from auth import get_password_hash
        session.add(User(
            username="admin",
            email="admin@localhost",
            hashed_password=get_password_hash("AdminPass123"),
            role="owner",
            is_active=True,
        ))
        session.add(User(
            username="viewer",
            email="viewer@localhost",
            hashed_password=get_password_hash("ViewerPass123"),
            role="user",
            is_active=True,
        ))
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    """TestClient wired to the isolated DB session."""
    import app as app_module

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app_module.app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app_module.app, raise_server_exceptions=False) as c:
        yield c
    app_module.app.dependency_overrides.pop(get_db, None)


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_admin_headers = None


def _admin(client: TestClient) -> dict:
    """Cached admin auth headers (re-login if the session was revoked)."""
    global _admin_headers
    if _admin_headers is None:
        _admin_headers = _login(client, "admin", "AdminPass123")
    return _admin_headers


def _make_user(client: TestClient, name: str, role: str = "user") -> dict:
    """Create a fresh user and return the created record."""
    r = client.post("/api/users", headers=_admin(client), json={
        "username": name,
        "email": f"{name}@localhost",
        "password": f"{name.capitalize()}Pass1",
        "role": role,
    })
    assert r.status_code in (200, 201), f"user create failed: {r.text}"
    return r.json()


# â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestAuth:
    def test_login_success_returns_session_token(self, client):
        headers = _login(client, "admin", "AdminPass123")
        assert headers["Authorization"].startswith("Bearer ")

    def test_login_wrong_password_401(self, client):
        r = client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_login_unknown_user_401(self, client):
        r = client.post(
            "/api/auth/login",
            data={"username": "ghost", "password": "whatever1A"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_me_requires_auth(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_returns_profile_and_admin_flag(self, client):
        headers = _login(client, "admin", "AdminPass123")
        me = client.get("/api/auth/me", headers=headers).json()
        assert me["username"] == "admin"
        assert me["is_admin"] is True

    def test_logout_invalidates_token(self, client):
        headers = _login(client, "admin", "AdminPass123")
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    def test_weak_password_change_rejected(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.put(
            "/api/auth/me/password",
            json={"current_password": "AdminPass123", "new_password": "weak"},
            headers=headers,
        )
        assert r.status_code in (400, 422)


# â”€â”€ User CRUD (/api/users â€” permission-gated) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestUserManagementPermissions:
    def test_regular_user_cannot_list_users(self, client):
        headers = _login(client, "viewer", "ViewerPass123")
        r = client.get("/api/users", headers=headers)
        assert r.status_code == 403, "regular users must not list all users"

    def test_admin_can_list_users(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.get("/api/users", headers=headers)
        assert r.status_code == 200
        body = r.json()
        users = body["users"] if isinstance(body, dict) else body
        assert {u["username"] for u in users} >= {"admin", "viewer"}

    def test_anonymous_cannot_create_user(self, client):
        r = client.post("/api/users", json={
            "username": "x", "email": "x@localhost", "password": "Password1"
        })
        assert r.status_code == 401

    def test_admin_creates_user(self, client):
        user = _make_user(client, "newbie")
        assert user["username"] == "newbie"

    def test_duplicate_username_rejected(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.post("/api/users", headers=headers, json={
            "username": "viewer",
            "email": "other@localhost",
            "password": "Password1",
            "role": "user",
        })
        assert r.status_code == 400

    def test_weak_password_rejected(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.post("/api/users", headers=headers, json={
            "username": "weakpw",
            "email": "weakpw@localhost",
            "password": "alllowercase1",
            "role": "user",
        })
        assert r.status_code in (400, 422)

    def test_admin_updates_role(self, client):
        target = _make_user(client, "roleupdate")
        r = client.put(f"/api/users/{target['id']}", headers=_admin(client), json={"role": "moderator"})
        assert r.status_code == 200
        assert r.json()["role"] == "moderator"

    def test_admin_deactivates_user(self, client):
        """Deactivate a throw-away user â€” must not poison other tests' fixtures."""
        target = _make_user(client, "deleteme")
        r = client.delete(f"/api/users/{target['id']}", headers=_admin(client))
        assert r.status_code in (200, 204)
        # Deactivated user can no longer log in.
        r = client.post(
            "/api/auth/login",
            data={"username": "deleteme", "password": "DeletemePass1"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401

    def test_last_active_admin_demotion_blocked(self, client):
        """Demoting/deactivating the only active owner/admin must fail."""
        headers = _login(client, "admin", "AdminPass123")
        me = client.get("/api/auth/me", headers=headers).json()
        r = client.put(f"/api/users/{me['id']}", headers=headers, json={"role": "user"})
        assert r.status_code == 400


# â”€â”€ Roles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestRoles:
    def test_roles_require_permission(self, client):
        headers = _login(client, "viewer", "ViewerPass123")
        assert client.get("/api/users/roles", headers=headers).status_code == 403

    def test_admin_lists_roles(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.get("/api/users/roles", headers=headers)
        assert r.status_code == 200
        names = {x["name"] for x in r.json()["roles"]}
        assert {"owner", "admin", "moderator", "user"} <= names

    def test_admin_creates_custom_role(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.post("/api/users/roles", headers=headers, json={
            "name": "custom_tester",
            "description": "Created by integration test",
            "permissions": ["server.view"],
        })
        assert r.status_code == 200, r.text

    def test_system_role_delete_blocked(self, client):
        headers = _login(client, "admin", "AdminPass123")
        r = client.delete("/api/users/roles/admin", headers=headers)
        assert r.status_code == 400


# â”€â”€ SPA reload routing (regression: raw 401 JSON on F5) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestSpaRouting:
    """Browser refresh (unauthenticated GET) on any client-side route must
    serve the React shell â€” never a shadowing protected API route returning
    {"detail": "Not authenticated"}."""

    SPA_PATHS = [
        "/", "/login", "/servers", "/servers/some-id",
        "/servers/some-id/overview",
        # Server-detail tabs (3-segment) — these were shadowed by bare API
        # routes like /servers/{name}/players, causing 401 JSON on refresh.
        "/servers/some-id/players", "/servers/some-id/worlds",
        "/servers/some-id/files", "/servers/some-id/console",
        "/servers/some-id/config", "/servers/some-id/backup",
        "/servers/some-id/schedule", "/servers/some-id/mods",
        "/users", "/settings", "/templates",
        "/steam", "/monitoring", "/security", "/multi-server", "/status",
        "/change-password", "/hytale",
    ]

    def test_spa_paths_serve_html_not_401_json(self, client):
        for path in self.SPA_PATHS:
            r = client.get(path)
            body = r.text
            is_html = r.status_code == 200 and (
                "text/html" in r.headers.get("content-type", "")
                or "<!doctype html" in body.lower()
                or "<html" in body.lower()
            )
            # Dev checkouts without static/index.html may 404 from spa_fallback,
            # which is still correct routing â€” the failure mode we guard against
            # is an API route answering with auth JSON.
            is_spa_fallback_404 = r.status_code == 404 and "Frontend not found" in body
            assert is_html or is_spa_fallback_404, (
                f"GET {path} -> {r.status_code} {body[:120]!r}"
            )
            if r.status_code == 401:
                pytest.fail(f"SPA route {path} was shadowed by an auth-protected API route")

    def test_api_stays_protected_under_api_prefix(self, client):
        r = client.get("/api/users")
        assert r.status_code in (401, 403)
        assert "text/html" not in r.headers.get("content-type", "")

    def test_healthcheck_bare_path_alive(self, client):
        # docker-compose healthcheck curls http://localhost:8000/health/quick
        r = client.get("/health/quick")
        assert r.status_code < 500



# ── Players roster contract ────────────────────────────────────────────────

class TestRoster:
    def test_roster_contract_matches_frontend(self, client, monkeypatch):
        """online must be a LIST of names (not an int) and offline must exist —
        the earlier pydantic response_model coerced online:int and broke the panel."""
        import player_routes as pr

        class FakeDM:
            def list_servers(self):
                return [{"name": "DAWG", "id": "abc123", "status": "running"}]

            def get_player_info(self, cid):
                return {"online": 1, "max": 20, "names": ["Steve"], "method": "rcon"}

        monkeypatch.setattr(pr, "get_runtime_manager_or_docker", lambda: FakeDM())

        headers = _login(client, "admin", "AdminPass123")
        r = client.get("/api/players/DAWG/roster", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        assert isinstance(body["online"], list), f"online must be a list, got {type(body['online'])}"
        assert body["online"] == ["Steve"]
        assert isinstance(body["offline"], list)
        assert body["count"] == 1
        assert body["max"] == 20
        assert body["method"] == "rcon"

    def test_roster_survives_manager_failure(self, client, monkeypatch):
        """If the runtime manager explodes, still return 200 with empty online
        so the panel degrades to logs-only instead of showing an error banner."""
        import player_routes as pr

        def _boom():
            raise RuntimeError("docker down")

        monkeypatch.setattr(pr, "get_runtime_manager_or_docker", _boom)

        headers = _login(client, "admin", "AdminPass123")
        r = client.get("/api/players/NOPE/roster", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["online"] == []
        assert isinstance(body["offline"], list)
