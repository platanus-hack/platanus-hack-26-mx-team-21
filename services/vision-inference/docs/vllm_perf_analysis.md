# vLLM on our private GPU server — análisis, mediciones y plan de experimentos

Estado: servicio **fast-only** corriendo (Qwen2.5-VL-7B en vLLM, `vllm/vllm-openai` arm64,
puerto 8001) + gateway :8080. Todas las cifras de abajo son **medidas en nuestro servidor GPU**
salvo donde diga "estimado".

Nomenclatura: llamamos **Servidor A** a nuestro servidor actual (unificado, mucha memoria /
ancho de banda modesto) y **Servidor B** a un GPU privado alternativo de **alto ancho de banda**
(p.ej. **RTX PRO 6000 Blackwell**, o un A100/H100). El análisis es por *specs*, no por marca.

## 0. Hardware
| | Servidor A (actual, unificado) | Servidor B (alta-BW, p.ej. RTX PRO 6000) *(verificar specs)* |
|---|---|---|
| Memoria | **128 GB unificada** | ~96 GB GDDR7 |
| **Ancho de banda** | **~273 GB/s** | **~1.7–1.8 TB/s** (≈ **6–7×** Servidor A) |
| Cómputo | Blackwell, FP4/FP8 | Blackwell, FP4/FP8, más SMs |
| CPU/host | ARM64, memoria unificada | x86 host + PCIe |
| Fuerte en | **capacidad** (modelos grandes sin cuantizar) | **latencia** (decode bandwidth-bound) |

> Insight clave: el **decode** de un LLM es **memory-bandwidth-bound** (cada token lee TODOS
> los pesos). Por eso el ancho de banda manda en latencia single-stream. Servidor A = mucha
> memoria pero BW modesto; Servidor B = menos memoria pero ~6–7× BW.

## 1. Mediciones (Qwen2.5-VL, Servidor A)
| métrica | valor medido |
|---|---|
| 7B bf16 decode | **~15 tok/s por secuencia** (bandwidth-bound) |
| 7B latencia (1 img, salida corta) | ~1.3–2.6 s |
| 7B **secuencial** 50 frames distintos | ~130 s (2.6 s/img) |
| 7B **vLLM batch** 50 frames distintos | **~7.6 s → 6.6 img/s** (152 ms/img) → **~17×** |
| 7B batch, misma imagen (cache MM) | 15.5 img/s (cache hit, no representativo) |
| 7B "Maximum concurrency" (8k tok) | **34.6×** (reportado por vLLM) |
| 32B bf16 latencia (1 img) | ~34 s |
| 32B 50 frames secuencial | ~1700 s (~28 min) |
| 32B 50 frames batch | **~6–10 min estimado** (KV chico → baja concurrencia) |
| carga modelo (cold, disco) | 7B ~1.5 min · 32B ~5 min |

Videos previos (7B): testjun20_11 (~99 fr) 4.3 min→~15 s · cutmexico (~339 fr) 15 min→~51 s.

## 2. Memoria en vLLM (modelo mental)
`--gpu-memory-utilization X` **pre-reserva** la fracción X de VRAM **al arrancar**, repartida en:
- **Pesos** (residentes, fijos): 7B bf16 ≈ 15 GB · 32B bf16 ≈ 64 GB.
- **Overhead CUDA** (context, CUDA graphs): ~1–2 GB.
- **Pool KV cache** (todo el resto): pre-asignado pero **vacío hasta que hay requests**
  (`GPU KV cache usage: 0.0%` en idle).

Medido: 7B @util 0.20 → ~22 GB (15+2+5). 32B @util 0.55 → ~68 GB. Idle: GPU 0 %, 50 °C, 12 W.

## 3. Concurrencia: de qué depende
`concurrencia ≈ Pool_KV ÷ KV_por_secuencia`, donde:
1. **Pool_KV** = util×VRAM − pesos − overhead (más memoria libre → más secuencias).
2. **KV_por_secuencia** crece con **longitud de contexto** = texto **+ vision tokens**
   (imágenes grandes = más tokens = menos concurrencia → capar `max_pixels` ayuda).
3. **Tamaño del modelo** (pesos grandes dejan menos KV).
4. **Caps de config**: `--max-num-seqs`, `--max-num-batched-tokens`, `--max-model-len`.
5. **Techo de cómputo/BW del GPU**: prefill (visión) es compute-bound y batchea bien;
   decode es BW-bound y satura el throughput agregado.

## 4. Arquitectura de modelos en 1 GPU
- 1 servidor = **1 GPU**. Cargar N modelos **no añade cómputo** → "paralelo entre modelos" =
  **time-slicing** (no acelera, solo evita recargar). "Paralelo dentro de un modelo"
  (continuous batching) **sí acelera** (medido: 17×).
- **2 modelos + agentes paralelos por modelo > 5 modelos** compitiendo.
- Cabe: 1×32B(64GB)+1×7B(16GB)=80GB (+~40GB KV) ✅ sweet spot. 5×7B=75GB cabe pero KV
  starved + contención de cómputo ❌.
- Más *tipos* sin penalizar: **cuantizar (FP8/AWQ)** o **cargar bajo demanda** (swap).

