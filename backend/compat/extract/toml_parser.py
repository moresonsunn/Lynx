"""Robust ``mods.toml`` / ``neoforge.mods.toml`` parsing.

Forge/NeoForge metadata is valid TOML, so we parse it with the stdlib
``tomllib`` first. Because a small fraction of real-world files contain template
placeholders or minor syntax slips, we fall back to a lenient structural parser
that understands the specific shapes we care about:

* ``[[mods]]`` blocks
* ``[[dependencies.<modid>]]`` blocks

This replaces the previous ``line.split('=')`` approach which silently
mis-parsed multi-mod jars, version strings containing ``=`` and NeoForge files.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any


def parse_mods_toml(content: str) -> dict[str, Any]:
    """Parse mods.toml content into a normalized dict.

    Returns a dict with keys ``mods`` (list), ``dependencies`` (dict of lists),
    ``modLoader`` and ``loaderVersion``.
    """
    try:
        data = tomllib.loads(content)
        if isinstance(data, dict) and ("mods" in data or "dependencies" in data
                                       or "modLoader" in data):
            return _normalize(data)
    except Exception:
        pass
    return _lenient_parse(content)


def _normalize(data: dict) -> dict:
    mods = data.get("mods") or []
    if isinstance(mods, dict):
        mods = [mods]
    deps = data.get("dependencies") or {}
    # tomllib gives dependencies as {owner: [ {..}, {..} ]}
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
        "mods": mods,
        "dependencies": norm_deps,
    }


# ------------------------------------------------------------------- lenient
_TABLE_RE = re.compile(r"^\s*\[\[([^\]]+)\]\]\s*$")
_KV_RE = re.compile(r'^\s*([A-Za-z0-9_\-]+)\s*=\s*(.+?)\s*$')


def _coerce(value: str) -> Any:
    v = value.strip()
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    # triple quoted / multiline start — just strip quotes best-effort
    return v.strip('"').strip("'")


def _lenient_parse(content: str) -> dict:
    result: dict[str, Any] = {"modLoader": None, "loaderVersion": None,
                              "mods": [], "dependencies": {}}
    current: dict | None = None
    current_kind: str | None = None
    current_owner: str | None = None

    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0]  # strip comments (best effort)
        if not line.strip():
            continue

        m = _TABLE_RE.match(line)
        if m:
            header = m.group(1).strip().lower()
            if header == "mods":
                current = {}
                current_kind = "mods"
                result["mods"].append(current)
            elif header.startswith("dependencies."):
                owner = header.split(".", 1)[1]
                current = {}
                current_kind = "dependencies"
                current_owner = owner
                result["dependencies"].setdefault(owner, []).append(current)
            else:
                current = None
                current_kind = None
            continue

        kv = _KV_RE.match(line)
        if not kv:
            continue
        key, value = kv.group(1), _coerce(kv.group(2))
        if current is not None:
            current[key] = value
        else:
            # top-level key (modLoader / loaderVersion)
            if key in ("modLoader", "loaderVersion"):
                result[key] = value

    return result
