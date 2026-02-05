"""
Enhanced Security & Access Control
2FA/TOTP, IP whitelisting, enhanced audit logging, per-server permissions
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import secrets
import hashlib
import base64
import json
import re

from database import get_db
from models import User, UserTwoFactor, AuditLog, UserAPIKey
from auth import require_auth, require_moderator, require_admin, get_password_hash

router = APIRouter(prefix="/security", tags=["security"])


# ==================== Request/Response Models ====================

class TOTPSetupResponse(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: List[str]


class TOTPVerifyRequest(BaseModel):
    code: str


class IPWhitelistEntry(BaseModel):
    ip_address: str
    description: Optional[str] = None
    enabled: bool = True


class ServerPermission(BaseModel):
    server_name: str
    can_view: bool = True
    can_edit: bool = False
    can_delete: bool = False
    can_execute_commands: bool = False


class UserServerPermissions(BaseModel):
    user_id: int
    permissions: List[ServerPermission]


class AuditLogQuery(BaseModel):
    user_id: Optional[int] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = 100


# ==================== 2FA/TOTP Support ====================

@router.post("/2fa/setup", response_model=TOTPSetupResponse)
async def setup_2fa(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Initialize 2FA setup for user"""
    
    # Check if already enabled
    existing = db.query(UserTwoFactor).filter(
        UserTwoFactor.user_id == current_user.id
    ).first()
    
    if existing and existing.is_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled")
    
    # Generate secret
    secret = base64.b32encode(secrets.token_bytes(20)).decode('utf-8')
    
    # Generate backup codes
    backup_codes = [
        ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(8))
        for _ in range(10)
    ]
    
    # Hash backup codes for storage
    hashed_backup_codes = [
        hashlib.sha256(code.encode()).hexdigest()
        for code in backup_codes
    ]
    
    if existing:
        # Update existing
        existing.secret = secret
        existing.backup_codes = hashed_backup_codes
        existing.is_enabled = False
    else:
        # Create new
        two_factor = UserTwoFactor(
            user_id=current_user.id,
            secret=secret,
            backup_codes=hashed_backup_codes,
            is_enabled=False
        )
        db.add(two_factor)
    
    db.commit()
    
    # Generate QR code URL for authenticator apps
    issuer = "Lynx"
    label = f"{issuer}:{current_user.username}"
    qr_url = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
    
    return TOTPSetupResponse(
        secret=secret,
        qr_code_url=qr_url,
        backup_codes=backup_codes  # Return plain codes once for user to save
    )


