from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging

from database import get_db
from models import PlayerAction, User
from auth import require_auth, require_moderator
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT
import os, json, re, gzip, datetime as _dt

router = APIRouter(prefix="/players", tags=["player_management"])
logger = logging.getLogger(__name__)


class PlayerActionCreate(BaseModel):
    player_name: str
    action_type: str  
    reason: Optional[str] = None


class PlayerActionResponse(BaseModel):
    id: int
    server_name: str
    player_name: str
    action_type: str
    reason: Optional[str]
    performed_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True


class PlayerResponse(BaseModel):
    name: str
    uuid: Optional[str] = None


class RosterResponse(BaseModel):
    players: List[PlayerResponse]
    online: int
    max: int
    method: str
    error: Optional[str] = None


_manager_cache = None


def get_docker_manager():
    """Get the active runtime manager (local or Docker)."""
    global _manager_cache
    if _manager_cache is None:
        _manager_cache = get_runtime_manager_or_docker()
    return _manager_cache


def _server_dir(server_name: str):
    try:
        p = (SERVERS_ROOT / server_name).resolve()
        if str(p).startswith(str(SERVERS_ROOT.resolve())):
            return p
    except Exception:
        pass
    return None


def _parse_log_timestamp(line: str, fallback_date: _dt.date | None) -> int | None:
    """Extract a timestamp (epoch seconds) from a log line if possible.
    Supports patterns like '2025-11-10 12:34:56' or '[12:34:56]'.
    """
    try:
        m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", line)
        if m:
            ts = f"{m.group(1)} {m.group(2)}"
            dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            return int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())
        m2 = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", line)
        if m2 and fallback_date:
            ts = f"{fallback_date.isoformat()} {m2.group(1)}"
            dt = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            return int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())
    except Exception:
        return None
    return None


