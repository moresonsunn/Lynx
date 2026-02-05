"""
UI/UX Enhancement Backend Support
Search, filters, file upload improvements, terminal history, dashboard widgets
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import json

from database import get_db
from models import User, AuditLog
from auth import require_auth, require_moderator
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT

router = APIRouter(prefix="/ui-enhancements", tags=["ui_enhancements"])


# ==================== Request/Response Models ====================

class ServerSearchRequest(BaseModel):
    query: Optional[str] = None
    server_type: Optional[str] = None  # minecraft, steam
    status: Optional[str] = None  # running, stopped, all
    tags: Optional[List[str]] = None
    sort_by: str = "name"  # name, created, status
    sort_order: str = "asc"  # asc, desc


class FileSearchRequest(BaseModel):
    server_name: str
    query: str
    file_types: Optional[List[str]] = None  # ['.jar', '.json', '.properties']
    max_results: int = 50


class TerminalCommand(BaseModel):
    server_name: str
    command: str
    timestamp: datetime = None


class DashboardWidget(BaseModel):
    widget_type: str  # server_status, performance, recent_players, quick_actions
    position: int
    config: Dict[str, Any]


class UserPreferences(BaseModel):
    theme: str = "dark"  # dark, light
    language: str = "en"
    dashboard_widgets: List[DashboardWidget] = []
    items_per_page: int = 20
    default_view: str = "grid"  # grid, list
    notifications_enabled: bool = True


# ==================== Server Search & Filter ====================

def get_docker_manager():
    return get_runtime_manager_or_docker()


@router.post("/search/servers")
async def search_servers(
    request: ServerSearchRequest,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Advanced server search and filtering"""
    
    manager = get_docker_manager()
    all_servers = manager.list_servers()
    
    results = all_servers
    
    # Filter by query (name search)
    if request.query:
        query_lower = request.query.lower()
        results = [s for s in results if query_lower in s.get('name', '').lower()]
    
    # Filter by status
    if request.status and request.status != 'all':
        results = [s for s in results if s.get('status', '').lower() == request.status.lower()]
    
    # Filter by server type (check if it's in a steam or minecraft directory)
    if request.server_type:
        if request.server_type == 'minecraft':
            results = [s for s in results if not s.get('name', '').startswith('steam-')]
        elif request.server_type == 'steam':
            results = [s for s in results if s.get('name', '').startswith('steam-')]
    
    # Filter by tags (if server groups are assigned)
    if request.tags:
        from models import ServerGroupMember
        tagged_servers = db.query(ServerGroupMember).filter(
            ServerGroupMember.group_id.in_(request.tags)
        ).all()
        tagged_names = {m.server_name for m in tagged_servers}
        results = [s for s in results if s.get('name') in tagged_names]
    
    # Sort results
    reverse = request.sort_order == "desc"
    if request.sort_by == "name":
        results.sort(key=lambda x: x.get('name', ''), reverse=reverse)
    elif request.sort_by == "status":
        results.sort(key=lambda x: x.get('status', ''), reverse=reverse)
    
    return {
        "total": len(results),
        "servers": results
    }


@router.post("/search/files")
async def search_files(
    request: FileSearchRequest,
    current_user: User = Depends(require_auth)
):
    """Search for files within a server directory"""
    
    server_path = SERVERS_ROOT / request.server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    query_lower = request.query.lower()
    results = []
    
    # Search recursively
    for file_path in server_path.rglob('*'):
        if file_path.is_file():
            # Check file type filter
            if request.file_types:
                if file_path.suffix not in request.file_types:
                    continue
            
            # Check if query matches filename
            if query_lower in file_path.name.lower():
                rel_path = file_path.relative_to(server_path)
                results.append({
                    'path': str(rel_path),
                    'name': file_path.name,
                    'size': file_path.stat().st_size,
                    'modified': int(file_path.stat().st_mtime),
                    'type': file_path.suffix
                })
                
                if len(results) >= request.max_results:
                    break
    
    return {
        "total": len(results),
        "files": results
    }


# ==================== Enhanced File Upload ====================

