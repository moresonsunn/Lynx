"""Core data models for the compatibility engine.

These dataclasses are the shared vocabulary of every stage. The three quantities
the old code merged are kept strictly separate here:

* **Identity** — :class:`CanonicalMod` (who is this mod, really).
* **Evidence** — :class:`Evidence` (what signals did we observe, from where).
* **Decision** — :class:`ModVerdict` (the graded, explainable conclusion).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing versioning at runtime where not needed
    from .versioning import ComparableVersion, VersionRange


# ════════════════════════════════════════════════════════════════════ enums
class Loader(str, Enum):
    FORGE = "forge"
    NEOFORGE = "neoforge"
    FABRIC = "fabric"
    QUILT = "quilt"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: object) -> "Loader":
        if isinstance(value, Loader):
            return value
        v = str(value or "").strip().lower()
        try:
            return cls(v)
        except ValueError:
            return cls.UNKNOWN


class Side(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    BOTH = "both"
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    REQUIRES = "requires"
    OPTIONAL = "optional"
    INCOMPATIBLE = "incompatible"
    EMBEDS = "embeds"          # jar-in-jar bundled dependency
    SUGGESTS = "suggests"
    PROVIDES = "provides"      # this mod provides an aliased/virtual id
    BREAKS = "breaks"          # runtime-breaks relationship


class Verdict(str, Enum):
    COMPATIBLE = "compatible"
    COMPATIBLE_WITH_WARNINGS = "compatible_with_warnings"
    NEEDS_REVIEW = "needs_review"
    LIKELY_INCOMPATIBLE = "likely_incompatible"
    INCOMPATIBLE = "incompatible"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ════════════════════════════════════════════════════════════════════ models
@dataclass
class Evidence:
    """A single observed signal, from a single source.

    Evidence never makes a decision on its own. The fusion engine combines all
    evidence for a given *claim* in log-odds space.
    """

    source: str                 # "jar" | "modrinth" | "curseforge" | "github" | "kb" | "filename"
    claim: str                  # e.g. "side", "loader", "mc_version", "dependency"
    polarity: float             # -1..+1  (contradicts .. supports compatibility)
    weight: float               # intrinsic strength of this signal (>= 0)
    trust: float                # source reliability 0..1
    detail: str                 # human-readable sentence
    freshness: float = 1.0      # 0..1 recency (immutable facts = 1.0)
    url: Optional[str] = None

    @property
    def effective(self) -> float:
        """Signed contribution to the log-odds sum."""
        return self.weight * self.trust * self.freshness * self.polarity

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "claim": self.claim,
            "polarity": round(self.polarity, 3),
            "weight": round(self.weight, 3),
            "trust": round(self.trust, 3),
            "freshness": round(self.freshness, 3),
            "effective": round(self.effective, 3),
            "detail": self.detail,
            "url": self.url,
        }


@dataclass
class Dependency:
    """A typed, version-aware edge declaration extracted from metadata."""

    target_id: str
    type: EdgeType
    range: "VersionRange | None" = None
    side: Side = Side.BOTH
    source: str = "jar"

    @property
    def mandatory(self) -> bool:
        return self.type in (EdgeType.REQUIRES,)

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "type": self.type.value,
            "range": self.range.raw if self.range is not None else None,
            "side": self.side.value,
            "source": self.source,
        }


@dataclass
class CanonicalMod:
    """Normalized, deduplicated identity of a mod file."""

    canonical_id: str
    name: str
    filename: str
    path: str = ""              # absolute path on disk (not serialized)
    sha512: str = ""
    version: "ComparableVersion | None" = None
    version_raw: str = ""
    loaders: frozenset[Loader] = field(default_factory=frozenset)
    mc_ranges: tuple = ()                      # tuple[VersionRange, ...]
    declared_side: Side = Side.UNKNOWN
    mod_ids: frozenset[str] = field(default_factory=frozenset)
    provider_ids: dict = field(default_factory=dict)  # {"modrinth": "...", "curseforge": 123}
    dependencies: list[Dependency] = field(default_factory=list)
    provides: frozenset[str] = field(default_factory=frozenset)
    embedded: tuple = ()                        # tuple[CanonicalMod, ...] (jar-in-jar)
    mixin_targets: frozenset[str] = field(default_factory=frozenset)
    access_transformers: frozenset[str] = field(default_factory=frozenset)
    file_size: int = 0

    def to_dict(self) -> dict:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "filename": self.filename,
            "sha512": self.sha512,
            "version": self.version_raw or (str(self.version) if self.version else None),
            "loaders": sorted(l.value for l in self.loaders),
            "mc_ranges": [r.raw for r in self.mc_ranges],
            "declared_side": self.declared_side.value,
            "mod_ids": sorted(self.mod_ids),
            "provider_ids": self.provider_ids,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "provides": sorted(self.provides),
            "embedded": [e.canonical_id for e in self.embedded],
            "file_size": self.file_size,
        }


@dataclass
class Axis:
    """One independent compatibility dimension with its own fused score."""

    name: str                    # loader | mc_version | dependencies | side | conflicts
    score: float = 50.0          # 0..100 (50 = neutral / unknown)
    confidence: float = 0.0      # 0..1 certainty in this axis
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 3),
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class Conflict:
    """A detected conflict between two mods (or a mod and the pack)."""

    kind: str                    # mod_id_collision | duplicate | mixin | namespace | known_pair | loader | access_transformer
    mod_a: str
    mod_b: str
    severity: Severity
    detail: str
    fix: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "mod_a": self.mod_a,
            "mod_b": self.mod_b,
            "severity": self.severity.value,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass
class ModVerdict:
    """The graded, explainable conclusion for a single mod."""

    mod: CanonicalMod
    verdict: Verdict = Verdict.NEEDS_REVIEW
    confidence: float = 0.0       # 0..1 certainty in the verdict
    compat_score: float = 50.0    # 0..100 degree of compatibility
    side: Side = Side.UNKNOWN
    side_confidence: float = 0.0
    axes: list[Axis] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    unresolved: list[Dependency] = field(default_factory=list)

    # Convenience flag for backward-compatibility with the old boolean API.
    @property
    def is_client_only(self) -> bool:
        return self.side == Side.CLIENT and self.side_confidence >= 0.6

    def axis(self, name: str) -> Optional[Axis]:
        return next((a for a in self.axes if a.name == name), None)

    def to_dict(self) -> dict:
        return {
            "mod": self.mod.to_dict(),
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 3),
            "compat_score": round(self.compat_score, 1),
            "side": self.side.value,
            "side_confidence": round(self.side_confidence, 3),
            "is_client_only": self.is_client_only,
            "axes": [a.to_dict() for a in self.axes],
            "reasons": self.reasons,
            "alternatives": self.alternatives,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "unresolved": [d.to_dict() for d in self.unresolved],
        }


@dataclass
class PackReport:
    """The result of analyzing an entire pack."""

    loader: Optional[str] = None
    mc_version: Optional[str] = None
    verdicts: list[ModVerdict] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    missing_dependencies: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "loader": self.loader,
            "mc_version": self.mc_version,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "missing_dependencies": self.missing_dependencies,
            "warnings": self.warnings,
            "stats": self.stats,
        }
