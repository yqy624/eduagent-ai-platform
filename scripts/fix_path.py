"""
sys.path 修复工具 — 所有脚本在导入 app 前先 import 此模块
确保项目 .venv 的 site-packages 优先于 Hermes 全局 venv
"""
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_script_dir)  # scripts/ 的上级即项目根
_venv_sp = os.path.join(_project_dir, ".venv", "Lib", "site-packages")

for p in list(sys.path):
    if _venv_sp in p:
        sys.path.remove(p)
sys.path.insert(0, _venv_sp)
if _project_dir in sys.path:
    sys.path.remove(_project_dir)
sys.path.insert(1, _project_dir)
