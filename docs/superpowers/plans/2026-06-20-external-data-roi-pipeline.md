# External-Signal ROI Pipeline (CDMX) — Implementation Plan

> **⚠️ Superseded (storage):** The object-storage portions of this document describe the original **Supabase Storage** implementation, which has since been migrated to **Cloudflare R2** with a Postgres-mediated access broker (no Supabase signed URLs, no `storage.buckets`, no Storage-RLS). For the current storage contract see [`supabase/STORAGE.md`](../../../supabase/STORAGE.md) and the migration docs (`docs/superpowers/specs/2026-06-20-cloudflare-migration-design.md`, `docs/superpowers/plans/2026-06-20-cloudflare-storage-broker-migration.md`). All non-storage content below remains accurate.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract CDMX point/geocodable risk signals, cluster them into granular risk-semantic ROI polygons, and persist them with a current/superseded lifecycle for the Priority Engine and Latent Issue Detection.

**Architecture:** A registry-driven Python package (`services/external-data/`). Adapters extract sources → raw + staging objects in object storage (local FS in dev, Supabase Storage in prod) → normalized `Signal` records. A pure-Python ROI engine (scikit-learn DBSCAN + shapely) clusters signals per risk dimension into polygons with risk semantics and a generated description. A `RoiStore` persists ROI generations with per-dimension supersession. The relational tables (`priority.external_signals`, `priority.roi_runs`, `priority.rois`) and an `external-data` bucket are authored as Supabase migrations for the DB-capable agent to apply.

**Tech Stack:** Python 3.11 · httpx · pydantic v2 / pydantic-settings · pyyaml · typer · pandas · pyarrow · shapely 2.x · scikit-learn · numpy · pyproj · feedparser · anthropic · fsspec + s3fs · psycopg[binary] · pytest.

## Global Constraints

- **Source of truth:** `docs/superpowers/specs/2026-06-20-external-data-pipeline-design.md`.
- **Scope:** Mexico City (CDMX) only. Hard requirement: per-record geolocation (lat/long or geocodable address).
- **This agent has no Supabase MCP / no local Supabase CLI/Docker.** SQL migrations + assertion tests are **authored only** (Task 11), numbered **`0101+`** to avoid the parallel DB agent's reserved `0003`–`0014`. The Python pipeline must run fully with `STORAGE_BACKEND=local` and an in-memory `RoiStore` — **no live Supabase needed for any pytest**.
- **Schema placement:** external-signal/ROI tables live in the existing **`priority`** schema (created by migration `0001`). Do not create or modify the parallel agent's tables.
- **DB conventions to mirror:** `id uuid primary key default gen_random_uuid()`; `text` + `check (... in (...))` enums; `timestamptz` with `default now()`; PostGIS `geography`/`geometry(...,4326)` + GIST indexes; PostGIS lives in the `extensions` schema.
- **Canonical taxonomy:** risk dimensions = `crash`, `violation`, `flooding`, `road_surface`, `crime`. `geom_quality` ∈ `point` | `geocoded` | `block_centroid`.
- **Determinism:** `signal_id` is a deterministic hash; re-runs never duplicate. ROI recompute is a new generation that supersedes prior current ROIs for the recomputed dimensions only.
- **CDMX bbox** (drop out-of-city coords): lon ∈ [-99.36, -98.94], lat ∈ [19.04, 19.59].
- **CRS for metric clustering:** project WGS84 → EPSG:32614 (UTM 14N).
- DRY, YAGNI, TDD, frequent commits. Run tests with `cd services/external-data && pytest`.

---

## File Structure

```
services/external-data/
  pyproject.toml
  .env.example
  README.md
  src/external_data/
    __init__.py            # version
    config.py              # env settings (pydantic-settings)
    schema.py              # Signal, Roi, RoiRun, RoiParams, taxonomy
    core/
      ids.py               # deterministic signal_id
      bbox.py              # CDMX bbox + recency weight
      storage.py           # ObjectStore (local fs / supabase s3 via fsspec)
      manifest.py          # raw-fetch manifest
    registry/
      models.py            # SourceConfig
      loader.py            # load + validate sources.yaml
      sources.yaml         # the CDMX source catalog
    adapters/
      base.py              # Adapter protocol, ExtractContext
      ckan_csv.py          # CKAN download + CSV → Signal
      news_geocode.py      # RSS → extract → geocode → Signal
    geocode/
      base.py              # Geocoder, Extractor protocols + dataclasses
      nominatim.py         # Nominatim geocoder
      llm.py               # Claude extractor + geocode fallback
    roi/
      engine.py            # cluster + polygon + semantics + describe (pure)
      store.py             # RoiStore protocol, InMemoryRoiStore, PgRoiStore
      runner.py            # compute_and_store orchestration
    cli.py                 # typer app: extract / roi / status
  tests/
    fixtures/              # recorded CKAN CSV + RSS samples
    test_*.py
supabase/
  migrations/0101_priority_external_signals.sql
  migrations/0102_priority_rois.sql
  migrations/0103_external_data_storage.sql
  tests/0101_priority_external_signals.test.sql
  tests/0102_priority_rois.test.sql
  tests/0103_external_data_storage.test.sql
```

---

### Task 1: Package scaffolding & config

**Files:**
- Create: `services/external-data/pyproject.toml`
- Create: `services/external-data/src/external_data/__init__.py`
- Create: `services/external-data/src/external_data/config.py`
- Create: `services/external-data/.env.example`
- Test: `services/external-data/tests/test_config.py`

**Interfaces:**
- Produces: `external_data.__version__: str`; `external_data.config.Settings` (pydantic-settings) with `storage_backend: str = "local"`, `local_root: str = ".data"`, `supabase_s3_endpoint/access_key/secret: str|None`, `external_data_bucket: str = "external-data"`, `db_url: str|None`, `anthropic_api_key: str|None`, `nominatim_base_url: str = "https://nominatim.openstreetmap.org"`; `config.get_settings() -> Settings`.

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_config.py
from external_data import __version__
from external_data.config import get_settings


def test_version_present():
    assert isinstance(__version__, str) and __version__


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    s = get_settings()
    assert s.storage_backend == "local"
    assert s.external_data_bucket == "external-data"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    get_settings.cache_clear()
    assert get_settings().storage_backend == "supabase"
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'external_data'`.

- [ ] **Step 3: Write pyproject and package files**

```toml
# services/external-data/pyproject.toml
[project]
name = "external-data"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27", "pydantic>=2.6", "pydantic-settings>=2.2", "pyyaml>=6",
  "typer>=0.12", "pandas>=2.2", "pyarrow>=15", "shapely>=2.0",
  "scikit-learn>=1.4", "numpy>=1.26", "pyproj>=3.6", "feedparser>=6",
  "anthropic>=0.40", "fsspec>=2024.6", "s3fs>=2024.6", "psycopg[binary]>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
external-data = "external_data.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
external_data = ["registry/sources.yaml"]
```

```python
# services/external-data/src/external_data/__init__.py
__version__ = "0.1.0"
```

```python
# services/external-data/src/external_data/config.py
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
```

```bash
# services/external-data/.env.example
STORAGE_BACKEND=local            # local | supabase
LOCAL_ROOT=.data
SUPABASE_S3_ENDPOINT=https://joixzhdpnxqhnuscxsoy.storage.supabase.co/storage/v1/s3
SUPABASE_S3_ACCESS_KEY=__set_me__
SUPABASE_S3_SECRET=__set_me__
EXTERNAL_DATA_BUCKET=external-data
DB_URL=postgresql://postgres:__pw__@db.joixzhdpnxqhnuscxsoy.supabase.co:5432/postgres
ANTHROPIC_API_KEY=__set_me__
NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org
```

- [ ] **Step 4: Install editable and run tests**

Run: `cd services/external-data && pip install -e ".[dev]" && python -m pytest tests/test_config.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/pyproject.toml services/external-data/src/external_data/__init__.py services/external-data/src/external_data/config.py services/external-data/.env.example services/external-data/tests/test_config.py
git commit -m "feat(external-data): package scaffolding and settings"
```

---

### Task 2: Canonical schema & taxonomy

**Files:**
- Create: `services/external-data/src/external_data/schema.py`
- Test: `services/external-data/tests/test_schema.py`

**Interfaces:**
- Produces:
  - `DIMENSIONS: frozenset[str]` = {`crash`,`violation`,`flooding`,`road_surface`,`crime`}
  - `GEOM_QUALITY: frozenset[str]` = {`point`,`geocoded`,`block_centroid`}
  - `GEOM_QUALITY_FACTOR: dict[str,float]` = {point:1.0, geocoded:0.7, block_centroid:0.5}
  - `Signal` (pydantic) fields: `signal_id, source_id, risk_dimension, event_type, event_subtype|None, lon, lat, geom_quality, occurred_at|None, reported_at|None, severity_weight=1.0, geocode_confidence|None, attributes: dict, source_object_ref|None, source_url|None, license|None, fetched_at|None`
  - `Roi` (pydantic): `risk_dimension, polygon_wkt, centroid_lon, centroid_lat, area_m2, risk_score, signal_count, dominant_type, risk_breakdown: dict, occurred_from|None, occurred_to|None, recency_score, description, contributing_signal_ids: list[str], source_object_refs: list[str]`
  - `RoiParams` (pydantic): `eps_m=100.0, min_points=5, buffer_m=15.0, half_life_days=365.0, per_dimension: dict[str, dict] = {}` + method `for_dimension(dim) -> RoiParams`
  - `RoiRun` (pydantic): `run_id: str, dimensions: list[str], params: dict, roi_count: int`

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_schema.py
import pytest
from external_data.schema import Signal, Roi, RoiParams, DIMENSIONS, GEOM_QUALITY_FACTOR


def test_dimensions_set():
    assert DIMENSIONS == {"crash", "violation", "flooding", "road_surface", "crime"}
    assert GEOM_QUALITY_FACTOR["block_centroid"] == 0.5


def test_signal_rejects_bad_dimension():
    with pytest.raises(ValueError):
        Signal(signal_id="a", source_id="s", risk_dimension="nope",
               event_type="x", lon=-99.1, lat=19.4, geom_quality="point")


def test_signal_rejects_out_of_range_lat():
    with pytest.raises(ValueError):
        Signal(signal_id="a", source_id="s", risk_dimension="crash",
               event_type="x", lon=-99.1, lat=200.0, geom_quality="point")


def test_roiparams_for_dimension_override():
    p = RoiParams(eps_m=100, per_dimension={"crash": {"eps_m": 60, "min_points": 8}})
    c = p.for_dimension("crash")
    assert c.eps_m == 60 and c.min_points == 8
    assert p.for_dimension("crime").eps_m == 100
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.schema`.

