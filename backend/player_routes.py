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


# NOTE: the roster endpoint returns a plain dict (see get_roster below) whose
# shape matches PlayersPanel.jsx: online=[names], offline=[{name,last_seen}],
# count, max, players (legacy alias), method. Do not re-add a pydantic
# response_model here — it silently coerced `online` to int and broke the UI.

_manager_cache = None


def get_docker_manager():
    """Get the active runtime manager (local or Docker)."""
    global _manager_cache
    if _manager_cache is None:
        _manager_cache = get_runtime_manager_or_docker()
    return _manager_cache


def _server_dir(server_name: str):
    """Resolve server directory with case-insensitive fallback.

    The UI passes the Docker container name (exact case). Users sometimes create
    names with mixed case; the filesystem on Linux is case-sensitive. We first
    try the exact path, then scan SERVERS_ROOT for a lower-case match.
    """
    try:
        p = (SERVERS_ROOT / server_name).resolve()
        if str(p).startswith(str(SERVERS_ROOT.resolve())) and p.exists():
            return p
    except Exception:
        pass
    # Case-insensitive scan fallback
    try:
        if SERVERS_ROOT.exists():
            needle = server_name.lower()
            for child in SERVERS_ROOT.iterdir():
                try:
                    if child.is_dir() and child.name.lower() == needle:
                        # Return resolved child, still must be under SERVERS_ROOT
                        cp = child.resolve()
                        if str(cp).startswith(str(SERVERS_ROOT.resolve())):
                            return cp
                except Exception:
                    continue
    except Exception:
        pass
    # Last resort: return the exact path even if not exists so callers can
    # still attempt disk reads (they will just miss). Preserve original behavior.
    try:
        p = (SERVERS_ROOT / server_name).resolve()
        if str(p).startswith(str(SERVERS_ROOT.resolve())):
            return p
    except Exception:
        pass
    return None


def _docker_logs_online_fallback(server_name: str) -> tuple[list[str], str]:
    """Try to derive online players directly from Docker container logs.

    This works even when SERVERS_ROOT is empty or server.properties RCON is
    disabled and mcstatus can't reach the server (localhost vs host port
    mismatch in Docker). Returns (names, source) or ([], "").
    """
    try:
        dm = get_docker_manager()
        servers = dm.list_servers() or []
        target = next(
            (s for s in servers if (s.get("name") or "").lower() == server_name.lower()
             or (s.get("id") or "") == server_name),
            None,
        )
        if not target:
            # Try loose match: any server whose name contains the hint
            # (covers e.g. truncated IDs)
            for s in servers:
                n = (s.get("name") or "")
                if n and (n.lower() in server_name.lower() or server_name.lower() in n.lower()):
                    target = s
                    break
        if not target:
            return [], ""
        cid = target.get("id") or target.get("name") or server_name
        # Use DockerManager's own get_player_info docker_logs branch by
        # calling it directly; it already handles join/leave parsing.
        # But to avoid recursion, call the low-level log scan here.
        try:
            c = dm._get_container_any(cid)  # type: ignore[attr-defined]
            log_output = c.logs(tail=400, timestamps=False).decode(errors="ignore")
            lines = log_output.splitlines()
            online_set: dict[str, bool] = {}
            joined_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (joined the game|logged in)", re.IGNORECASE)
            left_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (left the game|logged out|lost connection)", re.IGNORECASE)
            stop_re = re.compile(r"(Stopping the server|Stopping server|Server closed|Closing Server)", re.IGNORECASE)
            for line in lines:
                if stop_re.search(line):
                    online_set.clear()
                    continue
                jm = joined_re.search(line)
                if jm:
                    online_set[jm.group(1)] = True
                    continue
                lm = left_re.search(line)
                if lm:
                    online_set.pop(lm.group(1), None)
            names = _filter_client_players([n for n, v in online_set.items() if v])
            if names:
                return names, "docker_logs"
        except Exception as e:
            logger.debug(f"docker logs online fallback failed for {server_name}: {e}")
    except Exception as e:
        logger.debug(f"docker logs lookup failed for {server_name}: {e}")
    return [], ""


