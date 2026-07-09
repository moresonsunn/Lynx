"""
Lynx Compatibility Engine
=========================

A multi-stage, evidence-based mod compatibility analysis pipeline.

This package replaces the ad-hoc, single-signal compatibility logic that was
previously scattered across ``client_mod_filter.py``, ``mods_enhanced_routes.py``
and ``modpack_routes.py``.

Design goals:

* Separate the three quantities the old code merged: *identity*, *evidence*
  and *decision*.
* Combine evidence additively in log-odds space so no single weak signal can
  flip a verdict.
* Produce graded, explainable verdicts (not a binary ``is_client_only`` flag).
* Default to *keep + warn*: a false negative (deleting a needed mod) costs far
  more than a false positive (an extra warning).
* Keep knowledge in data, not code.

Public facade
-------------

>>> from compat import analyze_pack, analyze_jar
>>> report = analyze_pack("/data/servers/my-server/mods", loader="neoforge",
...                       mc_version="1.21.1")
>>> for v in report.verdicts:
...     print(v.mod.name, v.verdict, v.compat_score)
"""

from __future__ import annotations

# Version of the reasoning engine. Bump this whenever scoring/weights change so
# cached verdicts are invalidated.
ENGINE_VERSION = "1.0.0"

# The heavy imports are performed lazily inside the facade functions so that
# importing individual sub-packages (e.g. ``compat.versioning``) stays cheap and
# free of side effects.

__all__ = [
    "ENGINE_VERSION",
    "analyze_pack",
    "analyze_jar",
]


def analyze_pack(mods_dir, *, loader=None, mc_version=None, use_api: bool = True,
                 cf_api_key: str | None = None, max_workers: int = 4):
    """Analyze an entire mods directory and return a :class:`PackReport`.

    See :func:`compat.pack.analyzer.analyze_pack` for full documentation.
    """
    from .pack.analyzer import analyze_pack as _impl
    return _impl(
        mods_dir,
        loader=loader,
        mc_version=mc_version,
        use_api=use_api,
        cf_api_key=cf_api_key,
        max_workers=max_workers,
    )


def analyze_jar(jar_path, *, loader=None, mc_version=None, use_api: bool = True,
                cf_api_key: str | None = None):
    """Analyze a single JAR file and return a :class:`ModVerdict`."""
    from .pack.analyzer import analyze_single_jar as _impl
    return _impl(
        jar_path,
        loader=loader,
        mc_version=mc_version,
        use_api=use_api,
        cf_api_key=cf_api_key,
    )