@router.post("/2fa/verify")
async def verify_2fa_setup(
    request: TOTPVerifyRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Verify and enable 2FA"""
    
    two_factor = db.query(UserTwoFactor).filter(
        UserTwoFactor.user_id == current_user.id
    ).first()
    
    if not two_factor:
        raise HTTPException(status_code=404, detail="2FA not set up")
    
    # Verify TOTP code
    if _verify_totp(two_factor.secret, request.code):
        two_factor.is_enabled = True
        two_factor.verified_at = datetime.utcnow()
        db.commit()
        
        # Log action
        log = AuditLog(
            user_id=current_user.id,
            action='enable_2fa',
            resource_type='user',
            resource_id=str(current_user.id),
            details={'method': 'totp'}
        )
        db.add(log)
        db.commit()
        
        return {'success': True, 'message': '2FA enabled successfully'}
    else:
        raise HTTPException(status_code=400, detail="Invalid verification code")


@router.post("/2fa/disable")
async def disable_2fa(
    password: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Disable 2FA for user"""
    
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Verify password
    if not pwd_context.verify(password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    two_factor = db.query(UserTwoFactor).filter(
        UserTwoFactor.user_id == current_user.id
    ).first()
    
    if two_factor:
        db.delete(two_factor)
        db.commit()
        
        # Log action
        log = AuditLog(
            user_id=current_user.id,
            action='disable_2fa',
            resource_type='user',
            resource_id=str(current_user.id)
        )
        db.add(log)
        db.commit()
    
    return {'success': True, 'message': '2FA disabled'}


@router.get("/2fa/status")
async def get_2fa_status(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Check if 2FA is enabled for user"""
    
    two_factor = db.query(UserTwoFactor).filter(
        UserTwoFactor.user_id == current_user.id
    ).first()
    
    return {
        'enabled': two_factor.is_enabled if two_factor else False,
        'verified_at': two_factor.verified_at.isoformat() if two_factor and two_factor.verified_at else None
    }


def _verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify TOTP code"""
    
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=window)
    except ImportError:
        # Fallback simple implementation
        import time
        import hmac
        
        def _generate_totp(secret: str, time_step: int = 30) -> str:
            key = base64.b32decode(secret, casefold=True)
            counter = int(time.time()) // time_step
            msg = counter.to_bytes(8, byteorder='big')
            digest = hmac.new(key, msg, hashlib.sha1).digest()
            offset = digest[-1] & 0x0f
            truncated = int.from_bytes(digest[offset:offset+4], byteorder='big') & 0x7fffffff
            return str(truncated % 1000000).zfill(6)
        
        current_time = int(time.time())
        for i in range(-window, window + 1):
            time_counter = (current_time // 30) + i
            expected = _generate_totp(secret)
            if code == expected:
                return True
        return False


# ==================== IP Whitelisting ====================

@router.get("/ip-whitelist")
async def get_ip_whitelist(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get IP whitelist entries"""
    
    if not current_user.preferences:
        current_user.preferences = {}
    
    whitelist = current_user.preferences.get('ip_whitelist', [])
    
    return {'whitelist': whitelist}


@router.post("/ip-whitelist")
async def add_ip_to_whitelist(
    entry: IPWhitelistEntry,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Add IP to whitelist"""
    
    # Validate IP address format
    if not _is_valid_ip(entry.ip_address):
        raise HTTPException(status_code=400, detail="Invalid IP address format")
    
    if not current_user.preferences:
        current_user.preferences = {}
    
    if 'ip_whitelist' not in current_user.preferences:
        current_user.preferences['ip_whitelist'] = []
    
    # Check if IP already exists
    existing = next(
        (item for item in current_user.preferences['ip_whitelist'] 
         if item['ip_address'] == entry.ip_address),
        None
    )
    
    if existing:
        raise HTTPException(status_code=400, detail="IP already in whitelist")
    
    # Add to whitelist
    current_user.preferences['ip_whitelist'].append({
        'ip_address': entry.ip_address,
        'description': entry.description,
        'enabled': entry.enabled,
        'added_at': datetime.utcnow().isoformat()
    })
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, 'preferences')
    db.commit()
    
    # Log action
    log = AuditLog(
        user_id=current_user.id,
        action='add_ip_whitelist',
        resource_type='security',
        details={'ip_address': entry.ip_address}
    )
    db.add(log)
    db.commit()
    
    return {'success': True, 'message': 'IP added to whitelist'}


@router.delete("/ip-whitelist/{ip_address}")
async def remove_ip_from_whitelist(
    ip_address: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Remove IP from whitelist"""
    
    if not current_user.preferences or 'ip_whitelist' not in current_user.preferences:
        raise HTTPException(status_code=404, detail="IP not found in whitelist")
    
    whitelist = current_user.preferences['ip_whitelist']
    updated = [item for item in whitelist if item['ip_address'] != ip_address]
    
    if len(updated) == len(whitelist):
        raise HTTPException(status_code=404, detail="IP not found in whitelist")
    
    current_user.preferences['ip_whitelist'] = updated
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, 'preferences')
    db.commit()
    
    return {'success': True, 'message': 'IP removed from whitelist'}


@router.post("/ip-whitelist/check")
async def check_ip_access(
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Check if current IP is whitelisted"""
    
    client_ip = request.client.host if request.client else None
    
    if not client_ip:
        return {'whitelisted': False, 'ip': None}
    
    # Get admin's whitelist
    admin = db.query(User).filter(User.role == 'admin').first()
    if not admin or not admin.preferences:
        return {'whitelisted': True, 'ip': client_ip}  # No whitelist = allow all
    
    whitelist = admin.preferences.get('ip_whitelist', [])
    if not whitelist:
        return {'whitelisted': True, 'ip': client_ip}
    
    # Check if IP is whitelisted
    is_whitelisted = any(
        item['ip_address'] == client_ip and item.get('enabled', True)
        for item in whitelist
    )
    
    return {
        'whitelisted': is_whitelisted,
        'ip': client_ip
    }


def _is_valid_ip(ip: str) -> bool:
    """Validate IP address format"""
    
    # IPv4
    ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ipv4_pattern, ip):
        parts = ip.split('.')
        return all(0 <= int(part) <= 255 for part in parts)
    
    # IPv6 (basic validation)
    ipv6_pattern = r'^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$'
    if re.match(ipv6_pattern, ip):
        return True
    
    # CIDR notation
    if '/' in ip:
        ip_part, mask = ip.split('/')
        return _is_valid_ip(ip_part) and mask.isdigit() and 0 <= int(mask) <= 32
    
    return False


# ==================== Enhanced Audit Logging ====================

@router.post("/audit-logs/query")
async def query_audit_logs(
    query: AuditLogQuery,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Advanced audit log querying"""
    
    q = db.query(AuditLog)
    
    # Apply filters
    if query.user_id:
        q = q.filter(AuditLog.user_id == query.user_id)
    
    if query.action:
        q = q.filter(AuditLog.action.like(f"%{query.action}%"))
    
    if query.resource_type:
        q = q.filter(AuditLog.resource_type == query.resource_type)
    
    if query.start_date:
        q = q.filter(AuditLog.timestamp >= query.start_date)
    
    if query.end_date:
        q = q.filter(AuditLog.timestamp <= query.end_date)
    
    # Get results
    logs = q.order_by(AuditLog.timestamp.desc()).limit(query.limit).all()
    
    return {
        'total': len(logs),
        'logs': [
            {
                'id': log.id,
                'user': log.user.username if log.user else 'System',
                'action': log.action,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'details': log.details,
                'ip_address': log.ip_address,
                'timestamp': log.timestamp.isoformat()
            }
            for log in logs
        ]
    }


@router.get("/audit-logs/summary")
async def get_audit_summary(
    days: int = 7,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Get audit log summary statistics"""
    
    from sqlalchemy import func
    
    since = datetime.utcnow() - timedelta(days=days)
    
    # Total actions
    total = db.query(func.count(AuditLog.id)).filter(
        AuditLog.timestamp >= since
    ).scalar()
    
    # Actions by user
    by_user = db.query(
        User.username,
        func.count(AuditLog.id).label('count')
    ).join(User).filter(
        AuditLog.timestamp >= since
    ).group_by(User.username).all()
    
    # Actions by type
    by_action = db.query(
        AuditLog.action,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.timestamp >= since
    ).group_by(AuditLog.action).all()
    
    # Recent critical actions
    critical_actions = ['delete_server', 'delete_user', 'disable_2fa', 'update_permissions']
    recent_critical = db.query(AuditLog).filter(
        and_(
            AuditLog.timestamp >= since,
            AuditLog.action.in_(critical_actions)
        )
    ).order_by(AuditLog.timestamp.desc()).limit(10).all()
    
    return {
        'period_days': days,
        'total_actions': total,
        'by_user': [{'user': u, 'count': c} for u, c in by_user],
        'by_action': [{'action': a, 'count': c} for a, c in by_action],
        'recent_critical': [
            {
                'action': log.action,
                'user': log.user.username if log.user else 'System',
                'resource': f"{log.resource_type}/{log.resource_id}",
                'timestamp': log.timestamp.isoformat()
            }
            for log in recent_critical
        ]
    }


# ==================== Per-Server Permissions ====================

@router.get("/server-permissions/{user_id}")
async def get_user_server_permissions(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get per-server permissions for a user"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.preferences:
        user.preferences = {}
    
    permissions = user.preferences.get('server_permissions', [])
    
    return {
        'user_id': user_id,
        'username': user.username,
        'permissions': permissions
    }


@router.post("/server-permissions/{user_id}")
async def set_user_server_permissions(
    user_id: int,
    permissions: UserServerPermissions,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Set per-server permissions for a user"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.preferences:
        user.preferences = {}
    
    # Convert permissions to dict
    perms_dict = [
        {
            'server_name': p.server_name,
            'can_view': p.can_view,
            'can_edit': p.can_edit,
            'can_delete': p.can_delete,
            'can_execute_commands': p.can_execute_commands
        }
        for p in permissions.permissions
    ]
    
    user.preferences['server_permissions'] = perms_dict
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, 'preferences')
    db.commit()
    
    # Log action
    log = AuditLog(
        user_id=current_user.id,
        action='update_server_permissions',
        resource_type='user',
        resource_id=str(user_id),
        details={'servers': [p.server_name for p in permissions.permissions]}
    )
    db.add(log)
    db.commit()
    
    return {'success': True, 'message': 'Permissions updated'}


@router.post("/server-permissions/check")
async def check_server_permission(
    server_name: str,
    permission: str,  # view, edit, delete, execute_commands
    current_user: User = Depends(require_auth)
):
    """Check if user has specific permission for a server"""
    
    # Admins have all permissions
    if current_user.role == 'admin':
        return {'allowed': True, 'reason': 'admin'}
    
    # Check per-server permissions
    if current_user.preferences and 'server_permissions' in current_user.preferences:
        server_perms = next(
            (p for p in current_user.preferences['server_permissions'] 
             if p['server_name'] == server_name),
            None
        )
        
        if server_perms:
            perm_key = f"can_{permission}"
            allowed = server_perms.get(perm_key, False)
            return {
                'allowed': allowed,
                'reason': 'server_permission' if allowed else 'denied'
            }
    
    # Default to role-based permissions
    if current_user.role == 'moderator':
        # Moderators can view and edit by default
        allowed = permission in ['view', 'edit', 'execute_commands']
        return {'allowed': allowed, 'reason': 'role_moderator'}
    
    # Regular users can only view
    allowed = permission == 'view'
    return {'allowed': allowed, 'reason': 'role_user'}


# ==================== Security Dashboard ====================

@router.get("/dashboard")
async def get_security_dashboard(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get security overview dashboard"""
    
    # User stats
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    users_with_2fa = db.query(UserTwoFactor).filter(
        UserTwoFactor.is_enabled == True
    ).count()
    
    # Recent failed logins
    recent_failures = db.query(User).filter(
        User.failed_login_attempts > 0
    ).order_by(User.failed_login_attempts.desc()).limit(5).all()
    
    # API key usage
    active_api_keys = db.query(UserAPIKey).filter(
        UserAPIKey.is_active == True
    ).count()
    
    # Recent security events
    security_actions = ['login', 'failed_login', 'enable_2fa', 'disable_2fa', 'api_key_created']
    recent_events = db.query(AuditLog).filter(
        AuditLog.action.in_(security_actions)
    ).order_by(AuditLog.timestamp.desc()).limit(10).all()
    
    return {
        'users': {
            'total': total_users,
            'active': active_users,
            'with_2fa': users_with_2fa,
            '2fa_percentage': round((users_with_2fa / total_users * 100) if total_users > 0 else 0, 1)
        },
        'failed_logins': [
            {
                'username': u.username,
                'attempts': u.failed_login_attempts,
                'locked_until': u.locked_until.isoformat() if u.locked_until else None
            }
            for u in recent_failures
        ],
        'api_keys': {
            'active': active_api_keys
        },
        'recent_events': [
            {
                'action': e.action,
                'user': e.user.username if e.user else 'System',
                'timestamp': e.timestamp.isoformat(),
                'ip': e.ip_address
            }
            for e in recent_events
        ]
    }
