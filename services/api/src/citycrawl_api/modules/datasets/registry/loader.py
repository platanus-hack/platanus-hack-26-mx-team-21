from __future__ import annotations
from importlib.resources import files
import yaml
from citycrawl_api.modules.datasets.registry.models import SourceConfig

_DEFAULT = files("citycrawl_api.modules.datasets.registry") / "sources.yaml"


def load_registry(path: str | None = None) -> list[SourceConfig]:
    raw = open(path).read() if path else _DEFAULT.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    return [SourceConfig(**entry) for entry in data.get("sources", [])]


def get_source(source_id: str, path: str | None = None) -> SourceConfig:
    for s in load_registry(path):
        if s.id == source_id:
            return s
    raise KeyError(source_id)
