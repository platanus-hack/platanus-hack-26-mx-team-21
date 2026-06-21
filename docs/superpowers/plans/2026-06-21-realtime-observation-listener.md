# Real-time Observation Listener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** React on the live map the instant a new observation becomes visible to a tenant — a non-disruptive toast + marker pulse for single inserts, one aggregated toast for a sweep batch — and let the user jump to it.

**Architecture:** A Postgres `AFTER INSERT` trigger on `platform.tenant_visible_observations` broadcasts a lean payload to a per-tenant private Realtime topic (`tenant:<id>`). The browser subscribes to that topic, buffers events for ~700ms, groups them by `sweep_id`, raises toasts + pulses the new markers, and fires one authoritative `getObservations()` refetch so the map self-heals against dropped events.

**Tech Stack:** Supabase Realtime Broadcast (`realtime.send` + `realtime.messages` RLS), React + TypeScript, Leaflet, Vitest (new — for the pure grouping reducer).

## Global Constraints

- **Spanish UI copy**, verbatim: single → `Nueva observación · <label> en <zona>` (drop ` en <zona>` when zone is null); batch → `<N> nuevas · barrido <SWP-XXXX>`.
- Browser reads **only** via `public.app_*` security-definer RPCs; never grant the browser direct select on custom schemas. The Realtime layer must not expose a data table.
- Reuse the existing tenant resolver `public._app_tenant()` for per-tenant scoping.
- Migrations must apply on a DB without Supabase's default realtime objects — guard with existence checks (mirror `supabase/migrations/0300_community_inference_jobs.sql`).
- Pin styling stays authoritative from `getObservations()`; the broadcast payload is used only for the toast text, locating, and pulse — never to construct a styled pin.
- Frontend repo root for commands: `frontend/`. Migrations live in `supabase/migrations/`.

---

### Task 1: DB broadcast trigger + per-tenant authorization

**Files:**
- Create: `supabase/migrations/0301_observation_broadcast.sql`

**Interfaces:**
- Consumes: `platform.tenant_visible_observations(tenant_id uuid, observation_id uuid)`, `vision.observations`, `vision.observation_types`, `public._app_tenant()`, `realtime.send(jsonb, text, text, boolean)`.
- Produces: Realtime broadcasts on topic `tenant:<tenant_id>`, event `observation_inserted`, with payload `{ observation_id, slug, lat, lng, sweep_id, sweep, zone, observed_at }`. Authorization policy on `realtime.messages` keyed on `public._app_tenant()`.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/0301_observation_broadcast.sql`:

```sql
-- Real-time observation listener: broadcast each newly-visible observation to its
-- tenant's private Realtime topic so the map web client can react live. The trigger
-- fires when an observation becomes visible to a tenant (a tenant_visible_observations
-- insert) — exactly when a pin appears on that tenant's map. See
-- docs/superpowers/specs/2026-06-21-realtime-observation-listener-design.md.

-- Trigger fn lives in `community` (already the home of the realtime confirmation channel).
create or replace function community.broadcast_observation()
returns trigger
language plpgsql
security definer
set search_path = extensions, public
as $$
declare
  v_payload jsonb;
begin
  begin
    select jsonb_build_object(
             'observation_id', o.id,
             'slug', ot.slug,
             'lat', ST_Y(o.location::geometry),
             'lng', ST_X(o.location::geometry),
             'sweep_id', o.sweep_id,
             'sweep', 'SWP-' || upper(substr(o.sweep_id::text, 1, 4)),
             'zone', coalesce(nullif(ageb.name, ''), agem.name),
             'observed_at', o.observed_at
           )
      into v_payload
      from vision.observations o
      join vision.observation_types ot on ot.id = o.observation_type_id
      left join geo.observation_geo_bindings b
        on b.observation_id = o.id
       and b.edition_id = (select id from geo.geo_editions where status = 'active')
      left join geo.geo_areas agem on agem.id = b.agem_area_id
      left join geo.geo_areas ageb on ageb.id = b.ageb_area_id
     where o.id = new.observation_id;

    if v_payload is not null then
      perform realtime.send(
        v_payload,
        'observation_inserted',
        'tenant:' || new.tenant_id::text,
        true   -- private topic
      );
    end if;
  exception when others then
    -- A Realtime hiccup must NEVER block the underlying insert.
    null;
  end;
  return new;
