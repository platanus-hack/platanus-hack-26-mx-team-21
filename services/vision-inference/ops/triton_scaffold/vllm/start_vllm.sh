#!/usr/bin/env bash
# Serve Qwen2.5-VL on vLLM (OpenAI-compatible API) on the private GPU server.
# Fastest practical VLM server: paged-KV, continuous batching, multimodal.
#
# Model choice (speed vs quality):
#   - Qwen2.5-VL-7B-Instruct        : ~1-2s/call, recommended for real-time cascade
#   - Qwen2.5-VL-7B-Instruct-AWQ    : 4-bit, even faster/less memory (needs aarch64 AWQ kernels)
#   - Qwen2.5-VL-32B-Instruct       : highest quality, ~slow; use only if latency allows
set -euo pipefail

MODEL="${VLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"   # or a local path under /models
PORT="${VLM_PORT:-8000}"
MAXLEN="${VLM_MAX_LEN:-8192}"
GPU_UTIL="${VLM_GPU_UTIL:-0.55}"   # leave room for Triton detector + Segformer on the shared 128GB

# vLLM auto-detects the multimodal Qwen2.5-VL architecture.
exec vllm serve "$MODEL" \
  --port "$PORT" \
  --dtype bfloat16 \
  --max-model-len "$MAXLEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --limit-mm-per-prompt image=1 \
  --served-model-name "$MODEL"
