# Seed & Test Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the deployed Supabase data model (local stack) with a deterministic, reproducible dataset — one tenant, login users, ~130 CDMX observations across every lifecycle/priority state, geography, priority values, analysis enablement + pre-seeded runs, and ROIs — so the City Priority Map app (`apps/web`) can be built and tested against live data.

**Architecture:** Modular SQL fixtures under `supabase/seed/`, applied in filename order via `[db.seed].sql_paths` in `supabase/config.toml`, run by `supabase db reset` (migrations → seed). Pure SQL, fixed/deterministic UUIDs, idempotent, all final-state INSERTs (no UPDATEs — immutability triggers fire `BEFORE UPDATE` only). Finishes by advancing the data-version counter and rebuilding the cached geo-clip the read API depends on. A standalone verification script proves §4-contract coverage and the live-RLS visibility path.

**Tech Stack:** PostgreSQL 15 + PostGIS (Supabase local), Supabase CLI (`supabase db reset`), `psql` for assertions. No application code.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-20-seed-test-data-design.md`. **UI data contract:** `docs/superpowers/plans/2026-06-20-city-priority-map-application.md` §4. **As-built schema:** `supabase/SCHEMA.md` + `supabase/migrations/0001`–`0013`,`0101`–`0103`.
- **RLS is live (`0012`), scoped `to authenticated`.** `seed.sql` runs as `postgres` (bypasses RLS) — seeding is unobstructed; the dataset must still be *shaped* so reads as `authenticated` return the right rows.
- **No UPDATEs in the seed.** Immutability/append-only triggers (`0012`) fire `BEFORE UPDATE`/`DELETE` only. Insert superseded/resolved observations in final form (successor inserted before the predecessor that points at it).
- **Determinism:** fixed literal UUIDs for singletons (see ID map below); procedural UUIDs via `('00b50000-0000-4000-8000-'||lpad(to_hex(g),12,'0'))::uuid`. No `random()`. Time anchored to the constant `REF_TS = '2026-06-15 12:00:00+00'`.
- **Idempotent:** every insert uses `on conflict do nothing`.
- **Schema qualification:** each fixture starts with `set search_path = public, extensions;` and fully schema-qualifies tables (`vision.`, `geo.`, …). PostGIS `ST_*`/types resolve from `extensions`.
- **Single-active invariants:** exactly one active `priority_models`, one active `geo_editions`, one active `tenant_boundary_versions` per tenant (partial unique indexes — do not violate).
- **No secrets committed.** Dev users share one password; document it in the PR + `apps/web/.env.example` placeholders only.

### Fixed UUID map (used across tasks — keep identical everywhere)

```
tenant                          a0000000-0000-0000-0000-000000000001
geo_edition (active)            ed000000-0000-0000-0000-000000000001
geo_area AGEE 09 (CDMX)         9e000000-0000-0000-0000-000000000009
geo_area AGEM Cuauhtémoc 015    9e000000-0000-0000-0000-000000000015   (IN boundary)
geo_area AGEM Iztapalapa 007    9e000000-0000-0000-0000-000000000007   (IN)
geo_area AGEM Coyoacán 003      9e000000-0000-0000-0000-000000000003   (IN)
geo_area AGEM G. A. Madero 005  9e000000-0000-0000-0000-000000000005   (IN)
geo_area AGEM Á. Obregón 010    9e000000-0000-0000-0000-000000000010   (IN)
geo_area AGEM V. Carranza 017   9e000000-0000-0000-0000-000000000017   (IN)
geo_area AGEM Tlalpan 012       9e000000-0000-0000-0000-000000000012   (OUT of boundary)
tenant_boundary_version (active) b0000000-0000-0000-0000-000000000001
source truck_fleet              50000000-0000-0000-0000-000000000001
source adhoc_survey             50000000-0000-0000-0000-000000000002
type pothole                    70000000-0000-0000-0000-000000000001
type open_drain                 70000000-0000-0000-0000-000000000002
type broken_light               70000000-0000-0000-0000-000000000003
type missing_signage (latent)   70000000-0000-0000-0000-000000000004
type damaged_sidewalk           70000000-0000-0000-0000-000000000005
sweep A                         5e000000-0000-0000-0000-000000000001
sweep B                         5e000000-0000-0000-0000-000000000002
recording A1                    5ec00000-0000-0000-0000-000000000001
recording B1                    5ec00000-0000-0000-0000-000000000002
auth user author.a              c0000000-0000-0000-0000-00000000000a
auth user viewer.a              c0000000-0000-0000-0000-00000000000b
auth user nomember              c0000000-0000-0000-0000-00000000000c
oidc_subject author.a           05000000-0000-0000-0000-00000000000a
oidc_subject viewer.a           05000000-0000-0000-0000-00000000000b
oidc_subject nomember           05000000-0000-0000-0000-00000000000c
priority_model baseline/v1      b1000000-0000-0000-0000-000000000001
priority_batch                  ba000000-0000-0000-0000-000000000001
analysis_provider in_db         f0000000-0000-0000-0000-000000000001
def budget.route                de000000-0000-0000-0000-000000000001
def budget.cluster              de000000-0000-0000-0000-000000000002
def inspection.latent           de000000-0000-0000-0000-000000000003
def_version route v1            d1000000-0000-0000-0000-000000000001
def_version cluster v1          d1000000-0000-0000-0000-000000000002
def_version latent v1           d1000000-0000-0000-0000-000000000003
capability_snapshot route       5a000000-0000-0000-0000-000000000001
capability_snapshot cluster     5a000000-0000-0000-0000-000000000002
analysis_run route (succeeded)  1a000000-0000-0000-0000-000000000001
analysis_run cluster (succeeded)1a000000-0000-0000-0000-000000000002
analysis_run failed             1a000000-0000-0000-0000-000000000003
analysis_run queued             1a000000-0000-0000-0000-000000000004
roi_run                         40e00000-0000-0000-0000-000000000001
```

Dev password for all login users: **`vialia-dev-2026!`**

### Zone fixtures (used by geo areas + observation placement)

```
zone                 center lat   center lng   half-box°   in_boundary
cuauhtemoc           19.432       -99.133      0.025       yes
iztapalapa           19.357       -99.060      0.035       yes
coyoacan             19.345       -99.162      0.028       yes
gam                  19.484       -99.110      0.035       yes
alvaro_obregon       19.360       -99.200      0.030       yes
venustiano_carranza  19.430       -99.100      0.022       yes
tlalpan              19.290       -99.170      0.035       NO (clip test)
```
Each AGEM polygon = `ST_MakeEnvelope(clng-half, clat-half, clng+half, clat+half, 4326)`. Observation points are placed within `0.6*half` of a center, so spatial containment binds every point to exactly one AGEM box.

### Local prerequisites (run once before Task 1)

```bash
supabase start
# DB URL for assertions throughout this plan:
export DBURL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
```

---

## Task 1: Seeding harness

**Files:**
- Modify: `supabase/config.toml`
- Create: `supabase/seed/.gitkeep` (placeholder so the dir exists)
- Modify: `supabase/seed.sql` (retire the old one-liner — replaced by `seed/`)

**Interfaces:**
- Produces: a `supabase db reset` that applies `migrations/` then every `supabase/seed/*.sql` in filename order. Later tasks each add one file under `supabase/seed/`.

- [ ] **Step 1: Add the seed path config**

Add to `supabase/config.toml`:

```toml
[db.seed]
enabled = true
sql_paths = ["./seed/*.sql"]
```

- [ ] **Step 2: Retire the old seed.sql**

Replace the entire contents of `supabase/seed.sql` with:

```sql
-- Superseded by modular fixtures in supabase/seed/*.sql (wired via config.toml [db.seed].sql_paths).
-- Intentionally empty: db reset applies supabase/seed/ in filename order.
```

- [ ] **Step 3: Verify the CLI honors sql_paths**

Run: `supabase db reset`
Expected: completes without error; output includes "Seeding data ..." / applies files under `seed/`.
If the installed CLI ignores `[db.seed].sql_paths` (older version), use the **fallback**: delete the `[db.seed]` block and instead make `supabase/seed.sql` `\ir seed/00_catalog.sql` … `\ir seed/99_finalize.sql` in order, and create each fixture under `seed/` as planned. Record which path you took in the commit message.

- [ ] **Step 4: Commit**

```bash
git checkout -b seed/test-data
git add supabase/config.toml supabase/seed/.gitkeep supabase/seed.sql
git commit -m "chore(seed): wire supabase/seed/*.sql via config.toml [db.seed]"
```

---

## Task 2: Catalog & provenance (`00_catalog.sql`)

**Files:**
- Create: `supabase/seed/00_catalog.sql`

**Interfaces:**
- Produces: `vision.sources` (2), `vision.observation_types` (5, see ID map), per-type `observation_attribute_definitions` (`quantity` + `confidence`), `vision.sweeps` (2) + `recordings` (2) + `sweep_assessed_types`. Definition keys consumed later: `pothole→surface_area_m2`, `damaged_sidewalk→length_m`, others→`count`; every type also has `confidence`.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

-- Sources
insert into vision.sources (id, slug, name, status) values
  ('50000000-0000-0000-0000-000000000001','truck_fleet','Trash-truck fleet cam','active'),
  ('50000000-0000-0000-0000-000000000002','adhoc_survey','Ad-hoc survey','active')
on conflict do nothing;

-- Observation types (auto_resolvable=false on missing_signage => app is_latent)
insert into vision.observation_types
  (id, slug, label, category, description, merge_radius_m, auto_resolvable, auto_resolve_miss_threshold, status) values
  ('70000000-0000-0000-0000-000000000001','pothole','Bache','road_surface','Bache en superficie de rodamiento',10,true,4,'active'),
  ('70000000-0000-0000-0000-000000000002','open_drain','Coladera abierta','drainage','Coladera o registro sin tapa',12,true,4,'active'),
  ('70000000-0000-0000-0000-000000000003','broken_light','Luminaria dañada','lighting','Luminaria pública apagada o rota',15,true,5,'active'),
  ('70000000-0000-0000-0000-000000000004','missing_signage','Señalización faltante','signage','Señal de tránsito ausente (latente)',20,false,null,'active'),
  ('70000000-0000-0000-0000-000000000005','damaged_sidewalk','Banqueta dañada','pedestrian','Banqueta fracturada o levantada',10,true,4,'active')
on conflict do nothing;

-- Quantity attribute definitions (one per type) + a shared optional confidence per type
insert into vision.observation_attribute_definitions
  (id, observation_type_id, key, version, label, value_kind, unit, required, minimum_number, maximum_number, status) values
  ('7d000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','surface_area_m2',1,'Área (m²)','number','m2',true,0,500,'active'),
  ('7d000000-0000-0000-0000-000000000002','70000000-0000-0000-0000-000000000002','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000003','70000000-0000-0000-0000-000000000003','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000004','70000000-0000-0000-0000-000000000004','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000005','70000000-0000-0000-0000-000000000005','length_m',1,'Longitud (m)','number','m',true,0,300,'active'),
  -- confidence (optional) per type
  ('7dc00000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000002','70000000-0000-0000-0000-000000000002','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000003','70000000-0000-0000-0000-000000000003','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000004','70000000-0000-0000-0000-000000000004','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000005','70000000-0000-0000-0000-000000000005','confidence',1,'Confianza','number',null,false,0,1,'active')
on conflict do nothing;

-- Sweeps (coverage over CDMX bbox) + recordings + assessed types
insert into vision.sweeps (id, source_id, coverage, started_at, ended_at) values
  ('5e000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001',
     ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)::geography,
     '2026-06-10 08:00:00+00','2026-06-10 14:00:00+00'),
  ('5e000000-0000-0000-0000-000000000002','50000000-0000-0000-0000-000000000002',
     ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)::geography,
     '2026-06-14 08:00:00+00','2026-06-14 13:00:00+00')
on conflict do nothing;

insert into vision.recordings (id, sweep_id, storage_path, status, started_at, ended_at, duration_ms) values
  ('5ec00000-0000-0000-0000-000000000001','5e000000-0000-0000-0000-000000000001','sweeps/5e000000-0000-0000-0000-000000000001/5ec00000-0000-0000-0000-000000000001.mp4','ready','2026-06-10 08:00:00+00','2026-06-10 11:00:00+00',10800000),
  ('5ec00000-0000-0000-0000-000000000002','5e000000-0000-0000-0000-000000000002','sweeps/5e000000-0000-0000-0000-000000000002/5ec00000-0000-0000-0000-000000000002.mp4','ready','2026-06-14 08:00:00+00','2026-06-14 11:00:00+00',10800000)
on conflict do nothing;

insert into vision.sweep_assessed_types (sweep_id, observation_type_id)
select s.id, t.id from vision.sweeps s cross join vision.observation_types t
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from vision.observation_types), (select count(*) from vision.observation_attribute_definitions), (select count(*) from vision.sweep_assessed_types);"`
Expected: `5|10|10`

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/00_catalog.sql
git commit -m "feat(seed): vision catalog (sources, 5 types, attrs, sweeps, recordings)"
```

---

## Task 3: Geography & tenant boundary (`10_geo.sql`)

**Files:**
- Create: `supabase/seed/10_geo.sql`

**Interfaces:**
- Consumes: nothing (independent).
- Produces: active `geo.geo_editions` (`ed…01`), 1 AGEE + 7 AGEM `geo_areas` (boxes per zone fixtures), the `platform.tenants` row (`a0…01`), and an active `geo.tenant_boundary_versions` (`b0…01`) whose `materialized_geometry` is the union of the **6 in-boundary** AGEMs, with `tenant_boundary_areas` rows. Tlalpan (`9e…12`) exists but is **excluded** from the boundary.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

insert into platform.tenants (id, name, status) values
  ('a0000000-0000-0000-0000-000000000001','Vialia CDMX','active')
on conflict do nothing;

insert into geo.geo_editions (id, source_name, source_release, effective_date, status, imported_at) values
  ('ed000000-0000-0000-0000-000000000001','INEGI MGN (synthetic fixture)','2020','2020-03-15','active','2026-06-01 00:00:00+00')
on conflict do nothing;

-- AGEE (state of CDMX)
insert into geo.geo_areas (id, edition_id, level, source_cvegeo, cve_ent, name, geometry) values
  ('9e000000-0000-0000-0000-000000000009','ed000000-0000-0000-0000-000000000001','AGEE','09','09','Ciudad de México',
     ST_Multi(ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)))
on conflict do nothing;

-- AGEM alcaldías (boxes around zone centers). parent = AGEE.
insert into geo.geo_areas (id, edition_id, level, source_cvegeo, cve_ent, cve_mun, name, parent_area_id, geometry) values
  ('9e000000-0000-0000-0000-000000000015','ed000000-0000-0000-0000-000000000001','AGEM','09015','09','015','Cuauhtémoc','9e000000-0000-0000-0000-000000000009',          ST_Multi(ST_MakeEnvelope(-99.158,19.407,-99.108,19.457,4326))),
  ('9e000000-0000-0000-0000-000000000007','ed000000-0000-0000-0000-000000000001','AGEM','09007','09','007','Iztapalapa','9e000000-0000-0000-0000-000000000009',          ST_Multi(ST_MakeEnvelope(-99.095,19.322,-99.025,19.392,4326))),
  ('9e000000-0000-0000-0000-000000000003','ed000000-0000-0000-0000-000000000001','AGEM','09003','09','003','Coyoacán','9e000000-0000-0000-0000-000000000009',            ST_Multi(ST_MakeEnvelope(-99.190,19.317,-99.134,19.373,4326))),
  ('9e000000-0000-0000-0000-000000000005','ed000000-0000-0000-0000-000000000001','AGEM','09005','09','005','Gustavo A. Madero','9e000000-0000-0000-0000-000000000009',   ST_Multi(ST_MakeEnvelope(-99.145,19.449,-99.075,19.519,4326))),
  ('9e000000-0000-0000-0000-000000000010','ed000000-0000-0000-0000-000000000001','AGEM','09010','09','010','Álvaro Obregón','9e000000-0000-0000-0000-000000000009',      ST_Multi(ST_MakeEnvelope(-99.230,19.330,-99.170,19.390,4326))),
  ('9e000000-0000-0000-0000-000000000017','ed000000-0000-0000-0000-000000000001','AGEM','09017','09','017','Venustiano Carranza','9e000000-0000-0000-0000-000000000009', ST_Multi(ST_MakeEnvelope(-99.122,19.408,-99.078,19.452,4326))),
  ('9e000000-0000-0000-0000-000000000012','ed000000-0000-0000-0000-000000000001','AGEM','09012','09','012','Tlalpan','9e000000-0000-0000-0000-000000000009',            ST_Multi(ST_MakeEnvelope(-99.205,19.255,-99.135,19.325,4326)))
on conflict do nothing;

-- Active boundary = union of the 6 IN-boundary AGEMs (excludes Tlalpan 012)
insert into geo.tenant_boundary_versions
  (id, tenant_id, edition_id, version_number, status, materialized_geometry, geometry_checksum, created_at, activated_at)
select
  'b0000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',1,'active',
  ST_Multi(ST_Union(a.geometry)), 'seed-boundary-v1','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'
from geo.geo_areas a
where a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
  and a.id <> '9e000000-0000-0000-0000-000000000012'
on conflict do nothing;

insert into geo.tenant_boundary_areas (boundary_version_id, geo_area_id)
select 'b0000000-0000-0000-0000-000000000001', a.id
from geo.geo_areas a
where a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
  and a.id <> '9e000000-0000-0000-0000-000000000012'
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from geo.geo_areas where level='AGEM'), (select count(*) from geo.tenant_boundary_areas), (select status from geo.tenant_boundary_versions where tenant_id='a0000000-0000-0000-0000-000000000001');"`
Expected: `7|6|active`

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/10_geo.sql
git commit -m "feat(seed): geo edition, CDMX alcaldía areas, tenant + active boundary"
```

---

## Task 4: Auth users, subjects, memberships (`20_auth.sql`)

**Files:**
- Create: `supabase/seed/20_auth.sql`

**Interfaces:**
- Consumes: tenant `a0…01` (Task 3).
- Produces: 3 `auth.users` + `auth.identities` (email/password `vialia-dev-2026!`), 3 `platform.oidc_subjects`, and memberships: `author.a`→`analysis_author`, `viewer.a`→`viewer`, `nomember`→ none. Subject ids `05…0a/0b/0c` are referenced later (analysis runs, reviewed_by).

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

-- auth.users (email confirmed; bcrypt password). encrypted_password uses pgcrypto in extensions.
insert into auth.users
  (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
   raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
   confirmation_token, recovery_token, email_change_token_new, email_change)
values
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000a','authenticated','authenticated','author.a@vialia.test',
     extensions.crypt('vialia-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"Author A"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','',''),
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000b','authenticated','authenticated','viewer.a@vialia.test',
     extensions.crypt('vialia-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"Viewer A"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','',''),
  ('00000000-0000-0000-0000-000000000000','c0000000-0000-0000-0000-00000000000c','authenticated','authenticated','nomember@vialia.test',
     extensions.crypt('vialia-dev-2026!', extensions.gen_salt('bf')),'2026-06-01 00:00:00+00',
     '{"provider":"email","providers":["email"]}','{"display_name":"No Member"}','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','','','','')
on conflict (id) do nothing;

-- auth.identities (email provider; provider_id = user id for email logins)
insert into auth.identities
  (id, provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
values
  ('1de0000a-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a',
     '{"sub":"c0000000-0000-0000-0000-00000000000a","email":"author.a@vialia.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'),
  ('1de0000b-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b',
     '{"sub":"c0000000-0000-0000-0000-00000000000b","email":"viewer.a@vialia.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'),
  ('1de0000c-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c',
     '{"sub":"c0000000-0000-0000-0000-00000000000c","email":"nomember@vialia.test","email_verified":true}','email','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00')
on conflict (provider_id, provider) do nothing;

-- oidc_subjects bridge (issuer null => Supabase is the issuer)
insert into platform.oidc_subjects (id, user_id, display_name, status) values
  ('05000000-0000-0000-0000-00000000000a','c0000000-0000-0000-0000-00000000000a','Author A','active'),
  ('05000000-0000-0000-0000-00000000000b','c0000000-0000-0000-0000-00000000000b','Viewer A','active'),
  ('05000000-0000-0000-0000-00000000000c','c0000000-0000-0000-0000-00000000000c','No Member','active')
on conflict do nothing;

-- memberships (nomember intentionally has none)
insert into platform.tenant_memberships (tenant_id, subject_id, role) values
  ('a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','analysis_author'),
  ('a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000b','viewer')
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert (including a real password check)**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from auth.users where email like '%@vialia.test'), (select count(*) from auth.identities where provider='email' and user_id::text like 'c0000000%'), (select count(*) from platform.tenant_memberships), (select (encrypted_password = extensions.crypt('vialia-dev-2026!', encrypted_password)) from auth.users where id='c0000000-0000-0000-0000-00000000000a');"`
Expected: `3|3|2|t`

> If the `auth.identities` insert errors on a missing/extra column, your local GoTrue schema differs — inspect with `psql "$DBURL" -c "\d auth.identities"` and adjust the column list, keeping `provider='email'` and `provider_id=<user id>`. Keep it idempotent.

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/20_auth.sql
git commit -m "feat(seed): dev auth users + oidc subjects + tenant memberships"
```

---

## Task 5: Observations, facts, geo bindings (`30_observations.sql`)

**Files:**
- Create: `supabase/seed/30_observations.sql`

**Interfaces:**
- Consumes: types/sweeps/recordings (Task 2), geo areas/edition (Task 3), subject `05…0a` for `reviewed_by` (Task 4).
- Produces: `N_BULK` (default **120**) procedural observations + 4 superseded pairs (8 rows) + 4 resolved rows, each with one quantity `observation_attribute_value` + a `confidence` value, and an `observation_geo_bindings` row per observation. Pending vs scored is decided later (Task 6) by a deterministic md5 rule on `observation.id`; this task does not write priority.
- Procedural UUID: `('00b50000-0000-4000-8000-'||lpad(to_hex(g),12,'0'))::uuid`. Special rows use `g` in `9001..9999`.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

-- ---- Bulk procedural observations (current) ----
with zones (zi, zone, clat, clng, half, in_b) as (values
  (0,'cuauhtemoc',19.432,-99.133,0.025,true),
  (1,'iztapalapa',19.357,-99.060,0.035,true),
  (2,'coyoacan',19.345,-99.162,0.028,true),
  (3,'gam',19.484,-99.110,0.035,true),
  (4,'alvaro_obregon',19.360,-99.200,0.030,true),
  (5,'venustiano_carranza',19.430,-99.100,0.022,true),
  (6,'tlalpan',19.290,-99.170,0.035,false)  -- OUT of boundary
),
g as (select generate_series(1,120) as gi),
placed as (
  select
    gi,
    -- ~80% in 6 in-boundary zones; ~every 12th goes to tlalpan (out of boundary)
    case when gi % 12 = 0 then 6 else gi % 6 end as zi
  from g
),
pts as (
  select
    p.gi,
    z.zone, z.in_b,
    -- golden-angle spiral inside 0.6*half of the center => guaranteed inside the AGEM box
    z.clat + (0.6*z.half) * sqrt(((p.gi*7) % 23)::numeric/23.0) * cos(p.gi*2.399963) as lat,
    z.clng + (0.6*z.half) * sqrt(((p.gi*7) % 23)::numeric/23.0) * sin(p.gi*2.399963) as lng,
    1 + (p.gi % 5) as type_ix  -- 1..5
  from placed p join zones z on z.zi = p.zi
)
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count, valid_from, created_at)
select
  ('00b50000-0000-4000-8000-'||lpad(to_hex(gi),12,'0'))::uuid,
  ('70000000-0000-0000-0000-00000000000'||type_ix)::uuid,
  ST_SetSRID(ST_MakePoint(lng,lat),4326)::geography,
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  '5e000000-0000-0000-0000-000000000002',
  '5ec00000-0000-0000-0000-000000000002',
  (gi*937) % 9000000,
  'f'||(gi*13),
  jsonb_build_object('x',0.30,'y',0.30,'w',0.18,'h',0.18),
  'yolo-infra','v1.3',
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  1 + (gi % 4), (gi % 7),
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  now()
from pts
on conflict do nothing;

-- ---- Superseded pairs (successor inserted first, then predecessor pointing at it) ----
-- successors: g 9101..9104 (current); predecessors: g 9001..9004 (superseded)
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count, valid_from, created_at)
values
  ('00b50000-0000-4000-8000-000000009101','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.130,19.430),4326)::geography,'2026-06-14 10:00:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',101000,'f9101',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:00:00+00',2,0,'2026-06-14 10:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009102','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.060,19.357),4326)::geography,'2026-06-14 10:05:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',102000,'f9102',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:05:00+00',2,0,'2026-06-14 10:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009103','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.162,19.345),4326)::geography,'2026-06-14 10:10:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',103000,'f9103',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:10:00+00',2,0,'2026-06-14 10:10:00+00',now()),
  ('00b50000-0000-4000-8000-000000009104','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.110,19.484),4326)::geography,'2026-06-14 10:15:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',104000,'f9104',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:15:00+00',2,0,'2026-06-14 10:15:00+00',now())
on conflict do nothing;

insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count,
   superseded_by_observation_id, valid_from, valid_to, created_at)
values
  ('00b50000-0000-4000-8000-000000009001','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.1301,19.4301),4326)::geography,'2026-06-08 09:00:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9001,'f9001',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:00:00+00',1,1,'00b50000-0000-4000-8000-000000009101','2026-06-08 09:00:00+00','2026-06-14 10:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009002','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.0601,19.3571),4326)::geography,'2026-06-08 09:05:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9002,'f9002',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:05:00+00',1,1,'00b50000-0000-4000-8000-000000009102','2026-06-08 09:05:00+00','2026-06-14 10:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009003','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.1621,19.3451),4326)::geography,'2026-06-08 09:10:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9003,'f9003',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:10:00+00',1,2,'00b50000-0000-4000-8000-000000009103','2026-06-08 09:10:00+00','2026-06-14 10:10:00+00',now()),
  ('00b50000-0000-4000-8000-000000009004','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.1101,19.4841),4326)::geography,'2026-06-08 09:15:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9004,'f9004',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:15:00+00',1,1,'00b50000-0000-4000-8000-000000009104','2026-06-08 09:15:00+00','2026-06-14 10:15:00+00',now())
on conflict do nothing;

-- ---- Resolved observations (2 human, 2 auto_miss) ----
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count,
   resolved_at, resolution_source, reviewed_by_subject_id, valid_from, valid_to, created_at)
values
  ('00b50000-0000-4000-8000-000000009201','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.140,19.420),4326)::geography,'2026-06-02 09:00:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9201,'f9201',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-02 09:00:00+00',3,0,'2026-06-12 16:00:00+00','human','05000000-0000-0000-0000-00000000000a','2026-06-02 09:00:00+00','2026-06-12 16:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009202','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.165,19.350),4326)::geography,'2026-06-02 09:05:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9202,'f9202',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-02 09:05:00+00',2,0,'2026-06-12 16:05:00+00','human','05000000-0000-0000-0000-00000000000a','2026-06-02 09:05:00+00','2026-06-12 16:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009203','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.115,19.480),4326)::geography,'2026-06-01 09:10:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9203,'f9203',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-01 09:10:00+00',1,5,'2026-06-13 03:00:00+00','auto_miss',null,'2026-06-01 09:10:00+00','2026-06-13 03:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009204','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.075,19.360),4326)::geography,'2026-06-01 09:15:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9204,'f9204',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-01 09:15:00+00',1,4,'2026-06-13 03:05:00+00','auto_miss',null,'2026-06-01 09:15:00+00','2026-06-13 03:05:00+00',now())
on conflict do nothing;

-- ---- One quantity attribute value per observation (matches its type's quantity def) ----
insert into vision.observation_attribute_values (observation_id, definition_id, number_value)
select o.id,
       d.id,
       case d.key when 'surface_area_m2' then 1 + (get_byte(decode(md5(o.id::text),'hex'),2) % 40)
                  when 'length_m'        then 2 + (get_byte(decode(md5(o.id::text),'hex'),2) % 60)
                  else 1 + (get_byte(decode(md5(o.id::text),'hex'),2) % 8) end
from vision.observations o
join vision.observation_attribute_definitions d
  on d.observation_type_id = o.observation_type_id and d.key in ('surface_area_m2','length_m','count')
on conflict do nothing;

-- ---- Confidence value per observation ----
insert into vision.observation_attribute_values (observation_id, definition_id, number_value)
select o.id, d.id,
       round((0.55 + (get_byte(decode(md5(o.id::text),'hex'),3) % 45)::numeric/100.0)::numeric, 2)
from vision.observations o
join vision.observation_attribute_definitions d
  on d.observation_type_id = o.observation_type_id and d.key = 'confidence'
on conflict do nothing;

-- ---- Geo bindings (spatial containment binds each point to its AGEM box + the AGEE) ----
insert into geo.observation_geo_bindings (observation_id, edition_id, agee_area_id, agem_area_id, bound_at)
select o.id, 'ed000000-0000-0000-0000-000000000001','9e000000-0000-0000-0000-000000000009', a.id, now()
from vision.observations o
join geo.geo_areas a
  on a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
 and ST_Contains(a.geometry, o.location::geometry)
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert state coverage + binding completeness**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from vision.observations), (select count(*) from vision.observations where superseded_by_observation_id is not null), (select count(*) from vision.observations where resolved_at is not null), (select count(*) from vision.observations o where not exists (select 1 from geo.observation_geo_bindings b where b.observation_id=o.id)), (select count(*) from vision.observations o join geo.geo_areas a on a.id='9e000000-0000-0000-0000-000000000012' and ST_Contains(a.geometry,o.location::geometry));"`
Expected: `132|4|4|0|<nonzero>` — total 132 (120 bulk + 8 supersede + 4 resolved); 4 superseded; 4 resolved; **0 unbound**; the last value > 0 confirms some points fell in Tlalpan (out-of-boundary clip test). If the unbound count is not 0, a generated point fell outside all boxes — widen the relevant box or reduce the `0.6*half` spiral radius.

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/30_observations.sql
git commit -m "feat(seed): ~132 CDMX observations (scored/pending/superseded/resolved) + facts + geo bindings"
```

---

## Task 6: Priority model, batch, values (`40_priority.sql`)

**Files:**
- Create: `supabase/seed/40_priority.sql`

**Interfaces:**
- Consumes: observations (Task 5).
- Produces: 1 active `priority.priority_models` (`b1…01`), 1 completed `priority_batches` (`ba…01`), a `computed` `priority_values` row + `current_priority_values` pointer for every **current, non-pending** observation, plus `inherited` values on the 4 supersede successors. **Pending rule:** an observation is pending (no current value) when `get_byte(md5(id),0) % 9 = 0`. Predecessors (superseded) and resolved rows get no current value.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

insert into priority.priority_models (id, name, version, status) values
  ('b1000000-0000-0000-0000-000000000001','baseline','v1','active')
on conflict do nothing;

insert into priority.priority_batches (id, model_id, trigger_sweep_id, reason, status, created_at, started_at, completed_at) values
  ('ba000000-0000-0000-0000-000000000001','b1000000-0000-0000-0000-000000000001','5e000000-0000-0000-0000-000000000002','new_sweep','completed','2026-06-14 13:30:00+00','2026-06-14 13:31:00+00','2026-06-14 13:40:00+00')
on conflict do nothing;

-- Computed values for current, non-pending observations (deterministic weight 1..99).
-- "current" = superseded_by is null AND resolved_at is null. "pending" excluded.
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, computed_by_batch_id, created_at)
select
  ('00f10000-0000-4000-8000-'||substr(replace(o.id::text,'-',''),21,12))::uuid,
  o.id, 'b1000000-0000-0000-0000-000000000001',
  1 + (get_byte(decode(md5(o.id::text),'hex'),1) % 99),
  'computed','ba000000-0000-0000-0000-000000000001','2026-06-14 13:40:00+00'
from vision.observations o
where o.superseded_by_observation_id is null and o.resolved_at is null
  and (get_byte(decode(md5(o.id::text),'hex'),0) % 9) <> 0   -- not pending
  and o.id not in ('00b50000-0000-4000-8000-000000009101','00b50000-0000-4000-8000-000000009102',
                   '00b50000-0000-4000-8000-000000009103','00b50000-0000-4000-8000-000000009104') -- successors get inherited below
on conflict do nothing;

-- Predecessor computed values (so successors have something to inherit) — predecessors are not current.
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, computed_by_batch_id, created_at) values
  ('00f10000-0000-4000-8000-000000009001','00b50000-0000-4000-8000-000000009001','b1000000-0000-0000-0000-000000000001',82,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009002','00b50000-0000-4000-8000-000000009002','b1000000-0000-0000-0000-000000000001',64,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009003','00b50000-0000-4000-8000-000000009003','b1000000-0000-0000-0000-000000000001',77,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009004','00b50000-0000-4000-8000-000000009004','b1000000-0000-0000-0000-000000000001',55,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00')
on conflict do nothing;

-- Inherited values for the 4 successors (point at predecessor's value, same weight).
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, inherited_from_value_id, created_at) values
  ('00f10000-0000-4000-8000-00000000a101','00b50000-0000-4000-8000-000000009101','b1000000-0000-0000-0000-000000000001',82,'inherited','00f10000-0000-4000-8000-000000009001','2026-06-14 10:00:00+00'),
  ('00f10000-0000-4000-8000-00000000a102','00b50000-0000-4000-8000-000000009102','b1000000-0000-0000-0000-000000000001',64,'inherited','00f10000-0000-4000-8000-000000009002','2026-06-14 10:05:00+00'),
  ('00f10000-0000-4000-8000-00000000a103','00b50000-0000-4000-8000-000000009103','b1000000-0000-0000-0000-000000000001',77,'inherited','00f10000-0000-4000-8000-000000009003','2026-06-14 10:10:00+00'),
  ('00f10000-0000-4000-8000-00000000a104','00b50000-0000-4000-8000-000000009104','b1000000-0000-0000-0000-000000000001',55,'inherited','00f10000-0000-4000-8000-000000009004','2026-06-14 10:15:00+00')
on conflict do nothing;

-- Current pointers: latest value per (observation, model). Predecessors/resolved/pending excluded.
insert into priority.current_priority_values (observation_id, model_id, priority_value_id, updated_at)
select pv.observation_id, pv.model_id, pv.id, '2026-06-14 13:40:00+00'
from priority.priority_values pv
join vision.observations o on o.id = pv.observation_id
where o.superseded_by_observation_id is null and o.resolved_at is null
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert (scored vs pending split)**

Run: `supabase db reset && psql "$DBURL" -At -c "with cur as (select id from vision.observations where superseded_by_observation_id is null and resolved_at is null) select (select count(*) from cur), (select count(*) from cur c join priority.current_priority_values v on v.observation_id=c.id), (select count(*) from cur c where not exists (select 1 from priority.current_priority_values v where v.observation_id=c.id)), (select count(*) from priority.priority_values where value_state='inherited');"`
Expected: `<C>|<scored>|<pending>|4` where `C = scored + pending`, `pending` is between 5 and 25 (deterministic ~1/9 of current), and scored ≥ 90. (Exact numbers are reproducible across runs.)

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/40_priority.sql
git commit -m "feat(seed): priority model/batch + computed/inherited values + current pointers"
```

---

## Task 7: Analysis enablement + pre-seeded runs (`50_analysis.sql`)

**Files:**
- Create: `supabase/seed/50_analysis.sql`

**Interfaces:**
- Consumes: tenant/boundary/edition (Task 3), subject `05…0a` (Task 4), observations (Task 5), priority values (Task 6).
- Produces: 1 `analysis_providers`, 3 `analysis_definitions` (`budget.route`,`budget.cluster`,`inspection.latent`) + active `analysis_definition_versions` + 2 `provider_capability_snapshots`; and 4 `analysis_runs` (succeeded route, succeeded cluster, failed, queued). The succeeded route persists frozen inputs + attempt + result + `result_metrics` + a `map_features`(line)/`sequence_items`/`artifact_observation_refs` artifact; the succeeded cluster persists a polygon `map_features` + member refs + metrics. Result payload shape matches the app's `app_run_analysis` return contract.

- [ ] **Step 1: Write the fixture (definitions + enablement)**

```sql
set search_path = public, extensions;

insert into analysis.analysis_providers (id, slug, name, status, config_ref) values
  ('f0000000-0000-0000-0000-000000000001','in_db_executor','In-DB executor (seed stand-in)','enabled','seed')
on conflict do nothing;

insert into analysis.analysis_definitions (id, kind, label) values
  ('de000000-0000-0000-0000-000000000001','budget.route','Ruta óptima de servicio'),
  ('de000000-0000-0000-0000-000000000002','budget.cluster','Clúster de mayor impacto'),
  ('de000000-0000-0000-0000-000000000003','inspection.latent','Escaneo de inspección (latente)')
on conflict do nothing;

insert into analysis.analysis_definition_versions
  (id, definition_id, provider_id, interface_version, request_schema, result_schema, artifact_kinds, ui_descriptor, status) values
  ('d1000000-0000-0000-0000-000000000001','de000000-0000-0000-0000-000000000001','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features","ordered_sequence"]',
     '{"currency":"MXN","cost_basis":[{"slug":"pothole","unit":"m2","default_unit_cost":28000},{"slug":"open_drain","unit":"item","default_unit_cost":9000},{"slug":"broken_light","unit":"item","default_unit_cost":12000},{"slug":"missing_signage","unit":"item","default_unit_cost":4000},{"slug":"damaged_sidewalk","unit":"m","default_unit_cost":3500}]}','active'),
  ('d1000000-0000-0000-0000-000000000002','de000000-0000-0000-0000-000000000002','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features"]','{"currency":"MXN"}','active'),
  ('d1000000-0000-0000-0000-000000000003','de000000-0000-0000-0000-000000000003','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features"]','{"currency":"MXN"}','active')
on conflict do nothing;

insert into analysis.provider_capability_snapshots (id, definition_version_id, descriptor, config_version) values
  ('5a000000-0000-0000-0000-000000000001','d1000000-0000-0000-0000-000000000001','{"types":["pothole","open_drain","broken_light","missing_signage","damaged_sidewalk"],"currency":"MXN"}','cfg-v1'),
  ('5a000000-0000-0000-0000-000000000002','d1000000-0000-0000-0000-000000000002','{"types":["pothole","open_drain","broken_light","missing_signage","damaged_sidewalk"],"currency":"MXN"}','cfg-v1')
on conflict do nothing;
```

- [ ] **Step 2: Append the 4 runs to the same file**

Append to `supabase/seed/50_analysis.sql`:

```sql
-- ---- Runs ----
insert into analysis.analysis_runs
  (id, idempotency_key, tenant_id, requested_by_subject_id, definition_version_id, capability_snapshot_id,
   boundary_version_id, edition_id, budget_amount, budget_currency, status, created_at, started_at, finished_at) values
  ('1a000000-0000-0000-0000-000000000001','seed-route-1','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',3000000.00,'MXN','succeeded','2026-06-15 09:00:00+00','2026-06-15 09:00:05+00','2026-06-15 09:00:20+00'),
  ('1a000000-0000-0000-0000-000000000002','seed-cluster-1','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000002','5a000000-0000-0000-0000-000000000002','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',5000000.00,'MXN','succeeded','2026-06-15 09:10:00+00','2026-06-15 09:10:05+00','2026-06-15 09:10:18+00'),
  ('1a000000-0000-0000-0000-000000000003','seed-route-fail','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',1000000.00,'MXN','failed','2026-06-15 09:20:00+00','2026-06-15 09:20:05+00','2026-06-15 09:20:09+00'),
  ('1a000000-0000-0000-0000-000000000004','seed-route-queued','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',2000000.00,'MXN','queued','2026-06-15 09:30:00+00',null,null)
on conflict do nothing;

-- Frozen inputs for the succeeded route + cluster: pick 12 top-weight current scored observations.
-- Insert into run_observations for BOTH runs, then attributes/priority/exclusions.
with picked as (
  select o.id as obs_id, o.observation_type_id, o.location, o.observed_at, o.recording_id, o.frame_ref,
         v.weight,
         row_number() over (order by v.weight desc, o.id) as rn
  from vision.observations o
  join priority.current_priority_values cpv on cpv.observation_id=o.id
  join priority.priority_values v on v.id=cpv.priority_value_id
  where o.superseded_by_observation_id is null and o.resolved_at is null
  order by v.weight desc, o.id
  limit 12
)
insert into analysis.run_observations (run_id, observation_id, observation_type_id, location, observed_at, recording_id, frame_ref, lifecycle_version)
select r.run_id, p.obs_id, p.observation_type_id, p.location, p.observed_at, p.recording_id, p.frame_ref, 1
from picked p cross join (values ('1a000000-0000-0000-0000-000000000001'::uuid),('1a000000-0000-0000-0000-000000000002'::uuid)) r(run_id)
on conflict do nothing;

insert into analysis.run_priority_values (run_id, observation_id, weight, model_name, model_version, value_state)
select ro.run_id, ro.observation_id, v.weight, 'baseline','v1', v.value_state
from analysis.run_observations ro
join priority.current_priority_values cpv on cpv.observation_id=ro.observation_id
join priority.priority_values v on v.id=cpv.priority_value_id
where ro.run_id in ('1a000000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000002')
on conflict do nothing;

insert into analysis.run_observation_attributes (run_id, observation_id, definition_key, value_kind, number_value, unit)
select ro.run_id, ro.observation_id, d.key, 'number', av.number_value, d.unit
from analysis.run_observations ro
join vision.observation_attribute_values av on av.observation_id=ro.observation_id
join vision.observation_attribute_definitions d on d.id=av.definition_id and d.key in ('surface_area_m2','length_m','count')
where ro.run_id in ('1a000000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000002')
on conflict do nothing;

-- Exclusions: record the pending (unscored) current observations for the route run.
insert into analysis.run_observation_exclusions (run_id, observation_id, reason)
select '1a000000-0000-0000-0000-000000000001', o.id, 'unscored'
from vision.observations o
where o.superseded_by_observation_id is null and o.resolved_at is null
  and not exists (select 1 from priority.current_priority_values v where v.observation_id=o.id)
limit 10
on conflict do nothing;

-- Attempts (succeeded for route+cluster, failed for the failed run)
insert into analysis.analysis_attempts (id, run_id, attempt_number, provider_request_id, status, started_at, finished_at, failure_code, failure_details) values
  ('a77e0000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000001',1,'req-route-1','succeeded','2026-06-15 09:00:05+00','2026-06-15 09:00:20+00',null,'{}'),
  ('a77e0000-0000-0000-0000-000000000002','1a000000-0000-0000-0000-000000000002',1,'req-cluster-1','succeeded','2026-06-15 09:10:05+00','2026-06-15 09:10:18+00',null,'{}'),
  ('a77e0000-0000-0000-0000-000000000003','1a000000-0000-0000-0000-000000000003',1,'req-route-fail','failed','2026-06-15 09:20:05+00','2026-06-15 09:20:09+00','budget_too_low','{"message":"no eligible observations under budget"}')
on conflict do nothing;

-- Results (route + cluster). payload matches app_run_analysis return shape.
insert into analysis.analysis_results (id, run_id, accepted_attempt_id, provider_version, config_version, result_schema_version, payload) values
  ('5e5a0000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000001','a77e0000-0000-0000-0000-000000000001','v1','cfg-v1','1',
    jsonb_build_object('run_id','1a000000-0000-0000-0000-000000000001','kind','route','budget',3000000,
      'stats', jsonb_build_array(
        jsonb_build_object('key','spent','label','Gasto','value',2840000),
        jsonb_build_object('key','count','label','Atendidos','value',9),
        jsonb_build_object('key','riskRed','label','Riesgo reducido','value',62),
        jsonb_build_object('key','distKm','label','Distancia','value',7.4)),
      'items', '[]'::jsonb)),
  ('5e5a0000-0000-0000-0000-000000000002','1a000000-0000-0000-0000-000000000002','a77e0000-0000-0000-0000-000000000002','v1','cfg-v1','1',
    jsonb_build_object('run_id','1a000000-0000-0000-0000-000000000002','kind','cluster','budget',5000000,
      'stats', jsonb_build_array(
        jsonb_build_object('key','spent','label','Gasto','value',4720000),
        jsonb_build_object('key','count','label','Atendidos','value',12),
        jsonb_build_object('key','riskRed','label','Riesgo reducido','value',71)),
      'items','[]'::jsonb))
on conflict do nothing;

insert into analysis.result_metrics (id, result_id, key, label, unit, number_value) values
  ('5e3a0000-0000-0000-0000-000000000001','5e5a0000-0000-0000-0000-000000000001','spent','Gasto','MXN',2840000),
  ('5e3a0000-0000-0000-0000-000000000002','5e5a0000-0000-0000-0000-000000000001','count','Atendidos','item',9),
  ('5e3a0000-0000-0000-0000-000000000003','5e5a0000-0000-0000-0000-000000000001','distKm','Distancia','km',7.4),
  ('5e3a0000-0000-0000-0000-000000000004','5e5a0000-0000-0000-0000-000000000002','spent','Gasto','MXN',4720000),
  ('5e3a0000-0000-0000-0000-000000000005','5e5a0000-0000-0000-0000-000000000002','count','Atendidos','item',12)
on conflict do nothing;

-- Route artifact: line through the 9 cheapest-ordered picks + ordered stops.
insert into analysis.artifacts (id, result_id, kind, schema_version, display_order, title, payload) values
  ('a47a0000-0000-0000-0000-000000000001','5e5a0000-0000-0000-0000-000000000001','map_features',1,0,'Ruta','{}'),
  ('a47a0000-0000-0000-0000-000000000002','5e5a0000-0000-0000-0000-000000000001','ordered_sequence',1,1,'Paradas','{}'),
  ('a47a0000-0000-0000-0000-000000000003','5e5a0000-0000-0000-0000-000000000002','map_features',1,0,'Clúster','{}')
on conflict do nothing;

-- Route line geometry (LineString through the route run's frozen observations, weight desc).
insert into analysis.map_features (id, artifact_id, geometry, feature_key, properties)
select 'a47f0000-0000-0000-0000-000000000001','a47a0000-0000-0000-0000-000000000001',
       ST_SetSRID(ST_MakeLine(g.geom order by g.weight desc), 4326),'route-line','{"kind":"route"}'
from (
  select ro.location::geometry as geom, v.weight
  from analysis.run_observations ro
  join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
  where ro.run_id='1a000000-0000-0000-0000-000000000001'
) g
on conflict do nothing;

-- Cluster polygon = convex hull of the cluster run's frozen observations.
insert into analysis.map_features (id, artifact_id, geometry, feature_key, properties)
select 'a47f0000-0000-0000-0000-000000000002','a47a0000-0000-0000-0000-000000000003',
       ST_SetSRID(ST_ConvexHull(ST_Collect(ro.location::geometry)),4326),'cluster-poly','{"kind":"cluster"}'
from analysis.run_observations ro
where ro.run_id='1a000000-0000-0000-0000-000000000002'
on conflict do nothing;

-- Ordered stops (sequence_items) + artifact_observation_refs (role 'stop') for the route.
insert into analysis.sequence_items (id, artifact_id, position, run_id, observation_id, label)
select ('a4510000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by v.weight desc)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000002',
       row_number() over (order by v.weight desc),
       ro.run_id, ro.observation_id, 'Parada'
from analysis.run_observations ro
join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
where ro.run_id='1a000000-0000-0000-0000-000000000001'
on conflict do nothing;

insert into analysis.artifact_observation_refs (id, artifact_id, run_id, observation_id, role, display_order)
select ('a4520000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by v.weight desc)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000001', ro.run_id, ro.observation_id, 'stop',
       (row_number() over (order by v.weight desc))::int
from analysis.run_observations ro
join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
where ro.run_id='1a000000-0000-0000-0000-000000000001'
on conflict do nothing;

insert into analysis.artifact_observation_refs (id, artifact_id, run_id, observation_id, role, display_order)
select ('a4530000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by ro.observation_id)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000003', ro.run_id, ro.observation_id, 'member',
       (row_number() over (order by ro.observation_id))::int
from analysis.run_observations ro
where ro.run_id='1a000000-0000-0000-0000-000000000002'
on conflict do nothing;
```

- [ ] **Step 3: Apply and assert**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from analysis.analysis_definition_versions where status='active'), (select count(*) from analysis.analysis_runs), (select count(*) from analysis.analysis_runs where status='succeeded'), (select count(*) from analysis.analysis_results), (select count(*) from analysis.map_features), (select count(*) from analysis.sequence_items), (select ST_GeometryType(geometry) from analysis.map_features where feature_key='route-line');"`
Expected: `3|4|2|2|2|12|ST_LineString` (3 active definition versions; 4 runs; 2 succeeded; 2 results; 2 map_features; 12 sequence_items = the 12 frozen route observations; route-line is a LineString).

- [ ] **Step 4: Commit**

```bash
git add supabase/seed/50_analysis.sql
git commit -m "feat(seed): analysis enablement + succeeded route/cluster + failed/queued runs"
```

---

## Task 8: ROIs (`60_rois.sql`)

**Files:**
- Create: `supabase/seed/60_rois.sql`

**Interfaces:**
- Consumes: nothing (independent geometry).
- Produces: 1 `priority.roi_runs` + 5 `priority.rois` (all `valid_to` null → `priority.current_rois`) as small polygons in high-risk/low-observation zones, dimensions across `crash`/`crime`/`flooding`.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

insert into priority.roi_runs (id, dimensions, params, signal_window, started_at, completed_at, roi_count) values
  ('40e00000-0000-0000-0000-000000000001', array['crash','crime','flooding'], '{"eps_m":350,"min_samples":5}',
     tstzrange('2026-01-01 00:00:00+00','2026-06-15 00:00:00+00'), '2026-06-15 06:00:00+00','2026-06-15 06:05:00+00',5)
on conflict do nothing;

-- Helper: each ROI is a small box around a point; centroid = box center.
insert into priority.rois
  (id, run_id, risk_dimension, geom, centroid, area_m2, risk_score, signal_count, dominant_type,
   risk_breakdown, recency_score, description, valid_from, created_at)
values
  ('401a0000-0000-0000-0000-000000000001','40e00000-0000-0000-0000-000000000001','crash',
     ST_MakeEnvelope(-99.075,19.350,-99.065,19.360,4326)::geography, ST_SetSRID(ST_MakePoint(-99.070,19.355),4326)::geography,
     1100000,0.86,42,'collision','{"crash":0.86}',0.7,'Alta siniestralidad vial en Iztapalapa','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000002','40e00000-0000-0000-0000-000000000001','crime',
     ST_MakeEnvelope(-99.120,19.460,-99.110,19.470,4326)::geography, ST_SetSRID(ST_MakePoint(-99.115,19.465),4326)::geography,
     1100000,0.78,55,'robbery','{"crime":0.78}',0.6,'Concentración de incidentes en GAM','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000003','40e00000-0000-0000-0000-000000000001','flooding',
     ST_MakeEnvelope(-99.085,19.330,-99.075,19.340,4326)::geography, ST_SetSRID(ST_MakePoint(-99.080,19.335),4326)::geography,
     1100000,0.69,18,'urban_flood','{"flooding":0.69}',0.5,'Encharcamientos recurrentes','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000004','40e00000-0000-0000-0000-000000000001','crash',
     ST_MakeEnvelope(-99.205,19.355,-99.195,19.365,4326)::geography, ST_SetSRID(ST_MakePoint(-99.200,19.360),4326)::geography,
     1100000,0.74,33,'collision','{"crash":0.74}',0.65,'Cruces conflictivos en Álvaro Obregón','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000005','40e00000-0000-0000-0000-000000000001','crime',
     ST_MakeEnvelope(-99.140,19.425,-99.130,19.435,4326)::geography, ST_SetSRID(ST_MakePoint(-99.135,19.430),4326)::geography,
     1100000,0.81,47,'robbery','{"crime":0.81}',0.72,'Zona de atención prioritaria en Cuauhtémoc','2026-06-15 06:00:00+00',now())
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from priority.rois), (select count(*) from priority.current_rois), (select count(distinct risk_dimension) from priority.current_rois);"`
Expected: `5|5|3`

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/60_rois.sql
git commit -m "feat(seed): ROI run + 5 current ROIs across crash/crime/flooding"
```

---

## Task 9: Finalize — data version + cache rebuild + audit (`99_finalize.sql`)

**Files:**
- Create: `supabase/seed/99_finalize.sql`

**Interfaces:**
- Consumes: every prior fixture.
- Produces: an advanced `vision.read_model_state.data_version`, a populated `platform.tenant_visible_observations` for the tenant (the cache the read API reads), and a couple of `platform.audit_events`.

- [ ] **Step 1: Write the fixture**

```sql
set search_path = public, extensions;

select vision.bump_data_version();
select platform.rebuild_tenant_visible('a0000000-0000-0000-0000-000000000001');

insert into platform.audit_events (id, tenant_id, actor_subject_id, module, action, target_type, target_id, occurred_at, details) values
  ('aed10000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','geo','tenant_boundary_activated','tenant_boundary_version','b0000000-0000-0000-0000-000000000001','2026-06-01 00:00:00+00','{}'),
  ('aed10000-0000-0000-0000-000000000002','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','analysis','analysis_submitted','analysis_run','1a000000-0000-0000-0000-000000000001','2026-06-15 09:00:00+00','{"kind":"budget.route"}')
on conflict do nothing;
```

- [ ] **Step 2: Apply and assert the cache is populated and excludes Tlalpan**

Run: `supabase db reset && psql "$DBURL" -At -c "select (select count(*) from platform.tenant_visible_observations where tenant_id='a0000000-0000-0000-0000-000000000001'), (select count(*) from platform.tenant_visible_observations v join vision.observations o on o.id=v.observation_id join geo.geo_areas a on a.id='9e000000-0000-0000-0000-000000000012' and ST_Contains(a.geometry,o.location::geometry)), (select data_version from vision.read_model_state);"`
Expected: `<V>|0|<n>` — V > 0 (visible set populated; only current, in-boundary observations), the middle value is **0** (no Tlalpan/out-of-boundary observation is visible), and data_version ≥ 1.

- [ ] **Step 3: Commit**

```bash
git add supabase/seed/99_finalize.sql
git commit -m "feat(seed): bump data version + rebuild tenant-visible cache + audit events"
```

---

## Task 10: Verification script + handoff docs

**Files:**
- Create: `supabase/seed/verify.sql` (assertion script, not part of the seed run)
- Create or Modify: `apps/web/.env.example`
- Create: `supabase/seed/README.md`

**Interfaces:**
- Consumes: a fully seeded DB (`supabase db reset` completed).
- Produces: a single runnable verification (raises on any failed assertion) covering the §4 contract and the live-RLS visibility path; plus the credentials handoff doc the app team needs.

- [ ] **Step 1: Write the verification script**

`supabase/seed/verify.sql`:

```sql
-- Run AFTER `supabase db reset`:  psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql
-- Any failed assertion raises and aborts (non-zero exit) — this is the DoD #3 gate.
set search_path = public, extensions;

do $$
declare
  n int; scored int; pending int; visible int; tlalpan_visible int;
begin
  -- §4.1 catalog
  select count(*) into n from vision.observation_types;
  assert n = 5, format('expected 5 observation_types, got %s', n);
  assert exists (select 1 from vision.observation_types where slug='missing_signage' and auto_resolvable=false), 'missing_signage must be latent (auto_resolvable=false)';

  -- §4.2 observations + states
  select count(*) into n from vision.observations;
  assert n >= 120, format('expected >=120 observations, got %s', n);
  assert (select count(*) from vision.observations where superseded_by_observation_id is not null) >= 1, 'need >=1 superseded';
  assert (select count(*) from vision.observations where resolved_at is not null) >= 1, 'need >=1 resolved';

  -- priority: scored present, pending present, exactly one active model
  select count(*) into scored from vision.observations o
    join priority.current_priority_values v on v.observation_id=o.id
    where o.superseded_by_observation_id is null and o.resolved_at is null;
  select count(*) into pending from vision.observations o
    where o.superseded_by_observation_id is null and o.resolved_at is null
      and not exists (select 1 from priority.current_priority_values v where v.observation_id=o.id);
  assert scored >= 90, format('expected >=90 scored, got %s', scored);
  assert pending >= 1, format('expected >=1 pending, got %s', pending);
  assert (select count(*) from priority.priority_models where status='active') = 1, 'exactly one active priority model';

  -- geo: single active edition + boundary; every observation bound
  assert (select count(*) from geo.geo_editions where status='active') = 1, 'one active edition';
  assert (select count(*) from geo.tenant_boundary_versions where tenant_id='a0000000-0000-0000-0000-000000000001' and status='active') = 1, 'one active boundary';
  assert (select count(*) from vision.observations o where not exists (select 1 from geo.observation_geo_bindings b where b.observation_id=o.id)) = 0, 'all observations must be geo-bound';

  -- §4.6 analysis: definitions enabled + a succeeded route result with a line artifact
  assert (select count(*) from analysis.analysis_definition_versions where status='active') = 3, 'three active definition versions';
  assert exists (
    select 1 from analysis.analysis_runs r
    join analysis.analysis_results res on res.run_id=r.id
    join analysis.artifacts a on a.result_id=res.id
    join analysis.map_features mf on mf.artifact_id=a.id
    where r.status='succeeded' and ST_GeometryType(mf.geometry)='ST_LineString'), 'need a succeeded route with a LineString artifact';

  -- §4.5 ROIs
  assert (select count(*) from priority.current_rois) >= 1, 'need >=1 current ROI';

  raise notice 'CONTRACT OK: % observations, % scored, % pending', (select count(*) from vision.observations), scored, pending;
end $$;

-- ---- Live RLS path: author.a sees in-boundary, nothing from Tlalpan ----
do $$
declare visible int; tlalpan_visible int; nomember_visible int;
begin
  -- author.a
  perform set_config('request.jwt.claims', json_build_object('sub','c0000000-0000-0000-0000-00000000000a','role','authenticated')::text, true);
  perform set_config('app.tenant_id','a0000000-0000-0000-0000-000000000001', true);
  set local role authenticated;
  select count(*) into visible from vision.observations;
  select count(*) into tlalpan_visible
    from vision.observations o
    join geo.geo_areas a on a.id='9e000000-0000-0000-0000-000000000012' and ST_Contains(a.geometry,o.location::geometry);
  reset role;
  assert visible > 0, format('author.a should see observations, saw %s', visible);
  assert tlalpan_visible = 0, format('author.a must NOT see Tlalpan (out-of-boundary), saw %s', tlalpan_visible);

  -- nomember: no membership => no rows
  perform set_config('request.jwt.claims', json_build_object('sub','c0000000-0000-0000-0000-00000000000c','role','authenticated')::text, true);
  perform set_config('app.tenant_id','a0000000-0000-0000-0000-000000000001', true);
  set local role authenticated;
  select count(*) into nomember_visible from vision.observations;
  reset role;
  assert nomember_visible = 0, format('nomember must see 0 observations, saw %s', nomember_visible);

  raise notice 'RLS OK: author.a visible=%, tlalpan=%, nomember=%', visible, tlalpan_visible, nomember_visible;
end $$;
```

- [ ] **Step 2: Run the verification (DoD #3 — show the output)**

Run: `supabase db reset && psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql`
Expected: two `NOTICE` lines (`CONTRACT OK: …` and `RLS OK: …`) and exit code 0. Any assertion failure aborts with a clear message and non-zero exit.

> If the RLS block returns `visible = 0` for `author.a`, confirm `99_finalize.sql` ran `rebuild_tenant_visible` (the cache must be populated) and that `set local role authenticated` is inside the same transaction as the `set_config(..., true)` calls (it is, within the `do $$` block).

- [ ] **Step 3: Write the credentials handoff**

`apps/web/.env.example` (create if missing; do not commit real keys):

```
# Local Supabase (from `supabase status`)
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_ANON_KEY=<anon key from `supabase status`>

# Dev login users seeded by supabase/seed/* (password for all: vialia-dev-2026!)
#   author.a@vialia.test   role=analysis_author  (full app)
#   viewer.a@vialia.test   role=viewer           (read-only)
#   nomember@vialia.test   role=none             (no-membership empty-state test)
```

`supabase/seed/README.md`:

```markdown
# Seed data

`supabase db reset` applies `migrations/` then every `seed/*.sql` in order:
00 catalog → 10 geo → 20 auth → 30 observations → 40 priority → 50 analysis → 60 rois → 99 finalize.

Verify a fresh seed:
    export DBURL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase db reset
    psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql

Dev login users (password `vialia-dev-2026!`): author.a@ (analysis_author),
viewer.a@ (viewer), nomember@ (no membership). Tenant: "Vialia CDMX".
Tunable: bulk observation count is the `generate_series(1,120)` in 30_observations.sql.
```

- [ ] **Step 4: Commit**

```bash
git add supabase/seed/verify.sql supabase/seed/README.md apps/web/.env.example
git commit -m "feat(seed): contract+RLS verification script and credentials handoff"
```

---

## Self-review (spec coverage)

- §4.1 catalog → Task 2 ✓ · §4.2 geo → Task 3 ✓ · §4.3 tenant/auth → Tasks 3–4 ✓ · §4.4 observations+priority → Tasks 5–6 ✓ · §4.5 ROIs → Task 8 ✓ · §4.6 analysis enablement+runs → Task 7 ✓ · finalize/cache → Task 9 ✓ · verification (DoD #3) + handoff → Task 10 ✓.
- Grounding facts honored: pure INSERTs (no UPDATE); successor-before-predecessor for supersession; `rebuild_tenant_visible` in finalize; deterministic UUIDs/time; idempotent `on conflict`.
- Type/name consistency: UUIDs reused verbatim from the Fixed UUID map; definition keys (`surface_area_m2`/`length_m`/`count`/`confidence`) consistent between Tasks 2, 5, 7; run ids consistent between Tasks 7 and 9/10.
- Out of scope confirmed: no `0200`/`0201` app API here (extend `verify.sql` once they land — noted in §5 of the spec).
```
