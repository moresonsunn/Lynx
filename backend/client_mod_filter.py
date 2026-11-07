"""
Smart Client Mod Filter System – Integriert mit dem mehrstufigen `ModSideResolver`.

Unterstützt alle 6 Kategorien (CLIENT_ONLY, SERVER_ONLY, BOTH_SIDES_REQUIRED,
OPTIONAL_CLIENT, OPTIONAL_SERVER, UNKNOWN) sowie persistentes SHA256-Caching.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from mod_side_resolver import (
    ModSideResolver,
    ModSideCategory,
    ModSideCache,
    ModAnalysisResult,
)

logger = logging.getLogger(__name__)


class ModSide(str, Enum):
    """Kompatibilitäts-Enum für API-Antworten und interne Aufrufer."""

    CLIENT_ONLY = "CLIENT_ONLY"
    SERVER_ONLY = "SERVER_ONLY"
    BOTH_SIDES_REQUIRED = "BOTH_SIDES_REQUIRED"
    OPTIONAL_CLIENT = "OPTIONAL_CLIENT"
    OPTIONAL_SERVER = "OPTIONAL_SERVER"
    UNKNOWN = "UNKNOWN"
    # Legacy-Aliase
    CLIENT = "CLIENT_ONLY"
    SERVER = "SERVER_ONLY"
    BOTH = "BOTH_SIDES_REQUIRED"


class FilterAction(str, Enum):
    DISABLED = "disabled"
    KEPT = "kept"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"
    WHITELISTED = "whitelisted"


class FilterReason(str, Enum):
    FABRIC_CLIENT_ENV = "fabric_environment_client"
    QUILT_CLIENT_ENV = "quilt_environment_client"
    FORGE_CLIENT_SIDE_ONLY = "forge_client_side_only"
    FORGE_DISPLAY_TEST = "forge_display_test_ignore"
    OFFICIAL_METADATA_CLIENT = "official_metadata_client_only"
    BYTECODE_CLIENT_ONLY = "bytecode_client_only"
    REQUIRED_DEPENDENCY = "required_by_server_mod"
    SERVER_MOD = "server_compatible"
    UNKNOWN_KEPT = "unknown_kept_for_safety"


# Process-wide re-entrant lock for allowlist file operations
_ALLOWLIST_LOCK = threading.RLock()

ALLOWLIST_JSON_FILENAME = "client-only-allow.json"
ALLOWLIST_TXT_FILENAME = "client-only-allow.txt"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomically writes content to path using a temporary file and os.replace.
    Ensures readers never observe partial writes or corrupted files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp_{os.getpid()}_{threading.get_ident()}")
    try:
        tmp_path.write_text(content, encoding=encoding)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _save_allowlist_files(
    s_dir: Path,
    entries: List[Dict[str, Any]],
    updated_at: Optional[str] = None,
) -> None:
    """
    Saves entries to client-only-allow.json and mirrors active entries to client-only-allow.txt.
    Synchronizes file modification times (mtime) so neither file appears newer to sync_allowlist.
    """
    now_str = updated_at or _utcnow_iso()
    json_path = s_dir / ALLOWLIST_JSON_FILENAME
    txt_path = s_dir / ALLOWLIST_TXT_FILENAME

    json_content = {
        "version": 1,
        "updated_at": now_str,
        "entries": entries,
    }
    json_str = json.dumps(json_content, indent=2, ensure_ascii=False) + "\n"

    active_pats = [
        e["pattern"]
        for e in entries
        if isinstance(e, dict)
        and isinstance(e.get("pattern"), str)
        and e["pattern"].strip()
        and e.get("status", "active") == "active"
    ]
    txt_str = (
        "# Client-only mod allowlist - one pattern per line\n"
        + "\n".join(active_pats)
        + ("\n" if active_pats else "")
    )

    _atomic_write_text(json_path, json_str, encoding="utf-8")
    _atomic_write_text(txt_path, txt_str, encoding="utf-8")

    try:
        j_stat = json_path.stat()
        os.utime(str(txt_path), (j_stat.st_atime, j_stat.st_mtime))
    except Exception as exc:
        logger.debug(f"Could not synchronize mtimes on allowlist files: {exc}")


def sync_allowlist(server_dir: Union[str, Path]) -> None:
    """
    Synchronizes client-only-allow.json and client-only-allow.txt.
    - If only .txt exists, upgrades entries into .json with metadata.
    - If only .json exists, generates .txt mirror.
    - If both exist, reconciles based on modification timestamps (mtime).
      Preserves entries with status != 'active' (e.g. status='disabled').
    Thread-safe via _ALLOWLIST_LOCK.
    """
    with _ALLOWLIST_LOCK:
        s_dir = Path(server_dir)
        if not s_dir.exists():
            return

        json_path = s_dir / ALLOWLIST_JSON_FILENAME
        txt_path = s_dir / ALLOWLIST_TXT_FILENAME

        json_valid = False
        json_entries: List[Dict[str, Any]] = []
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    json_entries = [
                        e for e in data["entries"]
                        if isinstance(e, dict)
                        and isinstance(e.get("pattern"), str)
                        and e["pattern"].strip()
                    ]
                    json_valid = True
                else:
                    logger.warning(f"Invalid format in {json_path}")
            except Exception as exc:
                logger.warning(f"Could not parse {json_path}: {exc}")

        txt_exists = False
        txt_lines: List[str] = []
        if txt_path.exists():
            try:
                raw_lines = txt_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
                seen: set[str] = set()
                for line in raw_lines:
                    pat = line.strip()
                    if pat and not pat.startswith("#"):
                        pat_key = pat.lower()
                        if pat_key not in seen:
                            seen.add(pat_key)
                            txt_lines.append(pat)
                txt_exists = True
            except Exception as exc:
                logger.warning(f"Could not read {txt_path}: {exc}")

        # Case 1: TXT exists, but JSON is missing or corrupt -> upgrade from TXT
        if txt_exists and (not json_path.exists() or not json_valid):
            new_entries = [
                {
                    "pattern": pat,
                    "mod_name": None,
                    "added_at": _utcnow_iso(),
                    "added_by": "legacy_txt",
                    "status": "active",
                    "notes": None,
                }
                for pat in txt_lines
            ]
            _save_allowlist_files(s_dir, new_entries)
            return

        # Case 2: JSON exists and valid, but TXT is missing -> create TXT mirror
        if json_valid and not txt_exists:
            _save_allowlist_files(s_dir, json_entries)
            return

        # Case 3: Both exist and JSON is valid -> reconcile by mtime
        if json_valid and txt_exists:
            try:
                mtime_txt = txt_path.stat().st_mtime
                mtime_json = json_path.stat().st_mtime
            except Exception:
                return

            active_json_patterns = [
                e["pattern"] for e in json_entries
                if e.get("status", "active") == "active"
            ]
            txt_norm = [p.lower() for p in txt_lines]
            json_active_norm = [p.lower() for p in active_json_patterns]

            # If normalized active patterns already match, no sync action needed
            if txt_norm == json_active_norm:
                return

            if mtime_txt > mtime_json:
                # TXT was externally modified
                entry_map: Dict[str, Dict[str, Any]] = {
                    e["pattern"].lower(): e
                    for e in json_entries
                }
                reconciled: List[Dict[str, Any]] = []
                reconciled_keys: set[str] = set()

                for pat in txt_lines:
                    pat_lower = pat.lower()
                    reconciled_keys.add(pat_lower)
                    if pat_lower in entry_map:
                        entry = dict(entry_map[pat_lower])
                        entry["pattern"] = pat
                        entry["status"] = "active"
                        reconciled.append(entry)
                    else:
                        reconciled.append({
                            "pattern": pat,
                            "mod_name": None,
                            "added_at": _utcnow_iso(),
                            "added_by": "file_sync",
                            "status": "active",
                            "notes": None,
                        })

                # Preserve all existing non-active entries from JSON
                for e in json_entries:
                    pat_lower = e["pattern"].lower()
                    if pat_lower not in reconciled_keys and e.get("status", "active") != "active":
                        reconciled.append(e)
                        reconciled_keys.add(pat_lower)

                _save_allowlist_files(s_dir, reconciled)
            else:
                # JSON is newer or in sync -> mirror active patterns to TXT
                active_pats = [
                    e["pattern"] for e in json_entries
                    if e.get("status", "active") == "active"
                ]
                txt_content = (
                    "# Client-only mod allowlist - one pattern per line\n"
                    + "\n".join(active_pats)
                    + ("\n" if active_pats else "")
                )
                _atomic_write_text(txt_path, txt_content, encoding="utf-8")
                try:
                    j_stat = json_path.stat()
                    os.utime(str(txt_path), (j_stat.st_atime, j_stat.st_mtime))
                except Exception:
                    pass


def get_allowlist_entries(server_dir: Union[str, Path]) -> List[Dict[str, Any]]:
    """
    Get all structured allowlist entries for a server.
    Synchronizes client-only-allow.json and client-only-allow.txt automatically.
    Thread-safe via _ALLOWLIST_LOCK.
    """
    with _ALLOWLIST_LOCK:
        s_dir = Path(server_dir)
        sync_allowlist(s_dir)

        json_path = s_dir / ALLOWLIST_JSON_FILENAME
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    clean_entries = []
                    for e in data["entries"]:
                        if isinstance(e, dict) and isinstance(e.get("pattern"), str) and e["pattern"].strip():
                            entry = dict(e)
                            if not entry.get("added_at"):
                                entry["added_at"] = _utcnow_iso()
                            if not entry.get("status"):
                                entry["status"] = "active"
                            clean_entries.append(entry)
                    return clean_entries
            except Exception as exc:
                logger.warning(f"Error reading {json_path}: {exc}")

        # Fallback to txt parsing if json unreadable
        txt_path = s_dir / ALLOWLIST_TXT_FILENAME
        if txt_path.exists():
            try:
                lines = [
                    l.strip()
                    for l in txt_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
                    if l.strip() and not l.strip().startswith("#")
                ]
                return [
                    {
                        "pattern": pat,
                        "mod_name": None,
                        "added_at": _utcnow_iso(),
                        "added_by": "legacy_txt",
                        "status": "active",
                        "notes": None,
                    }
                    for pat in lines
                ]
            except Exception:
                pass

        return []


def add_to_allowlist(
    server_dir: Union[str, Path],
    pattern: str,
    mod_name: Optional[str] = None,
    added_by: Optional[str] = None,
    notes: Optional[str] = None,
    status: str = "active",
) -> Dict[str, Any]:
    """
    Add or update a pattern in the allowlist.
    Preserves metadata in client-only-allow.json and syncs client-only-allow.txt.
    Thread-safe via _ALLOWLIST_LOCK.
    """
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("Pattern cannot be empty")
    if "\n" in pattern or "\r" in pattern:
        raise ValueError("Pattern cannot contain newline characters")

    with _ALLOWLIST_LOCK:
        s_dir = Path(server_dir)
        s_dir.mkdir(parents=True, exist_ok=True)
        sync_allowlist(s_dir)

        json_path = s_dir / ALLOWLIST_JSON_FILENAME
        entries: List[Dict[str, Any]] = []
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    entries = [
                        e for e in data["entries"]
                        if isinstance(e, dict)
                        and isinstance(e.get("pattern"), str)
                        and e["pattern"].strip()
                    ]
            except Exception:
                entries = []

        target_entry = None
        for e in entries:
            pat = (e.get("pattern") or "").strip().lower()
            if pat == pattern.lower():
                target_entry = e
                break

        now_str = _utcnow_iso()
        if target_entry is not None:
            target_entry["pattern"] = pattern
            if mod_name is not None:
                target_entry["mod_name"] = mod_name
            if added_by is not None:
                target_entry["added_by"] = added_by
            if notes is not None:
                target_entry["notes"] = notes
            target_entry["status"] = status or "active"
            if not target_entry.get("added_at"):
                target_entry["added_at"] = now_str
            result_entry = target_entry
        else:
            result_entry = {
                "pattern": pattern,
                "mod_name": mod_name,
                "added_at": now_str,
                "added_by": added_by,
                "status": status or "active",
                "notes": notes,
            }
            entries.append(result_entry)

        _save_allowlist_files(s_dir, entries, updated_at=now_str)
        return result_entry


def remove_from_allowlist(server_dir: Union[str, Path], pattern: str) -> bool:
    """
    Remove a pattern from the allowlist.
    Updates both client-only-allow.json and client-only-allow.txt.
    Thread-safe via _ALLOWLIST_LOCK.
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    if "\n" in pattern or "\r" in pattern:
        return False

    with _ALLOWLIST_LOCK:
        s_dir = Path(server_dir)
        sync_allowlist(s_dir)

        json_path = s_dir / ALLOWLIST_JSON_FILENAME
        txt_path = s_dir / ALLOWLIST_TXT_FILENAME
        if not json_path.exists() and not txt_path.exists():
            return False

        entries: List[Dict[str, Any]] = []
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    entries = [
                        e for e in data["entries"]
                        if isinstance(e, dict)
                        and isinstance(e.get("pattern"), str)
                        and e["pattern"].strip()
                    ]
            except Exception:
                entries = []

        remaining = [
            e for e in entries
            if (e.get("pattern") or "").strip().lower() != pattern.lower()
        ]
        if len(remaining) == len(entries):
            return False

        now_str = _utcnow_iso()
        _save_allowlist_files(s_dir, remaining, updated_at=now_str)
        return True


