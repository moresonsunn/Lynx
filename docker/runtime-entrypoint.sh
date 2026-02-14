#!/bin/bash
set -e

# Function to determine the appropriate Java version based on server type and version
select_java_version() {
    local server_type="$1"
    local version="$2"
    
    # Default to Java 21 (modern, LTS; compatible with most recent servers)
  local java_version="21"
  echo "DEBUG: select_java_version: type='${server_type}', version='${version}'" >&2
    
    case "$server_type" in
    "vanilla"|"paper"|"purpur")
      # For 1.8-1.16 -> Java 8; 1.17-1.18 -> Java 17; 1.19+ -> Java 21
            if [[ "$version" == 1.8* ]] || [[ "$version" == 1.9* ]] || [[ "$version" == 1.10* ]] || [[ "$version" == 1.11* ]] || [[ "$version" == 1.12* ]] || [[ "$version" == 1.13* ]] || [[ "$version" == 1.14* ]] || [[ "$version" == 1.15* ]] || [[ "$version" == 1.16* ]]; then
                echo "DEBUG: select_java_version: vanilla/paper/purpur matched 1.8-1.16 -> Java 8" >&2
                java_version="8"
            elif [[ "$version" == 1.17* ]] || [[ "$version" == 1.18* ]]; then
                echo "DEBUG: select_java_version: vanilla/paper/purpur matched 1.17-1.18 -> Java 17" >&2
                java_version="17"
            elif [[ "$version" == 1.19* ]] || [[ "$version" == 1.20* ]] || [[ "$version" == 1.21* ]]; then
                echo "DEBUG: select_java_version: vanilla/paper/purpur matched 1.19+ -> Java 21" >&2
                java_version="21"
            else
                echo "DEBUG: select_java_version: vanilla/paper/purpur no explicit match; keeping default ${java_version}" >&2
            fi
            ;;
  "fabric"|"quilt"|"banner")
      # Fabric/Quilt/Banner: 1.8-1.16 -> Java 8; 1.17-1.18 -> Java 17; 1.19+ -> Java 21
      if [[ "$version" == 1.19* ]] || [[ "$version" == 1.20* ]] || [[ "$version" == 1.21* ]]; then
  echo "DEBUG: select_java_version: fabric/quilt matched 1.19+ -> Java 21" >&2
        java_version="21"
      elif [[ "$version" == 1.17* ]] || [[ "$version" == 1.18* ]]; then
  echo "DEBUG: select_java_version: fabric/quilt matched 1.17-1.18 -> Java 17" >&2
        java_version="17"
      else
  echo "DEBUG: select_java_version: fabric/quilt matched <=1.16 -> Java 8" >&2
        java_version="8"
      fi
      ;;
  "forge"|"neoforge"|"mohist"|"magma"|"catserver"|"spongeforge")
      # Forge-based hybrids: <=1.12 -> Java 8; 1.13-1.20.4 -> Java 17; 1.20.5+/1.21+ -> Java 21
      if [[ "$version" == 1.8* ]] || [[ "$version" == 1.9* ]] || [[ "$version" == 1.10* ]] || [[ "$version" == 1.11* ]] || [[ "$version" == 1.12* ]]; then
                echo "DEBUG: select_java_version: forge-hybrid matched <=1.12 -> Java 8" >&2
                java_version="8"
      elif [[ "$version" == 1.20.5* ]] || [[ "$version" == 1.20.6* ]] || [[ "$version" == 1.21* ]]; then
  echo "DEBUG: select_java_version: forge-hybrid matched 1.20.5+/1.21+ -> Java 21" >&2
        java_version="21"
            else
                echo "DEBUG: select_java_version: forge-hybrid matched 1.13-1.20.4 -> Java 17" >&2
                java_version="17"
            fi
            ;;
    esac
    
    echo "$java_version"
}

# Function to detect Minecraft version from server files
detect_mc_version() {
    local version=""
    
    # Try version.json (Fabric/Paper/Purpur often have this)
    if [ -f "version.json" ] && command -v grep >/dev/null 2>&1; then
        version=$(grep -oP '"id"\s*:\s*"\K[^"]+' version.json 2>/dev/null | head -1)
        [ -n "$version" ] && echo "$version" && return
    fi
    
    # Try .fabric/server/version.json
    if [ -f ".fabric/server/version.json" ]; then
        version=$(grep -oP '"id"\s*:\s*"\K[^"]+' .fabric/server/version.json 2>/dev/null | head -1)
        [ -n "$version" ] && echo "$version" && return
    fi
    
    # Try server_meta.json 
    if [ -f "server_meta.json" ]; then
        version=$(grep -oP '"detected_version"\s*:\s*"\K[^"]+' server_meta.json 2>/dev/null | head -1)
        [ -n "$version" ] && echo "$version" && return
        version=$(grep -oP '"server_version"\s*:\s*"\K[^"]+' server_meta.json 2>/dev/null | head -1)
        [ -n "$version" ] && echo "$version" && return
        version=$(grep -oP '"version"\s*:\s*"\K[^"]+' server_meta.json 2>/dev/null | head -1)
        [ -n "$version" ] && echo "$version" && return
    fi
    
    # Try to extract version from jar filename
    for jar in paper-*.jar purpur-*.jar; do
        if [ -f "$jar" ]; then
            version=$(echo "$jar" | grep -oP '(1\.\d+(\.\d+)?)' | head -1)
            [ -n "$version" ] && echo "$version" && return
        fi
    done
    
    echo ""
}

# Get server type and version from environment or labels
SERVER_TYPE="${SERVER_TYPE:-}"
SERVER_VERSION="${SERVER_VERSION:-}"

# If SERVER_VERSION is empty, try to detect it
if [ -z "$SERVER_VERSION" ]; then
    echo "DEBUG: SERVER_VERSION not set; attempting auto-detection..."
    detected_ver=$(detect_mc_version)
    if [ -n "$detected_ver" ]; then
        SERVER_VERSION="$detected_ver"
        echo "DEBUG: Auto-detected Minecraft version: $SERVER_VERSION"
    else
        echo "DEBUG: Could not auto-detect version; will use Java 21 as default"
    fi