- [ ] **Step 3: Write the schema**

```python
# services/external-data/src/external_data/schema.py
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

DIMENSIONS = frozenset({"crash", "violation", "flooding", "road_surface", "crime"})
GEOM_QUALITY = frozenset({"point", "geocoded", "block_centroid"})
GEOM_QUALITY_FACTOR = {"point": 1.0, "geocoded": 0.7, "block_centroid": 0.5}


class Signal(BaseModel):
    signal_id: str
    source_id: str
    risk_dimension: str
    event_type: str
    event_subtype: str | None = None
    lon: float
    lat: float
    geom_quality: str = "point"
    occurred_at: datetime | None = None
    reported_at: datetime | None = None
    severity_weight: float = 1.0
    geocode_confidence: float | None = None
    attributes: dict = Field(default_factory=dict)
    source_object_ref: str | None = None
    source_url: str | None = None
    license: str | None = None
    fetched_at: datetime | None = None

    @field_validator("risk_dimension")
    @classmethod
    def _dim(cls, v: str) -> str:
        if v not in DIMENSIONS:
            raise ValueError(f"unknown risk_dimension {v!r}")
        return v

    @field_validator("geom_quality")
    @classmethod
    def _gq(cls, v: str) -> str:
        if v not in GEOM_QUALITY:
            raise ValueError(f"unknown geom_quality {v!r}")
        return v

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("lat out of range")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("lon out of range")
        return v


class Roi(BaseModel):
    risk_dimension: str
    polygon_wkt: str
    centroid_lon: float
    centroid_lat: float
    area_m2: float
    risk_score: float
    signal_count: int
    dominant_type: str
    risk_breakdown: dict
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    recency_score: float = 0.0
    description: str = ""
    contributing_signal_ids: list[str] = Field(default_factory=list)
    source_object_refs: list[str] = Field(default_factory=list)


class RoiParams(BaseModel):
    eps_m: float = 100.0
    min_points: int = 5
    buffer_m: float = 15.0
    half_life_days: float = 365.0
    per_dimension: dict[str, dict] = Field(default_factory=dict)

    def for_dimension(self, dim: str) -> "RoiParams":
        base = self.model_dump(exclude={"per_dimension"})
        base.update(self.per_dimension.get(dim, {}))
        return RoiParams(**base)


class RoiRun(BaseModel):
    run_id: str
    dimensions: list[str]
    params: dict
    roi_count: int = 0
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/schema.py services/external-data/tests/test_schema.py
git commit -m "feat(external-data): canonical Signal/Roi schema and taxonomy"
```

---

### Task 3: Source registry

**Files:**
- Create: `services/external-data/src/external_data/registry/models.py`
- Create: `services/external-data/src/external_data/registry/loader.py`
- Create: `services/external-data/src/external_data/registry/sources.yaml`
- Create: `services/external-data/src/external_data/registry/__init__.py` (empty)
- Test: `services/external-data/tests/test_registry.py`

**Interfaces:**
- Consumes: `schema.DIMENSIONS`.
- Produces:
  - `registry.models.ColumnMap` (pydantic): `lon, lat, occurred_at|None, reported_at|None, native_id|None, event_subtype|None, attributes: list[str] = []`
  - `registry.models.SourceConfig` (pydantic): `id, kind ("ckan_csv"|"news_geocode"), enabled=True, risk_dimension, event_type, ckan_slug|None, resource_match|None, feeds: list[str]=[], column_map|None, subset: dict|None, geom_quality="point", severity: dict[str,float]={}, default_severity=1.0, license|None, schedule|None`
  - `registry.loader.load_registry(path: str|None=None) -> list[SourceConfig]` (defaults to packaged `sources.yaml`); `registry.loader.get_source(source_id, path=None) -> SourceConfig`

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_registry.py
from external_data.registry.loader import load_registry, get_source
from external_data.schema import DIMENSIONS


def test_registry_loads_and_validates():
    sources = load_registry()
    ids = {s.id for s in sources}
    # the kept CDMX sources from the spec
    assert {"ssc_hechos_transito", "fgj_carpetas", "infracciones_ee",
            "sacmex_encharcamientos", "news_nota_roja"} <= ids
    for s in sources:
        assert s.risk_dimension in DIMENSIONS
        assert s.kind in ("ckan_csv", "news_geocode")
        if s.kind == "ckan_csv":
            assert s.ckan_slug and s.column_map


def test_get_source():
    s = get_source("ssc_hechos_transito")
    assert s.risk_dimension == "crash"
    assert s.column_map.lat == "latitud" and s.column_map.lon == "longitud"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.registry.loader`.

- [ ] **Step 3: Write models, loader, and sources.yaml**

```python
# services/external-data/src/external_data/registry/models.py
from __future__ import annotations
from pydantic import BaseModel, field_validator
from external_data.schema import DIMENSIONS, GEOM_QUALITY


class ColumnMap(BaseModel):
    lon: str
    lat: str
    occurred_at: str | None = None
    reported_at: str | None = None
    native_id: str | None = None
    event_subtype: str | None = None
    attributes: list[str] = []


class SourceConfig(BaseModel):
    id: str
    kind: str
    enabled: bool = True
    risk_dimension: str
    event_type: str
    ckan_slug: str | None = None
    resource_match: str | None = None
    feeds: list[str] = []
    column_map: ColumnMap | None = None
    subset: dict | None = None           # {column: [allowed values]} filter on native rows
    geom_quality: str = "point"
    severity: dict[str, float] = {}      # event_subtype -> weight
    default_severity: float = 1.0
    license: str | None = None
    schedule: str | None = None

    @field_validator("risk_dimension")
    @classmethod
    def _dim(cls, v):
        if v not in DIMENSIONS:
            raise ValueError(f"bad dimension {v}")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("ckan_csv", "news_geocode"):
            raise ValueError(f"bad kind {v}")
        return v

    @field_validator("geom_quality")
    @classmethod
    def _gq(cls, v):
        if v not in GEOM_QUALITY:
            raise ValueError(f"bad geom_quality {v}")
        return v
```

```python
# services/external-data/src/external_data/registry/loader.py
from __future__ import annotations
from importlib.resources import files
import yaml
from external_data.registry.models import SourceConfig

_DEFAULT = files("external_data.registry") / "sources.yaml"


def load_registry(path: str | None = None) -> list[SourceConfig]:
    raw = (open(path).read() if path else _DEFAULT.read_text(encoding="utf-8"))
    data = yaml.safe_load(raw) or {}
    return [SourceConfig(**entry) for entry in data.get("sources", [])]


def get_source(source_id: str, path: str | None = None) -> SourceConfig:
    for s in load_registry(path):
        if s.id == source_id:
            return s
    raise KeyError(source_id)
