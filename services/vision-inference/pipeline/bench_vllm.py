"""Barrido de concurrencia para vLLM (mide QPS y p50/p95/p99 por nivel).

Úsalo para los experimentos A1/A2/A3 de docs/vllm_perf_analysis.md:
  python pipeline/bench_vllm.py --url http://127.0.0.1:8001/v1 \
    --model Qwen/Qwen2.5-VL-7B-Instruct --frames-dir /tmp/frames \
    --concurrency 1 2 4 8 16 32 64 --max-tokens 40 --requests 64

- --frames-dir: carpeta con .jpg distintas (evita el cache de imagen → cifras reales).
  Si faltan, repite las que haya (marcado en la salida).
- Imprime, por nivel de concurrencia: QPS, p50/p95/p99 y throughput agregado.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPT = ('Inspector vial. SOLO JSON: {"p":true|false,"a":[["tipo","sev"]]}. Anomalías urbanas.')


def load_imgs(d, need):
    files = sorted(glob.glob(f"{d}/*.jpg"))
    if not files:
        raise SystemExit(f"no .jpg en {d}")
    return [files[i % len(files)] for i in range(need)], len(files)


def call(url, model, b64, max_tokens):
    pl = {"model": model, "max_tokens": max_tokens, "temperature": 0.0,
          "messages": [{"role": "user", "content": [
              {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
              {"type": "text", "text": PROMPT}]}]}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(pl).encode(), headers={"content-type": "application/json"})
    t = time.time()
    urllib.request.urlopen(req, timeout=600).read()
    return time.time() - t


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16, 32])
    ap.add_argument("--requests", type=int, default=64)
    ap.add_argument("--max-tokens", type=int, default=40)
    args = ap.parse_args()
    files, uniq = load_imgs(args.frames_dir, args.requests)
    b64s = [base64.b64encode(open(f, "rb").read()).decode() for f in files]
    print(f"modelo={args.model}  imgs únicas={uniq}  requests/nivel={args.requests}")
    # warmup
    call(args.url, args.model, b64s[0], args.max_tokens)
    print(f"{'conc':>5} {'QPS':>7} {'p50':>7} {'p95':>7} {'p99':>7} {'wall':>7}")
    for c in args.concurrency:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=c) as ex:
            lat = list(ex.map(lambda b: call(args.url, args.model, b, args.max_tokens), b64s))
        wall = time.time() - t0
        print(f"{c:>5} {len(lat)/wall:>7.1f} {pct(lat,.5):>7.2f} {pct(lat,.95):>7.2f} "
              f"{pct(lat,.99):>7.2f} {wall:>7.1f}")


if __name__ == "__main__":
    main()
