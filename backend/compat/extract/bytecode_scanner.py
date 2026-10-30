"""Bytecode analysis for client/server side detection.

Performs technical inspection of Java .class files inside mod JARs:
- Constant pool analysis (package imports, class/method references)
- Class-level and member-level annotations (@OnlyIn, @Environment, @Mod, @EventBusSubscriber)
- Loader entrypoint interfaces (ModInitializer, ClientModInitializer, DedicatedServerModInitializer)
- Client-side rendering, HUD, GUI, keybinding, shader, and sound references
- Server/common-side registries, networking, commands, worldgen, and server lifecycle events
- DistExecutor / FMLEnvironment dist-guard detection

Crucial rule:
A mere import of a client class (or @OnlyIn(Dist.CLIENT) on helper methods) is NOT sufficient
proof of CLIENT_ONLY, because many mods bundle both client and server classes in one JAR.
"""

from __future__ import annotations

import io
import logging
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Client-side package prefixes
CLIENT_PACKAGE_PREFIXES = (
    "net/minecraft/client/",
    "com/mojang/blaze3d/",
    "org/lwjgl/opengl/",
    "org/lwjgl/glfw/",
    "org/lwjgl/openal/",
    "net/irisshaders/",
    "net/caffeinemc/mods/sodium/",
    "me/jellysquid/mods/sodium/",
)

# Client-only event & registration descriptors/names
CLIENT_EVENT_INDICATORS = (
    "RegisterKeyMappingsEvent",
    "RegisterGuiLayersEvent",
    "RenderGuiEvent",
    "RenderGuiLayerEvent",
    "RenderLevelStageEvent",
    "RenderHandEvent",
    "RenderLivingEvent",
    "RenderPlayerEvent",
    "RenderNameTagEvent",
    "RenderTooltipEvent",
    "RenderBlockScreenEffectEvent",
    "ViewportEvent",
    "ScreenEvent",
    "InputEvent",
    "MovementInputUpdateEvent",
    "ClientTickEvent",
    "ClientChatEvent",
    "ClientChatReceivedEvent",
    "ClientPlayerNetworkEvent",
    "EntityRenderersEvent",
    "RegisterParticleProvidersEvent",
    "RegisterShadersEvent",
    "RegisterColorHandlersEvent",
    "RegisterClientReloadListenersEvent",
    "RegisterClientTooltipComponentFactoriesEvent",
    "RegisterDimensionSpecialEffectsEvent",
    "ClientCommandRegistrationEvent",
    "WorldRenderEvents",
    "HudRenderCallback",
    "ClientTickEvents",
    "ClientLifecycleEvents",
    "ScreenEvents",
    "KeyBindingHelper",
)

# Server & common gameplay / registry / networking indicators
SERVER_AND_COMMON_INDICATORS = (
    # Registries & content
    "net/minecraft/core/Registry",
    "net/minecraft/core/registries/BuiltInRegistries",
    "net/neoforged/neoforge/registries/DeferredRegister",
    "net/minecraftforge/registries/DeferredRegister",
    "net/neoforged/neoforge/registries/NeoForgeRegistries",
    "net/minecraftforge/registries/ForgeRegistries",
    "net/neoforged/neoforge/registries/RegisterEvent",
    "net/minecraftforge/registries/RegisterEvent",
    "net/minecraft/world/level/block/Block",
    "net/minecraft/world/level/block/entity/BlockEntity",
    "net/minecraft/world/level/block/entity/BlockEntityType",
    "net/minecraft/world/item/Item",
    "net/minecraft/world/entity/EntityType",
    "net/minecraft/world/inventory/AbstractContainerMenu",
    "net/minecraft/world/inventory/MenuType",
    "net/minecraft/world/item/crafting/RecipeSerializer",
    "net/minecraft/world/item/crafting/RecipeType",
    "net/minecraft/world/level/levelgen/structure/Structure",
    "net/minecraft/world/level/levelgen/structure/StructureType",
    "net/minecraft/world/level/levelgen/feature/Feature",
    "net/minecraft/world/level/storage/loot/",
    "net/minecraft/world/effect/MobEffect",
    "net/neoforged/neoforge/attachment/AttachmentType",
    # Server classes & lifecycle events
    "net/minecraft/server/MinecraftServer",
    "net/minecraft/server/level/ServerLevel",
    "net/minecraft/server/level/ServerPlayer",
    "net/minecraft/commands/Commands",
    "net/minecraft/commands/CommandSourceStack",
    "com/mojang/brigadier/CommandDispatcher",
    "ServerStartingEvent",
    "ServerStartedEvent",
    "ServerStoppingEvent",
    "ServerStoppedEvent",
    "ServerTickEvent",
    "RegisterCommandsEvent",
    "ServerLifecycleEvents",
    "ServerTickEvents",
    "CommandRegistrationCallback",
    "ServerPlayConnectionEvents",
    "PlayerEvent$PlayerLoggedInEvent",
    "PlayerEvent$PlayerRespawnEvent",
    "LivingDropsEvent",
    "LivingHurtEvent",
    "LivingDamageEvent",
    "BlockEvent$BreakEvent",
    "BlockEvent$EntityPlaceEvent",
)

