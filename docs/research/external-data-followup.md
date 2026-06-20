# External Data — Follow-up: Pending Sources & Unorthodox Acquisition

Follow-up to [`external-risk-datasets.md`](./external-risk-datasets.md). Two tasks:
**(1)** resolve that doc's **Open Questions / Gaps** (the pending sources), and
**(2)** research **less orthodox** ways to obtain geolocated urban-risk data
(news scraping, social media, live dashboards, crowdsourced maps, news APIs).

- **Compiled:** 2026-06-20
- **Method:** fan-out web research (5 angles, 23 sources, 106 extracted claims) with
  3-vote adversarial verification, **plus** direct primary-source fetches by hand to
  ground the items the automated pass couldn't finish.
- **Verification caveat (read this):** the automated verification pass **hit an API
  session limit partway through synthesis.** The **Task-1 government-dataset claims
  were fully verified (2–3 votes)**; several **Task-2 (unorthodox) claims abstained**
  — they were *cut off, not refuted*. I independently re-fetched the highest-value of
  those (GDELT, Waze, @OVIALCDMX, NL Risk Atlas, SACMEX, NL C5) to confirm them. Each
  finding below is tagged: ✅ verified · ⚠️ single-source / partial · ❓ unverified.
- **Hard requirement (unchanged):** **point-level (lat/long)**. Municipio-aggregated
  data does not qualify.

---

## TL;DR — what changed

1. **New usable point-level source found:** ✅ **SACMEX `reportes-de-agua`** — citizen
   water reports with **point coordinates**, and it **includes `encharcamientos`
   (flooding)**. This **fills the flooding gap** for CDMX at point level. Caveat: same
   as the rest — **stalled at the April-2024 batch.**
2. **The "live" systems are alive but don't expose points.** ✅ SEMOVI's quarterly
   crash reports are *current* (Q4-2025 out Apr-2026) but **aggregated only**; ✅ the
   `tablero311` Locatel dashboard is *operational* but shows an **aggregated
   choropleth**, not points. Fresh point-level from either requires a **by-request /
   transparency data agreement**, not the open portal.
3. **NL still has nothing open at point level.** ✅ NL C5 geolocates 911 reports
   *internally* but ❌ publishes no open coordinate feed; ✅ the NL Risk Atlas geoportal
   is *inactive* (unpaid licenses) and ships **PDFs only**. NL's gap is confirmed, not
   closed.
4. **Best fresh-point path is unorthodox:** **news/nota-roja scraping → LLM geocoding**
   is the most viable way to get *fresh* incident points where open data is stale —
   especially for **NL**, where no open geodata exists at all. **Waze for Cities** is
   the strongest *production* real-time point source **because our customer is
   government** (the program is free to public agencies).

---

## Part 1 — Resolutions to the Open Questions

### Q1. Are the stalled CDMX feeds obtainable by-request or via live dashboards?

**Answer: the operational systems are alive, but none exposes fresh *point-level* data
openly. Fresh points = a by-request/transparency agreement, not the open portal.**

| Channel | Status | Point lat/long? | Verdict |
|---|---|---|---|
| **SEMOVI Hechos de Tránsito** quarterly PDFs | ✅ **current** — Q4-2025 published **Apr 2026** | ✅ **No** — totals by alcaldía/zone only | Fresh but aggregated. Good for *context/validation*, not ingestion. |
| **`tablero311.cdmx.gob.mx`** (0311 Locatel live dashboard) | ✅ operational, govt-run (ADIP + CentroGeo/GeoInt) | ✅ **No** — choropleth by alcaldía/colonia | Live system, but UI exposes aggregates only. |
| 0311 open CSV | ✅ **stalled** — last file 2024-04-01, no 2025/26 | yes (in the stale file) | Unchanged from prior doc. |

- ✅ **SEMOVI quarterly reports are current** (Q4-2025 = `CUARTO REPORTE TRIMESTRAL
  2025`, published 2026-04-09) — but ✅ contain **"only aggregated statistics, not
  point-level geolocated data… does not include individual incident latitude/longitude
  coordinates."**
