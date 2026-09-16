from pathlib import Path
import os
import re
from fastapi import HTTPException

# Container-visible servers directory (bind-mounted from host or a named volume)
SERVERS_ROOT = Path(os.environ.get("SERVERS_CONTAINER_ROOT", "/data/servers"))

# Be resilient: if creating the default path fails (e.g., running locally without permissions
# to create /data), fall back to a workspace-local directory.
try:
	SERVERS_ROOT.mkdir(parents=True, exist_ok=True)
except Exception as e:
	try:
		fallback = Path(os.environ.get("SERVERS_FALLBACK_ROOT", str(Path.cwd() / "servers_data")))
		fallback.mkdir(parents=True, exist_ok=True)
		print(f"WARN: Could not create {SERVERS_ROOT} ({e}); falling back to {fallback}")
		SERVERS_ROOT = fallback
	except Exception as e2:
		# Last resort: don't crash import, just leave as-is and hope downstream creates lazily
		print(f"ERROR: Failed to create servers root at {SERVERS_ROOT} and fallback: {e2}")

# Optional: absolute host path to servers directory for bind mounting into runtime containers
SERVERS_HOST_ROOT = os.environ.get("SERVERS_HOST_ROOT", "")
# In dev/local runs (no container), default host root to SERVERS_ROOT when unset
try:
	if not SERVERS_HOST_ROOT:
		# If SERVERS_ROOT is not the conventional container path, assume host path
		if str(SERVERS_ROOT) != "/data/servers":
			SERVERS_HOST_ROOT = str(SERVERS_ROOT)
except Exception:
	pass

# Named volume to share server data between controller and runtime containers
SERVERS_VOLUME_NAME = os.environ.get("SERVERS_VOLUME_NAME", "minecraft-server_mc_servers_data")

# Branding / application identity
APP_NAME = os.environ.get("APP_NAME", "Lynx")
APP_VERSION = os.environ.get("APP_VERSION", "dev")


def normalize_server_name(name: str) -> str:
    """Normalize server name for filesystem safety."""
    return re.sub(r'[^a-zA-Z0-9 \-_.]', '', name).strip()


def get_server_dir(server_name: str) -> Path:
    """Get validated server directory path."""
    normalized = normalize_server_name(server_name)
    server_dir = (SERVERS_ROOT / normalized).resolve()
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")
    return server_dir


def resolve_server_dir(server_name: str) -> Path | None:
    """Best-effort server directory without raising (exact, then case-insensitive)."""
    try:
        p = (SERVERS_ROOT / server_name)
        if p.is_dir():
            return p
        if SERVERS_ROOT.is_dir():
            needle = server_name.lower()
            for child in SERVERS_ROOT.iterdir():
                try:
                    if child.is_dir() and child.name.lower() == needle:
                        return child
                except Exception:
                    continue
    except Exception:
        pass
    return None


# NeoForge loader prefix (major.minor) -> Minecraft version. Fallback when only
# the installer jar (which carries no MC version) is present.
_NEOFORGE_MC_MAP = {
    "20.2": "1.20.2", "20.3": "1.20.3", "20.4": "1.20.4",
    "20.5": "1.20.5", "20.6": "1.20.6",
    "21.0": "1.21", "21.1": "1.21.1",
}

_MISSING = (None, "", "unknown", "custom")


