"""Bytecode analysis for client/server side detection.

Scans .class files inside JARs for:
- Imports from net.minecraft.client.* packages
- @OnlyIn(Dist.CLIENT) annotations
- References to client-only classes/methods

Returns a bytecode_side result with confidence.
"""

from __future__ import annotations

import logging
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Client-side package prefixes
CLIENT_PACKAGE_PREFIXES = (
    "net/minecraft/client/",
    "net/minecraft/client/",
    "com/mojang/blaze3d/",  # Rendering engine
    "org/lwjgl/",  # LWJGL - often client-only
)

# Client-only class name patterns
CLIENT_CLASS_PATTERNS = (
    "Client",
    "Gui",
    "Screen",
    "Renderer",
    "Render",
    "Shader",
    "Texture",
    "Model",
    "Font",
    "KeyBinding",
    "Mouse",
    "Input",
    "Hud",
    "Overlay",
    "Particle",
    "Sound",
    "Music",
    "Camera",
    "View",
    "Framebuffer",
    "VertexBuffer",
    "BufferBuilder",
    "Tesselator",
    "GlStateManager",
    "RenderSystem",
    "RenderLayer",
    "RenderType",
    "BlockEntityRenderer",
    "EntityRenderer",
    "ItemRenderer",
    "PlayerRenderer",
    "LivingRenderer",
)

# Annotation class names for @OnlyIn
ONLY_IN_ANNOTATIONS = (
    "OnlyIn",
    "Environment",
    "ClientOnly",
    "SideOnly",
)

# Dist enum values
DIST_CLIENT = "CLIENT"
DIST_DEDICATED_SERVER = "DEDICATED_SERVER"


@dataclass
class BytecodeSideResult:
    """Result of bytecode side analysis."""
    side: str  # "CLIENT" | "SERVER" | "BOTH" | "UNKNOWN"
    confidence: float  # 0.0..1.0
    client_refs: list[str]  # Found client references
    server_refs: list[str]  # Found server references
    only_in_client: bool  # Has @OnlyIn(Dist.CLIENT)
    only_in_server: bool  # Has @OnlyIn(Dist.DEDICATED_SERVER)
    classes_scanned: int


def _read_u2(data: bytes, offset: int) -> tuple[int, int]:
    """Read unsigned 16-bit integer."""
    return struct.unpack(">H", data[offset:offset+2])[0], offset + 2


def _read_u4(data: bytes, offset: int) -> tuple[int, int]:
    """Read unsigned 32-bit integer."""
    return struct.unpack(">I", data[offset:offset+4])[0], offset + 4


def _parse_constant_pool(data: bytes, offset: int, count: int) -> tuple[list, int]:
    """Parse constant pool entries."""
    pool = [None]  # 1-indexed
    i = 1
    while i < count:
        tag = data[offset]
        offset += 1
        if tag == 1:  # CONSTANT_Utf8
            length, offset = _read_u2(data, offset)
            value = data[offset:offset+length].decode("utf-8", "ignore")
            offset += length
            pool.append(("utf8", value))
        elif tag == 7:  # CONSTANT_Class
            name_index, offset = _read_u2(data, offset)
            pool.append(("class", name_index))
        elif tag == 8:  # CONSTANT_String
            string_index, offset = _read_u2(data, offset)
            pool.append(("string", string_index))
        elif tag == 9:  # CONSTANT_Fieldref
            class_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("fieldref", class_index, name_type_index))
        elif tag == 10:  # CONSTANT_Methodref
            class_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("methodref", class_index, name_type_index))
        elif tag == 11:  # CONSTANT_InterfaceMethodref
            class_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("interfacemethodref", class_index, name_type_index))
        elif tag == 12:  # CONSTANT_NameAndType
            name_index, offset = _read_u2(data, offset)
            descriptor_index, offset = _read_u2(data, offset)
            pool.append(("nameandtype", name_index, descriptor_index))
        elif tag == 15:  # CONSTANT_MethodHandle
            ref_kind = data[offset]
            offset += 1
            ref_index, offset = _read_u2(data, offset)
            pool.append(("methodhandle", ref_kind, ref_index))
        elif tag == 16:  # CONSTANT_MethodType
            descriptor_index, offset = _read_u2(data, offset)
            pool.append(("methodtype", descriptor_index))
        elif tag == 17:  # CONSTANT_Dynamic
            bootstrap_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("dynamic", bootstrap_index, name_type_index))
        elif tag == 18:  # CONSTANT_InvokeDynamic
            bootstrap_index, offset = _read_u2(data, offset)
            name_type_index, offset = _read_u2(data, offset)
            pool.append(("invokedynamic", bootstrap_index, name_type_index))
        elif tag in (3, 4):  # CONSTANT_Integer, CONSTANT_Float
            offset += 4
            pool.append((tag,))
        elif tag in (5, 6):  # CONSTANT_Long, CONSTANT_Double
            offset += 8
            pool.append((tag,))
            pool.append(None)  # Long/Double take two slots
            i += 1
        else:
            # Unknown tag, skip
            pool.append(("unknown", tag))
    return pool, offset


