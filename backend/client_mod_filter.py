"""
Smart Client Mod Filter System – Integriert mit dem mehrstufigen `ModSideResolver`.

Unterstützt alle 6 Kategorien (CLIENT_ONLY, SERVER_ONLY, BOTH_SIDES_REQUIRED,
OPTIONAL_CLIENT, OPTIONAL_SERVER, UNKNOWN) sowie persistentes SHA256-Caching.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        use_Allowlist: bool = True,
    ) -> Dict[str, Any]:
        """
        Analysiert das gesamte Modpack über `ModSideResolver` und deaktiviert ausschließlich
        verifizierte `CLIENT_ONLY`-Mods.
        WICHTIG: UNKNOWN wird niemals automatisch als CLIENT_ONLY interpretiert!
        """
        start_time = datetime.now()
        analysis = self.resolver.resolve_modpack(
            mods_dir=self.mods_dir,
            pack_dir=self.server_dir,
        )

        decisions: List[Dict[str, Any]] = []
        disabled_count = 0
        kept_count = 0
        quarantined_count = 0
        errors: List[str] = []

        if not dry_run and analysis["client_only_mods"]:
            self.disabled_dir.mkdir(parents=True, exist_ok=True)

        for mod_dict in analysis["results"]:
            side_val = mod_dict["side"]
            is_client_only = side_val == ModSideCategory.CLIENT_ONLY.value
            src_path = Path(mod_dict["file_path"])

            action = FilterAction.KEPT.value
            new_path: Optional[str] = None

            if is_client_only:
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
                    "keep_on_server": mod_dict["keep_on_server"],
                    "action": action,
                    "reason": "client_only" if is_client_only else "server_compatible",
                    "reason_detail": mod_dict["primary_reason"],
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
) -> Dict[str, Any]:
    filter_system = ClientModFilter(Path(server_dir))
    res = filter_system.scan_and_filter(
        dry_run=dry_run,
        quarantine_unknown=quarantine_unknown,
    )
    res["client_only_moved"] = res.get("disabled_count", 0)
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
        allow_file = Path(server_dir) / "client-only-allow.txt"
        existing = []
        if allow_file.exists():
            existing = [l.strip() for l in allow_file.read_text(encoding="utf-8", errors="ignore").splitlines()]
        if pattern.strip() not in existing:
            with open(allow_file, "a", encoding="utf-8") as f:
                f.write(f"{pattern.strip()}\n")
        return True
    except Exception:
        return False


def remove_from_whitelist(server_dir: Path, pattern: str) -> bool:
    try:
        allow_file = Path(server_dir) / "client-only-allow.txt"
        if not allow_file.exists():
            return False
        lines = allow_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = [l for l in lines if l.strip() != pattern.strip()]
        if len(new_lines) == len(lines):
            return False
        allow_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False