# Networking / packet registration indicators (require server & client sync)
NETWORK_INDICATORS = (
    "net/minecraft/network/protocol/common/custom/CustomPacketPayload",
    "net/neoforged/neoforge/network/registration/PayloadRegistrar",
    "net/neoforged/neoforge/network/event/RegisterPayloadHandlersEvent",
    "net/neoforged/neoforge/network/PacketDistributor",
    "net/minecraftforge/network/SimpleChannel",
    "net/minecraftforge/network/NetworkRegistry",
    "net/minecraftforge/network/ChannelBuilder",
    "net/minecraftforge/network/PacketDistributor",
    "net/fabricmc/fabric/api/networking/v1/ServerPlayNetworking",
    "net/fabricmc/fabric/api/networking/v1/PayloadTypeRegistry",
    "dev/architectury/networking/NetworkManager",
    " dev/architectury/networking/NetworkChannel",
)

# Dist-guarding utilities (used by multi-side mods to safely isolate client calls)
DIST_GUARD_INDICATORS = (
    "net/minecraftforge/fml/DistExecutor",
    "net/neoforged/fml/loading/FMLEnvironment",
    "net/minecraftforge/fml/loading/FMLEnvironment",
    "net/neoforged/fml/loading/FMLLoader",
    "net/minecraftforge/fml/loading/FMLLoader",
    "net/fabricmc/loader/api/FabricLoader",
    "dev/architectury/utils/EnvExecutor",
    "dev/architectury/platform/Platform",
)

# Annotation descriptors for side restriction
ONLY_IN_ANNOTATION_NAMES = (
    "OnlyIn",
    "Environment",
    "ClientOnly",
    "SideOnly",
)


@dataclass
class ClassScanSummary:
    """Detailed findings from scanning a single .class file."""
    class_name: str = ""
    super_name: str = ""
    interfaces: list[str] = field(default_factory=list)
    client_refs: list[str] = field(default_factory=list)
    server_refs: list[str] = field(default_factory=list)
    network_refs: list[str] = field(default_factory=list)
    client_events: list[str] = field(default_factory=list)
    server_events: list[str] = field(default_factory=list)
    dist_guards: list[str] = field(default_factory=list)
    class_only_in_client: bool = False
    class_only_in_server: bool = False
    member_only_in_client: bool = False
    member_only_in_server: bool = False
    is_mod_entrypoint: bool = False
    mod_entrypoint_dist: Optional[str] = None  # "CLIENT" | "DEDICATED_SERVER" | "BOTH"
    is_event_bus_subscriber: bool = False
    event_bus_subscriber_dist: Optional[str] = None  # "CLIENT" | "DEDICATED_SERVER" | "BOTH"


