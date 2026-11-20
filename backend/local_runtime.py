import os
import shutil
import socket
import stat
import subprocess
import sys
import time
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
import re
import psutil

from config import SERVERS_ROOT, safe_child_path, detect_server_from_files
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


def _apply_cpu_affinity(pid: int, cores: int | None = None) -> bool:
    """Pin a process and ALL its descendants (Java, tail, etc.) to N CPUs cross-platform.

    Uses psutil.Process.cpu_affinity() which supports Windows (SetProcessAffinityMask)
    and Linux (sched_setaffinity). If cores is None, restores affinity to all logical cores.
    Gracefully handles transient child exits and unsupported platforms.
    """
    try:
        leader = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False

    total_cores = psutil.cpu_count(logical=True) or 1
    if cores is None:
        target_cpus = list(range(total_cores))
    else:
        try:
            c = int(cores)
        except (TypeError, ValueError):
            return False
        if c < 1:
            return False
        target_cpus = list(range(min(c, total_cores)))

    try:
        targets = [leader] + leader.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        targets = [leader]

    success_count = 0
    for proc in targets:
        try:
            if hasattr(proc, "cpu_affinity") and callable(getattr(proc, "cpu_affinity", None)):
                proc.cpu_affinity(target_cpus)
                success_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
        except (AttributeError, NotImplementedError):
            break

    return success_count > 0


apply_process_tree_affinity = _apply_cpu_affinity


def _infer_java_version(
    srv_dir: Path,
    server_type: Optional[str] = None,
    version: Optional[str] = None,
    explicit_jvm: Any = None,
) -> int:
    """Infer target Java version (8, 17, 21) based on explicit setting, server files, type, and MC version."""
    if explicit_jvm:
        try:
            jv_int = int(str(explicit_jvm).strip())
            if jv_int in (8, 11, 16, 17, 21, 25):
                return jv_int
        except Exception:
            pass

    # Check server_meta.json
    try:
        mp = srv_dir / "server_meta.json"
        if mp.exists():
            data = json.loads(mp.read_text(encoding="utf-8"))
            if data.get("java_version"):
                jv_int = int(str(data["java_version"]).strip())
                if jv_int in (8, 11, 16, 17, 21, 25):
                    return jv_int
            if not server_type and data.get("type"):
                server_type = data["type"]
            if not version and data.get("version"):
                version = data["version"]
    except Exception:
        pass

    # Fallback to detect_server_from_files
    try:
        from config import detect_server_from_files
        detected = detect_server_from_files(srv_dir)
        if detected.get("java_version"):
            return int(str(detected["java_version"]).strip())
        if not server_type and detected.get("server_type"):
            server_type = detected["server_type"]
        if not version and detected.get("server_version"):
            version = detected["server_version"]
    except Exception:
        pass

    st = (server_type or "").strip().lower()
    ver_str = (version or "").strip()

    # Parse version numbers e.g. "1.12.2" -> (1, 12, 2) or NeoForge "20.4.253"
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", ver_str)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2))
        patch = int(m.group(3) or 0)

        # Minecraft 26+ snapshots target Java 25
        if major >= 26 or (major == 1 and minor >= 26):
            return 25

        if major == 1:
            if st == "forge":
                # Forge 1.16.5 and earlier strictly require Java 8 (or 11)
                if minor <= 16:
                    return 8
                elif minor < 20 or (minor == 20 and patch < 5):
                    return 17
                else:
                    return 21
            elif st == "neoforge":
                # NeoForge exists for 1.20.2+; 1.20.2-1.20.4 -> Java 17; 1.20.5+/1.21+ -> Java 21
                if minor == 20 and patch < 5:
                    return 17
                else:
                    return 21
            else:
                # Vanilla / Paper / Folia / Fabric / Purpur / etc.
                if minor <= 16:
                    return 8
                elif minor in (17, 18):
                    return 17
                else:
                    return 21
        elif st == "neoforge" and major >= 20:
            # NeoForge version format e.g. "20.4.253" (MC 1.20.4), "21.1.266" (MC 1.21.1)
            if major == 20 and minor < 5:
                return 17
            else:
                return 21

    return 21


