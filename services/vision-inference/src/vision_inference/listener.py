"""Realtime listener para community.inference_jobs (Etapa 2 — READ ONLY por ahora).

Escucha INSERTs con status=pending y SOLO los imprime (no descarga, no procesa, no escribe).
Cuando el equipo confirme, se activa el procesamiento con --process (llama al worker).

Requisitos del lado Supabase (config del equipo):
  - Realtime habilitado para la tabla community.inference_jobs (publication supabase_realtime).
  - (para queries REST) esquema 'community' expuesto en Project Settings → API.

Uso:
  docker run --rm --network host --env-file anomaly_api/.env -v "$PWD:/workspace" -w /workspace \
    road-anomaly-zero-shot:moe bash -lc 'pip install -q supabase; python anomaly_api/listener.py'
  # procesar de verdad (cuando esté listo):  ... python anomaly_api/listener.py --process
"""
from __future__ import annotations

import argparse
import asyncio
import os

from supabase import acreate_client

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_SERVICE_KEY"]
SCHEMA = os.environ.get("SUPABASE_SCHEMA", "community")
TABLE = os.environ.get("SUPABASE_TABLE", "inference_jobs")


def _record(payload):
    # el formato varía por versión de realtime-py
    for path in ("data", "new", "record"):
        v = payload.get(path) if isinstance(payload, dict) else None
        if isinstance(v, dict):
            return v.get("record") or v.get("new") or v
    return payload


async def main(process: bool):
    sb = await acreate_client(URL, KEY)
    print(f"conectado a {URL}  (process={process})", flush=True)

    def on_insert(payload):
        rec = _record(payload) or {}
        jid = rec.get("id"); mode = rec.get("thinking_mode"); url = rec.get("r2_url")
        print(f"[INSERT pending] id={jid} mode={mode} r2={str(url)[:70]}", flush=True)
        if process:
            # Etapa 2 activa: descarga R2 + VLM + update (worker.process_job)
            from . import supa, worker  # noqa
            try:
                claimed = supa.claim_pending(limit=5)  # reclama y procesa pendientes
                for j in claimed:
                    worker.process_job(j)
            except Exception as e:  # noqa: BLE001
                print(f"  process error: {type(e).__name__}: {e}", flush=True)

    ch = sb.channel(f"{TABLE}_listener")
    await ch.on_postgres_changes("INSERT", schema=SCHEMA, table=TABLE,
                                 filter="status=eq.pending", callback=on_insert).subscribe()
    print(f"SUSCRITO a {SCHEMA}.{TABLE} INSERT status=pending — escuchando…", flush=True)
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", action="store_true", help="procesar (descarga+VLM+update). default: READ ONLY")
    args = ap.parse_args()
    asyncio.run(main(args.process))
