"""
Automatisierte Tests für das `ModSideResolver`-System (Abschnitt 11 & 12).

Deckt ab:
  1. Alle 10 FTB Evolution 2 Regressions-Mods (ohne modpack-spezifisches Hardcoding!)
  2. Alle 14 geforderten Testszenarien:
     - Eindeutige Client-only-Mod (Sodium/Iris/Controlling)
     - Eindeutige Server-only-Mod
     - Mod mit Client- und Server-Anteil (BOTH_SIDES_REQUIRED)
     - Gemeinsame Bibliothek (Abhängigkeitsgraph schützt Library)
     - Mod mit fehlerhaften/widersprüchlichen Metadaten (Konflikterkennung -> UNKNOWN -> bleibt auf Server)
     - Mod mit eingebetteten Abhängigkeiten (Jar-in-Jar META-INF/jarjar/metadata.json)
     - Fabric-Mod (fabric.mod.json environment="client" vs "*")
     - NeoForge-Mod (META-INF/neoforge.mods.toml)
     - Forge-Mod (META-INF/mods.toml)
     - Quilt-Mod (quilt.mod.json)
     - Modpack mit offiziellem Server-Pack (Validierung & Nachfilterung)
     - Modpack ohne offizielles Server-Pack (Client-Pack-Konvertierung + Datapack-Erhalt)
     - Unbekannte Mod ohne Online-Metadaten (UNKNOWN bleibt immer auf Server)
     - Cache-Wiederverwendung und Versions-/Loader-Wechsel
"""

from __future__ import annotations

import json
import struct
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mod_side_resolver import (
    ModSideResolver,
    ModSideCache,
    ModSideCategory,
    ConfidenceLevel,
)
from client_mod_detector import process_client_pack


# ---------------------------------------------------------------------------
# Technischer JVM .class & .jar Generator für realistische Bytecode-Tests
# ---------------------------------------------------------------------------


def build_jvm_class_bytes(
    this_class_name: str = "com/example/TestMod",
    super_class_name: str = "java/lang/Object",
    interfaces: Optional[List[str]] = None,
    utf8_constants: Optional[List[str]] = None,
    class_annotations: Optional[List[Tuple[str, List[Tuple[str, str, str]]]]] = None,
) -> bytes:
    """
    Erzeugt eine valide JVM `.class`-Binärdatei (Magic 0xCAFEBABE, Version 65.0 / Java 21)
    inklusive Constant-Pool, Interfaces und `RuntimeVisibleAnnotations`-Attributen nach JVM Spec §4.7.16.

    `class_annotations`: Liste von `(annotation_descriptor, [(element_name, enum_desc, enum_const_name), ...])`
    z.B. `[("Lnet/neoforged/fml/common/Mod;", [("dist", "Lnet/neoforged/api/distmarker/Dist;", "CLIENT")])]`
    """
    interfaces = interfaces or []
    utf8_constants = list(utf8_constants or [])
    class_annotations = class_annotations or []

    cp_entries: List[bytes] = []
    utf8_index: Dict[str, int] = {}
    class_index: Dict[str, int] = {}

    def add_utf8(s: str) -> int:
        if s in utf8_index:
            return utf8_index[s]
        raw = s.encode("utf-8")
        entry = b"\x01" + struct.pack(">H", len(raw)) + raw
        cp_entries.append(entry)
        idx = len(cp_entries)
        utf8_index[s] = idx
        return idx

    def add_class(internal_name: str) -> int:
        if internal_name in class_index:
            return class_index[internal_name]
        name_idx = add_utf8(internal_name)
        entry = b"\x07" + struct.pack(">H", name_idx)
        cp_entries.append(entry)
        idx = len(cp_entries)
        class_index[internal_name] = idx
        return idx

    this_cls_idx = add_class(this_class_name)
    super_cls_idx = add_class(super_class_name)
    iface_indices = [add_class(ifc) for ifc in interfaces]

    for s in utf8_constants:
        add_utf8(s)

    # Baue optionales RuntimeVisibleAnnotations Attribut
    attributes_bytes = b""
    attributes_count = 0
    if class_annotations:
        rva_name_idx = add_utf8("RuntimeVisibleAnnotations")
        ann_payload = struct.pack(">H", len(class_annotations))
        for ann_desc, pairs in class_annotations:
            type_idx = add_utf8(ann_desc)
            ann_payload += struct.pack(">HH", type_idx, len(pairs))
            for elem_name, enum_desc, enum_const in pairs:
                elem_idx = add_utf8(elem_name)
                enum_desc_idx = add_utf8(enum_desc)
                enum_const_idx = add_utf8(enum_const)
                # Tag 'e' = enum_const_value
                ann_payload += struct.pack(">H", elem_idx) + b"e" + struct.pack(">HH", enum_desc_idx, enum_const_idx)

        attributes_bytes = struct.pack(">HI", rva_name_idx, len(ann_payload)) + ann_payload
        attributes_count = 1

    header = struct.pack(
        ">IHHH",
        0xCAFEBABE,
        0,  # minor
        65,  # major (Java 21)
        len(cp_entries) + 1,
    )
    cp_blob = b"".join(cp_entries)
    body = struct.pack(
        ">HHHH",
        0x0021,  # ACC_PUBLIC | ACC_SUPER
        this_cls_idx,
        super_cls_idx,
        len(iface_indices),
    )
    for ii in iface_indices:
        body += struct.pack(">H", ii)
    # fields_count=0, methods_count=0, attributes_count
    body += struct.pack(">HHH", 0, 0, attributes_count) + attributes_bytes
    return header + cp_blob + body


