"""
API Management & Rate Limiting
Rate limiting, API usage analytics, webhooks, API key management
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from pydantic import BaseModel, HttpUrl, validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import secrets
import hmac
import json
import time

from database import get_db
from models import User, UserAPIKey, APIRateLimit, APIUsageLog, Webhook, WebhookDelivery
from auth import require_auth, require_admin, get_current_user

router = APIRouter(prefix="/api-management", tags=["api-management"])


# ==================== Enums ====================

class RateLimitPeriod(str, Enum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


class WebhookEvent(str, Enum):
    SERVER_CREATED = "server.created"
    SERVER_STARTED = "server.started"
    SERVER_STOPPED = "server.stopped"
    SERVER_DELETED = "server.deleted"
    SERVER_CRASHED = "server.crashed"
    BACKUP_CREATED = "backup.created"
    BACKUP_FAILED = "backup.failed"
    USER_CREATED = "user.created"
    USER_DELETED = "user.deleted"
    ALERT_TRIGGERED = "alert.triggered"


# ==================== Request/Response Models ====================

class APIKeyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    expires_in_days: Optional[int] = None
    rate_limit_per_minute: int = 60


class RateLimitCreate(BaseModel):
    endpoint_pattern: str  # e.g., "/servers/*"
    requests_per_period: int
    period: RateLimitPeriod
    user_id: Optional[int] = None  # None = global


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: List[WebhookEvent]
    secret: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class WebhookUpdate(BaseModel):
    url: Optional[HttpUrl] = None
    events: Optional[List[WebhookEvent]] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


# ==================== API Key Management ====================

@router.post("/keys")
async def create_api_key(
    key_data: APIKeyCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create a new API key"""
    
    # Generate random API key
    raw_key = f"lynx_{secrets.token_urlsafe(32)}"
    
    # Hash for storage
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    
    # Calculate expiry
    expires_at = None
    if key_data.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=key_data.expires_in_days)
    
    # Create API key
    api_key = UserAPIKey(
        user_id=current_user.id,
        key_hash=key_hash,
        name=key_data.name,
        description=key_data.description,
        expires_at=expires_at,
        is_active=True
    )
    db.add(api_key)
    db.commit()
    
    # Create rate limit for this key
    if key_data.rate_limit_per_minute:
        rate_limit = APIRateLimit(
            api_key_id=api_key.id,
            endpoint_pattern="*",
            requests_per_period=key_data.rate_limit_per_minute,
            period=RateLimitPeriod.MINUTE
        )
        db.add(rate_limit)
        db.commit()
    
    return {
        'id': api_key.id,
        'key': raw_key,  # Only returned once!
        'name': key_data.name,
        'expires_at': expires_at.isoformat() if expires_at else None,
        'rate_limit': key_data.rate_limit_per_minute,
        'warning': 'Store this key securely. It will not be shown again.'
    }


