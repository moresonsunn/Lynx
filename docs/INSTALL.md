# Installation

## Requirements

- **Docker Engine 20.10+** or Docker Desktop
- **4 GB RAM** minimum (more if running multiple servers)
- **Supported platforms:** Linux (amd64/arm64), macOS (Intel + Apple Silicon), Windows (via WSL2)

## Quick Install

The install scripts pull the latest image and start Lynx with sensible defaults.

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

**Windows (PowerShell as Administrator):**

```powershell
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

## Manual Install

If you prefer to set things up yourself:

```bash
mkdir lynx && cd lynx
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml
docker compose up -d
```

That's it. The web UI will be available at **http://localhost:8000**.

## Post-Install

1. Open **http://localhost:8000**
2. Log in with `admin` / `admin123`
3. **Change the default password immediately**

## Platform Notes

### Linux

If Docker isn't installed yet:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

### macOS

- Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
- Both Apple Silicon and Intel are supported
- Server data is stored in Docker volumes

### Windows

- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the **WSL2 backend** enabled
- Run PowerShell as Administrator if you get permission errors
- WSL2 is recommended for performance — Hyper-V works but is slower

## Management Commands

```bash
# View logs
docker compose logs -f

# Stop Lynx
docker compose down

# Update to latest version
docker compose pull && docker compose up -d

# Remove everything including data
docker compose down -v
```

## Docker Images

Images are published to Docker Hub as `moresonsun/lynx`:

| Tag | Description |
|-----|-------------|
| `latest` | Current stable release |
| `vX.Y.Z` | Pinned version |
| `edge` | Development builds from `main` |

```bash
docker pull moresonsun/lynx:latest
```

## Environment Variables

All configuration is done through environment variables in your `docker-compose.yml` or `.env` file.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD` | `admin123` | Initial admin password (min 8 characters) |
| `APP_NAME` | `Lynx` | Branding name shown in the UI |
| `APP_VERSION` | `0.1.0` | Version string for the branding endpoint |
| `SECRET_KEY` | — | JWT signing key. **Change this in production.** |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVERS_CONTAINER_ROOT` | `/data/servers` | Path inside the container where server data lives |
| `SERVERS_HOST_ROOT` | *(inferred)* | Host path when using bind mounts instead of volumes |
| `SERVERS_VOLUME_NAME` | `minecraft-server_mc_servers_data` | Named Docker volume for server data |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_POSTGRES` | `false` | Set to `true` to use PostgreSQL instead of SQLite |
| `DATABASE_URL` | `sqlite:///...` | Full database connection string |
| `POSTGRES_DB` | `minecraft_controller` | PostgreSQL database name |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `postgres123` | PostgreSQL password |

### Networking

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_PORT` | `8000` | Port the web UI listens on |
| `ALLOWED_ORIGIN_REGEX` | — | CORS origin regex pattern |

### CasaOS Integration

| Variable | Description |
|----------|-------------|
| `CASAOS_API_TOKEN` | Auth token from your CasaOS browser session |
| `CASAOS_API_BASE` | CasaOS API URL (e.g. `http://<ip>/v2/app_management`) |

To get the CasaOS token:

1. Sign in to CasaOS in your browser
2. Open DevTools (F12) → Network tab
3. Refresh the page and look at any request's headers
4. Copy the `authorization` header value

## CasaOS Deployment

Lynx can be installed directly from CasaOS as a custom app store entry.

1. Go to CasaOS → Custom App Store
2. Add the store URL:
   ```
   https://raw.githubusercontent.com/moresonsunn/Lynx/main/casaos-appstore/index.json
   ```
3. Install "Lynx (Unified)" from the store

See [casaos-appstore/README.md](../casaos-appstore/README.md) for details on the app store structure.

## Importing Existing Servers

If you already have Minecraft server files on the host:

1. Stop the existing server container (if any)
2. Copy the server files to `/data/servers/<name>`
3. Call the import endpoint:
   ```bash
   curl -X POST http://localhost:8000/api/servers/import \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <token>" \
     -d '{"name": "<name>"}'
   ```
4. Start the server from the web UI

Lynx will auto-detect the server type (Paper, Forge, Fabric, etc.) and Minecraft version from jar filenames.

## Troubleshooting

**401 Unauthorized errors**
Your auth token has expired. Log in again or check that `SECRET_KEY` hasn't changed.

**CORS errors in the browser**
Set `ALLOWED_ORIGIN_REGEX=.*` in your environment to allow all origins. Tighten this for production.

**Port conflicts when creating servers**
Use `GET /api/ports/suggest` to find an available port before creating a server, or let Lynx auto-assign one by omitting `host_port`.

**Container won't start**
Make sure the Docker socket is mounted: `/var/run/docker.sock:/var/run/docker.sock`. Check `docker compose logs lynx` for errors.

**Windows Docker socket issues**
If using Docker Desktop on Windows, you may need to set `DOCKER_HOST=npipe:////./pipe/docker_engine` in your environment.
