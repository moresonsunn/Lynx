"""Allowlist evidence collector for mod side detection.

Uses the force_server/force_client allowlist and user overrides.
"""

from __future__ import annotations

import logging

from ...models import CanonicalMod, Evidence, Side
from ... import weights as W
from ..context import AnalysisContext
from .base import EvidenceCollector
from ...allowlist import (
    check_force_side,
    check_user_override,
    get_effective_side,
)

logger = logging.getLogger(__name__)


class AllowlistCollector(EvidenceCollector):
    """Collects evidence from allowlist and user overrides."""

    name = "allowlist"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        ev: list[Evidence] = []

        # Check user override first
        override = check_user_override(mod.canonical_id)
        if override:
            trust = W.trust("allowlist")
            polarity = -1.0 if override == "client" else +1.0
            weight = W.weight("user_override")
            detail = f"User override: mod forced to {override.upper()} via UI"
            ev.append(Evidence(
                source="allowlist",
                claim="side",
                polarity=polarity,
                weight=weight,
                trust=trust,
                detail=detail,
                freshness=1.0,
            ))
            return ev  # User override takes precedence

        # Check allowlist
        forced = check_force_side(mod.canonical_id, mod.name)
        if forced:
            trust = W.trust("allowlist")
            polarity = -1.0 if forced == "client" else +1.0
            weight = W.weight("allowlist_forced")
            detail = f"Allowlist: mod forced to {forced.upper()}"
            ev.append(Evidence(
                source="allowlist",
                claim="side",
                polarity=polarity,
                weight=weight,
                trust=trust,
                detail=detail,
                freshness=1.0,
            ))

        return ev


__all__ = ["AllowlistCollector"]