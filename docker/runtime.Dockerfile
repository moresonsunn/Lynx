FROM eclipse-temurin:21-jdk
# Build metadata (populated via build args in CI)
ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown

LABEL org.opencontainers.image.title="Lynx Runtime" \
    org.opencontainers.image.description="Lynx runtime container providing multiple Java versions for Minecraft servers" \
    org.opencontainers.image.version=$APP_VERSION \
    org.opencontainers.image.revision=$GIT_COMMIT \
    org.opencontainers.image.source="https://github.com/moresonsun/Minecraft-Controller" \
    org.opencontainers.image.licenses="MIT"

# Install tools and available Java versions
RUN apt-get update && apt-get install -y \
    bash \
    wget \
    curl \
    unzip \
    ca-certificates \
    fontconfig \
    libfreetype6 \
    libxi6 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Dsun.java2d.noddraw=true -Djava.net.preferIPv4Stack=true"
ENV APP_VERSION=$APP_VERSION \
    GIT_COMMIT=$GIT_COMMIT \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true -Dsun.java2d.noddraw=true -Djava.net.preferIPv4Stack=true"

# Download and install Java 8, 11, 17 (Eclipse Temurin) with multi-arch support
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

# Create symlink for Java 21 from base Temurin image
RUN ln -sf /opt/java/openjdk/bin/java /usr/local/bin/java21 && \
    # Verify the symlink was created correctly
    ls -la /usr/local/bin/java21 && \
    /usr/local/bin/java21 -version

# Verify all Java versions are accessible
RUN echo "=== Java installations ===" && \
    ls -la /usr/local/bin/java* && \
    echo "Java 8:" && /usr/local/bin/java8 -version 2>&1 | head -1 && \
    echo "Java 11:" && /usr/local/bin/java11 -version 2>&1 | head -1 && \
    echo "Java 17:" && /usr/local/bin/java17 -version 2>&1 | head -1 && \
    echo "Java 21:" && /usr/local/bin/java21 -version 2>&1 | head -1

# Set default Java version
ENV JAVA_BIN=/usr/local/bin/java21

WORKDIR /data
EXPOSE 25565
# The build context is the repo root, and the script is in the docker/ folder
COPY docker/runtime-entrypoint.sh /usr/local/bin/runtime-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/runtime-entrypoint.sh && chmod +x /usr/local/bin/runtime-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/runtime-entrypoint.sh"]
