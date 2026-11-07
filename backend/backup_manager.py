from pathlib import Path
import os
import shutil
import tarfile
import time
import zipfile
import asyncio
import threading as _threading
from typing import List, Optional
from fastapi import HTTPException
from config import SERVERS_ROOT, safe_child_path


DEFAULT_BACKUPS_ROOT = SERVERS_ROOT.parent / "backups"
DEFAULT_BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)

# Common backup directories created by Minecraft backup mods (SimpleBackups, FTB Backups, AromaBackup, Textile, etc.)
MOD_BACKUP_DIRS = (
    "backups",
    "simplebackups",
    "ftbbackups",
    "ftbbackups2",
    "backup",
    "world_backups",
)

BACKUP_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tar.xz",
    ".tar",
    ".zst",
    ".7z",
)

# Volatile directories excluded from backups to prevent archive bloat over time
_DEFAULT_BACKUP_EXCLUDES = {
    "logs",
    "crash-reports",
    "cache",
    ".cache",
    "tmp",
    *MOD_BACKUP_DIRS,
}

_BACKUP_IN_PROGRESS: set = set()
_BACKUP_LOCK = _threading.Lock()


def _backup_excludes() -> set:
    ex = set(_DEFAULT_BACKUP_EXCLUDES)
    for tok in os.getenv("BACKUP_EXCLUDE_DIRS", "").split(","):
        tok = tok.strip()
        if tok:
            ex.add(tok)
    return ex


def _is_excluded(rel: Path, excludes: set) -> bool:
    return bool(rel.parts) and rel.parts[0] in excludes


def _is_backup_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    low = path.name.lower()
    return any(low.endswith(ext) for ext in BACKUP_ARCHIVE_SUFFIXES)


def _archive_zip(root: Path, archive_path: Path, excludes: set) -> None:
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in ("session.lock",):
                continue
            if path.suffix in (".tmp", ".temp", ".lock"):
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if _is_excluded(rel, excludes):
                continue
            try:
                zf.write(path, rel.as_posix())
            except (OSError, ValueError):
                continue


def _archive_tar(root: Path, archive_path: Path, excludes: set, mode: str) -> None:
    def _filter(tarinfo):
        parts = [p for p in Path(tarinfo.name).parts if p not in (".", "")]
        if parts and parts[0] in excludes:
            return None
        return tarinfo
    with tarfile.open(archive_path, mode) as tf:
        tf.add(str(root), arcname=".", filter=_filter)


def _get_backups_root() -> Path:
    """Get backup root from settings or default."""
    try:
        from settings_routes import get_backup_settings
        backup_settings = get_backup_settings()
        backup_path = Path(backup_settings.get("location", str(DEFAULT_BACKUPS_ROOT)))
        backup_path.mkdir(parents=True, exist_ok=True)
        return backup_path
    except Exception:
        return DEFAULT_BACKUPS_ROOT


def _server_path(name: str) -> Path:
    server_dir = safe_child_path(SERVERS_ROOT, name)
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    return server_dir


