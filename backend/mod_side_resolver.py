"""
ModSideResolver – Intelligentes, mehrstufiges Mod-Side-Erkennungssystem für Minecraft-Modpacks.

Unterstützt NeoForge, Forge, Fabric und Quilt sowie Metadaten von Modrinth, CurseForge und FTB.
Kombiniert:
  A. Offizielle Mod-Metadaten (Modrinth API, CurseForge API, FTB-Metadaten, Modpack-Manifeste)
  B. JAR-Metadaten (META-INF/neoforge.mods.toml, META-INF/mods.toml, fabric.mod.json,
     quilt.mod.json, mcmod.info, Mixin-Konfigurationen, Entrypoints, Jar-in-Jar, Ressourcen/Datapacks)
  C. Java-Bytecode-Analyse (.class Constant-Pool + JVM §4.7.16 Annotations, DistExecutor,
     Registries, Networking, Client- vs. Server-Entrypoints)
  D. Vollständige Abhängigkeitsgraphen-Analyse (Required, Optional, Embedded, Integration/Addon-Mods)
  E. Konflikterkennung, Fehler-/Crashlog-Analyse & Serverpaket-Validierung
  F. Persistentes SHA256-basiertes Caching (ModSideCache) mit Versions- & Loader-Kontext

Sicherheitsregel:
  UNKNOWN wird NIEMALS als CLIENT_ONLY interpretiert. Im Zweifelsfall verbleibt die Mod auf dem Server.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

from compat.extract.bytecode_scanner import scan_jar_for_bytecode_side

logger = logging.getLogger(__name__)

RESOLVER_SCHEMA_VERSION = "2.1.0"


class ModSideCategory(str, Enum):
    """Klassifizierungskategorien des ModSideResolvers."""

    CLIENT_ONLY = "CLIENT_ONLY"
    SERVER_ONLY = "SERVER_ONLY"
    BOTH_SIDES_REQUIRED = "BOTH_SIDES_REQUIRED"
    OPTIONAL_CLIENT = "OPTIONAL_CLIENT"
    OPTIONAL_SERVER = "OPTIONAL_SERVER"
    UNKNOWN = "UNKNOWN"

    @property
    def keep_on_server(self) -> bool:
        """Nur eindeutige CLIENT_ONLY-Mods dürfen vom Dedicated Server ausgeschlossen werden."""
        return self != ModSideCategory.CLIENT_ONLY


class ConfidenceLevel(str, Enum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CONFLICTING = "CONFLICTING"


@dataclass
class DetectionEvidence:
    source: str  # z.B. "official_metadata:modrinth", "jar_metadata:neoforge.mods.toml", "bytecode", "dependency_graph"
    side_hint: ModSideCategory
    confidence: float  # 0.0 - 1.0
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "side_hint": self.side_hint.value,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class ModDependencyRef:
    mod_id: str
    dep_type: str = "required"  # "required", "optional", "embedded", "integration", "loader"
    side: str = "BOTH"  # "BOTH", "CLIENT", "SERVER"
    version_range: str = "*"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mod_id": self.mod_id,
            "dep_type": self.dep_type,
            "side": self.side,
            "version_range": self.version_range,
        }


@dataclass
class ModAnalysisResult:
    file_path: str
    file_name: str
    sha256: str
    mod_id: str
    mod_name: str
    mod_version: str
    minecraft_version: str
    modloader: str
    side: ModSideCategory
    confidence: float
    confidence_level: ConfidenceLevel
    keep_on_server: bool
    primary_reason: str
    detection_sources: List[str] = field(default_factory=list)
    evidences: List[DetectionEvidence] = field(default_factory=list)
    dependencies: List[ModDependencyRef] = field(default_factory=list)
    provided_mods: List[str] = field(default_factory=list)
    required_by_server_mods: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    from_cache: bool = False
    jar_details: Dict[str, Any] = field(default_factory=dict)
    bytecode_details: Dict[str, Any] = field(default_factory=dict)
    official_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_client_only(self) -> bool:
        return self.side == ModSideCategory.CLIENT_ONLY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "filename": self.file_name,
            "sha256": self.sha256,
            "mod_id": self.mod_id,
            "mod_name": self.mod_name,
            "name": self.mod_name,
            "mod_version": self.mod_version,
            "version": self.mod_version,
            "minecraft_version": self.minecraft_version,
            "modloader": self.modloader,
            "loader": self.modloader,
            "side": self.side.value,
            "classification": self.side.value,
            "is_client_only": self.side == ModSideCategory.CLIENT_ONLY,
            "confidence": round(self.confidence, 3),
            "confidence_level": self.confidence_level.value,
            "keep_on_server": self.keep_on_server,
            "primary_reason": self.primary_reason,
            "reason": self.primary_reason,
            "detection_method": ", ".join(self.detection_sources) if self.detection_sources else "mod_side_resolver",
            "detection_sources": self.detection_sources,
            "evidences": [e.to_dict() for e in self.evidences],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "provided_mods": self.provided_mods,
            "required_by_server_mods": self.required_by_server_mods,
            "conflicts": self.conflicts,
            "from_cache": self.from_cache,
            "jar_details": self.jar_details,
            "bytecode_details": self.bytecode_details,
            "official_metadata": self.official_metadata,
        }


# ---------------------------------------------------------------------------
# Persistentes Cache-System (Abschnitt 8)
# ---------------------------------------------------------------------------


class ModSideCache:
    """
    Dauerhafter SQLite-Cache für Mod-Side-Analysen.
    Speichert SHA256, Mod-ID, Mod-Version, Minecraft-Version, Modloader,
    Side-Klassifizierung, Erkennungsquellen, Confidence, Abhängigkeiten und Analyseergebnis.

    Ein Cache-Eintrag wird nur wiederverwendet, wenn:
      - der SHA256-Hash der JAR exakt übereinstimmt, UND
      - Minecraft-Version sowie Modloader kompatibel sind, UND
      - die Resolver-Schema-Version aktuell ist.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            base_dir = Path(os.environ.get("DATA_DIR", "/data/servers"))
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
                test_file = base_dir / ".write_test"
                test_file.touch()
                test_file.unlink(missing_ok=True)
            except Exception:
                base_dir = Path(__file__).resolve().parent / "data"
                base_dir.mkdir(parents=True, exist_ok=True)
            db_path = base_dir / "mod_side_cache.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mod_side_cache (
                    sha256 TEXT NOT NULL,
                    minecraft_version TEXT NOT NULL,
                    modloader TEXT NOT NULL,
                    mod_id TEXT NOT NULL,
                    mod_version TEXT NOT NULL,
                    side_classification TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    detection_sources TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    analysis_result_json TEXT NOT NULL,
                    resolver_version TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (sha256, minecraft_version, modloader)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mod_side_sha256 ON mod_side_cache(sha256)"
            )

    @staticmethod
    def _norm_ctx(value: Optional[str]) -> str:
        return (value or "unknown").strip().lower()

    def get(
        self,
        sha256: str,
        minecraft_version: Optional[str] = None,
        modloader: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        mc_key = self._norm_ctx(minecraft_version)
        loader_key = self._norm_ctx(modloader)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT mod_id, mod_version, side_classification, confidence,
                           detection_sources, dependencies_json, analysis_result_json, resolver_version
                    FROM mod_side_cache
                    WHERE sha256 = ? AND minecraft_version = ? AND modloader = ?
                    """,
                    (sha256, mc_key, loader_key),
                ).fetchone()
                if not row:
                    return None
                resolver_ver = row[7]
                if resolver_ver != RESOLVER_SCHEMA_VERSION:
                    return None
                return json.loads(row[6])
        except Exception as exc:
            logger.debug(f"ModSideCache read error for {sha256}: {exc}")
            return None

    def put(self, result: ModAnalysisResult) -> None:
        mc_key = self._norm_ctx(result.minecraft_version)
        loader_key = self._norm_ctx(result.modloader)
        payload = result.to_dict()
        payload["from_cache"] = False
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO mod_side_cache (
                        sha256, minecraft_version, modloader, mod_id, mod_version,
                        side_classification, confidence, detection_sources,
                        dependencies_json, analysis_result_json, resolver_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.sha256,
                        mc_key,
                        loader_key,
                        result.mod_id,
                        result.mod_version,
                        result.side.value,
                        result.confidence,
                        json.dumps(result.detection_sources),
                        json.dumps([d.to_dict() for d in result.dependencies]),
                        json.dumps(payload),
                        RESOLVER_SCHEMA_VERSION,
                        time.time(),
                    ),
                )
        except Exception as exc:
            logger.debug(f"ModSideCache write error for {result.sha256}: {exc}")

    def clear(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM mod_side_cache")
        except Exception as exc:
            logger.debug(f"ModSideCache clear error: {exc}")


# ---------------------------------------------------------------------------
# Hilfsfunktionen für TOML / JSON / JAR-Metadaten (Abschnitt 4B)
# ---------------------------------------------------------------------------

_SYSTEM_DEP_IDS = {
    "minecraft",
    "forge",
    "neoforge",
    "fml",
    "fabricloader",
    "fabric-loader",
    "fabric",
    "quilt_loader",
    "quilt-loader",
    "java",
    "mixinextras",
}


def compute_hashes(file_path: Path) -> Tuple[str, str]:
    """Berechnet (sha256, sha1) einer Datei in einem Durchgang."""
    h256 = hashlib.sha256()
    h1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h256.update(chunk)
            h1.update(chunk)
    return h256.hexdigest(), h1.hexdigest()


def _strip_toml_comments(text: str) -> str:
    """
    Entfernt TOML-Kommentare (# ...), die nicht innerhalb von Anführungszeichen stehen.
    Verhindert zuverlässig, dass auskommentierte Vorlagenzeilen wie `#clientSideOnly=true`
    in Standard-NeoForge/Forge-MDKs fälschlich als aktive Eigenschaft gewertet werden.
    """
    cleaned_lines: List[str] = []
    for raw_line in text.splitlines():
        in_single = False
        in_double = False
        escaped = False
        out_chars: List[str] = []
        for ch in raw_line:
            if escaped:
                out_chars.append(ch)
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                out_chars.append(ch)
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                out_chars.append(ch)
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                out_chars.append(ch)
                continue
            if ch == "#" and not in_single and not in_double:
                break
            out_chars.append(ch)
        cleaned_lines.append("".join(out_chars))
    return "\n".join(cleaned_lines)


def _parse_toml_document(raw_text: str) -> Dict[str, Any]:
    """
    Versucht zunächst Python 3.11+ `tomllib` und nutzt bei ungültigen/nicht-standardkonformen
    Mod-TOML-Dateien einen strukturierten Fallback-Parser nach Kommentarbereinigung.
    """
    try:
        import tomllib

        return tomllib.loads(raw_text)
    except Exception:
        pass

    stripped = _strip_toml_comments(raw_text)
    try:
        import tomllib

        return tomllib.loads(stripped)
    except Exception:
        pass

    # Strukturierter Fallback-Parser für leicht fehlerhafte mods.toml / neoforge.mods.toml
    result: Dict[str, Any] = {"mods": [], "dependencies": {}}
    current_section = "root"
    current_dep_target = ""
    current_obj: Dict[str, Any] = result

    for line in stripped.splitlines():
        s = line.strip()
        if not s:
            continue
        arr_match = re.match(r"^\[\[\s*([^\]]+?)\s*\]\]$", s)
        if arr_match:
            sec_name = arr_match.group(1).strip()
            if sec_name == "mods":
                current_section = "mods"
                current_obj = {}
                result["mods"].append(current_obj)
            elif sec_name.startswith("dependencies."):
                current_section = "dependencies"
                current_dep_target = sec_name.split(".", 1)[1].strip().strip("\"'")
                result["dependencies"].setdefault(current_dep_target, [])
                current_obj = {}
                result["dependencies"][current_dep_target].append(current_obj)
            else:
                current_section = sec_name
                current_obj = {}
            continue

        tbl_match = re.match(r"^\[\s*([^\]]+?)\s*\]$", s)
        if tbl_match:
            current_section = tbl_match.group(1).strip()
            current_obj = {}
            continue

        kv_match = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$", s)
        if kv_match:
            key = kv_match.group(1).strip()
            val_raw = kv_match.group(2).strip()
            val: Any
            if val_raw.lower() == "true":
                val = True
            elif val_raw.lower() == "false":
                val = False
            elif (val_raw.startswith('"') and val_raw.endswith('"')) or (
                val_raw.startswith("'") and val_raw.endswith("'")
            ):
                val = val_raw[1:-1]
            else:
                val = val_raw.strip("\"'")
            current_obj[key] = val

    return result


def inspect_jar_metadata(jar_path: Path) -> Dict[str, Any]:
    """
    Öffnet eine Mod-JAR als ZIP-Archiv und analysiert alle relevanten Metadaten:
      - META-INF/neoforge.mods.toml & META-INF/mods.toml
      - fabric.mod.json
      - quilt.mod.json
      - mcmod.info
      - META-INF/MANIFEST.MF
      - Mixin-Konfigurationsdateien (*.mixins.json / mixin*.json)
      - Eingebettete JARs (META-INF/jarjar/*.jar, META-INF/jars/*.jar)
      - Ressourcen, Datapacks, Worldgen, Rezepte, Loot-Tables, Strukturen, Tags
    """
    info: Dict[str, Any] = {
        "valid_zip": False,
        "loader": "unknown",
        "mod_id": "",
        "mod_name": "",
        "mod_version": "",
        "provided_mods": [],
        "client_side_only_flag": None,  # bool oder None
        "mod_side_field": None,  # "CLIENT", "SERVER", "BOTH"
        "display_test": None,  # "IGNORE_ALL_VERSION", "IGNORE_SERVER_VERSION", "MATCH_VERSION", "NONE"
        "fabric_environment": None,  # "*", "client", "server"
        "quilt_environment": None,  # "*", "client", "dedicated_server"
        "entrypoints": {
            "main": [],
            "client": [],
            "server": [],
        },
        "mixins": {
            "config_files": [],
            "common_mixins": 0,
            "client_mixins": 0,
            "server_mixins": 0,
        },
        "dependencies": [],  # List[ModDependencyRef]
        "embedded_jars": [],  # List[Dict]
        "resources": {
            "has_assets": False,
            "has_data": False,
            "has_worldgen": False,
            "has_dimensions": False,
            "has_structures": False,
            "has_recipes": False,
            "has_loot_tables": False,
            "has_server_tags": False,
            "has_datamaps": False,
        },
        "class_count": 0,
        "has_mod_descriptor": False,
        "manifest_attributes": {},
    }

    if not jar_path.exists() or not zipfile.is_zipfile(jar_path):
        return info

    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            info["valid_zip"] = True
            namelist = zf.namelist()
            name_set = set(namelist)

            # 1. Ressourcen, Klassen & Datapack-Strukturen zählen
            mixin_candidate_files: List[str] = []
            for entry in namelist:
                if entry.endswith(".class"):
                    info["class_count"] += 1
                elif entry.startswith("assets/") and not entry.endswith("/"):
                    info["resources"]["has_assets"] = True
                elif entry.startswith("data/") and not entry.endswith("/"):
                    info["resources"]["has_data"] = True
                    parts = entry.split("/")
                    # data/<namespace>/<category>/...
                    if len(parts) >= 3:
                        cat = parts[2].lower()
                        if cat == "worldgen" or "worldgen/" in entry:
                            info["resources"]["has_worldgen"] = True
                        if cat in ("dimension", "dimension_type"):
                            info["resources"]["has_dimensions"] = True
                        if cat in ("structures", "structure") or "/structure/" in entry or "/structures/" in entry:
                            info["resources"]["has_structures"] = True
                        if cat in ("recipes", "recipe"):
                            info["resources"]["has_recipes"] = True
                        if cat in ("loot_tables", "loot_table"):
                            info["resources"]["has_loot_tables"] = True
                        if cat == "tags":
                            info["resources"]["has_server_tags"] = True
                        if cat == "data_maps":
                            info["resources"]["has_datamaps"] = True

                lower_entry = entry.lower()
                if lower_entry.endswith(".json") and "mixin" in lower_entry and not lower_entry.startswith("assets/"):
                    mixin_candidate_files.append(entry)

            # 2. MANIFEST.MF prüfen (z.B. FMLModType, Automatic-Module-Name, MixinConfigs)
            if "META-INF/MANIFEST.MF" in name_set:
                try:
                    mf_text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="ignore")
                    for line in mf_text.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            info["manifest_attributes"][k.strip()] = v.strip()
                    if "MixinConfigs" in info["manifest_attributes"]:
                        for cfg in info["manifest_attributes"]["MixinConfigs"].split(","):
                            cfg = cfg.strip()
                            if cfg and cfg not in mixin_candidate_files and cfg in name_set:
                                mixin_candidate_files.append(cfg)
                except Exception:
                    pass

            # 3. NeoForge / Forge: META-INF/neoforge.mods.toml oder META-INF/mods.toml
            toml_path = None
            if "META-INF/neoforge.mods.toml" in name_set:
                toml_path = "META-INF/neoforge.mods.toml"
                info["loader"] = "neoforge"
            elif "META-INF/mods.toml" in name_set:
                toml_path = "META-INF/mods.toml"
                info["loader"] = "forge"

            if toml_path:
                info["has_mod_descriptor"] = True
                try:
                    raw_toml = zf.read(toml_path).decode("utf-8", errors="ignore")
                    parsed = _parse_toml_document(raw_toml)

                    # Top-Level clientSideOnly (nur echte boolesche Eigenschaft!)
                    top_cso = parsed.get("clientSideOnly")
                    if isinstance(top_cso, bool):
                        info["client_side_only_flag"] = top_cso

                    top_dt = parsed.get("displayTest")
                    if isinstance(top_dt, str):
                        info["display_test"] = top_dt.strip().upper()

                    mods_list = parsed.get("mods")
                    if isinstance(mods_list, list) and mods_list:
                        first_mod = mods_list[0] if isinstance(mods_list[0], dict) else {}
                        info["mod_id"] = str(first_mod.get("modId") or "").strip()
                        info["mod_name"] = str(first_mod.get("displayName") or info["mod_id"]).strip()
                        info["mod_version"] = str(first_mod.get("version") or "").strip()

                        for m_entry in mods_list:
                            if not isinstance(m_entry, dict):
                                continue
                            mid = str(m_entry.get("modId") or "").strip()
                            if mid and mid not in info["provided_mods"]:
                                info["provided_mods"].append(mid)
                            if isinstance(m_entry.get("clientSideOnly"), bool):
                                if info["client_side_only_flag"] is None:
                                    info["client_side_only_flag"] = m_entry["clientSideOnly"]
                            if isinstance(m_entry.get(" displayTest") or m_entry.get("displayTest"), str):
                                info["display_test"] = str(m_entry.get("displayTest")).strip().upper()
                            if isinstance(m_entry.get("side"), str):
                                info["mod_side_field"] = m_entry["side"].strip().upper()

                    # Mixins in neoforge.mods.toml: [[mixins]] config = "..."
                    mixins_list = parsed.get("mixins")
                    if isinstance(mixins_list, list):
                        for mx in mixins_list:
                            if isinstance(mx, dict) and isinstance(mx.get("config"), str):
                                cfg = mx["config"].strip()
                                if cfg and cfg not in mixin_candidate_files and cfg in name_set:
                                    mixin_candidate_files.append(cfg)

                    # Dependencies in [[dependencies.<modId>]]
                    deps_dict = parsed.get("dependencies")
                    if isinstance(deps_dict, dict):
                        for target_mod, dep_entries in deps_dict.items():
                            if not isinstance(dep_entries, list):
                                continue
                            for dep in dep_entries:
                                if not isinstance(dep, dict):
                                    continue
                                dep_id = str(dep.get("modId") or "").strip()
                                if not dep_id:
                                    continue
                                dep_side = str(dep.get("side") or "BOTH").strip().upper()
                                # NeoForge 1.20.5+ nutzt `type = "required" | "optional" | "discouraged" | "incompatible"`
                                # Ältere Forge/NeoForge nutzen `mandatory = true | false`
                                dep_type_raw = str(dep.get("type") or "").strip().lower()
                                mandatory_raw = dep.get("mandatory")
                                if dep_type_raw in ("incompatible", "discouraged"):
                                    continue
                                if dep_type_raw == "required" or mandatory_raw is True:
                                    dtype = "required"
                                else:
                                    dtype = "optional"

                                if dep_id.lower() == "neoforge" and info["loader"] == "forge":
                                    info["loader"] = "neoforge"

                                if dep_id.lower() in _SYSTEM_DEP_IDS:
                                    continue

                                info["dependencies"].append(
                                    ModDependencyRef(
                                        mod_id=dep_id,
                                        dep_type=dtype,
                                        side=dep_side,
                                        version_range=str(dep.get("versionRange") or "*"),
                                    )
                                )
                except Exception as exc:
                    logger.debug(f"Error parsing {toml_path} in {jar_path.name}: {exc}")

            # 4. Fabric: fabric.mod.json
            if "fabric.mod.json" in name_set:
                info["has_mod_descriptor"] = True
                if info["loader"] == "unknown":
                    info["loader"] = "fabric"
                try:
                    raw_fabric = zf.read("fabric.mod.json").decode("utf-8", errors="ignore")
                    f_data = json.loads(raw_fabric, strict=False)
                    if isinstance(f_data, dict):
                        fid = str(f_data.get("id") or "").strip()
                        if fid:
                            if not info["mod_id"]:
                                info["mod_id"] = fid
                            if fid not in info["provided_mods"]:
                                info["provided_mods"].append(fid)
                        if not info["mod_name"]:
                            info["mod_name"] = str(f_data.get("name") or fid).strip()
                        if not info["mod_version"]:
                            info["mod_version"] = str(f_data.get("version") or "").strip()

                        # Provided aliases
                        provides = f_data.get("provides")
                        if isinstance(provides, list):
                            for p in provides:
                                if isinstance(p, str) and p not in info["provided_mods"]:
                                    info["provided_mods"].append(p)
                                elif isinstance(p, dict) and isinstance(p.get("id"), str):
                                    if p["id"] not in info["provided_mods"]:
                                        info["provided_mods"].append(p["id"])

                        env = f_data.get("environment")
                        if isinstance(env, str):
                            info["fabric_environment"] = env.strip().lower()

                        # Entrypoints
                        ep = f_data.get("entrypoints")
                        if isinstance(ep, dict):
                            for ep_key, ep_vals in ep.items():
                                ep_list = ep_vals if isinstance(ep_vals, list) else [ep_vals]
                                k_lower = ep_key.lower()
                                if k_lower in ("client", "fabric-datagen"):
                                    info["entrypoints"]["client"].extend(str(x) for x in ep_list)
                                elif k_lower in ("server", "dedicated_server"):
                                    info["entrypoints"]["server"].extend(str(x) for x in ep_list)
                                elif k_lower in ("main", "common", "prelaunch"):
                                    info["entrypoints"]["main"].extend(str(x) for x in ep_list)

                        # Mixins in fabric.mod.json
                        f_mixins = f_data.get("mixins")
                        if isinstance(f_mixins, list):
                            for item in f_mixins:
                                if isinstance(item, str):
                                    if item in name_set and item not in mixin_candidate_files:
                                        mixin_candidate_files.append(item)
                                elif isinstance(item, dict):
                                    cfg = item.get("config")
                                    env_m = str(item.get("environment") or "*").lower()
                                    if env_m == "client":
                                        info["mixins"]["client_mixins"] += 1
                                    elif env_m == "server":
                                        info["mixins"]["server_mixins"] += 1
                                    if isinstance(cfg, str) and cfg in name_set and cfg not in mixin_candidate_files:
                                        mixin_candidate_files.append(cfg)

                        # Dependencies
                        for dep_field, dep_type in (("depends", "required"), ("recommends", "optional")):
                            dep_map = f_data.get(dep_field)
                            if isinstance(dep_map, dict):
                                for dep_id, ver_rng in dep_map.items():
                                    if dep_id.lower() in _SYSTEM_DEP_IDS or dep_id.lower().startswith("fabric-"):
                                        # Behalte fabric-api als Hinweis falls nötig, aber ignoriere Basis-Loader
                                        if dep_id.lower() in _SYSTEM_DEP_IDS:
                                            continue
                                    info["dependencies"].append(
                                        ModDependencyRef(
                                            mod_id=dep_id,
                                            dep_type=dep_type,
                                            side="BOTH",
                                            version_range=str(ver_rng),
                                        )
                                    )
                except Exception as exc:
                    logger.debug(f"Error parsing fabric.mod.json in {jar_path.name}: {exc}")

            # 5. Quilt: quilt.mod.json
            if "quilt.mod.json" in name_set:
                info["has_mod_descriptor"] = True
                if info["loader"] == "unknown":
                    info["loader"] = "quilt"
                try:
                    raw_quilt = zf.read("quilt.mod.json").decode("utf-8", errors="ignore")
                    q_data = json.loads(raw_quilt, strict=False)
                    ql = q_data.get("quilt_loader", {}) if isinstance(q_data, dict) else {}
                    if isinstance(ql, dict):
                        qid = str(ql.get("id") or "").strip()
                        if qid:
                            if not info["mod_id"]:
                                info["mod_id"] = qid
                            if qid not in info["provided_mods"]:
                                info["provided_mods"].append(qid)
                        if not info["mod_version"]:
                            info["mod_version"] = str(ql.get("version") or "").strip()
                        meta = ql.get("metadata", {})
                        if isinstance(meta, dict) and not info["mod_name"]:
                            info["mod_name"] = str(meta.get("name") or qid).strip()

                        ep = ql.get("entrypoints")
                        if isinstance(ep, dict):
                            for ep_key, ep_vals in ep.items():
                                ep_list = ep_vals if isinstance(ep_vals, list) else [ep_vals]
                                k_lower = ep_key.lower()
                                if "client" in k_lower:
                                    info["entrypoints"]["client"].extend(str(x) for x in ep_list)
                                elif "server" in k_lower:
                                    info["entrypoints"]["server"].extend(str(x) for x in ep_list)
                                else:
                                    info["entrypoints"]["main"].extend(str(x) for x in ep_list)

                        for dep in ql.get("depends", []):
                            if isinstance(dep, dict):
                                dep_id = str(dep.get("id") or "").strip()
                                optional = bool(dep.get("optional", False))
                                if dep_id and dep_id.lower() not in _SYSTEM_DEP_IDS:
                                    info["dependencies"].append(
                                        ModDependencyRef(
                                            mod_id=dep_id,
                                            dep_type="optional" if optional else "required",
                                            side="BOTH",
                                            version_range=str(dep.get("versions") or "*"),
                                        )
                                    )

                    mc_block = q_data.get("minecraft", {}) if isinstance(q_data, dict) else {}
                    if isinstance(mc_block, dict) and isinstance(mc_block.get("environment"), str):
                        info["quilt_environment"] = mc_block["environment"].strip().lower()
                except Exception as exc:
                    logger.debug(f"Error parsing quilt.mod.json in {jar_path.name}: {exc}")

            # 6. Legacy Forge: mcmod.info
            if "mcmod.info" in name_set and not info["mod_id"]:
                info["has_mod_descriptor"] = True
                if info["loader"] == "unknown":
                    info["loader"] = "forge"
                try:
                    raw_mcmod = zf.read("mcmod.info").decode("utf-8", errors="ignore")
                    mc_data = json.loads(raw_mcmod, strict=False)
                    mod_list = (
                        mc_data.get("modList", [])
                        if isinstance(mc_data, dict)
                        else (mc_data if isinstance(mc_data, list) else [])
                    )
                    if mod_list and isinstance(mod_list[0], dict):
                        m0 = mod_list[0]
                        info["mod_id"] = str(m0.get("modid") or "").strip()
                        info["mod_name"] = str(m0.get("name") or info["mod_id"]).strip()
                        info["mod_version"] = str(m0.get("version") or "").strip()
                        if info["mod_id"] and info["mod_id"] not in info["provided_mods"]:
                            info["provided_mods"].append(info["mod_id"])
                        if isinstance(m0.get("clientSideOnly"), bool):
                            info["client_side_only_flag"] = m0["clientSideOnly"]
                except Exception:
                    pass

            # 7. Mixin-Konfigurationsdateien untersuchen
            for mx_file in mixin_candidate_files[:15]:
                try:
                    mx_raw = zf.read(mx_file).decode("utf-8", errors="ignore")
                    mx_json = json.loads(mx_raw, strict=False)
                    if not isinstance(mx_json, dict):
                        continue
                    if not any(k in mx_json for k in ("mixins", "client", "server", "package")):
                        continue
                    info["mixins"]["config_files"].append(mx_file)
                    common_list = mx_json.get("mixins")
                    client_list = mx_json.get("client")
                    server_list = mx_json.get("server")
                    if isinstance(common_list, list):
                        info["mixins"]["common_mixins"] += len(common_list)
                    if isinstance(client_list, list):
                        info["mixins"]["client_mixins"] += len(client_list)
                    if isinstance(server_list, list):
                        info["mixins"]["server_mixins"] += len(server_list)
                except Exception:
                    pass

            # 8. Eingebettete JARs (Jar-in-Jar: META-INF/jarjar/metadata.json oder META-INF/jars/*.jar)
            if "META-INF/jarjar/metadata.json" in name_set:
                try:
                    jj_raw = zf.read("META-INF/jarjar/metadata.json").decode("utf-8", errors="ignore")
                    jj_data = json.loads(jj_raw, strict=False)
                    for j_entry in jj_data.get("jars", []):
                        ident = j_entry.get("identifier", {})
                        artifact = str(ident.get("artifact") or "").strip()
                        path_in_jar = str(j_entry.get("path") or "").strip()
                        if artifact:
                            info["embedded_jars"].append({"id": artifact, "path": path_in_jar})
                            if artifact.lower() not in [p.lower() for p in info["provided_mods"]]:
                                info["provided_mods"].append(artifact)
                except Exception:
                    pass

            for entry in namelist:
                if (entry.startswith("META-INF/jars/") or entry.startswith("META-INF/jarjar/")) and entry.endswith(".jar"):
                    nested_stem = Path(entry).stem
                    # Bereinige Versionssuffixe von eingebetteten Bibliotheken
                    base_id = re.split(r"-\d", nested_stem)[0].strip().lower()
                    if base_id and base_id not in [e.get("id", "").lower() for e in info["embedded_jars"]]:
                        info["embedded_jars"].append({"id": base_id, "path": entry})
                    if base_id and base_id not in [p.lower() for p in info["provided_mods"]]:
                        info["provided_mods"].append(base_id)

    except Exception as exc:
        logger.debug(f"Could not inspect JAR {jar_path.name}: {exc}")

    # Fallback für Mod-ID aus Dateinamen, falls keine Deskriptordatei (z.B. reine Library/Coremod)
    if not info["mod_id"]:
        stem = jar_path.stem
        cleaned = re.split(r"[-+_](?:neoforge|forge|fabric|quilt|mc|universal|\d)", stem, maxsplit=1, flags=re.IGNORECASE)[0]
        info["mod_id"] = (cleaned or stem).lower().replace(" ", "_")
    if not info["mod_name"]:
        info["mod_name"] = info["mod_id"]
    if info["mod_id"] and info["mod_id"] not in info["provided_mods"]:
        info["provided_mods"].insert(0, info["mod_id"])

    return info


# ---------------------------------------------------------------------------
# Offizielle Mod-Metadaten (Modrinth / CurseForge / FTB / Manifeste) (Abschnitt 4A)
# ---------------------------------------------------------------------------


class OfficialMetadataClient:
    """
    Fragt offizielle Mod-Metadaten (Modrinth Batch-Hash-API, CurseForge API,
    Modpack-Manifeste wie modrinth.index.json, FTB version.json, CurseForge manifest.json) ab.
    """

    MODRINTH_API = "https://api.modrinth.com/v2"
    CURSEFORGE_API = "https://api.curseforge.com/v1"

    def __init__(self, enable_network: bool = True, timeout: float = 8.0):
        self.enable_network = enable_network
        self.timeout = timeout
        self._cf_api_key = os.environ.get("CURSEFORGE_API_KEY", "").strip()
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "MinecraftController-ModSideResolver/2.1 (https://github.com)"}
        )

    def fetch_modrinth_by_hashes(self, sha1_map: Dict[str, Path]) -> Dict[str, Dict[str, Any]]:
        """
        Nutzt Modrinths Batch-Endpunkt `/v2/version_files` + `/v2/projects` um für alle JARs
        in wenigen Requests `client_side` und `server_side` separat auszuwerten.
        Gibt Mapping `sha1 -> {project_id, title, slug, client_side, server_side, loaders, game_versions, dependencies}` zurück.
        """
        if not self.enable_network or not sha1_map:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        sha1_list = list(sha1_map.keys())

        try:
            version_by_sha1: Dict[str, Dict[str, Any]] = {}
            project_ids: Set[str] = set()

            # Batch in Gruppen zu je 150 Hashes
            for i in range(0, len(sha1_list), 150):
                batch = sha1_list[i : i + 150]
                resp = self._session.post(
                    f"{self.MODRINTH_API}/version_files",
                    json={"hashes": batch, "algorithm": "sha1"},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if isinstance(data, dict):
                    for h, ver_obj in data.items():
                        if isinstance(ver_obj, dict):
                            version_by_sha1[h.lower()] = ver_obj
                            pid = ver_obj.get("project_id")
                            if pid:
                                project_ids.add(pid)

            projects_by_id: Dict[str, Dict[str, Any]] = {}
            pid_list = list(project_ids)
            for i in range(0, len(pid_list), 100):
                batch_pids = pid_list[i : i + 100]
                resp = self._session.get(
                    f"{self.MODRINTH_API}/projects",
                    params={"ids": json.dumps(batch_pids)},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    for proj in resp.json():
                        if isinstance(proj, dict) and proj.get("id"):
                            projects_by_id[proj["id"]] = proj

            for h, ver_obj in version_by_sha1.items():
                pid = ver_obj.get("project_id", "")
                proj = projects_by_id.get(pid, {})
                results[h] = {
                    "source": "modrinth_api",
                    "project_id": pid,
                    "slug": proj.get("slug", ""),
                    "title": proj.get("title", ""),
                    "client_side": proj.get("client_side", "unknown"),
                    "server_side": proj.get("server_side", "unknown"),
                    "version_number": ver_obj.get("version_number", ""),
                    "loaders": ver_obj.get("loaders", []),
                    "game_versions": ver_obj.get("game_versions", []),
                    "dependencies": ver_obj.get("dependencies", []),
                }
        except Exception as exc:
            logger.debug(f"Modrinth batch metadata lookup failed (offline or rate-limited): {exc}")

        return results

    @staticmethod
    def load_pack_manifest_hints(pack_dir: Path) -> Dict[str, Dict[str, Any]]:
        """
        Liest vorhandene Modpack-Manifestdateien im Zielverzeichnis aus:
          - Modrinth: `modrinth.index.json` (`files[].env.client`, `files[].env.server`)
          - FTB: `version.json` / `.ftb_manifest.json` (`files[].clientonly`, `files[].side`)
          - CurseForge: `manifest.json` (liefert projectID/fileID, aber laut Spezifikation allein KEINE verlässliche Side-Info)
        Gibt ein Mapping `dateiname_lower -> hint_dict` zurück.
        """
        hints: Dict[str, Dict[str, Any]] = {}
        if not pack_dir or not pack_dir.exists():
            return hints

        # 1. Modrinth modrinth.index.json
        mr_index = pack_dir / "modrinth.index.json"
        if mr_index.exists():
            try:
                mr_data = json.loads(mr_index.read_text(encoding="utf-8", errors="ignore"))
                for f_entry in mr_data.get("files", []):
                    path_str = str(f_entry.get("path") or "")
                    fname = Path(path_str).name.lower()
                    env = f_entry.get("env") or {}
                    if fname and isinstance(env, dict):
                        hints[fname] = {
                            "source": "modrinth_index",
                            "client_side": env.get("client", "unknown"),
                            "server_side": env.get("server", "unknown"),
                            "hashes": f_entry.get("hashes", {}),
                        }
            except Exception as exc:
                logger.debug(f"Could not read modrinth.index.json: {exc}")

        # 2. FTB version.json / ftb_manifest.json
        for ftb_file in ("version.json", ".ftb_manifest.json", "ftb-manifest.json"):
            ftb_path = pack_dir / ftb_file
            if ftb_path.exists():
                try:
                    ftb_data = json.loads(ftb_path.read_text(encoding="utf-8", errors="ignore"))
                    for f_entry in ftb_data.get("files", []):
                        fname = str(f_entry.get("name") or Path(str(f_entry.get("path") or "")).name).lower()
                        if not fname:
                            continue
                        client_only = bool(f_entry.get("clientonly", False))
                        server_only = bool(f_entry.get("serveronly", False))
                        side_str = str(f_entry.get("side") or "").upper()
                        hints[fname] = {
                            "source": "ftb_manifest",
                            "clientonly": client_only,
                            "serveronly": server_only,
                            "side": side_str,
                            "optional": bool(f_entry.get("optional", False)),
                        }
                except Exception as exc:
                    logger.debug(f"Could not read {ftb_file}: {exc}")

        return hints


# ---------------------------------------------------------------------------
# Hauptklasse: ModSideResolver (Abschnitt 3, 4, 5, 6, 8)
# ---------------------------------------------------------------------------


class ModSideResolver:
    """
    Eigenständiges und wiederverwendbares Mod-Side-Erkennungssystem.
    Bestimmt für jede Mod in einem Modpack mehrstufig und nachvollziehbar die benötigte Seite:
      - CLIENT_ONLY
      - SERVER_ONLY
      - BOTH_SIDES_REQUIRED
      - OPTIONAL_CLIENT
      - OPTIONAL_SERVER
      - UNKNOWN
    """

    def __init__(
        self,
        cache: Optional[ModSideCache] = None,
        enable_network: bool = True,
        minecraft_version: str = "unknown",
        modloader: str = "unknown",
    ):
        self.cache = cache or ModSideCache()
        self.metadata_client = OfficialMetadataClient(enable_network=enable_network)
        self.minecraft_version = minecraft_version
        self.modloader = modloader

    # ------------------------------------------------------------------
    # Einzel-Mod-Analyse (Stufen A, B, C + Konflikterkennung)
    # ------------------------------------------------------------------

    def analyze_mod(
        self,
        jar_path: Path,
        official_meta: Optional[Dict[str, Any]] = None,
        manifest_hint: Optional[Dict[str, Any]] = None,
        minecraft_version: Optional[str] = None,
        modloader: Optional[str] = None,
        force_reanalyze: bool = False,
    ) -> ModAnalysisResult:
        """
        Analysiert eine einzelne Mod-JAR-Datei über alle technischen Stufen (Offizielle Metadaten,
        JAR-Metadaten, Java-Bytecode) und berücksichtigt das Cache-System.
        """
        jar_path = Path(jar_path)
        mc_ver = minecraft_version or self.minecraft_version or "unknown"
        loader_ctx = modloader or self.modloader or "unknown"

        if not jar_path.exists() or not jar_path.is_file():
            return ModAnalysisResult(
                file_path=str(jar_path),
                file_name=jar_path.name,
                sha256="",
                mod_id=jar_path.stem.lower(),
                mod_name=jar_path.stem,
                mod_version="unknown",
                minecraft_version=mc_ver,
                modloader=loader_ctx,
                side=ModSideCategory.UNKNOWN,
                confidence=0.0,
                confidence_level=ConfidenceLevel.LOW,
                keep_on_server=True,
                primary_reason="Datei existiert nicht – Sicherheitsregel: UNKNOWN bleibt auf Server",
            )

        sha256, _ = compute_hashes(jar_path)

        # 1. Cache-Prüfung (sofern keine neuen dynamischen offiziellen Metadaten übergeben wurden)
        if not force_reanalyze and not official_meta and not manifest_hint:
            cached = self.cache.get(sha256, mc_ver, loader_ctx)
            if cached:
                return self._dict_to_result(cached, jar_path, from_cache=True)

        # 2. Stufe B: JAR-Metadaten analysieren
        jar_info = inspect_jar_metadata(jar_path)
        effective_loader = loader_ctx if loader_ctx != "unknown" else jar_info.get("loader", "unknown")

        # Falls der Loader erst aus der JAR erkannt wurde, nochmals im Cache nachschlagen
        if not force_reanalyze and not official_meta and not manifest_hint and effective_loader != loader_ctx:
            cached = self.cache.get(sha256, mc_ver, effective_loader)
            if cached:
                return self._dict_to_result(cached, jar_path, from_cache=True)

        # 3. Stufe C: Java-Bytecode analysieren
        raw_bc = scan_jar_for_bytecode_side(jar_path)
        if isinstance(raw_bc, dict):
            bytecode_info = raw_bc
        else:
            server_refs = list(getattr(raw_bc, "server_refs", []) or [])
            client_refs = list(getattr(raw_bc, "client_refs", []) or [])
            network_refs = list(getattr(raw_bc, "network_refs", []) or [])
            client_events = list(getattr(raw_bc, "client_events", []) or [])
            server_events = list(getattr(raw_bc, "server_events", []) or [])
            dist_guards = list(getattr(raw_bc, "dist_guards", []) or [])
            client_eps = list(getattr(raw_bc, "client_entrypoints", []) or [])
            common_eps = list(getattr(raw_bc, "common_entrypoints", []) or [])
            server_eps = list(getattr(raw_bc, "server_entrypoints", []) or [])
            cls_client_only = int(getattr(raw_bc, "class_level_client_only_count", 0) or 0)
            has_reg = any(
                any(tok in ref for tok in ("DeferredRegister", "Registry", "Block", "Item", "EntityType", "MenuType", "Recipe", "Structure"))
                for ref in server_refs
            )
            bytecode_info = {
                "side": getattr(raw_bc, "side", "UNKNOWN"),
                "confidence": float(getattr(raw_bc, "confidence", 0.0) or 0.0),
                "total_classes": int(getattr(raw_bc, "classes_scanned", 0) or 0),
                "client_classes": max(len(client_refs), cls_client_only),
                "server_classes": len(server_refs) + len(server_events) + len(common_eps) + len(server_eps),
                "client_signals": len(client_events) + len(client_eps) + cls_client_only,
                "server_signals": len(server_refs) + len(server_events) + len(common_eps) + len(server_eps),
                "has_registry_entries": has_reg or len( server_refs) > 0,
                "has_network_packets": len(network_refs) > 0,
                "has_server_entrypoint": len(server_eps) > 0 or len(common_eps) > 0 or len(server_events) > 0,
                "has_client_entrypoint": len(client_eps) > 0 or bool(getattr(raw_bc, "only_in_client", False)),
                "has_dist_executor": len(dist_guards) > 0,
                "has_only_client_classes_without_entrypoints": bool(
                    getattr(raw_bc, "has_only_client_classes_without_entrypoints", False)
                ),
            }

        # 4. Evidenzen sammeln & auswerten (Stufen A + B + C)
        evidences: List[DetectionEvidence] = []
        conflicts: List[str] = []

        # --- STUFE A: Offizielle Mod-Metadaten ---
        combined_official: Dict[str, Any] = {}
        if manifest_hint:
            combined_official.update(manifest_hint)
        if official_meta:
            combined_official.update(official_meta)

        self._collect_official_evidence(combined_official, evidences)

        # --- STUFE B: JAR-Metadaten ---
        self._collect_jar_metadata_evidence(jar_info, evidences)

        # --- STUFE C: Bytecode-Analyse ---
        self._collect_bytecode_evidence(bytecode_info, jar_info, evidences)

        # --- STUFE E: Intelligente Erkennungslogik & Konflikterkennung ---
        side, confidence, conf_level, primary_reason = self._synthesize_decision(
            jar_path=jar_path,
            jar_info=jar_info,
            bytecode_info=bytecode_info,
            evidences=evidences,
            conflicts=conflicts,
        )

        # Sicherheitsregel: UNKNOWN darf niemals als CLIENT_ONLY interpretiert werden!
        keep_on_server = side != ModSideCategory.CLIENT_ONLY

        sources = list(dict.fromkeys(e.source for e in evidences))
        result = ModAnalysisResult(
            file_path=str(jar_path),
            file_name=jar_path.name,
            sha256=sha256,
            mod_id=jar_info.get("mod_id") or jar_path.stem.lower(),
            mod_name=jar_info.get("mod_name") or jar_path.stem,
            mod_version=jar_info.get("mod_version") or "unknown",
            minecraft_version=mc_ver,
            modloader=effective_loader,
            side=side,
            confidence=confidence,
            confidence_level=conf_level,
            keep_on_server=keep_on_server,
            primary_reason=primary_reason,
            detection_sources=sources,
            evidences=evidences,
            dependencies=jar_info.get("dependencies", []),
            provided_mods=jar_info.get("provided_mods", []),
            conflicts=conflicts,
            from_cache=False,
            jar_details={
                "loader": jar_info.get("loader"),
                "client_side_only_flag": jar_info.get("client_side_only_flag"),
                "mod_side_field": jar_info.get("mod_side_field"),
                "display_test": jar_info.get("display_test"),
                "fabric_environment": jar_info.get("fabric_environment"),
                "quilt_environment": jar_info.get("quilt_environment"),
                "entrypoints": jar_info.get("entrypoints"),
                "mixins": jar_info.get("mixins"),
                "resources": jar_info.get("resources"),
                "embedded_jars": jar_info.get("embedded_jars"),
                "class_count": jar_info.get("class_count"),
            },
            bytecode_details=bytecode_info,
            official_metadata=combined_official,
        )

        # Im persistenten Cache speichern
        self.cache.put(result)
        return result

    def _collect_official_evidence(
        self, official: Dict[str, Any], evidences: List[DetectionEvidence]
    ) -> None:
        if not official:
            return

        src_name = f"official_metadata:{official.get('source', 'api')}"
        client_side = str(official.get("client_side") or "").lower()
        server_side = str(official.get("server_side") or "").lower()

        # Modrinth / modrinth.index.json: client_side & server_side separat auswerten
        if client_side or server_side:
            if client_side in ("required", "optional") and server_side == "unsupported":
                evidences.append(
                    DetectionEvidence(
                        source=src_name,
                        side_hint=ModSideCategory.CLIENT_ONLY,
                        confidence=0.95,
                        reason=f"Offizielle Metadaten: client_side={client_side}, server_side=unsupported (Sehr hohe Sicherheit: Client-only)",
                        details={"client_side": client_side, "server_side": server_side},
                    )
                )
            elif server_side == "required" and client_side == "unsupported":
                evidences.append(
                    DetectionEvidence(
                        source=src_name,
                        side_hint=ModSideCategory.SERVER_ONLY,
                        confidence=0.95,
                        reason="Offizielle Metadaten: server_side=required, client_side=unsupported",
                        details={"client_side": client_side, "server_side": server_side},
                    )
                )
            elif client_side == "required" and server_side == "required":
                evidences.append(
                    DetectionEvidence(
                        source=src_name,
                        side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                        confidence=0.95,
                        reason="Offizielle Metadaten: client_side=required, server_side=required",
                        details={"client_side": client_side, "server_side": server_side},
                    )
                )
            elif server_side == "optional" and client_side in ("required", "optional"):
                evidences.append(
                    DetectionEvidence(
                        source=src_name,
                        side_hint=ModSideCategory.OPTIONAL_SERVER,
                        confidence=0.88,
                        reason=f"Offizielle Metadaten: client_side={client_side}, server_side=optional (auf Server kompatibel/optional)",
                        details={"client_side": client_side, "server_side": server_side},
                    )
                )
            elif client_side == "optional" and server_side == "required":
                evidences.append(
                    DetectionEvidence(
                        source=src_name,
                        side_hint=ModSideCategory.OPTIONAL_CLIENT,
                        confidence=0.90,
                        reason="Offizielle Metadaten: client_side=optional, server_side=required",
                        details={"client_side": client_side, "server_side": server_side},
                    )
                )

        # FTB-spezifische Angaben
        if official.get("clientonly") is True or str(official.get("side", "")).upper() == "CLIENT":
            evidences.append(
                DetectionEvidence(
                    source=src_name,
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.92,
                    reason="Offizielle FTB-Modpack-Metadaten markieren die Mod als Client-only",
                    details={"clientonly": True},
                )
            )
        elif official.get("serveronly") is True or str(official.get("side", "")).upper() == "SERVER":
            evidences.append(
                DetectionEvidence(
                    source=src_name,
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=0.92,
                    reason="Offizielle FTB-Modpack-Metadaten markieren die Mod als Server-only",
                    details={"serveronly": True},
                )
            )

        # CurseForge gameVersions / environment tags falls vorhanden
        cf_envs = [str(x).lower() for x in official.get("cf_environments", [])]
        if "client" in cf_envs and "server" not in cf_envs:
            evidences.append(
                DetectionEvidence(
                    source="official_metadata:curseforge",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.88,
                    reason="CurseForge Datei-Metadaten deklarieren ausschließlich Client-Umgebung",
                    details={"cf_environments": cf_envs},
                )
            )
        elif "server" in cf_envs and "client" not in cf_envs:
            evidences.append(
                DetectionEvidence(
                    source="official_metadata:curseforge",
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=0.88,
                    reason="CurseForge Datei-Metadaten deklarieren ausschließlich Server-Umgebung",
                    details={"cf_environments": cf_envs},
                )
            )
        elif "client" in cf_envs and "server" in cf_envs:
            evidences.append(
                DetectionEvidence(
                    source="official_metadata:curseforge",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=0.85,
                    reason="CurseForge Datei-Metadaten deklarieren Client + Server",
                    details={"cf_environments": cf_envs},
                )
            )

    def _collect_jar_metadata_evidence(
        self, jar_info: Dict[str, Any], evidences: List[DetectionEvidence]
    ) -> None:
        if not jar_info.get("valid_zip"):
            return

        loader = jar_info.get("loader", "unknown")

        # 1. NeoForge / Forge `clientSideOnly = true` (echtes TOML-Attribut, keine Kommentare)
        if jar_info.get("client_side_only_flag") is True:
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.mods.toml",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.95,
                    reason="JAR-Metadaten setzen explizit clientSideOnly = true",
                )
            )
        elif jar_info.get("client_side_only_flag") is False:
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.mods.toml",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=0.75,
                    reason="JAR-Metadaten setzen explizit clientSideOnly = false",
                )
            )

        # 2. NeoForge / Forge `side = "CLIENT" | "SERVER" | "BOTH"` in [[mods]]
        mod_side_field = jar_info.get("mod_side_field")
        if mod_side_field == "CLIENT":
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.mods.toml",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.94,
                    reason="[[mods]]-Eintrag deklariert side = \"CLIENT\"",
                )
            )
        elif mod_side_field == "SERVER":
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.mods.toml",
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=0.94,
                    reason="[[mods]]-Eintrag deklariert side = \"SERVER\"",
                )
            )

        # 3. Fabric `environment` Feld
        fab_env = jar_info.get("fabric_environment")
        if fab_env == "client":
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:fabric.mod.json",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.96,
                    reason='fabric.mod.json deklariert "environment": "client" (Sehr hohe Sicherheit: Client-only)',
                )
            )
        elif fab_env == "server":
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:fabric.mod.json",
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=0.96,
                    reason='fabric.mod.json deklariert "environment": "server"',
                )
            )

        # 4. Quilt `minecraft.environment` Feld
        quilt_env = jar_info.get("quilt_environment")
        if quilt_env == "client":
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:quilt.mod.json",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.96,
                    reason='quilt.mod.json deklariert "environment": "client"',
                )
            )
        elif quilt_env in ("dedicated_server", "server"):
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:quilt.mod.json",
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=0.96,
                    reason=f'quilt.mod.json deklariert "environment": "{quilt_env}"',
                )
            )

        # 5. Fabric / Quilt Entrypoints in Metadaten
        eps = jar_info.get("entrypoints", {})
        has_client_ep = bool(eps.get("client"))
        has_main_ep = bool(eps.get("main"))
        has_server_ep = bool(eps.get("server"))
        if has_client_ep and not has_main_ep and not has_server_ep and fab_env != "server":
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:entrypoints",
                    side_hint=ModSideCategory.CLIENT_ONLY,
                    confidence=0.86,
                    reason="JAR-Metadaten definieren ausschließlich Client-Entrypoints und keine Main/Server-Entrypoints",
                    details={"client_entrypoints": eps.get("client")},
                )
            )
        elif has_main_ep or has_server_ep:
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:entrypoints",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED if has_main_ep else ModSideCategory.SERVER_ONLY,
                    confidence=0.80,
                    reason="JAR-Metadaten definieren Main/Server-Entrypoints",
                    details={"main": eps.get("main"), "server": eps.get("server")},
                )
            )

        # 6. Server-Ressourcen / Datapacks / Worldgen in `data/`
        res = jar_info.get("resources", {})
        if (
            res.get("has_worldgen")
            or res.get("has_dimensions")
            or res.get("has_structures")
            or res.get("has_recipes")
            or res.get("has_loot_tables")
            or res.get("has_datamaps")
        ):
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:datapack_resources",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=0.95,
                    reason="JAR enthält Server-Datapack-/Weltgenerierungsdaten (worldgen/structures/dimensions/recipes/loot_tables)",
                    details=res,
                )
            )
        elif res.get("has_server_tags") and jar_info.get("class_count", 0) == 0:
            evidences.append(
                DetectionEvidence(
                    source="jar_metadata:datapack_resources",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=0.90,
                    reason="Reine Datapack-JAR mit Server-Tags",
                    details=res,
                )
            )

        # 7. Mixin-Konfigurationen
        mx = jar_info.get("mixins", {})
        if mx.get("config_files"):
            c_cnt = mx.get("client_mixins", 0)
            m_cnt = mx.get("common_mixins", 0)
            s_cnt = mx.get("server_mixins", 0)
            if c_cnt > 0 and m_cnt == 0 and s_cnt == 0:
                evidences.append(
                    DetectionEvidence(
                        source="jar_metadata:mixins",
                        side_hint=ModSideCategory.CLIENT_ONLY,
                        confidence=0.78,
                        reason=f"Mixin-Konfiguration enthält ausschließlich Client-Mixins ({c_cnt} Client, 0 Common/Server)",
                        details=mx,
                    )
                )
            elif m_cnt > 0 or s_cnt > 0:
                evidences.append(
                    DetectionEvidence(
                        source="jar_metadata:mixins",
                        side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                        confidence=0.78,
                        reason=f"Mixin-Konfiguration enthält Common/Server-Mixins ({m_cnt} Common, {s_cnt} Server)",
                        details=mx,
                    )
                )

        # 8. DisplayTest als sekundärer Hinweis
        dt = jar_info.get("display_test")
        if dt == "IGNORE_ALL_VERSION":
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.displayTest",
                    side_hint=ModSideCategory.OPTIONAL_CLIENT,
                    confidence=0.55,
                    reason="displayTest = IGNORE_ALL_VERSION (Einseitiger Betrieb erlaubt, weitere Prüfung über Bytecode/Metadaten)",
                )
            )
        elif dt == "IGNORE_SERVER_VERSION":
            evidences.append(
                DetectionEvidence(
                    source=f"jar_metadata:{loader}.displayTest",
                    side_hint=ModSideCategory.OPTIONAL_SERVER,
                    confidence=0.65,
                    reason="displayTest = IGNORE_SERVER_VERSION (Server-seitige Mod ohne Client-Zwang)",
                )
            )

    def _collect_bytecode_evidence(
        self,
        bc: Dict[str, Any],
        jar_info: Dict[str, Any],
        evidences: List[DetectionEvidence],
    ) -> None:
        if not bc or bc.get("total_classes", 0) == 0:
            return

        bc_side = bc.get("side", "UNKNOWN")
        bc_conf = float(bc.get("confidence", 0.0))

        # Starke Server-/Common-Signale im Bytecode:
        # Registries (Block, Item, EntityType, DeferredRegister), Networking-Payloads, Server-Events, Commands
        if bc.get("has_registry_entries") or bc.get("has_network_packets") or bc.get("has_server_entrypoint"):
            reasons = []
            if bc.get("has_registry_entries"):
                reasons.append("Gameplay-Registrierungen (DeferredRegister/Blocks/Items/Menus/Entities)")
            if bc.get("has_network_packets"):
                reasons.append("Netzwerk-Payloads/Channel-Registrierung")
            if bc.get("has_server_entrypoint") or bc.get("server_signals", 0) > 0:
                reasons.append("Server-Events/Commands/Entrypoints")

            evidences.append(
                DetectionEvidence(
                    source="bytecode:server_common_features",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=max(0.88, bc_conf),
                    reason="Bytecode enthält Server-/Synchronisations-Logik: " + ", ".join(reasons),
                    details={
                        "has_registry_entries": bc.get("has_registry_entries"),
                        "has_network_packets": bc.get("has_network_packets"),
                        "server_classes": bc.get("server_classes"),
                        "client_classes": bc.get("client_classes"),
                        "has_dist_executor": bc.get("has_dist_executor"),
                    },
                )
            )
            return

        if bc_side == "SERVER":
            evidences.append(
                DetectionEvidence(
                    source="bytecode:server_only",
                    side_hint=ModSideCategory.SERVER_ONLY,
                    confidence=max(0.85, bc_conf),
                    reason="Bytecode enthält ausschließlich Dedicated-Server-Logik und keine Client-Referenzen",
                    details=bc,
                )
            )
            return

        if bc_side == "BOTH":
            evidences.append(
                DetectionEvidence(
                    source="bytecode:both_sides",
                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                    confidence=max(0.82, bc_conf),
                    reason="Bytecode enthält sowohl Server- als auch Client-Funktionalität",
                    details=bc,
                )
            )
            return

        if bc_side == "CLIENT":
            # Prüfe streng nach Abschnitt 4C & 5:
            # Ein bloßer Import einer Client-Klasse oder GUI/HUD allein reicht NICHT!
            has_client_ep = bool(bc.get("has_client_entrypoint"))
            client_signals = int(bc.get("client_signals", 0))
            total_cls = int(bc.get("total_classes", 1))
            client_cls = int(bc.get("client_classes", 0))
            server_cls = int(bc.get("server_classes", 0))

            if (has_client_ep or client_signals > 0) and server_cls == 0:
                evidences.append(
                    DetectionEvidence(
                        source="bytecode:client_entrypoint_and_events",
                        side_hint=ModSideCategory.CLIENT_ONLY,
                        confidence=bc_conf,
                        reason=(
                            f"Bytecode besitzt ausschließlich Client-Entrypoints/Client-Events "
                            f"({client_cls}/{total_cls} Client-Klassen, 0 Server-Klassen/Registries/Payloads)"
                        ),
                        details=bc,
                    )
                )
            else:
                # Nur Client-Klassen gefunden ohne klaren Client-Entrypoint -> laut Spezifikation KEIN ausreichender Beweis!
                evidences.append(
                    DetectionEvidence(
                        source="bytecode:client_imports_only",
                        side_hint=ModSideCategory.UNKNOWN,
                        confidence=0.40,
                        reason="Nur Client-Klassen/Imports im Bytecode gefunden – kein ausreichender Beweis für CLIENT_ONLY",
                        details=bc,
                    )
                )

    def _synthesize_decision(
        self,
        jar_path: Path,
        jar_info: Dict[str, Any],
        bytecode_info: Dict[str, Any],
        evidences: List[DetectionEvidence],
        conflicts: List[str],
    ) -> Tuple[ModSideCategory, float, ConfidenceLevel, str]:
        """
        Kombiniert alle gesammelten Beweise aus offiziellen Metadaten, JAR-Metadaten und Bytecode.
        Erkennt und dokumentiert Widersprüche zwischen Quellen (Abschnitt 5).
        """
        if not evidences:
            return (
                ModSideCategory.UNKNOWN,
                0.0,
                ConfidenceLevel.LOW,
                "Keine eindeutigen Metadaten- oder Bytecode-Signale gefunden (Sicherheitsregel: verbleibt auf dem Server)",
            )

        official_evs = [e for e in evidences if e.source.startswith("official_metadata:")]
        jar_evs = [e for e in evidences if e.source.startswith("jar_metadata:")]
        bc_evs = [e for e in evidences if e.source.startswith("bytecode:")]

        # Prüfe auf harte Server-/Common-Beweise in JAR-Ressourcen oder Bytecode
        has_datapack_worldgen = any(e.source == "jar_metadata:datapack_resources" for e in jar_evs)
        has_bc_server_features = any(
            e.source in ("bytecode:server_common_features", "bytecode:both_sides", "bytecode:server_only")
            for e in bc_evs
        )
        has_jar_client_only = any(
            e.side_hint == ModSideCategory.CLIENT_ONLY and e.confidence >= 0.85 for e in jar_evs
        )
        has_official_client_only = any(
            e.side_hint == ModSideCategory.CLIENT_ONLY and e.confidence >= 0.85 for e in official_evs
        )
        has_official_server_support = any(
            e.side_hint
            in (
                ModSideCategory.BOTH_SIDES_REQUIRED,
                ModSideCategory.SERVER_ONLY,
                ModSideCategory.OPTIONAL_SERVER,
                ModSideCategory.OPTIONAL_CLIENT,
            )
            for e in official_evs
        )

        # --- Konflikterkennung zwischen offiziellen Metadaten, JAR-Metadaten und Bytecode ---
        if (has_official_client_only or has_jar_client_only) and (has_datapack_worldgen or has_bc_server_features):
            conflict_msg = (
                "Konflikt erkannt: Metadaten deuten auf Client-only hin, aber JAR/Bytecode enthält "
                "aktive Server-Registrierungen, Netzwerk-Payloads oder Weltgenerierungs-/Datapack-Daten."
            )
            conflicts.append(conflict_msg)
            # Wenn offizielle Metadaten ODER JAR-Metadaten explizit `clientSideOnly=true` / `environment="client"`
            # sagen, es aber NUR Netzwerkpackets für optionale Client-Features sind vs. echte Server-Registries:
            if has_datapack_worldgen or bytecode_info.get("has_registry_entries"):
                return (
                    ModSideCategory.UNKNOWN,
                    0.50,
                    ConfidenceLevel.CONFLICTING,
                    f"{conflict_msg} -> Als UNKNOWN eingestuft und auf Server behalten.",
                )

        if has_official_server_support and not has_jar_client_only:
            # Offizielle Metadaten bestätigen Server-Kompatibilität (z.B. AppleSkin, JEI, AuthMe)
            best_off = max(
                (
                    e
                    for e in official_evs
                    if e.side_hint
                    in (
                        ModSideCategory.BOTH_SIDES_REQUIRED,
                        ModSideCategory.SERVER_ONLY,
                        ModSideCategory.OPTIONAL_SERVER,
                        ModSideCategory.OPTIONAL_CLIENT,
                    )
                ),
                key=lambda x: x.confidence,
            )
            if any(e.side_hint == ModSideCategory.CLIENT_ONLY for e in bc_evs):
                conflicts.append(
                    f"Hinweis: Bytecode enthält überwiegend Client-Klassen, aber offizielle Metadaten ({best_off.source}) bestätigen Server-Kompatibilität ({best_off.side_hint.value})."
                )
            return (
                best_off.side_hint,
                best_off.confidence,
                ConfidenceLevel.VERY_HIGH if best_off.confidence >= 0.9 else ConfidenceLevel.HIGH,
                best_off.reason,
            )

        # Fall 1: Explizite Client-Only-Deklaration in offiziellen Metadaten ODER JAR-Metadaten (clientSideOnly=true / fabric environment=client)
        if has_official_client_only or has_jar_client_only:
            client_evs = [
                e
                for e in (official_evs + jar_evs + bc_evs)
                if e.side_hint == ModSideCategory.CLIENT_ONLY
            ]
            best = max(client_evs, key=lambda x: x.confidence)
            # Wenn mehrere Quellen (z.B. JAR-Metadaten + Bytecode) übereinstimmen, steigt die Sicherheit
            combined_conf = min(0.99, best.confidence + 0.03 * (len(client_evs) - 1))
            return (
                ModSideCategory.CLIENT_ONLY,
                combined_conf,
                ConfidenceLevel.VERY_HIGH if combined_conf >= 0.90 else ConfidenceLevel.HIGH,
                best.reason,
            )

        # Fall 2: Datapack / Worldgen / Server-Registries / Networking im Bytecode
        if has_datapack_worldgen or has_bc_server_features:
            srv_evs = [
                e
                for e in (jar_evs + bc_evs)
                if e.side_hint in (ModSideCategory.BOTH_SIDES_REQUIRED, ModSideCategory.SERVER_ONLY)
            ]
            best = max(srv_evs, key=lambda x: x.confidence)
            return (
                best.side_hint,
                best.confidence,
                ConfidenceLevel.VERY_HIGH if best.confidence >= 0.90 else ConfidenceLevel.HIGH,
                best.reason,
            )

        # Fall 3: Explizite Server-Only-Deklaration in JAR-Metadaten
        jar_srv_only = [e for e in jar_evs if e.side_hint == ModSideCategory.SERVER_ONLY and e.confidence >= 0.85]
        if jar_srv_only:
            best = max(jar_srv_only, key=lambda x: x.confidence)
            return (
                ModSideCategory.SERVER_ONLY,
                best.confidence,
                ConfidenceLevel.VERY_HIGH,
                best.reason,
            )

        # Fall 4: Ausschließlich Client-Entrypoints & Client-Funktionen im Bytecode (ohne Server-Klassen, ohne Datapack)
        bc_client_ep = [
            e
            for e in bc_evs
            if e.source == "bytecode:client_entrypoint_and_events"
            and e.side_hint == ModSideCategory.CLIENT_ONLY
        ]
        if bc_client_ep:
            best_bc = bc_client_ep[0]
            # Prüfe ob die JAR überhaupt keine Server-Ressourcen hat und der Bytecode-Beweis hoch ist
            has_client_Mixin_or_dt = any(
                e.side_hint in (ModSideCategory.CLIENT_ONLY, ModSideCategory.OPTIONAL_CLIENT)
                for e in jar_evs
            )
            if best_bc.confidence >= 0.85 or (best_bc.confidence >= 0.78 and has_client_Mixin_or_dt):
                conf = min(0.95, best_bc.confidence + (0.05 if has_client_Mixin_or_dt else 0.0))
                return (
                    ModSideCategory.CLIENT_ONLY,
                    conf,
                    ConfidenceLevel.HIGH,
                    best_bc.reason,
                )

        # Fall 5: Optional Server / Optional Client Hinweise (z.B. displayTest = IGNORE_SERVER_VERSION)
        opt_srv = [e for e in jar_evs if e.side_hint == ModSideCategory.OPTIONAL_SERVER]
        if opt_srv:
            return (
                ModSideCategory.OPTIONAL_SERVER,
                opt_srv[0].confidence,
                ConfidenceLevel.MEDIUM,
                opt_srv[0].reason,
            )

        # Fall 6: Main/Common Entrypoints oder Common Mixins vorhanden
        common_jar_evs = [
            e for e in jar_evs if e.side_hint == ModSideCategory.BOTH_SIDES_REQUIRED and e.confidence >= 0.75
        ]
        if common_jar_evs:
            best = max(common_jar_evs, key=lambda x: x.confidence)
            return (
                ModSideCategory.BOTH_SIDES_REQUIRED,
                best.confidence,
                ConfidenceLevel.HIGH if best.confidence >= 0.80 else ConfidenceLevel.MEDIUM,
                best.reason,
            )

        # Fall 7: Reine Bibliothek / Coremod / Sprachpaket ohne eigene Entrypoints oder unklare Signale -> UNKNOWN (bleibt auf Server!)
        return (
            ModSideCategory.UNKNOWN,
            0.50,
            ConfidenceLevel.LOW,
            "Keine ausreichenden Beweise für Client-only (Bibliothek/Universal-Mod oder mehrdeutige Signale – verbleibt sicherheitshalber auf dem Server)",
        )

    # ------------------------------------------------------------------
    # Vollständige Modpack-Analyse inkl. Abhängigkeitsgraph (Stufe D)
    # ------------------------------------------------------------------

    def resolve_modpack(
        self,
        mods_dir: Path,
        pack_dir: Optional[Path] = None,
        minecraft_version: Optional[str] = None,
        modloader: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, ModAnalysisResult], None]] = None,
    ) -> Dict[str, Any]:
        """
        Analysiert alle `.jar`-Dateien in `mods_dir`:
          1. Berechnet SHA256/SHA1 aller JAR-Dateien
          2. Ruft gebündelt offizielle Metadaten (Modrinth Batch-API + Pack-Manifeste) ab
          3. Führt für jede JAR die mehrstufige Einzelanalyse (inkl. Cache) durch
          4. Erstellt den vollständigen Abhängigkeitsgraphen (Required, Optional, Embedded, Integration)
             und schützt alle Mods/Bibliotheken, die von mindestens einer Server-Mod benötigt werden
        """
        mods_dir = Path(mods_dir)
        mc_ver = minecraft_version or self.minecraft_version or "unknown"
        loader_ctx = modloader or self.modloader or "unknown"

        if not mods_dir.exists():
            return {
                "total_mods": 0,
                "client_only_mods": [],
                "server_mods": [],
                "results": [],
                "dependency_graph": {},
                "conflicts": [],
            }

        jar_files = sorted(
            [f for f in mods_dir.iterdir() if f.is_file() and f.suffix.lower() == ".jar"],
            key=lambda p: p.name.lower(),
        )
        total_mods = len(jar_files)

        # 1. Manifest-Hinweise aus dem Modpack-Verzeichnis laden
        manifest_hints = OfficialMetadataClient.load_pack_manifest_hints(pack_dir or mods_dir.parent)

        # 2. Hashes berechnen & prüfen, welche JARs bereits im Cache liegen
        sha1_to_path: Dict[str, Path] = {}
        path_to_hashes: Dict[Path, Tuple[str, str]] = {}
        uncached_sha1_map: Dict[str, Path] = {}

        for jar_file in jar_files:
            sha256, sha1 = compute_hashes(jar_file)
            path_to_hashes[jar_file] = (sha256, sha1)
            sha1_to_path[sha1.lower()] = jar_file
            if not self.cache.get(sha256, mc_ver, loader_ctx):
                uncached_sha1_map[sha1.lower()] = jar_file

        # 3. Offizielle Metadaten von Modrinth für nicht-gecachte JARs im Batch abrufen
        modrinth_meta_by_sha1 = self.metadata_client.fetch_modrinth_by_hashes(uncached_sha1_map)

        # 4. Einzelanalyse jeder JAR
        results_by_path: Dict[Path, ModAnalysisResult] = {}
        for idx, jar_file in enumerate(jar_files, start=1):
            _, sha1 = path_to_hashes[jar_file]
            off_meta = modrinth_meta_by_sha1.get(sha1.lower())
            m_hint = manifest_hints.get(jar_file.name.lower())

            res = self.analyze_mod(
                jar_path=jar_file,
                official_meta=off_meta,
                manifest_hint=m_hint,
                minecraft_version=mc_ver,
                modloader=loader_ctx,
            )
            results_by_path[jar_file] = res
            if progress_callback:
                try:
                    progress_callback(idx, total_mods, res)
                except Exception:
                    pass

        # 5. Stufe D: Vollständige Abhängigkeitsgraphen-Auflösung
        self._resolve_dependency_graph(results_by_path)

        all_results = list(results_by_path.values())
        client_only = [r for r in all_results if not r.keep_on_server]
        server_kept = [r for r in all_results if r.keep_on_server]
        all_conflicts = [
            {"mod_id": r.mod_id, "file_name": r.file_name, "conflicts": r.conflicts}
            for r in all_results
            if r.conflicts
        ]

        return {
            "total_mods": total_mods,
            "client_only_count": len(client_only),
            "server_mods_kept_count": len(server_kept),
            "client_only_mods": [r.to_dict() for r in client_only],
            "server_mods": [r.to_dict() for r in server_kept],
            "results": [r.to_dict() for r in all_results],
            "conflicts": all_conflicts,
        }

    def _resolve_dependency_graph(self, results_by_path: Dict[Path, ModAnalysisResult]) -> None:
        """
        Stufe D: Abhängigkeitsanalyse (Abschnitt 4D).
        Erstellt einen vollständigen Abhängigkeitsgraphen über alle Mods im Modpack.
        Wenn Mod A auf dem Server bleibt und Mod/Bibliothek B benötigt (oder als
        Server-Integration für B fungiert), MUSS B ebenfalls auf dem Server verbleiben!
        """
        # Mapping: normalisierte mod_id -> Liste von ModAnalysisResult
        mod_id_map: Dict[str, List[ModAnalysisResult]] = {}
        for res in results_by_path.values():
            for pid in set([res.mod_id] + res.provided_mods):
                norm_id = self._norm_mod_id(pid)
                if norm_id:
                    mod_id_map.setdefault(norm_id, []).append(res)

        # Iterativer Fixpunkt-Algorithmus (schützt transitive Abhängigkeiten beliebiger Tiefe)
        changed = True
        while changed:
            changed = False
            for res in list(results_by_path.values()):
                if not res.keep_on_server:
                    continue

                for dep in res.dependencies:
                    # Wenn eine Abhängigkeit explizit NUR für die CLIENT-Seite deklariert ist (`side = "CLIENT"`),
                    # zwingt sie die Zielmod NICHT auf den Dedicated Server.
                    if dep.side.upper() == "CLIENT":
                        continue

                    # Required Dependencies sowie Integration-Targets schützen
                    # (Wenn eine Server-/Integrationsmod wie `refinedstorage-jei-integration` auf dem Server bleibt,
                    # prüfen wir alle ihre Server/Both-Dependencies).
                    is_integration_mod = "integration" in res.mod_id.lower() or "compat" in res.mod_id.lower() or "addon" in res.mod_id.lower()
                    if dep.dep_type != "required" and not is_integration_mod:
                        continue

                    target_norm = self._norm_mod_id(dep.mod_id)
                    targets = mod_id_map.get(target_norm, [])
                    for target_res in targets:
                        if res.mod_id not in target_res.required_by_server_mods:
                            target_res.required_by_server_mods.append(res.mod_id)

                        if not target_res.keep_on_server:
                            # Mod war als CLIENT_ONLY eingestuft, wird aber von einer Server-Mod benötigt!
                            target_res.side = ModSideCategory.BOTH_SIDES_REQUIRED
                            target_res.keep_on_server = True
                            target_res.primary_reason = (
                                f"Abhängigkeitsschutz: Wird auf dem Server benötigt von {', '.join(target_res.required_by_server_mods)}"
                            )
                            target_res.evidences.append(
                                DetectionEvidence(
                                    source="dependency_graph:required_by_server_mod",
                                    side_hint=ModSideCategory.BOTH_SIDES_REQUIRED,
                                    confidence=0.98,
                                    reason=target_res.primary_reason,
                                    details={"required_by": target_res.required_by_server_mods},
                                )
                            )
                            if "dependency_graph:required_by_server_mod" not in target_res.detection_sources:
                                target_res.detection_sources.append("dependency_graph:required_by_server_mod")
                            changed = True

    @staticmethod
    def _norm_mod_id(mod_id: str) -> str:
        return (mod_id or "").strip().lower().replace("-", "_")

    # ------------------------------------------------------------------
    # Filterung & Verschiebung von Client-only-Mods (Abschnitt 6 & 10)
    # ------------------------------------------------------------------

    def filter_server_mods(
        self,
        server_dir: Path,
        minecraft_version: Optional[str] = None,
        modloader: Optional[str] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[int, int, ModAnalysisResult], None]] = None,
    ) -> Dict[str, Any]:
        """
        Analysiert alle Mods in `server_dir/mods` und verschiebt eindeutig als `CLIENT_ONLY`
        identifizierte Mods sicher nach `server_dir/mods-disabled-client/` (beschädigt niemals Originaldateien).
        Erstellt einen vollständigen Diagnosebericht unter `server_dir/.mod_side_report.json`.
        """
        server_dir = Path(server_dir)
        mods_dir = server_dir / "mods"
        disabled_dir = server_dir / "mods-disabled-client"

        analysis = self.resolve_modpack(
            mods_dir=mods_dir,
            pack_dir=server_dir,
            minecraft_version=minecraft_version,
            modloader=modloader,
            progress_callback=progress_callback,
        )

        moved_mods: List[Dict[str, Any]] = []
        errors: List[str] = []

        if not dry_run and analysis["client_only_mods"]:
            disabled_dir.mkdir(parents=True, exist_ok=True)
            for mod_entry in analysis["client_only_mods"]:
                src_path = Path(mod_entry["file_path"])
                if not src_path.exists():
                    continue
                dst_path = disabled_dir / src_path.name
                try:
                    if dst_path.exists():
                        dst_path.unlink()
                    shutil.move(str(src_path), str(dst_path))
                    moved_mods.append(
                        {
                            "file_name": src_path.name,
                            "mod_id": mod_entry["mod_id"],
                            "mod_name": mod_entry["mod_name"],
                            "mod_version": mod_entry["mod_version"],
                            "side": mod_entry["side"],
                            "confidence": mod_entry["confidence"],
                            "reason": mod_entry["primary_reason"],
                            "detection_sources": mod_entry["detection_sources"],
                        }
                    )
                    logger.info(
                        f"[ModSideResolver] Excluded CLIENT_ONLY mod: {src_path.name} ({mod_entry['primary_reason']})"
                    )
                except Exception as exc:
                    err_msg = f"Fehler beim Verschieben von {src_path.name}: {exc}"
                    logger.warning(err_msg)
                    errors.append(err_msg)

        report = {
            "timestamp": time.time(),
            "resolver_version": RESOLVER_SCHEMA_VERSION,
            "minecraft_version": minecraft_version or self.minecraft_version,
            "modloader": modloader or self.modloader,
            "dry_run": dry_run,
            "total_mods": analysis["total_mods"],
            "client_only_count": analysis["client_only_count"],
            "server_mods_kept_count": analysis["server_mods_kept_count"],
            "moved_count": len(moved_mods),
            "excluded_mods": moved_mods if not dry_run else analysis["client_only_mods"],
            "kept_mods": analysis["server_mods"],
            "conflicts": analysis["conflicts"],
            "errors": errors,
        }

        if not dry_run and server_dir.exists():
            try:
                report_path = server_dir / ".mod_side_report.json"
                report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:
                logger.debug(f"Could not write .mod_side_report.json: {exc}")

        return report

    # ------------------------------------------------------------------
    # Serverpaket-Validierung & Fehler-/Log-Analyse (Abschnitt 4E & 10)
    # ------------------------------------------------------------------

    def validate_server_pack(
        self,
        server_dir: Path,
        expected_minecraft_version: Optional[str] = None,
        expected_modloader: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Überprüft ein erstelltes Server-Modpack auf:
          - Unvollständige Downloads / korrupte JAR-Archive (0 Bytes oder ungültiges ZIP)
          - Doppelte Mods (gleiche `mod_id` mehrfach in `mods/` vorhanden)
          - Fehlende Pflichtabhängigkeiten (`required` Dependencies auf dem Server)
          - Inkompatible Modloader (z.B. reine Fabric-Mod ohne Connector in einem Forge/NeoForge-Pack)
          - Vorhandensein von Konfigurations- und Datapack-Ordnern
        """
        server_dir = Path(server_dir)
        mods_dir = server_dir / "mods"
        exp_loader = (expected_modloader or self.modloader or "unknown").lower()

        corrupted_jars: List[str] = []
        duplicate_mods: List[Dict[str, Any]] = []
        missing_dependencies: List[Dict[str, str]] = []
        incompatible_loader_mods: List[Dict[str, str]] = []

        if not mods_dir.exists():
            return {
                "valid": True,
                "status": "ok",
                "total_server_jars": 0,
                "corrupted_jars": [],
                "duplicate_mods": [],
                "missing_dependencies": [],
                "incompatible_loader_mods": [],
                "warnings": ["Kein mods-Verzeichnis vorhanden"],
            }

        jar_files = sorted(
            [f for f in mods_dir.iterdir() if f.is_file() and f.suffix.lower() == ".jar"],
            key=lambda p: p.name.lower(),
        )

        mod_id_to_files: Dict[str, List[str]] = {}
        installed_mod_ids: Set[str] = set(_SYSTEM_DEP_IDS)
        inspected_by_file: Dict[str, Dict[str, Any]] = {}

        # Prüfe ob Sinytra Connector / Forgified Fabric API installiert ist (erlaubt Fabric-Mods auf NeoForge/Forge)
        has_connector = False

        for jf in jar_files:
            if jf.stat().st_size == 0 or not zipfile.is_zipfile(jf):
                corrupted_jars.append(jf.name)
                continue

            info = inspect_jar_metadata(jf)
            inspected_by_file[jf.name] = info
            mid = self._norm_mod_id(info.get("mod_id", ""))
            if mid in ("connector", "sinytra_connector", "forgified_fabric_api"):
                has_connector = True

            if mid and info.get("has_mod_descriptor"):
                mod_id_to_files.setdefault(mid, []).append(jf.name)

            for provided in info.get("provided_mods", []):
                installed_mod_ids.add(self._norm_mod_id(provided))

        # 1. Doppelte Mods erkennen
        for mid, files in mod_id_to_files.items():
            if len(files) > 1:
                duplicate_mods.append({"mod_id": mid, "files": files})

        # 2. Fehlende Pflichtabhängigkeiten & Loader-Kompatibilität prüfen
        for jf_name, info in inspected_by_file.items():
            mod_loader = (info.get("loader") or "unknown").lower()
            if (
                exp_loader in ("neoforge", "forge")
                and mod_loader == "fabric"
                and not has_connector
                # Manche JARs haben sowohl neoforge.mods.toml als auch fabric.mod.json;
                # inspect_jar_metadata setzt `loader = "neoforge"` wenn neoforge.mods.toml existiert.
            ):
                incompatible_loader_mods.append(
                    {
                        "file": jf_name,
                        "mod_id": info.get("mod_id", ""),
                        "detected_loader": mod_loader,
                        "expected_loader": exp_loader,
                    }
                )

            for dep in info.get("dependencies", []):
                if dep.dep_type != "required" or dep.side.upper() == "CLIENT":
                    continue
                dep_norm = self._norm_mod_id(dep.mod_id)
                if dep_norm not in installed_mod_ids and not dep_norm.startswith("fabric_"):
                    missing_dependencies.append(
                        {
                            "mod_id": info.get("mod_id", jf_name),
                            "file": jf_name,
                            "missing_dependency": dep.mod_id,
                            "version_range": dep.version_range,
                        }
                    )

        is_valid = len(corrupted_jars) == 0 and len(missing_dependencies) == 0
        return {
            "valid": is_valid,
            "status": "valid" if is_valid else "warnings_found",
            "total_server_jars": len(jar_files),
            "corrupted_jars": corrupted_jars,
            "duplicate_mods": duplicate_mods,
            "missing_dependencies": missing_dependencies,
            "incompatible_loader_mods": incompatible_loader_mods,
        }

    @staticmethod
    def analyze_server_crash_log(log_text: str) -> Dict[str, Any]:
        """
        Stufe E: Automatische Fehleranalyse aus Server-Logs / Crash-Reports (Abschnitt 4E).
        Unterscheidet streng zwischen:
          1. Echten Client-Klassen-Fehlern auf dem Dedicated Server (`NoClassDefFoundError: net/minecraft/client/...`,
             `Attempted to load class net/minecraft/client/... for invalid dist DEDICATED_SERVER`,
             `Cannot load class ... in environment type SERVER`)
          2. Fehlenden Abhängigkeiten (`Missing or unsupported mandatory dependencies`), die NIEMALS
             als Beweis für eine Client-only-Mod gewertet werden dürfen!
        """
        if not log_text:
            return {"client_crash_mods": [], "missing_dependency_errors": []}

        client_crash_mods: Set[str] = set()
        missing_deps: List[Dict[str, str]] = []

        # 1. Fehlende Dependencies erkennen (dürfen NICHT als Client-only entfernt werden!)
        for match in re.finditer(
            r"Mod ID:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?,\s*Requested by:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?",
            log_text,
            re.IGNORECASE,
        ):
            missing_deps.append({"missing_mod": match.group(1), "requested_by": match.group(2)})

        # 2. Echte Dedicated-Server Client-Classloading-Crashes erkennen
        # NeoForge/Forge: "Mod File: /.../mods/Foo.jar" + "Attempted to load class net/minecraft/client/..."
        lines = log_text.splitlines()
        for idx, line in enumerate(lines):
            if any(
                pat in line
                for pat in (
                    "Attempted to load class net/minecraft/client/",
                    "Attempted to load class com/mojang/blaze3d/",
                    "java.lang.NoClassDefFoundError: net/minecraft/client/",
                    "java.lang.ClassNotFoundException: net.minecraft.client.",
                    "for invalid dist DEDICATED_SERVER",
                    "in environment type SERVER",
                )
            ):
                # Suche im umliegenden Stacktrace/Kontext nach einem expliziten Mod-JAR-Namen oder Mod-ID
                window = "\n".join(lines[max(0, idx - 15) : min(len(lines), idx + 25)])
                for jar_match in re.finditer(r"([A-Za-z0-9_.+-]+\.jar)", window):
                    jar_name = jar_match.group(1)
                    if not any(
                        sys_jar in jar_name.lower()
                        for sys_jar in ("neoforge-", "forge-", "server-", "minecraft-", "fabric-loader")
                    ):
                        client_crash_mods.add(jar_name)

        return {
            "client_crash_mods": sorted(client_crash_mods),
            "missing_dependency_errors": missing_deps,
        }

    # ------------------------------------------------------------------
    # Hilfsmethode zum Rehydrieren aus dem Cache
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_result(data: Dict[str, Any], jar_path: Path, from_cache: bool = True) -> ModAnalysisResult:
        side_str = data.get("side") or data.get("classification") or "UNKNOWN"
        try:
            side = ModSideCategory(side_str)
        except ValueError:
            side = ModSideCategory.UNKNOWN

        conf_lvl_str = data.get("confidence_level") or "MEDIUM"
        try:
            conf_lvl = ConfidenceLevel(conf_lvl_str)
        except ValueError:
            conf_lvl = ConfidenceLevel.MEDIUM

        evidences = [
            DetectionEvidence(
                source=e.get("source", "cache"),
                side_hint=ModSideCategory(e.get("side_hint", "UNKNOWN")),
                confidence=float(e.get("confidence", 0.5)),
                reason=e.get("reason", ""),
                details=e.get("details", {}),
            )
            for e in data.get("evidences", [])
            if isinstance(e, dict)
        ]

        deps = [
            ModDependencyRef(
                mod_id=d.get("mod_id", ""),
                dep_type=d.get("dep_type", "required"),
                side=d.get("side", "BOTH"),
                version_range=d.get("version_range", "*"),
            )
            for d in data.get("dependencies", [])
            if isinstance(d, dict)
        ]

        return ModAnalysisResult(
            file_path=str(jar_path),
            file_name=jar_path.name,
            sha256=data.get("sha256", ""),
            mod_id=data.get("mod_id", jar_path.stem.lower()),
            mod_name=data.get("mod_name", jar_path.stem),
            mod_version=data.get("mod_version", "unknown"),
            minecraft_version=data.get("minecraft_version", "unknown"),
            modloader=data.get("modloader", "unknown"),
            side=side,
            confidence=float(data.get("confidence", 0.5)),
            confidence_level=conf_lvl,
            keep_on_server=side != ModSideCategory.CLIENT_ONLY,
            primary_reason=data.get("primary_reason", ""),
            detection_sources=data.get("detection_sources", []),
            evidences=evidences,
            dependencies=deps,
            provided_mods=data.get("provided_mods", []),
            required_by_server_mods=data.get("required_by_server_mods", []),
            conflicts=data.get("conflicts", []),
            from_cache=from_cache,
            jar_details=data.get("jar_details", {}),
            bytecode_details=data.get("bytecode_details", {}),
            official_metadata=data.get("official_metadata", {}),
        )
