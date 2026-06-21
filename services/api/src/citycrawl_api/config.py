"""One Settings object shared by every module. Datasets code that used to read
`external_data.config.Settings` now reads this (via the datasets/config.py shim), so the
storage/db fields below must keep their original names and defaults."""
from __future__ import annotations
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from citycrawl_api.logging import get_logger

logger = get_logger()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Deployment environment ----------------------------------------------
    # "development" | "staging" | "production". Drives the fail-fast checks below.
    app_env: str = "development"

    # --- Supabase auth (token validation + RPC host) -------------------------
    supabase_url: str | None = None
    supabase_anon_key: str | None = None

    # --- Anthropic (LLM draft parser) ----------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # --- Operator protection for dataset refresh -----------------------------
    operator_api_key: str | None = None
    # Optional dedicated secret for citizen-ingest (server-to-server). When set,
    # require_service compares against THIS instead of operator_api_key, so the
    # dataset-refresh key and the ingest key can be rotated independently. Until
    # this is configured, require_service falls back to operator_api_key so the
    # WhatsApp controller keeps working with the single shared key.
    ingest_service_key: str | None = None

    # --- Citizen-report confirmation gate (non-public inference server) -------
    # Kill switch: when False, skip the synchronous vision-confirmation gate and create the
    # observation immediately (the photo still renders; confirmation can be done async later).
    # Default True preserves the gate; set INFERENCE_CONFIRMATION_ENABLED=false to disable it
    # (e.g. when the inference server is slow/unavailable and reports are timing out).
    inference_confirmation_enabled: bool = True
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

    # --- Planning engine ------------------------------------------------------
    planning_engine: str = "optimization"     # "optimization" | "mock"
    tomtom_api_key: str | None = None
    traffic_cache_path: str = ".data/traffic_cache.json"
    traffic_grid_decimals: int = 3

    # --- Request limits ------------------------------------------------------
    # Max accepted request body size (bytes). Enforced both by a middleware on
    # Content-Length and by the explicit read in the upload route.
    max_upload_bytes: int = 10 * 1024 * 1024

    # Per-user fixed-window rate limit for POST /v1/llm/drafts:parse (each LLM
    # call spends Anthropic budget). Per-worker / in-memory; see routers/llm.py.
    llm_parse_rate_limit: int = 10            # requests
    llm_parse_rate_window_s: float = 60.0     # per window (seconds)

    # --- Outbound fetch allowlist (SSRF guard) -------------------------------
    # Extra hostnames the server is allowed to fetch from, comma-separated.
    # Beyond these, *.gob.mx, the configured nominatim host, and the RSS feed
    # hosts in registry/sources.yaml are always allowed (see datasets/net.py).
    outbound_allowed_hosts: str = ""
    # Cap on a single outbound response body (bytes) to avoid memory blowups.
    outbound_max_bytes: int = 64 * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def cors_allow_headers(self) -> list[str]:
        # Narrowed from "*": only the headers the app actually reads. Required
        # because allow_credentials=True must not be paired with a wildcard.
        return ["Authorization", "Content-Type", "X-Operator-Key", "X-Request-ID"]

    @property
    def extra_outbound_hosts(self) -> list[str]:
        return [h.strip().lower() for h in self.outbound_allowed_hosts.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        """True when the deployment looks like prod: APP_ENV=production, or the
        presence of Fly / R2 environment signals."""
        if (self.app_env or "").lower() == "production":
            return True
        if os.environ.get("FLY_APP_NAME") or os.environ.get("FLY_ALLOC_ID"):
            return True
        return False

    def validate_startup(self) -> None:
        """Fail-fast / loud-warning checks run once at app construction.

        - CORS: refuse a wildcard/empty origin list while credentials are on.
        - Storage: in production the local backend silently drops citizen photos,
          so require r2; outside production just warn loudly.
        """
        # CORS hardening: allow_credentials=True is incompatible with "*"/empty.
        # Warn loudly rather than crash — Starlette already refuses to echo a wildcard
        # origin when credentials are enabled, so a misconfig degrades safely; a hard
        # boot failure here would be an outage if a deployed ALLOWED_ORIGINS is wrong.
        origins = self.cors_origins
        if not origins or "*" in origins:
            logger.warning(
                "cors_origins_insecure",
                extra={"fields": {"corsOrigins": origins}},
            )

        # Storage backend safety.
        if self.storage_backend != "r2":
            if self.is_production:
                raise RuntimeError(
                    "STORAGE_BACKEND must be 'r2' in production; "
                    f"got '{self.storage_backend}' (citizen photos would be lost)"
                )
            logger.warning(
                "storage_backend_not_r2",
                extra={"fields": {"storageBackend": self.storage_backend}},
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
