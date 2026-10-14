#!/bin/sh
# Start kontenera.
#   RUN_MIGRATIONS=true  – najpierw `alembic upgrade head` (lokalnie w docker compose).
#   W chmurze migracje uruchamia osobne zadanie przed wdrożeniem nowej wersji,
#   więc tam zostawiamy RUN_MIGRATIONS=false.
#   Polecenie `migrate` uruchamia tylko migracje (dla zadania Cloud Run Job).
set -e

if [ "$1" = "migrate" ]; then
  exec alembic upgrade head
fi

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*" "$@"