fi

# Get Java version override and JAVA_BIN override from environment
JAVA_VERSION_OVERRIDE="${JAVA_VERSION_OVERRIDE:-}"
JAVA_BIN_OVERRIDE="${JAVA_BIN_OVERRIDE:-}"
# Optional override for which jar to launch
SERVER_JAR="${SERVER_JAR:-}"

# Compute JAVA_VERSION from server type/version unless explicitly overridden
JAVA_VERSION=$(select_java_version "$SERVER_TYPE" "$SERVER_VERSION")
if [ -n "$JAVA_VERSION_OVERRIDE" ]; then
  echo "DEBUG: Overriding selected Java version with JAVA_VERSION_OVERRIDE=$JAVA_VERSION_OVERRIDE"
  JAVA_VERSION="$JAVA_VERSION_OVERRIDE"
fi
export JAVA_VERSION

# Function to find any working Java binary
find_any_java() {
  local candidates=(
    "/usr/local/bin/java${JAVA_VERSION}"
    "/opt/java/openjdk/bin/java"
    "/usr/lib/jvm/java-${JAVA_VERSION}-openjdk-amd64/bin/java"
    "/usr/lib/jvm/java-${JAVA_VERSION}-openjdk/bin/java"
    "/usr/lib/jvm/temurin-${JAVA_VERSION}-jdk/bin/java"
    "/usr/lib/jvm/adoptopenjdk-${JAVA_VERSION}-hotspot/bin/java"
    "/opt/jdk8u392-b08/bin/java"
    "/opt/jdk-11.0.21+9/bin/java"
    "/opt/jdk-17.0.9+9/bin/java"
    "/opt/jdk-21.0.5+9/bin/java"
    "/usr/local/bin/java21"
    "/usr/local/bin/java17"
    "/usr/local/bin/java11"
    "/usr/local/bin/java8"
    "/usr/bin/java"
  )
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  # Try command -v as last resort
  if command -v java >/dev/null 2>&1; then
    command -v java
    return 0
  fi
  return 1
}

# Set Java binary path: prefer explicit override, else pick by JAVA_VERSION
if [ -n "$JAVA_BIN_OVERRIDE" ]; then
  JAVA_BIN="$JAVA_BIN_OVERRIDE"
else
  JAVA_BIN="/usr/local/bin/java${JAVA_VERSION}"
fi

# Fallback if the desired JAVA_BIN doesn't exist or isn't executable
if [ ! -x "$JAVA_BIN" ]; then
  echo "DEBUG: Primary Java path $JAVA_BIN not executable; searching for alternatives..."
  
  # Try the explicit version symlink via command -v
  if command -v "java${JAVA_VERSION}" >/dev/null 2>&1; then
    JAVA_BIN="$(command -v "java${JAVA_VERSION}")"
    echo "DEBUG: Falling back to discovered java${JAVA_VERSION} at: $JAVA_BIN"
  # Try /opt/java/openjdk (Temurin base image default for Java 21)
  elif [ -x "/opt/java/openjdk/bin/java" ]; then
    JAVA_BIN="/opt/java/openjdk/bin/java"
    echo "DEBUG: Falling back to Temurin default Java at: $JAVA_BIN"
  # Try common alternative paths for Debian/Ubuntu
  elif [ -x "/usr/lib/jvm/java-${JAVA_VERSION}-openjdk-amd64/bin/java" ]; then
    JAVA_BIN="/usr/lib/jvm/java-${JAVA_VERSION}-openjdk-amd64/bin/java"
    echo "DEBUG: Falling back to OpenJDK amd64 at: $JAVA_BIN"
  elif [ -x "/usr/lib/jvm/java-${JAVA_VERSION}-openjdk/bin/java" ]; then
    JAVA_BIN="/usr/lib/jvm/java-${JAVA_VERSION}-openjdk/bin/java"
    echo "DEBUG: Falling back to OpenJDK at: $JAVA_BIN"
  elif [ -x "/usr/lib/jvm/temurin-${JAVA_VERSION}-jdk/bin/java" ]; then
    JAVA_BIN="/usr/lib/jvm/temurin-${JAVA_VERSION}-jdk/bin/java"
    echo "DEBUG: Falling back to Temurin JDK at: $JAVA_BIN"
  # Try to find ANY working Java
  else
    echo "DEBUG: Searching for any available Java installation..."
    FOUND_JAVA=$(find_any_java)
    if [ -n "$FOUND_JAVA" ] && [ -x "$FOUND_JAVA" ]; then
      JAVA_BIN="$FOUND_JAVA"
      echo "DEBUG: Found working Java at: $JAVA_BIN"
    else
      echo "ERROR: No suitable Java found for version ${JAVA_VERSION}" >&2
      echo "DEBUG: Listing available Java installations..."
      ls -la /usr/local/bin/java* 2>/dev/null || echo "  No /usr/local/bin/java* found"
      ls -la /opt/java/openjdk/bin/java 2>/dev/null || echo "  No /opt/java/openjdk/bin/java found"
      ls -la /opt/jdk*/bin/java 2>/dev/null || echo "  No /opt/jdk*/bin/java found"
      ls -la /usr/lib/jvm/*/bin/java 2>/dev/null || echo "  No /usr/lib/jvm/*/bin/java found"
      ls -la /usr/bin/java 2>/dev/null || echo "  No /usr/bin/java found"
      echo "DEBUG: PATH=$PATH"
      echo "DEBUG: which java: $(which java 2>/dev/null || echo 'not found')"
      exit 1
    fi
  fi
fi

echo "DEBUG: Server type: $SERVER_TYPE, version: $SERVER_VERSION"
echo "DEBUG: Selected Java version: $JAVA_VERSION"
echo "DEBUG: Java binary: $JAVA_BIN"

