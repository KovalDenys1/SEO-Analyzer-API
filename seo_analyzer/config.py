import re
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from ``SEO_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SEO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_key: SecretStr | None = None
    fetch_timeout_seconds: float = Field(default=12.0, ge=1, le=120)
    max_response_bytes: int = Field(default=3_000_000, ge=50_000, le=20_000_000)
    max_redirects: int = Field(default=5, ge=0, le=10)
    max_concurrent_fetches: int = Field(default=8, ge=1, le=50)
    allow_private_hosts: bool = False
    allowed_ports: str = "80,443"
    user_agent: str = "SaaSSEOAnalyzer/2.0 (+https://github.com/hlibsuslov/SEO-Analyzer-API)"
    robots_user_agent: str = "SaaSSEOAnalyzer"

    cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    cache_max_entries: int = Field(default=512, ge=1, le=10_000)
    max_site_pages: int = Field(default=100, ge=1, le=1_000)

    enable_pagespeed: bool = False
    pagespeed_api_key: SecretStr | None = None
    pagespeed_timeout_seconds: float = Field(default=60.0, ge=5, le=180)

    cors_origins: str = ""
    log_level: str = "INFO"

    @field_validator("allowed_ports")
    @classmethod
    def validate_allowed_ports(cls, value: str) -> str:
        tokens = [token.strip() for token in value.split(",") if token.strip()]
        if not tokens:
            raise ValueError("allowed_ports must contain at least one TCP port")
        try:
            ports = [int(token) for token in tokens]
        except ValueError as exc:
            raise ValueError("allowed_ports must be a comma-separated list of integers") from exc
        if any(port < 1 or port > 65_535 for port in ports):
            raise ValueError("allowed_ports values must be between 1 and 65535")
        return ",".join(str(port) for port in dict.fromkeys(ports))

    @field_validator("user_agent")
    @classmethod
    def validate_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character in value for character in "\r\n"):
            raise ValueError("user_agent must be a non-empty single-line value")
        return value

    @field_validator("robots_user_agent")
    @classmethod
    def validate_robots_user_agent(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
            raise ValueError("robots_user_agent must be a valid product token")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("log_level must be CRITICAL, ERROR, WARNING, INFO, or DEBUG")
        return normalized

    @property
    def parsed_allowed_ports(self) -> set[int]:
        return {int(value.strip()) for value in self.allowed_ports.split(",") if value.strip()}

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
