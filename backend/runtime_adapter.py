import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
import re
import json
import threading
import time
import psutil

from local_runtime import LocalRuntimeManager, MINECRAFT_PORT
from config import (SERVERS_ROOT, detect_server_from_files, resolve_server_dir,
                     get_lan_ip, sanitize_player_names, online_from_log_lines,
                     read_log_tail_lines, safe_child_path)


_RAM_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGTP]?)(?:I?B)?\s*$", re.IGNORECASE)

# Host network baseline for local-runtime net accounting (module-level on
# purpose). The stats collector constructs a FRESH LocalAdapter every cycle
# (get_runtime_manager() has no cache), so an instance attribute reset on
# every sample and rates were stuck at 0.0 forever. Process-persistent base
# fixes it; a backend restart simply starts a new baseline (one zero sample).
_HOST_NET_BASE: Optional[Tuple[int, int]] = None
_HOST_NET_BASE_LOCK = threading.Lock()

# Non-blocking telemetry cache for instantaneous multi-core CPU and thread deltas
# Key: container_id -> {
#   "timestamp": float,
#   "proc_times": dict[int, float],
#   "thread_times": dict[int, tuple[float, float]],
#   "thread_names": dict[int, str]
# }
_TELEMETRY_CACHE: Dict[str, Dict[str, Any]] = {}
_TELEMETRY_CACHE_LOCK = threading.Lock()

# Adaptive TPS probe cache (5-second TTL per container)
_TPS_CACHE: Dict[str, Dict[str, Any]] = {}
_TPS_CACHE_LOCK = threading.Lock()


def _resolve_thread_name(pid: int, tid: int) -> str:
    """Resolve OS / JVM thread name via /proc on Linux or descriptive fallback."""
    try:
        comm_path = Path(f"/proc/{pid}/task/{tid}/comm")
        if comm_path.exists():
            name = comm_path.read_text(encoding="utf-8", errors="replace").strip()
            if name:
                return name
    except Exception:
        pass
    if tid == pid:
        return "Server thread"
    return f"Worker-{tid}"


def _probe_server_tps(server_name: str, server_dir: Optional[Path] = None, server_type: Optional[str] = None) -> Dict[str, Any]:
    """Adaptive RCON TPS probe with fallback to logs/latest.log lag detection."""
    now = time.time()
    with _TPS_CACHE_LOCK:
        cached = _TPS_CACHE.get(server_name)
        if cached and (now - cached["timestamp"]) < 5.0:
            return dict(cached["result"])
        last_working_cmd = cached.get("working_command") if cached else None

    if server_dir is None:
        try:
            server_dir = safe_child_path(SERVERS_ROOT, server_name)
        except Exception:
            server_dir = None

    tps: Optional[float] = None
    mspt: Optional[float] = None
    method = "none"
    working_cmd = last_working_cmd

    # 1. RCON probe if properties exist
    rcon_port = 25575
    rcon_password = None
    rcon_enabled = False

    if server_dir and server_dir.exists():
        props_file = server_dir / "server.properties"
        if props_file.exists():
            try:
                content = props_file.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("rcon.port="):
                        rcon_port = int(line.split("=", 1)[1].strip() or 25575)
                    elif line.startswith("rcon.password="):
                        rcon_password = line.split("=", 1)[1].strip()
                    elif line.startswith("enable-rcon="):
                        rcon_enabled = line.split("=", 1)[1].strip().lower() == "true"
            except Exception:
                pass

    if rcon_enabled and rcon_password:
        # Determine probe commands to attempt
        st_lower = str(server_type or "").lower()
        if "paper" in st_lower or "purpur" in st_lower or "folia" in st_lower:
            candidates = ["/tps", "/tick query", "/forge tps"]
        elif "neoforge" in st_lower:
            candidates = ["/tick query", "/forge tps", "/tps"]
        elif "forge" in st_lower:
            candidates = ["/forge tps", "/tick query", "/tps"]
        elif "vanilla" in st_lower:
            candidates = ["/tick query", "/tps", "/forge tps"]
        else:
            candidates = ["/tick query", "/tps", "/forge tps"]

        # Prioritize last working command if known
        if last_working_cmd and last_working_cmd in candidates:
            candidates.remove(last_working_cmd)
            candidates.insert(0, last_working_cmd)

        try:
            from mcrcon import MCRcon
            with MCRcon("localhost", rcon_password, port=rcon_port, timeout=0.35) as mcr:
                for cmd in candidates:
                    try:
                        clean_cmd = cmd.lstrip("/")
                        raw = mcr.command(clean_cmd) or ""
                        # Strip Minecraft section colors and ANSI
                        text = re.sub(r"§[0-9a-fk-or]", "", str(raw), flags=re.IGNORECASE)
                        text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
                        if not text or "unknown command" in text.lower() or "error" in text.lower():
                            continue

                        if clean_cmd == "tick query":
                            m_tps = re.search(r"average:\s*([0-9.]+)\s*tps", text, re.IGNORECASE)
                            m_mspt = re.search(r"\(([0-9.]+)\s*mspt\)", text, re.IGNORECASE)
                            if not m_mspt:
                                m_mspt = re.search(r"Average tick time:\s*([0-9.]+)\s*ms", text, re.IGNORECASE)
                            if m_tps:
                                tps = float(m_tps.group(1))
                                if m_mspt:
                                    mspt = float(m_mspt.group(1))
                                else:
                                    mspt = round(min(1000.0 / max(0.1, tps), 50.0), 1)
                                method = "rcon_tick_query"
                                working_cmd = cmd
                                break

                        elif clean_cmd == "tps":
                            m_tps = re.search(r"TPS from last.*?:\s*\*?([0-9.]+)", text, re.IGNORECASE)
                            if not m_tps:
                                m_tps = re.search(r"([0-9.]+),\s*([0-9.]+),\s*([0-9.]+)", text)
                            if m_tps:
                                tps = float(m_tps.group(1))
                                try:
                                    raw_mspt = mcr.command("mspt") or ""
                                    text_mspt = re.sub(r"§[0-9a-fk-or]", "", str(raw_mspt), flags=re.IGNORECASE)
                                    m_ms = re.search(r"5s:\s*([0-9.]+)", text_mspt)
                                    if m_ms:
                                        mspt = float(m_ms.group(1))
                                except Exception:
                                    pass
                                if mspt is None and tps > 0:
                                    mspt = round(min(1000.0 / max(0.1, tps), 50.0), 1)
                                method = "rcon_paper_tps"
                                working_cmd = cmd
                                break

                        elif clean_cmd == "forge tps":
                            m_over = re.search(r"Overall:.*?Mean tick time:\s*([0-9.]+)\s*ms.*?Mean TPS:\s*([0-9.]+)", text, re.IGNORECASE)
                            if m_over:
                                mspt = float(m_over.group(1))
                                tps = float(m_over.group(2))
                                method = "rcon_forge_tps"
                                working_cmd = cmd
                                break
                            else:
                                dim_matches = re.findall(r"Mean tick time:\s*([0-9.]+)\s*ms.*?Mean TPS:\s*([0-9.]+)", text, re.IGNORECASE)
                                if dim_matches:
                                    mspt_vals = [float(x[0]) for x in dim_matches]
                                    tps_vals = [float(x[1]) for x in dim_matches]
                                    mspt = round(sum(mspt_vals) / len(mspt_vals), 1)
                                    tps = round(sum(tps_vals) / len(tps_vals), 1)
                                    method = "rcon_forge_tps"
                                    working_cmd = cmd
                                    break
                    except Exception:
                        continue
        except Exception:
            pass

    # 2. Fallback to logs/latest.log lag detection
    if tps is None and server_dir and server_dir.exists():
        log_file = server_dir / "logs" / "latest.log"
        if log_file.exists():
            try:
                raw_lines = read_log_tail_lines(log_file)
                lines = raw_lines[-80:] if raw_lines else []
                lag_matches = []
                for line in lines:
                    m = re.search(r"Can't keep up!\s*(?:Is the server overloaded\?\s*)?Running\s+(\d+)ms\s+or\s+(\d+)\s+ticks behind", line, re.IGNORECASE)
                    if m:
                        lag_matches.append((float(m.group(1)), float(m.group(2))))
                if lag_matches:
                    x_ms, y_ticks = lag_matches[-1]
                    extra_ms = x_ms / max(1.0, y_ticks)
                    mspt = round(50.0 + extra_ms, 1)
                    tps = round(min(20.0, max(0.0, 1000.0 / mspt)), 1)
                    method = "log_lag_detection"
                else:
                    tps = 20.0
                    mspt = 25.0
                    method = "nominal_healthy"
            except Exception:
                tps = 20.0
                mspt = 25.0
                method = "nominal_fallback"
        else:
            tps = 20.0
            mspt = 25.0
            method = "nominal_fallback"

    res = {
        "tps": round(tps, 1) if tps is not None else None,
        "mspt": round(mspt, 1) if mspt is not None else None,
        "method": method,
    }

    with _TPS_CACHE_LOCK:
        _TPS_CACHE[server_name] = {
            "timestamp": now,
            "working_command": working_cmd,
            "result": res,
        }

    return res

