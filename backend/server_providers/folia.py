import logging
from typing import List, Optional
import requests
from .providers import register_provider

logger = logging.getLogger(__name__)

# Folia uses PaperMC Fill v3 — https://fill.papermc.io/v3/projects/folia
API_BASE = "https://fill.papermc.io/v3/projects/folia"
USER_AGENT = "Lynx/1.0 (+https://github.com/moresonsun/Lynx)"
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


class FoliaProvider:
    name = "folia"

    def list_versions(self) -> List[str]:
        """List all supported Folia Minecraft versions from PaperMC Fill v3 API."""
        try:
            resp = requests.get(API_BASE, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            versions = data.get("versions", {})
            if isinstance(versions, dict):
                flat: List[str] = []
                for group in versions.values():
                    if isinstance(group, list):
                        flat.extend(group)
                    elif isinstance(group, str):
                        flat.append(group)
                return flat
            if isinstance(versions, list):
                return versions
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list Folia versions: {e}")
            return []

    def get_download_url(self, version: str) -> str:
        """Get the server JAR download URL for a specific Folia Minecraft version.

        Handles STABLE, ALPHA, and EXPERIMENTAL channels since Folia releases
        are often published under non-STABLE channels.
        """
        try:
            bresp = requests.get(f"{API_BASE}/versions/{version}/builds", headers=_HEADERS, timeout=20)
            bresp.raise_for_status()
            builds = bresp.json()
            if not isinstance(builds, list) or not builds:
                raise ValueError(f"No builds found for Folia version {version}")

            # 1. Prefer STABLE channel build with server:default download
            stable = [
                b for b in builds
                if b.get("channel") == "STABLE"
                and b.get("downloads", {}).get("server:default", {}).get("url")
            ]
            candidate = stable[0] if stable else None

            # 2. Fallback to ALPHA or EXPERIMENTAL channels
            if not candidate:
                alpha_exp = [
                    b for b in builds
                    if b.get("channel") in ("ALPHA", "EXPERIMENTAL")
                    and b.get("downloads", {}).get("server:default", {}).get("url")
                ]
                candidate = alpha_exp[0] if alpha_exp else None

            # 3. Fallback to any build with server:default download
            if not candidate:
                for b in builds:
                    if b.get("downloads", {}).get("server:default", {}).get("url"):
                        candidate = b
                        break

            if not candidate:
                raise ValueError(f"No downloadable build found for Folia version {version}")

            url = candidate.get("downloads", {}).get("server:default", {}).get("url")
            if not url:
                raise ValueError(f"Build {candidate.get('id')} has no server:default URL")
            return url

        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to get Folia download URL for version {version}: {e}")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Unexpected error getting Folia download URL for version {version}: {e}")


# Register on import
register_provider(FoliaProvider())
