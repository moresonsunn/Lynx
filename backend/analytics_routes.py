"""
Server Performance Monitoring & Analytics
Real-time metrics, historical graphs, alerts, and crash detection
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import docker
from pathlib import Path

from database import get_db
from models import ServerMetrics, PerformanceAlert, CrashReport, User
from auth import require_auth, require_moderator
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ==================== Request/Response Models ====================

class MetricsResponse(BaseModel):
    server_name: str
    timestamp: datetime
    cpu_percent: Optional[float]
    memory_used_mb: Optional[float]
    memory_total_mb: Optional[float]
    memory_percent: Optional[float]
    disk_used_gb: Optional[float]
    disk_total_gb: Optional[float]
    disk_percent: Optional[float]
    network_rx_bytes: Optional[int]
    network_tx_bytes: Optional[int]
    network_rx_rate: Optional[float]
    network_tx_rate: Optional[float]
    player_count: int
    tps: Optional[float]
    
    class Config:
        from_attributes = True


class AlertResponse(BaseModel):
    id: int
    server_name: str
    alert_type: str
    severity: str
    message: str
    threshold_value: Optional[float]
    current_value: Optional[float]
    triggered_at: datetime
    resolved_at: Optional[datetime]
    is_resolved: bool
    
    class Config:
        from_attributes = True


class CrashReportResponse(BaseModel):
    id: int
    server_name: str
    crash_time: datetime
    error_type: Optional[str]
    auto_restarted: bool
    probable_cause: Optional[str]
    suggested_fix: Optional[str]
    
    class Config:
        from_attributes = True


class AlertThreshold(BaseModel):
    cpu_percent: float = 80.0
    memory_percent: float = 85.0
    disk_percent: float = 90.0


class HistoricalStats(BaseModel):
    avg_cpu: Optional[float]
    max_cpu: Optional[float]
    avg_memory: Optional[float]
    max_memory: Optional[float]
    avg_players: Optional[float]
    max_players: Optional[int]
    total_data_points: int


# ==================== Metrics Collection ====================

def get_docker_manager():
    return get_runtime_manager_or_docker()


def _collect_container_stats(container_name: str) -> Dict[str, Any]:
    """Collect real-time stats from Docker container"""
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        stats = container.stats(stream=False)
        
        # CPU usage
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                   stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                      stats['precpu_stats']['system_cpu_usage']
        cpu_count = stats['cpu_stats'].get('online_cpus', 1)
        cpu_percent = 0.0
        if system_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
        
        # Memory usage
        mem_usage = stats['memory_stats'].get('usage', 0)
        mem_limit = stats['memory_stats'].get('limit', 1)
        mem_percent = (mem_usage / mem_limit) * 100.0 if mem_limit > 0 else 0.0
        
        # Network I/O
        networks = stats.get('networks', {})
        rx_bytes = sum(net.get('rx_bytes', 0) for net in networks.values())
        tx_bytes = sum(net.get('tx_bytes', 0) for net in networks.values())
        
        return {
            'cpu_percent': round(cpu_percent, 2),
            'memory_used_mb': round(mem_usage / (1024 * 1024), 2),
            'memory_total_mb': round(mem_limit / (1024 * 1024), 2),
            'memory_percent': round(mem_percent, 2),
            'network_rx_bytes': rx_bytes,
            'network_tx_bytes': tx_bytes,
        }
    except Exception as e:
        print(f"Error collecting stats for {container_name}: {e}")
        return {}


def _collect_disk_stats(server_name: str) -> Dict[str, Any]:
    """Collect disk usage statistics"""
    try:
        import shutil
        server_path = SERVERS_ROOT / server_name
        if not server_path.exists():
            return {}
        
        usage = shutil.disk_usage(str(server_path))
        return {
            'disk_used_gb': round(usage.used / (1024**3), 2),
            'disk_total_gb': round(usage.total / (1024**3), 2),
            'disk_percent': round((usage.used / usage.total) * 100, 2),
        }
    except Exception as e:
        print(f"Error collecting disk stats: {e}")
        return {}


def _get_player_count(server_name: str) -> int:
    """Get current online player count from logs"""
    try:
        from player_routes import _collect_history
        history = _collect_history(server_name, limit_files=1, limit_lines=1000)
        # Count players seen in last 10 minutes as "online"
        # This is a simplified approach; could be enhanced
        return len([p for p in history.values() if p.get('last_seen')])
    except Exception:
        return 0


@router.post("/metrics/collect/{server_name}")
async def collect_metrics(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Collect and store current metrics for a server"""
    
    # Get container stats
    container_stats = _collect_container_stats(f"mc-{server_name}")
    disk_stats = _collect_disk_stats(server_name)
    player_count = _get_player_count(server_name)
    
    # Create metrics record
    metrics = ServerMetrics(
        server_name=server_name,
        cpu_percent=container_stats.get('cpu_percent'),
        memory_used_mb=container_stats.get('memory_used_mb'),
        memory_total_mb=container_stats.get('memory_total_mb'),
        memory_percent=container_stats.get('memory_percent'),
        disk_used_gb=disk_stats.get('disk_used_gb'),
        disk_total_gb=disk_stats.get('disk_total_gb'),
        disk_percent=disk_stats.get('disk_percent'),
        network_rx_bytes=container_stats.get('network_rx_bytes'),
        network_tx_bytes=container_stats.get('network_tx_bytes'),
        player_count=player_count,
    )
    
    db.add(metrics)
    db.commit()
    db.refresh(metrics)
    
    # Check for alert conditions
    _check_alert_thresholds(db, server_name, metrics)
    
    return MetricsResponse.model_validate(metrics)


