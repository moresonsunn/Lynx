# API Reference

Lynx exposes a REST API on the same port as the web UI (default `8000`). Every feature available in the UI is backed by an API endpoint.

Interactive documentation is auto-generated at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## Authentication

Most endpoints require a valid JWT token. Obtain one by logging in:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

Response:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

Include the token in subsequent requests:

```bash
curl http://localhost:8000/api/servers \
  -H "Authorization: Bearer eyJ..."
```

Tokens expire after 30 minutes by default (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`).

### API Keys

For long-lived programmatic access, create an API key through the settings UI or the `/api/api-keys` endpoint. API keys don't expire but can be revoked at any time.

## Endpoint Groups

### Servers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers` | List all servers |
| `POST` | `/api/servers` | Create a new server |
| `POST` | `/api/servers/import` | Import an existing server directory |
| `POST` | `/api/servers/{id}/start` | Start a server |
| `POST` | `/api/servers/{id}/stop` | Stop a server |
| `POST` | `/api/servers/{id}/restart` | Restart a server |
| `POST` | `/api/servers/{id}/power` | Send a power signal (`start`, `stop`, `restart`, `kill`) |
| `DELETE` | `/api/servers/{id}` | Delete a server |
| `GET` | `/api/servers/{id}/state` | Get server state and phase |
| `GET` | `/api/servers/{id}/logs` | Get server console output |
| `POST` | `/api/servers/{id}/command` | Send a command to the server console |

### Server Creation

```bash
curl -X POST http://localhost:8000/api/servers \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "survival",
    "type": "paper",
    "version": "1.21.1",
    "host_port": null,
    "min_ram": 2048,
    "max_ram": 4096
  }'
```

Set `host_port` to `null` to auto-assign an available port. RAM values are in MB.

### Ports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ports/used` | List ports in use by Docker containers |
| `GET` | `/api/ports/validate?port=25565` | Check if a port is available |
| `GET` | `/api/ports/suggest?start=25565&end=25999` | Get the next available port |

### Files

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{id}/files?path=/` | List directory contents |
| `GET` | `/api/servers/{id}/files/read?path=/server.properties` | Read a file |
| `PUT` | `/api/servers/{id}/files/write` | Write/update a file |
| `DELETE` | `/api/servers/{id}/files?path=/old-world` | Delete a file or directory |
| `POST` | `/api/servers/{id}/files/upload` | Upload a file |
| `POST` | `/api/servers/{id}/files/zip` | Create a ZIP archive |
| `POST` | `/api/servers/{id}/files/unzip` | Extract a ZIP archive |

### Backups

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{id}/backups` | List backups |
| `POST` | `/api/servers/{id}/backups` | Create a backup |
| `POST` | `/api/servers/{id}/backups/{backup}/restore` | Restore from backup |

Advanced backup endpoints are available under `/api/backups/` for scheduled, incremental, and remote backups.

### Steam Servers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/steam/games` | List available Steam game configs |
| `POST` | `/api/steam/servers` | Create a Steam dedicated server |
| `GET` | `/api/steam/servers/{id}/mods` | List installed Workshop mods |
| `POST` | `/api/steam/servers/{id}/mods` | Install a Workshop mod |

### Modpacks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/modpacks/search` | Search CurseForge / Modrinth |
| `POST` | `/api/modpacks/install` | Install a modpack to a server |
| `GET` | `/api/servers/{id}/mods` | List installed mods |

### Players

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{id}/players` | Get online players |
| `POST` | `/api/servers/{id}/players/whitelist` | Manage whitelist |
| `POST` | `/api/servers/{id}/players/ban` | Ban a player |

### Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/servers/{id}/stats` | Current resource usage |
| `GET` | `/api/servers/{id}/stats/history` | Historical metrics |
| `GET` | `/api/monitoring/alerts` | Active performance alerts |

### Auth & Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Log in and get a JWT token |
| `POST` | `/api/auth/register` | Create a new user (admin only) |
| `GET` | `/api/users` | List users |
| `PUT` | `/api/users/{id}` | Update a user |
| `DELETE` | `/api/users/{id}` | Delete a user |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health/quick` | Basic health check (used by Docker healthcheck) |
| `GET` | `/api/health` | Detailed health status |

## WebSocket Endpoints

### Console Streaming

Connect to a server's live console output:

```
ws://localhost:8000/ws/servers/{id}/console
```

Messages are streamed as text frames with ANSI color codes intact. Send text frames to execute commands on the server.

### Real-Time Notifications

```
ws://localhost:8000/ws/notifications
```

Receive JSON messages for server state changes, backup completions, and alerts.

## Rate Limiting

API endpoints are rate-limited per user/key. Default limits are generous for normal usage. If you hit a rate limit, you'll get a `429 Too Many Requests` response with a `Retry-After` header.

## Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Human-readable error message"
}
```

Common status codes:

| Code | Meaning |
|------|---------|
| `400` | Bad request (validation error) |
| `401` | Not authenticated |
| `403` | Insufficient permissions |
| `404` | Resource not found |
| `429` | Rate limited |
| `503` | Docker engine unavailable |
