# Lynx

A web-based game server management platform for Minecraft and Steam dedicated servers.

![GitLab CI](https://gitlab.com/kyzen4/lynx/badges/main/pipeline.svg)
![GitHub CI](https://github.com/moresonsunn/Lynx/actions/workflows/ci.yml/badge.svg)
![Docker Pulls](https://img.shields.io/docker/pulls/moresonsun/lynx)
![Architecture](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-blue)

## Overview

Lynx provides a unified interface to deploy, configure, and monitor game servers running in Docker containers. The platform supports Minecraft servers with automatic Java version selection and over 70 Steam game servers.

## Features

- Server lifecycle management (create, start, stop, restart, delete)
- Real-time console output with ANSI color support
- File manager with upload, download, and archive operations
- Automated backup and restore
- User authentication with role-based access control
- REST API for automation and integration
- Multi-architecture support (amd64, arm64)

## Supported Games

### Minecraft

| Type | Description |
|------|-------------|
| Vanilla | Official Mojang server |
| Paper | High-performance Spigot fork |
| Purpur | Paper fork with additional features |
| Fabric | Lightweight modding platform |
| Forge | Classic modding platform |
| NeoForge | Modern Forge continuation |

Minecraft servers include automatic Java version selection (8, 11, 17, 21) and modpack installation from CurseForge and Modrinth.

### Steam Games

Over 70 dedicated server configurations including:

| Category | Games |
|----------|-------|
| Survival | Valheim, Rust, ARK, The Forest, Palworld, V Rising, 7 Days to Die, Enshrouded |
| Shooters | Counter-Strike 2, Hell Let Loose, Insurgency: Sandstorm, Squad, Arma 3 |
| Cooperative | Terraria, Don't Starve Together, Project Zomboid, Satisfactory, Core Keeper |

Full catalog available at [backend/data/steam_games/extended_catalog.json](backend/data/steam_games/extended_catalog.json)

## Installation

### Quick Start

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

### Requirements

- Docker Engine 20.10+ or Docker Desktop
- 4GB RAM minimum
- Supported platforms: Linux (amd64/arm64), macOS, Windows

### Manual Installation

```bash
mkdir lynx && cd lynx
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
docker compose pull
docker compose up -d
```

### Platform Notes

**macOS:**
- Install Docker Desktop for Mac
- Apple Silicon and Intel architectures supported
- Data stored in Docker volumes

**Windows:**
- Install Docker Desktop with WSL2 backend
- Run PowerShell as Administrator if permission errors occur
- WSL2 recommended for performance

**Linux:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### Post-Installation

1. Access the web interface at http://localhost:8000
2. Login with default credentials: admin / admin123
3. Change the default password immediately

### Management Commands

```bash
# View logs
docker compose logs -f

# Stop
docker compose down

# Update
docker compose pull
docker compose up -d

# Remove all data
docker compose down -v
```

## Docker Images

Published to Docker Hub under `moresonsun/lynx`:

| Tag | Description |
|-----|-------------|
| `latest` | Current stable release |
| `vX.Y.Z` | Specific version |
| `edge` | Development builds |

```bash
docker pull moresonsun/lynx:latest
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| ADMIN_PASSWORD | Initial admin password (min 8 characters) | admin123 |
| APP_NAME | Application branding name | Lynx |
| APP_VERSION | Version string for branding endpoint | 0.1.0 |
| SECRET_KEY | JWT signing key (change in production) | - |
| SERVERS_CONTAINER_ROOT | Container path for server data | /data/servers |
| SERVERS_HOST_ROOT | Host path for bind mounts | (inferred) |
| SERVERS_VOLUME_NAME | Docker volume name | minecraft-server_mc_servers_data |
| ALLOWED_ORIGIN_REGEX | CORS origin pattern | - |

### CasaOS Integration

Steam servers can be installed as CasaOS v2 compose applications. Required variables:

| Variable | Description |
|----------|-------------|
| CASAOS_API_TOKEN | Authentication token from CasaOS browser session |
| CASAOS_API_BASE | CasaOS API URL (e.g., `http://<ip>/v2/app_management`) |

To obtain the token:
1. Open CasaOS in browser and sign in
2. Open browser developer tools (F12) and go to Network tab
3. Refresh the page and inspect any request headers
4. Copy the `authorization` header value

## Development

### Local Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app:app --reload

# Frontend
cd frontend
npm install
npm start
```

### Building Images

```bash
# Build locally
docker build -t lynx:dev -f docker/controller-unified.Dockerfile .

# Multi-architecture build
docker buildx create --name builder --use
docker buildx build -f docker/controller-unified.Dockerfile \
  -t moresonsun/lynx:latest \
  --platform linux/amd64,linux/arm64 \
  --push .
```

### Project Structure

```
Lynx/
  backend/     # FastAPI application
  frontend/    # React application
  docker/      # Dockerfiles
  docker-compose.yml
```

## Releasing

Create an annotated tag to trigger versioned image builds:

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push --tags
```

## CasaOS Deployment

Add the custom store URL from `casaos-appstore/index.json` to CasaOS, then install "Lynx (Unified)" from the app store.

### Importing Existing Servers

1. Stop the existing Minecraft container
2. Copy server files to `/data/servers/<name>`
3. Call `POST /api/servers/import` with `{ "name": "<name>" }`
4. Start the server from the web interface

### Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 errors | Verify authentication token is valid |
| CORS errors | Set `ALLOWED_ORIGIN_REGEX=.*` temporarily |
| Port conflicts | Use `GET /api/ports/suggest` before creating servers |
| Container not starting | Check Docker socket mount at `/var/run/docker.sock` |

## Technical Details

- Backend: Python 3.11, FastAPI, SQLAlchemy, Docker SDK
- Frontend: React 18, Tailwind CSS
- Database: PostgreSQL (SQLite fallback)
- Container Runtime: Docker with multi-Java support (8, 11, 17, 21)

## Contributing

Pull requests and issues welcome. Include reproduction steps for bug reports.

## License

All rights reserved. See LICENSE file for details.