def _detect_from_jars(server_dir: Path) -> dict:
    """Detect type/version/loader from server jar filenames (no logs needed)."""
    out: dict = {}
    try:
        jars = [p.name for p in server_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".jar"]
    except Exception:
        return out
    if not jars:
        return out
    lower = {j: j.lower() for j in jars}

    def _set(t=None, v=None, l=None):
        if t and not out.get("server_type"):
            out["server_type"] = t
        if v and not out.get("server_version"):
            out["server_version"] = v
        if l and not out.get("loader_version"):
            out["loader_version"] = l

    for j, lj in lower.items():
        m = re.match(r"^paper-(\d+\.\d+(?:\.\d+)?)-(\d+)\.jar$", lj)
        if m:
            _set("paper", m.group(1));
            continue
        m = re.match(r"^purpur-(\d+\.\d+(?:\.\d+)?)-(\d+)\.jar$", lj)
        if m:
            _set("purpur", m.group(1));
            continue
        m = re.match(r"^spigot-(\d+\.\d+(?:\.\d+)?).*\.jar$", lj)
        if m:
            _set("spigot", m.group(1));
            continue
        if "craftbukkit" in lj:
            m2 = re.search(r"(\d+\.\d+(?:\.\d+)?)", lj)
            _set("craftbukkit", m2.group(1) if m2 else None);
            continue
        if lj == "fabric-server-launch.jar":
            _set("fabric");
            continue
        m = re.match(r"^(?:minecraft)?forge(?:-universal)?-(\d+\.\d+\.\d+)-(.+)\.jar$", lj)
        if m:
            _set("forge", m.group(1), m.group(2).replace("-installer", ""));
            continue
        m = re.match(r"^neoforge-([\d.]+)-installer\.jar$", lj)
        if m:
            loader = m.group(1)
            parts = loader.split(".")
            mc = _NEOFORGE_MC_MAP.get(".".join(parts[:2])) if len(parts) >= 2 else None
            _set("neoforge", mc, loader);
            continue
        m = re.match(r"^mohist-(\d+\.\d+(?:\.\d+)?)-.*\.jar$", lj)
        if m:
            _set("mohist", m.group(1));
            continue
        if "magma" in lj and lj.endswith(".jar"):
            m2 = re.search(r"(\d+\.\d+(?:\.\d+)?)", lj)
            _set("magma", m2.group(1) if m2 else None);
            continue
        if "banner" in lj and lj.endswith(".jar"):
            m2 = re.search(r"(\d+\.\d+(?:\.\d+)?)", lj)
            _set("banner", m2.group(1) if m2 else None);
            continue
        if "catserver" in lj:
            m2 = re.search(r"(\d+\.\d+(?:\.\d+)?)", lj)
            _set("catserver", m2.group(1) if m2 else None);
            continue
        if "spongeforge" in lj:
            m2 = re.search(r"(\d+\.\d+(?:\.\d+)?)", lj)
            _set("spongeforge", m2.group(1) if m2 else None);
            continue
        m = re.match(r"^velocity-(.+)\.jar$", lj)
        if m:
            _set("velocity", m.group(1));
            continue
        if lj == "bungeecord.jar":
            _set("bungeecord");
            continue
        m = re.match(r"^waterfall-(.+)\.jar$", lj)
        if m:
            _set("waterfall", m.group(1));
            continue
    return out


def _detect_from_startup_log(server_dir: Path) -> dict:
    """Scan the HEAD of logs/latest.log for boot banners.

    The head (not tail) is used because version banners print once at startup
    and scroll out of `tail` within minutes on busy servers — the old tail-only
    scan is why detection "never" worked.
    """
    out: dict = {}
    try:
        log_path = server_dir / "logs" / "latest.log"
        if not log_path.is_file():
            return out
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(150 * 1024)
        lines = head.splitlines()[:600]
        text = "\n".join(lines)

        def _set(t=None, v=None, l=None, j=None):
            if t and not out.get("server_type"):
                out["server_type"] = t
            if v and not out.get("server_version"):
                out["server_version"] = v
            if l and not out.get("loader_version"):
                out["loader_version"] = l
            if j and not out.get("java_version"):
                out["java_version"] = j

        m = re.search(r"Starting minecraft server version\s+(\S+)", text, re.IGNORECASE)
        if m:
            _set(v=m.group(1))
        m = re.search(r"\(MC:\s*([^)]+)\)", text)
        if m:
            _set(v=m.group(1).strip())
        if re.search(r"MinecraftForge|Forge mod loading|\bFML\b", text, re.IGNORECASE):
            _set("forge")
            fm = re.search(r"(?:MinecraftForge|Forge mod loading)[^\d]*v?(\d[\d.]+)", text)
            if fm:
                _set(l=fm.group(1))
        elif re.search(r"NeoForge", text, re.IGNORECASE):
            _set("neoforge")
            nm = re.search(r"NeoForge[^\d]*v?(\d[\d.]+)", text)
            if nm:
                _set(l=nm.group(1))
        elif re.search(r"\[fabric", text, re.IGNORECASE):
            _set("fabric")
            fm2 = re.search(r"fabricloader[^\d]*(\d[\d.]+)", text, re.IGNORECASE)
            if fm2:
                _set(l=fm2.group(1))
        elif re.search(r"Paper|Purpur|Spigot|CraftBukkit|Bukkit", text, re.IGNORECASE):
            for name in ("purpur", "paper", "spigot", "craftbukkit"):
                if re.search(name, text, re.IGNORECASE):
                    _set(name)
                    break
        jm = re.search(r"Running Java\s+(\d+)", text)
        if jm:
            _set(j=jm.group(1))
    except Exception:
        pass
    return out