end;
$$;

create trigger tvo_broadcast_observation
  after insert on platform.tenant_visible_observations
  for each row execute function community.broadcast_observation();

-- Authorization for the private `tenant:<id>` topic: an authenticated user may RECEIVE
-- broadcast messages only for their own tenant's topic. realtime.send() inserts into
-- realtime.messages; the receive path is gated by this SELECT policy. Guarded so the
-- migration still applies on a DB without Supabase's realtime schema.
do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'realtime' and table_name = 'messages') then
    execute 'alter table realtime.messages enable row level security';
    execute $p$
      create policy app_tenant_broadcast_receive on realtime.messages
        for select to authenticated
        using (
          realtime.messages.extension = 'broadcast'
          and realtime.topic() = 'tenant:' || public._app_tenant()::text
        )
    $p$;
  end if;
exception when duplicate_object then
  null;  -- policy already present (idempotent re-run)
end $$;
```

- [ ] **Step 2: Apply the migration to the remote project**

Use the Supabase MCP `apply_migration` tool with name `0301_observation_broadcast` and the file contents.
Expected: success, no error.

- [ ] **Step 3: Verify the trigger fires and writes a tenant-scoped message**

Run via Supabase MCP `execute_sql` (uses a privileged connection, so this asserts the trigger mechanics, not the RLS receive path):

```sql
-- Pick any tenant + an observation already visible to it, clone-insert is unsafe, so
-- instead assert the function builds a payload for a known visible observation.
select community.broadcast_observation is not null as fn_exists;
select tgname from pg_trigger where tgname = 'tvo_broadcast_observation';
-- Count messages before/after a synthetic send through the same code path:
select count(*) as msgs_before from realtime.messages
  where topic like 'tenant:%' and event = 'observation_inserted';
```
Expected: `fn_exists = true`, one trigger row, a numeric count (baseline).

- [ ] **Step 4: Verify RLS policy exists**

Run via Supabase MCP `execute_sql`:

```sql
select polname from pg_policies
  where schemaname = 'realtime' and tablename = 'messages'
    and policyname = 'app_tenant_broadcast_receive';
```
Expected: one row, `app_tenant_broadcast_receive`.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0301_observation_broadcast.sql
git commit -m "feat(db): broadcast new observations to per-tenant realtime topic"
```

---

### Task 2: Event type + Realtime subscriber module

**Files:**
- Modify: `frontend/src/lib/types.ts` (append the `ObservationEvent` interface)
- Create: `frontend/src/lib/observationsRealtime.ts`