# Configure memory settings from environment variables
MIN_RAM="${MIN_RAM:-1G}"
MAX_RAM="${MAX_RAM:-2G}"
MEM_ARGS="-Xmx${MAX_RAM} -Xms${MIN_RAM}"
JAVA_OPTS="${JAVA_OPTS:-}"
ALL_JAVA_ARGS="$MEM_ARGS $JAVA_OPTS"

echo "DEBUG: Memory configuration - Min: $MIN_RAM, Max: $MAX_RAM"
echo "DEBUG: Java memory args: $MEM_ARGS"
echo "DEBUG: Extra Java opts: $JAVA_OPTS"

# Debug: Print environment and directory info
echo "DEBUG: SERVER_DIR_NAME=$SERVER_DIR_NAME"
echo "DEBUG: WORKDIR=$WORKDIR"
echo "DEBUG: Current directory before change: $(pwd)"
echo "DEBUG: /data/servers exists: $([ -d "/data/servers" ] && echo "yes" || echo "no")"
[ -d "/data/servers" ] && echo "DEBUG: /data/servers contents: $(ls -la /data/servers)"

has_server_payload() {
  local d="$1"
  [ -d "$d" ] || return 1
  # If the container already started in the mounted server directory (common in CasaOS),
  # don't blindly cd to /data and lose access to the server jar.
  [ -f "$d/run.sh" ] && return 0
  for pat in "server.jar" "*paper*.jar" "*purpur*.jar" "*server*.jar"; do
    if compgen -G "$d/$pat" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

# Use current dir if it already looks like a server directory; otherwise use WORKDIR,
# then fall back to SERVER_DIR_NAME or /data.
if has_server_payload "$(pwd)"; then
  echo "DEBUG: Current directory contains server payload; keeping: $(pwd)"
elif [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
  cd "$WORKDIR"
  echo "DEBUG: Changed to WORKDIR: $(pwd)"
elif [ -n "$SERVER_DIR_NAME" ] && [ -d "/data/servers/$SERVER_DIR_NAME" ]; then
  cd "/data/servers/$SERVER_DIR_NAME"
  echo "DEBUG: Changed to /data/servers/$SERVER_DIR_NAME: $(pwd)"
elif [ -n "$SERVER_DIR_NAME" ] && [ -d "/data/$SERVER_DIR_NAME" ]; then
  cd "/data/$SERVER_DIR_NAME"
  echo "DEBUG: Changed to /data/$SERVER_DIR_NAME: $(pwd)"
else
  cd "/data"
  echo "DEBUG: Changed to /data: $(pwd)"
fi

# Ensure the Minecraft server binds to the expected container port.
# Lynx always publishes container port ${SERVER_PORT} (defaults to 25565).
# Many imported servers have server.properties set to the *host* port; that breaks container port publishing.
SERVER_PORT="${SERVER_PORT:-25565}"
if [ -f "server.properties" ]; then
  # Replace existing server-port line or append if missing.
  if grep -qE '^\s*server-port\s*=' server.properties; then
    # GNU sed compatible; keep it simple and overwrite the full value.
    sed -i -E "s/^\s*server-port\s*=.*/server-port=${SERVER_PORT}/" server.properties || true
  else
    echo "server-port=${SERVER_PORT}" >> server.properties
  fi
fi

# -------- Incompatible-loader & client-only purge --------
AUTO_CLIENT_PURGE=${AUTO_CLIENT_PURGE:-1}
AUTO_INCOMPATIBLE_PURGE=${AUTO_INCOMPATIBLE_PURGE:-1}
# Enable automatic crash recovery (disable problematic mods and retry)
AUTO_CRASH_RECOVERY=${AUTO_CRASH_RECOVERY:-1}
# Maximum auto-restart attempts before giving up
MAX_CRASH_RECOVERY_ATTEMPTS=${MAX_CRASH_RECOVERY_ATTEMPTS:-3}

have_unzip() { command -v unzip >/dev/null 2>&1; }
have_curl() { command -v curl >/dev/null 2>&1; }

load_extra_patterns() {
  # Sources: env var, optional URL, optional files (one pattern per line). All lowercased.
  local out=()
  # env var: comma-separated
  if [ -n "${CLIENT_ONLY_MOD_PATTERNS:-}" ]; then
    IFS=',' read -ra __tokarr <<< "${CLIENT_ONLY_MOD_PATTERNS}"
    for __tok in "${__tokarr[@]}"; do
      __tok="$(echo "$__tok" | tr '[:upper:]' '[:lower:]' | xargs)"
      [ -n "$__tok" ] && out+=("$__tok")
    done
  fi
  # URL: one per line, supports comments
  if [ -n "${CLIENT_ONLY_MOD_PATTERNS_URL:-}" ] && have_curl; then
    if curl -fsSL "$CLIENT_ONLY_MOD_PATTERNS_URL" -o /tmp/__client_only_list 2>/dev/null; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < /tmp/__client_only_list
      rm -f /tmp/__client_only_list 2>/dev/null || true
    fi
  fi
  # Files
  for cfg in "./client-only-mods.txt" "/data/servers/client-only-mods.txt"; do
    if [ -f "$cfg" ]; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < "$cfg"
    fi
  done
  printf '%s\n' "${out[@]}"
}

# Allowlist patterns for incompatible purge (never move if matched)
load_incompat_allowlist() {
  local out=()
  if [ -n "${INCOMPATIBLE_PURGE_ALLOWLIST:-}" ]; then
    IFS=',' read -ra __tokarr <<< "${INCOMPATIBLE_PURGE_ALLOWLIST}"
    for __tok in "${__tokarr[@]}"; do
      __tok="$(echo "$__tok" | tr '[:upper:]' '[:lower:]' | xargs)"
      [ -n "$__tok" ] && out+=("$__tok")
    done
  fi
  for cfg in "./incompatible-allowlist.txt" "/data/servers/incompatible-allowlist.txt"; do
    if [ -f "$cfg" ]; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < "$cfg"
    fi
  done
  printf '%s\n' "${out[@]}"
}

# Force patterns: always treated as client-only, regardless of metadata
load_force_patterns() {
  local out=()
  if [ -n "${CLIENT_ONLY_FORCE_PATTERNS:-}" ]; then
    IFS=',' read -ra __tokarr <<< "${CLIENT_ONLY_FORCE_PATTERNS}"
    for __tok in "${__tokarr[@]}"; do
      __tok="$(echo "$__tok" | tr '[:upper:]' '[:lower:]' | xargs)"
      [ -n "$__tok" ] && out+=("$__tok")
    done
  fi
  for cfg in "./client-only-force.txt" "/data/servers/client-only-force.txt"; do
    if [ -f "$cfg" ]; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < "$cfg"
    fi
  done
  printf '%s\n' "${out[@]}"
}


# Centralized list of known client-only mod patterns
# This is shared between purge_mods and crash recovery
get_known_client_patterns() {
  local patterns=(
    "iris" "oculus" "sodium" "embeddium" "rubidium" "optifine" "optifabric"
    "xaero" "journeymap" "voxelmap" "worldmap" "minimap"
    "replaymod" "replay" "dynamicfps" "dynamic-fps" "dynamic_fps"
    "lambdynamiclights" "betterf3" "better-f3" "itemphysic"
    "particular" "presence-footsteps" "soundphysics" "ambientsounds"
    "litematica" "minihud" "tweakeroo" "freecam" "flycam"
    "modmenu" "mod-menu" "controlling" "configured"
    "canvas-renderer" "immediatelyfast" "entityculling"
    "fpsreducer" "enhancedvisuals" "visuality" "cull-less-leaves"
    "skinlayers" "ears" "figura" "emotecraft" "emotes"
    "appleskin" "jade" "hwyla" "waila" "wthit" "emi" "rei"
    "blur" "smooth-boot" "smoothboot" "loadingscreen"
    "torohealth" "betterthirdperson" "cameraoverhaul" "citresewn"
    "shader" "dripsounds" "auditory" "extrasounds"
    "fancymenu" "konkrete" "drippyloadingscreen"
  )
  printf '%s\n' "${patterns[@]}"
}

is_client_only_jar() {
  local jar="$1"
  local has_meta=0
  if have_unzip; then
    # Fabric
    if unzip -p "$jar" fabric.mod.json >/tmp/__fmj 2>/dev/null; then
      has_meta=1
      if grep -qi '"environment"[[:space:]]*:[[:space:]]*"client"' /tmp/__fmj; then
        rm -f /tmp/__fmj
        return 0
      fi
      rm -f /tmp/__fmj
    fi
    # Quilt
    if unzip -p "$jar" quilt.mod.json >/tmp/__qmj 2>/dev/null; then
      has_meta=1
      if grep -qi '"environment"[[:space:]]*:[[:space:]]*"client"' /tmp/__qmj; then
        rm -f /tmp/__qmj
        return 0
      fi
      rm -f /tmp/__qmj
    fi
    # Forge heuristic via mods.toml
    if unzip -p "$jar" META-INF/mods.toml >/tmp/__mt 2>/dev/null; then
      has_meta=1
      # Strict: only treat as client-only if explicit boolean flags are present
      if grep -Eiq '(clientsideonly|onlyclient|client_only)\s*=\s*true' /tmp/__mt; then
        rm -f /tmp/__mt
        return 0
      fi
      rm -f /tmp/__mt
    fi
  fi
  
  local base lower
  base="$(basename "$jar")"
  lower="${base,,}"

  # Check against centralized known patterns
  # We check this EVEN IF metadata is present, because sometimes metadata is wrong or missing.
  # But we should be careful. Usually metadata wins. 
  # However, for known client-side-only mods like Optifine/Iris, we force it.
  # If metadata says "server", we trust it? 
  # Let's keep existing logic: Check metadata match FIRST.
  # If has_meta is 0, THEN check patterns.
  # BUT, load_force_patterns always runs.
  
  if [ "$has_meta" -eq 0 ]; then
    # Optional pattern fallback (from env/URL/files)
    while read -r pat; do
      [ -z "$pat" ] && continue
      [[ "$lower" == *"$pat"* ]] && return 0
    done < <(load_extra_patterns)
    
    # Internal known patterns (fallback)
    while read -r pat; do
      [ -z "$pat" ] && continue
      [[ "$lower" == *"$pat"* ]] && return 0
    done < <(get_known_client_patterns)
  fi

  # Force overrides: always apply
  while read -r fpat; do
    [ -z "$fpat" ] && continue
    [[ "$lower" == *"$fpat"* ]] && return 0
  done < <(load_force_patterns)
  
  return 1
}

detect_loader() {
  local jar="$1"
  local has_fabric=0
  local has_quilt=0
  local has_forge=0
  if have_unzip; then
    unzip -l "$jar" fabric.mod.json >/dev/null 2>&1 && has_fabric=1 || true
    unzip -l "$jar" quilt.mod.json  >/dev/null 2>&1 && has_quilt=1  || true
    unzip -l "$jar" META-INF/mods.toml >/dev/null 2>&1 && has_forge=1 || true
  fi
  if [ $has_forge -eq 1 ] && { [ $has_fabric -eq 1 ] || [ $has_quilt -eq 1 ]; }; then
    echo "both"
    return 0
  fi
  if [ $has_fabric -eq 1 ]; then echo "fabric"; return 0; fi
  if [ $has_quilt -eq 1 ]; then echo "quilt"; return 0; fi
  if [ $has_forge -eq 1 ]; then echo "forge"; return 0; fi
  echo ""
}

purge_mods() {
  local mods_dir="./mods"
  [ -d "$mods_dir" ] || return 0
  local disable_client_dir="./mods-disabled-client"
  local disable_incompat_dir="./mods-disabled-incompatible"
  mkdir -p "$disable_client_dir" "$disable_incompat_dir"
  
  # Ensure the allowlist file exists so the user knows where to use it
  if [ ! -f "client-only-allow.txt" ]; then
    touch "client-only-allow.txt"
    echo "# Add mod filenames (or parts of them) here to prevent them from being disabled as client-only." >> client-only-allow.txt
    echo "# Example: tooltipsfix" >> client-only-allow.txt
    
    # Also fix permissions if running as root/docker logic allows, though likely user is correct
    # no specific chown here as we assume container user is correct
  fi

  local moved_client=0
  local moved_incompat=0
  shopt -s nullglob
  for f in "$mods_dir"/*.jar; do
    # First, purge incompatible loader jars based on SERVER_TYPE
    if [ "$AUTO_INCOMPATIBLE_PURGE" = "1" ]; then
      loader="$(detect_loader "$f")"
      base_name="$(basename "$f")"; lower_name="${base_name,,}"
      # Check allowlist first
      allow_match=0
      while read -r ap; do
        [ -z "$ap" ] && continue
        if [[ "$lower_name" == *"$ap"* ]]; then allow_match=1; break; fi
      done < <(load_incompat_allowlist)
      if [ "$allow_match" = "1" ]; then
        echo "INFO: Allowlisted from incompatible purge: $base_name"
        continue
      fi
      # Skip incompatible purge for multi-loader jars
      if [ "$loader" = "both" ]; then
        : # compatible with both ecosystems; do not move
      elif { [ "$SERVER_TYPE" = "forge" ] || [ "$SERVER_TYPE" = "neoforge" ]; } && { [ "$loader" = "fabric" ] || [ "$loader" = "quilt" ]; }; then
        echo "INFO: Disabling incompatible loader (Fabric/Quilt on Forge): $(basename "$f")"
        mv -f "$f" "$disable_incompat_dir"/ || true
        moved_incompat=$((moved_incompat+1))
        continue
      fi
      if { [ "$SERVER_TYPE" = "fabric" ] || [ "$SERVER_TYPE" = "quilt" ]; } && [ "$loader" = "forge" ]; then
        echo "INFO: Disabling incompatible loader (Forge on Fabric/Quilt): $(basename "$f")"
        mv -f "$f" "$disable_incompat_dir"/ || true
        moved_incompat=$((moved_incompat+1))
        continue
      fi
    fi

# Allowlist patterns for client purge
load_client_allowlist() {
  local out=()
  if [ -n "${CLIENT_PURGE_ALLOWLIST:-}" ]; then
    IFS=',' read -ra __tokarr <<< "${CLIENT_PURGE_ALLOWLIST}"
    for __tok in "${__tokarr[@]}"; do
      __tok="$(echo "$__tok" | tr '[:upper:]' '[:lower:]' | xargs)"
      [ -n "$__tok" ] && out+=("$__tok")
    done
  fi
  for cfg in "./client-only-allow.txt" "/data/servers/client-only-allow.txt"; do
    if [ -f "$cfg" ]; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < "$cfg"
    fi
  done
  printf '%s\n' "${out[@]}"
}

    # Then, purge known client-only jars conservatively
    if [ "$AUTO_CLIENT_PURGE" = "1" ] && is_client_only_jar "$f"; then
      # Check allowlist
      base_name="$(basename "$f")"; lower_name="${base_name,,}"
      allow_match=0
      while read -r ap; do
        [ -z "$ap" ] && continue
        if [[ "$lower_name" == *"$ap"* ]]; then allow_match=1; break; fi
      done < <(load_client_allowlist)
      
      if [ "$allow_match" = "1" ]; then
        echo "INFO: Allowlisted from client purge: $base_name"
        continue
      fi

      echo "INFO: Disabling client-only mod: $(basename "$f")"
      mv -f "$f" "$disable_client_dir"/ || true
      moved_client=$((moved_client+1))
      continue
    fi
  done
  shopt -u nullglob
  [ "$moved_incompat" -gt 0 ] && echo "INFO: Moved $moved_incompat incompatible-loader mods to $disable_incompat_dir"
  [ "$moved_client" -gt 0 ] && echo "INFO: Moved $moved_client client-only mods to $disable_client_dir"
}

# Always run purge_mods (it respects the AUTO_* toggles internally)
purge_mods || true
# -------------------------------------------------------------------------

# Optionally disable problematic KubeJS datapacks referencing missing mods
AUTO_KUBEJS_PURGE=${AUTO_KUBEJS_PURGE:-1}

load_kubejs_disable_namespaces() {
  local out=()
  if [ -n "${KUBEJS_DISABLE_NAMESPACES:-}" ]; then
    IFS=',' read -ra __tokarr <<< "${KUBEJS_DISABLE_NAMESPACES}"
    for __tok in "${__tokarr[@]}"; do
      __tok="$(echo "$__tok" | tr '[:upper:]' '[:lower:]' | xargs)"
      [ -n "$__tok" ] && out+=("$__tok")
    done
  fi
  for cfg in "./kubejs-disable.txt" "./kubejs/kubejs-disable.txt"; do
    if [ -f "$cfg" ]; then
      while IFS= read -r __line || [ -n "$__line" ]; do
        __line="$(echo "$__line" | tr '[:upper:]' '[:lower:]' | sed 's/^\s\+//;s/\s\+$//')"
        if [ -n "$__line" ] && ! echo "$__line" | grep -qE '^#'; then
          out+=("$__line")
        fi
      done < "$cfg"
    fi
  done
  printf '%s\n' "${out[@]}"
}

disable_kubejs_namespace() {
  local ns="$1"
  local src="./kubejs/data/$ns"
  local dst="./kubejs/data.__disabled/$ns"
  if [ -d "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    echo "INFO: Disabling KubeJS datapack namespace: $ns"
    rm -rf "$dst" 2>/dev/null || true
    mv "$src" "$dst" || true
  fi
}

purge_kubejs_datapacks() {
  [ "$AUTO_KUBEJS_PURGE" = "1" ] || return 0
  [ -d ./kubejs/data ] || return 0
  # First, disable any namespaces explicitly provided via env/file
  while read -r ns; do
    [ -z "$ns" ] && continue
    disable_kubejs_namespace "$ns"
  done < <(load_kubejs_disable_namespaces)

  # Next, auto-disable namespaces whose backing mod isn't present
  # Heuristic: if no jar in ./mods (or disabled dirs) contains the namespace, move it out
  local mods_globs=("./mods" "./mods-disabled-client" "./mods-disabled-incompatible")
  for nsdir in ./kubejs/data/*; do
    [ -d "$nsdir" ] || continue
    ns="$(basename "$nsdir")"
    # Skip if already disabled explicitly above
    if [ -d "./kubejs/data.__disabled/$ns" ]; then
      continue
    fi
    # Check for any jar containing the namespace token
    local found=0
    for mg in "${mods_globs[@]}"; do
      [ -d "$mg" ] || continue
      if ls "$mg"/*"$ns"*.jar >/dev/null 2>&1; then
        found=1; break
      fi
    done
    if [ "$found" -eq 0 ]; then
      echo "INFO: KubeJS namespace '$ns' appears to target a missing mod; disabling"
      disable_kubejs_namespace "$ns"
    fi
  done
}

purge_kubejs_datapacks || true

# -------- Crash Recovery Functions --------
CRASH_RECOVERY_ATTEMPT=0

# Check if the latest crash report or log indicates a client-only mod issue
analyze_crash_for_client_mods() {
  local crash_dir="./crash-reports"
  local logs_dir="./logs"
  local found_client_issue=0
  
  # Client-only crash patterns
  local client_patterns=(
    "Client environment required"
    "Environment type CLIENT"
    "onlyIn.*CLIENT"
    "Dist.CLIENT"
    "No OpenGL context"
    "GLFW error"
    "org.lwjgl.opengl"
    "com.mojang.blaze3d"
    "net.minecraft.client"
    "RenderSystem.assert"
    "GlStateManager"
    "Display.*not created"
  )
  
  # Check latest crash report
  if [ -d "$crash_dir" ]; then
    local latest_crash
    latest_crash=$(ls -t "$crash_dir"/crash-*.txt 2>/dev/null | head -n1)
    if [ -n "$latest_crash" ] && [ -f "$latest_crash" ]; then
      for pattern in "${client_patterns[@]}"; do
        if grep -Eqi "$pattern" "$latest_crash" 2>/dev/null; then
          echo "INFO: Found client-only crash indicator: $pattern"
          found_client_issue=1
          break
        fi
      done
    fi
  fi
  
  # Check latest.log
  if [ "$found_client_issue" -eq 0 ] && [ -f "$logs_dir/latest.log" ]; then
    for pattern in "${client_patterns[@]}"; do
      if grep -Eqi "$pattern" "$logs_dir/latest.log" 2>/dev/null; then
        echo "INFO: Found client-only crash indicator in log: $pattern"
        found_client_issue=1
        break
      fi
    done
  fi
  
  return $found_client_issue
}

# Extract mod names from crash report and disable them
disable_crash_mods() {
  local crash_dir="./crash-reports"
  local mods_dir="./mods"
  local disable_dir="./mods-disabled-crash"
  local disabled_count=0
  
  [ -d "$mods_dir" ] || return 0
  mkdir -p "$disable_dir"
  
  # First, scan for known client-only mods
  shopt -s nullglob
  for jar in "$mods_dir"/*.jar; do
    local base lower
    base="$(basename "$jar")"
    lower="${base,,}"
    
    # Check metadata for environment=client
    local is_client=0
    if have_unzip; then
      if unzip -p "$jar" fabric.mod.json 2>/dev/null | grep -qi '"environment"[[:space:]]*:[[:space:]]*"client"'; then
        is_client=1
      elif unzip -p "$jar" quilt.mod.json 2>/dev/null | grep -qi '"environment"[[:space:]]*:[[:space:]]*"client"'; then
        is_client=1
      elif unzip -p "$jar" META-INF/mods.toml 2>/dev/null | grep -Eiq 'clientsideonly\s*=\s*true|client_only\s*=\s*true'; then
        is_client=1
      fi
    fi
    
    # Check against known patterns if not already identified
    if [ "$is_client" -eq 0 ]; then
      while read -r pattern; do
        if [[ "$lower" == *"$pattern"* ]]; then
          is_client=1
          break
        fi
      done < <(get_known_client_patterns)
    fi
    
    if [ "$is_client" -eq 1 ]; then
      echo "INFO: [Crash Recovery] Disabling client-only mod: $base"
      mv -f "$jar" "$disable_dir/" || true
      disabled_count=$((disabled_count+1))
    fi
  done
  shopt -u nullglob
  
  echo "INFO: [Crash Recovery] Disabled $disabled_count mods"
  return $disabled_count
}

# Main crash recovery handler
handle_crash_recovery() {
  local exit_code="$1"
  
  if [ "$AUTO_CRASH_RECOVERY" != "1" ]; then
    echo "INFO: Auto crash recovery disabled. Exiting with code $exit_code"
    exit "$exit_code"
  fi
  
  CRASH_RECOVERY_ATTEMPT=$((CRASH_RECOVERY_ATTEMPT+1))
  
  if [ "$CRASH_RECOVERY_ATTEMPT" -gt "$MAX_CRASH_RECOVERY_ATTEMPTS" ]; then
    echo "ERROR: Maximum crash recovery attempts ($MAX_CRASH_RECOVERY_ATTEMPTS) reached. Manual intervention required."
    exit "$exit_code"
  fi
  
  echo "INFO: =========================================="
  echo "INFO: Crash detected (exit code: $exit_code)"
  echo "INFO: Recovery attempt $CRASH_RECOVERY_ATTEMPT of $MAX_CRASH_RECOVERY_ATTEMPTS"
  echo "INFO: =========================================="
  
  # Analyze crash and try to fix
  if analyze_crash_for_client_mods; then
    echo "INFO: Client-only mod crash detected. Attempting auto-fix..."
    disable_crash_mods
    
    # Re-run purge functions
    echo "INFO: Running additional purge operations..."
    purge_mods || true
    
    echo "INFO: Restarting server in 5 seconds..."
    sleep 5
    
    # Restart the server
    return 0  # Signal to retry
  else
    echo "INFO: Could not identify crash cause. Running general purge and retrying..."
    disable_crash_mods
    sleep 3
    return 0  # Still try to restart
  fi
}

# Run installer if present (forge/neoforge)
INSTALLER_JAR=$(ls *installer*.jar 2>/dev/null || true)
if [ -n "$INSTALLER_JAR" ]; then
  echo "Running installer: $INSTALLER_JAR"
  # Use --installServer (note the capital S) for headless installation
  "$JAVA_BIN" -jar "$INSTALLER_JAR" --installServer || {
    echo "Installer failed, trying alternative flags..." >&2
    # Some older Forge versions might use different flags
    "$JAVA_BIN" -jar "$INSTALLER_JAR" --install-server || {
      echo "Installer failed with both flags" >&2
      exit 1
    }
  }
  rm -f *installer*.jar || true
  
  # For NeoForge, the installer creates a JAR with a specific naming pattern
  # Look for the generated server JAR
  echo "DEBUG: Looking for generated server JAR after installer"
  echo "DEBUG: Current directory contents after installer: $(ls -la)"
  
  # NeoForge creates JARs like: neoforge-{version}-universal.jar
  NEOFORGE_JAR=$(ls neoforge-*-universal.jar 2>/dev/null | head -n 1)
  if [ -n "$NEOFORGE_JAR" ]; then
    echo "DEBUG: Found NeoForge JAR: $NEOFORGE_JAR"
    # Rename to server.jar for consistency
    mv "$NEOFORGE_JAR" server.jar
    echo "DEBUG: Renamed $NEOFORGE_JAR to server.jar"
  fi
fi

# If EULA missing, accept
if [ ! -f eula.txt ]; then
  echo "eula=true" > eula.txt
fi

# Remove stale session.lock if present (from prior crash)
cleanup_stale_session_lock() {
  local level_name="world"
  if [ -f server.properties ]; then
    # Extract level-name; keep everything after first '=' and trim CR
    local ln
    ln=$(grep -E '^level-name=' server.properties | sed -E 's/^level-name=//;s/\r$//')
    if [ -n "$ln" ]; then
      level_name="$ln"
    fi
  fi
  local wdir="./${level_name}"
  # Fallback if directory doesn't exist
  if [ ! -d "$wdir" ] && [ -d ./world ]; then
    wdir=./world
  fi
  if [ -f "$wdir/session.lock" ]; then
    # Log size for diagnostics
    local sz
    sz=$(stat -c%s "$wdir/session.lock" 2>/dev/null || stat -f%z "$wdir/session.lock" 2>/dev/null || echo "?")
    echo "DEBUG: Removing stale session.lock at $wdir/session.lock (size: $sz)"
    rm -f "$wdir/session.lock" || true
  fi
}

cleanup_stale_session_lock || true

# Preferred jars/patterns
echo "DEBUG: Searching for server jars in $(pwd)"
echo "DEBUG: Current directory contents: $(ls -la)"
start_jar=""

# Prefer explicit SERVER_JAR if set and exists
if [ -n "$SERVER_JAR" ]; then
  if [ -f "$SERVER_JAR" ]; then
    start_jar="$SERVER_JAR"
    echo "DEBUG: Using SERVER_JAR specified: $start_jar"
  elif [ -f "./$SERVER_JAR" ]; then
    start_jar="./$SERVER_JAR"
    echo "DEBUG: Using SERVER_JAR specified (relative): $start_jar"
  else
    echo "WARNING: SERVER_JAR '$SERVER_JAR' not found; falling back to autodetection"
  fi
fi

# Check for specific JAR patterns in order of preference, tailored by server type
if [ -z "$start_jar" ]; then
  if [ "$SERVER_TYPE" = "forge" ] || [ "$SERVER_TYPE" = "neoforge" ] || [ "$SERVER_TYPE" = "mohist" ] || [ "$SERVER_TYPE" = "magma" ] || [ "$SERVER_TYPE" = "catserver" ] || [ "$SERVER_TYPE" = "spongeforge" ]; then
    patterns="server.jar neoforge-*-universal.jar *forge-*-universal.jar forge-*-server.jar *mohist*.jar *magma*.jar *catserver*.jar *spongeforge*.jar *server*.jar"
  elif [ "$SERVER_TYPE" = "fabric" ] || [ "$SERVER_TYPE" = "quilt" ] || [ "$SERVER_TYPE" = "banner" ]; then
    patterns="server.jar *fabric*.jar *quilt*.jar *banner*.jar *server*.jar"
  else
    patterns="server.jar *paper*.jar *purpur*.jar *server*.jar"
  fi
  for pattern in $patterns; do
    echo "DEBUG: Checking pattern: $pattern"
    found=$(ls $pattern 2>/dev/null | head -n 1 || true)
    if [ -n "$found" ]; then
      start_jar="$found"
      echo "DEBUG: Found jar: $start_jar"
      break
    fi
  done
fi

# Removed cross-directory fallback search to avoid picking jars from other servers

# For Forge/NeoForge servers: if a jar exists, try running installer first headlessly
# For Forge/NeoForge: prefer run.sh immediately; do not try to 'install' non-installer jars

# -------- Server Start with Crash Recovery --------
# Wrap server start in a function for crash recovery
start_server_with_recovery() {
  local cmd_type="$1"
  shift
  local cmd_args=("$@")
  
  while true; do
    echo "INFO: Starting server (recovery attempt: $CRASH_RECOVERY_ATTEMPT)..."
    
    # Create console FIFO
    mkfifo -m 600 console.in 2>/dev/null || true
    
    # Start the server process (not exec, so we can catch exit)
    set +e
    case "$cmd_type" in
      "runsh")
        tail -f -n +1 console.in | bash ./run.sh
        ;;
      "java")
        tail -f -n +1 console.in | "$JAVA_BIN" $ALL_JAVA_ARGS "${cmd_args[@]}"
        ;;
    esac
    local exit_code=$?
    set -e
    
    echo "INFO: Server exited with code: $exit_code"
    
    # Clean exit (0) or stop command (143 = SIGTERM)
    if [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 143 ]; then
      echo "INFO: Server stopped gracefully."
      exit 0
    fi
    
    # Crash - attempt recovery
    if [ "$AUTO_CRASH_RECOVERY" = "1" ]; then
      handle_crash_recovery "$exit_code"
      if [ $? -eq 0 ]; then
        # handle_crash_recovery returned 0, retry server start
        echo "INFO: Retrying server start after recovery..."
        rm -f console.in 2>/dev/null || true
        continue
      fi
    fi
    
    # Recovery failed or disabled
    echo "ERROR: Server crashed and recovery failed or disabled."
    exit "$exit_code"
  done
}

if { [ "$SERVER_TYPE" = "forge" ] || [ "$SERVER_TYPE" = "neoforge" ]; }; then
  if [ -f run.sh ]; then
    echo "Starting Forge/NeoForge via run.sh"
    chmod +x run.sh || true
    TMP_JAVA_DIR="/tmp/java-override"
    mkdir -p "$TMP_JAVA_DIR"
    ln -sf "$JAVA_BIN" "$TMP_JAVA_DIR/java"
    export PATH="$TMP_JAVA_DIR:$PATH"
    echo "DEBUG: Overriding 'java' for run.sh with: $JAVA_BIN"
    start_server_with_recovery "runsh"
  fi
fi

# Handle Fabric servers specially
if { [ "$SERVER_TYPE" = "fabric" ] || [ "$SERVER_TYPE" = "quilt" ]; } && [ -n "$start_jar" ]; then
  echo "Handling ${SERVER_TYPE^} server"
  
  # Validate JAR file before starting

  if [ ! -f "$start_jar" ]; then
    echo "ERROR: JAR file $start_jar not found!" >&2
    exit 1
  fi
  
  jar_size=$(stat -c%s "$start_jar" 2>/dev/null || stat -f%z "$start_jar" 2>/dev/null || echo "0")
  echo "DEBUG: Fabric JAR file size: $jar_size bytes"
  
  # Check if JAR is too small (likely corrupted)
  min_size=5000  # 5KB minimum for Fabric launcher JARs
  if [ "$jar_size" -lt $min_size ]; then
    echo "ERROR: Fabric JAR file $start_jar is too small ($jar_size bytes), likely corrupted!" >&2
    echo "ERROR: Expected at least ${min_size} bytes for a valid Fabric launcher JAR" >&2
    exit 1
  fi
  
  # If the chosen jar filename contains 'fabric' or 'quilt', assume it's the launcher and use 'server' argument; otherwise, run normally (nogui)
  if echo "$start_jar" | grep -Eqi "fabric|quilt"; then
    echo "Starting ${SERVER_TYPE^} via launcher: $start_jar (with 'server' argument)"
    start_server_with_recovery "java" -jar "$start_jar" server
  else
    echo "Starting ${SERVER_TYPE^} using standard server jar: $start_jar (nogui)"
    start_server_with_recovery "java" -jar "$start_jar" nogui
  fi
fi

# If run script exists, prefer it (execute script directly)
if [ -f run.sh ]; then
  echo "Starting via run.sh"
  chmod +x run.sh || true
  TMP_JAVA_DIR="/tmp/java-override"
  mkdir -p "$TMP_JAVA_DIR"
  ln -sf "$JAVA_BIN" "$TMP_JAVA_DIR/java"
  export PATH="$TMP_JAVA_DIR:$PATH"
  echo "DEBUG: Overriding 'java' for run.sh with: $JAVA_BIN"
  start_server_with_recovery "runsh"
fi

# For other server types
if [ -n "$start_jar" ]; then
  echo "Starting server in $(pwd): $start_jar"
  
  # Validate JAR file before starting
  if [ ! -f "$start_jar" ]; then
    echo "ERROR: JAR file $start_jar not found!" >&2
    exit 1
  fi
  
  jar_size=$(stat -c%s "$start_jar" 2>/dev/null || stat -f%z "$start_jar" 2>/dev/null || echo "0")
  echo "DEBUG: JAR file size: $jar_size bytes"
  
  # Check if JAR is too small (likely corrupted)
  min_size=50000  # 50KB minimum for general servers
  
  if [ "$jar_size" -lt $min_size ]; then
    echo "ERROR: JAR file $start_jar is too small ($jar_size bytes), likely corrupted!" >&2
    echo "ERROR: Expected at least ${min_size} bytes for a valid Minecraft server JAR" >&2
    exit 1
  fi
  
  # Test JAR file integrity
  if ! "$JAVA_BIN" $ALL_JAVA_ARGS -jar "$start_jar" --help >/dev/null 2>&1; then
    echo "WARNING: JAR file validation failed, but attempting to start anyway..."
  fi
  
  start_server_with_recovery "java" -jar "$start_jar" nogui
fi

echo "No server jar or run.sh found in $(pwd). Contents:" >&2
ls -la >&2
[ -d /data/servers ] && echo "Index of /data/servers:" >&2 && ls -la /data/servers >&2
[ -n "$SERVER_DIR_NAME" ] && [ -d "/data/servers/$SERVER_DIR_NAME" ] && echo "Index of /data/servers/$SERVER_DIR_NAME:" >&2 && ls -la "/data/servers/$SERVER_DIR_NAME" >&2
exit 1