"""Application configuration via Pydantic Settings.

All config loaded from environment variables with prefix APP_.
Nested delimiter: __ (double underscore).
See docs/architecture/02-foundation.md Section 4.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """HTTP server configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    executor_workers: int = 4


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection configuration."""

    host: str = "localhost"
    port: int = 5432
    name: str = "agent_platform"
    user: str = "postgres"
    password: str = "postgres"
    pool_min_size: int = 5
    pool_max_size: int = 20
    echo: bool = False

    @property
    def dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    """Redis connection configuration."""

    url: str = "redis://localhost:6379/0"
    max_connections: int = 50
    decode_responses: bool = True
    socket_timeout: float = 5.0
    retry_on_timeout: bool = True


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    lmstudio_base_url: str = "http://localhost:1234/v1"
    default_model: str = "claude-sonnet-4-5-20250514"
    default_timeout: float = 120.0
    max_connections: int = 100
    max_keepalive: int = 20


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "agent-platform"
    jwt_audience: str = "agent-platform"
    jwt_expiry_seconds: int = 3600
    api_key_hash_scheme: str = "bcrypt"


class TracingSettings(BaseSettings):
    """OpenTelemetry tracing configuration."""

    enabled: bool = True
    exporter: str = "otlp"
    otlp_endpoint: str = "http://localhost:4317"
    service_name: str = "agent-platform"
    sample_rate: float = 1.0


class GovernanceSettings(BaseSettings):
    """Data governance configuration."""

    audit_enabled: bool = True
    audit_buffer_size: int = 1000
    audit_flush_interval_ms: int = 500
    retention_enabled: bool = True
    retention_schedule_cron: str = "0 2 * * *"
    classification_enabled: bool = True
    cost_tracking_enabled: bool = True


class Settings(BaseSettings):
    """Root application settings.

    Loaded from environment variables with prefix APP_.
    Nested delimiter: __ (e.g., APP_DATABASE__HOST=localhost).
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "agent-platform"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    governance: GovernanceSettings = Field(default_factory=GovernanceSettings)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()
