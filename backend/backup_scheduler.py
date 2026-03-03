"""
Backup Scheduler — Automated scheduled backups with S3/B2/SFTP remote upload,
retention policies, and per-server backup configuration.
"""
import threading
import time
import logging
import json
import hashlib
import shutil
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from config import SERVERS_ROOT
from backup_manager import create_backup, list_backups, _get_backups_root

logger = logging.getLogger(__name__)

# Persistent config file
_CONFIG_FILE = SERVERS_ROOT.parent / "backup_schedules.json"
_running = False
_thread: Optional[threading.Thread] = None


def _load_config() -> Dict[str, Any]:
    """Load backup schedule config from disk."""
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"schedules": {}, "remote": {}}


def _save_config(cfg: Dict[str, Any]):
    """Save backup schedule config to disk."""
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Public API ──────────────────────────────────────────────────────────────

def get_all_schedules() -> Dict[str, Any]:
    """Return all backup schedules keyed by server name."""
    cfg = _load_config()
    return cfg.get("schedules", {})


def get_schedule(server_name: str) -> Dict[str, Any]:
    """Return backup schedule for a specific server."""
    cfg = _load_config()
    return cfg.get("schedules", {}).get(server_name, {})


def set_schedule(server_name: str, schedule: Dict[str, Any]):
    """Create or update a backup schedule for a server."""
    cfg = _load_config()
    if "schedules" not in cfg:
        cfg["schedules"] = {}
    cfg["schedules"][server_name] = {
        "enabled": schedule.get("enabled", True),
        "interval_hours": schedule.get("interval_hours", 24),
        "retention_count": schedule.get("retention_count", 10),
        "retention_days": schedule.get("retention_days", 30),
        "remote_upload": schedule.get("remote_upload", False),
        "compression": schedule.get("compression", "zip"),
        "last_backup": schedule.get("last_backup"),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_config(cfg)


def delete_schedule(server_name: str):
    """Remove a backup schedule."""
    cfg = _load_config()
    cfg.get("schedules", {}).pop(server_name, None)
    _save_config(cfg)


def get_remote_config() -> Dict[str, Any]:
    """Return remote storage (S3/B2/SFTP) configuration."""
    cfg = _load_config()
    remote = cfg.get("remote", {})
    # Mask secrets for API response
    safe = dict(remote)
    for key in ("secret_key", "password", "private_key"):
        if key in safe and safe[key]:
            safe[key] = "••••••••"
    return safe


def set_remote_config(remote: Dict[str, Any]):
    """Save remote storage configuration."""
    cfg = _load_config()
    existing = cfg.get("remote", {})
    # Don't overwrite secrets if masked value is sent back
    for key in ("secret_key", "password", "private_key"):
        if remote.get(key) == "••••••••" and key in existing:
            remote[key] = existing[key]
    cfg["remote"] = remote
    _save_config(cfg)


def test_remote_connection() -> Dict[str, Any]:
    """Test the remote storage connection."""
    cfg = _load_config()
    remote = cfg.get("remote", {})
    provider = remote.get("provider", "")

    if provider == "s3":
        return _test_s3(remote)
    elif provider == "b2":
        return _test_b2(remote)
    elif provider == "sftp":
        return _test_sftp(remote)
    else:
        return {"ok": False, "error": f"Unknown provider: {provider}"}


# ── Remote Upload Implementations ──────────────────────────────────────────

def _upload_to_remote(local_path: Path, server_name: str) -> Dict[str, Any]:
    """Upload a backup file to remote storage."""
    cfg = _load_config()
    remote = cfg.get("remote", {})
    provider = remote.get("provider", "")

    if provider == "s3":
        return _upload_s3(remote, local_path, server_name)
    elif provider == "b2":
        return _upload_b2(remote, local_path, server_name)
    elif provider == "sftp":
        return _upload_sftp(remote, local_path, server_name)
    else:
        return {"ok": False, "error": f"Unknown remote provider: {provider}"}


def _upload_s3(cfg: dict, local_path: Path, server_name: str) -> dict:
    """Upload to S3-compatible storage (AWS S3, MinIO, Wasabi, etc.)."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        s3_cfg = {}
        if cfg.get("endpoint_url"):
            s3_cfg["endpoint_url"] = cfg["endpoint_url"]

        client = boto3.client(
            "s3",
            aws_access_key_id=cfg.get("access_key"),
            aws_secret_access_key=cfg.get("secret_key"),
            region_name=cfg.get("region", "us-east-1"),
            config=BotoConfig(signature_version="s3v4"),
            **s3_cfg,
        )
        bucket = cfg.get("bucket", "lynx-backups")
        prefix = cfg.get("prefix", "backups").strip("/")
        key = f"{prefix}/{server_name}/{local_path.name}"

        client.upload_file(str(local_path), bucket, key)
        return {"ok": True, "remote_path": f"s3://{bucket}/{key}"}
    except ImportError:
        return {"ok": False, "error": "boto3 not installed. Run: pip install boto3"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _upload_b2(cfg: dict, local_path: Path, server_name: str) -> dict:
    """Upload to Backblaze B2 (uses S3-compatible API)."""
    b2_cfg = dict(cfg)
    if not b2_cfg.get("endpoint_url"):
        b2_cfg["endpoint_url"] = f"https://s3.{cfg.get('region', 'us-west-004')}.backblazeb2.com"
    return _upload_s3(b2_cfg, local_path, server_name)


def _upload_sftp(cfg: dict, local_path: Path, server_name: str) -> dict:
    """Upload to SFTP server."""
    try:
        import paramiko

        transport = paramiko.Transport((cfg.get("host", "localhost"), cfg.get("port", 22)))
        if cfg.get("private_key"):
            key = paramiko.RSAKey.from_private_key_file(cfg["private_key"])
            transport.connect(username=cfg.get("username", "backup"), pkey=key)
        else:
            transport.connect(username=cfg.get("username", "backup"), password=cfg.get("password", ""))

        sftp = paramiko.SFTPClient.from_transport(transport)
        remote_dir = f"{cfg.get('remote_path', '/backups')}/{server_name}"
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            # Create directories recursively
            parts = remote_dir.strip("/").split("/")
            current = ""
            for p in parts:
                current += f"/{p}"
                try:
                    sftp.stat(current)
                except FileNotFoundError:
                    sftp.mkdir(current)

        remote_file = f"{remote_dir}/{local_path.name}"
        sftp.put(str(local_path), remote_file)
        sftp.close()
        transport.close()
        return {"ok": True, "remote_path": f"sftp://{cfg.get('host')}{remote_file}"}
    except ImportError:
        return {"ok": False, "error": "paramiko not installed. Run: pip install paramiko"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _test_s3(cfg: dict) -> dict:
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        s3_cfg = {}
        if cfg.get("endpoint_url"):
            s3_cfg["endpoint_url"] = cfg["endpoint_url"]
        client = boto3.client(
            "s3",
            aws_access_key_id=cfg.get("access_key"),
            aws_secret_access_key=cfg.get("secret_key"),
            region_name=cfg.get("region", "us-east-1"),
            config=BotoConfig(signature_version="s3v4"),
            **s3_cfg,
        )
        bucket = cfg.get("bucket", "lynx-backups")
        client.head_bucket(Bucket=bucket)
        return {"ok": True, "message": f"Connected to bucket: {bucket}"}
    except ImportError:
        return {"ok": False, "error": "boto3 not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _test_b2(cfg: dict) -> dict:
    b2_cfg = dict(cfg)
    if not b2_cfg.get("endpoint_url"):
        b2_cfg["endpoint_url"] = f"https://s3.{cfg.get('region', 'us-west-004')}.backblazeb2.com"
    return _test_s3(b2_cfg)


def _test_sftp(cfg: dict) -> dict:
    try:
        import paramiko
        transport = paramiko.Transport((cfg.get("host", "localhost"), cfg.get("port", 22)))
        if cfg.get("private_key"):
            key = paramiko.RSAKey.from_private_key_file(cfg["private_key"])
            transport.connect(username=cfg.get("username"), pkey=key)
        else:
            transport.connect(username=cfg.get("username"), password=cfg.get("password"))
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.listdir(cfg.get("remote_path", "/"))
        sftp.close()
        transport.close()
        return {"ok": True, "message": f"Connected to {cfg.get('host')}"}
    except ImportError:
        return {"ok": False, "error": "paramiko not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Retention ──────────────────────────────────────────────────────────────

def _apply_retention(server_name: str, schedule: dict):
    """Remove old backups beyond retention limits."""
    try:
        backups = list_backups(server_name)
        max_count = schedule.get("retention_count", 10)
        max_days = schedule.get("retention_days", 30)
        cutoff = time.time() - (max_days * 86400)

        backup_dir = _get_backups_root() / server_name
        removed = 0

        # Sort by date (newest first)
        backups_sorted = sorted(backups, key=lambda b: b.get("modified", 0), reverse=True)

        for idx, bk in enumerate(backups_sorted):
            should_remove = False
            if idx >= max_count:
                should_remove = True
            if bk.get("modified", 0) < cutoff:
                should_remove = True
            if should_remove:
                try:
                    fp = backup_dir / bk["file"]
                    if fp.exists():
                        fp.unlink()
                        removed += 1
                except Exception:
                    pass

        if removed:
            logger.info(f"Retention: removed {removed} old backups for {server_name}")
    except Exception as e:
        logger.error(f"Retention error for {server_name}: {e}")


# ── Scheduler Loop ─────────────────────────────────────────────────────────

def _scheduler_loop():
    """Background thread that checks schedules and runs backups."""
    global _running
    while _running:
        try:
            cfg = _load_config()
            schedules = cfg.get("schedules", {})
            now = datetime.utcnow()

            for server_name, sched in schedules.items():
                if not sched.get("enabled", True):
                    continue

                interval_hours = sched.get("interval_hours", 24)
                last_backup_str = sched.get("last_backup")

                should_backup = False
                if not last_backup_str:
                    should_backup = True
                else:
                    try:
                        last_dt = datetime.fromisoformat(last_backup_str)
                        if now - last_dt >= timedelta(hours=interval_hours):
                            should_backup = True
                    except Exception:
                        should_backup = True

                if should_backup:
                    try:
                        logger.info(f"Scheduled backup starting for: {server_name}")
                        compression = sched.get("compression", "zip")
                        result = create_backup(server_name, compression=compression)
                        logger.info(f"Scheduled backup created: {result.get('file')}")

                        # Update last_backup time
                        sched["last_backup"] = now.isoformat()
                        _save_config(cfg)

                        # Remote upload if enabled
                        if sched.get("remote_upload") and cfg.get("remote", {}).get("provider"):
                            backup_dir = _get_backups_root() / server_name
                            backup_file = backup_dir / result["file"]
                            if backup_file.exists():
                                upload_result = _upload_to_remote(backup_file, server_name)
                                if upload_result.get("ok"):
                                    logger.info(f"Remote upload success: {upload_result.get('remote_path')}")
                                else:
                                    logger.error(f"Remote upload failed: {upload_result.get('error')}")

                        # Apply retention
                        _apply_retention(server_name, sched)

                    except Exception as e:
                        logger.error(f"Scheduled backup failed for {server_name}: {e}")

        except Exception as e:
            logger.error(f"Backup scheduler error: {e}")

        # Check every 60 seconds
        for _ in range(60):
            if not _running:
                break
            time.sleep(1)


def start_backup_scheduler():
    """Start the backup scheduler thread."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name="backup-scheduler")
    _thread.start()
    logger.info("Backup scheduler started")


def stop_backup_scheduler():
    """Stop the backup scheduler thread."""
    global _running
    _running = False
