# Observation Contract — Design

**Date:** 2026-06-20
**Status:** Approved (design)
**Component:** Issue Detection output contract (the shared schema between vision/latent detection, the map, and the optimization layer)

---

## 1. Scope

This spec defines **one thing**: the contract for the *final output of the vision layer* — the schema for the infrastructure issues that render on the **map** and feed the **optimization / priority** layer.

Explicitly **out of scope** (owned by other modules):

- Video / object storage. Observations only carry a **reference handle** (`recording_id`, `frame_ref`) back to the source frame; the bytes live elsewhere.
- The vision / VLM models themselves. We assume a generic producer that emits observations.
- Any **inference / derived data** — confidence, severity, priority. Those are **enrichments** other modules add, keyed on `observation.id`.

The term **"issue" is renamed `observation`** throughout: it is a *fact recorded by a sweep at a point in time*, which pairs naturally with the sweep concept (a sweep *observes*; a later sweep *re-observes*).

## 2. Principles

1. **Facts only.** An observation records *what* was detected, *where*, *when*, and *from what source*. Judgmental or derived data is never stored here; it is enriched elsewhere by reference to `observation.id`.
2. **Immutable core, mutable lifecycle.** The factual fields of a row never change. A small set of lifecycle fields (currency, counts) are updated as sweeps re-examine the area.
3. **Logical supersession, never hard delete.** Replacing/clearing an observation marks it superseded or resolved. History is preserved, "current" is a filter, and time-travel ("what did the city look like on date X") is free.
4. **Re-assess areas, don't match issues.** Cross-sweep "is this the same pothole?" identity tracking is deliberately avoided. Currency is driven by re-observation (confirmation) and area re-examination (resolution), not fuzzy persistent-identity matching.

## 3. Entities

Three tables: an extensible **type catalog**, a **sweep** (survey pass), and the **observations** themselves.

