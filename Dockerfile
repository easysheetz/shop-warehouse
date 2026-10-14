# Obraz aplikacji – ten sam lokalnie (docker compose) i w Google Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY static ./static
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

# aplikacja nie działa jako root
RUN useradd --system --uid 10001 --no-create-home app && chmod +x scripts/entrypoint.sh
USER app

# Cloud Run podaje port w zmiennej PORT (domyślnie 8080); lokalnie 8000
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint.sh"]
