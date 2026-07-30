"""Notification persistence and WebSocket fan-out helpers."""
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Enrollment, Notification, User
from app.services.notification_hub import notification_hub


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def to_payload(item: Notification) -> dict:
        created_at = item.created_at.isoformat() if item.created_at else None
        return {
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "category": item.category,
            "type": item.type,
            "link": item.link,
            "read": bool(item.is_read),
            "created_at": created_at,
            "createdAt": created_at,
        }

    async def create_for_usernames(
        self,
        recipients: Iterable[str],
        title: str,
        content: str,
        *,
        category: str = "SYSTEM",
        type_: str = "INFO",
        link: Optional[str] = None,
    ) -> list[Notification]:
        unique_recipients = sorted({name for name in recipients if name})
        if not unique_recipients:
            return []

        now = datetime.now()
        items = [
            Notification(
                recipient=username,
                title=title,
                content=content,
                category=category,
                type=type_,
                link=link,
                is_read=False,
                created_at=now,
            )
            for username in unique_recipients
        ]
        self.db.add_all(items)
        await self.db.flush()
        for item in items:
            await notification_hub.publish(item.recipient, self.to_payload(item))
        return items

    async def create_for_roles(
        self,
        roles: Iterable[str],
        title: str,
        content: str,
        *,
        category: str = "SYSTEM",
        type_: str = "INFO",
        link: Optional[str] = None,
    ) -> list[Notification]:
        result = await self.db.execute(
            select(User.username).where(
                User.role.in_(list(roles)),
                User.enabled.is_(True),
            )
        )
        return await self.create_for_usernames(
            result.scalars().all(),
            title,
            content,
            category=category,
            type_=type_,
            link=link,
        )

    async def create_for_course_students(
        self,
        course_id: int,
        title: str,
        content: str,
        *,
        category: str = "COURSE",
        type_: str = "INFO",
        link: Optional[str] = None,
    ) -> list[Notification]:
        result = await self.db.execute(
            select(User.username)
            .join(Enrollment, Enrollment.student_id == User.id)
            .where(
                Enrollment.course_id == course_id,
                User.enabled.is_(True),
            )
        )
        return await self.create_for_usernames(
            result.scalars().all(),
            title,
            content,
            category=category,
            type_=type_,
            link=link,
        )

    async def create_for_user_ids(
        self,
        user_ids: Iterable[int],
        title: str,
        content: str,
        *,
        category: str = "SYSTEM",
        type_: str = "INFO",
        link: Optional[str] = None,
    ) -> list[Notification]:
        ids = sorted({int(user_id) for user_id in user_ids if user_id})
        if not ids:
            return []
        result = await self.db.execute(
            select(User.username).where(
                User.id.in_(ids),
                User.enabled.is_(True),
            )
        )
        return await self.create_for_usernames(
            result.scalars().all(),
            title,
            content,
            category=category,
            type_=type_,
            link=link,
        )
