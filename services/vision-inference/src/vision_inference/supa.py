"""Cliente Supabase para la tabla community.inference_jobs (Etapa 2).

Tabla:
  id uuid, r2_url text, thinking_mode in ('flash','thinking'),
  status in ('pending','processing','done','error'),
  response jsonb, error text, observation_id uuid, created_at, updated_at

Contrato de salida (lo que escribimos):
  done  -> status='done',  response={"confirmed": true, "body": "<frase>"}
  error -> status='error', error="<mensaje>"
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from supabase import Client, create_client

SCHEMA = os.environ.get("SUPABASE_SCHEMA", "community")
TABLE = os.environ.get("SUPABASE_TABLE", "inference_jobs")

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return _client


def _tbl():
    return client().schema(SCHEMA).table(TABLE)


def claim_pending(limit: int = 1) -> list[dict]:
    """Toma jobs 'pending' y los marca 'processing' (lock optimista por id)."""
    rows = (_tbl().select("*").eq("status", "pending")
            .order("created_at").limit(limit).execute().data or [])
    claimed = []
    for r in rows:
        upd = (_tbl().update({"status": "processing", "updated_at": _now()})
               .eq("id", r["id"]).eq("status", "pending").execute().data)
        if upd:
            claimed.append(upd[0])
    return claimed


def mark_done(job_id: str, body: str):
    _tbl().update({"status": "done",
                   "response": {"confirmed": True, "body": body},
                   "updated_at": _now()}).eq("id", job_id).execute()


def mark_error(job_id: str, message: str):
    _tbl().update({"status": "error", "error": message[:500], "updated_at": _now()}
                  ).eq("id", job_id).execute()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
