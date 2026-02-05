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


# ==================== PLATFORM FEATURES ====================

# Multi-Tenancy & Organizations
class Organization(Base):
    """Organization/Team entity for multi-tenancy"""
    __tablename__ = "organizations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    billing_email = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    owner = relationship("User", backref="owned_organizations")
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    quotas = relationship("ResourceQuota", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    """Organization membership with roles"""
    __tablename__ = "organization_members"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # owner, admin, member, viewer
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", backref="organization_memberships")


class OrganizationInvite(Base):
    """Pending organization invitations"""
    __tablename__ = "organization_invites"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    invited_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    
    organization = relationship("Organization", backref="invites")
    inviter = relationship("User", foreign_keys=[invited_by], backref="sent_invites")
    invited_user = relationship("User", foreign_keys=[invited_user_id], backref="received_invites")


class ResourceQuota(Base):
    """Resource quotas for organizations"""
    __tablename__ = "resource_quotas"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    quota_type = Column(String, nullable=False)  # servers, storage, ram, monthly_cost
    limit = Column(Float, nullable=False)
    used = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    organization = relationship("Organization", back_populates="quotas")


class UsageRecord(Base):
    """Resource usage tracking for billing"""
    __tablename__ = "usage_records"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    resource_type = Column(String, nullable=False)  # server, storage, ram
    amount = Column(Float, nullable=False)
    cost = Column(Float, default=0.0)
    usage_metadata = Column(JSON, default=dict)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    organization = relationship("Organization", backref="usage_records")


# API Management & Rate Limiting
class APIRateLimit(Base):
    """Rate limiting rules for API endpoints"""
    __tablename__ = "api_rate_limits"
    
    id = Column(Integer, primary_key=True, index=True)
    endpoint_pattern = Column(String, nullable=False)  # e.g., "/servers/*"
    requests_per_period = Column(Integer, nullable=False)
    period = Column(String, nullable=False)  # second, minute, hour, day
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # None = global
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", backref="rate_limits")
    api_key = relationship("UserAPIKey", backref="rate_limits")


class APIUsageLog(Base):
    """API request logging for analytics"""
    __tablename__ = "api_usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id"), nullable=True)
    endpoint = Column(String, nullable=False, index=True)
    method = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Integer, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    user = relationship("User", backref="api_usage")
    api_key = relationship("UserAPIKey", backref="usage_logs")


class Webhook(Base):
    """Webhook configurations"""
    __tablename__ = "webhooks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    url = Column(String, nullable=False)
    events = Column(Text, nullable=False)  # JSON array of event types
    secret = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_delivery = Column(DateTime, nullable=True)
    
    user = relationship("User", backref="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")


class WebhookDelivery(Base):
    """Webhook delivery history"""
    __tablename__ = "webhook_deliveries"
    
    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False)
    event = Column(String, nullable=False)
    payload = Column(Text, nullable=False)  # JSON payload
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    delivered_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    webhook = relationship("Webhook", back_populates="deliveries")


# Plugin System
class Plugin(Base):
    """Plugin marketplace entries"""
    __tablename__ = "plugins"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=False)  # server_type, integration, theme, utility
    author = Column(String, nullable=False)
    publisher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repository_url = Column(String, nullable=True)
    documentation_url = Column(String, nullable=True)
    latest_version = Column(String, nullable=False)
    download_count = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    publisher = relationship("User", backref="published_plugins")


class PluginVersion(Base):
    """Plugin version history"""
    __tablename__ = "plugin_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    version = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    checksum = Column(String, nullable=False)
    changelog = Column(Text, nullable=True)
    min_lynx_version = Column(String, nullable=True)
    max_lynx_version = Column(String, nullable=True)
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    plugin = relationship("Plugin", backref="versions")


class PluginInstallation(Base):
    """User plugin installations"""
    __tablename__ = "plugin_installations"
    
    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    version = Column(String, nullable=False)
    is_enabled = Column(Boolean, default=True)
    installed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    plugin = relationship("Plugin", backref="installations")
    user = relationship("User", backref="plugin_installations")


class PluginReview(Base):
    """Plugin reviews and ratings"""
    __tablename__ = "plugin_reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    plugin = relationship("Plugin", backref="reviews")
    user = relationship("User", backref="plugin_reviews")


# Real-Time Communication
class Notification(Base):
    """User notifications"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(String, nullable=False)  # info, warning, error, success
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, default=dict)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)
    
    user = relationship("User", backref="notifications")


# Advanced API Features
class Task(Base):
    """Long-running task tracking"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_type = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pending, running, completed, failed, cancelled
    total_steps = Column(Integer, default=0)
    completed_steps = Column(Integer, default=0)
    result = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", backref="tasks")


