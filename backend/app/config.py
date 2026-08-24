from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def normalize_database_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "+" not in raw.split("://", 1)[0]:
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


class Settings(BaseSettings):
    DATABASE_URL: str
    API_KEY_READ: str
    API_KEY_WRITE: str
    PORT: int = 8000
    DATABASE_SSL: bool = False
    DEMO_MODE: bool = False
    DEMO_RECOVERY_WINDOW_SECONDS: int = 30
    RECOVERY_WINDOW_SECONDS: int = 180
    MAX_RECOVERY_ATTEMPTS: int = 3
    MAX_CART_HOLD_SECONDS: int = 180
    CORS_ORIGINS: str = ""
    CORS_ORIGIN_REGEX: str = ""
    LLM_PROVIDER: str = "simulated"
    WEBHOOK_URL: str = ""
    WEBHOOK_TIMEOUT_SECONDS: float = 2.0
    AUTO_CREATE_SCHEMA: bool = False
    CIRCUIT_FAILURE_RATE_THRESHOLD: float = 0.30
    CIRCUIT_MIN_SAMPLES: int = 8
    CIRCUIT_WINDOW_SECONDS: int = 60
    CIRCUIT_COOLDOWN_SECONDS: int = 60
    RATE_LIMIT_CHECKOUT_PER_MINUTE: int = 60
    RATE_LIMIT_RECOVERY_PER_MINUTE: int = 30
    ALERT_MANUAL_REVIEW_DEPTH: int = 25
    ALERT_CIRCUIT_OPEN_SECONDS: int = 300
    ALERT_ERROR_RATE_THRESHOLD: float = 0.50
    LOG_LEVEL: str = "INFO"
    DEFAULT_TENANT_ID: str = "TENANT_DEFAULT"
    API_KEY_OPS: str = ""
    TENANT_KEYS_JSON: str = ""
    REDIS_URL: str = ""
    WORKER_ENABLED: bool = False
    RETRAIN_INTERVAL_SECONDS: int = 3600
    SCORE_WINDOW_HOURS: int = 24
    SCORE_WINDOW_ATTEMPTS: int = 500
    PREDICT_FAIL_THRESHOLD: float = 0.65
    PREDICT_MIN_SAMPLES: int = 8
    CIRCUIT_ANOMALY_ZSCORE: float = 2.0
    CIRCUIT_ANOMALY_MIN_SAMPLES: int = 3
    BACKPRESSURE_REVIEW_DEPTH: int = 50
    BACKPRESSURE_JOB_DEPTH: int = 100
    POLICY_RETRY_MIN: int = 2
    POLICY_RETRY_MAX: int = 5
    POLICY_AMOUNT_MIN: int = 5000
    POLICY_AMOUNT_MAX: int = 50000
    POLICY_COOLDOWN_MIN: int = 10
    POLICY_COOLDOWN_MAX: int = 120

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @model_validator(mode="after")
    def _apply_ssl_and_deploy_guards(self) -> "Settings":
        if self.DATABASE_SSL and "ssl=" not in self.DATABASE_URL and "sslmode=" not in self.DATABASE_URL:
            sep = "&" if "?" in self.DATABASE_URL else "?"
            self.DATABASE_URL = f"{self.DATABASE_URL}{sep}ssl=require"
        if not self.AUTO_CREATE_SCHEMA:
            if self.is_sqlite:
                raise ValueError(
                    "DATABASE_URL must be PostgreSQL when AUTO_CREATE_SCHEMA is false. SQLite is not supported in deployed mode."
                )
            origins = self.CORS_ORIGINS.strip()
            regex = (self.CORS_ORIGIN_REGEX or "").strip()
            if origins == "*":
                raise ValueError(
                    "CORS_ORIGINS must be a comma-separated list of frontend origins in deployed mode. Wildcard origins are not allowed."
                )
            if not origins and not regex:
                raise ValueError(
                    "CORS_ORIGINS must be a comma-separated list of frontend origins in deployed mode. Wildcard origins are not allowed."
                )
        return self

    @property
    def recovery_window_seconds(self) -> int:
        if self.DEMO_MODE:
            return min(self.DEMO_RECOVERY_WINDOW_SECONDS, self.MAX_CART_HOLD_SECONDS)
        return min(self.RECOVERY_WINDOW_SECONDS, self.MAX_CART_HOLD_SECONDS)

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.CORS_ORIGINS.strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
