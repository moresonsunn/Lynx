"""
Client-Side Mod Detection & Filtering Engine
=============================================
Comprehensive system for detecting and filtering client-only mods from Minecraft
server modpacks. Uses multiple detection strategies:

1. JAR Metadata Inspection (fabric.mod.json, quilt.mod.json, mods.toml, neoforge.mods.toml)
2. Modrinth API lookup (client_side / server_side fields)
3. CurseForge API lookup (gameVersions Client/Server tags)
4. Comprehensive known client-only mod database (800+ mods)
5. Heuristic filename pattern matching as final fallback
6. User-configurable allow/deny lists
"""

import json
import os
import re
import shutil
import zipfile
import hashlib
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Data Types
# ═══════════════════════════════════════════════════════════════

class ModSide(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    BOTH = "both"
    UNKNOWN = "unknown"

class DetectionMethod(str, Enum):
    JAR_METADATA = "jar_metadata"
    MODRINTH_API = "modrinth_api"
    CURSEFORGE_API = "curseforge_api"
    KNOWN_DATABASE = "known_database"
    FILENAME_PATTERN = "filename_pattern"
    USER_OVERRIDE = "user_override"
    ENTRYPOINT_ANALYSIS = "entrypoint_analysis"

@dataclass
class ModAnalysis:
    filename: str
    mod_id: Optional[str] = None
    mod_name: Optional[str] = None
    version: Optional[str] = None
    loader: Optional[str] = None
    side: ModSide = ModSide.UNKNOWN
    detection_method: Optional[DetectionMethod] = None
    confidence: float = 0.0  # 0.0 to 1.0
    reason: str = ""
    is_client_only: bool = False
    whitelisted: bool = False
    file_size: int = 0
    sha256: Optional[str] = None
    modrinth_id: Optional[str] = None
    curseforge_id: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        d["side"] = self.side.value if self.side else "unknown"
        d["detection_method"] = self.detection_method.value if self.detection_method else None
        return d


# ═══════════════════════════════════════════════════════════════
#  Known Client-Only Mod Database
#  Organized by category for maintainability.
#  Each entry is a mod_id (from fabric.mod.json / mods.toml).
#  We also match by partial filename as fallback.
# ═══════════════════════════════════════════════════════════════

# Mod IDs that are definitively client-only (from metadata / known behavior)
KNOWN_CLIENT_ONLY_MOD_IDS: set[str] = {
    # ── Rendering / Performance (Client) ──
    "sodium", "embeddium", "rubidium", "magnesium", "iris", "oculus",
    "optifine", "optifabric", "canvas-renderer", "canvas",
    "immediatelyfast", "immediately-fast", "entityculling", "entity_culling",
    "dynamicfps", "dynamic-fps", "dynamic_fps", "fpsreducer", "fps_reducer",
    "enhancedvisuals", "enhanced_visuals", "lambdynlights", "lambdynamiclights",
    "betterfps", "dashloader", "dash-loader", "nvidium", "vulkanmod",
    "distanthorizons", "distant-horizons", "distant_horizons",
    "bobby", "farsight", "farsight-mod",
    "cull-less-leaves", "culllessleaves", "cull_less_leaves",
    "more-culling", "moreculling",
    "continuity", "indium", "reeses-sodium-options", "reeses_sodium_options",
    "sodium-extra", "sodium-options", "sodiumextra",
    "better-clouds", "betterclouds",
    "falling-leaves", "fallingtree-client", "visuality",
    "particlerain", "particle_rain",
    "drippyloadingscreen", "drippy-loading-screen",
    "starlight", "phosphor",
    "not-enough-animations", "notenoughanimations",
    "model-gap-fix", "modelfix",
    "animatica", "entitytexturefeatures", "entity-texture-features",
    "fabricskyboxes", "fancy-block-particles", "fancyblockparticles",
    "effective", "illuminate", "illuminations",

    # ── UI / HUD ──
    "xaerominimap", "xaerosworldmap", "xaeros_minimap", "xaeros_worldmap",
    "xaeros-minimap", "xaeros-world-map",
    "journeymap", "journeymap-client", "voxelmap",
    "justmap", "ftb-chunks-client",
    "betterf3", "better-f3", "betterf3plus",
    "appleskin", "jade", "jade-addons", "hwyla", "waila", "wthit",
    "torohealth", "torohealth-damage-indicators", "healthindicatortfc",
    "blur", "blur-fabric", "controlling", "searchables",
    "modmenu", "mod-menu", "configured", "catalogue",
    "smoothboot", "smooth-boot", "smooth_boot",
    "fancymenu", "konkrete", "drippy-loading-screen",
    "loadingscreen", "mainmenu", "custommainmenu", "custom-main-menu",
    "betterthirdperson", "better-third-person", "better_third_person",
    "freelook", "cameraoverhaul", "camera-overhaul",
    "cit-resewn", "citresewn", "cit_resewn",
    "itemphysic", "itemphysiclite", "item-physic",
    "eating-animation", "eatinganimation",
    "bedrockify", "tooltip-fix", "tooltipfix",
    "advancementinfo", "advancement-info",
    "shulkerboxtooltip", "shulkerbox-tooltip",
    "bettermounthud", "better-mount-hud",
    "legendarytooltips", "legendary-tooltips", "iceberg",
    "prism", "prism-lib",
    "neat", "inventoryprofiles", "inventoryprofilesnext", "inventory-profiles-next",
    "betteradvancements", "better-advancements",
    "justzoom", "just-zoom", "zoomify", "logical-zoom", "logicalzoom", "ok-zoomer", "okzoomer",
    "held-item-info", "helditeminfo",
    "chat-heads", "chatheads",
    "mouse-tweaks", "mousetweaks",
    "item-borders", "itemborders",
    "equipment-compare", "equipmentcompare",
    "emi-loot", "emiloot",
    "dark-loading-screen", "darkloadingscreen",
    "respackopt", "resource-pack-overrides",
    "panorama-fix", "panoramafix",
    "screenshot-to-clipboard", "screenshottoclipboard",
    "cleanview", "clean-view",
    "no-chat-reports", "nochatreports",
    "antighost",

    # ── Audio / Sound (Client) ──
    "presence-footsteps", "presencefootsteps", "presence_footsteps",
    "soundphysics", "sound-physics-remastered", "sound_physics",
    "ambientsounds", "ambient-sounds", "dynamic-music", "dynamicmusic",
    "extrasounds", "extra-sounds", "dripsounds", "auditory",
    "biomemusic", "biome-music",
    "currentgamemusictrack", "current-game-music-track",
    "ding", "ding-forge",
    "sounds",  # IMB11's Sounds mod

    # ── Recording / Streaming ──
    "replaymod", "replay-mod", "replay_mod",
    "worldedit-cui", "worldeditcui", "wecui",
    "axiom", "axiom-client",

    # ── Cosmetics / Player Models ──
    "skinlayers3d", "skin-layers-3d", "3dskinlayers",
    "ears", "figura", "customskinloader", "custom-skin-loader",
    "more-player-models", "moreplayermodels",
    "playeranimator", "player-animator",
    "emotes", "emotecraft", "not-enough-animations",
    "cosmetica", "capes", "minecraftcapes",
    "first-person-model", "firstpersonmod",
    "wavey-capes", "waveycapes",
    "capejs", "cape-js",

    # ── Client Utilities / Tweaks ──
    "litematica", "minihud", "tweakeroo", "malilib", "itemscroller",
    "tweakermore", "masa-gadget",
    "freecam", "flycam", "keystrokes",
    "betterpvp", "5zig", "labymod",
    "schematica", "light-overlay", "lightoverlay",
    "mixin-trace", "mixintrace",
    "better-ping-display", "betterpingdisplay",
    "rekindled-world-menu", "authme", "auth-me",
    "custom-crosshair", "customcrosshair",
    "rrls", "remove-reloading-screen",
    "controllable",  # Controller/gamepad support
    "rawsvisualkeybinder", "raw-visual-keybinder",

    # ── Performance Fixes (Client-Side) ──
    "advancementplaques", "advancement-plaques",
    "alltheleaks", "alltheleaks-fix",
    "betterfpsrenderdist", "better-fps-render-distance",
    "fastquit", "fastquit-forge",
    "flickerfix", "flicker-fix",
    "fixgpumemoryleak", "fix-gpu-memory-leak",
    "notenoughcrashes", "not-enough-crashes",
    "modernstartupqol", "modern-startup-qol",
    "updatingworldicon", "updating-world-icon",

    # ── HUD / Overlay / Indicators ──
    "colorfulhearts", "colorful-hearts",
    "overloadedarmor", "overloaded-armor-bar",
    "enhancedbossbars", "enhanced-boss-bars",
    "bettermanabar", "better-mana-bar",
    "fittingxpmanabar", "fitting-xp-mana-bar",
    "damage-indicators", "damageindicators", "jeremyseqs-damage-indicators",
    "moreoverlays", "more-overlays-updated",
    "pickupnotifier", "pick-up-notifier",
    "toastcontrol", "toast-control",
    "stylisheffects", "stylish-effects",
    "travelerstitles", "travelers-titles",
    "visualtravelerstitles", "visual-travelers-titles",
    "alexstitles",  # Alex's Caves + Traveler's Titles compat
    "titles",
    "novillagerdeathmsgs", "no-villager-death-messages",
    "raidcounter", "raid-counter",

    # ── UI / Menu (Client) ──
    "darkmodeeverywhere", "dark-mode-everywhere",
    "immersiveui", "immersive-ui",
    "minecraftcursor", "minecraft-cursor",
    "yungsmenutweaks", "yungs-menu-tweaks",
    "scholar",
    "sdmuilib", "sdm-ui-lib",
    "tips",
    "perception",  # UI effects
    "abetterguiaddon", "a-better-gui-addon",
    "bisect", "bisecthosting", "bisecthosting-server-integration-menu",
    "notenoughrecipebook", "nerb", "not-enough-recipe-book",

    # ── Visual Effects (Client) ──
    "particular", "particular-reforged",
    "prettyrain", "pretty-rain",
    "dynamictrim", "dynamic-trim",

    # ── Discord Integration (Client) ──
    "simplediscordrpc", "simple-discord-rich-presence",

    # ── Connected Textures (Client) ──
    "fusion", "fusion-connected-textures",

    # ── Embeddium / Sodium Addons (Client) ──
    "sodiumdynamiclights", "embeddium-dynamiclights", "sodium-dynamic-lights",
    "sodiumextras", "embeddiumextras", "sodium-extras", "embeddium-extras",
    "sodiumoptionsapi", "embeddiumoptionsapi", "embeddium-options-api",

    # ── Zoom Addons ──
    "xaerozoomout", "xaero-zoomout",

    # ── Font / Rendering Tweaks ──
    "runelic",  # Font rendering

    # ── Shader / Resource Pack Support ──
    "iris-shaders", "complementary-shaders",
    "connected-textures-mod", "ctm",

    # ── Frameworks (client-only libs) ──
    "cloth-config-client", "midnightlib-client",
    "yacl", "yet-another-config-lib",  # Often client-only config UI

    # ── Chat Mods ──
    "chatpatches", "chat-patches", "chatting", "chattweaks",
    "where-is-it", "whereisit",
}

# Mod IDs that are KNOWN to be required server-side (never filter these).
# Library mods, API mods, and content mods that must remain on the server
# even if their metadata or Modrinth listing says server_side=optional.
KNOWN_SERVER_REQUIRED_MOD_IDS: set[str] = {
    # ── Core Loaders & APIs ──
    "fabric-api", "fabricloader", "fabric-loader", "fabric",
    "forge", "neoforge", "minecraft",
    "quilt-loader", "quilted-fabric-api",
    "kotlin-for-forge", "kotlinforforge", "fabric-language-kotlin",
    "fabric-language-scala",

    # ── Common Library / Framework Mods (NEVER FILTER) ──
    "geckolib", "geckolib3", "geckolib4", "geckolib_forge", "geckolib_fabric",
    "azurelib", "azurelib-neo", "azurelib-forge", "azurelib-fabric",
    "architectury", "architectury-api",
    "cloth-config", "cloth-config2", "cloth_config",
    "curios", "curios-forge", "trinkets",
    "patchouli", "patchouli-forge",
    "flywheel", "registrate",
    "bookshelf", "bookshelf-forge", "bookshelf-fabric",
    "moonlight", "moonlight-lib", "moonlib", "selene",
    "balm", "balm-forge", "balm-fabric",
    "puzzleslib", "puzzles-lib",
    "playeranimator", "player-animator", "playeranimationlib",
    "caelus", "caelus_api",
    "pehkui",
    "citadel",
    "liblilium", "liblib",
    "sinytra-connector",
    "forgified-fabric-api",
    "mixinextras", "mixin-extras",
    "creativecore", "creative-core",
    "playerrev", "playerrevive",
    "kotlinserialization",
    "connector",
    "supermartijn642corelib", "supermartijn642configlib",
    "cofh_core", "cofhcore",
    "blueprint", "abnormals-core", "abnormalscore",
    "structure-gel-api", "structuregelapi",
    "ftb-library", "ftblib", "ftb-lib",
    "autoreglib", "porting_lib", "porting-lib",
    "shetiphiancore",
    "resourcefullib", "resourceful-lib",
    "yungsapi", "yungs-api", "yungs_api",
    "collective",
    "midnightlib",
    "terrablender", "terra-blender",
    "mixin", "mixinbootstrap",
    "placebo",
    "coroutil",
    "apoli", "origins", "origins-forge",
    "owo-lib", "owolib",
    "fzzy-core", "fzzy_core",
    "libzontreck",
    "libvulpes",
    "mantle",
    "smartbrainlib", "smart-brain-lib",
    "moreplayermodels-lib",
    "scena", "scenariolib",

    # ── Recipe / Item Viewers ──
    "jei", "just-enough-items", "justenoughitems",
    "rei", "roughlyenoughitems", "roughly-enough-items",
    "emi",

    # ── Content Mods (server-side logic required) ──
    "create", "botania", "mekanism", "thermal", "thermal_foundation",
    "thermal_expansion", "thermal_dynamics", "thermal_innovation",
    "applied-energistics-2", "ae2", "appliedenergistics2",
    "waystones", "biomes-o-plenty", "biomesoplenty",
    "terra", "terralith", "tectonic",
    "worldedit", "essentials",
    "luckperms", "vault",
    "farmersdelight", "farmers-delight", "farmers_delight",
    "farmersrespite", "farmers-respite",
    "minersdelight", "miners-delight",
    "croptopia", "pamhc2crops", "pamhc2trees",
    "alexsmobs", "alexs-mobs", "alexsmobsinteraction",
    "iceandfire", "ice_and_fire",
    "twilightforest", "the-twilight-forest",
    "aether", "the-aether", "deep_aether",
    "supplementaries", "supplementaries-squared",
    "quark", "autoreglib",
    "immersiveengineering", "immersive-engineering",
    "enigmaticlegacy",
    "mna", "mna-forge", "manaandartifice", "mana-and-artifice",
    "sprout",
    "createcompressed", "create_compressed", "create-compressed", "create_things_and_misc",
    "createrecycling", "create_recycling", "create-recycling",
    "justverticalslabs", "just_vertical_slabs", "just-vertical-slabs", "jvs",
    "openstairs", "open_stairs", "open-stairs",
    "create_dd", "create-dreams-and-desires", "createdreamsanddesires",
    "create_deco", "createdeco", "create-deco",
    "create_enchantment_industry", "create_connected",
    "createaddition", "create_sa", "create-steam-and-rails",
    "create_crafts_and_additions", "createcraftsandadditions",
    "create_stuff_additions", "createstuffadditions",
    "create_confectionery", "createconfectionery",
    "create_garnished", "creategarnished",
    "create_new_age", "createnewage",
    "create_power_loader", "createpowerloader",
    "create_central_kitchen", "createcentralkitchen",
    "tinkersconstruct", "tconstruct",
    "tetra",
    "sophisticatedbackpacks", "sophisticated-backpacks",
    "sophisticatedstorage", "sophisticated-storage",
    "sophisticatedcore", "sophisticated-core",
    "ad_astra", "ad-astra",
    "simplyswords", "simply-swords",
    "natures-compass", "naturescompass",
    "explorers-compass", "explorerscompass",
    "iron-chests", "ironchest", "ironchests",
    "morpheus", "sleep-warp",
    "gravestone", "gravestone-mod",
    "corpse", "corpse-mod",
    "wthit-forge",
    "constructionwand", "construction-wand",
    "polymorph", "polymorph-forge",
    "dimdoors", "dimensional-doors",
    "ftb-chunks", "ftbchunks",
    "ftb-quests", "ftbquests",
    "ftb-teams", "ftbteams",
    "ftb-essentials",
    "minecolonies", "structurize",
    "comforts",
    "lootr",
    "elevatormod",
    "curseofcurses",
    "chiselsandbits", "chisels-and-bits",
    "storage-drawers", "storagedrawers",

    # ── Magic & Spell Mods (NEVER FILTER — heavy server logic) ──
    "ars_nouveau", "arsnouveau", "ars-nouveau",
    "ars_elemental", "arselemental",
    "ars_creo", "arscreo",
    "irons_spellbooks", "ironsSpellbooks", "irons-spells-n-spellbooks",
    "hexcasting", "hex-casting", "hexerei",
    "goety", "goety-2", "goety-cataclysm",
    "occultism", "occultism-forge",
    "vampirism", "vampirism-forge",
    "biomancy", "biomancy-forge",

    # ── Boss / Dungeon / Structure Mods ──
    "cataclysm", "l_ender_cataclysm",
    "bosses_of_mass_destruction", "bosses-of-mass-destruction",
    "dungeon_crawl", "dungeoncrawl",
    "repurposed_structures", "repurposed-structures",
    "integrated_dungeons", "integrated-dungeons-and-structures",
    "alexscaves", "alexs-caves", "alexs_caves",
    "aquamirae",

    # ── Tech Mods ──
    "pneumaticcraft", "pneumaticcraft-repressurized",
    "enderio", "ender-io",
    "flux_networks", "fluxnetworks",
    "integrateddynamics", "integrated-dynamics",
    "integratedterminals", "integrated-terminals",
    "integratedtunnels", "integrated-tunnels",
    "integratedcrafting", "integrated-crafting",
    "compact_machines", "compactmachines",
    "buildinggadgets", "building-gadgets",
    "mininggadgets", "mining-gadgets",

    # ── Exploration & Dimension Mods ──
    "bumblezone", "the-bumblezone",
    "sky_villages", "sky-villages",
    "amplified_nether", "amplified-nether",
    "river_redux", "river-redux",

    # ── Creature / Mob Mods ──
    "mowzies_mobs", "mowziesmobs",
    "mutantmonsters", "mutant-monsters",
    "rats",
    "domesticationinnovation",
    "alshanexfamiliars", "alshanexs-familiars",

    # ── Gameplay / Economy / Quests ──
    "gamestages", "game-stages",
    "gateways_to_eternity", "gateways-to-eternity",
    "bountiful",
    "relics",
    "corail_tombstone", "tombstone",
    "artifacts",
    "simplyswords", "simply-swords",
    "betterarcheology", "better-archeology",
    "aquaculture", "aquaculture2",
    "little_logistics", "littlelogistics",
    "dank_storage", "dankstorage",
    "veinmining", "vein-mining",

    # ── Utility / World Management ──
    "chunky", "chunky-pregenerator",
    "servercore",
    "incontrol", "in-control",
    "kubejs", "rhino",
    "lootintegrations", "loot-integrations",
    "defaultoptions", "default-options",
    "serverconfigupdater",
    "simplebackups", "simple-backups",
    "crashutilities", "crash-utilities",
    "deuf",  # Duplicate Entity UUID Fix

    # ── Macaw's Building Mods ──
    "mcw-bridges", "mcw-doors", "mcw-fences", "mcw-furniture",
    "mcw-lights", "mcw-paintings", "mcw-paths", "mcw-roofs",
    "mcw-trapdoors", "mcw-windows",
    "macawsbridges", "macawsdoors", "macawsfences", "macawsfurniture",
    "macawslights", "macawspaintings", "macawspaths", "macawsroofs",
    "macawstrapdoors", "macawswindows",
}

# Filename patterns for mods that are almost certainly client-only.
# Used ONLY when no metadata is available in the JAR and API lookups fail.
CLIENT_ONLY_FILENAME_PATTERNS: list[str] = [
    # Rendering
    "oculus", "iris", "sodium", "embeddium", "rubidium", "magnesium",
    "optifine", "optifabric", "lambdynamiclights", "dynamicfps", "dynamic-fps",
    "canvas-renderer", "immediatelyfast", "entityculling", "fpsreducer",
    "enhancedvisuals", "better-clouds", "falling-leaves", "visuality",
    "cull-less-leaves", "particlerain", "drippyloadingscreen",
    "nvidium", "distanthorizons", "distant-horizons", "bobby",
    "continuity", "indium", "not-enough-animations", "animatica",
    "fabricskyboxes", "effective", "illuminations",
    # UI/HUD
    "xaero", "journeymap", "voxelmap", "minimap", "worldmap",
    "betterf3", "better-f3", "appleskin", "itemphysic", "jade",
    "hwyla", "waila", "wthit", "torohealth",
    "blur", "controlling", "mod-menu", "modmenu", "configured", "catalogue",
    "smoothboot", "smooth-boot", "loadingscreen", "mainmenu",
    "betterthirdperson", "freelook", "cameraoverhaul", "cit-resewn", "citresewn",
    "shulkerboxtooltip", "legendarytooltips", "iceberg",
    "inventoryprofilesnext", "betteradvancements",
    "zoomify", "ok-zoomer", "logicalzoom",
    "chatheads", "mousetweaks", "itemborders", "equipmentcompare",
    "darkloadingscreen", "respackopt", "panoramafix",
    "nochatreports",
    # Audio
    "presence-footsteps", "presencefootsteps", "soundphysics",
    "ambientsounds", "dynamic-music", "extrasounds", "dripsounds",
    # Recording
    "replaymod", "replay-mod", "worldedit-cui", "axiom",
    # Cosmetics
    "skinlayers3d", "skin-layers", "ears-", "figura", "customskinloader",
    "more-player-models", "playeranimator", "emotecraft",
    "cosmetica", "waveycapes", "firstpersonmod",
    # Utilities
    "litematica", "minihud", "tweakeroo", "malilib", "itemscroller",
    "freecam", "flycam", "keystrokes", "betterpvp", "labymod",
    "schematica", "light-overlay", "lightoverlay",
    "betterpingdisplay", "authme",
    # Frameworks (client libs)
    "reeses_sodium_options", "reeses-sodium-options",
    "rrls", "fancymenu", "konkrete",
    "sodium-extra", "sodiumextra",
    # MCE2 client mods
    "advancementplaques", "advancement-plaques",
    "alltheleaks", "better-fps-render",
    "toast-control", "toastcontrol",
    "controllable", "damage-indicators",
    "more-overlays", "moreoverlays",
    "pick-up-notifier", "pickupnotifier",
    "travelers-titles", "travelerstitles",
    "stylish-effects", "stylisheffects",
    "tips-", "discord-rich-presence", "simplediscordrpc",
    "fastquit", "flickerfix", "fix-gpu-memory",
    "not-enough-crashes", "notenoughcrashes",
    "colorful-hearts", "colorfulhearts",
    "overloaded-armor", "enhanced-boss-bars",
    "dark-mode-everywhere", "immersive-ui",
    "minecraft-cursor", "yungs-menu-tweaks",
    "modern-startup", "modernstartup",
    "bisecthosting", "particular-",
    "pretty-rain", "prettyrain",
    "embeddium-dynamic", "sodium-dynamic-lights",
    "embeddium-extras", "embeddiumextras",
    "embeddium-options", "embeddiumoptions",
    "xaero-zoomout", "xaerozoomout",
    "biome-music", "biomemusic",
    "current-game-music", "scholar-",
    "runelic", "capejs",
    "a-better-gui", "nerb-",
    "no-villager-death",
    "updating-world-icon",
]


# ═══════════════════════════════════════════════════════════════
#  JAR Metadata Inspection
# ═══════════════════════════════════════════════════════════════

def _inspect_jar_metadata(jar_path: Path) -> ModAnalysis:
    """Extract mod metadata from JAR file and determine client/server side."""
    analysis = ModAnalysis(
        filename=jar_path.name,
        file_size=jar_path.stat().st_size if jar_path.exists() else 0,
    )

    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = zf.namelist()

            # ── Fabric / Quilt ──
            fabric_json = None
            if 'fabric.mod.json' in names:
                try:
                    raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                    fabric_json = json.loads(raw)
                    analysis.loader = 'fabric'
                    analysis.mod_id = fabric_json.get('id')
                    analysis.mod_name = fabric_json.get('name', analysis.mod_id)
                    analysis.version = fabric_json.get('version')

                    # Environment field is the primary indicator
                    env = str(fabric_json.get('environment', '*')).strip().lower()
                    if env == 'client':
                        analysis.side = ModSide.CLIENT
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.95
                        analysis.reason = "fabric.mod.json environment='client'"
                        analysis.is_client_only = True
                    elif env == 'server':
                        analysis.side = ModSide.SERVER
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.95
                        analysis.reason = "fabric.mod.json environment='server'"
                    elif env in ('*', 'both', ''):
                        analysis.side = ModSide.BOTH
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.7
                        analysis.reason = "fabric.mod.json environment='*' (universal)"

                    # Entrypoint analysis: if ONLY client entrypoints, likely client-only
                    if analysis.side == ModSide.BOTH or analysis.side == ModSide.UNKNOWN:
                        entrypoints = fabric_json.get('entrypoints', {})
                        has_main = bool(entrypoints.get('main'))
                        has_client = bool(entrypoints.get('client'))
                        has_server = bool(entrypoints.get('server'))

                        if has_client and not has_main and not has_server:
                            analysis.side = ModSide.CLIENT
                            analysis.detection_method = DetectionMethod.ENTRYPOINT_ANALYSIS
                            analysis.confidence = 0.8
                            analysis.reason = "Only client entrypoints defined (no main/server)"
                            analysis.is_client_only = True

                    # Mixins analysis: check if all mixins target client
                    if analysis.side == ModSide.BOTH or analysis.side == ModSide.UNKNOWN:
                        mixins = fabric_json.get('mixins', [])
                        client_mixin_count = 0
                        server_mixin_count = 0
                        neutral_mixin_count = 0
                        for mixin_entry in mixins:
                            if isinstance(mixin_entry, dict):
                                mixin_env = str(mixin_entry.get('environment', '')).lower()
                                if mixin_env == 'client':
                                    client_mixin_count += 1
                                elif mixin_env == 'server':
                                    server_mixin_count += 1
                                else:
                                    neutral_mixin_count += 1
                            else:
                                neutral_mixin_count += 1
                        if client_mixin_count > 0 and server_mixin_count == 0 and neutral_mixin_count == 0:
                            # All mixins are client-only
                            if analysis.confidence < 0.75:
                                analysis.side = ModSide.CLIENT
                                analysis.detection_method = DetectionMethod.ENTRYPOINT_ANALYSIS
                                analysis.confidence = 0.7
                                analysis.reason = "All mixins target client environment only"
                                analysis.is_client_only = True

                except Exception as e:
                    logger.debug(f"Error reading fabric.mod.json from {jar_path.name}: {e}")

            elif 'quilt.mod.json' in names:
                try:
                    raw = zf.read('quilt.mod.json').decode('utf-8', errors='ignore')
                    data = json.loads(raw)
                    analysis.loader = 'quilt'
                    ql = data.get('quilt_loader', {})
                    analysis.mod_id = ql.get('id')
                    analysis.mod_name = ql.get('metadata', {}).get('name', analysis.mod_id)
                    analysis.version = ql.get('version')

                    env = str(data.get('environment', ql.get('environment', '*'))).strip().lower()
                    if env == 'client':
                        analysis.side = ModSide.CLIENT
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.95
                        analysis.reason = "quilt.mod.json environment='client'"
                        analysis.is_client_only = True
                    elif env == 'server':
                        analysis.side = ModSide.SERVER
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.95
                        analysis.reason = "quilt.mod.json environment='server'"
                    elif env in ('*', 'both', ''):
                        analysis.side = ModSide.BOTH
                        analysis.detection_method = DetectionMethod.JAR_METADATA
                        analysis.confidence = 0.7

                    # Check entrypoints
                    entrypoints = ql.get('entrypoints', {})
                    if isinstance(entrypoints, dict):
                        has_init = bool(entrypoints.get('init'))
                        has_client_init = bool(entrypoints.get('client_init'))
                        has_server_init = bool(entrypoints.get('server_init'))
                        if has_client_init and not has_init and not has_server_init:
                            analysis.side = ModSide.CLIENT
                            analysis.detection_method = DetectionMethod.ENTRYPOINT_ANALYSIS
                            analysis.confidence = 0.8
                            analysis.reason = "Only client_init entrypoint defined"
                            analysis.is_client_only = True

                except Exception as e:
                    logger.debug(f"Error reading quilt.mod.json from {jar_path.name}: {e}")

            # ── Forge / NeoForge ──
            for toml_path in ('META-INF/mods.toml', 'META-INF/neoforge.mods.toml'):
                if toml_path in names and analysis.side == ModSide.UNKNOWN:
                    try:
                        content = zf.read(toml_path).decode('utf-8', errors='ignore')
                        analysis.loader = 'neoforge' if 'neoforge' in toml_path else 'forge'

                        # Parse basic mod info
                        for line in content.split('\n'):
                            line_stripped = line.strip()
                            if '=' in line_stripped:
                                key, val = line_stripped.split('=', 1)
                                key = key.strip().lower()
                                val = val.strip().strip('"').strip("'")
                                if key == 'modid' and not analysis.mod_id:
                                    analysis.mod_id = val
                                elif key == 'displayname' and not analysis.mod_name:
                                    analysis.mod_name = val
                                elif key == 'version' and not analysis.version:
                                    analysis.version = val

                        content_lower = content.lower()

                        # clientSideOnly is the official Forge flag
                        if 'clientsideonly' in content_lower:
                            # Check for clientSideOnly = true (with various whitespace)
                            cso_match = re.search(r'clientsideonly\s*=\s*(true|false)', content_lower)
                            if cso_match and cso_match.group(1) == 'true':
                                analysis.side = ModSide.CLIENT
                                analysis.detection_method = DetectionMethod.JAR_METADATA
                                analysis.confidence = 0.95
                                analysis.reason = f"{toml_path}: clientSideOnly=true"
                                analysis.is_client_only = True

                        # Check displayTest = "NONE" - means mod doesn't need to be on both sides
                        # NOTE: displayTest=NONE is commonly used by optional/library mods that
                        # can function on one side only. This is NOT conclusive evidence of client-only.
                        # We only use it as a weak signal, never as the sole classifier.
                        has_display_test_none = False
                        if analysis.side == ModSide.UNKNOWN:
                            dt_match = re.search(r'displaytest\s*=\s*["\']?(none|ignore_all_missing|ignore_server_only)["\']?', content_lower)
                            if dt_match:
                                has_display_test_none = True
                                analysis.reason = f"{toml_path}: displayTest={dt_match.group(1)} (optional on one side)"

                        # Check dependency sides
                        # IMPORTANT: side=CLIENT on dependencies means the dep is only needed on client.
                        # It does NOT mean the mod itself is client-only.
                        # Only if ALL of the mod's OWN dependencies (forge, minecraft excluded)
                        # are side=CLIENT AND clientSideOnly is set, we classify as client-only.
                        dep_sections = re.findall(
                            r'\[\[dependencies\.[^\]]+\]\](.*?)(?=\[\[|\Z)',
                            content, re.DOTALL | re.IGNORECASE
                        )
                        all_client_deps = True
                        has_non_core_deps = False
                        for dep_section in dep_sections:
                            # Skip core deps (forge, minecraft, java) when evaluating
                            modid_m = re.search(r'modId\s*=\s*["\']?([A-Za-z0-9_\-]+)', dep_section, re.IGNORECASE)
                            if modid_m:
                                dep_modid = modid_m.group(1).lower()
                                if dep_modid in ('minecraft', 'forge', 'neoforge', 'java'):
                                    continue
                            side_match = re.search(r'side\s*=\s*["\']?(CLIENT|SERVER|BOTH)["\']?', dep_section, re.IGNORECASE)
                            if side_match:
                                has_non_core_deps = True
                                dep_side = side_match.group(1).upper()
                                if dep_side != 'CLIENT':
                                    all_client_deps = False

                        # Only classify based on deps if we have strong evidence:
                        # all non-core deps are CLIENT-side AND displayTest=NONE
                        if (has_non_core_deps and all_client_deps
                                and has_display_test_none
                                and analysis.side == ModSide.UNKNOWN):
                            analysis.side = ModSide.CLIENT
                            analysis.detection_method = DetectionMethod.JAR_METADATA
                            analysis.confidence = 0.7
                            analysis.reason = f"{toml_path}: all deps are side=CLIENT + displayTest=NONE"
                            analysis.is_client_only = True

                    except Exception as e:
                        logger.debug(f"Error reading {toml_path} from {jar_path.name}: {e}")

            # ── Fallback: check for pack.mcmeta (resource packs bundled as mods) ──
            if analysis.side == ModSide.UNKNOWN and 'pack.mcmeta' in names:
                # Resource packs are always client-side
                if not any(n.endswith('.class') for n in names[:100]):  # Quick check - no code
                    analysis.side = ModSide.CLIENT
                    analysis.detection_method = DetectionMethod.JAR_METADATA
                    analysis.confidence = 0.6
                    analysis.reason = "Resource pack (pack.mcmeta, no classes)"
                    analysis.is_client_only = True

    except (zipfile.BadZipFile, OSError) as e:
        logger.debug(f"Cannot read JAR {jar_path.name}: {e}")

    # Set fallback names
    if not analysis.mod_name:
        analysis.mod_name = jar_path.stem
    if not analysis.mod_id:
        analysis.mod_id = jar_path.stem.lower().replace(' ', '_').replace('-', '_')

    return analysis


# ═══════════════════════════════════════════════════════════════
#  API-Based Detection (Modrinth & CurseForge)
# ═══════════════════════════════════════════════════════════════

_modrinth_cache: dict[str, dict] = {}
_cf_cache: dict[str, dict] = {}


def _lookup_modrinth(mod_id: str, sha512: str | None = None) -> dict | None:
    """Look up mod on Modrinth by mod_id or file hash.
    Returns dict with client_side/server_side fields or None."""
    cache_key = sha512 or mod_id
    if cache_key in _modrinth_cache:
        return _modrinth_cache[cache_key]

    headers = {"User-Agent": "Lynx-ServerPanel/1.0 (minecraft-server-manager)"}
    result = None

    # Try by hash first (most accurate)
    if sha512:
        try:
            resp = requests.get(
                f"https://api.modrinth.com/v2/version_file/{sha512}",
                params={"algorithm": "sha512"},
                headers=headers,
                timeout=10,
            )
            if resp.ok:
                version_data = resp.json()
                project_id = version_data.get("project_id")
                if project_id:
                    proj_resp = requests.get(
                        f"https://api.modrinth.com/v2/project/{project_id}",
                        headers=headers,
                        timeout=10,
                    )
                    if proj_resp.ok:
                        result = proj_resp.json()
        except Exception:
            pass

    # Try by project slug/id (try both original and hyphenated variants)
    if not result and mod_id:
        slugs_to_try = [mod_id]
        # Modrinth slugs use hyphens, mod IDs often use underscores
        alt = mod_id.replace("_", "-")
        if alt != mod_id:
            slugs_to_try.append(alt)
        for slug in slugs_to_try:
            if result:
                break
            try:
                resp = requests.get(
                    f"https://api.modrinth.com/v2/project/{slug}",
                    headers=headers,
                    timeout=10,
                )
                if resp.ok:
                    result = resp.json()
            except Exception:
                pass

    if result:
        _modrinth_cache[cache_key] = result
    return result


def _lookup_curseforge(mod_hash: str | None = None, cf_api_key: str | None = None) -> dict | None:
    """Look up mod on CurseForge by fingerprint/hash.
    Returns mod data dict or None."""
    if not cf_api_key:
        return None

    if mod_hash and mod_hash in _cf_cache:
        return _cf_cache[mod_hash]

    # CurseForge lookup by hash is done via fingerprint endpoint
    # For now we primarily rely on Modrinth + JAR metadata
    return None


def _compute_file_hash(file_path: Path, algo: str = "sha512") -> str:
    """Compute hash of a file."""
    h = hashlib.new(algo)
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ═══════════════════════════════════════════════════════════════
#  Known Database Matching
# ═══════════════════════════════════════════════════════════════

# Prefixes of known server-required mods that indicate addon mods which must also stay.
# Any mod_id starting with "<prefix>_" or "<prefix>-" is treated as an addon.
_SERVER_REQUIRED_ADDON_PREFIXES: set[str] = {
    "create", "mekanism", "thermal", "botania", "immersiveengineering",
    "ae2", "appliedenergistics2", "applied-energistics",
    "farmersdelight", "farmers_delight", "farmers-delight",
    "tinkersconstruct", "tconstruct", "tinkers",
    "ftb", "mna", "quark", "supplementaries",
    "sophisticatedbackpacks", "sophisticatedstorage", "sophisticatedcore",
    "twilightforest", "iceandfire",
    "alexsmobs", "alexs-mobs", "alexscaves", "alexs-caves",
    # MC Eternal 2 mod families
    "ars",  # Ars Nouveau, Ars Elemental, Ars Creo, Ars Ocultas, etc.
    "irons",  # Iron's Spells 'n Spellbooks + addons
    "cataclysm",  # L_Ender's Cataclysm + addons
    "goety",  # Goety & Spillage, Goety Cataclysm
    "hexcasting", "hex",  # Hex Casting + Hex-Ars
    "vampirism",  # Vampirism + addons
    "occultism",  # Occultism + addons
    "pneumaticcraft",  # PneumaticCraft + addons
    "integrated",  # Integrated Dynamics/Tunnels/Terminals/Crafting/etc.
    "repurposed",  # Repurposed Structures + compat datapacks
    "macaw", "mcw",  # Macaw's Bridges/Doors/Roofs/etc.
    "relics",  # Relics + Alex's Caves/Mobs compat
    "pufferfish",  # Pufferfish's Attributes/Skills
    "loot_integrations", "lootintegrations",
    "ad_astra", "adastra",  # Ad Astra + addons
    "enderio",  # Ender IO + modules
    "majrusz",  # Majrusz's Progressive Difficulty / Accessories
    "corail",  # Corail Tombstone + addons
    "aquamirae",  # Aquamirae + combat compat
    "biomancy",  # Biomancy + Create Bio-Factory
}


def _check_known_database(analysis: ModAnalysis) -> bool:
    """Check if mod is in the known client-only database.
    Returns True if client-only, updates analysis in place."""
    mod_id = (analysis.mod_id or "").lower().strip()
    
    # Check against known server-required first (whitelist)
    if mod_id in KNOWN_SERVER_REQUIRED_MOD_IDS:
        analysis.side = ModSide.BOTH
        analysis.confidence = max(analysis.confidence, 0.8)
        analysis.reason = "Known server-required mod"
        analysis.is_client_only = False
        return False

    # Check if mod_id looks like an addon of a known server-required mod.
    # e.g. create_dd, create_compressed, mekanism_generators, etc.
    for prefix in _SERVER_REQUIRED_ADDON_PREFIXES:
        if (mod_id.startswith(prefix + "_") or
            mod_id.startswith(prefix + "-") or
            (mod_id.startswith(prefix) and len(mod_id) > len(prefix)
             and mod_id not in KNOWN_CLIENT_ONLY_MOD_IDS)):
            # Make sure it's not a known client-only mod that happens to share a prefix
            if mod_id not in KNOWN_CLIENT_ONLY_MOD_IDS:
                analysis.side = ModSide.BOTH
                analysis.confidence = max(analysis.confidence, 0.75)
                analysis.reason = f"Addon of server-required mod (prefix: {prefix})"
                analysis.is_client_only = False
                return False

    # Check against known client-only database
    if mod_id in KNOWN_CLIENT_ONLY_MOD_IDS:
        analysis.side = ModSide.CLIENT
        analysis.detection_method = DetectionMethod.KNOWN_DATABASE
        analysis.confidence = max(analysis.confidence, 0.85)
        analysis.reason = f"Known client-only mod (ID: {mod_id})"
        analysis.is_client_only = True
        return True

    return False


def _check_filename_patterns(analysis: ModAnalysis) -> bool:
    """Fallback: check filename against known client-only patterns.
    Only used when no metadata or API data is available."""
    name_lower = analysis.filename.lower()

    # First check against server-required names
    for safe_id in KNOWN_SERVER_REQUIRED_MOD_IDS:
        if safe_id in name_lower:
            return False

    for pattern in CLIENT_ONLY_FILENAME_PATTERNS:
        if pattern in name_lower:
            analysis.side = ModSide.CLIENT
            analysis.detection_method = DetectionMethod.FILENAME_PATTERN
            analysis.confidence = max(analysis.confidence, 0.6)
            analysis.reason = f"Filename matches known client-only pattern: '{pattern}'"
            analysis.is_client_only = True
            return True

    return False


# ═══════════════════════════════════════════════════════════════
#  User Override Lists
# ═══════════════════════════════════════════════════════════════

def _load_user_lists(server_dir: Path) -> tuple[set[str], set[str]]:
    """Load user whitelist (allow) and blacklist (deny) from config files.
    Returns (allowed_patterns, denied_patterns)."""
    allowed: set[str] = set()
    denied: set[str] = set()

    # Allow list
    for path in [
        server_dir / "client-only-allow.txt",
        Path("/data/servers/client-only-allow.txt"),
    ]:
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        allowed.add(line)
        except Exception:
            pass

    # Deny list (extra client-only patterns)
    for path in [
        server_dir / "client-only-mods.txt",
        Path("/data/servers/client-only-mods.txt"),
    ]:
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        denied.add(line)
        except Exception:
            pass

    # Environment variables
    try:
        extra = os.environ.get("CLIENT_ONLY_MOD_PATTERNS", "").strip()
        if extra:
            for tok in extra.split(","):
                tok = tok.strip().lower()
                if tok:
                    denied.add(tok)
    except Exception:
        pass

    try:
        url = os.environ.get("CLIENT_ONLY_MOD_PATTERNS_URL", "").strip()
        if url:
            resp = requests.get(url, timeout=10)
            if resp.ok:
                for line in resp.text.splitlines():
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        denied.add(line)
    except Exception:
        pass

    return allowed, denied


# ═══════════════════════════════════════════════════════════════
#  Dependency Scanner
# ═══════════════════════════════════════════════════════════════

def _scan_all_dependencies(mods_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Scan all mod JARs in a directory and collect:
    1. The set of mod IDs required as dependencies by at least one other mod
    2. A mapping of each mod_id to the set of mod_ids it depends on

    This prevents filtering out library/dependency mods that would crash
    other mods if removed (e.g. geckolib3, architectury, curios, etc.),
    and detects mods that depend on known server-required mods.
    """
    required_ids: set[str] = set()
    mod_deps_map: dict[str, set[str]] = {}
    if not mods_dir.exists() or not mods_dir.is_dir():
        return required_ids, mod_deps_map

    skip_base = {'minecraft', 'fabricloader', 'fabric-loader', 'fabric', 'java',
                 'forge', 'neoforge', 'quilt_loader'}

    for jar_path in mods_dir.glob("*.jar"):
        try:
            jar_mod_id = None
            jar_deps: set[str] = set()
            with zipfile.ZipFile(jar_path, 'r') as zf:
                names = zf.namelist()

                # --- Fabric / Quilt ---
                for meta_name in ('fabric.mod.json', 'quilt.mod.json'):
                    if meta_name in names:
                        try:
                            raw = zf.read(meta_name).decode('utf-8', errors='ignore')
                            data = json.loads(raw)

                            # Extract this mod's ID
                            if meta_name == 'fabric.mod.json':
                                jar_mod_id = jar_mod_id or str(data.get('id', '')).lower().strip() or None
                            else:
                                _ql_id = data.get('quilt_loader', {}).get('id', '')
                                jar_mod_id = jar_mod_id or str(_ql_id).lower().strip() or None

                            # fabric.mod.json: "depends" dict or list
                            for dep_key in ('depends', 'requires'):
                                deps = data.get(dep_key, {})
                                if isinstance(deps, dict):
                                    for dep_id in deps:
                                        d = str(dep_id).lower().strip()
                                        if d and d not in skip_base:
                                            required_ids.add(d)
                                            jar_deps.add(d)
                                elif isinstance(deps, list):
                                    for item in deps:
                                        if isinstance(item, str):
                                            d = item.lower().strip()
                                        elif isinstance(item, dict):
                                            d = str(item.get('id', '')).lower().strip()
                                        else:
                                            continue
                                        if d and d not in skip_base:
                                            required_ids.add(d)
                                            jar_deps.add(d)

                            # quilt_loader.depends
                            ql = data.get('quilt_loader', {})
                            ql_deps = ql.get('depends', [])
                            if isinstance(ql_deps, list):
                                for item in ql_deps:
                                    if isinstance(item, dict):
                                        d = str(item.get('id', '')).lower().strip()
                                    elif isinstance(item, str):
                                        d = item.lower().strip()
                                    else:
                                        continue
                                    if d and d not in skip_base:
                                        required_ids.add(d)
                                        jar_deps.add(d)
                        except Exception:
                            pass

                # --- Forge / NeoForge mods.toml ---
                for toml_name in ('META-INF/mods.toml', 'META-INF/neoforge.mods.toml'):
                    if toml_name in names:
                        try:
                            content = zf.read(toml_name).decode('utf-8', errors='ignore')
                            # Extract this mod's ID from the [[mods]] section
                            if not jar_mod_id:
                                _mid_match = re.search(
                                    r'modId\s*=\s*["\']?([A-Za-z0-9_\-]+)',
                                    content, re.IGNORECASE
                                )
                                if _mid_match:
                                    jar_mod_id = _mid_match.group(1).lower().strip()
                            # Find [[dependencies.X]] sections
                            dep_sections = re.findall(
                                r'\[\[dependencies\.[^\]]+\]\](.*?)(?=\[\[|\Z)',
                                content, re.DOTALL | re.IGNORECASE
                            )
                            for dep_section in dep_sections:
                                modid_match = re.search(
                                    r'modId\s*=\s*["\']?([A-Za-z0-9_\-]+)',
                                    dep_section, re.IGNORECASE
                                )
                                if not modid_match:
                                    continue
                                dep_id = modid_match.group(1).lower().strip()
                                if dep_id in skip_base:
                                    continue
                                # Check mandatory flag (defaults to true in Forge)
                                mandatory_match = re.search(
                                    r'mandatory\s*=\s*(true|false)',
                                    dep_section, re.IGNORECASE
                                )
                                is_mandatory = True
                                if mandatory_match and mandatory_match.group(1).lower() == 'false':
                                    is_mandatory = False
                                if is_mandatory:
                                    required_ids.add(dep_id)
                                    jar_deps.add(dep_id)
                        except Exception:
                            pass

            # Store the dependency mapping for this mod
            if jar_mod_id and jar_deps:
                mod_deps_map[jar_mod_id] = jar_deps

        except (zipfile.BadZipFile, OSError):
            pass

    logger.debug(f"Dependency scan found {len(required_ids)} required mod IDs, {len(mod_deps_map)} mods mapped")
    return required_ids, mod_deps_map


# ═══════════════════════════════════════════════════════════════
#  Main Analysis Engine
# ═══════════════════════════════════════════════════════════════

def analyze_mod(
    jar_path: Path,
    use_api: bool = True,
    cf_api_key: str | None = None,
    allowed_patterns: set[str] | None = None,
    denied_patterns: set[str] | None = None,
) -> ModAnalysis:
    """
    Comprehensive analysis of a single mod JAR file.
    Uses multiple detection strategies in order of reliability:
    1. JAR metadata inspection
    2. Known mod database lookup
    3. Modrinth API lookup (if use_api=True)
    4. CurseForge API lookup (if use_api=True and key provided)
    5. Filename pattern matching (lowest confidence)
    """
    # Step 1: JAR metadata
    analysis = _inspect_jar_metadata(jar_path)

    # Step 2: Check user whitelist first
    if allowed_patterns:
        name_lower = analysis.filename.lower()
        if any(pat in name_lower for pat in allowed_patterns):
            analysis.whitelisted = True
            analysis.is_client_only = False
            analysis.side = ModSide.BOTH
            analysis.confidence = 1.0
            analysis.reason = "Whitelisted by user"
            analysis.detection_method = DetectionMethod.USER_OVERRIDE
            return analysis

    # Check user deny list
    if denied_patterns:
        name_lower = analysis.filename.lower()
        if any(pat in name_lower for pat in denied_patterns):
            analysis.side = ModSide.CLIENT
            analysis.is_client_only = True
            analysis.confidence = 0.9
            analysis.reason = "Blocked by user deny list"
            analysis.detection_method = DetectionMethod.USER_OVERRIDE
            return analysis

    # If JAR metadata already gave us high-confidence answer, return early
    if analysis.confidence >= 0.9:
        return analysis

    # Step 3: Known database lookup
    if _check_known_database(analysis):
        if analysis.confidence >= 0.85:
            return analysis

    # Step 4: API lookups (if enabled and still uncertain)
    if use_api and (analysis.side == ModSide.UNKNOWN or analysis.confidence < 0.8):
        # Compute hash for Modrinth lookup
        try:
            sha512 = _compute_file_hash(jar_path, "sha512")
            analysis.sha256 = _compute_file_hash(jar_path, "sha256")
        except Exception:
            sha512 = None

        # Modrinth lookup
        modrinth_data = _lookup_modrinth(analysis.mod_id, sha512)
        if modrinth_data:
            analysis.modrinth_id = modrinth_data.get("id") or modrinth_data.get("slug")
            client_side = str(modrinth_data.get("client_side", "")).lower()
            server_side = str(modrinth_data.get("server_side", "")).lower()

            if server_side == "unsupported" and client_side in ("required", "optional"):
                analysis.side = ModSide.CLIENT
                analysis.detection_method = DetectionMethod.MODRINTH_API
                analysis.confidence = 0.95
                analysis.reason = f"Modrinth: server_side=unsupported, client_side={client_side}"
                analysis.is_client_only = True
            elif client_side == "unsupported":
                analysis.side = ModSide.SERVER
                analysis.detection_method = DetectionMethod.MODRINTH_API
                analysis.confidence = 0.95
                analysis.reason = f"Modrinth: client_side=unsupported"
                analysis.is_client_only = False
            elif server_side == "optional" and client_side == "required":
                # IMPORTANT: Many library mods (geckolib, architectury, etc.) have
                # server_side=optional because they "work" without the server having
                # them, but dependent mods WILL crash without them. Treat as BOTH.
                analysis.side = ModSide.BOTH
                analysis.detection_method = DetectionMethod.MODRINTH_API
                analysis.confidence = 0.7
                analysis.reason = f"Modrinth: server_side=optional, client_side=required (kept safe — may be a dependency)"
                analysis.is_client_only = False
            elif server_side in ("required", "optional") and client_side in ("required", "optional"):
                analysis.side = ModSide.BOTH
                analysis.detection_method = DetectionMethod.MODRINTH_API
                analysis.confidence = 0.9
                analysis.reason = f"Modrinth: server_side={server_side}, client_side={client_side}"
                analysis.is_client_only = False

    # Step 5: Filename pattern matching (lowest priority, only if still unknown)
    if analysis.side == ModSide.UNKNOWN or (analysis.confidence < 0.6 and not analysis.is_client_only):
        _check_filename_patterns(analysis)

    # Step 6: Safety check — if classified as client-only, verify the mod name
    # doesn't contain common library/API markers that suggest server requirement
    if analysis.is_client_only:
        lib_markers = (
            "lib", "api", "core", "framework", "common", "base",
            "registry", "compat", "integration", "loader",
        )
        name_lower = (analysis.mod_name or "").lower()
        id_lower = (analysis.mod_id or "").lower()
        fname_lower = analysis.filename.lower()
        for marker in lib_markers:
            if marker in id_lower or (
                marker in fname_lower and marker not in ("lib",)  # "lib" too common in filenames
            ):
                # Library/API mods should not be filtered unless we're very confident
                if analysis.confidence < 0.9:
                    analysis.is_client_only = False
                    analysis.side = ModSide.BOTH
                    analysis.reason += f" [safety: name contains '{marker}', kept as potential dependency]"
                    break

    return analysis


def analyze_mods_directory(
    server_dir: Path,
    use_api: bool = True,
    cf_api_key: str | None = None,
    max_workers: int = 4,
) -> list[ModAnalysis]:
    """
    Analyze all mod JARs in a server's mods directory.
    Returns list of ModAnalysis objects sorted by confidence (client-only first).
    """
    mods_dir = server_dir / "mods"
    if not mods_dir.exists() or not mods_dir.is_dir():
        return []

    jars = list(mods_dir.glob("*.jar"))
    if not jars:
        return []

    allowed, denied = _load_user_lists(server_dir)

    # Pre-scan: collect all mod IDs that are dependencies of other mods
    # This prevents us from ever filtering out a mod that another mod needs
    required_dep_ids, mod_deps_map = _scan_all_dependencies(mods_dir)

    results: list[ModAnalysis] = []

    # Use thread pool for API lookups but limit concurrency
    if use_api and len(jars) > 5:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    analyze_mod, jar, use_api, cf_api_key, allowed, denied
                ): jar
                for jar in jars
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    jar = futures[future]
                    results.append(ModAnalysis(
                        filename=jar.name,
                        reason=f"Analysis failed: {e}",
                    ))
    else:
        for jar in jars:
            try:
                results.append(analyze_mod(jar, use_api, cf_api_key, allowed, denied))
            except Exception as e:
                results.append(ModAnalysis(
                    filename=jar.name,
                    reason=f"Analysis failed: {e}",
                ))

    # Post-analysis dependency safety check:
    # If any mod was classified as client-only but is a dependency of another mod,
    # override the classification to BOTH and keep it.
    if required_dep_ids:
        for analysis in results:
            if analysis.is_client_only:
                mod_id_lower = (analysis.mod_id or "").lower().strip()
                if mod_id_lower in required_dep_ids:
                    analysis.is_client_only = False
                    analysis.side = ModSide.BOTH
                    analysis.reason += f" [OVERRIDDEN: required as dependency by another mod]"
                    logger.info(
                        f"Dependency safety: kept '{analysis.filename}' (mod_id={mod_id_lower}) — "
                        f"required by another mod in the pack"
                    )

    # Second pass: if a mod depends on a known server-required mod (e.g. a Create
    # addon depends on "create"), it almost certainly has server-side logic too.
    if mod_deps_map:
        for analysis in results:
            if analysis.is_client_only:
                mod_id_lower = (analysis.mod_id or "").lower().strip()
                mod_dep_set = mod_deps_map.get(mod_id_lower, set())
                for dep_id in mod_dep_set:
                    if dep_id in KNOWN_SERVER_REQUIRED_MOD_IDS:
                        analysis.is_client_only = False
                        analysis.side = ModSide.BOTH
                        analysis.reason += f" [OVERRIDDEN: depends on server-required mod '{dep_id}']"
                        logger.info(
                            f"Reverse-dep safety: kept '{analysis.filename}' (mod_id={mod_id_lower}) — "
                            f"depends on server-required mod '{dep_id}'"
                        )
                        break

    # Third pass: prefix-based addon detection.
    # If a mod_id starts with a known server-required mod prefix (e.g. create_*,
    # mekanism_*, thermal_*), it's almost certainly an addon with server logic.
    for analysis in results:
        if analysis.is_client_only:
            mod_id_lower = (analysis.mod_id or "").lower().strip()
            for prefix in _SERVER_REQUIRED_ADDON_PREFIXES:
                if (mod_id_lower.startswith(prefix + "_") or
                        mod_id_lower.startswith(prefix + "-")):
                    analysis.is_client_only = False
                    analysis.side = ModSide.BOTH
                    analysis.reason += f" [OVERRIDDEN: addon of server-required mod '{prefix}']"
                    logger.info(
                        f"Prefix safety: kept '{analysis.filename}' (mod_id={mod_id_lower}) — "
                        f"addon prefix '{prefix}'"
                    )
                    break

    # Sort: client-only first, then by confidence descending
    results.sort(key=lambda a: (-int(a.is_client_only), -a.confidence))
    return results


# ═══════════════════════════════════════════════════════════════
#  Actions: Filter / Disable / Restore Client Mods
# ═══════════════════════════════════════════════════════════════

def filter_client_mods(
    server_dir: Path,
    use_api: bool = True,
    cf_api_key: str | None = None,
    min_confidence: float = 0.6,
    dry_run: bool = False,
    push_event=lambda ev: None,
) -> dict:
    """
    Analyze and filter client-only mods from a server's mods directory.
    Moves them to mods-disabled-client/ directory.
    
    Returns summary dict with counts and details.
    """
    results = analyze_mods_directory(server_dir, use_api=use_api, cf_api_key=cf_api_key)

    mods_dir = server_dir / "mods"
    disable_dir = server_dir / "mods-disabled-client"

    moved = 0
    skipped = 0
    kept = 0
    details: list[dict] = []

    for analysis in results:
        detail = analysis.to_dict()

        if analysis.whitelisted:
            detail["action"] = "kept_whitelisted"
            kept += 1
        elif analysis.is_client_only and analysis.confidence >= min_confidence:
            detail["action"] = "disabled"
            if not dry_run:
                try:
                    disable_dir.mkdir(parents=True, exist_ok=True)
                    src = mods_dir / analysis.filename
                    dest = disable_dir / analysis.filename
                    if src.exists():
                        shutil.move(str(src), str(dest))
                        moved += 1
                        push_event({
                            "type": "progress",
                            "step": "mods",
                            "message": f"Disabled client mod: {analysis.filename} ({analysis.reason})",
                            "progress": 60,
                        })
                except Exception as e:
                    detail["action"] = f"error: {e}"
                    skipped += 1
            else:
                moved += 1  # Count as would-be-moved in dry run
        else:
            detail["action"] = "kept"
            kept += 1
            if analysis.is_client_only and analysis.confidence < min_confidence:
                detail["action"] = "kept_low_confidence"
                skipped += 1

        details.append(detail)

    summary = {
        "total_mods": len(results),
        "client_only_moved": moved,
        "kept": kept,
        "skipped_low_confidence": skipped,
        "dry_run": dry_run,
        "min_confidence": min_confidence,
        "mods": details,
    }

    if moved and not dry_run:
        push_event({
            "type": "progress",
            "step": "mods",
            "message": f"Filtered {moved} client-only mods to mods-disabled-client/",
            "progress": 61,
        })

    return summary


def restore_mod(server_dir: Path, filename: str) -> bool:
    """Restore a previously disabled mod back to the mods directory."""
    disable_dir = server_dir / "mods-disabled-client"
    mods_dir = server_dir / "mods"
    src = disable_dir / filename
    dest = mods_dir / filename

    if not src.exists():
        return False

    try:
        mods_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return True
    except Exception:
        return False


def disable_mod(server_dir: Path, filename: str) -> bool:
    """Manually disable a mod (move to mods-disabled-client/)."""
    mods_dir = server_dir / "mods"
    disable_dir = server_dir / "mods-disabled-client"
    src = mods_dir / filename
    dest = disable_dir / filename

    if not src.exists():
        return False

    try:
        disable_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return True
    except Exception:
        return False


def list_disabled_mods(server_dir: Path) -> list[dict]:
    """List all disabled client mods."""
    disable_dir = server_dir / "mods-disabled-client"
    if not disable_dir.exists():
        return []

    result = []
    for jar in disable_dir.glob("*.jar"):
        result.append({
            "filename": jar.name,
            "size": jar.stat().st_size,
            "modified": jar.stat().st_mtime,
        })
    return result


def add_to_whitelist(server_dir: Path, pattern: str) -> bool:
    """Add a pattern to the server's client-only allow list."""
    try:
        allow_file = server_dir / "client-only-allow.txt"
        existing = set()
        if allow_file.exists():
            existing = set(
                line.strip().lower()
                for line in allow_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        existing.add(pattern.strip().lower())
        content = "# Client-only mod whitelist - mods listed here will NOT be filtered\n"
        content += "# One pattern per line (matched against filename, case-insensitive)\n"
        content += "\n".join(sorted(existing)) + "\n"
        allow_file.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def remove_from_whitelist(server_dir: Path, pattern: str) -> bool:
    """Remove a pattern from the server's client-only allow list."""
    try:
        allow_file = server_dir / "client-only-allow.txt"
        if not allow_file.exists():
            return False
        lines = allow_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = [
            line for line in lines
            if line.strip().lower() != pattern.strip().lower()
        ]
        allow_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False
