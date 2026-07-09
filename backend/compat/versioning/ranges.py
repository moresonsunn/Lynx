"""Version ranges.

A :class:`VersionRange` is internally a *union of intervals*. Each interval is
``(low, low_inclusive, high, high_inclusive)`` where ``low``/``high`` are
:class:`ComparableVersion` or ``None`` (unbounded).

Membership and overlap tests return ``bool`` when the answer is known, or
``None`` when the range could not be parsed — callers must treat ``None`` as a
*neutral* signal, never as "incompatible".
"""

from __future__ import annotations

import re
from typing import Optional

from .version import ComparableVersion, parse_version

# An interval is a 4-tuple: (low, low_incl, high, high_incl)
Interval = tuple[Optional[ComparableVersion], bool, Optional[ComparableVersion], bool]


class VersionRange:
    """A union of version intervals."""

    __slots__ = ("raw", "intervals", "unknown", "unbounded")

    def __init__(self, raw: str, intervals: list[Interval] | None = None,
                 *, unknown: bool = False, unbounded: bool = False):
        self.raw = raw
        self.intervals: list[Interval] = intervals or []
        self.unknown = unknown
        self.unbounded = unbounded

    # ---------------------------------------------------------------- queries
    def contains(self, version: ComparableVersion | str | None) -> Optional[bool]:
        """Return whether ``version`` falls in the range.

        ``None`` means "cannot decide" (unknown range or unknown version).
        """
        if self.unknown:
            return None
        if self.unbounded:
            return True
        v = version if isinstance(version, ComparableVersion) else parse_version(version)
        if v is None:
            return None
        for low, low_incl, high, high_incl in self.intervals:
            if low is not None:
                if v < low or (v == low and not low_incl):
                    continue
            if high is not None:
                if v > high or (v == high and not high_incl):
                    continue
            return True
        return False

    def overlaps(self, other: "VersionRange") -> Optional[bool]:
        """Return whether two ranges share at least one version."""
        if self.unknown or other.unknown:
            return None
        if self.unbounded or other.unbounded:
            return True
        for a in self.intervals:
            for b in other.intervals:
                if _intervals_overlap(a, b):
                    return True
        return False

    def is_exact(self) -> bool:
        return (
            len(self.intervals) == 1
            and self.intervals[0][0] is not None
            and self.intervals[0][0] == self.intervals[0][2]
        )

    def __repr__(self) -> str:
        return f"VersionRange({self.raw!r})"


def _intervals_overlap(a: Interval, b: Interval) -> bool:
    a_low, a_low_i, a_high, a_high_i = a
    b_low, b_low_i, b_high, b_high_i = b
    # a must not end before b starts
    if a_high is not None and b_low is not None:
        if a_high < b_low or (a_high == b_low and not (a_high_i and b_low_i)):
            return False
    if b_high is not None and a_low is not None:
        if b_high < a_low or (b_high == a_low and not (b_high_i and a_low_i)):
            return False
    return True


# A range that matches everything.
def _unbounded(raw: str = "*") -> VersionRange:
    return VersionRange(raw, [(None, True, None, True)], unbounded=True)


UNKNOWN = VersionRange("<unknown>", [], unknown=True)


# --------------------------------------------------------------------- parsing
_MAVEN_GROUP_RE = re.compile(r"[\[\(][^\[\]\(\)]*[\]\)]")
_COMPARATOR_RE = re.compile(r"^(>=|<=|>|<|=|==|\^|~|!=)?\s*(.+)$")


def parse_range(raw: str | None, *, bare_is_minimum: bool = False) -> VersionRange:
    """Parse a version range string.

    Args:
        raw: the range expression.
        bare_is_minimum: when True, a bare version (``"1.20.1"``) is treated as
            ``>=1.20.1`` instead of an exact match. Forge/NeoForge dependency
            ranges without brackets use minimum semantics; Fabric ``depends``
            on an exact version uses exact semantics.
    """
    if raw is None:
        return UNKNOWN
    s = str(raw).strip()
    if not s or s in ("*", "x", "any", "*.*", "*.*.*"):
        return _unbounded(s or "*")

    try:
        if "[" in s or "(" in s:
            intervals = _parse_maven(s)
            if intervals:
                return VersionRange(s, intervals)
            return UNKNOWN

        interval = _parse_comparators(s, bare_is_minimum=bare_is_minimum)
        if interval is None:
            return UNKNOWN
        return VersionRange(s, [interval])
    except Exception:
        return UNKNOWN


