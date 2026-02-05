"""
Steam Game Mods Routes - Workshop, Thunderstore, and CurseForge Integration
Provides mod browsing and installation for Steam games
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import httpx
import os
import zipfile
import shutil
import asyncio
import re
from pathlib import Path

from auth import get_current_user, require_moderator
from database import get_db

router = APIRouter(prefix="/steam-mods", tags=["Steam Mods"])

# =============================================================================
# MOD SOURCE CONFIGURATIONS
# =============================================================================

# CurseForge Game IDs and configurations
# API Reference: https://docs.curseforge.com/
CURSEFORGE_GAMES = {
    # Palworld - 85196
    "palworld": {
        "game_id": 85196,
        "mod_path": "/Pal/Content/Paks/~mods",
        "name": "Palworld"
    },
    # 7 Days to Die - 7
    "7_days_to_die": {
        "game_id": 7,
        "mod_path": "/Mods",
        "name": "7 Days to Die"
    },
    "sdtd": {
        "game_id": 7,
        "mod_path": "/Mods",
        "name": "7 Days to Die"
    },
    # ARK Survival Ascended - 84698
    "ark_survival_ascended": {
        "game_id": 84698,
        "mod_path": "/ShooterGame/Content/Mods",
        "name": "ARK Survival Ascended"
    },
    # Terraria - 431
    "terraria": {
        "game_id": 431,
        "mod_path": "/tModLoader/Mods",
        "name": "Terraria"
    },
    "terraria_tmodloader": {
        "game_id": 431,
        "mod_path": "/tModLoader/Mods",
        "name": "Terraria"
    },
    # Kerbal Space Program - 4401
    "kerbal_space_program": {
        "game_id": 4401,
        "mod_path": "/GameData",
        "name": "Kerbal Space Program"
    },
    "ksp": {
        "game_id": 4401,
        "mod_path": "/GameData",
        "name": "Kerbal Space Program"
    },
    # Stardew Valley - 669
    "stardew_valley": {
        "game_id": 669,
        "mod_path": "/Mods",
        "name": "Stardew Valley"
    },
    # Hogwarts Legacy - 80815
    "hogwarts_legacy": {
        "game_id": 80815,
        "mod_path": "/Phoenix/Content/Paks/~mods",
        "name": "Hogwarts Legacy"
    },
    # American Truck Simulator - 64367
    "american_truck_simulator": {
        "game_id": 64367,
        "mod_path": "/mod",
        "name": "American Truck Simulator"
    },
    "ats": {
        "game_id": 64367,
        "mod_path": "/mod",
        "name": "American Truck Simulator"
    },
    # Valheim - 68940
    "valheim": {
        "game_id": 68940,
        "mod_path": "/BepInEx/plugins",
        "name": "Valheim"
    },
    # RimWorld - 73492
    "rimworld": {
        "game_id": 73492,
        "mod_path": "/Mods",
        "name": "RimWorld"
    },
    # Darkest Dungeon - 608
    "darkest_dungeon": {
        "game_id": 608,
        "mod_path": "/mods",
        "name": "Darkest Dungeon"
    },
    # Surviving Mars - 61489
    "surviving_mars": {
        "game_id": 61489,
        "mod_path": "/Mods",
        "name": "Surviving Mars"
    },
    # Lethal Company - 83671
    "lethal_company": {
        "game_id": 83671,
        "mod_path": "/BepInEx/plugins",
        "name": "Lethal Company"
    },
    # Among Us - 69761
    "among_us": {
        "game_id": 69761,
        "mod_path": "/BepInEx/plugins",
        "name": "Among Us"
    },
    # Dyson Sphere Program - 82729
    "dyson_sphere_program": {
        "game_id": 82729,
        "mod_path": "/BepInEx/plugins",
        "name": "Dyson Sphere Program"
    },
    # Satisfactory - 84368
    "satisfactory": {
        "game_id": 84368,
        "mod_path": "/FactoryGame/Mods",
        "name": "Satisfactory"
    },
    # Manor Lords - 85406
    "manor_lords": {
        "game_id": 85406,
        "mod_path": "/ManorLords/Content/Paks/~mods",
        "name": "Manor Lords"
    },
    # Baldur's Gate 3 - 84299
    "baldurs_gate_3": {
        "game_id": 84299,
        "mod_path": "/Mods",
        "name": "Baldur's Gate 3"
    },
    "bg3": {
        "game_id": 84299,
        "mod_path": "/Mods",
        "name": "Baldur's Gate 3"
    },
    # V Rising - 78135
    "vrising": {
        "game_id": 78135,
        "mod_path": "/BepInEx/plugins",
        "name": "V Rising"
    },
    # Cyberpunk 2077 - 78330
    "cyberpunk_2077": {
        "game_id": 78330,
        "mod_path": "/archive/pc/mod",
        "name": "Cyberpunk 2077"
    },
    # Starfield - 83951
    "starfield": {
        "game_id": 83951,
        "mod_path": "/Data",
        "name": "Starfield"
    },
    # Skyrim - 73492
    "skyrim": {
        "game_id": 73492,
        "mod_path": "/Data",
        "name": "The Elder Scrolls V: Skyrim"
    },
    # Fallout 4 - 80122
    "fallout_4": {
        "game_id": 80122,
        "mod_path": "/Data",
        "name": "Fallout 4"
    },
    # Sons of the Forest - 83879
    "sons_of_the_forest": {
        "game_id": 83879,
        "mod_path": "/BepInEx/plugins",
        "name": "Sons of the Forest"
    },
    # Core Keeper - 79917
    "core_keeper": {
        "game_id": 79917,
        "mod_path": "/BepInEx/plugins",
        "name": "Core Keeper"
    },
}

# Games that support Steam Workshop
WORKSHOP_GAMES = {
    "gmod": {"appid": 4000, "workshop_appid": 4000, "mod_path": "/garrysmod/addons"},
    "garrys_mod": {"appid": 4000, "workshop_appid": 4000, "mod_path": "/garrysmod/addons"},
    "arma3": {"appid": 107410, "workshop_appid": 107410, "mod_path": "/@mods"},
    "dont_starve_together": {"appid": 322330, "workshop_appid": 322330, "mod_path": "/mods"},
    "project_zomboid": {"appid": 108600, "workshop_appid": 108600, "mod_path": "/Zomboid/mods"},
    "space_engineers": {"appid": 244850, "workshop_appid": 244850, "mod_path": "/Mods"},
    "starbound": {"appid": 211820, "workshop_appid": 211820, "mod_path": "/mods"},
    "terraria_tmodloader": {"appid": 1281930, "workshop_appid": 1281930, "mod_path": "/Mods"},
    "rimworld": {"appid": 294100, "workshop_appid": 294100, "mod_path": "/Mods"},
    "cities_skylines": {"appid": 255710, "workshop_appid": 255710, "mod_path": "/Addons/Mods"},
    "7_days_to_die": {"appid": 251570, "workshop_appid": 251570, "mod_path": "/Mods"},
    "conan_exiles": {"appid": 440900, "workshop_appid": 440900, "mod_path": "/ConanSandbox/Mods"},
    "ark": {"appid": 346110, "workshop_appid": 346110, "mod_path": "/ShooterGame/Content/Mods"},
    "rust": {"appid": 252490, "workshop_appid": 252490, "mod_path": "/oxide/plugins"},  # Oxide/uMod
}

# Games that use Thunderstore
THUNDERSTORE_GAMES = {
    "valheim": {
        "community": "valheim",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True,
        "bepinex_url": "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/"
    },
    "lethal_company": {
        "community": "lethal-company",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True,
        "bepinex_url": "https://thunderstore.io/package/download/BepInEx/BepInExPack/"
    },
    "risk_of_rain_2": {
        "community": "ror2",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "vrising": {
        "community": "v-rising",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "sunkenland": {
        "community": "sunkenland",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "palworld": {
        "community": "palworld",
        "mod_path": "/Pal/Binaries/Win64/Mods",
        "bepinex_required": False
    },
    "content_warning": {
        "community": "content-warning",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "core_keeper": {
        "community": "core-keeper",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "among_us": {
        "community": "among-us",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "inscryption": {
        "community": "inscryption",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "gtfo": {
        "community": "gtfo",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    }
}

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class WorkshopInstallRequest(BaseModel):
    server_id: str
    workshop_id: str
    game_slug: str

class ThunderstoreInstallRequest(BaseModel):
    server_id: str
    namespace: str
    name: str
    version: str
    game_slug: str
    install_dependencies: bool = True

class ModUninstallRequest(BaseModel):
    server_id: str
    mod_name: str
    game_slug: str

class CurseForgeInstallRequest(BaseModel):
    server_id: str
    mod_id: int
    file_id: int
    game_slug: str

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_server_path(server_id: str) -> Path:
    """Get the data path for a server"""
    base_path = os.environ.get("DATA_DIR", "/data")
    return Path(base_path) / "servers" / server_id

def get_mod_source_for_game(game_slug: str) -> Dict[str, Any]:
    """Determine which mod source(s) a game supports"""
    sources = {
        "workshop": game_slug in WORKSHOP_GAMES,
        "thunderstore": game_slug in THUNDERSTORE_GAMES,
        "curseforge": game_slug in CURSEFORGE_GAMES,
        "workshop_config": WORKSHOP_GAMES.get(game_slug),
        "thunderstore_config": THUNDERSTORE_GAMES.get(game_slug),
        "curseforge_config": CURSEFORGE_GAMES.get(game_slug)
    }
    return sources

# =============================================================================
# CURSEFORGE API
# =============================================================================

CURSEFORGE_API_KEY = os.environ.get("CURSEFORGE_API_KEY", "$2a$10$bL4bIL5pUWqfcO7KQtnMReakwtfHbNKh6v1uTpKlzhwoueEJQnPnm")
CURSEFORGE_API = "https://api.curseforge.com/v1"

async def search_curseforge(game_id: int, search: str = "", page: int = 1, class_id: int = None) -> Dict[str, Any]:
    """Search CurseForge for mods"""
    url = f"{CURSEFORGE_API}/mods/search"
    
    params = {
        "gameId": game_id,
        "searchFilter": search,
        "index": (page - 1) * 20,
        "pageSize": 20,
        "sortField": 2,  # Popularity
        "sortOrder": "desc"
    }
    
    if class_id:
        params["classId"] = class_id
    
    headers = {
        "x-api-key": CURSEFORGE_API_KEY,
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code != 200:
                return {"results": [], "total": 0, "error": f"HTTP {response.status_code}"}
            
            data = response.json()
            mods = data.get("data", [])
            
            results = []
            for mod in mods:
                # Get the latest file
                latest_files = mod.get("latestFiles", [])
                latest_file = latest_files[0] if latest_files else None
                
                results.append({
                    "id": mod.get("id"),
                    "name": mod.get("name", ""),
                    "slug": mod.get("slug", ""),
                    "description": mod.get("summary", ""),
                    "author": mod.get("authors", [{}])[0].get("name", "Unknown"),
                    "downloads": mod.get("downloadCount", 0),
                    "icon_url": mod.get("logo", {}).get("thumbnailUrl", ""),
                    "website_url": mod.get("links", {}).get("websiteUrl", ""),
                    "latest_file": {
                        "id": latest_file.get("id") if latest_file else None,
                        "name": latest_file.get("fileName") if latest_file else None,
                        "download_url": latest_file.get("downloadUrl") if latest_file else None,
                        "file_size": latest_file.get("fileLength", 0) if latest_file else 0,
                    } if latest_file else None,
                    "source": "curseforge"
                })
            
            return {
                "results": results,
                "total": data.get("pagination", {}).get("totalCount", len(results)),
                "page": page
            }
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e)}

async def get_curseforge_mod(mod_id: int) -> Dict[str, Any]:
    """Get details for a specific CurseForge mod"""
    url = f"{CURSEFORGE_API}/mods/{mod_id}"
    
    headers = {
        "x-api-key": CURSEFORGE_API_KEY,
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(404, f"Mod {mod_id} not found")
        
        data = response.json().get("data", {})
        
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "slug": data.get("slug"),
            "description": data.get("summary"),
            "icon_url": data.get("logo", {}).get("thumbnailUrl"),
            "downloads": data.get("downloadCount"),
            "authors": [a.get("name") for a in data.get("authors", [])],
            "categories": [c.get("name") for c in data.get("categories", [])],
            "latest_files": [
                {
                    "id": f.get("id"),
                    "name": f.get("fileName"),
                    "download_url": f.get("downloadUrl"),
                    "file_size": f.get("fileLength"),
                    "game_versions": f.get("gameVersions", []),
                }
                for f in data.get("latestFiles", [])[:5]
            ]
        }

async def get_curseforge_mod_files(mod_id: int) -> List[Dict[str, Any]]:
    """Get all files for a CurseForge mod"""
    url = f"{CURSEFORGE_API}/mods/{mod_id}/files"
    
    headers = {
        "x-api-key": CURSEFORGE_API_KEY,
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            return []
        
        data = response.json().get("data", [])
        
        return [
            {
                "id": f.get("id"),
                "name": f.get("fileName"),
                "download_url": f.get("downloadUrl"),
                "file_size": f.get("fileLength"),
                "game_versions": f.get("gameVersions", []),
                "release_type": f.get("releaseType"),  # 1=Release, 2=Beta, 3=Alpha
                "date": f.get("fileDate"),
            }
            for f in data[:20]
        ]

async def download_curseforge_mod(
    download_url: str,
    install_path: Path,
    filename: str
) -> bool:
    """Download a mod from CurseForge"""
    if not download_url:
        raise HTTPException(400, "Download URL not available - mod may require manual download")
    
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(download_url)
        if response.status_code != 200:
            raise HTTPException(500, f"Failed to download: {response.status_code}")
        
        install_path.mkdir(parents=True, exist_ok=True)
        file_path = install_path / filename
        
        with open(file_path, "wb") as f:
            f.write(response.content)
        
        # If it's a zip, extract it
        if filename.endswith(".zip"):
            try:
                extract_dir = install_path / filename.replace(".zip", "")
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(extract_dir)
                # Optionally remove the zip after extraction
                # file_path.unlink()
            except Exception:
                pass  # Keep the zip if extraction fails
        
        return True

# =============================================================================
# STEAM WORKSHOP API
# =============================================================================

STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")

async def search_workshop(appid: int, search_text: str, page: int = 1) -> Dict[str, Any]:
    """Search Steam Workshop for mods"""
    # Steam Workshop Web API
    url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
    
    params = {
        "key": STEAM_API_KEY,
        "query_type": 9,  # All public files
        "page": page,
        "numperpage": 20,
        "appid": appid,
        "search_text": search_text,
        "return_tags": True,
        "return_metadata": True,
        "return_previews": True,
        "return_short_description": True,
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        # If no API key, use alternative scraping method
        if not STEAM_API_KEY:
            return await scrape_workshop(appid, search_text, page)
        
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return await scrape_workshop(appid, search_text, page)
        
        data = response.json()
        files = data.get("response", {}).get("publishedfiledetails", [])
        
        return {
            "results": [{
                "id": f["publishedfileid"],
                "title": f.get("title", "Unknown"),
                "description": f.get("short_description", ""),
                "preview_url": f.get("preview_url", ""),
                "subscriptions": f.get("subscriptions", 0),
                "file_size": f.get("file_size", 0),
                "time_updated": f.get("time_updated", 0),
                "tags": [t.get("tag", "") for t in f.get("tags", [])],
                "source": "workshop"
            } for f in files],
            "total": data.get("response", {}).get("total", 0)
        }

async def scrape_workshop(appid: int, search_text: str, page: int = 1) -> Dict[str, Any]:
    """Fallback: scrape workshop if no API key"""
    url = f"https://steamcommunity.com/workshop/browse/"
    params = {
        "appid": appid,
        "searchtext": search_text,
        "p": page,
        "browsesort": "trend",
        "section": "readytouseitems"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, params=params)
            # Basic HTML parsing for workshop items
            html = response.text
            items = []
            
            # Extract workshop item IDs and titles from HTML
            import re
            pattern = r'href="https://steamcommunity\.com/sharedfiles/filedetails/\?id=(\d+)"[^>]*>([^<]+)</a>'
            matches = re.findall(pattern, html)
            
            for workshop_id, title in matches[:20]:
                items.append({
                    "id": workshop_id,
                    "title": title.strip(),
                    "description": "",
                    "preview_url": f"https://steamuserimages-a.akamaihd.net/ugc/{workshop_id}/preview.jpg",
                    "subscriptions": 0,
                    "source": "workshop"
                })
            
            return {"results": items, "total": len(items)}
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e)}

async def get_workshop_item_details(workshop_id: str) -> Dict[str, Any]:
    """Get details for a specific workshop item"""
    url = "https://api.steampowered.com/IPublishedFileService/GetDetails/v1/"
    
    params = {
        "key": STEAM_API_KEY,
        "publishedfileids[0]": workshop_id,
        "includetags": True,
        "includeadditionalpreviews": True,
        "includechildren": True,
        "includekvtags": True,
        "includevotes": True,
        "short_description": True,
        "includeforsaledata": False,
        "includemetadata": True,
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        if not STEAM_API_KEY:
            # Fallback to scraping details page
            return {"id": workshop_id, "title": f"Workshop Item {workshop_id}"}
        
        response = await client.get(url, params=params)
        if response.status_code != 200:
            raise HTTPException(500, "Failed to fetch workshop item details")
        
        data = response.json()
        details = data.get("response", {}).get("publishedfiledetails", [{}])[0]
        
        return {
            "id": details.get("publishedfileid"),
            "title": details.get("title", "Unknown"),
            "description": details.get("description", ""),
            "preview_url": details.get("preview_url", ""),
            "file_url": details.get("file_url", ""),
            "file_size": details.get("file_size", 0),
            "subscriptions": details.get("subscriptions", 0),
            "favorited": details.get("favorited", 0),
            "time_created": details.get("time_created", 0),
            "time_updated": details.get("time_updated", 0),
            "tags": [t.get("tag", "") for t in details.get("tags", [])],
            "dependencies": details.get("children", [])
        }

# =============================================================================
# THUNDERSTORE API
# =============================================================================

THUNDERSTORE_API = "https://thunderstore.io/api/experimental"

async def search_thunderstore(community: str, search: str = "", page: int = 1) -> Dict[str, Any]:
    """Search Thunderstore for mods"""
    url = f"{THUNDERSTORE_API}/community/{community}/packages/"
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return {"results": [], "total": 0}
            
            packages = response.json()
            
            # Filter by search term if provided
            if search:
                search_lower = search.lower()
                packages = [
                    p for p in packages 
                    if search_lower in p.get("name", "").lower() 
                    or search_lower in p.get("owner", "").lower()
                    or search_lower in (p.get("description") or "").lower()
                ]
            
            # Sort by downloads
            packages.sort(key=lambda x: x.get("total_downloads", 0), reverse=True)
            
            # Paginate
            per_page = 20
            start = (page - 1) * per_page
            end = start + per_page
            paginated = packages[start:end]
            
            results = []
            for pkg in paginated:
                latest = pkg.get("latest", {})
                results.append({
                    "id": f"{pkg.get('owner')}-{pkg.get('name')}",
                    "namespace": pkg.get("owner", ""),
                    "name": pkg.get("name", ""),
                    "title": pkg.get("name", "").replace("_", " ").replace("-", " "),
                    "description": latest.get("description", ""),
                    "version": latest.get("version_number", ""),
                    "downloads": pkg.get("total_downloads", 0),
                    "rating": pkg.get("rating_score", 0),
                    "icon_url": latest.get("icon", ""),
                    "dependencies": latest.get("dependencies", []),
                    "categories": pkg.get("categories", []),
                    "date_updated": pkg.get("date_updated", ""),
                    "source": "thunderstore"
                })
            
            return {
                "results": results,
                "total": len(packages),
                "page": page,
                "per_page": per_page
            }
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e)}

async def get_thunderstore_package(community: str, namespace: str, name: str) -> Dict[str, Any]:
    """Get details for a specific Thunderstore package"""
    url = f"{THUNDERSTORE_API}/package/{namespace}/{name}/"
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        if response.status_code != 200:
            raise HTTPException(404, f"Package {namespace}/{name} not found")
        
        pkg = response.json()
        latest = pkg.get("latest", {})
        
        return {
            "namespace": pkg.get("owner", namespace),
            "name": pkg.get("name", name),
            "description": latest.get("description", ""),
            "version": latest.get("version_number", ""),
            "download_url": latest.get("download_url", ""),
            "dependencies": latest.get("dependencies", []),
            "file_size": latest.get("file_size", 0),
            "downloads": pkg.get("total_downloads", 0),
            "rating": pkg.get("rating_score", 0),
            "versions": [
                {
                    "version": v.get("version_number"),
                    "download_url": v.get("download_url"),
                    "downloads": v.get("downloads", 0),
                    "date_created": v.get("date_created")
                }
                for v in pkg.get("versions", [])[:10]
            ]
        }

async def download_thunderstore_mod(
    download_url: str, 
    install_path: Path,
    mod_name: str
) -> bool:
    """Download and extract a Thunderstore mod"""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(download_url)
        if response.status_code != 200:
            raise HTTPException(500, f"Failed to download mod: {response.status_code}")
        
        # Create temp file
        temp_zip = install_path / f"{mod_name}.zip"
        mod_dir = install_path / mod_name
        
        install_path.mkdir(parents=True, exist_ok=True)
        
        with open(temp_zip, "wb") as f:
            f.write(response.content)
        
        # Extract
        try:
            with zipfile.ZipFile(temp_zip, "r") as zf:
                # Check for plugins folder inside zip
                namelist = zf.namelist()
                
                # Thunderstore mods often have plugins/ folder
                if any(n.startswith("plugins/") for n in namelist):
                    # Extract only plugins content
                    for name in namelist:
                        if name.startswith("plugins/") and not name.endswith("/"):
                            # Get the relative path after plugins/
                            target = install_path / name[8:]  # Skip "plugins/"
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(name) as src, open(target, "wb") as dst:
                                dst.write(src.read())
                else:
                    # Extract to mod folder
                    mod_dir.mkdir(parents=True, exist_ok=True)
                    zf.extractall(mod_dir)
        finally:
            # Clean up zip
            if temp_zip.exists():
                temp_zip.unlink()
        
        return True

# =============================================================================
# API ROUTES
# =============================================================================

@router.get("/sources/{game_slug}")
async def get_mod_sources(game_slug: str, current_user=Depends(get_current_user)):
    """Get available mod sources for a game"""
    sources = get_mod_source_for_game(game_slug)
    
    return {
        "game": game_slug,
        "sources": {
            "workshop": {
                "available": sources["workshop"],
                "config": sources["workshop_config"]
            },
            "thunderstore": {
                "available": sources["thunderstore"],
                "config": sources["thunderstore_config"]
            }
        }
    }

@router.get("/workshop/search")
async def search_workshop_mods(
    appid: int = Query(..., description="Steam App ID"),
    q: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    current_user=Depends(get_current_user)
):
    """Search Steam Workshop for mods"""
    results = await search_workshop(appid, q, page)
    return results

@router.get("/workshop/item/{workshop_id}")
async def get_workshop_item(
    workshop_id: str,
    current_user=Depends(get_current_user)
):
    """Get details for a Steam Workshop item"""
    return await get_workshop_item_details(workshop_id)

@router.get("/thunderstore/search")
async def search_thunderstore_mods(
    community: str = Query(..., description="Thunderstore community slug"),
    q: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    current_user=Depends(get_current_user)
):
    """Search Thunderstore for mods"""
    results = await search_thunderstore(community, q, page)
    return results

@router.get("/thunderstore/package/{namespace}/{name}")
async def get_thunderstore_mod(
    namespace: str,
    name: str,
    current_user=Depends(get_current_user)
):
    """Get details for a Thunderstore package"""
    # Determine community from request context or default
    return await get_thunderstore_package("valheim", namespace, name)

@router.post("/thunderstore/install")
async def install_thunderstore_mod(
    request: ThunderstoreInstallRequest,
    current_user=Depends(require_moderator)
):
    """Install a mod from Thunderstore"""
    config = THUNDERSTORE_GAMES.get(request.game_slug)
    if not config:
        raise HTTPException(400, f"Game {request.game_slug} not supported for Thunderstore mods")
    
    # Get package details
    pkg = await get_thunderstore_package(
        config["community"],
        request.namespace,
        request.name
    )
    
    # Determine install path
    server_path = get_server_path(request.server_id)
    mod_path = server_path / config["mod_path"].lstrip("/")
    
    # Install dependencies first if requested
    installed = []
    if request.install_dependencies and pkg.get("dependencies"):
        for dep in pkg["dependencies"]:
            # Parse dependency string: owner-name-version
            parts = dep.split("-")
            if len(parts) >= 3:
                dep_namespace = parts[0]
                dep_name = parts[1]
                dep_version = "-".join(parts[2:])
                
                # Skip BepInEx dependency (handled separately)
                if "BepInEx" in dep_name or "BepInExPack" in dep_name:
                    continue
                
                try:
                    dep_pkg = await get_thunderstore_package(
                        config["community"],
                        dep_namespace,
                        dep_name
                    )
                    await download_thunderstore_mod(
                        dep_pkg["download_url"],
                        mod_path,
                        f"{dep_namespace}-{dep_name}"
                    )
                    installed.append(f"{dep_namespace}-{dep_name}")
                except Exception as e:
                    # Log but continue
                    pass
    
    # Install main mod
    download_url = f"https://thunderstore.io/package/download/{request.namespace}/{request.name}/{request.version}/"
    await download_thunderstore_mod(
        download_url,
        mod_path,
        f"{request.namespace}-{request.name}"
    )
    installed.append(f"{request.namespace}-{request.name}")
    
    return {
        "success": True,
        "installed": installed,
        "path": str(mod_path),
        "message": f"Installed {len(installed)} mod(s)"
    }

@router.get("/installed/{server_id}")
async def list_installed_mods(
    server_id: str,
    game_slug: str = Query(...),
    current_user=Depends(get_current_user)
):
    """List installed mods for a server"""
    # Determine mod path based on game
    mod_path = None
    
    if game_slug in THUNDERSTORE_GAMES:
        config = THUNDERSTORE_GAMES[game_slug]
        server_path = get_server_path(server_id)
        mod_path = server_path / config["mod_path"].lstrip("/")
    elif game_slug in WORKSHOP_GAMES:
        config = WORKSHOP_GAMES[game_slug]
        server_path = get_server_path(server_id)
        mod_path = server_path / config["mod_path"].lstrip("/")
    else:
        raise HTTPException(400, f"Game {game_slug} not supported")
    
    if not mod_path.exists():
        return {"mods": [], "path": str(mod_path)}
    
    mods = []
    for item in mod_path.iterdir():
        if item.is_dir():
            # Check for manifest
            manifest = item / "manifest.json"
            if manifest.exists():
                try:
                    import json
                    with open(manifest) as f:
                        data = json.load(f)
                    mods.append({
                        "name": data.get("name", item.name),
                        "version": data.get("version_number", "unknown"),
                        "description": data.get("description", ""),
                        "folder": item.name,
                        "type": "thunderstore"
                    })
                    continue
                except:
                    pass
            
            mods.append({
                "name": item.name,
                "version": "unknown",
                "folder": item.name,
                "type": "folder"
            })
        elif item.suffix in [".dll", ".zip", ".pak"]:
            mods.append({
                "name": item.stem,
                "file": item.name,
                "size": item.stat().st_size,
                "type": "file"
            })
    
    return {"mods": mods, "path": str(mod_path)}

@router.delete("/uninstall")
async def uninstall_mod(
    request: ModUninstallRequest,
    current_user=Depends(require_moderator)
):
    """Uninstall a mod from a server"""
    # Determine mod path
    if request.game_slug in THUNDERSTORE_GAMES:
        config = THUNDERSTORE_GAMES[request.game_slug]
    elif request.game_slug in WORKSHOP_GAMES:
        config = WORKSHOP_GAMES[request.game_slug]
    else:
        raise HTTPException(400, f"Game {request.game_slug} not supported")
    
    server_path = get_server_path(request.server_id)
    mod_path = server_path / config["mod_path"].lstrip("/") / request.mod_name
    
    if mod_path.exists():
        if mod_path.is_dir():
            shutil.rmtree(mod_path)
        else:
            mod_path.unlink()
        return {"success": True, "message": f"Uninstalled {request.mod_name}"}
    
    # Try as file
    for ext in [".dll", ".zip", ".pak"]:
        file_path = server_path / config["mod_path"].lstrip("/") / f"{request.mod_name}{ext}"
        if file_path.exists():
            file_path.unlink()
            return {"success": True, "message": f"Uninstalled {request.mod_name}"}
    
    raise HTTPException(404, f"Mod {request.mod_name} not found")

@router.get("/supported-games")
async def get_supported_games(current_user=Depends(get_current_user)):
    """Get list of games with mod support"""
    games = []
    
    for slug, config in WORKSHOP_GAMES.items():
        games.append({
            "slug": slug,
            "source": "workshop",
            "appid": config["appid"],
            "mod_path": config["mod_path"]
        })
    
    for slug, config in THUNDERSTORE_GAMES.items():
        games.append({
            "slug": slug,
            "source": "thunderstore",
            "community": config["community"],
            "mod_path": config["mod_path"],
            "bepinex_required": config.get("bepinex_required", False)
        })
    
    for slug, config in CURSEFORGE_GAMES.items():
        games.append({
            "slug": slug,
            "name": config["name"],
            "source": "curseforge",
            "game_id": config["game_id"],
            "mod_path": config["mod_path"]
        })
    
    return {"games": games}

@router.post("/bepinex/install")
async def install_bepinex(
    server_id: str = Query(...),
    game_slug: str = Query(...),
    current_user=Depends(require_moderator)
):
    """Install BepInEx mod loader for a game"""
    config = THUNDERSTORE_GAMES.get(game_slug)
    if not config:
        raise HTTPException(400, f"Game {game_slug} not supported")
    
    if not config.get("bepinex_required"):
        return {"success": True, "message": "BepInEx not required for this game"}
    
    server_path = get_server_path(server_id)
    
    # Download BepInEx
    bepinex_url = config.get("bepinex_url", "https://thunderstore.io/package/download/BepInEx/BepInExPack/5.4.2100/")
    
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(bepinex_url)
        if response.status_code != 200:
            raise HTTPException(500, "Failed to download BepInEx")
        
        temp_zip = server_path / "bepinex.zip"
        with open(temp_zip, "wb") as f:
            f.write(response.content)
        
        try:
            with zipfile.ZipFile(temp_zip, "r") as zf:
                zf.extractall(server_path)
        finally:
            temp_zip.unlink()
    
    return {
        "success": True,
        "message": "BepInEx installed successfully",
        "path": str(server_path)
    }

# ============================================================================
# CURSEFORGE API ROUTES
# ============================================================================

@router.get("/curseforge/games")
async def get_curseforge_games(current_user=Depends(get_current_user)):
    """Get list of games supported on CurseForge"""
    games = []
    for slug, config in CURSEFORGE_GAMES.items():
        games.append({
            "slug": slug,
            "name": config["name"],
            "game_id": config["game_id"],
            "mod_path": config["mod_path"]
        })
    return {"games": games, "total": len(games)}


@router.get("/curseforge/search")
async def curseforge_search_mods(
    game_slug: str = Query(..., description="Game slug like 'palworld', 'terraria'"),
    query: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    sort_field: int = Query(2, description="Sort field: 1=Featured, 2=Popularity, 3=LastUpdated, 4=Name, 5=Author, 6=TotalDownloads"),
    current_user=Depends(get_current_user)
):
    """Search mods on CurseForge for a specific game"""
    if game_slug not in CURSEFORGE_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported on CurseForge. Supported: {list(CURSEFORGE_GAMES.keys())}")
    
    game_config = CURSEFORGE_GAMES[game_slug]
    result = await search_curseforge(
        game_id=game_config["game_id"],
        search=query,
        page=page,
        class_id=game_config.get("class_ids", [None])[0] if game_config.get("class_ids") else None
    )
    
    return {
        "mods": result.get("results", []),
        "total": result.get("total", 0),
        "page": page,
        "game": game_slug,
        "source": "curseforge"
    }


@router.get("/curseforge/mod/{mod_id}")
async def curseforge_get_mod(
    mod_id: int,
    current_user=Depends(get_current_user)
):
    """Get detailed information about a specific CurseForge mod"""
    mod = await get_curseforge_mod(mod_id)
    if not mod:
        raise HTTPException(404, f"Mod with ID {mod_id} not found")
    return {"mod": mod, "source": "curseforge"}


@router.get("/curseforge/mod/{mod_id}/files")
async def curseforge_get_mod_files(
    mod_id: int,
    game_version: str = Query(None, description="Filter by game version"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    current_user=Depends(get_current_user)
):
    """Get files available for a CurseForge mod"""
    files = await get_curseforge_mod_files(mod_id)
    
    # Filter by game version if specified
    if game_version:
        files = [f for f in files if game_version in f.get("game_versions", [])]
    
    # Paginate
    start = (page - 1) * page_size
    end = start + page_size
    paginated = files[start:end]
    
    return {"files": paginated, "total": len(files), "page": page}


@router.post("/curseforge/install")
async def curseforge_install_mod(
    request: CurseForgeInstallRequest,
    current_user=Depends(require_moderator)
):
    """Install a mod from CurseForge"""
    if request.game_slug not in CURSEFORGE_GAMES:
        raise HTTPException(400, f"Game '{request.game_slug}' not supported on CurseForge")
    
    config = CURSEFORGE_GAMES[request.game_slug]
    server_path = get_server_path(request.server_id)
    mod_path = server_path / config["mod_path"].lstrip("/")
    
    # Create mod directory if needed
    mod_path.mkdir(parents=True, exist_ok=True)
    
    # First, get the file info to get download URL
    url = f"{CURSEFORGE_API}/mods/{request.mod_id}/files/{request.file_id}"
    headers = {
        "x-api-key": CURSEFORGE_API_KEY,
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(500, f"Failed to get file info: HTTP {response.status_code}")
        
        file_data = response.json().get("data", {})
        download_url = file_data.get("downloadUrl")
        filename = file_data.get("fileName", f"mod_{request.mod_id}_{request.file_id}.jar")
        
        if not download_url:
            raise HTTPException(400, "Download URL not available - mod may require manual download from CurseForge")
    
    # Download the mod
    result = await download_curseforge_mod(
        download_url=download_url,
        install_path=mod_path,
        filename=filename
    )
    
    return {
        "success": True,
        "message": f"Installed {filename} to {mod_path}",
        "path": str(mod_path / filename),
        "filename": filename,
        "source": "curseforge"
    }


@router.get("/curseforge/categories/{game_slug}")
async def curseforge_get_categories(
    game_slug: str,
    current_user=Depends(get_current_user)
):
    """Get mod categories for a CurseForge game"""
    if game_slug not in CURSEFORGE_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported on CurseForge")
    
    game_id = CURSEFORGE_GAMES[game_slug]["game_id"]
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{CURSEFORGE_API_BASE}/categories",
            params={"gameId": game_id},
            headers={"x-api-key": CURSEFORGE_API_KEY}
        )
        
        if response.status_code != 200:
            return {"categories": [], "error": "Failed to fetch categories"}
        
        data = response.json()
        return {"categories": data.get("data", []), "game": game_slug}