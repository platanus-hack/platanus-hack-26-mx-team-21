# whatsapp-controller

Kapso WhatsApp integration **controller**: turns citizen pothole/anomaly reports
(a **photo** + a **location pin** sent over WhatsApp) into **citizen observations**
by calling the write API. It is a pure WhatsApp adapter — it holds Kapso credentials
and conversation state, but **no R2 or DB write credentials**.

```
 WhatsApp user ──photo──▶ Kapso ──webhook──▶  whatsapp-controller  ── multipart ──▶  WRITE API ──▶ Postgres + R2
       ▲          ──pin──▶          (this service)                  /intake/...        observation + thumbnail
       └────────────── reply ───────────────────┘                                          │
                                                                                            ▼
                                                                          validation service (separate, later)
```

See the design + cross-team contract:
[`docs/superpowers/specs/2026-06-20-whatsapp-citizen-reports-design.md`](../../docs/superpowers/specs/2026-06-20-whatsapp-citizen-reports-design.md).

## What it does

- Receives Kapso webhooks (`POST /webhook`), verifies the signature, dedupes retries.
- Runs a **two-message intake** state machine per sender (WhatsApp strips EXIF GPS,
  so a photo alone is unplaceable — we require a shared location pin):

  ```
  IDLE ──image──▶ AWAITING_LOCATION ──location──▶ SUBMIT
  IDLE ──location▶ AWAITING_PHOTO   ──image─────▶ SUBMIT
  ```

- On SUBMIT: downloads the image bytes from Kapso and POSTs the report to the write API.
- Replies to the citizen in Spanish at each step.

Parsing handles **both** webhook shapes: the Kapso platform envelope
(`{ type: "whatsapp.message.received", data: [...] }`) and a raw Meta Graph payload
(unwrapped via the SDK's `normalizeWebhook`).

## Run

```bash
cp .env.example .env       # fill in Kapso sandbox ids
npm install
npm run dev                # tsx watch, http://localhost:8080
```

Until the write API exists, leave `WRITE_API_MODE=dry-run`: the controller logs the
would-be call and returns a synthetic observation id, so the full WhatsApp round-trip
is testable now. Flip to `WRITE_API_MODE=http` + `WRITE_API_BASE_URL` when the endpoint lands.

Point the Kapso webhook at `https://<public-host>/webhook` (use a tunnel such as
`cloudflared`/`ngrok` for local dev). Health check: `GET /health`.

### Offline smoke test

```bash
npx tsx scripts/smoke.ts   # drives the parser + state machine with fake Kapso I/O
```

## Configuration

| Var | Default | Notes |
|---|---|---|
| `PORT` | `8080` | |
| `KAPSO_API_KEY` | — | Kapso API key (send replies, download media) |
| `KAPSO_PHONE_NUMBER_ID` | — | sandbox phone number id |
| `KAPSO_BASE_URL` | `https://api.kapso.ai/meta/whatsapp` | Kapso proxy base |
| `KAPSO_VERIFY_TOKEN` | — | echoed on the `GET /webhook` handshake |
| `KAPSO_WEBHOOK_SECRET` | — | HMAC secret; empty = skip verify (sandbox) |
| `KAPSO_SIGNATURE_HEADER` | `x-hub-signature-256` | header carrying the signature |
| `KAPSO_SIGNATURE_REQUIRED` | `false` | set `true` in prod |
| `WRITE_API_MODE` | `dry-run` | `dry-run` \| `http` |
| `WRITE_API_BASE_URL` | — | required when `http` |
| `WRITE_API_TOKEN` | — | bearer token for the write API |
| `DEFAULT_OBSERVATION_TYPE` | `pothole` | observation type slug |
| `SESSION_TTL_MINUTES` | `15` | how long a half-finished report waits |

## The write-API contract (implemented in `services/api`)

```
POST {WRITE_API_BASE_URL}/v1/observations/citizen
Content-Type: multipart/form-data
X-Operator-Key: {WRITE_API_TOKEN}     # == citycrawl-api OPERATOR_API_KEY

fields:
  reporter_wa_id    string   reporter phone/wa id (provenance)
  observation_type  string   e.g. "pothole"
  lat, lng          float    the shared pin
  observed_at       ISO-8601 photo capture time
  caption           string?  optional
  kapso_message_id  string   the image's WhatsApp message id
  image             file     the photo bytes

→ 200 application/json   { "observationId", "inBoundary", "thumbnailPath" }
```

The API (`citycrawl_api.routers.observations`) owns the write side: create the
`whatsapp-citizen` source + a synthetic sweep, insert `vision.observations`
(`detector_name='whatsapp-citizen'`), store the photo in the `observation-thumbnails`
bucket at `observations/{id}/report.jpg` + link the `vision.observation_thumbnails` row,
emit the `observation_inserted` outbox event, and **make it visible**
(`platform.rebuild_tenant_visible`). The controller reads both `camelCase`/`snake_case`
response keys.

## Deploy (Fly.io)

```bash
cd services/whatsapp-controller
fly launch --no-deploy --copy-config --name citycrawl-whatsapp   # first time only
fly secrets set \
  KAPSO_API_KEY=… \
  KAPSO_PHONE_NUMBER_ID=597907523413541 \
  WRITE_API_TOKEN=<citycrawl-api OPERATOR_API_KEY>
fly deploy
```

Non-secret config (write-API URL, Kapso base, signature header) is in `fly.toml`. The app is
**always-on** (`min_machines_running=1`, `auto_stop_machines="off"`) because webhooks must be
answered instantly and sessions are in-memory. After deploy, **re-register the Kapso webhook**
to `https://citycrawl-whatsapp.fly.dev/webhook` (the cloudflared tunnel is dev-only). To turn
on signature verification, set `KAPSO_WEBHOOK_SECRET` to the webhook's `secret_key` and flip
`KAPSO_SIGNATURE_REQUIRED=true` — only after confirming Kapso's `x-webhook-signature` scheme.

## Limitations / next steps

- Sessions and idempotency are **in-memory** (single instance). Swap `SessionStore` /
  `DedupeStore` for Postgres/Redis to survive restarts and scale out.
- Observation type defaults to `pothole`. Add an interactive button step to let the
  reporter pick the type.
- Confirm the Kapso webhook signature scheme against the dashboard and set
  `KAPSO_WEBHOOK_SECRET` / `KAPSO_SIGNATURE_HEADER` accordingly.
