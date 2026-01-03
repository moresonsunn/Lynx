<#!
.SYNOPSIS
  Lynx quick installer for Windows PowerShell.
  Example (PowerShell 5+):
  irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
  irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex -v v0.1.1
.PARAMETER Version
  Optional tag (e.g. v0.1.1). If omitted uses latest GitHub release; fallback to :latest edge.
.PARAMETER Path
  Target directory (default ./lynx)
.PARAMETER Edge
  Use :latest images ignoring releases.
.PARAMETER NoStart
  Download compose file but do not start containers.
.PARAMETER DryRun
  Show actions only.
!#>
[CmdletBinding()]
param(
  [string]$Version,
  [string]$Path = "lynx",
  [switch]$Edge,
  [switch]$NoStart,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repo = 'moresonsunn/Lynx'
$namespace = $env:LYNX_NAMESPACE
if (-not $namespace -or $namespace -eq '') { $namespace = $env:BLOCKPANEL_NAMESPACE }
if (-not $namespace -or $namespace -eq '') { $namespace = 'moresonsun' }
$branch = 'main'
$rawBase = "https://raw.githubusercontent.com/$repo/$branch"

# Detect architecture
$arch = if ([Environment]::Is64BitOperatingSystem) { 'x64' } else { 'x86' }
Write-Host "Detected platform: Windows ($arch)" -ForegroundColor Cyan

function Invoke-Step($msg, [scriptblock]$action) {
  Write-Host "+ $msg" -ForegroundColor Cyan
  if (-not $DryRun) { & $action }
}

# Check Docker availability
Write-Host 'Checking Docker installation...' -ForegroundColor Yellow
try {
  $dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
  if (-not $dockerVersion) { throw 'Docker not responding' }
  Write-Host "Docker version: $dockerVersion" -ForegroundColor Green
} catch {
  Write-Host @'

ERROR: Docker is not installed or not running.

To install Docker Desktop for Windows:
1. Download from: https://docs.docker.com/desktop/install/windows-install/
2. Run the installer
3. Restart your computer if prompted
4. Start Docker Desktop from the Start menu
5. Wait for Docker to finish starting (tray icon stops animating)
6. Run this script again

Note: Windows 10/11 Pro/Enterprise can use Hyper-V or WSL2 backend.
      Windows 10/11 Home requires WSL2 backend.
'@ -ForegroundColor Red
  exit 1
}

# Verify Docker is running
try {
  docker info 2>$null | Out-Null
} catch {
  Write-Host @'

ERROR: Docker daemon is not running.

Please start Docker Desktop:
1. Click the Docker Desktop icon in your system tray
2. Wait for it to finish starting
3. Run this script again
'@ -ForegroundColor Red
  exit 1
}

if (-not $Version -and -not $Edge) {
  try {
    Write-Host 'Resolving latest GitHub release tag...' -ForegroundColor Yellow
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -UseBasicParsing
    $Version = $rel.tag_name
  } catch { Write-Warning 'Failed to fetch latest release; using edge (:latest).'; $Edge = $true }
}

if ($Edge) { Write-Host 'Using edge (latest) images.' -ForegroundColor Yellow }

Invoke-Step "Create target dir $Path" { New-Item -ItemType Directory -Path $Path -Force | Out-Null }
Set-Location $Path

$composeUrl = "$rawBase/docker-compose.yml"
Invoke-Step 'Download docker-compose.yml' { Invoke-WebRequest -Uri $composeUrl -OutFile 'docker-compose.yml' }

if (-not $Edge -and $Version) {
  Write-Host "Pinning images to $Version" -ForegroundColor Green
  Invoke-Step 'Replace controller image tag' {
    (Get-Content docker-compose.yml) -replace "$namespace/lynx:latest", "$namespace/lynx:$Version" | Set-Content docker-compose.yml
  }
  # Single-image deployment: controller and runtime use the same image.
  Invoke-Step 'Replace APP_VERSION env' {
    (Get-Content docker-compose.yml) -replace 'APP_VERSION=v[0-9A-Za-z\.\-]+', "APP_VERSION=$Version" | Set-Content docker-compose.yml
  }
}

if ($NoStart) { Write-Host 'Download complete (no start).'; exit 0 }
if ($DryRun) { Write-Host '(dry-run) Would run docker compose pull + up'; exit 0 }

Invoke-Step 'docker compose pull' { docker compose pull }
Invoke-Step 'docker compose up -d' { docker compose up -d }

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '║  Lynx is starting! Access it at: http://localhost:8000       ║' -ForegroundColor Green
Write-Host '╚══════════════════════════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
if ($Edge) { 
  Write-Host 'Build: Edge (:latest images)' 
} else { 
  Write-Host "Build: Release $Version" 
}
Write-Host "Platform: Windows ($arch)"
Write-Host ''
Write-Host 'Useful commands:' -ForegroundColor Yellow
Write-Host '  docker compose logs -f     # View logs'
Write-Host '  docker compose down        # Stop Lynx'
Write-Host '  docker compose pull        # Update to latest'
Write-Host ''
Write-Host 'Windows Note: Data is stored in Docker volumes.' -ForegroundColor Cyan
Write-Host '  View in Docker Desktop → Volumes → servers_data'