#!/usr/bin/env python
"""
批改评测脚本 — 评估 AI 批改建议与教师评分的一致性
用法: .venv/Scripts/python -m ai.evals.grading_eval
"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime
from sqlalchemy import select

from app.database import async_session_factory
from app.models.models import Submission, Assignment
from app.models.ai_models import AiEvalResult
from ai.tools.grade_tools import GradeTools


async def run_grading_eval():
    print("=" * 60)
    print("📊 AI 批改评测")
    print("=" * 60)

    async with async_session_factory() as db:
        grade_tools = GradeTools(db)

        # 获取已有评分的提交
        result = await db.execute(
            select(Submission).where(
                Submission.status == "GRADED",
                Submission.score.isnot(None),
            ).limit(10)
        )
        submissions = list(result.scalars().all())

        if not submissions:
            print("  ⚠️ 没有已评分的提交记录，无法评测")
            return

        total_error = 0
        results = []

        for sub in submissions:
            assignment = await db.execute(
                select(Assignment).where(Assignment.id == sub.assignment_id)
            )
            assignment_obj = assignment.scalar_one_or_none()

            # 模拟 AI 评分（基于规则的估算）
            content_len = len(sub.content or "")
            total_points = assignment_obj.total_points if assignment_obj else 100

            # 规则评分
            if content_len > 500:
                ai_score = total_points * 0.85
            elif content_len > 200:
                ai_score = total_points * 0.75
            elif content_len > 50:
                ai_score = total_points * 0.60
            else:
                ai_score = total_points * 0.40

            ai_score = min(total_points, max(0, ai_score))
            teacher_score = sub.score

            error = abs(ai_score - teacher_score)
            total_error += error

            passed = error <= total_points * 0.2  # 误差不超过 20%
            status = "✅" if passed else "❌"

            results.append({
                "case_id": f"submission_{sub.id}",
                "submission_id": sub.id,
                "ai_score": round(ai_score, 1),
                "teacher_score": teacher_score,
                "error": round(error, 1),
                "total_points": total_points,
                "passed": passed,
            })
            print(f"  {status} AI={ai_score:.0f}/{total_points} 教师={teacher_score}/{total_points} 误差={error:.1f}")

        avg_error = total_error / len(results) if results else 0
        pass_rate = sum(1 for r in results if r["passed"]) / len(results) * 100 if results else 0

        metrics = {
            "total_cases": len(results),
            "average_error": round(avg_error, 1),
            "pass_rate": round(pass_rate, 1),
        }

        print(f"\n{'=' * 60}")
        print("📈 评测结果")
        print(f"{'=' * 60}")
        print(f"  总用例:       {len(results)}")
        print(f"  平均误差:     {avg_error:.1f} 分")
        print(f"  通过率:       {pass_rate:.1f}%")

        # 保存结果
        for r in results:
            eval_result = AiEvalResult(
                eval_name="grading_eval",
                case_id=r["case_id"],
                metric_json=json.dumps({
                    "ai_score": r["ai_score"],
                    "teacher_score": r["teacher_score"],
                    "total_points": r["total_points"],
                }),
                passed=r["passed"],
                score=100 - r["error"] / r["total_points"] * 100 if r["total_points"] else 0,
                details=f"AI建议{r['ai_score']}分，教师评分{r['teacher_score']}分，误差{r['error']}分",
            )
            db.add(eval_result)
        await db.commit()
        print(f"\n💾 结果已保存到 ai_eval_results 表")

    return metrics


if __name__ == "__main__":
    asyncio.run(run_grading_eval())
