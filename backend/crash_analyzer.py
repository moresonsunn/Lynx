#!/usr/bin/env python3
"""
Crash Log Analyzer for Minecraft Server Manager
Automatically detects problematic mods from crash reports and server logs.
Integrates with the auto-fix system to disable failing mods.
"""

import os
import re
import json
import shutil
import zipfile
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from datetime import datetime

logger = logging.getLogger(__name__)


# Known client-only mod indicators - extended list
CLIENT_ONLY_INDICATORS = {
    # Rendering/Graphics mods
    "iris", "oculus", "sodium", "embeddium", "rubidium", "magnesium",
    "optifine", "optifabric", "starlight-fabric", "phosphor", "lambdynamiclights",
    "canvas-renderer", "immediatelyfast", "entityculling", "dynamicfps", "dynamic-fps",
    "dynamic_fps", "fpsreducer", "fps_reducer", "enhancedvisuals", "better-clouds",
    "falling-leaves", "visuality", "cull-less-leaves", "particlerain", "drippyloadingscreen",
    
    # UI/HUD mods
    "xaero", "xaeros", "journeymap", "voxelmap", "worldmap", "minimap",
    "betterf3", "better-f3", "appleskin", "itemphysic", "jade", "hwyla", "waila",
    "wthit", "emi", "rei", "jei", "roughlyenoughitems", "justmap", "torohealth",
    "blur", "tooltip", "controlling", "mod-menu", "modmenu", "configured", "catalogue",
    "smoothboot", "smooth-boot", "loading", "loadingscreen", "mainmenu", "panoramafix",
    "betterthirdperson", "freelook", "cameraoverhaul", "citresewn", "cit-resewn",
    
    # Audio/Sound mods
    "presence-footsteps", "presencefootsteps", "soundphysics", "ambientsounds",
    "dynamic-music", "music", "extrasounds", "dripsounds", "auditory",
    
    # Shaders/Resource packs
    "shader", "complementary", "sildurs", "continuum", "bsl", "seus", "kappa",
    
    # Recording/Streaming
    "replaymod", "replay-mod", "replay_mod", "worldedit-cui", "axiom",
    
    # Cosmetics
    "capes", "skinlayers3d", "skin-layers", "ears", "figura", "customskinloader",
    "more-player-models", "playeranimator", "emotes", "emotecraft",
    
    # Client utilities
    "litematica", "minihud", "tweakeroo", "malilib", "itemscroller", "tweakermore",
    "freecam", "flycam", "keystrokes", "betterpvp", "5zig", "labymod",
    "schematica", "worldeditcui", "wecui", "light-overlay", "lightoverlay",
    
    # Framework/Library (client-specific)
    "fabric-renderer-api", "fabric-rendering", "cloth-config-client",
}

# Patterns that indicate client-only in crash logs
CLIENT_CRASH_PATTERNS = [
    # Direct client-only indicators
    r"Caused by:.*Client environment required",
    r"Client environment is required but.*server",
    r"Environment type CLIENT is required",
    r"onlyIn.*CLIENT",
    r"@OnlyIn\(.*CLIENT\)",
    r"Dist\.CLIENT",
    
    # Rendering-related crashes
    r"No OpenGL context",
    r"GLFW error",
    r"Display.*not created",
    r"Framebuffer.*not complete",
    r"Cannot get.*GL context",
    r"org\.lwjgl\.opengl",
    r"com\.mojang\.blaze3d",
    r"net\.minecraft\.client",
    r"RenderSystem\.assert",
    r"GlStateManager",
    r"BufferBuilder",
    r"TessellatorImpl",
    r"WorldRenderer",
    
    # Input-related crashes
    r"GLFW.*keyboard",
    r"InputConstants",
    r"MouseHandler",
    r"KeyMapping",
    
    # Screen/GUI crashes
    r"Screen.*initialization",
    r"GuiScreen",
    r"ContainerScreen",
    r"InventoryScreen",
]

