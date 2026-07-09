"""Knowledge base — data-driven compatibility facts.

Loads seed JSON files (aliases, known-incompatible pairs, server-required
libraries, addon prefixes) and, for backward-compatibility, merges the large
historical sets that still live in the legacy ``client_mod_filter`` module so no
detection coverage is lost during migration.

The KB is intentionally a *plain data* object. It is cheap to construct and is
cached process-wide via :func:`get_default_kb`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).parent / "seeds"


@dataclass
class KnownPair:
    a: str
    b: str
    kind: str
    severity: str
    trust: float
    note: str = ""


@dataclass
class KnowledgeBase:
    aliases: dict[str, str] = field(default_factory=dict)
    client_only: set[str] = field(default_factory=set)
    server_required: set[str] = field(default_factory=set)
    addon_prefixes: set[str] = field(default_factory=set)
    known_pairs: list[KnownPair] = field(default_factory=list)

    # ---------------------------------------------------------------- lookups
    def resolve_alias(self, mod_id: str) -> str:
        mid = (mod_id or "").strip().lower()
        seen = set()
        while mid in self.aliases and mid not in seen:
            seen.add(mid)
            mid = self.aliases[mid]
        return mid

    def is_client_only(self, mod_id: str) -> bool:
        return self.resolve_alias(mod_id) in self.client_only

    def is_server_required(self, mod_id: str) -> bool:
        return self.resolve_alias(mod_id) in self.server_required

    def matches_addon_prefix(self, mod_id: str) -> str | None:
        mid = (mod_id or "").strip().lower()
        for prefix in self.addon_prefixes:
            if mid.startswith(prefix + "_") or mid.startswith(prefix + "-"):
                return prefix
        return None

    def pair_for(self, a: str, b: str) -> KnownPair | None:
        a, b = self.resolve_alias(a), self.resolve_alias(b)
        for p in self.known_pairs:
            pa, pb = self.resolve_alias(p.a), self.resolve_alias(p.b)
            if {pa, pb} == {a, b}:
                return p
        return None


def _load_seed(name: str) -> dict:
    path = _SEEDS_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - seed files ship with the package
        logger.warning("Could not load KB seed %s: %s", name, e)
        return {}


def _merge_legacy(kb: KnowledgeBase) -> None:
    """Best-effort merge of the historical sets from client_mod_filter."""
    try:
        import client_mod_filter as legacy  # type: ignore
    except Exception:
        return
    for attr, target in (
        ("KNOWN_CLIENT_ONLY_MOD_IDS", kb.client_only),
        ("KNOWN_SERVER_REQUIRED_MOD_IDS", kb.server_required),
        ("_SERVER_REQUIRED_ADDON_PREFIXES", kb.addon_prefixes),
    ):
        values = getattr(legacy, attr, None)
        if isinstance(values, (set, frozenset, list, tuple)):
            target.update(str(v).lower() for v in values)


def load_knowledge_base() -> KnowledgeBase:
    kb = KnowledgeBase()

    aliases = _load_seed("aliases.json").get("aliases", {})
    kb.aliases = {str(k).lower(): str(v).lower() for k, v in aliases.items()}

    kb.server_required = {str(x).lower() for x in
                          _load_seed("server_required.json").get("server_required", [])}
    kb.addon_prefixes = {str(x).lower() for x in
                         _load_seed("addon_prefixes.json").get("server_required_addon_prefixes", [])}

    for p in _load_seed("known_pairs.json").get("pairs", []):
        try:
            kb.known_pairs.append(KnownPair(
                a=str(p["a"]).lower(), b=str(p["b"]).lower(),
                kind=p.get("kind", "known_pair"), severity=p.get("severity", "warning"),
                trust=float(p.get("trust", 0.7)), note=p.get("note", ""),
            ))
        except Exception:
            continue

    _merge_legacy(kb)
    logger.debug(
        "KB loaded: %d aliases, %d client_only, %d server_required, %d prefixes, %d pairs",
        len(kb.aliases), len(kb.client_only), len(kb.server_required),
        len(kb.addon_prefixes), len(kb.known_pairs),
    )
    return kb


@lru_cache(maxsize=1)
def get_default_kb() -> KnowledgeBase:
    return load_knowledge_base()
