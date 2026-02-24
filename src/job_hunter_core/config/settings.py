"""Application settings using pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for job-hunter-agent."""

    model_config = SettingsConfigDict(env_prefix="JH_", env_file=".env")

    # --- LLM ---
    anthropic_api_key: SecretStr = Field(
        description="Anthropic API key for Claude models",
    )
    haiku_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model ID for fast/cheap LLM calls",
    )
    sonnet_model: str = Field(
        default="claude-sonnet-4-5-20250514",
        description="Model ID for high-quality LLM calls",
    )

    # --- Search ---
    tavily_api_key: SecretStr = Field(
        description="Tavily API key for web search",
    )

    # --- Database ---
    db_backend: Literal["postgres", "sqlite"] = Field(
        default="sqlite",
        description="Database backend: 'sqlite' for zero-infra, 'postgres' for production",
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./job_hunter.db",
        description="SQLAlchemy database URL (auto-set for postgres)",
    )
    postgres_url: str = Field(
        default="postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter",
        description="PostgreSQL connection URL",
    )

    # --- Embeddings ---
    embedding_provider: Literal["voyage", "local"] = Field(
        default="local",
        description="Embedding provider: 'local' (free) or 'voyage' (API)",
    )
    voyage_api_key: SecretStr | None = Field(
        default=None,
        description="Voyage API key (required if embedding_provider=voyage)",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Local embedding model name",
    )
    embedding_dimension: int = Field(
        default=384,
        description="Embedding vector dimension (384 for MiniLM, 1024 for Voyage)",
    )

    # --- Cache ---
    cache_dir: Path = Field(
        default=Path("./.cache/job_hunter"),
        description="Directory for diskcache persistent cache",
    )
    cache_ttl_hours: int = Field(
        default=24,
        description="Default cache TTL in hours",
    )
    company_cache_ttl_days: int = Field(
        default=7,
        description="Career URL cache TTL in days",
    )

    # --- Email ---
    email_provider: Literal["sendgrid", "smtp"] = Field(
        default="smtp",
        description="Email delivery provider",
    )
    sendgrid_api_key: SecretStr | None = Field(
        default=None,
        description="SendGrid API key (required if email_provider=sendgrid)",
    )
    smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname",
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port",
    )
    smtp_user: str = Field(
        default="",
        description="SMTP username",
    )
    smtp_password: SecretStr | None = Field(
        default=None,
        description="SMTP password",
    )

    # --- LangSmith (optional) ---
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        description="LangSmith API key for tracing (optional)",
    )
    langsmith_project: str = Field(
        default="job-hunter-agent",
        description="LangSmith project name",
    )

    # --- Scraping ---
    max_concurrent_scrapers: int = Field(
        default=5,
        description="Maximum concurrent scraping tasks",
    )
    scrape_timeout_seconds: int = Field(
        default=30,
        description="Timeout per scrape request in seconds",
    )
    scraper_retry_max: int = Field(
        default=3,
        description="Maximum retries per scrape request",
    )
    scraper_retry_wait_min: float = Field(
        default=1.0,
        description="Minimum retry wait in seconds",
    )
    scraper_retry_wait_max: float = Field(
        default=10.0,
        description="Maximum retry wait in seconds",
    )

    # --- Scoring ---
    min_score_threshold: int = Field(
        default=60,
        description="Minimum score to include in output",
    )
    top_k_semantic: int = Field(
        default=50,
        description="Number of jobs to shortlist via semantic search",
    )
    max_jobs_per_company: int = Field(
        default=10,
        description="Maximum jobs to process per company",
    )

    # --- Run ---
    output_dir: Path = Field(
        default=Path("./output"),
        description="Directory for output files",
    )
    run_id_prefix: str = Field(
        default="run",
        description="Prefix for auto-generated run IDs",
    )
    checkpoint_enabled: bool = Field(
        default=True,
        description="Enable checkpoint files for crash recovery",
    )
    checkpoint_dir: Path = Field(
        default=Path("./output/checkpoints"),
        description="Directory for checkpoint files",
    )

    # --- Cost Guardrails ---
    max_cost_per_run_usd: float = Field(
        default=5.0,
        description="Hard stop if estimated cost exceeds this (USD)",
    )
    warn_cost_threshold_usd: float = Field(
        default=2.0,
        description="Log warning at this cost threshold (USD)",
    )

    @model_validator(mode="after")
    def validate_db_config(self) -> Settings:
        """Set database_url from postgres_url when using postgres backend."""
        if self.db_backend == "postgres":
            self.database_url = self.postgres_url
        return self

    @model_validator(mode="after")
    def validate_embedding_config(self) -> Settings:
        """Validate embedding provider configuration."""
        if self.embedding_provider == "voyage" and not self.voyage_api_key:
            msg = "voyage_api_key required when embedding_provider=voyage"
            raise ValueError(msg)
        if self.embedding_provider == "voyage":
            self.embedding_dimension = 1024
        return self
