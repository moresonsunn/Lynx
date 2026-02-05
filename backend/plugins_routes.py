"""
Plugin & Extension System
Plugin marketplace, custom server types, extension loader
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, validator, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import importlib
import sys
import os
from pathlib import Path
import zipfile
import tempfile
import hashlib

from database import get_db
from models import User, Plugin, PluginVersion, PluginInstallation, PluginReview
from auth import require_auth, require_admin

router = APIRouter(prefix="/plugins", tags=["plugins"])


# ==================== Request/Response Models ====================

class PluginCreate(BaseModel):
    name: str
    display_name: str
    description: str
    category: str  # server_type, integration, theme, utility
    repository_url: Optional[HttpUrl] = None
    documentation_url: Optional[HttpUrl] = None
    author: str


class PluginVersionCreate(BaseModel):
    plugin_id: int
    version: str
    changelog: Optional[str] = None
    min_lynx_version: Optional[str] = None
    max_lynx_version: Optional[str] = None


class PluginReviewCreate(BaseModel):
    plugin_id: int
    rating: int
    comment: Optional[str] = None
    
    @validator('rating')
    def validate_rating(cls, v):
        if v < 1 or v > 5:
            raise ValueError('Rating must be between 1 and 5')
        return v


# ==================== Plugin Marketplace ====================

@router.get("/marketplace")
async def list_marketplace_plugins(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "downloads",  # downloads, rating, recent
    limit: int = 50,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List available plugins in marketplace"""
    
    query = db.query(Plugin).filter(Plugin.is_published == True)
    
    if category:
        query = query.filter(Plugin.category == category)
    
    if search:
        query = query.filter(
            or_(
                Plugin.name.ilike(f"%{search}%"),
                Plugin.display_name.ilike(f"%{search}%"),
                Plugin.description.ilike(f"%{search}%")
            )
        )
    
    # Sorting
    if sort_by == "downloads":
        query = query.order_by(Plugin.download_count.desc())
    elif sort_by == "rating":
        query = query.order_by(Plugin.average_rating.desc())
    elif sort_by == "recent":
        query = query.order_by(Plugin.created_at.desc())
    
    plugins = query.limit(limit).all()
    
    return {
        'plugins': [
            {
                'id': p.id,
                'name': p.name,
                'display_name': p.display_name,
                'description': p.description,
                'category': p.category,
                'author': p.author,
                'version': p.latest_version,
                'downloads': p.download_count,
                'rating': p.average_rating,
                'review_count': p.review_count,
                'repository_url': p.repository_url,
                'created_at': p.created_at.isoformat()
            }
            for p in plugins
        ]
    }


