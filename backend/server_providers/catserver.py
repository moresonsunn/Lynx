import requests
import re
from typing import List, Optional, Dict
from .providers import register_provider
import logging

logger = logging.getLogger(__name__)

# CatServer is a Forge+Bukkit hybrid — available for 1.12.2, 1.16.5, 1.18.2
# Downloads via GitHub releases.
# Release tags are date-based (e.g. "25.02.04") but the release *name*
# contains the MC version in parentheses: "25.02.24 (1.12.2)".
GITHUB_API = "https://api.github.com/repos/Luohuayu/CatServer/releases"


class CatServerProvider:
    """CatServer hybrid server provider (Forge + Bukkit/Spigot).

    CatServer is a high-performance Forge+Bukkit+Spigot hybrid server for
    Minecraft 1.12.2, 1.16.5 and 1.18.2.

    Downloads come from GitHub releases.
    Repo: https://github.com/Luohuayu/CatServer
    """
    name = "catserver"

    def __init__(self):
        self._cached_releases: Optional[List[dict]] = None
        self._version_release_map: Optional[Dict[str, dict]] = None

    def _fetch_releases(self) -> List[dict]:
        if self._cached_releases is not None:
            return self._cached_releases
        try:
            logger.info("Fetching CatServer releases from GitHub")
            resp = requests.get(
                GITHUB_API,
                timeout=20,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            resp.raise_for_status()
            releases = resp.json()
            self._cached_releases = releases
            return releases
        except Exception as e:
            logger.error(f"Failed to fetch CatServer releases: {e}")
            self._cached_releases = []
            return []

    def _build_version_map(self) -> Dict[str, dict]:
        """Map MC version -> best release (latest first)."""
        if self._version_release_map is not None:
            return self._version_release_map

        releases = self._fetch_releases()
        version_map: Dict[str, dict] = {}

        for release in releases:
            name = release.get("name", "")
            # Parse MC version from release name like "25.02.24 (1.12.2)"
            m = re.search(r"\((\d+\.\d+(?:\.\d+)?)\)", name)
            if m:
                mc_version = m.group(1)
            else:
                # Fallback: try to find MC version in asset filenames
                mc_version = None
                for asset in release.get("assets", []):
                    a_name = asset.get("name", "")
                    vm = re.search(r"(\d+\.\d+\.\d+)", a_name)
                    if vm:
                        mc_version = vm.group(1)
                        break
                if not mc_version:
                    continue

            # Only keep the first (latest) release per MC version
            if mc_version not in version_map:
                version_map[mc_version] = release

        self._version_release_map = version_map
        return version_map

    def list_versions(self) -> List[str]:
        """Return supported Minecraft versions for CatServer."""
        version_map = self._build_version_map()
        # Sort newest first
        versions = sorted(
            version_map.keys(),
            key=lambda v: tuple(int(p) for p in v.split(".")),
            reverse=True,
        )
        logger.info(f"CatServer versions: {versions}")
        return versions

    def get_download_url(self, version: str) -> str:
        """Get download URL for CatServer for the given MC version."""
        version_map = self._build_version_map()
        release = version_map.get(version)
        if not release:
            raise ValueError(
                f"CatServer does not support Minecraft {version}. "
                f"Supported: {self.list_versions()}"
            )

        # Find the JAR asset — accept both "server" and "universal" jars
        for asset in release.get("assets", []):
            a_name = asset.get("name", "").lower()
            if a_name.endswith(".jar") and ("server" in a_name or "universal" in a_name):
                url = asset.get("browser_download_url")
                if url:
                    logger.info(f"CatServer download for {version}: {url}")
                    return url

        # Last resort: pick any .jar asset from the release
        for asset in release.get("assets", []):
            a_name = asset.get("name", "").lower()
            if a_name.endswith(".jar"):
                url = asset.get("browser_download_url")
                if url:
                    logger.info(f"CatServer fallback JAR for {version}: {url}")
                    return url

        raise ValueError(f"No suitable JAR asset found in CatServer release for {version}")


register_provider(CatServerProvider())
