"""
edu-ai-platform 启动入口
使用方式: PYTHONPATH="" .venv/Scripts/python run.py
"""
import os
import sys

# 清除 Hermes venv 污染
os.environ.pop("PYTHONPATH", None)
project_sp = os.path.join(os.path.dirname(__file__), ".venv", "Lib", "site-packages")
sys.path = [project_sp] + [p for p in sys.path if p != project_sp and "hermes" not in p.lower()]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