def _collect_history(server_name: str, limit_files: int = 6, limit_lines: int = 8000) -> dict[str, dict]:
    """Scan recent logs and usercache.json to build {name: {last_seen, sources}}.
    Returns a map keyed by lowercase name.
    """
    try:
        base = _server_dir(server_name)
    except HTTPException:
        return {}
    hist: dict[str, dict] = {}
    if not base:
        return hist
    
    try:
        uc = base / "usercache.json"
        if uc.exists():
            data = json.loads(uc.read_text(encoding="utf-8", errors="ignore") or "[]")
            for ent in data or []:
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                k = name.lower()
                rec = hist.setdefault(k, {"name": name, "last_seen": None, "sources": set()})
                rec["sources"].add("usercache")
    except Exception:
        pass
    
    try:
        candidates = []
        latest = base / "logs" / "latest.log"
        if latest.exists():
            candidates.append(latest)
        logs_dir = base / "logs"
        if logs_dir.exists() and logs_dir.is_dir():
            for p in logs_dir.iterdir():
                if p.name == "latest.log":
                    continue
                if p.suffix in (".log", ".gz"):
                    candidates.append(p)
        
        candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        candidates = candidates[:limit_files]
        total_lines = 0
        joined_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (joined the game|logged in)", re.IGNORECASE)
        left_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (left the game|logged out)", re.IGNORECASE)
        
        for p in candidates:
            try:
                fallback_date = _dt.date.fromtimestamp(p.stat().st_mtime)
            except Exception:
                fallback_date = None
            
            lines: list[str] = []
            try:
                if p.suffix == ".gz":
                    with gzip.open(p, "rt", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                else:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
            except Exception:
                continue
            
            for line in reversed(lines):
                if total_lines >= limit_lines:
                    break
                total_lines += 1
                m = joined_re.search(line) or left_re.search(line)
                if not m:
                    continue
                name = m.group(1)
                k = name.lower()
                ts = _parse_log_timestamp(line, fallback_date)
                rec = hist.setdefault(k, {"name": name, "last_seen": None, "sources": set()})
                if ts and (rec["last_seen"] is None or int(ts) > int(rec["last_seen"])):
                    rec["last_seen"] = int(ts)
                rec["sources"].add("logs")
    except Exception:
        pass
    
    for v in hist.values():
        if isinstance(v.get("sources"), set):
            v["sources"] = sorted(list(v["sources"]))
    return hist


def _filter_client_players(players: list[str]) -> list[str]:
    """Filter out 'Client' entries from player list."""
    return [p for p in players if p.lower() not in ("client", "")]


async def _get_players_via_mcstatus(server_name: str) -> dict:
    """Get player list via mcstatus/JavaServer query (primary method - no RCON needed)."""
    try:
        dm = get_runtime_manager_or_docker()
        servers = dm.list_servers()
        target = next((s for s in servers if s.get("name") == server_name), None)
        if not target:
            return {"players": [], "online": 0, "max": 0, "error": "Server not found"}
        
        cid = target.get("id")
        if not cid:
            return {"players": [], "online": 0, "max": 0, "error": "Server container not found"}
        
        container = get_docker_manager()._get_container_any(cid)
        env_vars = container.attrs.get("Config", {}).get("Env", [])
        env_dict = dict(var.split("=", 1) for var in env_vars if "=" in var)
        
        # Get server port from environment
        server_port = env_dict.get("SERVER_PORT") or env_dict.get("MINECRAFT_PORT") or "25565"
        
        from mcstatus import JavaServer
        java_server = JavaServer.lookup(f"localhost:{server_port}")
        status = java_server.status(timeout=3)
        
        players = []
        if status.players and status.players.sample:
            for player in status.players.sample:
                players.append({
                    "name": player.name,
                    "uuid": str(player.id) if hasattr(player, 'id') and player.id else None
                })
        
        online = status.players.online if status.players else 0
        maxp = status.players.max if status.players else 0
        
        # Filter out "Client" entries
        filtered_players = [p for p in players if p["name"].lower() not in ("client", "")]
        
        return {"players": filtered_players, "online": online, "max": maxp}
        
    except Exception as e:
        logger.warning(f"mcstatus player list failed for {server_name}: {e}")
        return {"players": [], "online": 0, "max": 0, "error": f"Failed to query server: {str(e)}"}


def _filter_client_players(players: list[str]) -> list[str]:
    """Filter out 'Client' entries from player list."""
    return [p for p in players if p.lower() not in ("client", "")]


async def _get_players_via_rcon(server_name: str) -> dict:
    """Get player list directly via RCON (fallback method)."""
    try:
        dm = get_runtime_manager_or_docker()
        servers = dm.list_servers()
        target = next((s for s in servers if s.get("name") == server_name), None)
        if not target:
            return {"players": [], "online": 0, "max": 0, "error": "Server not found"}
        
        cid = target.get("id")
        if not cid:
            return {"players": [], "online": 0, "max": 0, "error": "Server container not found"}
        
        container = dm._get_container_any(cid)
        env_vars = container.attrs.get("Config", {}).get("Env", [])
        env_dict = dict(var.split("=", 1) for var in env_vars if "=" in var)
        
        # Get RCON config from environment
        rcon_password = env_dict.get("RCON_PASSWORD") or env_dict.get("RCON_PASSWORD") or ""
        rcon_port = env_dict.get("RCON_PORT") or "25575"
        
        if not rcon_password:
            return {"players": [], "online": 0, "max": 0, "error": "RCON not configured"}
        
        from mcrcon import MCRcon
        import re
        
        with MCRcon("localhost", rcon_password, port=int(rcon_port), timeout=3) as mcr:
            output = mcr.command("list") or ""
            text = str(output)
            online = 0
            maxp = 0
            names: list[str] = []
            
            # Parse "There are X of a max of Y players online: name1, name2, ..."
            m = re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", text)
            if m:
                online = int(m.group(1))
                maxp = int(m.group(2))
                colon_idx = text.find(":")
                if colon_idx != -1 and colon_idx + 1 < len(text):
                    names_str = text[colon_idx + 1:].strip()
                    if names_str:
                        names = [n.strip() for n in names_str.split(",") if n.strip()]
            
            # Filter out "Client" entries
            filtered_names = [n for n in names if n.lower() not in ("client", "")]
            
            return {"players": filtered_names, "online": online, "max": maxp, "method": "rcon"}
            
    except Exception as e:
        logger.warning(f"RCON player list failed for {server_name}: {e}")
        return {"players": [], "online": 0, "max": 0, "error": f"RCON failed: {str(e)}"}


def _filter_client_players(players: list[str]) -> list[str]:
    """Filter out 'Client' entries from player list."""
    return [p for p in players if p.lower() not in ("client", "")]


@router.get("/{server_name}/roster", response_model=RosterResponse)
async def get_roster(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    """
    Get player roster for a Minecraft server.
    Uses server status query (mcstatus) as primary method - NO RCON needed!
    """
    # Get server info
    dm = get_runtime_manager_or_docker()
    servers = dm.list_servers()
    target = next((s for s in servers if s.get("name") == server_name), None)
    if not target:
        return RosterResponse(players=[], online=0, max=0, method="error", error="Server not found")
    
    # Check if server is running
    if target.get("status") != "running":
        return RosterResponse(players=[], online=0, max=0, method="error", error="Server is not running")
    
    # Try mcstatus first (primary method - no RCON needed)
    mcstatus_result = await _get_players_via_mcstatus(server_name)
    
    if mcstatus_result.get("players"):
        # Success with mcstatus
        players = [PlayerResponse(name=p["name"], uuid=p.get("uuid")) for p in mcstatus_result["players"]]
        return RosterResponse(
            players=players,
            online=mcstatus_result.get("online", len(mcstatus_result["players"])),
            max=mcstatus_result.get("max", 0),
            method="mcstatus"
        )
    
    # If mcstatus failed, try RCON as fallback
    rcon_result = await _get_players_via_rcon(server_name)
    
    if rcon_result.get("players"):
        players = [PlayerResponse(name=p) for p in rcon_result["players"]]
        return RosterResponse(
            players=players,
            online=rcon_result.get("online", len(rcon_result["players"])),
            max=rcon_result.get("max", 0),
            method=rcon_result.get("method", "rcon")
        )
    
    # Both failed
    error = mcstatus_result.get("error") or rcon_result.get("error") or "Failed to get player list"
    return RosterResponse(players=[], online=0, max=0, method="error", error=error)


def _filter_client_players(players: list[str]) -> list[str]:
    """Filter out 'Client' entries from player list."""
    return [p for p in players if p.lower() not in ("client", "")]

@router.get("/{server_name}/actions", response_model=List[PlayerActionResponse])
async def list_player_actions(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List all player actions for a server."""
    actions = db.query(PlayerAction).filter(
        PlayerAction.server_name == server_name
    ).order_by(PlayerAction.performed_at.desc()).all()
    
    return actions


@router.post("/{server_name}/whitelist", response_model=PlayerActionResponse)
async def whitelist_player(
    server_name: str,
    action_data: PlayerActionCreate,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Add a player to the whitelist."""
    if action_data.action_type != "whitelist":
        action_data.action_type = "whitelist"
    
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        command = f"whitelist add {action_data.player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = PlayerAction(
            server_name=server_name,
            player_name=action_data.player_name,
            action_type="whitelist",
            reason=action_data.reason,
            performed_by=current_user.id,
            is_active=True
        )
        
        db.add(player_action)
        db.commit()
        db.refresh(player_action)
        
        return player_action
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to whitelist player: {str(e)}"
        )


@router.delete("/{server_name}/whitelist/{player_name}")
async def remove_from_whitelist(
    server_name: str,
    player_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Remove a player from the whitelist."""
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        command = f"whitelist remove {player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = db.query(PlayerAction).filter(
            PlayerAction.server_name == server_name,
            PlayerAction.player_name == player_name,
            PlayerAction.action_type == "whitelist",
            PlayerAction.is_active == True
        ).first()
        
        if player_action:
            try:
                
                setattr(player_action, 'is_active', False)
                db.commit()
            except Exception:
                pass
        
        return {"message": f"Player {player_name} removed from whitelist"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove player from whitelist: {str(e)}"
        )


@router.post("/{server_name}/ban", response_model=PlayerActionResponse)
async def ban_player(
    server_name: str,
    action_data: PlayerActionCreate,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Ban a player from the server."""
    if action_data.action_type != "ban":
        action_data.action_type = "ban"
    
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        if action_data.reason:
            command = f"ban {action_data.player_name} {action_data.reason}"
        else:
            command = f"ban {action_data.player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = PlayerAction(
            server_name=server_name,
            player_name=action_data.player_name,
            action_type="ban",
            reason=action_data.reason,
            performed_by=current_user.id,
            is_active=True
        )
        
        db.add(player_action)
        db.commit()
        db.refresh(player_action)
        
        return player_action
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ban player: {str(e)}"
        )


