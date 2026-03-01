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
from integrations_store import get_integration_key as _store_key

router = APIRouter(prefix="/steam-mods", tags=["Steam Mods"])

# =============================================================================
# SAFE ZIP EXTRACTION (Zip Slip protection)
# =============================================================================

def _safe_extractall(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract ZIP with path-traversal protection (Zip Slip prevention)."""
    resolved_target = target_dir.resolve()
    for member in zf.namelist():
        member_path = (target_dir / member).resolve()
        if not str(member_path).startswith(str(resolved_target)):
            raise ValueError(f"Zip Slip detected – refusing to extract: {member}")
    zf.extractall(target_dir)


def _safe_extract_member(zf: zipfile.ZipFile, name: str, target_dir: Path) -> Path:
    """Extract a single ZIP member with path-traversal protection."""
    resolved_target = target_dir.resolve()
    member_path = (target_dir / name).resolve()
    if not str(member_path).startswith(str(resolved_target)):
        raise ValueError(f"Zip Slip detected – refusing to extract: {name}")
    member_path.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(name) as src, open(member_path, "wb") as dst:
        dst.write(src.read())
    return member_path

# =============================================================================
# EXTERNAL API KEYS
# =============================================================================

def _api_key(provider: str) -> str:
    """Resolve API key: env var takes precedence, then integration store."""
    env_name = f"{provider.upper()}_API_KEY"
    return os.environ.get(env_name, "") or _store_key(provider) or ""

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
    # Enshrouded - 85767
    "enshrouded": {
        "game_id": 85767,
        "mod_path": "/BepInEx/plugins",
        "name": "Enshrouded"
    },
    # The Forest - 60028
    "the_forest": {
        "game_id": 60028,
        "mod_path": "/Mods",
        "name": "The Forest"
    },
    # Conan Exiles - 58498
    "conan_exiles": {
        "game_id": 58498,
        "mod_path": "/ConanSandbox/Mods",
        "name": "Conan Exiles"
    },
    # Project Zomboid - NOT on CurseForge; use Steam Workshop (app 108600) instead
    # "project_zomboid": { ... },  # removed: 78135 was V Rising's ID, not PZ
    # Don't Starve Together - 4525
    "dont_starve_together": {
        "game_id": 4525,
        "mod_path": "/mods",
        "name": "Don't Starve Together"
    },
    # Factorio - 79148
    "factorio": {
        "game_id": 79148,
        "mod_path": "/mods",
        "name": "Factorio"
    },
    # Rust - 69162
    "rust": {
        "game_id": 69162,
        "mod_path": "/oxide/plugins",
        "name": "Rust"
    },
    # DayZ - 82002
    "dayz": {
        "game_id": 82002,
        "mod_path": "/mods",
        "name": "DayZ"
    },
    # Eco - 79501
    "eco": {
        "game_id": 79501,
        "mod_path": "/Mods",
        "name": "Eco"
    },
    # Unturned - 79744
    "unturned": {
        "game_id": 79744,
        "mod_path": "/Modules",
        "name": "Unturned"
    },
}

# =============================================================================
# NEXUS MODS - Game domain mappings
# API Reference: https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0
# =============================================================================

NEXUS_GAMES = {
    # Game slug -> { domain_name, mod_path, name }
    "baldurs_gate_3": {
        "domain": "baldursgate3",
        "mod_path": "/Mods",
        "name": "Baldur's Gate 3"
    },
    "bg3": {
        "domain": "baldursgate3",
        "mod_path": "/Mods",
        "name": "Baldur's Gate 3"
    },
    "skyrim": {
        "domain": "skyrimspecialedition",
        "mod_path": "/Data",
        "name": "Skyrim Special Edition"
    },
    "fallout_4": {
        "domain": "fallout4",
        "mod_path": "/Data",
        "name": "Fallout 4"
    },
    "starfield": {
        "domain": "starfield",
        "mod_path": "/Data",
        "name": "Starfield"
    },
    "cyberpunk_2077": {
        "domain": "cyberpunk2077",
        "mod_path": "/archive/pc/mod",
        "name": "Cyberpunk 2077"
    },
    "palworld": {
        "domain": "palworld",
        "mod_path": "/Pal/Content/Paks/~mods",
        "name": "Palworld"
    },
    "valheim": {
        "domain": "valheim",
        "mod_path": "/BepInEx/plugins",
        "name": "Valheim"
    },
    "stardew_valley": {
        "domain": "stardewvalley",
        "mod_path": "/Mods",
        "name": "Stardew Valley"
    },
    "7_days_to_die": {
        "domain": "7daystodie",
        "mod_path": "/Mods",
        "name": "7 Days to Die"
    },
    "sdtd": {
        "domain": "7daystodie",
        "mod_path": "/Mods",
        "name": "7 Days to Die"
    },
    "vrising": {
        "domain": "vrising",
        "mod_path": "/BepInEx/plugins",
        "name": "V Rising"
    },
    "rimworld": {
        "domain": "rimworld",
        "mod_path": "/Mods",
        "name": "RimWorld"
    },
    "conan_exiles": {
        "domain": "conanexiles",
        "mod_path": "/ConanSandbox/Mods",
        "name": "Conan Exiles"
    },
    "manor_lords": {
        "domain": "manorlords",
        "mod_path": "/ManorLords/Content/Paks/~mods",
        "name": "Manor Lords"
    },
    "lethal_company": {
        "domain": "lethalcompany",
        "mod_path": "/BepInEx/plugins",
        "name": "Lethal Company"
    },
    "among_us": {
        "domain": "amongus",
        "mod_path": "/BepInEx/plugins",
        "name": "Among Us"
    },
    "satisfactory": {
        "domain": "satisfactory",
        "mod_path": "/FactoryGame/Mods",
        "name": "Satisfactory"
    },
    "core_keeper": {
        "domain": "corekeeper",
        "mod_path": "/BepInEx/plugins",
        "name": "Core Keeper"
    },
    "sons_of_the_forest": {
        "domain": "sonsoftheforest",
        "mod_path": "/BepInEx/plugins",
        "name": "Sons of the Forest"
    },
    "enshrouded": {
        "domain": "enshrouded",
        "mod_path": "/BepInEx/plugins",
        "name": "Enshrouded"
    },
    "project_zomboid": {
        "domain": "projectzomboid",
        "mod_path": "/Zomboid/mods",
        "name": "Project Zomboid"
    },
    "the_forest": {
        "domain": "theforest",
        "mod_path": "/Mods",
        "name": "The Forest"
    },
    "rust": {
        "domain": "rust",
        "mod_path": "/oxide/plugins",
        "name": "Rust"
    },
    "terraria": {
        "domain": "terraria",
        "mod_path": "/tModLoader/Mods",
        "name": "Terraria"
    },
    "terraria_tmodloader": {
        "domain": "terraria",
        "mod_path": "/tModLoader/Mods",
        "name": "Terraria"
    },
    "ark_survival_evolved": {
        "domain": "arksurvivalevolved",
        "mod_path": "/ShooterGame/Content/Mods",
        "name": "ARK: Survival Evolved"
    },
    "ark_survival_ascended": {
        "domain": "arksurvivalascended",
        "mod_path": "/ShooterGame/Content/Mods",
        "name": "ARK: Survival Ascended"
    },
    "dayz": {
        "domain": "dayz",
        "mod_path": "/mods",
        "name": "DayZ"
    },
    "dont_starve_together": {
        "domain": "dontstarvetogether",
        "mod_path": "/mods",
        "name": "Don't Starve Together"
    },
    "garrys_mod": {
        "domain": "garysmod",
        "mod_path": "/garrysmod/addons",
        "name": "Garry's Mod"
    },
    "gmod": {
        "domain": "garysmod",
        "mod_path": "/garrysmod/addons",
        "name": "Garry's Mod"
    },
}

# =============================================================================
# MOD.IO - Game ID mappings
# API Reference: https://docs.mod.io/
# =============================================================================

MODIO_GAMES = {
    "squad": {
        "game_id": 362,
        "mod_path": "/SquadGame/Plugins/Mods",
        "name": "Squad"
    },
    "mordhau": {
        "game_id": 264,
        "mod_path": "/Mordhau/Content/Paks/~mods",
        "name": "Mordhau"
    },
    "insurgency_sandstorm": {
        "game_id": 188,
        "mod_path": "/Insurgency/Mods",
        "name": "Insurgency: Sandstorm"
    },
    "killing_floor_2": {
        "game_id": 50,
        "mod_path": "/KFGame/Cache",
        "name": "Killing Floor 2"
    },
    "conan_exiles": {
        "game_id": 42,
        "mod_path": "/ConanSandbox/Mods",
        "name": "Conan Exiles"
    },
    "eco": {
        "game_id": 6,
        "mod_path": "/Mods",
        "name": "Eco"
    },
    "unturned": {
        "game_id": 51,
        "mod_path": "/Modules",
        "name": "Unturned"
    },
}

# Games that support Steam Workshop (expanded)
WORKSHOP_GAMES = {
    "gmod": {"appid": 4000, "workshop_appid": 4000, "mod_path": "/garrysmod/addons"},
    "garrys_mod": {"appid": 4000, "workshop_appid": 4000, "mod_path": "/garrysmod/addons"},
    "arma3": {"appid": 107410, "workshop_appid": 107410, "mod_path": "/@mods"},
    "dont_starve_together": {"appid": 322330, "workshop_appid": 322330, "mod_path": "/mods"},
    "project_zomboid": {"appid": 108600, "workshop_appid": 108600, "mod_path": "/Zomboid/mods"},
    "space_engineers": {"appid": 244850, "workshop_appid": 244850, "mod_path": "/Mods"},
    "starbound": {"appid": 211820, "workshop_appid": 211820, "mod_path": "/mods"},
    "terraria_tmodloader": {"appid": 1281930, "workshop_appid": 1281930, "mod_path": "/Mods"},
    "tmodloader": {"appid": 1281930, "workshop_appid": 1281930, "mod_path": "/Mods"},
    "rimworld": {"appid": 294100, "workshop_appid": 294100, "mod_path": "/Mods"},
    "cities_skylines": {"appid": 255710, "workshop_appid": 255710, "mod_path": "/Addons/Mods"},
    "7_days_to_die": {"appid": 251570, "workshop_appid": 251570, "mod_path": "/Mods"},
    "sdtd": {"appid": 251570, "workshop_appid": 251570, "mod_path": "/Mods"},
    "conan_exiles": {"appid": 440900, "workshop_appid": 440900, "mod_path": "/ConanSandbox/Mods"},
    "ark": {"appid": 346110, "workshop_appid": 346110, "mod_path": "/ShooterGame/Content/Mods"},
    "ark_survival_evolved": {"appid": 346110, "workshop_appid": 346110, "mod_path": "/ShooterGame/Content/Mods"},
    "rust": {"appid": 252490, "workshop_appid": 252490, "mod_path": "/oxide/plugins"},
    # New Workshop games
    "cs2": {"appid": 730, "workshop_appid": 730, "mod_path": "/game/csgo/maps/workshop"},
    "tf2": {"appid": 440, "workshop_appid": 440, "mod_path": "/tf/maps"},
    "left4dead2": {"appid": 550, "workshop_appid": 550, "mod_path": "/left4dead2/addons"},
    "l4d2": {"appid": 550, "workshop_appid": 550, "mod_path": "/left4dead2/addons"},
    "killing_floor_2": {"appid": 232090, "workshop_appid": 232090, "mod_path": "/KFGame/Cache"},
    "kf2": {"appid": 232090, "workshop_appid": 232090, "mod_path": "/KFGame/Cache"},
    "dayz": {"appid": 221100, "workshop_appid": 221100, "mod_path": "/mods"},
    "unturned": {"appid": 304930, "workshop_appid": 304930, "mod_path": "/Modules"},
    "stormworks": {"appid": 573090, "workshop_appid": 573090, "mod_path": "/rom/vehicles"},
    "barotrauma": {"appid": 602960, "workshop_appid": 602960, "mod_path": "/LocalMods"},
    "insurgency_sandstorm": {"appid": 581320, "workshop_appid": 581320, "mod_path": "/Insurgency/Mods"},
    "assetto_corsa": {"appid": 244210, "workshop_appid": 244210, "mod_path": "/content"},
    "factorio": {"appid": 427520, "workshop_appid": 427520, "mod_path": "/mods"},
    "mordhau": {"appid": 629760, "workshop_appid": 629760, "mod_path": "/Mordhau/Content/Paks/~mods"},
    "squad": {"appid": 393380, "workshop_appid": 393380, "mod_path": "/SquadGame/Plugins/Mods"},
    "eco": {"appid": 382310, "workshop_appid": 382310, "mod_path": "/Mods"},
    "avorion": {"appid": 445220, "workshop_appid": 445220, "mod_path": "/mods"},
    "core_keeper": {"appid": 1621690, "workshop_appid": 1621690, "mod_path": "/BepInEx/plugins"},
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
    },
    "dyson_sphere_program": {
        "community": "dyson-sphere-program",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "sons_of_the_forest": {
        "community": "sons-of-the-forest",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "enshrouded": {
        "community": "enshrouded",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "the_forest": {
        "community": "the-forest",
        "mod_path": "/BepInEx/plugins",
        "bepinex_required": True
    },
    "stardew_valley": {
        "community": "stardew-valley",
        "mod_path": "/Mods",
        "bepinex_required": False
    },
}

# =============================================================================
# UNIFIED GAME MOD SOURCES REGISTRY
# Maps every game to ALL its available mod sources
# =============================================================================

def build_game_mod_sources() -> Dict[str, Dict[str, Any]]:
    """Build a unified registry of which mod sources each game supports."""
    registry: Dict[str, Dict[str, Any]] = {}

    # Aggregate from all source dicts
    all_slugs = set()
    all_slugs.update(WORKSHOP_GAMES.keys())
    all_slugs.update(THUNDERSTORE_GAMES.keys())
    all_slugs.update(CURSEFORGE_GAMES.keys())
    all_slugs.update(NEXUS_GAMES.keys())
    all_slugs.update(MODIO_GAMES.keys())

    for slug in all_slugs:
        sources = []
        name = slug.replace("_", " ").title()

        if slug in WORKSHOP_GAMES:
            cfg = WORKSHOP_GAMES[slug]
            sources.append({"type": "workshop", "appid": cfg["appid"], "mod_path": cfg["mod_path"]})
        if slug in THUNDERSTORE_GAMES:
            cfg = THUNDERSTORE_GAMES[slug]
            sources.append({"type": "thunderstore", "community": cfg["community"], "mod_path": cfg["mod_path"], "bepinex_required": cfg.get("bepinex_required", False)})
            name = cfg.get("name", name) if isinstance(cfg, dict) else name
        if slug in CURSEFORGE_GAMES:
            cfg = CURSEFORGE_GAMES[slug]
            sources.append({"type": "curseforge", "game_id": cfg["game_id"], "mod_path": cfg["mod_path"]})
            name = cfg.get("name", name)
        if slug in NEXUS_GAMES:
            cfg = NEXUS_GAMES[slug]
            sources.append({"type": "nexus", "domain": cfg["domain"], "mod_path": cfg["mod_path"]})
            name = cfg.get("name", name)
        if slug in MODIO_GAMES:
            cfg = MODIO_GAMES[slug]
            sources.append({"type": "modio", "game_id": cfg["game_id"], "mod_path": cfg["mod_path"]})
            name = cfg.get("name", name)

        registry[slug] = {"name": name, "sources": sources}

    return registry

GAME_MOD_SOURCES = build_game_mod_sources()

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

class NexusInstallRequest(BaseModel):
    server_id: str
    game_slug: str
    mod_id: int
    file_id: int

class ModioInstallRequest(BaseModel):
    server_id: str
    game_slug: str
    mod_id: int

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
        "nexus": game_slug in NEXUS_GAMES,
        "modio": game_slug in MODIO_GAMES,
        "workshop_config": WORKSHOP_GAMES.get(game_slug),
        "thunderstore_config": THUNDERSTORE_GAMES.get(game_slug),
        "curseforge_config": CURSEFORGE_GAMES.get(game_slug),
        "nexus_config": NEXUS_GAMES.get(game_slug),
        "modio_config": MODIO_GAMES.get(game_slug),
    }
    return sources

# =============================================================================
# CURSEFORGE API
# =============================================================================

CURSEFORGE_API = "https://api.curseforge.com/v1"

async def search_curseforge(game_id: int, search: str = "", page: int = 1, class_id: int = None) -> Dict[str, Any]:
    """Search CurseForge for mods"""
    cf_key = _api_key("curseforge")
    if not cf_key:
        return {"results": [], "total": 0, "error": "CurseForge API key not configured. Add it in Settings → Integrations."}
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
        "x-api-key": cf_key,
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
        "x-api-key": _api_key("curseforge"),
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
        "x-api-key": _api_key("curseforge"),
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
                    _safe_extractall(zf, extract_dir)
                # Optionally remove the zip after extraction
                # file_path.unlink()
            except ValueError as e:
                import logging; logging.getLogger(__name__).warning(str(e))
            except Exception:
                pass  # Keep the zip if extraction fails
        
        return True

# =============================================================================
# STEAM WORKSHOP API
# =============================================================================

async def search_workshop(appid: int, search_text: str, page: int = 1) -> Dict[str, Any]:
    """Search Steam Workshop for mods"""
    # Steam Workshop Web API
    url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
    
    steam_key = _api_key("steam")
    params = {
        "key": steam_key,
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
        if not steam_key:
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
    
    steam_key = _api_key("steam")
    params = {
        "key": steam_key,
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
        if not steam_key:
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

# Cache Thunderstore package lists per community (avoids re-downloading MBs on every search)
import time as _time
_thunderstore_cache: Dict[str, Any] = {}         # community -> list[package]
_thunderstore_cache_ts: Dict[str, float] = {}    # community -> timestamp
_THUNDERSTORE_CACHE_TTL = 600                     # 10 minutes


async def _get_thunderstore_packages(community: str) -> list:
    """Fetch Thunderstore package list with caching."""
    now = _time.time()
    if community in _thunderstore_cache and (now - _thunderstore_cache_ts.get(community, 0)) < _THUNDERSTORE_CACHE_TTL:
        return _thunderstore_cache[community]

    url = f"{THUNDERSTORE_API}/community/{community}/packages/"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        if response.status_code != 200:
            return _thunderstore_cache.get(community, [])
        packages = response.json()

    _thunderstore_cache[community] = packages
    _thunderstore_cache_ts[community] = now
    return packages

async def search_thunderstore(community: str, search: str = "", page: int = 1) -> Dict[str, Any]:
    """Search Thunderstore for mods (uses cached package list)"""
    try:
        packages = await _get_thunderstore_packages(community)
        if not packages:
            return {"results": [], "total": 0}
        
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
                    # Extract only plugins content (with Zip Slip protection)
                    for name in namelist:
                        if name.startswith("plugins/") and not name.endswith("/"):
                            relative = name[8:]  # Skip "plugins/"
                            _safe_extract_member(zf, name, install_path)
                else:
                    # Extract to mod folder
                    mod_dir.mkdir(parents=True, exist_ok=True)
                    _safe_extractall(zf, mod_dir)
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
            },
            "curseforge": {
                "available": sources["curseforge"],
                "config": sources["curseforge_config"]
            },
            "nexus": {
                "available": sources["nexus"],
                "has_api_key": bool(_api_key("nexus")),
                "config": sources["nexus_config"]
            },
            "modio": {
                "available": sources["modio"],
                "has_api_key": bool(_api_key("modio")),
                "config": sources["modio_config"]
            },
        }
    }

@router.get("/sources-all")
async def get_all_game_mod_sources(current_user=Depends(get_current_user)):
    """Get the unified mod sources registry for all games"""
    return {"games": GAME_MOD_SOURCES}

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
    # Determine mod path based on game - check all source registries
    mod_path = None
    server_path = get_server_path(server_id)
    
    if game_slug in THUNDERSTORE_GAMES:
        config = THUNDERSTORE_GAMES[game_slug]
        mod_path = server_path / config["mod_path"].lstrip("/")
    elif game_slug in WORKSHOP_GAMES:
        config = WORKSHOP_GAMES[game_slug]
        mod_path = server_path / config["mod_path"].lstrip("/")
    elif game_slug in CURSEFORGE_GAMES:
        config = CURSEFORGE_GAMES[game_slug]
        mod_path = server_path / config["mod_path"].lstrip("/")
    elif game_slug in NEXUS_GAMES:
        config = NEXUS_GAMES[game_slug]
        mod_path = server_path / config["mod_path"].lstrip("/")
    elif game_slug in MODIO_GAMES:
        config = MODIO_GAMES[game_slug]
        mod_path = server_path / config["mod_path"].lstrip("/")
    else:
        raise HTTPException(400, f"Game {game_slug} not supported for mod listing")
    
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
    # Determine mod path from any source registry
    config = None
    if request.game_slug in THUNDERSTORE_GAMES:
        config = THUNDERSTORE_GAMES[request.game_slug]
    elif request.game_slug in WORKSHOP_GAMES:
        config = WORKSHOP_GAMES[request.game_slug]
    elif request.game_slug in CURSEFORGE_GAMES:
        config = CURSEFORGE_GAMES[request.game_slug]
    elif request.game_slug in NEXUS_GAMES:
        config = NEXUS_GAMES[request.game_slug]
    elif request.game_slug in MODIO_GAMES:
        config = MODIO_GAMES[request.game_slug]
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

# =============================================================================
# NEXUS MODS API
# =============================================================================

NEXUS_API_BASE = "https://api.nexusmods.com/v1"

async def search_nexus(domain: str, search: str = "", page: int = 1) -> Dict[str, Any]:
    """Search Nexus Mods for a game. Uses the updated mods list as search proxy."""
    nexus_key = _api_key("nexus")
    if not nexus_key:
        return {"results": [], "total": 0, "error": "Nexus Mods API key not configured. Add it in Settings → Integrations."}

    headers = {
        "apikey": nexus_key,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # Nexus doesn't have a true search endpoint in v1, so we use trending/latest + client-side filter
            # Use "updated" list which returns recently-updated mods
            url = f"{NEXUS_API_BASE}/games/{domain}/mods/updated.json"
            params = {"period": "1m"}  # Last month
            response = await client.get(url, params=params, headers=headers)

            if response.status_code == 403:
                return {"results": [], "total": 0, "error": "Nexus API key invalid or expired"}
            if response.status_code != 200:
                return {"results": [], "total": 0, "error": f"HTTP {response.status_code}"}

            updated_mods = response.json()
            
            # Get details for these mods (batch fetch top results)
            mod_ids = [m.get("mod_id") for m in updated_mods[:60]]
            
            results = []
            # Fetch details in batches of 10
            for i in range(0, min(len(mod_ids), 60), 10):
                batch = mod_ids[i:i+10]
                tasks = []
                for mid in batch:
                    task_url = f"{NEXUS_API_BASE}/games/{domain}/mods/{mid}.json"
                    tasks.append(client.get(task_url, headers=headers))
                
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                for resp in responses:
                    if isinstance(resp, Exception):
                        continue
                    if resp.status_code != 200:
                        continue
                    mod = resp.json()
                    
                    # Skip if removed/hidden
                    if mod.get("status") == "removed" or not mod.get("available"):
                        continue
                    
                    results.append({
                        "id": mod.get("mod_id"),
                        "mod_id": mod.get("mod_id"),
                        "name": mod.get("name", ""),
                        "title": mod.get("name", ""),
                        "description": mod.get("summary", ""),
                        "author": mod.get("author", ""),
                        "downloads": mod.get("mod_downloads", 0),
                        "endorsements": mod.get("endorsement_count", 0),
                        "icon_url": mod.get("picture_url", ""),
                        "version": mod.get("version", ""),
                        "category_id": mod.get("category_id"),
                        "page_url": f"https://www.nexusmods.com/{domain}/mods/{mod.get('mod_id')}",
                        "source": "nexus"
                    })

            # Client-side filter by search query
            if search:
                search_lower = search.lower()
                results = [r for r in results if
                           search_lower in r.get("name", "").lower() or
                           search_lower in r.get("description", "").lower() or
                           search_lower in r.get("author", "").lower()]

            # Sort by downloads
            results.sort(key=lambda x: x.get("downloads", 0), reverse=True)

            # Paginate
            per_page = 20
            start = (page - 1) * per_page
            paginated = results[start:start + per_page]

            return {"results": paginated, "total": len(results), "page": page}
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e)}


async def get_nexus_mod_details(domain: str, mod_id: int) -> Dict[str, Any]:
    """Get details for a specific Nexus mod"""
    nexus_key = _api_key("nexus")
    if not nexus_key:
        raise HTTPException(400, "Nexus Mods API key not configured")

    headers = {"apikey": nexus_key, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{NEXUS_API_BASE}/games/{domain}/mods/{mod_id}.json", headers=headers)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Failed to fetch mod {mod_id}")
        mod = resp.json()

        return {
            "id": mod.get("mod_id"),
            "name": mod.get("name"),
            "summary": mod.get("summary"),
            "description": mod.get("description"),
            "author": mod.get("author"),
            "version": mod.get("version"),
            "downloads": mod.get("mod_downloads"),
            "endorsements": mod.get("endorsement_count"),
            "icon_url": mod.get("picture_url"),
            "page_url": f"https://www.nexusmods.com/{domain}/mods/{mod_id}",
            "category_id": mod.get("category_id"),
        }


async def get_nexus_mod_files(domain: str, mod_id: int) -> List[Dict[str, Any]]:
    """Get files for a Nexus mod"""
    nexus_key = _api_key("nexus")
    if not nexus_key:
        raise HTTPException(400, "Nexus Mods API key not configured")

    headers = {"apikey": nexus_key, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{NEXUS_API_BASE}/games/{domain}/mods/{mod_id}/files.json", headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()

        return [
            {
                "id": f.get("file_id"),
                "name": f.get("file_name"),
                "version": f.get("version"),
                "category": f.get("category_name", ""),
                "description": f.get("description", ""),
                "file_size": f.get("size_kb", 0) * 1024,
                "is_primary": f.get("is_primary"),
                "uploaded_time": f.get("uploaded_time"),
            }
            for f in data.get("files", [])
        ]


async def get_nexus_download_link(domain: str, mod_id: int, file_id: int) -> str:
    """Get a download link for a Nexus mod file (requires Premium or manual download)"""
    nexus_key = _api_key("nexus")
    if not nexus_key:
        raise HTTPException(400, "Nexus Mods API key not configured")

    headers = {"apikey": nexus_key, "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{NEXUS_API_BASE}/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json",
            headers=headers
        )
        if resp.status_code == 403:
            raise HTTPException(403, "Nexus Mods Premium account required for direct downloads. Please download manually from the Nexus website.")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, "Failed to get download link")

        links = resp.json()
        if links:
            return links[0].get("URI", "")
        raise HTTPException(404, "No download link available")


async def download_nexus_mod(download_url: str, install_path: Path, filename: str) -> bool:
    """Download and install a mod from Nexus"""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(download_url)
        if response.status_code != 200:
            raise HTTPException(500, f"Failed to download: {response.status_code}")

        install_path.mkdir(parents=True, exist_ok=True)
        file_path = install_path / filename

        with open(file_path, "wb") as f:
            f.write(response.content)

        # Auto-extract zips
        if filename.lower().endswith(".zip"):
            try:
                extract_dir = install_path / filename.rsplit(".", 1)[0]
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(file_path, "r") as zf:
                    _safe_extractall(zf, extract_dir)
            except ValueError as e:
                import logging; logging.getLogger(__name__).warning(str(e))
            except Exception:
                pass

        return True


# =============================================================================
# MOD.IO API
# =============================================================================

MODIO_API_BASE = "https://api.mod.io/v1"

async def search_modio(game_id: int, search: str = "", page: int = 1) -> Dict[str, Any]:
    """Search mod.io for mods"""
    modio_key = _api_key("modio")
    if not modio_key:
        return {"results": [], "total": 0, "error": "mod.io API key not configured. Add it in Settings → Integrations."}

    params = {
        "api_key": modio_key,
        "_limit": 20,
        "_offset": (page - 1) * 20,
        "_sort": "-popular",
    }
    if search:
        params["_q"] = search

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{MODIO_API_BASE}/games/{game_id}/mods", params=params)
            if resp.status_code != 200:
                return {"results": [], "total": 0, "error": f"HTTP {resp.status_code}"}

            data = resp.json()
            results = []
            for mod in data.get("data", []):
                logo = mod.get("logo", {})
                modfile = mod.get("modfile", {})
                results.append({
                    "id": mod.get("id"),
                    "mod_id": mod.get("id"),
                    "name": mod.get("name", ""),
                    "title": mod.get("name", ""),
                    "description": mod.get("summary", ""),
                    "author": mod.get("submitted_by", {}).get("username", ""),
                    "downloads": mod.get("stats", {}).get("downloads_total", 0),
                    "rating": mod.get("stats", {}).get("ratings_positive", 0),
                    "icon_url": logo.get("thumb_320x180", logo.get("original", "")),
                    "version": modfile.get("version", "") if modfile else "",
                    "page_url": mod.get("profile_url", ""),
                    "download_url": modfile.get("download", {}).get("binary_url", "") if modfile else "",
                    "file_size": modfile.get("filesize", 0) if modfile else 0,
                    "source": "modio"
                })

            return {
                "results": results,
                "total": data.get("result_total", len(results)),
                "page": page
            }
        except Exception as e:
            return {"results": [], "total": 0, "error": str(e)}


async def get_modio_mod_details(game_id: int, mod_id: int) -> Dict[str, Any]:
    """Get details for a specific mod.io mod"""
    modio_key = _api_key("modio")
    if not modio_key:
        raise HTTPException(400, "mod.io API key not configured")

    params = {"api_key": modio_key}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{MODIO_API_BASE}/games/{game_id}/mods/{mod_id}", params=params)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Failed to fetch mod {mod_id}")
        mod = resp.json()
        logo = mod.get("logo", {})
        modfile = mod.get("modfile", {})

        return {
            "id": mod.get("id"),
            "name": mod.get("name"),
            "summary": mod.get("summary"),
            "description_plaintext": mod.get("description_plaintext"),
            "author": mod.get("submitted_by", {}).get("username", ""),
            "version": modfile.get("version", "") if modfile else "",
            "downloads": mod.get("stats", {}).get("downloads_total", 0),
            "icon_url": logo.get("thumb_320x180", ""),
            "page_url": mod.get("profile_url", ""),
            "download_url": modfile.get("download", {}).get("binary_url", "") if modfile else "",
            "file_size": modfile.get("filesize", 0) if modfile else 0,
        }


async def download_modio_mod(download_url: str, install_path: Path, filename: str) -> bool:
    """Download and install a mod from mod.io"""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(download_url)
        if response.status_code != 200:
            raise HTTPException(500, f"Failed to download: {response.status_code}")

        install_path.mkdir(parents=True, exist_ok=True)
        file_path = install_path / filename

        with open(file_path, "wb") as f:
            f.write(response.content)

        # Auto-extract zips
        if filename.lower().endswith(".zip"):
            try:
                extract_dir = install_path / filename.rsplit(".", 1)[0]
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(file_path, "r") as zf:
                    _safe_extractall(zf, extract_dir)
            except ValueError as e:
                import logging; logging.getLogger(__name__).warning(str(e))
            except Exception:
                pass

        return True


# =============================================================================
# NEXUS MODS API ROUTES
# =============================================================================

@router.get("/nexus/search")
async def nexus_search_mods(
    game_slug: str = Query(..., description="Game slug like 'valheim', 'baldurs_gate_3'"),
    q: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    current_user=Depends(get_current_user)
):
    """Search mods on Nexus Mods for a specific game"""
    if game_slug not in NEXUS_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported on Nexus Mods. Supported: {list(set(v['domain'] for v in NEXUS_GAMES.values()))}")

    domain = NEXUS_GAMES[game_slug]["domain"]
    result = await search_nexus(domain, q, page)
    return {
        "mods": result.get("results", []),
        "total": result.get("total", 0),
        "page": page,
        "game": game_slug,
        "source": "nexus",
        "error": result.get("error")
    }


@router.get("/nexus/mod/{game_slug}/{mod_id}")
async def nexus_get_mod(
    game_slug: str,
    mod_id: int,
    current_user=Depends(get_current_user)
):
    """Get details for a Nexus Mods mod"""
    if game_slug not in NEXUS_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported")
    domain = NEXUS_GAMES[game_slug]["domain"]
    return {"mod": await get_nexus_mod_details(domain, mod_id), "source": "nexus"}


@router.get("/nexus/mod/{game_slug}/{mod_id}/files")
async def nexus_get_mod_files(
    game_slug: str,
    mod_id: int,
    current_user=Depends(get_current_user)
):
    """Get files for a Nexus Mods mod"""
    if game_slug not in NEXUS_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported")
    domain = NEXUS_GAMES[game_slug]["domain"]
    files = await get_nexus_mod_files(domain, mod_id)
    return {"files": files, "total": len(files)}


@router.post("/nexus/install")
async def nexus_install_mod(
    server_id: str = Query(...),
    game_slug: str = Query(...),
    mod_id: int = Query(...),
    file_id: int = Query(...),
    current_user=Depends(require_moderator)
):
    """Install a mod from Nexus Mods (requires Premium API key)"""
    if game_slug not in NEXUS_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported")

    config = NEXUS_GAMES[game_slug]
    domain = config["domain"]
    server_path = get_server_path(server_id)
    mod_path = server_path / config["mod_path"].lstrip("/")

    # Get download link (requires Premium)
    try:
        download_url = await get_nexus_download_link(domain, mod_id, file_id)
    except HTTPException:
        raise

    # Get file info for filename
    files = await get_nexus_mod_files(domain, mod_id)
    filename = f"nexus_mod_{mod_id}_{file_id}"
    for f in files:
        if f.get("id") == file_id:
            filename = f.get("name", filename)
            break

    await download_nexus_mod(download_url, mod_path, filename)

    return {
        "success": True,
        "message": f"Installed {filename}",
        "path": str(mod_path / filename),
        "source": "nexus"
    }


# =============================================================================
# MOD.IO API ROUTES
# =============================================================================

@router.get("/modio/search")
async def modio_search_mods(
    game_slug: str = Query(..., description="Game slug like 'squad', 'mordhau'"),
    q: str = Query("", description="Search query"),
    page: int = Query(1, ge=1),
    current_user=Depends(get_current_user)
):
    """Search mods on mod.io for a specific game"""
    if game_slug not in MODIO_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported on mod.io. Supported: {list(MODIO_GAMES.keys())}")

    game_id = MODIO_GAMES[game_slug]["game_id"]
    result = await search_modio(game_id, q, page)
    return {
        "mods": result.get("results", []),
        "total": result.get("total", 0),
        "page": page,
        "game": game_slug,
        "source": "modio",
        "error": result.get("error")
    }


@router.get("/modio/mod/{game_slug}/{mod_id}")
async def modio_get_mod(
    game_slug: str,
    mod_id: int,
    current_user=Depends(get_current_user)
):
    """Get details for a mod.io mod"""
    if game_slug not in MODIO_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported")
    game_id = MODIO_GAMES[game_slug]["game_id"]
    return {"mod": await get_modio_mod_details(game_id, mod_id), "source": "modio"}


@router.post("/modio/install")
async def modio_install_mod(
    server_id: str = Query(...),
    game_slug: str = Query(...),
    mod_id: int = Query(...),
    current_user=Depends(require_moderator)
):
    """Install a mod from mod.io"""
    if game_slug not in MODIO_GAMES:
        raise HTTPException(400, f"Game '{game_slug}' not supported")

    config = MODIO_GAMES[game_slug]
    game_id = config["game_id"]
    server_path = get_server_path(server_id)
    mod_path = server_path / config["mod_path"].lstrip("/")

    # Get mod details including download URL
    mod = await get_modio_mod_details(game_id, mod_id)
    download_url = mod.get("download_url")
    if not download_url:
        raise HTTPException(400, "No download available for this mod")

    filename = f"{mod.get('name', f'mod_{mod_id}').replace(' ', '_')}.zip"
    await download_modio_mod(download_url, mod_path, filename)

    return {
        "success": True,
        "message": f"Installed {mod.get('name', filename)}",
        "path": str(mod_path / filename),
        "source": "modio"
    }


@router.get("/supported-games")
async def get_supported_games(current_user=Depends(get_current_user)):
    """Get list of games with mod support from all sources"""
    games = []
    seen_slugs = set()
    
    for slug, config in WORKSHOP_GAMES.items():
        if slug not in seen_slugs:
            games.append({
                "slug": slug,
                "source": "workshop",
                "appid": config["appid"],
                "mod_path": config["mod_path"]
            })
            seen_slugs.add(slug)
    
    for slug, config in THUNDERSTORE_GAMES.items():
        if slug not in seen_slugs:
            games.append({
                "slug": slug,
                "source": "thunderstore",
                "community": config["community"],
                "mod_path": config["mod_path"],
                "bepinex_required": config.get("bepinex_required", False)
            })
            seen_slugs.add(slug)
    
    for slug, config in CURSEFORGE_GAMES.items():
        if slug not in seen_slugs:
            games.append({
                "slug": slug,
                "name": config["name"],
                "source": "curseforge",
                "game_id": config["game_id"],
                "mod_path": config["mod_path"]
            })
            seen_slugs.add(slug)

    for slug, config in NEXUS_GAMES.items():
        if slug not in seen_slugs:
            games.append({
                "slug": slug,
                "name": config["name"],
                "source": "nexus",
                "domain": config["domain"],
                "mod_path": config["mod_path"]
            })
            seen_slugs.add(slug)

    for slug, config in MODIO_GAMES.items():
        if slug not in seen_slugs:
            games.append({
                "slug": slug,
                "name": config["name"],
                "source": "modio",
                "game_id": config["game_id"],
                "mod_path": config["mod_path"]
            })
            seen_slugs.add(slug)

    # Also include the unified registry for richer data
    return {"games": games, "registry": GAME_MOD_SOURCES}

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
                _safe_extractall(zf, server_path)
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
        "x-api-key": _api_key("curseforge"),
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
            f"{CURSEFORGE_API}/categories",
            params={"gameId": game_id},
            headers={"x-api-key": _api_key("curseforge")}
        )
        
        if response.status_code != 200:
            return {"categories": [], "error": "Failed to fetch categories"}
        
        data = response.json()
        return {"categories": data.get("data", []), "game": game_slug}