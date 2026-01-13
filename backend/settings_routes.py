"""System settings API for Lynx."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from pathlib import Path
import json
import os
import shutil
import subprocess

from auth import require_admin, require_auth
from models import User
from config import SERVERS_ROOT

router = APIRouter(prefix="/settings", tags=["settings"])

SETTINGS_FILE = SERVERS_ROOT.parent / "lynx_settings.json"


DEFAULT_SETTINGS = {
    
    "backup": {
        "enabled": True,
        "interval_hours": 24,
        "retention_days": 7,
        "location": "/data/backups",
        "compress": True,
        "include_worlds": True,
        "include_mods": True,
        "include_configs": True,
        "max_backup_size_gb": 50
    },
    
    "server_defaults": {
        "auto_start": False,
        "restart_on_crash": True,
        "crash_restart_delay": 30,
        "max_crash_restarts": 3,
        "memory_min_mb": 1024,
        "memory_max_mb": 4096,
        "java_args": "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200"
    },
    
    "notifications": {
        "webhook_url": "",
        "webhook_type": "discord",  
        "email_enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
        "smtp_to": "",
        "alert_server_crash": True,
        "alert_server_start": False,
        "alert_server_stop": False,
        "alert_high_cpu": True,
        "alert_high_memory": True,
        "alert_disk_space": True,
        "cpu_threshold": 90,
        "memory_threshold": 90,
        "disk_threshold": 90
    },
    
    "security": {
        "session_timeout_hours": 24,
        "max_sessions_per_user": 5,
        "require_strong_password": True,
        "min_password_length": 8,
        "lockout_attempts": 5,
        "lockout_duration_minutes": 15,
        "two_factor_enabled": False
    },
    
    "appearance": {
        "theme": "dark",
        "accent_color": "blue",
        "timezone": "UTC",
        "date_format": "YYYY-MM-DD",
        "time_format": "24h"
    },
    
    "performance": {
        "api_rate_limit": 100,
        "websocket_enabled": True,
        "log_level": "INFO",
        "log_retention_days": 30,
        "cache_enabled": True,
        "cache_ttl_seconds": 300
    },
    
    "docker": {
        "network_mode": "bridge",
        "auto_pull_images": True,
        "cleanup_unused_images": False,
        "container_restart_policy": "unless-stopped",
        "resource_limits_enabled": True
    }
}


def load_settings() -> Dict[str, Any]:
    """Load settings from file, merging with defaults."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  
    try:
        if SETTINGS_FILE.exists():
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            
            for key, value in saved.items():
                if key in settings and isinstance(settings[key], dict) and isinstance(value, dict):
                    settings[key].update(value)
                else:
                    settings[key] = value
    except Exception as e:
        print(f"Warning: Could not load settings: {e}")
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to file."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


def send_notification(event_type: str, title: str, message: str, color: int = 5814783) -> bool:
    """
    Send a notification via configured webhook if the event type is enabled.
    
    event_type: One of 'server_crash', 'server_start', 'server_stop', 'high_cpu', 'high_memory', 'disk_space'
    Returns True if sent successfully, False otherwise.
    """
    import requests
    import datetime
    
    settings = load_settings()
    notif = settings.get("notifications", {})
    webhook_url = notif.get("webhook_url", "")
    webhook_type = notif.get("webhook_type", "discord")
    
    
    if not webhook_url:
        return False
    
    
    alert_key = f"alert_{event_type}"
    if not notif.get(alert_key, False):
        return False
    
    try:
        if webhook_type == "discord":
            payload = {
                "embeds": [{
                    "title": title,
                    "description": message,
                    "color": color,
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }]
            }
        elif webhook_type == "slack":
            payload = {
                "text": f"*{title}*\n{message}"
            }
        else:
            payload = {
                "title": title,
                "message": message,
                "type": event_type
            }
        
        r = requests.post(webhook_url, json=payload, timeout=10)
        return r.ok
    except Exception as e:
        print(f"Failed to send notification: {e}")
        return False


