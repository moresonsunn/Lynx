# Development

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Engine (for running game servers locally)

## Local Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. FastAPI auto-generates interactive docs at `/docs` (Swagger) and `/redoc`.

### Frontend

```bash
cd frontend
npm install
npm start
```

The React dev server runs on `http://localhost:3000` and proxies API requests to the backend.

## Project Structure

```
Lynx/
├── backend/                 # FastAPI application
│   ├── app.py               # Main app, routes, startup
│   ├── docker_manager.py    # Docker SDK wrapper for server lifecycle
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # DB engine and session setup
│   ├── auth.py              # JWT auth, password hashing
│   ├── config.py            # App configuration
│   ├── backup_manager.py    # Backup create/restore logic
│   ├── backup_scheduler.py  # Scheduled backup engine
│   ├── scheduler.py         # Task scheduler
│   ├── steam_games.py       # Steam dedicated server catalog
│   ├── file_manager.py      # Server file operations
│   ├── crash_analyzer.py    # Log-based crash detection
│   ├── mod_sources.py       # CurseForge / Modrinth integration
│   ├── data/
│   │   └── steam_games/     # Extensible Steam game definitions
│   ├── routers/             # Grouped API route modules
│   ├── server_providers/    # Pluggable server type providers
│   └── modpack_providers/   # Modpack source integrations
├── frontend/                # React application
│   ├── src/
│   │   ├── pages/           # Page components
│   │   ├── components/      # Reusable UI components
│   │   ├── context/         # React context providers
│   │   └── utils/           # Helper functions
│   └── tailwind.config.js
├── docker/                  # Dockerfiles and entrypoints
│   ├── controller-unified.Dockerfile   # Production image (all-in-one)
│   ├── controller.Dockerfile           # Lightweight controller image
│   ├── runtime.Dockerfile              # Server runtime image
│   └── runtime-entrypoint.sh           # Container entrypoint script
├── scripts/                 # Build and publish scripts
├── casaos-appstore/         # CasaOS app store manifests
├── docker-compose.yml       # Default deployment
└── docker-compose.unified.yml  # All-in-one deployment
```

## Building Docker Images

### Local build

```bash
docker build -t lynx:dev -f docker/controller-unified.Dockerfile .
```

### Multi-architecture build

For publishing images that run on both amd64 and arm64:

```bash
docker buildx create --name builder --use
docker buildx build \
  -f docker/controller-unified.Dockerfile \
  -t moresonsun/lynx:latest \
  --platform linux/amd64,linux/arm64 \
  --push .
```

## Testing

```bash
# Run backend tests
cd backend
pytest

# Run from project root
python -m pytest test_complete_system.py
python -m pytest test_docker_build.py
python -m pytest test_server_types.py
```

## Releasing

Lynx uses Git tags to trigger versioned Docker image builds in CI.

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push --tags
```

This triggers the GitHub Actions workflow in `.github/workflows/release.yml`, which builds multi-arch images and pushes them to Docker Hub with the version tag.

### Manual publish

If you need to push images outside of CI:

```bash
# Linux/macOS
./scripts/manual-publish-dockerhub.sh

# Windows
./scripts/manual-publish-dockerhub.ps1
```

## CI/CD

The project runs CI on both GitHub Actions and GitLab CI:

- **GitHub Actions** — `.github/workflows/ci.yml` runs tests and linting on every push
- **GitHub Actions** — `.github/workflows/docker-build-push.yml` builds and pushes Docker images
- **GitHub Actions** — `.github/workflows/release.yml` handles tagged releases
- **GitLab CI** — `.gitlab-ci.yml` mirrors the GitHub pipeline

## Code Style

- **Backend:** Standard Python conventions. Type hints are used throughout.
- **Frontend:** React functional components with hooks. Tailwind CSS for styling.
- **Commits:** Use descriptive commit messages. Reference issue numbers where applicable.