def create_mod_jar(
    jar_path: Path,
    files: Dict[str, bytes | str],
) -> Path:
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(arcname, data)
    return jar_path


# Standard NeoForge TOML-Vorlage MIT dem berühmten auskommentierten `#clientSideOnly=true` Kommentar
NEOFORGE_MDK_COMMENT_TEMPLATE = """
modLoader="javafml"
loaderVersion="[4,)"
license="MIT"
# A boolean value declaring whether this mod is client side only.
#clientSideOnly=true

[[mods]]
modId="{mod_id}"
version="{version}"
displayName="{display_name}"
description="Test mod with commented clientSideOnly in template"
"""


# ---------------------------------------------------------------------------
# 1. REGRESSIONSTESTS: Die 10 FTB Evolution 2 Mods (Abschnitt 12)
# ---------------------------------------------------------------------------


def test_ftb_evolution_2_regression_suite(tmp_path: Path):
    """
    Prüft alle 10 im Master-Prompt genannten Mods aus FTB Evolution 2 anhand ihrer
    realen technischen Eigenschaften (TOML-Metadaten inkl. `#clientSideOnly=true`-Kommentar,
    Bytecode-Registrierungen, Netzwerk-Payloads, Weltgenerierungsdaten und Abhängigkeitsgraph):

      1. Controlling-neoforge-26.1.2-26.1.2.7.jar -> CLIENT_ONLY (Keybind-Screen/Client-Events)
      2. refinedstorage-jei-integration-neoforge-2.0.1.jar -> BOTH_SIDES_REQUIRED (Netzwerk-Payloads + Dependency auf jei)
      3. EclipseUI-neoforge-1.0.4+mc26.1.jar -> bleibt auf Server (UI/Common Library mit `#clientSideOnly=true`-Kommentar)
      4. RBMAddon26.1.2-beta3.jar -> bleibt auf Server (Gameplay/Addon-Mod mit `#clientSideOnly=true`-Kommentar)
      5. rgp-client-2.1.2+mc26.1.2-neoforge.jar -> bleibt auf Server (`client` im Dateinamen ist KEIN Beweis!)
      6. appleskin-neoforge-mc26.1-3.0.9.jar -> bleibt auf Server (Server-Netzwerksynchronisation für Saturation/Exhaustion)
      7. jei-26.1.2-neoforge-29.47.0.111.jar -> bleibt auf Server (Server-Recipe-Transfer-Channel + benötigt von refinedstorage-jei-integration)
      8. authme-neoforge-9.2.1+26.1.jar -> CLIENT_ONLY wenn reine Client-Auth-Mod mit clientSideOnly=true (bzw. entsprechend technischer Metadaten)
      9. MoogsTemplesReimagined-universal-1.21-2.0.4.jar -> BOTH_SIDES_REQUIRED (Strukturen/Worldgen in `data/`)
     10. AdvancedCoreInfo-neoforge-26.1.2-1.5.0.jar -> bleibt auf Server (Common/Server-Klassen + `#clientSideOnly=true`-Kommentar)
    """
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    cache = ModSideCache(tmp_path / "test_cache.sqlite3")
    resolver = ModSideResolver(cache=cache, enable_network=False, minecraft_version="1.21.1", modloader="neoforge")

    # 1. Controlling: Explizit Client-only (neoforge.mods.toml clientSideOnly=true + @Mod(dist=Dist.CLIENT) + KeyMapping)
    create_mod_jar(
        mods_dir / "Controlling-neoforge-26.1.2-26.1.2.7.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
license="MIT"
clientSideOnly=true
[[mods]]
modId="controlling"
version="26.1.2.7"
displayName="Controlling"
""",
            "com/blamejared/controlling/ControllingClient.class": build_jvm_class_bytes(
                this_class_name="com/blamejared/controlling/ControllingClient",
                utf8_constants=[
                    "net/minecraft/client/KeyMapping",
                    "net/minecraft/client/gui/screens/options/controls/KeyBindsScreen",
                    "net/neoforged/neoforge/client/event/ScreenEvent",
                ],
                class_annotations=[
                    ("Lnet/neoforged/fml/common/Mod;", [("dist", "Lnet/neoforged/api/distmarker/Dist;", "CLIENT")])
                ],
            ),
        },
    )

    # 2. refinedstorage-jei-integration: Hat `#clientSideOnly=true` als Kommentar, registriert Netzwerk-Payloads und benötigt `jei`
    create_mod_jar(
        mods_dir / "refinedstorage-jei-integration-neoforge-2.0.1.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="refinedstorage_jei_integration",
                version="2.0.1",
                display_name="Refined Storage - JEI Integration",
            )
            + """
[[dependencies.refinedstorage_jei_integration]]
modId="jei"
type="required"
side="BOTH"
versionRange="[19.0,)"
""",
            "com/refinedmods/refinedstorage/jei/ModInitializer.class": build_jvm_class_bytes(
                this_class_name="com/refinedmods/refinedstorage/jei/ModInitializer",
                utf8_constants=[
                    "net/minecraft/network/protocol/common/custom/CustomPacketPayload",
                    "net/neoforged/neoforge/network/registration/PayloadRegistrar",
                    "net/minecraft/world/inventory/AbstractContainerMenu",
                ],
            ),
        },
    )

    # 3. EclipseUI: UI/Common-Bibliothek mit `#clientSideOnly=true`-Kommentar und GUI-Klassen ohne Client-only-Zwang
    create_mod_jar(
        mods_dir / "EclipseUI-neoforge-1.0.4+mc26.1.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="eclipseui",
                version="1.0.4",
                display_name="EclipseUI",
            ),
            "dev/eclipseui/core/EclipseUICommon.class": build_jvm_class_bytes(
                this_class_name="dev/eclipseui/core/EclipseUICommon",
                utf8_constants=[
                    "net/minecraft/network/chat/Component",
                    "net/minecraft/resources/ResourceLocation",
                    "net/minecraft/client/gui/GuiGraphics",
                ],
            ),
        },
    )

    # 4. RBMAddon: Addon-Mod mit `#clientSideOnly=true`-Kommentar und Item/Block-Registrierungen
    create_mod_jar(
        mods_dir / "RBMAddon26.1.2-beta3.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="rbmaddon",
                version="26.1.2-beta3",
                display_name="RBM Addon",
            ),
            "com/rbm/addon/RBMAddon.class": build_jvm_class_bytes(
                this_class_name="com/rbm/addon/RBMAddon",
                utf8_constants=[
                    "net/neoforged/neoforge/registries/DeferredRegister",
                    "net/minecraft/world/item/Item",
                ],
            ),
        },
    )

    # 5. rgp-client: Enthält `client` im Dateinamen! Laut Abschnitt 5 ist Dateiname mit `client` KEIN ausreichender Beweis!
    create_mod_jar(
        mods_dir / "rgp-client-2.1.2+mc26.1.2-neoforge.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="rgp_client",
                version="2.1.2",
                display_name="RGP Client Sync",
            ),
            "com/rgp/sync/RgpMod.class": build_jvm_class_bytes(
                this_class_name="com/rgp/sync/RgpMod",
                utf8_constants=[
                    "net/minecraft/network/protocol/common/custom/CustomPacketPayload",
                    "net/minecraft/server/level/ServerPlayer",
                ],
            ),
        },
    )

    # 6. AppleSkin: Enthält Client-HUD-Klassen UND Server-Sync-Events/Payloads (ServerPlayer + PayloadRegistrar)
    create_mod_jar(
        mods_dir / "appleskin-neoforge-mc26.1-3.0.9.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="appleskin",
                version="3.0.9",
                display_name="AppleSkin",
            ),
            "squeek/appleskin/AppleSkin.class": build_jvm_class_bytes(
                this_class_name="squeek/appleskin/AppleSkin",
                utf8_constants=[
                    "net/minecraft/server/level/ServerPlayer",
                    "net/neoforged/neoforge/network/registration/PayloadRegistrar",
                    "net/minecraft/client/gui/GuiGraphics",
                ],
            ),
        },
    )

    # 7. JEI: Enthält Client-GUI-Klassen UND Server-Netzwerkkanäle (und wird von refinedstorage-jei-integration benötigt)
    create_mod_jar(
        mods_dir / "jei-26.1.2-neoforge-29.47.0.111.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="jei",
                version="29.47.0.111",
                display_name="Just Enough Items",
            ),
            "mezz/jei/neoforge/JustEnoughItems.class": build_jvm_class_bytes(
                this_class_name="mezz/jei/neoforge/JustEnoughItems",
                utf8_constants=[
                    "net/minecraft/network/protocol/common/custom/CustomPacketPayload",
                    "net/minecraft/world/inventory/AbstractContainerMenu",
                    "net/minecraft/client/gui/screens/Screen",
                ],
            ),
        },
    )

    # 8. AuthMe: Reine Client-Authentifizierungs-Mod (`clientSideOnly=true` + Client-Screen-Events)
    create_mod_jar(
        mods_dir / "authme-neoforge-9.2.1+26.1.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
license="MIT"
clientSideOnly=true
[[mods]]
modId="authme"
version="9.2.1"
displayName="Auth Me"
""",
            "me/axieum/mcmod/authme/AuthMeClient.class": build_jvm_class_bytes(
                this_class_name="me/axieum/mcmod/authme/AuthMeClient",
                utf8_constants=[
                    "net/minecraft/client/Minecraft",
                    "net/minecraft/client/gui/screens/TitleScreen",
                    "net/neoforged/neoforge/client/event/ScreenEvent",
                ],
                class_annotations=[
                    ("Lnet/neoforged/fml/common/Mod;", [("dist", "Lnet/neoforged/api/distmarker/Dist;", "CLIENT")])
                ],
            ),
        },
    )

    # 9. MoogsTemplesReimagined: Struktur-/Weltgenerierungs-Mod (`data/mvs/worldgen/...` & `data/mvs/structure/...`)
    create_mod_jar(
        mods_dir / "MoogsTemplesReimagined-universal-1.21-2.0.4.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="mvs",
                version="2.0.4",
                display_name="Moog's Temples Reimagined",
            ),
            "data/mvs/worldgen/structure/ancient_temple.json": '{"type": "minecraft:jigsaw"}',
            "data/mvs/structure/ancient_temple.nbt": b"\x00\x01",
        },
    )

    # 10. AdvancedCoreInfo: Core-Mod mit `#clientSideOnly=true`-Kommentar und Server-/Common-Logik
    create_mod_jar(
        mods_dir / "AdvancedCoreInfo-neoforge-26.1.2-1.5.0.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="advancedcoreinfo",
                version="1.5.0",
                display_name="AdvancedCoreInfo",
            ),
            "com/aci/AdvancedCoreInfo.class": build_jvm_class_bytes(
                this_class_name="com/aci/AdvancedCoreInfo",
                utf8_constants=[
                    "net/minecraft/server/MinecraftServer",
                    "net/neoforged/neoforge/event/server/ServerStartingEvent",
                ],
            ),
        },
    )

    # Führe vollständige Server-Filterung aus
    report = resolver.filter_server_mods(tmp_path, minecraft_version="1.21.1", modloader="neoforge")

    remaining_files = {p.name for p in mods_dir.glob("*.jar")}
    disabled_files = {p.name for p in (tmp_path / "mods-disabled-client").glob("*.jar")}

    # Controlling & AuthMe (explizit Client-only) müssen verschoben worden sein
    assert "Controlling-neoforge-26.1.2-26.1.2.7.jar" in disabled_files
    assert "authme-neoforge-9.2.1+26.1.jar" in disabled_files

    # Alle Server-, Worldgen-, Netzwerk-, Library- und falsch-benannten Mods MÜSSEN auf dem Server bleiben!
    must_keep = {
        "refinedstorage-jei-integration-neoforge-2.0.1.jar",
        "EclipseUI-neoforge-1.0.4+mc26.1.jar",
        "RBMAddon26.1.2-beta3.jar",
        "rgp-client-2.1.2+mc26.1.2-neoforge.jar",
        "appleskin-neoforge-mc26.1-3.0.9.jar",
        "jei-26.1.2-neoforge-29.47.0.111.jar",
        "MoogsTemplesReimagined-universal-1.21-2.0.4.jar",
        "AdvancedCoreInfo-neoforge-26.1.2-1.5.0.jar",
    }
    assert must_keep.issubset(remaining_files)
    assert report["client_only_count"] == 2
    assert report["server_mods_kept_count"] == 8


