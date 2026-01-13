from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Permission(Base):
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)  
    description = Column(String, nullable=True)
    category = Column(String, nullable=False)  
    created_at = Column(DateTime, default=datetime.utcnow)

class Role(Base):
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)  
    description = Column(String, nullable=True)
    permissions = Column(JSON, default=list)  
    is_system = Column(Boolean, default=False)  
    created_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")  
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    last_login_ip = Column(String, nullable=True)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=False)
    
    
    full_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    language = Column(String, default="en")
    
    
    preferences = Column(JSON, default=dict)
    
    
    scheduled_tasks = relationship("ScheduledTask", back_populates="created_by_user")
    audit_logs = relationship("AuditLog", back_populates="user")
    user_sessions = relationship("UserSession", back_populates="user")

class UserSession(Base):
    __tablename__ = "user_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String, unique=True, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    
    
    user = relationship("User", back_populates="user_sessions")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)  
    resource_type = Column(String, nullable=True)  
    resource_id = Column(String, nullable=True)  
    details = Column(JSON, nullable=True)  
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    
    user = relationship("User", back_populates="audit_logs")

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    task_type = Column(String, nullable=False)  
    server_name = Column(String, nullable=True)  
    cron_expression = Column(String, nullable=False)  
    command = Column(String, nullable=True)  
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    
    
    created_by = Column(Integer, ForeignKey("users.id"))
    created_by_user = relationship("User", back_populates="scheduled_tasks")
    integrity_reports = relationship("IntegrityReport", back_populates="task", cascade="all, delete-orphan")




class BackupTask(Base):
    __tablename__ = "backup_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False)
    backup_file = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    compression_type = Column(String, default="zip")
    retention_days = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    
    is_auto_created = Column(Boolean, default=False)

class IntegrityReport(Base):
    __tablename__ = "integrity_reports"

    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=True)
    status = Column(String, nullable=False)
    issues = Column(JSON, default=list)
    metadata_payload = Column("metadata", JSON, nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    task_id = Column(Integer, ForeignKey("scheduled_tasks.id"), nullable=True)

    task = relationship("ScheduledTask", back_populates="integrity_reports")

class ServerPerformance(Base):
    __tablename__ = "server_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    
    tps = Column(String, nullable=True)  
    cpu_usage = Column(String, nullable=True)
    memory_usage = Column(String, nullable=True)
    memory_total = Column(String, nullable=True)
    player_count = Column(Integer, default=0)
    
    
    metrics = Column(JSON, nullable=True)

class PlayerAction(Base):
    __tablename__ = "player_actions"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False)
    player_name = Column(String, nullable=False)
    action_type = Column(String, nullable=False)  
    reason = Column(String, nullable=True)
    performed_by = Column(Integer, ForeignKey("users.id"))
    performed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  


class UserAPIKey(Base):
    """API keys for programmatic access"""
    __tablename__ = "user_api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)  
    key_hash = Column(String, nullable=False)  
    key_prefix = Column(String, nullable=False)  
    permissions = Column(JSON, default=list)  
    expires_at = Column(DateTime, nullable=True)  
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    
    user = relationship("User", backref="api_keys")


class UserTwoFactor(Base):
    """Two-factor authentication (TOTP) for users"""
    __tablename__ = "user_two_factor"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    secret = Column(String, nullable=False)  
    is_enabled = Column(Boolean, default=False)  
    backup_codes = Column(JSON, default=list)  
    created_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    
    
    user = relationship("User", backref="two_factor")


class LoginHistory(Base):
    """Track all login attempts for security monitoring"""
    __tablename__ = "login_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  
    username = Column(String, nullable=False)  
    success = Column(Boolean, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)  
    location = Column(String, nullable=True)  
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    
    user = relationship("User", backref="login_history")