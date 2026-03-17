"""Application settings using Pydantic Settings."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=[
            ".env.local",
            ".env",
            "../deploy/.env",
        ],  # Tenta .env.local primeiro (dev local), depois .env, depois deploy/.env
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "AI SaaS Dashboard Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True  # Temporarily enabled for debugging
    ENVIRONMENT: str = "development"
    ADMIN_ONBOARDING_VERSION: int = 1

    # API
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
        description="CORS allowed origins (comma-separated)",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if not self.CORS_ORIGINS:
            return ["http://localhost:3000", "http://localhost:3001"]
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    # Database - can be built from separate env vars or provided as full URL
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db",
        description="Database connection URL (can be built from POSTGRES_* env vars)",
    )

    # Separate PostgreSQL environment variables (for Docker Compose)
    POSTGRES_USER: str = Field(default="postgres", description="PostgreSQL username")
    POSTGRES_PASSWORD: str = Field(default="", description="PostgreSQL password")
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL port")
    POSTGRES_DB: str = Field(
        default="ai_saas_db", description="PostgreSQL database name"
    )

    @model_validator(mode="after")
    def build_database_url(self):
        """Build DATABASE_URL from separate env vars if available, otherwise use provided URL."""
        import os
        from urllib.parse import quote_plus

        # Check if we have separate PostgreSQL environment variables (Docker Compose setup)
        # Priority: env vars > Field defaults
        postgres_user = os.getenv("POSTGRES_USER") or self.POSTGRES_USER
        postgres_password = os.getenv("POSTGRES_PASSWORD") or self.POSTGRES_PASSWORD
        postgres_host = os.getenv("POSTGRES_HOST") or self.POSTGRES_HOST
        postgres_port_env = os.getenv("POSTGRES_PORT")
        postgres_db = os.getenv("POSTGRES_DB") or self.POSTGRES_DB

        # If POSTGRES_PASSWORD is set as env var, always build URL from separate vars
        if os.getenv("POSTGRES_PASSWORD"):
            encoded_password = (
                quote_plus(postgres_password) if postgres_password else ""
            )
            port_str = (
                f":{postgres_port_env}"
                if postgres_port_env
                else (f":{self.POSTGRES_PORT}" if self.POSTGRES_PORT != 5432 else "")
            )
            self.DATABASE_URL = f"postgresql+asyncpg://{postgres_user}:{encoded_password}@{postgres_host}{port_str}/{postgres_db}"

        # Helper to ensure async driver
        if self.DATABASE_URL and self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )

        if (
            self.DATABASE_URL
            and "@" in self.DATABASE_URL
            and "asyncpg" in self.DATABASE_URL
        ):
            # Fix existing DATABASE_URL if password contains special characters
            import re

            # Format: postgresql+asyncpg://user:password@host:port/db
            pattern = r"^(postgresql(?:\+asyncpg)?)://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/(.+)$"
            match = re.match(pattern, self.DATABASE_URL)

            if match:
                scheme, username, password, host, port, database = match.groups()

                # Check if password needs encoding
                from urllib.parse import unquote_plus

                try:
                    # Try to decode if it's already encoded
                    decoded_password = (
                        unquote_plus(password) if "%" in password else password
                    )
                    # Only re-encode if password contains special chars that need encoding
                    if (
                        any(
                            c in decoded_password
                            for c in ["/", "=", "+", "@", ":", "?", "#", "[", "]"]
                        )
                        or "%" not in password
                    ):
                        encoded_password = quote_plus(decoded_password)
                        port_part = f":{port}" if port else ""
                        self.DATABASE_URL = f"{scheme}://{username}:{encoded_password}@{host}{port_part}/{database}"
                except Exception:
                    # If any error in complex parsing, leave as is
                    pass

        return self

    DATABASE_POOL_SIZE: int = (
        20  # Aumentado de 3 para 20 para evitar exaustão de conexões
    )
    DATABASE_MAX_OVERFLOW: int = (
        10  # Aumentado de 5 para 10 (total máximo: 30 conexões)
    )
    DATABASE_POOL_PRE_PING: bool = True

    # Redis
    REDIS_URL: str = Field(
        default="",
        description="Redis connection URL (empty to skip Redis - OK for local development)",
    )
    REDIS_HOST: Optional[str] = Field(
        default=None,
        description="Redis host (empty to use REDIS_URL or fallback to localhost in dev)",
    )
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    @model_validator(mode="after")
    def build_redis_url(self):
        """Build REDIS_URL from separate env vars if available and URL is empty."""
        import os

        # Priority: env var > Field default
        redis_host = os.getenv("REDIS_HOST") or self.REDIS_HOST
        redis_port = os.getenv("REDIS_PORT") or str(self.REDIS_PORT)
        redis_db = os.getenv("REDIS_DB") or str(self.REDIS_DB)
        redis_password = os.getenv("REDIS_PASSWORD") or self.REDIS_PASSWORD

        # Build REDIS_URL only if it's empty and we have at least a host
        if not self.REDIS_URL and redis_host:
            auth = f":{redis_password}@" if redis_password else ""
            self.REDIS_URL = f"redis://{auth}{redis_host}:{redis_port}/{redis_db}"
        elif (
            not self.REDIS_URL and not redis_host and self.ENVIRONMENT != "development"
        ):
            # Safety check for non-development environments
            import logging

            logging.getLogger(__name__).warning(
                "REDIS_URL and REDIS_HOST are both empty in non-development environment"
            )

        return self

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker URL",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL",
    )

    # JWT
    JWT_SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production",
        description="JWT secret key",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Password
    PASSWORD_HASH_ALGORITHM: str = "bcrypt"
    BCRYPT_ROUNDS: int = 12

    # Encryption (for connection credentials)
    ENCRYPTION_KEY: str = Field(
        default="your-32-byte-encryption-key-change-in-production",
        description="Encryption key for sensitive data (must be 32 bytes)",
    )

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"

    # Storage
    STORAGE_TYPE: str = "local"  # local, s3, gcs
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "us-east-1"
    GCS_BUCKET_NAME: str = ""
    GCS_PROJECT_ID: str = ""

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@example.com"
    SMTP_USE_TLS: bool = True

    # AI Service
    AI_SERVICE_TYPE: str = Field(
        default="mock", description="AI service type: mock, real"
    )  # mock, real
    AI_SERVICE_URL: str = Field(
        default="http://localhost:8001",
        description="URL of the AI service (ia-do-projeto)",
    )
    AI_METADATA_TTL_SECONDS: int = Field(
        default=21600,
        description="TTL (seconds) for AI table metadata before re-discover is triggered. 0 disables staleness checks.",
    )
    AI_RESPONSE_CACHE_TTL_SECONDS: int = Field(
        default=600,
        description="TTL (seconds) for cached AI responses. 0 disables caching.",
    )

    # Cache warming (background scheduler)
    CACHE_WARMING_ENABLED: bool = Field(
        default=True,
        description="Enable periodic cache warming for AI response cache.",
    )
    CACHE_WARMING_INTERVAL_SECONDS: int = Field(
        default=300,
        description="Interval (seconds) for cache warming scheduler.",
    )
    CACHE_WARMING_LOOKBACK_HOURS: int = Field(
        default=24,
        description="Lookback window (hours) when selecting warm candidates.",
    )
    CACHE_WARMING_TOP_N_PER_CONNECTION: int = Field(
        default=10,
        description="Top N questions per connection to consider for warming.",
    )
    CACHE_WARMING_MAX_WARMS_PER_RUN: int = Field(
        default=50,
        description="Hard cap on how many cache entries to warm per scheduler run.",
    )
    CACHE_WARMING_MAX_SCAN_ROWS: int = Field(
        default=5000,
        description="Max recent AIQuery rows scanned per run (bounds DB work).",
    )
    CACHE_WARMING_MAX_TOTAL_CANDIDATES: int = Field(
        default=200,
        description="Max candidates kept after grouping/ranking (bounds CPU work).",
    )
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4"
    ANTHROPIC_API_KEY: str = ""

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 300
    RATE_LIMIT_PER_HOUR: int = 10000

    # Tenant/User rate limiting for AI cost control (Subtask 2/3)
    AI_RATE_LIMIT_ENABLED: bool = True
    AI_RATE_LIMIT_USER_PER_MINUTE: int = 10
    AI_RATE_LIMIT_USER_PER_HOUR: int = 50
    AI_RATE_LIMIT_TENANT_PER_MINUTE: int = 40
    AI_RATE_LIMIT_TENANT_PER_HOUR: int = 200
    # Hard cap to prevent "switching tenant context" abuse
    AI_RATE_LIMIT_GLOBAL_USER_PER_HOUR: int = 80

    IDEMPOTENCY_TTL_SECONDS: int = Field(
        default=86400,
        description="TTL in seconds for idempotency keys stored in Redis.",
    )

    @model_validator(mode="after")
    def apply_environment_defaults(self):
        """
        Apply safer defaults for large-app development without impacting production.

        - In production: default to 300/min and 10000/hour unless explicitly set via env vars.
        - In development: keep rate limit enabled, but raise limits to avoid dev/HMR/test storms (3000/min).
        """
        import os

        is_prod = self.ENVIRONMENT == "production"

        # Only apply defaults when the env var is not explicitly set.
        if os.getenv("RATE_LIMIT_PER_MINUTE") is None:
            self.RATE_LIMIT_PER_MINUTE = 300 if is_prod else 3000
        if os.getenv("RATE_LIMIT_PER_HOUR") is None:
            self.RATE_LIMIT_PER_HOUR = 10000 if is_prod else 1000000
        if os.getenv("RATE_LIMIT_ENABLED") is None:
            # Keep enabled by default; can be disabled explicitly in env.
            self.RATE_LIMIT_ENABLED = True

        return self

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json, text

    # Prometheus
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.ENVIRONMENT == "development"

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic."""
        from urllib.parse import urlparse, urlunparse

        # Parse the async URL
        parsed = urlparse(self.DATABASE_URL)

        # Remove +asyncpg from scheme
        scheme = parsed.scheme.replace("+asyncpg", "")

        # Password is already encoded in DATABASE_URL, so we can use it directly
        # psycopg2 will handle URL decoding automatically
        if parsed.password:
            # Keep the encoded password as-is (psycopg2 handles URL decoding)
            netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"

            return urlunparse(
                (
                    scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )

        # If no password, just remove +asyncpg
        return self.DATABASE_URL.replace("+asyncpg", "")


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
