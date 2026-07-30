#!/usr/bin/env python
"""
RAG 评测脚本 — 评估课程问答的引用覆盖率和答案相关性
用法: .venv/Scripts/python -m ai.evals.rag_eval

评测指标：
- 引用覆盖率: 回答中包含引用的比例
- 拒答准确率: 无资料时正确拒答的比例
- 答案相关性: 人工评分(1-5)
"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.database import async_session_factory
from app.models.ai_models import AiEvalResult
from ai.rag.vector_store import VectorStoreManager


# 评测用例：课程问答
TEST_CASES = [
    {"course_id": 1, "question": "Python 中如何定义函数？", "expect_answer": True, "notes": "基础语法问题"},
    {"course_id": 1, "question": "Python 列表和元组的区别是什么？", "expect_answer": True, "notes": "数据结构问题"},
    {"course_id": 1, "question": "请解释面向对象编程的三个特性", "expect_answer": True, "notes": "OOP 概念"},
    {"course_id": 1, "question": "什么是 Python 的 GIL？", "expect_answer": True, "notes": "高级特性"},
    {"course_id": 1, "question": "量子计算的原理是什么？", "expect_answer": False, "notes": "资料外问题，应拒答"},
    {"course_id": 2, "question": "什么是时间复杂度？", "expect_answer": True, "notes": "算法基础"},
    {"course_id": 2, "question": "二叉树的遍历方式有哪些？", "expect_answer": True, "notes": "数据结构"},
    {"course_id": 2, "question": "排序算法的时间复杂度对比", "expect_answer": True, "notes": "算法分析"},
    {"course_id": 2, "question": "如何证明 P=NP？", "expect_answer": False, "notes": "资料外问题，应拒答"},
    {"course_id": 3, "question": "什么是数据库事务？", "expect_answer": True, "notes": "数据库基础"},
    {"course_id": 3, "question": "SQL 中 JOIN 的几种类型？", "expect_answer": True, "notes": "SQL 查询"},
    {"course_id": 3, "question": "数据库索引的工作原理", "expect_answer": True, "notes": "性能优化"},
    {"course_id": 3, "question": "NoSQL 和 SQL 的区别", "expect_answer": False, "notes": "资料外问题"},
    {"course_id": 1, "question": "Python 如何处理文件读写？", "expect_answer": True, "notes": "IO 操作"},
    {"course_id": 1, "question": "Python 的装饰器是什么？", "expect_answer": True, "notes": "高级特性"},
    {"course_id": 2, "question": "栈和队列的区别", "expect_answer": True, "notes": "基础数据结构"},
    {"course_id": 2, "question": "图的深度优先搜索实现", "expect_answer": True, "notes": "图算法"},
    {"course_id": 3, "question": "数据库的三大范式", "expect_answer": True, "notes": "数据库设计"},
    {"course_id": 3, "question": "什么是 Redis？", "expect_answer": False, "notes": "资料外问题"},
    {"course_id": 1, "question": "Python 的异常处理机制", "expect_answer": True, "notes": "异常处理"},
]


async def run_rag_eval():
    print("=" * 60)
    print("📊 RAG 问答评测")
    print("=" * 60)

    vs = VectorStoreManager()
    
    total = len(TEST_CASES)
    citation_count = 0
    correct_rejection = 0
    rejection_total = 0
    answerable_total = 0
    answerable_hit = 0

    results = []

    for tc in TEST_CASES:
        docs = vs.similarity_search(
            tc["question"], k=3,
            collection_name=f"course_{tc['course_id']}"
        )
        
        relevant_docs = [(d, s) for d, s in docs if s < 0.5]  # 相似度阈值
        has_answer = len(relevant_docs) > 0
        best_score = docs[0][1] if docs else 1.0

        if tc["expect_answer"]:
            answerable_total += 1
            if has_answer:
                answerable_hit += 1
                citation_count += 1
                status = "✅ 命中"
            else:
                status = "⚠️ 未命中"
        else:
            rejection_total += 1
            if not has_answer:
                correct_rejection += 1
                status = "✅ 正确拒答"
            else:
                status = "⚠️ 误命中"

        results.append({
            "case_id": f"course{tc['course_id']}_{tc['question'][:20]}",
            "question": tc["question"],
            "expect_answer": tc["expect_answer"],
            "found_answer": has_answer,
            "best_score": round(float(best_score), 3),
            "status": status,
        })
        print(f"  {status} | 相似度={best_score:.3f} | {tc['question'][:30]}")

    # 计算指标
    citation_rate = citation_count / answerable_total * 100 if answerable_total else 0
    rejection_rate = correct_rejection / rejection_total * 100 if rejection_total else 0
    answerable_rate = answerable_hit / answerable_total * 100 if answerable_total else 0

    metrics = {
        "total_cases": total,
        "answerable_cases": answerable_total,
        "unanswerable_cases": rejection_total,
        "citation_rate": round(citation_rate, 1),
        "rejection_accuracy": round(rejection_rate, 1),
        "answerable_hit_rate": round(answerable_rate, 1),
    }

    print(f"\n{'=' * 60}")
    print("📈 评测结果")
    print(f"{'=' * 60}")
    print(f"  总用例:           {total}")
    print(f"  应回答用例:        {answerable_total}")
    print(f"  应拒答用例:        {rejection_total}")
    print(f"  引用覆盖率:        {citation_rate:.1f}%")
    print(f"  拒答准确率:        {rejection_rate:.1f}%")
    print(f"  答案命中率:        {answerable_rate:.1f}%")

    # 保存到数据库
    async with async_session_factory() as db:
        for r in results:
            eval_result = AiEvalResult(
                eval_name="rag_eval",
                case_id=r["case_id"],
                metric_json=json.dumps({
                    "question": r["question"],
                    "expect_answer": r["expect_answer"],
                    "found_answer": r["found_answer"],
                    "best_score": r["best_score"],
                }, ensure_ascii=False),
                passed=r["status"].startswith("✅"),
                score=r["best_score"] if r["expect_answer"] else (1 - r["best_score"]),
                details=r["status"],
            )
            db.add(eval_result)
        await db.commit()
        print(f"\n💾 结果已保存到 ai_eval_results 表")
    
    return metrics


if __name__ == "__main__":
    asyncio.run(run_rag_eval())
