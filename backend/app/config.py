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

    # Annual Benefits / ROI (engines/roi.py). None = derive from the data.
    working_days_per_year: float = 230.0
    roi_minutes_saved_per_day: float | None = None   # derived: ticket downtime + boot + hang time recovered
    roi_minutes_per_hang: float = 3.0
    roi_boots_per_day: float = 1.0
    roi_unused_licenses: float | None = None         # None = 5% of the fleet (illustrative until SAM data is loaded)
    annual_license_cost_usd: float = 150.0
    roi_avoided_replacements: float | None = None    # derived: hardware fixes that repaired instead of replacing
    device_cost_usd: float = 1200.0

    # Software remediation (MCP email integration, app/remediation). Removal always runs against the
    # simulated fleet inventory; nothing is uninstalled on the host running this code.
    remediation_allowed_senders: list[str] = ["security-team@company.com", "it-compliance@company.com",
                                              "vulnerability-scanner@company.com"]
    remediation_service_account: str = "svc_software_removal"
    remediation_token_ttl_sec: int = 1800
    remediation_seed_inbox: bool = True  # demo emails in the built-in inbox on first use
    # Optional IMAP mailbox polled by the email_monitor tool (password via DEX_IMAP_PASSWORD)
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"

    # ServiceNow incident sync (app/integrations/servicenow). Basic auth against the Table API;
    # mode auto = live when instance + username + password are set, otherwise the built-in demo instance.
    servicenow_instance: str | None = None  # e.g. https://dev12345.service-now.com
    servicenow_username: str | None = None
    servicenow_password: str | None = None
    servicenow_mode: str = "auto"  # auto | live | mock
    servicenow_auto_sync_minutes: int = 0  # 0 = off; overridable at runtime from the UI
    servicenow_query: str | None = None  # extra encoded query, e.g. assignment_group.name=Service Desk
    servicenow_lookback_days: int = 90  # first sync reaches this far back
    servicenow_page_size: int = 500
    servicenow_max_records: int = 10_000
    servicenow_timeout_sec: float = 30.0

    # Static frontend build served by FastAPI
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
