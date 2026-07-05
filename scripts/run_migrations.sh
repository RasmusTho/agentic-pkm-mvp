#!/bin/bash
# Single migration authority for container stacks (KERNEL-05, #2850).
#
# Waits for the configured Postgres, creates the extensions the migration
# lineage needs (`vector` for the 202510241200 `embedding VECTOR` column,
# `pgcrypto` for gen_random_uuid defaults), then runs `alembic upgrade head`.
#
# Producers:
# - compose `migrate` one-shot service (docker-compose.yaml): worker/watcher/api
#   gate on its successful completion (`service_completed_successfully`), so no
#   runtime container boots against an unmigrated database.
# - scripts/start_api.sh: calls this before uvicorn, keeping non-compose
#   (bare-metal) API starts migration-covered. Under compose this re-run is an
#   idempotent no-op because the migrate service already completed —
#   `depends_on` ordering serializes the two alembic invocations.
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