def _check_alert_thresholds(db: Session, server_name: str, metrics: ServerMetrics):
    """Check if metrics exceed thresholds and create alerts"""
    
    alerts_to_create = []
    
    # CPU alert
    if metrics.cpu_percent and metrics.cpu_percent > 80:
        severity = "critical" if metrics.cpu_percent > 95 else "warning"
        alerts_to_create.append({
            'alert_type': 'cpu',
            'severity': severity,
            'message': f'High CPU usage: {metrics.cpu_percent:.1f}%',
            'threshold_value': 80.0,
            'current_value': metrics.cpu_percent,
        })
    
    # Memory alert
    if metrics.memory_percent and metrics.memory_percent > 85:
        severity = "critical" if metrics.memory_percent > 95 else "warning"
        alerts_to_create.append({
            'alert_type': 'memory',
            'severity': severity,
            'message': f'High memory usage: {metrics.memory_percent:.1f}%',
            'threshold_value': 85.0,
            'current_value': metrics.memory_percent,
        })
    
    # Disk alert
    if metrics.disk_percent and metrics.disk_percent > 90:
        severity = "critical" if metrics.disk_percent > 95 else "warning"
        alerts_to_create.append({
            'alert_type': 'disk',
            'severity': severity,
            'message': f'High disk usage: {metrics.disk_percent:.1f}%',
            'threshold_value': 90.0,
            'current_value': metrics.disk_percent,
        })
    
    # Create alerts
    for alert_data in alerts_to_create:
        # Check if similar alert already exists and is not resolved
        existing = db.query(PerformanceAlert).filter(
            and_(
                PerformanceAlert.server_name == server_name,
                PerformanceAlert.alert_type == alert_data['alert_type'],
                PerformanceAlert.is_resolved == False
            )
        ).first()
        
        if not existing:
            alert = PerformanceAlert(server_name=server_name, **alert_data)
            db.add(alert)
    
    db.commit()


# ==================== Query Endpoints ====================

