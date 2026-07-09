"""Structural extraction of mod metadata from JAR files.

Unlike the previous line-based scanners, this module:

* parses ``fabric.mod.json`` / ``quilt.mod.json`` as JSON and ``mods.toml`` as
  TOML;
* handles multi-mod jars (multiple ``[[mods]]`` blocks / provides);
* recurses into **jar-in-jar** bundles (``META-INF/jarjar/*.jar`` for
  Forge/NeoForge, nested ``jars`` for Fabric) so embedded libraries are counted
  as *provided*, not *missing*;
* collects mixin config targets and access-transformer entries for later
  conflict detection;
* detects the loader structurally (a NeoForge mod that ships ``mods.toml`` is no
  longer mislabeled as Forge).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path

from ..models import CanonicalMod, Dependency, EdgeType, Loader, Side
from ..versioning import parse_range, parse_version
from .toml_parser import parse_mods_toml

logger = logging.getLogger(__name__)

_CORE_IDS = {"minecraft", "forge", "neoforge", "fabric", "fabricloader",
             "fabric-loader", "quilt_loader", "quiltloader", "java", "mcp"}


# ═══════════════════════════════════════════════════════════════ public API
def extract_jar(path: Path, *, compute_hash: bool = True,
                max_depth: int = 2) -> CanonicalMod:
    """Extract a :class:`CanonicalMod` from a JAR file on disk."""
    path = Path(path)
    sha512 = ""
    size = 0
    try:
        size = path.stat().st_size
        if compute_hash:
            sha512 = _hash_file(path)
    except OSError:
        pass

    try:
        with zipfile.ZipFile(path, "r") as zf:
            mod = _extract_from_zip(zf, path.name, size, sha512, depth=0,
                                    max_depth=max_depth)
    except (zipfile.BadZipFile, OSError) as e:
        logger.debug("Cannot read JAR %s: %s", path.name, e)
        mod = CanonicalMod(
            canonical_id=_fallback_id(path.name),
            name=path.stem,
            filename=path.name,
            sha512=sha512,
            file_size=size,
        )
    mod.path = str(path)
    return mod


def extract_bytes(data: bytes, filename: str, *, max_depth: int = 2,
                  depth: int = 0) -> CanonicalMod | None:
    """Extract from raw JAR bytes (used for nested jar-in-jar)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            sha512 = hashlib.sha512(data).hexdigest()
            return _extract_from_zip(zf, filename, len(data), sha512,
                                     depth=depth, max_depth=max_depth)
    except (zipfile.BadZipFile, OSError):
        return None


# ═══════════════════════════════════════════════════════════════ internals
def _extract_from_zip(zf: zipfile.ZipFile, filename: str, size: int,
                      sha512: str, *, depth: int, max_depth: int) -> CanonicalMod:
    names = set(zf.namelist())

    mod_ids: set[str] = set()
    provides: set[str] = set()
    loaders: set[Loader] = set()
    deps: list[Dependency] = []
    mc_ranges: list = []
    name = ""
    version_raw = ""
    side = Side.UNKNOWN

    # ── Fabric ──
    if "fabric.mod.json" in names:
        f = _parse_fabric(_read_json(zf, "fabric.mod.json"))
        _merge(mod_ids, provides, loaders, deps, mc_ranges, f)
        name = name or f["name"]
        version_raw = version_raw or f["version"]
        if f["side"] != Side.UNKNOWN:
            side = f["side"]

    # ── Quilt ──
    if "quilt.mod.json" in names:
        q = _parse_quilt(_read_json(zf, "quilt.mod.json"))
        _merge(mod_ids, provides, loaders, deps, mc_ranges, q)
        name = name or q["name"]
        version_raw = version_raw or q["version"]
        if side == Side.UNKNOWN and q["side"] != Side.UNKNOWN:
            side = q["side"]

    # ── Forge / NeoForge ──
    for toml_name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
        if toml_name in names:
            t = _parse_forge(zf.read(toml_name).decode("utf-8", "ignore"), toml_name)
            _merge(mod_ids, provides, loaders, deps, mc_ranges, t)
            name = name or t["name"]
            version_raw = version_raw or t["version"]
            if side == Side.UNKNOWN and t["side"] != Side.UNKNOWN:
                side = t["side"]
            break  # one toml wins (neoforge preferred)

    # ── Resource / data pack with no loader metadata ──
    if not loaders and "pack.mcmeta" in names:
        has_classes = any(n.endswith(".class") for n in names)
        if not has_classes:
            # A jar that is only assets/data. Resource packs are client-side.
            has_assets = any(n.startswith("assets/") for n in names)
            has_data = any(n.startswith("data/") for n in names)
            if has_assets and not has_data:
                side = Side.CLIENT
            elif has_data and not has_assets:
                side = Side.SERVER

    # ── Mixins & access transformers (for conflict detection) ──
    mixin_targets = _collect_mixin_targets(zf, names)
    ats = _collect_access_transformers(zf, names)

    # ── Jar-in-Jar recursion ──
    embedded: list[CanonicalMod] = []
    if depth < max_depth:
        embedded = _extract_embedded(zf, names, depth=depth, max_depth=max_depth)
        for e in embedded:
            provides.update(e.mod_ids)
            provides.update(e.provides)

    primary = _primary_id(mod_ids, filename)
    return CanonicalMod(
        canonical_id=primary,
        name=name or Path(filename).stem,
        filename=filename,
        sha512=sha512,
        version=parse_version(version_raw),
        version_raw=version_raw,
        loaders=frozenset(loaders),
        mc_ranges=tuple(mc_ranges),
        declared_side=side,
        mod_ids=frozenset(mod_ids),
        dependencies=deps,
        provides=frozenset(provides),
        embedded=tuple(embedded),
        mixin_targets=frozenset(mixin_targets),
        access_transformers=frozenset(ats),
        file_size=size,
    )