def get_server_defaults() -> Dict[str, Any]:
    """Get server default settings for creating new servers."""
    settings = load_settings()
    return settings.get("server_defaults", DEFAULT_SETTINGS["server_defaults"])


def get_backup_settings() -> Dict[str, Any]:
    """Get backup settings."""
    settings = load_settings()
    return settings.get("backup", DEFAULT_SETTINGS["backup"])


class SettingsUpdate(BaseModel):
    """Partial settings update."""
    backup: Optional[Dict[str, Any]] = None
    server_defaults: Optional[Dict[str, Any]] = None
    notifications: Optional[Dict[str, Any]] = None
    security: Optional[Dict[str, Any]] = None
    appearance: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None
    docker: Optional[Dict[str, Any]] = None


@router.get("")
def get_settings(current_user: User = Depends(require_auth)):
    """Get all system settings."""
    return load_settings()


@router.put("")
def update_settings(updates: SettingsUpdate, current_user: User = Depends(require_admin)):
    """Update system settings (admin only)."""
    settings = load_settings()
    update_dict = updates.dict(exclude_none=True)
    
    for category, values in update_dict.items():
        if category in settings and isinstance(values, dict):
            settings[category].update(values)
        else:
            settings[category] = values
    
    save_settings(settings)
    return {"status": "ok", "settings": settings}


@router.post("/reset")
def reset_settings(current_user: User = Depends(require_admin)):
    """Reset all settings to defaults."""
    save_settings(DEFAULT_SETTINGS)
    return {"status": "ok", "message": "Settings reset to defaults"}


@router.post("/export")
def export_settings(current_user: User = Depends(require_admin)):
    """Export settings as JSON."""
    return load_settings()


@router.post("/import")
def import_settings(settings: Dict[str, Any], current_user: User = Depends(require_admin)):
    """Import settings from JSON."""
    
    for key in settings:
        if key not in DEFAULT_SETTINGS:
            raise HTTPException(status_code=400, detail=f"Unknown settings category: {key}")
    save_settings(settings)
    return {"status": "ok", "message": "Settings imported successfully"}



@router.get("/system/storage")
def get_storage_info(current_user: User = Depends(require_auth)):
    """Get storage usage information."""
    import psutil
    
    result = {
        "disk": {},
        "servers": {},
        "backups": {}
    }
    
    
    try:
        disk = psutil.disk_usage('/')
        result["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": round((disk.used / disk.total) * 100, 1)
        }
    except Exception as e:
        result["disk"]["error"] = str(e)
    
    
    try:
        if SERVERS_ROOT.exists():
            total_size = sum(f.stat().st_size for f in SERVERS_ROOT.rglob('*') if f.is_file())
            result["servers"] = {
                "path": str(SERVERS_ROOT),
                "size_gb": round(total_size / (1024**3), 2),
                "count": len([d for d in SERVERS_ROOT.iterdir() if d.is_dir()])
            }
    except Exception as e:
        result["servers"]["error"] = str(e)
    
    
    settings = load_settings()
    backup_path = Path(settings["backup"]["location"])
    try:
        if backup_path.exists():
            total_size = sum(f.stat().st_size for f in backup_path.rglob('*') if f.is_file())
            result["backups"] = {
                "path": str(backup_path),
                "size_gb": round(total_size / (1024**3), 2),
                "count": len(list(backup_path.glob("*.zip"))) + len(list(backup_path.glob("*.tar.gz")))
            }
        else:
            result["backups"] = {"path": str(backup_path), "size_gb": 0, "count": 0}
    except Exception as e:
        result["backups"]["error"] = str(e)
    
    return result


