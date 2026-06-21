"""Anomaly API gateway — Stage 1 (ingest + process).

POST /v1/analyze {image_url, mode, id}
  1. download the image (R2 / any URL)
  2. build a multimodal prompt + JSON schema (guided decoding)
  3. route by mode: flash->7B, thinking->32B  (two vLLM OpenAI servers)
  4. return structured anomalies + a natural-language `description`

Stage 2 (Supabase/R2 webhook + row UPDATE) is stubbed at the bottom — not wired yet.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time

import httpx
from fastapi import FastAPI, HTTPException

from . import db
from .schemas import (FLASH_SCHEMA, THINKING_SCHEMA, AnalyzeRequest, AnalyzeResponse)

# LLM modes. fast=7B, thinking=32B, reason=PENDIENTE (futuro reasoning model, p.ej. Qwen3-VL).
# En "Triton unificado" estas URLs apuntan al endpoint OpenAI del vLLM-backend de Triton.
VLLM = {
    "fast": {"url": os.environ.get("VLLM_FAST_URL", "http://localhost:8001/v1"),
             "model": os.environ.get("VLLM_FAST_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
             "schema": FLASH_SCHEMA, "max_tokens": 320},
    "thinking": {"url": os.environ.get("VLLM_THINKING_URL", "http://localhost:8002/v1"),
                 "model": os.environ.get("VLLM_THINKING_MODEL", "Qwen/Qwen2.5-VL-32B-Instruct"),
                 "schema": THINKING_SCHEMA, "max_tokens": 700},
    # "reason": pendiente -> ver PLAN.md (Qwen3-VL / modelo con razonamiento nativo)
}

# fast = salida COMPACTA (latencia ~1s en el servidor GPU): claves cortas, sin descripción larga.
PROMPT_FLASH = (
    "Inspector vial. Devuelve SOLO JSON minificado, claves cortas, sin texto extra: "
    '{"p":true|false,"a":[["<tipo>","<low|med|high>"]]}. '
    'p=hay bache/pothole. a=lista (máx 4) de [tipo, severidad] de anomalías presentes; '
    "tipo ∈ pothole|basura|alumbrado|ambulantes|senal|pavimento|obstruccion. Nada más."
)
PROMPT_THINKING = (
    "Eres un inspector vial experto. Devuelve SOLO un objeto JSON con estas claves: "
    '{"description":"<resumen en español>", "pothole_present":true|false, '
    '"road_condition":"good|fair|poor|very_poor", "tags":["..."], '
    '"anomalies":[{"type":"...", "severity":"low|medium|high", "where":"<ubicación>", '
    '"evidence":"<qué se ve>", "confidence":0-1}]}. '
    "Reporta TODAS las anomalías urbanas (bache, basura, alumbrado, vendedores ambulantes, "
    "falta de señalización, pavimento dañado, obstrucciones). No escribas nada fuera del JSON."
)

app = FastAPI(title="Anomaly API", version="1.0")
_http = httpx.Client(timeout=180)
db.init()


def fetch_image_b64(url: str) -> str:
    try:
        r = _http.get(url, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"no se pudo descargar la imagen: {type(e).__name__}")
    if r.content[:3] not in (b"\xff\xd8\xff", b"\x89PN"):
        raise HTTPException(400, "el contenido no es JPEG/PNG")
    return base64.b64encode(r.content).decode()


def call_vllm(mode: str, image_b64: str) -> dict:
    cfg = VLLM[mode]
    prompt = PROMPT_THINKING if mode == "thinking" else PROMPT_FLASH
    payload = {
        "model": cfg["model"], "max_tokens": cfg["max_tokens"], "temperature": 0.0,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "response_format": {"type": "json_object"},   # JSON válido garantizado
    }
    r = _http.post(cfg["url"].rstrip("/") + "/chat/completions", json=payload)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.DOTALL)        # tolera fences markdown / texto extra
    if not m:
        return {"description": txt.strip()[:500], "anomalies": [], "pothole_present": False}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"description": txt.strip()[:500], "anomalies": [], "pothole_present": False}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    if req.mode == "reason":
        raise HTTPException(501, "modo 'reason' pendiente (ver PLAN.md): requiere modelo con razonamiento nativo")
    if req.mode not in VLLM:
        raise HTTPException(400, "mode debe ser 'fast' | 'thinking' | 'reason'")
    # task 'potholes'/'potholes_verified' -> Triton pothole_detector / pothole_verified (BLS).
    # En Etapa 1 implementamos el camino VLM; el detector se conecta vía Triton (ver PLAN.md).
    t0 = time.perf_counter()
    img = fetch_image_b64(req.image_url)
    data = call_vllm(req.mode, img)
    dt = int((time.perf_counter() - t0) * 1000)
    # normaliza: fast usa formato compacto {"p":bool,"a":[[tipo,sev],...]}; thinking usa el rico
    if "a" in data or "p" in data:
        anomalies = []
        for x in data.get("a", []):
            if isinstance(x, (list, tuple)) and x:
                anomalies.append({"type": str(x[0]),
                                  "severity": (str(x[1]) if len(x) > 1 else "low")})
            elif isinstance(x, str):
                anomalies.append({"type": x, "severity": "low"})
        description = ", ".join(a["type"] for a in anomalies) or "sin anomalías evidentes"
        road_condition, tags, pothole = None, [], bool(data.get("p", False))
    else:
        anomalies = data.get("anomalies", [])
        description = data.get("description", "")
        road_condition = data.get("road_condition")
        tags = data.get("tags", [])
        pothole = bool(data.get("pothole_present", False))
    resp = AnalyzeResponse(
        id=req.id, model=VLLM[req.mode]["model"], mode=req.mode, latency_ms=dt,
        description=description, anomalies=anomalies,
        road_condition=road_condition, tags=tags, pothole_present=pothole,
    )
    # MVP: persist to local DB (Stage 2 -> Supabase UPDATE by id)
    db.save({"id": req.id, "image_url": req.image_url, "task": req.task, **resp.model_dump()})
    return resp


@app.get("/results")
def results(limit: int = 20):
    import sqlite3
    con = sqlite3.connect(db.DB_PATH); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT rowid,* FROM results ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()]
    con.close()
    return {"count": len(rows), "results": rows}


@app.get("/healthz")
def healthz():
    out = {"modes": {}}
    for m, cfg in VLLM.items():
        try:
            ok = _http.get(cfg["url"].rstrip("/") + "/models", timeout=5).status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
        out["modes"][m] = {"url": cfg["url"], "model": cfg["model"], "up": ok}
    return out


# ----------------- Stage 2 (stub, not wired) -----------------
# @app.post("/v1/webhook/supabase")
# def supabase_webhook(payload: dict):
#     rec = payload["record"]; res = analyze(AnalyzeRequest(image_url=rec["image_url"],
#                                                           mode=payload.get("mode","flash"), id=rec["id"]))
#     supabase.table(TABLE).update({"description": res.description, "anomalies": [a.dict() for a in res.anomalies],
#                                   "status": "done"}).eq("id", rec["id"]).execute()
#     return {"ok": True}
