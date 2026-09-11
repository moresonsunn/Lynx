import os
import subprocess
import time
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
import re

from config import SERVERS_ROOT
from download_manager import prepare_server_files

logger = logging.getLogger(__name__)

MINECRAFT_PORT = 25565

_RAM_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGTP]?)(?:I?B)?\s*$", re.IGNORECASE)


def _ram_to_mb(value: Any, default_mb: int) -> int:
    try:
        if value is None:
            return default_mb
        if isinstance(value, (int, float)):
            return max(int(float(value)), 0)
        raw = str(value).strip()
        if not raw:
            return default_mb
        m = _RAM_PATTERN.match(raw)
        if not m:
            return default_mb
        number = float(m.group(1))
        unit = (m.group(2) or '').upper()
        multipliers = {
            '': 1,
            'K': 1.0 / 1024.0,
            'M': 1,
            'G': 1024,
            'T': 1024 * 1024,
            'P': 1024 * 1024 * 1024,
        }
        factor = multipliers.get(unit, 1)
        mb_val = int(round(number * factor))
        if mb_val <= 0:
            return default_mb
        return mb_val
    except Exception:
        return default_mb


def _format_ram(mb_value: int, prefer: str = 'G') -> str:
    if mb_value <= 0:
        return '512M'
    if prefer.upper() == 'G' and mb_value % 1024 == 0:
        return f"{mb_value // 1024}G"
    return f"{mb_value}M"


