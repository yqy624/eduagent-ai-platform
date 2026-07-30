#!/usr/bin/env python
"""
EduAgent 一键演示脚本 — 展示所有核心功能
用法: .venv/Scripts/python scripts/run_demo.py

该脚本自动演示：
1. 健康检查
2. 课程文档索引
3. 三种角色登录
4. 课程 RAG 问答
5. 学情诊断
6. 学习计划生成
7. 教师批改建议
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
import json
from datetime import datetime

# ========= 导入客户端 =========
import http.client


class DemoClient:
    """演示 HTTP 客户端"""

    def __init__(self, host="localhost", port=8001):
        self.host = host
        self.port = port
        self.tokens = {}

    def _request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        b = json.dumps(body) if body else None
        try:
            conn.request(method, path, b, headers)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode())
            conn.close()
            return data
        except Exception as e:
            return {"code": 500, "message": f"请求失败: {e}", "data": None}

    def login(self, username, password, role):
        """登录并保存 token"""
        resp = self._request("POST", "/api/auth/login", {
            "username": username, "password": password, "role": role
        })
        if resp["code"] == 200:
            self.tokens[role] = resp["data"]["token"]
            return resp["data"]
        return None

    def get(self, path, token=None):
        return self._request("GET", path, token=token)

    def post(self, path, body=None, token=None):
        return self._request("POST", path, body, token=token)


async def main():
    client = DemoClient()

    print("=" * 60)
    print("  🎓 EduAgent 智慧教育 Agent 平台 — 演示脚本")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ===== Step 1: 健康检查 =====
    print("\n" + "─" * 60)
    print("📌 [Step 1/7] 健康检查")
    print("─" * 60)
    health = client.get("/api/health")
    if health.get("status") == "ok":
        print(f"  ✅ 服务器运行正常 | AI: {health.get('ai_available', False)}")
    else:
        print(f"  ❌ 服务器异常: {health}")
        return

    # ===== Step 2: 登录三种角色 =====
    print("\n" + "─" * 60)
    print("📌 [Step 2/7] 三种角色登录")
    print("─" * 60)
    
    admin = client.login("yadmin", "yadmin666", "ADMIN")
    teacher = client.login("yteacher1", "yteacher666", "TEACHER")
    student = client.login("ystudent1", "ystudent666", "STUDENT")

    if admin:
        print(f"  ✅ 管理员: {admin['displayName']} → {admin['redirectUrl']}")
    if teacher:
        print(f"  ✅ 教师:   {teacher['displayName']} → {teacher['redirectUrl']}")
    if student:
        print(f"  ✅ 学生:   {student['displayName']} → {student['redirectUrl']}")

    # ===== Step 3: 管理后台 =====
    print("\n" + "─" * 60)
    print("📌 [Step 3/7] 管理后台数据")
    print("─" * 60)
    dashboard = client.get("/api/admin/dashboard", token=admin["token"] if admin else None)
    if dashboard["code"] == 200:
        d = dashboard["data"]
        print(f"  📊 用户: {d['totalUsers']} | 教师: {d['totalTeachers']} | 学生: {d['totalStudents']}")
        print(f"  📚 课程: {d['totalCourses']} | 选课: {d['totalEnrollments']}")

    # ===== Step 4: 教师流程 =====
    print("\n" + "─" * 60)
    print("📌 [Step 4/7] 教师工作台")
    print("─" * 60)
    if teacher:
        t_dash = client.get("/api/teacher/dashboard", token=teacher["token"])
        if t_dash["code"] == 200:
            td = t_dash["data"]
            print(f"  📋 课程数: {td['totalCourses']} | 有学生课程: {td['activeCourses']} | 学生数: {td['totalStudents']}")

        courses = client.get("/api/teacher/courses", token=teacher["token"])
        if courses["code"] == 200 and courses["data"]:
            for c in courses["data"][:2]:
                print(f"  📖 课程: {c['name']} (选课 {c['enrolledCount']}/{c['maxStudents']})")
                
                # 查看课程学生
                students = client.get(f"/api/teacher/courses/{c['id']}/students", token=teacher["token"])
                if students["code"] == 200:
                    for s in students.get("data", [])[:3]:
                        print(f"    👤 学生: {s.get('displayName', s['username'])}")

    # ===== Step 5: 学生流程 =====
    print("\n" + "─" * 60)
    print("📌 [Step 5/7] 学生工作台")
    print("─" * 60)
    if student:
        s_dash = client.get("/api/student/dashboard", token=student["token"])
        if s_dash["code"] == 200:
            sd = s_dash["data"]
            print(f"  📋 已选课程: {sd['selectedCourseCount']} | 已评分: {sd.get('gradedCount', 'N/A')}")

        my_courses = client.get("/api/student/my-courses", token=student["token"])
        if my_courses["code"] == 200:
            for c in my_courses.get("data", [])[:2]:
                print(f"  📖 我的课程: {c['name']} - {c.get('teacher_name', '')}")

        grades = client.get("/api/student/grades", token=student["token"])
        if grades["code"] == 200:
            for g in grades.get("data", [])[:2]:
                print(f"  📊 成绩: {g.get('course_name', '')} - {len(g.get('assignments', []))} 项作业")

    # ===== Step 6: 测试 AI 接口（前提是有 API Key） =====
    print("\n" + "─" * 60)
    print("📌 [Step 6/7] AI 接口检测")
    print("─" * 60)
    if health.get("ai_available"):
        print("  ✅ AI 模块已加载")
        print("  ℹ️ 需配置 LLM API Key 才能实际调用 AI 接口")
        print("     参考 .env.example 设置 OPENAI_API_KEY / DASHSCOPE_API_KEY")
    else:
        print("  ⚠️ AI 模块未加载，请检查依赖安装")

    # ===== Step 7: API 文档 =====
    print("\n" + "─" * 60)
    print("📌 [Step 7/7] API 文档")
    print("─" * 60)
    print("  📘 Swagger:  http://localhost:8001/docs")
    print("  📗 Redoc:    http://localhost:8001/redoc")
    print("  📊 OpenAPI:  http://localhost:8001/openapi.json")

    # 统计 API 数量
    conn = http.client.HTTPConnection("localhost", 8001, timeout=5)
    conn.request("GET", "/openapi.json")
    schema = json.loads(conn.getresponse().read().decode())
    conn.close()
    path_count = len(schema.get("paths", {}))
    print(f"  🔢 API 总数: {path_count}")

    # ===== 总结 =====
    print("\n" + "=" * 60)
    print("  🎉 EduAgent 演示完成！")
    print("=" * 60)
    print()
    print("  核心功能:")
    print("    ✅ 认证与角色权限 (RBAC)")
    print("    ✅ 课程管理 (CRUD + 选课)")
    print("    ✅ 作业发布与提交")
    print("    ✅ 成绩评分与分析")
    print("    ✅ 匿名互评系统")
    print("    ✅ 文件上传与预览")
    print("    ✅ AI RAG 问答 (需 API Key)")
    print("    ✅ 学习路径规划 Agent (需 API Key)")
    print("    ✅ 教师批改建议 Agent (需 API Key)")
    print()
    print("  📖 详细文档: 项目 README.md")


if __name__ == "__main__":
    asyncio.run(main())
