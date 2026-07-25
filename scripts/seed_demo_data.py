#!/usr/bin/env python
"""
种子数据脚本 — 为演示环境准备测试数据
用法: PYTHONPATH="" .venv/Scripts/python scripts/seed_demo_data.py

检查数据库已有数据，不足时补充演示数据。
"""
import sys
import os

# 修复 sys.path — 优先使用项目 .venv
_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_proj, ".venv", "Lib", "site-packages")
for p in list(sys.path):
    if _venv_sp in p: sys.path.remove(p)
sys.path.insert(0, _venv_sp)
if _proj in sys.path: sys.path.remove(_proj)
sys.path.insert(1, _proj)

import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.models import User, Course, Enrollment, Assignment, Submission
from app.middleware.auth import hash_password


async def ensure_users():
    """确保演示用户存在"""
    async with async_session_factory() as db:
        demo_users = [
            {"username": "admin", "password": "admin123", "role": "ADMIN", "display_name": "系统管理员"},
            {"username": "teacher1", "password": "teacher123", "role": "TEACHER", "display_name": "张教授"},
            {"username": "teacher2", "password": "teacher123", "role": "TEACHER", "display_name": "李老师"},
            {"username": "student1", "password": "student123", "role": "STUDENT", "display_name": "王小明"},
            {"username": "student2", "password": "student123", "role": "STUDENT", "display_name": "赵小红"},
            {"username": "student3", "password": "student123", "role": "STUDENT", "display_name": "陈小华"},
        ]

        created = 0
        for u in demo_users:
            result = await db.execute(select(User).where(User.username == u["username"]))
            if result.scalar_one_or_none() is None:
                user = User(
                    username=u["username"],
                    password=hash_password(u["password"]),
                    display_name=u["display_name"],
                    role=u["role"],
                    enabled=True,
                    created_at=datetime.now(),
                )
                db.add(user)
                created += 1
                print(f"  👤 创建用户: {u['username']} ({u['role']})")

        await db.commit()
        if created == 0:
            print("  ✅ 所有用户已存在")
        return created


async def ensure_courses():
    """确保演示课程存在"""
    async with async_session_factory() as db:
        # 获取教师
        t1 = (await db.execute(select(User).where(User.username == "teacher1"))).scalar_one_or_none()
        t2 = (await db.execute(select(User).where(User.username == "teacher2"))).scalar_one_or_none()
        if not t1 or not t2:
            print("  ⚠️ 教师用户不存在，请先执行 ensure_users")
            return 0

        demo_courses = [
            {"name": "Python 程序设计", "description": "从零开始学习 Python 编程语言，涵盖基础语法、数据结构、面向对象编程等核心内容。", "schedule": "周一 3-4 节", "credits": 3, "max_students": 60, "category": "专业课", "teacher_id": t1.id},
            {"name": "数据结构与算法", "description": "学习常见数据结构和经典算法，包括数组、链表、树、图、排序、搜索等。", "schedule": "周三 1-2 节", "credits": 4, "max_students": 50, "category": "专业核心课", "teacher_id": t1.id},
            {"name": "数据库原理与应用", "description": "关系数据库设计、SQL 语言、事务管理、索引优化等。", "schedule": "周五 5-6 节", "credits": 3, "max_students": 55, "category": "专业核心课", "teacher_id": t2.id},
        ]

        created = 0
        course_ids = []
        for c in demo_courses:
            result = await db.execute(select(Course).where(Course.name == c["name"]))
            if result.scalar_one_or_none() is None:
                course = Course(
                    name=c["name"], description=c["description"], schedule=c["schedule"],
                    credits=c["credits"], max_students=c["max_students"],
                    category=c["category"], teacher_id=c["teacher_id"],
                    enrolled_count=0, visible=True, created_at=datetime.now(),
                )
                db.add(course)
                await db.flush()
                course_ids.append(course.id)
                created += 1
                print(f"  📚 创建课程: {c['name']}")
            else:
                existing = result.scalar_one()
                course_ids.append(existing.id)

        await db.commit()
        if created == 0:
            print("  ✅ 所有课程已存在")
        return course_ids


async def ensure_enrollments(course_ids):
    """确保选课记录存在"""
    async with async_session_factory() as db:
        students = (await db.execute(
            select(User).where(User.role == "STUDENT")
        )).scalars().all()

        created = 0
        for s in students:
            for cid in course_ids[:2]:  # 每个学生选前2门课
                result = await db.execute(
                    select(Enrollment).where(
                        Enrollment.course_id == cid,
                        Enrollment.student_id == s.id,
                    )
                )
                if result.scalar_one_or_none() is None:
                    enrollment = Enrollment(
                        course_id=cid, student_id=s.id,
                        enrolled_at=datetime.now(), score=0,
                        base_score=0, peer_review_bonus=0,
                    )
                    db.add(enrollment)

                    # 更新课程人数
                    course = await db.execute(select(Course).where(Course.id == cid))
                    course_obj = course.scalar_one_or_none()
                    if course_obj:
                        course_obj.enrolled_count += 1
                    created += 1

        await db.commit()
        print(f"  📝 创建 {created} 条选课记录")


