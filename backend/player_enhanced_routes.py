"""
Player Experience Enhancements
Bulk whitelist, temporary bans, player statistics, RCON support
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import csv
import io
import json

from database import get_db
from models import PlayerProfile, TemporaryBan, PlayerSession, User
from auth import require_auth, require_moderator
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT

router = APIRouter(prefix="/player-enhanced", tags=["player_enhanced"])


# ==================== Request/Response Models ====================

class PlayerProfileResponse(BaseModel):
    id: int
    server_name: str
    player_name: str
    player_uuid: Optional[str]
    first_joined: Optional[datetime]
    last_seen: Optional[datetime]
    total_playtime_minutes: int
    session_count: int
    is_online: bool
    is_whitelisted: bool
    is_banned: bool
    is_op: bool
    
    class Config:
        from_attributes = True


class PlayerStatsResponse(BaseModel):
    player_name: str
    playtime_formatted: str
    first_join_days_ago: Optional[int]
    last_seen_days_ago: Optional[int]
    sessions: int
    average_session_minutes: Optional[float]


class TemporaryBanRequest(BaseModel):
    player_name: str
    duration_hours: int
    reason: Optional[str] = None


class TemporaryBanResponse(BaseModel):
    id: int
    server_name: str
    player_name: str
    reason: Optional[str]
    banned_at: datetime
    expires_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True


class BulkWhitelistRequest(BaseModel):
    players: List[str]


class RCONCommandRequest(BaseModel):
    command: str


# ==================== Player Profiles & Statistics ====================

def get_docker_manager():
    return get_runtime_manager_or_docker()


@router.get("/profiles/{server_name}", response_model=List[PlayerProfileResponse])
async def get_player_profiles(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all player profiles for a server"""
    
    profiles = db.query(PlayerProfile).filter(
        PlayerProfile.server_name == server_name
    ).order_by(PlayerProfile.last_seen.desc()).all()
    
    return [PlayerProfileResponse.model_validate(p) for p in profiles]