def _parse_maven(s: str) -> list[Interval]:
    intervals: list[Interval] = []
    for group in _MAVEN_GROUP_RE.findall(s):
        low_incl = group[0] == "["
        high_incl = group[-1] == "]"
        body = group[1:-1].strip()
        if "," not in body:
            # single value: [1.0] means exactly 1.0
            v = parse_version(body)
            if v is None:
                continue
            intervals.append((v, True, v, True))
            continue
        low_s, high_s = (part.strip() for part in body.split(",", 1))
        low = parse_version(low_s) if low_s else None
        high = parse_version(high_s) if high_s else None
        intervals.append((low, low_incl if low else True, high, high_incl if high else True))
    return intervals


def _parse_comparators(s: str, *, bare_is_minimum: bool) -> Optional[Interval]:
    """Parse a whitespace/comma separated comparator list into a single interval.

    Multiple comparators are AND-ed (``>=1.0 <2.0``).
    """
    tokens = [t for t in re.split(r"[\s,]+", s.strip()) if t]
    low: Optional[ComparableVersion] = None
    low_incl = True
    high: Optional[ComparableVersion] = None
    high_incl = True
    matched = False

    for tok in tokens:
        m = _COMPARATOR_RE.match(tok)
        if not m:
            continue
        op, ver_s = m.group(1) or "", m.group(2).strip()

        # Wildcards like 1.20.x / 1.20.*
        if op in ("", "=", "==") and re.search(r"[.\-](x|\*)$", ver_s):
            base = re.sub(r"[.\-](x|\*)$", "", ver_s)
            lo = parse_version(base)
            if lo is None:
                continue
            hi = _bump_last(lo)
            low, low_incl = _max_low(low, low_incl, lo, True)
            high, high_incl = _min_high(high, high_incl, hi, False)
            matched = True
            continue

        # A usable version token must contain at least one digit; otherwise this
        # is junk (e.g. "any-old-string") and the whole range is unparseable.
        if not re.search(r"\d", ver_s):
            continue

        ver = parse_version(ver_s)
        if ver is None:
            continue
        matched = True

        if op in (">=",):
            low, low_incl = _max_low(low, low_incl, ver, True)
        elif op == ">":
            low, low_incl = _max_low(low, low_incl, ver, False)
        elif op == "<=":
            high, high_incl = _min_high(high, high_incl, ver, True)
        elif op == "<":
            high, high_incl = _min_high(high, high_incl, ver, False)
        elif op == "^":
            # caret: >=ver <next-major
            low, low_incl = _max_low(low, low_incl, ver, True)
            high, high_incl = _min_high(high, high_incl, _next_major(ver), False)
        elif op == "~":
            # tilde: >=ver <next-minor
            low, low_incl = _max_low(low, low_incl, ver, True)
            high, high_incl = _min_high(high, high_incl, _next_minor(ver), False)
        elif op == "!=":
            # Not directly representable as a single interval; approximate as
            # unbounded (neutral) to avoid false negatives.
            return (None, True, None, True)
        else:  # bare version
            if bare_is_minimum:
                low, low_incl = _max_low(low, low_incl, ver, True)
            else:
                # exact match
                low, low_incl = _max_low(low, low_incl, ver, True)
                high, high_incl = _min_high(high, high_incl, ver, True)

    if not matched:
        return None
    return (low, low_incl, high, high_incl)


def _max_low(cur, cur_incl, cand, cand_incl):
    if cur is None or cand > cur or (cand == cur and not cand_incl):
        return cand, cand_incl
    return cur, cur_incl


def _min_high(cur, cur_incl, cand, cand_incl):
    if cur is None or cand < cur or (cand == cur and not cand_incl):
        return cand, cand_incl
    return cur, cur_incl


def _bump_last(v: ComparableVersion) -> ComparableVersion:
    rel = list(v.release)
    rel[-1] += 1
    return ComparableVersion(".".join(str(x) for x in rel))


def _next_major(v: ComparableVersion) -> ComparableVersion:
    rel = list(v.release)
    return ComparableVersion(str(rel[0] + 1) + ".0.0")


def _next_minor(v: ComparableVersion) -> ComparableVersion:
    rel = list(v.release) + [0, 0]
    return ComparableVersion(f"{rel[0]}.{rel[1] + 1}.0")