def match_allowlist_pattern(
    pattern: str,
    filename: str,
    mod_id: Optional[str] = None,
) -> bool:
    """
    Evaluates whether a candidate mod filename or mod_id matches an allowlist pattern.

    Matching hierarchy:
    1. Direct case-insensitive equality:
       - Filename exact match (e.g. 'mod-(test)+[1].jar')
       - Stem match if pattern does not end in '.jar' (e.g. 'appleskin' matches 'appleskin.jar')
       - Mod ID exact match (e.g. 'sodium' matches 'sodium')
    2. Standard fnmatch globs (*, ?, [0-9] character classes).
    3. Literal bracket fallback ([ -> [[]):
       Matches patterns with literal brackets and wildcards (e.g. '[1.20.1]appleskin*').
    4. Safe prefix matching for non-glob patterns without .jar extension:
       Only matches stem followed by '-' or '_'. Prevents '.jar.bak' or unrelated mods ('mod' matching 'modmenu').
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return False
    if not filename or not isinstance(filename, str):
        return False

    pat = pattern.strip().lower()
    fn_name = Path(filename).name.lower()
    stem = Path(filename).stem.lower()
    mid = mod_id.strip().lower() if (mod_id and isinstance(mod_id, str) and mod_id.strip()) else None

    pat_ends_with_jar = pat.endswith(".jar")

    # 1. Direct case-insensitive exact matching
    if fn_name == pat:
        return True
    if not pat_ends_with_jar and stem == pat:
        return True
    if mid and mid == pat:
        return True

    # 2. Standard fnmatch (supports *, ?, and character classes like [0-9])
    if fnmatch.fnmatchcase(fn_name, pat):
        return True
    if not pat_ends_with_jar and fnmatch.fnmatchcase(stem, pat):
        return True
    if mid and fnmatch.fnmatchcase(mid, pat):
        return True

    # 3. Literal bracket fallback for fnmatch (e.g. [1.20.1]appleskin*)
    if "[" in pat:
        escaped_pat = pat.replace("[", "[[]")
        if fnmatch.fnmatchcase(fn_name, escaped_pat):
            return True
        if not pat_ends_with_jar and fnmatch.fnmatchcase(stem, escaped_pat):
            return True
        if mid and fnmatch.fnmatchcase(mid, escaped_pat):
            return True

    # 4. Safe prefix matching for non-glob patterns without .jar extension
    if not any(c in pat for c in ("*", "?", "[", "]")):
        if not pat_ends_with_jar:
            if stem.startswith(pat + "-") or stem.startswith(pat + "_"):
                return True

    return False


def is_mod_allowlisted(
    server_dir: Union[str, Path],
    filename: str,
    mod_id: Optional[str] = None,
) -> bool:
    """
    Checks whether a mod jar or mod_id is allowlisted for the server.
    Supports case-insensitive fnmatch wildcards (*, ?), bracketed filenames,
    exact filename, stem, and mod_id matches.
    """
    entries = get_allowlist_entries(server_dir)
    active_entries = [
        e for e in entries
        if isinstance(e, dict)
        and isinstance(e.get("pattern"), str)
        and e["pattern"].strip()
        and e.get("status", "active") == "active"
    ]
    if not active_entries:
        return False

    for e in active_entries:
        pat = e["pattern"]
        if match_allowlist_pattern(pat, filename=filename, mod_id=mod_id):
            return True

    return False


class ClientModFilter:
    """
    Analysiert und filtert Mods über den eigenständigen `ModSideResolver`.
    """

    def __init__(self, server_dir: Path, minecraft_version: str = "unknown", modloader: str = "unknown"):
        self.server_dir = Path(server_dir)
        self.mods_dir = self.server_dir / "mods"
        self.disabled_dir = self.server_dir / "mods-disabled-client"
        self.resolver = ModSideResolver(
            minecraft_version=minecraft_version,
            modloader=modloader,
        )

    def scan_and_filter(
        self,
        dry_run: bool = False,
        quarantine_unknown: bool = False,
        use_allowlist: bool = True,
        use_Allowlist: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Analysiert das gesamte Modpack über `ModSideResolver` und deaktiviert ausschließlich
        verifizierte `CLIENT_ONLY`-Mods, die nicht auf der Allowlist stehen.
        WICHTIG: UNKNOWN wird niemals automatisch als CLIENT_ONLY interpretiert!
        """
        if use_Allowlist is not None:
            use_allowlist = use_Allowlist

        start_time = datetime.now()
        analysis = self.resolver.resolve_modpack(
            mods_dir=self.mods_dir,
            pack_dir=self.server_dir,
        )

        decisions: List[Dict[str, Any]] = []
        disabled_count = 0
        kept_count = 0
        whitelisted_count = 0
        quarantined_count = 0
        errors: List[str] = []

        if not dry_run and analysis["client_only_mods"]:
            self.disabled_dir.mkdir(parents=True, exist_ok=True)

        for mod_dict in analysis["results"]:
            side_val = mod_dict["side"]
            is_client_only = side_val == ModSideCategory.CLIENT_ONLY.value
            src_path = Path(mod_dict["file_path"])

            is_allowlisted = False
            if use_allowlist and is_client_only:
                is_allowlisted = is_mod_allowlisted(
                    self.server_dir,
                    filename=src_path.name,
                    mod_id=mod_dict.get("mod_id"),
                )

            action = FilterAction.KEPT.value
            new_path: Optional[str] = None

            if is_client_only and not is_allowlisted:
                disabled_count += 1
                action = FilterAction.DISABLED.value
                if not dry_run and src_path.exists():
                    dst = self.disabled_dir / src_path.name
                    try:
                        if dst.exists():
                            dst.unlink()
                        shutil.move(str(src_path), str(dst))
                        new_path = str(dst)
                    except Exception as exc:
                        errors.append(f"Fehler beim Verschieben von {src_path.name}: {exc}")
            elif is_client_only and is_allowlisted:
                whitelisted_count += 1
                kept_count += 1
                action = FilterAction.WHITELISTED.value
            else:
                kept_count += 1

            decisions.append(
                {
                    "mod_path": mod_dict["file_path"],
                    "file_name": mod_dict["file_name"],
                    "mod_id": mod_dict["mod_id"],
                    "mod_name": mod_dict["mod_name"],
                    "version": mod_dict["mod_version"],
                    "loader": mod_dict["modloader"],
                    "side": side_val,
                    "classification": side_val,
                    "confidence": mod_dict["confidence"],
                    "confidence_level": mod_dict["confidence_level"],
                    "keep_on_server": True if is_allowlisted else mod_dict["keep_on_server"],
                    "action": action,
                    "whitelisted": is_allowlisted,
                    "reason": "whitelisted" if is_allowlisted else ("client_only" if is_client_only else "server_compatible"),
                    "reason_detail": "Allowlisted: preserved on server" if is_allowlisted else mod_dict["primary_reason"],
                    "detection_sources": mod_dict["detection_sources"],
                    "evidences": mod_dict["evidences"],
                    "dependencies": [d["mod_id"] for d in mod_dict.get("dependencies", [])],
                    "required_by": mod_dict.get("required_by_server_mods", []),
                    "conflicts": mod_dict.get("conflicts", []),
                    "from_cache": mod_dict.get("from_cache", False),
                    "new_path": new_path,
                }
            )

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return {
            "server_dir": str(self.server_dir),
            "timestamp": start_time.isoformat(),
            "total_mods": analysis["total_mods"],
            "disabled_count": disabled_count,
            "kept_count": kept_count,
            "whitelisted_count": whitelisted_count,
            "quarantined_count": quarantined_count,
            "decisions": decisions,
            "conflicts": analysis.get("conflicts", []),
            "errors": errors,
            "scan_duration_ms": duration_ms,
        }

    def restore_mod(self, mod_filename: str) -> bool:
        disabled_path = self.disabled_dir / mod_filename
        if disabled_path.exists():
            dst = self.mods_dir / mod_filename
            shutil.move(str(disabled_path), str(dst))
            return True
        return False

    def restore_all(self) -> int:
        count = 0
        if self.disabled_dir.exists():
            for jar in self.disabled_dir.glob("*.jar"):
                dst = self.mods_dir / jar.name
                shutil.move(str(jar), str(dst))
                count += 1
        return count


