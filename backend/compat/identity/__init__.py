"""Stage 1 — metadata normalization and canonical identity.

Turns the raw, inconsistent identifiers found in mod metadata into stable
canonical forms:

* loader names (``neoforge``/``NeoForge``/``neo`` -> :class:`Loader.NEOFORGE`)
* Minecraft versions (``1.20.1``, ``1.20.x``)
* mod ids (underscore/hyphen unified, then alias/rename resolved via the KB)
"""

from __future__ import annotations

import re

from ..knowledge import KnowledgeBase, get_default_kb
from ..models import CanonicalMod, Loader

# Common loader spellings seen in manifests and UIs.
_LOADER_ALIASES = {
    "forge": Loader.FORGE,
    "neoforge": Loader.NEOFORGE,
    "neo": Loader.NEOFORGE,
    "fabric": Loader.FABRIC,
    "quilt": Loader.QUILT,
    # hybrid servers run an underlying loader
    "mohist": Loader.FORGE,
    "magma": Loader.NEOFORGE,
    "banner": Loader.FABRIC,
    "catserver": Loader.FORGE,
    "spongeforge": Loader.FORGE,
    "arclight": Loader.FORGE,
}


def normalize_loader(value: object) -> Loader:
    v = str(value or "").strip().lower()
    if v in _LOADER_ALIASES:
        return _LOADER_ALIASES[v]
    return Loader.coerce(v)


def normalize_mc_version(value: object) -> str:
    """Normalize a Minecraft version string (strip leading ``mc``/``v``)."""
    v = str(value or "").strip().lower()
    v = re.sub(r"^(mc|minecraft[ _-]?|v)", "", v)
    return v.strip()


def normalize_mod_id(mod_id: object) -> str:
    """Lower-case and unify separators; alias resolution is applied separately."""
    return re.sub(r"[\s]+", "", str(mod_id or "").strip().lower())


def canonical_id_for(mod_id: str, kb: KnowledgeBase | None = None) -> str:
    kb = kb or get_default_kb()
    normalized = normalize_mod_id(mod_id)
    # unify separators to hyphen for a stable canonical key, then resolve alias
    unified = normalized.replace("_", "-")
    resolved = kb.resolve_alias(normalized)
    if resolved != normalized:
        return resolved
    resolved_unified = kb.resolve_alias(unified)
    if resolved_unified != unified:
        return resolved_unified
    return unified


def finalize_identity(mod: CanonicalMod, kb: KnowledgeBase | None = None) -> CanonicalMod:
    """Apply alias/rename resolution to a freshly extracted mod in place."""
    kb = kb or get_default_kb()
    mod.canonical_id = canonical_id_for(mod.canonical_id, kb)
    # Expand ``provides`` with alias-resolved forms so dependency matching is
    # separator- and rename-insensitive.
    expanded = set(mod.provides)
    for mid in list(mod.mod_ids) + list(mod.provides):
        expanded.add(canonical_id_for(mid, kb))
        expanded.add(normalize_mod_id(mid).replace("_", "-"))
    mod.provides = frozenset(expanded)
    return mod


__all__ = [
    "normalize_loader",
    "normalize_mc_version",
    "normalize_mod_id",
    "canonical_id_for",
    "finalize_identity",
]