@router.delete("/{server_name}/ban/{player_name}")
async def unban_player(
    server_name: str,
    player_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Unban a player from the server."""
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        command = f"pardon {player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = db.query(PlayerAction).filter(
            PlayerAction.server_name == server_name,
            PlayerAction.player_name == player_name,
            PlayerAction.action_type == "ban",
            PlayerAction.is_active == True
        ).first()
        
        if player_action:
            try:
                setattr(player_action, 'is_active', False)
                db.commit()
            except Exception:
                pass
        
        return {"message": f"Player {player_name} unbanned"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unban player: {str(e)}"
        )


@router.post("/{server_name}/kick")
async def kick_player(
    server_name: str,
    action_data: PlayerActionCreate,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Kick a player from the server."""
    if action_data.action_type != "kick":
        action_data.action_type = "kick"
    
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        if action_data.reason:
            command = f"kick {action_data.player_name} {action_data.reason}"
        else:
            command = f"kick {action_data.player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = PlayerAction(
            server_name=server_name,
            player_name=action_data.player_name,
            action_type="kick",
            reason=action_data.reason,
            performed_by=current_user.id,
            is_active=True
        )
        
        db.add(player_action)
        db.commit()
        db.refresh(player_action)
        
        return {"message": f"Player {action_data.player_name} kicked"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to kick player: {str(e)}"
        )