# ---------------------------------------------------------------------------
# 2. DIE 14 GEFORDERTEN AUTOMATISIERTEN TESTSZENARIEN (Abschnitt 11)
# ---------------------------------------------------------------------------


def test_01_clear_client_only_mod(tmp_path: Path):
    """Szenario 1: Eindeutige Client-only-Mod (z.B. Sodium / Iris / EntityCulling)."""
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "sodium-fabric-0.6.0.jar",
        {
            "fabric.mod.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "sodium",
                    "version": "0.6.0",
                    "name": "Sodium",
                    "environment": "client",
                    "entrypoints": {"client": ["net.caffeinemc.mods.sodium.client.SodiumClientMod"]},
                }
            ),
            "net/caffeinemc/mods/sodium/client/SodiumClientMod.class": build_jvm_class_bytes(
                this_class_name="net/caffeinemc/mods/sodium/client/SodiumClientMod",
                interfaces=["net/fabricmc/api/ClientModInitializer"],
                utf8_constants=["com/mojang/blaze3d/systems/RenderSystem", "net/minecraft/client/Minecraft"],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.CLIENT_ONLY
    assert res.keep_on_server is False
    assert res.confidence >= 0.95


def test_02_clear_server_only_mod(tmp_path: Path):
    """Szenario 2: Eindeutige Server-only-Mod."""
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "dedicated-backup-server-1.0.0.jar",
        {
            "fabric.mod.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "dedicated_backup",
                    "version": "1.0.0",
                    "environment": "server",
                    "entrypoints": {"server": ["com.example.backup.ServerBackupMod"]},
                }
            ),
            "com/example/backup/ServerBackupMod.class": build_jvm_class_bytes(
                this_class_name="com/example/backup/ServerBackupMod",
                interfaces=["net/fabricmc/api/DedicatedServerModInitializer"],
                utf8_constants=["net/minecraft/server/dedicated/DedicatedServer"],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.SERVER_ONLY
    assert res.keep_on_server is True


def test_03_both_sides_required_mod_with_client_and_server_code(tmp_path: Path):
    """
    Szenario 3: Mod mit Client- und Server-Anteil in derselben JAR.
    Besitzt Client-Rendering-Klassen, aber auch Server-Registrierungen (DeferredRegister/Blocks).
    Darf NIEMALS als CLIENT_ONLY eingestuft werden.
    """
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "create-machinery-1.0.jar",
        {
            "META-INF/neoforge.mods.toml": NEOFORGE_MDK_COMMENT_TEMPLATE.format(
                mod_id="createmachinery", version="1.0.0", display_name="Create Machinery"
            ),
            "com/example/machinery/ClientRenderer.class": build_jvm_class_bytes(
                this_class_name="com/example/machinery/ClientRenderer",
                utf8_constants=[
                    "net/minecraft/client/renderer/blockentity/BlockEntityRenderer",
                    "com/mojang/blaze3d/vertex/PoseStack",
                ],
            ),
            "com/example/machinery/CommonSetup.class": build_jvm_class_bytes(
                this_class_name="com/example/machinery/CommonSetup",
                utf8_constants=[
                    "net/neoforged/neoforge/registries/DeferredRegister",
                    "net/minecraft/world/level/block/Block",
                    "net/minecraft/network/protocol/common/custom/CustomPacketPayload",
                ],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.BOTH_SIDES_REQUIRED
    assert res.keep_on_server is True


def test_04_shared_library_dependency_protection(tmp_path: Path):
    """
    Szenario 4: Gemeinsame Bibliothek.
    Selbst wenn Bibliothek B scheinbar Client-lastige Metadaten hätte, muss sie auf dem Server
    erhalten bleiben, sobald Server-Mod A sie als Abhängigkeit benötigt (Abschnitt 4D).
    """
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)

    # Mod A: Server-Mod, die `shared_ui_lib` benötigt
    create_mod_jar(
        mods_dir / "TechServerMod-1.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
[[mods]]
modId="techservermod"
version="1.0"
[[dependencies.techservermod]]
modId="shared_ui_lib"
type="required"
side="BOTH"
""",
            "com/tech/TechServerMod.class": build_jvm_class_bytes(
                this_class_name="com/tech/TechServerMod",
                utf8_constants=["net/neoforged/neoforge/registries/DeferredRegister"],
            ),
        },
    )

    # Bibliothek B: Würde isoliert als CLIENT_ONLY erscheinen, wird aber von TechServerMod benötigt
    create_mod_jar(
        mods_dir / "SharedUiLib-1.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
clientSideOnly=true
[[mods]]
modId="shared_ui_lib"
version="1.0"
""",
        },
    )

    pack_res = resolver.resolve_modpack(mods_dir)
    lib_result = next(r for r in pack_res["results"] if r["mod_id"] == "shared_ui_lib")
    assert lib_result["keep_on_server"] is True
    assert lib_result["side"] == ModSideCategory.BOTH_SIDES_REQUIRED.value
    assert "techservermod" in lib_result["required_by_server_mods"]


def test_05_conflicting_metadata_and_bytecode_resolves_to_unknown_kept(tmp_path: Path):
    """
    Szenario 5: Mod mit fehlerhaften/widersprüchlichen Metadaten (Abschnitt 5).
    Metadaten behaupten `clientSideOnly=true`, aber die JAR registriert im Bytecode Server-Blöcke
    und enthält Weltgenerierungsdaten. Konflikt muss erkannt, dokumentiert und als `UNKNOWN`
    eingestuft werden (bleibt auf dem Server!).
    """
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "ConflictingMod-1.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
clientSideOnly=true
[[mods]]
modId="conflictingmod"
version="1.0"
""",
            "data/conflictingmod/worldgen/biome/custom_forest.json": "{}",
            "com/conflict/MainMod.class": build_jvm_class_bytes(
                this_class_name="com/conflict/MainMod",
                utf8_constants=["net/neoforged/neoforge/registries/DeferredRegister"],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.UNKNOWN
    assert res.confidence_level == ConfidenceLevel.CONFLICTING
    assert res.keep_on_server is True
    assert len(res.conflicts) >= 1


def test_06_embedded_jar_in_jar_dependencies(tmp_path: Path):
    """
    Szenario 6: Mod mit eingebetteten Abhängigkeiten (Jar-in-Jar `META-INF/jarjar/metadata.json`).
    Erkennt eingebettete Bibliotheken als `provided_mods`, sodass keine Fehlwarnung über
    angeblich fehlende Abhängigkeiten entsteht.
    """
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)

    nested_jar_bytes = b"PK\x05\x06" + b"\x00" * 18  # Leeres valides ZIP
    create_mod_jar(
        mods_dir / "CarrierMod-1.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
[[mods]]
modId="carriermod"
version="1.0"
[[dependencies.carriermod]]
modId="embedded_energy_api"
type="required"
""",
            "META-INF/jarjar/metadata.json": json.dumps(
                {
                    "jars": [
                        {
                            "identifier": {"group": "com.example", "artifact": "embedded_energy_api"},
                            "version": {"range": "[1.0,)", "artifactVersion": "1.0.0"},
                            "path": "META-INF/jarjar/embedded_energy_api-1.0.0.jar",
                        }
                    ]
                }
            ),
            "META-INF/jarjar/embedded_energy_api-1.0.0.jar": nested_jar_bytes,
            "com/carrier/CarrierMod.class": build_jvm_class_bytes(
                this_class_name="com/carrier/CarrierMod",
                utf8_constants=["net/neoforged/neoforge/registries/DeferredRegister"],
            ),
        },
    )

    validation = resolver.validate_server_pack(tmp_path, expected_modloader="neoforge")
    assert validation["valid"] is True
    assert validation["missing_dependencies"] == []


