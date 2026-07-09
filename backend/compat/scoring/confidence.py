"""Stage 4 — weighted confidence model.

Turns grouped evidence into per-axis :class:`Axis` objects (fused probability +
confidence), and combines axes into a single 0..100 compatibility score with an
evidence-quality-gated veto.
"""

from __future__ import annotations

from ..evidence.fusion import dominant_negative, fuse
from ..models import Axis, Evidence
from .. import weights as W


def fuse_axis(name: str, evidence: list[Evidence]) -> Axis:
    p, conf = fuse(evidence)
    return Axis(name=name, score=p * 100.0, confidence=conf, evidence=list(evidence))


def _signed(axis: Axis) -> float:
    """Map an axis score (0..100) to a signed contribution (-1..+1)."""
    return (axis.score - 50.0) / 50.0


# Relative importance of each axis in the final compatibility score.
_AXIS_WEIGHT = {
    "loader": 30.0,
    "mc_version": 20.0,
    "dependencies": 25.0,
    "conflicts": 20.0,
}


def combine_score(axes: dict[str, Axis]) -> float:
    score = 50.0
    for name, w in _AXIS_WEIGHT.items():
        ax = axes.get(name)
        if ax is not None:
            score += w * _signed(ax)

    # Evidence-quality-gated veto: only an authoritative negative signal
    # (jar/API, not filename) on a *fatal* axis may force the score down. These
    # are the hard incompatibilities — wrong loader or wrong Minecraft version —
    # a mod built for the wrong loader/MC simply will not load. This gating is
    # the core fix for false loader/version-mismatch incompatibilities: a weak
    # signal (filename, low-trust source) can never trigger it.
    for fatal_axis in ("loader", "mc_version"):
        ax = axes.get(fatal_axis)
        if ax is None or _signed(ax) >= 0:
            continue
        veto = dominant_negative(
            ax.evidence,
            min_trust=W.gate("veto_min_trust"),
            min_weight=W.gate("veto_min_weight"),
        )
        if veto is not None:
            score = min(score, W.gate("veto_score_cap"))

    return max(0.0, min(100.0, score))


def overall_confidence(axes: dict[str, Axis]) -> float:
    """Importance-weighted mean of the confidence of axes that have evidence."""
    num = 0.0
    den = 0.0
    for name, w in _AXIS_WEIGHT.items():
        ax = axes.get(name)
        if ax is not None and ax.evidence:
            num += ax.confidence * w
            den += w
    return num / den if den else 0.0


__all__ = ["fuse_axis", "combine_score", "overall_confidence"]