def _live_cpu_count() -> int:
    """Live CPU count — never cache, so a host CPU swap is reflected after container restart."""
    try:
        c = psutil.cpu_count(logical=True)
        if c and c > 0:
            return int(c)
    except Exception:
        pass
    try:
        c = os.cpu_count()
        if c and c > 0:
            return int(c)
    except Exception:
        pass
    return 1

# kept for compat, but recomputed live per call
_CPU_CORES = _live_cpu_count()


def _parse_ram_to_mb(value: object, default_mb: float) -> float:
    try:
        if value is None:
            return default_mb
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if not raw:
            return default_mb
        m = _RAM_PATTERN.match(raw)
        if not m:
            return default_mb
        number = float(m.group(1))
        unit = (m.group(2) or '').upper()
        factors = {
            '': 1.0,
            'K': 1.0 / 1024.0,
            'M': 1.0,
            'G': 1024.0,
            'T': 1024.0 * 1024.0,
            'P': 1024.0 * 1024.0 * 1024.0,
        }
        factor = factors.get(unit, 1.0)
        mb_val = number * factor
        if mb_val <= 0:
            return default_mb
        return mb_val
    except Exception:
        return default_mb


def _gather_process_tree(pid: int) -> List[psutil.Process]:
    procs: List[psutil.Process] = []
    try:
        root = psutil.Process(pid)
    except Exception:
        return procs
    procs.append(root)
    try:
        procs.extend(root.children(recursive=True))
    except Exception:
        pass
    return procs


