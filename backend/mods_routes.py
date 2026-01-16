from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel

from auth import require_auth, require_moderator
from models import User
from file_manager import upload_file as fm_upload_file, delete_path as fm_delete_path
from config import SERVERS_ROOT
import mod_sources

router = APIRouter(prefix="/mods", tags=["mods"])


def _server_dir(server_name: str) -> Path:
    server_dir = (SERVERS_ROOT / server_name).resolve()
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    return server_dir


def _mods_dir(server_name: str) -> Path:
    base = _server_dir(server_name)
    mdir = base / "mods"
    mdir.mkdir(parents=True, exist_ok=True)
    return mdir


@router.get("/{server_name}")
async def list_mods(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """List mod JARs in the server's mods directory."""
    mdir = _mods_dir(server_name)
    items: List[dict] = []
    for p in sorted(mdir.glob("*.jar")):
        items.append({
            "name": p.name,
            "size": p.stat().st_size,
            "modified": int(p.stat().st_mtime),
        })
    return {"mods": items}


@router.post("/{server_name}/upload")
async def upload_mod(
    server_name: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_auth),
):
    """Upload a mod JAR into the mods directory."""
    if file is None or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="No file provided")
    if not (file.filename and file.filename.lower().endswith(".jar")):
        raise HTTPException(status_code=400, detail="Only .jar files are allowed")
    
    fm_upload_file(server_name, "mods", file)
    return {"ok": True}


@router.delete("/{server_name}/{mod_file}")
async def delete_mod(
    server_name: str,
    mod_file: str,
    current_user: User = Depends(require_moderator),
):
    """Delete a mod JAR from the mods directory."""
    
    if "/" in mod_file or ".." in mod_file:
        raise HTTPException(status_code=400, detail="Invalid mod file")
    path = f"mods/{mod_file}"
    fm_delete_path(server_name, path)
    return {"ok": True}


# ===== New endpoints for mod search and install =====

@router.get("/{server_name}/sources")
async def list_mod_sources(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """List available mod sources."""
    sources = [
        {"id": "modrinth", "name": "Modrinth", "available": True},
    ]
    # Check if CurseForge is available
    cf_client = mod_sources.CurseForgeClient()
    sources.append({
        "id": "curseforge",
        "name": "CurseForge",
        "available": cf_client.is_available(),
    })
    return {"sources": sources}


@router.get("/{server_name}/search")
async def search_mods(
    server_name: str,
    query: str,
    source: str = "modrinth",
    version: Optional[str] = None,
    loader: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(require_auth),
):
    """Search for mods from external sources."""
    # Validate source
    if source not in ("modrinth", "curseforge"):
        raise HTTPException(status_code=400, detail="Invalid source. Use 'modrinth' or 'curseforge'")
    
    try:
        result = await mod_sources.search_mods(
            query=query,
            source=source,
            game_version=version,
            loader=loader,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/{server_name}/versions/{project_id}")
async def get_mod_versions(
    server_name: str,
    project_id: str,
    source: str = "modrinth",
    version: Optional[str] = None,
    loader: Optional[str] = None,
    current_user: User = Depends(require_auth),
):
    """Get available versions for a mod."""
    try:
        versions = await mod_sources.get_mod_versions(
            project_id=project_id,
            source=source,
            game_version=version,
            loader=loader,
        )
        return {"versions": versions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get versions: {str(e)}")


class ModInstallRequest(BaseModel):
    url: str
    filename: Optional[str] = None


@router.post("/{server_name}/install")
async def install_mod(
    server_name: str,
    payload: ModInstallRequest,
    current_user: User = Depends(require_auth),
):
    """Install a mod by downloading from URL."""
    # Validate server exists
    _server_dir(server_name)
    
    result = await mod_sources.download_mod_to_server(
        url=payload.url,
        server_name=server_name,
        dest_folder="mods",
        filename=payload.filename,
    )
    
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Download failed"))
    
    return result

