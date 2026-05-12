<p align="center">
  <h1 align="center">Lynx</h1>
  <p align="center">Self-hosted game server management panel built on Docker</p>
</p>

<p align="center">
  <a href="https://github.com/moresonsunn/Lynx/actions/workflows/ci.yml"><img src="https://github.com/moresonsunn/Lynx/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://hub.docker.com/r/moresonsun/lynx"><img src="https://img.shields.io/docker/pulls/moresonsun/lynx" alt="Docker Pulls"></a>
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-blue" alt="Architecture">
  <img src="https://img.shields.io/badge/license-proprietary-lightgrey" alt="License">
</p>

---

Lynx gives you a web UI to deploy, configure, and manage Minecraft and Steam dedicated servers — all running as Docker containers on your own hardware. Create a server, tweak its settings, watch the console live, manage files, schedule backups, and handle players, all from one place.

<!-- Add a screenshot here: ![Dashboard](docs/assets/screenshot.png) -->

## Features

**Server Management** — Create, start, stop, restart, and delete game servers through the web UI or REST API. Real-time console with ANSI color support and command history.

**File Manager** — Browse, edit, upload, download, and archive server files directly from the browser. Drag-and-drop uploads supported.

**Backups** — Automated and manual backups with scheduling. Incremental backup support and optional cloud storage (S3, GCS, Azure) with encryption.

**Minecraft** — Vanilla, Paper, Purpur, Fabric, Forge, and NeoForge. Automatic Java version selection (8, 11, 17, 21). Modpack installation from CurseForge and Modrinth with dependency resolution and conflict detection.

**Steam Games** — 70+ dedicated server configs out of the box: Valheim, Rust, ARK, CS2, Palworld, Terraria, Project Zomboid, Satisfactory, and many more. Workshop mod management included.

**Monitoring** — Real-time CPU, memory, and network metrics per server. Crash detection and performance alerts.

**Multi-Server Operations** — Bulk start/stop, server groups, cloning, and templates for quick deployment.

**Auth & Security** — User authentication with role-based access, per-server permissions, 2FA/TOTP, IP whitelisting, and audit logging.

**API** — Full REST API for automation. API key management, rate limiting, webhooks, and batch operations.

See [docs/FEATURES.md](docs/FEATURES.md) for the complete feature reference.

## Supported Games

### Minecraft

| Type | Description |
|------|-------------|
| Vanilla | Official Mojang server |
| Paper | High-performance Spigot fork |
| Purpur | Paper fork with extra gameplay options |
| Fabric | Lightweight modding platform |
| Forge | Classic modding platform |
| NeoForge | Modern Forge continuation |

Automatic Java version detection and modpack support from CurseForge and Modrinth.

### Steam

70+ dedicated servers with pre-configured defaults. Some highlights:

| Category | Examples |
|----------|---------|
| Survival | Valheim, Rust, ARK, Palworld, V Rising, 7 Days to Die, Enshrouded |
| Shooters | Counter-Strike 2, Hell Let Loose, Insurgency: Sandstorm, Squad |
| Co-op | Terraria, Don't Starve Together, Project Zomboid, Satisfactory, Core Keeper |

Full catalog: [backend/data/steam_games/extended_catalog.json](backend/data/steam_games/extended_catalog.json)

## Quick Start

**Requirements:** Docker Engine 20.10+ (or Docker Desktop) and 4GB RAM.

### One-line install

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash

# Windows (PowerShell as Admin)
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

### Manual install

```bash
mkdir lynx && cd lynx
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
docker compose up -d
```

Open **http://localhost:8000** and log in with `admin` / `admin123`. Change the password immediately.

For detailed installation options, platform notes, and environment variables, see [docs/INSTALL.md](docs/INSTALL.md).

## Architecture

```
┌──────────────────────────────────────────────┐
│                   Nginx                       │
│              (reverse proxy)                  │
├──────────────┬───────────────────────────────┤
│   React UI   │      FastAPI Backend          │
│  (Tailwind)  │  (SQLAlchemy + Docker SDK)    │
├──────────────┴───────────────────────────────┤
│           PostgreSQL / SQLite                 │
├──────────────────────────────────────────────┤
│         Docker Engine (game servers)          │
│   ┌────────┐ ┌────────┐ ┌────────┐          │
│   │ MC #1  │ │ MC #2  │ │ Valheim│  ...     │
│   └────────┘ └────────┘ └────────┘          │
└──────────────────────────────────────────────┘
```

| Layer | Tech |
|-------|------|
| Frontend | React 18, Tailwind CSS |
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| Database | PostgreSQL (SQLite fallback) |
| Runtime | Docker with multi-architecture support (amd64/arm64) |
| Real-time | WebSockets for console streaming and notifications |

## Development

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

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for building Docker images, project structure, and the release process.

## Documentation

| Document | Description |
|----------|-------------|
| [Installation Guide](docs/INSTALL.md) | Full setup, configuration, and troubleshooting |
| [Features](docs/FEATURES.md) | Complete feature reference |
| [API Reference](docs/API.md) | REST API overview and examples |
| [Development](docs/DEVELOPMENT.md) | Local dev setup, building, and releasing |
| [Contributing](CONTRIBUTING.md) | How to contribute |
| [Security](SECURITY.md) | Security policy and reporting |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

All rights reserved. See [LICENSE](LICENSE) for details.