def detect_server_from_files(server_dir: Path) -> dict:
    """Detect type/version/loader/java from files on the shared volume.

    Priority: server_meta.json > jar filenames > logs/latest.log head.
    Returns {server_type, server_version, loader_version, java_version}
    with None for anything undetectable.
    """
    merged: dict = {"server_type": None, "server_version": None,
                    "loader_version": None, "java_version": None}
    try:
        meta_path = server_dir / "server_meta.json"
        if meta_path.is_file():
            try:
                import json as _json
                meta = _json.loads(meta_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                if isinstance(meta, dict):
                    merged["server_version"] = (
                        meta.get("server_version") or meta.get("detected_version")
                        or meta.get("version") or meta.get("mc_version") or None)
                    merged["server_type"] = (
                        meta.get("server_type") or meta.get("type") or meta.get("loader")
                        or meta.get("detected_type") or None)
                    merged["loader_version"] = (
                        meta.get("loader_version") or meta.get("detected_loader_version") or None)
                    merged["java_version"] = meta.get("java_version") or None
            except Exception:
                pass

        for source in (_detect_from_jars(server_dir), _detect_from_startup_log(server_dir)):
            for key in ("server_type", "server_version", "loader_version", "java_version"):
                if not merged.get(key) and source.get(key):
                    merged[key] = source[key]

        # Lone server.jar with no mods/plugins hints at vanilla (Mojang ships
        # exactly one jar; every other loader keeps a distinct filename).
        if not merged.get("server_type"):
            try:
                names = [p.name.lower() for p in server_dir.iterdir() if p.is_file()]
                if names == ["server.jar", "eula.txt"] or (
                        "server.jar" in names and not (server_dir / "mods").exists()
                        and not (server_dir / "plugins").exists()):
                    merged["server_type"] = "vanilla"
            except Exception:
                pass
        if isinstance(merged.get("server_type"), str) and merged["server_type"].lower() == "custom":
            merged["server_type"] = None
    except Exception:
        pass
    return merged


_lan_ip_cache: dict = {"ts": 0.0, "ip": None}


def get_lan_ip() -> str | None:
    """Host LAN IP players on the local network should connect to.

    Env override LYNX_HOST_IP wins; otherwise derived via a UDP socket
    (connect() sends no traffic). Cached for 5 minutes.
    """
    import time as _time
    override = (os.environ.get("LYNX_HOST_IP") or "").strip()
    if override:
        return override
    try:
        now = _time.monotonic()
        if _lan_ip_cache["ip"] and now - _lan_ip_cache["ts"] < 300:
            return _lan_ip_cache["ip"]
        import socket as _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            try:
                s.close()
            except Exception:
                pass
        if ip and not ip.startswith("127."):
            _lan_ip_cache.update(ts=now, ip=ip)
            return ip
    except Exception:
        pass
    return None