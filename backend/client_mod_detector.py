"""
Client-only mod detection and removal for CurseForge modpack installation.

This module provides utilities to:
1. Detect client-only mods using multiple strategies
2. Remove client-only mods from a server directory
3. Provide a configurable blacklist of known client-only mods
"""

from __future__ import annotations
import os
import json
import zipfile
import logging
import shutil
from pathlib import Path
from typing import List, Set, Dict, Any, Optional, Callable

log = logging.getLogger(__name__)

# Default blacklist of known client-only mod IDs (CurseForge project IDs)
# These are commonly used client-only mods that should never be installed on a server
DEFAULT_CLIENT_ONLY_PROJECT_IDS: Set[int] = {
    # Client-side rendering/performance
    303583,  # Sodium
    304371,  # Iris Shaders
    238222,  # OptiFine (classic)
    447791,  # OptiFabric
    381781,  # Canvas Renderer
    442527,  # Sodium Extra
    
    # UI/Client-side only
    318443,  # Controlling (keybinds UI)
    319518,  # Mod Menu
    314749,  # Roughly Enough Items (REI) - client side
    280766,  # Just Enough Items (JEI) - has server component but often client-only in packs
    310704,  # EMI (Enchantment Menu Interface)
    313612,  # Inventory HUD+
    315717,  # Xaero's Minimap
    315718,  # Xaero's World Map
    318424,  # JourneyMap
    325630,  # VoxelMap
    318421,  # AppleSkin
    318422,  # Hwyla / Waila
    318423,  # The One Probe
    318425,  # Inventory Tweaks
    318426,  # Mouse Tweaks
    318427,  # Controlling
    
    # Shaders/Visual
    318428,  # Shaders mod
    318429,  # OptiFine HD
    318430,  # Better Foliage
    318431,  # Dynamic Lights
    
    # Map/Waypoint mods
    318432,  # Map Writer
    318433,  # Antique Atlas
    318434,  # JourneyMap (duplicate)
    
    # Client-side tweaks
    318435,  # Custom Main Menu
    318436,  # Resource Loader
    318437,  # Better Third Person
    318438,  # Perspective Mod
    318439,  # Zoom Mod
    318440,  # Fullbright
    318441,  # Gamma Utils
    
    # Sound/Music (client only)
    318442,  # Ambient Sounds
    318443,  # Dynamic Surroundings
    318444,  # Presence Footsteps
}

# Known client-only mod name patterns (case-insensitive)
CLIENT_ONLY_NAME_PATTERNS = [
    "sodium",
    "iris",
    "optifine",
    "optifabric",
    "canvas",
    "controlling",
    "modmenu",
    "roughly enough items",
    "rei",
    "jei",
    "emi",
    "inventory hud",
    "xaero",
    "journeymap",
    "voxelmap",
    "appleskin",
    "hwyla",
    "waila",
    "the one probe",
    "inventory tweaks",
    "mouse tweaks",
    "shader",
    "better foliage",
    "dynamic lights",
    "mapwriter",
    "antique atlas",
    "custom main menu",
    "resource loader",
    "better third person",
    "perspective",
    "zoom",
    "fullbright",
    "gamma",
    "ambient sounds",
    "dynamic surroundings",
    "presence footsteps",
    "fabric loader",  # fabric loader itself shouldn't be in mods folder
    "fabric api",     # fabric api is needed but usually auto-installed
]

# Mod filename patterns that indicate client-only
CLIENT_ONLY_FILENAME_PATTERNS = [
    "client",
    "shader",
    "optifine",
    "iris",
    "sodium",
]

# JAR metadata patterns that indicate client-only
CLIENT_ONLY_JAR_INDICATORS = {
    "fabric.mod.json": ["environment", "client"],
    "quilt.mod.json": ["environment", "client"],
    "mods.toml": ["clientsideonly", "true"],
    "META-INF/mods.toml": ["clientsideonly", "true"],
    "META-INF/neoforge.mods.toml": ["clientsideonly", "true"],
}


def load_client_only_config() -> Dict[str, Any]:
    """Load client-only mod configuration from environment or defaults."""
    config = {
        "project_ids": DEFAULT_CLIENT_ONLY_PROJECT_IDS.copy(),
        "name_patterns": CLIENT_ONLY_NAME_PATTERNS.copy(),
        "filename_patterns": CLIENT_ONLY_FILENAME_PATTERNS.copy(),
        "jar_indicators": CLIENT_ONLY_JAR_INDICATORS.copy(),
    }
    
    # Load additional project IDs from environment
    extra_ids = os.getenv("CLIENT_ONLY_PROJECT_IDS", "")
    if extra_ids:
        try:
            for pid in extra_ids.split(","):
                pid = pid.strip()
                if pid.isdigit():
                    config["project_ids"].add(int(pid))
        except Exception:
            pass
    
    # Load additional name patterns from environment
    extra_patterns = os.getenv("CLIENT_ONLY_NAME_PATTERNS", "")
    if extra_patterns:
        for pat in extra_patterns.split(","):
            pat = pat.strip().lower()
            if pat:
                config["name_patterns"].append(pat)
    
    return config


