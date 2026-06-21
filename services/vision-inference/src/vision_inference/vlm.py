"""VLM call compartido por el gateway (Etapa 1) y el worker (Etapa 2).

Modos: 'flash'/'fast' -> 7B (frase natural rápida) ; 'thinking' -> 32B (frase rica).
Devuelve una FRASE en lenguaje natural (estilo banner del demo) = el 'body' del job.
"""
from __future__ import annotations

import base64
import os

import httpx

ENDPOINTS = {
    "fast": (os.environ.get("VLLM_FAST_URL", "http://127.0.0.1:8001/v1"),
             os.environ.get("VLLM_FAST_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"), 110),
    "thinking": (os.environ.get("VLLM_THINKING_URL", "http://127.0.0.1:8002/v1"),
                 os.environ.get("VLLM_THINKING_MODEL", "Qwen/Qwen2.5-VL-32B-Instruct"), 200),
}
# la tabla usa 'flash'; lo mapeamos a 'fast'
ALIAS = {"flash": "fast", "fast": "fast", "thinking": "thinking"}

PROMPT = (
    "Eres un inspector vial. Describe en UNA sola frase en español, en lenguaje natural, "
    "las anomalías visibles en la vía: baches, basura o residuos, alumbrado/luminarias, "
    "vendedores ambulantes, falta de señalización, pavimento dañado u obstrucciones. "
    "Menciona solo lo que realmente se ve. Responde únicamente con la frase, sin listas ni JSON."
)
_http = httpx.Client(timeout=180)


def describe(image_bytes: bytes, mode: str) -> str:
    m = ALIAS.get(mode, "fast")
    url, model, max_tok = ENDPOINTS[m]
    b64 = base64.b64encode(image_bytes).decode()
    payload = {"model": model, "max_tokens": max_tok, "temperature": 0.0,
               "messages": [{"role": "user", "content": [
                   {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                   {"type": "text", "text": PROMPT}]}]}
    r = _http.post(url.rstrip("/") + "/chat/completions", json=payload)
    r.raise_for_status()
    return " ".join(r.json()["choices"][0]["message"]["content"].split()).strip()
