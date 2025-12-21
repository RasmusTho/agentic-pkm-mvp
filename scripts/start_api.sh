#!/bin/bash
set -euo pipefail

if [[ -n "${DATABASE_URL:-}" ]]; then
  for attempt in $(seq 1 30); do
    if python - <<'PY'
import os
import sys
import psycopg

dsn = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not dsn:
    sys.exit(0)
if dsn.startswith("postgresql+psycopg://"):
    dsn = "postgresql://" + dsn.split("postgresql+psycopg://", 1)[1]
try:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
    then
      break
    fi
    sleep 1
  done
fi

if [[ -n "${DATABASE_URL:-}" ]]; then
  python - <<'PY'
import os
import psycopg

dsn = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not dsn:
    raise SystemExit()
if dsn.startswith("postgresql+psycopg://"):
    dsn = "postgresql://" + dsn.split("postgresql+psycopg://", 1)[1]
with psycopg.connect(dsn, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("create extension if not exists vector")
        cur.execute("create extension if not exists pgcrypto")
PY
fi

alembic -c app/alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
