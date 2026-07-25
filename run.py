"""EduAgent 启动入口。

启动方式:
    python run.py
    python run.py --host 127.0.0.1 --port 8001 --reload

依赖应安装在当前执行命令所使用的 Python 环境中。这里不再手动修改
sys.path，避免把失效的虚拟环境路径注入到其他解释器。
"""

import argparse
import os
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 EduAgent FastAPI 服务")
    parser.add_argument("--host", default=os.getenv("SERVER_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("SERVER_PORT", "8001")),
    )
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        package = exc.name or "uvicorn"
        raise SystemExit(
            f"启动失败：当前 Python ({sys.executable}) 缺少依赖 {package!r}。\n"
            "请先执行 `python -m pip install -r requirements.txt`，"
            "再运行 `python run.py`。"
        ) from exc

    try:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    except ModuleNotFoundError as exc:
        package = exc.name or "unknown"
        raise SystemExit(
            f"启动失败：加载应用时缺少 Python 依赖 {package!r}。\n"
            "请执行 `python scripts/check_baseline.py` 查看完整检查结果。"
        ) from exc


if __name__ == "__main__":
    main()
