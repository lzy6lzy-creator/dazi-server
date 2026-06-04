import sys
import logging

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — 必须通过环境变量或 .env 提供，无默认值
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT — 必须通过环境变量或 .env 提供，无默认值
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Admin — 必须通过环境变量或 .env 提供，无默认值
    ADMIN_TOKEN: str

    # Internal TestFlight / staging login
    INTERNAL_TEST_MODE: bool = False
    INTERNAL_TEST_CODE: str = ""
    INTERNAL_TEST_PHONES: str = ""
    INTERNAL_TEST_PHONES_FILE: str = "internal_test_phones.txt"

    # LLM
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.moonshot.cn/v1"
    LLM_MODEL: str = "kimi-k2.5"
    LLM_MAX_CONCURRENT_REQUESTS: int = 1
    LLM_MIN_INTERVAL_SECONDS: float = 2.0
    LLM_RETRIES: int = 5

    # Embedding
    EMBEDDING_MODEL: str = "BAAI/bge-base-zh-v1.5"
    EMBEDDING_DIMENSION: int = 768

    class Config:
        env_file = ".env"
        extra = "ignore"


try:
    settings = Settings()
except Exception as e:
    logging.error(
        "Missing required config. Set DATABASE_URL, JWT_SECRET, and ADMIN_TOKEN "
        "in .env or environment variables. Error: %s", e
    )
    sys.exit(1)
