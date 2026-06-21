#!/usr/bin/env bash
# Serve BOTH Qwen-VL models on vLLM (OpenAI API), resident on the private GPU server.
# flash = 7B on :8001   |   thinking = 32B on :8002   (16GB + 64GB fit in 128GB unified)
set -euo pipefail
MODELS=/workspace/models

# flash (7B) — split GPU memory so both coexist
VLLM_LOGGING_LEVEL=WARNING vllm serve "$MODELS/Qwen2.5-VL-7B-Instruct" \
  --served-model-name Qwen/Qwen2.5-VL-7B-Instruct \
  --port 8001 --dtype bfloat16 --gpu-memory-utilization 0.18 \
  --limit-mm-per-prompt image=1 &

# thinking (32B)
VLLM_LOGGING_LEVEL=WARNING vllm serve "$MODELS/Qwen2.5-VL-32B-Instruct" \
  --served-model-name Qwen/Qwen2.5-VL-32B-Instruct \
  --port 8002 --dtype bfloat16 --gpu-memory-utilization 0.62 \
  --limit-mm-per-prompt image=1 &

wait