@router.get("/keys")
async def list_api_keys(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List user's API keys"""
    
    keys = db.query(UserAPIKey).filter(
        UserAPIKey.user_id == current_user.id
    ).all()
    
    return {
        'keys': [
            {
                'id': key.id,
                'name': key.name,
                'description': key.description,
                'created_at': key.created_at.isoformat(),
                'last_used': key.last_used.isoformat() if key.last_used else None,
                'expires_at': key.expires_at.isoformat() if key.expires_at else None,
                'is_active': key.is_active,
                'key_prefix': f"lynx_...{key.key_hash[-8:]}"
            }
            for key in keys
        ]
    }


@router.delete("/keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Revoke an API key"""
    
    key = db.query(UserAPIKey).filter(
        and_(
            UserAPIKey.id == key_id,
            UserAPIKey.user_id == current_user.id
        )
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    key.is_active = False
    db.commit()
    
    return {'success': True, 'message': 'API key revoked'}


@router.get("/keys/{key_id}/usage")
async def get_key_usage(
    key_id: int,
    days: int = 7,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get API key usage statistics"""
    
    key = db.query(UserAPIKey).filter(
        and_(
            UserAPIKey.id == key_id,
            UserAPIKey.user_id == current_user.id
        )
    ).first()
    
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    since = datetime.utcnow() - timedelta(days=days)
    
    # Get usage logs
    logs = db.query(APIUsageLog).filter(
        and_(
            APIUsageLog.api_key_id == key_id,
            APIUsageLog.timestamp >= since
        )
    ).all()
    
    # Aggregate statistics
    total_requests = len(logs)
    status_codes = {}
    endpoints = {}
    
    for log in logs:
        # Count by status code
        status = str(log.status_code)
        status_codes[status] = status_codes.get(status, 0) + 1
        
        # Count by endpoint
        endpoints[log.endpoint] = endpoints.get(log.endpoint, 0) + 1
    
    return {
        'key_id': key_id,
        'key_name': key.name,
        'period_days': days,
        'total_requests': total_requests,
        'by_status_code': status_codes,
        'by_endpoint': endpoints,
        'last_used': key.last_used.isoformat() if key.last_used else None
    }


# ==================== Rate Limiting ====================

@router.post("/rate-limits")
async def create_rate_limit(
    limit: RateLimitCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create rate limit rule (admin only)"""
    
    rate_limit = APIRateLimit(
        endpoint_pattern=limit.endpoint_pattern,
        requests_per_period=limit.requests_per_period,
        period=limit.period,
        user_id=limit.user_id
    )
    db.add(rate_limit)
    db.commit()
    
    return {
        'id': rate_limit.id,
        'endpoint_pattern': rate_limit.endpoint_pattern,
        'requests_per_period': rate_limit.requests_per_period,
        'period': rate_limit.period
    }


@router.get("/rate-limits")
async def list_rate_limits(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all rate limit rules"""
    
    limits = db.query(APIRateLimit).all()
    
    return {
        'rate_limits': [
            {
                'id': lim.id,
                'endpoint_pattern': lim.endpoint_pattern,
                'requests_per_period': lim.requests_per_period,
                'period': lim.period,
                'user_id': lim.user_id,
                'api_key_id': lim.api_key_id,
                'created_at': lim.created_at.isoformat()
            }
            for lim in limits
        ]
    }


@router.delete("/rate-limits/{limit_id}")
async def delete_rate_limit(
    limit_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete rate limit rule"""
    
    limit = db.query(APIRateLimit).filter(APIRateLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(status_code=404, detail="Rate limit not found")
    
    db.delete(limit)
    db.commit()
    
    return {'success': True, 'message': 'Rate limit deleted'}


@router.post("/rate-limits/check")
async def check_rate_limit(
    request: Request,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Check if current request would exceed rate limit"""
    
    endpoint = request.url.path
    result = _check_rate_limit(db, endpoint, current_user.id, None)
    
    return {
        'allowed': result['allowed'],
        'limit': result.get('limit'),
        'remaining': result.get('remaining'),
        'reset_at': result.get('reset_at')
    }


def _check_rate_limit(
    db: Session,
    endpoint: str,
    user_id: int,
    api_key_id: Optional[int]
) -> Dict[str, Any]:
    """Internal rate limit check"""
    
    # Get applicable rate limits
    limits = db.query(APIRateLimit).filter(
        or_(
            APIRateLimit.user_id == user_id,
            APIRateLimit.api_key_id == api_key_id,
            APIRateLimit.user_id == None  # Global limits
        )
    ).all()
    
    if not limits:
        return {'allowed': True}
    
    # Check each limit
    for limit in limits:
        # Match endpoint pattern
        import re
        pattern = limit.endpoint_pattern.replace('*', '.*')
        if not re.match(pattern, endpoint):
            continue
        
        # Calculate time window
        now = datetime.utcnow()
        period_map = {
            RateLimitPeriod.SECOND: timedelta(seconds=1),
            RateLimitPeriod.MINUTE: timedelta(minutes=1),
            RateLimitPeriod.HOUR: timedelta(hours=1),
            RateLimitPeriod.DAY: timedelta(days=1)
        }
        window_start = now - period_map[limit.period]
        
        # Count recent requests
        count_query = db.query(func.count(APIUsageLog.id)).filter(
            APIUsageLog.timestamp >= window_start
        )
        
        if api_key_id:
            count_query = count_query.filter(APIUsageLog.api_key_id == api_key_id)
        elif user_id:
            count_query = count_query.filter(APIUsageLog.user_id == user_id)
        
        count = count_query.scalar()
        
        if count >= limit.requests_per_period:
            reset_at = window_start + period_map[limit.period]
            return {
                'allowed': False,
                'limit': limit.requests_per_period,
                'remaining': 0,
                'reset_at': reset_at.isoformat()
            }
    
    return {'allowed': True}


# ==================== API Usage Analytics ====================

@router.get("/usage/overview")
async def get_usage_overview(
    days: int = 7,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get API usage overview for user"""
    
    since = datetime.utcnow() - timedelta(days=days)
    
    logs = db.query(APIUsageLog).filter(
        and_(
            APIUsageLog.user_id == current_user.id,
            APIUsageLog.timestamp >= since
        )
    ).all()
    
    # Aggregate by day
    by_day = {}
    by_endpoint = {}
    by_status = {}
    total_response_time = 0
    
    for log in logs:
        day = log.timestamp.date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
        
        by_endpoint[log.endpoint] = by_endpoint.get(log.endpoint, 0) + 1
        
        status_code = str(log.status_code)
        by_status[status_code] = by_status.get(status_code, 0) + 1
        
        if log.response_time_ms:
            total_response_time += log.response_time_ms
    
    avg_response_time = total_response_time / len(logs) if logs else 0
    
    return {
        'period_days': days,
        'total_requests': len(logs),
        'by_day': by_day,
        'by_endpoint': sorted(by_endpoint.items(), key=lambda x: x[1], reverse=True)[:10],
        'by_status': by_status,
        'avg_response_time_ms': round(avg_response_time, 2)
    }


@router.get("/usage/global")
async def get_global_usage(
    days: int = 7,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get global API usage statistics (admin only)"""
    
    since = datetime.utcnow() - timedelta(days=days)
    
    # Total requests
    total = db.query(func.count(APIUsageLog.id)).filter(
        APIUsageLog.timestamp >= since
    ).scalar()
    
    # By user
    by_user = db.query(
        User.username,
        func.count(APIUsageLog.id).label('count')
    ).join(User).filter(
        APIUsageLog.timestamp >= since
    ).group_by(User.username).order_by(func.count(APIUsageLog.id).desc()).limit(10).all()
    
    # By endpoint
    by_endpoint = db.query(
        APIUsageLog.endpoint,
        func.count(APIUsageLog.id).label('count')
    ).filter(
        APIUsageLog.timestamp >= since
    ).group_by(APIUsageLog.endpoint).order_by(func.count(APIUsageLog.id).desc()).limit(10).all()
    
    # Error rate
    total_errors = db.query(func.count(APIUsageLog.id)).filter(
        and_(
            APIUsageLog.timestamp >= since,
            APIUsageLog.status_code >= 400
        )
    ).scalar()
    
    error_rate = (total_errors / total * 100) if total > 0 else 0
    
    return {
        'period_days': days,
        'total_requests': total,
        'total_errors': total_errors,
        'error_rate': round(error_rate, 2),
        'top_users': [{'username': u, 'requests': c} for u, c in by_user],
        'top_endpoints': [{'endpoint': e, 'requests': c} for e, c in by_endpoint]
    }


# ==================== Webhooks ====================

@router.post("/webhooks")
async def create_webhook(
    webhook: WebhookCreate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Create a webhook"""
    
    # Generate secret if not provided
    if not webhook.secret:
        webhook.secret = secrets.token_urlsafe(32)
    
    wh = Webhook(
        user_id=current_user.id,
        url=str(webhook.url),
        events=json.dumps([e.value for e in webhook.events]),
        secret=webhook.secret,
        description=webhook.description,
        is_active=webhook.is_active
    )
    db.add(wh)
    db.commit()
    
    return {
        'id': wh.id,
        'url': wh.url,
        'events': [e.value for e in webhook.events],
        'secret': wh.secret,
        'is_active': wh.is_active,
        'created_at': wh.created_at.isoformat()
    }


@router.get("/webhooks")
async def list_webhooks(
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """List user's webhooks"""
    
    webhooks = db.query(Webhook).filter(
        Webhook.user_id == current_user.id
    ).all()
    
    return {
        'webhooks': [
            {
                'id': wh.id,
                'url': wh.url,
                'events': json.loads(wh.events),
                'description': wh.description,
                'is_active': wh.is_active,
                'created_at': wh.created_at.isoformat(),
                'last_delivery': wh.last_delivery.isoformat() if wh.last_delivery else None
            }
            for wh in webhooks
        ]
    }


@router.put("/webhooks/{webhook_id}")
async def update_webhook(
    webhook_id: int,
    update: WebhookUpdate,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update webhook"""
    
    webhook = db.query(Webhook).filter(
        and_(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        )
    ).first()
    
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    if update.url:
        webhook.url = str(update.url)
    if update.events is not None:
        webhook.events = json.dumps([e.value for e in update.events])
    if update.is_active is not None:
        webhook.is_active = update.is_active
    if update.description is not None:
        webhook.description = update.description
    
    db.commit()
    
    return {'success': True, 'message': 'Webhook updated'}


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete webhook"""
    
    webhook = db.query(Webhook).filter(
        and_(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        )
    ).first()
    
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    db.delete(webhook)
    db.commit()
    
    return {'success': True, 'message': 'Webhook deleted'}


@router.get("/webhooks/{webhook_id}/deliveries")
async def get_webhook_deliveries(
    webhook_id: int,
    limit: int = 50,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get webhook delivery history"""
    
    webhook = db.query(Webhook).filter(
        and_(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        )
    ).first()
    
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    deliveries = db.query(WebhookDelivery).filter(
        WebhookDelivery.webhook_id == webhook_id
    ).order_by(WebhookDelivery.delivered_at.desc()).limit(limit).all()
    
    return {
        'deliveries': [
            {
                'id': d.id,
                'event': d.event,
                'status_code': d.status_code,
                'success': d.success,
                'response_body': d.response_body,
                'error_message': d.error_message,
                'delivered_at': d.delivered_at.isoformat(),
                'duration_ms': d.duration_ms
            }
            for d in deliveries
        ]
    }


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(
    webhook_id: int,
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Test webhook delivery"""
    
    webhook = db.query(Webhook).filter(
        and_(
            Webhook.id == webhook_id,
            Webhook.user_id == current_user.id
        )
    ).first()
    
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    # Send test payload
    test_payload = {
        'event': 'webhook.test',
        'timestamp': datetime.utcnow().isoformat(),
        'data': {'message': 'This is a test webhook delivery'}
    }
    
    result = await _deliver_webhook(webhook, test_payload, db)
    
    return {
        'success': result['success'],
        'status_code': result.get('status_code'),
        'message': result.get('error') or 'Test webhook delivered successfully'
    }


async def _deliver_webhook(webhook: Webhook, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """Internal webhook delivery function"""
    
    import httpx
    
    # Create signature
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        webhook.secret.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        'Content-Type': 'application/json',
        'X-Lynx-Signature': signature,
        'X-Lynx-Event': payload.get('event', 'unknown')
    }
    
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook.url, json=payload, headers=headers)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log delivery
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                event=payload.get('event'),
                payload=payload_json,
                status_code=response.status_code,
                response_body=response.text[:1000],  # Limit size
                success=200 <= response.status_code < 300,
                duration_ms=duration_ms,
                delivered_at=datetime.utcnow()
            )
            db.add(delivery)
            
            webhook.last_delivery = datetime.utcnow()
            db.commit()
            
            return {
                'success': delivery.success,
                'status_code': response.status_code
            }
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log failed delivery
        delivery = WebhookDelivery(
            webhook_id=webhook.id,
            event=payload.get('event'),
            payload=payload_json,
            status_code=0,
            success=False,
            error_message=str(e),
            duration_ms=duration_ms,
            delivered_at=datetime.utcnow()
        )
        db.add(delivery)
        db.commit()
        
        return {'success': False, 'error': str(e)}