---

# 5. EXPERIMENTOS (correr en paralelo)

Herramienta: `pipeline/bench_vllm.py` (barrido de concurrencia, mide QPS y p50/p95/p99).

## A. Caracterizar 1 servidor (línea base)
**A1 — Curva de saturación (knee):** throughput e latencia vs concurrencia.
```bash
python pipeline/bench_vllm.py --url http://127.0.0.1:8001/v1 --model Qwen/Qwen2.5-VL-7B-Instruct \
  --frames-dir <dir_50_frames> --concurrency 1 2 4 8 16 32 64 --max-tokens 40
```
Busca el **knee**: dónde el QPS deja de subir (saturación de cómputo/BW) y la p95 se dispara.
**A2 — SLA QPS:** el QPS máximo con **p95 < 4 s** (tu límite). Ese es el "QPS sostenible/servidor".
**A3 — Resolución × tokens:** repetir variando `--max-pixels` y `--max-tokens` (impacto en KV/latencia).
**A4 — 32B:** levantar 32B y repetir A1–A2 (esperado: knee a baja concurrencia por KV chico).

## B. ¿Justifica un 2º servidor (doble carga)?
Decisión = **demanda real (img/s)** vs **QPS sostenible/servidor** (de A2).
**B1 — Demanda:** estima/mide tu tasa de jobs (p.ej. de Supabase: jobs/min en hora pico).
**B2 — Headroom:** si `demanda_pico > QPS_sostenible × 0.7` → 1 servidor se satura → **2º servidor**.
**B3 — Réplica data-parallel (lo más simple):** 2 servidores = 2 réplicas detrás de un load balancer
  → **~2× throughput lineal**, misma latencia. Medir: correr A1 en cada servidor, sumar QPS.
**B4 — Colas:** medir crecimiento de cola (`Waiting reqs` en logs vLLM) bajo demanda real;
  si la cola crece sin acotar → falta capacidad → 2º servidor.
**B5 — Mix de modelos:** si necesitas fast+thinking+otros con carga simultánea y no caben/
  rinden en 1 servidor (sección 4) → 2º servidor dedicado por rol (1 = fast, 1 = thinking).

## C. vLLM multi-servidor vs un GPU de alto ancho de banda (el cuello es bandwidth)
**C1 — Roofline de decode:** mide tok/s/secuencia aquí (Servidor A ~15 tok/s 7B). Estima Servidor B:
  `tok/s_B ≈ tok/s_A × (BW_B / BW_A) ≈ 15 × (1800/273) ≈ ~98 tok/s` → **~6–7× menor
  latencia single-stream**. Verificar con un Servidor B real.
**C2 — Single-stream latency:** misma imagen, 1 request, p50/p95 en Servidor A vs Servidor B.
  (B gana fuerte por BW; clave si tu SLA es latencia por imagen.)
**C3 — Throughput batch:** QPS máx por dispositivo (A1) en Servidor A vs Servidor B. B suele ganar
  por BW+SMs, pero **96 GB < 128 GB** limita modelos grandes / pool KV.
**C4 — Multi-servidor tensor-parallel (TP):** servir UN modelo grande (p.ej. 70B) repartido en 2
  servidores con vLLM `--tensor-parallel-size 2` sobre el interconnect (RDMA). Mide si la latencia
  mejora o si el **interconnect** (mucho < NVLink) la mata. Esperado: TP entre servidores
  por red es **lento** (BW de red ≪ BW de memoria) → útil solo para *caber*, no para acelerar.
**C5 — Multi-servidor pipeline-parallel:** alternativa a TP para modelos que no caben; medir overhead.
**C6 — Costo/latencia/throughput:** tabla final
  - 1 Servidor A: 128 GB, BW bajo → capacidad alta, latencia lenta.
  - 2 Servidor A data-parallel: 2× throughput, **misma** latencia lenta.
  - 1 Servidor B: 96 GB, BW ~6–7× → latencia rápida; modelos >~70B necesitan cuantizar/2 GPUs.
  - 2 Servidor A TP (1 modelo grande): solo si no cabe en otra cosa; latencia limitada por red.

### Regla de decisión
- **Cuello = latencia por imagen (single-stream)** → **GPU de alto ancho de banda (Servidor B)** (BW manda) o cuantizar (FP8/AWQ) en Servidor A.
- **Cuello = volumen (muchas img/s, latencia tolerable)** → **batching** (gratis) y, si satura, **2º Servidor A data-parallel** (2× lineal, barato).
- **Cuello = caber un modelo enorme sin cuantizar** → la **128 GB unificada del Servidor A** es la ventaja; TP multi-servidor solo si ni así cabe.

## 6. Cómo correr varios experimentos en paralelo
- vLLM ya batchea: lanza A1/A3 con `--concurrency` alto desde una o varias máquinas a la vez.
- Para 2 modelos a la vez (fast+thinking), levanta ambos (sección 4) y apunta cada bench a su puerto.
- Mantén `nvidia-smi --query-compute-apps` y los logs vLLM (`Waiting reqs`, `KV cache usage`) abiertos para ver saturación.