# ==================== HIGH-IMPACT FEATURES ====================

# 1. Server Performance Monitoring & Analytics
class ServerMetrics(Base):
    """Real-time and historical server performance metrics"""
    __tablename__ = "server_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # System metrics
    cpu_percent = Column(Float, nullable=True)
    memory_used_mb = Column(Float, nullable=True)
    memory_total_mb = Column(Float, nullable=True)
    memory_percent = Column(Float, nullable=True)
    disk_used_gb = Column(Float, nullable=True)
    disk_total_gb = Column(Float, nullable=True)
    disk_percent = Column(Float, nullable=True)
    
    # Network metrics
    network_rx_bytes = Column(Integer, nullable=True)
    network_tx_bytes = Column(Integer, nullable=True)
    network_rx_rate = Column(Float, nullable=True)  # bytes/sec
    network_tx_rate = Column(Float, nullable=True)  # bytes/sec
    
    # Game server metrics
    player_count = Column(Integer, default=0)
    tps = Column(Float, nullable=True)  # Minecraft TPS
    
    # Additional metrics (JSON for extensibility)
    extra_metrics = Column(JSON, nullable=True)


class PerformanceAlert(Base):
    """Alerts triggered when performance metrics exceed thresholds"""
    __tablename__ = "performance_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    alert_type = Column(String, nullable=False)  # cpu, memory, disk, crash, etc.
    severity = Column(String, default="warning")  # info, warning, critical
    message = Column(Text, nullable=False)
    threshold_value = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    is_resolved = Column(Boolean, default=False)
    notification_sent = Column(Boolean, default=False)
    
    # JSON for alert details
    details = Column(JSON, nullable=True)


class CrashReport(Base):
    """Server crash detection and logs"""
    __tablename__ = "crash_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    crash_time = Column(DateTime, default=datetime.utcnow)
    crash_log = Column(Text, nullable=True)
    stack_trace = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)
    auto_restarted = Column(Boolean, default=False)
    restart_time = Column(DateTime, nullable=True)
    
    # Analysis results
    probable_cause = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)


# 2. Multi-Server Management
class ServerGroup(Base):
    """Server groups/tags for organization"""
    __tablename__ = "server_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, nullable=True)  # Hex color for UI
    icon = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Members relationship
    servers = relationship("ServerGroupMember", back_populates="group", cascade="all, delete-orphan")


class ServerGroupMember(Base):
    """Many-to-many relationship between servers and groups"""
    __tablename__ = "server_group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("server_groups.id"), nullable=False)
    server_name = Column(String, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)
    added_by = Column(Integer, ForeignKey("users.id"))
    
    group = relationship("ServerGroup", back_populates="servers")


class BulkOperation(Base):
    """Track bulk operations on multiple servers"""
    __tablename__ = "bulk_operations"
    
    id = Column(Integer, primary_key=True, index=True)
    operation_type = Column(String, nullable=False)  # start, stop, restart, backup, etc.
    server_names = Column(JSON, nullable=False)  # List of server names
    status = Column(String, default="pending")  # pending, running, completed, failed
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    started_by = Column(Integer, ForeignKey("users.id"))
    
    # Results for each server
    results = Column(JSON, nullable=True)  # {server_name: {status, message}}
    total_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)


class ServerClone(Base):
    """Track server cloning operations"""
    __tablename__ = "server_clones"
    
    id = Column(Integer, primary_key=True, index=True)
    source_server = Column(String, nullable=False)
    target_server = Column(String, nullable=False)
    clone_type = Column(String, default="full")  # full, config_only, world_only
    status = Column(String, default="pending")
    progress_percent = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    cloned_by = Column(Integer, ForeignKey("users.id"))
    error_message = Column(Text, nullable=True)


# 3. Enhanced Modpack Features
class ModVersion(Base):
    """Track installed mod versions and updates"""
    __tablename__ = "mod_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    mod_id = Column(String, nullable=False)  # CurseForge/Modrinth ID
    mod_name = Column(String, nullable=False)
    current_version = Column(String, nullable=False)
    latest_version = Column(String, nullable=True)
    update_available = Column(Boolean, default=False)
    mod_source = Column(String, nullable=False)  # curseforge, modrinth, manual
    file_name = Column(String, nullable=False)
    download_url = Column(String, nullable=True)
    
    # Metadata
    minecraft_version = Column(String, nullable=True)
    mod_loader = Column(String, nullable=True)  # fabric, forge, neoforge
    dependencies = Column(JSON, nullable=True)  # List of dependency mod IDs
    last_checked = Column(DateTime, default=datetime.utcnow)
    installed_at = Column(DateTime, default=datetime.utcnow)