def test_07_fabric_mod_detection(tmp_path: Path):
    """Szenario 7: Fabric-Mod (Client-only vs. Universal)."""
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)

    client_jar = create_mod_jar(
        tmp_path / "iris-fabric-1.8.0.jar",
        {
            "fabric.mod.json": json.dumps(
                {"schemaVersion": 1, "id": "iris", "version": "1.8.0", "environment": "client"}
            )
        },
    )
    common_jar = create_mod_jar(
        tmp_path / "lithium-fabric-0.14.0.jar",
        {
            "fabric.mod.json": json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "lithium",
                    "version": "0.14.0",
                    "environment": "*",
                    "entrypoints": {"main": ["me.jellysquid.mods.lithium.common.LithiumMod"]},
                }
            )
        },
    )

    assert resolver.analyze_mod(client_jar).side == ModSideCategory.CLIENT_ONLY
    assert resolver.analyze_mod(common_jar).side == ModSideCategory.BOTH_SIDES_REQUIRED


def test_08_neoforge_mod_bytecode_annotation_dist_client(tmp_path: Path):
    """
    Szenario 8: NeoForge-Mod ohne `clientSideOnly=true` im TOML, aber mit `@Mod(dist = Dist.CLIENT)`
    und `@EventBusSubscriber(Dist.CLIENT)` im Bytecode.
    """
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "MouseTweaks-neoforge-1.21.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
displayTest="IGNORE_ALL_VERSION"
[[mods]]
modId="mousetweaks"
version="2.26"
""",
            "yalter/mousetweaks/MouseTweaks.class": build_jvm_class_bytes(
                this_class_name="yalter/mousetweaks/MouseTweaks",
                utf8_constants=[
                    "net/minecraft/client/Minecraft",
                    "net/minecraft/client/gui/screens/inventory/AbstractContainerScreen",
                    "net/neoforged/neoforge/client/event/ScreenEvent",
                ],
                class_annotations=[
                    ("Lnet/neoforged/fml/common/Mod;", [("dist", "Lnet/neoforged/api/distmarker/Dist;", "CLIENT")])
                ],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.CLIENT_ONLY
    assert res.keep_on_server is False


def test_09_forge_mod_with_dist_executor_is_kept(tmp_path: Path):
    """
    Szenario 9: Forge-Mod (`META-INF/mods.toml`), die `DistExecutor` nutzt, um Client-Code
    sicher abzukapseln, und gleichzeitig Server-Code enthält.
    """
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "Waystones-forge-1.20.1.jar",
        {
            "META-INF/mods.toml": """