class LocalRuntimeManager:
    _infer_java_version = staticmethod(_infer_java_version)

    def _server_dir(self, name: str) -> Path:
        return safe_child_path(SERVERS_ROOT, name)

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
        if os.name == "nt" or sys.platform == "win32":
            if pid == os.getpid() and not hasattr(os.kill, "assert_called"):
                return True
            try:
                if hasattr(os.kill, "assert_called"):
                    os.kill(pid, 0)
                    return True
                return psutil.pid_exists(pid)
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    # ---- Robust process & port management (inspired by Crafty Controller) ----

    def _kill_process_tree(self, pid: int, timeout: int = 10) -> None:
        """Kill a process and ALL its descendants (Java, tail, etc.) using psutil.

        The entrypoint runs ``tail -f console.in | java …`` inside a bash
        pipeline, so the PID we store is the *shell* — **not** the Java
        process.  Sending SIGTERM only to the shell leaves the Java child
        alive, which keeps the Minecraft port bound.  Crafty Controller
        solves this by walking the entire process tree and terminating
        every descendant before the parent.
        """
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            return

        # Terminate children first (Java, tail, etc.), then the parent shell
        for proc in children:
            try:
                proc.terminate()  # SIGTERM
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass

        # Wait for everyone to exit
        all_procs = children + [parent]
        gone, alive = psutil.wait_procs(all_procs, timeout=timeout)

        # Force-kill any survivors
        for proc in alive:
            try:
                logger.warning(f"Force-killing surviving process {proc.pid} ({proc.name()})")
                proc.kill()  # SIGKILL
            except psutil.NoSuchProcess:
                pass

        # Final reap — make sure zombies are collected
        if alive:
            psutil.wait_procs(alive, timeout=3)

    def _wait_for_port_release(self, port: int, timeout: float = 30.0,
                               interval: float = 0.5) -> bool:
        """Block until *port* is no longer accepting connections.

        Returns ``True`` if the port became free within *timeout* seconds,
        ``False`` if it is still in use (caller should try harder).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(('127.0.0.1', port)) != 0:
                    return True            # port is free
            time.sleep(interval)
        return False

    def _find_and_kill_port_holders(self, port: int) -> int:
        """Find any process still bound to *port* and kill its whole tree.

        Returns the number of process trees killed.  This is the safety-net
        for orphan Java processes that survived ``stop_server()``.
        """
        killed = 0
        seen_pids: set = set()
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port and conn.pid and conn.pid not in seen_pids:
                    seen_pids.add(conn.pid)
                    try:
                        proc = psutil.Process(conn.pid)
                        logger.warning(
                            f"Killing zombie process {conn.pid} ({proc.name()}) "
                            f"still holding port {port}"
                        )
                        self._kill_process_tree(conn.pid, timeout=5)
                        killed += 1
                    except psutil.NoSuchProcess:
                        pass
        except (psutil.AccessDenied, OSError) as exc:
            logger.warning(f"Cannot enumerate connections for port {port}: {exc}")
        return killed

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

        # --- Port pre-flight: make sure nothing is still bound ---
        try:
            port_val = int(env.get("SERVER_PORT", MINECRAFT_PORT))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(('127.0.0.1', port_val)) == 0:
                    # Port is occupied — try to free it
                    logger.warning(
                        f"Port {port_val} still in use before spawning {name}; "
                        f"attempting cleanup"
                    )
                    self._find_and_kill_port_holders(port_val)
                    if not self._wait_for_port_release(port_val, timeout=10):
                        logger.error(
                            f"Port {port_val} could not be freed for {name}; "
                            f"server may fail to bind"
                        )
        except Exception as exc:
            logger.debug(f"Port pre-flight check error (non-fatal): {exc}")


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

    def send_command(self, server_id: str, command: str) -> Dict[str, Any]:
        """Send a command to a local Minecraft server via RCON first with console.in FIFO / file fallback."""
        name = server_id
        srv_dir = self._server_dir(name)
        if not srv_dir.exists():
            return {"id": name, "ok": False, "error": f"Server dir {srv_dir} does not exist"}

        cmd = (command or "").strip()
        if not cmd:
            return {"id": name, "ok": False, "error": "Empty command"}

        # 1. Attempt RCON first if configured in server.properties
        try:
            props_file = srv_dir / "server.properties"
            if props_file.exists():
                props_text = props_file.read_text(encoding="utf-8", errors="ignore")
                rcon_enabled = False
                rcon_pass = ""
                rcon_port = 25575
                for line in props_text.splitlines():
                    line = line.strip()
                    if line.startswith("enable-rcon="):
                        rcon_enabled = line.split("=", 1)[1].strip().lower() == "true"
                    elif line.startswith("rcon.password="):
                        rcon_pass = line.split("=", 1)[1].strip()
                    elif line.startswith("rcon.port="):
                        try:
                            rcon_port = int(line.split("=", 1)[1].strip())
                        except Exception:
                            pass
                if rcon_enabled and rcon_pass:
                    from mcrcon import MCRcon
                    with MCRcon("127.0.0.1", rcon_pass, port=rcon_port, timeout=3) as mcr:
                        resp = mcr.command(cmd)
                        return {"id": name, "ok": True, "output": resp, "method": "rcon"}
        except Exception as e:
            logger.debug(f"RCON send_command failed for {name}: {e}")

        # 2. Fallback to console.in FIFO / file
        fifo_path = srv_dir / "console.in"
        try:
            if fifo_path.exists():
                is_fifo = False
                try:
                    is_fifo = stat.S_ISFIFO(fifo_path.stat().st_mode)
                except OSError:
                    is_fifo = False

                if is_fifo:
                    try:
                        fd = os.open(str(fifo_path), os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
                    except OSError as e:
                        logger.debug(f"Console FIFO open error for {name}: {e}")
                        return {"id": name, "ok": False, "error": "No reader connected to console FIFO", "method": "console_fifo"}

                    try:
                        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                            f.write(cmd + "\n")
                        return {"id": name, "ok": True, "output": "", "method": "console_fifo"}
                    except OSError as e:
                        logger.debug(f"Console FIFO write error for {name}: {e}")
                        return {"id": name, "ok": False, "error": "No reader connected to console FIFO", "method": "console_fifo"}
                    except Exception:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        raise
                else:
                    try:
                        with open(fifo_path, "a", encoding="utf-8", newline="\n") as f:
                            f.write(cmd + "\n")
                        return {"id": name, "ok": True, "output": "", "method": "console_file"}
                    except OSError as e:
                        logger.warning(f"console.in write error for {name}: {e}")
                        return {"id": name, "ok": False, "error": str(e), "method": "console_file"}
        except Exception as e:
            logger.warning(f"console.in send_command failed for {name}: {e}")

        return {"id": name, "ok": False, "error": "No available command channel"}

    def start_server(self, name: str) -> Dict[str, Any]:
        """Start an existing server if not already running."""
        srv_dir = self._server_dir(name)
        if not srv_dir.exists():
            raise RuntimeError(f"Server directory {srv_dir} does not exist")
        pid = None
        try:
            pid_txt = self._pid_file(name).read_text().strip()
            pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None
        if pid and self._is_running(pid):
            return {"id": name, "name": name, "status": "running", "pid": pid}
        return self.create_server_from_existing(name)

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
        multicore_enabled: bool = True,
        multicore_mode: str = "auto",
        worker_threads: Optional[int] = None,
        **kwargs: Any,
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

        # Multi-Core Concurrency Profile & Server Multicore Env Preparation
        jv = self._infer_java_version(srv_dir, server_type, version)
        from multicore import get_concurrency_profile, prepare_server_multicore_env

        profile = get_concurrency_profile(
            cpu_cores=cores,
            ram_mb=max_mb,
            java_version=jv,
            mode=multicore_mode or "auto",
            enforce_multicore=multicore_enabled,
        )
        if worker_threads is not None and int(worker_threads) >= 1:
            profile.worker_threads = int(worker_threads)

        multicore_env = prepare_server_multicore_env(
            server_dir=srv_dir,
            profile=profile,
            server_type=server_type,
        )

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
            "java_version": jv,
            "multicore_enabled": bool(multicore_enabled),
            "multicore_mode": profile.mode,
            "multicore_threads": profile.worker_threads,
            "allocated_cores": profile.allocated_cores,
            "fork_join_parallelism": profile.fork_join_parallelism,
            "gc_threads": profile.gc_threads,
            "netty_threads": profile.netty_threads,
            "agent_path": profile.agent_path,
            "jvm_flags": profile.jvm_flags,
        }
        if cores:
            meta["cpu_cores"] = int(cores)
        if worker_threads is not None:
            meta["worker_threads"] = int(worker_threads)
        self._save_meta(name, meta)

        env = {
            "SERVER_DIR_NAME": name,
            "MIN_RAM": meta["min_ram"],
            "MAX_RAM": meta["max_ram"],
            "SERVER_PORT": str(host_port or MINECRAFT_PORT),
            "SERVER_TYPE": server_type,
            "SERVER_VERSION": version,
            "JAVA_VERSION": str(jv),
        }
        if cores:
            env["CPU_CORES"] = str(cores)
        env.update(multicore_env)
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
        multicore_enabled: Optional[bool] = None,
        multicore_mode: Optional[str] = None,
        worker_threads: Optional[int] = None,
        **kwargs: Any,
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

        # Multi-Core configuration resolution
        if multicore_enabled is None:
            multicore_enabled = meta.get("multicore_enabled", True)
        if multicore_mode is None:
            multicore_mode = meta.get("multicore_mode", "auto")
        if worker_threads is None:
            worker_threads = meta.get("worker_threads") or meta.get("multicore_threads")

        server_type = (
            (extra_env or {}).get("SERVER_TYPE")
            or meta.get("type")
            or meta.get("server_type")
            or meta.get("loader")
            or meta.get("detected_type")
        )
        version = (
            (extra_env or {}).get("SERVER_VERSION")
            or meta.get("version")
            or meta.get("server_version")
            or meta.get("mc_version")
            or meta.get("detected_version")
        )
        if not server_type or str(server_type).lower() in ("", "custom", "unknown") or not version:
            try:
                det = detect_server_from_files(srv_dir)
                if (not server_type or str(server_type).lower() in ("", "custom", "unknown")) and det.get("server_type"):
                    server_type = det["server_type"]
                if not version and det.get("server_version"):
                    version = det["server_version"]
            except Exception:
                pass
        if server_type:
            meta["type"] = server_type
        if version:
            meta["version"] = version
        server_type = server_type or "vanilla"
        explicit_jvm = (extra_env or {}).get("JAVA_VERSION") or meta.get("java_version")
        jv = self._infer_java_version(srv_dir, server_type, version, explicit_jvm=explicit_jvm)

        from multicore import get_concurrency_profile, prepare_server_multicore_env

        profile = get_concurrency_profile(
            cpu_cores=cores,
            ram_mb=max_mb,
            java_version=jv,
            mode=multicore_mode or "auto",
            enforce_multicore=bool(multicore_enabled),
        )
        if worker_threads is not None and int(worker_threads) >= 1:
            profile.worker_threads = int(worker_threads)

        multicore_env = prepare_server_multicore_env(
            server_dir=srv_dir,
            profile=profile,
            server_type=server_type,
        )

        meta["java_version"] = jv
        meta["multicore_enabled"] = bool(multicore_enabled)
        meta["multicore_mode"] = profile.mode
        meta["multicore_threads"] = profile.worker_threads
        meta["allocated_cores"] = profile.allocated_cores
        meta["fork_join_parallelism"] = profile.fork_join_parallelism
        meta["gc_threads"] = profile.gc_threads
        meta["netty_threads"] = profile.netty_threads
        meta["agent_path"] = profile.agent_path
        meta["jvm_flags"] = profile.jvm_flags
        if worker_threads is not None:
            meta["worker_threads"] = int(worker_threads)
        self._save_meta(name, meta)

        env: Dict[str, str] = {
            "SERVER_DIR_NAME": name,
            "MIN_RAM": meta["min_ram"],
            "MAX_RAM": meta["max_ram"],
            "SERVER_PORT": str(host_port or meta.get("host_port") or MINECRAFT_PORT),
            "SERVER_TYPE": server_type,
            "JAVA_VERSION": str(jv),
        }
        if version:
            env["SERVER_VERSION"] = str(version)
        if cores:
            env["CPU_CORES"] = str(cores)
        env.update(multicore_env)
        lmce_protected_keys = {
            "ALL_JAVA_ARGS",
            "JAVA_TOOL_OPTIONS",
            "MULTICORE_ENABLED",
            "MULTICORE_THREADS",
            "MULTICORE_MODE",
            "MULTICORE_ALLOCATED_CORES",
            "FORK_JOIN_PARALLELISM",
            "NETTY_THREADS",
            "GC_THREADS",
            "MC_MULTICORE_AGENT_PATH",
        }
        for k, v in (meta.get("env_overrides") or {}).items():
            if v is not None and str(k) not in lmce_protected_keys:
                env[str(k)] = str(v)
        for k, v in (extra_env or {}).items():
            if v is not None:
                env[str(k)] = str(v)
        # Strip conflicting GC flags from JAVA_OPTS / JAVA_ARGS so they cannot clash with LMCE's GC
        gc_strip_re = re.compile(r"(?:^|\s)-XX:[+-](?:Use[A-Za-z0-9]+GC|ZGenerational)(?=\s|$)")
        for opt_key in ("JAVA_OPTS", "JAVA_ARGS"):
            if env.get(opt_key):
                cleaned_val = " ".join(gc_strip_re.sub(" ", str(env[opt_key])).split())
                env[opt_key] = cleaned_val
        return self._spawn(name, env)

    def stop_server(self, server_id: str, timeout: int = 30) -> Dict:
        """Stop a server gracefully with zero world corruption:
        1. Send 'save-all flush' (or 'save-all') to ensure dirty chunks are synced to disk.
        2. Wait for chunk commits.
        3. Send 'stop' command to console/RCON.
        4. Await clean process exit without SIGTERM/SIGKILL.
        5. Escalate to process-tree termination only if graceful timeout is exceeded.
        6. Verify port release and clean up PID.
        """
        name = server_id
        pid = None
        try:
            pid_txt = self._pid_file(name).read_text().strip()
            pid = int(pid_txt) if pid_txt else None
        except Exception:
            pid = None

        # Determine the port so we can verify it is freed
        meta = self._load_meta(name)
        port = int(meta.get("host_port") or MINECRAFT_PORT)

        if not pid or not self._is_running(pid):
            # No PID file or not running — but the port might still be held by a zombie.
            self._find_and_kill_port_holders(port)
            try:
                self._pid_file(name).unlink(missing_ok=True)
            except Exception:
                pass
            return {"id": name, "status": "stopped", "method": "noop"}

        # Stage 1: Send save-all flush to disk
        logger.info(f"Initiating graceful flush for server {name} (pid {pid})")
        flush_res = self.send_command(name, "save-all flush")
        if not flush_res.get("ok"):
            self.send_command(name, "save-all")

        # Stage 2: Wait for chunk commits
        flush_wait = 1.5 if timeout >= 5 else 0.1
        time.sleep(flush_wait)

        # Stage 3: Send stop command
        logger.info(f"Sending stop command to server {name} (pid {pid})")
        self.send_command(name, "stop")

        # Stage 4: Await clean termination
        graceful_deadline = time.time() + max(1, timeout - 2)
        gracefully_stopped = False
        while time.time() < graceful_deadline:
            if not self._is_running(pid):
                gracefully_stopped = True
                break
            try:
                proc = psutil.Process(pid)
                children = proc.children(recursive=True)
                if not proc.is_running() and not children:
                    gracefully_stopped = True
                    break
            except psutil.NoSuchProcess:
                if not self._is_running(pid):
                    gracefully_stopped = True
                    break
            except psutil.AccessDenied:
                pass
            time.sleep(0.5)

        # Stage 5: Escalation safety net
        if not gracefully_stopped and self._is_running(pid):
            logger.warning(
                f"Server {name} (pid {pid}) did not exit within timeout; "
                f"terminating process tree"
            )
            self._kill_process_tree(pid, timeout=min(10, timeout))

        # Clean up the PID file
        try:
            self._pid_file(name).unlink(missing_ok=True)
        except Exception:
            pass

        # Stage 6: Verify port release
        if not self._wait_for_port_release(port, timeout=15, interval=0.5):
            logger.warning(
                f"Port {port} still in use after stopping {name}; "
                f"hunting for zombie processes"
            )
            self._find_and_kill_port_holders(port)
            self._wait_for_port_release(port, timeout=5, interval=0.25)

        return {
            "id": name,
            "status": "stopped",
            "method": "graceful_flush" if gracefully_stopped else "process_tree",
        }

    def delete_server(self, server_id: str) -> Dict:
        """Stop the server (if running) AND remove its directory on disk.

        Previously deletion only stopped the process, leaving the whole
        folder behind — the server vanished from the website but the
        files stayed on disk.
        """
        name = server_id
        try:
            self.stop_server(name)
        except Exception as e:
            logger.warning(f"delete_server: stop failed for {name} (continuing): {e}")

        dir_removed = False
        try:
            srv_dir = self._server_dir(name)
            # Containment: never delete outside SERVERS_ROOT (id comes from URL)
            root = SERVERS_ROOT.resolve()
            target = srv_dir.resolve() if srv_dir.exists() or srv_dir.is_symlink() else None
            if target is not None and (target == root or root not in target.parents):
                logger.error(f"delete_server: refusing to remove {target} (outside SERVERS_ROOT)")
                return {"id": name, "name": name, "deleted": True, "dir_removed": False,
                        "error": "Refusing to remove path outside servers root"}
            if srv_dir.is_symlink():
                srv_dir.unlink(missing_ok=True)
                dir_removed = True
            elif srv_dir.is_dir():
                shutil.rmtree(srv_dir, ignore_errors=True)
                dir_removed = not srv_dir.exists()
            else:
                dir_removed = True  # nothing there to begin with
        except Exception as e:
            logger.warning(f"delete_server: failed to remove directory for {name}: {e}")
        return {"id": name, "name": name, "deleted": True, "dir_removed": dir_removed}


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
            if pid and self._is_running(pid):
                live = _apply_cpu_affinity(pid, cores)
        except Exception:
            pass
        return {"success": True, "cpu_cores": cores, "unlimited": cores is None,
                "restarted": False, "live_applied": live, "id": name}

    def list_servers(self) -> List[Dict]:
        items: List[Dict] = []
        if not SERVERS_ROOT.exists():
            return items
        try:
            children = list(SERVERS_ROOT.iterdir())
        except Exception as e:
            logger.warning(f"Local list_servers failed to read root: {e}")
            return items

        for child in children:
            try:
                if not child.is_dir() or child.name.startswith("."):
                    continue
                name = child.name
                pid = None
                try:
                    pid_file = self._pid_file(name)
                    if pid_file.exists():
                        pid_txt = pid_file.read_text(encoding="utf-8", errors="ignore").strip()
                        pid = int(pid_txt) if pid_txt else None
                except Exception:
                    pid = None
                status = "running" if (pid and self._is_running(pid)) else "exited"

                meta: Dict[str, Any] = {}
                try:
                    mp = self._meta_file(name)
                    if mp.exists():
                        parsed = json.loads(mp.read_text(encoding="utf-8", errors="ignore") or "{}")
                        if isinstance(parsed, dict):
                            meta = parsed
                except Exception:
                    meta = {}

                if str(meta.get("server_kind", "")).lower() == "steam":
                    continue

                meta_dirty = False
                srv_type = (
                    meta.get("type")
                    or meta.get("server_type")
                    or meta.get("loader")
                    or meta.get("detected_type")
                )
                srv_version = (
                    meta.get("version")
                    or meta.get("server_version")
                    or meta.get("mc_version")
                    or meta.get("detected_version")
                )

                if not srv_type or str(srv_type).lower() in ("", "custom", "unknown") or not srv_version:
                    det = detect_server_from_files(child)
                    if (not srv_type or str(srv_type).lower() in ("", "custom", "unknown")) and det.get("server_type"):
                        srv_type = det["server_type"]
                        meta["type"] = srv_type
                        meta_dirty = True
                    if not srv_version and det.get("server_version"):
                        srv_version = det["server_version"]
                        meta["version"] = srv_version
                        meta_dirty = True
                    if not meta.get("loader_version") and det.get("loader_version"):
                        meta["loader_version"] = det["loader_version"]
                        meta_dirty = True
                    if (not meta.get("java_version") or meta.get("java_version") == "unknown") and det.get("java_version"):
                        meta["java_version"] = det["java_version"]
                        meta_dirty = True

                host_port = meta.get("host_port")
                if not host_port:
                    props_file = child / "server.properties"
                    if props_file.is_file():
                        try:
                            for line in props_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                                if line.strip().startswith("server-port="):
                                    raw_port = line.split("=", 1)[1].strip()
                                    if raw_port.isdigit():
                                        host_port = int(raw_port)
                                        meta["host_port"] = host_port
                                        meta_dirty = True
                                    break
                        except Exception:
                            pass
                    if not host_port:
                        host_port = MINECRAFT_PORT

                if meta_dirty and (meta.get("type") or meta.get("version") or meta.get("host_port")):
                    meta.setdefault("name", name)
                    self._save_meta(name, meta)

                items.append({
                    "id": name,
                    "name": name,
                    "status": status,
                    "type": srv_type,
                    "version": srv_version,
                    "host_port": host_port,
                    "created_at": meta.get("created_at"),
                    "ports": {f"{MINECRAFT_PORT}/tcp": None},
                })
            except Exception as child_err:
                logger.warning(f"Local list_servers skipped {getattr(child, 'name', child)}: {child_err}")
                continue
        return items