@router.get("/metrics/{server_name}/current", response_model=MetricsResponse)
async def get_current_metrics(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get most recent metrics for a server"""
    
    metrics = db.query(ServerMetrics).filter(
        ServerMetrics.server_name == server_name
    ).order_by(ServerMetrics.timestamp.desc()).first()
    
    if not metrics:
        raise HTTPException(status_code=404, detail="No metrics found")
    
    return MetricsResponse.model_validate(metrics)


@router.get("/metrics/{server_name}/history", response_model=List[MetricsResponse])
async def get_metrics_history(
    server_name: str,
    hours: int = Query(24, description="Hours of history to retrieve"),
    limit: int = Query(100, description="Maximum data points"),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get historical metrics for a server"""
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    metrics = db.query(ServerMetrics).filter(
        and_(
            ServerMetrics.server_name == server_name,
            ServerMetrics.timestamp >= since
        )
    ).order_by(ServerMetrics.timestamp.desc()).limit(limit).all()
    
    return [MetricsResponse.model_validate(m) for m in metrics]


@router.get("/metrics/{server_name}/stats", response_model=HistoricalStats)
async def get_historical_stats(
    server_name: str,
    hours: int = Query(24, description="Hours to analyze"),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get aggregated statistics for a time period"""
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    stats = db.query(
        func.avg(ServerMetrics.cpu_percent).label('avg_cpu'),
        func.max(ServerMetrics.cpu_percent).label('max_cpu'),
        func.avg(ServerMetrics.memory_percent).label('avg_memory'),
        func.max(ServerMetrics.memory_percent).label('max_memory'),
        func.avg(ServerMetrics.player_count).label('avg_players'),
        func.max(ServerMetrics.player_count).label('max_players'),
        func.count(ServerMetrics.id).label('total_data_points'),
    ).filter(
        and_(
            ServerMetrics.server_name == server_name,
            ServerMetrics.timestamp >= since
        )
    ).first()
    
    return HistoricalStats(
        avg_cpu=round(stats.avg_cpu, 2) if stats.avg_cpu else None,
        max_cpu=round(stats.max_cpu, 2) if stats.max_cpu else None,
        avg_memory=round(stats.avg_memory, 2) if stats.avg_memory else None,
        max_memory=round(stats.max_memory, 2) if stats.max_memory else None,
        avg_players=round(stats.avg_players, 2) if stats.avg_players else None,
        max_players=stats.max_players or 0,
        total_data_points=stats.total_data_points or 0,
    )


# ==================== Alerts ====================

@router.get("/alerts", response_model=List[AlertResponse])
async def get_all_alerts(
    server_name: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get performance alerts with optional filtering"""
    
    query = db.query(PerformanceAlert)
    
    if server_name:
        query = query.filter(PerformanceAlert.server_name == server_name)
    if severity:
        query = query.filter(PerformanceAlert.severity == severity)
    if resolved is not None:
        query = query.filter(PerformanceAlert.is_resolved == resolved)
    
    alerts = query.order_by(PerformanceAlert.triggered_at.desc()).limit(100).all()
    
    return [AlertResponse.model_validate(a) for a in alerts]


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Mark an alert as resolved"""
    
    alert = db.query(PerformanceAlert).filter(PerformanceAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Alert resolved"}


# ==================== Crash Detection ====================

@router.get("/crashes/{server_name}", response_model=List[CrashReportResponse])
async def get_crash_reports(
    server_name: str,
    limit: int = Query(10, description="Maximum reports to return"),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get crash reports for a server"""
    
    crashes = db.query(CrashReport).filter(
        CrashReport.server_name == server_name
    ).order_by(CrashReport.crash_time.desc()).limit(limit).all()
    
    return [CrashReportResponse.model_validate(c) for c in crashes]


@router.post("/crashes/{server_name}/detect")
async def detect_crashes(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Scan logs for crash indicators and create crash reports"""
    
    try:
        server_path = SERVERS_ROOT / server_name
        if not server_path.exists():
            raise HTTPException(status_code=404, detail="Server not found")
        
        crash_log_path = server_path / "crash-reports"
        crashes_detected = []
        
        if crash_log_path.exists():
            for crash_file in sorted(crash_log_path.glob("crash-*.txt"), reverse=True)[:5]:
                try:
                    content = crash_file.read_text(encoding='utf-8', errors='ignore')
                    
                    # Extract error type from crash log
                    error_type = None
                    for line in content.split('\n')[:20]:
                        if 'Exception' in line or 'Error' in line:
                            error_type = line.strip()
                            break
                    
                    # Check if we already have this crash
                    existing = db.query(CrashReport).filter(
                        and_(
                            CrashReport.server_name == server_name,
                            CrashReport.error_type == error_type
                        )
                    ).first()
                    
                    if not existing:
                        crash = CrashReport(
                            server_name=server_name,
                            crash_log=content[:10000],  # Limit size
                            error_type=error_type,
                            probable_cause=_analyze_crash(content),
                        )
                        db.add(crash)
                        crashes_detected.append(crash_file.name)
                except Exception as e:
                    print(f"Error processing crash file {crash_file}: {e}")
        
        db.commit()
        
        return {
            "message": f"Detected {len(crashes_detected)} new crashes",
            "crashes": crashes_detected
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _analyze_crash(crash_log: str) -> str:
    """Simple crash log analysis to suggest probable cause"""
    
    crash_lower = crash_log.lower()
    
    if 'outofmemoryerror' in crash_lower:
        return "Out of memory - increase server RAM allocation"
    elif 'permgen' in crash_lower or 'metaspace' in crash_lower:
        return "PermGen/Metaspace error - increase JVM memory settings"
    elif 'classnotfound' in crash_lower or 'noclassdef' in crash_lower:
        return "Missing class - possible mod incompatibility or corrupt JAR"
    elif 'concurrent modification' in crash_lower:
        return "Concurrent modification - possible mod conflict"
    elif 'ticking entity' in crash_lower:
        return "Ticking entity error - corrupted entity in world"
    elif 'ticking block' in crash_lower:
        return "Ticking block error - corrupted tile entity in world"
    else:
        return "Unknown cause - review full crash log"


# ==================== Cleanup ====================

@router.delete("/metrics/{server_name}/cleanup")
async def cleanup_old_metrics(
    server_name: str,
    days: int = Query(30, description="Delete metrics older than X days"),
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Delete old metrics data to save space"""
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    deleted = db.query(ServerMetrics).filter(
        and_(
            ServerMetrics.server_name == server_name,
            ServerMetrics.timestamp < cutoff
        )
    ).delete()
    
    db.commit()
    
    return {"message": f"Deleted {deleted} old metric records"}
