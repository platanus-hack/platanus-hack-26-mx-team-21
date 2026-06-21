# Application System Architecture — Design

**Date:** 2026-06-20
**Status:** Approved architecture baseline
**Component:** Map application, geographic context, and analysis orchestration

---

## 1. Scope

This spec defines the application architecture for displaying current infrastructure
observations, their per-instance priorities, and the results of budget-driven analyses.
The first analysis types are an optimal service route and a highest-impact cluster.

The application also owns Mexico-specific geographic context through INEGI's Marco
Geoestadistico at these levels:

- Area Geoestadistica Estatal (AGEE / state)
- Area Geoestadistica Municipal (AGEM / municipality or CDMX territorial demarcation)
- Area Geoestadistica Basica (AGEB, urban or rural)

The architecture must support future analysis types without making the application run
lifecycle, persistence model, or API specific to routes and clusters.

Explicitly out of scope:

- Vision and VLM inference.
- Observation lifecycle logic, which is defined in the observation-contract spec.
- Priority calculation.
- Cost calculation, budget allocation, clustering, and routing algorithms.
- Work orders, crew dispatch, procurement, and project execution.
- Historical map playback. The initial application presents current state only.

## 2. Principles

1. **Application as orchestrator, not analyst.** The application gathers parameters,
   freezes inputs, invokes a provider, persists its response, and renders it. It does not
   reproduce provider computations.
2. **Stable shared contracts.** Vision, priority, media, geography, and analysis providers
   communicate through versioned interfaces.
3. **City isolation.** Every query, geographic binding, priority run, and analysis run is
   scoped to one city.
4. **Reproducible runs.** A submitted analysis uses a fixed set of inputs and versioned
   provider configuration even when live observations change while it runs.
5. **Extensible analyses.** Routes and clusters are provider plugins using the same generic
   run lifecycle and result envelope as future analyses.
6. **Application-only geography.** INEGI bindings enrich observations in the application
   schema; they do not alter the factual observation contract.
7. **Async compute.** Map reads never wait on optimization or other long-running analyses.

## 3. System Context

```text
 Upstream producers                     Application                     Analysis providers

 Vision / Sweep Ingest ───────┐       Map Web Client
                              │              ▲
 Per-instance Priority ───────┤              │
                              ▼              ▼
 R2 Broker Worker ───────▶ Application API ◀──────▶ Durable job queue
                              ▲      │                         │
 INEGI source data ─────▶ Importer   ▼                         ▼
                              PostgreSQL/PostGIS      Provider adapter worker
                                                               │
                                                               ▼
                                                      Optimization module
```

The production reference architecture has four application deployables:

- **Map web client:** renders observations, heat layers, geographic boundaries, analysis
  drafts, and result artifacts.
- **Application API:** owns map reads, observation details, geographic resolution,
  natural-language drafting, analysis definitions, and run lifecycle.
- **Provider adapter worker:** loads a frozen run input, invokes the selected external
  provider, validates the response contract, and persists an immutable result attempt.
- **INEGI importer:** loads a specific Marco Geoestadistico edition into application-owned
  reference tables and derives observation bindings.

PostgreSQL/PostGIS is the transactional and geospatial store. A durable queue isolates
interactive traffic from analysis work. A cache may accelerate tiles and reference-data
queries, but it is not a source of truth.

### 3.1 Data ownership

Logical schemas and database roles enforce module ownership even if the initial deployment
uses one PostgreSQL cluster:

| Data | Owner | Application access |
|---|---|---|
| Sweeps, observation types, observations | Vision/observation module | Read-only |
| Priority runs and per-observation scores | Priority module | Read-only |
| Media bytes and frame lookup | Cloudflare R2 + broker Worker (`app_authorize_object`) | Reference/API only — bytes served by broker, never owned by the application |
| Cities, INEGI editions/areas/bindings | Application | Read/write |
| Analysis definitions, runs, inputs, attempts, artifacts | Application | Read/write |
| Costing and optimization configuration | Analysis provider | Descriptor/API only |

## 4. Mexico Geographic Model

INEGI's Marco Geoestadistico is the canonical geographic reference. It defines AGEE,
AGEM, and AGEB areas; AGEBs may be urban or rural. These are geostatistical boundaries,
not assertions of official political boundaries.

