
"""
app/config.py

Centralized, typed application configuration.
"""

from functools import lru_cache
from typing import List, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App / Environment
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_NAME: str = "RevenueRescue AI"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"

    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:5175,http://localhost:3000"
    )

    # MongoDB
    MONGO_URI: str
    MONGO_DB_NAME: str = "revenue_rescue_ai"

    # Redis / Celery
    REDIS_URL: str
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Authentication / JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # Anthropic (optional - retained for future use)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_WORKSPACE_ID: str = ""

    # Groq AI
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Notification Providers
    EMAIL_PROVIDER: str = "sendgrid"
    EMAIL_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "recovery@revenuerescue.ai"

    SMS_PROVIDER: str = "twilio"
    SMS_ACCOUNT_SID: str = ""
    SMS_AUTH_TOKEN: str = ""
    SMS_FROM_NUMBER: str = ""

    WHATSAPP_PROVIDER: str = "twilio"
    WHATSAPP_API_KEY: str = ""
    WHATSAPP_FROM_NUMBER: str = ""

    # Rate Limiting
    COPILOT_RATE_LIMIT_PER_HOUR: int = 30
    LOGIN_RATE_LIMIT_PER_15_MIN: int = 10
    RETRY_ATTEMPTS_MAX_PER_CASE: int = 5

    # Scheduler / Worker Tuning
    ABANDONED_CHECKOUT_TIMEOUT_MINUTES: int = 30
    RECOVERY_PREDICTION_CACHE_MINUTES: int = 60

    # Observability
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    SENTRY_DSN: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def jwt_secret_must_be_set_in_production(cls, v: str, info) -> str:
        if v in ("", "change-me-to-a-long-random-string"):
            env = info.data.get("APP_ENV", "development")
            if env == "production":
                raise ValueError(
                    "JWT_SECRET_KEY must be set to a real secret in production."
                )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