def _get_pool_string(pool: list, index: int) -> str:
    """Resolve constant pool index to string."""
    if index <= 0 or index >= len(pool):
        return ""
    entry = pool[index]
    if entry is None:
        return ""
    if entry[0] == "utf8":
        return entry[1]
    return ""


def _resolve_class_name(pool: list, class_index: int) -> str:
    """Resolve class reference to full name."""
    if class_index <= 0 or class_index >= len(pool):
        return ""
    entry = pool[class_index]
    if entry is None or entry[0] != "class":
        return ""
    name_index = entry[1]
    name = _get_pool_string(pool, name_index)
    return name.replace("/", ".")


def _scan_class_file(class_data: bytes) -> tuple[list[str], list[str], bool, bool]:
    """
    Scan a single .class file for client/server indicators.
    Returns: (client_refs, server_refs, only_in_client, only_in_server)
    """
    client_refs = []
    server_refs = []
    only_in_client = False
    only_in_server = False

    if len(class_data) < 8:
        return client_refs, server_refs, only_in_client, only_in_server

    # Check magic number
    magic = struct.unpack(">I", class_data[:4])[0]
    if magic != 0xCAFEBABE:
        return client_refs, server_refs, only_in_client, only_in_server

    offset = 4
    # minor_version, major_version
    offset += 4

    # Constant pool
    cp_count, offset = _read_u2(class_data, offset)
    pool, offset = _parse_constant_pool(class_data, offset, cp_count)

    # Access flags
    access_flags, offset = _read_u2(class_data, offset)

    # This class
    this_class, offset = _read_u2(class_data, offset)
    this_class_name = _resolve_class_name(pool, this_class)

    # Super class
    super_class, offset = _read_u2(class_data, offset)
    super_class_name = _resolve_class_name(pool, super_class)

    # Interfaces count
    interfaces_count, offset = _read_u2(class_data, offset)
    offset += interfaces_count * 2

    # Fields count
    fields_count, offset = _read_u2(class_data, offset)
    for _ in range(fields_count):
        # access_flags
        offset += 2
        # name_index
        offset += 2
        # descriptor_index
        offset += 2
        # attributes_count
        attrs_count, offset = _read_u2(class_data, offset)
        for _ in range(attrs_count):
            attr_name_index, offset = _read_u2(class_data, offset)
            attr_name = _get_pool_string(pool, attr_name_index)
            attr_length, offset = _read_u4(class_data, offset)
            if attr_name == "RuntimeVisibleAnnotations" or attr_name == "RuntimeInvisibleAnnotations":
                # Parse annotations
                num_annotations, offset = _read_u2(class_data, offset)
                for _ in range(num_annotations):
                    type_index, offset = _read_u2(class_data, offset)
                    type_name = _resolve_class_name(pool, type_index)
                    if any(ann in type_name for ann in ONLY_IN_ANNOTATIONS):
                        num_values, offset = _read_u2(class_data, offset)
                        for _ in range(num_values):
                            elem_name_index, offset = _read_u2(class_data, offset)
                            elem_name = _get_pool_string(pool, elem_name_index)
                            # Parse element value
                            tag = class_data[offset]
                            offset += 1
                            if tag == 115:  # 's' = string
                                const_index, offset = _read_u2(class_data, offset)
                                const_value = _get_pool_string(pool, const_index)
                                if const_value == DIST_CLIENT:
                                    only_in_client = True
                                elif const_value == DIST_DEDICATED_SERVER:
                                    only_in_server = True
                            else:
                                # Skip other value types
                                if tag in (66, 67, 68, 70, 73, 74, 83, 90):  # B,C,D,F,I,J,S,Z
                                    offset += 2
                                elif tag == 101:  # 'e' = enum
                                    type_idx, offset = _read_u2(class_data, offset)
                                    const_idx, offset = _read_u2(class_data, offset)
                                elif tag == 99:  # 'c' = class
                                    const_idx, offset = _read_u2(class_data, offset)
                                elif tag == 64:  # '@' = annotation
                                    # Recursive annotation - skip for now
                                    pass
                                elif tag == 91:  # '[' = array
                                    num_vals, offset = _read_u2(class_data, offset)
                                    offset += num_vals * 3  # rough skip
                                else:
                                    offset += 2  # default skip
            else:
                offset += attr_length

    # Methods count
    methods_count, offset = _read_u2(class_data, offset)
    for _ in range(methods_count):
        # access_flags
        offset += 2
        # name_index
        offset += 2
        # descriptor_index
        offset += 2
        # attributes_count
        attrs_count, offset = _read_u2(class_data, offset)
        for _ in range(attrs_count):
            attr_name_index, offset = _read_u2(class_data, offset)
            attr_name = _get_pool_string(pool, attr_name_index)
            attr_length, offset = _read_u4(class_data, offset)
            if attr_name == "Code":
                # Skip code attribute
                offset += attr_length
            elif attr_name == "RuntimeVisibleAnnotations" or attr_name == "RuntimeInvisibleAnnotations":
                num_annotations, offset = _read_u2(class_data, offset)
                for _ in range(num_annotations):
                    type_index, offset = _read_u2(class_data, offset)
                    type_name = _resolve_class_name(pool, type_index)
                    if any(ann in type_name for ann in ONLY_IN_ANNOTATIONS):
                        num_values, offset = _read_u2(class_data, offset)
                        for _ in range(num_values):
                            elem_name_index, offset = _read_u2(class_data, offset)
                            elem_name = _get_pool_string(pool, elem_name_index)
                            tag = class_data[offset]
                            offset += 1
                            if tag == 115:  # 's' = string
                                const_index, offset = _read_u2(class_data, offset)
                                const_value = _get_pool_string(pool, const_index)
                                if const_value == DIST_CLIENT:
                                    only_in_client = True
                                elif const_value == DIST_DEDICATED_SERVER:
                                    only_in_server = True
                            else:
                                if tag in (66, 67, 68, 70, 73, 74, 83, 90):
                                    offset += 2
                                elif tag == 101:
                                    type_idx, offset = _read_u2(class_data, offset)
                                    const_idx, offset = _read_u2(class_data, offset)
                                elif tag == 99:
                                    const_idx, offset = _read_u2(class_data, offset)
                                elif tag == 64:
                                    pass
                                elif tag == 91:
                                    num_vals, offset = _read_u2(class_data, offset)
                                    offset += num_vals * 3
                                else:
                                    offset += 2
            else:
                offset += attr_length

    # Check class name and super class for client patterns
    for pattern in CLIENT_CLASS_PATTERNS:
        if pattern.lower() in this_class_name.lower():
            client_refs.append(f"class:{this_class_name}")
            break
        if pattern.lower() in super_class_name.lower():
            client_refs.append(f"super:{super_class_name}")
            break

    # Check constant pool for client package references
    for entry in pool:
        if entry and entry[0] == "utf8":
            value = entry[1]
            for prefix in CLIENT_PACKAGE_PREFIXES:
                if value.startswith(prefix):
                    client_refs.append(f"constpool:{value}")
                    break

    return client_refs, server_refs, only_in_client, only_in_server


