"""
Advanced Backup System
Incremental backups, cloud storage, compression levels, verification, selective backups
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import hashlib
import gzip
import bz2
import lzma
import tarfile
import zipfile
import json

from database import get_db
from models import BackupConfig, BackupHistory, User
from auth import require_auth, require_moderator
from config import SERVERS_ROOT

router = APIRouter(prefix="/backup-advanced", tags=["backup_advanced"])


# ==================== Request/Response Models ====================

class BackupConfigRequest(BaseModel):
    backup_type: str = "full"  # full, incremental, world_only
    compression_level: int = 6  # 0-9
    compression_format: str = "gzip"  # gzip, bzip2, xz, zip
    retention_count: int = 10
    retention_days: int = 30
    verify_backups: bool = True
    exclude_patterns: Optional[List[str]] = None
    cloud_enabled: bool = False
    cloud_provider: Optional[str] = None
    cloud_config: Optional[Dict[str, Any]] = None


class BackupConfigResponse(BaseModel):
    id: int
    server_name: str
    backup_type: str
    compression_level: int
    compression_format: str
    retention_count: int
    retention_days: int
    verify_backups: bool
    cloud_enabled: bool
    cloud_provider: Optional[str]
    
    class Config:
        from_attributes = True


class BackupHistoryResponse(BaseModel):
    id: int
    server_name: str
    backup_file: str
    backup_type: str
    file_size: int
    compression_ratio: Optional[float]
    is_verified: bool
    verification_status: Optional[str]
    cloud_path: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class CreateBackupRequest(BaseModel):
    backup_type: Optional[str] = None  # Override config
    note: Optional[str] = None


class RestoreBackupRequest(BaseModel):
    backup_id: int
    restore_type: str = "full"  # full, world_only, selective
    paths: Optional[List[str]] = None  # For selective restore


# ==================== Backup Configuration ====================

@router.post("/config/{server_name}", response_model=BackupConfigResponse)
async def create_backup_config(
    server_name: str,
    config: BackupConfigRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Create or update backup configuration for a server"""
    
    # Check if config exists
    existing = db.query(BackupConfig).filter(
        BackupConfig.server_name == server_name
    ).first()
    
    if existing:
        # Update existing
        existing.backup_type = config.backup_type
        existing.compression_level = config.compression_level
        existing.compression_format = config.compression_format
        existing.retention_count = config.retention_count
        existing.retention_days = config.retention_days
        existing.verify_backups = config.verify_backups
        existing.exclude_patterns = config.exclude_patterns
        existing.cloud_enabled = config.cloud_enabled
        existing.cloud_provider = config.cloud_provider
        existing.cloud_config = config.cloud_config
        existing.updated_at = datetime.utcnow()
        db_config = existing
    else:
        # Create new
        db_config = BackupConfig(
            server_name=server_name,
            backup_type=config.backup_type,
            compression_level=config.compression_level,
            compression_format=config.compression_format,
            retention_count=config.retention_count,
            retention_days=config.retention_days,
            verify_backups=config.verify_backups,
            exclude_patterns=config.exclude_patterns,
            cloud_enabled=config.cloud_enabled,
            cloud_provider=config.cloud_provider,
            cloud_config=config.cloud_config
        )
        db.add(db_config)
    
    db.commit()
    db.refresh(db_config)
    
    return BackupConfigResponse.model_validate(db_config)