```

```yaml
# services/external-data/src/external_data/registry/sources.yaml
# CDMX external risk-signal catalog. Verified against the CKAN API 2026-06-20.
# Each source maps to exactly one risk dimension. See the design spec §2.
sources:
  - id: ssc_hechos_transito
    kind: ckan_csv
    risk_dimension: crash
    event_type: traffic_crash
    ckan_slug: hechos-de-transito-registrados-por-la-ssc-2024-serie-de-datos-ampliada-no-comparativa
    resource_match: "(?i)^hechos de tr.nsito registrados por la ssc$"
    geom_quality: point
    license: CC-BY-4.0
    schedule: monthly
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_hechos,
                 attributes: [tipo_evento, alcaldia, colonia]}

  - id: c5_incidentes_viales
    kind: ckan_csv
    risk_dimension: crash
    event_type: traffic_incident
    ckan_slug: incidentes-viales-c5
    resource_match: "(?i)2022.*2024"
    geom_quality: point
    license: CC-BY-4.0
    schedule: monthly
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_creacion,
                 event_subtype: incidente_c4, attributes: [alcaldia, dia_semana]}

  - id: fgj_carpetas
    kind: ckan_csv
    risk_dimension: crime
    event_type: crime
    ckan_slug: carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico
    resource_match: "(?i)acumulado"
    geom_quality: point
    license: CC-BY-4.0
    schedule: monthly
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_hecho,
                 event_subtype: categoria_delito, attributes: [delito, alcaldia_hecho]}

  - id: fgj_victimas
    kind: ckan_csv
    risk_dimension: crime
    event_type: crime_victim
    ckan_slug: victimas-en-carpetas-de-investigacion-fgj
    resource_match: "(?i)2024|acumulado"
    geom_quality: point
    license: CC-BY-4.0
    schedule: monthly
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_hecho,
                 event_subtype: categoria_delito, attributes: [delito, sexo, edad]}

  - id: sacmex_encharcamientos
    kind: ckan_csv
    risk_dimension: flooding
    event_type: water_report
    ckan_slug: reportes-de-agua
    resource_match: "(?i)2022.*2024"
    geom_quality: point
    license: CC-BY-4.0
    schedule: monthly
    subset: {tipo_reporte: ["ENCHARCAMIENTO", "ENCHARCAMIENTOS", "INUNDACION"]}
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha,
                 event_subtype: tipo_reporte, attributes: [colonia_catalogo]}

  - id: locatel_0311_agua
    kind: ckan_csv
    risk_dimension: flooding
    event_type: citizen_report
    ckan_slug: "0311"
    resource_match: "(?i)2024"
    geom_quality: point
    license: CC-BY-4.0
    subset: {tema: ["AGUA"]}
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_alta,
                 event_subtype: tema, attributes: [colonia_catalogo]}

  - id: locatel_0311_baches
    kind: ckan_csv
    risk_dimension: road_surface
    event_type: citizen_report
    ckan_slug: "0311"
    resource_match: "(?i)2024"
    geom_quality: point
    license: CC-BY-4.0
    subset: {tema: ["BACHE", "BACHES", "BACHEO"]}
    column_map: {lon: longitud, lat: latitud, occurred_at: fecha_alta,
                 event_subtype: tema, attributes: [colonia_catalogo]}

  - id: infracciones_ee
    kind: news_geocode      # address-level → geocode path (no lat/long in source)
    risk_dimension: violation
    event_type: traffic_violation
    geom_quality: geocoded
    license: CC-BY-4.0
    feeds: []               # populated by a CKAN-address loader variant; see Task 7 note
    schedule: weekly

  - id: news_nota_roja
    kind: news_geocode
    risk_dimension: crash
    event_type: traffic_incident_news
    geom_quality: geocoded
    schedule: daily
    feeds:
      - https://www.eluniversal.com.mx/rss/metropoli.xml
      - https://www.jornada.com.mx/rss/capital.xml
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_registry.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/registry/ services/external-data/tests/test_registry.py
git commit -m "feat(external-data): source registry + CDMX catalog"
```

> **Note on `resource_match`/`column_map` accuracy:** the exact CSV header names (e.g. `fecha_hechos` vs `fecha_hecho`) must be confirmed against each resource's real header at build time via `datastore_search?limit=1`. SSC/FGJ/0311/SACMEX lat-long columns were verified `latitud`/`longitud` on 2026-06-20. Fix any mismatched attribute/date column names when Task 6's live smoke runs.

---

### Task 4: Core utilities — ids, bbox, manifest

**Files:**
- Create: `services/external-data/src/external_data/core/__init__.py` (empty)
- Create: `services/external-data/src/external_data/core/ids.py`
- Create: `services/external-data/src/external_data/core/bbox.py`
- Create: `services/external-data/src/external_data/core/manifest.py`
- Test: `services/external-data/tests/test_core_utils.py`

**Interfaces:**
- Produces:
  - `core.ids.signal_id(source_id: str, native_id: str) -> str` (sha256 hex, 32 chars)
  - `core.bbox.CDMX_BBOX = (-99.36, 19.04, -98.94, 19.59)` (minlon,minlat,maxlon,maxlat); `core.bbox.in_cdmx(lon, lat) -> bool`; `core.bbox.recency_weight(occurred_at: datetime|None, half_life_days: float, now: datetime) -> float`
  - `core.manifest.Manifest` (pydantic): `source_id, source_url, sha256, byte_size, row_count, license|None, fetched_at: datetime, adapter: str`

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_core_utils.py
from datetime import datetime, timezone, timedelta
from external_data.core.ids import signal_id
from external_data.core.bbox import in_cdmx, recency_weight


def test_signal_id_deterministic():
    a = signal_id("ssc", "row-1")
    assert a == signal_id("ssc", "row-1")
    assert a != signal_id("ssc", "row-2")
    assert len(a) == 32


def test_in_cdmx():
    assert in_cdmx(-99.13, 19.43)         # Zócalo
    assert not in_cdmx(-100.31, 25.67)    # Monterrey
    assert not in_cdmx(0.0, 0.0)


def test_recency_weight_halves_at_half_life():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = now - timedelta(days=365)
    assert recency_weight(now, 365, now) == 1.0
    assert abs(recency_weight(old, 365, now) - 0.5) < 1e-6
    assert recency_weight(None, 365, now) == 0.5   # unknown date → neutral half
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_core_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.core.ids`.

- [ ] **Step 3: Write the utilities**

```python
# services/external-data/src/external_data/core/ids.py
import hashlib


def signal_id(source_id: str, native_id: str) -> str:
    return hashlib.sha256(f"{source_id}|{native_id}".encode()).hexdigest()[:32]
```

```python
# services/external-data/src/external_data/core/bbox.py
from __future__ import annotations
import math
from datetime import datetime

CDMX_BBOX = (-99.36, 19.04, -98.94, 19.59)  # minlon, minlat, maxlon, maxlat


def in_cdmx(lon: float, lat: float) -> bool:
    mnx, mny, mxx, mxy = CDMX_BBOX
    return mnx <= lon <= mxx and mny <= lat <= mxy


def recency_weight(occurred_at: datetime | None, half_life_days: float, now: datetime) -> float:
    if occurred_at is None:
        return 0.5
    age_days = max(0.0, (now - occurred_at).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life_days)
```

```python
# services/external-data/src/external_data/core/manifest.py
from datetime import datetime
from pydantic import BaseModel


class Manifest(BaseModel):
    source_id: str
    source_url: str
    sha256: str
    byte_size: int
    row_count: int
    license: str | None = None
    fetched_at: datetime
    adapter: str
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_core_utils.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/core/ services/external-data/tests/test_core_utils.py
git commit -m "feat(external-data): core ids, bbox, recency, manifest"
```

---

### Task 5: Object storage abstraction

**Files:**
- Create: `services/external-data/src/external_data/core/storage.py`
- Test: `services/external-data/tests/test_storage.py`

**Interfaces:**
- Consumes: `config.Settings`.
- Produces: `core.storage.ObjectStore` with `write_bytes(path: str, data: bytes) -> str`, `write_text(path, text) -> str`, `read_text(path) -> str`, `exists(path) -> bool`, and attribute `root: str`; factory `core.storage.make_store(settings) -> ObjectStore`. Paths are bucket-relative POSIX strings; `write_*` returns the full object ref (`root/path`).

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_storage.py
from external_data.config import Settings
from external_data.core.storage import make_store


def test_local_store_roundtrip(tmp_path):
    s = make_store(Settings(storage_backend="local", local_root=str(tmp_path)))
    ref = s.write_text("raw/ssc/2026/f.csv", "a,b\n1,2\n")
    assert s.exists("raw/ssc/2026/f.csv")
    assert s.read_text("raw/ssc/2026/f.csv") == "a,b\n1,2\n"
    assert ref.endswith("raw/ssc/2026/f.csv")
    assert not s.exists("raw/ssc/2026/missing.csv")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_storage.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.core.storage`.

- [ ] **Step 3: Write the storage abstraction**

```python
# services/external-data/src/external_data/core/storage.py
from __future__ import annotations
import fsspec
from external_data.config import Settings


class ObjectStore:
    def __init__(self, fs: fsspec.AbstractFileSystem, root: str):
        self.fs = fs
        self.root = root.rstrip("/")

    def _full(self, path: str) -> str:
        return f"{self.root}/{path.lstrip('/')}"

    def write_bytes(self, path: str, data: bytes) -> str:
        full = self._full(path)
        self.fs.makedirs(full.rsplit("/", 1)[0], exist_ok=True)
        with self.fs.open(full, "wb") as fh:
            fh.write(data)
        return full

    def write_text(self, path: str, text: str) -> str:
        return self.write_bytes(path, text.encode("utf-8"))

    def read_text(self, path: str) -> str:
        with self.fs.open(self._full(path), "rb") as fh:
            return fh.read().decode("utf-8")

    def exists(self, path: str) -> bool:
        return self.fs.exists(self._full(path))


