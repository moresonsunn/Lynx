from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel

from database import get_db
from auth import require_auth, require_moderator
from models import User
from file_manager import upload_file as fm_upload_file, delete_path as fm_delete_path
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT
import mod_sources

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _server_dir(server_name: str) -> Path:
    server_dir = (SERVERS_ROOT / server_name).resolve()
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    return server_dir


def _plugins_dir(server_name: str) -> Path:
    base = _server_dir(server_name)
    pdir = base / "plugins"
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


_manager_cache = None


def _get_docker_manager():
    global _manager_cache
    if _manager_cache is None:
        _manager_cache = get_runtime_manager_or_docker()
    return _manager_cache


@router.get("/{server_name}")
async def list_plugins(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """List plugin JARs in the server's plugins directory."""
    pdir = _plugins_dir(server_name)
    items: List[dict] = []
    for p in sorted(pdir.glob("*.jar")):
        items.append({
            "name": p.name,
            "size": p.stat().st_size,
            "modified": int(p.stat().st_mtime),
        })
    return {"plugins": items}


@router.post("/{server_name}/upload")
async def upload_plugin(
    server_name: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
):
    """Upload a plugin JAR into the plugins directory."""
    if file is None or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="No file provided")
    if not (file.filename and file.filename.lower().endswith(".jar")):
        raise HTTPException(status_code=400, detail="Only .jar files are allowed")
    
    fm_upload_file(server_name, "plugins", file)
    return {"ok": True}


@router.delete("/{server_name}/{plugin_file}")
async def delete_plugin(
    server_name: str,
    plugin_file: str,
    current_user: User = Depends(require_moderator),
):
    """Delete a plugin JAR from the plugins directory."""
    
    if "/" in plugin_file or ".." in plugin_file:
        raise HTTPException(status_code=400, detail="Invalid plugin file")
    path = f"plugins/{plugin_file}"
    fm_delete_path(server_name, path)
    return {"ok": True}


@router.post("/{server_name}/reload")
async def reload_plugins(
    server_name: str,
    current_user: User = Depends(require_moderator),
):
    """Reload plugins by issuing a server reload command."""
    dm = _get_docker_manager()
    servers = dm.list_servers()
    container_id = None
    for s in servers:
        if s.get("name") == server_name:
            container_id = s.get("id")
            break
    if not container_id:
        raise HTTPException(status_code=404, detail="Server container not found")
    
    resp = dm.send_command(container_id, "reload confirm")
    if resp.get("exit_code", 1) != 0:
        resp = dm.send_command(container_id, "reload")
    return {"ok": True, "method": resp.get("method"), "output": resp.get("output", "")}


# ===== New endpoints for plugin search and install =====

@router.get("/{server_name}/sources")
async def list_plugin_sources(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """List available plugin sources."""
    sources = [
        {"id": "modrinth", "name": "Modrinth", "available": True},
        {"id": "spiget", "name": "SpigotMC", "available": True},
    ]
    return {"sources": sources}


@router.get("/{server_name}/search")
async def search_plugins(
    server_name: str,
    query: str,
    source: str = "modrinth",
    version: Optional[str] = None,
    server_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(require_auth),
):
    """Search for plugins from external sources."""
    # Validate source
    if source not in ("modrinth", "spiget"):
        raise HTTPException(status_code=400, detail="Invalid source. Use 'modrinth' or 'spiget'")
    
    try:
        result = await mod_sources.search_plugins(
            query=query,
            source=source,
            game_version=version,
            server_type=server_type,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


class PluginInstallRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    resource_id: Optional[str] = None  # For Spiget resources
    source: str = "modrinth"


@router.post("/{server_name}/install")
async def install_plugin(
    server_name: str,
    payload: PluginInstallRequest,
    current_user: User = Depends(require_auth),
):
    """Install a plugin by downloading from URL."""
    # Validate server exists
    _server_dir(server_name)
    
    # For Spiget, get the download URL
    download_url = payload.url
    if payload.source == "spiget" and payload.resource_id:
        client = mod_sources.SpigetClient()
        download_url = await client.get_download_url(payload.resource_id)
    
    if not download_url:
        raise HTTPException(status_code=400, detail="No download URL provided")
    
    result = await mod_sources.download_mod_to_server(
        url=download_url,
        server_name=server_name,
        dest_folder="plugins",
        filename=payload.filename,
    )
    
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Download failed"))
    
    return result