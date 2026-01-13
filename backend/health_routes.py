from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
import psutil
import sys
import os

from database import get_db, engine, get_connection_pool_status, health_check_db
from auth import require_auth, require_admin
from models import User
from runtime_adapter import get_runtime_manager_or_docker

router = APIRouter(prefix="/health", tags=["health"])

class SystemInfo(BaseModel):
    python_version: str
    platform: str
    cpu_count: int
    memory_total_gb: float
    memory_available_gb: float
    memory_used_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_used_percent: float
    uptime_hours: float
    load_average: Optional[tuple]

class DatabaseHealth(BaseModel):
    connected: bool
    database_type: str
    total_tables: int
    user_count: int
    error: Optional[str]

class DockerHealth(BaseModel):
    connected: bool
    version: Optional[str]
    containers_running: int
    containers_total: int
    images_count: int
    error: Optional[str]

class ApplicationHealth(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    ai_monitoring: bool
    scheduler_running: bool
    
class OverallHealth(BaseModel):
    status: str  
    timestamp: datetime
    system_info: SystemInfo
    database: DatabaseHealth
    docker: DockerHealth
    application: ApplicationHealth

_manager_cache = None


def get_docker_manager():
    global _manager_cache
    if _manager_cache is None:
        _manager_cache = get_runtime_manager_or_docker()
    return _manager_cache

@router.get("/system-info", response_model=SystemInfo)
async def get_system_info():
    """Get detailed system information."""
    
    cpu_count = psutil.cpu_count()
    memory = psutil.virtual_memory()
    memory_total_gb = memory.total / (1024**3)
    memory_available_gb = memory.available / (1024**3)
    memory_used_percent = memory.percent
    
    
    disk = psutil.disk_usage('/')
    disk_total_gb = disk.total / (1024**3)
    disk_used_gb = disk.used / (1024**3)
    disk_used_percent = (disk.used / disk.total) * 100
    
    
    boot_time = psutil.boot_time()
    uptime_seconds = datetime.now().timestamp() - boot_time
    uptime_hours = uptime_seconds / 3600
    
    
    load_average = None
    try:
        if hasattr(os, 'getloadavg'):
            load_average = os.getloadavg()
    except (OSError, AttributeError):
        pass
    
    return SystemInfo(
        python_version=sys.version,
        platform=sys.platform,
        cpu_count=cpu_count,
        memory_total_gb=round(memory_total_gb, 2),
        memory_available_gb=round(memory_available_gb, 2),
        memory_used_percent=round(memory_used_percent, 2),
        disk_total_gb=round(disk_total_gb, 2),
        disk_used_gb=round(disk_used_gb, 2),
        disk_used_percent=round(disk_used_percent, 2),
        uptime_hours=round(uptime_hours, 2),
        load_average=load_average
    )

@router.get("/database", response_model=DatabaseHealth)
async def get_database_health(db: Session = Depends(get_db)):
    """Get database health status."""
    try:
        
        if not health_check_db():
            raise Exception("Database connection failed")
        
        
        db_url = str(engine.url)
        if "postgresql" in db_url:
            database_type = "PostgreSQL"
        elif "sqlite" in db_url:
            database_type = "SQLite"
        else:
            database_type = "Unknown"
        
        
        inspector = None
        total_tables = 0
        try:
            from sqlalchemy import inspect
            inspector = inspect(engine)
            total_tables = len(inspector.get_table_names())
        except Exception:
            pass
        
        
        user_count = db.query(User).count()
        
        return DatabaseHealth(
            connected=True,
            database_type=database_type,
            total_tables=total_tables,
            user_count=user_count,
            error=None
        )
        
    except Exception as e:
        return DatabaseHealth(
            connected=False,
            database_type="Unknown",
            total_tables=0,
            user_count=0,
            error=str(e)
        )

@router.get("/docker", response_model=DockerHealth)
async def get_docker_health():
    """Get Docker daemon health status."""
    try:
        docker_manager = get_docker_manager()
        client = getattr(docker_manager, "client", None)

        
        if client is None:
            return DockerHealth(
                connected=True,
                version="local-runtime",
                containers_running=0,
                containers_total=0,
                images_count=0,
                error=None
            )

        
        version_info = client.version()
        version = version_info.get('Version', 'Unknown')

        
        containers = client.containers.list(all=True)
        containers_total = len(containers)
        containers_running = len([c for c in containers if getattr(c, "status", None) == 'running'])

        
        images = client.images.list()
        images_count = len(images)

        return DockerHealth(
            connected=True,
            version=version,
            containers_running=containers_running,
            containers_total=containers_total,
            images_count=images_count,
            error=None
        )

    except Exception as e:
        return DockerHealth(
            connected=False,
            version=None,
            containers_running=0,
            containers_total=0,
            images_count=0,
            error=str(e)
        )

@router.get("/application", response_model=ApplicationHealth)
async def get_application_health():
    """Get application health status."""
    
    uptime_seconds = 0  
    
    
    ai_monitoring = False
    
    
    scheduler_running = False
    try:
        from scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler_running = scheduler.scheduler.running if scheduler else False
    except Exception:
        pass
    
    return ApplicationHealth(
        status="healthy",
        version="1.0.0",  
        uptime_seconds=uptime_seconds,
        ai_monitoring=ai_monitoring,
        scheduler_running=scheduler_running
    )

@router.get("/", response_model=OverallHealth)
async def get_overall_health(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get comprehensive health status."""
    
    system_info = await get_system_info()
    database = await get_database_health(db)
    docker = await get_docker_health()
    application = await get_application_health()
    
    
    status = "healthy"
    
    if not database.connected or not docker.connected:
        status = "error"
    elif (system_info.memory_used_percent > 90 or 
          system_info.disk_used_percent > 90 or
          docker.containers_running == 0):
        status = "warning"
    
    return OverallHealth(
        status=status,
        timestamp=datetime.utcnow(),
        system_info=system_info,
        database=database,
        docker=docker,
        application=application
    )

@router.get("/database/pool")
async def get_database_pool_status(current_user: User = Depends(require_auth)):
    """Get database connection pool status for monitoring."""
    pool_status = get_connection_pool_status()
    db_healthy = health_check_db()
    
    
    utilization = 0
    if not pool_status.get('error') and pool_status.get('pool_size', 0) > 0:
        checked_out = pool_status.get('checked_out', 0)
        total_capacity = pool_status.get('pool_size', 0) + pool_status.get('overflow', 0)
        utilization = (checked_out / total_capacity) * 100 if total_capacity > 0 else 0
    
    return {
        "healthy": db_healthy,
        "pool_status": pool_status,
        "utilization_percent": round(utilization, 2),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/quick")
async def get_quick_health():
    """Get a quick health check (no authentication required)."""
    try:
        
        from database import DATABASE_URL, init_db
        db_ok = health_check_db()
        
        if not db_ok and isinstance(DATABASE_URL, str) and DATABASE_URL.startswith('sqlite'):
            try:
                
                path_part = DATABASE_URL.split('sqlite:')[-1]
                
                sqlite_path = path_part
                
                if sqlite_path.startswith(':///'):
                    sqlite_path = sqlite_path[2:]
                
                db_file = sqlite_path
                db_dir = os.path.dirname(db_file)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                
                try:
                    init_db()
                except Exception:
                    
                    pass
                
                db_ok = health_check_db()
            except Exception:
                db_ok = False
    except Exception:
        db_ok = False
    
    
    try:
        docker_manager = get_docker_manager()
        client = getattr(docker_manager, "client", None)
        if client is None:
            docker_ok = True
        else:
            client.ping()
            docker_ok = True
    except Exception:
        docker_ok = False
    
    
    memory = psutil.virtual_memory()
    memory_ok = memory.percent < 95
    
    disk = psutil.disk_usage('/')
    disk_ok = (disk.used / disk.total) < 0.95
    
    overall_status = "ok" if all([db_ok, docker_ok, memory_ok, disk_ok]) else "error"

    
    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            "database": db_ok,
            "docker": docker_ok,
            "memory": memory_ok,
            "disk": disk_ok
        },
        "diagnostic": {
            "database_url": str(globals().get('DATABASE_URL', 'unknown')) if 'DATABASE_URL' in globals() else None,
        }
    }
