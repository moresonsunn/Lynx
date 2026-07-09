"""Evidence collector base class and registry."""

from __future__ import annotations

from typing import Optional

from ...models import CanonicalMod, Evidence, Loader
from ..context import AnalysisContext


class EvidenceCollector:
    """Base class. A collector observes a mod and emits :class:`Evidence`.

    Collectors never decide anything — they only report signals with a source,
    polarity, weight and trust. The fusion engine combines them.
    """

    name: str = "base"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        raise NotImplementedError


def loader_compatibility(pack: Loader, mod_loaders: frozenset[Loader]) -> Optional[bool]:
    """Return True/False/None (unknown) for loader compatibility.

    ``None`` deliberately means "cannot decide" so we never emit a false
    mismatch. NeoForge/Forge cross-compatibility is version-dependent, so it is
    treated as neutral rather than a hard mismatch.
    """
    if pack == Loader.UNKNOWN or not mod_loaders:
        return None
    if pack in mod_loaders:
        return True
    if pack == Loader.QUILT and Loader.FABRIC in mod_loaders:
        return True  # Quilt runs Fabric mods
    if pack == Loader.NEOFORGE and Loader.FORGE in mod_loaders:
        return None  # ambiguous (1.20.1 compatible, later versions not)
    if pack in (Loader.FORGE, Loader.NEOFORGE) and (
        Loader.FABRIC in mod_loaders or Loader.QUILT in mod_loaders
    ):
        return False
    if pack in (Loader.FABRIC, Loader.QUILT) and (
        Loader.FORGE in mod_loaders or Loader.NEOFORGE in mod_loaders
    ):
        return False
    if pack == Loader.FORGE and Loader.NEOFORGE in mod_loaders:
        return False
    return False


__all__ = ["EvidenceCollector", "loader_compatibility"]
