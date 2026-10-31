from fastapi import APIRouter, Depends, HTTPException, UploadFile, Query, File
from fastapi.responses import FileResponse
from pathlib import Path
import shutil
import tempfile
import time
from typing import List, Dict, Any

from auth import require_auth, require_moderator
from server_permissions import require_server_permission
from models import User
from config import get_server_dir, safe_child_path

router = APIRouter(prefix="/worlds", tags=["worlds"])


def _read_active_level_name(server_dir: Path) -> str:
    props = server_dir / "server.properties"
    if props.is_file():
        try:
            for raw in props.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if line.startswith("level-name="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
        except Exception:
            pass
    return "world"


def _is_world_folder(p: Path) -> bool:
    if not p.is_dir():
        return False
    markers = ("level.dat", "level.dat_old", "session.lock", "region", "DIM-1", "DIM1", "playerdata")
    return any((p / m).exists() for m in markers)


def _detect_world_dirs(server_dir: Path) -> List[Path]:
    worlds: List[Path] = []
    if not server_dir.exists():
        return worlds

    active_level = _read_active_level_name(server_dir)
    try:
        active_dir = safe_child_path(server_dir, active_level)
        if active_dir.is_dir():
            worlds.append(active_dir)
    except Exception:
        pass

    for name in ["world", "world_nether", "world_the_end"]:
        p = server_dir / name
        if p.is_dir() and p not in worlds:
            worlds.append(p)

    try:
        for p in sorted(server_dir.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and p not in worlds and _is_world_folder(p):
                worlds.append(p)
    except Exception:
        pass

    # Also check a dedicated worlds/ container directory if present (e.g. Multiverse / modpacks)
    worlds_container = server_dir / "worlds"
    if worlds_container.is_dir():
        try:
            for p in sorted(worlds_container.iterdir(), key=lambda x: x.name.lower()):
                if p.is_dir() and p not in worlds and _is_world_folder(p):
                    worlds.append(p)
        except Exception:
            pass

    return worlds


def collect_worlds_info(server_dir: Path) -> List[Dict[str, Any]]:
    active_level = _read_active_level_name(server_dir)
    worlds = _detect_world_dirs(server_dir)
    items: List[Dict[str, Any]] = []

    for w in worlds:
        size = 0
        modified = 0
        try:
            modified = int(w.stat().st_mtime)
        except Exception:
            pass
        try:
            count = 0
            for f in w.rglob('*'):
                if f.is_file():
                    try:
                        st = f.stat()
                        size += st.st_size
                        if int(st.st_mtime) > modified:
                            modified = int(st.st_mtime)
                    except Exception:
                        pass
                    count += 1
                    if count > 8000:
                        break
                if size > 10 * 1024 * 1024 * 1024:
                    break
        except Exception:
            pass

        dims = ["Overworld"]
        if (w / "DIM-1").is_dir() or w.name.endswith("_nether"):
            if "Nether" not in dims:
                dims.append("Nether")
        if (w / "DIM1").is_dir() or w.name.endswith("_the_end"):
            if "The End" not in dims:
                dims.append("The End")

        rel_path = w.relative_to(server_dir).as_posix()
        items.append({
            "name": w.name,
            "path": rel_path,
            "size": size,
            "modified": modified,
            "is_active": rel_path == active_level or w.name == active_level,
            "has_level_dat": (w / "level.dat").exists(),
            "dimensions": dims,
        })
    return items


@router.get("/{server_name}")
def list_worlds(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    server_dir = get_server_dir(server_name)
    return {"worlds": collect_worlds_info(server_dir), "active_level": _read_active_level_name(server_dir)}


@router.get("/{server_name}/download")
async def download_world(
    server_name: str,
    world: str = Query("world"),
    current_user: User = Depends(require_server_permission("view"))
):
    server_dir = get_server_dir(server_name)
    world_dir = safe_child_path(server_dir, world)
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="World not found")

    ts = time.strftime("%Y%m%d-%H%M%S")
    safe_world_slug = world.replace("/", "_").replace("\\", "_")
    tmpdir = Path(tempfile.mkdtemp(prefix="worlddl_"))
    archive_base = safe_child_path(tmpdir, f"{server_name}-{safe_world_slug}-{ts}")
    archive_path = shutil.make_archive(str(archive_base), 'zip', root_dir=str(world_dir))
    return FileResponse(archive_path, filename=f"{server_name}-{safe_world_slug}-{ts}.zip")


@router.post("/{server_name}/upload")
async def upload_world(
    server_name: str,
    file: UploadFile = File(...),
    world_name: str = Query("world"),
    current_user: User = Depends(require_server_permission("manage")),
):
    if file is None or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="No file provided")
    fname = Path(file.filename or "upload.zip").name
    low = fname.lower()
    if not (low.endswith('.zip') or low.endswith('.tar') or low.endswith('.tar.gz')):
        raise HTTPException(status_code=400, detail="Only .zip/.tar(.gz) archives are allowed")

    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", world_name):
        raise HTTPException(status_code=400, detail="Invalid world name")

    server_dir = get_server_dir(server_name)
    target_dir = safe_child_path(server_dir, world_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="worldup_"))
    tmpfile = safe_child_path(tmpdir, fname)
    with tmpfile.open('wb') as f:
        f.write(file.file.read())

    shutil.unpack_archive(str(tmpfile), str(target_dir), format=None)
    return {"ok": True, "world": world_name}


@router.post("/{server_name}/backup")
async def backup_world(
    server_name: str,
    world: str = Query("world"),
    compression: str = Query("zip"),
    current_user: User = Depends(require_moderator),
):
    server_dir = get_server_dir(server_name)
    world_dir = safe_child_path(server_dir, world)
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="World not found")

    ts = time.strftime("%Y%m%d-%H%M%S")
    from config import SERVERS_ROOT
    backups_root = safe_child_path(SERVERS_ROOT.parent / "backups", server_name)
    backups_root.mkdir(parents=True, exist_ok=True)
    safe_world_slug = world.replace("/", "_").replace("\\", "_")
    archive_base = safe_child_path(backups_root, f"{server_name}-world-{safe_world_slug}-{ts}")

    fmt = compression if compression in {"zip", "gztar", "bztar", "tar"} else "zip"
    archive_path = shutil.make_archive(str(archive_base), fmt, root_dir=str(world_dir))
    p = Path(archive_path)
    return {"file": p.name, "size": p.stat().st_size}
