from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "WhatLawSays Backend"
    API_V1_STR: str = "/api/v1"

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    CROSS_ENCODER_MODEL: str = "BAAI/bge-reranker-base"

    QDRANT_URL: str = "http://localhost:6333"
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/whatlawsays"

    RATE_LIMIT_PER_MINUTE: int = 10

    CONTRACT_LLM_CONCURRENCY: int = 4
    CONTRACT_LLM_CALL_BUDGET: int = 40
    CONTRACT_HOT_BATCH: int = 4
    CONTRACT_WARM_BATCH: int = 10
    CONTRACT_CLASSIFY_BATCH: int = 12

    FIREBASE_PROJECT_ID: str = ""

    # Where the built React app lives. The Docker image copies it to /app/static.
    FRONTEND_DIST: str = str(_REPO_ROOT / "frontend" / "dist")


settings = Settings()
