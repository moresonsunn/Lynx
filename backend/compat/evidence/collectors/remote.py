"""Remote evidence collectors: Modrinth, CurseForge, GitHub releases.

All remote calls are cached (:class:`ApiCache`) and degrade gracefully: any
network/parse failure yields *no evidence* (neutral), never a negative signal.
This is central to avoiding false incompatibilities when a source is simply
unavailable.
"""

from __future__ import annotations

import logging
import re

import requests

from ...models import CanonicalMod, Evidence
from ... import weights as W
from ..context import AnalysisContext
from .base import EvidenceCollector

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Lynx-CompatEngine/1.0 (+https://github.com/moresonsunn/Lynx)"}
_TIMEOUT = 12


def _cache():
    from ...cache import get_api_cache as _g
    return _g()


class ModrinthCollector(EvidenceCollector):
    name = "modrinth"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        if not ctx.use_api:
            return []
        data = self._lookup(mod)
        if not data:
            return []
        ev: list[Evidence] = []
        trust = W.trust("modrinth")
        mod.provider_ids["modrinth"] = data.get("id") or data.get("slug")

        # discover github repo for the GitHub collector
        src = str(data.get("source_url") or "")
        m = re.search(r"github\.com/([^/]+/[^/#?]+)", src)
        if m:
            mod.provider_ids.setdefault("github", m.group(1).removesuffix(".git"))

        client_side = str(data.get("client_side", "")).lower()
        server_side = str(data.get("server_side", "")).lower()
        if server_side == "unsupported" and client_side in ("required", "optional"):
            ev.append(Evidence("modrinth", "side", -1.0, W.weight("side_api"), trust,
                               "Modrinth: server_side=unsupported (client-only)",
                               url=self._project_url(data)))
        elif client_side == "unsupported":
            ev.append(Evidence("modrinth", "side", +1.0, W.weight("side_api"), trust,
                               "Modrinth: client_side=unsupported (server-only)",
                               url=self._project_url(data)))
        elif server_side in ("required", "optional") and client_side in ("required", "optional"):
            # required-on-both is a stronger 'keep' signal than optional
            pol = +1.0
            ev.append(Evidence("modrinth", "side", pol, W.weight("side_api"), trust,
                               f"Modrinth: client_side={client_side}, server_side={server_side}",
                               url=self._project_url(data)))

        # loader
        loaders = [str(x).lower() for x in (data.get("loaders") or [])]
        if loaders and ctx.loader.value != "unknown":
            if ctx.loader.value in loaders or (ctx.loader.value == "quilt" and "fabric" in loaders):
                ev.append(Evidence("modrinth", "loader", +1.0, W.weight("loader_match"), trust,
                                   f"Modrinth lists loaders {loaders}"))
            elif not _loader_family_overlap(ctx.loader.value, loaders):
                ev.append(Evidence("modrinth", "loader", -1.0, W.weight("loader_mismatch"), trust,
                                   f"Modrinth loaders {loaders} exclude {ctx.loader.value}"))

        # mc version
        gvs = [str(x) for x in (data.get("game_versions") or [])]
        if gvs and ctx.mc_version:
            if ctx.mc_version in gvs:
                ev.append(Evidence("modrinth", "mc_version", +1.0, W.weight("mc_overlap"), trust,
                                   f"Modrinth supports Minecraft {ctx.mc_version}"))
            else:
                ev.append(Evidence("modrinth", "mc_version", -1.0, W.weight("mc_disjoint") * 0.6,
                                   trust, f"Modrinth version list does not include {ctx.mc_version}"))
        return ev

    # ---------------------------------------------------------------- helpers
    def _project_url(self, data: dict) -> str | None:
        slug = data.get("slug") or data.get("id")
        return f"https://modrinth.com/mod/{slug}" if slug else None

    def _lookup(self, mod: CanonicalMod) -> dict | None:
        cache = _cache()
        if mod.sha512:
            key = f"modrinth:hash:{mod.sha512}"
            cached = cache.get(key)
            if cached is not None:
                return cached or None
            proj = self._by_hash(mod.sha512)
            cache.put(key, proj or {})
            if proj:
                return proj
        for slug in _slug_variants(mod.canonical_id):
            key = f"modrinth:slug:{slug}"
            cached = cache.get(key)
            if cached is not None:
                if cached:
                    return cached
                continue
            proj = self._by_slug(slug)
            cache.put(key, proj or {})
            if proj:
                return proj
        return None

    def _by_hash(self, sha512: str) -> dict | None:
        try:
            r = requests.get(f"https://api.modrinth.com/v2/version_file/{sha512}",
                             params={"algorithm": "sha512"}, headers=_UA, timeout=_TIMEOUT)
            if not r.ok:
                return None
            pid = r.json().get("project_id")
            if not pid:
                return None
            pr = requests.get(f"https://api.modrinth.com/v2/project/{pid}",
                              headers=_UA, timeout=_TIMEOUT)
            return pr.json() if pr.ok else None
        except Exception:
            return None

    def _by_slug(self, slug: str) -> dict | None:
        try:
            r = requests.get(f"https://api.modrinth.com/v2/project/{slug}",
                             headers=_UA, timeout=_TIMEOUT)
            return r.json() if r.ok else None
        except Exception:
            return None


class CurseForgeCollector(EvidenceCollector):
    name = "curseforge"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        if not ctx.use_api or not ctx.cf_api_key or not mod.path:
            return []
        file_data = self._fingerprint_lookup(mod, ctx.cf_api_key)
        if not file_data:
            return []
        ev: list[Evidence] = []
        trust = W.trust("curseforge")
        gvs = [str(x).lower() for x in (file_data.get("gameVersions") or [])]
        if "client" in gvs and "server" not in gvs:
            ev.append(Evidence("curseforge", "side", -1.0, W.weight("side_api"), trust,
                               "CurseForge file tagged Client (not Server)"))
        elif "server" in gvs and "client" not in gvs:
            ev.append(Evidence("curseforge", "side", +1.0, W.weight("side_api"), trust,
                               "CurseForge file tagged Server"))
        # loader
        for ln in ("forge", "fabric", "neoforge", "quilt"):
            if ln in gvs and ctx.loader.value != "unknown":
                if ln == ctx.loader.value or (ctx.loader.value == "quilt" and ln == "fabric"):
                    ev.append(Evidence("curseforge", "loader", +1.0, W.weight("loader_match"),
                                       trust, f"CurseForge file targets {ln}"))
                break
        # mc version
        if ctx.mc_version and ctx.mc_version.lower() in gvs:
            ev.append(Evidence("curseforge", "mc_version", +1.0, W.weight("mc_overlap"), trust,
                               f"CurseForge file targets Minecraft {ctx.mc_version}"))
        return ev

    def _fingerprint_lookup(self, mod: CanonicalMod, api_key: str) -> dict | None:
        cache = _cache()
        key = f"cf:fp:{mod.sha512 or mod.filename}"
        cached = cache.get(key)
        if cached is not None:
            return cached or None
        try:
            fp = _cf_fingerprint(mod.path)
            r = requests.post(
                "https://api.curseforge.com/v1/fingerprints",
                json={"fingerprints": [fp]},
                headers={"x-api-key": api_key, "Accept": "application/json", **_UA},
                timeout=_TIMEOUT,
            )
            if not r.ok:
                cache.put(key, {})
                return None
            matches = (r.json().get("data") or {}).get("exactMatches") or []
            file_data = matches[0].get("file") if matches else None
            cache.put(key, file_data or {})
            if file_data:
                pid = file_data.get("modId")
                if pid:
                    mod.provider_ids["curseforge"] = pid
            return file_data
        except Exception:
            cache.put(key, {})
            return None


class GitHubReleaseCollector(EvidenceCollector):
    """Reads GitHub releases when a repo was discovered (e.g. via Modrinth)."""

    name = "github"

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        if not ctx.use_api or not ctx.mc_version:
            return []
        repo = mod.provider_ids.get("github")
        if not repo:
            return []
        releases = self._releases(repo)
        if not releases:
            return []
        for rel in releases[:5]:
            blob = " ".join(str(rel.get(k) or "") for k in ("name", "tag_name", "body"))
            if ctx.mc_version in blob:
                return [Evidence("github", "mc_version", +1.0, W.weight("github_supports"),
                                 W.trust("github"),
                                 f"GitHub release mentions Minecraft {ctx.mc_version}",
                                 freshness=0.9, url=rel.get("html_url"))]
        return []

    def _releases(self, repo: str) -> list[dict]:
        cache = _cache()
        key = f"gh:releases:{repo}"
        cached = cache.get(key)
        if cached is not None:
            return cached or []
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}/releases",
                             params={"per_page": 5}, headers=_UA, timeout=_TIMEOUT)
            data = r.json() if r.ok else []
            data = data if isinstance(data, list) else []
            cache.put(key, data)
            return data
        except Exception:
            cache.put(key, [])
            return []


