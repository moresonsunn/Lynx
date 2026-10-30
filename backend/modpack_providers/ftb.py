from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from .base import PackDetail, PackSummary, PackVersion

logger = logging.getLogger(__name__)

FTB_API_BASE = "https://api.feed-the-beast.com/v1/modpacks/public/modpack"


class FTBProvider:
    """Provider für Feed The Beast (FTB) Modpacks inkl. Datei- und Side-Metadaten."""

    id = "ftb"
    name = "Feed The Beast"

    def search(
        self,
        query: str,
        *,
        mc_version: Optional[str] = None,
        loader: Optional[str] = None,
        limit: int = 24,
        offset: int = 0,
    ) -> List[PackSummary]:
        term = (query or "").strip()
        try:
            if term:
                r = requests.get(
                    f"{FTB_API_BASE}/search/{min(max(limit, 1), 50)}",
                    params={"term": term},
                    timeout=10,
                )
            else:
                r = requests.get(
                    f"{FTB_API_BASE}/popular/installs/{min(max(limit, 1), 50)}",
                    timeout=10,
                )
            r.raise_for_status()
            data = r.json()
            pack_ids = data.get("packs", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.debug(f"FTB search failed: {exc}")
            return []

        results: List[PackSummary] = []
        for pid in pack_ids[offset : offset + limit]:
            try:
                detail = self.get_pack(str(pid))
                if not detail or detail.get("status") == "error":
                    continue
                if mc_version and mc_version not in detail.get("game_versions", []):
                    continue
                if loader and loader.lower() not in [l.lower() for l in detail.get("loaders", [])]:
                    continue
                results.append(
                    {
                        "id": str(detail.get("id") or pid),
                        "slug": detail.get("slug") or str(pid),
                        "name": detail.get("name") or f"FTB Pack #{pid}",
                        "description": detail.get("description") or "",
                        "downloads": detail.get("installs", 0),
                        "updated": detail.get("updated"),
                        "icon_url": detail.get("icon_url"),
                        "categories": detail.get("categories", []),
                        "provider": self.id,
                    }
                )
            except Exception:
                continue
        return results

    def get_pack(self, pack_id: str) -> PackDetail:
        r = requests.get(f"{FTB_API_BASE}/{pack_id}", timeout=10)
        r.raise_for_status()
        p = r.json()

        icon_url = None
        for art in p.get("art", []) or []:
            if isinstance(art, dict) and art.get("type") == "square":
                icon_url = art.get("url")
                break
        if not icon_url and p.get("art"):
            first_art = p["art"][0]
            if isinstance(first_art, dict):
                icon_url = first_art.get("url")

        versions_raw = p.get("versions", []) or []
        game_versions: List[str] = []
        loaders: List[str] = []
        for v in versions_raw:
            if not isinstance(v, dict):
                continue
            for tgt in v.get("targets", []) or []:
                if not isinstance(tgt, dict):
                    continue
                t_type = str(tgt.get("type") or "").lower()
                t_name = str(tgt.get("name") or "").lower()
                t_ver = str(tgt.get("version") or "")
                if t_type == "game" and t_ver and t_ver not in game_versions:
                    game_versions.append(t_ver)
                elif t_type == "modloader" and t_name and t_name not in loaders:
                    loaders.append(t_name)

        return {
            "id": str(p.get("id") or pack_id),
            "slug": str(p.get("slug") or pack_id),
            "name": p.get("name") or f"FTB Pack {pack_id}",
            "description": p.get("synopsis") or p.get("description") or "",
            "icon_url": icon_url,
            "categories": [t.get("name") for t in (p.get("tags") or []) if isinstance(t, dict) and t.get("name")],
            "loaders": loaders,
            "game_versions": game_versions,
            "installs": p.get("installs", 0),
            "updated": p.get("updated"),
            "provider": self.id,
        }

    def get_versions(self, pack_id: str, *, limit: int = 50) -> List[PackVersion]:
        r = requests.get(f"{FTB_API_BASE}/{pack_id}", timeout=10)
        r.raise_for_status()
        p = r.json()
        versions_raw = sorted(
            p.get("versions", []) or [],
            key=lambda x: x.get("id", 0) if isinstance(x, dict) else 0,
            reverse=True,
        )

        versions: List[PackVersion] = []
        for v in versions_raw[:limit]:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id"))
            game_versions: List[str] = []
            loaders: List[str] = []
            for tgt in v.get("targets", []) or []:
                if isinstance(tgt, dict):
                    if tgt.get("type") == "game" and tgt.get("version"):
                        game_versions.append(str(tgt["version"]))
                    elif tgt.get("type") == "modloader" and tgt.get("name"):
                        loaders.append(str(tgt["name"]).lower())

            versions.append(
                {
                    "id": vid,
                    "name": v.get("name") or vid,
                    "version_number": v.get("name") or vid,
                    "game_versions": game_versions,
                    "loaders": loaders,
                    "date_published": v.get("updated"),
                    "files": [],
                }
            )
        return versions

    def get_version_manifest(self, pack_id: str, version_id: str) -> Dict[str, Any]:
        """Ruft das vollständige FTB-Versionsmanifest inkl. aller Dateien & `clientonly`-Flags ab."""
        r = requests.get(f"{FTB_API_BASE}/{pack_id}/{version_id}", timeout=15)
        r.raise_for_status()
        return r.json()

