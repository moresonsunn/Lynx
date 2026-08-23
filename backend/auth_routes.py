from fastapi import APIRouter, Depends, HTTPException, status, Request
import logging
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field, validator
from typing import List, Optional
from datetime import datetime, timedelta

from database import get_db
from models import User, UserSession
from auth import (
    require_auth,
    get_password_hash,
    get_client_ip, get_user_agent
)
from user_service import UserService

router = APIRouter(prefix="/auth", tags=["authentication"])

logger = logging.getLogger(__name__)


class Token(BaseModel):
    access_token: str
    token_type: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @validator("new_password")
    def validate_new_password(cls, v: str) -> str:
        _ensure_password_strength(v)
        return v


class SessionInfo(BaseModel):
    id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


def _get_password_settings():
    """Load password policy from system settings with sane defaults."""
    try:
        from settings_routes import load_settings
        settings = load_settings()
        sec = settings.get("security", {})
        return {
            "min_length": int(sec.get("min_password_length", 8)),
            "require_strong": bool(sec.get("require_strong_password", True)),
        }
    except Exception:
        return {"min_length": 8, "require_strong": True}


def _ensure_password_strength(password: str):
    policy = _get_password_settings()
    if len(password or "") < policy["min_length"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {policy['min_length']} characters long",
        )
    if not policy["require_strong"]:
        return
    if not any(ch.isupper() for ch in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if not any(ch.islower() for ch in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
    if not any(ch.isdigit() for ch in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one digit")


# ── Login / identity ───────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate user and return a session token (revocable, not a JWT)."""
    svc = UserService(db)
    ip = get_client_ip(request)
    user = svc.authenticate_user(form_data.username, form_data.password, ip_address=ip)
    if not user:
        logger.warning(
            "Login failed username='%s' IP=%s user_agent='%s'",
            form_data.username, ip, get_user_agent(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Return the session token (stored in DB) rather than a JWT so logout and
    # admin revocation can actually invalidate it. auth.get_current_user accepts both.
    session = svc.create_user_session(user, ip_address=ip, user_agent=get_user_agent(request))
    logger.info("Login success username='%s' session_id=%s IP=%s", user.username, session.id, ip)
    return Token(access_token=session.session_token, token_type="bearer")


@router.get("/me")
async def read_users_me(current_user: User = Depends(require_auth)):
    """Return the authenticated user's profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "full_name": current_user.full_name,
        "avatar_url": current_user.avatar_url,
        "is_active": current_user.is_active,
        "must_change_password": bool(current_user.must_change_password),
        "is_admin": current_user.role in ("admin", "owner"),
    }


# ── Own-account actions ────────────────────────────────────────────────────

@router.put("/me/password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Change current user's password."""
    from auth import verify_password

    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password")

    current_user.hashed_password = get_password_hash(password_data.new_password)
    current_user.must_change_password = False
    db.commit()

    return {"message": "Password updated successfully"}


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Logout current session by invalidating the bearer token if it is a session token."""
    svc = UserService(db)

    auth_header = request.headers.get("authorization", "")
    token = auth_header.split(" ")[-1] if auth_header else None
    if token:
        svc.invalidate_session(token)
    return {"message": "Logged out"}


# ── Sessions ───────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=List[SessionInfo])
async def list_my_sessions(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List current user's active sessions."""
    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == current_user.id, UserSession.is_active == True)  # noqa: E712
        .all()
    )
    return [
        SessionInfo(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            created_at=s.created_at,
            expires_at=s.expires_at,
            is_active=bool(s.is_active),
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Revoke a session. Users can revoke their own sessions; users with
    user.sessions.revoke can revoke anyone's."""
    svc = UserService(db)
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    can_revoke_any = current_user.role in ("admin", "owner") or svc.user_has_permission(
        current_user, "user.sessions.revoke"
    )
    if session.user_id != current_user.id and not can_revoke_any:
        raise HTTPException(status_code=403, detail="Not allowed to revoke this session")

    svc.revoke_session(session_id)
    return {"message": "Session revoked"}
