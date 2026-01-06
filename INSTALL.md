# Lynx Installation Guide

Complete installation guide for Lynx – a **Game Server Manager** supporting **Minecraft** and **70+ Steam games** – on all supported platforms using Docker Hub images.

## Supported Platforms

| Platform | Architecture | Docker Backend | Status |
|----------|-------------|----------------|--------|
| macOS (Intel) | x86_64 | Docker Desktop | ✅ Fully Supported |
| macOS (Apple Silicon) | arm64 | Docker Desktop | ✅ Fully Supported |
| Windows 10/11 | x86_64 | Docker Desktop (WSL2) | ✅ Fully Supported |
| Windows 10/11 Pro | x86_64 | Docker Desktop (Hyper-V) | ✅ Fully Supported |
| Linux (Debian/Ubuntu) | x86_64, arm64 | Docker Engine | ✅ Fully Supported |
| Linux (RHEL/CentOS) | x86_64, arm64 | Docker Engine | ✅ Fully Supported |
| Raspberry Pi 4+ | arm64 | Docker Engine | ✅ Fully Supported |
| CasaOS | x86_64, arm64 | Integrated | ✅ Fully Supported |

## Requirements

### Minimum Requirements
- **CPU:** 2 cores
- **RAM:** 4 GB (8 GB recommended)
- **Disk:** 10 GB free space
- **Docker:** 20.10+ with Compose v2

### Docker Desktop Requirements
- **macOS:** macOS 12 (Monterey) or later
- **Windows:** Windows 10 version 2004+ or Windows 11
- **Windows Home:** WSL2 required

---

## 🍎 macOS Installation

### Step 1: Install Docker Desktop

