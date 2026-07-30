"""
初始化数据库脚本 — 确保所有 AI 辅助表存在
用法: .venv/Scripts/python scripts/init_db.py
"""
import sys, os

# 修复 sys.path — 优先使用项目 .venv
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_venv_sp = os.path.join(_project_dir, ".venv", "Lib", "site-packages")
for p in list(sys.path):
    if _venv_sp in p:
        sys.path.remove(p)
sys.path.insert(0, _venv_sp)
if _project_dir in sys.path:
    sys.path.remove(_project_dir)
sys.path.insert(1, _project_dir)

import asyncio
from app.database import engine, Base
from app.models import models, ai_models


async def init_database():
    """创建所有 AI 辅助表"""
    print("=" * 50)
    print("🗄️ EduAgent 数据库初始化")
    print("=" * 50)
    
    # 业务表模型已存在，只创建 AI 辅助表
    print("\n创建 AI 辅助表...")
    
    # 获取 AI 模型的表
    ai_tables = [t for t in Base.metadata.tables.values() if t.name.startswith("ai_")]
    print(f"  找到 {len(ai_tables)} 个 AI 表:")
    for t in ai_tables:
        print(f"    - {t.name}")
    
    async with engine.begin() as conn:
        # 只创建 AI 表（业务表已存在）
        for t in ai_models.Base.metadata.tables.values():
            await conn.run_sync(t.create, checkfirst=True)
            print(f"  ✅ 已确保 {t.name} 存在")
    
    print("\n✅ 数据库初始化完成！")


if __name__ == "__main__":
    asyncio.run(init_database())
