"""Local (offline) evidence collectors: JAR metadata, knowledge base, filename."""

from __future__ import annotations

from ...models import CanonicalMod, Evidence, Side
from ... import weights as W
from ..context import AnalysisContext
from .base import EvidenceCollector, loader_compatibility

# Best-effort import of the legacy filename patterns so we keep coverage.
try:  # pragma: no cover - depends on legacy module presence
    from client_mod_filter import CLIENT_ONLY_FILENAME_PATTERNS as _LEGACY_PATTERNS
except Exception:
    _LEGACY_PATTERNS = [
        "sodium", "iris", "oculus", "optifine", "embeddium", "rubidium",
        "xaeros", "journeymap", "voxelmap", "replaymod", "litematica",
        "minihud", "tweakeroo", "betterf3", "modmenu", "jei-",  # heuristic
    ]


class JarMetadataCollector(EvidenceCollector):
    name = "jar"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        ev: list[Evidence] = []
        trust = W.trust("jar")

        # ---- loader ----
        compat = loader_compatibility(ctx.loader, mod.loaders)
        if compat is True:
            ev.append(Evidence("jar", "loader", +1.0, W.weight("loader_match"), trust,
                               f"JAR declares loader(s) {sorted(l.value for l in mod.loaders)} "
                               f"matching pack loader {ctx.loader.value}"))
        elif compat is False:
            ev.append(Evidence("jar", "loader", -1.0, W.weight("loader_mismatch"), trust,
                               f"JAR loader(s) {sorted(l.value for l in mod.loaders)} do not "
                               f"match pack loader {ctx.loader.value}"))

        # ---- minecraft version ----
        if ctx.mc_parsed is not None and mod.mc_ranges:
            results = [r.contains(ctx.mc_parsed) for r in mod.mc_ranges]
            if any(r is True for r in results):
                ev.append(Evidence("jar", "mc_version", +1.0, W.weight("mc_overlap"), trust,
                                   f"Declared Minecraft range includes {ctx.mc_version}"))
            elif results and all(r is False for r in results):
                ev.append(Evidence("jar", "mc_version", -1.0, W.weight("mc_disjoint"), trust,
                                   f"Declared Minecraft range excludes {ctx.mc_version} "
                                   f"({[r.raw for r in mod.mc_ranges]})"))

        # ---- side ----
        if mod.declared_side == Side.CLIENT:
            ev.append(Evidence("jar", "side", -1.0, W.weight("side_explicit"), trust,
                               "JAR metadata declares client-only environment"))
        elif mod.declared_side in (Side.SERVER, Side.BOTH):
            ev.append(Evidence("jar", "side", +1.0, W.weight("side_explicit"), trust,
                               f"JAR metadata declares environment={mod.declared_side.value}"))

        return ev


class KnowledgeBaseCollector(EvidenceCollector):
    name = "kb"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        ev: list[Evidence] = []
        trust = W.trust("kb")
        kb = ctx.kb
        ids = {mod.canonical_id, *mod.mod_ids}

        if any(kb.is_server_required(i) for i in ids):
            ev.append(Evidence("kb", "side", +1.0, W.weight("server_required"), trust,
                               "Known server-required library/API — must stay on the server"))
        prefix = next((kb.matches_addon_prefix(i) for i in ids
                       if kb.matches_addon_prefix(i)), None)
        if prefix:
            ev.append(Evidence("kb", "side", +1.0, W.weight("addon_prefix"), trust,
                               f"Content addon of server-required family '{prefix}'"))
        if any(kb.is_client_only(i) for i in ids):
            ev.append(Evidence("kb", "side", -1.0, W.weight("side_kb"), trust,
                               "Listed in known client-only database"))
        return ev


class FilenameCollector(EvidenceCollector):
    """Lowest-trust fallback. Weight is capped so it can never gate a verdict."""

    name = "filename"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        name = mod.filename.lower()
        for pattern in _LEGACY_PATTERNS:
            if pattern and pattern in name:
                return [Evidence("filename", "side", -1.0, W.weight("side_filename"),
                                 W.trust("filename"),
                                 f"Filename matches client-only pattern '{pattern}'")]
        return []


__all__ = ["JarMetadataCollector", "KnowledgeBaseCollector", "FilenameCollector"]