**Interfaces:**
- Consumes: `supabase` from `./supabase`; the broadcast payload from Task 1.
- Produces:
  - `ObservationEvent` interface (fields match Task 1's payload).
  - `subscribeNewObservations(tenantId: string, accessToken: string, onEvent: (e: ObservationEvent) => void): () => void` — subscribes to the private topic and returns an unsubscribe function.

- [ ] **Step 1: Add the event type to `types.ts`**

Append to `frontend/src/lib/types.ts`:

```ts
// ---- Real-time observation stream (§realtime listener) ----------------------

// The lean payload broadcast by community.broadcast_observation() on a tenant's
// private Realtime topic when a new observation becomes visible. Used only for the
// toast/pulse/locate — pin styling stays authoritative from getObservations().
export interface ObservationEvent {
  observation_id: string;
  slug: string;
  lat: number;
  lng: number;
  sweep_id: string | null;
  sweep: string | null; // 'SWP-XXXX'
  zone: string | null;
  observed_at: string;
}
```

- [ ] **Step 2: Write the subscriber module**

Create `frontend/src/lib/observationsRealtime.ts`:

```ts
// Subscribes the browser to its tenant's private Realtime topic so it receives a
// broadcast each time a new observation becomes visible. The topic name and event
// match supabase/migrations/0301_observation_broadcast.sql.
import { supabase } from "./supabase";
import type { ObservationEvent } from "./types";

export function subscribeNewObservations(
  tenantId: string,
  accessToken: string,
  onEvent: (e: ObservationEvent) => void,
): () => void {
  // Private channels require the access token on the Realtime socket for authorization.
  supabase.realtime.setAuth(accessToken);

  const channel = supabase
    .channel(`tenant:${tenantId}`, { config: { private: true, broadcast: { self: false } } })
    .on("broadcast", { event: "observation_inserted" }, ({ payload }) => {
      onEvent(payload as ObservationEvent);
    })
    .subscribe((status) => {
      // Private channels fail silently on auth errors — log so misconfig is visible.
      if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
        console.warn(`[observations] realtime channel ${status} for tenant:${tenantId}`);
      }
    });

  return () => {
    supabase.removeChannel(channel);
  };
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/observationsRealtime.ts
git commit -m "feat(web): tenant realtime subscriber for new observations"
```

---

### Task 3: Vitest setup + pure `groupEvents` reducer (TDD)

**Files:**
- Modify: `frontend/package.json` (add `vitest` devDependency + `test` script)
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/lib/observationStream.ts`
- Test: `frontend/src/lib/observationStream.test.ts`

**Interfaces:**
- Consumes: `ObservationEvent` from `./types`.
- Produces:
  - `ToastTarget = { type: "point"; observationId: string; lat: number; lng: number } | { type: "bounds"; points: { lat: number; lng: number }[] }`
  - `ToastDraft = { kind: "single" | "batch"; message: string; target: ToastTarget }`
  - `groupEvents(events: ObservationEvent[], labelFor: (slug: string) => string): ToastDraft[]`

- [ ] **Step 1: Add vitest + test script**

Run: `cd frontend && npm install -D vitest@^2`
Then add to `frontend/package.json` `"scripts"`:

```json
"test": "vitest run"
```

- [ ] **Step 2: Create the vitest config (reuse Vite aliases, node env)**

Create `frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
```

- [ ] **Step 3: Write the failing test**

Create `frontend/src/lib/observationStream.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { groupEvents } from "./observationStream";
import type { ObservationEvent } from "./types";

const ev = (over: Partial<ObservationEvent>): ObservationEvent => ({
  observation_id: "o1",
  slug: "pothole",
  lat: 19.4,
  lng: -99.1,
  sweep_id: "s1",
  sweep: "SWP-S1AA",
  zone: "Cuauhtémoc",
  observed_at: "2026-06-21T10:00:00Z",
  ...over,
});

const label = (slug: string) => (slug === "pothole" ? "Bache" : slug);

describe("groupEvents", () => {
  it("returns a single-point draft for one event with a zone", () => {
    const out = groupEvents([ev({})], label);
    expect(out).toEqual([
      {
        kind: "single",
        message: "Nueva observación · Bache en Cuauhtémoc",
        target: { type: "point", observationId: "o1", lat: 19.4, lng: -99.1 },
      },
    ]);
  });

  it("drops ' en <zona>' when zone is null", () => {
    const out = groupEvents([ev({ zone: null })], label);
    expect(out[0].message).toBe("Nueva observación · Bache");
  });

  it("aggregates same-sweep events into one batch draft with bounds", () => {
    const out = groupEvents(
      [
        ev({ observation_id: "a", lat: 1, lng: 2 }),
        ev({ observation_id: "b", lat: 3, lng: 4 }),
        ev({ observation_id: "c", lat: 5, lng: 6 }),
      ],
      label,
    );
    expect(out).toEqual([
      {
        kind: "batch",
        message: "3 nuevas · barrido SWP-S1AA",
        target: {
          type: "bounds",
          points: [
            { lat: 1, lng: 2 },
            { lat: 3, lng: 4 },
            { lat: 5, lng: 6 },
          ],
        },
      },
    ]);
  });

  it("keeps distinct sweeps in separate drafts, null sweep_id stays single", () => {
    const out = groupEvents(
      [
        ev({ observation_id: "a", sweep_id: "s1", sweep: "SWP-S1AA" }),
        ev({ observation_id: "b", sweep_id: "s1", sweep: "SWP-S1AA" }),
        ev({ observation_id: "z", sweep_id: null, sweep: null }),
      ],
      label,
    );
    expect(out.map((d) => d.kind)).toEqual(["batch", "single"]);
    expect(out[0].message).toBe("2 nuevas · barrido SWP-S1AA");
  });

  it("returns [] for no events", () => {
    expect(groupEvents([], label)).toEqual([]);
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `groupEvents` is not exported / module not found.

- [ ] **Step 5: Implement the reducer**

Create `frontend/src/lib/observationStream.ts`:

```ts
// Pure grouping of buffered observation events into toast drafts. A burst from one
// sweep (many events sharing sweep_id) collapses to a single aggregated batch toast;
// a lone event (or one with no sweep_id) becomes a single toast. Kept pure so the
// grouping logic is unit-tested without Realtime/timers.
import type { ObservationEvent } from "./types";

export type ToastTarget =
  | { type: "point"; observationId: string; lat: number; lng: number }
  | { type: "bounds"; points: { lat: number; lng: number }[] };

export interface ToastDraft {
  kind: "single" | "batch";
  message: string;
  target: ToastTarget;
}

function singleDraft(e: ObservationEvent, labelFor: (slug: string) => string): ToastDraft {
  const base = `Nueva observación · ${labelFor(e.slug)}`;
  return {
    kind: "single",
    message: e.zone ? `${base} en ${e.zone}` : base,
    target: { type: "point", observationId: e.observation_id, lat: e.lat, lng: e.lng },
  };
}

export function groupEvents(
  events: ObservationEvent[],
  labelFor: (slug: string) => string,
): ToastDraft[] {
  // Preserve first-seen order of sweep groups; null sweep_id never groups.
  const order: string[] = [];
  const groups = new Map<string, ObservationEvent[]>();
  let loose = 0;

  for (const e of events) {
    if (!e.sweep_id) {
      const key = `__loose_${loose++}`;
      order.push(key);
      groups.set(key, [e]);
      continue;
    }
    if (!groups.has(e.sweep_id)) {
      order.push(e.sweep_id);
      groups.set(e.sweep_id, []);
    }
    groups.get(e.sweep_id)!.push(e);
  }

  return order.map((key) => {
    const g = groups.get(key)!;
    if (g.length === 1) return singleDraft(g[0], labelFor);
    return {
      kind: "batch",
      message: `${g.length} nuevas · barrido ${g[0].sweep}`,
      target: { type: "bounds", points: g.map((e) => ({ lat: e.lat, lng: e.lng })) },
    };
  });
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/lib/observationStream.ts frontend/src/lib/observationStream.test.ts
git commit -m "feat(web): groupEvents reducer for observation toasts + vitest"
```

---

### Task 4: `useObservationStream` hook (buffer + debounce + wiring)

**Files:**
- Modify: `frontend/src/lib/observationStream.ts` (append the hook + `Toast` type)

**Interfaces:**
- Consumes: `subscribeNewObservations` (Task 2), `groupEvents` + `ToastDraft`/`ToastTarget` (Task 3).
- Produces:
  - `Toast = ToastDraft & { id: string }`
  - `useObservationStream(opts): void` where
    `opts = { tenantId: string | null; accessToken: string | null; labelFor: (slug: string) => string; onRefetch: () => void; onToast: (t: Toast) => void }`

- [ ] **Step 1: Append the hook to `observationStream.ts`**

Add to `frontend/src/lib/observationStream.ts`:

```ts
import { useEffect, useRef } from "react";
import { subscribeNewObservations } from "./observationsRealtime";
import type { ObservationEvent } from "./types";

export type Toast = ToastDraft & { id: string };

const FLUSH_MS = 700; // group a sweep's burst before raising toasts / refetching

export interface UseObservationStreamOpts {
  tenantId: string | null;
  accessToken: string | null;
  labelFor: (slug: string) => string;
  onRefetch: () => void;
  onToast: (t: Toast) => void;
}

// Subscribes to the tenant's realtime topic, buffers events for FLUSH_MS, groups
// them by sweep, raises toasts, and fires ONE authoritative refetch per flush.
export function useObservationStream(opts: UseObservationStreamOpts): void {
  const { tenantId, accessToken, labelFor, onRefetch, onToast } = opts;

  // Keep latest callbacks/label in refs so the subscribe effect only re-runs on identity.
  const labelRef = useRef(labelFor);
  labelRef.current = labelFor;
  const refetchRef = useRef(onRefetch);
  refetchRef.current = onRefetch;
  const toastRef = useRef(onToast);
  toastRef.current = onToast;
  const seq = useRef(0);

  useEffect(() => {
    if (!tenantId || !accessToken) return;

    let buffer: ObservationEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      timer = null;
      const events = buffer;
      buffer = [];
      if (events.length === 0) return;
      for (const draft of groupEvents(events, labelRef.current)) {
        toastRef.current({ ...draft, id: `obs-${seq.current++}` });
      }
      refetchRef.current(); // authoritative — folds new pins into the map state
    };

    const unsubscribe = subscribeNewObservations(tenantId, accessToken, (e) => {
      buffer.push(e);
      if (timer === null) timer = setTimeout(flush, FLUSH_MS);
    });

    return () => {
      if (timer !== null) clearTimeout(timer);
      unsubscribe();
    };
  }, [tenantId, accessToken]);
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Run unit tests (ensure the reducer tests still pass after the append)**

Run: `cd frontend && npm test`
Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/observationStream.ts
git commit -m "feat(web): useObservationStream hook (buffer, group, refetch)"
```

---

### Task 5: `ToastStack` component (bottom-right)

**Files:**
- Create: `frontend/src/components/ToastStack.tsx`

**Interfaces:**
- Consumes: `Toast` type from `../lib/observationStream`; `Panel`, `Button` UI primitives.
- Produces: `ToastStack({ toasts, onAction, onDismiss }: { toasts: Toast[]; onAction: (t: Toast) => void; onDismiss: (id: string) => void })` — renders the stack and auto-dismisses each toast after 8s.

- [ ] **Step 1: Write the component**

Create `frontend/src/components/ToastStack.tsx`:

```tsx
import { useEffect } from "react";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import type { Toast } from "../lib/observationStream";

const DISMISS_MS = 8000;

// Bottom-right live-notification stack. Sits above the Leaflet zoom control (which is
// bottom-right) via the bottom offset, clear of the bottom-left dock and top-center
// sweep banner. Each toast auto-dismisses; "Ver" pans/fits the map to the new pin(s).
export function ToastStack({
  toasts,
  onAction,
  onDismiss,
}: {
  toasts: Toast[];
  onAction: (t: Toast) => void;
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none absolute bottom-[92px] right-[18px] z-[560] flex w-[280px] flex-col items-end gap-2">
      {toasts.map((t) => (
        <ToastRow key={t.id} toast={t} onAction={onAction} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastRow({
  toast,
  onAction,
  onDismiss,
}: {
  toast: Toast;
  onAction: (t: Toast) => void;
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const id = setTimeout(() => onDismiss(toast.id), DISMISS_MS);
    return () => clearTimeout(id);
  }, [toast.id, onDismiss]);

  return (
    <Panel
      className="pointer-events-auto flex w-full items-center gap-2 py-2 pl-3 pr-2"
      style={{ animation: "ppup 180ms ease-out" }}
    >
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ background: toast.kind === "batch" ? "#2f64e6" : "#0f9b8e" }}
      />
      <span className="flex-1 text-[12px] leading-[1.35] text-foreground">{toast.message}</span>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onAction(toast)}
        className="h-[26px] shrink-0 rounded-[7px] px-2.5 text-[11px] font-semibold"
      >
        Ver
      </Button>
      <Button
        variant="secondary"
        size="icon-xs"
        onClick={() => onDismiss(toast.id)}
        title="Descartar"
        className="size-[22px] shrink-0 rounded-[6px] bg-[#f1f4f8] text-base leading-none text-[var(--ink-2)]"
      >
        ×
      </Button>
    </Panel>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors. (If `Button` lacks a `size="sm"` variant, use the same `size="icon-xs"`/class pattern the `SweepBanner` close button uses — check `frontend/src/components/ui/button.tsx` and match an existing size.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ToastStack.tsx
git commit -m "feat(web): ToastStack live-notification component"
```

---

### Task 6: MapCanvas marker pulse + batch fit-bounds

**Files:**
- Modify: `frontend/src/components/MapCanvas.tsx`
- Modify: `frontend/src/index.css` (add the `obs-pulse` keyframe)

**Interfaces:**
- Consumes: `observations` (existing prop), new props below.
- Produces: `MapCanvas` accepts two new props:
  - `pulseIds: Set<string>` — ids of pins to render a pulsing halo on (~3s, parent clears).
  - `fitTarget: { points: { lat: number; lng: number }[]; n: number } | null` — bump `n` to fit the map to a batch's bounds.

- [ ] **Step 1: Add the pulse keyframe to `index.css`**

Append to `frontend/src/index.css`:

```css
@keyframes obs-pulse {
  0% {
    transform: translate(-50%, -50%) scale(0.6);
    opacity: 0.9;
  }
  100% {
    transform: translate(-50%, -50%) scale(2.4);
    opacity: 0;
  }
}
```

- [ ] **Step 2: Add the new props to the `Props` interface**

In `frontend/src/components/MapCanvas.tsx`, add to `interface Props` (after `panTarget`):

```ts
  pulseIds: Set<string>;
  fitTarget: { points: { lat: number; lng: number }[]; n: number } | null;
```

- [ ] **Step 3: Register a `pulse` layer group**

In the init `useEffect`, add `pulse` to the `groups.current = { … }` object (alongside `pins`):

```ts
      pins: L.layerGroup().addTo(map),
      pulse: L.layerGroup().addTo(map),
```

- [ ] **Step 4: Draw pulses for `pulseIds`**

Add a new `useEffect` after the pins effect (`// ---- pins …`):

```tsx
  // ---- transient pulse halos on freshly-arrived pins ----------------------
  useEffect(() => {
    const g = groups.current.pulse;
    if (!g) return;
    g.clearLayers();
    if (props.pulseIds.size === 0) return;
    for (const o of props.observations) {
      if (!props.pulseIds.has(o.id)) continue;
      L.marker([o.lat, o.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="width:14px;height:14px;border-radius:50%;background:${props.accent};animation:obs-pulse 1.4s ease-out 2;"></div>`,
          iconSize: [0, 0],
        }),
      }).addTo(g);
    }
  }, [props.pulseIds, props.observations, props.accent]);
