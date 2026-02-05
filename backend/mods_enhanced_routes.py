"""
Enhanced Modpack Features
Mod update checker, dependency resolver, client modpack generator, version rollback, conflict detection
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import zipfile
import json
import requests
import shutil
import hashlib

from database import get_db
from models import ModVersion, ModConflict, ClientModpack, User
from auth import require_auth, require_moderator
from config import SERVERS_ROOT

router = APIRouter(prefix="/mods-enhanced", tags=["mods_enhanced"])


# ==================== Request/Response Models ====================

class ModVersionResponse(BaseModel):
    id: int
    server_name: str
    mod_name: str
    current_version: str
    latest_version: Optional[str]
    update_available: bool
    mod_source: str
    minecraft_version: Optional[str]
    
    class Config:
        from_attributes = True


class ModConflictResponse(BaseModel):
    id: int
    server_name: str
    mod_a: str
    mod_b: str
    conflict_type: str
    severity: str
    description: Optional[str]
    
    class Config:
        from_attributes = True


class ClientModpackResponse(BaseModel):
    id: int
    server_name: str
    version: str
    file_path: str
    file_size: int
    mod_count: int
    generated_at: datetime
    download_count: int
    
    class Config:
        from_attributes = True


class ModUpdateRequest(BaseModel):
    mod_ids: List[int]  # List of ModVersion IDs to update


class ClientModpackRequest(BaseModel):
    server_name: str
    version: str
    include_config: bool = True
    include_resourcepacks: bool = False


# ==================== Mod Scanning ====================

def _scan_mod_file(mod_path: Path) -> Dict[str, Any]:
    """Extract metadata from a mod JAR file"""
    
    metadata = {
        'file_name': mod_path.name,
        'mod_id': None,
        'mod_name': None,
        'version': None,
        'minecraft_version': None,
        'loader': None,
        'dependencies': [],
        'environment': 'both',  # client, server, both
    }
    
    try:
        with zipfile.ZipFile(mod_path, 'r') as zf:
            # Fabric mod
            if 'fabric.mod.json' in zf.namelist():
                data = json.loads(zf.read('fabric.mod.json').decode('utf-8', errors='ignore'))
                metadata['mod_id'] = data.get('id')
                metadata['mod_name'] = data.get('name', metadata['mod_id'])
                metadata['version'] = data.get('version')
                metadata['loader'] = 'fabric'
                metadata['environment'] = data.get('environment', 'both')
                
                # Dependencies
                depends = data.get('depends', {})
                for dep_id, dep_version in depends.items():
                    if dep_id not in ['minecraft', 'fabricloader', 'java']:
                        metadata['dependencies'].append({'id': dep_id, 'version': dep_version})
                
                # Minecraft version
                mc_dep = depends.get('minecraft', '')
                if isinstance(mc_dep, str):
                    metadata['minecraft_version'] = mc_dep.replace('>=', '').replace('~', '').split()[0]
            
            # Quilt mod
            elif 'quilt.mod.json' in zf.namelist():
                data = json.loads(zf.read('quilt.mod.json').decode('utf-8', errors='ignore'))
                metadata['mod_id'] = data.get('quilt_loader', {}).get('id')
                metadata['mod_name'] = data.get('quilt_loader', {}).get('metadata', {}).get('name', metadata['mod_id'])
                metadata['version'] = data.get('quilt_loader', {}).get('version')
                metadata['loader'] = 'quilt'
            
            # Forge/NeoForge mod
            elif 'META-INF/mods.toml' in zf.namelist():
                content = zf.read('META-INF/mods.toml').decode('utf-8', errors='ignore')
                metadata['loader'] = 'forge'
                
                # Parse TOML (simple approach)
                for line in content.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        
                        if key == 'modId':
                            metadata['mod_id'] = value
                        elif key == 'displayName':
                            metadata['mod_name'] = value
                        elif key == 'version':
                            metadata['version'] = value
            
            # NeoForge mod
            elif 'META-INF/neoforge.mods.toml' in zf.namelist():
                content = zf.read('META-INF/neoforge.mods.toml').decode('utf-8', errors='ignore')
                metadata['loader'] = 'neoforge'
                
                for line in content.split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        
                        if key == 'modId':
                            metadata['mod_id'] = value
                        elif key == 'displayName':
                            metadata['mod_name'] = value
                        elif key == 'version':
                            metadata['version'] = value
    
    except Exception as e:
        print(f"Error scanning mod {mod_path.name}: {e}")
    
    # Fallback to filename if no metadata found
    if not metadata['mod_name']:
        metadata['mod_name'] = mod_path.stem
    if not metadata['mod_id']:
        metadata['mod_id'] = mod_path.stem.lower().replace(' ', '_')
    
    return metadata


@router.post("/scan/{server_name}")
async def scan_server_mods(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Scan all mods in a server and update database"""
    
    server_path = SERVERS_ROOT / server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    mods_dir = server_path / "mods"
    if not mods_dir.exists():
        return {"message": "No mods directory found", "scanned": 0}
    
    scanned = 0
    updated = 0
    
    for mod_file in mods_dir.glob("*.jar"):
        metadata = _scan_mod_file(mod_file)
        
        # Check if mod already exists in database
        existing = db.query(ModVersion).filter(
            ModVersion.server_name == server_name,
            ModVersion.file_name == metadata['file_name']
        ).first()
        
        if existing:
            # Update existing
            existing.mod_name = metadata['mod_name']
            existing.current_version = metadata['version'] or 'unknown'
            existing.mod_loader = metadata['loader']
            existing.minecraft_version = metadata['minecraft_version']
            existing.dependencies = metadata['dependencies']
            updated += 1
        else:
            # Create new
            mod = ModVersion(
                server_name=server_name,
                mod_id=metadata['mod_id'],
                mod_name=metadata['mod_name'],
                current_version=metadata['version'] or 'unknown',
                mod_source='manual',
                file_name=metadata['file_name'],
                mod_loader=metadata['loader'],
                minecraft_version=metadata['minecraft_version'],
                dependencies=metadata['dependencies']
            )
            db.add(mod)
        
        scanned += 1
    
    db.commit()
    
    return {
        "message": f"Scanned {scanned} mods",
        "scanned": scanned,
        "updated": updated,
        "new": scanned - updated
    }


