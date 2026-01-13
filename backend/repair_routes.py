from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import json, time, hashlib
from auth import require_moderator
from models import User
from config import SERVERS_ROOT
from docker_manager import fix_server_jar

router = APIRouter(prefix="/servers", tags=["server_maintenance"])

def _detect_type_version(server_dir: Path) -> tuple[str | None, str | None]:
    """Best-effort detection of server type and version from existing files."""
    stype = None
    sver = None
    try:
        
        meta_path = server_dir / "server_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
                stype = meta.get("detected_type") or meta.get("server_type") or stype
                sver = meta.get("detected_version") or meta.get("server_version") or meta.get("version") or sver
            except Exception:
                pass
        
        jar_files = [p for p in server_dir.glob("*.jar") if p.is_file()]
        
        jar_files.sort(key=lambda p: (p.name != "server.jar", -p.stat().st_size))
        import re
        patterns = [
            ("paper", re.compile(r"paper-(?P<ver>\d+(?:\.\d+)+)-(?P<build>\d+)\.jar", re.IGNORECASE)),
            ("purpur", re.compile(r"purpur-(?P<ver>\d+(?:\.\d+)+)-(?P<build>\d+)\.jar", re.IGNORECASE)),
            ("fabric", re.compile(r"fabric-server-launch\.jar", re.IGNORECASE)),
            ("forge", re.compile(r"forge-(?P<ver>\d+(?:\.\d+)+).*\.jar", re.IGNORECASE)),
            ("neoforge", re.compile(r"neoforge-(?P<ver>\d+(?:\.\d+)+).*\.jar", re.IGNORECASE)),
        ]
        for jf in jar_files:
            lower = jf.name.lower()
            for t, rgx in patterns:
                m = rgx.search(lower)
                if m:
                    stype = stype or t
                    v = m.groupdict().get("ver")
                    if v:
                        sver = sver or v
                    break
            if stype:
                break
        
        if not stype and (server_dir / "server.jar").exists() and (server_dir / "server.jar").stat().st_size > 50_000:
            stype = "vanilla"
    except Exception:
        pass
    return stype, sver

def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

@router.post("/{server_name}/repair-jar")
def repair_server_jar(server_name: str, current_user: User = Depends(require_moderator)):
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")

    jar_path = server_dir / "server.jar"
    before_size = jar_path.stat().st_size if jar_path.exists() else 0
    stype, sver = _detect_type_version(server_dir)
    if not stype or not sver:
        raise HTTPException(status_code=400, detail="Cannot repair: missing detected server type/version")

    try:
        fix_server_jar(server_dir, stype, sver)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Repair attempt failed: {e}")

    if not jar_path.exists() or jar_path.stat().st_size < 100*1024:
        raise HTTPException(status_code=500, detail="Repaired jar still invalid (size below threshold)")

    
    meta_path = server_dir / "server_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            meta = {}
    meta.update({
        "detected_type": stype,
        "detected_version": sver,
        "jar_size_bytes": jar_path.stat().st_size,
        "jar_sha256": _sha256(jar_path),
        "last_repair_ts": int(time.time()),
    })
    try:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {
        "message": "server.jar repaired",
        "server": server_name,
        "type": stype,
        "version": sver,
        "previous_size": before_size,
        "new_size": jar_path.stat().st_size,
        "sha256": meta.get("jar_sha256"),
    }




class AutoFixRequest(BaseModel):
    dry_run: bool = False

class CrashAnalysisResponse(BaseModel):
    server_name: str
    analyzed_at: str
    crash_reports_found: int
    client_only_issues: List[str]
    mods_to_disable: List[str]
    auto_fixed: bool
    details: List[str]
    error: Optional[str] = None

class AutoFixResponse(BaseModel):
    server_name: str
    fixed_at: str
    dry_run: bool
    mods_disabled: List[str]
    actions_taken: List[str]
    error: Optional[str] = None


