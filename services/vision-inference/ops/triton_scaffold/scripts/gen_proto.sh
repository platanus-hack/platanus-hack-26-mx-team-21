#!/usr/bin/env bash
# Generate gRPC stubs from proto/anomaly.proto into orchestrator/ (imported by server & client).
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc \
  -I proto \
  --python_out=orchestrator \
  --grpc_python_out=orchestrator \
  proto/anomaly.proto
echo "generated orchestrator/anomaly_pb2.py + anomaly_pb2_grpc.py"
