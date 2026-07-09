"""Stage 5 — reasoning engine.

Assembles all axes into an explainable :class:`ModVerdict`: a graded verdict, a
numeric score, ranked human-readable reasons, and concrete alternatives.
"""

from __future__ import annotations

from ..evidence.context import AnalysisContext
from ..graph import ResolvedEdge
from ..models import (Axis, CanonicalMod, Conflict, Evidence, ModVerdict,
                      Severity, Side, Verdict)
from .. import weights as W
from .confidence import combine_score, fuse_axis, overall_confidence


def build_dependency_axis(resolved: list[ResolvedEdge]) -> Axis:
    ev: list[Evidence] = []
    trust = W.trust("graph")
    for e in resolved:
        if e.status == "satisfied":
            ev.append(Evidence("graph", "dependencies", +1.0, W.weight("dep_satisfied"),
                               trust, f"Required dependency '{e.dep.target_id}' is present "
                               f"({e.provider})"))
        elif e.status == "missing":
            ev.append(Evidence("graph", "dependencies", -1.0, W.weight("dep_missing"), trust,
                               f"Required dependency '{e.dep.target_id}' is missing"))
        elif e.status == "wrong_version":
            ev.append(Evidence("graph", "dependencies", -1.0, W.weight("dep_wrong_version"),
                               trust, f"Dependency '{e.dep.target_id}' present but outside "
                               f"required range {e.dep.range.raw if e.dep.range else ''}"))
        elif e.status == "optional_missing":
            ev.append(Evidence("graph", "dependencies", -1.0, W.weight("dep_optional_missing"),
                               trust, f"Optional dependency '{e.dep.target_id}' not installed "
                               f"(informational)"))
    return fuse_axis("dependencies", ev)


def build_conflict_axis(conflicts: list[Conflict]) -> Axis:
    ev: list[Evidence] = []
    sev_weight = {Severity.CRITICAL: 1.0, Severity.WARNING: 0.5, Severity.INFO: 0.15}
    for c in conflicts:
        ev.append(Evidence("kb", "conflicts", -1.0,
                           W.weight("known_pair") * sev_weight.get(c.severity, 0.5),
                           W.trust("kb"), f"{c.kind}: {c.detail}"))
    return fuse_axis("conflicts", ev)


def determine_side(side_axis: Axis, mod: CanonicalMod) -> tuple[Side, float]:
    if mod.declared_side == Side.SERVER:
        return Side.SERVER, max(side_axis.confidence, 0.8)
    if not side_axis.evidence:
        return Side.UNKNOWN, 0.0
    p_needs_server = side_axis.score / 100.0
    conf = side_axis.confidence
    if p_needs_server < 0.4:
        return Side.CLIENT, conf
    if p_needs_server > 0.6:
        return Side.BOTH, conf
    return Side.UNKNOWN, conf


def _map_verdict(score: float, confidence: float, has_critical: bool,
                 has_authoritative_negative: bool) -> Verdict:
    if confidence < W.gate("review_confidence") and not has_authoritative_negative:
        # Not enough signal either way -> never silently drop; ask for review.
        return Verdict.NEEDS_REVIEW
    if (score >= W.gate("compatible_score")
            and confidence >= W.gate("compatible_confidence")
            and not has_critical):
        return Verdict.COMPATIBLE
    if score >= W.gate("warn_score"):
        return Verdict.COMPATIBLE_WITH_WARNINGS
    if score < W.gate("incompatible_score") and has_authoritative_negative:
        return Verdict.INCOMPATIBLE
    return Verdict.LIKELY_INCOMPATIBLE


def _reasons(axes: dict[str, Axis], side: Side) -> list[str]:
    all_ev: list[Evidence] = []
    for ax in axes.values():
        all_ev.extend(ax.evidence)
    all_ev.sort(key=lambda e: abs(e.effective), reverse=True)
    reasons = [f"{e.detail} (source={e.source}, weight={round(e.effective, 2)})"
               for e in all_ev[:6]]
    if side == Side.CLIENT:
        reasons.insert(0, "Detected as client-only — not required on a dedicated server.")
    return reasons


def _alternatives(mod: CanonicalMod, axes: dict[str, Axis], resolved: list[ResolvedEdge],
                  ctx: AnalysisContext) -> list[str]:
    alts: list[str] = []
    loader = axes.get("loader")
    if loader is not None and (loader.score - 50) / 50 < -0.2 and ctx.loader.value != "unknown":
        alts.append(f"Install the {ctx.loader.value} build of '{mod.name}' instead of the "
                    f"current {sorted(l.value for l in mod.loaders)} build.")
    mc = axes.get("mc_version")
    if mc is not None and (mc.score - 50) / 50 < -0.2 and ctx.mc_version:
        alts.append(f"Find a build of '{mod.name}' that targets Minecraft {ctx.mc_version}.")
    for e in resolved:
        if e.status == "missing":
            alts.append(f"Add the missing dependency '{e.dep.target_id}'"
                        + (f" ({e.dep.range.raw})" if e.dep.range and e.dep.range.raw != '*' else ""))
        elif e.status == "wrong_version":
            alts.append(f"Update '{e.dep.target_id}' to satisfy "
                        f"{e.dep.range.raw if e.dep.range else 'the required range'}.")
    return alts


def decide(mod: CanonicalMod, grouped: dict[str, list[Evidence]],
           resolved: list[ResolvedEdge], conflicts: list[Conflict],
           ctx: AnalysisContext) -> ModVerdict:
    loader_axis = fuse_axis("loader", grouped.get("loader", []))
    mc_axis = fuse_axis("mc_version", grouped.get("mc_version", []))
    side_axis = fuse_axis("side", grouped.get("side", []))
    dep_axis = build_dependency_axis(resolved)
    conflict_axis = build_conflict_axis(conflicts)

    axes = {
        "loader": loader_axis,
        "mc_version": mc_axis,
        "dependencies": dep_axis,
        "conflicts": conflict_axis,
        "side": side_axis,
    }

    score = combine_score(axes)
    confidence = overall_confidence(axes)
    has_critical = any(c.severity == Severity.CRITICAL for c in conflicts)

    # Is there an authoritative negative anywhere (loader/mc/deps)?
    from ..evidence.fusion import dominant_negative
    authoritative_negative = any(
        dominant_negative(axes[a].evidence,
                          min_trust=W.gate("veto_min_trust"),
                          min_weight=W.gate("veto_min_weight")) is not None
        for a in ("loader", "mc_version", "dependencies")
    )

    verdict = _map_verdict(score, confidence, has_critical, authoritative_negative)
    side, side_conf = determine_side(side_axis, mod)

    unresolved = [e.dep for e in resolved if e.status in ("missing", "wrong_version")]

    return ModVerdict(
        mod=mod,
        verdict=verdict,
        confidence=confidence,
        compat_score=score,
        side=side,
        side_confidence=side_conf,
        axes=list(axes.values()),
        reasons=_reasons(axes, side),
        alternatives=_alternatives(mod, axes, resolved, ctx),
        conflicts=conflicts,
        unresolved=unresolved,
    )


__all__ = ["decide", "build_dependency_axis", "build_conflict_axis", "determine_side"]
