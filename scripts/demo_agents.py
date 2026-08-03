"""
AI 三闭环演示脚本
"""
import http.client, json, time

HOST = "localhost"
PORT = 8001

def req(method, path, body=None, token=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=120)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body:
        conn.request(method, path, json.dumps(body), headers)
    else:
        conn.request(method, path, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    return data

print("=" * 60)
print("🤖 演示: EduAgent 三个 AI 闭环")
print("=" * 60)

# 1. 登录
admin = req("POST", "/api/auth/login", {"username": "yadmin", "password": "yadmin666", "role": "ADMIN"})
adm_tok = admin["data"]["token"]
print(f"\n✅ 管理员登录成功")

teacher = req("POST", "/api/auth/login", {"username": "yteacher1", "password": "yteacher666", "role": "TEACHER"})
tch_tok = teacher["data"]["token"]
print(f"✅ 教师登录成功")

# === Agent 1: RAG 问答 ===
print("\n" + "─" * 60)
print("📚 [Agent 1] 课程 RAG 问答 → POST /api/ai/courses/4/qa")
print("─" * 60)

qa = req("POST", "/api/ai/courses/4/qa", {"question": "Python 课程讲什么内容？"}, token=adm_tok)
print(f"状态码: {qa['code']}")

answer = qa["data"]["answer"]
citations = qa["data"]["citations"]
confidence = qa["data"]["confidence"]

print(f"置信度: {confidence}")
if citations:
    print(f"引用来源: {citations[0]['source']}")
print(f"回答预览: {answer[:200]}...")

# === Agent 2: 学情诊断 + 学习路径 ===
print("\n" + "─" * 60)
print("🎯 [Agent 2] 学情诊断 + 学习路径 (LangChain)")
print("─" * 60)

print("\n[2a] 学情诊断...")
diag = req("POST", "/api/ai/students/4/diagnosis", {"course_id": 4}, token=tch_tok)
print(f"状态: {diag['code']}")
if diag["code"] == 200:
    d = diag["data"]
    print(f"  薄弱点: {d['weakness']}")
    print(f"  证据: {d['evidence']}")

print("\n[2b] 学习路径（LangChain Agent）...")
plan = req("POST", "/api/ai/students/4/learning-plan?course_id=4", token=tch_tok)
print(f"状态: {plan['code']}")
if plan["code"] == 200:
    p = plan["data"]
    print(f"  总时长: {p['totalHours']}h")
    print(f"  每日任务: {len(p['dailyTasks'])} 天")
    for t in p["dailyTasks"][:2]:
        print(f"    📅 {t['day']}: {t['focus']} ({t['durationHours']}h)")
    print(f"  练习题: {len(p['exercises'])} 道")
    print(f"  薄弱分析: {p['weaknessSummary'][:100]}")

# === Agent 3: 批改建议 ===
print("\n" + "─" * 60)
print("✍️ [Agent 3] 教师批改建议 (Human-in-the-loop)")
print("─" * 60)

grade = req("POST", "/api/ai/teacher/submissions/1/grade-suggestion", token=tch_tok)
print(f"状态: {grade['code']}")
if grade["code"] == 200:
    g = grade["data"]
    print(f"  建议分数: {g['suggestedScore']}")
    print(f"  评分标准: {json.dumps(g['rubric'], ensure_ascii=False)[:100]}")
    print(f"  优点: {g['strengths']}")
    print(f"  改进: {g['weaknesses']}")
    print(f"  风险: {g['risks']}")
    print(f"  评语预览: {g['comment'][:150]}...")

print("\n" + "=" * 60)
print("✅ 三个 Agent 闭环演示完成！")
print("=" * 60)