def make_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "supabase":
        fs = fsspec.filesystem(
            "s3",
            key=settings.supabase_s3_access_key,
            secret=settings.supabase_s3_secret,
            client_kwargs={"endpoint_url": settings.supabase_s3_endpoint},
        )
        return ObjectStore(fs, settings.external_data_bucket)
    fs = fsspec.filesystem("file")
    return ObjectStore(fs, settings.local_root)
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_storage.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/core/storage.py services/external-data/tests/test_storage.py
git commit -m "feat(external-data): fsspec object-store abstraction (local/supabase)"
```

---

### Task 6: CKAN CSV adapter

**Files:**
- Create: `services/external-data/src/external_data/adapters/__init__.py` (empty)
- Create: `services/external-data/src/external_data/adapters/base.py`
- Create: `services/external-data/src/external_data/adapters/ckan_csv.py`
- Create: `services/external-data/tests/fixtures/ssc_sample.csv`
- Test: `services/external-data/tests/test_ckan_csv.py`

**Interfaces:**
- Consumes: `schema.Signal`, `registry.models.SourceConfig`, `core.ids.signal_id`, `core.bbox.in_cdmx`, `core.storage.ObjectStore`.
- Produces:
  - `adapters.base.ExtractContext` (dataclass): `store: ObjectStore, now: datetime, http_get: Callable[[str], httpx.Response] | None = None`
  - `adapters.ckan_csv.rows_to_signals(rows: list[dict], source: SourceConfig, now: datetime) -> list[Signal]` (pure; applies subset filter, column_map, bbox drop, geom_quality, severity, deterministic id; native_id = column_map.native_id or stable row hash)
  - `adapters.ckan_csv.resolve_resource_url(slug: str, resource_match: str, http_get) -> tuple[str, str]` (returns `(resource_id, download_url)` via CKAN `package_show`)
  - `adapters.ckan_csv.extract(source: SourceConfig, ctx: ExtractContext) -> list[Signal]` (resolve → download → land raw + manifest → parse)

- [ ] **Step 1: Write the failing test (pure parsing — no network)**

```python
# services/external-data/tests/test_ckan_csv.py
import csv, io
from datetime import datetime, timezone
from external_data.adapters.ckan_csv import rows_to_signals
from external_data.registry.loader import get_source

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _rows():
    text = open("tests/fixtures/ssc_sample.csv", encoding="utf-8").read()
    return list(csv.DictReader(io.StringIO(text)))


def test_rows_to_signals_maps_and_filters():
    src = get_source("ssc_hechos_transito")
    sigs = rows_to_signals(_rows(), src, NOW)
    # 3 rows in fixture; one is in Monterrey and must be dropped by bbox
    assert len(sigs) == 2
    s = sigs[0]
    assert s.risk_dimension == "crash" and s.event_type == "traffic_crash"
    assert s.geom_quality == "point"
    assert -99.36 <= s.lon <= -98.94 and 19.04 <= s.lat <= 19.59
    assert s.signal_id == sigs[0].signal_id           # deterministic
    assert "alcaldia" in s.attributes


def test_rows_to_signals_dedup_ids_stable():
    src = get_source("ssc_hechos_transito")
    a = {x.signal_id for x in rows_to_signals(_rows(), src, NOW)}
    b = {x.signal_id for x in rows_to_signals(_rows(), src, NOW)}
    assert a == b and len(a) == 2
```

```csv
# services/external-data/tests/fixtures/ssc_sample.csv
id_evento,latitud,longitud,fecha_hechos,tipo_evento,alcaldia,colonia
E1,19.4326,-99.1332,2024-05-01,colision,Cuauhtemoc,Centro
E2,19.3600,-99.1800,2024-06-15,atropello,Benito Juarez,Narvarte
E3,25.6700,-100.3100,2024-06-20,colision,Monterrey,Centro
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_ckan_csv.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.adapters.ckan_csv`.

- [ ] **Step 3: Write base + adapter**

```python
# services/external-data/src/external_data/adapters/base.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
import httpx
from external_data.core.storage import ObjectStore


@dataclass
class ExtractContext:
    store: ObjectStore
    now: datetime
    http_get: Callable[[str], httpx.Response] | None = None

    def get(self, url: str) -> httpx.Response:
        if self.http_get:
            return self.http_get(url)
        return httpx.get(url, timeout=60, follow_redirects=True)
```

```python
# services/external-data/src/external_data/adapters/ckan_csv.py
from __future__ import annotations
import csv, hashlib, io, json, re
from datetime import datetime
from dateutil import parser as dtparse  # from pandas' dep; or use datetime.fromisoformat
from external_data.adapters.base import ExtractContext
from external_data.core.bbox import in_cdmx
from external_data.core.ids import signal_id
from external_data.core.manifest import Manifest
from external_data.registry.models import SourceConfig
from external_data.schema import Signal


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dtparse.parse(value)
    except (ValueError, OverflowError):
        return None


def _passes_subset(row: dict, subset: dict | None) -> bool:
    if not subset:
        return True
    for col, allowed in subset.items():
        val = (row.get(col) or "").strip().upper()
        if val not in {a.upper() for a in allowed}:
            return False
    return True


def _native_id(row: dict, source: SourceConfig) -> str:
    cm = source.column_map
    if cm and cm.native_id and row.get(cm.native_id):
        return str(row[cm.native_id])
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]


def rows_to_signals(rows: list[dict], source: SourceConfig, now: datetime) -> list[Signal]:
    cm = source.column_map
    out: list[Signal] = []
    for row in rows:
        if not _passes_subset(row, source.subset):
            continue
        try:
            lon = float(row[cm.lon]); lat = float(row[cm.lat])
        except (KeyError, TypeError, ValueError):
            continue
        if not in_cdmx(lon, lat):
            continue
        subtype = row.get(cm.event_subtype) if cm.event_subtype else None
        weight = source.severity.get((subtype or "").upper(), source.default_severity)
        out.append(Signal(
            signal_id=signal_id(source.id, _native_id(row, source)),
            source_id=source.id,
            risk_dimension=source.risk_dimension,
            event_type=source.event_type,
            event_subtype=subtype,
            lon=lon, lat=lat,
            geom_quality=source.geom_quality,
            occurred_at=_parse_dt(row.get(cm.occurred_at)) if cm.occurred_at else None,
            reported_at=_parse_dt(row.get(cm.reported_at)) if cm.reported_at else None,
            severity_weight=weight,
            attributes={k: row.get(k) for k in (cm.attributes or [])},
            license=source.license,
            fetched_at=now,
        ))
    return out


def resolve_resource_url(slug: str, resource_match: str | None, ctx: ExtractContext) -> tuple[str, str]:
    api = f"https://datos.cdmx.gob.mx/api/3/action/package_show?id={slug}"
    data = ctx.get(api).json()["result"]["resources"]
    csvs = [r for r in data if (r.get("format") or "").upper() == "CSV"]
    if resource_match:
        rx = re.compile(resource_match)
        matched = [r for r in csvs if rx.search(r.get("name") or "")]
        csvs = matched or csvs
    csvs.sort(key=lambda r: r.get("created") or "", reverse=True)
    if not csvs:
        raise RuntimeError(f"no CSV resource for {slug}")
    return csvs[0]["id"], csvs[0]["url"]


def extract(source: SourceConfig, ctx: ExtractContext) -> list[Signal]:
    rid, url = resolve_resource_url(source.ckan_slug, source.resource_match, ctx)
    body = ctx.get(url).content
    sha = hashlib.sha256(body).hexdigest()
    stamp = ctx.now.strftime("%Y%m%dT%H%M%SZ")
    raw_path = f"raw/{source.id}/{stamp}/{url.rsplit('/', 1)[-1]}"
    ctx.store.write_bytes(raw_path, body)
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace"))))
    ctx.store.write_text(f"raw/{source.id}/{stamp}/manifest.json", Manifest(
        source_id=source.id, source_url=url, sha256=sha, byte_size=len(body),
        row_count=len(rows), license=source.license, fetched_at=ctx.now, adapter="ckan_csv",
    ).model_dump_json())
    return rows_to_signals(rows, source, ctx.now)
