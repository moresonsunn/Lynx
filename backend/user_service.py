
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
import logging
import os
from passlib.context import CryptContext
import secrets

from models import User, Role, Permission, UserSession, AuditLog
from database import get_db

logger = logging.getLogger(__name__)


def _load_idle_timeout() -> int:
    try:
        val = int(os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "5"))
        return max(val, 1)
    except Exception:
        return 5

SESSION_IDLE_TIMEOUT_MINUTES = _load_idle_timeout()


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


DEFAULT_PERMISSIONS = {
    
    "server.view": {"description": "View server list and basic details", "category": "server_control", "level": 1},
    "server.create": {"description": "Create new servers", "category": "server_control", "level": 3},
    "server.start": {"description": "Start servers", "category": "server_control", "level": 2},
    "server.stop": {"description": "Stop servers", "category": "server_control", "level": 2},
    "server.restart": {"description": "Restart servers", "category": "server_control", "level": 2},
    "server.kill": {"description": "Force kill servers", "category": "server_control", "level": 3},
    "server.delete": {"description": "Delete servers permanently", "category": "server_control", "level": 4},
    "server.clone": {"description": "Clone/duplicate servers", "category": "server_control", "level": 3},
    
    
    "server.console.view": {"description": "View server console output", "category": "server_console", "level": 1},
    "server.console.send": {"description": "Send commands to server console", "category": "server_console", "level": 2},
    "server.console.history": {"description": "Access console command history", "category": "server_console", "level": 2},
    
    
    "server.config.view": {"description": "View server configuration files", "category": "server_config", "level": 1},
    "server.config.edit": {"description": "Edit server configuration files", "category": "server_config", "level": 3},
    "server.properties.edit": {"description": "Edit server.properties", "category": "server_config", "level": 2},
    "server.startup.edit": {"description": "Modify server startup parameters", "category": "server_config", "level": 3},
    
    
    "server.files.view": {"description": "Browse server files and folders", "category": "server_files", "level": 1},
    "server.files.download": {"description": "Download files from server", "category": "server_files", "level": 2},
    "server.files.upload": {"description": "Upload files to server", "category": "server_files", "level": 2},
    "server.files.edit": {"description": "Edit text files on server", "category": "server_files", "level": 2},
    "server.files.delete": {"description": "Delete server files", "category": "server_files", "level": 3},
    "server.files.create": {"description": "Create new files and folders", "category": "server_files", "level": 2},
    "server.files.compress": {"description": "Create/extract archives", "category": "server_files", "level": 2},
    
    
    "server.players.view": {"description": "View online players and stats", "category": "server_players", "level": 1},
    "server.players.kick": {"description": "Kick players from server", "category": "server_players", "level": 2},
    "server.players.ban": {"description": "Ban/unban players", "category": "server_players", "level": 2},
    "server.players.whitelist": {"description": "Manage server whitelist", "category": "server_players", "level": 2},
    "server.players.op": {"description": "Grant/revoke operator status", "category": "server_players", "level": 3},
    "server.players.chat": {"description": "Send messages as server/view chat", "category": "server_players", "level": 2},
    
    
    "server.backup.view": {"description": "View server backups", "category": "server_backup", "level": 1},
    "server.backup.create": {"description": "Create server backups", "category": "server_backup", "level": 2},
    "server.backup.restore": {"description": "Restore server from backup", "category": "server_backup", "level": 3},
    "server.backup.delete": {"description": "Delete server backups", "category": "server_backup", "level": 3},
    "server.backup.download": {"description": "Download backup files", "category": "server_backup", "level": 2},
    "server.backup.schedule": {"description": "Schedule automatic backups", "category": "server_backup", "level": 3},
    
    
    "user.view": {"description": "View user list and basic details", "category": "user_management", "level": 2},
    "user.create": {"description": "Create new users", "category": "user_management", "level": 3},
    "user.edit": {"description": "Edit user details and settings", "category": "user_management", "level": 3},
    "user.delete": {"description": "Delete users from system", "category": "user_management", "level": 4},
    "user.password.reset": {"description": "Reset user passwords", "category": "user_management", "level": 3},
    "user.sessions.view": {"description": "View active user sessions", "category": "user_management", "level": 3},
    "user.sessions.revoke": {"description": "Revoke user sessions", "category": "user_management", "level": 3},
    
    
    "role.view": {"description": "View roles and permissions", "category": "role_management", "level": 2},
    "role.create": {"description": "Create custom roles", "category": "role_management", "level": 4},
    "role.edit": {"description": "Modify role permissions", "category": "role_management", "level": 4},
    "role.delete": {"description": "Delete custom roles", "category": "role_management", "level": 4},
    "role.assign": {"description": "Assign roles to users", "category": "role_management", "level": 3},
    
    
    "system.monitoring.view": {"description": "View system monitoring and stats", "category": "system_admin", "level": 2},
    "system.logs.view": {"description": "View system and application logs", "category": "system_admin", "level": 2},
    "system.audit.view": {"description": "View audit logs and security events", "category": "system_admin", "level": 3},
    "system.settings.view": {"description": "View system settings", "category": "system_admin", "level": 2},
    "system.settings.edit": {"description": "Modify system settings", "category": "system_admin", "level": 4},
    "system.maintenance": {"description": "Perform system maintenance tasks", "category": "system_admin", "level": 4},
    "system.updates": {"description": "Manage system updates", "category": "system_admin", "level": 4},
    
    
    "schedule.view": {"description": "View scheduled tasks", "category": "automation", "level": 2},
    "schedule.create": {"description": "Create scheduled tasks", "category": "automation", "level": 3},
    "schedule.edit": {"description": "Modify scheduled tasks", "category": "automation", "level": 3},
    "schedule.delete": {"description": "Delete scheduled tasks", "category": "automation", "level": 3},
    "schedule.execute": {"description": "Manually execute scheduled tasks", "category": "automation", "level": 3},
    
    
    "plugins.view": {"description": "View installed plugins/mods", "category": "plugin_management", "level": 1},
    "plugins.install": {"description": "Install new plugins/mods", "category": "plugin_management", "level": 3},
    "plugins.remove": {"description": "Remove plugins/mods", "category": "plugin_management", "level": 3},
    "plugins.configure": {"description": "Configure plugin settings", "category": "plugin_management", "level": 2},
    "plugins.update": {"description": "Update plugins/mods", "category": "plugin_management", "level": 3},
}


