# storage-daemon-cli берём из официального образа TON: у демона нет HTTP API,
# и backend управляет им через эту утилиту по управляющему порту.
FROM ghcr.io/ton-blockchain/ton:latest AS ton

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# каталоги создаём до монтирования томов: Docker наследует владельца
# из образа, иначе новый том достаётся root, а сервис работает не под ним
RUN useradd -m appuser && mkdir -p /data/sites /data/uploads && chown -R appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# Образ без утилиты storage-daemon-cli: для машин, где TON Storage не поднимается
# (тогда TON_STORAGE_MODE=local). Экономит полтора гигабайта — образ ton не тянется.
FROM base AS lite

# Полный образ: по умолчанию собирается он.
FROM base AS full
COPY --from=ton /usr/local/bin/storage-daemon-cli /usr/local/bin/storage-daemon-cli
