"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 导入核心业务路由
import app.routers.auth as auth_router
import app.routers.admin as admin_router
import app.routers.teacher as teacher_router
import app.routers.student as student_router
import app.routers.files as files_router
import app.routers.notifications as notifications_router

# AI 路由可选导入（依赖 langchain 等第三方包）
if settings.ai_enabled:
    try:
        import app.routers.ai as ai_router
        AI_AVAILABLE = True
    except ImportError as e:
        print(f"⚠️ AI 路由加载失败（可选）: {e}")
        print("   AI 功能不可用，核心业务接口正常工作")
        AI_AVAILABLE = False
        ai_router = None
else:
    print("ℹ️ AI_ENABLED=false，已跳过 AI/Agent 路由加载")
    AI_AVAILABLE = False
    ai_router = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    print(f"🚀 EduAgent 智慧教育 Agent 平台启动中...")
    print(f"📚 数据库: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    if not AI_AVAILABLE:
        print("⚡ AI 功能未加载，仅核心业务接口可用")
    yield
    print("👋 应用已停止")


app = FastAPI(
    title="EduAgent — 智慧教育 Agent 平台",
    description="基于 FastAPI + LangGraph 的多 Agent 智慧教育学习运营平台",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CamelCase 中间件 — 自动转换 snake_case → camelCase 兼容前端
from app.middleware.camelcase import camelcase_middleware
app.middleware("http")(camelcase_middleware)

# 注册路由
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(teacher_router.router)
app.include_router(student_router.router)
app.include_router(files_router.router)
app.include_router(notifications_router.router)
app.include_router(notifications_router.ws_router)
if AI_AVAILABLE and ai_router:
    app.include_router(ai_router.router)

# === 兼容 Java 前端的 /api/profile 路径 ===
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db as _get_db
from app.middleware.auth import get_current_user as _get_user
from app.models.models import User as _User
from app.schemas.auth import ProfileResponse, ProfileUpdateRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService


@app.get("/api/profile", include_in_schema=False)
async def _profile_get(user: _User = Depends(_get_user), db: AsyncSession = Depends(_get_db)):
    svc = AuthService(db)
    p = await svc.get_profile(user.username)
    return ApiResponse.ok(data=p)


@app.put("/api/profile", include_in_schema=False)
async def _profile_put(req: ProfileUpdateRequest, user: _User = Depends(_get_user), db: AsyncSession = Depends(_get_db)):
    svc = AuthService(db)
    p = await svc.update_profile(user.username, req)
    return ApiResponse.ok(data=p, message="更新成功")

# 静态文件 — 仅挂载 /static 路径
import os as _os
_static_dir = _os.path.join(_os.path.dirname(__file__), "..", "static")
if _os.path.isdir(_static_dir):
    from starlette.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=_static_dir, html=True), name="static")
    print(f"  📁 静态文件: {_static_dir}")

@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(_os.path.join(_static_dir, "login.html"))


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0", "project": "EduAgent", "ai_available": AI_AVAILABLE}
