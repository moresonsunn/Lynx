# Optimierte Unified Lynx Image: Backend API + gebautes Frontend + Multi-Java Runtime
# Diese Datei ersetzt die alte, langsame unified.Dockerfile.

# ---- Stage 1: Frontend bauen ----
FROM node:20-alpine AS ui
WORKDIR /ui

# Abhängigkeiten installieren (mit explizitem react-is)
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps && npm install react-is --save-dev

# Frontend-Quellcode kopieren und bauen
COPY frontend ./
ENV NODE_ENV=production
RUN npm run build

# ---- Stage 2: Haupt-Image ----
# Basis: Eclipse Temurin 21 (enthält bereits Java 21)
FROM eclipse-temurin:21-jdk-jammy AS unified
WORKDIR /app

# Build-Argumente für Versionierung
ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown

# OCI-Labels für bessere Rückverfolgbarkeit
LABEL org.opencontainers.image.title="Lynx" \
      org.opencontainers.image.description="Lynx Controller + statisches Frontend + Multi-Java Runtime" \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.source="https://github.com/moresonsun/Lynx" \
      org.opencontainers.image.licenses="MIT"

# ---- APT-Mirror für schnellere Downloads ----
RUN sed -i 's/archive.ubuntu.com/mirror.rackspace.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirror.rackspace.com/g' /etc/apt/sources.list

# ---- System-Abhängigkeiten ----
# Split into multiple RUN commands to avoid QEMU segfaults on ARM64
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    gcc curl wget unzip bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- Multi-Java Toolchain (Java 8, 11, 17) ----
RUN ARCH=$(dpkg --print-architecture) && \
    echo "=== Detected architecture: $ARCH ===" && \
    if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then \
        JAVA8_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u392-b08/OpenJDK8U-jdk_aarch64_linux_hotspot_8u392b08.tar.gz"; \
        JAVA8_DIR="jdk8u392-b08"; \
        JAVA11_URL="https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.21%2B9/OpenJDK11U-jdk_aarch64_linux_hotspot_11.0.21_9.tar.gz"; \
        JAVA11_DIR="jdk-11.0.21+9"; \
        JAVA17_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9%2B9/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.9_9.tar.gz"; \
        JAVA17_DIR="jdk-17.0.9+9"; \
    else \
        JAVA8_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u392-b08/OpenJDK8U-jdk_x64_linux_hotspot_8u392b08.tar.gz"; \
        JAVA8_DIR="jdk8u392-b08"; \
        JAVA11_URL="https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.21%2B9/OpenJDK11U-jdk_x64_linux_hotspot_11.0.21_9.tar.gz"; \
        JAVA11_DIR="jdk-11.0.21+9"; \
        JAVA17_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz"; \
        JAVA17_DIR="jdk-17.0.9+9"; \
    fi && \
    echo "Downloading Java 8..." && \
    wget -qO- "$JAVA8_URL" | tar -xz -C /opt/ && \
    ln -sf /opt/$JAVA8_DIR/bin/java /usr/local/bin/java8 && \
    echo "Downloading Java 11..." && \
    wget -qO- "$JAVA11_URL" | tar -xz -C /opt/ && \
    ln -sf /opt/$JAVA11_DIR/bin/java /usr/local/bin/java11 && \
    echo "Downloading Java 17..." && \
    wget -qO- "$JAVA17_URL" | tar -xz -C /opt/ && \
    ln -sf /opt/$JAVA17_DIR/bin/java /usr/local/bin/java17

# ---- Java 21 Symlink ----
RUN if [ -x "/opt/java/openjdk/bin/java" ]; then \
        ln -sf /opt/java/openjdk/bin/java /usr/local/bin/java21; \
    elif [ -n "$JAVA_HOME" ] && [ -x "$JAVA_HOME/bin/java" ]; then \
        ln -sf "$JAVA_HOME/bin/java" /usr/local/bin/java21; \
    elif command -v java >/dev/null 2>&1; then \
        ln -sf "$(command -v java)" /usr/local/bin/java21; \
    else \
        echo "WARNING: Could not find Java 21 to create symlink"; \
    fi

# ---- Fallback /usr/bin/java Symlink ----
RUN if [ ! -x "/usr/bin/java" ] && [ -x "/opt/java/openjdk/bin/java" ]; then \
        ln -sf /opt/java/openjdk/bin/java /usr/bin/java; \
    fi

# ---- Java-Installationen verifizieren ----
RUN echo "=== Verifying Java installations ===" && \
    ls -la /usr/local/bin/java* && \
    echo "Java 8:" && /usr/local/bin/java8 -version 2>&1 | head -1 && \
    echo "Java 11:" && /usr/local/bin/java11 -version 2>&1 | head -1 && \
    echo "Java 17:" && /usr/local/bin/java17 -version 2>&1 | head -1 && \
    echo "Java 21:" && /usr/local/bin/java21 -version 2>&1 | head -1

# ---- Runtime-Entrypoint ----
COPY docker/runtime-entrypoint.sh /usr/local/bin/runtime-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/runtime-entrypoint.sh && chmod +x /usr/local/bin/runtime-entrypoint.sh

# ---- Umgebungsvariablen ----
ENV JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Dsun.java2d.noddraw=true -Djava.net.preferIPv4Stack=true" \
    APP_VERSION=$APP_VERSION \
    GIT_COMMIT=$GIT_COMMIT

# ---- Python-Abhängigkeiten ----
COPY backend/requirements.txt ./
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH="/opt/venv/bin:$PATH"

# ---- Backend und Frontend kopieren ----
COPY backend ./
COPY --from=ui /ui/build ./static

# ---- Datenverzeichnisse ----
RUN mkdir -p /data/servers /data/sqlite

# ---- Ports ----
ENV PORT=8000
EXPOSE 8000 25565

# ---- Modus-Erkennung ----
ENV LYNX_UNIFIED_IMAGE=1 \
    BLOCKPANEL_UNIFIED_IMAGE=1

# ---- Startbefehl ----
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]