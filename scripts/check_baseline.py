"""项目基线检查。

用法:
    python scripts/check_baseline.py
    python scripts/check_baseline.py --skip-dependencies

该脚本不连接 MySQL、Redis 或 LLM，只检查本地代码、配置和当前 Python
环境是否具备启动条件。
"""

from __future__ import annotations

import argparse
import compileall
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".html", ".md", ".ini", ".txt", ".json", ".yaml", ".yml"}
TEXT_NAMES = {".env", ".env.example"}
SKIP_DIRS = {
    ".git",
    ".venv",
    ".venv-legacy",
    "venv",
    "__pycache__",
    "uploads",
    "logs",
    "node_modules",
}

REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic_settings": "pydantic-settings",
    "sqlalchemy": "sqlalchemy",
    "aiomysql": "aiomysql",
    "pymysql": "pymysql",
    "alembic": "alembic",
    "jose": "python-jose",
    "passlib": "passlib",
    "multipart": "python-multipart",
}
OPTIONAL_PACKAGES = {
    "redis": "redis",
    "langchain": "langchain",
    "langgraph": "langgraph",
    "chromadb": "chromadb",
    "sentence_transformers": "sentence-transformers",
}
REQUIRED_ENV_KEYS = {
    "APP_ENV",
    "LOG_LEVEL",
    "SERVER_HOST",
    "SERVER_PORT",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USERNAME",
    "DB_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "JWT_SECRET",
    "UPLOAD_DIR",
    "MAX_UPLOAD_SIZE_MB",
    "AI_ENABLED",
    "VECTOR_STORE",
}
MOJIBAKE_MARKERS = ("\u951f\u65a4\u62f7", "\ufffd", "ï»¿", "Ã", "Â", "馃")


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0

    def ok(self, message: str) -> None:
        print(f"[PASS] {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"[WARN] {message}")

    def fail(self, message: str) -> None:
        self.errors += 1
        print(f"[FAIL] {message}")


def iter_text_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            yield path


def check_encoding(report: Report) -> None:
    invalid = []
    bom = []
    suspicious = []
    for path in iter_text_files():
        if path.resolve() == Path(__file__).resolve():
            continue
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            bom.append(path.relative_to(PROJECT_ROOT))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            invalid.append(path.relative_to(PROJECT_ROOT))
            continue
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                suspicious.append((path.relative_to(PROJECT_ROOT), marker))
                break

    if invalid:
        report.fail(f"不是有效 UTF-8 的文件：{', '.join(map(str, invalid))}")
    else:
        report.ok("文本文件均可按 UTF-8 解码")
    if bom:
        report.fail(f"发现 UTF-8 BOM：{', '.join(map(str, bom))}")
    else:
        report.ok("未发现 UTF-8 BOM")
    if suspicious:
        report.fail(
            "发现疑似乱码标记："
            + ", ".join(f"{path}({marker})" for path, marker in suspicious)
        )
    else:
        report.ok("未发现常见乱码标记")


def check_python(report: Report) -> None:
    targets = [PROJECT_ROOT / name for name in ("app", "ai", "scripts")]
    failed = [
        str(path.relative_to(PROJECT_ROOT))
        for path in targets
        if not compileall.compile_dir(path, quiet=1)
    ]
    if failed:
        report.fail(f"Python 编译检查失败：{', '.join(failed)}")
    else:
        report.ok("Python 编译检查通过：app、ai、scripts")


def check_node(report: Report) -> None:
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        report.warn("未找到 Node.js，跳过 JavaScript 语法检查")
        return

    js_files = sorted((PROJECT_ROOT / "static").rglob("*.js"))
    failed = []
    for path in js_files:
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            failed.append(path.relative_to(PROJECT_ROOT))
    if failed:
        report.fail(f"JavaScript 语法检查失败：{', '.join(map(str, failed))}")
    else:
        report.ok(f"JavaScript 语法检查通过：{len(js_files)} 个文件")


def check_dependencies(report: Report, skip: bool) -> None:
    if skip:
        report.warn("按参数跳过 Python 依赖检查")
        return
    for module, package in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module) is None:
            report.fail(f"当前 Python 缺少核心依赖 {package} ({module})")
        else:
            report.ok(f"核心依赖可用：{package}")
    for module, package in OPTIONAL_PACKAGES.items():
        if importlib.util.find_spec(module) is None:
            report.warn(f"当前 Python 未安装可选依赖 {package}，对应功能可能不可用")
        else:
            report.ok(f"可选依赖可用：{package}")


def check_virtualenv(report: Report) -> None:
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ]
    executable = next((path for path in candidates if path.exists()), None)
    if executable is None:
        report.warn("项目目录未发现 .venv，当前命令将使用系统或 bundled Python")
        return
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        report.warn(f"项目虚拟环境无法执行：{executable}（{exc}）")
        return
    if result.returncode == 0:
        report.ok(f"项目虚拟环境可执行：{executable}")
    else:
        report.warn(
            f"项目虚拟环境启动失败：{executable}。"
            "建议删除并按 README 重新创建 .venv。"
        )


def check_config(report: Report) -> None:
    env_example = PROJECT_ROOT / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    keys = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    missing = sorted(REQUIRED_ENV_KEYS - keys)
    if missing:
        report.fail(f".env.example 缺少配置项：{', '.join(missing)}")
    else:
        report.ok(".env.example 已覆盖基础服务、数据库、Redis、JWT、文件和 AI 配置")

    alembic_ini = (PROJECT_ROOT / "alembic.ini").read_text(encoding="utf-8")
    alembic_env = (PROJECT_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    if (
        "sqlalchemy.url =" in alembic_ini
        and "root:" not in alembic_ini
        and "settings.database_url_sync" in alembic_env
    ):
        report.ok("Alembic 使用 Settings 动态读取数据库连接")
    else:
        report.fail("Alembic 仍可能使用硬编码数据库连接")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 EduAgent 项目基线")
    parser.add_argument("--skip-dependencies", action="store_true")
    args = parser.parse_args()

    print(f"EduAgent baseline check | Python: {sys.executable}")
    report = Report()
    check_encoding(report)
    check_python(report)
    check_node(report)
    check_virtualenv(report)
    check_dependencies(report, args.skip_dependencies)
    check_config(report)
    print(f"\n结果：{report.errors} 个错误，{report.warnings} 个警告")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