@router.post("/{server_name}/op", response_model=PlayerActionResponse)
async def op_player(
    server_name: str,
    action_data: PlayerActionCreate,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Give operator privileges to a player."""
    if action_data.action_type != "op":
        action_data.action_type = "op"
    
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        command = f"op {action_data.player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = PlayerAction(
            server_name=server_name,
            player_name=action_data.player_name,
            action_type="op",
            reason=action_data.reason,
            performed_by=current_user.id,
            is_active=True
        )
        
        db.add(player_action)
        db.commit()
        db.refresh(player_action)
        
        return player_action
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to OP player: {str(e)}"
        )


@router.delete("/{server_name}/op/{player_name}")
async def deop_player(
    server_name: str,
    player_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Remove operator privileges from a player."""
    try:
        
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        
        command = f"deop {player_name}"
        docker_manager.send_command(container_id, command)
        
        
        player_action = db.query(PlayerAction).filter(
            PlayerAction.server_name == server_name,
            PlayerAction.player_name == player_name,
            PlayerAction.action_type == "op",
            PlayerAction.is_active == True
        ).first()
        
        if player_action:
            try:
                setattr(player_action, 'is_active', False)
                db.commit()
            except Exception:
                pass
        
        return {"message": f"Player {player_name} de-opped"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to de-OP player: {str(e)}"
        )


@router.get("/{server_name}/online")
async def get_online_players(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    """Get list of currently online players."""
@router.get("/{server_name}/online")
async def get_online_players(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    """Get list of currently online players."""
    try:
        docker_manager = get_docker_manager()
        servers = docker_manager.list_servers()
        
        target_server = None
        for server in servers:
            if server.get("name") == server_name:
                target_server = server
                break
        
        if not target_server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found"
            )
        
        container_id = target_server.get("id")
        if not container_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server container not found"
            )
        
        try:
            info = docker_manager.get_player_info(container_id)
            names = _filter_client_players([n for n in (info.get('names') or []) if isinstance(n, str)])
            online = info.get('online') or 0
            maxp = info.get('max') or info.get('max_players') or 0
            method = info.get('method') or 'none'
            return {"players": names, "count": online, "max": maxp, "method": method}
        except Exception:
            pass
        
        # Fallback: RCON list command
        try:
            result = docker_manager.send_command(container_id, "list")
            text = result if isinstance(result, str) else (result.get('output') if isinstance(result, dict) else '')
            import re as _re
            m = _re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", str(text))
            if not m:
                m = _re.search(r"(\d+)\s*/\s*(\d+)\s+players? online", str(text))
            names = []
            online = int(m.group(1)) if m else 0
            maxp = int(m.group(2)) if m else 0
        except Exception:
            names = []
            online = 0
            maxp = 0
        
        return {"players": _filter_client_players(names), "count": online, "max": maxp}
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get online players: {str(e)}"
        )