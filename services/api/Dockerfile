# citycrawl-api — single image, one Uvicorn worker. The dataset stack (pandas/pyarrow/
# shapely/scikit-learn/geo) ships in the image but is imported lazily at request time, so
# planning/LLM requests stay light within the 1 GB Machine budget.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

# Runtime libs needed by shapely/pyproj/psycopg wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

EXPOSE 8080

# One worker on 0.0.0.0:8080 (matches fly.toml internal_port and the health check).
CMD ["uvicorn", "citycrawl_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
