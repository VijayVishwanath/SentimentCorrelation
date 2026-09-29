"""Application settings, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_prefix="DEX_", extra="ignore"
    )

    app_name: str = "DEX Sentinel"
    environment: str = "development"
    log_level: str = "INFO"

    # Data
    seed_dataset: Path = PROJECT_ROOT / "data" / "DEX_Sentinel_Simulated_Dataset.xlsx"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'dex_sentinel.db').as_posix()}"

    # Security: when set, every /api call must send header X-API-Key.
    api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    mask_pii: bool = False

    # DEX Copilot LLM provider: auto | anthropic | azure_openai | template
    llm_provider: str = "auto"
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"  # low | medium | high | xhigh | max
    azure_openai_endpoint: str | None = Field(default=None, validation_alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = Field(default=None, validation_alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str | None = Field(default=None, validation_alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_sec: float = 60.0

    # Module 8 uploads
    # "local" = persistent disk; "ephemeral" = container filesystem (e.g. Cloud Run demo tier):
    # uploads reset on restart and the UI says so.
    storage_mode: str = "local"
    max_upload_mb: int = 200
    max_upload_files: int = 10

    # Business-impact assumptions (editable at runtime via /api/v1/settings)
    cost_per_ticket_usd: float = 22.0
    hourly_employee_cost_usd: float = 55.0
    productivity_loss_factor: float = 0.5  # share of resolution time the employee is impaired
    resolution_sla_hours: float = 8.0

    # Static frontend build served by FastAPI
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
