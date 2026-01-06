from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status, Body, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime
import re
import os
import uuid
import base64

from database import get_db
from models import User
from user_service import UserService
from auth import get_current_user, require_auth, require_admin, require_user_view, require_user_create, require_user_edit
from auth import require_user_delete, require_user_manage_roles, require_system_audit, log_user_action
from auth import require_permission
from pydantic import BaseModel, Field, validator

# Avatar storage directory
AVATAR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

# Custom email validation that allows localhost domains for development
def validate_email(email: str) -> str:
    """Custom email validator that allows localhost domains."""
    # Basic email format validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    localhost_pattern = r'^[a-zA-Z0-9._%+-]+@localhost$'
    
    if re.match(email_pattern, email) or re.match(localhost_pattern, email):
        return email
    else:
        raise ValueError('Invalid email format')

# Pydantic models for request/response
class UserBase(BaseModel):
    username: str
    email: str
    role: str = "user"
    full_name: Optional[str] = None
    
    @validator('email')
    def validate_email_field(cls, v):
        return validate_email(v)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    
    @validator('password')
    def password_strength(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    
    @validator('email')
    def validate_email_field(cls, v):
        if v is not None:
            return validate_email(v)
        return v
    
    @validator('password')
    def password_strength(cls, v):
        """Validate password strength if provided."""
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def password_strength(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

class UserLoginRequest(BaseModel):
    username: str
    password: str

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    failed_login_attempts: Optional[int] = 0
    locked_until: Optional[datetime] = None
    must_change_password: bool = False
    has_2fa: bool = False  # Will be populated dynamically
    
    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    users: List[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class UserSessionResponse(BaseModel):
    session_token: str
    user: UserResponse

class RoleResponse(BaseModel):
    name: str
    description: str
    permissions: List[str]
    is_system: bool

    class Config:
        from_attributes = True

class PermissionResponse(BaseModel):
    name: str
    description: str
    category: str

    class Config:
        from_attributes = True

class RolesListResponse(BaseModel):
    roles: List[RoleResponse]

class PermissionsListResponse(BaseModel):
    permissions: List[PermissionResponse]

class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    timestamp: datetime
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]

    class Config:
        from_attributes = True

class AuditLogListResponse(BaseModel):
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

# Create router
router = APIRouter(prefix="/users", tags=["users"])

# Authentication routes
@router.post("/login", response_model=UserSessionResponse)
async def login(
    request: Request,
    login_data: UserLoginRequest,
    db: Session = Depends(get_db)
):
    """Login and get a session token."""
    user_service = UserService(db)
    
    user = user_service.authenticate_user(
        login_data.username, 
        login_data.password,
        get_client_ip(request)
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create session
    session = user_service.create_user_session(
        user,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent")
    )
    
    return {
        "session_token": session.session_token,
        "user": user
    }

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Logout and invalidate session token."""
    user_service = UserService(db)
    # Get session token from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        session_token = auth_header[7:]
        user_service.invalidate_session(session_token)
    
    # Log the action
    log_user_action(
        user=user,
        action="user.logout",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        db=db
    )
    
    return None

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(require_auth)
):
    """Get information about the current authenticated user."""
    return user

@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    password_data: UserPasswordChange,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Change user's own password."""
    user_service = UserService(db)
    
    # Verify current password
    if not user_service.verify_password(password_data.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Update password
    updates = {
        "password": password_data.new_password,
        "must_change_password": False
    }
    
    user_service.update_user(user.id, updates, updated_by=user.id)
    
    # Log the action
    log_user_action(
        user=user,
        action="user.change_password",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        db=db
    )
    
    return None

# User management routes
@router.get("", response_model=UserListResponse)
async def list_users(
    request: Request,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_user_view),
    db: Session = Depends(get_db)
):
    """List all users with pagination."""
    user_service = UserService(db)
    result = user_service.list_users(include_inactive, page, page_size)
    
    # Log the action
    log_user_action(
        user=user,
        action="user.list",
        resource_type="users",
        details={"page": page, "page_size": page_size, "include_inactive": include_inactive},
        request=request,
        db=db
    )
    
    return result

# Move static routes before dynamic /{user_id} to avoid path conflicts
# Role and permission routes
@router.get("/roles", response_model=RolesListResponse)
async def get_roles(
    request: Request,
    current_user: User = Depends(require_user_manage_roles),
    db: Session = Depends(get_db)
):
    """Get all available roles."""
    user_service = UserService(db)
    roles = user_service.get_roles()
    
    # Log the action
    log_user_action(
        user=current_user,
        action="role.list",
        resource_type="roles",
        request=request,
        db=db
    )
    
    return {"roles": roles}

@router.get("/permissions", response_model=PermissionsListResponse)
async def get_permissions(
    request: Request,
    current_user: User = Depends(require_user_manage_roles),
    db: Session = Depends(get_db)
):
    """Get all available permissions."""
    user_service = UserService(db)
    permissions = user_service.get_permissions()
    
    # Log the action
    log_user_action(
        user=current_user,
        action="permission.list",
        resource_type="permissions",
        request=request,
        db=db
    )
    
    return {"permissions": permissions}

# Audit logs
@router.get("/audit-logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    request: Request,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    page: int = 1, 
    page_size: int = 50,
    current_user: User = Depends(require_system_audit),
    db: Session = Depends(get_db)
):
    """Get audit logs with filtering and pagination."""
    user_service = UserService(db)
    result = user_service.get_audit_logs(user_id, action, page, page_size)
    
    # Log the action
    log_user_action(
        user=current_user,
        action="audit.view",
        resource_type="audit_logs",
        details={"user_id": user_id, "action": action, "page": page, "page_size": page_size},
        request=request,
        db=db
    )
    
    return result

# Role management (create/update/delete custom roles)
class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []

class RoleUpdate(BaseModel):
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

@router.post("/roles")
async def create_role(
    request: Request,
    role: RoleCreate,
    current_user: User = Depends(require_permission("role.create")),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    try:
        new_role = service.create_role(role.name, role.description, role.permissions)
        log_user_action(user=current_user, action="role.create", resource_type="role", resource_id=role.name, request=request, db=db)
        return {"message": "Role created", "role": {"name": new_role.name, "description": new_role.description, "permissions": new_role.permissions, "is_system": new_role.is_system}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/roles/{name}")
async def update_role(
    request: Request,
    name: str,
    role: RoleUpdate,
    current_user: User = Depends(require_permission("role.edit")),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    try:
        updated = service.update_role(name, description=role.description, permissions=role.permissions)
        log_user_action(user=current_user, action="role.edit", resource_type="role", resource_id=name, request=request, db=db)
        return {"message": "Role updated", "role": {"name": updated.name, "description": updated.description, "permissions": updated.permissions, "is_system": updated.is_system}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/roles/{name}")
async def delete_role(
    request: Request,
    name: str,
    current_user: User = Depends(require_permission("role.delete")),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    try:
        service.delete_role(name)
        log_user_action(user=current_user, action="role.delete", resource_type="role", resource_id=name, request=request, db=db)
        return {"message": "Role deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_user_view),
    db: Session = Depends(get_db)
):
    """Get a specific user by ID."""
    user_service = UserService(db)
    user = user_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Log the action
    log_user_action(
        user=current_user,
        action="user.view",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return user

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    request: Request,
    current_user: User = Depends(require_user_create),
    db: Session = Depends(get_db)
):
    """Create a new user."""
    user_service = UserService(db)
    
    try:
        user = user_service.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            role=user_data.role,
            full_name=user_data.full_name,
            created_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    current_user: User = Depends(require_user_edit),
    db: Session = Depends(get_db)
):
    """Update a user's information."""
    user_service = UserService(db)
    
    # Check if updating role and if user has permission
    if user_data.role is not None and user_data.role != current_user.role:
        # Verify that the current user has permission to manage roles
        if not user_service.user_has_permission(current_user, "user.manage_roles"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: cannot change user roles"
            )
    
    try:
        updates = user_data.dict(exclude_unset=True, exclude_none=True)
        user = user_service.update_user(
            user_id=user_id,
            updates=updates,
            updated_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_user_delete),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) a user."""
    user_service = UserService(db)
    
    try:
        user_service.delete_user(
            user_id=user_id,
            deleted_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return None


# ==================== SESSION MANAGEMENT ====================

class SessionResponse(BaseModel):
    id: int
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: Optional[str]
    expires_at: Optional[str]
    is_active: bool
    is_current: bool

class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]

@router.get("/{user_id}/sessions", response_model=SessionListResponse)
async def get_user_sessions(
    user_id: int,
    request: Request,
    include_expired: bool = False,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all active sessions for a user."""
    # Users can view their own sessions, admins can view anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other user's sessions"
        )
    
    user_service = UserService(db)
    sessions = user_service.get_user_sessions(user_id, include_expired)
    
    # Mark current session
    auth_header = request.headers.get("Authorization")
    current_token = None
    if auth_header and auth_header.startswith("Bearer "):
        current_token = auth_header[7:]
    
    # We need to check which session is current by comparing tokens
    from models import UserSession
    for session in sessions:
        db_session = db.query(UserSession).filter(UserSession.id == session["id"]).first()
        if db_session and db_session.session_token == current_token:
            session["is_current"] = True
    
    return {"sessions": sessions}

@router.delete("/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_session(
    user_id: int,
    session_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revoke a specific session."""
    # Users can revoke their own sessions, admins can revoke anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke other user's sessions"
        )
    
    user_service = UserService(db)
    success = user_service.revoke_session(session_id, user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    log_user_action(
        user=current_user,
        action="session.revoke",
        resource_type="session",
        resource_id=str(session_id),
        request=request,
        db=db
    )
    
    return None

@router.delete("/{user_id}/sessions", status_code=status.HTTP_200_OK)
async def revoke_all_user_sessions(
    user_id: int,
    request: Request,
    keep_current: bool = True,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revoke all sessions for a user."""
    # Users can revoke their own sessions, admins can revoke anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke other user's sessions"
        )
    
    user_service = UserService(db)
    
    # Get current session ID if keeping current
    except_session_id = None
    if keep_current and current_user.id == user_id:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            current_token = auth_header[7:]
            from models import UserSession
            current_session = db.query(UserSession).filter(
                UserSession.session_token == current_token
            ).first()
            if current_session:
                except_session_id = current_session.id
    
    count = user_service.revoke_all_sessions(user_id, except_session_id)
    
    log_user_action(
        user=current_user,
        action="session.revoke_all",
        resource_type="user",
        resource_id=str(user_id),
        details={"revoked_count": count, "kept_current": keep_current},
        request=request,
        db=db
    )
    
    return {"message": f"Revoked {count} sessions", "revoked_count": count}


# ==================== LOGIN HISTORY ====================

class LoginHistoryEntry(BaseModel):
    id: int
    user_id: Optional[int]
    username: str
    success: bool
    ip_address: Optional[str]
    user_agent: Optional[str]
    failure_reason: Optional[str]
    timestamp: Optional[str]

class LoginHistoryResponse(BaseModel):
    entries: List[LoginHistoryEntry]
    total: int
    page: int
    page_size: int
    total_pages: int

@router.get("/{user_id}/login-history", response_model=LoginHistoryResponse)
async def get_user_login_history(
    user_id: int,
    request: Request,
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get login history for a user."""
    # Users can view their own history, admins can view anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other user's login history"
        )
    
    user_service = UserService(db)
    result = user_service.get_login_history(user_id, page, page_size)
    
    return result

@router.get("/login-history/all", response_model=LoginHistoryResponse)
async def get_all_login_history(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    success_only: Optional[bool] = None,
    current_user: User = Depends(require_system_audit),
    db: Session = Depends(get_db)
):
    """Get all login history (admin only)."""
    user_service = UserService(db)
    result = user_service.get_login_history(None, page, page_size, success_only)
    
    log_user_action(
        user=current_user,
        action="login_history.view",
        resource_type="login_history",
        details={"page": page, "success_only": success_only},
        request=request,
        db=db
    )
    
    return result


# ==================== API KEY MANAGEMENT ====================

class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    permissions: Optional[List[str]] = None
    expires_days: Optional[int] = None

class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    permissions: List[str]
    expires_at: Optional[str]
    last_used_at: Optional[str]
    last_used_ip: Optional[str]
    created_at: Optional[str]
    is_expired: bool

class APIKeyCreatedResponse(BaseModel):
    id: int
    name: str
    key: str  # Only returned once
    key_prefix: str
    permissions: List[str]
    expires_at: Optional[str]
    created_at: Optional[str]

class APIKeyListResponse(BaseModel):
    api_keys: List[APIKeyResponse]

@router.get("/{user_id}/api-keys", response_model=APIKeyListResponse)
async def get_user_api_keys(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all API keys for a user."""
    # Users can view their own keys, admins can view anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other user's API keys"
        )
    
    user_service = UserService(db)
    keys = user_service.get_api_keys(user_id)
    
    return {"api_keys": keys}

@router.post("/{user_id}/api-keys", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_user_api_key(
    user_id: int,
    key_data: APIKeyCreate,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create a new API key for a user."""
    # Users can create their own keys, admins can create for anyone
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create API keys for other users"
        )
    
    user_service = UserService(db)
    result = user_service.create_api_key(
        user_id=user_id,
        name=key_data.name,
        permissions=key_data.permissions,
        expires_days=key_data.expires_days
    )
    
    log_user_action(
        user=current_user,
        action="api_key.create",
        resource_type="api_key",
        resource_id=str(result["id"]),
        details={"name": key_data.name},
        request=request,
        db=db
    )
    
    return result

@router.delete("/{user_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_api_key(
    user_id: int,
    key_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revoke an API key."""
    # Users can revoke their own keys, admins can revoke anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke other user's API keys"
        )
    
    user_service = UserService(db)
    success = user_service.revoke_api_key(key_id, user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    log_user_action(
        user=current_user,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=str(key_id),
        request=request,
        db=db
    )
    
    return None


# ==================== TWO-FACTOR AUTHENTICATION ====================

class TwoFactorSetupResponse(BaseModel):
    secret: str
    totp_uri: str
    backup_codes: List[str]
    message: str

class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)

class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    verified: bool
    verified_at: Optional[str] = None
    backup_codes_remaining: int

class TwoFactorDisableRequest(BaseModel):
    code: Optional[str] = None

@router.get("/{user_id}/2fa/status", response_model=TwoFactorStatusResponse)
async def get_2fa_status(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get 2FA status for a user."""
    # Users can view their own status, admins can view anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other user's 2FA status"
        )
    
    user_service = UserService(db)
    status_info = user_service.get_2fa_status(user_id)
    
    return status_info

@router.post("/{user_id}/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Set up 2FA for a user."""
    # Users can only set up their own 2FA
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only set up 2FA for yourself"
        )
    
    user_service = UserService(db)
    
    try:
        result = user_service.setup_2fa(user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return result

@router.post("/{user_id}/2fa/verify", status_code=status.HTTP_200_OK)
async def verify_2fa_setup(
    user_id: int,
    verify_data: TwoFactorVerifyRequest,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Verify 2FA setup with a code."""
    # Users can only verify their own 2FA
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only verify 2FA for yourself"
        )
    
    user_service = UserService(db)
    
    try:
        success = user_service.verify_2fa_setup(user_id, verify_data.code)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )
    
    log_user_action(
        user=current_user,
        action="2fa.enabled",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return {"message": "2FA enabled successfully"}

@router.post("/{user_id}/2fa/disable", status_code=status.HTTP_200_OK)
async def disable_2fa(
    user_id: int,
    disable_data: TwoFactorDisableRequest,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Disable 2FA for a user."""
    # Users can disable their own 2FA, admins can disable anyone's
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot disable other user's 2FA"
        )
    
    user_service = UserService(db)
    
    try:
        # Non-admins must provide a code
        code = disable_data.code if current_user.id == user_id else None
        user_service.disable_2fa(user_id, code)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    log_user_action(
        user=current_user,
        action="2fa.disabled",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return {"message": "2FA disabled successfully"}

@router.post("/{user_id}/2fa/regenerate-backup-codes")
async def regenerate_backup_codes(
    user_id: int,
    verify_data: TwoFactorVerifyRequest,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Regenerate 2FA backup codes."""
    # Users can only regenerate their own codes
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only regenerate backup codes for yourself"
        )
    
    user_service = UserService(db)
    
    # Verify the code first
    if not user_service.verify_2fa(user_id, verify_data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )
    
    # Regenerate by setting up again (but keeping enabled status)
    from models import UserTwoFactor
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    two_factor = db.query(UserTwoFactor).filter(
        UserTwoFactor.user_id == user_id
    ).first()
    
    if not two_factor or not two_factor.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled"
        )
    
    # Generate new backup codes
    import secrets as sec
    backup_codes = [sec.token_hex(4).upper() for _ in range(10)]
    two_factor.backup_codes = [pwd_ctx.hash(code) for code in backup_codes]
    db.commit()
    
    log_user_action(
        user=current_user,
        action="2fa.backup_codes_regenerated",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return {"backup_codes": backup_codes, "message": "New backup codes generated"}


# ==================== USER UNLOCK ====================

@router.post("/{user_id}/unlock", status_code=status.HTTP_200_OK)
async def unlock_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_user_edit),
    db: Session = Depends(get_db)
):
    """Unlock a locked user account."""
    user_service = UserService(db)
    
    try:
        user = user_service.unlock_user(user_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    log_user_action(
        user=current_user,
        action="user.unlock",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return {"message": f"User {user.username} unlocked successfully"}


# ==================== PASSWORD RESET BY ADMIN ====================

class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8)
    force_change: bool = True

@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
async def admin_reset_password(
    user_id: int,
    reset_data: AdminPasswordReset,
    request: Request,
    current_user: User = Depends(require_permission("user.password.reset")),
    db: Session = Depends(get_db)
):
    """Reset a user's password (admin only)."""
    user_service = UserService(db)
    
    try:
        user = user_service.reset_user_password(
            user_id=user_id,
            new_password=reset_data.new_password,
            force_change=reset_data.force_change,
            updated_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    log_user_action(
        user=current_user,
        action="user.password.reset",
        resource_type="user",
        resource_id=str(user_id),
        details={"force_change": reset_data.force_change},
        request=request,
        db=db
    )
    
    return {"message": f"Password reset for user {user.username}"}


# ==================== AVATAR MANAGEMENT ====================

class AvatarUploadRequest(BaseModel):
    image_data: str  # Base64 encoded image

@router.post("/{user_id}/avatar", status_code=status.HTTP_200_OK)
async def upload_avatar(
    user_id: int,
    avatar_data: AvatarUploadRequest,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Upload a user avatar (base64 encoded image)."""
    # Users can upload their own avatar, admins can upload for anyone
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot upload avatar for other users"
        )
    
    user_service = UserService(db)
    user = user_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    try:
        # Parse base64 data
        image_data = avatar_data.image_data
        
        # Handle data URL format (data:image/png;base64,...)
        if "," in image_data:
            header, image_data = image_data.split(",", 1)
            # Detect format from header
            if "png" in header.lower():
                ext = "png"
            elif "gif" in header.lower():
                ext = "gif"
            elif "webp" in header.lower():
                ext = "webp"
            else:
                ext = "jpg"
        else:
            ext = "jpg"
        
        # Decode base64
        image_bytes = base64.b64decode(image_data)
        
        # Validate size (max 2MB)
        if len(image_bytes) > 2 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image too large (max 2MB)"
            )
        
        # Generate filename
        filename = f"{user_id}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(AVATAR_DIR, filename)
        
        # Remove old avatar if exists
        if user.avatar_url:
            old_filename = user.avatar_url.split("/")[-1]
            old_path = os.path.join(AVATAR_DIR, old_filename)
            if os.path.exists(old_path):
                os.remove(old_path)
        
        # Save new avatar
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        
        # Update user
        user.avatar_url = f"/api/users/{user_id}/avatar/{filename}"
        db.commit()
        
        log_user_action(
            user=current_user,
            action="user.avatar.upload",
            resource_type="user",
            resource_id=str(user_id),
            request=request,
            db=db
        )
        
        return {"avatar_url": user.avatar_url}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to upload avatar: {str(e)}"
        )

@router.get("/{user_id}/avatar/{filename}")
async def get_avatar(
    user_id: int,
    filename: str,
    db: Session = Depends(get_db)
):
    """Get a user's avatar image."""
    from fastapi.responses import FileResponse
    
    # Validate filename to prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )
    
    filepath = os.path.join(AVATAR_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found"
        )
    
    # Determine content type
    ext = filename.split(".")[-1].lower()
    content_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp"
    }
    content_type = content_types.get(ext, "image/jpeg")
    
    return FileResponse(filepath, media_type=content_type)

@router.delete("/{user_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_avatar(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete a user's avatar."""
    # Users can delete their own avatar, admins can delete for anyone
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete avatar for other users"
        )
    
    user_service = UserService(db)
    user = user_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Remove file if exists
    if user.avatar_url:
        filename = user.avatar_url.split("/")[-1]
        filepath = os.path.join(AVATAR_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    
    # Clear avatar URL
    user.avatar_url = None
    db.commit()
    
    log_user_action(
        user=current_user,
        action="user.avatar.delete",
        resource_type="user",
        resource_id=str(user_id),
        request=request,
        db=db
    )
    
    return None


# ==================== PROFILE UPDATE ====================

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None

@router.patch("/{user_id}/profile", response_model=UserResponse)
async def update_user_profile(
    user_id: int,
    profile_data: ProfileUpdate,
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update user profile settings."""
    # Users can update their own profile, admins can update for anyone
    if current_user.id != user_id and current_user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update other user's profile"
        )
    
    user_service = UserService(db)
    user = user_service.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    if profile_data.full_name is not None:
        user.full_name = profile_data.full_name
    if profile_data.timezone is not None:
        user.timezone = profile_data.timezone
    if profile_data.language is not None:
        user.language = profile_data.language
    if profile_data.preferences is not None:
        # Merge preferences
        current_prefs = user.preferences or {}
        current_prefs.update(profile_data.preferences)
        user.preferences = current_prefs
    
    db.commit()
    db.refresh(user)
    
    log_user_action(
        user=current_user,
        action="user.profile.update",
        resource_type="user",
        resource_id=str(user_id),
        details=profile_data.dict(exclude_unset=True),
        request=request,
        db=db
    )
    
    return user


def get_client_ip(request: Request) -> str:
    """Get client IP address from request."""
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0]
    if "x-real-ip" in request.headers:
        return request.headers["x-real-ip"]
    return request.client.host