# ---------------------------------------------------------------- loaders
def _parse_fabric(data: dict) -> dict:
    ids = set()
    provides = set()
    deps: list[Dependency] = []
    mc_ranges: list = []
    loaders = {Loader.FABRIC}

    mid = str(data.get("id") or "").strip().lower()
    if mid:
        ids.add(mid)
    for p in _as_list(data.get("provides")):
        provides.add(str(p).lower())

    env = str(data.get("environment", "*")).strip().lower()
    side = {"client": Side.CLIENT, "server": Side.SERVER,
            "*": Side.BOTH, "": Side.BOTH, "both": Side.BOTH}.get(env, Side.UNKNOWN)

    for kind, edge in (("depends", EdgeType.REQUIRES),
                       ("recommends", EdgeType.SUGGESTS),
                       ("suggests", EdgeType.SUGGESTS),
                       ("breaks", EdgeType.INCOMPATIBLE),
                       ("conflicts", EdgeType.INCOMPATIBLE)):
        block = data.get(kind) or {}
        if isinstance(block, dict):
            for dep_id, rng in block.items():
                _add_dep(deps, mc_ranges, dep_id, rng, edge, source="jar")
        elif isinstance(block, list):
            for item in block:
                if isinstance(item, str):
                    _add_dep(deps, mc_ranges, item, "*", edge, source="jar")
                elif isinstance(item, dict):
                    _add_dep(deps, mc_ranges, item.get("id"), item.get("version", "*"),
                             edge, source="jar")

    return {"ids": ids, "provides": provides, "loaders": loaders, "deps": deps,
            "mc_ranges": mc_ranges, "name": data.get("name") or mid,
            "version": str(data.get("version") or ""), "side": side}


def _parse_quilt(data: dict) -> dict:
    ids = set()
    provides = set()
    deps: list[Dependency] = []
    mc_ranges: list = []
    loaders = {Loader.QUILT, Loader.FABRIC}  # quilt runs fabric mods

    ql = data.get("quilt_loader", {}) if isinstance(data, dict) else {}
    mid = str(ql.get("id") or "").strip().lower()
    if mid:
        ids.add(mid)
    for p in _as_list(ql.get("provides")):
        pid = p.get("id") if isinstance(p, dict) else p
        if pid:
            provides.add(str(pid).lower())

    meta = ql.get("metadata", {}) if isinstance(ql, dict) else {}
    name = meta.get("name") or mid

    env = str(data.get("environment", "*")).strip().lower()
    side = {"client": Side.CLIENT, "server": Side.SERVER, "dedicated_server": Side.SERVER,
            "*": Side.BOTH, "": Side.BOTH}.get(env, Side.UNKNOWN)

    for kind, edge in (("depends", EdgeType.REQUIRES), ("breaks", EdgeType.INCOMPATIBLE)):
        for item in _as_list(ql.get(kind)):
            if isinstance(item, str):
                _add_dep(deps, mc_ranges, item, "*", edge, source="jar")
            elif isinstance(item, dict):
                optional = bool(item.get("optional"))
                e = EdgeType.OPTIONAL if (optional and edge == EdgeType.REQUIRES) else edge
                _add_dep(deps, mc_ranges, item.get("id"), item.get("versions", "*"),
                         e, source="jar")

    return {"ids": ids, "provides": provides, "loaders": loaders, "deps": deps,
            "mc_ranges": mc_ranges, "name": name,
            "version": str(ql.get("version") or ""), "side": side}


