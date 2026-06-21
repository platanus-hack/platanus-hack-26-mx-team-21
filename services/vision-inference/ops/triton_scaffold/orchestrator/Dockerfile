# Lightweight orchestrator (no model weights — it only calls Triton + vLLM).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
# stubs are generated at build time from the mounted proto (or pre-generated via gen_proto.sh)
CMD ["python", "server.py"]
