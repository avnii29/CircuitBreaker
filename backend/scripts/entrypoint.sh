#!/bin/sh
set -eu

echo "Running Alembic migrations..."
alembic upgrade head
echo "Migrations complete. Starting API on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