# Patterns to extract mod names from crash logs
MOD_EXTRACTION_PATTERNS = [
    r"Caused by:.*at ([\w.]+)\.",
    r"Mod ID: '?([\w-]+)'?",
    r"Mod File: ([\w.-]+\.jar)",
    r"at ([\w.]+)\$",
    r"\[([\w-]+)\].*Exception",
    r"-- MOD ([\w-]+) --",
    r"Failure message: ([\w-]+)",
    r"The following mods.*?:\s*([\w, -]+)",
    r"Mixin injection failed:.*?([\w.-]+)",
    r"from mod ([\w-]+)",
    r"caused by mod ([\w-]+)",
    r"([\w-]+)\.mixins\.json",
]

# Common crash signatures and their associated mods
CRASH_SIGNATURES = {
    "iris": ["iris", "irisshaders"],
    "sodium": ["sodium", "sodiumextra", "reeses_sodium_options"],
    "create": ["create", "flywheel"],
    "mekanism": ["mekanism", "mekanismgenerators", "mekanismadditions"],
    "rubidium": ["rubidium", "oculus"],
    "xaero": ["xaero", "xaerominimap", "xaerosworldmap"],
    "journeymap": ["journeymap"],
    "optifine": ["optifine", "optifabric"],
    "replaymod": ["replaymod", "replay"],
}


