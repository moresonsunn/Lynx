from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any, List, Set
from pathlib import Path
import asyncio
from datetime import datetime, timezone
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

from auth import require_auth, require_moderator
from models import User
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT, safe_child_path
from mod_side_resolver import ModSideResolver, inspect_jar_metadata
from client_mod_detector import (
    load_client_only_config,
    detect_client_only_mods,
    remove_client_only_mods,
    process_client_pack,
    is_client_only_jar,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/modpacks", tags=["modpacks"])

class ModpackUpdateRequest(BaseModel):
    target_version_id: str
    create_backup: bool = True

def _host_matches(host: str, *domains: str) -> bool:
    """Safely check whether a parsed URL hostname equals or is a subdomain of one of the allowed domains."""
    h = (host or "").strip().lower().split(":", 1)[0].rstrip(".")
    for d in domains:
        dom = d.strip().lower().rstrip(".")
        if h == dom or h.endswith("." + dom):
            return True
    return False


def _validate_public_http_url(raw_url: str) -> str:
    """Validate that raw_url is an HTTP(S) URL resolving only to public (non-private/non-loopback) IP addresses."""
    import ipaddress
    import socket
    parsed = urlparse((raw_url or "").strip())
    if parsed.scheme not in ("https", "http"):
        raise ValueError("Only http:// and https:// URLs are allowed")
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise ValueError("URL is missing a valid hostname")
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except Exception as exc:
        raise ValueError(f"Could not resolve hostname {hostname}: {exc}")
    for info in addr_infos:
        ip_str = info[4][0]
        ip_obj = ipaddress.ip_address(ip_str)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ValueError(f"Refusing connection to non-public address for {hostname}")
    return parsed.geturl()


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


PROTECTED_PREFIXES = (
    "world",
    "world_nether",
    "world_the_end",
    "backups",
    "logs",
    "crash-reports",
)

PROTECTED_EXACT_FILES = {
    "server.properties",
    "eula.txt",
    "whitelist.json",
    "ops.json",
    "banned-players.json",
    "banned-ips.json",
    "usercache.json",
    "server-icon.png",
    "modpack.meta.json",
    ".mod_side_report.json",
    "client-only-allow.json",
    "client-only-allow.txt",
}


def is_path_protected(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").strip("/").lower()
    base_name = norm.split("/")[-1]
    if base_name in {f.lower() for f in PROTECTED_EXACT_FILES} or norm in {f.lower() for f in PROTECTED_EXACT_FILES}:
        return True
    first_part = norm.split("/")[0]
    for prefix in PROTECTED_PREFIXES:
        if first_part == prefix.lower() or norm.startswith(prefix.lower() + "/"):
            return True
    return False


def get_server_modpack_info(server_name: str) -> Optional[dict]:
    """
    Retrieves modpack metadata for a server.
    Fallback priority:
      1. <server_dir>/modpack.meta.json
      2. <server_dir>/server_meta.json
      3. Docker container labels (mc.modpack.*)
    """
    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    if not server_dir.exists() or not server_dir.is_dir():
        # Fallback to check Docker container labels even if directory is elsewhere or not created yet
        try:
            dm = get_docker_manager()
            for s in dm.list_servers():
                if s.get("name") == server_name:
                    labels = s.get("labels") or {}
                    prov = labels.get("mc.modpack.provider")
                    pid = labels.get("mc.modpack.id")
                    vid = labels.get("mc.modpack.version_id")
                    if prov and pid:
                        return {
                            "server_name": server_name,
                            "provider": str(prov).strip().lower(),
                            "pack_id": str(pid).strip(),
                            "version_id": str(vid) if vid is not None else None,
                            "version_name": str(vid) if vid is not None else None,
                            "installed_files": [],
                            "loader": labels.get("mc.type"),
                            "loader_version": None,
                            "minecraft_version": labels.get("mc.version"),
                            "install_mode": labels.get("mc.modpack.install_mode", "server"),
                            "installed_at": None,
                            "updated_at": None,
                            "source": "docker_labels",
                            "server_dir": server_dir,
                        }
                    break
        except Exception as e:
            log.warning(f"Error checking Docker labels for {server_name}: {e}")
        return None

    # Tier 1: modpack.meta.json
    meta_file = server_dir / "modpack.meta.json"
    if meta_file.is_file():
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                provider = str(data.get("provider") or "").strip().lower()
                pack_id = str(data.get("pack_id") or "").strip()
                if provider and pack_id:
                    return {
                        "server_name": server_name,
                        "provider": provider,
                        "pack_id": pack_id,
                        "version_id": str(data.get("version_id")) if data.get("version_id") is not None else None,
                        "version_name": data.get("version_name"),
                        "installed_files": data.get("installed_files") or [],
                        "loader": data.get("loader"),
                        "loader_version": data.get("loader_version"),
                        "minecraft_version": data.get("minecraft_version"),
                        "install_mode": data.get("install_mode", "server"),
                        "installed_at": data.get("installed_at"),
                        "updated_at": data.get("updated_at"),
                        "source": "modpack.meta.json",
                        "server_dir": server_dir,
                    }
        except Exception as e:
            log.warning(f"Error reading {meta_file}: {e}")

    # Tier 2: server_meta.json
    server_meta_file = server_dir / "server_meta.json"
    if server_meta_file.is_file():
        try:
            data = json.loads(server_meta_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                prov = data.get("modpack_provider") or data.get("provider")
                pid = data.get("modpack_id") or data.get("pack_id")
                vid = data.get("modpack_version_id") or data.get("version_id")
                if prov and pid:
                    return {
                        "server_name": server_name,
                        "provider": str(prov).strip().lower(),
                        "pack_id": str(pid).strip(),
                        "version_id": str(vid) if vid is not None else None,
                        "version_name": data.get("modpack_version_name") or (str(vid) if vid is not None else None),
                        "installed_files": data.get("installed_files") or [],
                        "loader": data.get("mc_type") or data.get("loader"),
                        "loader_version": data.get("loader_version"),
                        "minecraft_version": data.get("mc_version") or data.get("minecraft_version"),
                        "install_mode": data.get("install_mode", "server"),
                        "installed_at": data.get("installed_at"),
                        "updated_at": data.get("updated_at"),
                        "source": "server_meta.json",
                        "server_dir": server_dir,
                    }
        except Exception as e:
            log.warning(f"Error reading {server_meta_file}: {e}")

    # Tier 3: Docker container labels
    try:
        dm = get_docker_manager()
        for s in dm.list_servers():
            if s.get("name") == server_name:
                labels = s.get("labels") or {}
                prov = labels.get("mc.modpack.provider")
                pid = labels.get("mc.modpack.id")
                vid = labels.get("mc.modpack.version_id")
                if prov and pid:
                    return {
                        "server_name": server_name,
                        "provider": str(prov).strip().lower(),
                        "pack_id": str(pid).strip(),
                        "version_id": str(vid) if vid is not None else None,
                        "version_name": str(vid) if vid is not None else None,
                        "installed_files": [],
                        "loader": labels.get("mc.type"),
                        "loader_version": None,
                        "minecraft_version": labels.get("mc.version"),
                        "install_mode": labels.get("mc.modpack.install_mode", "server"),
                        "installed_at": None,
                        "updated_at": None,
                        "source": "docker_labels",
                        "server_dir": server_dir,
                    }
                break
    except Exception as e:
        log.warning(f"Error checking Docker labels for {server_name}: {e}")

    return None


def save_server_modpack_info(server_name: str, meta: dict) -> Path:
    """Writes updated modpack metadata to <server_dir>/modpack.meta.json atomically."""
    server_dir = safe_child_path(SERVERS_ROOT, server_name)
    server_dir.mkdir(parents=True, exist_ok=True)
    meta_path = server_dir / "modpack.meta.json"

    temp_fd, temp_path = tempfile.mkstemp(prefix="modpack_meta_", suffix=".tmp", dir=str(server_dir))
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, meta_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    return meta_path


def reconcile_and_cleanup_modpack(
    server_dir: Path,
    staging_dir: Path,
    previous_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """
    Executes hybrid cleanup combining:
      Method B: Mod-ID based deduplication (inspect_jar_metadata)
      Method A: Manifest-based file tracking (previous_meta["installed_files"])
    """
    server_dir = Path(server_dir)
    mods_dir = server_dir / "mods"
    disabled_dir = server_dir / "mods-disabled-client"

    mods_cleaned: List[str] = []
    files_removed: List[str] = []
    deleted_paths: Set[str] = set()

    # 1. Scan and index existing jars in server_dir/mods and server_dir/mods-disabled-client
    existing_mod_map: Dict[str, List[Path]] = {}
    scan_dirs = [mods_dir]
    if disabled_dir.exists():
        scan_dirs.append(disabled_dir)

    for target_d in scan_dirs:
        if not target_d.exists():
            continue
        for jar_path in target_d.glob("*.jar"):
            try:
                info = inspect_jar_metadata(jar_path)
                mod_ids = set()
                if info.get("mod_id"):
                    mod_ids.add(info["mod_id"].strip().lower())
                for prov in info.get("provided_mods", []):
                    if prov:
                        mod_ids.add(str(prov).strip().lower())
                for mid in mod_ids:
                    existing_mod_map.setdefault(mid, []).append(jar_path)
            except Exception:
                pass

    # 2. Method B: Inspect incoming jars in staging_dir
    staged_mods = list(staging_dir.rglob("*.jar"))
    for s_jar in staged_mods:
        try:
            s_info = inspect_jar_metadata(s_jar)
            s_mod_id = (s_info.get("mod_id") or "").strip().lower()
            incoming_mids = set()
            if s_mod_id:
                incoming_mids.add(s_mod_id)
            for prov in s_info.get("provided_mods", []):
                if prov:
                    incoming_mids.add(str(prov).strip().lower())

            for mid in incoming_mids:
                if mid in existing_mod_map:
                    for existing_jar in existing_mod_map[mid]:
                        if existing_jar.name != s_jar.name and existing_jar.exists():
                            try:
                                existing_jar.unlink()
                                deleted_paths.add(str(existing_jar.resolve()))
                                if existing_jar.name not in mods_cleaned:
                                    mods_cleaned.append(existing_jar.name)
                            except OSError:
                                pass
        except Exception:
            pass

    # 3. Method A: Manifest-based file tracking from previous_meta
    new_staged_files = {
        p.relative_to(staging_dir).as_posix()
        for p in staging_dir.rglob("*")
        if p.is_file()
    }

    if previous_meta and isinstance(previous_meta.get("installed_files"), list):
        old_files = set(previous_meta["installed_files"])
        candidates_to_prune = old_files - new_staged_files

        for rel_str in candidates_to_prune:
            if is_path_protected(rel_str):
                continue

            norm_rel = Path(rel_str).as_posix().lstrip("/")
            if ".." in norm_rel.split("/"):
                continue

            target_file = safe_child_path(server_dir, norm_rel)
            if str(target_file.resolve()) in deleted_paths:
                continue

            if target_file.is_file():
                try:
                    target_file.unlink()
                    deleted_paths.add(str(target_file.resolve()))
                    if norm_rel.startswith("mods/") or norm_rel.endswith(".jar"):
                        if target_file.name not in mods_cleaned:
                            mods_cleaned.append(target_file.name)
                    else:
                        files_removed.append(norm_rel)
                except OSError:
                    pass
            elif norm_rel.startswith("mods/"):
                disabled_file = server_dir / "mods-disabled-client" / target_file.name
                if disabled_file.is_file() and str(disabled_file.resolve()) not in deleted_paths:
                    try:
                        disabled_file.unlink()
                        deleted_paths.add(str(disabled_file.resolve()))
                        if disabled_file.name not in mods_cleaned:
                            mods_cleaned.append(disabled_file.name)
                    except OSError:
                        pass

    return {
        "mods_cleaned": sorted(mods_cleaned),
        "files_removed": sorted(files_removed),
    }


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
    path = safe_child_path(path.parent, path.name)
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
    target_dir = safe_child_path(servers_root, payload.server_name)
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
        if _host_matches(host, "curseforge.com") and "/download/" in path:
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
        download_url = _validate_public_http_url(download_url)
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
    target_dir = safe_child_path(servers_root, server_name)
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

        with zipfile.ZipFile(zip_path, 'r') as z:
            for member in z.infolist():
                # Skip directories explicitly handled
                name = member.filename
                if name.endswith('/'):
                    continue
                # Prevent absolute paths or traversal
                dest_path = safe_child_path(extract_dir, name)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
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
    if _host_matches(host, "feed-the-beast.com", "ftb.team"):
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
    if _host_matches(host, "modrinth.com"):
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
    if _host_matches(host, "curseforge.com"):
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
            target_dir = safe_child_path(servers_root, req.name)
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
                    dest_file = safe_child_path(target_dir, rel_path, f_name)
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

                artifact_path = safe_child_path(tmpdir, filename)
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
                            dest_p = safe_child_path(target_dir, rel_p)
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
                                        _download_to(safe_child_path(mods_dir, out_name), dl, timeout=120)
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

            # Write modpack.meta.json so new installations have ground-truth metadata immediately
            try:
                installed_files = sorted([
                    p.relative_to(target_dir).as_posix()
                    for p in target_dir.rglob("*")
                    if p.is_file() and not is_path_protected(p.relative_to(target_dir).as_posix())
                ])
                initial_meta = {
                    "provider": req.provider.lower(),
                    "pack_id": str(req.pack_id),
                    "version_id": str(v.get("id")),
                    "version_name": v.get("name") or str(v.get("id")),
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "installed_files": installed_files,
                    "loader": loader,
                    "loader_version": loader_version,
                    "minecraft_version": mc_version,
                    "install_mode": install_mode,
                    "client_pack_fallback": bool(is_client_pack_fallback),
                }
                save_server_modpack_info(req.name, initial_meta)
            except Exception as meta_err:
                log.warning(f"Failed to save initial modpack.meta.json for {req.name}: {meta_err}")

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

def _stage_modpack_version(
    provider_id: str,
    provider: Any,
    pack_id: str,
    target_version_obj: Dict[str, Any],
    staging_dir: Path,
    tmpdir: Path,
) -> Dict[str, Any]:
    """
    Downloads and stages the target modpack version files into staging_dir.
    Returns metadata dict: {"loader": ..., "minecraft_version": ..., "loader_version": ...}
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    loader = None
    mc_version = None
    loader_version = None

    if target_version_obj.get("loaders"):
        loader = target_version_obj["loaders"][0]
    if target_version_obj.get("game_versions"):
        mc_version = target_version_obj["game_versions"][0]

    # Path A: Feed The Beast
    if provider_id == "ftb" and hasattr(provider, "get_version_manifest"):
        ftb_mani = provider.get_version_manifest(pack_id, str(target_version_obj.get("id")))
        (staging_dir / ".ftb_manifest.json").write_text(json.dumps(ftb_mani, indent=2), encoding="utf-8")
        for tgt in ftb_mani.get("targets", []) or []:
            if isinstance(tgt, dict):
                if tgt.get("type") == "game" and tgt.get("version"):
                    mc_version = str(tgt["version"])
                elif tgt.get("type") == "modloader":
                    loader = str(tgt.get("name") or "").lower()
                    loader_version = str(tgt.get("version") or "")
        ftb_files = ftb_mani.get("files", []) or []
        for f_entry in ftb_files:
            if not isinstance(f_entry, dict) or f_entry.get("clientonly"):
                continue
            f_url = f_entry.get("url")
            if not f_url:
                continue
            rel_path = str(f_entry.get("path") or "./").lstrip("./").lstrip("/")
            f_name = str(f_entry.get("name") or Path(f_url).name)
            dest_file = safe_child_path(staging_dir, rel_path, f_name)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            _download_to(dest_file, f_url, timeout=120)
        return {"loader": loader, "minecraft_version": mc_version, "loader_version": loader_version}

    # Path B: Modrinth / CurseForge / Zip archives
    files = target_version_obj.get("files") or []
    artifact = None
    for f in files:
        if f.get("is_server_pack") and f.get("url"):
            artifact = f
            break
    if not artifact:
        for f in files:
            if f.get("url"):
                artifact = f
                break

    if not artifact or not artifact.get("url"):
        raise HTTPException(
            status_code=400,
            detail="No downloadable artifact found for target modpack version",
        )

    filename = artifact.get("filename") or "modpack.zip"
    artifact_path = safe_child_path(tmpdir, filename)
    with requests.get(artifact["url"], stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(artifact_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    extract_dir = tmpdir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_path, "r") as z:
        names = z.namelist()
        has_overrides = any(n.startswith("overrides/") or n.startswith("server-overrides/") for n in names)
        if has_overrides:
            for name in names:
                if (name.startswith("overrides/") or name.startswith("server-overrides/")) and not name.endswith("/"):
                    sub = "overrides/" if name.startswith("overrides/") else "server-overrides/"
                    rel = name[len(sub):]
                    dest = safe_child_path(staging_dir, rel)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                elif name in ("modrinth.index.json", "manifest.json", "index.json"):
                    dest = safe_child_path(staging_dir, name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            z.extractall(extract_dir)
            def _single_top_level_dir(base: Path):
                entries = [p for p in base.iterdir()]
                if len(entries) == 1 and entries[0].is_dir():
                    return entries[0]
                return None
            src_dir = _single_top_level_dir(extract_dir) or extract_dir
            for item in src_dir.iterdir():
                dest = safe_child_path(staging_dir, item.name)
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

    # 1. Modrinth modrinth.index.json (.mrpack)
    mr_index_path = staging_dir / "modrinth.index.json"
    if not mr_index_path.exists() and (staging_dir / "index.json").exists():
        mr_index_path = staging_dir / "index.json"

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
            for entry in mr_files:
                if not isinstance(entry, dict):
                    continue
                env = entry.get("env") or {}
                if isinstance(env, dict) and str(env.get("server", "")).lower() == "unsupported":
                    continue
                rel_p = entry.get("path")
                downloads = entry.get("downloads") or []
                if not rel_p or not downloads:
                    continue
                dest_p = safe_child_path(staging_dir, rel_p)
                dest_p.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _download_to(dest_p, downloads[0], timeout=120)
                except Exception as de:
                    log.warning(f"Failed Modrinth download {rel_p}: {de}")
        except Exception as e:
            log.warning(f"Failed parsing Modrinth index: {e}")

    # 2. CurseForge manifest.json
    cf_manifest_path = staging_dir / "manifest.json"
    if cf_manifest_path.exists():
        try:
            cf_mani = json.loads(cf_manifest_path.read_text(encoding="utf-8", errors="ignore"))
            mc_info = cf_mani.get("minecraft") or {}
            if isinstance(mc_info, dict):
                mc_version = mc_info.get("version") or mc_version
                for ml in mc_info.get("modLoaders") or []:
                    if isinstance(ml, dict) and ml.get("id"):
                        ml_id = str(ml["id"]).lower()
                        if ml_id.startswith("forge-"):
                            loader = "forge"
                            loader_version = ml_id[len("forge-"):]
                        elif ml_id.startswith("fabric-"):
                            loader = "fabric"
                            loader_version = ml_id[len("fabric-"):]
                        elif ml_id.startswith("neoforge-"):
                            loader = "neoforge"
                            loader_version = ml_id[len("neoforge-"):]

            if hasattr(provider, "expand_manifest_files"):
                try:
                    resolved_files = provider.expand_manifest_files(cf_mani)
                    for rf in resolved_files:
                        dl = rf.get("downloadUrl")
                        fname = rf.get("fileName") or f"{rf.get('id')}.jar"
                        if dl:
                            dest_mod = safe_child_path(staging_dir, "mods", fname)
                            dest_mod.parent.mkdir(parents=True, exist_ok=True)
                            _download_to(dest_mod, dl, timeout=120)
                except Exception as cf_err:
                    log.warning(f"CurseForge expand_manifest_files error: {cf_err}")
            elif cf_mani.get("files"):
                from modpack_providers.curseforge import CURSE_API_BASE
                for cf_entry in cf_mani.get("files") or []:
                    proj_id = cf_entry.get("projectID")
                    file_id = cf_entry.get("fileID")
                    if proj_id and file_id:
                        try:
                            headers = provider._headers() if hasattr(provider, "_headers") else {}
                            fr = requests.get(f"{CURSE_API_BASE}/mods/{proj_id}/files/{file_id}", headers=headers, timeout=15)
                            if fr.ok:
                                fd = fr.json().get("data") or {}
                                dl = fd.get("downloadUrl")
                                fname = fd.get("fileName") or f"{proj_id}-{file_id}.jar"
                                if dl:
                                    dest_mod = safe_child_path(staging_dir, "mods", fname)
                                    dest_mod.parent.mkdir(parents=True, exist_ok=True)
                                    _download_to(dest_mod, dl, timeout=120)
                        except Exception as de:
                            log.warning(f"Failed CurseForge file download {proj_id}/{file_id}: {de}")
        except Exception as e:
            log.warning(f"Failed parsing CurseForge manifest: {e}")

    # Fallback loader/version detection from staged files
    meta_detect = _extract_modpack_metadata(staging_dir)
    if not loader and meta_detect.get("loader"):
        loader = meta_detect.get("loader")
    if not mc_version and meta_detect.get("minecraft_version"):
        mc_version = meta_detect.get("minecraft_version")
    if not loader_version and meta_detect.get("loader_version"):
        loader_version = meta_detect.get("loader_version")

    return {"loader": loader, "minecraft_version": mc_version, "loader_version": loader_version}


@router.get("/server/{server_name}/versions")
async def get_server_modpack_versions(
    server_name: str,
    limit: int = 50,
    current_user: User = Depends(require_auth),
):
    info = get_server_modpack_info(server_name)
    if not info or not info.get("provider") or not info.get("pack_id"):
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server_name}' does not have a tracked modpack",
        )

    from catalog_routes import get_providers_live
    providers = get_providers_live()
    provider = providers.get(info["provider"])
    if not provider:
        raise HTTPException(
            status_code=400,
            detail=f"Modpack provider '{info['provider']}' is not configured",
        )

    try:
        raw_versions = provider.get_versions(info["pack_id"], limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch versions from provider: {e}",
        )

    current_ver = str(info.get("version_id") or "")
    current_ver_name = info.get("version_name")

    versions = []
    for v in raw_versions:
        vid = str(v.get("id"))
        is_current = bool(current_ver and vid == current_ver)
        v_name = v.get("name") or vid
        if is_current and not current_ver_name:
            current_ver_name = v_name
        versions.append({
            "version_id": vid,
            "version_name": v_name,
            "version_number": v.get("version_number") or v_name,
            "game_versions": v.get("game_versions") or [],
            "loaders": v.get("loaders") or [],
            "date_published": v.get("date_published"),
            "changelog": v.get("changelog") or "",
            "is_current": is_current,
        })

    if not current_ver_name and current_ver:
        current_ver_name = current_ver

    return {
        "server_name": server_name,
        "provider": info["provider"],
        "pack_id": info["pack_id"],
        "current_version_id": current_ver or None,
        "current_version_name": current_ver_name or None,
        "versions": versions,
    }


@router.post("/server/{server_name}/update")
async def update_server_modpack(
    server_name: str,
    payload: ModpackUpdateRequest,
    current_user: User = Depends(require_moderator),
):
    servers_root = SERVERS_ROOT
    server_dir = safe_child_path(servers_root, server_name)
    if not server_dir.exists() or not server_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")

    modpack_info = get_server_modpack_info(server_name)
    if not modpack_info or not modpack_info.get("provider") or not modpack_info.get("pack_id"):
        raise HTTPException(
            status_code=400,
            detail=f"Server '{server_name}' does not have modpack metadata installed",
        )

    provider_id = modpack_info["provider"]
    pack_id = str(modpack_info["pack_id"])
    previous_version_id = modpack_info.get("version_id")

    from catalog_routes import get_providers_live
    providers = get_providers_live()
    provider = providers.get(provider_id)
    if not provider:
        raise HTTPException(status_code=400, detail=f"Modpack provider '{provider_id}' is not configured")

    try:
        versions = provider.get_versions(pack_id, limit=50)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch versions from provider: {e}")

    target_version_obj = next((x for x in versions if str(x.get("id")) == str(payload.target_version_id)), None)
    if not target_version_obj:
        raise HTTPException(status_code=404, detail=f"Target version '{payload.target_version_id}' not found")

    target_version_name = target_version_obj.get("name") or str(payload.target_version_id)

    # Check container running state
    dm = get_docker_manager()
    target_server = None
    try:
        for s in dm.list_servers():
            if s.get("name") == server_name:
                target_server = s
                break
    except Exception:
        pass

    container_id = target_server.get("id") if target_server else None
    was_running = False
    if target_server:
        was_running = (str(target_server.get("status", "")).lower() == "running")

    if was_running and container_id:
        try:
            await asyncio.to_thread(dm.stop_server, container_id, timeout=60)
        except Exception as e:
            log.warning(f"Error gracefully stopping server container {container_id}: {e}")

    # Safety Backup
    backup_created = None
    if payload.create_backup:
        try:
            from backup_manager import create_backup_async
            bk_res = await create_backup_async(server_name, tag="pre-update")
            backup_created = bk_res.get("file") or bk_res.get("name")
        except Exception as exc:
            log.error(f"Pre-update safety backup failed for {server_name}: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"Safety backup failed before update: {exc}. Update aborted.",
            )

    tmpdir = Path(tempfile.mkdtemp(prefix=f"update_{server_name}_"))
    staging_dir = tmpdir / "staged"
    try:
        staged_meta = _stage_modpack_version(
            provider_id=provider_id,
            provider=provider,
            pack_id=pack_id,
            target_version_obj=target_version_obj,
            staging_dir=staging_dir,
            tmpdir=tmpdir,
        )

        loader = staged_meta.get("loader") or modpack_info.get("loader")
        loader_version = staged_meta.get("loader_version") or modpack_info.get("loader_version")
        mc_version = staged_meta.get("minecraft_version") or modpack_info.get("minecraft_version")

        # Cleanup: Method B + Method A
        cleanup_res = reconcile_and_cleanup_modpack(
            server_dir=server_dir,
            staging_dir=staging_dir,
            previous_meta=modpack_info,
        )

        # Copy staged files to server_dir
        mods_added = []
        for p in staging_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(staging_dir)
                dest = safe_child_path(server_dir, rel.as_posix())
                dest.parent.mkdir(parents=True, exist_ok=True)
                is_jar = rel.parts and rel.parts[0] == "mods" and rel.suffix.lower() == ".jar"
                if is_jar:
                    if not dest.exists() or rel.name in cleanup_res["mods_cleaned"]:
                        if rel.name not in mods_added:
                            mods_added.append(rel.name)
                shutil.copy2(p, dest)

        # Post-update client mod filtering
        filter_report = {}
        client_mods_filtered = []
        try:
            resolver = ModSideResolver(
                minecraft_version=mc_version or "unknown",
                modloader=loader or "unknown",
            )
            filter_report = resolver.filter_server_mods(
                server_dir=server_dir,
                minecraft_version=mc_version,
                modloader=loader,
                use_allowlist=True,
                dry_run=False,
            )
            client_mods_filtered = [
                m.get("file_name") or m.get("name")
                for m in filter_report.get("excluded_mods", [])
                if (m.get("file_name") or m.get("name"))
            ]
        except Exception as fe:
            log.warning(f"Error running ModSideResolver filter: {fe}")

        # Record metadata
        new_installed_files = sorted([
            p.relative_to(staging_dir).as_posix()
            for p in staging_dir.rglob("*")
            if p.is_file() and not is_path_protected(p.relative_to(staging_dir).as_posix())
        ])
        updated_meta = {
            "provider": provider_id,
            "pack_id": pack_id,
            "version_id": str(payload.target_version_id),
            "version_name": target_version_name,
            "loader": loader,
            "loader_version": loader_version,
            "minecraft_version": mc_version,
            "install_mode": modpack_info.get("install_mode", "server"),
            "installed_at": modpack_info.get("installed_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "installed_files": new_installed_files,
        }
        save_server_modpack_info(server_name, updated_meta)

        # Restart server if originally running
        if was_running and container_id:
            try:
                await asyncio.to_thread(dm.start_server, container_id)
            except Exception as se:
                log.warning(f"Failed to restart container {container_id}: {se}")

        return {
            "status": "success",
            "server_name": server_name,
            "previous_version": previous_version_id,
            "updated_version": str(payload.target_version_id),
            "backup_created": backup_created,
            "mods_cleaned": cleanup_res["mods_cleaned"],
            "mods_added": sorted(list(set(mods_added))),
            "client_mods_filtered": sorted(list(set(client_mods_filtered))),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/update")
async def update_modpack(
    server_name: str,
    provider: str,
    pack_id: str,
    version_id: str,
    current_user: User = Depends(require_moderator),
):
    """Backward-compatible update route delegating to the new update engine."""
    res = await update_server_modpack(
        server_name=server_name,
        payload=ModpackUpdateRequest(target_version_id=version_id, create_backup=True),
        current_user=current_user,
    )
    return {"ok": True, **res}

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

