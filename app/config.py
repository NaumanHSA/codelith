from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "insecure-dev-secret"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # JWT
    JWT_SECRET_KEY: str = "insecure-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://docuser:docpassword@localhost:5432/documentanything"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # LLM — OpenAI-compatible (LM Studio by default)
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_API_KEY: str = "lm-studio"
    LLM_DEFAULT_MODEL: str = "local-model"
    LLM_FAST_MODEL: str = "local-model"
    LLM_QUALITY_MODEL: str = "local-model"
    LLM_MAX_TOKENS: int = 8192
    LLM_TEMPERATURE: float = 0.2

    # pgvector — embedding dimensions (must match your LM Studio embedding model output)
    VECTOR_DIMENSIONS: int = 1536

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4jpassword"

    # MinIO / S3
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "documentanything"
    S3_REGION: str = "us-east-1"

    # OAuth2 (Phase 4)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    # Ingestion scratch dir
    REPO_SCRATCH_DIR: str = "/tmp/repos"

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