class CrashAnalyzer:
    """Analyzes Minecraft crash reports and logs to identify problematic mods."""

    def __init__(self, servers_root: Optional[Path] = None):
        self.servers_root = servers_root or Path("/data/servers")
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}
        
    def analyze_crash_report(self, crash_content: str) -> Dict[str, Any]:
        """
        Analyze a crash report and identify problematic mods.
        
        Returns:
            Dict with keys:
                - client_only_detected: bool
                - problematic_mods: List[str] - mod names/jars to disable
                - crash_type: str - category of crash
                - recommendation: str - suggested action
        """
        result = {
            "client_only_detected": False,
            "problematic_mods": [],
            "crash_type": "unknown",
            "recommendation": "",
            "confidence": 0.0,
            "details": [],
        }
        
        content_lower = crash_content.lower()
        
        # Check for client-only crash patterns
        for pattern in CLIENT_CRASH_PATTERNS:
            if re.search(pattern, crash_content, re.IGNORECASE | re.MULTILINE):
                result["client_only_detected"] = True
                result["crash_type"] = "client_only_mod"
                result["confidence"] = 0.9
                result["details"].append(f"Matched client-crash pattern: {pattern}")
                break
        
        # Extract mod names from crash
        found_mods: Set[str] = set()
        for pattern in MOD_EXTRACTION_PATTERNS:
            matches = re.findall(pattern, crash_content, re.IGNORECASE)
            for match in matches:
                mod_name = match.lower().strip()
                # Filter out common Java packages
                if not any(pkg in mod_name for pkg in ["java.", "sun.", "org.apache", "io.netty"]):
                    found_mods.add(mod_name)
        
        # Check found mods against client-only indicators
        for mod in found_mods:
            mod_clean = re.sub(r'[^a-z0-9]', '', mod)
            for indicator in CLIENT_ONLY_INDICATORS:
                indicator_clean = re.sub(r'[^a-z0-9]', '', indicator)
                if indicator_clean in mod_clean or mod_clean in indicator_clean:
                    result["problematic_mods"].append(mod)
                    result["client_only_detected"] = True
                    result["details"].append(f"Found client-only mod: {mod}")
                    break
        
        # Check for crash signatures
        for signature, related_mods in CRASH_SIGNATURES.items():
            if signature in content_lower:
                for mod in related_mods:
                    if mod not in result["problematic_mods"]:
                        result["problematic_mods"].append(mod)
                result["details"].append(f"Matched crash signature: {signature}")
        
        # Determine recommendation
        if result["client_only_detected"]:
            result["recommendation"] = "disable_client_mods"
            if result["confidence"] < 0.9:
                result["confidence"] = 0.7
        elif result["problematic_mods"]:
            result["recommendation"] = "investigate_mods"
            result["crash_type"] = "mod_conflict"
            result["confidence"] = 0.6
        else:
            result["recommendation"] = "manual_review"
            result["confidence"] = 0.3
        
        return result

    def find_crash_reports(self, server_dir: Path) -> List[Path]:
        """Find all crash reports in a server directory."""
        crash_files = []
        
        # Check crash-reports folder
        crash_dir = server_dir / "crash-reports"
        if crash_dir.exists():
            crash_files.extend(crash_dir.glob("crash-*.txt"))
        
        # Check logs folder for latest.log and debug.log
        logs_dir = server_dir / "logs"
        if logs_dir.exists():
            for log_file in ["latest.log", "debug.log"]:
                log_path = logs_dir / log_file
                if log_path.exists():
                    crash_files.append(log_path)
        
        # Sort by modification time (newest first)
        crash_files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        
        return crash_files

    def analyze_server(self, server_name: str) -> Dict[str, Any]:
        """
        Analyze a server for crash-related issues.
        
        Returns analysis results including detected problems and recommended fixes.
        """
        server_dir = self.servers_root / server_name
        if not server_dir.exists():
            return {"error": f"Server directory not found: {server_name}"}
        
        result = {
            "server_name": server_name,
            "analyzed_at": datetime.now().isoformat(),
            "crash_reports_found": 0,
            "client_only_issues": [],
            "mods_to_disable": [],
            "auto_fixed": False,
            "details": [],
        }
        
        crash_files = self.find_crash_reports(server_dir)
        result["crash_reports_found"] = len(crash_files)
        
        if not crash_files:
            result["details"].append("No crash reports found")
            return result
        
        # Analyze the most recent crash report
        latest_crash = crash_files[0]
        try:
            content = latest_crash.read_text(encoding="utf-8", errors="ignore")
            analysis = self.analyze_crash_report(content)
            
            result["client_only_issues"] = analysis.get("details", [])
            result["mods_to_disable"] = analysis.get("problematic_mods", [])
            
            if analysis["client_only_detected"] and analysis["confidence"] > 0.6:
                result["details"].append(
                    f"Detected client-only crash (confidence: {analysis['confidence']:.0%})"
                )
                result["recommendation"] = analysis["recommendation"]
            
        except Exception as e:
            result["error"] = f"Failed to analyze crash report: {e}"
        
        self.analysis_cache[server_name] = result
        return result

    def auto_fix_server(self, server_name: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Automatically fix detected issues for a server.
        
        Args:
            server_name: Name of the server to fix
            dry_run: If True, only report what would be done without making changes
            
        Returns:
            Dict with fix results
        """
        analysis = self.analyze_server(server_name)
        if analysis.get("error"):
            return analysis
        
        server_dir = self.servers_root / server_name
        mods_dir = server_dir / "mods"
        disabled_dir = server_dir / "mods-disabled-crash"
        
        result = {
            "server_name": server_name,
            "fixed_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "mods_disabled": [],
            "actions_taken": [],
        }
        
        if not mods_dir.exists():
            result["actions_taken"].append("No mods directory found")
            return result
        
        mods_to_disable = set(analysis.get("mods_to_disable", []))
        
        if not mods_to_disable:
            # Fallback: scan all mods for client-only indicators
            for jar in mods_dir.glob("*.jar"):
                jar_lower = jar.name.lower()
                for indicator in CLIENT_ONLY_INDICATORS:
                    if indicator in jar_lower:
                        mods_to_disable.add(jar.name)
                        break
        
        if not mods_to_disable:
            result["actions_taken"].append("No problematic mods identified")
            return result
        
        if not dry_run:
            disabled_dir.mkdir(parents=True, exist_ok=True)
        
        # Find and disable matching mods
        for jar in mods_dir.glob("*.jar"):
            jar_lower = jar.name.lower()
            should_disable = False
            
            # Check against analysis results
            for mod_pattern in mods_to_disable:
                pattern_clean = re.sub(r'[^a-z0-9]', '', mod_pattern.lower())
                jar_clean = re.sub(r'[^a-z0-9]', '', jar_lower)
                if pattern_clean in jar_clean or jar_clean.startswith(pattern_clean):
                    should_disable = True
                    break
            
            # Also check jar metadata for client-only environment
            if not should_disable:
                should_disable = self._is_client_only_jar(jar)
            
            if should_disable:
                if dry_run:
                    result["mods_disabled"].append(f"[DRY RUN] Would disable: {jar.name}")
                else:
                    try:
                        shutil.move(str(jar), str(disabled_dir / jar.name))
                        result["mods_disabled"].append(jar.name)
                        result["actions_taken"].append(f"Moved {jar.name} to mods-disabled-crash/")
                        logger.info(f"Auto-disabled mod: {jar.name}")
                    except Exception as e:
                        result["actions_taken"].append(f"Failed to disable {jar.name}: {e}")
        
        if result["mods_disabled"]:
            result["actions_taken"].append(
                f"Disabled {len(result['mods_disabled'])} problematic mods"
            )
        
        return result

    def _is_client_only_jar(self, jar_path: Path) -> bool:
        """Check if a JAR file is client-only based on its metadata."""
        try:
            with zipfile.ZipFile(jar_path, 'r') as zf:
                namelist = zf.namelist()
                
                # Check Fabric/Quilt metadata
                for meta_file in ['fabric.mod.json', 'quilt.mod.json']:
                    if meta_file in namelist:
                        try:
                            data = json.loads(zf.read(meta_file).decode('utf-8', errors='ignore'))
                            env = str(data.get('environment', '')).lower().strip()
                            if env == 'client':
                                return True
                        except Exception:
                            pass
                
                # Check Forge metadata
                if 'META-INF/mods.toml' in namelist:
                    try:
                        content = zf.read('META-INF/mods.toml').decode('utf-8', errors='ignore').lower()
                        if 'clientsideonly=true' in content or 'client_only=true' in content:
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        
        return False

    def get_cached_analysis(self, server_name: str) -> Optional[Dict[str, Any]]:
        """Get cached analysis for a server if available."""
        return self.analysis_cache.get(server_name)

    def clear_cache(self, server_name: Optional[str] = None):
        """Clear analysis cache for a server or all servers."""
        if server_name:
            self.analysis_cache.pop(server_name, None)
        else:
            self.analysis_cache.clear()


# Global instance
crash_analyzer = CrashAnalyzer()


def analyze_server_crashes(server_name: str) -> Dict[str, Any]:
    """Analyze a server for crash-related issues."""
    return crash_analyzer.analyze_server(server_name)


def auto_fix_server_crashes(server_name: str, dry_run: bool = False) -> Dict[str, Any]:
    """Automatically fix detected crash issues for a server."""
    result = crash_analyzer.auto_fix_server(server_name, dry_run=dry_run)
    
    # Send crash notification if issues were detected
    if not dry_run and result.get("issues_found"):
        try:
            from settings_routes import send_notification
            issues_count = len(result.get("issues_found", []))
            mods_disabled = len(result.get("mods_disabled", []))
            send_notification(
                "server_crash",
                f"⚠️ Server Crash Detected: {server_name}",
                f"Detected **{issues_count}** issue(s) on server **{server_name}**. "
                + (f"Auto-disabled **{mods_disabled}** problematic mod(s)." if mods_disabled else "Manual intervention may be required."),
                color=15844367  # Orange/amber
            )
        except Exception:
            pass
    
    return result


def analyze_crash_log(content: str) -> Dict[str, Any]:
    """Analyze crash log content directly."""
    return crash_analyzer.analyze_crash_report(content)