def filter_client_mods(
    server_dir: Path,
    dry_run: bool = False,
    quarantine_unknown: bool = False,
    use_api: bool = True,
    cf_api_key: Optional[str] = None,
    min_confidence: float = 0.6,
    push_event: Optional[Any] = None,
    use_allowlist: bool = True,
) -> Dict[str, Any]:
    filter_system = ClientModFilter(Path(server_dir))
    res = filter_system.scan_and_filter(
        dry_run=dry_run,
        quarantine_unknown=quarantine_unknown,
        use_allowlist=use_allowlist,
    )
    res["client_only_moved"] = res.get("disabled_count", 0)
    res["whitelisted_count"] = res.get("whitelisted_count", 0)
    res["mods"] = [
        {
            "filename": d["file_name"],
            "mod_id": d["mod_id"],
            "name": d["mod_name"],
            "version": d["version"],
            "loader": d["loader"],
            "side": d["side"],
            "classification": d["classification"],
            "is_client_only": d["side"] == ModSideCategory.CLIENT_ONLY.value,
            "whitelisted": d.get("whitelisted", False),
            "confidence": d["confidence"],
            "confidence_level": d["confidence_level"],
            "detection_method": ", ".join(d.get("detection_sources", [])) or "mod_side_resolver",
            "reason": d["reason_detail"],
            "action": d["action"],
            "evidences": d.get("evidences", []),
            "dependencies": d.get("dependencies", []),
            "required_by": d.get("required_by", []),
            "conflicts": d.get("conflicts", []),
            "from_cache": d.get("from_cache", False),
        }
        for d in res.get("decisions", [])
    ]
    return res


