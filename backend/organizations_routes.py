"""
Multi-Tenancy & Organizations
Teams, resource quotas, billing tracking, organization permissions
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from pydantic import BaseModel, validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from database import get_db
from models import User, Organization, OrganizationMember, ResourceQuota, UsageRecord, OrganizationInvite
from auth import require_auth, require_admin, get_current_user

router = APIRouter(prefix="/organizations", tags=["organizations"])


# ==================== Enums ====================

class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class QuotaType(str, Enum):
    SERVERS = "servers"
    STORAGE = "storage"  # GB
    RAM = "ram"  # GB
    MONTHLY_COST = "monthly_cost"  # dollars


# ==================== Request/Response Models ====================

class OrganizationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    billing_email: Optional[str] = None


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    billing_email: Optional[str] = None
    is_active: Optional[bool] = None


class MemberInvite(BaseModel):
    email: str
    role: OrganizationRole = OrganizationRole.MEMBER


class MemberRoleUpdate(BaseModel):
    role: OrganizationRole


class QuotaUpdate(BaseModel):
    quota_type: QuotaType
    limit: float


class UsageRecordCreate(BaseModel):
    resource_type: str  # server, storage, ram, etc.
    amount: float
    cost: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


# ==================== Organization Management ====================

@router.post("/")
async def create_organization(
    org: OrganizationCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create a new organization"""
    
    # Create organization
    organization = Organization(
        name=org.name,
        description=org.description,
        billing_email=org.billing_email or current_user.email,
        owner_id=current_user.id,
        is_active=True
    )
    db.add(organization)
    db.flush()
    
    # Add creator as owner
    member = OrganizationMember(
        organization_id=organization.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
        joined_at=datetime.utcnow()
    )
    db.add(member)
    
    # Create default quotas
    default_quotas = [
        ResourceQuota(
            organization_id=organization.id,
            quota_type=QuotaType.SERVERS,
            limit=10,
            used=0
        ),
        ResourceQuota(
            organization_id=organization.id,
            quota_type=QuotaType.STORAGE,
            limit=100,  # 100 GB
            used=0
        ),
        ResourceQuota(
            organization_id=organization.id,
            quota_type=QuotaType.RAM,
            limit=32,  # 32 GB
            used=0
        ),
        ResourceQuota(
            organization_id=organization.id,
            quota_type=QuotaType.MONTHLY_COST,
            limit=100,  # $100/month
            used=0
        )
    ]
    for quota in default_quotas:
        db.add(quota)
    
    db.commit()
    db.refresh(organization)
    
    return {
        'id': organization.id,
        'name': organization.name,
        'description': organization.description,
        'created_at': organization.created_at.isoformat(),
        'role': OrganizationRole.OWNER
    }


@router.get("/")
async def list_organizations(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List all organizations user belongs to"""
    
    # Get organizations where user is a member
    memberships = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == current_user.id
    ).all()
    
    organizations = []
    for membership in memberships:
        org = membership.organization
        if not org.is_active:
            continue
        
        # Get member count
        member_count = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == org.id
        ).count()
        
        organizations.append({
            'id': org.id,
            'name': org.name,
            'description': org.description,
            'role': membership.role,
            'member_count': member_count,
            'created_at': org.created_at.isoformat(),
            'is_owner': org.owner_id == current_user.id
        })
    
    return {'organizations': organizations}


@router.get("/{org_id}")
async def get_organization(
    org_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get organization details"""
    
    # Check membership
    membership = _check_org_membership(db, org_id, current_user.id)
    org = membership.organization
    
    # Get quotas
    quotas = db.query(ResourceQuota).filter(
        ResourceQuota.organization_id == org_id
    ).all()
    
    quota_dict = {
        q.quota_type: {
            'limit': q.limit,
            'used': q.used,
            'percentage': round((q.used / q.limit * 100) if q.limit > 0 else 0, 1)
        }
        for q in quotas
    }
    
    # Get members
    members = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == org_id
    ).all()
    
    member_list = [
        {
            'user_id': m.user_id,
            'username': m.user.username,
            'email': m.user.email,
            'role': m.role,
            'joined_at': m.joined_at.isoformat()
        }
        for m in members
    ]
    
    return {
        'id': org.id,
        'name': org.name,
        'description': org.description,
        'billing_email': org.billing_email,
        'created_at': org.created_at.isoformat(),
        'is_active': org.is_active,
        'owner_id': org.owner_id,
        'current_user_role': membership.role,
        'quotas': quota_dict,
        'members': member_list
    }