@router.get("/config/{server_name}", response_model=BackupConfigResponse)
async def get_backup_config(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get backup configuration for a server"""
    
    config = db.query(BackupConfig).filter(
        BackupConfig.server_name == server_name
    ).first()
    
    if not config:
        # Return default config
        return BackupConfigResponse(
            id=0,
            server_name=server_name,
            backup_type="full",
            compression_level=6,
            compression_format="gzip",
            retention_count=10,
            retention_days=30,
            verify_backups=True,
            cloud_enabled=False,
            cloud_provider=None
        )
    
    return BackupConfigResponse.model_validate(config)


# ==================== Backup Creation ====================

def _calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def _should_exclude(path: Path, exclude_patterns: List[str]) -> bool:
    """Check if path matches any exclusion pattern"""
    if not exclude_patterns:
        return False
    
    path_str = str(path)
    for pattern in exclude_patterns:
        if pattern in path_str:
            return True
    return False


def _create_incremental_backup(
    server_path: Path,
    backup_path: Path,
    parent_backup_id: Optional[int],
    config: BackupConfig,
    db: Session
) -> Dict[str, Any]:
    """Create an incremental backup"""
    
    # Get parent backup if exists
    parent_backup = None
    if parent_backup_id:
        parent_backup = db.query(BackupHistory).filter(
            BackupHistory.id == parent_backup_id
        ).first()
    
    # Collect files and their timestamps
    changed_files = []
    parent_time = parent_backup.created_at if parent_backup else datetime.fromtimestamp(0)
    
    for file_path in server_path.rglob('*'):
        if file_path.is_file():
            # Check exclusions
            if _should_exclude(file_path, config.exclude_patterns or []):
                continue
            
            # Check if modified since parent backup
            if file_path.stat().st_mtime > parent_time.timestamp():
                rel_path = file_path.relative_to(server_path)
                changed_files.append(rel_path)
    
    # Create archive with only changed files
    if config.compression_format == 'gzip':
        with tarfile.open(backup_path, 'w:gz', compresslevel=config.compression_level) as tar:
            for rel_path in changed_files:
                tar.add(server_path / rel_path, arcname=rel_path)
    elif config.compression_format == 'bzip2':
        with tarfile.open(backup_path, 'w:bz2', compresslevel=config.compression_level) as tar:
            for rel_path in changed_files:
                tar.add(server_path / rel_path, arcname=rel_path)
    elif config.compression_format == 'xz':
        with tarfile.open(backup_path, 'w:xz', preset=config.compression_level) as tar:
            for rel_path in changed_files:
                tar.add(server_path / rel_path, arcname=rel_path)
    
    return {
        'changed_files': len(changed_files),
        'backup_file': backup_path.name
    }


def _create_full_backup(
    server_path: Path,
    backup_path: Path,
    config: BackupConfig
) -> Dict[str, Any]:
    """Create a full backup"""
    
    original_size = 0
    
    if config.compression_format == 'zip':
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=config.compression_level) as zf:
            for file_path in server_path.rglob('*'):
                if file_path.is_file():
                    if _should_exclude(file_path, config.exclude_patterns or []):
                        continue
                    rel_path = file_path.relative_to(server_path)
                    zf.write(file_path, rel_path)
                    original_size += file_path.stat().st_size
    
    elif config.compression_format == 'gzip':
        with tarfile.open(backup_path, 'w:gz', compresslevel=config.compression_level) as tar:
            for file_path in server_path.rglob('*'):
                if file_path.is_file():
                    if _should_exclude(file_path, config.exclude_patterns or []):
                        continue
                    rel_path = file_path.relative_to(server_path)
                    tar.add(file_path, arcname=rel_path)
                    original_size += file_path.stat().st_size
    
    elif config.compression_format == 'bzip2':
        with tarfile.open(backup_path, 'w:bz2', compresslevel=config.compression_level) as tar:
            for file_path in server_path.rglob('*'):
                if file_path.is_file():
                    if _should_exclude(file_path, config.exclude_patterns or []):
                        continue
                    rel_path = file_path.relative_to(server_path)
                    tar.add(file_path, arcname=rel_path)
                    original_size += file_path.stat().st_size
    
    elif config.compression_format == 'xz':
        with tarfile.open(backup_path, 'w:xz', preset=config.compression_level) as tar:
            for file_path in server_path.rglob('*'):
                if file_path.is_file():
                    if _should_exclude(file_path, config.exclude_patterns or []):
                        continue
                    rel_path = file_path.relative_to(server_path)
                    tar.add(file_path, arcname=rel_path)
                    original_size += file_path.stat().st_size
    
    return {'original_size': original_size}


def _create_world_backup(
    server_path: Path,
    backup_path: Path,
    config: BackupConfig
) -> Dict[str, Any]:
    """Create a world-only backup"""
    
    world_dirs = ['world', 'world_nether', 'world_the_end']
    original_size = 0
    
    if config.compression_format == 'zip':
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=config.compression_level) as zf:
            for world_dir in world_dirs:
                world_path = server_path / world_dir
                if world_path.exists():
                    for file_path in world_path.rglob('*'):
                        if file_path.is_file():
                            rel_path = file_path.relative_to(server_path)
                            zf.write(file_path, rel_path)
                            original_size += file_path.stat().st_size
    else:
        # Use tar for other formats
        mode = f'w:{config.compression_format[0]}'  # w:g, w:b, w:x
        kwargs = {'compresslevel': config.compression_level} if config.compression_format != 'xz' else {'preset': config.compression_level}
        
        with tarfile.open(backup_path, mode, **kwargs) as tar:
            for world_dir in world_dirs:
                world_path = server_path / world_dir
                if world_path.exists():
                    for file_path in world_path.rglob('*'):
                        if file_path.is_file():
                            rel_path = file_path.relative_to(server_path)
                            tar.add(file_path, arcname=rel_path)
                            original_size += file_path.stat().st_size
    
    return {'original_size': original_size}


@router.post("/create/{server_name}", response_model=BackupHistoryResponse)
async def create_advanced_backup(
    server_name: str,
    request: CreateBackupRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Create an advanced backup with configured settings"""
    
    server_path = SERVERS_ROOT / server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Get backup config
    config = db.query(BackupConfig).filter(BackupConfig.server_name == server_name).first()
    if not config:
        # Use defaults
        config = BackupConfig(
            server_name=server_name,
            backup_type="full",
            compression_level=6,
            compression_format="gzip"
        )
    
    # Override backup type if requested
    backup_type = request.backup_type or config.backup_type
    
    # Prepare backup path
    backup_dir = SERVERS_ROOT.parent / "backups" / server_name
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    ext = {'gzip': '.tar.gz', 'bzip2': '.tar.bz2', 'xz': '.tar.xz', 'zip': '.zip'}[config.compression_format]
    backup_filename = f"{server_name}-{backup_type}-{timestamp}{ext}"
    backup_path = backup_dir / backup_filename
    
    # Record start time
    start_time = datetime.utcnow()
    
    # Create backup based on type
    if backup_type == "incremental":
        # Find most recent full backup
        parent = db.query(BackupHistory).filter(
            BackupHistory.server_name == server_name,
            BackupHistory.backup_type == "full"
        ).order_by(BackupHistory.created_at.desc()).first()
        
        result = _create_incremental_backup(
            server_path,
            backup_path,
            parent.id if parent else None,
            config,
            db
        )
    elif backup_type == "world_only":
        result = _create_world_backup(server_path, backup_path, config)
    else:  # full
        result = _create_full_backup(server_path, backup_path, config)
    
    # Calculate stats
    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()
    file_size = backup_path.stat().st_size
    original_size = result.get('original_size', file_size)
    compression_ratio = (1 - (file_size / original_size)) * 100 if original_size > 0 else 0
    
    # Calculate checksum
    checksum = _calculate_checksum(backup_path)
    
    # Create backup history record
    backup_history = BackupHistory(
        server_name=server_name,
        backup_file=backup_filename,
        backup_type=backup_type,
        file_size=file_size,
        compression_ratio=compression_ratio,
        backup_duration_seconds=duration,
        local_path=str(backup_path),
        checksum=checksum,
        created_by=current_user.id,
        is_auto_backup=False
    )
    
    db.add(backup_history)
    db.commit()
    db.refresh(backup_history)
    
    # Verify backup if configured
    if config.verify_backups:
        background_tasks.add_task(_verify_backup, backup_history.id, db)
    
    # Upload to cloud if configured
    if config.cloud_enabled and config.cloud_provider:
        background_tasks.add_task(_upload_to_cloud, backup_history.id, config, db)
    
    # Clean up old backups
    background_tasks.add_task(_cleanup_old_backups, server_name, config, db)
    
    return BackupHistoryResponse.model_validate(backup_history)


def _verify_backup(backup_id: int, db: Session):
    """Verify backup integrity"""
    try:
        backup = db.query(BackupHistory).filter(BackupHistory.id == backup_id).first()
        if not backup:
            return
        
        backup_path = Path(backup.local_path)
        if not backup_path.exists():
            backup.verification_status = "failed"
            backup.is_verified = False
            db.commit()
            return
        
        # Verify checksum
        current_checksum = _calculate_checksum(backup_path)
        if current_checksum == backup.checksum:
            backup.verification_status = "passed"
            backup.is_verified = True
        else:
            backup.verification_status = "failed"
            backup.is_verified = False
        
        backup.verification_date = datetime.utcnow()
        db.commit()
    
    except Exception as e:
        print(f"Error verifying backup {backup_id}: {e}")


def _upload_to_cloud(backup_id: int, config: BackupConfig, db: Session):
    """Upload backup to cloud storage"""
    try:
        backup = db.query(BackupHistory).filter(BackupHistory.id == backup_id).first()
        if not backup:
            return
        
        backup_path = Path(backup.local_path)
        
        if config.cloud_provider == "s3":
            _upload_to_s3(backup_path, config.cloud_config, backup, db)
        elif config.cloud_provider == "gcs":
            _upload_to_gcs(backup_path, config.cloud_config, backup, db)
        elif config.cloud_provider == "azure":
            _upload_to_azure(backup_path, config.cloud_config, backup, db)
        
    except Exception as e:
        print(f"Error uploading backup {backup_id} to cloud: {e}")


def _upload_to_s3(backup_path: Path, cloud_config: Dict, backup: BackupHistory, db: Session):
    """Upload to AWS S3"""
    try:
        import boto3
        
        s3 = boto3.client(
            's3',
            aws_access_key_id=cloud_config.get('access_key'),
            aws_secret_access_key=cloud_config.get('secret_key'),
            region_name=cloud_config.get('region', 'us-east-1')
        )
        
        bucket = cloud_config.get('bucket')
        key = f"backups/{backup.server_name}/{backup.backup_file}"
        
        s3.upload_file(str(backup_path), bucket, key)
        
        backup.cloud_path = f"s3://{bucket}/{key}"
        backup.cloud_provider = "s3"
        db.commit()
    
    except Exception as e:
        print(f"S3 upload error: {e}")


def _upload_to_gcs(backup_path: Path, cloud_config: Dict, backup: BackupHistory, db: Session):
    """Upload to Google Cloud Storage"""
    # Placeholder for GCS implementation
    pass


def _upload_to_azure(backup_path: Path, cloud_config: Dict, backup: BackupHistory, db: Session):
    """Upload to Azure Blob Storage"""
    # Placeholder for Azure implementation
    pass


def _cleanup_old_backups(server_name: str, config: BackupConfig, db: Session):
    """Clean up old backups based on retention policy"""
    try:
        # Get all backups for server
        backups = db.query(BackupHistory).filter(
            BackupHistory.server_name == server_name
        ).order_by(BackupHistory.created_at.desc()).all()
        
        # Apply retention count
        if len(backups) > config.retention_count:
            to_delete = backups[config.retention_count:]
            for backup in to_delete:
                try:
                    # Delete local file
                    if backup.local_path:
                        Path(backup.local_path).unlink(missing_ok=True)
                    # Delete from database
                    db.delete(backup)
                except Exception as e:
                    print(f"Error deleting backup {backup.id}: {e}")
        
        # Apply retention days
        cutoff = datetime.utcnow() - timedelta(days=config.retention_days)
        old_backups = db.query(BackupHistory).filter(
            BackupHistory.server_name == server_name,
            BackupHistory.created_at < cutoff
        ).all()
        
        for backup in old_backups:
            try:
                if backup.local_path:
                    Path(backup.local_path).unlink(missing_ok=True)
                db.delete(backup)
            except Exception as e:
                print(f"Error deleting old backup {backup.id}: {e}")
        
        db.commit()
    
    except Exception as e:
        print(f"Error cleaning up backups: {e}")


# ==================== Backup History ====================

@router.get("/history/{server_name}", response_model=List[BackupHistoryResponse])
async def get_backup_history(
    server_name: str,
    limit: int = 50,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get backup history for a server"""
    
    backups = db.query(BackupHistory).filter(
        BackupHistory.server_name == server_name
    ).order_by(BackupHistory.created_at.desc()).limit(limit).all()
    
    return [BackupHistoryResponse.model_validate(b) for b in backups]


@router.post("/verify/{backup_id}")
async def verify_backup_manually(
    backup_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Manually verify a backup"""
    
    backup = db.query(BackupHistory).filter(BackupHistory.id == backup_id).first()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    background_tasks.add_task(_verify_backup, backup_id, db)
    
    return {"message": "Verification started"}


@router.delete("/history/{backup_id}")
async def delete_backup(
    backup_id: int,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Delete a specific backup"""
    
    backup = db.query(BackupHistory).filter(BackupHistory.id == backup_id).first()
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Delete local file
    if backup.local_path:
        Path(backup.local_path).unlink(missing_ok=True)
    
    # Delete from database
    db.delete(backup)
    db.commit()
    
    return {"message": "Backup deleted"}
