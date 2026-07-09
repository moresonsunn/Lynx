"""Stage 6 — conflict detection.

Pluggable detectors run once over the whole mod set and the dependency graph.
Each emits :class:`Conflict` objects that feed the per-mod conflict axis (graded)
rather than causing an instant rejection.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from ..graph import DependencyGraph
from ..knowledge import KnowledgeBase, get_default_kb
from ..models import CanonicalMod, Conflict, Loader, Severity


class ConflictDetector:
    name = "base"

    def detect(self, mods: list[CanonicalMod], graph: DependencyGraph,
               kb: KnowledgeBase) -> list[Conflict]:
        raise NotImplementedError


class ModIdCollisionDetector(ConflictDetector):
    name = "mod_id_collision"

    def detect(self, mods, graph, kb):
        out: list[Conflict] = []
        by_id: dict[str, list[CanonicalMod]] = defaultdict(list)
        for mod in mods:
            for mid in mod.mod_ids:
                by_id[mid].append(mod)
        for mid, owners in by_id.items():
            distinct = {o.filename for o in owners}
            if len(distinct) > 1:
                a, b = sorted(distinct)[:2]
                out.append(Conflict(
                    kind="mod_id_collision", mod_a=a, mod_b=b, severity=Severity.CRITICAL,
                    detail=f"Two jars declare the same mod id '{mid}'.",
                    fix="Remove the duplicate/older jar.",
                ))
        return out


class DuplicateLibraryDetector(ConflictDetector):
    name = "duplicate"

    def detect(self, mods, graph, kb):
        out: list[Conflict] = []
        by_canon: dict[str, list[CanonicalMod]] = defaultdict(list)
        for mod in mods:
            by_canon[mod.canonical_id].append(mod)
        for cid, group in by_canon.items():
            files = sorted({m.filename for m in group})
            if len(files) > 1:
                out.append(Conflict(
                    kind="duplicate", mod_a=files[0], mod_b=files[1],
                    severity=Severity.WARNING,
                    detail=f"Multiple copies of '{cid}' installed ({', '.join(files)}).",
                    fix="Keep only the newest compatible version.",
                ))
        return out


class MixinConflictDetector(ConflictDetector):
    name = "mixin"

    def detect(self, mods, graph, kb):
        out: list[Conflict] = []
        for a, b in combinations([m for m in mods if m.mixin_targets], 2):
            shared = a.mixin_targets & b.mixin_targets
            if shared:
                out.append(Conflict(
                    kind="mixin", mod_a=a.filename, mod_b=b.filename,
                    severity=Severity.WARNING,
                    detail=f"Overlapping mixin targets ({len(shared)}): "
                           f"{', '.join(sorted(shared)[:3])} ...",
                    fix="Verify these mods are known to coexist; check load order.",
                ))
        return out


class AccessTransformerDetector(ConflictDetector):
    name = "access_transformer"

    def detect(self, mods, graph, kb):
        out: list[Conflict] = []
        for a, b in combinations([m for m in mods if m.access_transformers], 2):
            shared = a.access_transformers & b.access_transformers
            if len(shared) >= 3:
                out.append(Conflict(
                    kind="access_transformer", mod_a=a.filename, mod_b=b.filename,
                    severity=Severity.INFO,
                    detail=f"{len(shared)} identical access-transformer entries.",
                    fix="Usually harmless; noted for completeness.",
                ))
        return out


class KnownPairDetector(ConflictDetector):
    name = "known_pair"

    def detect(self, mods, graph, kb):
        out: list[Conflict] = []
        present = {mod.canonical_id: mod for mod in mods}
        ids = list(present)
        for a, b in combinations(ids, 2):
            pair = kb.pair_for(a, b)
            if pair:
                out.append(Conflict(
                    kind=pair.kind, mod_a=present[a].filename, mod_b=present[b].filename,
                    severity=Severity(pair.severity) if pair.severity in
                    (s.value for s in Severity) else Severity.WARNING,
                    detail=pair.note or f"Known incompatibility between {a} and {b}.",
                    fix="Remove one of the two conflicting mods.",
                ))
        return out


class LoaderMixDetector(ConflictDetector):
    name = "loader"

    def detect(self, mods, graph, kb):
        loaders = set()
        for mod in mods:
            loaders |= mod.loaders
        fabricish = loaders & {Loader.FABRIC, Loader.QUILT}
        forgeish = loaders & {Loader.FORGE, Loader.NEOFORGE}
        if fabricish and forgeish:
            return [Conflict(
                kind="loader", mod_a="Fabric/Quilt mods", mod_b="Forge/NeoForge mods",
                severity=Severity.CRITICAL,
                detail="The pack mixes Fabric/Quilt and Forge/NeoForge mods, which cannot "
                       "run on the same server.",
                fix="Choose a single mod loader for the pack.",
            )]
        return []


DEFAULT_DETECTORS: list[ConflictDetector] = [
    ModIdCollisionDetector(),
    DuplicateLibraryDetector(),
    MixinConflictDetector(),
    AccessTransformerDetector(),
    KnownPairDetector(),
    LoaderMixDetector(),
]


def detect_all(mods: list[CanonicalMod], graph: DependencyGraph,
               kb: KnowledgeBase | None = None,
               detectors: list[ConflictDetector] | None = None) -> list[Conflict]:
    kb = kb or get_default_kb()
    detectors = detectors or DEFAULT_DETECTORS
    out: list[Conflict] = []
    for det in detectors:
        try:
            out.extend(det.detect(mods, graph, kb) or [])
        except Exception:
            continue
    return out


__all__ = ["ConflictDetector", "detect_all", "DEFAULT_DETECTORS"]
