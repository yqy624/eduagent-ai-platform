"""应用配置管理。

所有可变配置从环境变量读取，.env 仅用于本地开发。
"""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # Server
    app_env: str = "development"
    server_host: str = "0.0.0.0"
    server_port: int = 8001
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8001,http://127.0.0.1:8001"

    # Database
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "student_db"
    db_username: str = "root"
    db_password: str = "change-me"

    @property
    def database_url(self) -> str:
        return f"mysql+aiomysql://{self.db_username}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"

    @property
    def database_url_sync(self) -> str:
        """用于 Alembic 等同步工具"""
        return f"mysql+pymysql://{self.db_username}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = ""
    redis_database: int = 0

    # JWT
    jwt_secret: str = "ChangeThisJwtSecretBeforeProductionUse_AtLeast32CharsLong"
    jwt_expiration: int = 86400000  # 24 hours in ms

    # MinIO (optional)
    minio_endpoint: Optional[str] = "http://localhost:9000"
    minio_access_key: Optional[str] = "minioadmin"
    minio_secret_key: Optional[str] = "minioadmin"
    minio_bucket: str = "education-files"

    # Local file storage
    upload_dir: str = "uploads"
    max_upload_size_mb: int = Field(default=20, ge=1, le=1024)

    # AI and vector store
    ai_enabled: bool = True
    vector_store: str = "faiss"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_persist_dir: str = "data/chroma"

    # LLM API Keys
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4"
    dashscope_api_key: Optional[str] = None
    dashscope_model: str = "qwen-max"

    # Ollama（本地 LLM）
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """返回可直接交给 CORSMiddleware 的来源列表。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def upload_path(self) -> Path:
        """返回相对于项目根目录解析后的上传目录。"""
        path = Path(self.upload_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def chroma_path(self) -> Path:
        path = Path(self.chroma_persist_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path


settings = Settings()