Authoritative references:

- [INEGI Marco Geoestadistico](https://www.inegi.org.mx/programas/mg/)
- [INEGI catalog service](https://www.inegi.org.mx/servicios/catalogounico.html)

### 4.1 Imported reference data

```text
geo_editions
  id, source_name, source_release, effective_date, imported_at, checksum, status

geo_areas
  id, edition_id, level, source_cvegeo,
  cve_ent, cve_mun?, cve_loc?, cve_ageb?,
  name, ageb_kind?, parent_id?, geometry

observation_geo_bindings
  observation_id, edition_id, agee_id, agem_id?, ageb_id?, bound_at
```

Rules:

- Preserve INEGI keys as strings, including leading zeroes and check characters.
- Use `(edition_id, level, source_cvegeo)` as the stable imported identity.
- Preserve component keys separately. An AGEB reference must include its state and
  municipality components; `cve_ageb` alone is not globally unique.
- Preserve locality keys when present in source data, but surface the requested
  AGEE -> AGEM -> AGEB hierarchy in the application.
- Keep prior editions after importing a replacement. Exactly one edition is active per
  city, and submitted analysis runs pin their edition.
- Recompute bindings for the new active edition without changing bindings retained for
  prior runs.

### 4.2 Geographic resolution

The application supports three mutually exclusive scope forms for a query or analysis:

- Entire city.
- One or more INEGI areas from the same city and edition; their geometries form a union.
- One user-drawn polygon contained by the city boundary.

Prompts such as "show potholes in AGEB 0229" or "best route in Gustavo A. Madero" are
resolved against the application catalog. Ambiguous names or keys produce an editable
choice in the draft; they never silently choose an area. A scope cannot span cities.

## 5. Application Read Model

### 5.1 Priorities

The priority module publishes immutable, city-scoped priority runs:

```text
priority_run: id, city_id, model_name, model_version, computed_at, status
observation_priority: run_id, observation_id, weight
```

Only a complete run becomes active. The application joins the active run to current
observations. A newly ingested observation may temporarily lack a score because priority
calculation is asynchronous, failed, or does not yet support its type.

Pending observations:

- Appear immediately on the instance layer with a neutral "priority pending" state.
- Do not contribute to the heat layer.
- Are excluded from analysis inputs until scored.
- Are counted in the scenario draft so the user can see the exclusion.

### 5.2 Map APIs

The baseline read surface is:

```text
GET /cities/{city_id}/tiles/observations/{z}/{x}/{y}
GET /cities/{city_id}/tiles/geographies/{edition_id}/{level}/{z}/{x}/{y}
GET /cities/{city_id}/observations/{observation_id}
GET /cities/{city_id}/geo-areas?level=&parent_id=&query=&edition_id=
```

Observation vector tiles contain only map fields: observation ID, type, location,
priority state, and priority weight when present. The client can display instances,
a weighted heat layer, or both. Full attributes and frame evidence references come from
the detail endpoint. The broker Worker resolves `recording_id` and `frame_ref` to
Cloudflare R2 objects, authorizing access via `public.app_authorize_object`; media
bytes never pass through map tiles. Live storage contract: `supabase/STORAGE.md`.

Tile cache keys include city, active observation data version, active priority run, INEGI
edition where applicable, and tile coordinates.

## 6. Generic Analysis Model

### 6.1 Definitions and capabilities

An analysis provider registers a versioned definition:

```text
analysis_definition
  kind                 e.g. "budget.route.v1"
  provider
  interface_version
  request_schema       JSON Schema
  result_schema        JSON Schema
  artifact_kinds
  ui_descriptor
  enabled_cities
```

`ui_descriptor` supplies labels, supported scope forms, and parameter controls. For the
initial budget providers it also supplies the cost basis for each supported observation
type:

```text
observation_type
cost_basis_id
label                  e.g. "Pothole cost / m2"
unit                   e.g. "m2", "linear_m", "item"
currency
default_unit_cost
```

These fields are provider-owned scenario parameters. The application displays defaults,
accepts user overrides, and passes them unchanged. It does not infer quantities, calculate
per-instance costs, or verify the provider's allocation logic. Observation `attributes`
are sent to the provider so it can interpret measurements such as area or length.

Initial definitions:

- `budget.route.v1`: returns an optimal service route.
- `budget.cluster.v1`: returns a highest-impact geographic cluster.

A run chooses one analysis kind. It does not implicitly request both outputs.

### 6.2 Drafting and submission

Both manual controls and natural-language commands produce the same editable draft:

```json
{
  "analysis_kind": "budget.route.v1",
  "city_id": "...",
  "scope": { "kind": "inegi_areas", "area_ids": ["..."] },
  "budget": { "amount": "3000000.00", "currency": "MXN" },
  "type_settings": [
    {
      "observation_type": "pothole",
      "enabled": true,
      "cost_basis_id": "area",
      "unit": "m2",
      "unit_cost": "28000.00"
    }
  ],
  "provider_version": "..."
}
```

Natural-language parsing never submits work directly. It resolves recognized analysis
kinds, observation types, budgets, and geographic names into a draft. The user reviews
and explicitly submits the structured form.

### 6.3 Frozen run input

Submission creates an immutable analysis run and freezes only the provider inputs needed
for that run:

- City and geographic edition.
- Resolved scope geometry/reference.
- Analysis kind, provider version, and submitted parameters.
- Exact eligible observation IDs.
- Each eligible observation's type, location, attributes, and priority weight.
- Observation and priority data versions.

It does not duplicate recordings, frames, observation history, or unrelated city data.
Later sweeps and priority runs affect new analyses only. This makes a result explainable
and repeatable even when live data changes during computation.

### 6.4 Lifecycle and async execution

```text
draft (client only)
       |
       v
queued -> running -> succeeded
                   -> failed
       -> cancelled
```

Creating a run and its queue outbox record is one transaction. The API returns
`202 Accepted` with the run ID. Workers may safely retry the same run after a timeout or
crash; a run/attempt idempotency key prevents two responses from becoming the accepted
result. Cancellation is cooperative, and a response arriving after cancellation is not
promoted.

```text
GET  /cities/{city_id}/analysis-definitions
POST /cities/{city_id}/analysis-drafts:parse
POST /cities/{city_id}/analysis-runs
GET  /cities/{city_id}/analysis-runs/{run_id}
POST /cities/{city_id}/analysis-runs/{run_id}:cancel
GET  /cities/{city_id}/analysis-runs/{run_id}/result
```

## 7. Extensible Result Contract

The application stores one generic result envelope:

```json
{
  "schema_version": 1,
  "analysis_kind": "budget.route.v1",
  "provider": { "name": "...", "version": "...", "config_version": "..." },
  "summary": {
    "metrics": [],
    "warnings": []
  },
  "artifacts": []
}
```

Supported artifact classes are deliberately broader than the initial providers:

| Artifact | Purpose |
|---|---|
| `map_features` | Versioned point, line, polygon, or multi-geometry features with typed properties |
| `ordered_sequence` | Ordered references such as route stops |
| `table` | Typed columns and rows for ranked or comparative output |
| `chart` | Declarative chart data and presentation metadata |
| `asset_ref` | Reference to a provider-produced file or external artifact |

Geometry is normalized into PostGIS-backed feature rows for spatial queries and tile
rendering; the original validated result payload is retained for audit and replay.

The initial route renderer expects a line feature, an ordered observation sequence, and
provider metrics. The initial cluster renderer expects polygon/multipolygon display
geometry, member observation references, and provider metrics. Spending, allocation,
distance, and other computed values are provider output, not application calculations.

Adding a new analysis type requires:

1. A provider definition and versioned request/result schemas.
2. An adapter capable of invoking that provider.
3. Renderers for any artifact types not already supported.

It does not require a new run table, status model, queue, or top-level API family. Unknown
artifact versions remain stored and auditable but are shown as unsupported until a
compatible renderer is deployed.

## 8. Failure Handling

- **Priority lag:** show the observation as pending and omit it from analysis input.
- **Ambiguous geography:** keep the prompt as a draft and require explicit area choice.
- **Provider timeout/transient failure:** retry with a configured limit, then retain a
  failed attempt with sanitized diagnostics.
- **Invalid provider response:** reject unknown observation references, incompatible
  contract versions, malformed geometry, and schema-invalid artifacts.
- **Resolved/superseded after completion:** retain the immutable result and flag affected
  observation references as no longer current when rendering.
- **INEGI edition change:** existing runs keep their pinned edition; new drafts use the
  active edition.
- **Media unavailable:** show observation facts and an unavailable-evidence state without
  failing the map.
- **Unsupported analysis artifact:** retain it and expose its metadata; do not fail other
  supported artifacts in the same result.

## 9. Security and Operations

- Delegate authentication to an external OIDC-compatible identity provider.
- Enforce city scope and two baseline roles: `viewer` and `analysis_author`.
- Audit prompt parsing, draft submission, cancellation, provider version, and accepted
  result attempt.
- Do not place raw prompts, media URLs, or provider diagnostics in general application
  logs without redaction.
- Trace a run from API request through queue message, provider attempt, and result using
  `analysis_run_id`.
- Monitor tile latency/error rate, pending-priority count/age, queue depth, run duration,
  provider failures, invalid responses, and INEGI import/binding failures.

## 10. Testing and Acceptance

### 10.1 Contract tests

- Validate observation and priority joins against their schema versions.
- Validate every provider request and result against its registered schema.
- Verify route and cluster providers use the generic result envelope.
- Verify an additional fixture analysis kind can be registered without modifying the run
  lifecycle or top-level analysis APIs.

### 10.2 Geography tests

- Import AGEE, AGEM, urban AGEB, and rural AGEB fixtures with leading-zero keys intact.
- Resolve the AGEE -> AGEM -> AGEB hierarchy and preserve optional locality source keys.
- Spatially bind observations on both sides of an AGEB boundary.
- Reject cross-city scope unions and disambiguate repeated names.
- Activate a new edition, rebuild bindings, and confirm older runs retain old references.

### 10.3 Map tests

- Return only current observations inside the requested tile and city.
- Render scored observations in instance and heat modes.
- Render unscored observations as pending and exclude them from heat/analysis inputs.
- Resolve detail and media evidence independently from tile delivery.
- Verify cache keys cannot mix cities, priority runs, or geographic editions.

### 10.4 Analysis tests

- Produce equivalent structured drafts from manual controls and representative prompts.
- Require user submission after natural-language drafting.
- Freeze exact provider inputs and prove later observation/priority changes do not mutate
  an existing run.
- Exercise queued, running, succeeded, failed, and cancelled transitions.
- Redeliver the same queued request and accept only one result.
- Reject malformed geometry, unknown observation references, and incompatible versions.
- Flag result members that later cease to be current.

### 10.5 Non-functional acceptance

- Map tile latency remains within the product target while analysis workers are saturated.
- City authorization is enforced in API, worker, cache, and database access paths.
- A provider outage does not make observation or geography reads unavailable.
- Analysis runs and results remain auditable by input/provider/data versions.

## 11. Decisions and Deferred Work

| Decision | Rationale |
|---|---|
| Modular API plus async provider workers | Keeps map traffic responsive without premature service sprawl |
| Multi-city application partitions | Supports asymmetric CDMX/Monterrey inputs without mixing data |
| INEGI geography owned by the application | Enables Mexico-specific filters/prompts without changing factual observations |
| Versioned local INEGI import | Avoids runtime dependency on an external catalog and preserves reproducibility |
| Per-instance priority points | Matches the priority/optimizer boundary; the heat layer is a client visualization |
| Provider-owned cost basis and unit costs | The application surfaces assumptions but does not implement optimization logic |
| Generic analysis runs and artifacts | Prevents coupling core architecture to routes and clusters |
| Natural language creates drafts only | Keeps user intent inspectable before long-running work executes |

Deferred to focused follow-up specs:

- Concrete technology and framework selection.
- Physical monorepo layout and deployment manifests.
- Exact provider transport (in-process, subprocess, or network API).
- Natural-language model/provider and prompt design.
- INEGI import scheduling and data-release operations.
- Individual analysis algorithms and provider-specific schemas beyond their application
  interface.
- Historical playback and comparison between analysis runs.