1. Download Docker Desktop from [docker.com](https://docs.docker.com/desktop/install/mac-install/)
   - **Apple Silicon (M1/M2/M3):** Choose "Mac with Apple chip"
   - **Intel Mac:** Choose "Mac with Intel chip"

2. Open the downloaded `.dmg` file
3. Drag Docker to Applications folder
4. Launch Docker Desktop from Applications
5. Accept the license agreement
6. Wait for Docker to finish starting (whale icon in menu bar stops animating)

### Step 2: Configure Docker Desktop (Recommended)

1. Click Docker icon in menu bar → Preferences
2. Go to **Resources** → **Advanced**
3. Set Memory to at least **4 GB** (8 GB recommended for multiple servers)
4. Set CPUs to at least **2**
5. Click **Apply & Restart**

### Step 3: Install Lynx

**Quick Install (Terminal):**
```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

**Manual Install:**
```bash
# Create directory
mkdir -p ~/lynx && cd ~/lynx

# Download compose file
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml

# Pull and start
docker compose pull
docker compose up -d

# View logs
docker compose logs -f
```

### Step 4: Access Lynx

Open http://localhost:8000 in your browser.

**Default credentials:** admin / admin123

### macOS Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot connect to Docker daemon" | Start Docker Desktop from Applications |
| "Protocol not available" | Restart Docker Desktop |
| Slow performance | Increase RAM in Docker Desktop settings |
| Port 8000 in use | Stop other services or change port in compose file |

---

## 🪟 Windows Installation

### Step 1: Install WSL2 (Windows Home users)

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   wsl --install
   ```
3. Restart your computer
4. After restart, set up your Linux username/password when prompted

### Step 2: Install Docker Desktop

1. Download Docker Desktop from [docker.com](https://docs.docker.com/desktop/install/windows-install/)
2. Run the installer
3. Select "Use WSL 2 instead of Hyper-V" (recommended for all users)
4. Complete installation and restart if prompted
5. Launch Docker Desktop from Start menu
6. Accept the license agreement
7. Wait for Docker to finish starting (Docker icon in system tray stops animating)

### Step 3: Configure Docker Desktop (Recommended)

1. Right-click Docker icon in system tray → Settings
2. Go to **Resources** → **WSL Integration**
3. Enable integration with your default WSL distro
4. Go to **Resources** → **Advanced** (if using Hyper-V)
   - Set Memory to at least **4 GB**
   - Set CPUs to at least **2**
5. Click **Apply & Restart**

### Step 4: Install Lynx

**Quick Install (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

**Manual Install (PowerShell):**
```powershell
# Create directory
mkdir $HOME\lynx
cd $HOME\lynx

# Download compose file
Invoke-WebRequest -Uri https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -OutFile docker-compose.yml

# Pull and start
docker compose pull
docker compose up -d

# View logs
docker compose logs -f
```

### Step 5: Access Lynx

Open http://localhost:8000 in your browser.

**Default credentials:** admin / admin123

### Windows Troubleshooting

| Issue | Solution |
|-------|----------|
| "Docker daemon not running" | Start Docker Desktop from Start menu |
| "WSL 2 is not installed" | Run `wsl --install` in Admin PowerShell |
| "Hyper-V not enabled" | Enable in Windows Features |
| Permission denied | Run PowerShell as Administrator |
| Slow I/O performance | Store project in WSL filesystem (`\\wsl$\`) |
| Port 8000 in use | Check with `netstat -an | findstr 8000` |

---

## 🐧 Linux Installation

### Step 1: Install Docker Engine

**Ubuntu/Debian:**
```bash
# Remove old versions
sudo apt-get remove docker docker-engine docker.io containerd runc

# Install via convenience script
curl -fsSL https://get.docker.com | sh

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, then verify
docker --version
docker compose version
```

**CentOS/RHEL/Fedora:**
```bash
# Install via convenience script
curl -fsSL https://get.docker.com | sh

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, then verify
docker --version
```

**Arch Linux:**
```bash
sudo pacman -S docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
```

### Step 2: Install Lynx

**Quick Install:**
```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

**Manual Install:**
```bash
# Create directory
mkdir -p ~/lynx && cd ~/lynx

# Download compose file
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml

# Pull and start
docker compose pull
docker compose up -d
```

### Step 3: Access Lynx

Open http://localhost:8000 or http://<server-ip>:8000

**Default credentials:** admin / admin123

### Linux Troubleshooting

| Issue | Solution |
|-------|----------|
| "Permission denied" | Run `sudo usermod -aG docker $USER` and re-login |
| "Cannot connect to daemon" | Run `sudo systemctl start docker` |
| SELinux blocking | Use `:Z` flag for volumes or configure SELinux |
| Firewall blocking | Run `sudo ufw allow 8000` or equivalent |

---

## 🏠 CasaOS Installation

CasaOS users can install Lynx from the custom app store:

### Add Custom Store

1. Open CasaOS web interface
2. Go to App Store → Settings (gear icon)
3. Add custom source: `https://raw.githubusercontent.com/moresonsunn/Lynx/main/casaos-appstore/index.json`
4. Click Save

### Install Lynx

1. Search for "Lynx" in the App Store
2. Click Install
3. Wait for installation to complete
4. Access via the CasaOS dashboard

---

## 📦 Docker Hub Images

All Lynx images are published to Docker Hub:

```
moresonsun/lynx:latest    # Latest stable release
moresonsun/lynx:v0.1.1    # Specific version
moresonsun/lynx:edge      # Development builds
```

### Multi-Architecture Support

Images support both `linux/amd64` and `linux/arm64`:

```bash
# Pull for specific platform
docker pull --platform linux/arm64 moresonsun/lynx:latest

# Check image architecture
docker inspect moresonsun/lynx:latest | grep Architecture
```

---

## 🔧 Post-Installation

### Change Default Password

1. Log in with admin / admin123
2. Go to Settings → Security
3. Change the admin password immediately

### Configure Firewall (Linux)

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 8000/tcp        # Lynx web panel
sudo ufw allow 25565/tcp       # Default Minecraft port
sudo ufw allow 27015:27020/udp # Common Steam game ports

# firewalld (CentOS/RHEL)
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --add-port=25565/tcp --permanent
sudo firewall-cmd --add-port=27015-27020/udp --permanent
sudo firewall-cmd --reload
```

### Set Up Automatic Updates

Create a cron job for automatic updates:

```bash
# Edit crontab
crontab -e

# Add weekly update (Sundays at 3 AM)
0 3 * * 0 cd ~/lynx && docker compose pull && docker compose up -d
```

---

## 🆘 Getting Help

- **Documentation:** See [README.md](README.md)
- **Issues:** [GitHub Issues](https://github.com/moresonsunn/Lynx/issues)
- **Logs:** `docker compose logs -f`

### Debug Commands

```bash
# Check container status
docker compose ps

# View resource usage
docker stats

# Inspect container
docker inspect lynx-lynx-1

# Check Docker version
docker version
docker compose version

# Test connectivity
curl -f http://localhost:8000/health/quick
```
