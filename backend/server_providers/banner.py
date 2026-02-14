import requests
from typing import List, Optional
from .providers import register_provider
import logging

logger = logging.getLogger(__name__)

# Banner is a Fabric+Bukkit hybrid server maintained by MohistMC.
#
# The legacy MohistMC API v2 is broken. The newer api.mohistmc.com provides
# properly built JARs with Main-Class: com.mohistmc.banner.BannerLauncher.
API_BASE = "https://api.mohistmc.com/project/banner"


class BannerProvider:
    """Banner hybrid server provider (Fabric + Bukkit/Spigot).

    Banner is maintained by MohistMC and allows running both Fabric mods
    and Bukkit/Spigot plugins on the same server.

    API: https://api.mohistmc.com/project/banner
    """
    name = "banner"

    def __init__(self):
        self._cached_versions: Optional[List[str]] = None

    def list_versions(self) -> List[str]:
        if self._cached_versions:
            return self._cached_versions

        try:
            logger.info("Fetching Banner versions from api.mohistmc.com")
            resp = requests.get(f"{API_BASE}/versions", timeout=20)
            resp.raise_for_status()
            data = resp.json()  # [{"name": "1.21.1"}, ...]

            # Only include versions that have builds available
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
                            logger.debug(f"Banner {name}: no builds, skipping")
                except Exception:
                    pass

            versions.sort(
                key=lambda v: tuple(int(p) for p in v.split(".")),
                reverse=True,
            )
            self._cached_versions = versions
            logger.info(f"Found {len(versions)} Banner versions with builds: {versions}")
            return versions
        except Exception as e:
            logger.error(f"Failed to fetch Banner versions: {e}")
            raise ValueError(f"Could not fetch Banner versions: {e}")

    def get_download_url(self, version: str) -> str:
        """Get download URL for the latest Banner build.

        Uses api.mohistmc.com which returns complete JARs with the
        BannerLauncher embedded (Main-Class in manifest).
        """
        url = f"{API_BASE}/{version}/builds/latest/download"
        try:
            head = requests.head(url, timeout=15, allow_redirects=True)
            if head.status_code == 200:
                cd = head.headers.get("content-disposition", "")
                logger.info(f"Banner download for {version}: {url} ({cd})")
                return url
            else:
                logger.warning(f"Banner API returned {head.status_code} for {version}")
        except Exception as e:
            logger.warning(f"Banner API HEAD check failed for {version}: {e}")

        raise ValueError(
            f"Banner JAR not available for Minecraft {version}. "
            f"Available versions: {self.list_versions()}"
        )


register_provider(BannerProvider())
