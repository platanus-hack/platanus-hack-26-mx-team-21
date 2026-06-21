"""Queries READ-ONLY a community.inference_jobs (Etapa 2).

Requiere que el esquema 'community' esté EXPUESTO en Supabase (Settings → API → Exposed
schemas), si no devuelve PGRST106.

Uso:
  python anomaly_api/query_jobs.py            # resumen por status + últimos 10
  python anomaly_api/query_jobs.py --status pending
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from supabase import create_client

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
SCHEMA = os.environ.get("SUPABASE_SCHEMA", "community")
TABLE = os.environ.get("SUPABASE_TABLE", "inference_jobs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default=None)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    sb = create_client(URL, KEY)
    try:
        q = sb.schema(SCHEMA).table(TABLE).select("id,status,thinking_mode,r2_url,created_at")
        if args.status:
            q = q.eq("status", args.status)
        rows = q.order("created_at", desc=True).limit(args.limit).execute().data or []
        allrows = sb.schema(SCHEMA).table(TABLE).select("status").execute().data or []
        print("por status:", dict(Counter(r["status"] for r in allrows)), f"(total {len(allrows)})")
        for r in rows:
            print(f"  {r['id'][:8]} {r['status']:<10} {r.get('thinking_mode'):<8} {str(r.get('r2_url'))[:60]}")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        print("Si es PGRST106: exponer el esquema 'community' en Supabase (Settings → API).")
        sys.exit(1)


if __name__ == "__main__":
    main()
