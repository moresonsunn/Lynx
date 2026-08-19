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