def analyze_mods_directory(
    server_dir: Path,
    use_api: bool = True,
    cf_api_key: Optional[str] = None,
) -> List[ModAnalysisResult]:
    resolver = ModSideResolver(enable_network=use_api)
    s_dir = Path(server_dir)
    mods_dir = s_dir / "mods"
    if not mods_dir.exists():
        return []
    out: List[ModAnalysisResult] = []
    pack_res = resolver.resolve_modpack(mods_dir=mods_dir, pack_dir=s_dir)
    for r_dict in pack_res.get("results", []):
        out.append(resolver._dict_to_result(r_dict, Path(r_dict["file_path"]), from_cache=r_dict.get("from_cache", False)))
    return out


def graded_compat_report(
    server_dir: Path,
    loader: Optional[str] = None,
    mc_version: Optional[str] = None,
    use_api: bool = True,
    cf_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    s_dir = Path(server_dir)
    resolver = ModSideResolver(
        enable_network=use_api,
        minecraft_version=mc_version or "unknown",
        modloader=loader or "unknown",
    )
    pack_res = resolver.resolve_modpack(
        mods_dir=s_dir / "mods",
        pack_dir=s_dir,
        minecraft_version=mc_version,
        modloader=loader,
    )
    validation = resolver.validate_server_pack(
        s_dir,
        expected_minecraft_version=mc_version,
        expected_modloader=loader,
    )
    return {
        "server_dir": str(s_dir),
        "minecraft_version": mc_version or "unknown",
        "modloader": loader or "unknown",
        "total_mods": pack_res["total_mods"],
        "client_only_count": pack_res["client_only_count"],
        "server_mods_kept_count": pack_res["server_mods_kept_count"],
        "mods": pack_res["results"],
        "conflicts": pack_res["conflicts"],
        "validation": validation,
    }


def analyze_single_mod(jar_path: Path) -> Dict[str, Any]:
    resolver = ModSideResolver()
    res = resolver.analyze_mod(Path(jar_path))
    return res.to_dict()


def analyze_mod(jar_path: Path) -> ModAnalysisResult:
    resolver = ModSideResolver()
    return resolver.analyze_mod(Path(jar_path))


def disable_mod(server_dir: Path, filename: str) -> bool:
    s_dir = Path(server_dir)
    src = s_dir / "mods" / filename
    if not src.exists():
        return False
    dst_dir = s_dir / "mods-disabled-client"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst_dir / filename))
    return True