@router.get("/marketplace/{plugin_id}")
async def get_plugin_details(
    plugin_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get detailed plugin information"""
    
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Get versions
    versions = db.query(PluginVersion).filter(
        PluginVersion.plugin_id == plugin_id
    ).order_by(PluginVersion.created_at.desc()).all()
    
    # Get reviews
    reviews = db.query(PluginReview).filter(
        PluginReview.plugin_id == plugin_id
    ).order_by(PluginReview.created_at.desc()).limit(10).all()
    
    # Check if installed
    installation = db.query(PluginInstallation).filter(
        and_(
            PluginInstallation.plugin_id == plugin_id,
            PluginInstallation.user_id == current_user.id
        )
    ).first()
    
    return {
        'id': plugin.id,
        'name': plugin.name,
        'display_name': plugin.display_name,
        'description': plugin.description,
        'category': plugin.category,
        'author': plugin.author,
        'repository_url': plugin.repository_url,
        'documentation_url': plugin.documentation_url,
        'latest_version': plugin.latest_version,
        'downloads': plugin.download_count,
        'average_rating': plugin.average_rating,
        'review_count': plugin.review_count,
        'is_installed': installation is not None,
        'installed_version': installation.version if installation else None,
        'versions': [
            {
                'version': v.version,
                'changelog': v.changelog,
                'downloads': v.download_count,
                'created_at': v.created_at.isoformat()
            }
            for v in versions
        ],
        'recent_reviews': [
            {
                'user': r.user.username,
                'rating': r.rating,
                'comment': r.comment,
                'created_at': r.created_at.isoformat()
            }
            for r in reviews
        ]
    }


@router.post("/marketplace")
async def publish_plugin(
    plugin: PluginCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Publish a new plugin to marketplace"""
    
    # Check if plugin name already exists
    existing = db.query(Plugin).filter(Plugin.name == plugin.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plugin name already exists")
    
    new_plugin = Plugin(
        name=plugin.name,
        display_name=plugin.display_name,
        description=plugin.description,
        category=plugin.category,
        repository_url=str(plugin.repository_url) if plugin.repository_url else None,
        documentation_url=str(plugin.documentation_url) if plugin.documentation_url else None,
        author=plugin.author,
        publisher_id=current_user.id,
        is_published=False,  # Requires approval
        latest_version="0.0.0",
        download_count=0,
        average_rating=0.0,
        review_count=0
    )
    db.add(new_plugin)
    db.commit()
    db.refresh(new_plugin)
    
    return {
        'id': new_plugin.id,
        'name': new_plugin.name,
        'message': 'Plugin submitted for review'
    }


@router.post("/marketplace/{plugin_id}/versions")
async def upload_plugin_version(
    plugin_id: int,
    version: str,
    file: UploadFile = File(...),
    changelog: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Upload a new version of a plugin"""
    
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Check ownership
    if plugin.publisher_id != current_user.id and current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Save file
    plugins_dir = Path("plugins") / plugin.name
    plugins_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = plugins_dir / f"{version}.zip"
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Calculate checksum
    checksum = hashlib.sha256(content).hexdigest()
    
    # Create version record
    plugin_version = PluginVersion(
        plugin_id=plugin_id,
        version=version,
        file_path=str(file_path),
        file_size=len(content),
        checksum=checksum,
        changelog=changelog,
        download_count=0
    )
    db.add(plugin_version)
    
    # Update plugin latest version
    plugin.latest_version = version
    db.commit()
    
    return {
        'success': True,
        'version': version,
        'checksum': checksum
    }


# ==================== Plugin Installation ====================

@router.post("/{plugin_id}/install")
async def install_plugin(
    plugin_id: int,
    version: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Install a plugin"""
    
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Use latest version if not specified
    if not version:
        version = plugin.latest_version
    
    # Get version details
    plugin_version = db.query(PluginVersion).filter(
        and_(
            PluginVersion.plugin_id == plugin_id,
            PluginVersion.version == version
        )
    ).first()
    
    if not plugin_version:
        raise HTTPException(status_code=404, detail="Plugin version not found")
    
    # Check if already installed
    existing = db.query(PluginInstallation).filter(
        and_(
            PluginInstallation.plugin_id == plugin_id,
            PluginInstallation.user_id == current_user.id
        )
    ).first()
    
    if existing:
        # Update version
        existing.version = version
        existing.updated_at = datetime.utcnow()
    else:
        # New installation
        installation = PluginInstallation(
            plugin_id=plugin_id,
            user_id=current_user.id,
            version=version,
            is_enabled=True
        )
        db.add(installation)
        
        # Increment download count
        plugin.download_count += 1
        plugin_version.download_count += 1
    
    db.commit()
    
    return {
        'success': True,
        'plugin': plugin.name,
        'version': version,
        'message': 'Plugin installed successfully'
    }


@router.delete("/{plugin_id}/uninstall")
async def uninstall_plugin(
    plugin_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Uninstall a plugin"""
    
    installation = db.query(PluginInstallation).filter(
        and_(
            PluginInstallation.plugin_id == plugin_id,
            PluginInstallation.user_id == current_user.id
        )
    ).first()
    
    if not installation:
        raise HTTPException(status_code=404, detail="Plugin not installed")
    
    db.delete(installation)
    db.commit()
    
    return {'success': True, 'message': 'Plugin uninstalled'}


@router.get("/installed")
async def list_installed_plugins(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List user's installed plugins"""
    
    installations = db.query(PluginInstallation).filter(
        PluginInstallation.user_id == current_user.id
    ).all()
    
    return {
        'plugins': [
            {
                'id': inst.plugin.id,
                'name': inst.plugin.name,
                'display_name': inst.plugin.display_name,
                'category': inst.plugin.category,
                'version': inst.version,
                'latest_version': inst.plugin.latest_version,
                'is_enabled': inst.is_enabled,
                'installed_at': inst.installed_at.isoformat(),
                'needs_update': inst.version != inst.plugin.latest_version
            }
            for inst in installations
        ]
    }


@router.put("/{plugin_id}/toggle")
async def toggle_plugin(
    plugin_id: int,
    enabled: bool,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Enable or disable an installed plugin"""
    
    installation = db.query(PluginInstallation).filter(
        and_(
            PluginInstallation.plugin_id == plugin_id,
            PluginInstallation.user_id == current_user.id
        )
    ).first()
    
    if not installation:
        raise HTTPException(status_code=404, detail="Plugin not installed")
    
    installation.is_enabled = enabled
    db.commit()
    
    return {
        'success': True,
        'plugin': installation.plugin.name,
        'enabled': enabled
    }


# ==================== Plugin Reviews ====================

@router.post("/{plugin_id}/reviews")
async def create_review(
    plugin_id: int,
    review: PluginReviewCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create a plugin review"""
    
    # Check if plugin exists
    plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    # Check if already reviewed
    existing = db.query(PluginReview).filter(
        and_(
            PluginReview.plugin_id == plugin_id,
            PluginReview.user_id == current_user.id
        )
    ).first()
    
    if existing:
        # Update existing review
        existing.rating = review.rating
        existing.comment = review.comment
        existing.updated_at = datetime.utcnow()
    else:
        # Create new review
        new_review = PluginReview(
            plugin_id=plugin_id,
            user_id=current_user.id,
            rating=review.rating,
            comment=review.comment
        )
        db.add(new_review)
        plugin.review_count += 1
    
    # Recalculate average rating
    from sqlalchemy import func
    avg_rating = db.query(func.avg(PluginReview.rating)).filter(
        PluginReview.plugin_id == plugin_id
    ).scalar()
    
    plugin.average_rating = round(float(avg_rating), 2) if avg_rating else 0.0
    db.commit()
    
    return {'success': True, 'message': 'Review submitted'}


@router.get("/{plugin_id}/reviews")
async def list_reviews(
    plugin_id: int,
    limit: int = 50,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List plugin reviews"""
    
    reviews = db.query(PluginReview).filter(
        PluginReview.plugin_id == plugin_id
    ).order_by(PluginReview.created_at.desc()).limit(limit).all()
    
    return {
        'reviews': [
            {
                'id': r.id,
                'user': r.user.username,
                'rating': r.rating,
                'comment': r.comment,
                'created_at': r.created_at.isoformat()
            }
            for r in reviews
        ]
    }


# ==================== Plugin Loading (Custom Server Types) ====================

@router.get("/server-types")
async def list_plugin_server_types(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List custom server types from plugins"""
    
    # Get enabled plugin installations
    installations = db.query(PluginInstallation).filter(
        and_(
            PluginInstallation.user_id == current_user.id,
            PluginInstallation.is_enabled == True
        )
    ).all()
    
    server_types = []
    
    for inst in installations:
        if inst.plugin.category != "server_type":
            continue
        
        # Try to load plugin metadata
        try:
            metadata = _load_plugin_metadata(inst.plugin.name, inst.version)
            if metadata and 'server_types' in metadata:
                server_types.extend(metadata['server_types'])
        except Exception as e:
            print(f"Error loading plugin {inst.plugin.name}: {e}")
    
    return {'server_types': server_types}


def _load_plugin_metadata(plugin_name: str, version: str) -> Optional[Dict[str, Any]]:
    """Load plugin metadata from installed plugin"""
    
    plugin_dir = Path("plugins") / plugin_name / version
    metadata_file = plugin_dir / "plugin.json"
    
    if not metadata_file.exists():
        return None
    
    with open(metadata_file, 'r') as f:
        return json.load(f)


@router.post("/reload")
async def reload_plugins(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Reload all enabled plugins (admin only)"""
    
    installations = db.query(PluginInstallation).filter(
        PluginInstallation.is_enabled == True
    ).all()
    
    loaded = []
    errors = []
    
    for inst in installations:
        try:
            # Reload plugin module
            module_name = f"plugins.{inst.plugin.name}"
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
            
            loaded.append(inst.plugin.name)
        except Exception as e:
            errors.append({
                'plugin': inst.plugin.name,
                'error': str(e)
            })
    
    return {
        'success': len(errors) == 0,
        'loaded': loaded,
        'errors': errors
    }
