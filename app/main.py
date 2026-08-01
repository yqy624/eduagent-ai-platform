"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
import os as _os
from pathlib import Path
import sys
from typing import Any

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, ensure_runtime_schema, get_db as _get_db
from app.middleware.auth import get_current_user as _get_user
from app.middleware.camelcase import camelcase_middleware
from app.models.models import User as _User
from app.schemas.auth import ProfileUpdateRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.routers.auth as auth_router
import app.routers.admin as admin_router
import app.routers.teacher as teacher_router
import app.routers.student as student_router
import app.routers.files as files_router
import app.routers.notifications as notifications_router

if settings.ai_enabled:
    try:
        import app.routers.ai as ai_router

        AI_AVAILABLE = True
    except ImportError as exc:
        print(f"AI routes failed to load: {exc}")
        AI_AVAILABLE = False
        ai_router = None
else:
    print("AI_ENABLED=false; AI and Agent routes are disabled")
    AI_AVAILABLE = False
    ai_router = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("EduAgent platform starting...")
    print(f"Database: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    await ensure_runtime_schema()
    if not AI_AVAILABLE:
        print("AI routes are not available; core business APIs remain loaded")
    try:
        yield
    finally:
        await engine.dispose()
        print("EduAgent platform stopped")


app = FastAPI(
    title="EduAgent",
    description="FastAPI based education Agent platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(camelcase_middleware)

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(teacher_router.router)
app.include_router(student_router.router)
app.include_router(files_router.router)
app.include_router(notifications_router.router)
app.include_router(notifications_router.ws_router)
if AI_AVAILABLE and ai_router:
    app.include_router(ai_router.router)


@app.get("/api/profile", include_in_schema=False)
async def _profile_get(
    user: _User = Depends(_get_user),
    db: AsyncSession = Depends(_get_db),
):
    svc = AuthService(db)
    profile = await svc.get_profile(user.username)
    return ApiResponse.ok(data=profile)


@app.put("/api/profile", include_in_schema=False)
async def _profile_put(
    req: ProfileUpdateRequest,
    user: _User = Depends(_get_user),
    db: AsyncSession = Depends(_get_db),
):
    svc = AuthService(db)
    profile = await svc.update_profile(user.username, req)
    return ApiResponse.ok(data=profile, message="Profile updated")


_static_dir = _os.path.join(_os.path.dirname(__file__), "..", "static")
if _os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir, html=True), name="static")
    print(f"Static files mounted: {_static_dir}")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(_os.path.join(_static_dir, "login.html"))


@app.get("/login.html", include_in_schema=False)
async def login_page():
    return FileResponse(_os.path.join(_static_dir, "login.html"))


async def _check_database() -> dict[str, Any]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_llm() -> dict[str, Any]:
    if not settings.ai_enabled:
        return {"status": "skipped", "reason": "AI_ENABLED=false"}
    if not AI_AVAILABLE:
        return {"status": "error", "error": "AI routes failed to load"}

    ollama_model = settings.ollama_model.strip()
    if ollama_model:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
            models = response.json().get("models", [])
            names = {item.get("name", "").split(":", 1)[0] for item in models}
            exact_names = {item.get("name", "") for item in models}
            model_available = ollama_model in exact_names or ollama_model in names
            return {
                "status": "ok" if model_available else "degraded",
                "provider": "ollama",
                "model": ollama_model,
                "model_available": model_available,
            }
        except Exception as exc:
            return {
                "status": "error",
                "provider": "ollama",
                "model": ollama_model,
                "error": str(exc),
            }

    providers = []
    if settings.openai_api_key:
        providers.append({"provider": "openai", "model": settings.openai_model})
    if settings.dashscope_api_key:
        providers.append({"provider": "dashscope", "model": settings.dashscope_model})
    if settings.anthropic_api_key:
        providers.append({"provider": "anthropic", "model": settings.anthropic_model})
    if providers:
        return {"status": "configured", "providers": providers}
    return {"status": "error", "error": "No LLM provider configured"}


def _check_embeddings() -> dict[str, Any]:
    model = settings.embedding_model.strip()
    if not model:
        return {"status": "error", "error": "EMBEDDING_MODEL is empty"}

    try:
        if model.startswith("ollama:"):
            from langchain_community.embeddings import OllamaEmbeddings  # noqa: F401
        else:
            from langchain_community.embeddings import HuggingFaceEmbeddings  # noqa: F401
        return {"status": "ok", "model": model}
    except Exception as exc:
        return {"status": "error", "model": model, "error": str(exc)}


def _check_vector_store() -> dict[str, Any]:
    try:
        from ai.rag.vector_store import VectorStoreManager

        manager = VectorStoreManager()
        path = Path(manager.persist_directory)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"status": "ok", "path": str(path)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/api/health")
async def health_check():
    checks = {
        "database": await _check_database(),
        "ai_routes": {"status": "ok" if AI_AVAILABLE else "disabled" if not settings.ai_enabled else "error"},
        "llm": await _check_llm(),
        "embeddings": _check_embeddings(),
        "vector_store": _check_vector_store(),
    }

    critical_ok = checks["database"]["status"] == "ok"
    if settings.ai_enabled:
        critical_ok = critical_ok and checks["ai_routes"]["status"] == "ok"
        critical_ok = critical_ok and checks["llm"]["status"] in {"ok", "configured"}
        critical_ok = critical_ok and checks["embeddings"]["status"] == "ok"
        critical_ok = critical_ok and checks["vector_store"]["status"] == "ok"

    payload = {
        "status": "ok" if critical_ok else "degraded",
        "version": "2.0.0",
        "project": "EduAgent",
        "ai_available": AI_AVAILABLE,
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if critical_ok else 503)
