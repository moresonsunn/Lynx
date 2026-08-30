import requests
from typing import List
from .providers import register_provider

# Migrated to Fill v3 — api.papermc.io/v2 was sunset 2026-07-01 (410 Gone). See https://docs.papermc.io/misc/downloads-service/
API_BASE = "https://fill.papermc.io/v3/projects/paper"
USER_AGENT = "Lynx/1.0 (+https://github.com/moresonsun/Lynx)"

_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

class PaperProvider:
    name = "paper"

    def list_versions(self) -> List[str]:
        resp = requests.get(API_BASE, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        versions = data.get("versions", {})
        # Fill v3 returns {"1.21": ["1.21.11","1.21.4",...], "1.20": [...] } — flatten and keep stable order (newest first is already)
        if isinstance(versions, dict):
            flat: List[str] = []
            for group in versions.values():
                if isinstance(group, list):
                    flat.extend(group)
                elif isinstance(group, str):
                    flat.append(group)
            # Preserve display order: newest versions first (1.21.x before 1.20 etc. is already grouped newest first)
            # but flatten loses grouping order — keep as returned (API returns newest groups first)
            # Filter to stable-looking versions (exclude -rc, -pre) for cleaner picker, but keep all if needed
            return flat
        if isinstance(versions, list):
            return versions
        return []

    def get_download_url(self, version: str) -> str:
        # Get builds for the version and return the latest STABLE server jar URL
        try:
            bresp = requests.get(f"{API_BASE}/versions/{version}/builds", headers=_HEADERS, timeout=20)
            bresp.raise_for_status()
            builds = bresp.json()
            if not isinstance(builds, list) or not builds:
                raise ValueError(f"No builds found for Paper version {version}")

            # Prefer STABLE channel, fallback to any build with a server:default download
            stable = [b for b in builds if b.get("channel") == "STABLE" and b.get("downloads", {}).get("server:default", {}).get("url")]
            candidate = stable[0] if stable else None
            if not candidate:
                # fallback: first build that has a server:default download
                for b in builds:
                    if b.get("downloads", {}).get("server:default", {}).get("url"):
                        candidate = b
                        break
            if not candidate:
                raise ValueError(f"No downloadable build found for Paper version {version}")

            url = candidate["downloads"]["server:default"]["url"]
            if not url:
                raise ValueError(f"Build {candidate.get('id')} has no server:default URL")
            return url

        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to get Paper download URL for version {version}: {e}")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Unexpected error getting Paper download URL for version {version}: {e}")

# Register on import
register_provider(PaperProvider())
