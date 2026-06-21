# External-Dataset ROIs as Per-Dimension Map Layers — Design

**Date:** 2026-06-21
**Status:** Approved (design) — pending plan
**Scope:** Mexico City (CDMX) only.
**Components:** External-data ROI pipeline (`services/external-data`) + CityCrawl/Vialia app (`frontend/`).

Builds on:
- `docs/superpowers/specs/2026-06-20-external-data-pipeline-design.md` (the ROI pipeline)
- `docs/superpowers/plans/2026-06-20-city-priority-map-application.md` (the app)
- Memory: `external-data-pipeline-scope`, `cdmx-point-data-recency`,
  `city-priority-map-architecture`, `no-client-priority-heuristics`.

---

## 1. Goal

Make the application's **risk zones a real, per-dimension feature backed by the external-data
pipeline**. Today the app has a single combined "Zonas de riesgo" toggle that draws every
`priority.current_rois` row in one red style, and the remote DB holds only a representative
sample (12 crash signals → 5 crash ROIs). This work delivers two coordinated halves:

1. **Data (WS-A):** run the existing pipeline live for the four native-lat/long risk
   dimensions and bulk-load real ROIs into the remote DB.
2. **Frontend (WS-B):** turn the one combined toggle into a **grouped, per-dimension layer
   control** (master + sub-toggles) with per-dimension map styling and an ROI detail popup.

The two halves are independent except for the shared contract (the `risk_dimension` values and
the `public.app_*` RPC shapes), so WS-B is built and tested against the current 5-ROI sample
and lights up fully as WS-A lands.

**Non-goals:** computing any priority/weight client-side (the pipeline already emits
`risk_score` per ROI — the app only visualizes it, per `no-client-priority-heuristics`).

---

## 2. Current state (verified 2026-06-20/21)

