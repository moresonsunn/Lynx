from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from server_providers.providers import get_provider_names, get_provider
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/server-types")
def list_server_types():
    """Return all available server provider types (e.g. vanilla, paper, fabric, purpur, forge, neoforge)."""
    try:
        names = sorted(get_provider_names())
        return {"types": names}
    except Exception as e:
        logger.error(f"Failed to list server types: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/server-types/{server_type}/versions")
def list_server_type_versions(server_type: str):
    """Return all known versions for a given server type."""
    try:
        provider = get_provider(server_type)
        versions = provider.list_versions()
        # Limit extremely long lists to something reasonable but include total count
        truncated = versions[:500]
        return {"type": server_type, "count": len(versions), "versions": truncated, "truncated": len(truncated) < len(versions)}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to list versions for {server_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/server-types/{server_type}/loader-versions")
def list_loader_versions(
    server_type: str,
    version: str = Query(..., description="Minecraft version to get loader versions for")
):
    """
    Return all available loader versions for modded server types (fabric, forge, neoforge).
    
    For Fabric: Returns loader versions and installer versions
    For Forge: Returns Forge versions (recommended/latest marked)
    For NeoForge: Returns NeoForge versions
    """
    try:
        provider = get_provider(server_type)
        
        # Check if provider supports loader versions
        if not hasattr(provider, 'list_loader_versions'):
            raise HTTPException(
                status_code=400, 
                detail=f"Server type '{server_type}' does not support loader versions"
            )
        
        loader_versions = provider.list_loader_versions(version)
        
        result = {
            "type": server_type,
            "minecraft_version": version,
            "loader_versions": loader_versions,
            "count": len(loader_versions),
        }
        
        # For Fabric, also include installer versions
        if server_type == "fabric" and hasattr(provider, 'get_installer_versions'):
            try:
                installers = provider.get_installer_versions()
                installer_versions = [i.get("version") for i in installers if i.get("version")]
                result["installer_versions"] = installer_versions
                
                # Get latest stable installer
                if hasattr(provider, 'get_latest_installer_version'):
                    result["latest_installer_version"] = provider.get_latest_installer_version()
            except Exception as e:
                logger.warning(f"Could not fetch installer versions: {e}")
        
        # For Forge, mark recommended/latest versions
        if server_type == "forge":
            try:
                if hasattr(provider, 'get_recommended_forge_version'):
                    result["recommended_version"] = provider.get_recommended_forge_version(version)
                if hasattr(provider, 'get_latest_forge_version'):
                    result["latest_version"] = provider.get_latest_forge_version(version)
            except Exception as e:
                logger.warning(f"Could not fetch Forge promotions: {e}")
        
        # For NeoForge, mark latest version
        if server_type == "neoforge":
            try:
                if hasattr(provider, 'get_latest_neoforge_version'):
                    result["latest_version"] = provider.get_latest_neoforge_version(version)
            except Exception as e:
                logger.warning(f"Could not fetch NeoForge latest: {e}")
        
        return result
        
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list loader versions for {server_type}/{version}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Alias endpoints under /api prefix to mitigate aggressive browser extensions blocking plain paths ---
@router.get("/api/server-types")
def list_server_types_api():
    return list_server_types()

@router.get("/api/server-types/{server_type}/versions")
def list_server_type_versions_api(server_type: str):
    return list_server_type_versions(server_type)

@router.get("/api/server-types/{server_type}/loader-versions")
def list_loader_versions_api(
    server_type: str,
    version: str = Query(..., description="Minecraft version to get loader versions for")
):
    return list_loader_versions(server_type, version)
