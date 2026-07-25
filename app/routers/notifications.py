"""Notification REST and WebSocket endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import decode_access_token, get_current_user
from app.models.models import Notification, User
from app.schemas.common import ApiResponse
from app.services.notification_hub import notification_hub

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
ws_router = APIRouter(tags=["notifications"])


def notification_payload(item: Notification) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "category": item.category,
        "type": item.type,
        "link": item.link,
        "read": bool(item.is_read),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("")
async def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Notification)
        .where(Notification.recipient == user.username)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    result = await db.execute(query)
    return ApiResponse.ok(data=[notification_payload(item) for item in result.scalars().all()])


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification.id).where(
            Notification.recipient == user.username,
            Notification.is_read.is_(False),
        )
    )
    return ApiResponse.ok(data={"count": len(result.scalars().all())})


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient == user.username,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    item.is_read = True
    await db.flush()
    return ApiResponse.ok(data=notification_payload(item))


@router.put("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(
            Notification.recipient == user.username,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.flush()
    return ApiResponse.ok(message="通知已全部标记为已读")


@ws_router.websocket("/ws/notifications")
async def notifications_websocket(websocket: WebSocket):
    token: Optional[str] = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="缺少认证令牌")
        return
    try:
        username = decode_access_token(token).get("sub")
    except HTTPException:
        await websocket.close(code=1008, reason="认证令牌无效")
        return
    if not username:
        await websocket.close(code=1008, reason="认证令牌无效")
        return

    await notification_hub.connect(username, websocket)
    await websocket.send_json({"type": "CONNECTED"})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_hub.disconnect(username, websocket)
    except Exception:
        notification_hub.disconnect(username, websocket)
