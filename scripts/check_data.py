#!/usr/bin/env python
"""查看数据库数据分布"""
import sys, os
_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for p in list(sys.path):
    if _venv_sp in p: sys.path.remove(p)
sys.path.insert(0, _venv_sp)
sys.path.insert(1, _proj)

import asyncio
from app.database import async_session_factory
from app.models.models import User, Course, Assignment, Submission
from sqlalchemy import select

async def check():
    async with async_session_factory() as db:
        t = (await db.execute(select(User).where(User.username == "yteacher1"))).scalar_one()
        print(f"Teacher: id={t.id}, display={t.display_name}")
        
        courses = (await db.execute(select(Course))).scalars().all()
        print(f"\nAll courses:")
        for c in courses:
            print(f"  [{c.id}] {c.name} (teacher_id={c.teacher_id})")
            ass = (await db.execute(select(Assignment).where(Assignment.course_id == c.id))).scalars().all()
            print(f"    Assignments: {len(ass)}")
            for a in ass:
                subs = (await db.execute(select(Submission).where(Submission.assignment_id == a.id))).scalars().all()
                print(f"      [{a.id}] {a.title} - {len(subs)} subs")

asyncio.run(check())