# --------------------------------------------------------------------- utils
def _slug_variants(mod_id: str) -> list[str]:
    variants = [mod_id]
    alt = mod_id.replace("_", "-")
    if alt != mod_id:
        variants.append(alt)
    alt2 = mod_id.replace("-", "_")
    if alt2 not in variants:
        variants.append(alt2)
    return variants


def _loader_family_overlap(pack_loader: str, loaders: list[str]) -> bool:
    fabricish = {"fabric", "quilt"}
    forgeish = {"forge", "neoforge"}
    if pack_loader in fabricish:
        return any(l in fabricish for l in loaders)
    if pack_loader in forgeish:
        return any(l in forgeish for l in loaders)
    return pack_loader in loaders


def _cf_fingerprint(path: str) -> int:
    """CurseForge's file fingerprint: murmur2 (seed 1) over the file with
    whitespace bytes (9, 10, 13, 32) removed."""
    with open(path, "rb") as f:
        data = f.read()
    filtered = bytes(b for b in data if b not in (9, 10, 13, 32))
    return _murmur2(filtered, seed=1)


def _murmur2(data: bytes, seed: int = 1) -> int:
    m = 0x5BD1E995
    r = 24
    length = len(data)
    h = (seed ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = (data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24)) & 0xFFFFFFFF
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length == 3:
        h ^= data[i + 2] << 16
    if length >= 2:
        h ^= data[i + 1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF


__all__ = ["ModrinthCollector", "CurseForgeCollector", "GitHubReleaseCollector"]