### 3.1 Full DDL

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- ─────────────────────────────────────────────────────────────
-- observation_types : extensible catalog
--   A new issue type is a row, not a migration — this is what makes
--   "start reviewing a new issue type" (an NL prompt) cheap.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE observation_types (
    slug            TEXT PRIMARY KEY,             -- 'pothole'
    label           TEXT NOT NULL,                -- 'Pothole'
    category        TEXT NOT NULL,                -- 'road_surface'
    description     TEXT,
    merge_radius_m  REAL    NOT NULL DEFAULT 10,  -- "same instance" distance for confirmation
    auto_resolvable BOOLEAN NOT NULL DEFAULT true,-- false for latent / absence types
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- sweeps : one survey pass and what it examined.
--   Required by resolution: "not re-observed" is only meaningful
--   relative to a sweep that actually looked there, for those types.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE sweeps (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coverage       geography   NOT NULL,          -- swath examined ((multi)polygon, e.g. buffered route)
    assessed_types TEXT[]      NOT NULL,          -- observation types this sweep looked for
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ NOT NULL,
    platform       TEXT,                           -- 'trash_truck_07', 'adhoc', ...
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sweeps_coverage_gix ON sweeps USING GIST (coverage);

-- ─────────────────────────────────────────────────────────────
-- observations : immutable factual detections + currency lifecycle
-- ─────────────────────────────────────────────────────────────
CREATE TABLE observations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_version   SMALLINT NOT NULL DEFAULT 1,

    -- what / where / when  (the asserted fact)
    observation_type TEXT NOT NULL REFERENCES observation_types(slug),
    location         geography(Point,4326) NOT NULL,
    observed_at      TIMESTAMPTZ NOT NULL,         -- capture time of the source frame

    -- provenance (inline / denormalized; reference back to source frame + producer)
    sweep_id         UUID NOT NULL REFERENCES sweeps(id),
    recording_id     UUID NOT NULL,                -- handle into the storage module
    frame_ref        TEXT NOT NULL,                -- frame index / media-time offset
    image_bbox       JSONB,                        -- {x,y,w,h} normalized 0–1
    detector_name    TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    detected_at      TIMESTAMPTZ NOT NULL,         -- when detection ran
    attributes       JSONB NOT NULL DEFAULT '{}',  -- type-specific facts only

    -- lifecycle signals (machine, from sweep ingest)
    confirmation_count INT NOT NULL DEFAULT 1,     -- sweeps that have observed this instance
    miss_count         INT NOT NULL DEFAULT 0,     -- near-by sweeps that didn't re-find it (triage signal)

    -- lifecycle outcome (two exit doors out of "current")
    superseded_by_observation_id UUID REFERENCES observations(id),  -- confirmed & replaced
    resolved_at        TIMESTAMPTZ,                                  -- gone; NULL = still present
    resolution_source  TEXT CHECK (resolution_source IN ('human','auto_miss')),
    reviewed_by        TEXT,                                         -- reviewer id, when human

    -- temporal validity
    valid_from       TIMESTAMPTZ NOT NULL,         -- = producing sweep's start
    valid_to         TIMESTAMPTZ,                  -- set when superseded or resolved
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()   -- ingestion time
);

-- fast spatial lookups over the *current* set only
CREATE INDEX observations_current_gix ON observations
    USING GIST (location)
    WHERE superseded_by_observation_id IS NULL AND resolved_at IS NULL;
CREATE INDEX observations_type_ix  ON observations (observation_type);
CREATE INDEX observations_sweep_ix ON observations (sweep_id);

-- the live set everyone reads
CREATE VIEW current_observations AS
    SELECT * FROM observations
     WHERE superseded_by_observation_id IS NULL
       AND resolved_at IS NULL;
```

### 3.2 Field reference (observations)

| Field | Meaning | Who uses it |
|---|---|---|
| `id` | Stable identity; enrichment join key | everyone |
| `schema_version` | Lets consumers evolve safely | everyone |
| `observation_type` → catalog | What was detected | map (icon), optimization (weighting input) |
| `location` `geography(Point,4326)` | Where — the pin | map, optimization (spatial joins) |
| `observed_at` | Capture time of the source frame (freshness) | map, optimization |
| `sweep_id` | Which survey pass produced it | lifecycle |
| `recording_id`, `frame_ref` | Reference back to the source frame | storage module (evidence) |
| `image_bbox` | Detector's region in the frame `{x,y,w,h}` 0–1 | storage module (crop/overlay) |
| `detector_name` / `detector_version` | Provenance / reproducibility / filtering | audit |
| `detected_at` | When detection ran | audit |
| `attributes` jsonb | Type-specific **facts** only | type-aware consumers |
| `confirmation_count` | Sweeps that have observed this instance | review triage, optimization confidence-by-reference |
| `miss_count` | Near-by sweeps that didn't re-find it | review triage / overflow auto-resolve |
| `superseded_by_observation_id` | Confirmed & replaced (NULL = not) | currency |
| `resolved_at` / `resolution_source` / `reviewed_by` | Resolution outcome (NULL = still present) | map filter, optimization |
| `valid_from` / `valid_to` | Temporal validity window | time-travel queries |

**Enrichments other modules layer on, keyed on `observation.id` (NOT in this contract):** confidence/severity (vision quality), priority score (optimization), region/grid binding, the full human-review queue/UI, dismissals.

## 4. Lifecycle

An observation enters as **active** (`current`) and leaves the current set through exactly one of two doors:

- **Confirmed** → a later sweep re-observes it (same type, within the type's `merge_radius_m`). The fresh observation **supersedes** the old one and carries the confirmation forward (`confirmation_count + 1`). *Still there.*
- **Resolved** → a **reviewed decision** that it is gone. *Gone.*

```
                       ┌─────────────── re-observed (same type, ≤ merge_radius) ──────────────┐
                       │                                                                      ▼
   new sweep ─▶  [ active observation ]  ── passed near, not re-found (≤ tolerance) ─▶ miss_count++
                       │                                                                      │
                       │                                                  (signal, not a gate)│
                       ▼                                                                      ▼
              superseded_by = fresh                                        reviewed (human | auto_miss overflow)
              (confirmation_count++)                                                  │
                                                                                      ▼
                                                                              resolved_at set
```

### 4.1 Confirmation vs Resolution — why both, and why each needs what it needs

- **Confirmation is observation-vs-observation.** Same type + close proximity ≈ same instance, so a re-detection retires the nearby same-type one and takes its place. This needs *no* sweep coverage — only the new observation and the old one. It deliberately avoids fuzzy persistent-identity tracking.
- **Resolution is observation-vs-sweep.** A *missing* re-observation is ambiguous: gone, or never looked at? It is only meaningful relative to a sweep that (a) **covered** the spot and (b) **assessed** that type. Hence `sweeps.coverage` + `sweeps.assessed_types`. The fresh observations alone cannot supply this: they are the few points where issues were *found*, not the whole area examined, and they say nothing about a type that was looked for and found *zero* of.

### 4.2 Robustness to route divergence

No two sweeps capture the same perspective; routes drift by meters and GPS jitters. Two consequences are designed in:

- **Tolerant coverage.** The resolution check is "did the sweep pass *near* this spot," `ST_DWithin(location, coverage, tolerance_m)`, not strict containment — so a slightly diverged route still triggers a resolution *attempt*.
- **`miss_count` is a signal, not a gate.** One miss can be a bad angle, not a repair. Misses accumulate; a single near-miss never resolves anything on its own.

### 4.3 Resolution is human-in-the-loop

Resolution is a **reviewed decision**, never an ingest-time flip. Sweep ingest only *tallies signals*.

- **Primary path — human.** A person confirms batches: these exist, those are gone. Sets `resolved_at, resolution_source = 'human', reviewed_by`.
- **Overflow assist — `auto_miss`.** When there is too much to review by hand, `miss_count` ranks the queue and can auto-clear the obvious cases: many near-misses ⇒ very likely gone. Sets `resolved_at, resolution_source = 'auto_miss'`.
- **Latent issues opt out.** "Not re-spotted ⇒ gone" is sound for a physical pothole but wrong for an *absence* like "missing streetlight" (a normal detector pass never re-spots it). The overflow rule is gated by `observation_types.auto_resolvable` — `false` for latent types, which are then resolved only by a human.

`confirmation_count` is the trust signal that makes review tractable: a heavily-confirmed issue is clearly real; the ambiguous middle is what a human looks at.

## 5. Data flow

### 5.1 Ingest — one sweep, one transaction

> The SQL below is **illustrative**. A production implementation resolves each confirmation to a single nearest match and handles 1:1 mapping explicitly.

```sql
BEGIN;

-- 1. record the sweep
INSERT INTO sweeps (coverage, assessed_types, started_at, ended_at, platform)
VALUES (:coverage, :assessed_types, :t0, :t1, :platform)
RETURNING id;                                  -- → :sweep_id

-- 2. insert the sweep's fresh observations (default confirmation_count=1, miss_count=0)
INSERT INTO observations (observation_type, location, observed_at, sweep_id,
                          recording_id, frame_ref, image_bbox,
                          detector_name, detector_version, detected_at, attributes,
                          valid_from)
VALUES ( /* ... */, :t0 ) /*, ... */;

-- 3. CONFIRM: each fresh observation supersedes the active same-type instance
--    within the type's merge radius, and inherits its confirmation_count + 1.
UPDATE observations old
   SET superseded_by_observation_id = fresh.id,
       valid_to = fresh.observed_at
  FROM observations fresh
  JOIN observation_types t ON t.slug = fresh.observation_type
 WHERE fresh.sweep_id = :sweep_id
   AND old.sweep_id  <> :sweep_id
   AND old.observation_type = fresh.observation_type
   AND old.superseded_by_observation_id IS NULL
   AND old.resolved_at IS NULL
   AND ST_DWithin(old.location, fresh.location, t.merge_radius_m);

UPDATE observations fresh
   SET confirmation_count = old.confirmation_count + 1
  FROM observations old
 WHERE old.superseded_by_observation_id = fresh.id;

-- 4. NEAR-MISS: still-active observations the sweep passed near (within tolerance)
--    and assessed the type of, but did not re-find → bump the triage signal only.
UPDATE observations a
   SET miss_count = a.miss_count + 1
 WHERE a.superseded_by_observation_id IS NULL
   AND a.resolved_at IS NULL
   AND a.sweep_id <> :sweep_id
   AND a.observation_type = ANY(:assessed_types)
   AND ST_DWithin(a.location, :coverage, :tolerance_m);

COMMIT;
-- Nothing is resolved here. Resolution happens in the review layer (§4.3).
```

### 5.2 Read patterns

```sql
-- MAP: the live set (optionally filtered by viewport / type)
SELECT * FROM current_observations
 WHERE ST_Intersects(location, :viewport_bbox);

-- OPTIMIZATION: same live set; spatially join external risk signals,
--               use confirmation_count as a (referenced) trust signal.
SELECT * FROM current_observations;

-- TIME TRAVEL: the city as it was known on date :t
SELECT * FROM observations
 WHERE valid_from <= :t AND (valid_to IS NULL OR valid_to > :t);

-- EVIDENCE: hand (recording_id, frame_ref, image_bbox) to the storage module.
```

### 5.3 Review layer (out of ingest)

```sql
-- human confirms a batch resolved
UPDATE observations
   SET resolved_at = now(), resolution_source = 'human', reviewed_by = :reviewer,
       valid_to = now()
 WHERE id = ANY(:ids);

-- overflow assist: auto-clear obvious-gone, non-latent observations
UPDATE observations a
   SET resolved_at = now(), resolution_source = 'auto_miss', valid_to = now()
  FROM observation_types t
 WHERE t.slug = a.observation_type
   AND t.auto_resolvable
   AND a.superseded_by_observation_id IS NULL
   AND a.resolved_at IS NULL
   AND a.miss_count >= :K;
```

## 6. Edge cases

- **Recurrence** (a resolved issue comes back): a later sweep finds it again; there is no *active* instance to supersede, so it enters as a fresh active observation. History shows the prior resolved chain.
- **Partial sweeps**: a sweep that covers only part of the city only confirms/resolves within its `coverage`; untouched streets are untouched.
- **A repaired issue**: the next covering sweep doesn't re-find it → `miss_count` climbs → resolved by human or `auto_miss`.
- **A perspective-only miss**: tolerant coverage + miss accumulation prevents a single bad angle from resolving a real issue.
- **Latent issues**: never `auto_miss`-resolved; reviewed by a human.

## 7. Decisions & rejected alternatives

| Decision | Why | Rejected alternative |
|---|---|---|
| Facts-only contract; enrich by reference | Keeps the shared contract stable and unopinionated; modules own their own derived data | Carrying confidence/severity/priority inline |
| `observation` / `sweep` naming | Reflects "fact recorded at a point in time"; pairs with re-observation | `issue` (vague, Jira/GitHub connotations), `finding`, `defect` (wrong for absences) |
| Confirmation = observation-vs-observation (type + proximity) | Avoids fuzzy persistent-identity tracking the team flagged as a pain | Maintaining stable cross-sweep issue identity |
| Resolution needs sweep coverage + assessed_types | "Not re-observed" is meaningless without knowing the sweep looked there, for those types | Driving resolution off the new observations alone |
| Tolerant coverage (`ST_DWithin`) | No two sweeps share a perspective; strict containment would never resolve | Strict `ST_Intersects` containment |
| `miss_count` is a triage/overflow signal, not a gate | A mechanical threshold is the wrong authority; confirmations + a human are | Auto-resolve at a fixed consecutive-miss count |
| Resolution is human-in-the-loop | A person confirms batches; signals make the queue tractable | Fully automatic resolution |
| `auto_resolvable` per type | Absence-type latent issues break the "not re-spotted ⇒ gone" heuristic | Applying the heuristic uniformly |
| Logical supersession, not delete | Immutable facts, free history + time-travel, "current" is a filter | Hard `DELETE` / overwrite |
| Type catalog table | A new type is a row, supporting the NL "review a new type" prompt | Hard-coded enum |

## 8. Testing considerations

- **Catalog**: seed `observation_types` incl. a latent type with `auto_resolvable = false`.
- **Confirmation**: a second sweep with a same-type detection inside `merge_radius_m` supersedes the prior; `confirmation_count` increments; the prior leaves `current_observations`.
- **No false confirm**: a same-type detection *outside* `merge_radius_m` does **not** supersede (two distinct instances).
- **Near-miss**: a covering sweep that assessed the type but didn't re-find bumps `miss_count` and resolves **nothing**.
- **Coverage scoping**: a sweep that did **not** cover a spot (or didn't assess the type) leaves those observations untouched.
- **Resolution**: human resolution sets the outcome fields and drops the row from `current_observations`; `auto_miss` clears non-latent high-`miss_count` rows; latent rows are never `auto_miss`-resolved.
- **Recurrence**: re-detection after resolution creates a new active observation.
- **Time-travel**: `valid_from/valid_to` query reconstructs the current set as of a past date.
- **Index usage**: `EXPLAIN` confirms `observations_current_gix` is used for viewport reads.

## 9. Open items / future

- **Coverage representation**: buffered GPS route vs. street-segment set — pick during the storage/capture module's design; this contract only needs a `geography` swath.
- **Per-type tuning**: `merge_radius_m` and the `auto_miss` threshold `K` may move per-type as real data arrives.
- **Confirmations as explicit event rows**: if an audit trail of every confirmation/miss is needed, add an append-only `observation_events` table; the counts on `observations` stay as the fast-path summary.
- **Review queue/UI**: lives in the application module; it reads the signals defined here and writes the resolution outcome fields.
