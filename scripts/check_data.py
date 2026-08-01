#!/usr/bin/env python
"""Inspect demo data in the configured database."""
import asyncio
import os
import sys

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for path in list(sys.path):
    if _venv_sp in path:
        sys.path.remove(path)
sys.path.insert(0, _venv_sp)
if _proj in sys.path:
    sys.path.remove(_proj)
sys.path.insert(1, _proj)

from sqlalchemy import select

from app.database import async_session_factory, engine
from app.models.models import Assignment, Course, Submission, User


async def check() -> None:
    try:
        async with async_session_factory() as db:
            teacher = (
                await db.execute(select(User).where(User.username == "teacher1"))
            ).scalar_one_or_none()
            if teacher is None:
                print("Teacher account teacher1 was not found. Run scripts/seed_demo_data.py first.")
            else:
                print(f"Teacher: id={teacher.id}, display={teacher.display_name}")

            courses = (await db.execute(select(Course))).scalars().all()
            print("\nAll courses:")
            for course in courses:
                print(f"  [{course.id}] {course.name} (teacher_id={course.teacher_id})")
                assignments = (
                    await db.execute(select(Assignment).where(Assignment.course_id == course.id))
                ).scalars().all()
                print(f"    Assignments: {len(assignments)}")
                for assignment in assignments:
                    submissions = (
                        await db.execute(select(Submission).where(Submission.assignment_id == assignment.id))
                    ).scalars().all()
                    print(f"      [{assignment.id}] {assignment.title} - {len(submissions)} subs")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())