```

> Replace `from dateutil import parser as dtparse` with the stdlib if `python-dateutil` is not pulled in transitively: use `datetime.fromisoformat` with a fallback. Add `python-dateutil>=2.9` to `pyproject.toml` dependencies to be explicit.

- [ ] **Step 4: Add `python-dateutil` to deps, reinstall, run tests**

Run: `cd services/external-data && pip install -e ".[dev]" python-dateutil && python -m pytest tests/test_ckan_csv.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/adapters/ services/external-data/tests/test_ckan_csv.py services/external-data/tests/fixtures/ssc_sample.csv services/external-data/pyproject.toml
git commit -m "feat(external-data): CKAN CSV adapter with bbox/subset/column mapping"
```

---

### Task 7: News/geocode adapter

**Files:**
- Create: `services/external-data/src/external_data/geocode/__init__.py` (empty)
- Create: `services/external-data/src/external_data/geocode/base.py`
- Create: `services/external-data/src/external_data/geocode/nominatim.py`
- Create: `services/external-data/src/external_data/geocode/llm.py`
- Create: `services/external-data/src/external_data/adapters/news_geocode.py`
- Create: `services/external-data/tests/fixtures/nota_roja.xml`
- Test: `services/external-data/tests/test_news_geocode.py`

**Interfaces:**
- Consumes: `schema.Signal`, `SourceConfig`, `core.bbox.in_cdmx`, `core.ids.signal_id`.
- Produces:
  - `geocode.base.ExtractedEvent` (dataclass): `native_id, location_text, occurred_at|None, is_incident: bool`
  - `geocode.base.GeocodeResult` (dataclass): `lon, lat, confidence`
  - `geocode.base.Extractor` (Protocol): `extract(title: str, summary: str) -> ExtractedEvent | None`
  - `geocode.base.Geocoder` (Protocol): `geocode(text: str) -> GeocodeResult | None`
  - `adapters.news_geocode.entries_to_signals(entries: list[dict], source, extractor, geocoder, now) -> list[Signal]` (pure given injected extractor/geocoder); entry dict has `id,title,summary`
  - `adapters.news_geocode.extract(source, ctx, extractor, geocoder) -> list[Signal]` (feedparser over `source.feeds`)

- [ ] **Step 1: Write the failing test (fakes — no network/LLM)**

```python
# services/external-data/tests/test_news_geocode.py
from datetime import datetime, timezone
from external_data.geocode.base import ExtractedEvent, GeocodeResult
from external_data.adapters.news_geocode import entries_to_signals
from external_data.registry.loader import get_source

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


class FakeExtractor:
    def extract(self, title, summary):
        if "choque" in (title + summary).lower():
            return ExtractedEvent(native_id=title, location_text="Av. Reforma y Bucareli",
                                  occurred_at=NOW, is_incident=True)
        return ExtractedEvent(native_id=title, location_text="", occurred_at=None, is_incident=False)


class FakeGeocoder:
    def geocode(self, text):
        if "Reforma" in text:
            return GeocodeResult(lon=-99.146, lat=19.435, confidence=0.9)
        return None


def test_entries_to_signals_filters_and_geocodes():
    src = get_source("news_nota_roja")
    entries = [
        {"id": "1", "title": "Choque en Reforma", "summary": "dos autos"},
        {"id": "2", "title": "Clima soleado hoy", "summary": "sin novedades"},
    ]
    sigs = entries_to_signals(entries, src, FakeExtractor(), FakeGeocoder(), NOW)
    assert len(sigs) == 1
    assert sigs[0].geom_quality == "geocoded"
    assert sigs[0].geocode_confidence == 0.9
    assert sigs[0].risk_dimension == "crash"
```

```xml
<!-- services/external-data/tests/fixtures/nota_roja.xml -->
<rss version="2.0"><channel>
  <item><guid>1</guid><title>Choque en Reforma</title><description>dos autos</description></item>
  <item><guid>2</guid><title>Clima soleado</title><description>sin novedades</description></item>
</channel></rss>
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_news_geocode.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.geocode.base`.

- [ ] **Step 3: Write protocols, geocoders, and adapter**

```python
# services/external-data/src/external_data/geocode/base.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class ExtractedEvent:
    native_id: str
    location_text: str
    occurred_at: datetime | None
    is_incident: bool


@dataclass
class GeocodeResult:
    lon: float
    lat: float
    confidence: float


class Extractor(Protocol):
    def extract(self, title: str, summary: str) -> ExtractedEvent | None: ...


class Geocoder(Protocol):
    def geocode(self, text: str) -> GeocodeResult | None: ...
```

```python
# services/external-data/src/external_data/geocode/nominatim.py
from __future__ import annotations
import httpx
from external_data.geocode.base import GeocodeResult


class NominatimGeocoder:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def geocode(self, text: str) -> GeocodeResult | None:
        r = httpx.get(f"{self.base_url}/search", params={
            "q": f"{text}, Ciudad de México, México", "format": "json", "limit": 1,
            "viewbox": "-99.36,19.59,-98.94,19.04", "bounded": 1,
        }, headers={"User-Agent": "external-data-pipeline/0.1"}, timeout=30)
        hits = r.json()
        if not hits:
            return None
        h = hits[0]
        return GeocodeResult(lon=float(h["lon"]), lat=float(h["lat"]),
                             confidence=min(1.0, float(h.get("importance", 0.5))))
```

```python
# services/external-data/src/external_data/geocode/llm.py
from __future__ import annotations
import json
from datetime import datetime
import anthropic
from external_data.geocode.base import ExtractedEvent

_PROMPT = (
    "You extract road-incident facts from a Spanish news headline+summary about "
    "Mexico City. Return JSON: {\"is_incident\": bool, \"location_text\": str, "
    "\"occurred_hint\": str}. is_incident=true only for crashes/collisions/road "
    "hazards. location_text = the most specific street/intersection/colonia named, "
    "or \"\" if none."
)


class ClaudeExtractor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-8"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def extract(self, title: str, summary: str) -> ExtractedEvent | None:
        msg = self.client.messages.create(
            model=self.model, max_tokens=300,
            system=_PROMPT,
            messages=[{"role": "user", "content": f"TITLE: {title}\nSUMMARY: {summary}"}],
        )
        try:
            data = json.loads(msg.content[0].text)
        except (json.JSONDecodeError, IndexError, AttributeError):
            return None
        return ExtractedEvent(
            native_id=title,
            location_text=data.get("location_text", ""),
            occurred_at=None,
            is_incident=bool(data.get("is_incident")),
        )
```

```python
# services/external-data/src/external_data/adapters/news_geocode.py
from __future__ import annotations
from datetime import datetime
import feedparser
from external_data.adapters.base import ExtractContext
from external_data.core.bbox import in_cdmx
from external_data.core.ids import signal_id
from external_data.geocode.base import Extractor, Geocoder
from external_data.registry.models import SourceConfig
from external_data.schema import Signal


def entries_to_signals(entries: list[dict], source: SourceConfig,
                       extractor: Extractor, geocoder: Geocoder, now: datetime) -> list[Signal]:
    out: list[Signal] = []
    for e in entries:
        ev = extractor.extract(e.get("title", ""), e.get("summary", ""))
        if not ev or not ev.is_incident or not ev.location_text:
            continue
        geo = geocoder.geocode(ev.location_text)
        if not geo or not in_cdmx(geo.lon, geo.lat):
            continue
        out.append(Signal(
            signal_id=signal_id(source.id, e.get("id") or ev.native_id),
            source_id=source.id,
            risk_dimension=source.risk_dimension,
            event_type=source.event_type,
            event_subtype=None,
            lon=geo.lon, lat=geo.lat,
            geom_quality="geocoded",
            occurred_at=ev.occurred_at,
            geocode_confidence=geo.confidence,
            attributes={"location_text": ev.location_text, "title": e.get("title")},
            source_url=e.get("link"),
            license=source.license,
            fetched_at=now,
        ))
    return out


def extract(source: SourceConfig, ctx: ExtractContext,
            extractor: Extractor, geocoder: Geocoder) -> list[Signal]:
    entries: list[dict] = []
    for feed in source.feeds:
        parsed = feedparser.parse(feed)
        for it in parsed.entries:
            entries.append({"id": getattr(it, "id", None) or it.get("guid"),
                            "title": it.get("title", ""), "summary": it.get("summary", ""),
                            "link": it.get("link")})
    return entries_to_signals(entries, source, extractor, geocoder, ctx.now)
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_news_geocode.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/geocode/ services/external-data/src/external_data/adapters/news_geocode.py services/external-data/tests/test_news_geocode.py services/external-data/tests/fixtures/nota_roja.xml
git commit -m "feat(external-data): news/RSS -> LLM extract -> geocode adapter"
```

---

### Task 8: ROI engine (pure)

**Files:**
- Create: `services/external-data/src/external_data/roi/__init__.py` (empty)
- Create: `services/external-data/src/external_data/roi/engine.py`
- Test: `services/external-data/tests/test_roi_engine.py`

**Interfaces:**
- Consumes: `schema.Signal`, `schema.Roi`, `schema.RoiParams`, `core.bbox.recency_weight`.
- Produces:
  - `roi.engine.cluster_indices(lonlats: list[tuple[float,float]], eps_m: float, min_points: int) -> list[list[int]]` (DBSCAN on UTM-14N; returns lists of input indices, noise excluded)
  - `roi.engine.compute_rois(signals: list[Signal], params: RoiParams, now: datetime) -> list[Roi]` (clusters a single-dimension signal list; builds polygon, risk_score, breakdown, description)
  - `roi.engine.describe_roi(dimension: str, breakdown: dict, n: int, occurred_to) -> str`

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_roi_engine.py
from datetime import datetime, timezone
from external_data.schema import Signal, RoiParams
from external_data.roi.engine import cluster_indices, compute_rois

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _sig(i, lon, lat, dim="crash", w=1.0, sub="colision"):
    return Signal(signal_id=f"s{i}", source_id="ssc", risk_dimension=dim,
                  event_type="traffic_crash", event_subtype=sub, lon=lon, lat=lat,
                  geom_quality="point", occurred_at=NOW, severity_weight=w)


def test_cluster_indices_groups_dense_separates_far():
    # tight cluster around Zócalo + one far point near Coyoacán
    pts = [(-99.1332, 19.4326), (-99.1334, 19.4327), (-99.1331, 19.4325),
           (-99.1333, 19.4328), (-99.1335, 19.4326), (-99.16, 19.35)]
    groups = cluster_indices(pts, eps_m=100, min_points=4)
    assert len(groups) == 1
    assert set(groups[0]) == {0, 1, 2, 3, 4}      # far point is noise


def test_compute_rois_builds_polygon_and_semantics():
    sigs = [_sig(i, -99.1332 + i * 0.0001, 19.4326 + i * 0.0001) for i in range(6)]
    rois = compute_rois(sigs, RoiParams(eps_m=150, min_points=4), NOW)
    assert len(rois) == 1
    r = rois[0]
    assert r.risk_dimension == "crash"
    assert r.signal_count == 6 and r.risk_score > 0
    assert r.dominant_type == "traffic_crash"
    assert r.area_m2 > 0
    assert r.polygon_wkt.startswith("POLYGON")
    assert len(r.contributing_signal_ids) == 6
    assert "crash" in r.description.lower()


def test_compute_rois_excludes_sparse():
    sigs = [_sig(0, -99.1, 19.4), _sig(1, -99.2, 19.5)]  # 2 far-apart points
    assert compute_rois(sigs, RoiParams(min_points=4), NOW) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_roi_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.roi.engine`.