def restore_mod(server_dir: Path, filename: str) -> bool:
    s_dir = Path(server_dir)
    src = s_dir / "mods-disabled-client" / filename
    if not src.exists():
        return False
    dst_dir = s_dir / "mods"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst_dir / filename))
    return True


def list_disabled_mods(server_dir: Path) -> List[Dict[str, Any]]:
    s_dir = Path(server_dir)
    disabled_dir = s_dir / "mods-disabled-client"
    if not disabled_dir.exists():
        return []
    resolver = ModSideResolver(enable_network=False)
    items: List[Dict[str, Any]] = []
    for jar in sorted(disabled_dir.glob("*.jar"), key=lambda p: p.name.lower()):
        res = resolver.analyze_mod(jar)
        items.append(
            {
                "filename": jar.name,
                "mod_id": res.mod_id,
                "name": res.mod_name,
                "version": res.mod_version,
                "side": res.side.value,
                "reason": res.primary_reason,
                "size": jar.stat().st_size,
            }
        )
    return items


def add_to_whitelist(server_dir: Path, pattern: str) -> bool:
    try:
        add_to_allowlist(server_dir, pattern)
        return True
    except Exception:
        return False


def remove_from_whitelist(server_dir: Path, pattern: str) -> bool:
    try:
        return remove_from_allowlist(server_dir, pattern)
    except Exception:
        return False
