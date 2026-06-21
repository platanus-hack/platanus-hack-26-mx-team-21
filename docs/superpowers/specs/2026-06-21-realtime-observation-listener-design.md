# Real-time observation listener — design

**Date:** 2026-06-21
**Status:** Approved (brainstorming) → ready for implementation plan

## Goal

React on the live map the instant a new observation becomes visible to the tenant:
show a non-disruptive notification, pulse the new marker(s), and let the user jump to
it. Handle both a **single** new observation and a **batch** of observations that land
together from one inspection sweep.

## Constraints / context

- The browser authenticates as `authenticated` and reads **only** via `public.app_*`
  security-definer RPCs. It has **no** direct select on the custom schemas
  (`vision`/`priority`/`geo`/`platform`). The real-time design must not break this.
- Map pins are driven by `platform.tenant_visible_observations` (`tvo`): an observation
  appears on a tenant's map exactly when a `tvo` row is inserted. `tvo` carries
  `tenant_id` and the row references `vision.observations` (which carries `sweep_id`).
- A sweep inserts **many** `tvo` rows at once, all sharing a `sweep_id`.
- Precedent: `community.inference_jobs` is published to `supabase_realtime`, but that
  subscriber is a **backend** using `service_role` (bypasses RLS) — not the browser.
- Map is **Leaflet** (`frontend/src/components/MapCanvas.tsx`), canvas renderer. It
  already has `panTarget` (`flyTo`) and `fitBounds` with panel-aware padding for the
  plan and sweep overlays.
- Tenant resolver `public._app_tenant()` (security-definer, resolves tenant from
  `auth.uid()`) already exists and is reused by every RPC.

## Decisions

| Question | Decision |
|---|---|
| Transport | **DB Broadcast** to a per-tenant private topic `tenant:<tenant_id>`. No new queryable table — stays true to the RPC-only/security-definer model. |
| Single-obs UX | **Toast + pulsing marker; click to open.** Non-disruptive. "Ver" pans + opens the `ObservationCard`. |
| Batch UX | **One aggregated toast** (`"N nuevas · barrido SWP-XXXX"`); "Ver" fits the map to the batch bounds. No auto-open. |
| Toast placement | **Bottom-right**, stacked above the zoom control; verify it clears the AgentPanel and nudge if needed. |
| Settings toggle | Out of scope. Ship enabled. |

## Data flow

```
sweep/citizen insert → vision.observations
                     → platform.tenant_visible_observations   (visibility moment)
                            └─ AFTER INSERT trigger (per row)
                                   → realtime.send(payload, 'observation_inserted',
                                                    'tenant:<tenant_id>', private=true)
                                                          │
   browser  supabase.channel('tenant:<id>', {private}) ───┘
            → buffer (~700ms) → group by sweep_id
                → toast(s) + set pulseIds + ONE debounced getObservations() refetch
```

The trigger hooks `tenant_visible_observations` (not `vision.observations`) because that
insert is the exact moment a pin becomes visible to a tenant and the row carries
`tenant_id`. A sweep batch = many `tvo` rows with the same `sweep_id` → many events the
client groups into one toast.

## DB component — migration `0301_observation_broadcast.sql`

### Trigger function `community.broadcast_observation()`
- `AFTER INSERT … FOR EACH ROW` on `platform.tenant_visible_observations`.
- Joins `vision.observations` (+ `observation_types`, geo binding for `zone`) to build a
  **lean** payload:
  ```json
  { "observation_id": "...", "slug": "pothole", "lat": 19.42, "lng": -99.13,
    "sweep_id": "...", "sweep": "SWP-9F2A", "zone": "Cuauhtémoc",
    "observed_at": "2026-06-21T..." }
  ```
- Calls `realtime.send(payload, 'observation_inserted', 'tenant:'||NEW.tenant_id::text, true)`.
- Body wrapped in `BEGIN … EXCEPTION WHEN OTHERS THEN RETURN NEW; END` so a Realtime
  failure can **never** block the underlying insert.
- `zone` may be `null` if priority/geo bindings land after the `tvo` row — acceptable
  (toast falls back to district/omits zone; the refetch fills styling later).

### Authorization (private channel)
- RLS read policy on `realtime.messages` allowing `authenticated` to **receive** where
  `realtime.topic() = 'tenant:' || public._app_tenant()::text`.