def _docker_logs_history_fallback(server_name: str, existing: dict[str, dict]) -> dict[str, dict]:
    """Populate history from Docker logs when filesystem history is empty."""
    if existing:
        return existing
    try:
        dm = get_docker_manager()
        servers = dm.list_servers() or []
        target = next(
            (s for s in servers if (s.get("name") or "").lower() == server_name.lower()
             or (s.get("id") or "") == server_name),
            None,
        )
        if not target:
            return existing
        cid = target.get("id") or server_name
        try:
            c = dm._get_container_any(cid)  # type: ignore[attr-defined]
            log_output = c.logs(tail=600, timestamps=False).decode(errors="ignore")
            lines = log_output.splitlines()
            hist = dict(existing)
            joined_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (joined the game|logged in)", re.IGNORECASE)
            left_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (left the game|logged out)", re.IGNORECASE)
            for line in reversed(lines[-8000:]):
                m = joined_re.search(line) or left_re.search(line)
                if not m:
                    continue
                name = m.group(1)
                k = name.lower()
                if k in hist:
                    continue
                rec = hist.setdefault(k, {"name": name, "last_seen": None, "sources": set()})
                rec["sources"].add("docker_logs")
            for v in hist.values():
                if isinstance(v.get("sources"), set):
                    v["sources"] = sorted(list(v["sources"]))
            return hist
        except Exception as e:
            logger.debug(f"docker logs history fallback failed for {server_name}: {e}")
    except Exception:
        pass
    return existing


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
    # Docker logs fallback when filesystem yielded nothing (common on fresh
    # Docker volumes or when logs are buffered inside the container).
    try:
        if not hist:
            hist = _docker_logs_history_fallback(server_name, hist)
    except Exception:
        pass
    return hist


def _filter_client_players(players: list[str]) -> list[str]:
    """Filter out 'Client' entries from the player list."""
    return [p for p in players if isinstance(p, str) and p.lower() not in ("client", "")]