@dataclass
class BytecodeSideResult:
    """Result of bytecode side analysis."""
    side: str  # "CLIENT" | "SERVER" | "BOTH" | "UNKNOWN"
    confidence: float  # 0.0..1.0
    client_refs: list[str]
    server_refs: list[str]
    only_in_client: bool
    only_in_server: bool
    classes_scanned: int
    network_refs: list[str] = field(default_factory=list)
    client_events: list[str] = field(default_factory=list)
    server_events: list[str] = field(default_factory=list)
    dist_guards: list[str] = field(default_factory=list)
    client_entrypoints: list[str] = field(default_factory=list)
    common_entrypoints: list[str] = field(default_factory=list)
    server_entrypoints: list[str] = field(default_factory=list)
    class_level_client_only_count: int = 0
    member_level_client_only_count: int = 0
    has_only_client_classes_without_entrypoints: bool = False


def _read_u1(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 1 > len(data):
        raise ValueError("EOF")
    return data[offset], offset + 1


def _read_u2(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 2 > len(data):
        raise ValueError("EOF")
    return struct.unpack(">H", data[offset:offset + 2])[0], offset + 2


def _read_u4(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError("EOF")
    return struct.unpack(">I", data[offset:offset + 4])[0], offset + 4


def _parse_constant_pool(data: bytes, offset: int, count: int) -> tuple[list, int]:
    pool: list = [None]
    i = 1
    while i < count:
        tag, offset = _read_u1(data, offset)
        if tag == 1:  # CONSTANT_Utf8
            length, offset = _read_u2(data, offset)
            value = data[offset:offset + length].decode("utf-8", "ignore")
            offset += length
            pool.append(("utf8", value))
        elif tag == 7:  # CONSTANT_Class
            name_index, offset = _read_u2(data, offset)
            pool.append(("class", name_index))
        elif tag == 8:  # CONSTANT_String
            string_index, offset = _read_u2(data, offset)
            pool.append(("string", string_index))
        elif tag in (9, 10, 11):  # Fieldref, Methodref, InterfaceMethodref
            class_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("ref", class_index, name_type_index))
        elif tag == 12:  # CONSTANT_NameAndType
            name_index, offset = _read_u2(data, offset)
            descriptor_index, offset = _read_u2(data, offset)
            pool.append(("nameandtype", name_index, descriptor_index))
        elif tag == 15:  # CONSTANT_MethodHandle
            ref_kind, offset = _read_u1(data, offset)
            ref_index, offset = _read_u2(data, offset)
            pool.append(("methodhandle", ref_kind, ref_index))
        elif tag == 16:  # CONSTANT_MethodType
            descriptor_index, offset = _read_u2(data, offset)
            pool.append(("methodtype", descriptor_index))
        elif tag in (17, 18):  # CONSTANT_Dynamic, CONSTANT_InvokeDynamic
            bootstrap_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("dynamic", bootstrap_index, name_type_index))
        elif tag in (19, 20):  # CONSTANT_Module, CONSTANT_Package
            name_index, offset = _read_u2(data, offset)
            pool.append(("module_or_pkg", name_index))
        elif tag in (3, 4):  # CONSTANT_Integer, CONSTANT_Float
            offset += 4
            pool.append((tag,))
        elif tag in (5, 6):  # CONSTANT_Long, CONSTANT_Double
            offset += 8
            pool.append((tag,))
            pool.append(None)
            i += 1
        else:
            raise ValueError(f"Unknown constant pool tag {tag}")
        i += 1
    return pool, offset


def _get_pool_string(pool: list, index: int) -> str:
    if index <= 0 or index >= len(pool):
        return ""
    entry = pool[index]
    if entry is None:
        return ""
    if entry[0] == "utf8":
        return entry[1]
    if entry[0] == "class":
        return _get_pool_string(pool, entry[1])
    return ""


def _resolve_class_name(pool: list, class_index: int) -> str:
    if class_index <= 0 or class_index >= len(pool):
        return ""
    entry = pool[class_index]
    if entry is None:
        return ""
    if entry[0] == "class":
        return _get_pool_string(pool, entry[1]).replace("/", ".")
    if entry[0] == "utf8":
        raw = entry[1]
        if raw.startswith("L") and raw.endswith(";"):
            raw = raw[1:-1]
        return raw.replace("/", ".")
    return ""


def _parse_element_value(data: bytes, offset: int, pool: list) -> tuple[object, int]:
    """Parse an annotation element_value structure per JVM spec §4.7.16.1."""
    tag, offset = _read_u1(data, offset)
    ch = chr(tag)
    if ch in ("B", "C", "D", "F", "I", "J", "S", "Z", "s"):
        const_idx, offset = _read_u2(data, offset)
        return _get_pool_string(pool, const_idx), offset
    if ch == "e":  # enum_const_value
        type_idx, offset = _read_u2(data, offset)
        const_idx, offset = _read_u2(data, offset)
        return ("enum", _get_pool_string(pool, type_idx), _get_pool_string(pool, const_idx)), offset
    if ch == "c":  # class_info_index
        class_idx, offset = _read_u2(data, offset)
        return ("class", _get_pool_string(pool, class_idx)), offset
    if ch == "@":  # nested annotation
        ann, offset = _parse_annotation(data, offset, pool)
        return ("annotation", ann), offset
    if ch == "[":  # array_value
        num_vals, offset = _read_u2(data, offset)
        items = []
        for _ in range(num_vals):
            val, offset = _parse_element_value(data, offset, pool)
            items.append(val)
        return items, offset
    raise ValueError(f"Unknown annotation element_value tag: {tag}")


def _parse_annotation(data: bytes, offset: int, pool: list) -> tuple[tuple[str, dict[str, object]], int]:
    """Parse a single annotation structure per JVM spec §4.7.16."""
    type_index, offset = _read_u2(data, offset)
    type_name = _resolve_class_name(pool, type_index)
    num_pairs, offset = _read_u2(data, offset)
    pairs: dict[str, object] = {}
    for _ in range(num_pairs):
        elem_name_idx, offset = _read_u2(data, offset)
        elem_name = _get_pool_string(pool, elem_name_idx)
        val, offset = _parse_element_value(data, offset, pool)
        pairs[elem_name] = val
    return (type_name, pairs), offset


def _extract_dist_from_value(val: object) -> Optional[str]:
    """Extract 'CLIENT' or 'DEDICATED_SERVER' from an annotation value (enum, string, or array)."""
    if isinstance(val, str):
        u = val.upper()
        if u == "CLIENT":
            return "CLIENT"
        if u in ("DEDICATED_SERVER", "SERVER"):
            return "DEDICATED_SERVER"
    elif isinstance(val, tuple) and len(val) == 3 and val[0] == "enum":
        const_name = str(val[2]).upper()
        if const_name == "CLIENT":
            return "CLIENT"
        if const_name in ("DEDICATED_SERVER", "SERVER"):
            return "DEDICATED_SERVER"
    elif isinstance(val, list):
        dists = [_extract_dist_from_value(item) for item in val]
        dists = [d for d in dists if d]
        if dists:
            if "CLIENT" in dists and "DEDICATED_SERVER" not in dists:
                return "CLIENT"
            if "DEDICATED_SERVER" in dists and "CLIENT" not in dists:
                return "DEDICATED_SERVER"
            return "BOTH"
    return None


def _parse_annotations_attribute(
    data: bytes, offset: int, attr_length: int, pool: list
) -> list[tuple[str, dict[str, object]]]:
    end = offset + attr_length
    out: list[tuple[str, dict[str, object]]] = []
    try:
        num_annotations, offset = _read_u2(data, offset)
        for _ in range(num_annotations):
            ann, offset = _parse_annotation(data, offset, pool)
            out.append(ann)
    except Exception:
        pass
    return out


def _inspect_annotations(
    annotations: list[tuple[str, dict[str, object]]],
    *,
    is_class_level: bool,
    summary: ClassScanSummary,
) -> None:
    for type_name, pairs in annotations:
        short_name = type_name.rsplit(".", 1)[-1].rsplit("$", 1)[-1]

        # 1. @OnlyIn / @Environment / @SideOnly / @ClientOnly
        if any(ann in short_name for ann in ONLY_IN_ANNOTATION_NAMES):
            dist = None
            if "ClientOnly" in short_name:
                dist = "CLIENT"
            else:
                for v in pairs.values():
                    dist = _extract_dist_from_value(v)
                    if dist:
                        break
            if dist == "CLIENT":
                if is_class_level:
                    summary.class_only_in_client = True
                else:
                    summary.member_only_in_client = True
            elif dist == "DEDICATED_SERVER":
                if is_class_level:
                    summary.class_only_in_server = True
                else:
                    summary.member_only_in_server = True

        # 2. @Mod (Forge / NeoForge entrypoint)
        if is_class_level and (
            type_name in (
                "net.minecraftforge.fml.common.Mod",
                "net.neoforged.fml.common.Mod",
                "cpw.mods.fml.common.Mod",
            )
            or short_name == "Mod"
        ):
            summary.is_mod_entrypoint = True
            dist = _extract_dist_from_value(pairs.get("dist"))
            if not dist and "clientSideOnly" in pairs and str(pairs.get("clientSideOnly")).lower() == "true":
                dist = "CLIENT"
            summary.mod_entrypoint_dist = dist or "BOTH"

        # 3. @EventBusSubscriber
        if is_class_level and "EventBusSubscriber" in short_name:
            summary.is_event_bus_subscriber = True
            dist = _extract_dist_from_value(pairs.get("value") or pairs.get("dist"))
            summary.event_bus_subscriber_dist = dist or "BOTH"


def scan_class_bytes(class_data: bytes) -> ClassScanSummary:
    """Scan a single .class file and return a structured ClassScanSummary."""
    summary = ClassScanSummary()
    if len(class_data) < 10:
        return summary

    try:
        magic, _ = _read_u4(class_data, 0)
        if magic != 0xCAFEBABE:
            return summary

        offset = 8  # skip magic (4) + minor/major (4)
        cp_count, offset = _read_u2(class_data, offset)
        pool, offset = _parse_constant_pool(class_data, offset, cp_count)

        _access_flags, offset = _read_u2(class_data, offset)
        this_class, offset = _read_u2(class_data, offset)
        summary.class_name = _resolve_class_name(pool, this_class)

        super_class, offset = _read_u2(class_data, offset)
        summary.super_name = _resolve_class_name(pool, super_class)

        interfaces_count, offset = _read_u2(class_data, offset)
        for _ in range(interfaces_count):
            iface_idx, offset = _read_u2(class_data, offset)
            iface_name = _resolve_class_name(pool, iface_idx)
            if iface_name:
                summary.interfaces.append(iface_name)

        # Fields
        fields_count, offset = _read_u2(class_data, offset)
        for _ in range(fields_count):
            offset += 6  # access_flags, name_index, descriptor_index
            attrs_count, offset = _read_u2(class_data, offset)
            for _ in range(attrs_count):
                attr_name_idx, offset = _read_u2(class_data, offset)
                attr_name = _get_pool_string(pool, attr_name_idx)
                attr_len, offset = _read_u4(class_data, offset)
                if attr_name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                    anns = _parse_annotations_attribute(class_data, offset, attr_len, pool)
                    _inspect_annotations(anns, is_class_level=False, summary=summary)
                offset += attr_len

        # Methods
        methods_count, offset = _read_u2(class_data, offset)
        for _ in range(methods_count):
            offset += 6  # access_flags, name_index, descriptor_index
            attrs_count, offset = _read_u2(class_data, offset)
            for _ in range(attrs_count):
                attr_name_idx, offset = _read_u2(class_data, offset)
                attr_name = _get_pool_string(pool, attr_name_idx)
                attr_len, offset = _read_u4(class_data, offset)
                if attr_name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                    anns = _parse_annotations_attribute(class_data, offset, attr_len, pool)
                    _inspect_annotations(anns, is_class_level=False, summary=summary)
                offset += attr_len

        # Class-level attributes
        if offset + 2 <= len(class_data):
            class_attrs_count, offset = _read_u2(class_data, offset)
            for _ in range(class_attrs_count):
                if offset + 6 > len(class_data):
                    break
                attr_name_idx, offset = _read_u2(class_data, offset)
                attr_name = _get_pool_string(pool, attr_name_idx)
                attr_len, offset = _read_u4(class_data, offset)
                if attr_name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                    anns = _parse_annotations_attribute(class_data, offset, attr_len, pool)
                    _inspect_annotations(anns, is_class_level=True, summary=summary)
                offset += attr_len

        # Fabric / Quilt entrypoint interfaces
        for iface in summary.interfaces:
            if iface in ("net.fabricmc.api.ClientModInitializer", "org.quiltmc.qsl.base.api.entrypoint.client.ClientModInitializer"):
                summary.is_mod_entrypoint = True
                summary.mod_entrypoint_dist = "CLIENT"
            elif iface in ("net.fabricmc.api.DedicatedServerModInitializer", "org.quiltmc.qsl.base.api.entrypoint.server.DedicatedServerModInitializer"):
                summary.is_mod_entrypoint = True
                summary.mod_entrypoint_dist = "DEDICATED_SERVER"
            elif iface in ("net.fabricmc.api.ModInitializer", "org.quiltmc.qsl.base.api.entrypoint.ModInitializer"):
                summary.is_mod_entrypoint = True
                if summary.mod_entrypoint_dist != "DEDICATED_SERVER":
                    summary.mod_entrypoint_dist = "BOTH"

        # Scan constant pool UTF8 strings for technical references
        for entry in pool:
            if not entry or entry[0] != "utf8":
                continue
            val: str = entry[1]
            if not val or len(val) < 4:
                continue

            # Check Dist guards
            for dg in DIST_GUARD_INDICATORS:
                if dg in val:
                    summary.dist_guards.append(dg)
                    break

            # Check Networking
            for net_ind in NETWORK_INDICATORS:
                if net_ind in val:
                    summary.network_refs.append(net_ind)
                    break

            # Check Client packages
            for c_pref in CLIENT_PACKAGE_PREFIXES:
                if c_pref in val:
                    summary.client_refs.append(val[:80])
                    break

            # Check Client events
            for c_ev in CLIENT_EVENT_INDICATORS:
                if c_ev in val:
                    summary.client_events.append(c_ev)
                    break

            # Check Server & Common registries / events
            for s_ind in SERVER_AND_COMMON_INDICATORS:
                if s_ind in val:
                    if "Event" in s_ind or "Callback" in s_ind or "Server" in s_ind or "Command" in s_ind:
                        summary.server_events.append(s_ind)
                    else:
                        summary.server_refs.append(s_ind)
                    break

    except Exception as e:
        logger.debug("Bytecode parse error in class %s: %s", summary.class_name, e)

    return summary


def _scan_class_file(class_data: bytes) -> tuple[list[str], list[str], bool, bool]:
    """Legacy helper signature for backward compatibility."""
    s = scan_class_bytes(class_data)
    return (
        s.client_refs + s.client_events,
        s.server_refs + s.server_events + s.network_refs,
        s.class_only_in_client,
        s.class_only_in_server,
    )


def scan_jar_for_bytecode_side(jar_path: Path, max_classes: int = 500) -> BytecodeSideResult:
    """
    Scan a JAR file for bytecode side indicators.

    Crucial distinction:
    - A mod that has BOTH client classes (or @OnlyIn(Dist.CLIENT) methods/classes) AND
      server/common registries, networking, commands, or common @Mod entrypoints is
      classified as BOTH (never CLIENT).
    - A mod that ONLY has client class references without client-only entrypoints/events
      is treated with caution (low confidence / UNKNOWN) because mere client class imports
      are not sufficient proof of CLIENT_ONLY.
    """
    client_refs: list[str] = []
    server_refs: list[str] = []
    network_refs: list[str] = []
    client_events: list[str] = []
    server_events: list[str] = []
    dist_guards: list[str] = []
    client_entrypoints: list[str] = []
    common_entrypoints: list[str] = []
    server_entrypoints: list[str] = []
    class_level_client_only = 0
    class_level_server_only = 0
    member_level_client_only = 0
    non_client_annotated_classes = 0
    classes_scanned = 0

    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            all_names = zf.namelist()
            class_files = [
                n for n in all_names
                if n.endswith(".class") and not n.startswith("META-INF/versions/")
                and "module-info" not in n and "package-info" not in n
            ]

            for class_name in class_files[:max_classes]:
                try:
                    class_data = zf.read(class_name)
                    s = scan_class_bytes(class_data)
                    classes_scanned += 1

                    # If this specific class is annotated @OnlyIn(Dist.CLIENT) or
                    # @EventBusSubscriber(Dist.CLIENT), its internal client_refs are
                    # isolated to the client dist!
                    is_isolated_client_class = (
                        s.class_only_in_client
                        or s.mod_entrypoint_dist == "CLIENT"
                        or s.event_bus_subscriber_dist == "CLIENT"
                    )

                    if s.class_only_in_client:
                        class_level_client_only += 1
                    else:
                        non_client_annotated_classes += 1

                    if s.class_only_in_server:
                        class_level_server_only += 1
                    if s.member_only_in_client:
                        member_level_client_only += 1

                    if s.is_mod_entrypoint:
                        if s.mod_entrypoint_dist == "CLIENT":
                            client_entrypoints.append(s.class_name)
                        elif s.mod_entrypoint_dist == "DEDICATED_SERVER":
                            server_entrypoints.append(s.class_name)
                        else:
                            common_entrypoints.append(s.class_name)
                            # If the common @Mod entrypoint itself has zero server/network refs
                            # and only registers client events / client classes without dist guards,
                            # we still inspect what the JAR actually does.

                    client_refs.extend(s.client_refs)
                    client_events.extend(s.client_events)
                    dist_guards.extend(s.dist_guards)

                    if not is_isolated_client_class:
                        server_refs.extend(s.server_refs)
                        server_events.extend(s.server_events)
                        network_refs.extend(s.network_refs)
                    else:
                        # Even in a client class, network payload references mean the mod uses networking
                        network_refs.extend(s.network_refs)

                except Exception as e:
                    logger.debug("Failed to scan class %s in %s: %s", class_name, jar_path.name, e)
                    continue
    except Exception as e:
        logger.debug("Failed to open JAR %s: %s", jar_path, e)

    # Deduplicate lists
    client_refs = list(dict.fromkeys(client_refs))[:30]
    server_refs = list(dict.fromkeys(server_refs))[:30]
    network_refs = list(dict.fromkeys(network_refs))[:20]
    client_events = list(dict.fromkeys(client_events))[:20]
    server_events = list(dict.fromkeys(server_events))[:20]
    dist_guards = list(dict.fromkeys(dist_guards))[:10]

    has_server_activity = bool(server_refs or server_events or network_refs or server_entrypoints)
    has_client_activity = bool(client_refs or client_events or client_entrypoints or class_level_client_only > 0)
    all_classes_client_annotated = (classes_scanned > 0 and class_level_client_only == classes_scanned)
    has_only_client_entrypoints = bool(client_entrypoints and not common_entrypoints and not server_entrypoints)
    has_only_client_classes_without_entrypoints = False

    if has_server_activity and has_client_activity:
        # Mod has both server/common registrations/networking/events and client classes
        side = "BOTH"
        confidence = 0.85
    elif has_server_activity and not has_client_activity:
        if server_entrypoints and not common_entrypoints and class_level_server_only > 0:
            side = "SERVER"
            confidence = 0.90
        else:
            side = "BOTH"
            confidence = 0.80
    elif has_client_activity and not has_server_activity:
        # Only client references found, zero server/common registrations or networking
        if all_classes_client_annotated or has_only_client_entrypoints:
            # Explicit client-only entrypoints (@Mod(dist=Dist.CLIENT) / ClientModInitializer)
            # or every class in the JAR is @OnlyIn(Dist.CLIENT)
            side = "CLIENT"
            confidence = 0.92 if (all_classes_client_annotated or (has_only_client_entrypoints and client_events)) else 0.88
        elif client_events and not common_entrypoints:
            # Registers only client events (keybinds, HUD, screen, render) and no common entrypoint
            side = "CLIENT"
            confidence = 0.85
        elif client_events and common_entrypoints and not dist_guards:
            # Has a @Mod class that only registers client events/renderers and zero server/common registries
            side = "CLIENT"
            confidence = 0.80
        else:
            # Mere client class references without client-only entrypoints or client-only event registrations:
            # Per specification: "Ein bloßer Import einer Client-Klasse ist kein ausreichender Beweis für CLIENT_ONLY"
            side = "UNKNOWN"
            confidence = 0.35
            has_only_client_classes_without_entrypoints = True
    else:
        side = "UNKNOWN"
        confidence = 0.0

    return BytecodeSideResult(
        side=side,
        confidence=confidence,
        client_refs=client_refs,
        server_refs=server_refs,
        only_in_client=all_classes_client_annotated or has_only_client_entrypoints,
        only_in_server=(classes_scanned > 0 and class_level_server_only == classes_scanned),
        classes_scanned=classes_scanned,
        network_refs=network_refs,
        client_events=client_events,
        server_events=server_events,
        dist_guards=dist_guards,
        client_entrypoints=client_entrypoints,
        common_entrypoints=common_entrypoints,
        server_entrypoints=server_entrypoints,
        class_level_client_only_count=class_level_client_only,
        member_level_client_only_count=member_level_client_only,
        has_only_client_classes_without_entrypoints=has_only_client_classes_without_entrypoints,
    )


def scan_bytes_for_bytecode_side(class_data: bytes, filename: str = "") -> BytecodeSideResult:
    """Scan raw class file bytes."""
    s = scan_class_bytes(class_data)
    has_server = bool(s.server_refs or s.server_events or s.network_refs or s.class_only_in_server or s.mod_entrypoint_dist == "DEDICATED_SERVER")
    has_client = bool(s.client_refs or s.client_events or s.class_only_in_client or s.mod_entrypoint_dist == "CLIENT")

    if s.class_only_in_client or s.mod_entrypoint_dist == "CLIENT":
        side = "CLIENT"
        confidence = 0.95
    elif s.class_only_in_server or s.mod_entrypoint_dist == "DEDICATED_SERVER":
        side = "SERVER"
        confidence = 0.95
    elif has_server and has_client:
        side = "BOTH"
        confidence = 0.80
    elif has_server:
        side = "SERVER" if s.class_only_in_server else "BOTH"
        confidence = 0.80
    elif has_client and s.client_events:
        side = "CLIENT"
        confidence = 0.80
    elif has_client:
        side = "UNKNOWN"
        confidence = 0.35
    else:
        side = "UNKNOWN"
        confidence = 0.0

    return BytecodeSideResult(
        side=side,
        confidence=confidence,
        client_refs=s.client_refs,
        server_refs=s.server_refs,
        only_in_client=s.class_only_in_client or s.mod_entrypoint_dist == "CLIENT",
        only_in_server=s.class_only_in_server or s.mod_entrypoint_dist == "DEDICATED_SERVER",
        classes_scanned=1,
        network_refs=s.network_refs,
        client_events=s.client_events,
        server_events=s.server_events,
        dist_guards=s.dist_guards,
    )


__all__ = [
    "ClassScanSummary",
    "BytecodeSideResult",
    "scan_class_bytes",
    "scan_jar_for_bytecode_side",
    "scan_bytes_for_bytecode_side",
]