def _parse_forge(content: str, toml_name: str) -> dict:
    parsed = parse_mods_toml(content)
    ids = set()
    provides = set()
    deps: list[Dependency] = []
    mc_ranges: list = []
    name = ""
    version_raw = ""
    side = Side.UNKNOWN

    is_neo = "neoforge" in toml_name

    mods = parsed.get("mods") or []
    for i, m in enumerate(mods):
        mid = str(m.get("modId") or "").strip().lower()
        if mid:
            ids.add(mid)
        if i == 0:
            name = m.get("displayName") or mid
            version_raw = str(m.get("version") or "")
        # NeoForge per-mod side
        s = str(m.get("side") or "").strip().upper()
        if s == "CLIENT":
            side = Side.CLIENT
        elif s == "SERVER" and side == Side.UNKNOWN:
            side = Side.SERVER

    # Older Forge flag
    if "clientsideonly" in content.lower():
        import re as _re
        if _re.search(r"clientsideonly\s*=\s*true", content.lower()):
            side = Side.CLIENT

    deps_map = parsed.get("dependencies") or {}
    for _owner, dep_list in deps_map.items():
        for d in dep_list:
            dep_id = str(d.get("modId") or "").strip().lower()
            if not dep_id:
                continue
            mandatory = d.get("mandatory")
            if mandatory is None:
                mandatory = True
            rng = d.get("versionRange") or "*"
            dep_side = _forge_side(d.get("side"))
            if dep_id == "neoforge":
                is_neo = True
            edge = EdgeType.REQUIRES if mandatory else EdgeType.OPTIONAL
            _add_dep(deps, mc_ranges, dep_id, rng, edge, source="jar",
                     side=dep_side, bare_min=True)

    loaders = {Loader.NEOFORGE} if is_neo else {Loader.FORGE}
    return {"ids": ids, "provides": provides, "loaders": loaders, "deps": deps,
            "mc_ranges": mc_ranges, "name": name, "version": version_raw, "side": side}


def _forge_side(value) -> Side:
    v = str(value or "").strip().upper()
    return {"CLIENT": Side.CLIENT, "SERVER": Side.SERVER, "BOTH": Side.BOTH}.get(v, Side.BOTH)


# --------------------------------------------------------------- jar-in-jar
def _extract_embedded(zf: zipfile.ZipFile, names: set[str], *, depth: int,
                      max_depth: int) -> list[CanonicalMod]:
    nested_paths = [
        n for n in names
        if n.endswith(".jar") and (
            n.startswith("META-INF/jarjar/")   # Forge/NeoForge JiJ
            or n.startswith("META-INF/jars/")   # Fabric nested jars
            or n.startswith("jars/")
        )
    ]
    out: list[CanonicalMod] = []
    for np in nested_paths:
        try:
            data = zf.read(np)
        except Exception:
            continue
        child = extract_bytes(data, Path(np).name, max_depth=max_depth, depth=depth + 1)
        if child and (child.mod_ids or child.provides):
            out.append(child)
    return out


# ------------------------------------------------------------- mixins / ATs
def _collect_mixin_targets(zf: zipfile.ZipFile, names: set[str]) -> set[str]:
    targets: set[str] = set()
    mixin_configs = [n for n in names if n.endswith(".mixins.json") or
                     (n.endswith(".json") and "mixin" in n.lower() and "/" not in n)]
    for cfg in mixin_configs[:20]:
        try:
            data = json.loads(zf.read(cfg).decode("utf-8", "ignore"))
        except Exception:
            continue
        pkg = str(data.get("package") or "")
        for key in ("mixins", "client", "server"):
            for m in data.get(key) or []:
                if isinstance(m, str):
                    targets.add(f"{pkg}.{m}" if pkg else m)
    return targets


def _collect_access_transformers(zf: zipfile.ZipFile, names: set[str]) -> set[str]:
    ats: set[str] = set()
    for at in ("META-INF/accesstransformer.cfg", "META-INF/accesstransformer.cfg"):
        if at in names:
            try:
                content = zf.read(at).decode("utf-8", "ignore")
                for line in content.splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line:
                        ats.add(line)
            except Exception:
                pass
    return ats


# ------------------------------------------------------------------ helpers
def _merge(mod_ids, provides, loaders, deps, mc_ranges, parsed):
    mod_ids.update(parsed["ids"])
    provides.update(parsed["provides"])
    loaders.update(parsed["loaders"])
    deps.extend(parsed["deps"])
    mc_ranges.extend(parsed["mc_ranges"])


def _add_dep(deps, mc_ranges, dep_id, rng, edge, *, source, side=Side.BOTH,
             bare_min=False):
    if not dep_id:
        return
    dep_id = str(dep_id).strip().lower()
    if isinstance(rng, list):
        rng = rng[0] if rng else "*"
    range_obj = parse_range(str(rng), bare_is_minimum=bare_min)
    if dep_id == "minecraft":
        mc_ranges.append(range_obj)
        return
    if dep_id in _CORE_IDS:
        return
    deps.append(Dependency(target_id=dep_id, type=edge, range=range_obj,
                           side=side, source=source))


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _read_json(zf: zipfile.ZipFile, name: str) -> dict:
    try:
        return json.loads(zf.read(name).decode("utf-8", "ignore"))
    except Exception:
        return {}


def _primary_id(mod_ids: set[str], filename: str) -> str:
    non_core = sorted(m for m in mod_ids if m and m not in _CORE_IDS)
    if non_core:
        return non_core[0]
    if mod_ids:
        return sorted(mod_ids)[0]
    return _fallback_id(filename)


def _fallback_id(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = stem.split("-")[0].split("_")[0]
    return stem or "unknown"


def _hash_file(path: Path, algo: str = "sha512") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
