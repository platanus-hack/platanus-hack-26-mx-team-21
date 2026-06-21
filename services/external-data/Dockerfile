FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV STORAGE_BACKEND=r2
ENTRYPOINT ["external-data"]
CMD ["--help"]
