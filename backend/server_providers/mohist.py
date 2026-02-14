import requests
from typing import List, Optional
from .providers import register_provider
import logging

logger = logging.getLogger(__name__)

# Mohist is a Forge+Bukkit hybrid server maintained by MohistMC.
#
# The legacy MohistMC API v2 (mohistmc.com/api/v2) is broken — download
# endpoints return filesystem paths instead of JAR content.
# The newer api.mohistmc.com provides properly built, launchable JARs
# with Main-Class: com.mohistmc.MohistMCStart in the manifest.
API_BASE = "https://api.mohistmc.com/project/mohist"


class MohistProvider:
    """Mohist hybrid server provider (Forge + Bukkit/Spigot).

    Mohist allows running both Forge mods and Bukkit/Spigot plugins on the
    same server.  Downloads come from the MohistMC API which hosts properly
    built JARs with embedded launcher.

    API: https://api.mohistmc.com/project/mohist
    """
    name = "mohist"

    def __init__(self):
        self._cached_versions: Optional[List[str]] = None

    def list_versions(self) -> List[str]:
        if self._cached_versions:
            return self._cached_versions

        try:
            logger.info("Fetching Mohist versions from api.mohistmc.com")
            resp = requests.get(f"{API_BASE}/versions", timeout=20)
            resp.raise_for_status()
            data = resp.json()  # [{"name": "1.20.1"}, ...]

            # Only include versions that actually have builds available
            all_names = [v["name"] for v in data if isinstance(v, dict) and "name" in v]
            versions = []
            for name in all_names:
                try:
                    builds_resp = requests.get(
                        f"{API_BASE}/{name}/builds", timeout=10
                    )
                    if builds_resp.status_code == 200:
                        builds = builds_resp.json()
                        if isinstance(builds, list) and len(builds) > 0:
                            versions.append(name)
                        else:
                            logger.debug(f"Mohist {name}: no builds, skipping")
                    else:
                        logger.debug(f"Mohist {name}: builds returned {builds_resp.status_code}")
                except Exception:
                    pass

            # Sort newest first
            versions.sort(
                key=lambda v: tuple(int(p) for p in v.split(".")),
                reverse=True,
            )
            self._cached_versions = versions
            logger.info(f"Found {len(versions)} Mohist versions with builds: {versions}")
            return versions
        except Exception as e:
            logger.error(f"Failed to fetch Mohist versions: {e}")
            raise ValueError(f"Could not fetch Mohist versions: {e}")

    def get_download_url(self, version: str) -> str:
        """Get download URL for the latest Mohist build of the given MC version.

        Uses api.mohistmc.com which returns complete JARs with the
        MohistMCStart launcher embedded (Main-Class in manifest).
        """
        url = f"{API_BASE}/{version}/builds/latest/download"
        # Quick HEAD check to verify the artifact exists
        try:
            head = requests.head(url, timeout=15, allow_redirects=True)
            if head.status_code == 200:
                cd = head.headers.get("content-disposition", "")
                logger.info(f"Mohist download for {version}: {url} ({cd})")
                return url
            else:
                logger.warning(f"Mohist API returned {head.status_code} for {version}")
        except Exception as e:
            logger.warning(f"Mohist API HEAD check failed for {version}: {e}")

        raise ValueError(
            f"Mohist JAR not available for Minecraft {version}. "
            f"Available versions: {self.list_versions()}"
        )


register_provider(MohistProvider())