- Reuses the existing tenant resolver; double-guards the per-tenant scoping the trigger
  already applies (no cross-tenant leakage).
- Ensure RLS is enabled on `realtime.messages` and the policy is additive to anything
  Supabase ships. Guard the publication/realtime setup so the migration also applies on
  a DB without the default Supabase realtime objects (mirror the `0300` guard style).

## Client components

### `lib/observationsRealtime.ts`
`subscribeNewObservations(tenantId, onEvent): () => void`
- `await supabase.realtime.setAuth()` (private channels need the access token), then
  `supabase.channel('tenant:'+tenantId, { config: { private: true, broadcast: { self: false } } })`
  `.on('broadcast', { event: 'observation_inserted' }, ({ payload }) => onEvent(payload))`
  `.subscribe(status => …)`.
- Logs non-`SUBSCRIBED` statuses (`CHANNEL_ERROR`/`TIMED_OUT`) — private channels fail
  silently otherwise.
- Returns an unsubscribe that removes the channel.

### `lib/observationStream.ts`
- **Pure reducer** `groupEvents(buffer: ObservationEvent[]): ToastSpec[]` — the unit of
  testable logic:
  - 1 event → single toast `"Nueva observación · <label> en <zona>"`, target = point.
  - N events same `sweep_id` → aggregated `"N nuevas · barrido SWP-XXXX"`, target = bounds.
  - Mixed sweeps in one window → one toast per sweep group (+ a singles group).
- `useObservationStream({ tenantId, onRefetch, pushToast, setPulseIds })` hook:
  - Buffers incoming events, debounces ~700ms, runs `groupEvents`, pushes toasts, sets
    `pulseIds` (cleared after ~3s), and fires **one** `onRefetch()` per flush.
  - The authoritative `getObservations()` refetch makes the map self-healing against
    dropped/reconnected events.

### `components/ToastStack.tsx`
- Dependency-free, `Panel`/`Button`-styled stack, **bottom-right**, stacked above the
  zoom control. Each toast: message + **"Ver"** action + auto-dismiss (~8s) + manual ×.
- Verify it clears the AgentPanel; nudge offset if it collides.

### `MapCanvas.tsx`
- New `pulseIds: Set<string>` prop → a `pulse` layer group rendering an accent halo
  (CSS keyframe in `index.css`, ~3s) over the matching new pins.
- New `fitTarget: { points: {lat,lng}[]; n: number } | null` prop for the **batch "Ver"**
  → `fitBounds(points)` with the same panel-aware padding used by plan/sweep.
- **Single "Ver"** reuses the existing `panTarget` + `onSelect` (opens the card).

### `MapPage.tsx`
- Capture `tenant.id` (today only `accent` is kept from `getActiveTenant`).
- Subscribe via `useObservationStream` once `loaded`; clean up on unmount.
- Hold `toasts`, `pulseIds`, `fitTarget` state; wire toast "Ver" → single (`onSelect` +
  `panTarget`) or batch (`fitTarget`).
- The refetch reuses the existing `api.getObservations()` and folds results into the
  `observations` state.

## Error handling / edge cases

- **Insert safety:** trigger swallows its own errors; the write always commits.
- **Dropped / reconnect events:** the debounced authoritative refetch reconciles state;
  worst case a pin is delayed until the next event or a reload.
- **Duplicate events:** grouping + id-keyed refetch dedupe naturally.
- **Null `zone`:** toast falls back to district name or omits zone.
- **Cross-tenant:** trigger scopes by `NEW.tenant_id`; RLS double-guards on receive.
- **Auth on token refresh:** `setAuth()` is called at subscribe; on session refresh the
  channel is re-subscribed (handled by re-running the effect on session change).

## Testing

- **Unit:** `groupEvents` reducer — single, batch (one sweep), mixed sweeps, empty,
  debounce boundary.
- **DB (Supabase MCP):** as a tenant, insert a `tvo` row and assert a `realtime.messages`
  row lands on topic `tenant:<id>` (`realtime.send` writes there → directly assertable);
  assert another tenant's policy cannot read it.
- **Manual:** run the app, `INSERT` an observation (single and a multi-row sweep), confirm
  toast text, marker pulse, "Ver" behavior, and that the pin persists after the refetch.

## Out of scope

- A user-facing "live notifications" on/off toggle.
- Constructing a fully-styled pin from the broadcast payload (we refetch instead).
- Real-time for ROIs, plans, or runs — observations only.
```
