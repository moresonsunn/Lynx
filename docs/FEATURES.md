# Features

Complete feature reference for Lynx. For a quick overview, see the [README](../README.md).

---

## Server Management

Lynx manages game servers as Docker containers. Each server gets its own isolated environment with dedicated storage, ports, and resource limits.

- **Lifecycle control** — Create, start, stop, restart, and delete servers from the web UI or API
- **Real-time console** — Live log streaming over WebSockets with ANSI color support. Send commands directly from the browser.
- **Command history** — Previous commands are saved per server for quick re-use
- **Server state tracking** — Phase detection (starting, running, stopped, crashed) with uptime tracking
- **Port management** — Automatic port assignment with conflict detection, or specify ports manually
- **Import existing servers** — Adopt servers you already have running by pointing Lynx at their data directory. Auto-detects server type and version.

## Minecraft Support

### Server Types

| Type | Description |
|------|-------------|
| Vanilla | Official Mojang server |
| Paper | High-performance Spigot fork |
| Purpur | Paper fork with additional gameplay features |
| Fabric | Lightweight modding platform |
| Forge | Classic modding platform |
| NeoForge | Modern Forge continuation |

### Java Version Management

Lynx includes Java 8, 11, 17, and 21 in the runtime image. The correct version is selected automatically based on the Minecraft version:

- Minecraft 1.7–1.16 → Java 8 or 11
- Minecraft 1.17 → Java 16 or 17
- Minecraft 1.18–1.20.4 → Java 17
- Minecraft 1.20.5+ → Java 21

You can also override the Java version per server if needed.

### Modpack Support

Install modpacks directly from CurseForge and Modrinth through the UI:

- Browse and search modpacks by name
- Automatic dependency resolution
- Client-only mod detection and filtering
- Mod conflict detection
- Update checking for installed mods
- Loader version management (Fabric/Forge/NeoForge)

## Steam Dedicated Servers

70+ pre-configured Steam game servers. Each game definition includes the correct SteamCMD app ID, default ports, environment variables, and container image.

**Survival:** Valheim, Rust, ARK: Survival Evolved, The Forest, Palworld, V Rising, 7 Days to Die, Enshrouded, Conan Exiles

**Shooters:** Counter-Strike 2, Hell Let Loose, Insurgency: Sandstorm, Squad, Arma 3, Team Fortress 2

**Co-op:** Terraria, Don't Starve Together, Project Zomboid, Satisfactory, Core Keeper, Stardew Valley

**Other:** Factorio, Eco, Unturned, Barotrauma, Vintage Story, and many more

The full catalog is at [`backend/data/steam_games/extended_catalog.json`](../backend/data/steam_games/extended_catalog.json). You can add custom game definitions by placing JSON files in `backend/data/steam_games/` — see [the README there](../backend/data/steam_games/README.md).

### Steam Workshop Integration

For games that support it, Lynx can manage Steam Workshop mods: browse, install, update, and remove workshop items per server.

## File Management

The built-in file manager gives you full access to each server's data directory:

- Browse, create, rename, and delete files and folders
- Edit text files (configs, scripts, etc.) in the browser
- Upload files with drag-and-drop support
- Download individual files or entire directories as ZIP archives
- Extract uploaded ZIP archives in place

## Backups

### Basic Backups

- Manual backup and restore per server
- Download backup archives

### Scheduled Backups

- Cron-style scheduling per server
- Configurable retention policies

### Advanced Backups

- Incremental backups (only changed files)
- Remote storage targets: S3-compatible, Google Cloud Storage, Azure Blob Storage
- Backup encryption
- Restore from any backup point

## Monitoring & Analytics

### Real-Time Metrics

Per-server resource monitoring:

- CPU usage
- Memory consumption
- Network I/O
- Disk usage

Metrics are collected on a configurable interval and stored for historical charts.

### Crash Detection

Lynx watches server logs for crash patterns and JVM errors. When a crash is detected:

- The event is logged with the relevant stack trace
- Performance alerts can be triggered
- Crash analytics are available through the monitoring dashboard

### Player Analytics

- Active player tracking
- Join/leave history
- Playtime statistics
- Bulk whitelist management
- Temporary bans with expiry

## Configuration Management

### Visual Config Editor

Edit `server.properties` and other config files through a structured form UI instead of raw text editing. The editor understands the property schema and provides:

- Descriptions for each setting
- Type validation (boolean, integer, string)
- Default value indicators

### Server Templates

Save a server's configuration as a reusable template. Templates capture:

- Server type and version
- Memory allocation
- Environment variables
- Configuration files

Apply templates when creating new servers to standardize setups.

### Config Diff

Compare current configuration against defaults or previous versions to see what changed.

## Authentication & Security

### User Management

- Local user accounts with bcrypt password hashing
- Role-based access: Admin, Moderator, Viewer
- Per-server permissions — restrict which servers a user can see or control

### Two-Factor Authentication

TOTP-based 2FA (compatible with Google Authenticator, Authy, etc.)

### Security Features

- IP whitelisting
- Audit logging for all administrative actions
- JWT-based session management with configurable token expiry
- Rate limiting on auth endpoints

## API

Lynx exposes a full REST API. Every action available in the UI is also available through the API.

- JWT authentication
- API key management for programmatic access
- Webhook support for event notifications
- Rate limiting per key
- Batch operations for multi-server actions

See [docs/API.md](API.md) for endpoint documentation and examples.

## Multi-Server Operations

When managing many servers, these features help:

- **Bulk actions** — Start, stop, or restart multiple servers at once
- **Server groups** — Organize servers into logical groups
- **Cloning** — Duplicate a server's configuration and data
- **Search and filter** — Find servers by name, type, status, or game

## Organizations (Multi-Tenancy)

For shared hosting or team setups:

- Create organizations with separate user pools
- Resource quotas per organization
- Billing tracking
- Isolated server namespaces

## Plugin System

- Install and manage plugins from a central catalog
- Custom server type definitions
- Plugin versioning
- Community contributions through the plugin marketplace

## Real-Time Features

WebSocket-based real-time capabilities:

- **Console streaming** — Live server output with < 1s latency
- **Server status updates** — Instant status change notifications
- **Notifications** — In-app alerts for crashes, backup completions, player events

## CasaOS Integration

Lynx integrates with [CasaOS](https://casaos.io/) for users running home servers:

- Install Lynx from the CasaOS app store
- Deploy Steam servers as CasaOS compose applications
- Automatic container labeling and discovery

See [docs/INSTALL.md](INSTALL.md#casaos-deployment) for setup instructions.
