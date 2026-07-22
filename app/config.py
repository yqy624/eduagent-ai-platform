"""应用配置管理"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000

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

    # LLM API Keys
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4"
    dashscope_api_key: Optional[str] = None
    dashscope_model: str = "qwen-max"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
