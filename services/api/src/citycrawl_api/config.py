"""One Settings object shared by every module. Datasets code that used to read
`external_data.config.Settings` now reads this (via the datasets/config.py shim), so the
storage/db fields below must keep their original names and defaults."""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Supabase auth (token validation + RPC host) -------------------------
    supabase_url: str | None = None
    supabase_anon_key: str | None = None

    # --- Anthropic (LLM draft parser) ----------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # --- Operator protection for dataset refresh -----------------------------
    operator_api_key: str | None = None

    # --- Citizen-report confirmation gate (non-public inference server) -------
    inference_thinking_mode: str = "flash"     # 'flash' | 'thinking'
    inference_timeout_s: float = 60.0
    inference_poll_interval_s: float = 1.0

    # --- CORS ----------------------------------------------------------------
    # Comma-separated list of allowed browser origins.
    allowed_origins: str = "http://localhost:5173"

    # --- Object storage + dataset pipeline (carried over from external-data) --
    storage_backend: str = "local"            # "local" | "supabase" | "r2"
    local_root: str = ".data"
    supabase_s3_endpoint: str | None = None
    supabase_s3_access_key: str | None = None
    supabase_s3_secret: str | None = None
    r2_s3_endpoint: str | None = None
    r2_access_key: str | None = None
    r2_secret: str | None = None
    external_data_bucket: str = "external-data"
    db_url: str | None = None
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"

    # --- Upstream timeouts (seconds) -----------------------------------------
    supabase_timeout_s: float = 10.0
    anthropic_timeout_s: float = 30.0

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