class LocalAdapter:
    """DockerManager-compatible adapter for LocalRuntimeManager."""

    def __init__(self) -> None:
        self.local = LocalRuntimeManager()
        self._docker = None
        self._steam_index: Dict[str, Dict[str, Any]] = {}
        self._list_cache: Optional[Tuple[float, str, List[Dict[str, Any]]]] = None
        self._bulk_stats_cache: Dict[bool, Tuple[float, Dict[str, Dict]]] = {}

    def _invalidate_caches(self) -> None:
        self._list_cache = None
        self._bulk_stats_cache.clear()

    def _get_docker(self):
        if self._docker is None:
            try:
                from docker_manager import DockerManager  
            except Exception as exc:
                raise RuntimeError(f"Docker manager unavailable: {exc}")
            self._docker = DockerManager()
        return self._docker

    def _refresh_steam_index(self, entries: List[Dict[str, Any]]) -> None:
        index: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("server_kind", "")).lower() != "steam":
                continue
            cid = str(entry.get("id") or "")
            name = str(entry.get("name") or "")
            if cid:
                index[cid] = entry
            if name:
                index[name] = entry
        self._steam_index = index

    def _resolve_steam_id(self, container_id: str) -> Optional[str]:
        if not container_id:
            return None
        cached = self._steam_index.get(container_id)
        if cached and str(cached.get("server_kind", "")).lower() == "steam":
            return str(cached.get("id"))
        # Fast-path: local server directory exists and is not marked server_kind == "steam"
        try:
            srv_dir = safe_child_path(SERVERS_ROOT, container_id)
            if srv_dir.exists() and srv_dir.is_dir():
                meta_path = srv_dir / "server_meta.json"
                is_steam = False
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore") or "{}")
                        if isinstance(meta, dict) and str(meta.get("server_kind", "")).lower() == "steam":
                            is_steam = True
                    except Exception:
                        pass
                if not is_steam:
                    return None
        except Exception:
            pass
        try:
            docker = self._get_docker()
        except Exception:
            return None
        try:
            container = docker.client.containers.get(container_id)
        except Exception:
            return None
        labels = (container.attrs.get("Config", {}) or {}).get("Labels", {}) or {}
        if str(labels.get("steam.server", "")).lower() == "true":
            identifier = container.id
            data = {
                "id": identifier,
                "name": getattr(container, "name", container_id),
                "status": getattr(container, "status", "unknown"),
                "server_kind": "steam",
            }
            self._steam_index[identifier] = data
            self._steam_index[data["name"]] = data
            return identifier
        return None

    
    def list_servers(self) -> List[Dict]:
        now = time.time()
        root_key = str(SERVERS_ROOT)
        if (
            self._list_cache is not None
            and (now - self._list_cache[0]) <= 1.5
            and self._list_cache[1] == root_key
        ):
            return [dict(x) for x in self._list_cache[2]]

        items = self.local.list_servers()
        for it in items:
            it.setdefault("server_kind", "minecraft")
        for it in items:
            name = it.get("name") or it.get("id")
            it.setdefault("labels", {})
            it.setdefault("mounts", [])
            it.setdefault("image", "local")
            raw_ports = {f"{MINECRAFT_PORT}/tcp": None}
            it.setdefault("ports", raw_ports)
            it.setdefault("port_mappings", {f"{MINECRAFT_PORT}/tcp": {"host_port": None, "host_ip": None}})
            
            try:
                if name:
                    meta_path = safe_child_path(SERVERS_ROOT, str(name), "server_meta.json")
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        lbl = it.get("labels") or {}
                        if isinstance(meta, dict):
                            prov = meta.get("modpack_provider")
                            pid = meta.get("modpack_id")
                            ver = meta.get("modpack_version_id")
                            if prov:
                                lbl["mc.modpack.provider"] = str(prov)
                            if pid:
                                lbl["mc.modpack.id"] = str(pid)
                            if ver:
                                lbl["mc.modpack.version_id"] = str(ver)
                        it["labels"] = lbl
            except Exception:
                pass

        steam_entries: List[Dict[str, Any]] = []
        steam_enabled = bool(
            (os.getenv("STEAM_DOCKER_HOST") or "").strip()
            or Path("/data/servers/.steam-docker.sock").exists()
            or self._docker is not None
        )
        if steam_enabled:
            try:
                docker = self._get_docker()
                docker_servers = docker.list_servers()
                for entry in docker_servers:
                    try:
                        if str(entry.get("server_kind", "")).lower() != "steam":
                            continue
                        steam_entry = dict(entry)
                        steam_entries.append(steam_entry)
                    except Exception:
                        continue
            except Exception:
                steam_entries = []

        if steam_entries:
            self._refresh_steam_index(steam_entries)
            items.extend(steam_entries)
        else:
            self._steam_index = {}
        self._list_cache = (time.time(), root_key, [dict(x) for x in items])
        return items

    def create_server(
        self,
        name: str,
        server_type: str,
        version: str,
        host_port: Optional[int] = None,
        loader_version: Optional[str] = None,
        min_ram: str = "1G",
        max_ram: str = "2G",
        installer_version: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        extra_labels: Optional[Dict[str, str]] = None,
        cpu_cores=None,
    ) -> Dict:
        result = self.local.create_server(
            name,
            server_type,
            version,
            host_port=host_port,
            loader_version=loader_version,
            min_ram=min_ram,
            max_ram=max_ram,
            installer_version=installer_version,
            cpu_cores=cpu_cores,
        )
        
        try:
            if extra_labels:
                meta_updates: Dict[str, Any] = {}
                if "mc.modpack.provider" in extra_labels:
                    meta_updates["modpack_provider"] = extra_labels.get("mc.modpack.provider")
                if "mc.modpack.id" in extra_labels:
                    meta_updates["modpack_id"] = extra_labels.get("mc.modpack.id")
                if "mc.modpack.version_id" in extra_labels:
                    meta_updates["modpack_version_id"] = extra_labels.get("mc.modpack.version_id")
                if meta_updates:
                    self.local.update_metadata(name, **meta_updates)
        except Exception:
            pass
        self._invalidate_caches()
        return result

    def create_server_from_existing(
        self,
        name: str,
        host_port: Optional[int] = None,
        min_ram: str = "1G",
        max_ram: str = "2G",
        extra_env: Optional[Dict[str, str]] = None,
        extra_labels: Optional[Dict[str, str]] = None,
        cpu_cores=None,
    ) -> Dict:
        result = self.local.create_server_from_existing(
            name,
            host_port=host_port,
            min_ram=min_ram,
            max_ram=max_ram,
            extra_env=extra_env,
            extra_labels=extra_labels,
            cpu_cores=cpu_cores,
        )
        
        try:
            if extra_labels:
                meta_updates: Dict[str, Any] = {}
                if "mc.modpack.provider" in extra_labels:
                    meta_updates["modpack_provider"] = extra_labels.get("mc.modpack.provider")
                if "mc.modpack.id" in extra_labels:
                    meta_updates["modpack_id"] = extra_labels.get("mc.modpack.id")
                if "mc.modpack.version_id" in extra_labels:
                    meta_updates["modpack_version_id"] = extra_labels.get("mc.modpack.version_id")
                if meta_updates:
                    self.local.update_metadata(name, **meta_updates)
        except Exception:
            pass
        self._invalidate_caches()
        return result

    def stop_server(self, container_id: str) -> Dict:
        self._invalidate_caches()
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self._get_docker().stop_server(steam_id)
        return self.local.stop_server(container_id)

    def start_server(self, container_id: str) -> Dict:
        self._invalidate_caches()
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self._get_docker().start_server(steam_id)
        return self.local.create_server_from_existing(container_id, min_ram=None, max_ram=None)

    def restart_server(self, container_id: str) -> Dict:
        """Restart a server with robust port-release handling.

        The old implementation called stop → start with zero delay, which
        caused 'address already in use' when the Java child process was
        still alive or the socket lingered in TIME_WAIT.  Now stop_server()
        handles full process-tree kill + port verification internally, and
        we add a final safety check before re-spawning.
        """
        self._invalidate_caches()
        try:
            steam_id = self._resolve_steam_id(container_id)
        except Exception:
            steam_id = None
        if steam_id:
            return self._get_docker().restart_server(steam_id)

        # Stop — this now kills the full process tree and waits for the port
        try:
            self.local.stop_server(container_id)
        except Exception:
            pass

        # Extra safety: brief pause to let the OS fully release the socket
        # (handles the rare TIME_WAIT edge case)
        time.sleep(0.5)

        return self.local.create_server_from_existing(container_id, min_ram=None, max_ram=None)


    def kill_server(self, container_id: str) -> Dict:
        self._invalidate_caches()
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self._get_docker().kill_server(steam_id)
        return self.local.stop_server(container_id)

    def delete_server(self, container_id: str) -> Dict:
        self._invalidate_caches()
        with _TELEMETRY_CACHE_LOCK:
            _TELEMETRY_CACHE.pop(container_id, None)
        with _TPS_CACHE_LOCK:
            _TPS_CACHE.pop(container_id, None)
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            res = self._get_docker().delete_server(steam_id)
            try:
                local_dir = safe_child_path(SERVERS_ROOT, container_id)
                if local_dir.exists() or local_dir.is_symlink():
                    local_res = self.local.delete_server(container_id)
                    if isinstance(res, dict) and not local_res.get("dir_removed"):
                        res["dir_removed"] = False
            except Exception:
                pass
            self._invalidate_caches()
            return res
        res = self.local.delete_server(container_id)
        self._invalidate_caches()
        return res

    def update_metadata(self, container_id: str, **fields: Any) -> None:
        self._invalidate_caches()
        self.local.update_metadata(container_id, **fields)

    
    def get_server_tps(self, server_name: str) -> Dict[str, Any]:
        """Adaptive RCON / log probe for server TPS and MSPT."""
        steam_id = self._resolve_steam_id(server_name)
        if steam_id:
            return {"tps": None, "mspt": None, "method": "steam"}
        p = safe_child_path(SERVERS_ROOT, server_name)
        pid = None
        try:
            pid_txt = (p / ".server.pid").read_text().strip()
            pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None

        if not (pid and psutil.pid_exists(pid)):
            return {"tps": None, "mspt": None, "method": "stopped"}

        server_type = None
        try:
            meta_path = p / "server_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                server_type = meta.get("type")
        except Exception:
            pass

        return _probe_server_tps(server_name, p, server_type)

    def get_server_stats(self, container_id: str, include_players: bool = True) -> Dict:
        # NOTE: include_players runs the full mcstatus→RCON→log probe chain
        # (seconds in the worst case). The 5s global poll must pass False —
        # player counts come from the roster endpoint, not from stats.
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self._get_docker().get_server_stats(steam_id)
        p = safe_child_path(SERVERS_ROOT, container_id)
        pid = None
        try:
            pid_txt = (p / ".server.pid").read_text().strip()
            pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None

        cpu_percent = 0.0
        cpu_percent_normalized = 0.0
        per_core_cpu: List[float] = []
        active_threads = 0
        thread_metrics: List[Dict[str, Any]] = []
        tps: Optional[float] = None
        mspt: Optional[float] = None
        mem_usage_mb = 0.0
        mem_limit_mb = float(psutil.virtual_memory().total) / (1024 * 1024)
        mem_percent = 0.0
        net_rx_mb = 0.0
        net_tx_mb = 0.0
        uptime_seconds = 0
        restart_count = 0
        health_status = "unknown"
        player_count = 0

        try:
            meta_path = (p / "server_meta.json")
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                mem_limit_mb = _parse_ram_to_mb(meta.get("max_ram_mb") or meta.get("max_ram"), mem_limit_mb)
                # Get restart count and started time from meta
                restart_count = meta.get("restart_count", 0)
                started_ts = meta.get("started_ts") or meta.get("container_created_ts")
                if started_ts:
                    try:
                        from datetime import datetime, timezone
                        started_dt = datetime.fromtimestamp(int(started_ts), tz=timezone.utc)
                        uptime_seconds = int((datetime.now(timezone.utc) - started_dt).total_seconds())
                    except Exception:
                        pass
                health_status = "healthy" if pid and psutil.pid_exists(pid) else "unhealthy"
        except Exception:
            pass

        if pid and psutil.pid_exists(pid):
            try:
                procs = _gather_process_tree(pid)
                if not procs:
                    procs = [psutil.Process(pid)]

                # Sum active threads across process tree
                for pr in procs:
                    try:
                        active_threads += pr.num_threads()
                    except Exception:
                        pass

                # Collect process and thread timings for telemetry cache
                now = time.time()
                with _TELEMETRY_CACHE_LOCK:
                    prev_snap = _TELEMETRY_CACHE.get(container_id)

                curr_proc_times: Dict[int, float] = {}
                curr_thread_times: Dict[int, Tuple[float, float]] = {}
                curr_thread_names: Dict[int, str] = {}
                direct_proc_cpus: float = 0.0

                for pr in procs:
                    try:
                        # Some mocks or wrappers define cpu_percent directly
                        direct_proc_cpus += pr.cpu_percent(interval=None)
                    except Exception:
                        pass
                    try:
                        c_t = pr.cpu_times()
                        curr_proc_times[pr.pid] = float(c_t.user + c_t.system)
                    except Exception:
                        pass
                    try:
                        for th in pr.threads():
                            curr_thread_times[th.id] = (float(th.user_time), float(th.system_time))
                            curr_thread_names[th.id] = getattr(th, "name", None) or _resolve_thread_name(pr.pid, th.id)
                    except Exception:
                        pass

                # If non-blocking cached baseline exists within 0.05s-60.0s window:
                if prev_snap and (0.05 <= (now - prev_snap["timestamp"]) <= 60.0) and prev_snap.get("proc_times"):
                    dt = max(0.001, now - prev_snap["timestamp"])
                    total_cpu_delta = 0.0
                    for p_id, curr_t in curr_proc_times.items():
                        prev_t = prev_snap["proc_times"].get(p_id)
                        if prev_t is not None:
                            total_cpu_delta += max(0.0, curr_t - prev_t)
                    total_cpu = (total_cpu_delta / dt) * 100.0
                    if total_cpu == 0.0 and direct_proc_cpus > 0.0:
                        total_cpu = direct_proc_cpus

                    prev_threads = prev_snap.get("thread_times", {})
                    for tid, (u_t, s_t) in curr_thread_times.items():
                        curr_t = u_t + s_t
                        prev_t_pair = prev_threads.get(tid)
                        if prev_t_pair is not None:
                            prev_t = prev_t_pair[0] + prev_t_pair[1]
                            th_delta = max(0.0, curr_t - prev_t)
                            th_pct = round((th_delta / dt) * 100.0, 1)
                        else:
                            th_pct = 0.0
                        if th_pct == 0.0:
                            mock_th_pct = getattr(th, "cpu_percent", None)
                            if isinstance(mock_th_pct, (int, float)) and mock_th_pct > 0:
                                th_pct = float(mock_th_pct)
                        thread_metrics.append({
                            "id": tid,
                            "name": curr_thread_names.get(tid, f"Worker-{tid}"),
                            "cpu_percent": th_pct,
                            "user_time": round(u_t, 2),
                            "system_time": round(s_t, 2),
                        })
                else:
                    # Cold start: sleep 0.1s to establish high-precision baseline
                    time.sleep(0.1)
                    now2 = time.time()
                    dt = max(0.001, now2 - now)
                    total_cpu_delta = 0.0
                    new_proc_times: Dict[int, float] = {}
                    new_thread_times: Dict[int, Tuple[float, float]] = {}

                    second_direct_cpu = 0.0
                    for pr in procs:
                        try:
                            second_direct_cpu += pr.cpu_percent(interval=None)
                        except Exception:
                            pass
                        try:
                            c_t = pr.cpu_times()
                            c_tot = float(c_t.user + c_t.system)
                            new_proc_times[pr.pid] = c_tot
                            prev_t = curr_proc_times.get(pr.pid)
                            if prev_t is not None:
                                total_cpu_delta += max(0.0, c_tot - prev_t)
                        except Exception:
                            pass
                        try:
                            for th in pr.threads():
                                new_thread_times[th.id] = (float(th.user_time), float(th.system_time))
                                curr_t = float(th.user_time + th.system_time)
                                prev_pair = curr_thread_times.get(th.id)
                                if prev_pair is not None:
                                    prev_t = prev_pair[0] + prev_pair[1]
                                    th_delta = max(0.0, curr_t - prev_t)
                                    th_pct = round((th_delta / dt) * 100.0, 1)
                                    if th_pct == 0.0:
                                        mock_th_pct = getattr(th, "cpu_percent", None)
                                        if isinstance(mock_th_pct, (int, float)) and mock_th_pct > 0:
                                            th_pct = float(mock_th_pct)
                                else:
                                    mock_th_pct = getattr(th, "cpu_percent", 0.0)
                                    th_pct = float(mock_th_pct) if isinstance(mock_th_pct, (int, float)) else 0.0
                                thread_metrics.append({
                                    "id": th.id,
                                    "name": getattr(th, "name", None) or curr_thread_names.get(th.id, f"Worker-{th.id}"),
                                    "cpu_percent": th_pct,
                                    "user_time": round(float(th.user_time), 2),
                                    "system_time": round(float(th.system_time), 2),
                                })
                        except Exception:
                            pass

                    total_cpu = (total_cpu_delta / dt) * 100.0
                    if total_cpu == 0.0 and second_direct_cpu > 0.0:
                        total_cpu = second_direct_cpu
                    curr_proc_times = new_proc_times
                    curr_thread_times = new_thread_times
                    now = now2

                with _TELEMETRY_CACHE_LOCK:
                    _TELEMETRY_CACHE[container_id] = {
                        "timestamp": now,
                        "proc_times": curr_proc_times,
                        "thread_times": curr_thread_times,
                    }

                thread_metrics.sort(key=lambda x: x["cpu_percent"], reverse=True)
                thread_metrics = thread_metrics[:15]

                # Per-core CPU array (psutil.cpu_percent with percpu=True)
                try:
                    raw_per_core = psutil.cpu_percent(interval=None, percpu=True)
                    if isinstance(raw_per_core, list):
                        per_core_cpu = [round(float(c), 1) for c in raw_per_core]
                except Exception:
                    per_core_cpu = []
                if not per_core_cpu:
                    cores = _live_cpu_count()
                    if cores > 0:
                        per_core_cpu = [0.0] * cores

                total_mem = 0
                for pr in procs:
                    try:
                        added = 0
                        # Prefer Unique Set Size (USS) so ZGC shared/multi-mapped virtual pages
                        # on Linux are never counted multiple times against the server RAM limit.
                        if hasattr(pr, "memory_full_info"):
                            full = pr.memory_full_info()
                            uss_val = getattr(full, "uss", 0)
                            pss_val = getattr(full, "pss", 0)
                            if isinstance(uss_val, int) and not isinstance(uss_val, bool) and uss_val > 0:
                                added = uss_val
                            elif isinstance(pss_val, int) and not isinstance(pss_val, bool) and pss_val > 0:
                                added = pss_val
                        if added <= 0:
                            added = pr.memory_info().rss
                        total_mem += added
                    except Exception:
                        pass
                mem_usage_mb = float(total_mem) / (1024 * 1024)

                # UNCLAMPED Aggregate CPU percent (e.g. 200% for 2 loaded cores)
                cpu_percent = total_cpu
                live_cores = _live_cpu_count()
                # Normalized CPU percent (0-100% of host capacity)
                cpu_percent_normalized = min((total_cpu / live_cores), 100.0) if live_cores > 0 else 0.0

                # Host net counters approximation
                try:
                    hc = psutil.net_io_counters()
                    raw_rx = hc.bytes_recv
                    raw_tx = hc.bytes_sent
                    global _HOST_NET_BASE
                    with _HOST_NET_BASE_LOCK:
                        if _HOST_NET_BASE is None:
                            _HOST_NET_BASE = (raw_rx, raw_tx)
                        base_rx, base_tx = _HOST_NET_BASE
                    total_rx = max(0, raw_rx - base_rx)
                    total_tx = max(0, raw_tx - base_tx)
                except Exception:
                    total_rx = total_tx = 0
                net_rx_mb = round(total_rx / (1024 * 1024), 2) if total_rx else net_rx_mb
                net_tx_mb = round(total_tx / (1024 * 1024), 2) if total_tx else net_tx_mb

                if mem_limit_mb:
                    mem_percent = (mem_usage_mb / mem_limit_mb) * 100.0
            except Exception:
                pass

            # Adaptive TPS probe query
            try:
                tps_res = self.get_server_tps(container_id)
                tps = tps_res.get("tps")
                mspt = tps_res.get("mspt")
            except Exception:
                tps = None
                mspt = None

        # Get player count via RCON/mcstatus if server is running.
        # Skipped when include_players=False (hot polling path) — the roster
        # endpoint owns player counts; probing here added seconds per call.
        if include_players and pid and psutil.pid_exists(pid):
            try:
                player_info = self.get_player_info(container_id)
                player_count = player_info.get("online", 0)
            except Exception:
                pass

        if mem_limit_mb <= 0:
            mem_limit_mb = max(mem_usage_mb, 1.0)

        return {
            "id": container_id,
            "cpu_percent": round(cpu_percent, 2),
            "cpu_percent_aggregate": round(cpu_percent, 2),
            "cpu_percent_normalized": round(cpu_percent_normalized, 2),
            "per_core_cpu": per_core_cpu,
            "active_threads": active_threads,
            "thread_metrics": thread_metrics,
            "memory_usage_mb": round(mem_usage_mb, 2),
            "memory_used_mb": round(mem_usage_mb, 2),
            "memory_limit_mb": round(mem_limit_mb, 2),
            "memory_percent": round(mem_percent, 2),
            "network_rx_mb": net_rx_mb,
            "network_tx_mb": net_tx_mb,
            "uptime_seconds": uptime_seconds,
            "restart_count": restart_count,
            "health_status": health_status,
            "player_count": player_count,
            "tps": tps,
            "mspt": mspt,
        }

    def _stopped_local_stats(self, container_id: str, total_ram_mb: float) -> Dict[str, Any]:
        p = safe_child_path(SERVERS_ROOT, container_id)
        mem_limit_mb = total_ram_mb
        restart_count = 0
        health_status = "unknown"
        try:
            meta_path = p / "server_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    mem_limit_mb = _parse_ram_to_mb(meta.get("max_ram_mb") or meta.get("max_ram"), mem_limit_mb)
                    restart_count = meta.get("restart_count", 0)
                    health_status = "unhealthy"
        except Exception:
            pass
        if mem_limit_mb <= 0:
            mem_limit_mb = 1.0
        return {
            "id": container_id,
            "cpu_percent": 0.0,
            "cpu_percent_aggregate": 0.0,
            "cpu_percent_normalized": 0.0,
            "per_core_cpu": [],
            "active_threads": 0,
            "thread_metrics": [],
            "memory_usage_mb": 0.0,
            "memory_used_mb": 0.0,
            "memory_limit_mb": round(mem_limit_mb, 2),
            "memory_percent": 0.0,
            "network_rx_mb": 0.0,
            "network_tx_mb": 0.0,
            "uptime_seconds": 0,
            "restart_count": restart_count,
            "health_status": health_status,
            "player_count": 0,
            "tps": None,
            "mspt": None,
        }

    def get_bulk_server_stats(self, ttl_seconds: int = 3, include_players: bool = False) -> Dict:
        # Hot path for the global 5s poll: honor TTL cache, short-circuit stopped
        # local servers, and run live servers in parallel.
        now = time.time()
        cache_key = bool(include_players)
        cached = self._bulk_stats_cache.get(cache_key)
        if cached and ttl_seconds > 0 and (now - cached[0]) <= ttl_seconds:
            return dict(cached[1])

        from concurrent.futures import ThreadPoolExecutor
        results: Dict[str, Dict] = {}
        running_ids: List[str] = []
        total_ram_mb: Optional[float] = None

        for it in self.list_servers():
            container_id = it.get("id") or it.get("name")
            if not container_id:
                continue
            cid = str(container_id)
            is_steam = str(it.get("server_kind", "")).lower() == "steam"
            if not is_steam and it.get("status") != "running":
                if total_ram_mb is None:
                    total_ram_mb = float(psutil.virtual_memory().total) / (1024 * 1024)
                results[cid] = self._stopped_local_stats(cid, total_ram_mb)
            else:
                running_ids.append(cid)

        if running_ids:
            with ThreadPoolExecutor(max_workers=min(8, len(running_ids))) as ex:
                futs = {ex.submit(self.get_server_stats, cid, include_players): cid for cid in running_ids}
                for fut, cid in futs.items():
                    try:
                        results[cid] = fut.result(timeout=15)
                    except Exception:
                        results[cid] = {"id": cid, "error": "stats timeout"}

        self._bulk_stats_cache[cache_key] = (time.time(), dict(results))
        return results

    def get_player_info(self, container_id: str) -> Dict:
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            try:
                return self._get_docker().get_player_info(steam_id)
            except Exception:
                return {"online": 0, "max": 0, "names": [], "method": "error"}

        # --- Minecraft local-mode player detection ---
        # Try mcstatus first, then RCON, then log parsing
        meta = self.local._load_meta(container_id) if hasattr(self.local, '_load_meta') else {}
        host_port = meta.get("host_port") or MINECRAFT_PORT

        # Strategy 1: mcstatus query
        try:
            from mcstatus import JavaServer
            server = JavaServer("localhost", port=int(host_port))
            status_resp = server.status(timeout=3)
            players = getattr(status_resp, "players", None)
            online = int(getattr(players, "online", 0) or 0) if players else 0
            maxp = int(getattr(players, "max", 0) or 0) if players else 0
            names: List[str] = []
            sample = getattr(players, "sample", None) if players else None
            if sample:
                for p in sample:
                    nm = getattr(p, "name", None)
                    if nm is None and isinstance(p, dict):
                        nm = p.get("name")
                    if nm:
                        names.append(str(nm))
            if names or online == 0:
                return {"online": online, "max": maxp, "names": names, "method": "mcstatus"}
            # If mcstatus gave a count but no names, keep trying RCON
            mcstatus_result = {"online": online, "max": maxp, "names": [], "method": "mcstatus"}
        except Exception:
            mcstatus_result = None

        # Strategy 2: RCON (read port/password from server.properties)
        try:
            server_dir = safe_child_path(SERVERS_ROOT, container_id)
            props_file = server_dir / "server.properties"
            if props_file.exists():
                props_text = props_file.read_text(encoding="utf-8", errors="ignore")
                rcon_enabled = False
                rcon_password = ""
                rcon_port = 25575
                for line in props_text.splitlines():
                    line = line.strip()
                    if line.startswith("enable-rcon="):
                        rcon_enabled = line.split("=", 1)[1].strip().lower() == "true"
                    elif line.startswith("rcon.password="):
                        rcon_password = line.split("=", 1)[1].strip()
                    elif line.startswith("rcon.port="):
                        try:
                            rcon_port = int(line.split("=", 1)[1].strip())
                        except Exception:
                            pass

                if rcon_enabled and rcon_password:
                    from mcrcon import MCRcon
                    with MCRcon("localhost", rcon_password, port=rcon_port, timeout=3) as mcr:
                        output = mcr.command("list") or ""
                        text = str(output)
                        online_r = 0
                        maxp_r = 0
                        names_r: List[str] = []
                        m = re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", text)
                        if not m:
                            m = re.search(r"(\d+)\s*/\s*(\d+)\s*players? online", text)
                        if m:
                            online_r = int(m.group(1))
                            maxp_r = int(m.group(2))
                            colon_idx = text.find(":")
                            if colon_idx != -1 and colon_idx + 1 < len(text):
                                names_str = text[colon_idx + 1:].strip()
                                if names_str:
                                    names_r = [n.strip() for n in names_str.split(",") if n.strip()]
                        if names_r:
                            return {"online": online_r, "max": maxp_r, "names": names_r, "method": "rcon"}
                        elif mcstatus_result and mcstatus_result["online"] > online_r:
                            return {"online": mcstatus_result["online"], "max": max(maxp_r, mcstatus_result.get("max", 0)), "names": names_r, "method": "rcon+mcstatus"}
                        else:
                            return {"online": online_r, "max": maxp_r, "names": names_r, "method": "rcon"}
        except Exception:
            pass

        # Strategy 3: Parse latest.log for online players (bounded tail read +
        # settled-state scan: newest event per player decides, stop lines end
        # the session so stale joins can't resurrect).
        try:
            server_dir = safe_child_path(SERVERS_ROOT, container_id)
            log_file = server_dir / "logs" / "latest.log"
            if log_file.exists():
                names_log, _ = online_from_log_lines(read_log_tail_lines(log_file))
                if names_log or mcstatus_result is None:
                    online_count = len(names_log)
                    if mcstatus_result and mcstatus_result["online"] > online_count:
                        online_count = mcstatus_result["online"]
                    return {"online": online_count, "max": mcstatus_result.get("max", 0) if mcstatus_result else 0, "names": names_log, "method": "log_parse"}
        except Exception:
            pass

        # Fallback: return mcstatus partial result or empty
        if mcstatus_result:
            return mcstatus_result
        return {"online": 0, "max": 0, "names": [], "method": "none"}

    def get_server_info(self, container_id: str) -> Dict:
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            info = self._get_docker().get_server_info(steam_id)
            info.setdefault("server_kind", "steam")
            return info
        p = safe_child_path(SERVERS_ROOT, container_id)
        exists = p.exists()
        pid = None
        try:
            pid_file = p / ".server.pid"
            if pid_file.exists():
                pid_txt = pid_file.read_text(encoding="utf-8", errors="ignore").strip()
                pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None
        status = "running" if (pid and self.local._is_running(pid)) else "exited"

        meta: Dict[str, Any] = {}
        mp = p / "server_meta.json"
        try:
            if mp.exists():
                parsed = json.loads(mp.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    meta = parsed
        except Exception:
            meta = {}

        host_port = meta.get("host_port") or MINECRAFT_PORT
        server_type = (
            meta.get("type")
            or meta.get("server_type")
            or meta.get("loader")
            or meta.get("detected_type")
        )
        version = (
            meta.get("version")
            or meta.get("server_version")
            or meta.get("mc_version")
            or meta.get("detected_version")
        )
        # Fill gaps from the server directory itself (jars, latest.log head) and persist once.
        meta_dirty = False
        try:
            srv_dir = resolve_server_dir(container_id)
            if srv_dir is not None:
                files = detect_server_from_files(srv_dir)
                if (not server_type or str(server_type).lower() in ("", "custom", "unknown")) and files.get("server_type"):
                    server_type = files["server_type"]
                    meta["type"] = server_type
                    meta_dirty = True
                if not version and files.get("server_version"):
                    version = files["server_version"]
                    meta["version"] = version
                    meta_dirty = True
                if not meta.get("loader_version") and files.get("loader_version"):
                    meta["loader_version"] = files["loader_version"]
                    meta_dirty = True
                if (not meta.get("java_version") or meta.get("java_version") == "unknown") and files.get("java_version"):
                    meta["java_version"] = files["java_version"]
                    meta_dirty = True
                if meta_dirty and exists:
                    try:
                        meta.setdefault("name", container_id)
                        mp.write_text(json.dumps(meta), encoding="utf-8")
                        self._invalidate_caches()
                    except Exception:
                        pass
        except Exception:
            pass
        created_at = meta.get("created_at")
        
        if not created_at:
            epoch_source = meta.get("created_ts") or meta.get("container_created_ts")
            if epoch_source:
                try:
                    from datetime import datetime
                    created_at = datetime.utcfromtimestamp(int(epoch_source))
                except Exception:
                    created_at = None
        java_version = meta.get("java_version", "unknown")
        minecraft_version = meta.get("minecraft_version") or meta.get("game_version")
        loader_version = meta.get("loader_version")

        java_args = ""
        try:
            env_overrides = meta.get("env_overrides")
            if isinstance(env_overrides, dict):
                val = env_overrides.get("JAVA_OPTS") or env_overrides.get("JAVA_ARGS")
                if isinstance(val, str):
                    java_args = val
        except Exception:
            java_args = ""

        info = {
            "id": container_id,
            "name": container_id,
            "status": status,
            "type": server_type,
            "version": version,
            "created_at": created_at,
            "java_version": java_version,
            "minecraft_version": minecraft_version,
            "loader_version": loader_version,
            "mounts": [],
            "ports": {f"{MINECRAFT_PORT}/tcp": None},
            "port_mappings": {f"{MINECRAFT_PORT}/tcp": {"host_port": host_port, "host_ip": None}},
            "exists": exists,
            "java_args": java_args,
            "lan_ip": get_lan_ip(),
            "server_kind": str(meta.get("server_kind") or "minecraft").lower(),
        }
        return info

    def update_server_java_version(self, container_id: str, java_version: str) -> Dict:
        
        try:
            if java_version not in ("8", "11", "17", "21", "25"):
                raise ValueError(f"Invalid Java version: {java_version}")
            java_bin = f"/usr/local/bin/java{java_version}"

            
            
            try:
                meta_path = safe_child_path(SERVERS_ROOT, container_id, "server_meta.json")
                meta = {}
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
            except Exception:
                meta = {}

            stored_overrides = meta.get("env_overrides") or {}
            if not isinstance(stored_overrides, dict):
                stored_overrides = {}
            merged = {str(k): str(v) for k, v in stored_overrides.items() if v is not None}
            
            merged["JAVA_VERSION_OVERRIDE"] = str(java_version)
            merged["JAVA_BIN_OVERRIDE"] = str(java_bin)
            merged["JAVA_VERSION"] = str(java_version)
            merged["JAVA_BIN"] = str(java_bin)

            
            try:
                
                
                self.local.update_metadata(container_id, env_overrides=merged, java_version=str(java_version))
            except Exception:
                pass

            
            try:
                self.local.stop_server(container_id)
            except Exception:
                pass
            
            result = self.local.create_server_from_existing(container_id, min_ram=None, max_ram=None)
            return {
                "success": True,
                "message": f"Java version updated to {java_version} and server restarted",
                "java_version": java_version,
                "java_bin": java_bin,
                "restarted": True,
                "result": result,
            }
        except Exception as e:
            return {"success": False, "error": "Runtime operation failed", "id": container_id}

    def update_server_java_args(self, container_id: str, java_args: str) -> Dict:
        """Persist custom Java arguments (JAVA_OPTS) for local runtime and restart the server."""
        try:
            normalized = " ".join((java_args or "").replace("\r", " ").split())
            if len(normalized) > 4096:
                raise ValueError("java_args too long (max 4096 characters when normalized)")

            meta_path = safe_child_path(SERVERS_ROOT, container_id, "server_meta.json")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}") if meta_path.exists() else {}
            except Exception:
                meta = {}

            stored_overrides = meta.get("env_overrides") or {}
            if not isinstance(stored_overrides, dict):
                stored_overrides = {}
            merged = {str(k): str(v) for k, v in stored_overrides.items() if v is not None}
            if normalized:
                merged["JAVA_OPTS"] = normalized
            else:
                merged.pop("JAVA_OPTS", None)

            try:
                self.local.update_metadata(container_id, env_overrides=merged)
            except Exception:
                pass

            try:
                self.local.stop_server(container_id)
            except Exception:
                pass

            result = self.local.create_server_from_existing(
                container_id,
                min_ram=None,
                max_ram=None,
                extra_env=merged or None,
            )

            return {
                "success": True,
                "java_args": normalized,
                "restarted": True,
                "result": result,
            }
        except Exception as e:
            return {"success": False, "error": "Runtime operation failed", "id": container_id}

    def update_server_ram(self, container_id: str, min_ram: str | None = None, max_ram: str | None = None) -> Dict:
        """Update RAM allocation for local runtime via restart."""
        try:
            self._invalidate_caches()
            res = self.local.update_server_ram(container_id, min_ram, max_ram)
            self._invalidate_caches()
            return res
        except Exception as e:
            return {"success": False, "error": "Runtime operation failed", "id": container_id}

    def update_server_cpu(self, container_id: str, cpu_cores=None) -> Dict:
        """Update CPU core cap for local runtime — live, no restart."""
        try:
            return self.local.update_server_cpu(container_id, cpu_cores)
        except Exception as e:
            return {"success": False, "error": "Runtime operation failed", "id": container_id}

    
    def get_server_logs(self, container_id: str, tail: int = 200) -> Dict:
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            try:
                logs = self._get_docker().get_server_logs(steam_id, tail=tail)
                logs.setdefault("server_kind", "steam")
                return logs
            except Exception:
                return {"id": container_id, "logs": ""}
        log_path = safe_child_path(SERVERS_ROOT, container_id, "server.stdout.log")
        try:
            if not log_path.exists():
                return {"id": container_id, "logs": ""}
            # Tail-read the last 64KB instead of the whole file (can be 50MB+).
            # Reading the full file on every 4s console poll stalled the worker.
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 65536))
                # drop a possible partial first line
                chunk = f.read().decode("utf-8", errors="ignore")
            lines = chunk.splitlines()
            if lines and size > 65536:
                lines = lines[1:]
            tail_lines = lines[-tail:] if tail and tail > 0 else lines
            return {"id": container_id, "logs": "\n".join(tail_lines)}
        except Exception:
            return {"id": container_id, "logs": ""}

    def get_server_terminal(self, container_id: str, tail: int = 100) -> Dict:
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self.get_server_logs(steam_id, tail=tail)
        return self.get_server_logs(container_id, tail=tail)

    def send_command(self, container_id: str, command: str) -> Dict:
        steam_id = self._resolve_steam_id(container_id)
        if steam_id:
            return self._get_docker().send_command(steam_id, command)
        fifo_path = safe_child_path(SERVERS_ROOT, container_id, "console.in")
        try:
            if not fifo_path.exists():
                return {"id": container_id, "ok": False, "error": "Console pipe not available"}
            data = (command or '').strip()
            if not data:
                return {"id": container_id, "ok": False, "error": "Empty command"}
            with open(fifo_path, 'w', encoding='utf-8', buffering=1) as f:
                f.write(data + "\n")
            return {"id": container_id, "ok": True}
        except Exception as e:
            return {"id": container_id, "ok": False, "error": "Failed to send command"}

    
    def rename_server(self, old_name: str, new_name: str) -> Dict:
        """Rename a local-runtime server directory and restart under the new name.

        Steps:
        - Stop any running local process for old_name (best-effort)
        - Rename directory SERVERS_ROOT/old_name -> SERVERS_ROOT/new_name
        - Update server_meta.json (name + previous_names)
        - Recreate the local server process preserving RAM and env_overrides
        """
        old_dir = safe_child_path(SERVERS_ROOT, old_name)
        new_dir = safe_child_path(SERVERS_ROOT, new_name)
        if not old_dir.exists() or not old_dir.is_dir():
            return {"ok": False, "error": f"Server directory {old_dir} not found"}
        if new_dir.exists():
            return {"ok": False, "error": f"Target directory {new_dir} already exists"}

        
        try:
            self.local.stop_server(old_name)
        except Exception:
            pass

        
        meta_path = old_dir / "server_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
            except Exception:
                meta = {}
        try:
            _min_mb = meta.get("min_ram_mb")
            min_ram = meta.get("min_ram") or (f"{int(_min_mb)}M" if isinstance(_min_mb, (int, float, str)) and str(_min_mb).isdigit() else None)
        except Exception:
            min_ram = meta.get("min_ram")
        try:
            _max_mb = meta.get("max_ram_mb")
            max_ram = meta.get("max_ram") or (f"{int(_max_mb)}M" if isinstance(_max_mb, (int, float, str)) and str(_max_mb).isdigit() else None)
        except Exception:
            max_ram = meta.get("max_ram")
        env_overrides = meta.get("env_overrides") if isinstance(meta.get("env_overrides"), dict) else {}

        
        old_dir.rename(new_dir)

        
        try:
            new_meta = dict(meta or {})
            prev = new_meta.get("previous_names") or []
            if isinstance(prev, list):
                if old_name not in prev:
                    prev.append(old_name)
                new_meta["previous_names"] = prev
            new_meta["name"] = new_name
            (new_dir / "server_meta.json").write_text(json.dumps(new_meta), encoding="utf-8")
        except Exception:
            pass

        
        try:
            result = self.local.create_server_from_existing(
                new_name,
                host_port=None,
                min_ram=min_ram,
                max_ram=max_ram,
                extra_env=env_overrides or None,
            )
        except Exception as e:
            self._invalidate_caches()
            return {"ok": False, "error": "Failed to recreate server"}

        self._invalidate_caches()
        return {"ok": True, "old_name": old_name, "new_name": new_name, "result": result}

    
    def get_used_host_ports(self, only_minecraft: bool = True) -> Set[int]:
        return set()

    def pick_available_port(self, preferred: Optional[int] = None, start: int = 25565, end: int = 25999) -> int:
        return int(preferred or start)


_adapter_cache: Optional[Any] = None


def get_runtime_manager():
    if os.getenv("RUNTIME_MODE", "docker").lower() == "local":
        return LocalAdapter()
    return None


def get_runtime_manager_or_docker():
    global _adapter_cache
    if _adapter_cache is not None:
        return _adapter_cache

    adapter = None
    try:
        adapter = get_runtime_manager()
    except Exception:
        adapter = None

    if adapter is not None:
        _adapter_cache = adapter
        return adapter

    from docker_manager import DockerManager  

    _adapter_cache = DockerManager()
    return _adapter_cache


def get_server_tps(server_name: str) -> Dict[str, Any]:
    """Module-level adaptive TPS query."""
    return LocalAdapter().get_server_tps(server_name)