- **App:** `frontend/src/components/LayersPanel.tsx` has one "Zonas de riesgo" row
  (`showRois` / `onToggleRois` / `roiCount`, subtitle "externas · crimen, choques,
  inundación"). `MapCanvas.tsx` renders all ROIs in one red style with a zoom-gated,
  dimension-labelled centroid marker. `lib/api.ts#getRois()` calls `app_current_rois()` and
  already receives `risk_dimension` per ROI.
- **RPC:** `public.app_current_rois()` (migration `0200_app_read_api.sql`) returns
  `id, risk_dimension, centroid_lat, centroid_lng, risk_score, dominant_type, description,
  geom_geojson`, clipped to the tenant boundary. No dimension filter, no limit.
- **DB:** `priority.external_signals` = 12 rows (all `crash`); `priority.current_rois` = 5 rows
  (all `crash`). Zero ROIs in the other four dimensions.
- **Pipeline:** `services/external-data` is built and locally validated on live SSC crash data
  (30,652 signals → 870 ROIs). CLI: `extract`, `load-db`, `roi-compute`, `status`. Writes to
  remote Postgres directly via `DB_URL`. **Only SSC column maps are verified live**; the other
  sources' CSV headers must be confirmed before their first real extract. The `external-data`
  R2 bucket exists but is empty.

---

## 3. Risk dimensions in scope

Five dimensions exist in the pipeline registry; this work targets the four with **native
lat/long** (no geocoding), full real load:

| Dimension | Spanish label | Color | Sources (point) | Notes |
|---|---|---|---|---|
| `crash` | Choques | `#e5484d` | SSC, C5, ciclistas, peatones | SSC verified; others need header check |
| `flooding` | Inundación | `#2f64e6` | SACMEX, 0311-agua | header check |
| `road_surface` | Bacheo | `#f5a623` | 0311-baches | header check |
| `crime` | Crimen | `#7c3aed` | FGJ carpetas + víctimas | via CKAN URL (archive subdomain not routable from dev sandbox); 2024–2025-01 |

**Deferred (geocoding required):** `violation` (Infracciones, `#0f9b8e` — both `infracciones`
sources are address-level) and the crash-`news` source. The app still renders a disabled
"Infracciones" sub-row so the layer set is visibly complete.

Colors mirror the existing `TYPE_PRESENTATION` palette for visual consistency and are tunable
in one place (`lib/dimensions.ts`).

---

## 4. WS-A — Data load

**Prerequisite (user-provided):** the remote Postgres password as `DB_URL`
(`postgresql://postgres:<pw>@db.joixzhdpnxqhnuscxsoy.supabase.co:5432/postgres`) and live CKAN
reachability from wherever the pipeline runs. The user either runs the load (`! external-data
load-db …`) or provides `DB_URL`. If unavailable, WS-A is skipped and WS-B runs against the
5-ROI sample (still a working, if sparse, feature).

**Procedure — per source, in dimension order (crash → flooding → road_surface → crime):**

1. **Verify headers.** Fetch the live CSV head; confirm each `registry/sources.yaml` column
   map (lat/lng/date/type) resolves. Fix the YAML entry if a header drifted. SSC is already
   verified.
2. **`extract --source <id>`** → raw + staging (local FS in dev; R2 in prod).
3. **`load-db --source <id>`** → `priority.external_signals` (bbox-clipped to CDMX,
   recency/geom-quality weighting, deterministic `signal_id` → idempotent).
4. **`roi-compute --dimension <d>`** → `priority.roi_runs` + `priority.rois`; supersedes the
   prior current ROIs **for that dimension only** (other dimensions untouched).

**Resilience:** per-source isolation — if a source is unreachable or its headers don't resolve,
skip it and log; every other dimension still lands. Out-of-CDMX-bbox coords are dropped
(SSC has stray points).

**Done when:** `select risk_dimension, count(*) from priority.current_rois group by 1` shows
**≥3 of the 4 dimensions** populated with plausible counts (crash in the hundreds; others ≥
tens), and `priority.external_signals` has the corresponding signals.

---

## 5. WS-B.1 — API contract changes

New migration `supabase/migrations/0212_app_roi_layers.sql` (security-definer, tenant-clipped,
following the `0200` conventions). Applied via Supabase MCP; types regenerated.

- **Modify `public.app_current_rois(p_dimensions text[] default null, p_limit int default 250)`.**
  - `p_dimensions` null/empty → all dimensions (backward-compatible with the current call).
    Otherwise filter `risk_dimension = any(p_dimensions)`.
  - Order by `risk_score desc`, cap to `p_limit` (so a dimension with hundreds of ROIs never
    floods the map). Same return columns as today.
- **Add `public.app_roi_dimension_counts()` → `table(risk_dimension text, roi_count int,
  max_risk real)`** — current ROI count and peak risk per dimension within the tenant
  boundary. Drives the panel's per-dimension rows; a dimension with 0 ROIs renders **disabled**
  (visible but greyed), not hidden.
- Regenerate `packages/db-types/database.ts`; verify both functions appear under
  `Database['public']['Functions']`.

**Grants:** `execute` to `authenticated` for both, matching the existing `app_*` grants.

---

## 6. WS-B.2 — Frontend per-dimension layers

### 6.1 Dimension presentation — `frontend/src/lib/dimensions.ts` (new)
A `DIMENSION_PRESENTATION: Record<string, { label: string; color: string }>` map per §3, plus
`dimensionColor(slug)` / `dimensionLabel(slug)` helpers with a neutral fallback. Single source
of truth for layer color + label.

### 6.2 API wrappers — `frontend/src/lib/api.ts`
- `getRois(dimensions?: string[], limit?: number)` → passes `p_dimensions` / `p_limit`.
- `getRoiDimensionCounts()` → maps `app_roi_dimension_counts` rows to
  `{ dimension, count, maxRisk }[]`.
- `Roi` type already carries `riskDimension`, `riskScore`, `dominantType`, `description`,
  `geojson` — add `signalCount` if exposed (optional; popup degrades gracefully without it).

### 6.3 State + lazy fetch — `frontend/src/pages/MapPage.tsx`
- `riskMaster: boolean` (master on/off) and `activeDimensions: Record<string, boolean>`.
- **Lazy per-dimension fetch with a cache:** a dimension's ROIs are fetched only the first time
  its sub-toggle (or master) turns it on, then cached in a `Map<string, Roi[]>`; toggling off
  hides without refetching. Never ships all dimensions' polygons up front.
- `app_roi_dimension_counts()` is fetched once on load to populate the panel rows (counts +
  which dimensions are disabled).

### 6.4 LayersPanel — `frontend/src/components/LayersPanel.tsx`
Replace the single "Zonas de riesgo" row with the **grouped section**:
- **Master row:** checkbox "Zonas de riesgo" + total ROI count + a collapse/expand chevron.
- **Sub-rows (one per dimension, incl. disabled `violation`):** indented checkbox, dimension
  color dot, Spanish label, ROI count (monospace). A 0-count/deferred dimension is greyed and
  non-interactive.
- Master toggles all enabled dimensions; sub-toggles flip one. Drop the old static subtitle.
- Props change from `showRois/onToggleRois/roiCount` to
  `riskMaster/activeDimensions/dimensionCounts/onToggleRiskMaster/onToggleDimension`
  (+ collapse state). Mirror the existing "Tipos de observación" row styling.

### 6.5 MapCanvas — `frontend/src/components/MapCanvas.tsx`
- Maintain **one Leaflet layer group per dimension** (replacing the single `rois` group);
  attach/detach by `activeDimensions`.
- **Styling:** polygon stroke = `dimensionColor` (dashed, matching the current ROI look);
  **fill opacity scaled by `risk_score` normalized within its dimension** (e.g. 0.08–0.32) so
  hotter zones read stronger; centroid label colored per dimension; keep the
  `ROI_LABEL_ZOOM` zoom-gate.
- **ROI click → popup** (Leaflet popup): dimension label, `risk_score`, `dominant_type`,
  `signal_count` (if present), and the generated `description` (the inspection brief). This is
  the payoff that makes the "real source" visible.
- Props: `rois: Roi[]` → `roisByDimension: Record<string, Roi[]>` (or keep `rois: Roi[]` and
  group internally by `riskDimension` — implementer's choice; group internally is simpler).

---

## 7. Performance & volume

Full real load can yield hundreds of crash ROIs (870 from SSC alone) plus more per dimension.
Two guards keep the map responsive: (1) **server-side `p_limit` top-N by `risk_score`** (default
250 per dimension) — also better visually than thousands of tiny hulls; (2) **lazy per-dimension
fetch + client cache** so only toggled-on dimensions are ever loaded/rendered. If a future need
arises to see *all* ROIs, raise `p_limit`; no architecture change required.

---

## 8. Out of scope (explicit)
- `violation` and crash-`news` dimensions (require geocoding) — shown as a disabled sub-row.
- Latent-scan rework: the client-side latent mock stays as-is; real ROIs are **only** the
  standalone per-dimension layer source (per `no-client-priority-heuristics`).
- ROI editing/authoring; time-travel ("ROIs as of date X"); R2 raw-object viewing.

---

## 9. Testing & Definition of Done

Per the project DoD (schema-compatible + visually close to reference + integration tests run
and pass — no "should pass" claims):

- **WS-A:** the §4 verification query shown with real counts across ≥3 dimensions.
- **WS-B.1:** integration test (dev session `author.a@vialia.test`) asserting
  `app_current_rois({p_dimensions:['crash']})` returns only crash rows, `≤ p_limit`, ordered by
  `risk_score desc`; and `app_roi_dimension_counts()` returns a row per populated dimension.
- **WS-B.2:** component test — toggling a sub-dimension attaches/detaches exactly that
  dimension's layer group and updates the panel; master toggles all enabled dimensions; a
  disabled dimension row is non-interactive.
- **Visual:** a headless-Chrome screenshot of the map with ≥2 dimension layers on (distinct
  colors) and an ROI popup open, checked against the existing panel styling.

---

## 10. File-change summary

**WS-A (data):** `services/external-data/src/external_data/registry/sources.yaml` (header-map
fixes per source); pipeline run (no code change expected beyond YAML unless a header doesn't
resolve).

**WS-B (app):**
- `supabase/migrations/0212_app_roi_layers.sql` (new)
- `packages/db-types/database.ts` (regen)
- `frontend/src/lib/dimensions.ts` (new)
- `frontend/src/lib/api.ts` (getRois params, getRoiDimensionCounts, Roi.signalCount)
- `frontend/src/lib/types.ts` (Roi.signalCount; dimension-count type)
- `frontend/src/pages/MapPage.tsx` (state, lazy fetch, cache, wiring)
- `frontend/src/components/LayersPanel.tsx` (grouped section)
- `frontend/src/components/MapCanvas.tsx` (per-dimension groups, styling, popup)
- tests: integration (RPCs) + component (panel/layer toggles)

---

## 11. Self-review (spec coverage)
- "Both halves" → WS-A (§4) + WS-B (§5–6). ✓
- "Point-source dims, full real load" → §3 four dimensions, geocoded ones deferred (§3, §8). ✓
- "Grouped: master + sub-toggles" → §6.4. ✓
- Real `priority` ROI source, no client heuristics → §1 non-goal, §6.5 (visualize `risk_score`
  only). ✓
- Schema-compat + tests run → §5 (RPC conventions), §9. ✓
- Performance with full load → §7 (top-N + lazy fetch). ✓
- Credential dependency surfaced → §4 prerequisite + fallback. ✓
- Open risk: non-SSC CSV headers unverified (§2, §4 step 1) — per-source verification is the
  first step of each source's load and the documented skip-on-failure keeps the rest landing.