@router.post("/upload/drag-drop/{server_name}")
async def drag_drop_upload(
    server_name: str,
    files: List[UploadFile] = File(...),
    target_path: str = Form("."),
    current_user: User = Depends(require_moderator)
):
    """Handle multiple file uploads (drag-and-drop support)"""
    
    server_path = SERVERS_ROOT / server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    target_dir = (server_path / target_path).resolve()
    
    # Security check
    if not str(target_dir).startswith(str(server_path)):
        raise HTTPException(status_code=400, detail="Invalid target path")
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    uploaded = []
    failed = []
    
    for file in files:
        try:
            file_path = target_dir / file.filename
            
            # Write file
            content = await file.read()
            file_path.write_bytes(content)
            
            uploaded.append({
                'filename': file.filename,
                'size': len(content),
                'path': str(file_path.relative_to(server_path))
            })
        
        except Exception as e:
            failed.append({
                'filename': file.filename,
                'error': str(e)
            })
    
    return {
        'message': f'Uploaded {len(uploaded)} files',
        'uploaded': uploaded,
        'failed': failed
    }


# ==================== Terminal Command History ====================

@router.post("/terminal/history/{server_name}")
async def save_command_history(
    server_name: str,
    command: TerminalCommand,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Save terminal command to user's history"""
    
    # Store in user preferences
    if not current_user.preferences:
        current_user.preferences = {}
    
    history_key = f"terminal_history_{server_name}"
    
    if history_key not in current_user.preferences:
        current_user.preferences[history_key] = []
    
    # Add command to history
    current_user.preferences[history_key].append({
        'command': command.command,
        'timestamp': datetime.utcnow().isoformat()
    })
    
    # Keep only last 100 commands
    current_user.preferences[history_key] = current_user.preferences[history_key][-100:]
    
    # Mark as modified for SQLAlchemy
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, 'preferences')
    
    db.commit()
    
    return {'message': 'Command saved to history'}


@router.get("/terminal/history/{server_name}")
async def get_command_history(
    server_name: str,
    limit: int = 50,
    current_user: User = Depends(require_auth)
):
    """Get terminal command history for a server"""
    
    if not current_user.preferences:
        return {'history': []}
    
    history_key = f"terminal_history_{server_name}"
    history = current_user.preferences.get(history_key, [])
    
    return {
        'history': history[-limit:] if limit else history
    }


# ==================== Dashboard Widgets ====================

@router.get("/dashboard/widgets")
async def get_dashboard_widgets(
    current_user: User = Depends(require_auth)
):
    """Get user's dashboard widget configuration"""
    
    if not current_user.preferences:
        return {'widgets': []}
    
    widgets = current_user.preferences.get('dashboard_widgets', [])
    
    return {'widgets': widgets}


@router.post("/dashboard/widgets")
async def update_dashboard_widgets(
    widgets: List[DashboardWidget],
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update user's dashboard widget layout"""
    
    if not current_user.preferences:
        current_user.preferences = {}
    
    current_user.preferences['dashboard_widgets'] = [
        {
            'widget_type': w.widget_type,
            'position': w.position,
            'config': w.config
        }
        for w in widgets
    ]
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, 'preferences')
    
    db.commit()
    
    return {'message': 'Dashboard widgets updated'}