def scan_jar_for_bytecode_side(jar_path: Path, max_classes: int = 500) -> BytecodeSideResult:
    """
    Scan a JAR file for bytecode side indicators.
    
    Args:
        jar_path: Path to the JAR file
        max_classes: Maximum number of class files to scan (performance)
    
    Returns:
        BytecodeSideResult with side determination and confidence
    """
    client_refs = []
    server_refs = []
    only_in_client = False
    only_in_server = False
    classes_scanned = 0

    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            class_files = [n for n in zf.namelist() if n.endswith(".class")]
            
            for class_name in class_files[:max_classes]:
                try:
                    class_data = zf.read(class_name)
                    c_refs, s_refs, oic, ois = _scan_class_file(class_data)
                    client_refs.extend(c_refs)
                    server_refs.extend(s_refs)
                    only_in_client = only_in_client or oic
                    only_in_server = only_in_server or ois
                    classes_scanned += 1
                except Exception as e:
                    logger.debug(f"Failed to scan class {class_name}: {e}")
                    continue
    except Exception as e:
        logger.debug(f"Failed to open JAR {jar_path}: {e}")

    # Determine side based on findings
    if only_in_client:
        side = "CLIENT"
        confidence = 0.95
    elif only_in_server:
        side = "SERVER"
        confidence = 0.95
    elif client_refs and not server_refs:
        side = "CLIENT"
        confidence = min(0.7 + len(client_refs) * 0.05, 0.9)
    elif server_refs and not client_refs:
        side = "SERVER"
        confidence = min(0.7 + len(server_refs) * 0.05, 0.9)
    elif client_refs and server_refs:
        side = "BOTH"
        confidence = 0.6
    else:
        side = "UNKNOWN"
        confidence = 0.0

    # Deduplicate refs
    client_refs = list(dict.fromkeys(client_refs))[:20]
    server_refs = list(dict.fromkeys(server_refs))[:20]

    return BytecodeSideResult(
        side=side,
        confidence=confidence,
        client_refs=client_refs,
        server_refs=server_refs,
        only_in_client=only_in_client,
        only_in_server=only_in_server,
        classes_scanned=classes_scanned,
    )


