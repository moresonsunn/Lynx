"""Caching layer.

Two cache tiers:

* :class:`ContentCache` — keyed by the SHA-512 of a jar. Jar contents are
  immutable, so extraction results never need invalidation. In-memory for the
  process lifetime.
* :class:`ApiCache` — TTL cache for remote source responses (Modrinth /
  CurseForge / GitHub), optionally persisted to SQLite so restarts stay warm.
"""

from .content_cache import ContentCache, get_content_cache
from .api_cache import ApiCache, get_api_cache

__all__ = ["ContentCache", "get_content_cache", "ApiCache", "get_api_cache"]
