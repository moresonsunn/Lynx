"""Stage 8 — knowledge fusion.

Combines many :class:`Evidence` items for a single claim into one probability
using **log-odds addition**::

    L = L0 + Σ (weight_i · trust_i · freshness_i · polarity_i)
    P = sigmoid(L)

Properties that fix the old single-signal bug:

* Agreement compounds; a lone weak signal cannot flip a verdict.
* Disagreement cancels in ``L`` so ``P -> 0.5`` and confidence drops toward 0 —
  conflicting sources yield *review*, never a hard reject.
* Confidence is derived as ``|2P - 1|`` (0 = coin-flip, 1 = certain).
"""

from __future__ import annotations

import math

from ..models import Evidence


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def fuse(evidence: list[Evidence], *, prior: float = 0.0) -> tuple[float, float]:
    """Fuse evidence into ``(probability, confidence)``.

    ``probability`` is P(claim is true / compatible) in ``[0, 1]``.
    ``confidence`` is ``|2P - 1|`` in ``[0, 1]``.
    """
    if not evidence:
        return sigmoid(prior), 0.0
    logodds = prior + sum(e.effective for e in evidence)
    p = sigmoid(logodds)
    return p, abs(2.0 * p - 1.0)


def dominant_negative(evidence: list[Evidence], *, min_trust: float = 0.9,
                      min_weight: float = 2.0) -> Evidence | None:
    """Return the strongest *authoritative* negative signal, if any.

    Used to decide whether a hard veto (loader/known-issue) is justified. A
    filename guess (low trust/weight) can never qualify, which is what stops
    false loader mismatches from vetoing a good mod.
    """
    negatives = [e for e in evidence
                 if e.polarity < 0 and e.trust >= min_trust and e.weight >= min_weight]
    if not negatives:
        return None
    return min(negatives, key=lambda e: e.effective)


__all__ = ["sigmoid", "fuse", "dominant_negative"]
