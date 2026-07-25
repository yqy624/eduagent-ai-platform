"""通知发送工具（Agent 可用）"""
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Notification


class NotificationTools:
    """Agent 可调用的通知工具"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def send_notification(
        self,
        recipient_username: str,
        title: str,
        content: str,
        category: str = "SYSTEM",
        link: Optional[str] = None,
    ) -> dict:
        """发送通知给用户"""
        notification = Notification(
            recipient=recipient_username,
            title=title,
            content=content,
            category=category,
            link=link,
            is_read=False,
            created_at=datetime.now(),
        )
        self.db.add(notification)
        await self.db.flush()
        return {
            "id": notification.id,
            "title": title,
            "content": content,
            "created_at": notification.created_at.isoformat()
            if notification.created_at else None,
        }

    async def get_unread_count(self, username: str) -> int:
        """获取未读通知数"""
        from sqlalchemy import select, func
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.recipient == username,
                Notification.is_read == False,
            )
        )
        return result.scalar() or 0
