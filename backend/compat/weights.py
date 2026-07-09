"""Central, tunable weights for evidence and scoring.

Weights live in data (``knowledge/seeds/weights.json``) with code defaults as a
fallback, so tuning the model never requires touching logic. ``trust`` values
encode per-source reliability; ``weight`` values encode per-signal strength.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# Per-source trust (0..1).
TRUST = {
    "jar": 0.95,
    "modrinth": 0.85,
    "curseforge": 0.70,
    "github": 0.75,
    "kb": 0.80,
    "filename": 0.30,
    "graph": 0.90,
}

# Per-signal intrinsic weight. Filename is capped low so it can never gate.
WEIGHT = {
    "loader_match": 3.0,
    "loader_mismatch": 3.0,
    "mc_overlap": 2.2,
    "mc_disjoint": 3.0,
    "side_explicit": 3.0,
    "side_api": 2.0,
    "side_kb": 1.6,
    "side_filename": 0.6,
    "dep_satisfied": 2.5,
    "dep_missing": 2.5,
    "dep_optional_missing": 0.3,
    "dep_wrong_version": 1.5,
    "known_pair": 3.5,
    "server_required": 2.4,
    "addon_prefix": 2.0,
    "experimental": 1.0,
    "github_supports": 1.8,
}

# Thresholds used by the reasoner / veto logic.
GATE = {
    "veto_min_trust": 0.9,
    "veto_min_weight": 2.5,
    "veto_score_cap": 12.0,
    "review_confidence": 0.45,
    "compatible_score": 78.0,
    "compatible_confidence": 0.55,
    "warn_score": 58.0,
    "incompatible_score": 38.0,
    "client_only_confidence": 0.6,
}

_SEED = Path(__file__).parent / "knowledge" / "seeds" / "weights.json"


@lru_cache(maxsize=1)
def _overlay() -> dict:
    try:
        return json.loads(_SEED.read_text(encoding="utf-8"))
    except Exception:
        return {}


def trust(source: str) -> float:
    return float(_overlay().get("TRUST", {}).get(source, TRUST.get(source, 0.5)))


def weight(signal: str) -> float:
    return float(_overlay().get("WEIGHT", {}).get(signal, WEIGHT.get(signal, 1.0)))


def gate(name: str) -> float:
    return float(_overlay().get("GATE", {}).get(name, GATE.get(name, 0.0)))
