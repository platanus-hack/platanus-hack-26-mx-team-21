# WhatsApp Citizen Reports (Kapso) — Design

**Date:** 2026-06-20
**Status:** In implementation (controller built; write API pending)
**Component:** Citizen-report ingestion — a new observation source fed from WhatsApp via Kapso

---

## 1. Scope

Let citizens report potholes / urban anomalies by sending a **photo** and a **location**
over WhatsApp. The report becomes a **citizen observation** on the city priority map,
to be validated later by a separate service.

This spec covers the **Kapso integration controller** (built, `services/whatsapp-controller`)
and the **contract** it depends on from the write API (owned by another stream). It does
**not** redefine the observation contract (`2026-06-20-observation-contract-design.md`) or
the storage contract (`supabase/STORAGE.md`) — it reuses them.

## 2. Decisions (settled)

| Decision | Choice |
|---|---|
| Image storage | Reuse the `observation-thumbnails` R2 bucket (`observations/{id}/report.jpg`) — renders in the existing detail panel, no broker change |
| Trust model | **Direct insert** as a citizen observation; a separate validation service verifies later (enrichment keyed on `observation.id`) — no human-review staging in the controller |
| Location | **Require a WhatsApp location pin** (EXIF is stripped from in-chat photos), joined to the photo per sender |
| Responsibility split | Controller = WhatsApp adapter (Kapso creds + conversation state); write API = all R2/DB mutations |

## 3. Architecture

```
 WhatsApp user ──photo──▶ Kapso ──webhook──▶  CONTROLLER  ── multipart ──▶  WRITE API  ──▶ Postgres + R2
       ▲          ──pin──▶        (this repo)               /intake/...       observation + thumbnail
       └────────────── reply ──────────────────┘                                  │
                                                                                  ▼
                                                                   VALIDATION SERVICE (separate, later)
```

Credential domains stay isolated: **Kapso keys** live only in the controller, **R2 + DB
write keys** live only in the write API.

## 4. Intake state machine (controller)

WhatsApp delivers the photo and the pin as **separate messages**. The controller keeps a
short-lived session per sender and submits once both parts are present.

```
IDLE ──image──▶ AWAITING_LOCATION ──location──▶ SUBMIT
IDLE ──location▶ AWAITING_PHOTO   ──image─────▶ SUBMIT
```

- Order-independent; session TTL ~15 min; one photo per report (v1).
- **Idempotency:** dedupe on the inbound WhatsApp message id; the write API dedupes on
  `kapso_message_id` (the image's message id).
- **Webhook parsing** tolerates both the Kapso platform envelope
  (`{type:"whatsapp.message.received", data:[…]}`, fields `message_type`, `media_data`,
  `message_type_data`) and a raw Meta Graph payload (`normalizeWebhook`).
- **Media bytes:** fetched from Kapso's mirrored `media_data.url` (auth header applied by
  the SDK's `client.fetch`), or `media.download({mediaId, phoneNumberId})` as fallback.
- **Signature:** HMAC-SHA256 over the raw body vs `KAPSO_WEBHOOK_SECRET` (header
  configurable; skipped when no secret, for sandbox bring-up).

## 5. Write-API contract (what the API stream must build)

```
POST {WRITE_API_BASE_URL}/intake/citizen-observation   (multipart/form-data)
  reporter_wa_id, observation_type, lat, lng, observed_at, caption?, kapso_message_id, image
→ 200 { observation_id, in_boundary?, thumbnail_path? }   // idempotent on kapso_message_id
```

The API performs, in one unit:

1. Resolve/create `vision.sources` slug `whatsapp-citizen`.
2. Create a synthetic `vision.sweeps` row (coverage = small buffer around the point;
   `sweep_assessed_types` = the reported type).
3. Insert `vision.observations`: `location`=pin, `observed_at`, `detector_name='whatsapp-citizen'`,
   `detector_version='1'`, `recording_id`/`media_offset_ms`=null.
4. Store the photo in `observation-thumbnails` at `observations/{id}/report.jpg`; insert the
   `vision.observation_thumbnails` row (`status='ready'`).
5. Emit `vision.vision_outbox_events` (`event_kind='observation_inserted'`).
6. **Make it visible:** compute `geo.observation_geo_bindings` and insert into
   `platform.tenant_visible_observations` for the containing tenant.

### Known risk (must be owned by the write API)

Today only a **full** `platform.rebuild_tenant_visible()` exists (no incremental insert) and
**no worker consumes the outbox queues**. Unless step 6 explicitly adds the new row, a
citizen observation will be created but **won't render on the map**. This is the single
biggest integration dependency.

## 6. Validation service (separate, later)

Reads citizen observations (`detector_name='whatsapp-citizen'` / source) and writes a verdict
as an enrichment keyed on `observation.id` — same "facts here, judgments elsewhere" pattern
as priority. Out of scope for the controller.

## 7. Status

- **Built:** `services/whatsapp-controller` — webhook receive/verify/dedupe, dual-shape
  parsing, state machine, Kapso media download, Spanish replies, `dry-run` + `http` write
  modes, offline smoke test. Typechecks; HTTP + state-machine smoke-tested.
- **Pending:** the write API endpoint (§5); confirm the Kapso webhook signature scheme;
  optional interactive type-picker; durable session/dedupe store for multi-instance.