def _roster_online_from_disk(server_name: str) -> tuple[list[str], str]:
    """Best-effort online-player extraction straight from the server directory.

    Works for BOTH runtimes because SERVERS_ROOT is a shared volume:
      1. server.properties RCON (enable-rcon/rcon.password/rcon.port) → `list`
      2. logs/latest.log (+ rotated .log) join/leave tracking

    Returns (names, source) where source is 'rcon-props' | 'log_parse' | ''.
    """
    try:
        base = _server_dir(server_name)
    except HTTPException:
        return [], ""
    if not base:
        return [], ""

    # 1) RCON via server.properties (independent of container env vars)
    props = base / "server.properties"
    if props.exists():
        rcon_enabled = rcon_pass = ""
        rcon_port = 25575
        try:
            for line in props.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip()
                if s.startswith("enable-rcon="):
                    rcon_enabled = s.split("=", 1)[1].strip().lower()
                elif s.startswith("rcon.password="):
                    rcon_pass = s.split("=", 1)[1].strip()
                elif s.startswith("rcon.port="):
                    try:
                        rcon_port = int(s.split("=", 1)[1].strip())
                    except ValueError:
                        pass
            if rcon_enabled == "true" and rcon_pass:
                try:
                    from mcrcon import MCRcon
                    with MCRcon("localhost", rcon_pass, port=rcon_port, timeout=2) as mcr:
                        text = str(mcr.command("list") or "")
                        m = re.search(
                            r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", text
                        ) or re.search(r"(\d+)\s*/\s*(\d+)\s*players? online", text)
                        names: list[str] = []
                        if m:
                            colon = text.find(":")
                            if colon != -1:
                                names = [n.strip() for n in text[colon + 1:].split(",") if n.strip()]
                        names = _filter_client_players(names)
                        if names:
                            return names, "rcon-props"
                except Exception as e:
                    logger.debug(f"disk RCON list failed for {server_name}: {e}")
        except Exception as e:
            logger.debug(f"server.properties parse failed for {server_name}: {e}")

    # 2) Join/leave tracking across recent logs (newest first)
    joined_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (joined the game|logged in)", re.IGNORECASE)
    left_re = re.compile(r"([A-Za-z0-9_\-]{2,16}) (left the game|logged out|lost connection)", re.IGNORECASE)
    stop_re = re.compile(r"Stopping the server|Stopping server|Server closed|Closing Server", re.IGNORECASE)

    candidates = []
    latest = base / "logs" / "latest.log"
    if latest.exists():
        candidates.append(latest)
    logs_dir = base / "logs"
    if logs_dir.is_dir():
        try:
            candidates.extend(
                p for p in logs_dir.iterdir()
                if p != latest and p.suffix in (".log", ".gz")
            )
        except OSError:
            pass
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    online: dict[str, bool] = {}
    try:
        for p in candidates[:6]:
            try:
                if p.suffix == ".gz":
                    import gzip
                    with gzip.open(p, "rt", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                else:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
            except OSError:
                continue
            for line in reversed(lines):
                if stop_re.search(line):
                    online.clear()
                    continue
                jm = joined_re.search(line)
                if jm:
                    online[jm.group(1)] = True
                    continue
                lm = left_re.search(line)
                if lm:
                    online.pop(lm.group(1), None)
            if online:
                break  # newest log with activity wins
    except Exception as e:
        logger.debug(f"log scan failed for {server_name}: {e}")

    names = _filter_client_players([n for n, ok in online.items() if ok])
    if names:
        return names, "log_parse"
    # Filesystem logs empty -> try Docker container logs directly
    try:
        d_names, d_src = _docker_logs_online_fallback(server_name)
        if d_names:
            return d_names, d_src
    except Exception:
        pass
    return [], ""


@router.get("/{server_name}/roster")
def get_roster(server_name: str, current_user: User = Depends(require_auth)):
    """Player roster for the Players panel.

    Contract (frontend/src/components/server-details/PlayersPanel.jsx):
      online  — list of currently-connected player names
      offline — [{name, last_seen}] sorted most-recent first
      count / max / method
    Never raises for lookup failures; degrades to logs-only history so the
    panel still renders. `method` mirrors dm.get_player_info's probe chain
    (mcstatus → rcon → log_parse) or one of:
      server-stopped | server-not-found | error
    """
    online_names: list[str] = []
    count = 0
    max_players = 0
    method = "unknown"
    target = None

    try:
        dm = get_docker_manager()
        servers = dm.list_servers() or []
        # exact match first, then case-insensitive, then id prefix
        target = next(
            (s for s in servers
             if s.get("name") == server_name or s.get("id") == server_name),
            None,
        )
        if target is None:
            lower = server_name.lower()
            target = next(
                (s for s in servers if (s.get("name") or "").lower() == lower),
                None,
            )
        if target is None and servers:
            # last chance: id prefix (Docker short id) or name contains
            for s in servers:
                sid = s.get("id") or ""
                if sid and (sid.startswith(server_name) or server_name.startswith(sid[:12])):
                    target = s
                    break
        if target is None:
            logger.info(f"roster: server-not-found for '{server_name}' among {[s.get('name') for s in servers]}")
            method = "server-not-found"
        elif target.get("status") != "running":
            method = "server-stopped"
        else:
            cid = target.get("id") or server_name
            info = dm.get_player_info(cid) or {}
            online_names = _filter_client_players(info.get("names") or [])
            count = int(info.get("online") or len(online_names))
            max_players = int(info.get("max") or 0)
            method = info.get("method") or "unknown"
    except Exception as e:  # never 500 the panel over a stats nicety
        logger.warning(f"roster live lookup failed for {server_name}: {e}")
        method = "error"

    # Disk fallback: the server directory is on the shared volume in both
    # runtimes, so server.properties RCON + join/leave logs work even when the
    # live probe chain can't reach the server (mcstatus localhost fails
    # container-to-container, RCON env vars missing, docker sock hiccup...).
    probe_failed = method in ("error", "unknown", "server-not-found")
    names_without_count = bool(count > 0 and not online_names)
    # Also try disk/docker fallback whenever live probe returned no names - the
    # Docker network's localhost often can't reach the Minecraft port from the
    # controller container, but container logs on the host do contain joins.
    should_try_disk = probe_failed or names_without_count or not online_names
    # Don't override a definitive server-stopped state with stale log data.
    if method == "server-stopped":
        should_try_disk = False
    if should_try_disk:
        try:
            disk_names, disk_src = _roster_online_from_disk(server_name)
            if disk_names:
                online_names = disk_names
                count = max(count, len(disk_names))
                method = disk_src
            elif probe_failed:
                method = "mcstatus-failed"  # frontend shows a clear, honest banner
        except Exception as e:
            logger.warning(f"roster disk fallback failed for {server_name}: {e}")
            if probe_failed:
                method = "mcstatus-failed"

    # Offline history from usercache.json + rotated logs (works even when the
    # live query fails, e.g. RCON disabled and mcstatus unreachable).
    hist = _collect_history(server_name)
    online_set = {n.lower() for n in online_names}
    offline = [
        {"name": rec.get("name"), "last_seen": rec.get("last_seen")}
        for k, rec in hist.items()
        if k not in online_set
    ]
    offline.sort(key=lambda x: (x.get("last_seen") or 0), reverse=True)

    return {
        "online": online_names,
        "offline": offline,
        "count": count,
        "max": max_players,
        "players": online_names,  # legacy alias for older consumers
        "method": method,
    }


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
def get_online_players(
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