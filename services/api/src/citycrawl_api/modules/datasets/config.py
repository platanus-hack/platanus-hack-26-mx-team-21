"""Datasets config is the shared API config. This shim keeps the moved pipeline's
`from citycrawl_api.modules.datasets.config import Settings, get_settings` imports working
while there is a single source of truth in citycrawl_api.config."""
from citycrawl_api.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
