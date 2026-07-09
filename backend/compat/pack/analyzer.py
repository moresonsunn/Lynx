"""Stages 9 & 10 — pack-wide analysis orchestration.

Ties every stage together:

1. extract (content-cached, parallel)
2. normalize identity
3. build dependency graph + resolve
4. detect conflicts pack-wide
5. gather + fuse evidence per mod (parallel), injecting pack-level signals
   (a mod required by another mod is a strong "keep on server" signal)
6. reason -> graded verdicts
7. aggregate pack statistics and warnings
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..conflicts import detect_all
from ..evidence import AnalysisContext, gather_evidence, group_by_claim
from ..evidence.engine import gather_evidence as _gather
from ..extract import _hash_file, extract_jar
from ..graph import build_graph
from ..identity import finalize_identity, normalize_loader
from ..knowledge import get_default_kb
from ..models import CanonicalMod, Evidence, ModVerdict, PackReport, Severity
from ..cache import get_content_cache
from .. import weights as W
from ..scoring.reasoner import decide

logger = logging.getLogger(__name__)


def _extract_cached(path: Path, kb) -> CanonicalMod:
    sha = ""
    try:
        sha = _hash_file(path)
    except OSError:
        pass
    cache = get_content_cache()
    if sha:
        hit = cache.get(sha)
        if hit is not None:
            # Return a distinct copy so two byte-identical files (same SHA) each
            # keep their own filename/path — otherwise duplicate detection breaks.
            from dataclasses import replace as _dc_replace
            return _dc_replace(hit, path=str(path), filename=path.name)
    mod = extract_jar(path, compute_hash=not sha)
    if sha:
        mod.sha512 = sha
    finalize_identity(mod, kb)
    if mod.sha512:
        cache.put(mod.sha512, mod)
    return mod


def analyze_pack(mods_dir, *, loader=None, mc_version=None, use_api: bool = True,
                 cf_api_key: str | None = None, max_workers: int = 4) -> PackReport:
    mods_path = Path(mods_dir)
    if mods_path.name != "mods" and (mods_path / "mods").is_dir():
        mods_path = mods_path / "mods"
    if not mods_path.is_dir():
        return PackReport(loader=loader, mc_version=mc_version,
                          warnings=[f"No mods directory at {mods_path}"])

    jars = sorted(mods_path.glob("*.jar"))
    if not jars:
        return PackReport(loader=loader, mc_version=mc_version)

    kb = get_default_kb()
    ctx = AnalysisContext(
        loader=normalize_loader(loader),
        mc_version=mc_version,
        use_api=use_api,
        cf_api_key=cf_api_key,
        kb=kb,
    )

    # 1-2: extract + normalize (parallel, I/O bound)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        mods: list[CanonicalMod] = list(pool.map(lambda p: _extract_cached(p, kb), jars))

    # Infer the pack loader from the mods themselves when the caller did not
    # supply one, so loader evidence is still available.
    if ctx.loader.value == "unknown":
        inferred = _infer_loader(mods)
        if inferred is not None:
            ctx.loader = inferred

    # 3: dependency graph + resolution
    graph = build_graph(mods, kb)
    resolved = graph.resolve()
    resolved_by_src: dict[str, list] = defaultdict(list)
    for e in resolved:
        resolved_by_src[e.src].append(e)
    required_closure = graph.required_closure()

    # 4: conflicts
    conflicts = detect_all(mods, graph, kb)
    conflicts_by_file: dict[str, list] = defaultdict(list)
    for c in conflicts:
        conflicts_by_file[c.mod_a].append(c)
        conflicts_by_file[c.mod_b].append(c)

    # 5: evidence (parallel)
    def _evidence_for(mod: CanonicalMod):
        ev = _gather(mod, ctx)
        grouped = group_by_claim(ev)
        _inject_pack_signals(mod, grouped, required_closure, kb)
        return mod, grouped

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        evidence_pairs = list(pool.map(_evidence_for, mods))

    # 6: reason
    verdicts: list[ModVerdict] = []
    for mod, grouped in evidence_pairs:
        verdict = decide(mod, grouped, resolved_by_src.get(mod.canonical_id, []),
                         conflicts_by_file.get(mod.filename, []), ctx)
        verdicts.append(verdict)

    verdicts.sort(key=lambda v: (v.compat_score, v.confidence))

    # 7: pack-wide aggregation
    report = PackReport(loader=ctx.loader.value, mc_version=mc_version, verdicts=verdicts,
                        conflicts=conflicts)
    _aggregate(report, graph, resolved, verdicts)
    return report


def analyze_single_jar(jar_path, *, loader=None, mc_version=None, use_api: bool = True,
                       cf_api_key: str | None = None) -> ModVerdict:
    kb = get_default_kb()
    ctx = AnalysisContext(loader=normalize_loader(loader), mc_version=mc_version,
                          use_api=use_api, cf_api_key=cf_api_key, kb=kb)
    mod = _extract_cached(Path(jar_path), kb)
    ev = gather_evidence(mod, ctx)
    grouped = group_by_claim(ev)
    # Single jar out of pack context: do not penalize unresolved dependencies.
    return decide(mod, grouped, [], [], ctx)


def _infer_loader(mods: list[CanonicalMod]):
    from collections import Counter
    from ..models import Loader
    counter: Counter = Counter()
    for mod in mods:
        for loader in mod.loaders:
            if loader != Loader.UNKNOWN:
                counter[loader] += 1
    if not counter:
        return None
    if Loader.FORGE in counter and Loader.NEOFORGE in counter:
        return Loader.NEOFORGE if counter[Loader.NEOFORGE] >= counter[Loader.FORGE] else Loader.FORGE
    return counter.most_common(1)[0][0]


def _inject_pack_signals(mod: CanonicalMod, grouped: dict[str, list[Evidence]],
                         required_closure: set[str], kb) -> None:
    if mod.canonical_id in required_closure:
        grouped.setdefault("side", []).append(Evidence(
            "graph", "side", +1.0, W.weight("server_required"), W.trust("graph"),
            "Required as a dependency by another mod in the pack — must stay on the server",
        ))
    # depends on a server-required family -> has server-side logic
    for dep in mod.dependencies:
        if kb.is_server_required(dep.target_id) or kb.matches_addon_prefix(dep.target_id):
            grouped.setdefault("side", []).append(Evidence(
                "graph", "side", +1.0, W.weight("addon_prefix"), W.trust("graph"),
                f"Depends on server-required mod '{dep.target_id}'",
            ))
            break


def _aggregate(report: PackReport, graph, resolved, verdicts: list[ModVerdict]) -> None:
    missing = defaultdict(lambda: {"dependency_id": "", "required_by": [], "range": None})
    for e in resolved:
        if e.status in ("missing", "wrong_version"):
            src_mod = graph.mods.get(e.src)
            entry = missing[e.target_key]
            entry["dependency_id"] = e.dep.target_id
            entry["range"] = e.dep.range.raw if e.dep.range else None
            entry["status"] = e.status
            if src_mod:
                entry["required_by"].append(src_mod.name)
    report.missing_dependencies = list(missing.values())

    counts = defaultdict(int)
    for v in verdicts:
        counts[v.verdict.value] += 1
    report.stats = {
        "total": len(verdicts),
        "by_verdict": dict(counts),
        "client_only": sum(1 for v in verdicts if v.is_client_only),
        "conflicts": len(report.conflicts),
        "missing_dependencies": len(report.missing_dependencies),
        "cycles": len(graph.cycles()),
    }

    if any(c.severity == Severity.CRITICAL and c.kind == "loader" for c in report.conflicts):
        report.warnings.append("Mixed mod loaders detected — the pack will not start.")
    if report.missing_dependencies:
        report.warnings.append(
            f"{len(report.missing_dependencies)} required dependency(ies) are missing.")


__all__ = ["analyze_pack", "analyze_single_jar"]