def scan_bytes_for_bytecode_side(class_data: bytes, filename: str = "") -> BytecodeSideResult:
    """Scan raw class file bytes."""
    client_refs = []
    server_refs = []
    only_in_client = False
    only_in_server = False

    c_refs, s_refs, oic, ois = _scan_class_file(class_data)
    client_refs.extend(c_refs)
    server_refs.extend(s_refs)
    only_in_client = only_in_client or oic
    only_in_server = only_in_server or ois
    classes_scanned = 1

    if only_in_client:
        side = "CLIENT"
        confidence = 0.95
    elif only_in_server:
        side = "SERVER"
        confidence = 0.95
    elif client_refs and not server_refs:
        side = "CLIENT"
        confidence = min(0.7 + len(client_refs) * 0.05, 0.9)
    elif server_refs and not client_refs:
        side = "SERVER"
        confidence = min(0.7 + len(server_refs) * 0.05, 0.9)
    elif client_refs and server_refs:
        side = "BOTH"
        confidence = 0.6
    else:
        side = "UNKNOWN"
        confidence = 0.0

    return BytecodeSideResult(
        side=side,
        confidence=confidence,
        client_refs=client_refs,
        server_refs=server_refs,
        only_in_client=only_in_client,
        only_in_server=only_in_server,
        classes_scanned=classes_scanned,
    )


__all__ = [
    "BytecodeSideResult",
    "scan_jar_for_bytecode_side",
    "scan_bytes_for_bytecode_side",
]

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    if len(sys.argv) > 1:
        jar_path = Path(sys.argv[1])
        result = scan_jar_for_bytecode_side(jar_path)
        print(f"Side: {result.side}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Classes scanned: {result.classes_scanned}")
        print(f"Client refs: {result.client_refs[:5]}")
        print(f"Server refs: {result.server_refs[:5]}")
        print(f"@OnlyIn(CLIENT): {result.only_in_client}")
        print(f"@OnlyIn(SERVER): {result.only_in_server}")