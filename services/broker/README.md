# R2 Access Broker Worker

Python Cloudflare Worker that authorizes R2 object reads via Supabase RPC and streams bytes from R2.

## R2 Buckets

The broker manages access to the following R2 buckets:
- `sweep-video`: Video recordings (mp4, serves as `video/mp4`)
- `observation-thumbnails`: Observation thumbnail images (jpeg, serves as `image/jpeg`)
- `tenant-tiles`: Tenant vector tiles (pbf, serves as `application/octet-stream`)

## S3 Endpoint Note

When configuring S3 clients to interact with these buckets directly, use the Cloudflare R2 S3-compatible endpoint:
```
https://<account-id>.r2.cloudflarestorage.com
```

Authorization is delegated to Postgres via the Supabase RPC `public.app_authorize_object(p_bucket, p_path)`. The Worker forwards the caller's `Authorization` bearer token and the anon `apikey` to validate access before streaming from R2.

## Setup

1. **Set the Supabase anon key as a secret:**
   ```bash
   cd services/broker
   npx wrangler secret put SUPABASE_ANON_KEY
   ```
   Paste the project anon key from Supabase dashboard when prompted.

2. **Start the dev server with remote R2 bindings:**
   ```bash
   npx wrangler dev --remote
   ```
   Expected: dev server on `http://localhost:8787`.
   The `--remote` flag ensures R2 bindings hit the real buckets for testing.

## Running Integration Tests

Set environment variables and run the test script:
```bash
SUPABASE_URL=https://joixzhdpnxqhnuscxsoy.supabase.co \
SUPABASE_ANON_KEY=<your_anon_key> \
TENANT_ID=<seeded_tenant_uuid> \
BROKER_TEST_EMAIL=<dev_user_email> \
BROKER_TEST_PASSWORD=<dev_user_password> \
./test/integration.sh
```

Expected output: `broker integration OK` (proves authz works: 403 for foreign tenant, 404 for own tenant but absent object).

## Route

- `GET /api/r2/object?bucket=<id>&path=<path>` with `Authorization: Bearer <token>`

**Status codes:**
- `200`: Member authenticated, object exists, streamed with `Content-Type` and `Cache-Control`
- `206`: Member authenticated, object exists (partial), Range request fulfilled with `Content-Range`
- `401`: No bearer token
- `403`: Authorization denied by RPC
- `404`: Authorization passed, object not found
- `400`: Bad or unknown bucket, missing path
