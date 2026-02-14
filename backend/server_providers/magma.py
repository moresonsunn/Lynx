import requests
from typing import List, Optional
from .providers import register_provider
import logging

logger = logging.getLogger(__name__)

# Magma Foundation API - Magma is a NeoForge+Bukkit hybrid server
API_BASE = "https://magmafoundation.org/api"


class MagmaProvider:
    """Magma hybrid server provider (NeoForge + Bukkit).

    Magma combines NeoForge mods and Bukkit plugins into one server.
    Downloads are served through the Magma Foundation API.

    API docs: https://magmafoundation.org/api-docs
    """
    name = "magma"

    def __init__(self):
        self._cached_versions: Optional[List[dict]] = None

    def _fetch_all_versions(self) -> List[dict]:
        if self._cached_versions:
            return self._cached_versions

        try:
            logger.info("Fetching Magma versions from API")
            resp = requests.get(f"{API_BASE}/versions", timeout=20)
            resp.raise_for_status()
            data = resp.json()
            versions = data.get("versions", [])
            self._cached_versions = versions
            logger.info(f"Found {len(versions)} Magma versions")
            return versions
        except Exception as e:
            logger.error(f"Failed to fetch Magma versions: {e}")
            raise ValueError(f"Could not fetch Magma versions: {e}")

    def list_versions(self) -> List[str]:
        """Get unique Minecraft versions supported by Magma."""
        all_versions = self._fetch_all_versions()
        # Extract unique MC versions
        mc_versions = []
        seen = set()
        for v in all_versions:
            mc = v.get("minecraftVersion", "")
            if mc and mc not in seen:
                seen.add(mc)
                mc_versions.append(mc)
        return mc_versions

    def get_download_url(self, version: str) -> str:
        """Get download URL for the latest Magma build matching the given MC version."""
        all_versions = self._fetch_all_versions()
        # Find latest build for this MC version (prefer launcher jar)
        for v in all_versions:
            mc = v.get("minecraftVersion", "")
            if mc == version:
                launcher_url = v.get("launcherUrl")
                installer_url = v.get("installerUrl")
                url = launcher_url or installer_url
                if url:
                    logger.info(f"Magma download URL for {version}: {url}")
                    return url
        raise ValueError(f"No Magma builds found for Minecraft version {version}")


register_provider(MagmaProvider())