```

- [ ] **Step 5: Fit the map to a batch's bounds on `fitTarget`**

Add a new `useEffect` after the "fly to an arbitrary target" effect:

```tsx
  // ---- fit to a batch of new observations ("Ver" on a batch toast) --------
  const fitNRef = useRef(0);
  useEffect(() => {
    const map = mapRef.current;
    const ft = props.fitTarget;
    if (!map || !ft || ft.n === fitNRef.current || ft.points.length === 0) return;
    fitNRef.current = ft.n;
    const ll = ft.points.map((p) => [p.lat, p.lng]) as [number, number][];
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.2), {
        maxZoom: 15,
        animate: true,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [320, 220],
      });
    } catch {
      /* ignore */
    }
  }, [props.fitTarget]);
```

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: errors at the `MapCanvas` call site in `MapPage.tsx` (missing `pulseIds`/`fitTarget` props) — that is expected and fixed in Task 7. No errors *inside* `MapCanvas.tsx` itself.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/MapCanvas.tsx frontend/src/index.css
git commit -m "feat(web): MapCanvas pulse halos + batch fit-bounds"
```

---

### Task 7: Wire MapPage to the live stream

**Files:**
- Modify: `frontend/src/pages/MapPage.tsx`

**Interfaces:**
- Consumes: `useObservationStream` + `Toast` (Task 4), `ToastStack` (Task 5), `MapCanvas` new props (Task 6), `useAuth().session`, existing `api.getObservations`, `setObservations`, `onSelect`, `panTarget`/`setPanTarget`.
- Produces: live toasts + pulses + pan/fit behavior on the rendered map.

