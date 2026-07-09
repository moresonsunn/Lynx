"""Comparable version type.

``ComparableVersion`` parses a version string into a canonical, orderable
representation that understands numeric release components and pre-release
qualifiers (snapshot/alpha/beta/rc), so that::

    1.0.0-rc1  <  1.0.0  <  1.0.1-alpha  <  1.0.1

The parser is deliberately lenient: it never raises on malformed input, it just
does its best. This matters because mod version strings are wildly inconsistent
(``mc1.20.1-1.2.3``, ``0.6.1a``, ``2.6.15+build.4`` ...).
"""

from __future__ import annotations

import re
from functools import total_ordering

# Rank of trailing qualifiers relative to a plain release (rank 0).
# Lower rank sorts earlier (i.e. is "less than").
_QUALIFIER_RANK: dict[str, int] = {
    "snapshot": -6,
    "nightly": -6,
    "dev": -5,
    "exp": -5,
    "experimental": -5,
    "alpha": -4,
    "a": -4,
    "beta": -3,
    "b": -3,
    "m": -3,          # milestone
    "milestone": -3,
    "pre": -2,
    "prerelease": -2,
    "preview": -2,
    "rc": -1,
    "cr": -1,
    "candidate": -1,
    # release-equivalent qualifiers
    "": 0,
    "final": 0,
    "release": 0,
    "stable": 0,
    "ga": 0,
    # post-release
    "sp": 1,
    "patch": 1,
    "hotfix": 1,
}

# Minecraft snapshot pattern e.g. 23w14a, 1.20-pre1, 24w45a
_MC_SNAPSHOT_RE = re.compile(r"^(\d{2})w(\d{2})([a-z])$")

# Leading numeric-dotted release, then an optional remainder.
_RELEASE_RE = re.compile(r"^[^\d]*?(\d+(?:\.\d+)*)(.*)$")


def _coerce_int(tok: str) -> int:
    try:
        return int(tok)
    except (TypeError, ValueError):
        return 0


@total_ordering
class ComparableVersion:
    """An orderable version.

    Attributes:
        raw: the original string.
        release: tuple of ints (the numeric part).
        qual_rank: qualifier rank (see :data:`_QUALIFIER_RANK`).
        qual_num: numeric suffix of the qualifier (rc *1*, beta.*2*).
        local: leftover metadata string used only as a final tiebreaker.
        is_snapshot: True for Minecraft weekly snapshots (23w14a style).
    """

    __slots__ = ("raw", "release", "qual_rank", "qual_num", "local", "is_snapshot")

    def __init__(self, raw: str):
        self.raw = (raw or "").strip()
        self.release: tuple[int, ...] = (0,)
        self.qual_rank: int = 0
        self.qual_num: int = 0
        self.local: str = ""
        self.is_snapshot: bool = False
        self._parse(self.raw)

    # ------------------------------------------------------------------ parse
    def _parse(self, s: str) -> None:
        if not s:
            self.release = (0,)
            return

        low = s.strip().lower()

        # Minecraft weekly snapshot: sorts *below* any numbered release, but we
        # still give it an approximate ordering by (year, week).
        m = _MC_SNAPSHOT_RE.match(low)
        if m:
            year, week, rev = int(m.group(1)), int(m.group(2)), m.group(3)
            self.is_snapshot = True
            # A leading -1 sentinel makes snapshots sort *below* any numbered
            # release (which start at 0/1). Snapshots order among themselves by
            # (year, week, revision). Exact snapshot<->release mapping is a known
            # limitation; treating snapshots as pre-release is the safe default.
            self.release = (-1, year, week)
            self.qual_rank = -6
            self.qual_num = ord(rev) - ord("a") + 1
            self.local = low
            return

        # Strip a leading "v" or "mc" prefix ("v1.2.3", "mc1.20.1").
        low = re.sub(r"^(v|mc)(?=\d)", "", low)

        m = _RELEASE_RE.match(low)
        if not m:
            # No numeric component at all — treat the whole thing as a qualifier.
            self.release = (0,)
            self._parse_qualifier(low)
            return

        core, remainder = m.group(1), m.group(2)
        self.release = tuple(_coerce_int(p) for p in core.split(".")) or (0,)
        self._parse_qualifier(remainder)

    def _parse_qualifier(self, remainder: str) -> None:
        remainder = remainder.strip()
        # drop build metadata (semver "+...") — not significant for ordering
        remainder = remainder.split("+", 1)[0]
        remainder = remainder.strip(" .-_")
        if not remainder:
            self.qual_rank = 0
            return

        # Tokens: alphabetic and numeric runs.
        tokens = re.findall(r"[a-z]+|\d+", remainder.lower())
        if not tokens:
            self.qual_rank = 0
            self.local = remainder.lower()
            return

        # First alphabetic token decides the qualifier class.
        alpha = next((t for t in tokens if t.isalpha()), "")
        if alpha in _QUALIFIER_RANK:
            self.qual_rank = _QUALIFIER_RANK[alpha]
        elif alpha:
            # Unknown alphabetic suffix (e.g. loader tag "fabric"): treat as
            # release-equivalent metadata so it does not falsely sort below a
            # plain release.
            self.qual_rank = 0
        # First numeric token after the qualifier is the qualifier number.
        num = next((t for t in tokens if t.isdigit()), "")
        self.qual_num = _coerce_int(num) if num else 0
        self.local = remainder.lower()

    # -------------------------------------------------------------- comparison
    def _key(self) -> tuple:
        return (self.release, self.qual_rank, self.qual_num)

    @staticmethod
    def _padded(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple, tuple]:
        n = max(len(a), len(b))
        return (a + (0,) * (n - len(a)), b + (0,) * (n - len(b)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ComparableVersion):
            return NotImplemented
        ra, rb = self._padded(self.release, other.release)
        return (ra, self.qual_rank, self.qual_num) == (rb, other.qual_rank, other.qual_num)

    def __lt__(self, other: "ComparableVersion") -> bool:
        if not isinstance(other, ComparableVersion):
            return NotImplemented
        ra, rb = self._padded(self.release, other.release)
        if ra != rb:
            return ra < rb
        if self.qual_rank != other.qual_rank:
            return self.qual_rank < other.qual_rank
        return self.qual_num < other.qual_num

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:
        return f"ComparableVersion({self.raw!r})"

    def __str__(self) -> str:
        return self.raw


def parse_version(raw: str | None) -> ComparableVersion | None:
    """Parse ``raw`` into a :class:`ComparableVersion`, or ``None`` if empty."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    return ComparableVersion(raw)