- [ ] **Step 3: Write the engine**

```python
# services/external-data/src/external_data/roi/engine.py
from __future__ import annotations
from collections import Counter
from datetime import datetime
import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint
from shapely.ops import transform as shp_transform
from sklearn.cluster import DBSCAN
from external_data.core.bbox import recency_weight
from external_data.schema import Roi, RoiParams, Signal, GEOM_QUALITY_FACTOR

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)
_TO_WGS = Transformer.from_crs("EPSG:32614", "EPSG:4326", always_xy=True)

_HYPOTHESES = {
    "crash": "signal timing, lane geometry, lighting, road surface",
    "violation": "signage clarity, signal timing, speed calming",
    "flooding": "drainage capacity, road grade, blocked inlets",
    "road_surface": "pavement condition, recurring potholes",
    "crime": "lighting, sightlines, activation of the space",
}


def cluster_indices(lonlats: list[tuple[float, float]], eps_m: float, min_points: int) -> list[list[int]]:
    if len(lonlats) < min_points:
        return []
    xs, ys = _TO_UTM.transform([p[0] for p in lonlats], [p[1] for p in lonlats])
    coords = np.column_stack([xs, ys])
    labels = DBSCAN(eps=eps_m, min_samples=min_points).fit_predict(coords)
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        if lab == -1:
            continue
        groups.setdefault(lab, []).append(idx)
    return list(groups.values())


def describe_roi(dimension: str, breakdown: dict, n: int, occurred_to) -> str:
    parts = ", ".join(f"{v}× {k}" for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1]))
    upto = f" through {occurred_to.date()}" if occurred_to else ""
    return (f"{dimension.replace('_', ' ').title()} hotspot: {n} signals ({parts}){upto}. "
            f"Candidate root causes to inspect: {_HYPOTHESES.get(dimension, 'on-site review')}.")


def compute_rois(signals: list[Signal], params: RoiParams, now: datetime) -> list[Roi]:
    if not signals:
        return []
    lonlats = [(s.lon, s.lat) for s in signals]
    rois: list[Roi] = []
    for grp in cluster_indices(lonlats, params.eps_m, params.min_points):
        members = [signals[i] for i in grp]
        pts_utm = list(zip(*_TO_UTM.transform([m.lon for m in members], [m.lat for m in members])))
        hull_utm = MultiPoint(pts_utm).convex_hull.buffer(params.buffer_m)
        poly_wgs = shp_transform(lambda x, y, z=None: _TO_WGS.transform(x, y), hull_utm)
        centroid = poly_wgs.centroid
        subtypes = Counter(m.event_subtype or m.event_type for m in members)
        occ = [m.occurred_at for m in members if m.occurred_at]
        score = sum(
            m.severity_weight
            * recency_weight(m.occurred_at, params.half_life_days, now)
            * GEOM_QUALITY_FACTOR[m.geom_quality]
            for m in members
        )
        recency = (sum(recency_weight(m.occurred_at, params.half_life_days, now) for m in members)
                   / len(members))
        rois.append(Roi(
            risk_dimension=members[0].risk_dimension,
            polygon_wkt=poly_wgs.wkt,
            centroid_lon=centroid.x, centroid_lat=centroid.y,
            area_m2=hull_utm.area,
            risk_score=round(score, 4),
            signal_count=len(members),
            dominant_type=Counter(m.event_type for m in members).most_common(1)[0][0],
            risk_breakdown=dict(subtypes),
            occurred_from=min(occ) if occ else None,
            occurred_to=max(occ) if occ else None,
            recency_score=round(recency, 4),
            description=describe_roi(members[0].risk_dimension, dict(subtypes), len(members),
                                     max(occ) if occ else None),
            contributing_signal_ids=[m.signal_id for m in members],
            source_object_refs=sorted({m.source_object_ref for m in members if m.source_object_ref}),
        ))
    return rois
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_roi_engine.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/roi/engine.py services/external-data/tests/test_roi_engine.py
git commit -m "feat(external-data): ROI engine (DBSCAN clustering, polygons, risk semantics)"
```

---

### Task 9: ROI store & runner (supersession)

**Files:**
- Create: `services/external-data/src/external_data/roi/store.py`
- Create: `services/external-data/src/external_data/roi/runner.py`
- Test: `services/external-data/tests/test_roi_runner.py`

**Interfaces:**
- Consumes: `schema.Roi`, `schema.RoiParams`, `schema.RoiRun`, `roi.engine.compute_rois`.
- Produces:
  - `roi.store.RoiStore` (Protocol): `start_run(dimensions: list[str], params: dict) -> str`; `write_rois(run_id: str, rois: list[Roi]) -> None`; `supersede(run_id: str, dimensions: list[str]) -> int`; `complete_run(run_id: str, count: int) -> None`; `current(dimension: str | None = None) -> list[Roi]`
  - `roi.store.InMemoryRoiStore` (implements the protocol; deterministic run ids `run-1`, `run-2`, …)
  - `roi.store.PgRoiStore(dsn: str)` (psycopg implementation; same protocol)
  - `roi.runner.compute_and_store(signals_by_dim: dict[str, list[Signal]], store: RoiStore, params: RoiParams, now: datetime) -> RoiRun`

- [ ] **Step 1: Write the failing test (in-memory store; supersession semantics)**

```python
# services/external-data/tests/test_roi_runner.py
from datetime import datetime, timezone
from external_data.schema import Signal, RoiParams
from external_data.roi.store import InMemoryRoiStore
from external_data.roi.runner import compute_and_store

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _cluster(dim, n=6, base=( -99.1332, 19.4326)):
    return [Signal(signal_id=f"{dim}-{i}", source_id="x", risk_dimension=dim,
                   event_type=f"{dim}_evt", lon=base[0] + i * 0.0001, lat=base[1] + i * 0.0001,
                   geom_quality="point", occurred_at=NOW, severity_weight=1.0) for i in range(n)]


def test_first_run_creates_current_rois():
    store = InMemoryRoiStore()
    run = compute_and_store({"crash": _cluster("crash")}, store, RoiParams(eps_m=150, min_points=4), NOW)
    assert run.roi_count == 1
    assert len(store.current()) == 1
    assert len(store.current("crash")) == 1


def test_recompute_supersedes_only_that_dimension():
    store = InMemoryRoiStore()
    compute_and_store({"crash": _cluster("crash"), "crime": _cluster("crime")},
                      store, RoiParams(eps_m=150, min_points=4), NOW)
    assert len(store.current()) == 2
    # recompute only crash → previous crash ROI superseded; crime untouched
    compute_and_store({"crash": _cluster("crash")}, store,
                      RoiParams(eps_m=150, min_points=4), NOW)
    cur = store.current()
    assert len(cur) == 2                       # 1 fresh crash + 1 untouched crime
    assert len(store.current("crash")) == 1
    assert len(store.current("crime")) == 1
    assert len(store.all_rois()) == 3          # history retained: 2 crash + 1 crime
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_roi_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.roi.store`.

- [ ] **Step 3: Write store + runner**