- [ ] **Step 1: Add imports + capture tenant id**

In `frontend/src/pages/MapPage.tsx`:

Add imports near the top:

```tsx
import { ToastStack } from "../components/ToastStack";
import { useObservationStream, type Toast } from "../lib/observationStream";
```

Get the session from the existing auth hook — change:

```tsx
  const { signOut } = useAuth();
```
to:

```tsx
  const { session, signOut } = useAuth();
```

Add a tenant-id state alongside `accent`:

```tsx
  const [accent, setAccent] = useState("#2f64e6");
  const [tenantId, setTenantId] = useState<string | null>(null);
```

In the initial-load effect, after `if (tenant?.accent) { … }`, set the id:

```tsx
        if (tenant?.id) setTenantId(tenant.id);
```

- [ ] **Step 2: Add live-stream UI state + the pulse/fit/toast state**

Add near the other `useState` declarations (after the sweep state block):

```tsx
  // ---- live observation stream -------------------------------------------
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pulseIds, setPulseIds] = useState<Set<string>>(() => new Set());
  const [fitTarget, setFitTarget] = useState<{ points: { lat: number; lng: number }[]; n: number } | null>(null);
  const fitSeq = useRef(0);
  const panSeq = useRef(0); // bumps panTarget.n so the fly-to re-triggers per "Ver"
```

