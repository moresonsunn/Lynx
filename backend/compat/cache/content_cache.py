"""Content-addressed cache for immutable jar extraction results."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..models import CanonicalMod


class ContentCache:
    """In-memory, thread-safe SHA-512 -> CanonicalMod cache.

    Jar files are immutable for a given hash, so entries never expire. This makes
    re-scans of an unchanged pack effectively free (incremental scanning).
    """

    def __init__(self) -> None:
        self._data: dict[str, "CanonicalMod"] = {}
        self._lock = threading.Lock()

    def get(self, sha512: str) -> Optional["CanonicalMod"]:
        if not sha512:
            return None
        with self._lock:
            return self._data.get(sha512)

    def put(self, sha512: str, mod: "CanonicalMod") -> None:
        if not sha512:
            return
        with self._lock:
            self._data[sha512] = mod

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


@lru_cache(maxsize=1)
def get_content_cache() -> ContentCache:
    return ContentCache()
