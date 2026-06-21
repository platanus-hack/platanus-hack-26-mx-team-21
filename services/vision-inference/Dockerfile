# Gateway/worker/listener (lightweight — no GPU, no model weights here).
# The VLM runs in a separate vLLM container/host; this service only orchestrates.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# install deps first for layer caching, then the package itself.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 8080
# default: API gateway (Stage 1). For Stage 2: python -m vision_inference.worker / .listener
CMD ["uvicorn", "vision_inference.app:app", "--host", "0.0.0.0", "--port", "8080"]