@router.put("/{org_id}")
async def update_organization(
    org_id: int,
    update: OrganizationUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update organization details"""
    
    # Check admin permission
    membership = _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    org = membership.organization
    
    # Update fields
    if update.name is not None:
        org.name = update.name
    if update.description is not None:
        org.description = update.description
    if update.billing_email is not None:
        org.billing_email = update.billing_email
    
    # Only owner can change active status
    if update.is_active is not None:
        if org.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only owner can change active status")
        org.is_active = update.is_active
    
    db.commit()
    
    return {'success': True, 'message': 'Organization updated'}


@router.delete("/{org_id}")
async def delete_organization(
    org_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete organization (owner only)"""
    
    membership = _check_org_membership(db, org_id, current_user.id)
    org = membership.organization
    
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can delete organization")
    
    # Soft delete
    org.is_active = False
    db.commit()
    
    return {'success': True, 'message': 'Organization deleted'}


# ==================== Member Management ====================

@router.post("/{org_id}/members/invite")
async def invite_member(
    org_id: int,
    invite: MemberInvite,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Invite user to organization"""
    
    # Check admin permission
    _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    
    # Find user by email
    user = db.query(User).filter(User.email == invite.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if already member
    existing = db.query(OrganizationMember).filter(
        and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id
        )
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="User already a member")
    
    # Create invite
    org_invite = OrganizationInvite(
        organization_id=org_id,
        invited_by=current_user.id,
        invited_user_id=user.id,
        role=invite.role,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db.add(org_invite)
    db.commit()
    
    return {
        'success': True,
        'message': f'Invitation sent to {invite.email}',
        'invite_id': org_invite.id
    }


@router.post("/{org_id}/invites/{invite_id}/accept")
async def accept_invite(
    org_id: int,
    invite_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Accept organization invitation"""
    
    invite = db.query(OrganizationInvite).filter(
        and_(
            OrganizationInvite.id == invite_id,
            OrganizationInvite.organization_id == org_id,
            OrganizationInvite.invited_user_id == current_user.id,
            OrganizationInvite.accepted_at == None
        )
    ).first()
    
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or already accepted")
    
    if invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite has expired")
    
    # Create membership
    member = OrganizationMember(
        organization_id=org_id,
        user_id=current_user.id,
        role=invite.role,
        joined_at=datetime.utcnow()
    )
    db.add(member)
    
    # Mark invite as accepted
    invite.accepted_at = datetime.utcnow()
    db.commit()
    
    return {'success': True, 'message': 'Invitation accepted'}


@router.get("/{org_id}/invites")
async def list_invites(
    org_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List pending invitations"""
    
    _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    
    invites = db.query(OrganizationInvite).filter(
        and_(
            OrganizationInvite.organization_id == org_id,
            OrganizationInvite.accepted_at == None,
            OrganizationInvite.expires_at > datetime.utcnow()
        )
    ).all()
    
    return {
        'invites': [
            {
                'id': inv.id,
                'invited_user': inv.invited_user.username,
                'invited_by': inv.inviter.username,
                'role': inv.role,
                'created_at': inv.created_at.isoformat(),
                'expires_at': inv.expires_at.isoformat()
            }
            for inv in invites
        ]
    }


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(
    org_id: int,
    user_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Remove member from organization"""
    
    membership = _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    org = membership.organization
    
    # Cannot remove owner
    if org.owner_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove organization owner")
    
    # Find member
    member = db.query(OrganizationMember).filter(
        and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id
        )
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    
    db.delete(member)
    db.commit()
    
    return {'success': True, 'message': 'Member removed'}


@router.put("/{org_id}/members/{user_id}/role")
async def update_member_role(
    org_id: int,
    user_id: int,
    role_update: MemberRoleUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update member role"""
    
    membership = _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    org = membership.organization
    
    # Cannot change owner role
    if org.owner_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot change owner role")
    
    member = db.query(OrganizationMember).filter(
        and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id
        )
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    
    member.role = role_update.role
    db.commit()
    
    return {'success': True, 'message': 'Role updated'}


# ==================== Resource Quotas ====================

@router.get("/{org_id}/quotas")
async def get_quotas(
    org_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get organization resource quotas"""
    
    _check_org_membership(db, org_id, current_user.id)
    
    quotas = db.query(ResourceQuota).filter(
        ResourceQuota.organization_id == org_id
    ).all()
    
    return {
        'quotas': [
            {
                'type': q.quota_type,
                'limit': q.limit,
                'used': q.used,
                'available': q.limit - q.used,
                'percentage': round((q.used / q.limit * 100) if q.limit > 0 else 0, 1)
            }
            for q in quotas
        ]
    }


@router.put("/{org_id}/quotas")
async def update_quota(
    org_id: int,
    quota_update: QuotaUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update resource quota (admin only)"""
    
    quota = db.query(ResourceQuota).filter(
        and_(
            ResourceQuota.organization_id == org_id,
            ResourceQuota.quota_type == quota_update.quota_type
        )
    ).first()
    
    if quota:
        quota.limit = quota_update.limit
    else:
        quota = ResourceQuota(
            organization_id=org_id,
            quota_type=quota_update.quota_type,
            limit=quota_update.limit,
            used=0
        )
        db.add(quota)
    
    db.commit()
    
    return {'success': True, 'message': 'Quota updated'}


@router.post("/{org_id}/quotas/check")
async def check_quota(
    org_id: int,
    quota_type: QuotaType,
    amount: float,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Check if quota allows specified amount"""
    
    _check_org_membership(db, org_id, current_user.id)
    
    quota = db.query(ResourceQuota).filter(
        and_(
            ResourceQuota.organization_id == org_id,
            ResourceQuota.quota_type == quota_type
        )
    ).first()
    
    if not quota:
        return {'allowed': False, 'reason': 'Quota not configured'}
    
    available = quota.limit - quota.used
    allowed = available >= amount
    
    return {
        'allowed': allowed,
        'available': available,
        'requested': amount,
        'would_use': quota.used + amount if allowed else None,
        'limit': quota.limit
    }


# ==================== Usage Tracking & Billing ====================

@router.post("/{org_id}/usage")
async def record_usage(
    org_id: int,
    usage: UsageRecordCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Record resource usage"""
    
    _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    
    # Create usage record
    record = UsageRecord(
        organization_id=org_id,
        resource_type=usage.resource_type,
        amount=usage.amount,
        cost=usage.cost or 0.0,
        metadata=usage.metadata,
        recorded_at=datetime.utcnow()
    )
    db.add(record)
    
    # Update quota if applicable
    quota_type_map = {
        'server': QuotaType.SERVERS,
        'storage': QuotaType.STORAGE,
        'ram': QuotaType.RAM
    }
    
    if usage.resource_type in quota_type_map:
        quota = db.query(ResourceQuota).filter(
            and_(
                ResourceQuota.organization_id == org_id,
                ResourceQuota.quota_type == quota_type_map[usage.resource_type]
            )
        ).first()
        
        if quota:
            quota.used += usage.amount
    
    db.commit()
    
    return {'success': True, 'message': 'Usage recorded'}


@router.get("/{org_id}/usage")
async def get_usage_history(
    org_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    resource_type: Optional[str] = None,
    limit: int = Query(100, le=1000),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get usage history"""
    
    _check_org_membership(db, org_id, current_user.id)
    
    query = db.query(UsageRecord).filter(UsageRecord.organization_id == org_id)
    
    if start_date:
        query = query.filter(UsageRecord.recorded_at >= start_date)
    if end_date:
        query = query.filter(UsageRecord.recorded_at <= end_date)
    if resource_type:
        query = query.filter(UsageRecord.resource_type == resource_type)
    
    records = query.order_by(UsageRecord.recorded_at.desc()).limit(limit).all()
    
    return {
        'usage_records': [
            {
                'id': r.id,
                'resource_type': r.resource_type,
                'amount': r.amount,
                'cost': r.cost,
                'metadata': r.usage_metadata,
                'recorded_at': r.recorded_at.isoformat()
            }
            for r in records
        ]
    }


@router.get("/{org_id}/billing/summary")
async def get_billing_summary(
    org_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get billing summary for month"""
    
    _check_org_membership(db, org_id, current_user.id, min_role=OrganizationRole.ADMIN)
    
    # Default to current month
    if not month or not year:
        now = datetime.utcnow()
        month = month or now.month
        year = year or now.year
    
    # Get usage for month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)
    
    records = db.query(UsageRecord).filter(
        and_(
            UsageRecord.organization_id == org_id,
            UsageRecord.recorded_at >= start_date,
            UsageRecord.recorded_at < end_date
        )
    ).all()
    
    # Aggregate by resource type
    by_resource = {}
    total_cost = 0.0
    
    for record in records:
        if record.resource_type not in by_resource:
            by_resource[record.resource_type] = {
                'total_amount': 0.0,
                'total_cost': 0.0,
                'record_count': 0
            }
        
        by_resource[record.resource_type]['total_amount'] += record.amount
        by_resource[record.resource_type]['total_cost'] += record.cost
        by_resource[record.resource_type]['record_count'] += 1
        total_cost += record.cost
    
    return {
        'period': f"{year}-{month:02d}",
        'total_cost': round(total_cost, 2),
        'by_resource': by_resource,
        'record_count': len(records)
    }


# ==================== Helper Functions ====================

def _check_org_membership(
    db: Session,
    org_id: int,
    user_id: int,
    min_role: OrganizationRole = OrganizationRole.VIEWER
) -> OrganizationMember:
    """Check if user is member of organization with minimum role"""
    
    membership = db.query(OrganizationMember).filter(
        and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id
        )
    ).first()
    
    if not membership:
        raise HTTPException(status_code=404, detail="Organization not found or access denied")
    
    if not membership.organization.is_active:
        raise HTTPException(status_code=400, detail="Organization is not active")
    
    # Check role hierarchy
    role_hierarchy = {
        OrganizationRole.VIEWER: 0,
        OrganizationRole.MEMBER: 1,
        OrganizationRole.ADMIN: 2,
        OrganizationRole.OWNER: 3
    }
    
    if role_hierarchy[membership.role] < role_hierarchy[min_role]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    return membership