class ModConflict(Base):
    """Detected mod conflicts and incompatibilities"""
    __tablename__ = "mod_conflicts"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    mod_a = Column(String, nullable=False)
    mod_b = Column(String, nullable=False)
    conflict_type = Column(String, nullable=False)  # incompatible, duplicate, version_mismatch
    severity = Column(String, default="warning")  # info, warning, critical
    description = Column(Text, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)


class ClientModpack(Base):
    """Generated client modpack exports"""
    __tablename__ = "client_modpacks"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    minecraft_version = Column(String, nullable=True)
    mod_loader = Column(String, nullable=True)
    mod_count = Column(Integer, default=0)
    generated_at = Column(DateTime, default=datetime.utcnow)
    generated_by = Column(Integer, ForeignKey("users.id"))
    download_count = Column(Integer, default=0)


# 4. Advanced Backup System
class BackupConfig(Base):
    """Per-server backup configuration"""
    __tablename__ = "backup_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, unique=True, nullable=False)
    
    # Backup types
    backup_type = Column(String, default="full")  # full, incremental, world_only
    compression_level = Column(Integer, default=6)  # 0-9 for gzip
    compression_format = Column(String, default="gzip")  # gzip, bzip2, xz, zip
    
    # Retention
    retention_count = Column(Integer, default=10)
    retention_days = Column(Integer, default=30)
    
    # Cloud storage
    cloud_enabled = Column(Boolean, default=False)
    cloud_provider = Column(String, nullable=True)  # s3, gcs, azure, dropbox
    cloud_config = Column(JSON, nullable=True)  # Provider-specific config
    
    # Verification
    verify_backups = Column(Boolean, default=True)
    last_verified = Column(DateTime, nullable=True)
    
    # Exclusions
    exclude_patterns = Column(JSON, nullable=True)  # List of glob patterns
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BackupHistory(Base):
    """Extended backup metadata and tracking"""
    __tablename__ = "backup_history"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    backup_file = Column(String, nullable=False)
    backup_type = Column(String, default="full")
    
    # Size and timing
    file_size = Column(Integer, nullable=False)
    compression_ratio = Column(Float, nullable=True)
    backup_duration_seconds = Column(Float, nullable=True)
    
    # Storage locations
    local_path = Column(String, nullable=True)
    cloud_path = Column(String, nullable=True)
    cloud_provider = Column(String, nullable=True)
    
    # Verification
    is_verified = Column(Boolean, default=False)
    verification_status = Column(String, nullable=True)  # passed, failed, pending
    verification_date = Column(DateTime, nullable=True)
    checksum = Column(String, nullable=True)  # SHA256
    
    # Metadata
    minecraft_version = Column(String, nullable=True)
    world_size_mb = Column(Float, nullable=True)
    player_count_snapshot = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_auto_backup = Column(Boolean, default=False)
    
    # Parent backup for incremental
    parent_backup_id = Column(Integer, ForeignKey("backup_history.id"), nullable=True)


# 5. Player Experience Enhancements
class PlayerProfile(Base):
    """Extended player statistics and profiles"""
    __tablename__ = "player_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    player_name = Column(String, nullable=False)
    player_uuid = Column(String, nullable=True, index=True)
    
    # Statistics
    first_joined = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    total_playtime_minutes = Column(Integer, default=0)
    session_count = Column(Integer, default=0)
    
    # Status
    is_online = Column(Boolean, default=False)
    is_whitelisted = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    is_op = Column(Boolean, default=False)
    
    # Additional data
    last_ip = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # Custom tags
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TemporaryBan(Base):
    """Temporary bans with auto-expiration"""
    __tablename__ = "temporary_bans"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    player_name = Column(String, nullable=False)
    player_uuid = Column(String, nullable=True)
    
    reason = Column(Text, nullable=True)
    banned_by = Column(Integer, ForeignKey("users.id"))
    banned_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    is_active = Column(Boolean, default=True)
    unbanned_at = Column(DateTime, nullable=True)
    unbanned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Auto-unban tracking
    auto_unbanned = Column(Boolean, default=False)


class PlayerSession(Base):
    """Track player login/logout sessions"""
    __tablename__ = "player_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    server_name = Column(String, nullable=False, index=True)
    player_name = Column(String, nullable=False)
    player_uuid = Column(String, nullable=True)
    
    login_time = Column(DateTime, default=datetime.utcnow)
    logout_time = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    
    ip_address = Column(String, nullable=True)


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