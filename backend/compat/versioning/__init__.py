"""Version algebra for Minecraft, mod loaders and mods.

Handles the range dialects seen in the wild:

* Maven ranges: ``[1.0,2.0)``, ``[1.0,)``, ``(,1.0]``, ``[1.0]``
* Comparator lists: ``>=1.0 <2.0``, ``>=1.0,<2.0``
* Semver operators: ``^1.2.3``, ``~1.2.3``
* Wildcards: ``1.20.x``, ``1.20.*``, ``*``
* Snapshots / pre-releases: ``1.0.0-rc1``, ``23w14a``, ``1.0.0-beta.2``

Anything unparseable becomes an :data:`UNKNOWN` range whose membership tests
return ``None`` (neutral) rather than ``False`` — the engine must never treat
"we could not parse this" as "incompatible".
"""

from .version import ComparableVersion, parse_version
from .ranges import VersionRange, UNKNOWN, parse_range

__all__ = [
    "ComparableVersion",
    "parse_version",
    "VersionRange",
    "parse_range",
    "UNKNOWN",
]
