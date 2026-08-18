"""Allowlist and user overrides for mod side detection.

Provides force_server/force_client lists and user override persistence.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path to allowlist and overrides files
ALLOWLIST_PATH = Path(__file__).parent / "allowlist.json"
OVERRIDES_PATH = Path(__file__).parent / "overrides.json"

# In-memory caches
_allowlist_cache: Optional[dict] = None
_overrides_cache: Optional[dict] = None
_cache_lock = threading.Lock()


def _load_json(path: Path) -> dict:
    """Load JSON file with error handling."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load {path}: {e}")
        return {}


def get_allowlist() -> dict:
    """Get the allowlist (force_server, force_client)."""
    global _allowlist_cache
    with _cache_lock:
        if _allowlist_cache is None:
            _allowlist_cache = _load_json(ALLOWLIST_PATH)
        return _allowlist_cache


def get_overrides() -> dict:
    """Get user overrides for mod side detection."""
    global _overrides_cache
    with _cache_lock:
        if _overrides_cache is None:
            data = _load_json(OVERRIDES_PATH)
            _overrides_cache = data.get("user_overrides", {})
        return _overrides_cache


def set_override(mod_id: str, side: str) -> bool:
    """Set a user override for a mod's side. side must be 'client', 'server', or 'both'."""
    global _overrides_cache
    side = side.lower().strip()
    if side not in ("client", "server", "both"):
        raise ValueError(f"Invalid side: {side}. Must be 'client', 'server', or 'both'")

    with _cache_lock:
        if _overrides_cache is None:
            get_overrides()  # initialize cache
        _overrides_cache[mod_id.lower()] = side
        _save_overrides()
    return True


def remove_override(mod_id: str) -> bool:
    """Remove a user override for a mod."""
    global _overrides_cache
    with _cache_lock:
        if _overrides_cache is None:
            get_overrides()
        if mod_id.lower() in _overrides_cache:
            del _overrides_cache[mod_id.lower()]
            _save_overrides()
            return True
    return False


def _save_overrides() -> None:
    """Save overrides to file."""
    try:
        data = {"user_overrides": _overrides_cache}
        with open(OVERRIDES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save overrides: {e}")


def check_force_side(mod_id: str, mod_name: str = "") -> Optional[str]:
    """
    Check if a mod is in the force_server or force_client list.
    Returns 'server', 'client', or None.
    """
    allowlist = get_allowlist()
    mod_id_lower = mod_id.lower()
    mod_name_lower = mod_name.lower()

    # Check canonical ID first
    if mod_id_lower in allowlist.get("force_server", []):
        return "server"
    if mod_id_lower in allowlist.get("force_client", []):
        return "client"

    # Check by name (partial match)
    for forced in allowlist.get("force_server", []):
        if forced in mod_id_lower or (mod_name_lower and forced in mod_name_lower):
            return "server"
    for forced in allowlist.get("force_client", []):
        if forced in mod_id_lower or (mod_name_lower and forced in mod_name_lower):
            return "client"

    return None


def check_user_override(mod_id: str) -> Optional[str]:
    """Check if there's a user override for this mod."""
    overrides = get_overrides()
    return overrides.get(mod_id.lower())


def get_effective_side(
    mod_id: str,
    mod_name: str,
    detected_side: str,
    detected_confidence: float
) -> tuple[str, str]:
    """
    Determine the effective side for a mod considering:
    1. User override (highest priority)
    2. Allowlist force_server/force_client
    3. Detected side (with confidence threshold)
    
    Returns: (effective_side, reason)
    """
    # 1. User override
    override = check_user_override(mod_id)
    if override:
        return override, "user_override"

    # 2. Allowlist
    forced = check_force_side(mod_id, mod_name)
    if forced:
        return forced, "allowlist"

    # 3. Detected side - only trust high confidence detections
    if detected_confidence >= 0.7:
        if detected_side == "CLIENT":
            return "client", "detected_high_conf"
        elif detected_side == "SERVER":
            return "server", "detected_high_conf"
        elif detected_side == "BOTH":
            return "both", "detected_high_conf"

    # 4. Default - unknown/needs review
    return "unknown", "insufficient_evidence"


__all__ = [
    "get_allowlist",
    "get_overrides",
    "set_override",
    "remove_override",
    "check_force_side",
    "check_user_override",
    "get_effective_side",
]