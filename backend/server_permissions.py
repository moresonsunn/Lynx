"""
Server-level multi-user permission system.

Permission levels (cumulative):
  view    — see server in list, view stats/console (read-only)
  operate — start / stop / restart / send console commands
  manage  — full access (files, backups, mods, settings, delete)

Admins & owners bypass all checks. Regular users only see servers
they have an explicit ServerPermission row for.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from database import get_db
from auth import require_auth, require_admin
from models import User, ServerPermission

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

PERMISSION_LEVELS = {"view": 0, "operate": 1, "manage": 2}


# ── Helpers (importable by other modules) ──────────────────────────────────

def user_can_access_server(user: User, server_name: str, required: str = "view", db: Session = None) -> bool:
    """
    Return True if *user* has at least *required* permission on *server_name*.
    Admins/owners always pass.
    """
    if user.role in ("admin", "owner"):
        return True
    if db is None:
        return False
    perm = (
        db.query(ServerPermission)
        .filter(ServerPermission.user_id == user.id, ServerPermission.server_name == server_name)
        .first()
    )
    if not perm:
        return False
    return PERMISSION_LEVELS.get(perm.permission, 0) >= PERMISSION_LEVELS.get(required, 0)


def get_user_server_names(user: User, db: Session) -> Optional[List[str]]:
    """
    Return list of server_names the user can see, or None if the user is admin/owner
    (meaning they can see everything).
    """
    if user.role in ("admin", "owner"):
        return None  # no filter needed
    rows = db.query(ServerPermission.server_name).filter(ServerPermission.user_id == user.id).all()
    return [r[0] for r in rows]


# ── API Models ─────────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    user_id: int
    server_name: str
    permission: str = "manage"  # view | operate | manage


class GrantResponse(BaseModel):
    id: int
    user_id: int
    server_name: str
    permission: str


# ── CRUD Endpoints ─────────────────────────────────────────────────────────

@router.get("/servers/{server_name}")
def list_server_permissions(
    server_name: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users with access to a given server."""
    rows = (
        db.query(ServerPermission)
        .filter(ServerPermission.server_name == server_name)
        .all()
    )
    result = []
    for r in rows:
        u = db.query(User).filter(User.id == r.user_id).first()
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "username": u.username if u else "unknown",
            "email": u.email if u else "",
            "permission": r.permission,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"permissions": result}


@router.get("/users/{user_id}")
def list_user_permissions(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all servers a user has access to."""
    rows = db.query(ServerPermission).filter(ServerPermission.user_id == user_id).all()
    return {
        "permissions": [
            {
                "id": r.id,
                "server_name": r.server_name,
                "permission": r.permission,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("")
def grant_permission(
    req: GrantRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Grant a user access to a server (upsert)."""
    if req.permission not in PERMISSION_LEVELS:
        raise HTTPException(400, f"Invalid permission. Choose from: {list(PERMISSION_LEVELS)}")
    target = db.query(User).filter(User.id == req.user_id).first()
    if not target:
        raise HTTPException(404, "User not found")

    existing = (
        db.query(ServerPermission)
        .filter(ServerPermission.user_id == req.user_id, ServerPermission.server_name == req.server_name)
        .first()
    )
    if existing:
        existing.permission = req.permission
        db.commit()
        return {"ok": True, "id": existing.id, "action": "updated"}

    perm = ServerPermission(
        user_id=req.user_id,
        server_name=req.server_name,
        permission=req.permission,
        granted_by=current_user.id,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return {"ok": True, "id": perm.id, "action": "created"}


@router.delete("/{permission_id}")
def revoke_permission(
    permission_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke a specific permission."""
    perm = db.query(ServerPermission).filter(ServerPermission.id == permission_id).first()
    if not perm:
        raise HTTPException(404, "Permission not found")
    db.delete(perm)
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/servers/{server_name}")
def revoke_user_server(
    user_id: int,
    server_name: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke a user's access to a specific server."""
    perm = (
        db.query(ServerPermission)
        .filter(ServerPermission.user_id == user_id, ServerPermission.server_name == server_name)
        .first()
    )
    if not perm:
        raise HTTPException(404, "Permission not found")
    db.delete(perm)
    db.commit()
    return {"ok": True}


@router.get("/my-servers")
def my_server_permissions(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the current user's server permissions."""
    if current_user.role in ("admin", "owner"):
        return {"all_access": True, "permissions": []}
    rows = db.query(ServerPermission).filter(ServerPermission.user_id == current_user.id).all()
    return {
        "all_access": False,
        "permissions": [
            {"server_name": r.server_name, "permission": r.permission}
            for r in rows
        ],
    }