def _normalize_cpu_cores(value: Any) -> int | None:
    """Normalize a CPU core cap to a positive int, or None for unlimited."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() in ("unlimited", "none", "0"):
                return None
        cores = int(float(value))
    except (TypeError, ValueError):
        return None
    if cores < 1:
        return None
    return min(cores, 1024)


def _apply_cpu_affinity(pid: int, cores: int | None) -> bool:
    """Pin a process tree leader to the first N CPUs (Linux only). Returns ok."""
    if not cores:
        return False
    set_affinity = getattr(os, "sched_setaffinity", None)
    if not callable(set_affinity):
        return False
    try:
        import psutil as _psutil
        total = _psutil.cpu_count(logical=True) or cores
    except Exception:
        try:
            total = os.cpu_count() or cores
        except Exception:
            total = cores
    mask = set(range(min(cores, total)))
    try:
        set_affinity(pid, mask)
        return True
    except Exception as e:
        logger.warning(f"sched_setaffinity failed for pid {pid}: {e}")
        return False


class LocalRuntimeManager:
    def _server_dir(self, name: str) -> Path:
        return SERVERS_ROOT / name

    def _pid_file(self, name: str) -> Path:
        return self._server_dir(name) / ".server.pid"

    def _log_file(self, name: str) -> Path:
        return self._server_dir(name) / "server.stdout.log"

    def _meta_file(self, name: str) -> Path:
        return self._server_dir(name) / "server_meta.json"

    def _load_meta(self, name: str) -> Dict[str, Any]:
        p = self._meta_file(name)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_meta(self, name: str, meta: Dict[str, Any]) -> None:
        try:
            self._meta_file(name).write_text(json.dumps(meta), encoding="utf-8")
        except Exception:
            pass

    def update_metadata(self, name: str, **fields: Any) -> None:
        meta = self._load_meta(name)
        if not meta:
            meta = {"name": name, "created_at": int(time.time())}
        changed = False
        for k, v in fields.items():
            if v is None:
                continue
            if meta.get(k) != v:
                meta[k] = v
                changed = True
        if changed:
            meta.setdefault("name", name)
            meta.setdefault("created_at", int(time.time()))
            self._save_meta(name, meta)

    def _is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _ensure_server_port(self, srv_dir: Path, port: int) -> None:
        props = srv_dir / "server.properties"
        try:
            content = props.read_text(encoding="utf-8", errors="ignore") if props.exists() else ""
            lines = [ln for ln in content.splitlines() if ln.strip() != ""] if content else []
            found = False
            for idx, ln in enumerate(lines):
                if ln.strip().startswith("server-port="):
                    lines[idx] = f"server-port={int(port)}"
                    found = True
                    break
            if not found:
                lines.append(f"server-port={int(port)}")
            props.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _spawn(self, name: str, env: Dict[str, str]) -> Dict:
        srv_dir = self._server_dir(name)
        srv_dir.mkdir(parents=True, exist_ok=True)

        try:
            (srv_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        except Exception:
            pass

        try:
            port_val = int(env.get("SERVER_PORT", MINECRAFT_PORT))
            self._ensure_server_port(srv_dir, port_val)
        except Exception:
            pass

        # Rotate server.stdout.log if it grows beyond 50 MB to avoid filling disk after a day
        try:
            lf = self._log_file(name)
            if lf.exists() and lf.stat().st_size > 50 * 1024 * 1024:
                lf.rename(lf.with_suffix(".log.1"))
        except Exception:
            pass
        logf = open(self._log_file(name), "ab", buffering=0)
        cmd = ["/usr/local/bin/runtime-entrypoint.sh"]
        run_env = os.environ.copy()
        run_env.update(env)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(srv_dir),
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=run_env,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as e:
            try:
                logf.close()
            except Exception:
                pass
            raise RuntimeError(f"Failed to launch server process: {e}")
        # Parent no longer needs the FD — child has its own dup; close to avoid FD leak (was leaking 1 FD per restart)
        try:
            logf.close()
        except Exception:
            pass
        try:
            self._pid_file(name).write_text(str(proc.pid), encoding="utf-8")
        except Exception:
            pass
        # Enforce per-server CPU cap (first N CPUs) when configured
        try:
            cores = _normalize_cpu_cores(env.get("CPU_CORES"))
            if cores:
                _apply_cpu_affinity(proc.pid, cores)
        except Exception:
            pass
        return {"id": name, "name": name, "status": "running", "pid": proc.pid}

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
        cpu_cores=None,
    ) -> Dict:
        srv_dir = self._server_dir(name)
        srv_dir.mkdir(parents=True, exist_ok=True)
        prepare_server_files(
            server_type,
            version,
            srv_dir,
            loader_version=loader_version or "",
            installer_version=installer_version or "",
        )
        min_mb = _ram_to_mb(min_ram, default_mb=1024)
        max_mb = _ram_to_mb(max_ram, default_mb=2048)
        if max_mb < min_mb:
            max_mb = min_mb
        cores = _normalize_cpu_cores(cpu_cores)
        meta = {
            "name": name,
            "type": server_type,
            "version": version,
            "loader_version": loader_version or None,
            "installer_version": installer_version or None,
            "min_ram": _format_ram(min_mb),
            "max_ram": _format_ram(max_mb),
            "min_ram_mb": min_mb,
            "max_ram_mb": max_mb,
            "host_port": int(host_port or MINECRAFT_PORT),
            "created_at": int(time.time()),
        }
        if cores:
            meta["cpu_cores"] = int(cores)
        self._save_meta(name, meta)
        env = {
            "SERVER_DIR_NAME": name,
            "MIN_RAM": meta["min_ram"],
            "MAX_RAM": meta["max_ram"],
            "SERVER_PORT": str(host_port or MINECRAFT_PORT),
            "SERVER_TYPE": server_type,
            "SERVER_VERSION": version,
        }
        if cores:
            env["CPU_CORES"] = str(cores)
        return self._spawn(name, env)

    def create_server_from_existing(
        self,
        name: str,
        host_port: Optional[int] = None,
        min_ram: Optional[str] = None,
        max_ram: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        extra_labels: Optional[Dict[str, str]] = None,
        cpu_cores=None,
    ) -> Dict:
        srv_dir = self._server_dir(name)
        if not srv_dir.exists() or not srv_dir.is_dir():
            raise RuntimeError(f"Server directory {srv_dir} does not exist")
        meta = self._load_meta(name)
        meta.setdefault("name", name)
        meta.setdefault("type", None)
        meta.setdefault("version", None)
        meta.setdefault("created_at", int(time.time()))
        if host_port is not None:
            try:
                meta["host_port"] = int(host_port)
            except Exception:
                pass

        
        stored_overrides = meta.get("env_overrides") or {}
        if not isinstance(stored_overrides, dict):
            stored_overrides = {}
        merged_overrides: Dict[str, str] = {str(k): str(v) for k, v in stored_overrides.items() if v is not None}
        for k, v in (extra_env or {}).items():
            if v is None:
                continue
            merged_overrides[str(k)] = str(v)
        if merged_overrides != stored_overrides:
            meta["env_overrides"] = merged_overrides

        
        min_mb = _ram_to_mb(min_ram, default_mb=int(meta.get("min_ram_mb") or 1024))
        max_mb = _ram_to_mb(max_ram, default_mb=int(meta.get("max_ram_mb") or 2048))
        if max_mb < min_mb:
            max_mb = min_mb
        meta["min_ram"] = _format_ram(min_mb)
        meta["max_ram"] = _format_ram(max_mb)
        meta["min_ram_mb"] = min_mb
        meta["max_ram_mb"] = max_mb
        # CPU cap: explicit param wins, then env override, then stored meta
        cores = _normalize_cpu_cores(cpu_cores)
        if cores is None:
            try:
                cores = _normalize_cpu_cores((meta.get("env_overrides") or {}).get("CPU_CORES"))
            except Exception:
                cores = None
        if cores is None:
            cores = _normalize_cpu_cores(meta.get("cpu_cores"))
        if cores:
            meta["cpu_cores"] = int(cores)
        else:
            meta.pop("cpu_cores", None)
        self._save_meta(name, meta)

        env: Dict[str, str] = {
            "SERVER_DIR_NAME": name,
            "MIN_RAM": meta["min_ram"],
            "MAX_RAM": meta["max_ram"],
            "SERVER_PORT": str(host_port or meta.get("host_port") or MINECRAFT_PORT),
        }
        if cores:
            env["CPU_CORES"] = str(cores)
        for k, v in (meta.get("env_overrides") or {}).items():
            if v is None:
                continue
            env[str(k)] = str(v)
        for k, v in (extra_env or {}).items():
            if v is None:
                continue
            env[str(k)] = str(v)
        return self._spawn(name, env)

    def stop_server(self, server_id: str) -> Dict:
        name = server_id
        pid = None
        try:
            pid_txt = self._pid_file(name).read_text().strip()
            pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None
        if not pid:
            return {"id": name, "status": "unknown", "method": "noop"}
        try:
            killpg = getattr(os, "killpg", None)
            if callable(killpg):
                killpg(pid, 15)
            else:
                os.kill(pid, 15)
        except Exception as e:
            logger.warning(f"SIGTERM failed for {name} ({pid}): {e}")
        deadline = time.time() + 10
        while time.time() < deadline:
            if not self._is_running(pid):
                break
            time.sleep(0.5)
        if self._is_running(pid):
            try:
                killpg = getattr(os, "killpg", None)
                if callable(killpg):
                    killpg(pid, 9)
                else:
                    os.kill(pid, 9)
            except Exception as e:
                logger.warning(f"SIGKILL failed for {name} ({pid}): {e}")
        try:
            self._pid_file(name).unlink(missing_ok=True)
        except Exception:
            pass
        return {"id": name, "status": "stopped", "method": "signal"}

    def update_server_ram(self, server_id: str, min_ram: str | None, max_ram: str | None) -> Dict:
        """Update RAM allocation for a local server and restart it."""
        name = server_id
        srv_dir = self._server_dir(name)
        if not srv_dir.exists():
            raise RuntimeError(f"Server directory {srv_dir} not found")
        # Validate and normalize
        def norm(v):
            if v is None:
                return None
            mb = _ram_to_mb(v, default_mb=0)
            if mb < 128:
                raise ValueError(f"RAM too small: {v} (min 128M)")
            if mb > 256 * 1024:
                raise ValueError(f"RAM too large: {v} (max 256G)")
            return _format_ram(mb)
        n_min = norm(min_ram) if min_ram else None
        n_max = norm(max_ram) if max_ram else None
        if n_min and n_max:
            if _ram_to_mb(n_min, 0) > _ram_to_mb(n_max, 0):
                raise ValueError(f"min_ram {n_min} > max_ram {n_max}")
        # Stop if running
        try:
            self.stop_server(name)
        except Exception:
            pass
        # Recreate with new RAM (meta will be updated inside create_server_from_existing)
        return self.create_server_from_existing(name, min_ram=n_min, max_ram=n_max)

    def update_server_cpu(self, server_id, cpu_cores=None) -> Dict:
        """Update CPU core cap for a local server — applied live, no restart.

        cpu_cores: positive int, or None/"unlimited" to remove the cap.
        """
        name = server_id
        srv_dir = self._server_dir(name)
        if not srv_dir.exists():
            raise RuntimeError(f"Server directory {srv_dir} not found")
        cores = _normalize_cpu_cores(cpu_cores)
        meta = self._load_meta(name)
        if cores:
            meta["cpu_cores"] = int(cores)
        else:
            meta.pop("cpu_cores", None)
        stored = meta.get("env_overrides") or {}
        if not isinstance(stored, dict):
            stored = {}
        if cores:
            stored["CPU_CORES"] = str(cores)
        else:
            stored.pop("CPU_CORES", None)
        meta["env_overrides"] = stored
        self._save_meta(name, meta)
        # Live-apply to the running process if present
        live = False
        try:
            pid_txt = self._pid_file(name).read_text().strip()
            pid = int(pid_txt) if pid_txt else None
            if pid and self._is_running(pid) and cores:
                live = _apply_cpu_affinity(pid, cores)
        except Exception:
            pass
        return {"success": True, "cpu_cores": cores, "unlimited": cores is None,
                "restarted": False, "live_applied": live, "id": name}

    def list_servers(self) -> List[Dict]:
        items: List[Dict] = []
        try:
            for child in SERVERS_ROOT.iterdir():
                if not child.is_dir():
                    continue
                name = child.name
                pid = None
                try:
                    pid_txt = self._pid_file(name).read_text().strip()
                    pid = int(pid_txt) if pid_txt else None
                except Exception:
                    pid = None
                status = "running" if (pid and self._is_running(pid)) else "exited"
                meta: Dict[str, Any] = {}
                try:
                    mp = self._meta_file(name)
                    if mp.exists():
                        meta = json.loads(mp.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
                if str(meta.get("server_kind", "")).lower() == "steam":
                    
                    continue
                host_port = meta.get("host_port") or MINECRAFT_PORT
                items.append({
                    "id": name,
                    "name": name,
                    "status": status,
                    "type": meta.get("type"),
                    "version": meta.get("version"),
                    "host_port": host_port,
                    "created_at": meta.get("created_at"),
                    "ports": {f"{MINECRAFT_PORT}/tcp": None},
                })
        except Exception as e:
            logger.warning(f"Local list_servers failed: {e}")
        return items
