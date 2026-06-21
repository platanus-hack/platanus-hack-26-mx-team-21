"""Etapa 2 — worker poller.

Bucle: toma jobs 'pending' de community.inference_jobs -> descarga imagen de R2 ->
VLM (flash/thinking) -> escribe response {"confirmed":true,"body":"<frase>"} y status='done'
(o status='error'). Cuando lleguen las indicaciones del webhook, el mismo process_job()
se reusa desde el handler HTTP.

Uso (con secretos):
  docker run --rm --network host --env-file anomaly_api/.env -v "$PWD:/workspace" -w /workspace \
    road-anomaly-zero-shot:moe bash -lc 'pip install -q boto3 supabase httpx; python anomaly_api/worker.py --once'
"""
from __future__ import annotations

import argparse
import time
import traceback

from . import r2, supa, vlm


def process_job(job: dict) -> str:
    img = r2.fetch(job["r2_url"])
    body = vlm.describe(img, job.get("thinking_mode", "flash"))
    supa.mark_done(job["id"], body)
    return body


def tick() -> int:
    jobs = supa.claim_pending(limit=1)
    for j in jobs:
        t = time.time()
        try:
            body = process_job(j)
            print(f"[done] {j['id']} ({j.get('thinking_mode')}, {time.time()-t:.1f}s): {body[:90]}", flush=True)
        except Exception as e:  # noqa: BLE001
            supa.mark_error(j["id"], f"{type(e).__name__}: {e}")
            print(f"[error] {j['id']}: {e}", flush=True)
            traceback.print_exc()
    return len(jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="procesa una tanda y sale")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()
    print("worker arrancado (Etapa 2)", flush=True)
    if args.once:
        n = tick(); print(f"procesados {n} jobs"); return
    while True:
        if tick() == 0:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