async def ensure_assignments(course_ids):
    """确保演示作业存在"""
    async with async_session_factory() as db:
        teacher = (await db.execute(select(User).where(User.username == "teacher1"))).scalar_one_or_none()

        demo_assignments = [
            {"course_id": course_ids[0], "title": "第一次实验报告", "description": "完成 Python 基础语法练习，包括变量、数据类型、条件判断和循环。提交 PDF 格式的实验报告。", "due_date": datetime.now() + timedelta(days=7), "total_points": 100},
            {"course_id": course_ids[0], "title": "第二次作业：函数与模块", "description": "编写一个计算器程序，支持加减乘除和括号运算。提交源代码和运行截图。", "due_date": datetime.now() + timedelta(days=14), "total_points": 100},
            {"course_id": course_ids[1], "title": "链表操作实验", "description": "实现单向链表和双向链表的创建、插入、删除、查找操作，分析时间复杂度。", "due_date": datetime.now() + timedelta(days=10), "total_points": 100},
        ]

        created = 0
        assignment_ids = []
        for a in demo_assignments:
            result = await db.execute(
                select(Assignment).where(
                    Assignment.course_id == a["course_id"],
                    Assignment.title == a["title"],
                )
            )
            if result.scalar_one_or_none() is None:
                assignment = Assignment(
                    course_id=a["course_id"], title=a["title"],
                    description=a["description"], due_date=a["due_date"],
                    total_points=a["total_points"], teacher_id=teacher.id,
                    created_at=datetime.now(),
                )
                db.add(assignment)
                await db.flush()
                assignment_ids.append(assignment.id)
                created += 1
                print(f"  📄 创建作业: {a['title']}")

        await db.commit()
        if created == 0:
            print("  ✅ 所有作业已存在")
        return assignment_ids


async def ensure_submissions(assignment_ids):
    """为每个作业创建演示提交"""
    async with async_session_factory() as db:
        students = (await db.execute(
            select(User).where(User.role == "STUDENT")
        )).scalars().all()

        submission_contents = [
            "本次实验完成了 Python 基础语法的练习，包括变量声明、数据类型转换、条件判断语句和循环结构。通过实验掌握了 Python 的基本编程范式。",
            "实现了计算器程序，支持加减乘除四则运算以及括号优先级。使用了函数模块化设计，主函数负责输入解析，各运算函数分别实现。",
            "实现了单向链表和双向链表的全部操作。单向链表每个节点包含数据和 next 指针；双向链表额外包含 prev 指针。插入和删除操作的时间复杂度为 O(n)。",
        ]

        created = 0
        for i, aid in enumerate(assignment_ids[:3]):
            for j, s in enumerate(students):
                result = await db.execute(
                    select(Submission).where(
                        Submission.assignment_id == aid,
                        Submission.student_id == s.id,
                    )
                )
                if result.scalar_one_or_none() is None:
                    content_idx = i % len(submission_contents)
                    submission = Submission(
                        assignment_id=aid, student_id=s.id,
                        content=submission_contents[content_idx],
                        status="SUBMITTED",
                        submitted_at=datetime.now() - timedelta(hours=2),
                    )
                    db.add(submission)
                    created += 1

        await db.commit()
        print(f"  📝 创建 {created} 条提交记录")


async def main():
    print("=" * 50)
    print("🌱 EduAgent 种子数据初始化")
    print("=" * 50)
    
    print("\n[1/5] 检查演示用户...")
    await ensure_users()
    
    print("\n[2/5] 检查演示课程...")
    course_ids = await ensure_courses()
    
    print("\n[3/5] 检查选课记录...")
    await ensure_enrollments(course_ids)
    
    print("\n[4/5] 检查演示作业...")
    assignment_ids = await ensure_assignments(course_ids)
    
    print("\n[5/5] 检查提交记录...")
    await ensure_submissions(assignment_ids)
    
    print("\n" + "=" * 50)
    print("✅ 种子数据初始化完成！")
    print("=" * 50)
    print("演示账号:")
    print("  管理员: admin / admin123")
    print("  教师:   teacher1 / teacher123")
    print("  学生:   student1 / student123")


if __name__ == "__main__":
    asyncio.run(main())