@router.post("/system/cleanup-logs")
def cleanup_logs(current_user: User = Depends(require_admin)):
    """Clean up old log files from servers."""
    cleaned = 0
    errors = []
    settings = load_settings()
    retention_days = settings["performance"].get("log_retention_days", 30)
    
    import time
    cutoff = time.time() - (retention_days * 86400)
    
    try:
        for server_dir in SERVERS_ROOT.iterdir():
            if not server_dir.is_dir():
                continue
            logs_dir = server_dir / "logs"
            if not logs_dir.exists():
                continue
            for log_file in logs_dir.glob("*.log*"):
                try:
                    if log_file.stat().st_mtime < cutoff:
                        log_file.unlink()
                        cleaned += 1
                except Exception as e:
                    errors.append(f"{server_dir.name}/{log_file.name}: {e}")
    except Exception as e:
        errors.append(f"Scan error: {e}")
    
    return {"cleaned": cleaned, "errors": errors[:20]}


@router.post("/system/cleanup-backups")
def cleanup_backups(current_user: User = Depends(require_admin)):
    """Clean up old backups based on retention policy."""
    cleaned = 0
    freed_mb = 0
    errors = []
    settings = load_settings()
    retention_days = settings["backup"].get("retention_days", 7)
    backup_path = Path(settings["backup"]["location"])
    
    import time
    cutoff = time.time() - (retention_days * 86400)
    
    try:
        if backup_path.exists():
            for backup_file in list(backup_path.glob("*.zip")) + list(backup_path.glob("*.tar.gz")):
                try:
                    if backup_file.stat().st_mtime < cutoff:
                        size_mb = backup_file.stat().st_size / (1024**2)
                        backup_file.unlink()
                        cleaned += 1
                        freed_mb += size_mb
                except Exception as e:
                    errors.append(f"{backup_file.name}: {e}")
    except Exception as e:
        errors.append(f"Cleanup error: {e}")
    
    return {"cleaned": cleaned, "freed_mb": round(freed_mb, 2), "errors": errors[:20]}


@router.post("/notifications/test")
def test_notification(current_user: User = Depends(require_admin)):
    """Send a test notification."""
    import requests
    
    settings = load_settings()
    notif = settings.get("notifications", {})
    webhook_url = notif.get("webhook_url", "")
    webhook_type = notif.get("webhook_type", "discord")
    
    if not webhook_url:
        raise HTTPException(status_code=400, detail="No webhook URL configured")
    
    try:
        if webhook_type == "discord":
            payload = {
                "embeds": [{
                    "title": "🔔 Lynx Test Notification",
                    "description": "This is a test notification from Lynx. If you see this, notifications are working correctly!",
                    "color": 5814783,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat()
                }]
            }
        elif webhook_type == "slack":
            payload = {
                "text": "🔔 *Lynx Test Notification*\nThis is a test notification from Lynx. If you see this, notifications are working correctly!"
            }
        else:
            payload = {
                "title": "Lynx Test Notification",
                "message": "This is a test notification from Lynx.",
                "type": "test"
            }
        
        r = requests.post(webhook_url, json=payload, timeout=10)
        if not r.ok:
            raise HTTPException(status_code=400, detail=f"Webhook returned {r.status_code}: {r.text[:200]}")
        
        return {"status": "ok", "message": "Test notification sent successfully"}
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to send notification: {e}")


@router.get("/java")
def get_java_versions(current_user: User = Depends(require_auth)):
    """Get available Java versions on the system."""
    java_versions = []
    
    
    java_paths = [
        "/opt/java/java8/bin/java",
        "/opt/java/java11/bin/java",
        "/opt/java/java17/bin/java",
        "/opt/java/java21/bin/java",
        "/usr/lib/jvm/java-8-openjdk/bin/java",
        "/usr/lib/jvm/java-11-openjdk/bin/java",
        "/usr/lib/jvm/java-17-openjdk/bin/java",
        "/usr/lib/jvm/java-21-openjdk/bin/java",
    ]
    
    
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        java_paths.insert(0, f"{java_home}/bin/java")
    
    for path in java_paths:
        if os.path.exists(path):
            try:
                result = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
                version_line = result.stderr.split('\n')[0] if result.stderr else result.stdout.split('\n')[0]
                java_versions.append({
                    "path": path,
                    "version": version_line,
                    "available": True
                })
            except Exception:
                java_versions.append({
                    "path": path,
                    "version": "Unknown",
                    "available": True
                })
    
    return {"versions": java_versions}
