# Lynx - Schnellstart-Anleitung

Eine vollständige Anleitung zur Installation und Verwendung von Lynx auf allen Plattformen.

Lynx ist ein **Game Server Manager** – verwalte **Minecraft** und **70+ Steam-Spiele** über eine einheitliche Web-Oberfläche.

---

## 📋 Inhaltsverzeichnis

1. [Voraussetzungen](#voraussetzungen)
2. [Installation nach Plattform](#installation-nach-plattform)
3. [Erster Start](#erster-start)
4. [Wichtige Befehle](#wichtige-befehle)
5. [Minecraft-Server verwalten](#minecraft-server-verwalten)
6. [Steam-Server erstellen](#steam-server-erstellen)
7. [Fehlerbehebung](#fehlerbehebung)

---

## 🔧 Voraussetzungen

| Komponente | Minimum | Empfohlen |
|------------|---------|-----------|
| RAM | 4 GB | 8 GB+ |
| Festplatte | 10 GB | 50 GB+ |
| CPU | 2 Kerne | 4+ Kerne |
| Docker | 20.10+ | Neueste Version |

---

## 🖥️ Installation nach Plattform

### 🍎 macOS (Intel & Apple Silicon)

#### Schritt 1: Docker Desktop installieren

1. Gehe zu https://docs.docker.com/desktop/install/mac-install/
2. Wähle die richtige Version:
   - **Apple Silicon (M1/M2/M3/M4):** "Mac with Apple chip"
   - **Intel Mac:** "Mac with Intel chip"
3. Öffne die `.dmg` Datei und ziehe Docker in den Applications-Ordner
4. Starte Docker Desktop aus dem Applications-Ordner
5. Warte bis das Wal-Symbol in der Menüleiste aufhört zu animieren

#### Schritt 2: Terminal öffnen

- Drücke `Cmd + Leertaste`, tippe "Terminal" und drücke Enter

#### Schritt 3: Lynx installieren (One-Liner)

```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

#### Alternative: Manuelle Installation

```bash
# Ordner erstellen
mkdir -p ~/lynx && cd ~/lynx

# Docker Compose Datei herunterladen
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml

# Image herunterladen und starten
docker compose pull
docker compose up -d
```

#### Lokaler Build (für Entwickler oder Apple Silicon ohne ARM-Image)

```bash
# Repository klonen
git clone https://github.com/moresonsunn/Lynx.git
cd Lynx

# Lokal bauen und starten
docker compose build
docker compose up -d
```

---

### 🪟 Windows 10/11

#### Schritt 1: WSL2 installieren (Windows Home)

1. Öffne PowerShell als Administrator (Rechtsklick → "Als Administrator ausführen")
2. Führe aus:
   ```powershell
   wsl --install
   ```
3. Starte den Computer neu

#### Schritt 2: Docker Desktop installieren

1. Gehe zu https://docs.docker.com/desktop/install/windows-install/
2. Lade den Installer herunter und führe ihn aus
3. Wähle "Use WSL 2 instead of Hyper-V" (empfohlen)
4. Starte Docker Desktop nach der Installation
5. Warte bis das Symbol im System-Tray aufhört zu animieren

#### Schritt 3: PowerShell öffnen

- Drücke `Win + X` → "Windows PowerShell" oder "Terminal"

#### Schritt 4: Lynx installieren (One-Liner)

```powershell
irm https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.ps1 | iex
```

#### Alternative: Manuelle Installation

```powershell
# Ordner erstellen
mkdir $HOME\lynx
cd $HOME\lynx

# Docker Compose Datei herunterladen
Invoke-WebRequest -Uri https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -OutFile docker-compose.yml

# Image herunterladen und starten
docker compose pull
docker compose up -d
```

---

### 🐧 Linux (Ubuntu/Debian/CentOS)

#### Schritt 1: Docker installieren

```bash
# Docker installieren (alle Distros)
curl -fsSL https://get.docker.com | sh

# Benutzer zur Docker-Gruppe hinzufügen
sudo usermod -aG docker $USER

# Ausloggen und wieder einloggen (oder neu starten)
# Dann prüfen:
docker --version
```

#### Schritt 2: Lynx installieren (One-Liner)

```bash
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/install.sh | bash
```

#### Alternative: Manuelle Installation

```bash
# Ordner erstellen
mkdir -p ~/lynx && cd ~/lynx

# Docker Compose Datei herunterladen
curl -fsSL https://raw.githubusercontent.com/moresonsunn/Lynx/main/docker-compose.yml -o docker-compose.yml

# Image herunterladen und starten
docker compose pull
docker compose up -d
```

---

## 🚀 Erster Start

Nach der Installation:

1. **Browser öffnen:** http://localhost:8000
2. **Einloggen:**
   - Benutzername: `admin`
   - Passwort: `admin123` oder `YourNewStrongPass123!`
3. **Sprache wählen:** Oben rechts auf der Login-Seite
4. **Passwort ändern:** Nach dem Login unter Settings → Security

---

## 📖 Wichtige Befehle

### Container-Management

| Befehl | Beschreibung |
|--------|-------------|
| `docker compose up -d` | Lynx starten (im Hintergrund) |
| `docker compose down` | Lynx stoppen |
| `docker compose restart` | Lynx neustarten |
| `docker compose logs -f` | Live-Logs anzeigen |
| `docker compose logs -f --tail=100` | Letzte 100 Log-Zeilen + Live |
| `docker compose ps` | Container-Status anzeigen |

### Update-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `docker compose pull` | Neueste Images herunterladen |
| `docker compose up -d` | Mit neuen Images starten |
| `docker compose pull && docker compose up -d` | Update in einem Befehl |

### Build-Befehle (für Entwickler)

| Befehl | Beschreibung |
|--------|-------------|
| `docker compose build` | Image lokal bauen |
| `docker compose build --no-cache` | Komplett neu bauen |
| `docker compose up -d --build` | Bauen und starten |

### Aufräum-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `docker compose down` | Container stoppen und entfernen |
| `docker compose down -v` | ⚠️ + Alle Daten löschen! |
| `docker system prune` | Ungenutzte Docker-Ressourcen löschen |
| `docker image prune -a` | Ungenutzte Images löschen |

### Debugging-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `docker compose exec lynx bash` | Shell im Container öffnen |
| `docker stats` | Ressourcenverbrauch anzeigen |
| `docker inspect lynx-lynx-1` | Container-Details anzeigen |
| `curl http://localhost:8000/health/quick` | Health-Check |

---

## 🎮 Minecraft-Server verwalten

### Neuen Minecraft-Server erstellen

1. Klicke auf "New Server" oder "+" im Dashboard
2. Wähle Server-Typ (Vanilla, Paper, Forge, Fabric, Purpur, NeoForge)
3. Wähle Minecraft-Version
4. Gib einen Namen ein
5. Klicke auf "Create"

### Server-Aktionen

| Aktion | Beschreibung |
|--------|-------------|
| ▶️ Start | Server starten |
| ⏸️ Stop | Server stoppen |
| 🔄 Restart | Server neustarten |
| 🗑️ Delete | Server löschen |
| 📁 Files | Dateimanager öffnen |
| 💾 Backup | Backup erstellen |

### Ports

- Lynx Web-Interface: `8000`
- Minecraft-Server: Beginnt bei `25565`, dann automatisch `25566`, `25567`, etc.

---

## 🎮 Steam-Server erstellen

Lynx unterstützt **70+ Steam-Spiele** – von Valheim bis Counter-Strike.

### Neuen Steam-Server erstellen

1. Gehe zum "Steam Games" Tab in der Seitenleiste
2. Durchsuche oder filtere die verfügbaren Spiele
3. Klicke auf das gewünschte Spiel
4. Passe Name und Einstellungen an (z.B. MAX_PLAYERS, SERVER_PASSWORD)
5. Klicke auf "Create Server"

### Beliebte Steam-Spiele

| Spiel | Beschreibung |
|-------|-------------|
| Valheim | Wikinger-Survival |
| Rust | Hardcore-Survival |
| ARK: Survival Evolved | Dinosaurier-Survival |
| Terraria | 2D-Sandbox-Abenteuer |
| Palworld | Pokémon-artiges Survival |
| Counter-Strike 2 | Taktischer Shooter |
| Project Zomboid | Zombie-Survival |
| The Forest / Sons of the Forest | Horror-Survival |
| 7 Days to Die | Zombie-Survival |
| V Rising | Vampir-Survival |

### CasaOS-Integration

Auf CasaOS können Steam-Server als native v2-Apps installiert werden:

1. Setze `CASAOS_API_TOKEN` in den Lynx-Umgebungsvariablen
2. Steam-Server erscheinen dann in CasaOS als reguläre Apps
3. Siehe README.md für Details zur Token-Ermittlung

---

## ❓ Fehlerbehebung

### "Docker is not running"

**macOS:**
```bash
# Docker Desktop aus Applications starten
# Oder:
open -a Docker
```

**Windows:**
```powershell
# Docker Desktop aus dem Startmenü starten
```

**Linux:**
```bash
sudo systemctl start docker
sudo systemctl enable docker  # Autostart aktivieren
```

### "Permission denied"

**Linux:**
```bash
sudo usermod -aG docker $USER
# Dann ausloggen und wieder einloggen
```

**Windows:**
- PowerShell als Administrator ausführen

### "Port 8000 already in use"

Finde heraus, was den Port nutzt:

**macOS/Linux:**
```bash
lsof -i :8000
# Oder anderen Port nutzen:
# In docker-compose.yml ändern: "8080:8000"
```

**Windows:**
```powershell
netstat -an | findstr 8000
```

### "No matching manifest for linux/arm64"

Auf Apple Silicon Macs muss lokal gebaut werden:
```bash
docker compose build
docker compose up -d
```

### "Cannot connect to Docker daemon"

**macOS/Windows:**
- Docker Desktop starten und warten

**Linux:**
```bash
sudo systemctl start docker
```

### Container startet nicht

```bash
# Logs prüfen
docker compose logs

# Container-Status prüfen
docker compose ps

# Neustart erzwingen
docker compose down
docker compose up -d
```

### Daten sichern

```bash
# Alle Volumes anzeigen
docker volume ls

# Volume-Pfad finden
docker volume inspect lynx_servers_data

# Backup erstellen (Linux/macOS)
docker run --rm -v lynx_servers_data:/data -v $(pwd):/backup alpine tar czf /backup/servers-backup.tar.gz /data
```

---

## 🌐 Netzwerk-Zugriff

### Lokaler Zugriff
- URL: `http://localhost:8000`

### Im Netzwerk (andere Geräte)
1. Finde deine IP-Adresse:
   - **macOS/Linux:** `ifconfig | grep inet` oder `ip addr`
   - **Windows:** `ipconfig`
2. Öffne im Browser: `http://DEINE-IP:8000`

### Firewall öffnen

**macOS:** Automatisch erlaubt (Docker Desktop)

**Windows:** Docker Desktop konfiguriert die Firewall

**Linux:**
```bash
# UFW
sudo ufw allow 8000
sudo ufw allow 25565

# Firewalld
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --add-port=25565/tcp --permanent
sudo firewall-cmd --reload
```

---

## 📱 Unterstützte Sprachen

Lynx unterstützt 28 Sprachen:

🇬🇧 English, 🇩🇪 Deutsch, 🇪🇸 Español, 🇫🇷 Français, 🇮🇹 Italiano, 🇵🇹 Português, 🇷🇺 Русский, 🇨🇳 中文, 🇯🇵 日本語, 🇰🇷 한국어, 🇵🇱 Polski, 🇳🇱 Nederlands, 🇹🇷 Türkçe, 🇸🇦 العربية, 🇸🇪 Svenska, 🇩🇰 Dansk, 🇳🇴 Norsk, 🇫🇮 Suomi, 🇨🇿 Čeština, 🇺🇦 Українська, 🇭🇺 Magyar, 🇷🇴 Română, 🇬🇷 Ελληνικά, 🇹🇭 ไทย, 🇻🇳 Tiếng Việt, 🇮🇩 Bahasa Indonesia, 🇮🇳 हिन्दी

Sprache wechseln: Oben rechts auf der Login-Seite oder im Sidebar-Menü

---

## 📞 Hilfe & Support

- **GitHub Issues:** https://github.com/moresonsunn/Lynx/issues
- **README:** https://github.com/moresonsunn/Lynx/blob/main/README.md
- **Logs:** `docker compose logs -f`

---

*Lynx - Minecraft Server Management Made Easy* 🎮
