# Anomaly API — plan de arquitectura (Triton unificado + vLLM)

Servicio que recibe una imagen (link R2) y devuelve anomalías. Un cliente puede pedir:
- **baches** (detector) — cajas de potholes (modelo de segmentación pablo_v1) — opción rápida,
- **baches verificados** — detector + el VLM confirma (cascade interno),
- **análisis VLM** de la imagen (descripción + anomalías urbanas) con tres niveles:
  - **fast** → Qwen2.5-VL-**7B**
  - **thinking** → Qwen2.5-VL-**32B**
  - **reason** → *pendiente* (placeholder para un modelo con razonamiento nativo, p.ej. Qwen3-VL).

## Triton UNIFICADO (un solo front gRPC/HTTP)
Imagen **`tritonserver:*-vllm-py3`** (NGC) = trae Triton **+ vLLM backend** en su propio
entorno torch (aislado del `:moe` del detector). Modelos servidos:

```
TRITON (HTTP :8000 / gRPC :8001)  [imagen triton-vllm, torch propio]
 ├── qwen_fast        (vLLM backend, Qwen2.5-VL-7B)        modo fast
 ├── qwen_thinking    (vLLM backend, Qwen2.5-VL-32B)       modo thinking
 ├── qwen_reason      (vLLM backend, PENDIENTE)            modo reason (futuro)
 ├── pothole_detector (python backend: pablo_v1 seg + Segformer floor) -> cajas baches
 └── pothole_verified (BLS ensemble): pothole_detector -> por cada bache llama qwen_fast
                         para validar (¿bache real vs alcantarilla/sombra?) -> baches verificados
```

- **vLLM para los LLMs**: paged-KV, batching, **guided_json** (salida estructurada).
- **Triton mantiene los baches** (detector) y **valida internamente con vLLM** vía un modelo
  **BLS** (`pothole_verified`) que llama a `qwen_fast` dentro de Triton (cascade sin salir del server).
- **Gateway (FastAPI)** delgado al frente: ingesta (descarga R2), arma el prompt/imagen,
  enruta al modelo Triton pedido, parsea, responde; en Etapa 2 escribe a Supabase.

```
Supabase row (image_url R2) ──(webhook, Etapa 2)──► GATEWAY :8080
   POST /v1/analyze {image_url, task, mode, id}                │
     task = vlm | potholes | potholes_verified                ▼
                                          Triton (qwen_* / pothole_*)
                                                   │ JSON
        Etapa 1: responde  ·  Etapa 2: UPDATE fila id (description) ◄┘
```

## Aislamiento vLLM ↔ torch NGC (importante)
`pip install vllm` exige **torch 2.11 / torchvision 0.26**, que **reemplazarían** el torch
NGC `2.12.0a0+…nv26.05` (optimizado para el servidor GPU). Por eso:
- **NO se instala vLLM en `:moe`** (rompería el detector/CUDA).
- vLLM corre en la **imagen triton-vllm de NGC** (o `vllm/vllm-openai` aarch64), con su torch.
- El detector pesado puede seguir en `:moe`, **o** portarse al python-backend de la imagen
  triton-vllm (instalando ahí `ultralytics`+`transformers`, sin tocar `:moe`).
- Resultado: dos entornos torch separados, comunicados por gRPC/HTTP. Sin conflictos.

## ¿Por qué LocateAnything NO entró (aunque "ayudaría al bache")?
No fue solo por la segmentación; son varias razones, en orden:
1. **Ya hay un especialista mejor para detectar baches**: pablo_v1 / RDD2022 (YOLO) son
   detectores/segmentadores rápidos (ms/frame) y más precisos en pothole que un VLM
   zero-shot. LocateAnything-3B localiza por texto (lento, ~como un LLM).
2. **Calidad/estabilidad**: en nuestras pruebas LocateAnything dio cajas **degeneradas
   (runaway)** y resultados inestables; no apto como detector de producción.
3. **Redundancia con Qwen-VL**: para *razonar/verificar/describir* ya usamos Qwen2.5-VL
   7B/32B, **más capaz** que LocateAnything-3B. LocateAnything quedaba en tierra de nadie:
   peor que YOLO para detectar y peor que Qwen para razonar.
4. **Licencia**: LocateAnything es **research/non-commercial** → descartado para un servicio.
5. La segmentación del modelo de baches (máscaras finas del pavimento) es un **plus**
   adicional (mejor para el "floor"/cuadrícula), pero la razón principal es 1–4.
   → En cascade: **YOLO-seg detecta**, **Qwen-VL valida/describe**. LocateAnything no aporta
   sobre ese par.

## Modos LLM
| modo | modelo | uso | estado |
|---|---|---|---|
| **fast** | Qwen2.5-VL-7B | descripción/anomalías rápida | ✅ |
| **thinking** | Qwen2.5-VL-32B | razonamiento + más características | ✅ |
| **reason** | (Qwen3-VL / reasoning) | razonamiento nativo, cadena de pensamiento | ⏳ pendiente |

## Etapa 1 (ahora) / Etapa 2 (después)
- **Etapa 1**: `POST /v1/analyze` → descarga imagen → Triton (task+mode) → JSON estructurado.
  Tareas: `potholes` (solo detector), `potholes_verified` (detector+VLM), `vlm` (descripción).
- **Etapa 2**: webhook Supabase → mismo pipeline → `UPDATE fila id SET description=…`
  (supabase-py, R2, secretos por env, idempotencia con `status`, verificación de firma).

## RAG / técnicas gen-AI (sin fine-tune), por ROI
1. **guided_json / structured output** (vLLM) — JSON válido siempre. *Mayor ROI.*
2. **Prompt + taxonomía fija + few-shot** — categorías consistentes.
3. **RAG de taxonomía/normativa** (pgvector en Supabase) — criterios municipales al prompt.
4. **RAG visual / few-shot dinámico** (embeddings CLIP/SigLIP) — ejemplos similares.
5. **Dedup por embeddings + GPS** — agrupar anomalías repetidas.
6. **Cascade detector→VLM** (ya lo tenemos) — precisión sin entrenar el VLM.
### Alternativas a fine-tuning (si 1–3 no bastan): LoRA/QLoRA; cabezal clasificador sobre
embeddings. Recomendación: empezar sin fine-tune, medir por categoría, entrenar solo si se estanca.
