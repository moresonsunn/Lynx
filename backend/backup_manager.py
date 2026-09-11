from pathlib import Path
import os
import shutil
import tarfile
import time
import zipfile
import asyncio
from typing import List
from fastapi import HTTPException
from config import SERVERS_ROOT


DEFAULT_BACKUPS_ROOT = SERVERS_ROOT.parent / "backups"
DEFAULT_BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)

# Volatile directories excluded from backups to prevent archive bloat over time
# (rotated logs, crash dumps, loader caches, previous backups). Extend via BACKUP_EXCLUDE_DIRS.
# NOTE: "backups" MUST stay excluded — the old code copied each archive into
# server_dir/backups/ and the next run re-archived all previous zips (exponential growth + freeze).
_DEFAULT_BACKUP_EXCLUDES = {"logs", "crash-reports", "cache", ".cache", "tmp", "backups"}

# Guard against overlapping runs (scheduler + manual click at same time)
_BACKUP_IN_PROGRESS: set = set()
import threading as _threading
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


def _archive_zip(root: Path, archive_path: Path, excludes: set) -> None:
    # compresslevel=1: ~3x faster than default 6, slightly larger file.
    # Backups used to freeze the whole app for minutes on big worlds.
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # skip lock / temp / socket files that break zips or bloat them
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
                # file vanished mid-backup (world saving) — skip, don't abort
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
    server_dir = (SERVERS_ROOT / name).resolve()
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    return server_dir


def list_backups(name: str) -> List[dict]:
    server_dir = _server_path(name)
    dest_dir = _get_backups_root() / name
    dest_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(dest_dir.glob("*.zip")):
        items.append({
            "file": p.name,
            "size": p.stat().st_size,
            "modified": int(p.stat().st_mtime),
        })
    
    for p in sorted(dest_dir.glob("*.tar.gz")):
        items.append({
            "file": p.name,
            "size": p.stat().st_size,
            "modified": int(p.stat().st_mtime),
        })
    
    # Also check server's own backups/ folder
    server_backup_dir = server_dir / "backups"
    if server_backup_dir.exists():
        for p in sorted(server_backup_dir.glob("*.zip")):
            # Check if already in list (avoid duplicates)
            if not any(item["file"] == p.name for item in items):
                items.append({
                    "file": p.name,
                    "size": p.stat().st_size,
                    "modified": int(p.stat().st_mtime),
                })
        for p in sorted(server_backup_dir.glob("*.tar.gz")):
            if not any(item["file"] == p.name for item in items):
                items.append({
                    "file": p.name,
                    "size": p.stat().st_size,
                    "modified": int(p.stat().st_mtime),
                })
    
    return sorted(items, key=lambda x: x["modified"], reverse=True)


def create_backup(name: str, compression: str = 'zip') -> dict:
    """Create a backup of the server synchronously (blocking)."""
    return _create_backup_sync(name, compression)


async def create_backup_async(name: str, compression: str = 'zip') -> dict:
    """Create a backup of the server asynchronously in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _create_backup_sync, name, compression)


def _create_backup_sync(name: str, compression: str = 'zip') -> dict:
    """Internal synchronous backup implementation.

    Runs in a worker thread (see create_backup_async / scheduler to_thread).
    Never call directly from an async event-loop handler — it blocks for
    seconds/minutes on big worlds and freezes the whole panel.
    """
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
        dest_dir = _get_backups_root() / name
        dest_dir.mkdir(parents=True, exist_ok=True)

        compress = backup_settings.get("compress", True)
        fmt = compression if compression in {"zip", "gztar", "bztar", "tar"} else ('zip' if compress else 'tar')
        excludes = _backup_excludes()

        started = time.time()
        if fmt == 'zip':
            archive_path = dest_dir / f"{name}-{ts}.zip"
            _archive_zip(server_dir, archive_path, excludes)
        else:
            ext = {'gztar': '.tar.gz', 'bztar': '.tar.bz2', 'tar': '.tar'}[fmt]
            mode = {'gztar': 'w:gz', 'bztar': 'w:bz2', 'tar': 'w'}[fmt]
            archive_path = dest_dir / f"{name}-{ts}{ext}"
            _archive_tar(server_dir, archive_path, excludes, mode)

        # NOTE: intentionally NO second copy into server_dir/backups/ anymore.
        # The old duplicate doubled disk IO/time AND got re-archived on the
        # next run (backups-inside-backups → exponential growth → freeze).
        # list_backups() still reads legacy copies if present.
        size = archive_path.stat().st_size
        _log.info(f"Backup {archive_path.name} done in {time.time()-started:.1f}s ({size//1024//1024} MB)")
        return {"file": archive_path.name, "size": size}
    finally:
        with _BACKUP_LOCK:
            _BACKUP_IN_PROGRESS.discard(name)


def restore_backup(name: str, backup_file: str) -> None:
    server_dir = _server_path(name)
    dest_dir = _get_backups_root() / name
    archive = (dest_dir / backup_file).resolve()
    if not str(archive).startswith(str(dest_dir)) or not archive.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    
    shutil.unpack_archive(str(archive), str(server_dir))


def delete_backup(name: str, backup_file: str) -> None:
    server_dir = _server_path(name)
    dest_dir = _get_backups_root() / name
    archive = (dest_dir / backup_file).resolve()
    if not str(archive).startswith(str(dest_dir)) or not archive.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    archive.unlink()
