"""
Client-Side Mod Management API Routes
======================================
Endpoints for analyzing, filtering, and managing client-only mods on servers.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path

from auth import require_auth, require_moderator
from models import User
from config import SERVERS_ROOT

router = APIRouter(prefix="/client-mods", tags=["client_mods"])


# ─── Request / Response Models ──────────────────────────────

class AnalyzeRequest(BaseModel):
    use_api: bool = True
    min_confidence: float = 0.6

class FilterRequest(BaseModel):
    use_api: bool = True
    min_confidence: float = 0.6
    dry_run: bool = False
    filenames: Optional[List[str]] = None  # If provided, only filter these specific files

class RestoreRequest(BaseModel):
    filename: str

class DisableRequest(BaseModel):
    filename: str

class WhitelistRequest(BaseModel):
    pattern: str


# ─── Endpoints ──────────────────────────────────────────────

@router.get("/analyze/{server_name}")
async def analyze_server_mods(
    server_name: str,
    use_api: bool = Query(True, description="Use Modrinth/CurseForge APIs for detection"),
    current_user: User = Depends(require_auth),
):
    """
    Analyze all mods in a server's mods directory for client-side detection.
    Returns detailed analysis for each mod including detection method and confidence.
    Does NOT move or disable any mods - this is read-only.
    """
    from client_mod_filter import analyze_mods_directory

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    mods_dir = server_dir / "mods"
    if not mods_dir.exists():
        return {
            "total_mods": 0,
            "client_only_count": 0,
            "server_or_both_count": 0,
            "unknown_count": 0,
            "mods": [],
        }

    # Get CurseForge API key if available
    cf_api_key = None
    try:
        from integrations_store import get_integration_key
        cf_api_key = get_integration_key("curseforge")
    except Exception:
        pass

    results = analyze_mods_directory(
        server_dir, use_api=use_api, cf_api_key=cf_api_key
    )

    mods_data = [r.to_dict() for r in results]
    client_count = sum(1 for r in results if r.is_client_only)
    server_count = sum(1 for r in results if not r.is_client_only and r.side.value != "unknown")
    unknown_count = sum(1 for r in results if r.side.value == "unknown" and not r.is_client_only)

    return {
        "total_mods": len(results),
        "client_only_count": client_count,
        "server_or_both_count": server_count,
        "unknown_count": unknown_count,
        "mods": mods_data,
    }


@router.post("/filter/{server_name}")
async def filter_server_mods(
    server_name: str,
    req: FilterRequest,
    current_user: User = Depends(require_moderator),
):
    """
    Filter (disable) client-only mods from a server.
    Moves detected client-only mods to mods-disabled-client/ directory.
    Use dry_run=true to preview without making changes.
    Optionally provide specific filenames to only filter those.
    """
    from client_mod_filter import filter_client_mods, analyze_mod, disable_mod

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    cf_api_key = None
    try:
        from integrations_store import get_integration_key
        cf_api_key = get_integration_key("curseforge")
    except Exception:
        pass

    # If specific filenames provided, handle individually
    if req.filenames:
        mods_dir = server_dir / "mods"
        results = []
        moved = 0
        for fn in req.filenames:
            jar_path = mods_dir / fn
            if not jar_path.exists():
                results.append({"filename": fn, "action": "not_found"})
                continue
            if not req.dry_run:
                if disable_mod(server_dir, fn):
                    results.append({"filename": fn, "action": "disabled"})
                    moved += 1
                else:
                    results.append({"filename": fn, "action": "error"})
            else:
                results.append({"filename": fn, "action": "would_disable"})
                moved += 1

        return {
            "total_mods": len(req.filenames),
            "client_only_moved": moved,
            "dry_run": req.dry_run,
            "mods": results,
        }

    # Full analysis and filter
    summary = filter_client_mods(
        server_dir,
        use_api=req.use_api,
        cf_api_key=cf_api_key,
        min_confidence=req.min_confidence,
        dry_run=req.dry_run,
    )

    return summary


@router.post("/restore/{server_name}")
async def restore_disabled_mod(
    server_name: str,
    req: RestoreRequest,
    current_user: User = Depends(require_moderator),
):
    """Restore a disabled client mod back to the active mods directory."""
    from client_mod_filter import restore_mod

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    success = restore_mod(server_dir, req.filename)
    if not success:
        raise HTTPException(status_code=404, detail="Disabled mod not found")

    return {"message": f"Restored {req.filename}", "filename": req.filename}


@router.post("/disable/{server_name}")
async def manually_disable_mod(
    server_name: str,
    req: DisableRequest,
    current_user: User = Depends(require_moderator),
):
    """Manually disable a specific mod (move to mods-disabled-client/)."""
    from client_mod_filter import disable_mod

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    success = disable_mod(server_dir, req.filename)
    if not success:
        raise HTTPException(status_code=404, detail="Mod not found in mods directory")

    return {"message": f"Disabled {req.filename}", "filename": req.filename}


@router.get("/disabled/{server_name}")
async def get_disabled_mods(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """List all disabled client mods for a server."""
    from client_mod_filter import list_disabled_mods

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    return {"mods": list_disabled_mods(server_dir)}


@router.post("/whitelist/{server_name}")
async def add_whitelist_pattern(
    server_name: str,
    req: WhitelistRequest,
    current_user: User = Depends(require_moderator),
):
    """Add a pattern to the server's whitelist (mods matching this won't be filtered)."""
    from client_mod_filter import add_to_whitelist

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    success = add_to_whitelist(server_dir, req.pattern)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update whitelist")

    return {"message": f"Added '{req.pattern}' to whitelist"}


@router.delete("/whitelist/{server_name}")
async def remove_whitelist_pattern(
    server_name: str,
    pattern: str = Query(..., description="Pattern to remove from whitelist"),
    current_user: User = Depends(require_moderator),
):
    """Remove a pattern from the server's whitelist."""
    from client_mod_filter import remove_from_whitelist

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    success = remove_from_whitelist(server_dir, pattern)
    if not success:
        raise HTTPException(status_code=404, detail="Pattern not found in whitelist")

    return {"message": f"Removed '{pattern}' from whitelist"}


@router.get("/whitelist/{server_name}")
async def get_whitelist(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """Get the current whitelist patterns for a server."""
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    allow_file = server_dir / "client-only-allow.txt"
    patterns = []
    if allow_file.exists():
        for line in allow_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)

    return {"patterns": patterns}


@router.post("/restore-all/{server_name}")
async def restore_all_disabled_mods(
    server_name: str,
    current_user: User = Depends(require_moderator),
):
    """Restore ALL disabled client mods back to the active mods directory."""
    from client_mod_filter import restore_mod, list_disabled_mods

    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    disabled = list_disabled_mods(server_dir)
    restored = 0
    failed = 0
    for mod in disabled:
        if restore_mod(server_dir, mod["filename"]):
            restored += 1
        else:
            failed += 1

    return {
        "message": f"Restored {restored} mods",
        "restored": restored,
        "failed": failed,
    }
