"""
Multi-Server Management
Server groups/tags, bulk operations, server cloning, and file sync
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import shutil
import asyncio

from database import get_db
from models import ServerGroup, ServerGroupMember, BulkOperation, ServerClone, User
from auth import require_auth, require_moderator
from runtime_adapter import get_runtime_manager_or_docker
from config import SERVERS_ROOT

router = APIRouter(prefix="/multi-server", tags=["multi_server"])


# ==================== Request/Response Models ====================

class ServerGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#3b82f6"
    icon: Optional[str] = "📁"


class ServerGroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    color: Optional[str]
    icon: Optional[str]
    server_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class AddToGroupRequest(BaseModel):
    server_names: List[str]


class BulkOperationRequest(BaseModel):
    operation_type: str  # start, stop, restart, backup
    server_names: List[str]


class BulkOperationResponse(BaseModel):
    id: int
    operation_type: str
    status: str
    total_count: int
    success_count: int
    failed_count: int
    results: Optional[Dict[str, Any]]
    
    class Config:
        from_attributes = True


class ServerCloneRequest(BaseModel):
    source_server: str
    target_server: str
    clone_type: str = "full"  # full, config_only, world_only
    include_worlds: bool = True
    include_mods: bool = True
    include_plugins: bool = True


class ServerCloneResponse(BaseModel):
    id: int
    source_server: str
    target_server: str
    clone_type: str
    status: str
    progress_percent: int
    
    class Config:
        from_attributes = True


class FileSyncRequest(BaseModel):
    source_server: str
    target_servers: List[str]
    paths: List[str]  # Relative paths to sync (e.g., ["mods", "plugins"])


# ==================== Server Groups ====================

@router.post("/groups", response_model=ServerGroupResponse)
async def create_server_group(
    group: ServerGroupCreate,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Create a new server group"""
    
    # Check if group name already exists
    existing = db.query(ServerGroup).filter(ServerGroup.name == group.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Group name already exists")
    
    db_group = ServerGroup(
        name=group.name,
        description=group.description,
        color=group.color,
        icon=group.icon,
        created_by=current_user.id
    )
    
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    
    return ServerGroupResponse(
        id=db_group.id,
        name=db_group.name,
        description=db_group.description,
        color=db_group.color,
        icon=db_group.icon,
        server_count=0,
        created_at=db_group.created_at
    )


@router.get("/groups", response_model=List[ServerGroupResponse])
async def list_server_groups(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List all server groups"""
    
    groups = db.query(ServerGroup).all()
    
    return [
        ServerGroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            color=g.color,
            icon=g.icon,
            server_count=len(g.servers),
            created_at=g.created_at
        )
        for g in groups
    ]


@router.get("/groups/{group_id}/servers")
async def get_group_servers(
    group_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all servers in a group"""
    
    group = db.query(ServerGroup).filter(ServerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    return {
        "group_name": group.name,
        "servers": [
            {
                "server_name": m.server_name,
                "added_at": m.added_at
            }
            for m in group.servers
        ]
    }


@router.post("/groups/{group_id}/servers")
async def add_servers_to_group(
    group_id: int,
    request: AddToGroupRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Add servers to a group"""
    
    group = db.query(ServerGroup).filter(ServerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    added = []
    for server_name in request.server_names:
        # Check if server exists
        server_path = SERVERS_ROOT / server_name
        if not server_path.exists():
            continue
        
        # Check if already in group
        existing = db.query(ServerGroupMember).filter(
            ServerGroupMember.group_id == group_id,
            ServerGroupMember.server_name == server_name
        ).first()
        
        if not existing:
            member = ServerGroupMember(
                group_id=group_id,
                server_name=server_name,
                added_by=current_user.id
            )
            db.add(member)
            added.append(server_name)
    
    db.commit()
    
    return {"message": f"Added {len(added)} servers to group", "servers": added}


@router.delete("/groups/{group_id}/servers/{server_name}")
async def remove_server_from_group(
    group_id: int,
    server_name: str,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Remove a server from a group"""
    
    member = db.query(ServerGroupMember).filter(
        ServerGroupMember.group_id == group_id,
        ServerGroupMember.server_name == server_name
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Server not in group")
    
    db.delete(member)
    db.commit()
    
    return {"message": "Server removed from group"}


@router.delete("/groups/{group_id}")
async def delete_server_group(
    group_id: int,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Delete a server group"""
    
    group = db.query(ServerGroup).filter(ServerGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    db.delete(group)
    db.commit()
    
    return {"message": "Group deleted"}


# ==================== Bulk Operations ====================

def get_docker_manager():
    return get_runtime_manager_or_docker()


async def _execute_bulk_operation(
    operation_id: int,
    operation_type: str,
    server_names: List[str],
    db: Session
):
    """Background task to execute bulk operation"""
    
    manager = get_docker_manager()
    results = {}
    success_count = 0
    failed_count = 0
    
    # Update status to running
    operation = db.query(BulkOperation).filter(BulkOperation.id == operation_id).first()
    operation.status = "running"
    db.commit()
    
    for server_name in server_names:
        try:
            if operation_type == "start":
                manager.start_server(server_name)
                results[server_name] = {"status": "success", "message": "Server started"}
                success_count += 1
            
            elif operation_type == "stop":
                manager.stop_server(server_name)
                results[server_name] = {"status": "success", "message": "Server stopped"}
                success_count += 1
            
            elif operation_type == "restart":
                manager.stop_server(server_name)
                manager.start_server(server_name)
                results[server_name] = {"status": "success", "message": "Server restarted"}
                success_count += 1
            
            elif operation_type == "backup":
                from backup_manager import create_backup
                backup = create_backup(server_name)
                results[server_name] = {"status": "success", "message": f"Backup created: {backup['file']}"}
                success_count += 1
            
            else:
                results[server_name] = {"status": "error", "message": "Unknown operation type"}
                failed_count += 1
        
        except Exception as e:
            results[server_name] = {"status": "error", "message": str(e)}
            failed_count += 1
    
    # Update operation with results
    operation.results = results
    operation.success_count = success_count
    operation.failed_count = failed_count
    operation.status = "completed"
    operation.completed_at = datetime.utcnow()
    db.commit()


@router.post("/bulk-operations", response_model=BulkOperationResponse)
async def create_bulk_operation(
    request: BulkOperationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Execute a bulk operation on multiple servers"""
    
    if request.operation_type not in ["start", "stop", "restart", "backup"]:
        raise HTTPException(status_code=400, detail="Invalid operation type")
    
    # Create operation record
    operation = BulkOperation(
        operation_type=request.operation_type,
        server_names=request.server_names,
        total_count=len(request.server_names),
        started_by=current_user.id
    )
    
    db.add(operation)
    db.commit()
    db.refresh(operation)
    
    # Execute in background
    background_tasks.add_task(
        _execute_bulk_operation,
        operation.id,
        request.operation_type,
        request.server_names,
        db
    )
    
    return BulkOperationResponse.model_validate(operation)


@router.get("/bulk-operations/{operation_id}", response_model=BulkOperationResponse)
async def get_bulk_operation_status(
    operation_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get status of a bulk operation"""
    
    operation = db.query(BulkOperation).filter(BulkOperation.id == operation_id).first()
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    return BulkOperationResponse.model_validate(operation)


@router.get("/bulk-operations", response_model=List[BulkOperationResponse])
async def list_bulk_operations(
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List recent bulk operations"""
    
    operations = db.query(BulkOperation).order_by(
        BulkOperation.started_at.desc()
    ).limit(limit).all()
    
    return [BulkOperationResponse.model_validate(op) for op in operations]


# ==================== Server Cloning ====================

async def _execute_clone(
    clone_id: int,
    source_server: str,
    target_server: str,
    clone_type: str,
    include_worlds: bool,
    include_mods: bool,
    include_plugins: bool,
    db: Session
):
    """Background task to clone a server"""
    
    try:
        clone = db.query(ServerClone).filter(ServerClone.id == clone_id).first()
        clone.status = "running"
        db.commit()
        
        source_path = SERVERS_ROOT / source_server
        target_path = SERVERS_ROOT / target_server
        
        if not source_path.exists():
            raise Exception("Source server not found")
        
        if target_path.exists():
            raise Exception("Target server already exists")
        
        # Create target directory
        target_path.mkdir(parents=True, exist_ok=True)
        clone.progress_percent = 10
        db.commit()
        
        # Clone based on type
        if clone_type == "full":
            # Copy everything
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            clone.progress_percent = 90
        
        elif clone_type == "config_only":
            # Copy config files only
            for config_file in ["server.properties", "eula.txt", "ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]:
                src_file = source_path / config_file
                if src_file.exists():
                    shutil.copy2(src_file, target_path / config_file)
            clone.progress_percent = 90
        
        elif clone_type == "world_only":
            # Copy worlds only
            for world_dir in ["world", "world_nether", "world_the_end"]:
                src_world = source_path / world_dir
                if src_world.exists():
                    shutil.copytree(src_world, target_path / world_dir, dirs_exist_ok=True)
            clone.progress_percent = 90
        
        else:
            # Custom clone with selections
            if include_worlds:
                for world_dir in ["world", "world_nether", "world_the_end"]:
                    src_world = source_path / world_dir
                    if src_world.exists():
                        shutil.copytree(src_world, target_path / world_dir, dirs_exist_ok=True)
            
            if include_mods:
                for mod_dir in ["mods", "coremods"]:
                    src_mod = source_path / mod_dir
                    if src_mod.exists():
                        shutil.copytree(src_mod, target_path / mod_dir, dirs_exist_ok=True)
            
            if include_plugins:
                src_plugins = source_path / "plugins"
                if src_plugins.exists():
                    shutil.copytree(src_plugins, target_path / "plugins", dirs_exist_ok=True)
            
            # Always copy config files
            for config_file in ["server.properties", "eula.txt"]:
                src_file = source_path / config_file
                if src_file.exists():
                    shutil.copy2(src_file, target_path / config_file)
            
            clone.progress_percent = 90
        
        # Update clone status
        clone.status = "completed"
        clone.progress_percent = 100
        clone.completed_at = datetime.utcnow()
        db.commit()
    
    except Exception as e:
        clone.status = "failed"
        clone.error_message = str(e)
        db.commit()


@router.post("/clone", response_model=ServerCloneResponse)
async def clone_server(
    request: ServerCloneRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Clone a server to a new server"""
    
    # Validate source server exists
    source_path = SERVERS_ROOT / request.source_server
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source server not found")
    
    # Validate target doesn't exist
    target_path = SERVERS_ROOT / request.target_server
    if target_path.exists():
        raise HTTPException(status_code=400, detail="Target server already exists")
    
    # Create clone record
    clone = ServerClone(
        source_server=request.source_server,
        target_server=request.target_server,
        clone_type=request.clone_type,
        cloned_by=current_user.id
    )
    
    db.add(clone)
    db.commit()
    db.refresh(clone)
    
    # Execute clone in background
    background_tasks.add_task(
        _execute_clone,
        clone.id,
        request.source_server,
        request.target_server,
        request.clone_type,
        request.include_worlds,
        request.include_mods,
        request.include_plugins,
        db
    )
    
    return ServerCloneResponse.model_validate(clone)


@router.get("/clone/{clone_id}", response_model=ServerCloneResponse)
async def get_clone_status(
    clone_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get status of a clone operation"""
    
    clone = db.query(ServerClone).filter(ServerClone.id == clone_id).first()
    if not clone:
        raise HTTPException(status_code=404, detail="Clone operation not found")
    
    return ServerCloneResponse.model_validate(clone)


# ==================== File Sync ====================

@router.post("/file-sync")
async def sync_files(
    request: FileSyncRequest,
    current_user: User = Depends(require_moderator),
    db: Session = Depends(get_db)
):
    """Sync files/folders from one server to multiple servers"""
    
    source_path = SERVERS_ROOT / request.source_server
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source server not found")
    
    results = {}
    
    for target_server in request.target_servers:
        target_path = SERVERS_ROOT / target_server
        if not target_path.exists():
            results[target_server] = {"status": "error", "message": "Server not found"}
            continue
        
        synced_paths = []
        errors = []
        
        for rel_path in request.paths:
            try:
                src = source_path / rel_path
                dst = target_path / rel_path
                
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    synced_paths.append(rel_path)
                elif src.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    synced_paths.append(rel_path)
                else:
                    errors.append(f"{rel_path} not found in source")
            
            except Exception as e:
                errors.append(f"{rel_path}: {str(e)}")
        
        results[target_server] = {
            "status": "success" if not errors else "partial",
            "synced": synced_paths,
            "errors": errors
        }
    
    return {
        "message": "File sync completed",
        "results": results
    }
