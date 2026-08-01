"""Persistent short-term and long-term memory for EduAgent."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AiAgentMemory


class AgentMemoryStore:
    """Stores bounded, user-scoped memories instead of copying all chat logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def load(
        self,
        user_id: int,
        session_id: str,
        course_id: Optional[int],
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        scope = [AiAgentMemory.user_id == user_id]
        memory_scope = [
            AiAgentMemory.session_id == session_id,
            (
                AiAgentMemory.course_id == course_id
                if course_id is not None
                else AiAgentMemory.course_id.is_(None)
            ),
        ]
        result = await self.db.execute(
            select(AiAgentMemory)
            .where(*scope, and_(*memory_scope))
            .order_by(AiAgentMemory.created_at.desc(), AiAgentMemory.id.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        memories: List[Dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row.content_json)
            except (TypeError, ValueError):
                payload = {"text": row.content_json}
            memories.append(
                {
                    "id": row.id,
                    "type": row.memory_type,
                    "importance": row.importance,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    **payload,
                }
            )
        return memories

    async def remember_turn(
        self,
        user_id: int,
        session_id: str,
        course_id: Optional[int],
        question: str,
        answer: str,
        tool_names: List[str],
    ) -> AiAgentMemory:
        row = AiAgentMemory(
            user_id=user_id,
            course_id=course_id,
            session_id=session_id,
            memory_type="interaction",
            content_json=json.dumps(
                {
                    "question": question[:2000],
                    "answer": answer[:5000],
                    "tool_names": tool_names[:20],
                },
                ensure_ascii=False,
            ),
            importance=0.6,
            created_at=datetime.now(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def remember_fact(
        self,
        user_id: int,
        session_id: str,
        course_id: Optional[int],
        fact: str,
        importance: float = 0.8,
    ) -> AiAgentMemory:
        row = AiAgentMemory(
            user_id=user_id,
            course_id=course_id,
            session_id=session_id,
            memory_type="fact",
            content_json=json.dumps({"fact": fact[:1000]}, ensure_ascii=False),
            importance=max(0.0, min(1.0, importance)),
            created_at=datetime.now(),
        )
        self.db.add(row)
        await self.db.flush()
        return row
