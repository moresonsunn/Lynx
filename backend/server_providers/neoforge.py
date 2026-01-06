import requests
from typing import List, Optional, Dict, Any
from .providers import register_provider
from .vanilla import VanillaProvider
import logging
import re

logger = logging.getLogger(__name__)

# Official NeoForge Maven API endpoint
MAVEN_API = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
MAVEN_BASE = "https://maven.neoforged.net/releases/net/neoforged/neoforge"

class NeoForgeProvider:
    """Official NeoForge server provider using NeoForge Maven API.
    
    NeoForge servers require an installer that sets up the server environment.
    The installer is obtained from: https://maven.neoforged.net/releases/net/neoforged/neoforge/{neoforge_version}/neoforge-{neoforge_version}-installer.jar
    
    NeoForge Version Scheme:
    - Version XX.Y.Z maps to Minecraft 1.XX.Y (where XX >= 20)
    - Example: 21.4.56 → MC 1.21.4
    - Example: 20.4.251 → MC 1.20.4
    """
    name = "neoforge"

    def __init__(self):
        self._cached_versions = None
        self._cached_neoforge_versions = None
        self._cached_mc_mappings = {}

    def list_versions(self) -> List[str]:
        """Get all Minecraft versions supported by NeoForge."""
        if self._cached_versions:
            return self._cached_versions
        
        try:
            logger.info("Fetching NeoForge supported versions from Maven API")
            neoforge_versions = self._get_all_neoforge_versions()
            
            # Extract unique MC versions
            mc_versions = set()
            for nf_version in neoforge_versions:
                mc_version = self._infer_mc_version_from_neoforge(nf_version)
                if mc_version:
                    mc_versions.add(mc_version)
            
            # Sort versions (newest first)
            sorted_versions = sorted(mc_versions, key=self._version_key, reverse=True)
            
            self._cached_versions = sorted_versions
            logger.info(f"Found {len(sorted_versions)} NeoForge-compatible MC versions: {sorted_versions}")
            return sorted_versions
            
        except Exception as e:
            logger.warning(f"Could not fetch NeoForge versions from API, using fallback: {e}")
            # Fallback: Return common recent versions
            fallback = ["1.21.5", "1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.2"]
            self._cached_versions = fallback
            return fallback

    def _version_key(self, version: str) -> tuple:
        """Create a sortable key from a version string."""
        try:
            parts = version.split('.')
            return tuple(int(p) for p in parts)
        except:
            return (0,)

    def _get_all_neoforge_versions(self) -> List[str]:
        """Get all NeoForge versions from Maven API."""
        if self._cached_neoforge_versions:
            return self._cached_neoforge_versions
            
        try:
            logger.info("Fetching NeoForge versions from Maven API")
            resp = requests.get(MAVEN_API, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract versions list
            versions = data.get("versions", [])
            
            # Filter out snapshots, alpha, and special versions
            stable_versions = []
            for v in versions:
                # Skip snapshot/alpha/special versions
                if "alpha" in v.lower() or "snapshot" in v.lower() or "craftmine" in v.lower():
                    continue
                stable_versions.append(v)
            
            # Cache the result
            self._cached_neoforge_versions = stable_versions
            logger.info(f"Cached {len(stable_versions)} NeoForge versions")
            return stable_versions
            
        except Exception as e:
            logger.error(f"Failed to fetch NeoForge versions from Maven API: {e}")
            return []

    def _infer_mc_version_from_neoforge(self, neoforge_version: str) -> Optional[str]:
        """Infer Minecraft version from NeoForge version.
        
        NeoForge version scheme: XX.Y.Z → Minecraft 1.XX.Y
        - 21.4.56 → 1.21.4
        - 20.4.251 → 1.20.4
        - 21.1.217 → 1.21.1
        - 21.0.167 → 1.21 (or 1.21.0)
        """
        try:
            # Parse XX.Y.Z format
            match = re.match(r'^(\d+)\.(\d+)\.', neoforge_version)
            if not match:
                return None
            
            major = int(match.group(1))  # e.g., 21
            minor = int(match.group(2))  # e.g., 4
            
            # NeoForge versions for MC 1.20.x start with 20.x
            # NeoForge versions for MC 1.21.x start with 21.x
            if major < 20:
                return None  # Invalid for NeoForge
            
            # Build MC version: 1.XX.Y
            if minor == 0:
                return f"1.{major}"  # 1.21 instead of 1.21.0
            else:
                return f"1.{major}.{minor}"
                
        except Exception as e:
            logger.debug(f"Could not parse NeoForge version {neoforge_version}: {e}")
            return None

    def get_neoforge_versions_for_minecraft(self, minecraft_version: str) -> List[str]:
        """Get all available NeoForge versions for a specific Minecraft version.
        
        Args:
            minecraft_version: Minecraft version like "1.21.4" or "1.21"
        
        Returns:
            List of NeoForge versions sorted by newest first
        """
        if minecraft_version in self._cached_mc_mappings:
            return self._cached_mc_mappings[minecraft_version]
            
        try:
            all_versions = self._get_all_neoforge_versions()
            matching_versions = []
            
            for nf_version in all_versions:
                mc_version = self._infer_mc_version_from_neoforge(nf_version)
                if mc_version == minecraft_version:
                    matching_versions.append(nf_version)
            
            # Sort versions (newest first) - handle both stable and beta
            def version_sort_key(v):
                # Remove -beta suffix for sorting
                base = v.replace('-beta', '')
                try:
                    parts = base.split('.')
                    return tuple(int(p) for p in parts[:3])
                except:
                    return (0, 0, 0)
            
            matching_versions.sort(key=version_sort_key, reverse=True)
            
            # Separate stable and beta versions - stable first
            stable = [v for v in matching_versions if '-beta' not in v]
            beta = [v for v in matching_versions if '-beta' in v]
            sorted_versions = stable + beta
            
            self._cached_mc_mappings[minecraft_version] = sorted_versions
            logger.info(f"Found {len(sorted_versions)} NeoForge versions for MC {minecraft_version} ({len(stable)} stable, {len(beta)} beta)")
            return sorted_versions
            
        except Exception as e:
            logger.error(f"Failed to get NeoForge versions for {minecraft_version}: {e}")
            return []

    def get_latest_neoforge_version(self, minecraft_version: str) -> Optional[str]:
        """Get the latest NeoForge version for a Minecraft version."""
        versions = self.get_neoforge_versions_for_minecraft(minecraft_version)
        return versions[0] if versions else None

    def get_download_url(self, version: str) -> str:
        """Get download URL for NeoForge installer with the latest version."""
        neoforge_version = self.get_latest_neoforge_version(version)
        
        if not neoforge_version:
            raise ValueError(f"No NeoForge versions available for Minecraft {version}")
        
        url = f"{MAVEN_BASE}/{neoforge_version}/neoforge-{neoforge_version}-installer.jar"
        logger.info(f"NeoForge download URL: {url}")
        return url

    def get_download_url_with_loader(self, version: str, loader_version: Optional[str] = None, installer_version: Optional[str] = None) -> str:
        """Get download URL with specific NeoForge version.
        
        Args:
            version: Minecraft version
            loader_version: Specific NeoForge version (latest if None)
            installer_version: Ignored for NeoForge (compatibility parameter)
        """
        # For NeoForge, loader_version is the NeoForge version
        if not loader_version:
            neoforge_version = self.get_latest_neoforge_version(version)
            if not neoforge_version:
                raise ValueError(f"No NeoForge versions available for Minecraft {version}")
        else:
            # Validate the NeoForge version exists for this MC version
            available_versions = self.get_neoforge_versions_for_minecraft(version)
            if loader_version not in available_versions:
                raise ValueError(f"NeoForge version {loader_version} not available for Minecraft {version}")
            
            neoforge_version = loader_version
        
        url = f"{MAVEN_BASE}/{neoforge_version}/neoforge-{neoforge_version}-installer.jar"
        logger.info(f"NeoForge download URL (custom): {url}")
        return url

    def list_loader_versions(self, game_version: str) -> List[str]:
        """Get list of NeoForge version strings for a specific Minecraft version."""
        return self.get_neoforge_versions_for_minecraft(game_version)

register_provider(NeoForgeProvider())
