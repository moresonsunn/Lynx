"""Robust ``mods.toml`` / ``neoforge.mods.toml`` parsing compatible with Python 3.10+.

Forge/NeoForge metadata is valid TOML, so we parse it with ``tomllib`` (Python 3.11+)
or ``tomli`` (Python 3.10) when available, and fall back to a comment-aware structural
parser that understands ``[[mods]]``, ``[[mixins]]``, and ``[[dependencies.<modid>]]``.
"""

from __future__ import annotations

import re
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


def parse_mods_toml(content: str) -> dict[str, Any]:
    """Parse mods.toml content into a normalized dict."""
    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            if isinstance(data, dict) and (
                "mods" in data or "dependencies" in data or "modLoader" in data
            ):
                return _normalize(data)
        except Exception:
            pass
    return _lenient_parse(content)


def _normalize(data: dict) -> dict:
    mods = data.get("mods") or []
    if isinstance(mods, dict):
        mods = [mods]
    deps = data.get("dependencies") or {}
    norm_deps: dict[str, list] = {}
    if isinstance(deps, dict):
        for owner, lst in deps.items():
            if isinstance(lst, dict):
                lst = [lst]
            if isinstance(lst, list):
                norm_deps[str(owner).lower()] = lst
    return {
        "modLoader": data.get("modLoader"),
        "loaderVersion": data.get("loaderVersion"),
        "clientSideOnly": data.get("clientSideOnly"),
        "displayTest": data.get("displayTest"),
        "mods": mods,
        "mixins": data.get("mixins") or [],
        "dependencies": norm_deps,
    }


_TABLE_RE = re.compile(r"^\s*\[\[([^\]]+)\]\]\s*$")
_KV_RE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=\s*(.+?)\s*$")


def _coerce(value: str) -> Any:
    v = value.strip()
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v.strip('"').strip("'")


def _lenient_parse(content: str) -> dict:
    result: dict[str, Any] = {
        "modLoader": None,
        "loaderVersion": None,
        "clientSideOnly": None,
        "displayTest": None,
        "mods": [],
        "mixins": [],
        "dependencies": {},
    }
    current: dict | None = None
    in_multiline = False
    multiline_delim = '"""'

    for raw_line in content.splitlines():
        if in_multiline:
            if multiline_delim in raw_line:
                in_multiline = False
            continue

        # Check if a multiline string starts on this line and doesn't close on this line
        for delim in ('"""', "'''"):
            if raw_line.count(delim) == 1:
                in_multiline = True
                multiline_delim = delim
                raw_line = raw_line.split(delim, 1)[0]
                break

        line = raw_line.split("#", 1)[0]
        if not line.strip():
            continue

        m = _TABLE_RE.match(line)
        if m:
            header = m.group(1).strip().lower()
            if header == "mods":
                current = {}
                result["mods"].append(current)
            elif header == "mixins":
                current = {}
                result["mixins"].append(current)
            elif header.startswith("dependencies."):
                owner = header.split(".", 1)[1].strip().strip("\"'")
                current = {}
                result["dependencies"].setdefault(owner, []).append(current)
            else:
                current = None
            continue

        kv = _KV_RE.match(line)
        if not kv:
            continue
        key, value = kv.group(1), _coerce(kv.group(2))
        if current is not None:
            current[key] = value
        else:
            if key in ("modLoader", "loaderVersion", "clientSideOnly", "displayTest"):
                result[key] = value

    return result
