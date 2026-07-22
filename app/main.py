"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # Startup
    print(f"🚀 智慧教育管理系统启动中...")
    print(f"📚 数据库: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    yield
    # Shutdown
    print("👋 应用已停止")


app = FastAPI(
    title="智慧教育管理系统 API",
    description="Smart Education Management System — Python + AI 版",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（原 Java 项目前端页面）
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
