"""Lynx Multi-Core Engine (LMCE) - Universal Java Agent Manager.

Manages compilation, packaging, verification, and deployment of mc-multicore-agent.jar.
Provides deterministic packaging via Python's standard zipfile module, eliminating external
jar command dependencies.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional
import zipfile

logger = logging.getLogger(__name__)

AGENT_JAR_NAME = "mc-multicore-agent.jar"
AGENT_PREMAIN_CLASS = "com.lynx.multicore.agent.MultiCoreAgent"
AGENT_CLASS = "com.lynx.multicore.agent.MultiCoreAgent"

AGENT_DIR = Path(__file__).resolve().parent / "agent"
AGENT_SRC_DIR = AGENT_DIR / "src"
BUNDLED_AGENT_JAR = AGENT_DIR / AGENT_JAR_NAME
MANIFEST_FILE = AGENT_DIR / "META-INF" / "MANIFEST.MF"

DEFAULT_MANIFEST = (
    "Manifest-Version: 1.0\r\n"
    f"Premain-Class: {AGENT_PREMAIN_CLASS}\r\n"
    f"Agent-Class: {AGENT_CLASS}\r\n"
    "Can-Redefine-Classes: true\r\n"
    "Can-Retransform-Classes: true\r\n"
    "Created-By: Minecraft-Controller LMCE\r\n"
    "\r\n"
)


def validate_agent_jar(jar_path: Path | str) -> bool:
    """Validate that a JAR file exists, is a valid zip, and contains required agent manifest headers."""
    path = Path(jar_path)
    if not path.is_file() or path.stat().st_size == 0:
        return False

    try:
        with zipfile.ZipFile(path, "r") as zf:
            namelist = zf.namelist()
            # Must contain manifest
            manifest_names = [n for n in namelist if n.upper() == "META-INF/MANIFEST.MF"]
            if not manifest_names:
                logger.debug("validate_agent_jar: META-INF/MANIFEST.MF missing in %s", path)
                return False

            manifest_content = zf.read(manifest_names[0]).decode("utf-8", errors="replace")
            if "Premain-Class:" not in manifest_content or AGENT_PREMAIN_CLASS not in manifest_content:
                logger.debug("validate_agent_jar: Premain-Class header missing/invalid in %s", path)
                return False

            return True
    except (zipfile.BadZipFile, OSError, Exception) as e:
        logger.debug("validate_agent_jar error reading %s: %s", path, e)
        return False


def compile_java_sources(src_root: Optional[Path] = None) -> bool:
    """Compile Java agent sources using system javac with --release 8 target."""
    root = src_root or AGENT_SRC_DIR
    if not root.is_dir():
        return False

    java_files = list(root.rglob("*.java"))
    if not java_files:
        return False

    try:
        cmd = [
            "javac",
            "--release",
            "8",
            "-Xlint:-options",
            "-encoding",
            "UTF-8",
        ] + [str(p) for p in java_files]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            logger.info("Successfully compiled %d Java agent sources to Java 8 bytecode.", len(java_files))
            return True
        else:
            logger.warning("javac compilation failed: %s %s", result.stdout, result.stderr)
            return False
    except FileNotFoundError:
        logger.info("javac not found on system PATH; proceeding with pre-compiled classes/fallback.")
        return False
    except Exception as e:
        logger.warning("javac execution encountered error: %s", e)
        return False


def build_agent_jar(output_jar_path: Path | str, source_dir: Optional[Path | str] = None) -> Path:
    """Package Java agent bytecode and manifest into a valid, deterministic JAR archive."""
    out_path = Path(output_jar_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    src_root = Path(source_dir) if source_dir else AGENT_SRC_DIR

    # Attempt compilation if javac is available
    compile_java_sources(src_root)

    # Locate compiled class files
    class_files = list(src_root.rglob("*.class"))

    manifest_bytes = DEFAULT_MANIFEST.encode("utf-8")
    if MANIFEST_FILE.is_file():
        try:
            content = MANIFEST_FILE.read_text(encoding="utf-8").strip() + "\r\n\r\n"
            manifest_bytes = content.encode("utf-8")
        except Exception as e:
            logger.debug("Error reading custom MANIFEST.MF: %s", e)

    temp_jar = out_path.parent / f"{out_path.name}.tmp"
    with zipfile.ZipFile(temp_jar, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write MANIFEST.MF
        manifest_info = zipfile.ZipInfo("META-INF/MANIFEST.MF")
        manifest_info.external_attr = 0o644 << 16
        zf.writestr(manifest_info, manifest_bytes)

        # Write compiled .class files
        for cf in class_files:
            rel_path = cf.relative_to(src_root).as_posix()
            zinfo = zipfile.ZipInfo(rel_path)
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, cf.read_bytes())

    # Atomic rename
    temp_jar.replace(out_path)
    logger.info("Built agent JAR at %s with %d classes.", out_path, len(class_files))
    return out_path


def ensure_agent_binary(target_dir: Path | str) -> Path:
    """Ensure mc-multicore-agent.jar is present and valid in the target directory.

    Reconstructs or copies if missing or corrupted, verifying zip and manifest integrity.
    """
    dest_dir = Path(target_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    agent_dest = dest_dir / AGENT_JAR_NAME

    # 1. If destination already has a valid JAR, return it
    if agent_dest.is_file() and validate_agent_jar(agent_dest):
        return agent_dest

    # 2. Check bundled JAR in backend/multicore/agent/
    if BUNDLED_AGENT_JAR.is_file() and validate_agent_jar(BUNDLED_AGENT_JAR):
        if agent_dest != BUNDLED_AGENT_JAR:
            shutil.copy2(BUNDLED_AGENT_JAR, agent_dest)
        return agent_dest

    # 3. Build bundled JAR first if missing
    try:
        build_agent_jar(BUNDLED_AGENT_JAR)
    except Exception as e:
        logger.warning("Failed building bundled agent JAR: %s", e)

    if BUNDLED_AGENT_JAR.is_file() and validate_agent_jar(BUNDLED_AGENT_JAR):
        if agent_dest != BUNDLED_AGENT_JAR:
            shutil.copy2(BUNDLED_AGENT_JAR, agent_dest)
        return agent_dest

    # 4. Fallback: Build directly to destination
    build_agent_jar(agent_dest)

    if not validate_agent_jar(agent_dest):
        raise RuntimeError(f"Failed to generate valid Universal Agent JAR at {agent_dest}")

    return agent_dest
