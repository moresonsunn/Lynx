"""
Configuration Management System
Visual editor, templates, comparison, validation, world seed generator
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from pathlib import Path
import json
import re
import random
import difflib

from database import get_db
from models import User
from auth import require_auth, require_moderator
from config import SERVERS_ROOT

router = APIRouter(prefix="/config-management", tags=["config_management"])


# ==================== Request/Response Models ====================

class ServerProperty(BaseModel):
    key: str
    value: Union[str, int, bool]
    type: str  # string, integer, boolean
    description: Optional[str] = None
    validation_rule: Optional[str] = None


class ServerPropertiesConfig(BaseModel):
    properties: Dict[str, ServerProperty]


class ConfigTemplate(BaseModel):
    name: str
    description: str
    category: str  # survival, creative, pvp, modded, minigame
    icon: Optional[str] = "⚙️"
    properties: Dict[str, Any]


class ConfigComparisonRequest(BaseModel):
    server_a: str
    server_b: str


class ValidationRule(BaseModel):
    property_key: str
    rule_type: str  # range, enum, regex, custom
    parameters: Dict[str, Any]
    error_message: str


# ==================== Server Properties Schema ====================

PROPERTY_SCHEMA = {
    # World Settings
    'level-name': {
        'type': 'string',
        'description': 'Name of the world folder',
        'default': 'world',
        'category': 'World'
    },
    'level-seed': {
        'type': 'string',
        'description': 'World generation seed',
        'default': '',
        'category': 'World'
    },
    'level-type': {
        'type': 'enum',
        'description': 'World generation type',
        'default': 'default',
        'options': ['default', 'flat', 'largeBiomes', 'amplified'],
        'category': 'World'
    },
    'generator-settings': {
        'type': 'string',
        'description': 'Settings for flat or custom world generation',
        'default': '',
        'category': 'World'
    },
    'max-world-size': {
        'type': 'integer',
        'description': 'Maximum world radius in blocks',
        'default': 29999984,
        'min': 1,
        'max': 29999984,
        'category': 'World'
    },
    
    # Server Settings
    'server-port': {
        'type': 'integer',
        'description': 'Server port',
        'default': 25565,
        'min': 1,
        'max': 65535,
        'category': 'Server'
    },
    'server-ip': {
        'type': 'string',
        'description': 'IP address to bind to',
        'default': '',
        'category': 'Server'
    },
    'motd': {
        'type': 'string',
        'description': 'Message of the day',
        'default': 'A Minecraft Server',
        'category': 'Server'
    },
    'max-players': {
        'type': 'integer',
        'description': 'Maximum players',
        'default': 20,
        'min': 1,
        'max': 2147483647,
        'category': 'Server'
    },
    'online-mode': {
        'type': 'boolean',
        'description': 'Verify player authentication',
        'default': True,
        'category': 'Server'
    },
    'white-list': {
        'type': 'boolean',
        'description': 'Enable whitelist',
        'default': False,
        'category': 'Server'
    },
    'enforce-whitelist': {
        'type': 'boolean',
        'description': 'Kick non-whitelisted players',
        'default': False,
        'category': 'Server'
    },
    
    # Gameplay
    'gamemode': {
        'type': 'enum',
        'description': 'Default game mode',
        'default': 'survival',
        'options': ['survival', 'creative', 'adventure', 'spectator'],
        'category': 'Gameplay'
    },
    'difficulty': {
        'type': 'enum',
        'description': 'World difficulty',
        'default': 'easy',
        'options': ['peaceful', 'easy', 'normal', 'hard'],
        'category': 'Gameplay'
    },
    'hardcore': {
        'type': 'boolean',
        'description': 'Hardcore mode',
        'default': False,
        'category': 'Gameplay'
    },
    'pvp': {
        'type': 'boolean',
        'description': 'Allow PvP',
        'default': True,
        'category': 'Gameplay'
    },
    'allow-flight': {
        'type': 'boolean',
        'description': 'Allow flight in survival',
        'default': False,
        'category': 'Gameplay'
    },
    'allow-nether': {
        'type': 'boolean',
        'description': 'Enable Nether',
        'default': True,
        'category': 'Gameplay'
    },
    
    # Performance
    'view-distance': {
        'type': 'integer',
        'description': 'View distance in chunks',
        'default': 10,
        'min': 3,
        'max': 32,
        'category': 'Performance'
    },
    'simulation-distance': {
        'type': 'integer',
        'description': 'Simulation distance in chunks',
        'default': 10,
        'min': 3,
        'max': 32,
        'category': 'Performance'
    },
    'max-tick-time': {
        'type': 'integer',
        'description': 'Max tick time before watchdog',
        'default': 60000,
        'category': 'Performance'
    },
    'spawn-protection': {
        'type': 'integer',
        'description': 'Spawn protection radius',
        'default': 16,
        'min': 0,
        'category': 'Performance'
    }
}


# ==================== Configuration Templates ====================

CONFIG_TEMPLATES = [
    {
        'name': 'Vanilla Survival',
        'description': 'Standard survival experience',
        'category': 'survival',
        'icon': '⛏️',
        'properties': {
            'gamemode': 'survival',
            'difficulty': 'normal',
            'pvp': True,
            'hardcore': False,
            'max-players': 20,
            'view-distance': 10
        }
    },
    {
        'name': 'Creative Build',
        'description': 'Creative mode for building',
        'category': 'creative',
        'icon': '🏗️',
        'properties': {
            'gamemode': 'creative',
            'difficulty': 'peaceful',
            'pvp': False,
            'allow-flight': True,
            'max-players': 20,
            'view-distance': 15
        }
    },
    {
        'name': 'PvP Arena',
        'description': 'PvP focused server',
        'category': 'pvp',
        'icon': '⚔️',
        'properties': {
            'gamemode': 'survival',
            'difficulty': 'hard',
            'pvp': True,
            'hardcore': False,
            'spawn-protection': 0,
            'max-players': 50,
            'view-distance': 8
        }
    },
    {
        'name': 'Hardcore Survival',
        'description': 'Hardcore mode challenge',
        'category': 'survival',
        'icon': '💀',
        'properties': {
            'gamemode': 'survival',
            'difficulty': 'hard',
            'hardcore': True,
            'pvp': True,
            'max-players': 10,
            'view-distance': 10
        }
    },
    {
        'name': 'Skyblock',
        'description': 'Skyblock challenge',
        'category': 'minigame',
        'icon': '☁️',
        'properties': {
            'gamemode': 'survival',
            'difficulty': 'normal',
            'level-type': 'flat',
            'generator-settings': '{"layers":[{"block":"air","height":1}],"biome":"plains"}',
            'spawn-protection': 5
        }
    },
    {
        'name': 'High Performance',
        'description': 'Optimized for performance',
        'category': 'modded',
        'icon': '🚀',
        'properties': {
            'view-distance': 6,
            'simulation-distance': 6,
            'max-players': 100,
            'spawn-protection': 0
        }
    }
]


# ==================== Visual Editor ====================

@router.get("/properties/{server_name}")
async def get_server_properties(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    """Get server.properties with schema for visual editing"""
    
    server_path = SERVERS_ROOT / server_name
    props_file = server_path / "server.properties"
    
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties not found")
    
    # Parse properties file
    properties = {}
    content = props_file.read_text(encoding='utf-8', errors='ignore')
    
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            # Get schema info
            schema = PROPERTY_SCHEMA.get(key, {
                'type': 'string',
                'description': key,
                'category': 'Other'
            })
            
            # Convert value based on type
            if schema['type'] == 'boolean':
                value = value.lower() == 'true'
            elif schema['type'] == 'integer':
                try:
                    value = int(value)
                except:
                    value = 0
            
            properties[key] = {
                'value': value,
                'schema': schema
            }
    
    # Group by category
    categorized = {}
    for key, prop in properties.items():
        category = prop['schema'].get('category', 'Other')
        if category not in categorized:
            categorized[category] = {}
        categorized[category][key] = prop
    
    return {
        'server_name': server_name,
        'properties': properties,
        'categorized': categorized,
        'schema': PROPERTY_SCHEMA
    }


@router.post("/properties/{server_name}")
async def update_server_properties(
    server_name: str,
    properties: Dict[str, Any],
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Update server.properties with validation"""
    
    server_path = SERVERS_ROOT / server_name
    props_file = server_path / "server.properties"
    
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties not found")
    
    # Validate properties
    errors = _validate_properties(properties)
    if errors:
        return {'success': False, 'errors': errors}
    
    # Read existing file
    content = props_file.read_text(encoding='utf-8', errors='ignore')
    lines = content.split('\n')
    
    # Update properties
    new_lines = []
    updated_keys = set()
    
    for line in lines:
        if line.strip() and not line.strip().startswith('#') and '=' in line:
            key = line.split('=', 1)[0].strip()
            if key in properties:
                # Update value
                value = properties[key]
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                new_lines.append(f"{key}={value}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    # Add new properties
    for key, value in properties.items():
        if key not in updated_keys:
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            new_lines.append(f"{key}={value}")
    
    # Write back
    backup_file = props_file.with_suffix('.properties.bak')
    props_file.rename(backup_file)
    
    try:
        props_file.write_text('\n'.join(new_lines), encoding='utf-8')
        
        # Log action
        from models import AuditLog
        log = AuditLog(
            user_id=current_user.id,
            action='update_server_properties',
            resource_type='server',
            resource_id=server_name,
            details={'properties_updated': list(properties.keys())}
        )
        db.add(log)
        db.commit()
        
        return {'success': True, 'message': 'Properties updated'}
    
    except Exception as e:
        # Restore backup on error
        backup_file.rename(props_file)
        raise HTTPException(status_code=500, detail=f"Failed to update properties: {str(e)}")


def _validate_properties(properties: Dict[str, Any]) -> List[Dict[str, str]]:
    """Validate properties against schema"""
    
    errors = []
    
    for key, value in properties.items():
        schema = PROPERTY_SCHEMA.get(key)
        if not schema:
            continue
        
        # Type validation
        if schema['type'] == 'integer':
            if not isinstance(value, int):
                errors.append({'property': key, 'error': 'Must be an integer'})
                continue
            
            # Range validation
            if 'min' in schema and value < schema['min']:
                errors.append({'property': key, 'error': f"Must be >= {schema['min']}"})
            if 'max' in schema and value > schema['max']:
                errors.append({'property': key, 'error': f"Must be <= {schema['max']}"})
        
        elif schema['type'] == 'boolean':
            if not isinstance(value, bool):
                errors.append({'property': key, 'error': 'Must be true or false'})
        
        elif schema['type'] == 'enum':
            if value not in schema.get('options', []):
                errors.append({'property': key, 'error': f"Must be one of: {', '.join(schema['options'])}"})
    
    return errors


# ==================== Configuration Templates ====================

@router.get("/templates")
async def list_config_templates(
    category: Optional[str] = None,
    current_user: User = Depends(require_auth)
):
    """List available configuration templates"""
    
    templates = CONFIG_TEMPLATES
    
    if category:
        templates = [t for t in templates if t['category'] == category]
    
    return {'templates': templates}


@router.post("/templates/apply/{server_name}")
async def apply_config_template(
    server_name: str,
    template_name: str,
    merge: bool = True,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Apply a configuration template to a server"""
    
    # Find template
    template = next((t for t in CONFIG_TEMPLATES if t['name'] == template_name), None)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    server_path = SERVERS_ROOT / server_name
    props_file = server_path / "server.properties"
    
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties not found")
    
    if merge:
        # Merge with existing properties
        content = props_file.read_text(encoding='utf-8', errors='ignore')
        existing = {}
        for line in content.split('\n'):
            if line.strip() and not line.strip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                existing[key.strip()] = value.strip()
        
        # Merge template properties
        existing.update(template['properties'])
        properties = existing
    else:
        # Use template properties only
        properties = template['properties']
    
    # Apply properties
    result = await update_server_properties(server_name, properties, current_user, db)
    
    return {
        'success': result.get('success', True),
        'template_applied': template_name,
        'properties_set': len(template['properties'])
    }


# ==================== Configuration Comparison ====================

@router.post("/compare")
async def compare_configs(
    request: ConfigComparisonRequest,
    current_user: User = Depends(require_auth)
):
    """Compare server.properties between two servers"""
    
    server_a_path = SERVERS_ROOT / request.server_a / "server.properties"
    server_b_path = SERVERS_ROOT / request.server_b / "server.properties"
    
    if not server_a_path.exists() or not server_b_path.exists():
        raise HTTPException(status_code=404, detail="One or both servers not found")
    
    # Read both files
    props_a = _parse_properties(server_a_path.read_text(encoding='utf-8', errors='ignore'))
    props_b = _parse_properties(server_b_path.read_text(encoding='utf-8', errors='ignore'))
    
    # Find differences
    all_keys = set(props_a.keys()) | set(props_b.keys())
    
    differences = []
    same = []
    
    for key in sorted(all_keys):
        val_a = props_a.get(key)
        val_b = props_b.get(key)
        
        if val_a != val_b:
            differences.append({
                'property': key,
                'server_a_value': val_a,
                'server_b_value': val_b,
                'status': 'different'
            })
        else:
            same.append({
                'property': key,
                'value': val_a
            })
    
    # Generate diff text
    lines_a = server_a_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    lines_b = server_b_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    
    diff_html = list(difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=request.server_a,
        tofile=request.server_b,
        lineterm=''
    ))
    
    return {
        'server_a': request.server_a,
        'server_b': request.server_b,
        'differences': differences,
        'same_properties': same,
        'diff_count': len(differences),
        'diff_text': '\n'.join(diff_html)
    }


def _parse_properties(content: str) -> Dict[str, str]:
    """Parse properties file into dict"""
    
    properties = {}
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            properties[key.strip()] = value.strip()
    
    return properties


# ==================== World Seed Generator ====================

@router.get("/seed/generate")
async def generate_world_seed(
    seed_type: str = "random",  # random, numeric, text
    current_user: User = Depends(require_auth)
):
    """Generate Minecraft world seeds"""
    
    if seed_type == "random":
        # Generate random numeric seed
        seed = random.randint(-9223372036854775808, 9223372036854775807)
        return {'seed': str(seed), 'type': 'random'}
    
    elif seed_type == "numeric":
        # Generate smaller numeric seed
        seed = random.randint(1000000, 999999999)
        return {'seed': str(seed), 'type': 'numeric'}
    
    elif seed_type == "text":
        # Generate text-based seed
        words = [
            'mountain', 'valley', 'ocean', 'forest', 'desert', 'jungle',
            'plains', 'taiga', 'swamp', 'mesa', 'ice', 'volcanic',
            'crystal', 'ancient', 'mystic', 'hidden', 'epic', 'legendary'
        ]
        seed = '-'.join(random.sample(words, 3))
        return {'seed': seed, 'type': 'text'}
    
    else:
        raise HTTPException(status_code=400, detail="Invalid seed type")


@router.get("/seed/suggestions")
async def get_seed_suggestions(
    current_user: User = Depends(require_auth)
):
    """Get curated world seed suggestions"""
    
    suggestions = [
        {'seed': '8678942899319966093', 'description': 'Spawn on small island with village', 'version': '1.20+'},
        {'seed': '-1654510255', 'description': 'Massive mountain range at spawn', 'version': '1.18+'},
        {'seed': 'glacier', 'description': 'Ice spikes biome near spawn', 'version': '1.20+'},
        {'seed': '7000', 'description': 'Classic spawn with varied biomes', 'version': 'Any'},
        {'seed': '-4530634556500121041', 'description': 'Jungle temple at spawn', 'version': '1.20+'},
        {'seed': '2151901553968352745', 'description': 'Mushroom island spawn', 'version': '1.18+'},
        {'seed': 'village', 'description': 'Village at spawn point', 'version': 'Any'},
        {'seed': '-1880625916', 'description': 'Mega taiga with mountain views', 'version': '1.18+'}
    ]
    
    return {'suggestions': suggestions}


# ==================== Validation Rules ====================

@router.post("/validate")
async def validate_config(
    server_name: str,
    current_user: User = Depends(require_auth)
):
    """Validate server configuration"""
    
    server_path = SERVERS_ROOT / server_name
    props_file = server_path / "server.properties"
    
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties not found")
    
    content = props_file.read_text(encoding='utf-8', errors='ignore')
    properties = _parse_properties(content)
    
    # Convert to proper types for validation
    typed_props = {}
    for key, value in properties.items():
        schema = PROPERTY_SCHEMA.get(key)
        if schema:
            if schema['type'] == 'integer':
                try:
                    typed_props[key] = int(value)
                except:
                    typed_props[key] = value
            elif schema['type'] == 'boolean':
                typed_props[key] = value.lower() == 'true'
            else:
                typed_props[key] = value
        else:
            typed_props[key] = value
    
    # Validate
    errors = _validate_properties(typed_props)
    warnings = []
    
    # Additional validation checks
    if 'max-players' in typed_props and typed_props['max-players'] > 100:
        warnings.append({
            'property': 'max-players',
            'message': 'High player count may impact performance'
        })
    
    if 'view-distance' in typed_props and typed_props['view-distance'] > 15:
        warnings.append({
            'property': 'view-distance',
            'message': 'High view distance may impact performance'
        })
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'properties_checked': len(typed_props)
    }
