#!/usr/bin/env python
"""
重置演示环境账号数据。

用法:
    python scripts/seed_demo_data.py

执行后会清空现有账号及其关联的课程、作业、提交、通知、AI 运行记录等
业务数据，然后只创建指定的三类演示账号。
"""
import asyncio
import os
import sys
from datetime import datetime


# 修复 sys.path - 优先使用项目 .venv
_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for p in list(sys.path):
    if _venv_sp in p:
        sys.path.remove(p)
sys.path.insert(0, _venv_sp)
if _proj in sys.path:
    sys.path.remove(_proj)
sys.path.insert(1, _proj)

from sqlalchemy import delete, inspect

from app.database import async_session_factory
from app.middleware.auth import hash_password
from app.models.ai_models import (
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
        "username": "yadmin",
        "password": "yadmin666",
        "role": "ADMIN",
        "display_name": "系统管理员",
    },
    {
        "username": "yteacher1",
        "password": "yteacher666",
        "role": "TEACHER",
        "display_name": "演示教师",
    },
    {
        "username": "ystudent1",
        "password": "ystudent666",
        "role": "STUDENT",
        "display_name": "演示学生",
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
    """清空账号及其关联业务数据。"""
    async with async_session_factory() as db:
        for model in DELETE_ORDER:
            exists = await db.run_sync(
                lambda session, table_name: inspect(session.connection()).has_table(table_name),
                model.__tablename__,
            )
            if not exists:
                print(f"  已跳过: {model.__tablename__} 不存在")
                continue
            await db.execute(delete(model))
            print(f"  已清空: {model.__tablename__}")
        await db.commit()


async def create_demo_users() -> None:
    """创建新的演示账号。"""
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
            print(f"  已创建账号: {item['username']} ({item['role']})")
        await db.commit()


async def main() -> None:
    print("=" * 50)
    print("EduAgent 演示账号数据重置")
    print("=" * 50)

    print("\n[1/2] 清空账号及关联业务数据...")
    await reset_database_data()

    print("\n[2/2] 创建新的演示账号...")
    await create_demo_users()

    print("\n" + "=" * 50)
    print("重置完成。演示账号不会在首页显示，请仅向授权测试者单独提供。")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
