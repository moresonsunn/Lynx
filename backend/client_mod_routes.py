"""
Client-Side Mod Management API Routes
======================================
Endpoints for analyzing, filtering, and managing client-only mods on servers.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any
from pathlib import Path
from datetime import datetime, timezone

from auth import require_auth, require_moderator
from models import User
from config import SERVERS_ROOT, safe_child_path

router = APIRouter(prefix="/client-mods", tags=["client_mods"])


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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

class AllowlistEntry(BaseModel):
    pattern: str = Field(..., description="Mod filename pattern or mod ID")
    mod_name: Optional[str] = Field(None, description="Human readable mod display name")
    added_at: Optional[str] = Field(default_factory=_utcnow_iso, description="ISO-8601 UTC timestamp")
    added_by: Optional[str] = Field(None, description="Username who added this entry")
    status: str = Field("active", description="Status ('active' or 'disabled')")
    notes: Optional[str] = Field(None, description="Optional notes or comment")

    @field_validator("added_at", mode="before")
    @classmethod
    def ensure_added_at(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            return _utcnow_iso()
        return v.strip()

    @field_validator("status", mode="before")
    @classmethod
    def ensure_status(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            return "active"
        return v.strip().lower()

class WhitelistRequest(BaseModel):
    pattern: str = Field(..., description="Mod pattern to allowlist")
    mod_name: Optional[str] = Field(None, description="Optional mod display name")
    notes: Optional[str] = Field(None, description="Optional notes or comment")
    status: Optional[str] = Field("active", description="Status (default: 'active')")

AllowlistAddRequest = WhitelistRequest

class WhitelistDeleteRequest(BaseModel):
    pattern: Optional[str] = Field(None, description="Pattern to remove from allowlist")

AllowlistDeleteRequest = WhitelistDeleteRequest

class WhitelistResponse(BaseModel):
    patterns: List[str] = Field(..., description="List of pattern strings")
    entries: List[AllowlistEntry] = Field(..., description="Structured allowlist entries")

AllowlistResponse = WhitelistResponse


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

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
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
    server_count = sum(1 for r in results if not r.is_client_only and r.side.value.upper() != "UNKNOWN")
    unknown_count = sum(1 for r in results if r.side.value.upper() == "UNKNOWN" and not r.is_client_only)

    return {
        "total_mods": len(results),
        "client_only_count": client_count,
        "server_or_both_count": server_count,
        "unknown_count": unknown_count,
        "mods": mods_data,
    }


@router.get("/report/{server_name}")
async def compat_report(
    server_name: str,
    loader: Optional[str] = Query(None, description="Target mod loader (auto-detected if omitted)"),
    mc_version: Optional[str] = Query(None, description="Target Minecraft version"),
    use_api: bool = Query(True, description="Use Modrinth/CurseForge/GitHub APIs"),
    current_user: User = Depends(require_auth),
):
    """Graded, explainable compatibility report from the multi-stage engine.

    Unlike ``/analyze`` (binary client-only detection), this returns per-mod
    verdicts (compatible / needs_review / incompatible ...), a 0-100 score,
    confidence, the evidence trail, detected conflicts and missing dependencies.
    Read-only.
    """
    from client_mod_filter import graded_compat_report

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    cf_api_key = None
    try:
        from integrations_store import get_integration_key
        cf_api_key = get_integration_key("curseforge")
    except Exception:
        pass

    return graded_compat_report(
        server_dir,
        loader=loader,
        mc_version=mc_version,
        use_api=use_api,
        cf_api_key=cf_api_key,
    )


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

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
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
            jar_path = safe_child_path(mods_dir, fn)
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

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
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

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
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

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    return {"mods": list_disabled_mods(server_dir)}


@router.post("/whitelist/{server_name}")
async def add_whitelist_pattern(
    server_name: str,
    req: WhitelistRequest,
    current_user: User = Depends(require_moderator),
):
    """
    Add or update a pattern in the server's allowlist.
    Preserves metadata (mod_name, notes, status, added_by, added_at) in client-only-allow.json
    and synchronizes client-only-allow.txt.
    """
    from client_mod_filter import add_to_allowlist

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    pattern = req.pattern.strip() if req.pattern else ""
    if not pattern:
        raise HTTPException(status_code=400, detail="Pattern cannot be empty")
    if "\n" in pattern or "\r" in pattern:
        raise HTTPException(status_code=400, detail="Pattern cannot contain newline characters")

    username = getattr(current_user, "username", None)
    mod_name = req.mod_name.strip() if req.mod_name and req.mod_name.strip() else None
    notes = req.notes.strip() if req.notes and req.notes.strip() else None
    status = (req.status or "active").strip()

    try:
        entry = add_to_allowlist(
            server_dir=server_dir,
            pattern=pattern,
            mod_name=mod_name,
            added_by=username,
            notes=notes,
            status=status,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update whitelist: {exc}")

    return {
        "message": f"Added '{pattern}' to whitelist",
        "entry": entry,
        "pattern": pattern,
    }


@router.delete("/whitelist/{server_name}")
async def remove_whitelist_pattern(
    server_name: str,
    pattern: Optional[str] = Query(None, description="Pattern to remove from whitelist"),
    body: Optional[WhitelistDeleteRequest] = Body(None),
    current_user: User = Depends(require_moderator),
):
    """
    Remove a pattern from the server's allowlist.
    Accepts pattern via query param (?pattern=...) or JSON request body ({"pattern": "..."}).
    Removes the entry from both client-only-allow.json and client-only-allow.txt.
    """
    from client_mod_filter import remove_from_allowlist

    target_pattern = pattern
    if not target_pattern and body and body.pattern:
        target_pattern = body.pattern

    if not target_pattern or not target_pattern.strip():
        raise HTTPException(
            status_code=400,
            detail="Pattern must be provided in query parameter or request body",
        )
    target_pattern = target_pattern.strip()
    if "\n" in target_pattern or "\r" in target_pattern:
        raise HTTPException(status_code=400, detail="Pattern cannot contain newline characters")

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    success = remove_from_allowlist(server_dir, target_pattern)
    if not success:
        raise HTTPException(status_code=404, detail="Pattern not found in whitelist")

    return {
        "message": f"Removed '{target_pattern}' from whitelist",
        "pattern": target_pattern,
    }


@router.get("/whitelist/{server_name}", response_model=WhitelistResponse)
async def get_whitelist(
    server_name: str,
    current_user: User = Depends(require_auth),
):
    """
    Get the current allowlist patterns and structured entries for a server.
    Synchronizes client-only-allow.json and client-only-allow.txt automatically.
    """
    from client_mod_filter import get_allowlist_entries

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")

    entries = get_allowlist_entries(server_dir)
    patterns = [
        e["pattern"]
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("pattern"), str) and e["pattern"].strip()
    ]

    return {
        "patterns": patterns,
        "entries": entries,
    }


@router.post("/restore-all/{server_name}")
async def restore_all_disabled_mods(
    server_name: str,
    current_user: User = Depends(require_moderator),
):
    """Restore ALL disabled client mods back to the active mods directory."""
    from client_mod_filter import restore_mod, list_disabled_mods

    server_dir = safe_child_path(SERVERS_ROOT, server_name)
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