DEFAULT_ROLES = {
    "owner": {
        "description": "System owner with unrestricted access to everything",
        "permissions": list(DEFAULT_PERMISSIONS.keys()),
        "is_system": True,
        "level": 5,
        "color": "#dc2626"
    },
    "admin": {
        "description": "System administrator with full server and user management",
        "permissions": [
            
            "server.view", "server.create", "server.start", "server.stop", "server.restart",
            "server.kill", "server.delete", "server.clone",
            
            "server.console.view", "server.console.send", "server.console.history",
            "server.config.view", "server.config.edit", "server.properties.edit", "server.startup.edit",
            
            "server.files.view", "server.files.download", "server.files.upload", 
            "server.files.edit", "server.files.delete", "server.files.create", "server.files.compress",
            
            "server.players.view", "server.players.kick", "server.players.ban", 
            "server.players.whitelist", "server.players.op", "server.players.chat",
            
            "server.backup.view", "server.backup.create", "server.backup.restore", 
            "server.backup.delete", "server.backup.download", "server.backup.schedule",
            
            "user.view", "user.create", "user.edit", "user.password.reset",
            "user.sessions.view", "user.sessions.revoke",
            
            "role.view", "role.edit",
            
            "system.monitoring.view", "system.logs.view", "system.audit.view", "system.settings.view",
            
            "schedule.view", "schedule.create", "schedule.edit", "schedule.delete", "schedule.execute",
            
            "plugins.view", "plugins.install", "plugins.remove", "plugins.configure", "plugins.update"
        ],
        "is_system": True,
        "level": 4,
        "color": "#f97316"
    },
    "moderator": {
        "description": "Server moderator with management rights but limited system access",
        "permissions": [
            
            "server.view", "server.start", "server.stop", "server.restart",
            
            "server.console.view", "server.console.send", "server.console.history",
            "server.config.view", "server.properties.edit",
            
            "server.files.view", "server.files.download", "server.files.upload", 
            "server.files.edit", "server.files.create",
            
            "server.players.view", "server.players.kick", "server.players.ban", 
            "server.players.whitelist", "server.players.chat",
            
            "server.backup.view", "server.backup.create", "server.backup.download",
            
            "system.monitoring.view", "system.logs.view",
            
            "plugins.view", "plugins.configure"
        ],
        "is_system": True,
        "level": 3,
        "color": "#eab308"
    },
    "helper": {
        "description": "Server helper with console access and basic management",
        "permissions": [
            
            "server.view", "server.start", "server.stop",
            
            "server.console.view", "server.console.send",
            "server.config.view",
            
            "server.files.view", "server.files.download",
            
            "server.players.view", "server.players.kick", "server.players.chat",
            
            "server.backup.view", "server.backup.create",
            
            "system.monitoring.view",
            
            "plugins.view"
        ],
        "is_system": True,
        "level": 2,
        "color": "#22c55e"
    },
    "user": {
        "description": "Regular user with read-only access to assigned servers",
        "permissions": [
            
            "server.view",
            
            "server.console.view",
            "server.config.view",
            
            "server.files.view", "server.files.download",
            
            "server.players.view",
            
            "server.backup.view",
            
            "plugins.view"
        ],
        "is_system": True,
        "level": 1,
        "color": "#3b82f6"
    },
    "guest": {
        "description": "Guest user with minimal read-only access",
        "permissions": [
            "server.view",
            "server.console.view",
            "server.players.view"
        ],
        "is_system": True,
        "level": 0,
        "color": "#6b7280"
    }
}

