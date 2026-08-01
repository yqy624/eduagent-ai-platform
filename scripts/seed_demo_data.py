#!/usr/bin/env python
"""Reset demo data and seed stable demo accounts."""
import asyncio
import os
import sys
from datetime import datetime

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for path in list(sys.path):
    if _venv_sp in path:
        sys.path.remove(path)
sys.path.insert(0, _venv_sp)
if _proj in sys.path:
    sys.path.remove(_proj)
sys.path.insert(1, _proj)

from sqlalchemy import delete, inspect

from app.database import async_session_factory
from app.middleware.auth import hash_password
from app.models.ai_models import (
    AiAgentMemory,
    AiDocumentChunk,
    AiEvalResult,
    AiGradingSuggestion,
    AiIndexJob,
    AiLearningReport,
    AiQaLog,
    AiRun,
    AiToolCall,
)
from app.models.models import (
    Assignment,
    AuditLog,
    Course,
    Enrollment,
    Notification,
    PeerReview,
    PublishedActivity,
    StoredFile,
    Submission,
    TeacherCommentMemory,
    TeacherCommentUsageHistory,
    User,
)


DEMO_USERS = [
    {
        "username": "admin",
        "password": "admin666",
        "role": "ADMIN",
        "display_name": "System Admin",
    },
    {
        "username": "teacher1",
        "password": "teacher666",
        "role": "TEACHER",
        "display_name": "Demo Teacher",
    },
    {
        "username": "student1",
        "password": "student666",
        "role": "STUDENT",
        "display_name": "Demo Student",
    },
]


DELETE_ORDER = [
    AiToolCall,
    AiGradingSuggestion,
    AiLearningReport,
    AiQaLog,
    AiDocumentChunk,
    AiIndexJob,
    AiEvalResult,
    AiAgentMemory,
    TeacherCommentUsageHistory,
    TeacherCommentMemory,
    PeerReview,
    Submission,
    Assignment,
    Enrollment,
    StoredFile,
    Course,
    Notification,
    PublishedActivity,
    AuditLog,
    AiRun,
    User,
]


async def reset_database_data() -> None:
    async with async_session_factory() as db:
        for model in DELETE_ORDER:
            exists = await db.run_sync(lambda session: inspect(session.connection()).has_table(model.__tablename__))
            if not exists:
                print(f"Skipping missing table: {model.__tablename__}")
                continue
            await db.execute(delete(model))
            print(f"Cleared: {model.__tablename__}")
        await db.commit()


async def create_demo_users() -> None:
    async with async_session_factory() as db:
        now = datetime.now()
        for item in DEMO_USERS:
            db.add(
                User(
                    username=item["username"],
                    password=hash_password(item["password"]),
                    display_name=item["display_name"],
                    email=None,
                    role=item["role"],
                    enabled=True,
                    created_at=now,
                )
            )
            print(f"Created: {item['username']} ({item['role']})")
        await db.commit()


async def main() -> None:
    print("=" * 50)
    print("EduAgent demo account reset")
    print("=" * 50)
    print("\n[1/2] Clearing demo data...")
    await reset_database_data()
    print("\n[2/2] Seeding demo users...")
    await create_demo_users()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