@router.get("/stats/{server_name}/{player_name}", response_model=PlayerStatsResponse)
async def get_player_stats(
    server_name: str,
    player_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get detailed statistics for a specific player"""
    
    profile = db.query(PlayerProfile).filter(
        and_(
            PlayerProfile.server_name == server_name,
            PlayerProfile.player_name == player_name
        )
    ).first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Calculate days ago
    now = datetime.utcnow()
    first_join_days = (now - profile.first_joined).days if profile.first_joined else None
    last_seen_days = (now - profile.last_seen).days if profile.last_seen else None
    
    # Calculate average session length
    avg_session = None
    if profile.session_count > 0:
        avg_session = profile.total_playtime_minutes / profile.session_count
    
    # Format playtime
    hours = profile.total_playtime_minutes // 60
    minutes = profile.total_playtime_minutes % 60
    playtime_formatted = f"{hours}h {minutes}m"
    
    return PlayerStatsResponse(
        player_name=profile.player_name,
        playtime_formatted=playtime_formatted,
        first_join_days_ago=first_join_days,
        last_seen_days_ago=last_seen_days,
        sessions=profile.session_count,
        average_session_minutes=round(avg_session, 1) if avg_session else None
    )


@router.post("/sync-profiles/{server_name}")
async def sync_player_profiles(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Sync player profiles from server files (usercache.json, logs)"""
    
    server_path = SERVERS_ROOT / server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    synced = 0
    
    # Read usercache.json
    usercache_path = server_path / "usercache.json"
    if usercache_path.exists():
        try:
            data = json.loads(usercache_path.read_text(encoding='utf-8', errors='ignore'))
            for entry in data:
                player_name = entry.get('name')
                player_uuid = entry.get('uuid')
                
                if not player_name:
                    continue
                
                # Get or create profile
                profile = db.query(PlayerProfile).filter(
                    and_(
                        PlayerProfile.server_name == server_name,
                        PlayerProfile.player_name == player_name
                    )
                ).first()
                
                if not profile:
                    profile = PlayerProfile(
                        server_name=server_name,
                        player_name=player_name,
                        player_uuid=player_uuid
                    )
                    db.add(profile)
                else:
                    profile.player_uuid = player_uuid
                
                synced += 1
        except Exception as e:
            print(f"Error reading usercache.json: {e}")
    
    # Read whitelist
    whitelist_path = server_path / "whitelist.json"
    if whitelist_path.exists():
        try:
            data = json.loads(whitelist_path.read_text(encoding='utf-8', errors='ignore'))
            for entry in data:
                player_name = entry.get('name')
                
                if not player_name:
                    continue
                
                profile = db.query(PlayerProfile).filter(
                    and_(
                        PlayerProfile.server_name == server_name,
                        PlayerProfile.player_name == player_name
                    )
                ).first()
                
                if profile:
                    profile.is_whitelisted = True
        except Exception as e:
            print(f"Error reading whitelist.json: {e}")
    
    # Read ops
    ops_path = server_path / "ops.json"
    if ops_path.exists():
        try:
            data = json.loads(ops_path.read_text(encoding='utf-8', errors='ignore'))
            for entry in data:
                player_name = entry.get('name')
                
                if not player_name:
                    continue
                
                profile = db.query(PlayerProfile).filter(
                    and_(
                        PlayerProfile.server_name == server_name,
                        PlayerProfile.player_name == player_name
                    )
                ).first()
                
                if profile:
                    profile.is_op = True
        except Exception as e:
            print(f"Error reading ops.json: {e}")
    
    # Read banned players
    banned_path = server_path / "banned-players.json"
    if banned_path.exists():
        try:
            data = json.loads(banned_path.read_text(encoding='utf-8', errors='ignore'))
            for entry in data:
                player_name = entry.get('name')
                
                if not player_name:
                    continue
                
                profile = db.query(PlayerProfile).filter(
                    and_(
                        PlayerProfile.server_name == server_name,
                        PlayerProfile.player_name == player_name
                    )
                ).first()
                
                if profile:
                    profile.is_banned = True
        except Exception as e:
            print(f"Error reading banned-players.json: {e}")
    
    db.commit()
    
    return {"message": f"Synced {synced} player profiles"}


# ==================== Bulk Whitelist ====================

@router.post("/bulk-whitelist/{server_name}")
async def bulk_whitelist(
    server_name: str,
    request: BulkWhitelistRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Add multiple players to whitelist at once"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    target_server = next((s for s in servers if s.get("name") == server_name), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    container_id = target_server.get("id")
    if not container_id:
        raise HTTPException(status_code=400, detail="Server container not found")
    
    added = []
    failed = []
    
    for player_name in request.players:
        try:
            command = f"whitelist add {player_name}"
            manager.send_command(container_id, command)
            added.append(player_name)
            
            # Update profile
            profile = db.query(PlayerProfile).filter(
                and_(
                    PlayerProfile.server_name == server_name,
                    PlayerProfile.player_name == player_name
                )
            ).first()
            
            if profile:
                profile.is_whitelisted = True
            else:
                profile = PlayerProfile(
                    server_name=server_name,
                    player_name=player_name,
                    is_whitelisted=True
                )
                db.add(profile)
        
        except Exception as e:
            failed.append({'player': player_name, 'error': str(e)})
    
    db.commit()
    
    return {
        "message": f"Added {len(added)} players to whitelist",
        "added": added,
        "failed": failed
    }


@router.post("/import-whitelist/{server_name}")
async def import_whitelist_csv(
    server_name: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Import whitelist from CSV file"""
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be CSV format")
    
    content = await file.read()
    text = content.decode('utf-8')
    
    players = []
    reader = csv.reader(io.StringIO(text))
    
    for row in reader:
        if row and row[0]:
            player_name = row[0].strip()
            if player_name and not player_name.startswith('#'):
                players.append(player_name)
    
    # Use bulk whitelist endpoint
    request = BulkWhitelistRequest(players=players)
    return await bulk_whitelist(server_name, request, current_user, db)


# ==================== Temporary Bans ====================

@router.post("/temp-ban/{server_name}", response_model=TemporaryBanResponse)
async def create_temporary_ban(
    server_name: str,
    request: TemporaryBanRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Ban a player temporarily with auto-expiration"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    target_server = next((s for s in servers if s.get("name") == server_name), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    container_id = target_server.get("id")
    
    # Ban player
    command = f"ban {request.player_name} {request.reason or 'Temporary ban'}"
    manager.send_command(container_id, command)
    
    # Create temporary ban record
    expires_at = datetime.utcnow() + timedelta(hours=request.duration_hours)
    
    temp_ban = TemporaryBan(
        server_name=server_name,
        player_name=request.player_name,
        reason=request.reason,
        banned_by=current_user.id,
        expires_at=expires_at
    )
    
    db.add(temp_ban)
    
    # Update profile
    profile = db.query(PlayerProfile).filter(
        and_(
            PlayerProfile.server_name == server_name,
            PlayerProfile.player_name == request.player_name
        )
    ).first()
    
    if profile:
        profile.is_banned = True
    
    db.commit()
    db.refresh(temp_ban)
    
    return TemporaryBanResponse.model_validate(temp_ban)


@router.get("/temp-bans/{server_name}", response_model=List[TemporaryBanResponse])
async def get_temporary_bans(
    server_name: str,
    active_only: bool = True,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get list of temporary bans"""
    
    query = db.query(TemporaryBan).filter(TemporaryBan.server_name == server_name)
    
    if active_only:
        query = query.filter(TemporaryBan.is_active == True)
    
    bans = query.order_by(TemporaryBan.banned_at.desc()).all()
    
    return [TemporaryBanResponse.model_validate(b) for b in bans]


@router.post("/process-expired-bans/{server_name}")
async def process_expired_bans(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Process and unban expired temporary bans"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    target_server = next((s for s in servers if s.get("name") == server_name), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    container_id = target_server.get("id")
    
    # Find expired bans
    now = datetime.utcnow()
    expired_bans = db.query(TemporaryBan).filter(
        and_(
            TemporaryBan.server_name == server_name,
            TemporaryBan.is_active == True,
            TemporaryBan.expires_at <= now
        )
    ).all()
    
    unbanned = []
    
    for ban in expired_bans:
        try:
            # Unban player
            command = f"pardon {ban.player_name}"
            manager.send_command(container_id, command)
            
            # Update ban record
            ban.is_active = False
            ban.unbanned_at = now
            ban.auto_unbanned = True
            
            # Update profile
            profile = db.query(PlayerProfile).filter(
                and_(
                    PlayerProfile.server_name == server_name,
                    PlayerProfile.player_name == ban.player_name
                )
            ).first()
            
            if profile:
                profile.is_banned = False
            
            unbanned.append(ban.player_name)
        
        except Exception as e:
            print(f"Error unbanning {ban.player_name}: {e}")
    
    db.commit()
    
    return {
        "message": f"Processed {len(unbanned)} expired bans",
        "unbanned_players": unbanned
    }


# ==================== RCON Support ====================

@router.post("/rcon/{server_name}")
async def execute_rcon_command(
    server_name: str,
    request: RCONCommandRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Execute an RCON command on the server"""
    
    manager = get_docker_manager()
    servers = manager.list_servers()
    
    target_server = next((s for s in servers if s.get("name") == server_name), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    container_id = target_server.get("id")
    if not container_id:
        raise HTTPException(status_code=400, detail="Server container not found")
    
    try:
        # Send command via Docker exec (acts as RCON)
        output = manager.send_command(container_id, request.command)
        
        return {
            "command": request.command,
            "success": True,
            "output": output
        }
    
    except Exception as e:
        return {
            "command": request.command,
            "success": False,
            "error": str(e)
        }


# ==================== Session Tracking ====================

@router.post("/session/{server_name}/login")
async def record_player_login(
    server_name: str,
    player_name: str,
    ip_address: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Record a player login session"""
    
    # Create session
    session = PlayerSession(
        server_name=server_name,
        player_name=player_name,
        ip_address=ip_address
    )
    
    db.add(session)
    
    # Update or create profile
    profile = db.query(PlayerProfile).filter(
        and_(
            PlayerProfile.server_name == server_name,
            PlayerProfile.player_name == player_name
        )
    ).first()
    
    if not profile:
        profile = PlayerProfile(
            server_name=server_name,
            player_name=player_name,
            first_joined=datetime.utcnow(),
            is_online=True
        )
        db.add(profile)
    else:
        if not profile.first_joined:
            profile.first_joined = datetime.utcnow()
        profile.is_online = True
    
    profile.last_seen = datetime.utcnow()
    profile.last_ip = ip_address
    
    db.commit()
    
    return {"message": "Login recorded"}


@router.post("/session/{server_name}/logout")
async def record_player_logout(
    server_name: str,
    player_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Record a player logout session"""
    
    # Find most recent session without logout
    session = db.query(PlayerSession).filter(
        and_(
            PlayerSession.server_name == server_name,
            PlayerSession.player_name == player_name,
            PlayerSession.logout_time == None
        )
    ).order_by(PlayerSession.login_time.desc()).first()
    
    if session:
        session.logout_time = datetime.utcnow()
        duration = (session.logout_time - session.login_time).total_seconds() / 60
        session.duration_minutes = int(duration)
        
        # Update profile
        profile = db.query(PlayerProfile).filter(
            and_(
                PlayerProfile.server_name == server_name,
                PlayerProfile.player_name == player_name
            )
        ).first()
        
        if profile:
            profile.is_online = False
            profile.last_seen = datetime.utcnow()
            profile.total_playtime_minutes += session.duration_minutes
            profile.session_count += 1
    
    db.commit()
    
    return {"message": "Logout recorded"}
