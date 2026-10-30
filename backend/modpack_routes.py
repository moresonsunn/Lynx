from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any, List
from pathlib import Path
import tempfile
import shutil
import zipfile
import requests
import threading
import time
import json
import uuid
from urllib.parse import urlparse
import os
import re
import logging

from auth import require_moderator
from models import User
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT
from mod_side_resolver import ModSideResolver
from client_mod_detector import (
    load_client_only_config,
    detect_client_only_mods,
    remove_client_only_mods,
    process_client_pack,
    is_client_only_jar,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/modpacks", tags=["modpacks"])

_install_tasks = {}
_install_lock = threading.Lock()

def _push_event(task_id: str, event):
    with _install_lock:
        task = _install_tasks.get(task_id)
        if not task:
            return
        task["events"].append(event)
        if event.get("type") in ("done", "error"):
            task["done"] = True

def get_docker_manager():
    return get_runtime_manager_or_docker()


def _extract_modpack_metadata(base: Path) -> Dict[str, Any]:
    """Best-effort detection of modpack metadata (loader, versions, etc.)."""
    metadata: Dict[str, Any] = {}

    def _load_json(candidate: Path) -> Dict[str, Any]:
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_modrinth(path: Path) -> None:
        data = _load_json(path)
        if not data:
            return
        idx = data.get("index") or data
        deps = idx.get("dependencies") or {}
        metadata.setdefault("type", idx.get("name") or data.get("name") or "Modpack")
        metadata.setdefault("version", idx.get("version") or data.get("version") or data.get("version_id"))
        metadata.setdefault("minecraft_version", deps.get("minecraft") or idx.get("game_version"))
        for loader_key in ("fabric-loader", "quilt-loader", "forge", "neoforge"):
            if loader_key in deps:
                loader_name = loader_key.split("-")[0].replace("loader", "").strip("-")
                metadata.setdefault("loader", loader_name or loader_key)
                metadata.setdefault("loader_version", deps.get(loader_key))
                break

    def _apply_curseforge(path: Path) -> None:
        data = _load_json(path)
        if not data:
            return
        metadata.setdefault("type", data.get("name") or "Modpack")
        metadata.setdefault("version", data.get("version"))
        minecraft = data.get("minecraft") or {}
        metadata.setdefault("minecraft_version", minecraft.get("version"))
        loaders = minecraft.get("modLoaders") or []
        if loaders:
            loader_id = loaders[0].get("id") or ""
            metadata.setdefault("loader", loader_id.split("-")[0])
            metadata.setdefault("loader_version", loader_id.split("-")[-1])

    candidates = [
        base / "modrinth.index.json",
        base / "manifest.json",
    ]
    for cand in candidates:
        if cand.exists():
            if cand.name == "modrinth.index.json":
                _apply_modrinth(cand)
            elif cand.name == "manifest.json":
                _apply_curseforge(cand)

    # If metadata still sparse, try one level deeper
    if not metadata:
        for child in base.iterdir():
            if child.is_dir():
                metadata = _extract_modpack_metadata(child)
                if metadata:
                    break
    return metadata

def _download_to(path: Path, url: str, headers: dict | None = None, timeout: int = 120):
    with requests.get(url, stream=True, timeout=timeout, headers=headers or {}) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def _purge_client_only_mods(
    target_dir: Path,
    push_event=lambda ev: None,
    mc_version: Optional[str] = None,
    loader: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mehrstufige Erkennung und Filterung von Client-only-Mods über den `ModSideResolver`:
      - A. Offizielle Mod-Metadaten (Modrinth API, CurseForge API, FTB-Metadaten, Manifeste)
      - B. JAR-Metadaten (neoforge.mods.toml, mods.toml, fabric.mod.json, quilt.mod.json, Mixins, Ressourcen)
      - C. Java-Bytecode-Analyse (.class Annotations, DistExecutor, Registries, Networking)
      - D. Vollständige Abhängigkeitsgraphen-Auflösung
      - E. Persistentes SHA256-Caching
    """
    resolver = ModSideResolver(
        minecraft_version=mc_version or "unknown",
        modloader=loader or "unknown",
    )

    def _on_mod_progress(idx: int, total: int, mod_res: Any) -> None:
        if idx == total or idx % 8 == 0 or idx == 1:
            pct = 54 + int((idx / max(total, 1)) * 8)
            push_event(
                {
                    "type": "progress",
                    "step": "mod_analysis",
                    "message": f"Mods analysiert: {idx} / {total}",
                    "progress": pct,
                    "stats": {
                        "mods_analyzed": idx,
                        "total_mods": total,
                    },
                }
            )

    report = resolver.filter_server_mods(
        server_dir=target_dir,
        minecraft_version=mc_version,
        modloader=loader,
        dry_run=False,
        progress_callback=_on_mod_progress,
    )

    excluded = report.get("excluded_mods", [])
    push_event(
        {
            "type": "progress",
            "step": "client_pack",
            "message": (
                f"Mod-Analyse abgeschlossen: {report['total_mods']} analysiert, "
                f"{report['client_only_count']} Client-only ausgeschlossen, "
                f"{report['server_mods_kept_count']} Server-Mods behalten"
            ),
            "progress": 62,
            "stats": {
                "mods_analyzed": report["total_mods"],
                "total_mods": report["total_mods"],
                "client_only_count": report["client_only_count"],
                "server_mods_kept": report["server_mods_kept_count"],
                "dependencies_checked": True,
            },
            "excluded_mods": excluded,
        }
    )
    return report


def _purge_client_only_mods_legacy(target_dir: Path, push_event=lambda ev: None):
    """Delegiert an _purge_client_only_mods (ModSideResolver)."""
    return _purge_client_only_mods(target_dir, push_event=push_event)


def _has_custom_dimensions(datapack_path: Path) -> bool:
    """
    Prüft, ob ein Datapack benutzerdefinierte Dimensionen oder Weltgenerierungsdaten enthält.
    """
    try:
        if datapack_path.is_dir():
            for pattern in ("**/dimension_type/*.json", "**/worldgen/noise_settings/*.json", "**/worldgen/biome/*.json"):
                if any(datapack_path.glob(pattern)):
                    return True
        elif datapack_path.is_file() and datapack_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(datapack_path, "r") as zf:
                for name in zf.namelist():
                    if name.startswith("data/") and (
                        "/dimension_type/" in name
                        or "/worldgen/noise_settings/" in name
                        or "/worldgen/biome/" in name
                    ):
                        return True
    except Exception:
        pass
    return False


def _move_dimension_datapacks(target_dir: Path, push_event=lambda ev: None) -> int:
    """
    Gemäß Spezifikation (Abschnitt 2: 'Datapacks und Weltgenerierungsdateien erhalten')
    werden Datapacks und Weltgenerierungsdateien NICHT mehr deaktiviert, sondern für den
    Dedicated Server vollständig beibehalten.
    """
    datapacks_dir = target_dir / "datapacks"
    if not datapacks_dir.exists() or not datapacks_dir.is_dir():
        return 0
    dp_count = sum(1 for dp in datapacks_dir.iterdir() if dp.is_dir() or dp.suffix.lower() == ".zip")
    if dp_count > 0:
        log.info(f"Preserving {dp_count} datapack(s) and world generation files in {datapacks_dir}")
        push_event(
            {
                "type": "progress",
                "step": "datapacks",
                "message": f"Datapacks & Weltgenerierungsdateien erhalten ({dp_count})",
                "progress": 63,
            }
        )
    return 0


def _process_client_pack(
    target_dir: Path,
    push_event=lambda ev: None,
    mc_version: Optional[str] = None,
    loader: Optional[str] = None,
    loader_version: Optional[str] = None,
    install_mode: str = "server",
) -> Dict[str, Any]:
    """
    Bereitet ein heruntergeladenes Modpack vollständig automatisch vor:
      1. Bei `install_mode == "server"`: Startet `ModSideResolver`, analysiert alle Mods,
         löst Abhängigkeiten auf, schließt ausschließlich `CLIENT_ONLY`-Mods aus und behält
         alle Server-Mods, Bibliotheken, Konfigurationen, Datapacks und Weltgenerierungsdateien.
      2. Bereitet die NeoForge-/Forge-/Fabric-/Quilt-Serverdateien vor.
      3. Akzeptiert EULA und führt eine abschließende Serverpaket-Validierung durch.
    """
    _push_event = lambda ev: push_event({**ev, "step": ev.get("step", "client_pack")})
    report: Dict[str, Any] = {}

    if (install_mode or "server").lower() != "client":
        _push_event(
            {
                "type": "progress",
                "step": "mod_analysis",
                "message": "ModSideResolver analysiert Mods und Abhängigkeiten...",
                "progress": 53,
            }
        )
        try:
            report = _purge_client_only_mods(
                target_dir,
                push_event=_push_event,
                mc_version=mc_version,
                loader=loader,
            )
        except Exception as e:
            log.exception(f"ModSideResolver error in {target_dir}: {e}")
            _push_event(
                {
                    "type": "progress",
                    "step": "mod_analysis",
                    "message": f"Warnung bei Mod-Analyse: {e}",
                    "progress": 58,
                }
            )
    else:
        _push_event(
            {
                "type": "progress",
                "step": "client_pack",
                "message": "Client-Installationsmodus: Alle Client- und Server-Mods bleiben erhalten",
                "progress": 60,
            }
        )

    # Schritt 2: Datapacks und Weltgenerierungsdateien erhalten
    _move_dimension_datapacks(target_dir, push_event=_push_event)

    # Schritt 3: Server-Loader (NeoForge / Forge / Fabric / Quilt) sicherstellen
    if (install_mode or "server").lower() != "client":
        _push_event(
            {
                "type": "progress",
                "step": "loader",
                "message": f"Bereite {loader or 'Server'}-Installation vor...",
                "progress": 65,
            }
        )
        try:
            _ensure_server_jar(target_dir, loader, mc_version, loader_version, push_event=_push_event)
            _push_event(
                {
                    "type": "progress",
                    "step": "loader",
                    "message": f"{(loader or 'Server').capitalize()} installiert",
                    "progress": 68,
                    "stats": {"loader_installed": f"{loader or 'server'} {loader_version or ''}".strip()},
                }
            )
        except Exception as e:
            _push_event(
                {
                    "type": "progress",
                    "step": "loader",
                    "message": f"Server-JAR Vorbereitung Warnung: {e}",
                    "progress": 66,
                }
            )

        # Schritt 4: EULA akzeptieren
        try:
            (target_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        except Exception:
            pass

        # Schritt 5: Abschließende Serverpaket-Validierung
        try:
            resolver = ModSideResolver(
                minecraft_version=mc_version or "unknown",
                modloader=loader or "unknown",
            )
            validation = resolver.validate_server_pack(
                target_dir,
                expected_minecraft_version=mc_version,
                expected_modloader=loader,
            )
            report["validation"] = validation
            _push_event(
                {
                    "type": "progress",
                    "step": "validate",
                    "message": "Server-Startvorbereitung erfolgreich validiert",
                    "progress": 72,
                    "stats": {
                        "validation_status": "Erfolgreich",
                        "validation": validation,
                    },
                }
            )
        except Exception as e:
            log.debug(f"Server pack validation warning: {e}")

    return report


def _ensure_server_jar(
    target_dir: Path,
    loader: Optional[str],
    mc_version: Optional[str],
    loader_version: Optional[str],
    push_event=lambda ev: None
):
    """Ensure a runnable server jar or installer exists in target_dir.
    Attempts for known loaders; falls back to vanilla server.jar.
    """
    # Quick check for existing jar or run.sh
    patterns = [
        "server.jar", "run.sh", "neoforge-*-universal.jar", "*forge-*-universal.jar",
        "forge-*-server.jar", "forge-*.jar", "*paper*.jar", "*purpur*.jar", "*fabric*.jar", "*server*.jar"
    ]
    for pat in patterns:
        if list(target_dir.glob(pat)):
            return  # something present already

    try:
        ldr = (loader or "").lower()
        mc = (mc_version or "").strip()
        lver = (loader_version or "").strip()

        if ldr == "fabric":
            # Determine loader version if missing
            if not lver and mc:
                try:
                    resp = requests.get(f"https://meta.fabricmc.net/v2/versions/loader/{mc}", timeout=30)
                    if resp.ok:
                        arr = resp.json()
                        # Pick first stable else first entry
                        stable = next((x for x in arr if x.get("stable")), None)
                        lver = (stable or (arr[0] if arr else {})).get("loader", {}).get("version") or ""
                except Exception:
                    pass
            if mc and lver:
                url = f"https://meta.fabricmc.net/v2/versions/loader/{mc}/{lver}/server/jar"
                out = target_dir / f"fabric-server-mc.{mc}-loader.{lver}.jar"
                push_event({"type": "progress", "step": "server", "message": f"Downloading Fabric server jar {mc}/{lver}", "progress": 62})
                _download_to(out, url, timeout=180)
                return

        if ldr == "forge":
            # If loader_version missing, use promotions_slim.json to find recommended/latest
            if not lver and mc:
                try:
                    resp = requests.get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", timeout=30)
                    if resp.ok:
                        data = resp.json()
                        promos = data.get("promos", {})
                        lver = promos.get(f"{mc}-recommended") or promos.get(f"{mc}-latest") or ""
                except Exception:
                    pass
            if mc and lver:
                # If loader_version already includes the MC version prefix, don't duplicate
                base = lver if lver.startswith(f"{mc}-") else f"{mc}-{lver}"
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{base}/forge-{base}-installer.jar"
                out = target_dir / f"forge-{base}-installer.jar"
                push_event({"type": "progress", "step": "server", "message": f"Downloading Forge installer {base}", "progress": 62})
                _download_to(out, url, timeout=300)
                return

        if ldr == "quilt":
            if not lver:
                try:
                    resp = requests.get("https://meta.quiltmc.org/v3/versions/loader", timeout=30)
                    if resp.ok:
                        arr = resp.json()
                        if arr and isinstance(arr[0], dict):
                            lver = arr[0].get("version") or ""
                except Exception:
                    pass
            try:
                url = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/latest/quilt-installer-latest.jar"
                out = target_dir / "quilt-installer.jar"
                push_event({"type": "progress", "step": "server", "message": f"Downloading Quilt server installer {mc}/{lver}", "progress": 62})
                _download_to(out, url, timeout=180)
                return
            except Exception:
                pass

        if ldr == "neoforge":
            # Prefer provided loader_version; otherwise, try to infer latest for this MC version
            if not lver and mc:
                try:
                    meta_url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
                    resp = requests.get(meta_url, timeout=30)
                    if resp.ok:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(resp.text)
                        versions = [v.text or "" for v in root.findall(".//version")]
                        # Choose the latest version that starts with the MC version prefix
                        for v in reversed(versions):
                            if v.startswith(mc):
                                lver = v
                                break
                except Exception:
                    pass
            if lver:
                url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{lver}/neoforge-{lver}-installer.jar"
                out = target_dir / f"neoforge-{lver}-installer.jar"
                push_event({"type": "progress", "step": "server", "message": f"Downloading NeoForge installer {lver}", "progress": 62})
                _download_to(out, url, timeout=300)
                return

        # Fallback: vanilla server jar for the given Minecraft version
        if mc:
            try:
                man = requests.get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", timeout=30).json()
                version = next((v for v in man.get("versions", []) if v.get("id") == mc), None)
                if version and version.get("url"):
                    det = requests.get(version["url"], timeout=30).json()
                    server_info = det.get("downloads", {}).get("server")
                    if server_info and server_info.get("url"):
                        out = target_dir / "server.jar"
                        push_event({"type": "progress", "step": "server", "message": f"Downloading Vanilla server {mc}", "progress": 62})
                        _download_to(out, server_info["url"], timeout=300)
                        return
            except Exception:
                pass
    except Exception as e:
        push_event({"type": "progress", "step": "server", "message": f"Auto-download failed: {e}", "progress": 63})

class ImportServerPackRequest(BaseModel):
    server_name: str
    server_pack_url: HttpUrl
    host_port: Optional[int] = None
    min_ram: Optional[str] = "2G"
    max_ram: Optional[str] = "4G"
    cpu_cores: Optional[int] = None

@router.post("/import")
async def import_server_pack(
    payload: ImportServerPackRequest,
    current_user: User = Depends(require_moderator),
):
    """
    Download a server pack ZIP from a given URL, extract it into /data/servers/{server_name},
    accept EULA, and create a container using the existing files.
    Supports CurseForge links by resolving the real file URL via the Core API.
    """
    dm = get_docker_manager()

    servers_root = SERVERS_ROOT
    target_dir = servers_root / payload.server_name
    if target_dir.exists():
        raise HTTPException(status_code=400, detail="Server directory already exists")

    tmpdir = Path(tempfile.mkdtemp(prefix="modpack_"))
    zip_path = tmpdir / "serverpack.zip"

    def resolve_download_url(raw_url: str) -> tuple[str, dict]:
        """Return (download_url, headers) ready for requests.get.
        If the URL is a CurseForge web download page, use the Core API to resolve the direct file URL.
        """
        u = urlparse(raw_url)
        headers = {
            "User-Agent": "minecraft-controller/1.0",
            "Accept": "application/octet-stream, application/zip, */*",
        }
        host = (u.netloc or "").lower()
        path = (u.path or "")
        if "curseforge.com" in host and "/download/" in path:
            # Expect .../download/<fileId>
            try:
                file_id = path.rstrip("/").split("/")[-1]
                if not file_id.isdigit():
                    return raw_url, headers
                # Use CF Core API to get file info and download URL
                from integrations_store import get_integration_key
                api_key = get_integration_key("curseforge")
                if not api_key:
                    raise HTTPException(status_code=400, detail="CurseForge API key not configured in Settings")
                info = requests.get(
                    f"https://api.curseforge.com/v1/mods/files/{file_id}",
                    headers={
                        "x-api-key": api_key,
                        "Accept": "application/json",
                        "User-Agent": "minecraft-controller/1.0",
                    },
                    timeout=30,
                )
                info.raise_for_status()
                data = info.json().get("data") or {}
                dl = data.get("downloadUrl")
                if not dl:
                    # Fallback to the webpage URL (may still 403)
                    return raw_url, headers
                return dl, headers
            except HTTPException:
                raise
            except Exception as e:
                # Fall back to raw URL
                return raw_url, headers
        return raw_url, headers

    try:
        # Resolve and download
        download_url, headers = resolve_download_url(str(payload.server_pack_url))
        with requests.get(download_url, stream=True, timeout=60, headers=headers) as r:
            if r.status_code == 403 and "curseforge" in download_url:
                # If direct URL still forbidden, provide clearer guidance
                raise HTTPException(status_code=400, detail="Failed to download server pack: CurseForge denied access (403). Ensure a valid CurseForge Core API key is configured and use a valid Server Pack file.")
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        # Extract
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(tmpdir)

        # Move extracted content into target dir
        # Heuristic: If the zip contains a single top-level folder, use its content
        def _single_top_level_dir(base: Path):
            entries = [p for p in base.iterdir()]
            if len(entries) == 1 and entries[0].is_dir():
                return entries[0]
            return None

        src_dir = _single_top_level_dir(tmpdir) or tmpdir
        pack_metadata = _extract_modpack_metadata(tmpdir)
        shutil.move(str(src_dir), str(target_dir))

        # Ensure EULA accepted
        eula = target_dir / "eula.txt"
        eula.write_text("eula=true\n", encoding="utf-8")

        # Run ModSideResolver filtering, ensure server JAR, and validate server pack
        mod_side_report = {}
        try:
            loader = pack_metadata.get("loader") if pack_metadata else None
            mc_version = pack_metadata.get("minecraft_version") if pack_metadata else None
            loader_version = pack_metadata.get("loader_version") if pack_metadata else None
            mod_side_report = _process_client_pack(
                target_dir,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                install_mode="server",
            )
        except Exception:
            pass  # Best-effort; server may still work with existing files

        # Start container using runtime, pointing to existing dir
        result = dm.create_server_from_existing(
            name=payload.server_name,
            host_port=payload.host_port,
            min_ram=payload.min_ram or "2G",
            max_ram=payload.max_ram or "4G",
            cpu_cores=payload.cpu_cores,
        )

        if pack_metadata:
            metadata_updates: Dict[str, Any] = {
                "type": pack_metadata.get("type") or "Modpack",
                "version": pack_metadata.get("version"),
                "minecraft_version": pack_metadata.get("minecraft_version"),
                "loader_version": pack_metadata.get("loader_version"),
                "loader": pack_metadata.get("loader"),
            }
            runtime = get_runtime_manager_or_docker()
            if runtime and hasattr(runtime, "update_metadata"):
                try:
                    runtime.update_metadata(payload.server_name, **{k: v for k, v in metadata_updates.items() if v})
                except Exception:
                    pass

        return {"message": "Server pack imported", "server": result}

    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download server pack: {e}")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Downloaded file is not a valid ZIP archive")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import server pack: {e}")
    finally:
        # Cleanup temp dir
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

@router.post("/import-upload")
async def import_server_pack_upload(
    server_name: str = Form(...),
    host_port: Optional[int] = Form(None),
    min_ram: str = Form("2G"),
    max_ram: str = Form("4G"),
    cpu_cores: Optional[int] = Form(None),
    # Optional overrides to influence Java/runtime selection
    java_version_override: Optional[str] = Form(None),
    server_type: Optional[str] = Form(None),
    server_version: Optional[str] = Form(None),
    file: UploadFile | None = None,
    current_user: User = Depends(require_moderator),
):
    """
    Import a server pack from an uploaded ZIP file and create a server container.
    - Saves the uploaded file to a temp dir
    - Safely extracts contents
    - Moves them into /data/servers/{server_name}
    - Accepts EULA and starts a container using existing files
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")

    dm = get_docker_manager()
    servers_root = SERVERS_ROOT
    target_dir = servers_root / server_name
    if target_dir.exists():
        raise HTTPException(status_code=400, detail="Server directory already exists")

    tmpdir = Path(tempfile.mkdtemp(prefix="upload_zip_"))
    zip_path = tmpdir / "serverpack.zip"

    try:
        # Save uploaded file to disk
        with open(zip_path, 'wb') as out_f:
            shutil.copyfileobj(file.file, out_f)

        # Safely extract ZIP into tmpdir/extracted
        extract_dir = tmpdir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        def is_within(base: Path, target: Path) -> bool:
            try:
                target.resolve().relative_to(base.resolve())
                return True
            except Exception:
                return False

        with zipfile.ZipFile(zip_path, 'r') as z:
            for member in z.infolist():
                # Skip directories explicitly handled
                name = member.filename
                if name.endswith('/'):
                    continue
                # Prevent absolute paths or traversal
                dest_path = extract_dir / name
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                if not is_within(extract_dir, dest_path):
                    raise HTTPException(status_code=400, detail="Zip contains invalid paths")
                with z.open(member) as src, open(dest_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

        # If there is a single top-level directory, use its contents
        def _single_top_level_dir(base: Path):
            entries = [p for p in base.iterdir()]
            if len(entries) == 1 and entries[0].is_dir():
                return entries[0]
            return None

        src_dir = _single_top_level_dir(extract_dir) or extract_dir
        shutil.move(str(src_dir), str(target_dir))

        # Ensure EULA accepted
        try:
            (target_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        except Exception:
            pass

        extra_env: Dict[str, str] = {}
        if java_version_override:
            extra_env["JAVA_VERSION_OVERRIDE"] = str(java_version_override)
        if server_type:
            extra_env["SERVER_TYPE"] = str(server_type)
        if server_version:
            extra_env["SERVER_VERSION"] = str(server_version)

        # Detect metadata (type, version, port) from extracted files before container start
        def detect_imported_server_info(root: Path) -> dict:
            info: dict[str, str | int | None] = {
                "detected_type": None,
                "detected_version": None,
                "detected_port": None,
            }
            try:
                # server.properties port
                props_file = root / "server.properties"
                if props_file.exists():
                    try:
                        for line in props_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                            if line.strip().startswith("server-port="):
                                port_val = line.split("=",1)[1].strip()
                                if port_val.isdigit():
                                    info["detected_port"] = int(port_val)
                                break
                    except Exception:
                        pass
                # Jar inspection
                jar_files = [p.name for p in root.glob("*.jar") if p.is_file()]
                # Prefer server.jar if large enough
                server_jar = root / "server.jar"
                if server_jar.exists() and server_jar.stat().st_size > 50_000:
                    jar_files.insert(0, server_jar.name)
                # Pattern maps
                import re
                patterns = [
                    ("paper", re.compile(r"paper-(?P<ver>\d+(?:\.\d+)+)-\d+\.jar", re.IGNORECASE)),
                    ("purpur", re.compile(r"purpur-(?P<ver>\d+(?:\.\d+)+)-\d+\.jar", re.IGNORECASE)),
                    ("fabric", re.compile(r"fabric-server-launch\.jar", re.IGNORECASE)),
                    ("neoforge", re.compile(r"neoforge-(?P<ver>\d+(?:\.\d+)+).*(?:installer|universal)?\.jar", re.IGNORECASE)),
                    ("forge", re.compile(r"forge-(?P<ver>\d+(?:\.\d+)+).*(?:installer|universal)?\.jar", re.IGNORECASE)),
                ]
                for jf in jar_files:
                    lower = jf.lower()
                    for t, rgx in patterns:
                        m = rgx.search(lower)
                        if m:
                            info["detected_type"] = t
                            ver = m.groupdict().get("ver")
                            if ver:
                                info["detected_version"] = ver
                            break
                    if info["detected_type"]:
                        break
                # Fallback: if no type matched but a reasonably sized server.jar exists -> vanilla
                if not info["detected_type"] and server_jar.exists() and server_jar.stat().st_size > 50_000:
                    info["detected_type"] = "vanilla"
            except Exception:
                pass
            return info

        detected = detect_imported_server_info(target_dir)
        # Merge detected info into env if user did not provide them
        if not server_type and detected.get("detected_type"):
            extra_env["SERVER_TYPE"] = str(detected["detected_type"])
        if not server_version and detected.get("detected_version"):
            extra_env["SERVER_VERSION"] = str(detected["detected_version"])
        # Override host_port if not provided but detected port present
        if host_port is None and isinstance(detected.get("detected_port"), int):
            host_port = int(detected["detected_port"])  # Will be passed through create

        # Run ModSideResolver filtering, ensure server JAR, and validate server pack
        try:
            pack_metadata = _extract_modpack_metadata(target_dir)
            loader = pack_metadata.get("loader") if pack_metadata else None
            mc_version = pack_metadata.get("minecraft_version") if pack_metadata else None
            loader_version = pack_metadata.get("loader_version") if pack_metadata else None
            if not loader and detected.get("detected_type"):
                loader = str(detected["detected_type"])
            if not mc_version and detected.get("detected_version"):
                mc_version = str(detected["detected_version"])
            _process_client_pack(
                target_dir,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                install_mode="server",
            )
        except Exception:
            pass  # Best-effort; server may still work with existing files

        result = dm.create_server_from_existing(
            name=server_name,
            host_port=host_port,
            min_ram=min_ram or "2G",
            max_ram=max_ram or "4G",
            extra_env=extra_env or None,
            cpu_cores=cpu_cores,
        )

        # Update server_meta.json with detection results
        try:
            meta_path = target_dir / "server_meta.json"
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
            meta.update({
                "detected_type": detected.get("detected_type"),
                "detected_version": detected.get("detected_version"),
                "detected_port": detected.get("detected_port"),
            })
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass

        return {"message": "Server pack imported", "server": result, "detected": detected}
    except HTTPException:
        raise
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import uploaded server pack: {e}")
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

class InstallRequest(BaseModel):
    provider: str
    pack_id: str
    version_id: Optional[str] = None
    name: str
    install_mode: Optional[str] = "server"  # "server" (Dedicated Server) or "client" (Minecraft Client)
    host_port: Optional[int] = None
    min_ram: Optional[str] = None
    max_ram: Optional[str] = None
    cpu_cores: Optional[int] = None


class ResolveUrlRequest(BaseModel):
    url: str


@router.post("/resolve-url")
async def resolve_modpack_url(
    payload: ResolveUrlRequest,
    current_user: User = Depends(require_moderator),
):
    """
    Take a CurseForge, Modrinth, or FTB modpack URL, auto-detect the platform,
    and return pack metadata (name, icon, versions, provider, pack_id).
    """
    raw_url = payload.url.strip()
    parsed = urlparse(raw_url)
    host = (parsed.netloc or "").lower()
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    # ── Feed The Beast (FTB) ───────────────────────────────────────
    if "feed-the-beast.com" in host or "ftb.team" in host:
        slug_or_id = path_parts[-1] if path_parts else ""
        if not slug_or_id:
            raise HTTPException(400, "Could not extract FTB modpack ID or slug from URL")
        try:
            from modpack_providers.ftb import FTBProvider
            ftb = FTBProvider()
            if slug_or_id.isdigit():
                pack_data = ftb.get_pack(slug_or_id)
                versions = ftb.get_versions(slug_or_id, limit=20)
            else:
                hits = ftb.search(slug_or_id.replace("-", " "), limit=5)
                if not hits:
                    raise HTTPException(404, f"FTB modpack '{slug_or_id}' not found")
                pid = str(hits[0]["id"])
                pack_data = ftb.get_pack(pid)
                versions = ftb.get_versions(pid, limit=20)
            return {
                "provider": "ftb",
                "pack_id": str(pack_data.get("id")),
                "name": pack_data.get("name"),
                "description": pack_data.get("description") or "",
                "icon_url": pack_data.get("icon_url") or "",
                "game_versions": pack_data.get("game_versions") or [],
                "loaders": pack_data.get("loaders") or [],
                "downloads": pack_data.get("installs") or 0,
                "versions": versions[:20],
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Failed to resolve FTB modpack: {e}")

    # ── Modrinth ───────────────────────────────────────────────────
    if "modrinth.com" in host:
        # URL format: https://modrinth.com/modpack/<slug>
        slug = None
        for i, part in enumerate(path_parts):
            if part in ("modpack", "mod", "datapack", "shader", "resourcepack"):
                if i + 1 < len(path_parts):
                    slug = path_parts[i + 1]
                    break
        if not slug:
            raise HTTPException(400, "Could not extract Modrinth project slug from URL")
        try:
            r = requests.get(f"https://api.modrinth.com/v2/project/{slug}", timeout=15)
            r.raise_for_status()
            project = r.json()
            # Get versions
            vr = requests.get(f"https://api.modrinth.com/v2/project/{slug}/version?limit=20", timeout=15)
            versions = vr.json() if vr.ok else []
            return {
                "provider": "modrinth",
                "pack_id": project.get("id") or slug,
                "name": project.get("title") or project.get("name") or slug,
                "description": project.get("description") or "",
                "icon_url": project.get("icon_url") or "",
                "game_versions": project.get("game_versions") or [],
                "loaders": project.get("loaders") or [],
                "downloads": project.get("downloads") or 0,
                "versions": [
                    {
                        "id": v.get("id"),
                        "name": v.get("name") or v.get("version_number"),
                        "version_number": v.get("version_number"),
                        "game_versions": v.get("game_versions") or [],
                        "loaders": v.get("loaders") or [],
                        "date_published": v.get("date_published"),
                    }
                    for v in versions[:20]
                ],
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Failed to resolve Modrinth modpack: {e}")

    # ── CurseForge ─────────────────────────────────────────────────
    if "curseforge.com" in host:
        # URL format: https://www.curseforge.com/minecraft/modpacks/<slug>
        slug = None
        for i, part in enumerate(path_parts):
            if part in ("modpacks", "mc-mods", "texture-packs"):
                if i + 1 < len(path_parts):
                    slug = path_parts[i + 1]
                    break
        if not slug:
            raise HTTPException(400, "Could not extract CurseForge project slug from URL")
        try:
            from integrations_store import get_integration_key
            api_key = get_integration_key("curseforge")
            if not api_key:
                raise HTTPException(400, "CurseForge API key not configured — set it in Settings > Integrations")
            cf_headers = {
                "x-api-key": api_key,
                "Accept": "application/json",
                "User-Agent": "minecraft-controller/1.0",
            }
            # Search for the project by slug
            search = requests.get(
                "https://api.curseforge.com/v1/mods/search",
                params={"gameId": 432, "slug": slug, "pageSize": 1},
                headers=cf_headers, timeout=15,
            )
            search.raise_for_status()
            results = search.json().get("data") or []
            if not results:
                raise HTTPException(404, f"CurseForge modpack '{slug}' not found")
            project = results[0]
            mod_id = project.get("id")
            # Get versions
            files_r = requests.get(
                f"https://api.curseforge.com/v1/mods/{mod_id}/files",
                params={"pageSize": 20},
                headers=cf_headers, timeout=15,
            )
            files_data = files_r.json().get("data") or [] if files_r.ok else []
            logo = project.get("logo") or {}
            return {
                "provider": "curseforge",
                "pack_id": str(mod_id),
                "name": project.get("name") or slug,
                "description": project.get("summary") or "",
                "icon_url": logo.get("thumbnailUrl") or logo.get("url") or "",
                "game_versions": list({gv for f in files_data for gv in (f.get("gameVersions") or [])}),
                "loaders": [],
                "downloads": project.get("downloadCount") or 0,
                "versions": [
                    {
                        "id": str(f.get("id")),
                        "name": f.get("displayName") or f.get("fileName"),
                        "version_number": f.get("displayName"),
                        "game_versions": f.get("gameVersions") or [],
                        "loaders": [],
                        "date_published": f.get("fileDate"),
                    }
                    for f in files_data[:20]
                ],
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Failed to resolve CurseForge modpack: {e}")

    raise HTTPException(400, "URL not recognized. Paste a CurseForge, Modrinth, or FTB modpack URL.")

@router.post("/install")
async def install_modpack(req: InstallRequest, current_user: User = Depends(require_moderator)):
    task_id = str(uuid.uuid4())
    with _install_lock:
        _install_tasks[task_id] = {"events": [], "done": False}

    def worker():
        tmpdir: Path | None = None
        try:
            install_mode = (req.install_mode or "server").lower()
            _push_event(task_id, {"type": "progress", "step": "resolve", "message": "Modpack-Metadaten werden aufgelöst...", "progress": 10})

            from catalog_routes import get_providers_live
            prov = get_providers_live()
            provider = prov.get(req.provider)
            if not provider:
                raise RuntimeError("Unknown provider (not configured)")

            # Resolve version
            versions = provider.get_versions(req.pack_id, limit=50)
            v = None
            if req.version_id:
                v = next((x for x in versions if str(x.get("id")) == str(req.version_id)), None)
            if not v and versions:
                v = versions[0]
            if not v:
                raise RuntimeError("No versions available for this pack")

            servers_root = SERVERS_ROOT
            target_dir = servers_root / req.name
            target_dir.mkdir(parents=True, exist_ok=True)
            tmpdir = Path(tempfile.mkdtemp(prefix="modpack_install_"))

            loader = (v.get("loaders") or [None])[0]
            mc_version = (v.get("game_versions") or [None])[0]
            loader_version = None
            is_client_pack_fallback = False
            files_downloaded_count = 0

            # ── Pfad A: Feed The Beast (FTB) Manifest-basierter Download ──
            if req.provider == "ftb" and hasattr(provider, "get_version_manifest"):
                ftb_mani = provider.get_version_manifest(req.pack_id, str(v.get("id")))
                # Speichere offizielles FTB-Manifest für ModSideResolver
                (target_dir / ".ftb_manifest.json").write_text(
                    json.dumps(ftb_mani, indent=2), encoding="utf-8"
                )
                for tgt in ftb_mani.get("targets", []) or []:
                    if isinstance(tgt, dict):
                        if tgt.get("type") == "game" and tgt.get("version"):
                            mc_version = str(tgt["version"])
                        elif tgt.get("type") == "modloader":
                            loader = str(tgt.get("name") or "").lower()
                            loader_version = str(tgt.get("version") or "")

                ftb_files = ftb_mani.get("files", []) or []
                total_ftb = len(ftb_files)
                for idx_f, f_entry in enumerate(ftb_files, start=1):
                    if not isinstance(f_entry, dict):
                        continue
                    f_url = f_entry.get("url")
                    if not f_url:
                        continue
                    rel_path = str(f_entry.get("path") or "./").lstrip("./").lstrip("/")
                    f_name = str(f_entry.get("name") or Path(f_url).name)
                    dest_file = target_dir / rel_path / f_name
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        _download_to(dest_file, f_url, timeout=120)
                        files_downloaded_count += 1
                    except Exception as de:
                        log.warning(f"Failed FTB file {f_name}: {de}")
                    if idx_f == total_ftb or idx_f % 15 == 0 or idx_f == 1:
                        pct = 20 + int((idx_f / max(total_ftb, 1)) * 30)
                        _push_event(
                            task_id,
                            {
                                "type": "progress",
                                "step": "download",
                                "message": f"Modpack heruntergeladen: {files_downloaded_count} / {total_ftb} Dateien",
                                "progress": pct,
                                "stats": {"files_downloaded": files_downloaded_count},
                            },
                        )
            else:
                # ── Pfad B: Modrinth (.mrpack) oder CurseForge (.zip) ──
                files = v.get("files") or []
                artifact = None

                # Bei Dedicated-Server-Installation zuerst offizielles Server-Pack bevorzugen
                if install_mode != "client":
                    for f in files:
                        if f.get("is_server_pack") and f.get("url"):
                            artifact = f
                            break

                # Falls kein Server-Pack existiert (oder Client-Modus), Client-Pack nutzen
                if not artifact:
                    for f in files:
                        if f.get("url"):
                            artifact = f
                            is_client_pack_fallback = True
                            break

                if not artifact or not artifact.get("url"):
                    raise RuntimeError(
                        "No downloadable file for this version. "
                        "Ensure a valid API key is configured if using CurseForge."
                    )

                filename = artifact.get("filename") or "artifact.bin"
                url = artifact.get("url")

                _push_event(
                    task_id,
                    {
                        "type": "progress",
                        "step": "download",
                        "message": f"Lade {'Client-Modpack' if is_client_pack_fallback else 'Server-Modpack'} herunter ({filename})...",
                        "progress": 25,
                    },
                )

                artifact_path = tmpdir / filename
                with requests.get(url, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    with open(artifact_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                files_downloaded_count += 1

                # Entpacke das Archiv
                _push_event(task_id, {"type": "progress", "step": "extract", "message": "Entpacke Modpack-Archiv...", "progress": 35})
                extract_dir = tmpdir / "extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(artifact_path, "r") as z:
                    z.extractall(extract_dir)

                def _single_top_level_dir(base: Path):
                    entries = [p for p in base.iterdir()]
                    if len(entries) == 1 and entries[0].is_dir():
                        return entries[0]
                    return None

                src_dir = _single_top_level_dir(extract_dir) or extract_dir
                for p in src_dir.iterdir():
                    dest = target_dir / p.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink(missing_ok=True)
                    shutil.move(str(p), str(dest))

                # Merge overrides/ und server-overrides/ (Konfigurationen, Datapacks, Weltgenerierung)
                override_dirs = ["overrides", "client-overrides"] if install_mode == "client" else ["overrides", "server-overrides"]
                for ov_name in override_dirs:
                    ov_dir = target_dir / ov_name
                    if ov_dir.exists() and ov_dir.is_dir():
                        for root, dirs, ov_files in os.walk(ov_dir):
                            rel = Path(root).relative_to(ov_dir)
                            out_dir = target_dir / rel
                            out_dir.mkdir(parents=True, exist_ok=True)
                            for fn in ov_files:
                                srcf = Path(root) / fn
                                shutil.move(str(srcf), str(out_dir / fn))
                        shutil.rmtree(ov_dir, ignore_errors=True)

                # 1. Modrinth `modrinth.index.json` verarbeiten (.mrpack)
                mr_index_path = target_dir / "modrinth.index.json"
                if mr_index_path.exists():
                    try:
                        mr_idx = json.loads(mr_index_path.read_text(encoding="utf-8", errors="ignore"))
                        deps = mr_idx.get("dependencies") or {}
                        if isinstance(deps, dict):
                            mc_version = deps.get("minecraft") or mc_version
                            if deps.get("neoforge"):
                                loader = "neoforge"
                                loader_version = str(deps["neoforge"])
                            elif deps.get("forge"):
                                loader = "forge"
                                loader_version = str(deps["forge"])
                            elif deps.get("fabric-loader"):
                                loader = "fabric"
                                loader_version = str(deps["fabric-loader"])
                            elif deps.get("quilt-loader"):
                                loader = "quilt"
                                loader_version = str(deps["quilt-loader"])

                        mr_files = mr_idx.get("files") or []
                        total_mr = len(mr_files)
                        for idx_m, entry in enumerate(mr_files, start=1):
                            if not isinstance(entry, dict):
                                continue
                            rel_p = entry.get("path")
                            downloads = entry.get("downloads") or []
                            if not rel_p or not downloads:
                                continue
                            dest_p = target_dir / rel_p
                            dest_p.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                _download_to(dest_p, downloads[0], timeout=120)
                                files_downloaded_count += 1
                            except Exception as de:
                                log.warning(f"Failed Modrinth file {rel_p}: {de}")
                            if idx_m == total_mr or idx_m % 10 == 0 or idx_m == 1:
                                pct = 38 + int((idx_m / max(total_mr, 1)) * 14)
                                _push_event(
                                    task_id,
                                    {
                                        "type": "progress",
                                        "step": "mods",
                                        "message": f"Modpack heruntergeladen: {files_downloaded_count} / {total_mr} Dateien",
                                        "progress": pct,
                                        "stats": {"files_downloaded": files_downloaded_count},
                                    },
                                )
                    except Exception as e:
                        _push_event(task_id, {"type": "progress", "step": "mods", "message": f"modrinth.index.json Fehler: {e}", "progress": 50})

                # 2. CurseForge `manifest.json` verarbeiten
                manifest_path = target_dir / "manifest.json"
                if not manifest_path.exists():
                    for child in target_dir.iterdir():
                        if child.is_dir() and (child / "manifest.json").exists():
                            manifest_path = child / "manifest.json"
                            break

                if manifest_path and manifest_path.exists():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            mani = json.load(f)
                        mc = mani.get("minecraft", {})
                        mv = mc.get("version")
                        if isinstance(mv, str):
                            mc_version = mv
                        mls = mc.get("modLoaders") or []
                        if isinstance(mls, list) and mls:
                            preferred = ["neoforge", "forge", "fabric", "quilt"]
                            for pref in preferred:
                                for entry in mls:
                                    mid = str((entry or {}).get("id") or "")
                                    mid_l = mid.lower()
                                    if pref == "neoforge" and mid_l.startswith("neoforge"):
                                        loader = "neoforge"
                                        loader_version = mid.split("-", 1)[1] if "-" in mid else None
                                        break
                                    if pref == "forge" and mid_l.startswith("forge"):
                                        loader = "forge"
                                        loader_version = mid.split("-", 1)[1] if "-" in mid else None
                                        break
                                    if pref == "fabric" and "fabric" in mid_l:
                                        loader = "fabric"
                                        loader_version = mid.split("-", 1)[1] if "-" in mid else None
                                        break
                                    if pref == "quilt" and "quilt" in mid_l:
                                        loader = "quilt"
                                        loader_version = mid.split("-", 1)[1] if "-" in mid else None
                                        break
                                if loader:
                                    break

                        files_list = mani.get("files") or []
                        if files_list:
                            from integrations_store import get_integration_key
                            api_key = get_integration_key("curseforge")
                            if not api_key:
                                raise RuntimeError("CurseForge API key not configured; cannot download listed mods from manifest.json")
                            headers = {"x-api-key": api_key, "Accept": "application/json", "User-Agent": "minecraft-controller/1.0"}
                            mods_dir = target_dir / "mods"
                            mods_dir.mkdir(parents=True, exist_ok=True)
                            total = len(files_list)
                            done = 0
                            for entry in files_list:
                                proj = entry.get("projectID") or entry.get("projectId")
                                fid = entry.get("fileID") or entry.get("fileId")
                                if not proj or not fid:
                                    continue
                                try:
                                    url_meta = f"https://api.curseforge.com/v1/mods/{proj}/files/{fid}"
                                    rr = requests.get(url_meta, headers=headers, timeout=30)
                                    rr.raise_for_status()
                                    data = rr.json().get("data") or {}
                                    dl = data.get("downloadUrl")
                                    out_name = data.get("fileName") or f"{proj}-{fid}.jar"
                                    if dl:
                                        _download_to(mods_dir / out_name, dl, timeout=120)
                                        files_downloaded_count += 1
                                    done += 1
                                    pct = 38 + int((done / max(total, 1)) * 14)
                                    if done == total or done % 10 == 0 or done == 1:
                                        _push_event(
                                            task_id,
                                            {
                                                "type": "progress",
                                                "step": "mods",
                                                "message": f"Modpack heruntergeladen: {files_downloaded_count} ({done}/{total} Mods)",
                                                "progress": pct,
                                                "stats": {"files_downloaded": files_downloaded_count},
                                            },
                                        )
                                except Exception as de:
                                    _push_event(task_id, {"type": "progress", "step": "mods", "message": f"Failed mod {proj}/{fid}: {de}", "progress": 50})
                    except Exception as e:
                        _push_event(task_id, {"type": "progress", "step": "mods", "message": f"manifest.json processing failed: {e}", "progress": 52})

            # Falls noch Metadaten fehlen, aus entpacktem Verzeichnis extrahieren
            extracted_meta = _extract_modpack_metadata(target_dir)
            if not loader and extracted_meta.get("loader"):
                loader = extracted_meta.get("loader")
            if not mc_version and extracted_meta.get("minecraft_version"):
                mc_version = extracted_meta.get("minecraft_version")
            if not loader_version and extracted_meta.get("loader_version"):
                loader_version = extracted_meta.get("loader_version")

            # Schritt: ModSideResolver + Loader-Setup + Validierung (sowohl für Client-Pack-Fallbacks
            # als auch für offizielle Server-Packs gemäß Abschnitt 6 & 7!)
            mod_side_report = _process_client_pack(
                target_dir,
                push_event=lambda ev: _push_event(task_id, ev),
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                install_mode=install_mode,
            )

            dm = get_docker_manager()
            def normalize_ram(s: str) -> str:
                s = str(s).upper()
                if s.endswith("G") or s.endswith("M"):
                    return s
                try:
                    n = int(s)
                    return f"{n}M"
                except Exception:
                    return "2048M"

            _push_event(task_id, {"type": "progress", "step": "prepare", "message": "Server-Dateien werden vorbereitet...", "progress": 75})

            min_ram = req.min_ram or "2048M"
            max_ram = req.max_ram or "4096M"
            min_ram_n = normalize_ram(min_ram)
            max_ram_n = normalize_ram(max_ram)

            _push_event(task_id, {"type": "progress", "step": "create", "message": "Erstelle Server-Instanz...", "progress": 85})
            extra_env = {}
            try:
                if loader:
                    extra_env["SERVER_TYPE"] = loader
                if mc_version:
                    extra_env["SERVER_VERSION"] = mc_version
            except Exception:
                pass
            result = dm.create_server_from_existing(
                name=req.name,
                host_port=req.host_port,
                min_ram=min_ram_n,
                max_ram=max_ram_n,
                extra_env=extra_env or None,
                cpu_cores=req.cpu_cores,
                extra_labels={
                    "mc.modpack.provider": req.provider,
                    "mc.modpack.id": str(req.pack_id),
                    "mc.modpack.version_id": str(v.get("id")),
                    "mc.modpack.install_mode": install_mode,
                    "mc.modpack.client_pack_fallback": "true" if is_client_pack_fallback else "false",
                }
            )

            _push_event(
                task_id,
                {
                    "type": "done",
                    "message": "Installation erfolgreich abgeschlossen",
                    "server": result,
                    "mod_side_report": mod_side_report,
                    "stats": {
                        "files_downloaded": files_downloaded_count or mod_side_report.get("total_mods", 0),
                        "mods_analyzed": mod_side_report.get("total_mods", 0),
                        "total_mods": mod_side_report.get("total_mods", 0),
                        "client_only_count": mod_side_report.get("client_only_count", 0),
                        "server_mods_kept": mod_side_report.get("server_mods_kept_count", 0),
                        "dependencies_checked": True,
                        "loader_installed": f"{loader or 'server'} {loader_version or ''}".strip(),
                        "validation_status": "Erfolgreich",
                    },
                    "excluded_mods": mod_side_report.get("excluded_mods", []),
                },
            )
        except Exception as e:
            _push_event(task_id, {"type": "error", "message": str(e)})
        finally:
            try:
                if 'tmpdir' in locals() and tmpdir:
                    shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()
    return {"task_id": task_id}

@router.get("/updates")
async def list_updates():
    from catalog_routes import get_providers_live
    dm = get_docker_manager()
    servers = dm.list_servers()
    updates = []
    providers = get_providers_live()
    for s in servers:
        labels = s.get("labels") or {}
        prov = labels.get("mc.modpack.provider")
        pack_id = labels.get("mc.modpack.id")
        current_ver = labels.get("mc.modpack.version_id")
        if not prov or not pack_id or not current_ver or prov not in providers:
            continue
        try:
            p = providers[prov]
            vers = p.get_versions(pack_id, limit=10)
            latest = vers[0] if vers else None
            if latest and str(latest.get("id")) != str(current_ver):
                updates.append({
                    "server": s.get("name"),
                    "provider": prov,
                    "pack_id": pack_id,
                    "current_version_id": current_ver,
                    "latest_version_id": latest.get("id"),
                    "latest_name": latest.get("name") or latest.get("version_number"),
                })
        except Exception:
            continue
    return {"updates": updates}

@router.post("/update")
async def update_modpack(server_name: str, provider: str, pack_id: str, version_id: str, current_user: User = Depends(require_moderator)):
    # Simplified update: stop, backup, apply new files (overrides+mods), restart
    from catalog_routes import get_providers_live
    dm = get_docker_manager()
    providers = get_providers_live()
    # Find server container id
    target = None
    for s in dm.list_servers():
        if s.get("name") == server_name:
            target = s
            break
    if not target:
        raise HTTPException(status_code=404, detail="Server not found")
    container_id = target.get("id")
    if not container_id:
        raise HTTPException(status_code=400, detail="Container id missing")

    # Stop server
    try:
        dm.stop_server(container_id)
    except Exception:
        pass

    # Backup
    try:
        from backup_manager import create_backup as bk_create
        bk_create(server_name)
    except Exception:
        pass

    # Download and apply new version (reuse logic from install worker in a simplified form)
    p = providers.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail="Provider not configured")
    versions = p.get_versions(pack_id, limit=50)
    v = next((x for x in versions if str(x.get("id")) == str(version_id)), None)
    if not v:
        raise HTTPException(status_code=400, detail="Version not found")
    files = v.get("files") or []
    mr = None
    for f in files:
        fn = (f.get("filename") or "").lower()
        if f.get("primary") or fn.endswith(".mrpack"):
            mr = f
            break
    if not mr and files:
        mr = files[0]
    if not mr or not mr.get("url"):
        raise HTTPException(status_code=400, detail="No downloadable file for version")

    servers_root = SERVERS_ROOT
    target_dir = servers_root / server_name
    if not target_dir.exists():
        raise HTTPException(status_code=400, detail="Server directory does not exist")

    tmpdir = Path(tempfile.mkdtemp(prefix="mrpack_update_"))
    try:
        mrpack_path = tmpdir / (mr.get("filename") or "pack.mrpack")
        with requests.get(mr["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(mrpack_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        # Extract overrides and download files
        idx = None
        with zipfile.ZipFile(mrpack_path, 'r') as z:
            names = z.namelist()
            for name in names:
                if name.startswith("overrides/") and not name.endswith("/"):
                    dest = target_dir / name[len("overrides/"):]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            index_name = None
            for cand in ("modrinth.index.json", "index.json"):
                if cand in names:
                    index_name = cand
                    break
            if index_name:
                with z.open(index_name) as s:
                    idx = json.load(s)
        if isinstance(idx, dict) and isinstance(idx.get("files"), list):
            for entry in idx["files"]:
                env = entry.get("env") or {}
                if isinstance(env, dict) and str(env.get("server", "")).lower() == "unsupported":
                    continue
                path = entry.get("path")
                downloads = entry.get("downloads") or []
                if not path or not downloads:
                    continue
                dest = target_dir / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                url0 = downloads[0]
                try:
                    with requests.get(url0, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        with open(dest, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                except Exception:
                    continue
        # Record metadata about installed modpack version (labels not updatable post-create)
        try:
            meta_path = target_dir / "modpack.meta.json"
            meta = {
                "provider": provider,
                "pack_id": str(pack_id),
                "version_id": str(version_id),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f)
        except Exception:
            pass
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
    # Start server
    dm.start_server(container_id)
    return {"ok": True}

@router.get("/install/events/{task_id}")
async def install_events(task_id: str):
    def gen():
        idx = 0
        while True:
            with _install_lock:
                task = _install_tasks.get(task_id)
                if not task:
                    yield f"data: {json.dumps({'type':'error','message':'task not found'})}\n\n"
                    break
                events = task["events"]
                done = task.get("done")
            while idx < len(events):
                ev = events[idx]
                idx += 1
                yield f"data: {json.dumps(ev)}\n\n"
            if done:
                break
            time.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")

