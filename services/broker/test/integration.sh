#!/usr/bin/env bash
set -euo pipefail
BASE="${BROKER_URL:-http://localhost:8787}"
# Mint a member JWT for the seeded dev user.
TOK=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Content-Type: application/json" \
  -d "{\"email\":\"$BROKER_TEST_EMAIL\",\"password\":\"$BROKER_TEST_PASSWORD\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

code () { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# no bearer -> 401
[ "$(code "$BASE/api/r2/object?bucket=tenant-tiles&path=$TENANT_ID/bv/1/0.pbf")" = "401" ]
# unknown bucket -> 400
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=nope&path=x")" = "400" ]
# member + own tenant tiles, object absent -> 404 (authz PASSED)
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=tenant-tiles&path=$TENANT_ID/bv/1/0.pbf")" = "404" ]
# member + a foreign tenant -> 403 (authz DENIED)
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=tenant-tiles&path=00000000-0000-0000-0000-000000000000/bv/1/0.pbf")" = "403" ]
echo "broker integration OK"