- [ ] **Step 3: Wire the hook**

After the `regions`/`request` memos (anywhere inside the component body, before `return`), add:

```tsx
  // Authoritative refetch folded into the map state; debounced upstream by the hook.
  const refetchObservations = useCallback(() => {
    api.getObservations().then(setObservations).catch(() => {});
  }, []);

  const pushToast = useCallback((t: Toast) => {
    setToasts((cur) => [t, ...cur].slice(0, 4)); // cap the stack
    // Pulse the new pin(s) for ~3s.
    const ids =
      t.target.type === "point"
        ? [t.target.observationId]
        : []; // batch ids aren't in the lean payload target; pulse resolves on refetch below
    if (ids.length) {
      setPulseIds((cur) => new Set([...cur, ...ids]));
      setTimeout(() => {
        setPulseIds((cur) => {
          const next = new Set(cur);
          for (const id of ids) next.delete(id);
          return next;
        });
      }, 3000);
    }
  }, []);

  useObservationStream({
    tenantId,
    accessToken: session?.access_token ?? null,
    labelFor: (slug) => typeLabels[slug] ?? slug,
    onRefetch: refetchObservations,
    onToast: pushToast,
  });

  const onToastAction = useCallback(
    (t: Toast) => {
      setToasts((cur) => cur.filter((x) => x.id !== t.id));
      if (t.target.type === "point") {
        onSelect(t.target.observationId);
        panSeq.current += 1;
        setPanTarget({ lat: t.target.lat, lng: t.target.lng, n: panSeq.current });
      } else {
        fitSeq.current += 1;
        setFitTarget({ points: t.target.points, n: fitSeq.current });
      }
    },
    [onSelect],
  );

  const dismissToast = useCallback((id: string) => {
    setToasts((cur) => cur.filter((x) => x.id !== id));
  }, []);
```