modLoader="javafml"
loaderVersion="[47,)"
[[mods]]
modId="waystones"
version="14.1.0"
""",
            "net/blay09/mods/waystones/Waystones.class": build_jvm_class_bytes(
                this_class_name="net/blay09/mods/waystones/Waystones",
                utf8_constants=[
                    "net/minecraftforge/fml/DistExecutor",
                    "net/minecraftforge/registries/DeferredRegister",
                    "net/minecraft/client/gui/screens/Screen",
                ],
            ),
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.BOTH_SIDES_REQUIRED
    assert res.keep_on_server is True


def test_10_quilt_mod_detection(tmp_path: Path):
    """Szenario 10: Quilt-Mod (`quilt.mod.json` mit `minecraft.environment = "client"`)."""
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)
    jar = create_mod_jar(
        tmp_path / "justzoom-quilt-2.0.jar",
        {
            "quilt.mod.json": json.dumps(
                {
                    "schema_version": 1,
                    "quilt_loader": {"id": "justzoom", "version": "2.0.0"},
                    "minecraft": {"environment": "client"},
                }
            )
        },
    )
    res = resolver.analyze_mod(jar)
    assert res.side == ModSideCategory.CLIENT_ONLY
    assert res.keep_on_server is False


def test_11_official_server_pack_is_still_verified_and_filtered(tmp_path: Path):
    """
    Szenario 11: Modpack mit offiziellem Server-Pack (Abschnitt 7).
    Auch ein offizielles Serverpaket kann versehentlich noch eine Client-only-Mod (z.B. Oculus/Iris)
    enthalten und muss von `ModSideResolver` überprüft und bereinigt werden.
    """
    server_dir = tmp_path / "official_server_pack"
    mods_dir = server_dir / "mods"
    mods_dir.mkdir(parents=True)

    create_mod_jar(
        mods_dir / "oculus-mc1.20.1-1.7.0.jar",
        {
            "META-INF/mods.toml": """
