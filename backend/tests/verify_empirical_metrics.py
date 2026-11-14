import sys
import time
import subprocess
import tempfile
import json
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from runtime_adapter import LocalAdapter
import unittest.mock as mock

def run_empirical_evidence():
    with tempfile.TemporaryDirectory() as td:
        srv_dir = Path(td) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server_meta.json").write_text(
            json.dumps({"max_ram_mb": 2048, "restart_count": 0, "type": "vanilla"}),
            encoding="utf-8"
        )
        worker_code = (
            "import threading, hashlib, time\n"
            "def b():\n"
            "    d = b'x' * 65536\n"
            "    while True:\n"
            "        hashlib.sha256(d)\n"
            "for _ in range(4):\n"
            "    threading.Thread(target=b, daemon=True).start()\n"
            "time.sleep(15)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", worker_code])
        (srv_dir / ".server.pid").write_text(str(proc.pid), encoding="utf-8")
        try:
            time.sleep(0.5)
            adapter = LocalAdapter()
            with mock.patch("runtime_adapter.safe_child_path", return_value=srv_dir), \
                 mock.patch.object(adapter, "get_server_tps", return_value={"tps": 20.0, "mspt": 10.0}):
                stats = adapter.get_server_stats("srv", include_players=False)
                time.sleep(0.2)
                warm = adapter.get_server_stats("srv", include_players=False)
                print(f"VERBATIM_COLD_CPU: {stats['cpu_percent']}")
                print(f"VERBATIM_WARM_CPU: {warm['cpu_percent']}")
                print(f"VERBATIM_WARM_NORMALIZED: {warm['cpu_percent_normalized']}")
                print(f"VERBATIM_ACTIVE_THREADS: {warm['active_threads']}")
                print(f"VERBATIM_PER_CORE_LEN: {len(warm['per_core_cpu'])}")
                nonzero_cores = [(i, c) for i, c in enumerate(warm['per_core_cpu']) if c > 0]
                print(f"VERBATIM_NONZERO_CORES_COUNT: {len(nonzero_cores)}")
                print(f"VERBATIM_TOP_CORES: {nonzero_cores[:8]}")
                print(f"VERBATIM_THREAD_METRICS_COUNT: {len(warm['thread_metrics'])}")
                for t in warm['thread_metrics'][:4]:
                    print(f"  TID: {t['id']} | NAME: {t['name']} | CPU: {t['cpu_percent']}%")
        finally:
            proc.terminate()
            proc.wait(timeout=2.0)

if __name__ == "__main__":
    run_empirical_evidence()