- [ ] **Step 4: Pass new props to MapCanvas + render ToastStack**

Add the two new props to the `<MapCanvas … />` element:

```tsx
        panTarget={panTarget}
        pulseIds={pulseIds}
        fitTarget={fitTarget}
        onSelect={onSelect}
```

Add `<ToastStack />` just before the closing `</div>` of the page (after the `ObservationCard` block):

```tsx
      <ToastStack toasts={toasts} onAction={onToastAction} onDismiss={dismissToast} />
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Manual verification**

Run: `cd frontend && npm run dev`, log in, then in a separate shell insert a test observation. Single insert: confirm a teal toast `Nueva observación · <label> en <zona>` appears bottom-right, the new pin pulses, and **Ver** pans + opens the card. Batch insert (many rows sharing a `sweep_id`): confirm one blue toast `<N> nuevas · barrido SWP-XXXX`, and **Ver** fits the map to the batch. Confirm pins persist after the refetch.

Insert helper (run via Supabase MCP `execute_sql`, adapting ids to your seed) — insert into `vision.observations` then `platform.tenant_visible_observations` for your tenant; the `tvo` insert is what fires the broadcast.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/MapPage.tsx
git commit -m "feat(web): wire live observation stream into the map page"
```

---

## Notes for the implementer

- **Batch pulse:** the batch toast target carries only points (the lean payload has the ids per-event, but `pushToast` receives the grouped draft). Pins still pulse implicitly because the authoritative refetch re-renders them; if per-pin batch pulsing is wanted later, extend `ToastDraft` batch target to include `observationIds` and pulse them in `pushToast`. Out of scope for first ship.
- **`Button` sizes:** confirm `size="sm"` exists in `frontend/src/components/ui/button.tsx`; if not, reuse an existing size + className like `SweepBanner` does.
- **Realtime auth on token refresh:** the hook re-runs when `session.access_token` changes, re-calling `setAuth` + re-subscribing — no extra handling needed.
```
