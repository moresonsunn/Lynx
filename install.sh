#!/usr/bin/env bash
set -euo pipefail

# Lynx quick installer (Linux/macOS) - pulls a specified or latest version and launches via docker compose.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash -s -- -v v0.1.1
# Options:
#   -v|--version <tag>   Use a specific released tag (defaults to latest)
#   -d|--dir <path>      Target directory (default: ./lynx)
#   --no-start           Download assets but do not run docker compose up
#   --edge               Use :latest images instead of a tagged release
#   --dry-run            Show actions only
#   --skip-chown         Skip ownership adjustment on data dir

VERSION=""
TARGET_DIR="lynx"
NO_START="false"
EDGE="false"
DRY="false"
SKIP_CHOWN="false"
GITHUB_REPO="moresonsunn/Lynx"  # Source repository (GitHub)
NAMESPACE="${LYNX_NAMESPACE:-${BLOCKPANEL_NAMESPACE:-moresonsun}}"  # Docker image namespace (override with LYNX_NAMESPACE)
RAW_BASE="https://raw.githubusercontent.com/${GITHUB_REPO}"
BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--version) VERSION="$2"; shift 2;;
    -d|--dir) TARGET_DIR="$2"; shift 2;;
    --no-start) NO_START="true"; shift;;
    --edge) EDGE="true"; shift;;
    --dry-run) DRY="true"; shift;;
    --skip-chown) SKIP_CHOWN="true"; shift;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# //'; exit 0;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# Detect platform
PLATFORM="$(uname -s)"
ARCH="$(uname -m)"
echo "Detected platform: $PLATFORM ($ARCH)"

# Check Docker availability
if ! command -v docker &> /dev/null; then
  echo "Error: Docker is not installed or not in PATH."
  if [[ "$PLATFORM" == "Darwin" ]]; then
    echo "Install Docker Desktop for macOS: https://docs.docker.com/desktop/install/mac-install/"
  elif [[ "$PLATFORM" == "Linux" ]]; then
    echo "Install Docker: curl -fsSL https://get.docker.com | sh"
  fi
  exit 1
fi

# Verify Docker is running
if ! docker info &> /dev/null 2>&1; then
  echo "Error: Docker daemon is not running."
  if [[ "$PLATFORM" == "Darwin" ]]; then
    echo "Please start Docker Desktop and try again."
  else
    echo "Run: sudo systemctl start docker"
  fi
  exit 1
fi

run() { echo "+ $*"; [[ "$DRY" == "true" ]] || eval "$*"; }

if [[ -z "$VERSION" && "$EDGE" != "true" ]]; then
  echo "Resolving latest release tag from GitHub..."
  VERSION=$(curl -fsSL https://api.github.com/repos/${GITHUB_REPO}/releases/latest | grep '"tag_name"' | head -1 | cut -d '"' -f4 || true)
  if [[ -z "$VERSION" ]]; then
    echo "Could not determine latest release (falling back to edge).";
    EDGE="true"
  fi
fi

if [[ "$EDGE" == "true" ]]; then
  echo "Using edge (latest) images instead of tagged release."
fi

echo "Target directory: $TARGET_DIR"
run mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# Fetch docker-compose.yml template
COMPOSE_URL="${RAW_BASE}/${BRANCH}/docker-compose.yml"
run curl -fsSL "$COMPOSE_URL" -o docker-compose.yml

if [[ "$EDGE" == "false" && -n "$VERSION" ]]; then
  echo "Pinning images to $VERSION"
  # Replace :latest with :$VERSION (macOS-compatible sed)
  if [[ "$(uname)" == "Darwin" ]]; then
    run sed -i '' "s#${NAMESPACE}/lynx:latest#${NAMESPACE}/lynx:${VERSION}#" docker-compose.yml || true
    run sed -i '' "s#APP_VERSION=v[^\"]*#APP_VERSION=${VERSION}#" docker-compose.yml || true
  else
    run sed -i "s#${NAMESPACE}/lynx:latest#${NAMESPACE}/lynx:${VERSION}#" docker-compose.yml || true
    run sed -i "s#APP_VERSION=v[^\"]*#APP_VERSION=${VERSION}#" docker-compose.yml || true
  fi
fi

# Data directory ownership (Linux)
if [[ "$SKIP_CHOWN" != "true" && "$DRY" != "true" && -d mc_servers_data ]]; then
  if command -v id >/dev/null 2>&1; then
    sudo chown -R $(id -u):$(id -g) mc_servers_data || true
  fi
fi

if [[ "$NO_START" == "true" ]]; then
  echo "Download complete. Skipping start due to --no-start."
  exit 0
fi

# Launch
if [[ "$DRY" == "true" ]]; then
  echo "(dry-run) Would run: docker compose pull && docker compose up -d"
  exit 0
fi

run docker compose pull
run docker compose up -d

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Lynx is starting! Access it at: http://localhost:8000      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
[[ "$EDGE" == "true" ]] && echo "Build: Edge (:latest images)" || echo "Build: Release ${VERSION}"
echo "Platform: $PLATFORM ($ARCH)"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f     # View logs"
echo "  docker compose down        # Stop Lynx"
echo "  docker compose pull        # Update to latest"
if [[ "$PLATFORM" == "Darwin" ]]; then
  echo ""
  echo "macOS Note: Data is stored in Docker volumes."
  echo "  View in Docker Desktop → Volumes → servers_data"
fi