@router.get("/{server_name}/analyze-crashes")
def analyze_server_crashes(server_name: str, current_user: User = Depends(require_moderator)):
    """
    Analyze crash reports for a server to identify problematic mods.
    
    This endpoint scans crash-reports/ and logs/ for crash indicators,
    identifies client-only mods and mod conflicts, and provides recommendations.
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")
    
    try:
        from crash_analyzer import analyze_server_crashes as do_analyze
        result = do_analyze(server_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


@router.post("/{server_name}/auto-fix-mods")
def auto_fix_server_mods(
    server_name: str,
    req: AutoFixRequest = AutoFixRequest(),
    current_user: User = Depends(require_moderator)
):
    """
    Automatically fix detected mod issues for a server.
    
    This endpoint analyzes crash logs, identifies problematic mods (client-only,
    incompatible, etc.), and moves them to a disabled folder.
    
    Set dry_run=true to preview what would be done without making changes.
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")
    
    try:
        from crash_analyzer import auto_fix_server_crashes
        result = auto_fix_server_crashes(server_name, dry_run=req.dry_run)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auto-fix failed: {e}")


@router.post("/{server_name}/purge-client-mods")
def purge_client_only_mods(
    server_name: str,
    current_user: User = Depends(require_moderator)
):
    """
    Immediately scan and disable all detectable client-only mods.
    
    This uses both metadata inspection (fabric.mod.json, mods.toml) and
    known patterns to identify and disable client-only mods.
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")
    
    mods_dir = server_dir / "mods"
    if not mods_dir.exists():
        return {"message": "No mods directory found", "mods_disabled": []}
    
    try:
        
        from modpack_routes import _purge_client_only_mods
        
        disabled = []
        def capture_event(ev):
            if ev.get("type") == "progress" and "Disabled" in ev.get("message", ""):
                mod_name = ev.get("message", "").split(":")[-1].strip()
                disabled.append(mod_name)
        
        _purge_client_only_mods(server_dir, push_event=capture_event)
        
        
        disabled_dir = server_dir / "mods-disabled-client"
        moved_count = len(list(disabled_dir.glob("*.jar"))) if disabled_dir.exists() else 0
        
        return {
            "message": f"Purged client-only mods",
            "server": server_name,
            "mods_disabled_count": moved_count,
            "disabled_mods_folder": str(disabled_dir),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Purge failed: {e}")


@router.get("/{server_name}/disabled-mods")
def list_disabled_mods(server_name: str, current_user: User = Depends(require_moderator)):
    """
    List all disabled mods (client-only, crash-related, incompatible).
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")
    
    result = {
        "server": server_name,
        "disabled_client": [],
        "disabled_crash": [],
        "disabled_incompatible": [],
    }
    
    for category, folder in [
        ("disabled_client", "mods-disabled-client"),
        ("disabled_crash", "mods-disabled-crash"),
        ("disabled_incompatible", "mods-disabled-incompatible"),
    ]:
        disabled_dir = server_dir / folder
        if disabled_dir.exists():
            result[category] = [f.name for f in disabled_dir.glob("*.jar")]
    
    return result


@router.post("/{server_name}/restore-mod")
def restore_disabled_mod(
    server_name: str,
    mod_name: str,
    current_user: User = Depends(require_moderator)
):
    """
    Restore a previously disabled mod back to the mods folder.
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server directory not found")
    
    mods_dir = server_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    
    
    for folder in ["mods-disabled-client", "mods-disabled-crash", "mods-disabled-incompatible"]:
        disabled_dir = server_dir / folder
        mod_path = disabled_dir / mod_name
        if mod_path.exists():
            import shutil
            dest = mods_dir / mod_name
            shutil.move(str(mod_path), str(dest))
            return {
                "message": f"Restored {mod_name} to mods folder",
                "server": server_name,
                "restored_from": folder,
            }
    
    raise HTTPException(status_code=404, detail=f"Mod {mod_name} not found in disabled folders")