def list_backups(name: str) -> List[dict]:
    """List both Panel backups and automatic Modpack backups inside the server directory."""
    server_dir = _server_path(name)
    dest_dir = safe_child_path(_get_backups_root(), name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    items: List[dict] = []
    seen_files = set()

    # 1. Scan Panel Backups directory (/data/backups/<server_name>)
    try:
        for p in sorted(dest_dir.iterdir()):
            if _is_backup_archive(p):
                st = p.stat()
                items.append({
                    "file": p.name,
                    "name": p.name,
                    "size": st.st_size,
                    "modified": int(st.st_mtime),
                    "source": "panel",
                    "source_label": "Panel Backup",
                    "folder_path": None,
                })
                seen_files.add(p.name)
    except Exception:
        pass

    # 2. Scan Modpack / In-Server Backup directories (backups/, simplebackups/, ftbbackups/, etc.)
    for mod_dir_name in MOD_BACKUP_DIRS:
        mod_backup_dir = server_dir / mod_dir_name
        if not mod_backup_dir.is_dir():
            continue
        try:
            for p in mod_backup_dir.rglob("*"):
                if not _is_backup_archive(p):
                    continue
                rel_to_server = p.relative_to(server_dir).as_posix()
                if p.name in seen_files or rel_to_server in seen_files:
                    continue
                st = p.stat()
                items.append({
                    "file": rel_to_server,
                    "name": p.name,
                    "size": st.st_size,
                    "modified": int(st.st_mtime),
                    "source": "mod",
                    "source_label": f"Mod Backup ({mod_dir_name})",
                    "folder": p.parent.relative_to(server_dir).as_posix(),
                    "folder_path": p.parent.relative_to(server_dir).as_posix(),
                })
                seen_files.add(rel_to_server)
        except Exception:
            continue

    return sorted(items, key=lambda x: x["modified"], reverse=True)


def get_detected_mod_backup_folders(name: str) -> List[dict]:
    """Return any backup folders found inside the server directory."""
    server_dir = _server_path(name)
    found = []
    for mod_dir_name in MOD_BACKUP_DIRS:
        d = server_dir / mod_dir_name
        if d.is_dir():
            count = sum(1 for p in d.rglob("*") if _is_backup_archive(p))
            found.append({
                "name": mod_dir_name,
                "folder": mod_dir_name,
                "path": mod_dir_name,
                "count": count,
                "archive_count": count,
            })
    return found


def resolve_backup_archive(name: str, backup_file: str) -> Path:
    """Safely resolve a backup archive from either the panel backup root or the server's mod backup folders."""
    server_dir = _server_path(name)
    dest_dir = safe_child_path(_get_backups_root(), name)

    # Try panel backup directory first
    try:
        candidate = safe_child_path(dest_dir, backup_file)
        if candidate.is_file():
            return candidate
    except Exception:
        pass

    # Try server directory (if backup_file is e.g. "simplebackups/world.zip" or "backups/2026.zip")
    try:
        candidate_in_server = safe_child_path(server_dir, backup_file)
        if candidate_in_server.is_file() and _is_backup_archive(candidate_in_server):
            rel_parts = candidate_in_server.relative_to(server_dir).parts
            if rel_parts and rel_parts[0] in MOD_BACKUP_DIRS:
                return candidate_in_server
    except Exception:
        pass

    # Also check by bare filename inside each MOD_BACKUP_DIRS
    bare_name = Path(backup_file).name
    for mod_dir_name in MOD_BACKUP_DIRS:
        mod_dir = server_dir / mod_dir_name
        if mod_dir.is_dir():
            try:
                candidate = safe_child_path(mod_dir, bare_name)
                if candidate.is_file() and _is_backup_archive(candidate):
                    return candidate
            except Exception:
                continue

    raise HTTPException(status_code=404, detail="Backup not found")


resolve_backup_path = resolve_backup_archive


def create_backup(name: str, compression: str = 'zip', tag: Optional[str] = None) -> dict:
    """Create a backup of the server synchronously (blocking)."""
    return _create_backup_sync(name, compression, tag=tag)


async def create_backup_async(name: str, compression: str = 'zip', tag: Optional[str] = None) -> dict:
    """Create a backup of the server asynchronously in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _create_backup_sync, name, compression, tag)


def _create_backup_sync(name: str, compression: str = 'zip', tag: Optional[str] = None) -> dict:
    from settings_routes import get_backup_settings
    import logging as _logging
    _log = _logging.getLogger(__name__)

    with _BACKUP_LOCK:
        if name in _BACKUP_IN_PROGRESS:
            raise ValueError(f"Backup already running for {name} — please wait")
        _BACKUP_IN_PROGRESS.add(name)
    try:
        server_dir = _server_path(name)
        backup_settings = get_backup_settings()

        ts = time.strftime("%Y%m%d-%H%M%S")
        dest_dir = safe_child_path(_get_backups_root(), name)
        dest_dir.mkdir(parents=True, exist_ok=True)

        compress = backup_settings.get("compress", True)
        fmt = compression if compression in {"zip", "gztar", "bztar", "tar"} else ('zip' if compress else 'tar')
        excludes = _backup_excludes()

        prefix = f"{name}-{tag}" if tag else name
        started = time.time()
        if fmt == 'zip':
            archive_path = dest_dir / f"{prefix}-{ts}.zip"
            _archive_zip(server_dir, archive_path, excludes)
        else:
            ext = {'gztar': '.tar.gz', 'bztar': '.tar.bz2', 'tar': '.tar'}[fmt]
            mode = {'gztar': 'w:gz', 'bztar': 'w:bz2', 'tar': 'w'}[fmt]
            archive_path = dest_dir / f"{prefix}-{ts}{ext}"
            _archive_tar(server_dir, archive_path, excludes, mode)

        size = archive_path.stat().st_size
        _log.info(f"Backup {archive_path.name} done in {time.time()-started:.1f}s ({size//1024//1024} MB)")
        return {"file": archive_path.name, "name": archive_path.name, "size": size}
    finally:
        with _BACKUP_LOCK:
            _BACKUP_IN_PROGRESS.discard(name)


def restore_backup(name: str, backup_file: str) -> None:
    server_dir = _server_path(name)
    archive = resolve_backup_archive(name, backup_file)
    shutil.unpack_archive(str(archive), str(server_dir))


def delete_backup(name: str, backup_file: str) -> None:
    archive = resolve_backup_archive(name, backup_file)
    archive.unlink()
