from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    storage_backend: str = "local"            # "local" | "supabase"
    local_root: str = ".data"
    supabase_s3_endpoint: str | None = None
    supabase_s3_access_key: str | None = None
    supabase_s3_secret: str | None = None
    external_data_bucket: str = "external-data"
    db_url: str | None = None
    anthropic_api_key: str | None = None
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"


@lru_cache
def get_settings() -> Settings:
    return Settings()