@router.get("/dashboard/data/{widget_type}")
async def get_widget_data(
    widget_type: str,
    server_name: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get data for a specific widget type"""
    
    if widget_type == "server_status":
        manager = get_docker_manager()
        servers = manager.list_servers()
        
        running = sum(1 for s in servers if s.get('status') == 'running')
        stopped = sum(1 for s in servers if s.get('status') == 'stopped')
        
        return {
            'total': len(servers),
            'running': running,
            'stopped': stopped,
            'servers': servers[:5]  # Top 5 servers
        }
    
    elif widget_type == "performance":
        if not server_name:
            raise HTTPException(status_code=400, detail="server_name required for performance widget")
        
        from models import ServerMetrics
        
        latest = db.query(ServerMetrics).filter(
            ServerMetrics.server_name == server_name
        ).order_by(ServerMetrics.timestamp.desc()).first()
        
        if not latest:
            return {'message': 'No metrics available'}
        
        return {
            'cpu_percent': latest.cpu_percent,
            'memory_percent': latest.memory_percent,
            'disk_percent': latest.disk_percent,
            'player_count': latest.player_count
        }
    
    elif widget_type == "recent_players":
        from models import PlayerProfile
        
        if server_name:
            recent = db.query(PlayerProfile).filter(
                PlayerProfile.server_name == server_name
            ).order_by(PlayerProfile.last_seen.desc()).limit(10).all()
        else:
            recent = db.query(PlayerProfile).order_by(
                PlayerProfile.last_seen.desc()
            ).limit(10).all()
        
        return {
            'players': [
                {
                    'name': p.player_name,
                    'server': p.server_name,
                    'last_seen': p.last_seen.isoformat() if p.last_seen else None,
                    'online': p.is_online
                }
                for p in recent
            ]
        }
    
    elif widget_type == "quick_actions":
        # Return available quick actions
        return {
            'actions': [
                {'id': 'create_server', 'label': 'Create Server', 'icon': '➕'},
                {'id': 'create_backup', 'label': 'Create Backup', 'icon': '💾'},
                {'id': 'view_alerts', 'label': 'View Alerts', 'icon': '🔔'},
                {'id': 'check_updates', 'label': 'Check Updates', 'icon': '🔄'}
            ]
        }
    
    else:
        raise HTTPException(status_code=400, detail="Unknown widget type")


# ==================== User Preferences ====================

@router.get("/preferences")
async def get_user_preferences(
    current_user: User = Depends(require_auth)
):
    """Get user's UI preferences"""
    
    if not current_user.preferences:
        return UserPreferences().dict()
    
    # Merge with defaults
    defaults = UserPreferences().dict()
    merged = {**defaults, **current_user.preferences}
    
    return merged


@router.post("/preferences")
async def update_user_preferences(
    preferences: UserPreferences,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update user's UI preferences"""
    
    if not current_user.preferences:
        current_user.preferences = {}
    
    # Update preferences
    pref_dict = preferences.dict()
    current_user.preferences.update(pref_dict)
    
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, 'preferences')
    
    db.commit()
    
    return {'message': 'Preferences updated'}


# ==================== Quick Stats ====================

@router.get("/stats/overview")
async def get_overview_stats(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get quick overview statistics for dashboard"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    # Server stats
    total_servers = len(servers)
    running_servers = sum(1 for s in servers if s.get('status') == 'running')
    
    # Player stats
    from models import PlayerProfile
    total_players = db.query(PlayerProfile).count()
    online_players = db.query(PlayerProfile).filter(PlayerProfile.is_online == True).count()
    
    # Alert stats
    from models import PerformanceAlert
    active_alerts = db.query(PerformanceAlert).filter(
        PerformanceAlert.is_resolved == False
    ).count()
    
    # Recent activity
    recent_logs = db.query(AuditLog).order_by(
        AuditLog.timestamp.desc()
    ).limit(5).all()
    
    return {
        'servers': {
            'total': total_servers,
            'running': running_servers,
            'stopped': total_servers - running_servers
        },
        'players': {
            'total': total_players,
            'online': online_players
        },
        'alerts': {
            'active': active_alerts
        },
        'recent_activity': [
            {
                'action': log.action,
                'user': log.user.username if log.user else 'System',
                'timestamp': log.timestamp.isoformat()
            }
            for log in recent_logs
        ]
    }


# ==================== Mobile Support ====================

@router.get("/mobile/summary")
async def get_mobile_summary(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get simplified data for mobile devices"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    # Simplified server list
    server_summary = [
        {
            'name': s.get('name'),
            'status': s.get('status'),
            'players': 0  # TODO: Get from metrics
        }
        for s in servers[:10]  # Limit to 10 for mobile
    ]
    
    # Active alerts
    from models import PerformanceAlert
    alerts = db.query(PerformanceAlert).filter(
        PerformanceAlert.is_resolved == False,
        PerformanceAlert.severity == 'critical'
    ).limit(5).all()
    
    return {
        'servers': server_summary,
        'critical_alerts': [
            {
                'server': a.server_name,
                'message': a.message,
                'time': a.triggered_at.isoformat()
            }
            for a in alerts
        ]
    }