class UserService:
    """Comprehensive user management service similar to Crafty Controller."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def initialize_default_permissions_and_roles(self):
        """Initialize default permissions and roles in the database."""
        
        for perm_name, perm_data in DEFAULT_PERMISSIONS.items():
            existing_perm = self.db.query(Permission).filter(Permission.name == perm_name).first()
            if not existing_perm:
                permission = Permission(
                    name=perm_name,
                    description=perm_data["description"],
                    category=perm_data["category"]
                )
                self.db.add(permission)
        
        
        for role_name, role_data in DEFAULT_ROLES.items():
            existing_role = self.db.query(Role).filter(Role.name == role_name).first()
            if not existing_role:
                role = Role(
                    name=role_name,
                    description=role_data["description"],
                    permissions=role_data["permissions"],
                    is_system=role_data["is_system"]
                )
                self.db.add(role)
            else:
                
                if existing_role.is_system:
                    existing_role.permissions = role_data["permissions"]
        
        self.db.commit()
        logger.info("Initialized default permissions and roles")
    
    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return self.db.query(User).filter(User.id == user_id).first()
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self.db.query(User).filter(User.username == username).first()
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return self.db.query(User).filter(User.email == email).first()
    
    def create_user(self, username: str, email: str, password: str, role: str = "user", 
                   full_name: Optional[str] = None, created_by: Optional[int] = None) -> User:
        """Create a new user."""
        
        if self.get_user_by_username(username):
            raise ValueError(f"Username '{username}' already exists")
        if self.get_user_by_email(email):
            raise ValueError(f"Email '{email}' already exists")
        
        
        role_obj = self.db.query(Role).filter(Role.name == role).first()
        if not role_obj:
            raise ValueError(f"Role '{role}' does not exist")
        
        
        user = User(
            username=username,
            email=email,
            hashed_password=self.hash_password(password),
            role=role,
            full_name=full_name,
            must_change_password=True  
        )
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        
        self.log_audit_action(
            user_id=created_by,
            action="user.create",
            resource_type="user",
            resource_id=str(user.id),
            details={"username": username, "email": email, "role": role}
        )
        
        logger.info(f"Created user: {username} with role: {role}")
        return user
    
    def update_user(self, user_id: int, updates: Dict[str, Any], updated_by: Optional[int] = None) -> User:
        """Update user details."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
        
        
        if "password" in updates:
            updates["hashed_password"] = self.hash_password(updates.pop("password"))
            updates["must_change_password"] = False
        
        
        if "role" in updates:
            role_obj = self.db.query(Role).filter(Role.name == updates["role"]).first()
            if not role_obj:
                raise ValueError(f"Role '{updates['role']}' does not exist")
        
        
        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        self.db.commit()
        self.db.refresh(user)
        
        
        self.log_audit_action(
            user_id=updated_by,
            action="user.edit",
            resource_type="user",
            resource_id=str(user.id),
            details={"updates": list(updates.keys())}
        )
        
        logger.info(f"Updated user: {user.username}")
        return user
    
    def delete_user(self, user_id: int, deleted_by: Optional[int] = None) -> bool:
        """Delete a user (soft delete by deactivating)."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
        
        if user.role == "admin" and self.count_active_admins() <= 1:
            raise ValueError("Cannot delete the last active admin user")
        
        
        user.is_active = False
        self.db.commit()
        
        
        self.invalidate_user_sessions(user_id)
        
        
        self.log_audit_action(
            user_id=deleted_by,
            action="user.delete",
            resource_type="user",
            resource_id=str(user.id),
            details={"username": user.username}
        )
        
        logger.info(f"Deactivated user: {user.username}")
        return True
    
    def list_users(self, include_inactive: bool = False, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """List users with pagination."""
        query = self.db.query(User)
        
        if not include_inactive:
            query = query.filter(User.is_active == True)
        
        total = query.count()
        users = query.offset((page - 1) * page_size).limit(page_size).all()
        
        return {
            "users": users,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    
    def count_active_admins(self) -> int:
        """Count active admin users."""
        return self.db.query(User).filter(
            and_(User.role == "admin", User.is_active == True)
        ).count()
    
    def authenticate_user(self, username: str, password: str, ip_address: Optional[str] = None) -> Optional[User]:
        """Authenticate a user and handle login attempts."""
        user = self.get_user_by_username(username)
        if not user:
            return None
        
        
        if user.locked_until and user.locked_until > datetime.utcnow():
            logger.warning(f"User {username} is locked until {user.locked_until}")
            return None
        
        if not user.is_active:
            logger.warning(f"Inactive user {username} attempted login")
            return None

        
        hashed = str(user.hashed_password or "")
        if self.verify_password(password, hashed):
            
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login = datetime.utcnow()
            user.last_login_ip = ip_address
            self.db.commit()

            
            
            uid = None
            try:
                uid = int(getattr(user, "id"))
            except Exception:
                pass
            self.log_audit_action(
                user_id=uid if uid is not None else None,
                action="user.login",
                resource_type="user",
                resource_id=str(user.id),
                details={"success": True},
                ip_address=ip_address
            )

            logger.info(f"User {username} logged in successfully")
            return user
        else:
            
            
            fa = user.failed_login_attempts
            try:
                current_attempts = fa if isinstance(fa, int) else 0
            except Exception:
                current_attempts = 0
            user.failed_login_attempts = current_attempts + 1

            
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=30)
                logger.warning(f"User {username} locked due to failed login attempts")

            self.db.commit()

            
            uid = None
            try:
                uid = int(getattr(user, "id"))
            except Exception:
                pass
            self.log_audit_action(
                user_id=uid if uid is not None else None,
                action="user.login",
                resource_type="user",
                resource_id=str(user.id),
                details={"success": False, "failed_attempts": user.failed_login_attempts},
                ip_address=ip_address
            )

            logger.warning(f"Failed login attempt for user {username}")
            return None
    
    def create_user_session(self, user: User, ip_address: Optional[str] = None, 
                           user_agent: Optional[str] = None) -> UserSession:
        """Create a new user session with short idle timeout."""
        session_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES)
        
        session = UserSession(
            user_id=user.id,
            session_token=session_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        
        self.db.add(session)
        self.db.commit()
        
        logger.info(f"Created session for user {user.username} with {SESSION_IDLE_TIMEOUT_MINUTES}m idle timeout")
        return session
    
    def get_user_by_session_token(self, session_token: str, refresh_expiry: bool = True) -> Optional[User]:
        """Get user by session token and optionally extend idle expiry."""
        session = self.db.query(UserSession).filter(
            and_(
                UserSession.session_token == session_token,
                UserSession.is_active == True
            )
        ).first()

        if not session:
            return None

        now = datetime.utcnow()
        if not session.expires_at or session.expires_at <= now:
            try:
                session.is_active = False
                self.db.commit()
            except Exception:
                self.db.rollback()
            return None

        if refresh_expiry:
            new_expiry = now + timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES)
            
            if session.expires_at < new_expiry - timedelta(seconds=30):
                session.expires_at = new_expiry
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()

        return session.user
    
    def invalidate_session(self, session_token: str) -> bool:
        """Invalidate a session."""
        updated = self.db.query(UserSession).filter(
            UserSession.session_token == session_token
        ).update({"is_active": False})
        self.db.commit()
        return updated > 0
    
    def invalidate_user_sessions(self, user_id: int) -> int:
        """Invalidate all sessions for a user."""
        count = self.db.query(UserSession).filter(
            and_(UserSession.user_id == user_id, UserSession.is_active == True)
        ).update({"is_active": False})
        
        self.db.commit()
        logger.info(f"Invalidated {count} sessions for user {user_id}")
        return count
    
    def get_user_permissions(self, user: User) -> List[str]:
        """Get all permissions for a user based on their role."""
        role = self.db.query(Role).filter(Role.name == user.role).first()
        if role:
            perms = role.permissions or []
            
            try:
                if isinstance(perms, list):
                    return perms
                
                return []
            except Exception:
                return []
        return []
    
    def user_has_permission(self, user: User, permission: str) -> bool:
        """Check if user has a specific permission."""
        permissions = self.get_user_permissions(user)
        return permission in permissions
    
    def log_audit_action(self, action: str, resource_type: Optional[str] = None,
                        resource_id: Optional[str] = None, details: Optional[Dict] = None,
                        user_id: Optional[int] = None, ip_address: Optional[str] = None,
                        user_agent: Optional[str] = None):
        """Log an audit action."""
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self.db.add(audit_log)
        self.db.commit()
    
    def get_audit_logs(self, user_id: Optional[int] = None, action: Optional[str] = None,
                      page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Get audit logs with filtering and pagination."""
        query = self.db.query(AuditLog)
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action == action)
        
        query = query.order_by(AuditLog.timestamp.desc())
        
        total = query.count()
        logs = query.offset((page - 1) * page_size).limit(page_size).all()
        
        return {
            "logs": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    
    def get_roles(self) -> List[Role]:
        """Get all available roles."""
        return self.db.query(Role).all()
    
    def get_permissions(self) -> List[Permission]:
        """Get all available permissions."""
        return self.db.query(Permission).all()

    def create_role(self, name: str, description: Optional[str], permissions: List[str], is_system: bool = False) -> Role:
        """Create a new custom role."""
        existing = self.db.query(Role).filter(Role.name == name).first()
        if existing:
            raise ValueError(f"Role '{name}' already exists")
        
        valid_perms = {p.name for p in self.get_permissions()}
        invalid = [p for p in permissions if p not in valid_perms]
        if invalid:
            raise ValueError(f"Invalid permissions: {invalid}")
        role = Role(name=name, description=description, permissions=permissions, is_system=is_system)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def update_role(self, name: str, description: Optional[str] = None, permissions: Optional[List[str]] = None) -> Role:
        """Update an existing role by name."""
        role = self.db.query(Role).filter(Role.name == name).first()
        if not role:
            raise ValueError(f"Role '{name}' not found")
        if description is not None:
            role.description = description
        if permissions is not None:
            valid_perms = {p.name for p in self.get_permissions()}
            invalid = [p for p in permissions if p not in valid_perms]
            if invalid:
                raise ValueError(f"Invalid permissions: {invalid}")
            role.permissions = permissions
        self.db.commit()
        self.db.refresh(role)
        return role

    def delete_role(self, name: str) -> bool:
        """Delete a custom role by name."""
        role = self.db.query(Role).filter(Role.name == name).first()
        if not role:
            raise ValueError(f"Role '{name}' not found")
        if role.is_system:
            raise ValueError("Cannot delete system role")
        self.db.delete(role)
        self.db.commit()
        return True

    def reset_user_password(self, user_id: int, new_password: str, force_change: bool = True, updated_by: Optional[int] = None) -> User:
        """Reset a user's password and optionally force change on next login."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
        user.hashed_password = self.hash_password(new_password)
        user.must_change_password = bool(force_change)
        
        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.commit()
        self.db.refresh(user)
        self.log_audit_action(
            user_id=updated_by,
            action="user.password.reset",
            resource_type="user",
            resource_id=str(user.id),
            details={"force_change": bool(force_change)}
        )
        return user

    def unlock_user(self, user_id: int, updated_by: Optional[int] = None) -> User:
        """Unlock a user's account by clearing lock and failed attempts."""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
        user.failed_login_attempts = 0
        user.locked_until = None
        self.db.commit()
        self.db.refresh(user)
        self.log_audit_action(
            user_id=updated_by,
            action="user.unlock",
            resource_type="user",
            resource_id=str(user.id),
            details={}
        )
        return user
    
    
    def get_user_sessions(self, user_id: int, include_expired: bool = False) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        from models import UserSession
        query = self.db.query(UserSession).filter(UserSession.user_id == user_id)
        
        if not include_expired:
            query = query.filter(
                and_(
                    UserSession.is_active == True,
                    UserSession.expires_at > datetime.utcnow()
                )
            )
        
        sessions = query.order_by(UserSession.created_at.desc()).all()
        
        return [{
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "is_active": s.is_active and (s.expires_at > datetime.utcnow() if s.expires_at else False),
            "is_current": False  
        } for s in sessions]
    
    def revoke_session(self, session_id: int, user_id: int = None) -> bool:
        """Revoke a specific session."""
        from models import UserSession
        query = self.db.query(UserSession).filter(UserSession.id == session_id)
        
        if user_id:
            query = query.filter(UserSession.user_id == user_id)
        
        session = query.first()
        if not session:
            return False
        
        session.is_active = False
        self.db.commit()
        return True
    
    def revoke_all_sessions(self, user_id: int, except_session_id: int = None) -> int:
        """Revoke all sessions for a user, optionally keeping one."""
        from models import UserSession
        query = self.db.query(UserSession).filter(
            and_(
                UserSession.user_id == user_id,
                UserSession.is_active == True
            )
        )
        
        if except_session_id:
            query = query.filter(UserSession.id != except_session_id)
        
        count = query.update({"is_active": False})
        self.db.commit()
        return count
    
    
    
    def log_login_attempt(self, username: str, success: bool, user_id: int = None,
                         ip_address: str = None, user_agent: str = None,
                         failure_reason: str = None) -> None:
        """Log a login attempt."""
        from models import LoginHistory
        entry = LoginHistory(
            user_id=user_id,
            username=username,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=failure_reason
        )
        self.db.add(entry)
        self.db.commit()
    
    def get_login_history(self, user_id: int = None, page: int = 1, 
                         page_size: int = 50, success_only: bool = None) -> Dict[str, Any]:
        """Get login history with optional filtering."""
        from models import LoginHistory
        query = self.db.query(LoginHistory)
        
        if user_id:
            query = query.filter(LoginHistory.user_id == user_id)
        if success_only is not None:
            query = query.filter(LoginHistory.success == success_only)
        
        query = query.order_by(LoginHistory.timestamp.desc())
        total = query.count()
        entries = query.offset((page - 1) * page_size).limit(page_size).all()
        
        return {
            "entries": [{
                "id": e.id,
                "user_id": e.user_id,
                "username": e.username,
                "success": e.success,
                "ip_address": e.ip_address,
                "user_agent": e.user_agent,
                "failure_reason": e.failure_reason,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None
            } for e in entries],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    
    
    
    def create_api_key(self, user_id: int, name: str, permissions: List[str] = None,
                      expires_days: int = None) -> Dict[str, Any]:
        """Create a new API key for a user. Returns the raw key (only shown once)."""
        from models import UserAPIKey
        import hashlib
        
        
        raw_key = secrets.token_urlsafe(32)
        key_prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        
        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)
        
        api_key = UserAPIKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            permissions=permissions or [],
            expires_at=expires_at
        )
        
        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)
        
        return {
            "id": api_key.id,
            "name": api_key.name,
            "key": raw_key,  
            "key_prefix": key_prefix,
            "permissions": api_key.permissions,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None
        }
    
    def get_api_keys(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all API keys for a user (without revealing the actual keys)."""
        from models import UserAPIKey
        keys = self.db.query(UserAPIKey).filter(
            and_(
                UserAPIKey.user_id == user_id,
                UserAPIKey.is_active == True
            )
        ).order_by(UserAPIKey.created_at.desc()).all()
        
        return [{
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "permissions": k.permissions or [],
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "last_used_ip": k.last_used_ip,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "is_expired": k.expires_at and k.expires_at < datetime.utcnow()
        } for k in keys]
    
    def validate_api_key(self, raw_key: str) -> Optional[User]:
        """Validate an API key and return the associated user."""
        from models import UserAPIKey
        import hashlib
        
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        api_key = self.db.query(UserAPIKey).filter(
            and_(
                UserAPIKey.key_hash == key_hash,
                UserAPIKey.is_active == True
            )
        ).first()
        
        if not api_key:
            return None
        
        
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None
        
        
        api_key.last_used_at = datetime.utcnow()
        self.db.commit()
        
        return api_key.user
    
    def revoke_api_key(self, key_id: int, user_id: int = None) -> bool:
        """Revoke an API key."""
        from models import UserAPIKey
        query = self.db.query(UserAPIKey).filter(UserAPIKey.id == key_id)
        
        if user_id:
            query = query.filter(UserAPIKey.user_id == user_id)
        
        key = query.first()
        if not key:
            return False
        
        key.is_active = False
        self.db.commit()
        return True
    
    
    
    def setup_2fa(self, user_id: int) -> Dict[str, Any]:
        """Generate 2FA secret and return setup info (QR code URI)."""
        from models import UserTwoFactor
        import base64
        
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        
        
        existing = self.db.query(UserTwoFactor).filter(
            UserTwoFactor.user_id == user_id
        ).first()
        
        if existing and existing.is_enabled:
            raise ValueError("2FA is already enabled for this user")
        
        
        secret = secrets.token_hex(20)
        
        
        backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
        backup_codes_hashed = [
            pwd_context.hash(code) for code in backup_codes
        ]
        
        if existing:
            existing.secret = secret
            existing.backup_codes = backup_codes_hashed
            existing.is_enabled = False
            existing.verified_at = None
        else:
            two_factor = UserTwoFactor(
                user_id=user_id,
                secret=secret,
                backup_codes=backup_codes_hashed,
                is_enabled=False
            )
            self.db.add(two_factor)
        
        self.db.commit()
        
        
        
        import urllib.parse
        totp_uri = f"otpauth://totp/Lynx:{urllib.parse.quote(user.username)}?secret={secret}&issuer=Lynx&algorithm=SHA1&digits=6&period=30"
        
        return {
            "secret": secret,
            "totp_uri": totp_uri,
            "backup_codes": backup_codes,  
            "message": "Scan the QR code with your authenticator app, then verify with a code"
        }
    
    def verify_2fa_setup(self, user_id: int, code: str) -> bool:
        """Verify a 2FA code to complete setup."""
        from models import UserTwoFactor
        
        two_factor = self.db.query(UserTwoFactor).filter(
            UserTwoFactor.user_id == user_id
        ).first()
        
        if not two_factor:
            raise ValueError("2FA not set up for this user")
        
        if two_factor.is_enabled:
            raise ValueError("2FA is already enabled")
        
        
        if not self._verify_totp(two_factor.secret, code):
            return False
        
        
        two_factor.is_enabled = True
        two_factor.verified_at = datetime.utcnow()
        self.db.commit()
        
        self.log_audit_action(
            user_id=user_id,
            action="user.2fa.enabled",
            resource_type="user",
            resource_id=str(user_id)
        )
        
        return True
    
    def verify_2fa(self, user_id: int, code: str) -> bool:
        """Verify a 2FA code for login."""
        from models import UserTwoFactor
        
        two_factor = self.db.query(UserTwoFactor).filter(
            and_(
                UserTwoFactor.user_id == user_id,
                UserTwoFactor.is_enabled == True
            )
        ).first()
        
        if not two_factor:
            return True  
        
        
        if self._verify_totp(two_factor.secret, code):
            return True
        
        
        for i, hashed_code in enumerate(two_factor.backup_codes or []):
            if pwd_context.verify(code.upper(), hashed_code):
                
                codes = list(two_factor.backup_codes)
                codes.pop(i)
                two_factor.backup_codes = codes
                self.db.commit()
                return True
        
        return False
    
    def disable_2fa(self, user_id: int, code: str = None) -> bool:
        """Disable 2FA for a user."""
        from models import UserTwoFactor
        
        two_factor = self.db.query(UserTwoFactor).filter(
            UserTwoFactor.user_id == user_id
        ).first()
        
        if not two_factor:
            return True  
        
        
        if two_factor.is_enabled and code:
            if not self.verify_2fa(user_id, code):
                raise ValueError("Invalid 2FA code")
        
        self.db.delete(two_factor)
        self.db.commit()
        
        self.log_audit_action(
            user_id=user_id,
            action="user.2fa.disabled",
            resource_type="user",
            resource_id=str(user_id)
        )
        
        return True
    
    def get_2fa_status(self, user_id: int) -> Dict[str, Any]:
        """Get 2FA status for a user."""
        from models import UserTwoFactor
        
        two_factor = self.db.query(UserTwoFactor).filter(
            UserTwoFactor.user_id == user_id
        ).first()
        
        if not two_factor:
            return {
                "enabled": False,
                "verified": False,
                "backup_codes_remaining": 0
            }
        
        return {
            "enabled": two_factor.is_enabled,
            "verified": two_factor.verified_at is not None,
            "verified_at": two_factor.verified_at.isoformat() if two_factor.verified_at else None,
            "backup_codes_remaining": len(two_factor.backup_codes or [])
        }
    
    def _verify_totp(self, secret: str, code: str) -> bool:
        """Verify a TOTP code against a secret."""
        import hmac
        import struct
        import time
        
        try:
            
            code = code.replace(" ", "").replace("-", "")
            if len(code) != 6 or not code.isdigit():
                return False
            
            
            now = int(time.time())
            
            
            for offset in [-1, 0, 1]:
                time_counter = (now // 30) + offset
                
                
                msg = struct.pack(">Q", time_counter)
                h = hmac.new(bytes.fromhex(secret), msg, "sha1").digest()
                
                offset_byte = h[-1] & 0x0F
                truncated = struct.unpack(">I", h[offset_byte:offset_byte + 4])[0]
                truncated &= 0x7FFFFFFF
                expected = str(truncated % 1000000).zfill(6)
                
                if code == expected:
                    return True
            
            return False
        except Exception:
            return False