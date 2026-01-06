import requests
from typing import List, Optional, Dict, Any
from .providers import register_provider
from .vanilla import VanillaProvider
import logging
import re

logger = logging.getLogger(__name__)

# Official MinecraftForge API endpoints
PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
MAVEN_API = "https://maven.minecraftforge.net/api/maven/versions/releases/net/minecraftforge/forge"
MAVEN_BASE = "https://maven.minecraftforge.net/net/minecraftforge/forge"

class ForgeProvider:
    """Official MinecraftForge server provider using Forge Maven API.
    
    Forge servers require an installer that sets up the server environment.
    The installer is obtained from: https://maven.minecraftforge.net/net/minecraftforge/forge/{maven_coord}/forge-{maven_coord}-installer.jar
    Where maven_coord is usually "{mc_version}-{forge_version}", but for legacy versions (e.g., 1.7.10)
    it is "{mc_version}-{forge_version}-{mc_version}".
    
    Forge Version Format: {mc_version}-{forge_version}
    Example: 1.20.1-47.3.0 → MC 1.20.1, Forge 47.3.0
    """
    name = "forge"

    def __init__(self):
        self._cached_versions = None
        self._cached_promotions = None
        self._cached_forge_versions = {}
        self._cached_all_versions = None

    def list_versions(self) -> List[str]:
        """Get all Minecraft versions supported by Forge."""
        if self._cached_versions:
            return self._cached_versions
        
        try:
            all_forge_versions = self._get_all_forge_versions()
            
            # Extract unique MC versions from forge versions
            mc_versions = set()
            for forge_version in all_forge_versions:
                mc_version = self._extract_mc_version(forge_version)
                if mc_version:
                    mc_versions.add(mc_version)
            
            # Sort versions (newest first)
            sorted_versions = sorted(mc_versions, key=self._version_key, reverse=True)
            
            self._cached_versions = sorted_versions
            logger.info(f"Found {len(sorted_versions)} Forge-compatible MC versions")
            return sorted_versions
            
        except Exception as e:
            logger.warning(f"Could not fetch Forge versions from Maven API, falling back to promotions: {e}")
            # Fallback to promotions API
            return self._list_versions_from_promotions()

    def _list_versions_from_promotions(self) -> List[str]:
        """Fallback: Get supported MC versions from promotions API."""
        vanilla_versions = VanillaProvider().list_versions()
        try:
            promotions = self._get_promotions()
            supported_versions = []
            
            for version in vanilla_versions:
                if f"{version}-recommended" in promotions or f"{version}-latest" in promotions:
                    supported_versions.append(version)
            
            self._cached_versions = supported_versions
            return supported_versions
        except Exception as e:
            logger.warning(f"Could not filter Forge versions: {e}")
            return vanilla_versions

    def _version_key(self, version: str) -> tuple:
        """Create a sortable key from a version string."""
        try:
            parts = version.split('.')
            return tuple(int(p) for p in parts)
        except:
            return (0,)

    def _get_all_forge_versions(self) -> List[str]:
        """Get all Forge versions from Maven API."""
        if self._cached_all_versions:
            return self._cached_all_versions
            
        try:
            logger.info("Fetching Forge versions from Maven API")
            resp = requests.get(MAVEN_API, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            versions = data.get("versions", [])
            
            # Filter out prerelease and special versions
            stable_versions = []
            for v in versions:
                # Skip prerelease, snapshot versions
                if "pre" in v.lower() or "snapshot" in v.lower():
                    continue
                stable_versions.append(v)
            
            self._cached_all_versions = stable_versions
            logger.info(f"Cached {len(stable_versions)} Forge versions")
            return stable_versions
            
        except Exception as e:
            logger.error(f"Failed to fetch Forge versions from Maven API: {e}")
            return []

    def _extract_mc_version(self, forge_version: str) -> Optional[str]:
        """Extract Minecraft version from Forge version string.
        
        Forge versions are in format: {mc_version}-{forge_version}[-{mc_version}]
        Examples:
        - 1.20.1-47.3.0 → 1.20.1
        - 1.7.10-10.13.4.1614-1.7.10 → 1.7.10
        """
        try:
            # Split by first hyphen to get MC version
            parts = forge_version.split('-')
            if len(parts) >= 2:
                mc_version = parts[0]
                # Validate it looks like a MC version
                if re.match(r'^\d+\.\d+(\.\d+)?$', mc_version):
                    return mc_version
            return None
        except:
            return None

    def _get_promotions(self) -> Dict[str, Any]:
        """Get the promotions data (recommended/latest versions)."""
        if self._cached_promotions:
            return self._cached_promotions
            
        try:
            logger.info("Fetching Forge promotions from API")
            resp = requests.get(PROMOTIONS_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            promotions = data.get("promos", {})
            self._cached_promotions = promotions
            logger.info(f"Cached {len(promotions)} Forge promotions")
            return promotions
            
        except Exception as e:
            logger.error(f"Failed to fetch Forge promotions: {e}")
            raise ValueError(f"Could not fetch Forge promotions: {e}")

    def get_forge_versions_for_minecraft(self, minecraft_version: str) -> List[str]:
        """Get all available Forge versions for a specific Minecraft version.
        
        Args:
            minecraft_version: Minecraft version like "1.20.1" or "1.16.5"
        
        Returns:
            List of Forge version numbers (without MC prefix) sorted by newest first
        """
        if minecraft_version in self._cached_forge_versions:
            return self._cached_forge_versions[minecraft_version]
            
        try:
            all_versions = self._get_all_forge_versions()
            matching_versions = []
            
            for full_version in all_versions:
                mc_version = self._extract_mc_version(full_version)
                if mc_version == minecraft_version:
                    # Extract just the forge version part
                    forge_version = self._extract_forge_version(full_version)
                    if forge_version:
                        matching_versions.append(forge_version)
            
            # Sort versions (newest first)
            def version_sort_key(v):
                try:
                    # Handle versions like "47.3.0" or "10.13.4.1614"
                    parts = v.split('.')
                    return tuple(int(p) for p in parts)
                except:
                    return (0,)
            
            matching_versions.sort(key=version_sort_key, reverse=True)
            
            self._cached_forge_versions[minecraft_version] = matching_versions
            logger.info(f"Found {len(matching_versions)} Forge versions for MC {minecraft_version}")
            return matching_versions
            
        except Exception as e:
            logger.error(f"Failed to get Forge versions for {minecraft_version}: {e}")
            return []

    def _extract_forge_version(self, full_version: str) -> Optional[str]:
        """Extract Forge version number from full version string.
        
        Examples:
        - 1.20.1-47.3.0 → 47.3.0
        - 1.7.10-10.13.4.1614-1.7.10 → 10.13.4.1614
        """
        try:
            parts = full_version.split('-')
            if len(parts) >= 2:
                return parts[1]
            return None
        except:
            return None

    def get_recommended_forge_version(self, minecraft_version: str) -> Optional[str]:
        """Get the recommended Forge version for a Minecraft version."""
        promotions = self._get_promotions()
        return promotions.get(f"{minecraft_version}-recommended")

    def get_latest_forge_version(self, minecraft_version: str) -> Optional[str]:
        """Get the latest Forge version for a Minecraft version."""
        promotions = self._get_promotions()
        return promotions.get(f"{minecraft_version}-latest")

    def get_best_forge_version(self, minecraft_version: str) -> str:
        """Get the best available Forge version (recommended > latest > newest available)."""
        # Try recommended first
        recommended = self.get_recommended_forge_version(minecraft_version)
        if recommended:
            return recommended
            
        # Try latest
        latest = self.get_latest_forge_version(minecraft_version)
        if latest:
            return latest
            
        # Try getting from version list
        versions = self.get_forge_versions_for_minecraft(minecraft_version)
        if versions:
            return versions[0]  # First one should be newest
            
        raise ValueError(f"No Forge versions available for Minecraft {minecraft_version}")

    def _resolve_installer_url(self, mc_version: str, forge_version: str) -> str:
        """
        Build a working installer URL by trying known coordinate patterns and fallbacks.
        Patterns tried in order:
          1) {mc}-{forge}
          2) {mc}-{forge}-{mc}  (legacy coordinates like 1.7.10)
        For each, try -installer.jar, then fallback to -universal.jar if installer is missing.
        """
        import requests
        candidates = []
        # pattern 1
        coord1 = f"{mc_version}-{forge_version}"
        candidates.append(f"{MAVEN_BASE}/{coord1}/forge-{coord1}-installer.jar")
        candidates.append(f"{MAVEN_BASE}/{coord1}/forge-{coord1}-universal.jar")
        # pattern 2 (legacy)
        coord2 = f"{mc_version}-{forge_version}-{mc_version}"
        candidates.append(f"{MAVEN_BASE}/{coord2}/forge-{coord2}-installer.jar")
        candidates.append(f"{MAVEN_BASE}/{coord2}/forge-{coord2}-universal.jar")
        
        last_err = None
        for url in candidates:
            try:
                r = requests.head(url, timeout=20)
                if r.status_code == 200:
                    return url
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise ValueError(f"No valid Forge installer/universal found for {mc_version} {forge_version}: {last_err}")
        raise ValueError(f"No valid Forge installer/universal found for {mc_version} {forge_version}")

    def get_download_url(self, version: str) -> str:
        """Get download URL for Forge installer with the best available version."""
        forge_version = self.get_best_forge_version(version)
        url = self._resolve_installer_url(version, forge_version)
        logger.info(f"Forge download URL: {url}")
        return url

    def get_download_url_with_loader(self, version: str, loader_version: Optional[str] = None, installer_version: Optional[str] = None) -> str:
        """Get download URL with specific Forge version.
        
        Args:
            version: Minecraft version
            loader_version: Specific Forge version (best available if None)
            installer_version: Ignored for Forge (compatibility parameter)
        """
        # For Forge, loader_version is the Forge version
        if not loader_version:
            forge_version = self.get_best_forge_version(version)
        else:
            # Validate the Forge version exists
            available_versions = self.get_forge_versions_for_minecraft(version)
            if loader_version not in available_versions:
                # Try promotions as fallback
                promotions = self._get_promotions()
                recommended = promotions.get(f"{version}-recommended")
                latest = promotions.get(f"{version}-latest")
                
                if loader_version not in [recommended, latest]:
                    raise ValueError(f"Forge version {loader_version} not available for Minecraft {version}")
            
            forge_version = loader_version
        
        url = self._resolve_installer_url(version, forge_version)
        logger.info(f"Forge download URL (custom): {url}")
        return url

    def list_loader_versions(self, game_version: str) -> List[str]:
        """Get list of Forge version strings for a specific Minecraft version."""
        return self.get_forge_versions_for_minecraft(game_version)

register_provider(ForgeProvider())
