"""
Real-Time Communication
WebSocket support, live console streaming, real-time notifications
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Set
from datetime import datetime
import json
import asyncio

from database import get_db
from models import User, Notification
from auth import get_current_user

router = APIRouter(prefix="/realtime", tags=["realtime"])


# ==================== WebSocket Connection Manager ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.console_subscribers: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        # Remove from console subscriptions
        for server_name in list(self.console_subscribers.keys()):
            self.console_subscribers[server_name].discard(websocket)
    
    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)
    
    async def broadcast(self, message: dict):
        for connections in self.active_connections.values():
            for connection in connections:
                await connection.send_json(message)
    
    async def broadcast_to_server(self, server_name: str, message: dict):
        if server_name in self.console_subscribers:
            for websocket in self.console_subscribers[server_name]:
                await websocket.send_json(message)
    
    def subscribe_to_console(self, websocket: WebSocket, server_name: str):
        if server_name not in self.console_subscribers:
            self.console_subscribers[server_name] = set()
        self.console_subscribers[server_name].add(websocket)
    
    def unsubscribe_from_console(self, websocket: WebSocket, server_name: str):
        if server_name in self.console_subscribers:
            self.console_subscribers[server_name].discard(websocket)


manager = ConnectionManager()


# ==================== WebSocket Endpoints ====================

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """Main WebSocket connection for real-time updates"""
    
    # Authenticate user from token
    from auth import verify_token
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=1008)
        return
    
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get('type') == 'ping':
                await websocket.send_json({'type': 'pong'})
            
            elif message.get('type') == 'subscribe_console':
                server_name = message.get('server_name')
                if server_name:
                    manager.subscribe_to_console(websocket, server_name)
                    await websocket.send_json({
                        'type': 'subscribed',
                        'server_name': server_name
                    })
            
            elif message.get('type') == 'unsubscribe_console':
                server_name = message.get('server_name')
                if server_name:
                    manager.unsubscribe_from_console(websocket, server_name)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)


@router.websocket("/console/{server_name}")
async def console_stream(websocket: WebSocket, server_name: str, token: str):
    """Stream console output for a specific server"""
    
    from auth import verify_token
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    manager.subscribe_to_console(websocket, server_name)
    
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(1)
    
    except WebSocketDisconnect:
        manager.unsubscribe_from_console(websocket, server_name)


# ==================== Notification System ====================

@router.get("/notifications")
async def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user notifications"""
    
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    
    return {
        'notifications': [
            {
                'id': n.id,
                'type': n.notification_type,
                'title': n.title,
                'message': n.message,
                'data': n.data,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat()
            }
            for n in notifications
        ]
    }


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark notification as read"""
    
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.commit()
    
    return {'success': True}


@router.post("/notifications/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark all notifications as read"""
    
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).update({'is_read': True, 'read_at': datetime.utcnow()})
    
    db.commit()
    
    return {'success': True}


# ==================== Event Broadcasting ====================

async def broadcast_event(event_type: str, data: dict, user_id: int = None):
    """Broadcast event to connected clients"""
    
    message = {
        'type': 'event',
        'event': event_type,
        'data': data,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    if user_id:
        await manager.send_personal_message(message, user_id)
    else:
        await manager.broadcast(message)


async def broadcast_console_output(server_name: str, line: str):
    """Broadcast console output to subscribers"""
    
    message = {
        'type': 'console',
        'server_name': server_name,
        'line': line,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    await manager.broadcast_to_server(server_name, message)
