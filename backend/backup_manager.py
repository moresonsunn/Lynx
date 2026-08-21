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
# (rotated logs, crash dumps, loader caches). Extend via BACKUP_EXCLUDE_DIRS.
_DEFAULT_BACKUP_EXCLUDES = {"logs", "crash-reports", "cache", ".cache", "tmp"}


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
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _is_excluded(rel, excludes):
                continue
            zf.write(path, rel.as_posix())


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
    """Internal synchronous backup implementation."""
    from settings_routes import get_backup_settings

    server_dir = _server_path(name)
    backup_settings = get_backup_settings()

    ts = time.strftime("%Y%m%d-%H%M%S")
    dest_dir = _get_backups_root() / name
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Also create in server's own backups/ folder
    server_backup_dir = server_dir / "backups"
    server_backup_dir.mkdir(parents=True, exist_ok=True)

    compress = backup_settings.get("compress", True)
    fmt = compression if compression in {"zip", "gztar", "bztar", "tar"} else ('zip' if compress else 'tar')
    excludes = _backup_excludes()

    if fmt == 'zip':
        archive_path = dest_dir / f"{name}-{ts}.zip"
        _archive_zip(server_dir, archive_path, excludes)
    else:
        ext = {'gztar': '.tar.gz', 'bztar': '.tar.bz2', 'tar': '.tar'}[fmt]
        mode = {'gztar': 'w:gz', 'bztar': 'w:bz2', 'tar': 'w'}[fmt]
        archive_path = dest_dir / f"{name}-{ts}{ext}"
        _archive_tar(server_dir, archive_path, excludes, mode)

    # Also copy to server's own backups/ folder
    server_archive_path = server_backup_dir / archive_path.name
    shutil.copy2(archive_path, server_archive_path)

    return {"file": archive_path.name, "size": archive_path.stat().st_size}


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
