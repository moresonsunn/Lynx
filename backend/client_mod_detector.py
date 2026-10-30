"""
Client Mod Detector – Delegiert vollständig an den mehrstufigen `ModSideResolver`.

Erkennt und entfernt ausschließlich technisch verifizierte CLIENT_ONLY-Mods aus Server-Installationen
(ohne naive Dateinamen-Heuristiken und ohne Fehlinterpretation von TOML-Kommentaren).
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from mod_side_resolver import (
    ModSideResolver,
    ModSideCategory,
    inspect_jar_metadata,
)

logger = logging.getLogger(__name__)


class ClientModDetector:
    """Erkennt Client-only-Mods über den mehrstufigen ModSideResolver."""

    def __init__(self, server_dir: Path, minecraft_version: str = "unknown", modloader: str = "unknown"):
        self.server_dir = Path(server_dir)
        self.mods_dir = self.server_dir / "mods"
        self.disabled_dir = self.server_dir / "mods-disabled-client"
        self.resolver = ModSideResolver(
            minecraft_version=minecraft_version,
            modloader=modloader,
        )

    def scan_and_remove_client_mods(
        self,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[int, int, Any], None]] = None,
    ) -> Dict[str, Any]:
        """
        Analysiert alle Mods im `mods/`-Verzeichnis mit `ModSideResolver` und verschiebt
        ausschließlich verifizierte `CLIENT_ONLY`-Mods nach `mods-disabled-client/`.
        """
        if not self.mods_dir.exists():
            return {
                "detected_client_mods": [],
                "moved_count": 0,
                "moved_mods": [],
                "excluded_mods": [],
                "kept_mods": [],
                "errors": [],
                "total_mods": 0,
                "server_mods_remaining": 0,
            }

        report = self.resolver.filter_server_mods(
            server_dir=self.server_dir,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )

        excluded = report.get("excluded_mods", [])
        detected_list = [
            {
                "file": m.get("file_name", ""),
                "name": m.get("mod_name", m.get("mod_id", "")),
                "mod_id": m.get("mod_id", ""),
                "version": m.get("mod_version", "unknown"),
                "side": m.get("side", ModSideCategory.CLIENT_ONLY.value),
                "confidence": m.get("confidence", 0.9),
                "reason": m.get("reason") or m.get("primary_reason", ""),
                "detection_sources": m.get("detection_sources", []),
            }
            for m in excluded
        ]

        return {
            "detected_client_mods": detected_list,
            "moved_count": report.get("moved_count", 0),
            "moved_mods": [m.get("file_name", "") for m in excluded] if not dry_run else [],
            "excluded_mods": excluded,
            "kept_mods": report.get("kept_mods", []),
            "conflicts": report.get("conflicts", []),
            "errors": report.get("errors", []),
            "total_mods": report.get("total_mods", 0),
            "client_only_count": report.get("client_only_count", 0),
            "server_mods_remaining": report.get("server_mods_kept_count", 0),
        }

    def analyze_mod_jar(self, jar_path: Path) -> Tuple[bool, str, str]:
        """
        Analysiert eine einzelne JAR-Datei über ModSideResolver.
        Gibt `(is_client_only, reason, mod_name)` zurück.
        """
        res = self.resolver.analyze_mod(jar_path)
        return (res.side == ModSideCategory.CLIENT_ONLY, res.primary_reason, res.mod_name)

    def _extract_mod_info(self, jar_path: Path) -> Dict[str, Any]:
        info = inspect_jar_metadata(jar_path)
        return {
            "id": info.get("mod_id", ""),
            "name": info.get("mod_name", ""),
            "description": "",
            "side": info.get("mod_side_field") or "",
            "environment": info.get("fabric_environment") or info.get("quilt_environment") or "",
        }


def load_client_only_config() -> Dict[str, Any]:
    """Kompatibilitäts-Helper für ältere Aufrufer."""
    return {"resolver": "ModSideResolver", "version": "2.1.0"}


def is_client_only_jar(jar_path: Path) -> Tuple[bool, str]:
    """Prüft über ModSideResolver, ob eine einzelne JAR eindeutig CLIENT_ONLY ist."""
    resolver = ModSideResolver(enable_network=False)
    res = resolver.analyze_mod(Path(jar_path))
    return (res.side == ModSideCategory.CLIENT_ONLY, res.primary_reason)


def detect_client_only_mods(server_dir: Path) -> List[Dict[str, Any]]:
    """Erkennt alle CLIENT_ONLY-Mods im Server-Verzeichnis (Dry-Run)."""
    detector = ClientModDetector(Path(server_dir))
    res = detector.scan_and_remove_client_mods(dry_run=True)
    return res.get("detected_client_mods", [])


def remove_client_only_mods(server_dir: Path) -> Dict[str, Any]:
    """Entfernt alle eindeutig erkannten CLIENT_ONLY-Mods aus dem Server-Verzeichnis."""
    detector = ClientModDetector(Path(server_dir))
    return detector.scan_and_remove_client_mods(dry_run=False)


def process_client_pack(
    server_dir: Path,
    dry_run: bool = False,
    minecraft_version: str = "unknown",
    modloader: str = "unknown",
    progress_callback: Optional[Callable[[int, int, Any], None]] = None,
    push_event: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    Verarbeitet ein Modpack für den Dedicated Server über `ModSideResolver`:
      1. Analysiert alle Mods mehrstufig (Metadaten, JAR, Bytecode, Abhängigkeitsgraph)
      2. Verschiebt ausschließlich `CLIENT_ONLY`-Mods nach `mods-disabled-client/`
      3. Behält alle `SERVER_ONLY`, `BOTH_SIDES_REQUIRED`, `OPTIONAL_CLIENT`, `OPTIONAL_SERVER` und `UNKNOWN` Mods
    """
    detector = ClientModDetector(
        server_dir=server_dir,
        minecraft_version=minecraft_version,
        modloader=modloader,
    )

    def _combined_progress(idx: int, total: int, mod_res: Any) -> None:
        if progress_callback:
            progress_callback(idx, total, mod_res)
        if push_event and (idx == total or idx % 10 == 0 or idx == 1):
            pct = 52 + int((idx / max(total, 1)) * 10)
            push_event(
                {
                    "type": "progress",
                    "step": "mod_analysis",
                    "message": f"Mods analysiert: {idx} / {total}",
                    "progress": pct,
                    "mods_analyzed": idx,
                    "total_mods": total,
                }
            )

    out = detector.scan_and_remove_client_mods(
        dry_run=dry_run,
        progress_callback=_combined_progress,
    )
    out["removed"] = out.get("moved_count", 0)
    return out