```python
# services/external-data/src/external_data/roi/store.py
from __future__ import annotations
import json
from typing import Protocol
from external_data.schema import Roi


class RoiStore(Protocol):
    def start_run(self, dimensions: list[str], params: dict) -> str: ...
    def write_rois(self, run_id: str, rois: list[Roi]) -> None: ...
    def supersede(self, run_id: str, dimensions: list[str]) -> int: ...
    def complete_run(self, run_id: str, count: int) -> None: ...
    def current(self, dimension: str | None = None) -> list[Roi]: ...


class _Row:
    __slots__ = ("roi", "run_id", "valid")

    def __init__(self, roi: Roi, run_id: str):
        self.roi, self.run_id, self.valid = roi, run_id, True


class InMemoryRoiStore:
    def __init__(self):
        self._rows: list[_Row] = []
        self._runs = 0

    def start_run(self, dimensions: list[str], params: dict) -> str:
        self._runs += 1
        return f"run-{self._runs}"

    def write_rois(self, run_id: str, rois: list[Roi]) -> None:
        self._rows.extend(_Row(r, run_id) for r in rois)

    def supersede(self, run_id: str, dimensions: list[str]) -> int:
        n = 0
        for row in self._rows:
            if row.valid and row.run_id != run_id and row.roi.risk_dimension in dimensions:
                row.valid = False
                n += 1
        return n

    def complete_run(self, run_id: str, count: int) -> None:  # no-op in memory
        pass

    def current(self, dimension: str | None = None) -> list[Roi]:
        return [r.roi for r in self._rows
                if r.valid and (dimension is None or r.roi.risk_dimension == dimension)]

    def all_rois(self) -> list[Roi]:
        return [r.roi for r in self._rows]


class PgRoiStore:
    """psycopg implementation. Requires migrations 0101-0102 applied. Not unit-tested
    (no local Postgres); exercised by an opt-in integration test when DB_URL is set."""

    def __init__(self, dsn: str):
        import psycopg
        self._psycopg = psycopg
        self.dsn = dsn

    def start_run(self, dimensions: list[str], params: dict) -> str:
        with self._psycopg.connect(self.dsn) as c:
            row = c.execute(
                "insert into priority.roi_runs (dimensions, params) values (%s, %s) returning id",
                (dimensions, json.dumps(params)),
            ).fetchone()
            c.commit()
            return str(row[0])

    def write_rois(self, run_id: str, rois: list[Roi]) -> None:
        with self._psycopg.connect(self.dsn) as c:
            for r in rois:
                c.execute(
                    """insert into priority.rois
                       (run_id, risk_dimension, geom, centroid, area_m2, risk_score,
                        signal_count, dominant_type, risk_breakdown, occurred_from, occurred_to,
                        recency_score, description, contributing_signal_ids, source_object_refs)
                       values (%s,%s,
                         ST_SetSRID(ST_GeomFromText(%s),4326)::geography,
                         ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, r.risk_dimension, r.polygon_wkt, r.centroid_lon, r.centroid_lat,
                     r.area_m2, r.risk_score, r.signal_count, r.dominant_type,
                     json.dumps(r.risk_breakdown), r.occurred_from, r.occurred_to,
                     r.recency_score, r.description, r.contributing_signal_ids,
                     r.source_object_refs),
                )
            c.commit()

    def supersede(self, run_id: str, dimensions: list[str]) -> int:
        with self._psycopg.connect(self.dsn) as c:
            cur = c.execute(
                """update priority.rois set valid_to = now(), superseded_by_run_id = %s
                   where valid_to is null and run_id <> %s and risk_dimension = any(%s)""",
                (run_id, run_id, dimensions),
            )
            c.commit()
            return cur.rowcount

    def complete_run(self, run_id: str, count: int) -> None:
        with self._psycopg.connect(self.dsn) as c:
            c.execute("update priority.roi_runs set completed_at = now(), roi_count = %s where id = %s",
                      (count, run_id))
            c.commit()

    def current(self, dimension: str | None = None) -> list[Roi]:
        raise NotImplementedError("read ROIs via SQL/current_rois for serving")
```

```python
# services/external-data/src/external_data/roi/runner.py
from __future__ import annotations
from datetime import datetime
from external_data.roi.engine import compute_rois
from external_data.roi.store import RoiStore
from external_data.schema import RoiParams, RoiRun, Signal


def compute_and_store(signals_by_dim: dict[str, list[Signal]], store: RoiStore,
                      params: RoiParams, now: datetime) -> RoiRun:
    dimensions = sorted(signals_by_dim)
    run_id = store.start_run(dimensions, params.model_dump())
    total = 0
    for dim in dimensions:
        rois = compute_rois(signals_by_dim[dim], params.for_dimension(dim), now)
        store.write_rois(run_id, rois)
        total += len(rois)
    store.supersede(run_id, dimensions)
    store.complete_run(run_id, total)
    return RoiRun(run_id=run_id, dimensions=dimensions, params=params.model_dump(), roi_count=total)
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_roi_runner.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add services/external-data/src/external_data/roi/store.py services/external-data/src/external_data/roi/runner.py services/external-data/tests/test_roi_runner.py
git commit -m "feat(external-data): ROI store (in-memory + pg) and runner with supersession"
```

---

### Task 10: CLI

**Files:**
- Create: `services/external-data/src/external_data/cli.py`
- Test: `services/external-data/tests/test_cli.py`

**Interfaces:**
- Consumes: registry, adapters, storage, roi runner, config.
- Produces: `cli.app` (typer) with commands `extract` (`--source`, `--all`), `roi-compute` (`--dimension`, `--all`), `status`. Extract writes staged signals to `staging/<source_id>/signals.jsonl` in the store; `roi-compute` reads staging, groups by dimension, runs `compute_and_store`.

- [ ] **Step 1: Write the failing test**

```python
# services/external-data/tests/test_cli.py
from typer.testing import CliRunner
from external_data.cli import app

runner = CliRunner()


def test_status_lists_sources():
    res = runner.invoke(app, ["status"])
    assert res.exit_code == 0
    assert "ssc_hechos_transito" in res.stdout
    assert "crash" in res.stdout


def test_help():
    assert runner.invoke(app, ["--help"]).exit_code == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/external-data && python -m pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: external_data.cli`.

- [ ] **Step 3: Write the CLI**

```python
# services/external-data/src/external_data/cli.py
from __future__ import annotations
import json
from datetime import datetime, timezone
import typer
from external_data.config import get_settings
from external_data.core.storage import make_store
from external_data.registry.loader import load_registry, get_source
from external_data.adapters.base import ExtractContext
from external_data.adapters import ckan_csv
from external_data.roi.runner import compute_and_store
from external_data.roi.store import InMemoryRoiStore, PgRoiStore
from external_data.schema import RoiParams, Signal

app = typer.Typer(help="CDMX external-signal ROI pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.command()
def status():
    """List configured sources and their risk dimensions."""
    for s in load_registry():
        flag = "on" if s.enabled else "off"
        typer.echo(f"{s.id:28} {s.risk_dimension:13} {s.kind:12} [{flag}]")


@app.command()
def extract(source: str = typer.Option(None), all: bool = typer.Option(False, "--all")):
    """Extract a source (or --all ckan_csv sources) → staging signals.jsonl."""
    settings = get_settings()
    store = make_store(settings)
    ctx = ExtractContext(store=store, now=_now())
    targets = load_registry() if all else [get_source(source)]
    for s in targets:
        if s.kind != "ckan_csv" or not s.enabled:
            continue
        sigs = ckan_csv.extract(s, ctx)
        lines = "\n".join(sig.model_dump_json() for sig in sigs)
        store.write_text(f"staging/{s.id}/signals.jsonl", lines)
        typer.echo(f"{s.id}: {len(sigs)} signals")


@app.command(name="roi-compute")
def roi_compute(dimension: str = typer.Option(None), all: bool = typer.Option(False, "--all")):
    """Compute ROIs from staged signals and persist with supersession."""
    settings = get_settings()
    store = make_store(settings)
    by_dim: dict[str, list[Signal]] = {}
    for s in load_registry():
        path = f"staging/{s.id}/signals.jsonl"
        if not store.exists(path):
            continue
        for line in store.read_text(path).splitlines():
            sig = Signal(**json.loads(line))
            if dimension and sig.risk_dimension != dimension:
                continue
            by_dim.setdefault(sig.risk_dimension, []).append(sig)
    roi_store = PgRoiStore(settings.db_url) if settings.db_url else InMemoryRoiStore()
    run = compute_and_store(by_dim, roi_store, RoiParams(), _now())
    typer.echo(f"run {run.run_id}: {run.roi_count} ROIs across {run.dimensions}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run tests**

Run: `cd services/external-data && python -m pytest tests/test_cli.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full suite and commit**

