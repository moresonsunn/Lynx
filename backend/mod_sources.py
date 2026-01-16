"""
Mod and Plugin source API clients for Modrinth, CurseForge, and Spiget.
"""
import os
import logging
import httpx
from typing import Optional
from pathlib import Path
from config import SERVERS_ROOT

logger = logging.getLogger(__name__)

# API Configuration
MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com"
SPIGET_API = "https://api.spiget.org/v2"

# CurseForge requires an API key - get from environment
CURSEFORGE_API_KEY = os.getenv("CURSEFORGE_API_KEY", "")

# Minecraft game ID on CurseForge
CURSEFORGE_MINECRAFT_GAME_ID = 432

# Mod loader IDs for CurseForge
CURSEFORGE_LOADERS = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

# User agent for API requests
USER_AGENT = "Lynx-Server-Manager/1.0 (https://github.com/moresonsunn/Lynx)"


class ModrinthClient:
    """Client for Modrinth API - supports mods and plugins."""
    
    def __init__(self):
        self.base_url = MODRINTH_API
        self.headers = {"User-Agent": USER_AGENT}
    
    async def search(
        self,
        query: str,
        project_type: str = "mod",  # "mod" or "plugin"
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Search for mods or plugins on Modrinth."""
        # Build facets for filtering
        facets = [[f'project_type:{project_type}']]
        
        if game_version:
            facets.append([f'versions:{game_version}'])
        
        if loader:
            # Normalize loader name
            loader_lower = loader.lower()
            if loader_lower in ("paper", "spigot", "bukkit", "purpur"):
                facets.append([f'categories:paper', f'categories:spigot', f'categories:bukkit'])
            elif loader_lower in ("fabric", "forge", "neoforge", "quilt"):
                facets.append([f'categories:{loader_lower}'])
        
        import json
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "facets": json.dumps(facets),
        }
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/search",
                params=params,
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
        
        # Transform to common format
        results = []
        for hit in data.get("hits", []):
            results.append({
                "id": hit.get("project_id") or hit.get("slug"),
                "slug": hit.get("slug"),
                "name": hit.get("title"),
                "description": hit.get("description", ""),
                "author": hit.get("author", ""),
                "icon_url": hit.get("icon_url"),
                "downloads": hit.get("downloads", 0),
                "source": "modrinth",
                "categories": hit.get("categories", []),
                "versions": hit.get("versions", []),
                "page_url": f"https://modrinth.com/{project_type}/{hit.get('slug')}",
            })
        
        return {
            "results": results,
            "total": data.get("total_hits", len(results)),
            "offset": offset,
            "limit": limit,
        }
    
    async def get_versions(
        self,
        project_id: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
    ) -> list:
        """Get available versions/files for a project."""
        params = {}
        if game_version:
            params["game_versions"] = f'["{game_version}"]'
        if loader:
            params["loaders"] = f'["{loader.lower()}"]'
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/project/{project_id}/version",
                params=params,
                headers=self.headers,
            )
            resp.raise_for_status()
            versions = resp.json()
        
        results = []
        for v in versions:
            # Get the primary file
            files = v.get("files", [])
            primary_file = next((f for f in files if f.get("primary")), files[0] if files else None)
            
            if primary_file:
                results.append({
                    "id": v.get("id"),
                    "version": v.get("version_number"),
                    "name": v.get("name"),
                    "game_versions": v.get("game_versions", []),
                    "loaders": v.get("loaders", []),
                    "download_url": primary_file.get("url"),
                    "filename": primary_file.get("filename"),
                    "size": primary_file.get("size", 0),
                })
        
        return results


class CurseForgeClient:
    """Client for CurseForge API - requires API key."""
    
    def __init__(self):
        self.base_url = CURSEFORGE_API
        self.api_key = CURSEFORGE_API_KEY
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self.api_key:
            self.headers["x-api-key"] = self.api_key
    
    def is_available(self) -> bool:
        """Check if CurseForge API is available (has API key)."""
        return bool(self.api_key)
    
    async def search(
        self,
        query: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Search for mods on CurseForge."""
        if not self.is_available():
            return {"results": [], "total": 0, "offset": 0, "limit": 0, "error": "CurseForge API key not configured"}
        
        params = {
            "gameId": CURSEFORGE_MINECRAFT_GAME_ID,
            "searchFilter": query,
            "pageSize": limit,
            "index": offset,
            "classId": 6,  # Mods class
        }
        
        if game_version:
            params["gameVersion"] = game_version
        
        if loader and loader.lower() in CURSEFORGE_LOADERS:
            params["modLoaderType"] = CURSEFORGE_LOADERS[loader.lower()]
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/v1/mods/search",
                params=params,
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
        
        results = []
        for mod in data.get("data", []):
            # Get icon
            icon_url = None
            logo = mod.get("logo")
            if logo:
                icon_url = logo.get("thumbnailUrl") or logo.get("url")
            
            # Get authors
            authors = mod.get("authors", [])
            author_name = authors[0].get("name") if authors else ""
            
            results.append({
                "id": str(mod.get("id")),
                "slug": mod.get("slug"),
                "name": mod.get("name"),
                "description": mod.get("summary", ""),
                "author": author_name,
                "icon_url": icon_url,
                "downloads": mod.get("downloadCount", 0),
                "source": "curseforge",
                "categories": [c.get("name") for c in mod.get("categories", [])],
                "page_url": mod.get("links", {}).get("websiteUrl", ""),
            })
        
        return {
            "results": results,
            "total": data.get("pagination", {}).get("totalCount", len(results)),
            "offset": offset,
            "limit": limit,
        }
    
    async def get_versions(
        self,
        mod_id: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
    ) -> list:
        """Get available files for a mod."""
        if not self.is_available():
            return []
        
        params = {}
        if game_version:
            params["gameVersion"] = game_version
        if loader and loader.lower() in CURSEFORGE_LOADERS:
            params["modLoaderType"] = CURSEFORGE_LOADERS[loader.lower()]
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/v1/mods/{mod_id}/files",
                params=params,
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
        
        results = []
        for f in data.get("data", []):
            results.append({
                "id": str(f.get("id")),
                "version": f.get("displayName"),
                "name": f.get("fileName"),
                "game_versions": f.get("gameVersions", []),
                "loaders": [l.lower() for l in f.get("gameVersions", []) if l.lower() in CURSEFORGE_LOADERS],
                "download_url": f.get("downloadUrl"),
                "filename": f.get("fileName"),
                "size": f.get("fileLength", 0),
            })
        
        return results


class SpigetClient:
    """Client for Spiget API - SpigotMC resources."""
    
    def __init__(self):
        self.base_url = SPIGET_API
        self.headers = {"User-Agent": USER_AGENT}
    
    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Search for plugins on SpigotMC via Spiget."""
        # Spiget uses page-based pagination
        page = (offset // limit) + 1
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/search/resources/{query}",
                params={"size": limit, "page": page},
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
        
        results = []
        for resource in data:
            # Get icon URL (Spiget uses base64 encoded icons or external URLs)
            icon = resource.get("icon", {})
            icon_url = None
            if icon.get("url"):
                icon_url = f"https://www.spigotmc.org/{icon['url']}"
            
            # Get author info
            author = resource.get("author", {})
            author_name = author.get("name", "") if isinstance(author, dict) else ""
            
            results.append({
                "id": str(resource.get("id")),
                "slug": resource.get("name", "").lower().replace(" ", "-"),
                "name": resource.get("name"),
                "description": resource.get("tag", ""),
                "author": author_name,
                "icon_url": icon_url,
                "downloads": resource.get("downloads", 0),
                "source": "spiget",
                "categories": [],
                "page_url": f"https://www.spigotmc.org/resources/{resource.get('id')}",
                "external": resource.get("external", False),
            })
        
        return {
            "results": results,
            "total": len(results),  # Spiget doesn't provide total count
            "offset": offset,
            "limit": limit,
        }
    
    async def get_download_url(self, resource_id: str) -> Optional[str]:
        """Get the download URL for a resource."""
        # Spiget provides a direct download endpoint
        return f"{self.base_url}/resources/{resource_id}/download"


# Download helper
async def download_mod_to_server(
    url: str,
    server_name: str,
    dest_folder: str = "mods",
    filename: Optional[str] = None,
) -> dict:
    """
    Download a mod/plugin file to the server's folder.
    
    Args:
        url: Download URL
        server_name: Name of the server
        dest_folder: Destination folder ('mods' or 'plugins')
        filename: Optional filename (will be extracted from URL if not provided)
    
    Returns:
        Dict with success status and file info
    """
    server_dir = SERVERS_ROOT / server_name
    if not server_dir.exists():
        return {"ok": False, "error": "Server not found"}
    
    target_dir = server_dir / dest_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            
            # Determine filename
            if not filename:
                # Try to get from Content-Disposition header
                cd = resp.headers.get("content-disposition", "")
                if "filename=" in cd:
                    import re
                    match = re.search(r'filename[*]?=["\']?([^"\';]+)', cd)
                    if match:
                        filename = match.group(1)
                
                # Fallback to URL path
                if not filename:
                    from urllib.parse import urlparse, unquote
                    path = urlparse(url).path
                    filename = unquote(path.split("/")[-1])
                
                # Ensure .jar extension
                if not filename.lower().endswith(".jar"):
                    filename = f"{filename}.jar"
            
            # Write file
            target_path = target_dir / filename
            target_path.write_bytes(resp.content)
            
            return {
                "ok": True,
                "filename": filename,
                "path": str(target_path),
                "size": len(resp.content),
            }
    
    except Exception as e:
        logger.error(f"Failed to download mod: {e}")
        return {"ok": False, "error": str(e)}


# Convenience functions
async def search_mods(
    query: str,
    source: str = "modrinth",
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search for mods from specified source."""
    if source == "curseforge":
        client = CurseForgeClient()
        return await client.search(query, game_version, loader, limit, offset)
    else:
        client = ModrinthClient()
        return await client.search(query, "mod", game_version, loader, limit, offset)


async def search_plugins(
    query: str,
    source: str = "modrinth",
    game_version: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search for plugins from specified source."""
    if source == "spiget":
        client = SpigetClient()
        return await client.search(query, limit, offset)
    else:
        client = ModrinthClient()
        # For plugins, use paper/spigot/bukkit loaders
        return await client.search(query, "plugin", game_version, "paper", limit, offset)


async def get_mod_versions(
    project_id: str,
    source: str = "modrinth",
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
) -> list:
    """Get available versions for a mod."""
    if source == "curseforge":
        client = CurseForgeClient()
        return await client.get_versions(project_id, game_version, loader)
    else:
        client = ModrinthClient()
        return await client.get_versions(project_id, game_version, loader)
