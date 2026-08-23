"""
Server file-management routes.

Extracted from app.py to keep route concerns modular:
directory listing/ETags, file read/write/delete, download (file or zipped dir),
uploads (single + batch), mkdir, rename (path and server), zip/unzip.

All mutating endpoints require per-server "manage" permission; reads require "view".
Admins/owners bypass via require_server_permission.
"""
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import (
    APIRouter, Depends, HTTPException, Query, Form,
    UploadFile, File, Request,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from typing import Optional

from config import SERVERS_ROOT, get_server_dir
from models import User
from server_permissions import require_server_permission
from file_manager import (
    list_dir as fm_list_dir,
    read_file as fm_read_file,
    write_file as fm_write_file,
    delete_path as fm_delete_path,
    upload_files as fm_upload_files,
    rename_path as fm_rename_path,
    zip_path as fm_zip_path,
    unzip_path as fm_unzip_path,
)

router = APIRouter(tags=["server-files"])


# ── Request models ─────────────────────────────────────────────────────────

class MkdirRequest(BaseModel):
    path: str


class FileRenameRequest(BaseModel):
    src: str
    dest: str


class ServerRenameRequest(BaseModel):
    new_name: str


class ZipRequest(BaseModel):
    path: str
    dest: Optional[str] = None


class UnzipRequest(BaseModel):
    path: str
    dest: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_within_server(name: str, rel: str) -> Path:
    """Resolve *rel* under the server dir, rejecting path traversal."""
    server_dir = get_server_dir(name).resolve()
    target = (server_dir / rel).resolve()
    if not str(target).startswith(str(server_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return server_dir, target


def _etag_response(request: Request, etag: Optional[str]):
    """Return a 304 Response if If-None-Match matches, else None."""
    if not etag:
        return None
    inm = request.headers.get("if-none-match") if request else None
    if inm == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return None


# ── Directory listing / file IO ────────────────────────────────────────────

@router.post("/servers/{name}/mkdir")
def mkdir_path(name: str, req: MkdirRequest, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    try:
        base = SERVERS_ROOT.resolve() / name
        target = (base / req.path).resolve()
        if not str(target).startswith(str(base)):
            raise HTTPException(status_code=400, detail="Invalid path")
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/servers/{name}/files")
def files_list(name: str, request: Request, path: str = ".", current_user: User = Depends(require_server_permission("view", param_name="name"))):
    # Compute a simple ETag based on directory mtime to enable client caching
    etag = None
    try:
        server_dir, base = _resolve_within_server(name, path)
        if base.exists() and base.is_dir():
            try:
                with os.scandir(base) as it:
                    count = sum(1 for _ in it)
            except OSError:
                count = 0
            st = base.stat()
            etag = f'W/"dir-{count}-{int(st.st_mtime)}"'
        elif base.exists():
            st = base.stat()
            etag = f'W/"dirfile-{st.st_size}-{int(st.st_mtime)}"'
        else:
            etag = 'W/"dir-0"'
    except HTTPException:
        raise
    except OSError as e:
        # Server dir vanished mid-request; fall through to empty listing below.
        pass

    not_modified = _etag_response(request, etag)
    if not_modified is not None:
        return not_modified

    items = fm_list_dir(name, path)
    headers = {"ETag": etag} if etag else {}
    return JSONResponse(content={"items": items}, headers=headers)


@router.get("/servers/{name}/file")
def file_read(name: str, request: Request, path: str, current_user: User = Depends(require_server_permission("view", param_name="name"))):
    # ETag based on file size and mtime
    etag = None
    try:
        server_dir, p = _resolve_within_server(name, path)
        if p.exists() and p.is_file():
            st = p.stat()
            etag = f'W/"file-{st.st_size}-{int(st.st_mtime)}"'
        else:
            etag = 'W/"file-0-0"'
    except HTTPException:
        raise
    except OSError:
        pass

    not_modified = _etag_response(request, etag)
    if not_modified is not None:
        return not_modified

    content = fm_read_file(name, path)
    headers = {"ETag": etag} if etag else {}
    return JSONResponse(content={"content": content}, headers=headers)


@router.post("/servers/{name}/file")
def file_write(name: str, path: str, content: str = Form(""), current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    fm_write_file(name, path, content)
    return {"ok": True}


@router.delete("/servers/{name}/file")
def file_delete(name: str, path: str, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    fm_delete_path(name, path)
    return {"ok": True}


# ── Download ───────────────────────────────────────────────────────────────

@router.get("/servers/{name}/download")
def file_or_folder_download(
    name: str,
    path: str = Query("."),
    current_user: User = Depends(require_server_permission("view", param_name="name")),
):
    """Download a single file directly, or a directory as an on-the-fly zip."""
    server_dir, target = _resolve_within_server(name, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    if target.is_file():
        return FileResponse(str(target), filename=target.name)

    tmpdir = Path(tempfile.mkdtemp(prefix="dl_zip_"))
    archive_base = tmpdir / (Path(path).name or "folder")
    archive_path = shutil.make_archive(str(archive_base), 'zip', root_dir=str(target))
    fname = f"{(Path(path).name or 'folder')}.zip"
    return FileResponse(archive_path, filename=fname)


# ── Upload ─────────────────────────────────────────────────────────────────

@router.post("/servers/{name}/upload")
async def file_upload(
    name: str,
    path: str = Query("."),
    file: UploadFile = File(...),
    current_user: User = Depends(require_server_permission("manage", param_name="name")),
):
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    from file_manager import get_upload_dest
    dest = get_upload_dest(name, path, file.filename or "uploaded")
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    finally:
        try:
            await file.close()
        except Exception:
            pass

    # Post-process potential server icon uploads
    try:
        from file_manager import maybe_process_server_icon
        maybe_process_server_icon(name, dest, file.filename or dest.name)
    except Exception:
        pass

    # Invalidate caches for this server after upload
    try:
        from file_manager import _invalidate_cache
        _invalidate_cache(name)
    except Exception:
        pass
    return {"ok": True}


@router.post("/servers/{name}/upload-multiple")
async def files_upload(
    name: str,
    path: str = Form("."),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_server_permission("manage", param_name="name")),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    count = fm_upload_files(name, path, files)
    return {"ok": True, "count": count}


# ── Rename / archive ops ───────────────────────────────────────────────────

@router.post("/servers/{name}/rename")
def file_rename(name: str, req: FileRenameRequest, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    fm_rename_path(name, req.src, req.dest)
    return {"ok": True}


@router.post("/servers/{name}/rename-server")
def rename_server(name: str, req: ServerRenameRequest, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    """Rename an existing server (directory + container)."""
    from runtime_adapter import get_runtime_manager_or_docker
    dm = get_runtime_manager_or_docker()
    try:
        result = dm.rename_server(old_name=name, new_name=req.new_name)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/servers/{name}/zip")
def make_zip(name: str, req: ZipRequest, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    archive_rel = fm_zip_path(name, req.path, req.dest)
    return {"ok": True, "archive": archive_rel}


@router.post("/servers/{name}/unzip")
def do_unzip(name: str, req: UnzipRequest, current_user: User = Depends(require_server_permission("manage", param_name="name"))):
    dest_rel = fm_unzip_path(name, req.path, req.dest)
    return {"ok": True, "dest": dest_rel}