- ✅ The **`tablero311` dashboard is real and operational** ("Tablero de Solicitudes
  *0311 Locatel, ADIP CDMX, powered by CentroGeo and GeoInt"), confirming the **0311
  system is still running** even though the open CSV lapsed — but ✅ it presents an
  **aggregated choropleth keyed to percentage tiers, broken down by alcaldía/colonia**,
  not point coordinates.
- **Implication:** to get *fresh* CDMX points you must file a **transparency / data
  request** (Plataforma Nacional de Transparencia → Locatel/ADIP, or SSC/SEMOVI). The
  underlying data is point-level internally; it is simply not *published* as such
  anymore. Too slow for the hackathon; this is the *production* answer.

### Q2. Any current geolocated flooding / civil-protection / atlas-de-riesgo dataset?

**Answer: yes for CDMX — a *new* point-level source (SACMEX) that includes flooding —
but it's stale-2024. The "atlas de riesgo" leads are dead ends. NL has nothing open.**

- ✅ **SACMEX `datos.cdmx.gob.mx/dataset/reportes-de-agua` — NEW, point-level, includes
  flooding.** Daily citizen water reports disaggregated by **`coordenadas puntuales`**;
  categories include **`encharcamientos` (flooding/ponding)**, `drenaje obstruido`
  (obstructed drainage), `fugas` (leaks), `falta de agua`. CSV, CC-BY 4.0.
  - **Currency:** ✅ last updated **2024-04-01** (active file 2022–2024; historical
    2018–2021). Cadence *claimed* monthly, but **effectively the same April-2024 batch**
    as 0311 — treat as **stalled historical prior**, like everything else on this portal.
  - **Why it matters:** this is **both** (a) the **point-level flooding signal** the
    prior doc couldn't find, **and** (b) another **citizen-report analog** (like 0311)
    — a labeled ground-truth set for **Latent-Issue Detection** (README §5).
- ✅ **`atlas-de-riesgo-inundaciones` is a dead end for points** — it's **AGEB
  (polygon) level**, not lat/long ("a nivel ageb"). The claim that it's a current
  SGIRPC civil-protection point dataset was ✅ **refuted (1–2)**.
- ✅ **NL Risk Atlas (`atlas.nl.gob.mx`) — unusable.** Geoportal **currently inactive**
  ("Portal Atlas inactivo temporalmente. Debido a pago pendiente de licencias"); ships
  **PDF documents + a mobile app (AtlasNL) only**; **no CSV/GeoJSON/shapefile/KML, no
  API, no download portal.** Document-centric, not open data.

### Q3. Does C5 Nuevo León publish open emergency data with coordinates?

**Answer: no. ✅ NL C5 geolocates 911 reports *internally*, but ❌ publishes no open,
downloadable coordinate feed.** State Secretaría de Seguridad publicly presented a tool
that geolocalizes 911-based reports, but a targeted search surfaced **no NL C5 open-data
portal or downloadable incident dataset with coordinates** — only privacy notices for
the 911/Enlace-911 app. The point data exists operationally; it is not published.
Getting it = a **transparency request to NL Secretaría de Seguridad / C5.** Prior doc's
gap is **confirmed.**

### Q4. ZMM municipal coverage in SESNSP / INEGI

**Answer: RESOLVED in the main doc — INEGI georeferences accidents for the ZMM
(18 NL municipalities, incl. all six named), but it's a *map-viewer*, not a clean
point CSV.**

- ✅ INEGI's georeferenced ATUS accident data covers **all 16 CDMX alcaldías + 72
  municipios across 28 states** (2019–2020 bulletin) via the **"Espacio y datos de
  México" / Mapa Digital** interactive platform.
- ✅ **ZMM is covered.** The companion edit to [`external-risk-datasets.md`](./external-risk-datasets.md)
  checked INEGI's municipal-selection document and found **18 NL municipalities
  georeferenced, including all six from the original question** (San Pedro, Guadalupe,
  San Nicolás, Apodaca, Santa Catarina, Escobedo). *(My own re-fetch of
  `Municipios_georreferenciados.pdf` returned a scanned image I couldn't OCR — the main
  doc's check supersedes that.)*
- ⚠️ **Big caveat (still true):** the claim that INEGI ATUS is **true ingestible point
  lat/long** was ✅ **refuted (0–3).** INEGI exposes accidents as a **map visualization**
  (locate-on-map by entity/municipio/date), **not as a bulk downloadable point file.**
  Treat it as a **point-level *viewer*, hard to ingest in bulk** — automated extraction
  is the one open issue. The per-city open crash datasets (SSC, MTY) stay the clean
  choices.
- SESNSP unchanged: **municipio-only** (fails the requirement).

---

## Part 2 — Unorthodox acquisition methods

Where open data is stale (CDMX) or absent (NL), these are the routes to *fresh* points.
Graded on feasibility / geo-quality / freshness / legal-ToS.

| Method | Feasibility | Geo quality | Freshness | ToS / legal | Verdict for us |
|---|---|---|---|---|---|
| **News / nota-roja scraping → LLM geocoding** | Medium | Imperfect (depends on how precisely the article names the spot) | **High** (daily/hourly) | Per-site robots/ToS; news facts not copyrightable but layout is | **★ Best fresh-point path**, esp. **NL** |
| **Waze for Cities (CCP)** | Needs public-agency partner | **High** (point) | **Real-time** | Partner agreement; redistribution restricted | **★ Production path** (customer = govt) |
| **GDELT GEO 2.0 API** | Easy (free API) | **Coarse/error-prone** | 15-min | Open/free | Broad signal / ROI seeding, not precise points |
| **Social media (@OVIALCDMX, civil-protection X)** | Hard (X API cost/ToS) | Text-only → needs geocoding | Real-time | X ToS restricts scraping | Low priority — high friction, flaky |
| **Crowdsourced base maps (OSM)** | Easy | n/a (base map) | n/a | ODbL | Geocoding/snapping aid, not a risk signal |
| **Transparency / by-request (PNT/INFOMEX)** | Slow (weeks) | **High** (point) | Stale→current | Legal right of access | Production, not hackathon |

### 1. News / nota-roja scraping → LLM geocoding  ★ recommended for the demo
- **How:** scrape local accident/crime news (CDMX & MTY nota-roja outlets), extract the
  street / intersection / colonia in the prose, resolve to **lat/long** with a geocoder
  (Nominatim/Google) or directly with an LLM. We **already have LLM/VLM infra**, so the
  extraction step is cheap for us.
- **Evidence:** documented academic approach for **Spanish-language accident news**
  (MDPI *Applied Sciences* 10/18/6253; *Expert Systems w/ Applications*
  S0957417421002967 — NER + grammatical-pattern pipelines). ❓ Reported (but
  **unverified** — source paywalled on re-fetch): one pipeline found a location in
  **100% of 1,620** accident items, **~53% exact / ~47% partial** matches, partials
  resolved by majority vote across street names. Use as a feasibility signal, not a
  hard number.
- **Trade-offs:** geo precision tracks how specifically the article names the spot —
  "choque en Av. Constituyentes y Av. Observatorio" geocodes tightly; "en la México-
  Cuernavaca" doesn't. Freshness is the upside: **daily, sometimes within the hour.**
- **Why it's our best fresh option:** it's the **only practical way to get fresh points
  for Nuevo León**, where *no* open geodata exists, and it freshens stale CDMX clusters.

### 2. Waze for Cities (Connected Citizens Program)  ★ the production play
- ✅ **Free** program for **"authorities that manage traffic or public infrastructure —
  transport departments, emergency services, road operators."** Real-time **crashes,
  construction, hazards, closures**; partners also get **BigQuery access to Waze data
  (1 TB/month free).**
- **Catch:** access requires being / partnering with an **eligible public agency** —
  not open to a random team. Our **customer *is* government**, so this is the natural
  **production-grade real-time point source.** Data-sharing is two-way; **redistribution
  is restricted** by the partner agreement.
- ⚠️ Third-party "Waze traffic scrapers" exist (e.g. Apify) but **scraping Waze
  violates its ToS** — note, do not build on it.

### 3. GDELT GEO 2.0 API
- ✅ **Free, near-real-time (refreshes every 15 min)**, all 65 languages, filterable by
  **country / admin division / keyword theme** (e.g. Mexico + accidents/crime).
- ✅ **But not reliable point-level:** it **aggregates news mentions by place** and
  explicitly warns of geocoding error ("one city confused for another… name
  mistranslated"). Good as a **broad discovery / ROI-seeding signal**, not for
  pinpointing incidents.

### 4. Social media — traffic & civil-protection accounts (Twitter/X)
- ✅ **@OVIALCDMX** is CDMX's official real-time traffic account (fed by C5 cameras) —
  but ✅ it was **offline / "en mantenimiento" as of June 2023**, with SSC posting as a
  fallback. Posts are **free text, no structured geo** → still needs NER geocoding (same
  pipeline as news).
- **Friction:** the **X API is now expensive/restricted** and scraping violates X ToS;
  account availability is unreliable. **Low priority** unless a specific account proves
  consistently useful.

### 5. Crowdsourced base maps (OpenStreetMap)
- Not an incident feed, but **free (ODbL)** road network + geocoding base — useful for
  **snapping** scraped/news points to streets and for the map UI. Pair with method 1.

---

## How this updates the Priority Engine plan

- **CDMX flooding kernel — NEW:** add **SACMEX `reportes-de-agua`** (point-level,
  `encharcamientos`) as a flooding/water-infrastructure risk layer **and** as
  latent-issue ground truth alongside 0311. (Both stale-2024 — historical priors.)
- **The "real-time" story:** the open portals **cannot** deliver fresh points for
  either city. If the demo needs "what's happening now," it must come from **news
  scraping (method 1)** or **Waze for Cities (method 2, via the govt customer)** — say
  this explicitly rather than implying the open data is live.
- **Nuevo León stays asymmetric:** no open crime/flooding/civil-protection points
  exist; NL C5 and the NL Risk Atlas hold data but don't publish it. **For fresh NL
  points, news scraping is effectively the only option** short of a transparency request.
- **Don't over-invest in INEGI ATUS:** it's a **map viewer, not a bulk point file** —
  ingestion cost is high; the per-city open crash datasets (SSC for CDMX, MTY
  Incidentes Viales for Monterrey) remain the clean choices.

---

## Reconciliation with the concurrent main-doc edit

The main doc [`external-risk-datasets.md`](./external-risk-datasets.md) was revised in
parallel and resolved the open questions via the government portals (CKAN API, INEGI
municipal doc, NL C5 notices, Monterrey lighting procedure). This follow-up **agrees**
with it and **adds two things its pass didn't cover**:

1. **The whole Part 2 (unorthodox methods)** — news scraping, Waze for Cities, GDELT,
   social media, OSM. This is the user's *second* ask and is unique to this doc.
2. **SACMEX `reportes-de-agua`** as a **point-level flooding source** (incl.
   `encharcamientos`). The main doc concludes flooding is "resolved negatively for
   current point data" (citing **RUSE** — a CDMX emergencies point feed it surfaced that
   *this* pass missed — plus the coarse atlases). That's true for *current* data, but
   SACMEX is a **stale-2024 *point-level* flooding/water-report set** worth folding in
   alongside RUSE — comparable currency, finer than the AGEB atlas. **→ reconcile these.**

## Still open / would verify with more budget

1. ❓ The **news-geocoding accuracy numbers** (paywalled re-fetch) — pin down real-world
   exact/partial match rates for Mexican-Spanish accident prose before relying on them.
2. Whether a **transparency request** to Locatel/ADIP (0311) or NL C5 actually yields
   **point-level** rows (vs. aggregated) — the legitimate route to fresh points.

---

## Sources (this follow-up)

| Topic | Source | Tag |
|---|---|---|
| SACMEX water reports (point flooding) | https://datos.cdmx.gob.mx/dataset/reportes-de-agua | ✅ primary |
| SEMOVI quarterly crash reports | https://www.semovi.cdmx.gob.mx/tramites-y-servicios/transparencia/reportes-e-informes/hechos-de-transito | ✅ primary |
| 0311 Locatel live dashboard | https://tablero311.cdmx.gob.mx/ | ✅ primary |
| 0311 open dataset (stalled) | https://datos.cdmx.gob.mx/dataset/0311 | ✅ primary |
| Atlas de riesgo inundaciones (AGEB, not point) | https://datos.cdmx.gob.mx/dataset/atlas-de-riesgo-inundaciones | ✅ primary |
| NL Risk Atlas (inactive, PDFs only) | https://atlas.nl.gob.mx/ | ✅ primary |
| NL C5 geolocates 911 (internal only) | https://multimedios.com/local/nl-c5-geolocaliza-reportes-que-llegan-al-911 | ⚠️ secondary |
| INEGI georeferenced accidents bulletin | https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2021/accidentes/ACCIDENTES_2021.pdf | ✅ primary |
| INEGI georeferenced municipios list | https://gaia.inegi.org.mx/mdm6/docs/accidentes/download/Municipios_georreferenciados.pdf | ❓ scanned image |
| Waze for Cities | https://www.waze.com/wazeforcities/ | ✅ primary |
| GDELT GEO 2.0 API | https://blog.gdeltproject.org/gdelt-geo-2-0-api-debuts/ | ✅ primary |
| @OVIALCDMX status | https://www.eluniversal.com.mx/metropoli/que-esta-pasando-con-la-cuenta-de-ovial-de-cdmx-en-twitter/ | ⚠️ secondary |
| News→geocode (Spanish accident news) | https://www.mdpi.com/2076-3417/10/18/6253 | ❓ paywalled |
| News→geocode (NER pipeline) | https://www.sciencedirect.com/science/article/abs/pii/S0957417421002967 | ❓ paywalled |

---

## Appendix — raw verification record

Full claim-level output of the automated pass (5 angles → 23 sources → 106 claims →
top-25 verified by 3-vote adversarial check). Kept verbatim so the file is the complete
record. **Vote = (refutes–confirms or confirm tally as reported); ✓ survived, ✗ killed,
abstain = verifier cut off by the session limit (treat as *unverified*, not refuted).**

**Run stats:** angles 5 · sources 23 · claims extracted 106 · verified 25 · confirmed 15
· killed 10 · synthesis step **failed (session limit)**.

### ✅ Confirmed claims (survived verification)

1. **(3–0)** CDMX portal hosts **SSC "Hechos de tránsito" (serie ampliada)** with
   **per-event coordinates** — point-level, not aggregated.
   `datos.cdmx.gob.mx/dataset/hechos-de-transito-reportados-por-ssc-base-ampliada-no-comparativa`
2. **(3–0)** SSC geolocation is point-level — it even **retains records whose coords
   fall outside CDMX** ("PUNTOS QUE ESTÁN FUERA DE LA CIUDAD DE MÉXICO"), proving
   individual lat/long points. *(same source)*
3. **(3–0)** **SEMOVI publishes current quarterly crash reports** — newest **Q4-2025,
   published 2026-04-09**. `semovi.cdmx.gob.mx/.../hechos-de-transito`
4. **(3–0)** SEMOVI quarterly reports are **aggregated only** — "does not include
   individual incident latitude/longitude coordinates." *(same source)*
5. **(2–1)** **0311 Locatel** dataset uses **lat/long georeferencing** ("se generó a
   partir del cruce de la georreferenciación (latitud y longitud)"). `datos.cdmx.gob.mx/dataset/0311`
6. **(3–0)** **0311 open feed stalled** — newest file "Solicitudes *0311 (2024) — Last
   Updated: April 1, 2024", no 2025/26. *(same source)*
7. **(3–0)** **`tablero311.cdmx.gob.mx` live dashboard operational**, govt-run (ADIP +
   CentroGeo/GeoInt). `tablero311.cdmx.gob.mx`
8. **(2–1)** That dashboard shows an **aggregated choropleth by alcaldía/colonia**
   (percentage tiers), **not point coords**. *(same source)*
9. **(3–0)** **SACMEX `reportes-de-agua`** — daily citizen water reports disaggregable
   by **`coordenadas puntuales`** (point-level). `datos.cdmx.gob.mx/dataset/reportes-de-agua`
10. **(3–0)** That dataset's categories include **`encharcamientos` (flooding)**,
    `drenaje obstruido`, `fugas`. *(same source)*
11. **(3–0)** **`atlas-de-riesgo-inundaciones` is AGEB (polygon) level**, not point ("a
    nivel ageb"). `datos.cdmx.gob.mx/dataset/atlas-de-riesgo-inundaciones`
12. **(3–0)** **Monterrey "Incidentes Viales"** = geocoded point-level siniestros on
    primary/secondary roads. `mide.monterrey.gob.mx/.../incidentes_viales/metadata_detail`
13. **(3–0)** That MTY dataset covers **Monterrey municipality only** (bbox
    x0=-100.68897, x1=-100.160648, y0=25.50868086, y1=25.81578015), **not the ZMM**.
    *(same source)*
14. **(3–0)** INEGI georeferenced accident data covers **88 areas = all 16 CDMX
    alcaldías + 72 municipios / 28 states** (2019–2020).
    `inegi.org.mx/contenidos/saladeprensa/boletines/2021/accidentes/ACCIDENTES_2021.pdf`
15. **(2–0, 1 abstain)** That data is published via the **"Espacio y datos de México"
    interactive platform**, distinguishable by entity/municipio/year/month/day/hour/class
    /type. *(same source)*

### ✗ Killed by genuine refutation (real votes)

- **(1–2)** "CDMX hosts a *current* SGIRPC civil-protection flooding **point** dataset"
  — **refuted.** (The atlas is AGEB-level; see confirmed #11.)
- **(0–3)** "INEGI ATUS is **true ingestible point lat/long** satisfying the
  requirement" — **strongly refuted.** It's a map *viewer*, not a bulk point file.

### ❓ Abstained — cut off by session limit (UNVERIFIED, not refuted)

These ran out of budget before reaching a verdict. **Independently re-fetched by hand**
where marked ✓; the rest remain open.

- INEGI **`Municipios_georreferenciados.pdf`** ZMM list — *(❓ here; **resolved in the
  main doc**: 18 NL municipalities incl. all six named).*
- All 16 CDMX alcaldías in INEGI ATUS — supported by confirmed #14.
- **NL Risk Atlas geoportal inactive (unpaid licenses)** — ✓ **re-fetched & confirmed**
  (`atlas.nl.gob.mx`: "Portal Atlas inactivo temporalmente. Debido a pago pendiente de
  licencias"; PDFs + mobile app only, no open data).
- **NL Risk Atlas publishes no machine-readable GIS data** — ✓ **re-fetched & confirmed.**
- "News-text → point lat/long pipeline works for a Mexican city" (MDPI 10/18/6253) —
  ❓ **paywalled on re-fetch**, unverified.
- "Spanish accident-news NER pipeline (SpaCy)" — ❓ paywalled, unverified.
- "News geolocation quality: 1,620 items, 100% located, 53% exact / 47% partial" — ❓
  **paywalled, unverified — do not quote as fact.**
- "All ZMM municipios covered by INEGI ATUS" — ❓ here; see main-doc resolution above.

### Independently grounded by hand (not in the automated top-25)

- ✅ **NL C5 geolocates 911 reports internally**, but **no public open coordinate feed**
  (WebSearch: only 911/Enlace-911 privacy notices; no NL C5 open-data portal).
  `multimedios.com/local/nl-c5-geolocaliza-reportes-que-llegan-al-911`
- ✅ **GDELT GEO 2.0**: free, refreshes every 15 min, filterable by country/theme, **but
  aggregates by place with explicit geocoding error** — not reliable point-level.
  `blog.gdeltproject.org/gdelt-geo-2-0-api-debuts/`
- ✅ **Waze for Cities**: free for public agencies; real-time crashes/hazards/closures +
  1 TB/mo BigQuery; redistribution restricted. `waze.com/wazeforcities`
- ✅ **@OVIALCDMX**: official real-time traffic account (C5 cameras), **offline "en
  mantenimiento" as of Jun 2023**, free-text (no structured geo).
  `eluniversal.com.mx/metropoli/que-esta-pasando-con-la-cuenta-de-ovial-de-cdmx-en-twitter`
- ✅ **SACMEX `reportes-de-agua` currency**: last updated **2024-04-01** (active
  2022–2024 + historical 2018–2021), CSV, CC-BY 4.0 — **stalled, like the rest.**
