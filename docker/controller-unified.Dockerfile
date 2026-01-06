# Unified Lynx image: backend API + built frontend + embedded multi-Java runtime
# This eliminates the separate runtime image for single-container deployments.

FROM node:20-alpine AS ui
WORKDIR /ui
ENV NODE_ENV=production
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev --silent; else npm install --omit=dev --silent; fi
COPY frontend ./
RUN npm run build

# Base: start from OpenJDK 21 (includes Java 21)
# Use Eclipse Temurin as official OpenJDK base to ensure tag stability across arches
FROM eclipse-temurin:21-jdk-jammy AS unified
WORKDIR /app

ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown

LABEL org.opencontainers.image.title="Lynx" \
    org.opencontainers.image.description="Lynx controller + static frontend + embedded multi-Java runtime" \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.source="https://github.com/moresonsun/Lynx" \
      org.opencontainers.image.licenses="MIT"

# System deps (minimal headless set to reduce multi-arch emulation issues)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev gcc curl wget unzip bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Multi-Java toolchain (8, 11, 17 already added manually like runtime image)
# Note: eclipse-temurin:21-jdk-jammy has Java 21 at /opt/java/openjdk/bin/java
RUN echo "=== Finding Java 21 location ===" && \
    ls -la /opt/java/ 2>/dev/null || true && \
    ls -la /opt/java/openjdk/bin/ 2>/dev/null || true && \
    echo "JAVA_HOME=$JAVA_HOME" && \
    which java || true

RUN wget -qO- https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u392-b08/OpenJDK8U-jdk_x64_linux_hotspot_8u392b08.tar.gz | tar -xz -C /opt/ && \
    ln -sf /opt/jdk8u392-b08/bin/java /usr/local/bin/java8 && \
    wget -qO- https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.21%2B9/OpenJDK11U-jdk_x64_linux_hotspot_11.0.21_9.tar.gz | tar -xz -C /opt/ && \
    ln -sf /opt/jdk-11.0.21+9/bin/java /usr/local/bin/java11 && \
    wget -qO- https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz | tar -xz -C /opt/ && \
    ln -sf /opt/jdk-17.0.9+9/bin/java /usr/local/bin/java17

# Create Java 21 symlink - try multiple possible locations
RUN if [ -x "/opt/java/openjdk/bin/java" ]; then \
        ln -sf /opt/java/openjdk/bin/java /usr/local/bin/java21; \
    elif [ -n "$JAVA_HOME" ] && [ -x "$JAVA_HOME/bin/java" ]; then \
        ln -sf "$JAVA_HOME/bin/java" /usr/local/bin/java21; \
    elif command -v java >/dev/null 2>&1; then \
        ln -sf "$(command -v java)" /usr/local/bin/java21; \
    else \
        echo "WARNING: Could not find Java 21 to create symlink"; \
    fi

# Also add java to PATH and create /usr/bin/java symlink as fallback
RUN if [ ! -x "/usr/bin/java" ]; then \
        if [ -x "/opt/java/openjdk/bin/java" ]; then \
            ln -sf /opt/java/openjdk/bin/java /usr/bin/java; \
        fi; \
    fi

# Verify Java installations
RUN echo "=== Verifying Java installations ===" && \
    ls -la /usr/local/bin/java* && \
    ls -la /usr/bin/java 2>/dev/null || echo "No /usr/bin/java" && \
    echo "Java 8:" && /usr/local/bin/java8 -version 2>&1 | head -1 && \
    echo "Java 11:" && /usr/local/bin/java11 -version 2>&1 | head -1 && \
    echo "Java 17:" && /usr/local/bin/java17 -version 2>&1 | head -1 && \
    echo "Java 21:" && /usr/local/bin/java21 -version 2>&1 | head -1

# Include runtime entrypoint so unified image can act as runtime image for server containers
COPY docker/runtime-entrypoint.sh /usr/local/bin/runtime-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/runtime-entrypoint.sh && chmod +x /usr/local/bin/runtime-entrypoint.sh

ENV JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Dsun.java2d.noddraw=true -Djava.net.preferIPv4Stack=true" \
    APP_VERSION=$APP_VERSION \
    GIT_COMMIT=$GIT_COMMIT

# Python dependencies (use venv to avoid Debian PEP 668 externally managed restriction)
COPY backend/requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/venv/bin:$PATH"

# Copy backend
COPY backend ./
# Copy built frontend
COPY --from=ui /ui/build ./static

# Data dirs
RUN mkdir -p /data/servers /data/sqlite
ENV PORT=8000
EXPOSE 8000 25565

# Provide an internal marker so backend can detect unified mode
ENV LYNX_UNIFIED_IMAGE=1 \
    BLOCKPANEL_UNIFIED_IMAGE=1

# Uvicorn startup (same as controller base)
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
