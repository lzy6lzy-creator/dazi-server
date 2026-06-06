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

    # App Store Connect API for TestFlight internal invitations
    ASC_KEY_ID: str = ""
    ASC_ISSUER_ID: str = ""
    ASC_PRIVATE_KEY_PATH: str = ""
    ASC_BUNDLE_ID: str = "com.linke.dazi"
    ASC_APP_ID: str = ""
    ASC_INTERNAL_GROUP_NAME: str = "搭子test"
    ASC_INTERNAL_GROUP_ID: str = ""
    ASC_INVITE_ROLE: str = "MARKETING"

    # Apple Push Notification service (APNs) for iOS remote notifications.
    # TestFlight and App Store builds use production APNs; DEBUG builds use sandbox.
    APNS_KEY_ID: str = ""
    APNS_TEAM_ID: str = ""
    APNS_PRIVATE_KEY_PATH: str = ""
    APNS_BUNDLE_ID: str = "com.linke.dazi"

    # Legacy model config names accepted as agent server fallbacks.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.moonshot.cn/v1"
    LLM_MODEL: str = "kimi-k2.5"

    # Agent model routing.
    AGENT_MODEL_PROVIDER: str = ""
    AGENT_MODEL: str = ""
    AGENT_BASE_URL: str = ""
    AGENT_API_KEY: str = ""
    AGENT_DRAFT_MODEL_PROVIDER: str = ""
    AGENT_DRAFT_MODEL: str = ""
    AGENT_DRAFT_BASE_URL: str = ""
    AGENT_DRAFT_API_KEY: str = ""

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