Run: `cd services/external-data && python -m pytest -q`
Expected: PASS (all tasks' tests green).

```bash
git add services/external-data/src/external_data/cli.py services/external-data/tests/test_cli.py
git commit -m "feat(external-data): typer CLI (status/extract/roi-compute)"
```

---

### Task 11: Supabase migrations & SQL tests (authored for DB agent)

**Files:**
- Create: `supabase/migrations/0101_priority_external_signals.sql`
- Create: `supabase/migrations/0102_priority_rois.sql`
- Create: `supabase/migrations/0103_external_data_storage.sql`
- Create: `supabase/tests/0101_priority_external_signals.test.sql`
- Create: `supabase/tests/0102_priority_rois.test.sql`
- Create: `supabase/tests/0103_external_data_storage.test.sql`

**Interfaces:**
- Consumes: schemas + PostGIS from migration `0001` (`priority` schema; PostGIS in `extensions`); `platform.is_member` from `0002` (storage policy).
- Produces: `priority.external_signals`, `priority.roi_runs`, `priority.rois`, view `priority.current_rois`; private bucket `external-data`.

> **Apply mechanic:** this agent cannot apply migrations (no Supabase MCP/CLI). Hand these files to the DB-capable agent to apply via the Supabase MCP (`apply_migration`) and verify via `execute_sql` against each `*.test.sql`. Numbers `0101+` sit after the reserved `0003`–`0014` band and depend only on `0001`/`0002`.

- [ ] **Step 1: Write the external_signals migration**

```sql
-- supabase/migrations/0101_priority_external_signals.sql
create table priority.external_signals (
    signal_id          text primary key,
    source_id          text not null,
    risk_dimension     text not null
        check (risk_dimension in ('crash','violation','flooding','road_surface','crime')),
    event_type         text not null,
    event_subtype      text,
    geom               geography(Point,4326) not null,
    geom_quality       text not null check (geom_quality in ('point','geocoded','block_centroid')),
    occurred_at        timestamptz,
    reported_at        timestamptz,
    severity_weight    real not null default 1,
    geocode_confidence real,
    attributes         jsonb not null default '{}'::jsonb,
    source_object_ref  text,
    source_url         text,
    license            text,
    fetched_at         timestamptz,
    ingested_at        timestamptz not null default now()
);
create index external_signals_gix    on priority.external_signals using gist (geom);
create index external_signals_dim_ix on priority.external_signals (risk_dimension);
```

- [ ] **Step 2: Write its assertion test**

```sql
-- supabase/tests/0101_priority_external_signals.test.sql
do $$
begin
  assert to_regclass('priority.external_signals') is not null, 'external_signals missing';
  assert (select format_type(atttypid,atttypmod) from pg_attribute
          where attrelid='priority.external_signals'::regclass and attname='geom') like 'geography%',
    'geom must be geography';
  assert exists (select 1 from pg_constraint
    where conrelid='priority.external_signals'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%risk_dimension%'), 'dimension check missing';
end $$;
```

- [ ] **Step 3: Write the ROI tables migration**

```sql
-- supabase/migrations/0102_priority_rois.sql
create table priority.roi_runs (
    id            uuid primary key default gen_random_uuid(),
    dimensions    text[] not null,
    params        jsonb  not null default '{}'::jsonb,
    signal_window tstzrange,
    started_at    timestamptz not null default now(),
    completed_at  timestamptz,
    roi_count     int
);

create table priority.rois (
    id               uuid primary key default gen_random_uuid(),
    run_id           uuid not null references priority.roi_runs(id),
    risk_dimension   text not null
        check (risk_dimension in ('crash','violation','flooding','road_surface','crime')),
    geom             geography(Polygon,4326) not null,
    centroid         geography(Point,4326)   not null,
    area_m2          real not null,
    risk_score       real not null,
    signal_count     int  not null,
    dominant_type    text not null,
    risk_breakdown   jsonb not null default '{}'::jsonb,
    occurred_from    timestamptz,
    occurred_to      timestamptz,
    recency_score    real,
    description      text not null,
    contributing_signal_ids text[] not null default '{}',
    source_object_refs      text[] not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    superseded_by_run_id uuid references priority.roi_runs(id),
    created_at       timestamptz not null default now()
);
create index rois_current_gix on priority.rois using gist (geom) where valid_to is null;
create index rois_dim_ix      on priority.rois (risk_dimension)  where valid_to is null;

create view priority.current_rois as select * from priority.rois where valid_to is null;
```

- [ ] **Step 4: Write its assertion test**

```sql
-- supabase/tests/0102_priority_rois.test.sql
do $$
declare r1 uuid; r2 uuid;
begin
  assert to_regclass('priority.roi_runs') is not null, 'roi_runs missing';
  assert to_regclass('priority.rois') is not null, 'rois missing';
  assert to_regclass('priority.current_rois') is not null, 'current_rois view missing';

  -- supersession behaviour: run2 retires run1's crash ROI only
  insert into priority.roi_runs(dimensions) values (array['crash','crime']) returning id into r1;
  insert into priority.rois(run_id,risk_dimension,geom,centroid,area_m2,risk_score,signal_count,
                            dominant_type,description)
    values (r1,'crash',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,5,'traffic_crash','x'),
           (r1,'crime',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,5,'crime','y');
  assert (select count(*) from priority.current_rois) = 2, 'expected 2 current';

  insert into priority.roi_runs(dimensions) values (array['crash']) returning id into r2;
  insert into priority.rois(run_id,risk_dimension,geom,centroid,area_m2,risk_score,signal_count,
                            dominant_type,description)
    values (r2,'crash',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,6,'traffic_crash','z');
  update priority.rois set valid_to = now(), superseded_by_run_id = r2
   where valid_to is null and run_id <> r2 and risk_dimension = any(array['crash']);

  assert (select count(*) from priority.current_rois) = 2, 'still 2 current (fresh crash + crime)';
  assert (select count(*) from priority.current_rois where risk_dimension='crash') = 1, 'one crash';
  assert (select count(*) from priority.rois) = 3, 'history retained';
end $$;
```

- [ ] **Step 5: Write the storage bucket migration + test**

```sql
-- supabase/migrations/0103_external_data_storage.sql
insert into storage.buckets (id, name, public, file_size_limit) values
    ('external-data', 'external-data', false, 5368709120)
on conflict (id) do update set file_size_limit = excluded.file_size_limit;
```

```sql
-- supabase/tests/0103_external_data_storage.test.sql
do $$
begin
  assert exists (select 1 from storage.buckets where id='external-data' and public=false),
    'external-data bucket missing';
end $$;
```

- [ ] **Step 6: Commit (apply is the DB agent's step)**

```bash
git add supabase/migrations/0101_priority_external_signals.sql supabase/migrations/0102_priority_rois.sql supabase/migrations/0103_external_data_storage.sql supabase/tests/0101_priority_external_signals.test.sql supabase/tests/0102_priority_rois.test.sql supabase/tests/0103_external_data_storage.test.sql
git commit -m "feat(db): external_signals + rois tables and external-data bucket (priority schema)"
```

> After commit, notify the DB-capable agent: apply `0101`–`0103` via the Supabase MCP and run the three `*.test.sql` assertions. Once applied, set `DB_URL`/`SUPABASE_S3_*` in the worker env and the CLI `roi-compute`/`extract` write to Supabase instead of local FS.

---

## Self-Review

**1. Spec coverage:**
- §1 goal (ROIs as product) → Tasks 8–9, 11. §2 source catalog → Task 3 (`sources.yaml`). §3 three stages → Tasks 6/7 (extract), 8 (compute), 9/11 (persist). §4 weighting (severity × recency × geom_quality) → `engine.compute_rois` (Task 8) + `bbox.recency_weight` (Task 4). §5 DBSCAN/UTM/polygon/description/object-refs → Task 8 (Python DBSCAN; spec's listed alternative, chosen because no local Postgres). §6 data model + lifecycle → Tasks 9, 11. §7 components → Tasks 1–11. §8 idempotency/scheduling/secrets → `signal_id` (Task 4), registry `schedule` (Task 3), `config` (Task 1). §9 repo placement → `services/external-data/`. §10 testing → every task. §12 integration (priority schema, 0101+, no MCP) → Task 11 + Global Constraints.
- Gap noted: §5 recommended PostGIS `ST_ClusterDBSCAN`; this plan computes ROIs in Python (the spec's documented alternative) because this agent has no local Postgres. The `PgRoiStore` still persists to `priority.rois`. If in-DB clustering is later wanted, add it as a SQL function migration; the table contract is unchanged.

**2. Placeholder scan:** No "TBD/TODO". Two explicit build-time verifications are flagged with concrete actions, not deferred code: (a) exact CKAN CSV header names per source (Task 3 note — confirm via `datastore_search?limit=1`); (b) `infracciones_ee` address loading (Task 3 marks it `news_geocode` with empty `feeds`; its CKAN-address variant is wired when its real headers are confirmed — until then it is `enabled` but yields no signals, which is safe). These are data-accuracy confirmations, not missing logic.

**3. Type consistency:** `Signal`/`Roi`/`RoiParams`/`RoiRun` defined once (Task 2) and used with matching fields throughout. `RoiStore` protocol methods (`start_run`,`write_rois`,`supersede`,`complete_run`,`current`) match `InMemoryRoiStore`, `PgRoiStore`, and `runner.compute_and_store`. `compute_rois(signals, params, now)`, `cluster_indices(lonlats, eps_m, min_points)`, `signal_id(source_id, native_id)`, `in_cdmx(lon, lat)`, `recency_weight(occurred_at, half_life_days, now)`, `make_store(settings)`, `ExtractContext(store, now, http_get)` signatures are consistent across all callers. The `priority.rois` columns in `0102` match the `PgRoiStore.write_rois` insert (geom/centroid/area_m2/risk_score/signal_count/dominant_type/risk_breakdown/occurred_from/occurred_to/recency_score/description/contributing_signal_ids/source_object_refs) and the supersession SQL matches `PgRoiStore.supersede`.
