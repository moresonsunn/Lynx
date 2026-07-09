"""Evidence engine — runs collectors and groups their output by claim."""

from __future__ import annotations

import logging
from collections import defaultdict

from ..models import CanonicalMod, Evidence
from .collectors import EvidenceCollector, default_collectors
from .context import AnalysisContext

logger = logging.getLogger(__name__)


def gather_evidence(mod: CanonicalMod, ctx: AnalysisContext,
                    collectors: list[EvidenceCollector] | None = None) -> list[Evidence]:
    collectors = collectors if collectors is not None else default_collectors(use_api=ctx.use_api)
    out: list[Evidence] = []
    for collector in collectors:
        try:
            out.extend(collector.collect(mod, ctx) or [])
        except Exception as e:  # a broken collector must never fail the analysis
            logger.debug("Collector %s failed for %s: %s", collector.name, mod.filename, e)
    return out


def group_by_claim(evidence: list[Evidence]) -> dict[str, list[Evidence]]:
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for e in evidence:
        grouped[e.claim].append(e)
    return dict(grouped)


__all__ = ["gather_evidence", "group_by_claim"]
