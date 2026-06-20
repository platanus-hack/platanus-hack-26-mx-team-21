# External Risk-Signal Datasets — CDMX & Monterrey

Research for the **Priority Engine** (README §Components #4): external geolocated
incident/event data to combine with detected infrastructure issues into a
priority map.

- **Compiled:** 2026-06-20
- **Method:** multi-source web research over primary government open-data portals,
  with adversarial verification of each claim. The original pass fetched 20
  primary sources, verified 25 claims, and refuted 2. A follow-up on 2026-06-20
  queried the CDMX CKAN API directly and checked INEGI's municipal-selection
  document, Nuevo Leon's C5 notices and risk-atlas services, and Monterrey's
  public-lighting procedure. All findings below rest on primary government
  sources -- no blog/forum sources.
- **Scope:** geolocated urban risk/incident events — crashes, crime, emergency
  calls, traffic, flooding/civil-protection, 311-style citizen complaints.

---

## ⚠️ Read this first: the "live data" reality

**None of these are live feeds.** Mexican government open data is published in
**annual batches**, not real-time streams. The freshest geolocated data you can
obtain from the open portals is **calendar-year 2024, released mid-2025.**

An earlier draft of this research labeled several datasets "current /
recommended." That was misleading: it meant *"freshest batch that exists and the
series isn't abandoned,"* **not** *"updated recently."* Corrected currency, as of
**2026-06-20**:

| Dataset | Last portal update | Newest data point | Age of newest data | Update pattern |
|---|---|---|---|---|
| FGJ Carpetas (crime, CDMX) | 2025-03-06 (~15 mo ago) | full-year 2024 | ~18 mo | annual batch |
| SSC Hechos de tránsito (crashes, CDMX) | 2025-05-02 (~13 mo ago) | Dec 2024 | ~18 mo | annual batch |
| MTY Incidentes Viales (crashes, MTY) | data through Dec 2024 | Dec 2024 | ~18 mo | annual batch (cadence unclear) |
| C5 Incidentes viales (crashes, CDMX) | 2024-03-08 (~27 mo ago) | Feb 2024 | ~28 mo | **stalled** |
| *0311 Locatel/SUAC (311, CDMX) | 2024-04-01 (~27 mo ago) | early 2024 | ~27 mo | **stalled** |
| 911 calls (CDMX) | 2023-07-06 (~35 mo ago) | 1st-half 2022 | ~48 mo | **discontinued** |
| RUSE emergencies (CDMX) | downloadable resource updated 2021 | Dec 2020 | ~66 mo | **discontinued download**; dashboard ends Apr 2023 |
| SESNSP (crime, national) | 2026-06-19 (yesterday) | May 2026 | ~1 mo | **live, monthly** — but municipio-only |
| INEGI ATUS (accidents, national) | 2025-07-29 (~11 mo ago) | 2024 | ~18 mo | annual; selected municipalities have points, but only through map products |

**The irony:** the only genuinely fresh source (SESNSP, updated the day before
this research) is the municipio-aggregated one that is too coarse to use. Every
**point-level** geolocated source is ~18 months stale at best, and the broadest
Nuevo Leon point source (INEGI ATUS) is exposed through map products rather than
an obvious bulk download.

**Is ~18-month-old data a problem for us?** Probably not, and here's the honest
case either way:

- **For:** a priority map needs *stable spatial risk density* — where crashes and
  crime persistently cluster — not this week's incidents. Year-old batch data is
  appropriate for computing spatial priors, and these clusters move slowly.
- **Against:** if the product story depends on "real-time" / "what's happening
  now," open data cannot deliver that for either city. There is **no real-time
  geolocated risk feed** in the open portals. Real-time would require scraping
  live dashboards (e.g. `tablero311.cdmx.gob.mx`) or a by-request data agreement.

---

## Requirement filter applied

You stated **point-level (lat/long) geolocation is a hard requirement** —
municipio-aggregated data is not useful right now. The catalog below is split
accordingly:

- **Tier A / B / C** = geolocated point data (meets the requirement), graded by currency.
- **Parked** = municipio-aggregated, areal hazard data, or currently unavailable
  services (does *not* meet the point-event requirement) -- listed only because
  they are the sole option for some gaps (see §Gaps).

---

## Tier A — Geolocated, freshest batch available (2024 data)

These are the strongest ingestible signals. Point lat/long, not abandoned,
latest batch is full-year 2024 released in 2025. Treat as **historical risk
priors**, not live.

### A1. FGJ Carpetas de investigación — CDMX crime ★ best crime signal
- **Covers:** street-level crime investigation folders (homicide, robbery,
  assault, kidnapping), Jan 2016 onward.
- **Geo:** **point lat/long per event**, plus `colonia_catalogo` / `alcaldia_catalogo`
  *derived from* the coordinates (good for spatial joins).
- **Currency:** updated 2025-03-06, data through 2024. Annual batch.
- **Format:** CSV, CC-BY 4.0, monthly cadence historically.
- **URL:** https://datos.cdmx.gob.mx/dataset/carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico
- **Note:** specific street *names* removed since May 2022 for sensitivity, but
  **lat/long coordinates remain**. This is the **only point-geolocated crime
  source found — CDMX only.**

### A2. SSC Hechos de tránsito — CDMX road crashes ★ use instead of C5 (B1)
- **Covers:** traffic crashes recorded by Secretaría de Seguridad Ciudadana from
  2018 — event date, type, deceased/injured characteristics, supporting medical unit.
- **Geo:** **point lat/long per event.**
- **Currency:** the 2024 companion file was updated 2025-05-02 (data through Dec
  2024). The "base ampliada" parent file ends Dec 2023.
- **Format:** CSV, CC-BY 4.0.
- **URLs:**
  - 2024 file (newest): https://datos.cdmx.gob.mx/dataset/hechos-de-transito-registrados-por-la-ssc-2024-serie-de-datos-ampliada-no-comparativa
  - base series: https://www.datos.cdmx.gob.mx/dataset/hechos-de-transito-reportados-por-ssc-base-ampliada-no-comparativa
- **Note:** some records carry coordinates that fall **outside** CDMX (source
  errors, retained for completeness) — filter on a CDMX bounding box at ingest.

### A3. MIDE / DatosMTY GeoNode "Incidentes Viales" — Monterrey road crashes ★ best MTY signal
- **Covers:** geocoded *Siniestros de Tránsito* on primary & secondary roadways
  within the **municipality of Monterrey** ("Nuestras Calles Seguras").
- **Geo:** **point lat/long, EPSG:4326** (WFS returns `longitud`/`latitud` + POINT geometry).
- **Currency:** Jan 2017 – **Dec 2024**. (Adversarial check refuted a "coverage
  ends 2023" claim 0-3 — it does include 2024.)
- **Format:** CSV / GeoJSON / Shapefile / GML via **WFS API**. ODbL license.
- **URLs:**
  - metadata: https://mide.monterrey.gob.mx/datasets/god_datosmty_data:geonode:incidentes_viales/metadata_detail
  - WFS endpoint: https://mide.monterrey.gob.mx/geoserver/ows
- **Note:** the bare dataset slug URL 404s; use `/metadata_detail` and the WFS/data
  endpoints. **Covers Monterrey municipality only** — not the wider ZMM (San
  Pedro, Guadalupe, San Nicolás, Apodaca, etc.).

---

## Tier B — Geolocated but stalled (use as static historical priors only)

Point data exists and is rich, but the open CSV stopped updating. Fine for a
one-time historical prior; do **not** expect refreshes.

### B1. C5 "Incidentes viales reportados por C5" — CDMX traffic
- **Covers:** 500k+ traffic incidents tagged *accidentes, atropellos, choques,
  ciclistas, motociclistas.*
- **Geo:** **point lat/long** + alcaldía.
- **Currency:** **STALLED** — most recent record 2024-02-29; portal last modified
  2024-03-08; no 2025/2026 data.
- **Format:** CSV (split 2014-15 / 2016-18 / 2019-21 / 2022-24 + full historical).
- **URL:** https://datos.cdmx.gob.mx/dataset/incidentes-viales-c5
- **Note:** this is the **most-cited CDMX traffic dataset online** — easy to assume
  it's live. It is not. Prefer **A2 (SSC)** for anything past Feb 2024. (Online
  "Q1-2025 traffic" figures come from SEMOVI's separate *Hechos de Tránsito*
  quarterly PDFs, not this CSV.)

### B2. *0311 Locatel / SUAC — CDMX 311-style citizen complaints ★ closest to our own output
- **Covers:** citizen service requests via Mexico City's **0311 Locatel** system
  (renamed from SUAC, Nov 2021) — explicitly tagged **bacheo/baches (potholes)**,
  **reportes de agua**, servicios urbanos.
- **Geo:** **point lat/long** + `colonia_datos` (derived from coords).
- **Currency:** **STALLED** — annual CSVs 2019-2024, last updated 2024-04-01,
  coverage through early 2024.
- **Format:** CSV, CC-BY 4.0.
- **URL:** https://datos.cdmx.gob.mx/dataset/0311
- **Why it matters for us:** this is the **closest existing analog to our own
  output** (citizen-reported potholes/water). Even stale, it's a labeled
  ground-truth set to validate Latent-Issue Detection (README §5) against — and a
  prior for where citizens already report problems. **The underlying 0311 system
  and a live dashboard (`tablero311.cdmx.gob.mx`) remain operational** even though
  the CSV lapsed — a candidate for scraping/by-request if live data is needed.

---

## Tier C — Geolocated but discontinued

### C1. C5 "Llamadas 911" — CDMX emergency calls
- **Covers:** emergency-call incidents — fires, robberies, accidents, medical
  emergencies, injuries, aggressions.
- **Geo:** lat/long present but = **manzana (city-block) centroid**, not exact point.
- **Currency:** **DISCONTINUED** — ends 1st-half 2022, last updated 2023-07-06.
- **URL:** https://datos.cdmx.gob.mx/dataset/llamadas-numero-de-atencion-a-emergencias-911
- **Verdict:** too old and too coarse (block centroid) to recommend. Listed for
  completeness.

### C2. RUSE — CDMX civil-protection emergencies and flood events
- **Covers:** the *Registro Unico de Situaciones de Emergencia*: reports received
  by the civil-protection secretariat and adjacent institutions such as C5,
  categorized as geological, hydrometeorological, chemical-technological,
  sanitary-ecological, or socio-organizational.
- **Geo:** **point lat/long per event**, plus GeoJSON point, colonia and alcaldia.
- **Currency:** the downloadable data contains **31,589 events from 2018-01-01
  through 2020-12-11**. The separate RUSE dashboard states a wider validity
  period through **2023-04-30**, but offers no current open batch.
- **Flood subset:** direct CKAN SQL finds **989** records whose taxonomy or
  incident is inundation/encharcamiento: 450 `INUNDACION / ENCHARCAMIENTO`, 271
  `INUNDACION / INUNDACION PLUVIAL`, and 268 other matching combinations.
- **Format:** CSV in CKAN DataStore and SHP, CC-BY 4.0.
- **URLs:**
  - dataset: https://datos.cdmx.gob.mx/dataset/registro-unico-de-situaciones-de-emergencia
  - DataStore API resource: https://datos.cdmx.gob.mx/api/3/action/datastore_search?resource_id=803cb0b9-43af-4073-bbfd-0b542c5fd337
  - dashboard: https://atlas.cdmx.gob.mx/RUSE/
- **Verdict:** useful labeled historical flood/civil-protection points, but far
  too old to represent current conditions.

---

## Tier D — Geolocated, current batch, but map-only

These meet the point-level requirement in the government product, but are not
offered as a straightforward bulk point file. Treat ingestion as an engineering
spike, not a guaranteed hackathon input.

### D1. INEGI ATUS georeferenced selected municipalities — national crashes
- **Covers:** per-accident locations for selected municipalities from 2019 onward;
  annual data currently runs through 2024. Urban/suburban roads only (federal
  highways excluded).
- **Geo:** point locations in INEGI's *Espacio y Datos de Mexico* and *Mapa
  Digital de Mexico* products.
- **Nuevo Leon coverage:** INEGI explicitly lists **18 municipalities**: Abasolo,
  Apodaca, Cadereyta Jimenez, El Carmen, Cienega de Flores, Garcia, San Pedro
  Garza Garcia, General Escobedo, General Zuazua, Guadalupe, Juarez, Monterrey,
  Pesqueria, Salinas Victoria, San Nicolas de los Garza, Hidalgo, Santa Catarina,
  and Santiago.
- **Format/access caveat:** INEGI's program page directs users to its two map
  products. The normal ATUS microdata download is municipio-coded but does not
  contain the published point geometry, and no supported bulk point download was
  identified. An older 2020 "Base municipal de Accidentes de Transito
  Georreferenciados" download page now reports that its file does not exist.
- **URLs:**
  - program: https://www.inegi.org.mx/programas/accidentes/
  - official municipality list: https://www.inegi.org.mx/contenidos/programas/accidentes/doc/municipios_georreferenciados.pdf
  - map: https://www.inegi.org.mx/app/mapa/espacioydatos/
- **Verdict:** materially better ZMM coverage than A3 if its map service can be
  queried reliably. A3 remains the easiest hackathon ingest for Monterrey proper.

---

## Parked — does NOT meet the point-event requirement

Kept only because they are the **sole** option for two gaps. **Not useful right
now** given the point-level requirement.

### P1. SESNSP Incidencia Delictiva — national crime counts
- Both CDMX and NL/ZMM. **Live and monthly** (through May 2026), Excel + dashboards.
- **Municipio granularity only** — no colonia, no points.
- **Only crime signal that exists for Monterrey/NL at all** (see Gaps).
- https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva

### P2. CDMX Atlas de Riesgo — inundation hazard surface
- **Geo:** AGEB-level hazard indicator, not incident points. CSV and SHP.
- **Currency:** underlying CSV updated 2021-01-28 and SHP 2021-06-26; metadata
  changed in 2023. The portal labels it annual, but no later resource exists.
- **Verdict:** possible static polygon prior if area-level signals become
  acceptable; fails the current point-event requirement.
- https://datos.cdmx.gob.mx/dataset/atlas-de-riesgo-inundaciones

### P3. Nuevo Leon Atlas de Riesgos — legacy hazard maps
- Covers hydrometeorological hazards, including flooding, through state and
  municipal atlas documents. The principal metropolitan atlas dates to 2013;
  Monterrey's visible update is from 2015, while a Guadalupe revision is dated
  2023.
- The official geoportal currently says it is disabled indefinitely because of
  unpaid licenses. Its ArcGIS REST directory is visible, but tested map services
  return HTTP 500 because the service instance cannot initialize.
- **Verdict:** documents may guide manual feature engineering, but there is no
  dependable live or bulk geospatial service to ingest for the hackathon.
- https://atlas.nl.gob.mx/

---

## Gaps found (don't spend hackathon time hunting these)

- **Monterrey/NL crime — no geolocated dataset exists.** The NL state catalog
  (`catalogodatos.nl.gob.mx`) is actively maintained (through Jun 2026) but holds
  only **aggregated 070 citizen-call volumes**. Searches for `transito`,
  `accidentes`, `vialidad`, `proteccion civil` each return **0 results**;
  `seguridad` returns only penitentiary stats. For NL crime, **SESNSP at municipio
  level (P1) is the only option** — and it fails the point-level requirement.
- **Current flooding / civil protection:** no current point-event source surfaced
  for either metro. CDMX has historical RUSE points through 2020 (dashboard
  through Apr 2023) and an AGEB flood surface last published in 2021. Nuevo Leon
  has legacy atlas documents, but its official geoportal and map services are
  currently disabled.
- **C5 Nuevo Leon:** no public incident dataset surfaced. A current (Jun 2025)
  official privacy notice proves that the Enlace 911 app captures exact real-time
  locations and that C5 may produce anonymized statistics by geographic zone.
  The data therefore exists operationally, but availability requires a formal
  transparency/data-sharing request.
- **Monterrey public-lighting reports:** no open dataset surfaced, but the city's
  documented workflow proves that reports from the Regina app or 072 are captured
  in an internal system, dispatched to a provider, and closed after work. This is
  a strong by-request source for broken-light ground truth. Request anonymized
  report ID, category/failure type, coordinates or address, created/closed times,
  and status through the municipal transparency channel.

---

## How this maps to the Priority Engine

- **Primary risk kernels (point-level, per requirement):**
  - CDMX → **A1 FGJ crime** + **A2 SSC crashes**
  - Monterrey → **A3 MTY Incidentes Viales** (Monterrey municipality only)
- **Expansion candidate:** **D1 INEGI ATUS** supplies mapped point crashes for 18
  Nuevo Leon municipalities, but needs an extraction/API spike before it can
  replace or augment A3.
- **Coverage asymmetry to design around:** CDMX has both crime *and* crashes at
  point level; Monterrey has **crashes only** — no point-level crime exists for
  NL. The priority model must not assume symmetric inputs across cities.
- **Latent-issue ground truth (README §5):** **B2 *0311** baches/agua reports are
  a labeled set of citizen-reported infrastructure issues — validate VLM ROI
  hypotheses against it (CDMX only, historical).
- **Coordinate-quality handling at ingest:**
  - 911 (C1) coords are block centroids — not exact points.
  - SSC (A2) contains out-of-CDMX coords from source errors — bbox-filter.
  - FGJ/0311 `colonia` fields are *derived from* coords — reliable for joins.
  - RUSE (C2) contains point geometry but is historical only; keep source dates
    visible so its density is not mistaken for current risk.

---

## Resolved questions and remaining unknowns

1. **CDMX stalled feeds:** the 0311 dashboard remains online and exposes date
   controls into 2026, while SEMOVI publishes current quarterly traffic PDFs.
   Neither is a documented bulk point feed. Whether complete current records can
   be obtained by request remains unverified.
2. **Flooding:** resolved negatively for current point data. RUSE supplies stale
   event points; CDMX and NL atlases supply stale/coarse hazard surfaces.
3. **C5 Nuevo Leon:** resolved negatively for public open data, positively for
   internal exact-location collection. A transparency/data-sharing request is the
   next action, not more portal searching.
4. **ZMM crash coverage:** resolved. INEGI maps georeferenced accidents for 18 NL
   municipalities, including all six municipalities named in the original
   question. Practical automated extraction remains the only open issue.
5. **Monterrey lighting ground truth:** the internal Regina/072 workflow exists;
   public release and coordinate quality remain unknown pending a transparency
   request.

---

## Source list (all primary government sources)

| Source | URL |
|---|---|
| FGJ carpetas (CDMX crime) | https://datos.cdmx.gob.mx/dataset/carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico |
| SSC hechos de tránsito 2024 (CDMX crashes) | https://datos.cdmx.gob.mx/dataset/hechos-de-transito-registrados-por-la-ssc-2024-serie-de-datos-ampliada-no-comparativa |
| SSC hechos base series | https://www.datos.cdmx.gob.mx/dataset/hechos-de-transito-reportados-por-ssc-base-ampliada-no-comparativa |
| MTY Incidentes Viales (metadata) | https://mide.monterrey.gob.mx/datasets/god_datosmty_data:geonode:incidentes_viales/metadata_detail |
| MTY GeoServer WFS | https://mide.monterrey.gob.mx/geoserver/ows |
| C5 incidentes viales (CDMX, stalled) | https://datos.cdmx.gob.mx/dataset/incidentes-viales-c5 |
| *0311 Locatel/SUAC (CDMX 311, stalled) | https://datos.cdmx.gob.mx/dataset/0311 |
| C5 911 calls (CDMX, discontinued) | https://datos.cdmx.gob.mx/dataset/llamadas-numero-de-atencion-a-emergencias-911 |
| RUSE emergencies (CDMX, discontinued download) | https://datos.cdmx.gob.mx/dataset/registro-unico-de-situaciones-de-emergencia |
| RUSE dashboard | https://atlas.cdmx.gob.mx/RUSE/ |
| SESNSP incidencia delictiva (national, municipio) | https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva |
| INEGI ATUS | https://www.inegi.org.mx/programas/accidentes/ |
| INEGI georeferenced municipality list | https://www.inegi.org.mx/contenidos/programas/accidentes/doc/municipios_georreferenciados.pdf |
| NL state open-data catalog | https://catalogodatos.nl.gob.mx/dataset/ |
| C5 NL Enlace 911 privacy notice | https://www.nl.gob.mx/es/publicaciones/aviso-de-privacidad-integral-app-enlace-911 |
| CDMX atlas de riesgo inundaciones | https://datos.cdmx.gob.mx/dataset/atlas-de-riesgo-inundaciones |
| Nuevo Leon Atlas de Riesgos | https://atlas.nl.gob.mx/ |
| Monterrey public-lighting procedure | https://www.monterrey.gob.mx/pdf/new/Procedimientos/ServiciosP/P_SSP_GPJ_01_Servicio_de_Alumbrado_Publico.pdf |
| Monterrey transparency requests | https://www.monterrey.gob.mx/transparencia/Oficial_/Presenta_tu_Solicitud.html |
