"""TTL cache for remote source responses, optionally persisted to SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 6 * 3600  # 6 hours


class ApiCache:
    """A small TTL cache. Falls back to memory-only if SQLite is unavailable."""

    def __init__(self, db_path: Optional[str] = None, ttl: int = _DEFAULT_TTL):
        self.ttl = ttl
        self._mem: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        if db_path:
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(db_path, check_same_thread=False)
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS api_cache ("
                    "cache_key TEXT PRIMARY KEY, payload TEXT, fetched_at REAL)"
                )
                self._conn.commit()
            except Exception as e:  # pragma: no cover - environment dependent
                logger.debug("ApiCache SQLite disabled: %s", e)
                self._conn = None

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            hit = self._mem.get(key)
            if hit and now - hit[0] <= self.ttl:
                return hit[1]
            if self._conn is not None:
                try:
                    row = self._conn.execute(
                        "SELECT payload, fetched_at FROM api_cache WHERE cache_key=?",
                        (key,),
                    ).fetchone()
                    if row and now - row[1] <= self.ttl:
                        value = json.loads(row[0])
                        self._mem[key] = (row[1], value)
                        return value
                except Exception:
                    pass
        return None

    def put(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            self._mem[key] = (now, value)
            if self._conn is not None:
                try:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)",
                        (key, json.dumps(value), now),
                    )
                    self._conn.commit()
                except Exception:
                    pass


@lru_cache(maxsize=1)
def get_api_cache() -> ApiCache:
    import os
    db = os.environ.get("COMPAT_CACHE_DB", "")
    return ApiCache(db_path=db or None)
