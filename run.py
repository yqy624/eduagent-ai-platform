"""
edu-ai-platform 启动入口
使用方式: .venv/Scripts/python run.py
"""
import os
import sys

project_dir = os.path.dirname(os.path.abspath(__file__))
venv_sp = os.path.join(project_dir, ".venv", "Lib", "site-packages")

# 将项目 .venv 的 site-packages 放在 sys.path 最前面
for p in list(sys.path):
    if venv_sp in p:
        sys.path.remove(p)
sys.path.insert(0, venv_sp)

# 把项目根目录放第二位
if project_dir in sys.path:
    sys.path.remove(project_dir)
sys.path.insert(1, project_dir)

os.environ.pop("PYTHONPATH", None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=False)
