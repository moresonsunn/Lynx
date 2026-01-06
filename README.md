# Lynx – Game Server Manager

![GitLab CI](https://gitlab.com/kyzen4/lynx/badges/main/pipeline.svg)
![GitHub CI](https://github.com/moresonsunn/Lynx/actions/workflows/ci.yml/badge.svg)
![Docker Pulls](https://img.shields.io/docker/pulls/moresonsun/lynx)
![Architecture](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-blue)

Lynx is a modern web-based controller to create, manage, monitor, and automate **Minecraft** and **Steam game servers** using Docker containers. Inspired by Crafty but expanded to support 70+ games:
- Fast, preload-first UI (React + Tailwind)
- **Minecraft**: Vanilla, Paper, Purpur, Fabric, Forge, NeoForge with automatic Java version selection
- **Steam games**: Valheim, Rust, ARK, Terraria, Palworld, Counter-Strike, and 70+ more
- Declarative server creation with loader + installer resolution
- Efficient file operations (streaming uploads, zip/unzip, optimistic UI, ETag cache busting)
- Colored live console with reset-on-power events
- Role & permission management (users, roles, audit logs)
- REST API + future extensibility

## Supported Games

### Minecraft Server Types
| Type | Description |
|------|-------------|
| Vanilla | Official Mojang server |
| Paper | High-performance Spigot fork |
| Purpur | Paper fork with extra features |
| Fabric | Lightweight modding platform |
| Forge | Classic modding platform |
| NeoForge | Modern Forge continuation |

### Steam Games (70+ Supported)
Deploy dedicated servers for popular Steam games including:

| Survival & Sandbox | Shooters & Tactical | Coop & Other |
|-------------------|---------------------|--------------|
| Valheim | Counter-Strike 2 / CS:GO | Terraria |
| Rust | Hell Let Loose | Don't Starve Together |
| ARK: Survival Evolved | Ready or Not | VRChat |
| The Forest / Sons of the Forest | Insurgency: Sandstorm | Project Zomboid |
| Palworld | Squad | Satisfactory |
| V Rising | Arma 3 | Core Keeper |
| 7 Days to Die | Pavlov VR | Stardew Valley |
| Enshrouded | DayZ | Factorio |
| Astroneer | Unturned | Barotrauma |

See the full catalog: [backend/data/steam_games/extended_catalog.json](backend/data/steam_games/extended_catalog.json)

---

Single Docker image (multi-arch: linux/amd64 + linux/arm64) is published (default namespace: `moresonsun`):
- Image (controller + UI + embedded multi-Java runtime): `moresonsun/lynx:latest`

Brand / Org Override: set `DOCKERHUB_NAMESPACE=lynx` (or explicitly set `DOCKERHUB_REPO` / `DOCKERHUB_RUNTIME_REPO`) in CI to publish under a dedicated namespace without code changes.

GitLab Container Registry (when pipeline runs with `GITLAB_PUSH=true`):
- Controller: `registry.gitlab.com/kyzen4/lynx/lynx:latest`


Release tags (when pushing annotated git tags like `v0.1.0`) will also publish versioned images once available.

## Core Features

### General
- Create / start / stop / restart / kill game servers
- Port suggestion & validation endpoints
- Live resource stats & player info (aggregated polling)
- Backup create/restore (zip snapshot)
- File manager: upload (files/folders), download, zip/unzip, rename, delete
- ANSI-colored console output with reset between power cycles
- User authentication, roles, permissions, audit logging
- Monitoring endpoints (system health, dashboard data, alerts)

### Minecraft-Specific
- Multi server types: Vanilla, Paper, Purpur, Fabric, Forge, NeoForge
- Dynamic version/loader fetching from official APIs
- Automatic Java version selection (Java 8, 11, 17, 21)
- Modpack installation from CurseForge and Modrinth
- Automatic server-icon detection & normalization

### Steam Games
- 70+ preconfigured game templates
- One-click server deployment using community Docker images
- Automatic port configuration per game
- Environment variable customization
- CasaOS integration (install as v2 compose apps)

## Tech Stack
- Backend: Python (FastAPI, SQLAlchemy, Docker SDK)
- Frontend: React 18 + Tailwind CSS
- Images: Multi-stage Docker builds (controller + runtime)
- Storage: Host bind or named volume at `data/servers/<server_name>`
- DB: Postgres (in CI) / can fallback to SQLite (if configured separately)

## Project Structure
```
Lynx/
  backend/
  frontend/
  docker/
  docker-compose.yml
```

## Local Dev
- Backend: `cd backend && pip install -r requirements.txt && uvicorn app:app --reload`
- Frontend: `cd frontend && npm install && npm start`

## Quick Start (Docker Compose)

### One-Line Installation (Recommended)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

### Platform-Specific Instructions

#### 🍎 macOS (Docker Desktop)

**Prerequisites:**
1. Install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
   - Apple Silicon (M1/M2/M3): Download the Apple chip version
   - Intel Mac: Download the Intel chip version
2. Start Docker Desktop and wait for it to fully initialize (whale icon stops animating)
3. Allocate at least 4GB RAM in Docker Desktop → Settings → Resources

**Install Lynx:**
```bash
# Quick install (latest release)
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash

# Or with specific version
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash -s -- -v v0.1.1

# Or manual install
mkdir lynx && cd lynx
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

**macOS Notes:**
- Data is stored in Docker volumes, viewable in Docker Desktop → Volumes
- Apple Silicon Macs use ARM64 images (automatically selected)
- If you see "protocol not available", restart Docker Desktop

---

#### 🪟 Windows (Docker Desktop)

**Prerequisites:**
1. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
   - Windows 10/11 Home: Requires WSL2 backend
   - Windows 10/11 Pro/Enterprise: Can use Hyper-V or WSL2
2. If using WSL2, ensure it's installed: `wsl --install` in Admin PowerShell
3. Start Docker Desktop and wait for it to fully initialize
4. Allocate at least 4GB RAM in Docker Desktop → Settings → Resources → WSL Integration

**Install Lynx (PowerShell):**
```powershell
# Quick install (latest release)
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex

# Or with specific version
$env:Version='v0.1.1'; irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex

# Or manual install
mkdir lynx; cd lynx
Invoke-WebRequest -Uri https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -OutFile docker-compose.yml
docker compose pull
docker compose up -d
```

**Windows Notes:**
- Use PowerShell 5.1+ or PowerShell Core 7+
- Data is stored in Docker volumes (WSL2 filesystem for best performance)
- If you see permission errors, run PowerShell as Administrator
- WSL2 backend recommended for better performance

---

#### 🐧 Linux (Docker Engine)

**Prerequisites:**
```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect

# Verify installation
docker --version
docker compose version
```

**Install Lynx:**
```bash
# Quick install (latest release)
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash

# Or with specific version
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash -s -- -v v0.1.1

# Or manual install
mkdir lynx && cd lynx
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

**Linux Notes:**
- Supports both amd64 and arm64 architectures
- Raspberry Pi 4+ (64-bit OS) is supported
- Rootless Docker is supported but may require additional configuration

---

### After Installation

1. **Access Lynx:** Open http://localhost:8000 in your browser
2. **Default Login:** admin / admin123 (change immediately!)
3. **Create your first server:** Click "New Server" and select a type

### Useful Commands

```bash
# View logs
docker compose logs -f

# Stop Lynx
docker compose down

# Update to latest version
docker compose pull
docker compose up -d

# Full cleanup (removes data!)
docker compose down -v
```

### Docker Hub Images

Lynx images are published to Docker Hub under `moresonsun/lynx`:

| Tag | Description |
|-----|-------------|
| `moresonsun/lynx:latest` | Latest stable release |
| `moresonsun/lynx:v0.1.1` | Specific version |
| `moresonsun/lynx:edge` | Development builds |

Multi-arch support: `linux/amd64` and `linux/arm64`

```bash
# Pull specific version
docker pull moresonsun/lynx:v0.1.1

# Pull for specific platform
docker pull --platform linux/arm64 moresonsun/lynx:latest
```

---

### Legacy Method

1. Clone repo (optional if just using images):
```
git clone https://github.com/moresonsunn/Lynx.git
cd Lynx
```
2. Pull image:
```
docker pull moresonsun/lynx:latest
```
3. (Optional) Adjust `docker-compose.yml` to pin a version tag instead of :latest.
4. Launch (build locally if modifying sources):
```
docker compose up -d --build
```
5. Open: http://localhost:8000

Data persists under `./data/servers/` (or mapped volume). Each server runs in its own container created by the controller using the runtime image.

## Local Development
Build unified image locally:
```
docker build -t lynx:dev -f docker/controller-unified.Dockerfile .
```
Run:
```
docker compose up -d --build
```

## Troubleshooting: `protocol not available` During `docker compose up --build`
On some Docker Desktop / Windows setups, especially when BuildKit or buildx integration is in a transient state, you may see an immediate `protocol not available` with a 0/0 build graph.

Common causes & fixes:
- BuildKit temporarily unhappy / stale builder context.
  Fix: Restart Docker Desktop OR run:
  ```
  docker buildx inspect --bootstrap
  docker buildx ls
  ```
- Disabled BuildKit via environment variables (`DOCKER_BUILDKIT=0` or `COMPOSE_DOCKER_CLI_BUILD=0`). These disable optimized builds and can surface obscure errors.
  Fix: Remove or unset those vars in your shell and retry.
- Outdated Docker Desktop (older Compose versions had occasional WSL2 socket glitches).
  Fix: Update Docker Desktop.
- Corrupted buildx builder instance.
  Fix:
  ```
  docker buildx rm lynxx  # or the failing builder name
  docker buildx create --name lynxx --use
  docker buildx inspect --bootstrap
  ```
- WSL2 backend networking hiccup (less common now).
  Fix: `wsl --shutdown` from an elevated PowerShell, then restart Docker Desktop.

If the error occurs only with the dev override + `--build` but manual `docker build` works:
1. Ensure BuildKit is enabled (unset `DOCKER_BUILDKIT` or set it to `1`).
2. Run a manual build once (as you did) to populate the local image, then `docker compose ... up -d` without `--build` while you diagnose.
3. Run `docker compose config` to confirm the merged file shows the expected `lynx-dev-controller:latest` image and not the remote one.

If problems persist, capture:
```
docker version
docker buildx ls
docker compose version
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```
And open an issue with that output.

## Environment Variables

## Environment Variables
| Variable | Purpose | Default |
|----------|---------|---------|
| APP_NAME | Branding for UI/backend `/branding` | Lynx |
| APP_VERSION | Optional version string exposed at `/branding` | 0.1.0 |
| SERVERS_CONTAINER_ROOT | Container path for servers data | /data/servers |
| SERVERS_HOST_ROOT | Absolute host path (for bind mapping) | (inferred) |
| SERVERS_VOLUME_NAME | Named volume (if using volumes) | minecraft-server_mc_servers_data |
| CASAOS_API_BASE | CasaOS AppManagement API base for v2 compose installs (Steam servers) | (auto-probed) |
| CASAOS_API_TOKEN | CasaOS auth token used as `Authorization` header for API calls | (unset) |

Frontend build-time override: set `REACT_APP_APP_NAME` to change displayed branding.

## Branding Endpoint
`GET /branding` returns `{ "name": APP_NAME, "version": APP_VERSION }` to allow dynamic frontend adaptation.

## Building Image Manually
```
docker build -t lynx:dev -f docker/controller-unified.Dockerfile .
```

### Publishing the unified `latest` tag
Runtime container launches default to the `moresonsun/lynx:latest` image. Build and push that tag whenever you cut a release so modpack installs and containerized servers can start without manual rebuilds:
```
docker build -t moresonsun/lynx:latest -f docker/controller-unified.Dockerfile .
docker push moresonsun/lynx:latest
```
If you publish additional versioned tags (for example `v0.1.1`), push them alongside `latest`, but keep `latest` updated to the newest stable build.

## Multi-Arch Notes
The CI workflow uses `docker/setup-buildx-action` and `docker/build-push-action` to publish `linux/amd64, linux/arm64` manifests. Local multi-arch emulate build example:
```
docker buildx create --name bp --use
docker buildx build -f docker/controller-unified.Dockerfile -t moresonsun/lynx:test --platform linux/amd64,linux/arm64 --push .
```

## Releasing
Push an annotated git tag starting with `v` (e.g. `v0.1.0`) to trigger version-tagged unified image publish:
```
git tag -a v0.1.0 -m "v0.1.0"
git push --tags
```

## GitLab Mirror / Dual-Registry Workflow

Push to GitHub (primary) and mirror to GitLab (or add GitLab as a second remote) to leverage both registries:
```
git remote add gitlab https://gitlab.com/kyzen4/lynx.git
git push gitlab main
```
Set GitLab CI/CD variables:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- (optional) `GITLAB_PUSH=true` to publish images to `registry.gitlab.com/kyzen4/lynx/*`.

Run a tagged release on either platform (`vX.Y.Z`) to produce versioned images in both registries.

Pulling by version:
```
docker pull moresonsun/lynx:v0.1.1
```
## Namespace & Branding Strategy

Current Docker Hub default namespace: `moresonsun`. If you publish under a different org, set `DOCKERHUB_NAMESPACE` in CI.

## Roadmap (Excerpt)
- Websocket or SSE live logs (reduce polling)
- Template/modpack catalog UI enhancements
- Advanced metrics (prometheus style endpoint)
- Plugin & mod marketplace integration
- Automatic port range reservation and conflict resolution

## CasaOS Deployment

The unified image is optimized for CasaOS by exposing only the panel/API port (8000) and optionally a single default server port (25565). Avoid mapping large static port ranges; runtime containers will dynamically bind Minecraft ports as you create servers.

### Add Custom Store
Add the raw URL to `casaos-appstore/index.json` as a custom source in CasaOS, then install "Lynx (Unified)".

### Import Existing Server
1. Stop any legacy standalone Minecraft container.
2. Copy its world/server directory into the Lynx servers volume (visible in the unified container at `/data/servers/<name>`).
3. Call `POST /api/servers/import` with `{ "name": "<name>" }` (optionally `host_port`, `java_version`).
4. Start the server from the UI.

### CasaOS Token + Base API (for Steam as CasaOS v2 Apps)

Steam servers can be installed as CasaOS v2 *compose apps* (so they don't show up as "Legacy-App" containers). To enable this, Lynx needs:

- `CASAOS_API_TOKEN`: CasaOS auth token (copied from the browser)
- `CASAOS_API_BASE`: CasaOS AppManagement base URL (usually `http://<casaos-ip>/v2/app_management`)

**How to get `CASAOS_API_TOKEN` (fastest method)**
1. Open CasaOS in your browser and sign in.
2. Press `F12` → open **Network**.
3. Refresh the page.
4. Click any request to your CasaOS host (for example `/v2/...`).
5. In **Request Headers**, copy the full `authorization` header value.

The value is typically a JWT that looks like `eyJhbGciOi...` (no extra prefix). Paste it into `CASAOS_API_TOKEN`.

**How to choose `CASAOS_API_BASE`**
- If the controller container can reach CasaOS via LAN IP, use:
  - `http://<casaos-ip>/v2/app_management`
- If the controller runs on the same Docker host and LAN routing is restricted, use:
  - `http://172.17.0.1/v2/app_management`

If `CASAOS_API_BASE` is not set, Lynx will probe common defaults (`host.docker.internal`, `gateway.docker.internal`, then `172.17.0.1`).

**Security note**
Treat `CASAOS_API_TOKEN` like a password. If you pasted it into chat/logs, rotate it (log out / re-login) and update the env var.

### Hiding Steam Servers From CasaOS

If Steam servers are created on the **same Docker engine** CasaOS uses, CasaOS can still list them under **Legacy Apps / Docker** even if you set `io.casaos.*` labels.

To keep Steam servers visible only inside Lynx, run Steam containers on a **different Docker engine** and point Lynx at it:

- `STEAM_DOCKER_HOST`: Docker daemon URL used *only* for Steam servers (example: `tcp://<remote-docker-host>:2375`).

This is the only reliable approach because CasaOS enumerates containers from its Docker engine.

**No separate machine? (Single-host option)**

Use a Docker-in-Docker sidecar as the Steam engine:

- Run a `docker:dind` container in `network_mode: host` and `privileged: true`
- Expose its daemon on `tcp://0.0.0.0:23750`
- Mount the same `/data/servers` path into it so Steam containers can bind-mount server data
- Set Lynx: `STEAM_DOCKER_HOST=tcp://172.17.0.1:23750`

The CasaOS appstore manifest for the unified app includes an example `steam_engine` service wired this way.

### Environment Quick Reference
| Variable | Purpose |
|----------|---------|
| ADMIN_PASSWORD | Sets/overrides admin password at startup (>=8 chars) |
| ALLOWED_ORIGIN_REGEX | Broad CORS (use `.*` initially, tighten later) |
| LYNX_RUNTIME_IMAGE/TAG | Image & tag used for spawned runtime servers (legacy: `BLOCKPANEL_RUNTIME_IMAGE/TAG`) |
| STEAM_DOCKER_HOST | Optional separate Docker engine for Steam servers (keeps them out of CasaOS) |
| SERVERS_VOLUME_NAME | Docker volume name for servers data |
| SERVERS_CONTAINER_ROOT | In-container path for servers (default `/data/servers`) |

### Troubleshooting on CasaOS
| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Legacy flag shown | Too many mapped ports / old manifest | Use pruned `app.json` (only 8000 & 25565) |
| Servers fail to start | Docker socket missing | Mount `/var/run/docker.sock` |
| CORS errors for logs/files | Origin mismatch | Set `ALLOWED_ORIGIN_REGEX=.*` temporarily |
| Port mismatch in UI | Wide pre-mapped range consumed | Remove static range; specify `host_port` per server if needed |

### Dynamic Host Ports
If you omit `host_port` on server creation the controller finds the next free port by inspecting Docker mappings. Use `GET /api/ports/suggest` before creation or specify a desired port (validated with `GET /api/ports/validate`).

### Security Notes
- Change `ADMIN_PASSWORD` immediately after first run.
- Replace `SECRET_KEY` in production for JWT/session integrity.
- Limit `ALLOWED_ORIGIN_REGEX` to specific origins once stable.


## Contributing
PRs and issues welcome. Keep changes small & focused. Include reproduction steps for bug reports.

## License
Currently unlicensed (all rights reserved) unless updated. Add a LICENSE file before public distribution if desired.

> Ultra-Quick Install (Controller only, ephemeral DB fallback)
>
> 1. Pull image (or rely on on-demand pull):
>    docker pull moresonsun/lynx:latest
> 2. Start with compose (build not required unless modifying source):
>    curl -L https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
>    docker compose up -d controller
>
> Or if you cloned the repo already:
>    docker compose up -d controller
>
> Need Postgres + runtime prewarm? Use the full docker-compose.yml in the repo instead of docker-compose.min.yml.
