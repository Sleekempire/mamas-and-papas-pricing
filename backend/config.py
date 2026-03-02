"""
config.py — Environment-driven application settings.
Uses Pydantic Settings for type-safe, validated configuration.
Supports development / staging / production separation.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Literal

from pydantic import field_validator, AnyHttpUrl, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = "PricingOptimiser"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False

    # ── Security ─────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "INSECURE_DEV_KEY_CHANGE_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./pricing_v2.db"

    # ── Model Storage ────────────────────────────────────────────────────
    MODEL_STORE_PATH: Path = Path("./model_store")
    RL_POLICY_PATH: Path = Path("./model_store/rl_policy.json")

    # ── Pricing Constraints ──────────────────────────────────────────────
    MIN_MARGIN_PCT: float = 0.15
    PRICE_GRID_POINTS: int = 20
    PRICE_LOWER_BOUND: float = 0.80
    PRICE_UPPER_BOUND: float = 1.20
    MAX_DAILY_PRICE_CHANGE: float = 0.20
    STOCK_SAFETY_FACTOR: float = 0.90

    # ── Rate Limiting ────────────────────────────────────────────────────
    RATE_LIMIT_ADMIN: str = "200/minute"
    RATE_LIMIT_ANALYST: str = "100/minute"
    RATE_LIMIT_MERCHANDISER: str = "60/minute"
    RATE_LIMIT_VIEWER: str = "30/minute"

    # ── Response Controls ────────────────────────────────────────────────
    MAX_RESPONSE_SIZE_BYTES: int = 1_048_576  # 1 MB
    MAX_RECOMMENDATION_ROWS: int = 500
    SKU_QUERY_ANOMALY_THRESHOLD: int = 10

    # ── CORS ─────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080,http://localhost:5500"

    # ── Logging ──────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    AUDIT_LOG_ENABLED: bool = True

    # ── Computed ─────────────────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[misc]
    @property
    def allowed_hosts_list(self) -> List[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:  # type: ignore[override]
        env = os.getenv("ENVIRONMENT", "development")
        if env == "production" and v == "INSECURE_DEV_KEY_CHANGE_IN_PRODUCTION":
            raise ValueError("JWT_SECRET_KEY must be changed in production")
        return v

    @field_validator("MODEL_STORE_PATH", mode="before")
    @classmethod
    def create_model_store_path(cls, v) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p


# Singleton instance used throughout the app
settings = Settings()
