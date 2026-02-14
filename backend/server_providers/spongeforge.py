import requests
import re
from typing import List, Optional, Dict, Any
from .providers import register_provider
import logging

logger = logging.getLogger(__name__)

# SpongePowered Download API v2
API_BASE = "https://dl-api.spongepowered.org/v2/groups/org.spongepowered/artifacts/spongeforge"
MAVEN_BASE = "https://repo.spongepowered.org/repository/maven-releases/org/spongepowered/spongeforge"


class SpongeForgeProvider:
    """SpongeForge hybrid server provider (Forge + Sponge API).

    SpongeForge is a mod that runs on top of Forge and adds the Sponge plugin
    API, allowing both Forge mods and Sponge plugins to run together.

    Note: SpongeForge is technically a Forge mod (placed in the mods folder),
    but we treat it as a server type for user convenience.
    The download provides the SpongeForge mod jar; the user also needs a Forge
    server which is set up automatically.

    API: https://dl-api.spongepowered.org/v2
    """
    name = "spongeforge"

    def __init__(self):
        self._cached_versions: Optional[List[str]] = None
        self._cached_artifacts: Optional[Dict[str, Any]] = None

    def _fetch_artifacts(self) -> Dict[str, Any]:
        if self._cached_artifacts is not None:
            return self._cached_artifacts

        try:
            logger.info("Fetching SpongeForge versions from API")
            resp = requests.get(f"{API_BASE}/versions", timeout=30)
            resp.raise_for_status()
            data = resp.json()
            artifacts = data.get("artifacts", {})
            self._cached_artifacts = artifacts
            logger.info(f"Found {len(artifacts)} SpongeForge artifacts")
            return artifacts
        except Exception as e:
            logger.error(f"Failed to fetch SpongeForge versions: {e}")
            raise ValueError(f"Could not fetch SpongeForge versions: {e}")

    def list_versions(self) -> List[str]:
        """Get supported Minecraft versions for SpongeForge."""
        if self._cached_versions:
            return self._cached_versions

        artifacts = self._fetch_artifacts()
        mc_versions = set()
        for artifact_key, info in artifacts.items():
            tags = info.get("tagValues", {})
            mc = tags.get("minecraft")
            if mc:
                mc_versions.add(mc)

        # Sort newest first
        def version_key(v: str):
            try:
                parts = v.split(".")
                return tuple(int(p) for p in parts)
            except ValueError:
                return (0,)

        sorted_versions = sorted(mc_versions, key=version_key, reverse=True)
        self._cached_versions = sorted_versions
        logger.info(f"Found {len(sorted_versions)} SpongeForge MC versions")
        return sorted_versions

    def _get_best_artifact_for_version(self, mc_version: str) -> Optional[str]:
        """Get the best (recommended or latest) SpongeForge artifact key for an MC version."""
        artifacts = self._fetch_artifacts()
        candidates = []
        for artifact_key, info in artifacts.items():
            tags = info.get("tagValues", {})
            mc = tags.get("minecraft")
            if mc == mc_version:
                recommended = info.get("recommended", False)
                candidates.append((artifact_key, recommended))

        if not candidates:
            return None

        # Prefer recommended
        for key, rec in candidates:
            if rec:
                return key

        # Fall back to first (latest) entry
        return candidates[0][0]

    def get_download_url(self, version: str) -> str:
        """Get download URL for SpongeForge universal jar for the given MC version."""
        artifact_key = self._get_best_artifact_for_version(version)
        if not artifact_key:
            raise ValueError(f"No SpongeForge build found for Minecraft {version}")

        # The maven coordinate is: org.spongepowered:spongeforge:{artifact_key}:universal
        url = f"{MAVEN_BASE}/{artifact_key}/spongeforge-{artifact_key}-universal.jar"
        logger.info(f"SpongeForge download URL for MC {version}: {url}")
        return url


register_provider(SpongeForgeProvider())
