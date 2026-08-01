"""数据库连接管理"""
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def ensure_runtime_schema() -> None:
    import app.models.models  # noqa: F401
    import app.models.ai_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        has_assignments = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("assignments")
        )
        if has_assignments:
            columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"]
                    for column in inspect(sync_conn).get_columns("assignments")
                }
            )
            if "detail" not in columns:
                await conn.execute(text("ALTER TABLE assignments ADD COLUMN detail TEXT NULL"))

        ai_runs_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("ai_runs")
            }
            if inspect(sync_conn).has_table("ai_runs")
            else set()
        )
        if ai_runs_columns and "plan_json" not in ai_runs_columns:
            await conn.execute(text("ALTER TABLE ai_runs ADD COLUMN plan_json TEXT NULL"))


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