def is_client_only_jar(jar_path: Path, config: Dict[str, Any]) -> bool:
    """
    Check if a JAR file is client-only by inspecting its metadata.
    
    Checks:
    1. fabric.mod.json / quilt.mod.json for environment=client
    2. mods.toml / neoforge.mods.toml for clientsideonly=true
    """
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            # Check fabric.mod.json
            for meta_file in ("fabric.mod.json", "quilt.mod.json"):
                if meta_file in zf.namelist():
                    try:
                        data = json.loads(zf.read(meta_file).decode('utf-8', errors='ignore'))
                        env = str(data.get("environment", "")).lower()
                        if env == "client":
                            return True
                    except Exception:
                        pass
            
            # Check mods.toml (Forge/NeoForge)
            for toml_file in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml", "mods.toml"):
                if toml_file in zf.namelist():
                    try:
                        content = zf.read(toml_file).decode('utf-8', errors='ignore').lower()
                        if "clientsideonly" in content.replace(" ", "") and "true" in content:
                            return True
                    except Exception:
                        pass
    except Exception:
        pass
    return False


def is_client_only_by_name(filename: str, config: Dict[str, Any]) -> bool:
    """Check if a mod is client-only based on filename patterns."""
    name_lower = filename.lower()
    
    # Check filename patterns
    for pattern in config.get("filename_patterns", []):
        if pattern.lower() in name_lower:
            return True
    
    # Check name patterns (more comprehensive)
    for pattern in config.get("name_patterns", []):
        if pattern.lower() in name_lower:
            return True
    
    return False


def is_client_only_by_project_id(project_id: int, config: Dict[str, Any]) -> bool:
    """Check if a mod is client-only based on CurseForge project ID."""
    return project_id in config.get("project_ids", set())


def detect_client_only_mods(server_dir: Path, config: Optional[Dict[str, Any]] = None, 
                            push_event: Optional[Callable] = None) -> Dict[str, Any]:
    """
    Detect client-only mods in a server directory.
    
    Returns a summary with:
    - client_only_mods: list of detected client-only mod paths
    - total_mods: total number of mods scanned
    - detection_methods: which methods detected each mod
    """
    if config is None:
        config = load_client_only_config()
    
    mods_dir = server_dir / "mods"
    if not mods_dir.exists() or not mods_dir.is_dir():
        return {"client_only_mods": [], "total_mods": 0, "detection_methods": {}}
    
    client_only_mods = []
    detection_methods = {}
    total_mods = 0
    
    for jar_file in mods_dir.glob("*.jar"):
        total_mods += 1
        methods = []
        
        # Method 1: JAR metadata inspection
        if is_client_only_jar(jar_file, config):
            methods.append("jar_metadata")
        
        # Method 2: Filename/name patterns
        if is_client_only_by_name(jar_file.name, config):
            methods.append("name_pattern")
        
        # Method 3: Could add project ID lookup via API if available
        
        if methods:
            client_only_mods.append({
                "path": str(jar_file),
                "name": jar_file.name,
                "methods": methods
            })
            detection_methods[jar_file.name] = methods
            
            if push_event:
                push_event({
                    "type": "progress",
                    "step": "client_mod_detection",
                    "message": f"Detected client-only mod: {jar_file.name} ({', '.join(methods)})",
                    "progress": 60
                })
    
    return {
        "client_only_mods": client_only_mods,
        "total_mods": total_mods,
        "detection_methods": detection_methods
    }


def remove_client_only_mods(server_dir: Path, 
                            client_only_mods: List[Dict[str, Any]],
                            push_event: Optional[Callable] = None,
                            dry_run: bool = False) -> int:
    """
    Remove detected client-only mods by moving them to mods-disabled-client/.
    
    Returns the number of mods removed.
    """
    mods_dir = server_dir / "mods"
    disabled_dir = server_dir / "mods-disabled-client"
    
    if not dry_run:
        disabled_dir.mkdir(parents=True, exist_ok=True)
    
    removed = 0
    for mod_info in client_only_mods:
        src_path = Path(mod_info["path"])
        if not src_path.exists():
            continue
        
        dest_path = disabled_dir / src_path.name
        
        if not dry_run:
            try:
                shutil.move(str(src_path), str(dest_path))
                removed += 1
                log.info("Moved client-only mod to disabled: %s", src_path.name)
                if push_event:
                    push_event({
                        "type": "progress",
                        "step": "client_mod_removal",
                        "message": f"Disabled client-only mod: {src_path.name}",
                        "progress": 62
                    })
            except Exception as e:
                log.error("Failed to move client-only mod %s: %s", src_path.name, e)
        else:
            removed += 1
    
    return removed


def process_client_pack(server_dir: Path, 
                        push_event: Optional[Callable] = None,
                        dry_run: bool = False,
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Process a client pack to make it server-ready:
    1. Detect client-only mods
    2. Remove them to mods-disabled-client/
    3. Return summary
    """
    if config is None:
        config = load_client_only_config()
    
    # Detect client-only mods
    detection_result = detect_client_only_mods(server_dir, config, push_event)
    
    # Remove client-only mods
    removed = remove_client_only_mods(
        server_dir, 
        detection_result["client_only_mods"], 
        push_event, 
        dry_run
    )
    
    return {
        "detected": len(detection_result["client_only_mods"]),
        "removed": removed,
        "total_mods": detection_result["total_mods"],
        "details": detection_result["client_only_mods"]
    }


# Example usage for manual testing
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        server_dir = Path(sys.argv[1])
        result = process_client_pack(server_dir)
        print(f"Total mods: {result['total_mods']}")
        print(f"Client-only detected: {result['detected']}")
        print(f"Removed: {result['removed']}")
        for mod in result['details']:
            print(f"  - {mod['name']} ({', '.join(mod['methods'])})")