# ==================== Update Checker ====================

def _check_modrinth_updates(mod_id: str, current_version: str, minecraft_version: str) -> Optional[str]:
    """Check Modrinth for mod updates"""
    try:
        # Search for project
        url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
        params = {
            'game_versions': f'["{minecraft_version}"]',
            'loaders': '["fabric","forge","neoforge"]'
        }
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            versions = resp.json()
            if versions:
                latest = versions[0]['version_number']
                return latest if latest != current_version else None
    except Exception as e:
        print(f"Error checking Modrinth updates for {mod_id}: {e}")
    
    return None


def _check_curseforge_updates(mod_id: str, current_version: str, minecraft_version: str) -> Optional[str]:
    """Check CurseForge for mod updates"""
    try:
        # Would need CF API key for this
        # Placeholder for now
        pass
    except Exception:
        pass
    
    return None


@router.post("/check-updates/{server_name}")
async def check_mod_updates(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Check for available updates for all mods"""
    
    mods = db.query(ModVersion).filter(ModVersion.server_name == server_name).all()
    
    if not mods:
        return {"message": "No mods found. Run scan first.", "checked": 0}
    
    updates_found = 0
    
    for mod in mods:
        latest_version = None
        
        # Try Modrinth first
        if mod.minecraft_version:
            latest_version = _check_modrinth_updates(
                mod.mod_id,
                mod.current_version,
                mod.minecraft_version
            )
        
        # Try CurseForge if Modrinth didn't work
        if not latest_version and mod.minecraft_version:
            latest_version = _check_curseforge_updates(
                mod.mod_id,
                mod.current_version,
                mod.minecraft_version
            )
        
        if latest_version:
            mod.latest_version = latest_version
            mod.update_available = True
            mod.last_checked = datetime.utcnow()
            updates_found += 1
        else:
            mod.latest_version = mod.current_version
            mod.update_available = False
            mod.last_checked = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": f"Checked {len(mods)} mods",
        "checked": len(mods),
        "updates_available": updates_found
    }


@router.get("/updates/{server_name}", response_model=List[ModVersionResponse])
async def get_available_updates(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get list of mods with available updates"""
    
    mods = db.query(ModVersion).filter(
        ModVersion.server_name == server_name,
        ModVersion.update_available == True
    ).all()
    
    return [ModVersionResponse.model_validate(m) for m in mods]


@router.get("/mods/{server_name}", response_model=List[ModVersionResponse])
async def list_server_mods(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List all tracked mods for a server"""
    
    mods = db.query(ModVersion).filter(ModVersion.server_name == server_name).all()
    
    return [ModVersionResponse.model_validate(m) for m in mods]


# ==================== Dependency Resolver ====================

@router.post("/resolve-dependencies/{server_name}")
async def resolve_dependencies(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Check for missing mod dependencies"""
    
    mods = db.query(ModVersion).filter(ModVersion.server_name == server_name).all()
    
    installed_mod_ids = {mod.mod_id for mod in mods}
    missing_deps = {}
    
    for mod in mods:
        if not mod.dependencies:
            continue
        
        for dep in mod.dependencies:
            dep_id = dep.get('id')
            if dep_id and dep_id not in installed_mod_ids:
                if dep_id not in missing_deps:
                    missing_deps[dep_id] = {
                        'dependency_id': dep_id,
                        'required_by': [],
                        'version': dep.get('version', 'any')
                    }
                missing_deps[dep_id]['required_by'].append(mod.mod_name)
    
    return {
        "message": f"Found {len(missing_deps)} missing dependencies",
        "missing_dependencies": list(missing_deps.values())
    }


# ==================== Conflict Detection ====================

@router.post("/detect-conflicts/{server_name}")
async def detect_mod_conflicts(
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Detect potential mod conflicts"""
    
    mods = db.query(ModVersion).filter(ModVersion.server_name == server_name).all()
    
    # Clear old conflicts
    db.query(ModConflict).filter(ModConflict.server_name == server_name).delete()
    
    conflicts_found = 0
    
    # Check for duplicate mod IDs
    mod_id_map = {}
    for mod in mods:
        if mod.mod_id in mod_id_map:
            conflict = ModConflict(
                server_name=server_name,
                mod_a=mod_id_map[mod.mod_id].mod_name,
                mod_b=mod.mod_name,
                conflict_type='duplicate',
                severity='critical',
                description=f'Both mods have the same mod ID: {mod.mod_id}'
            )
            db.add(conflict)
            conflicts_found += 1
        else:
            mod_id_map[mod.mod_id] = mod
    
    # Check for incompatible loaders
    loaders = {mod.mod_loader for mod in mods if mod.mod_loader}
    if 'fabric' in loaders and 'forge' in loaders:
        conflict = ModConflict(
            server_name=server_name,
            mod_a='Fabric mods',
            mod_b='Forge mods',
            conflict_type='incompatible',
            severity='critical',
            description='Cannot mix Fabric and Forge mods in the same server'
        )
        db.add(conflict)
        conflicts_found += 1
    
    # Check for version mismatches
    mc_versions = {mod.minecraft_version for mod in mods if mod.minecraft_version}
    if len(mc_versions) > 1:
        conflict = ModConflict(
            server_name=server_name,
            mod_a='Various mods',
            mod_b='Server',
            conflict_type='version_mismatch',
            severity='warning',
            description=f'Mods target different Minecraft versions: {", ".join(sorted(mc_versions))}'
        )
        db.add(conflict)
        conflicts_found += 1
    
    db.commit()
    
    return {
        "message": f"Detected {conflicts_found} conflicts",
        "conflicts_found": conflicts_found
    }


@router.get("/conflicts/{server_name}", response_model=List[ModConflictResponse])
async def get_mod_conflicts(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get list of detected mod conflicts"""
    
    conflicts = db.query(ModConflict).filter(
        ModConflict.server_name == server_name,
        ModConflict.resolved == False
    ).all()
    
    return [ModConflictResponse.model_validate(c) for c in conflicts]


# ==================== Client Modpack Generator ====================

@router.post("/generate-client-modpack", response_model=ClientModpackResponse)
async def generate_client_modpack(
    request: ClientModpackRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Generate a client modpack ZIP for players"""
    
    server_path = SERVERS_ROOT / request.server_name
    if not server_path.exists():
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Create temporary directory for client pack
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Copy mods (excluding server-only mods)
        mods_src = server_path / "mods"
        mods_dst = temp_path / "mods"
        mod_count = 0
        
        if mods_src.exists():
            mods_dst.mkdir(parents=True)
            for mod_file in mods_src.glob("*.jar"):
                # Check if server-only
                metadata = _scan_mod_file(mod_file)
                if metadata['environment'] in ['both', 'client']:
                    shutil.copy2(mod_file, mods_dst / mod_file.name)
                    mod_count += 1
        
        # Copy config if requested
        if request.include_config:
            config_src = server_path / "config"
            if config_src.exists():
                shutil.copytree(config_src, temp_path / "config")
        
        # Copy resourcepacks if requested
        if request.include_resourcepacks:
            rp_src = server_path / "resourcepacks"
            if rp_src.exists():
                shutil.copytree(rp_src, temp_path / "resourcepacks")
        
        # Create modpack metadata
        metadata_file = temp_path / "modpack-info.json"
        metadata = {
            "name": f"{request.server_name} Client Pack",
            "version": request.version,
            "generated_at": datetime.utcnow().isoformat(),
            "mod_count": mod_count,
        }
        metadata_file.write_text(json.dumps(metadata, indent=2))
        
        # Create README
        readme = temp_path / "README.txt"
        readme.write_text(f"""
{request.server_name} Client Modpack
Version: {request.version}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}

Installation:
1. Install the appropriate mod loader (Fabric/Forge/NeoForge)
2. Copy the 'mods' folder to your .minecraft directory
3. Copy the 'config' folder if included
4. Launch the game!

Mod count: {mod_count}
        """.strip())
        
        # Create ZIP archive
        output_dir = SERVERS_ROOT.parent / "client-modpacks" / request.server_name
        output_dir.mkdir(parents=True, exist_ok=True)
        
        zip_name = f"{request.server_name}-client-{request.version}.zip"
        zip_path = output_dir / zip_name
        
        shutil.make_archive(
            str(zip_path.with_suffix('')),
            'zip',
            str(temp_path)
        )
        
        file_size = zip_path.stat().st_size
    
    # Save to database
    client_pack = ClientModpack(
        server_name=request.server_name,
        version=request.version,
        file_path=str(zip_path),
        file_size=file_size,
        mod_count=mod_count,
        generated_by=current_user.id
    )
    
    db.add(client_pack)
    db.commit()
    db.refresh(client_pack)
    
    return ClientModpackResponse.model_validate(client_pack)


@router.get("/client-modpacks/{server_name}", response_model=List[ClientModpackResponse])
async def list_client_modpacks(
    server_name: str,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List all generated client modpacks for a server"""
    
    packs = db.query(ClientModpack).filter(
        ClientModpack.server_name == server_name
    ).order_by(ClientModpack.generated_at.desc()).all()
    
    return [ClientModpackResponse.model_validate(p) for p in packs]