modLoader="javafml"
loaderVersion="[47,)"
clientSideOnly=true
[[mods]]
modId="oculus"
version="1.7.0"
"""
        },
    )
    create_mod_jar(
        mods_dir / "mekanism-1.20.1-10.4.0.jar",
        {
            "META-INF/mods.toml": """
modLoader="javafml"
loaderVersion="[47,)"
[[mods]]
modId="mekanism"
version="10.4.0"
""",
            "mekanism/common/Mekanism.class": build_jvm_class_bytes(
                this_class_name="mekanism/common/Mekanism",
                utf8_constants=["net/minecraftforge/registries/DeferredRegister"],
            ),
        },
    )

    out = process_client_pack(server_dir)
    assert out["moved_count"] == 1
    assert not (mods_dir / "oculus-mc1.20.1-1.7.0.jar").exists()
    assert (server_dir / "mods-disabled-client" / "oculus-mc1.20.1-1.7.0.jar").exists()
    assert (mods_dir / "mekanism-1.20.1-10.4.0.jar").exists()


def test_12_client_pack_conversion_preserves_datapacks_and_configs(tmp_path: Path):
    """
    Szenario 12: Modpack ohne offizielles Server-Pack (Client-Modpack Konvertierung).
    Prüft, dass Client-only-Mods ausgeschlossen werden, während Server-Mods, Konfigurationen,
    Datapacks und Weltgenerierungsdateien vollständig erhalten bleiben (und `name 'log' is not defined`
    nicht mehr auftritt!).
    """
    from modpack_routes import _process_client_pack

    server_dir = tmp_path / "converted_pack"
    mods_dir = server_dir / "mods"
    config_dir = server_dir / "config"
    datapack_dir = server_dir / "datapacks" / "custom_dimensions" / "data" / "my_dim" / "dimension_type"
    mods_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    datapack_dir.mkdir(parents=True)

    (config_dir / "common.toml").write_text("enabled = true\n", encoding="utf-8")
    (datapack_dir / "void_world.json").write_text('{"ultrawarm": false}', encoding="utf-8")
    (server_dir / "server.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    create_mod_jar(
        mods_dir / "ImmediatelyFast-NeoForge-1.3.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
clientSideOnly=true
[[mods]]
modId="immediatelyfast"
version="1.3.0"
"""
        },
    )
    create_mod_jar(
        mods_dir / "AppliedEnergistics2-19.0.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
[[mods]]
modId="ae2"
version="19.0.0"
""",
            "appeng/core/AE2.class": build_jvm_class_bytes(
                this_class_name="appeng/core/AE2",
                utf8_constants=["net/neoforged/neoforge/registries/DeferredRegister"],
            ),
        },
    )

    events = []
    report = _process_client_pack(
        target_dir=server_dir,
        push_event=lambda ev: events.append(ev),
        mc_version="1.21.1",
        loader="neoforge",
        install_mode="server",
    )

    # Keine "Datapack scan failed: name 'log' is not defined" Meldung!
    assert not any("Datapack scan failed" in str(ev.get("message", "")) for ev in events)
    # Datapack & Weltgenerierung muss erhalten sein!
    assert (datapack_dir / "void_world.json").exists()
    assert (config_dir / "common.toml").exists()
    assert (mods_dir / "AppliedEnergistics2-19.0.0.jar").exists()
    assert not (mods_dir / "ImmediatelyFast-NeoForge-1.3.0.jar").exists()
    assert report["validation"]["valid"] is True


def test_13_unknown_mod_without_online_metadata_never_classified_as_client_only(tmp_path: Path):
    """
    Szenario 13: Unbekannte Mod ohne Online-Metadaten und selbst mit bloßen Client-Klassen-Imports.
    WICHTIG: UNKNOWN darf niemals automatisch als CLIENT_ONLY interpretiert werden (Abschnitt 3 & 5).
    """
    resolver = ModSideResolver(cache=ModSideCache(tmp_path / "cache.db"), enable_network=False)

    # 13a: Komplett unbekannte JAR ohne Deskriptor
    mystery_jar = create_mod_jar(
        tmp_path / "mystery-helper-client-1.0.jar",
        {
            "com/mystery/Util.class": build_jvm_class_bytes(
                this_class_name="com/mystery/Util",
                utf8_constants=["net/minecraft/client/Minecraft"],  # Bloßer Import ohne Client-Entrypoint!
            )
        },
    )
    res = resolver.analyze_mod(mystery_jar)
    assert res.side == ModSideCategory.UNKNOWN
    assert res.keep_on_server is True


def test_14_persistent_cache_reuse_and_version_invalidation(tmp_path: Path):
    """
    Szenario 14: Cache-Wiederverwendung und Versions-/Kontextwechsel (Abschnitt 8).
    - Identischer SHA256 + gleicher (Minecraft-Version, Modloader) -> aus Cache geladen (`from_cache=True`).
    - Neue Mod-Version (anderer SHA256) -> erzwingt neue Analyse (`from_cache=False`).
    - Andere Minecraft-Version oder anderer Modloader -> kein unkritischer Cache-Übertrag (`from_cache=False`).
    """
    cache = ModSideCache(tmp_path / "persistent_cache.sqlite3")
    resolver = ModSideResolver(cache=cache, enable_network=False, minecraft_version="1.21.1", modloader="neoforge")

    jar_v1 = create_mod_jar(
        tmp_path / "entityculling-1.7.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
clientSideOnly=true
[[mods]]
modId="entityculling"
version="1.7.0"
"""
        },
    )

    # Erste Analyse -> frisch berechnet
    res1 = resolver.analyze_mod(jar_v1, minecraft_version="1.21.1", modloader="neoforge")
    assert res1.from_cache is False
    assert res1.side == ModSideCategory.CLIENT_ONLY

    # Zweite Analyse derselben JAR im selben Kontext -> aus Cache!
    res2 = resolver.analyze_mod(jar_v1, minecraft_version="1.21.1", modloader="neoforge")
    assert res2.from_cache is True
    assert res2.sha256 == res1.sha256
    assert res2.side == ModSideCategory.CLIENT_ONLY

    # Andere Minecraft-Version -> darf Cache-Eintrag nicht ungeprüft übernehmen!
    res_diff_mc = resolver.analyze_mod(jar_v1, minecraft_version="1.20.1", modloader="neoforge")
    assert res_diff_mc.from_cache is False

    # Neue Mod-Version (geänderter Inhalt/Hash) -> erzwingt Neu-Analyse!
    jar_v2 = create_mod_jar(
        tmp_path / "entityculling-1.8.0.jar",
        {
            "META-INF/neoforge.mods.toml": """
modLoader="javafml"
loaderVersion="[4,)"
clientSideOnly=false
[[mods]]
modId="entityculling"
version="1.8.0"
"""
        },
    )
    res_v2 = resolver.analyze_mod(jar_v2, minecraft_version="1.21.1", modloader="neoforge")
    assert res_v2.from_cache is False
    assert res_v2.sha256 != res1.sha256
    assert res_v2.side == ModSideCategory.BOTH_SIDES_REQUIRED
