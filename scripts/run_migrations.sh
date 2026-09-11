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
#
# Production migration safety is enforced here, immediately before the first
# `alembic upgrade head`. The canonical prod launcher marks the compose
# migration service with MIGRATION_PRODUCTION_GATE=1; a prod API re-run also
# carries PKM_ENVIRONMENT=prod. Dev/test migrations do not enter this gate.
set -euo pipefail

run_production_migration_gate() {
  python - <<'PY'
import hashlib
import hmac
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from app.release_channels.cutover_readiness import (
    _load_migrations,
    _pending_migration_delta,
)
from app.release_channels.reversibility import (
    MigrationMarkerError,
    classify_migration,
)

ACK_PREFIX = "prod-migration-ack.v1:"
TARGET_IDENTITY = "pkm-prod/app"


def fail(reason: str) -> None:
    print(f"ERROR: production migration gate blocked: {reason}", file=sys.stderr)
    raise SystemExit(78)


target_identity = os.environ.get("MIGRATION_TARGET_IDENTITY") or TARGET_IDENTITY
if target_identity != TARGET_IDENTITY:
    fail(f"unexpected migration target identity {target_identity!r}")

dsn = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not dsn:
    fail("target database is unavailable")
if dsn.startswith("postgresql+psycopg://"):
    dsn = "postgresql://" + dsn.split("postgresql+psycopg://", 1)[1]
try:
    parsed_dsn = urlsplit(dsn)
    database_name = parsed_dsn.path.lstrip("/").split("?", 1)[0]
    database_endpoint = f"{parsed_dsn.hostname or ''}:{parsed_dsn.port or 5432}"
except ValueError:
    parsed_dsn = urlsplit("")
    database_name = ""
    database_endpoint = ""
if database_name != "app" or not parsed_dsn.hostname:
    fail("target database is not the canonical pkm-prod/app database")

current = subprocess.run(
    ["alembic", "-c", "app/alembic.ini", "current"],
    capture_output=True,
    text=True,
    check=False,
)
if current.returncode != 0:
    fail("could not resolve the current database revision")

migrations_dir = Path("app/alembic/versions")
try:
    migrations = _load_migrations(migrations_dir)
except (OSError, ValueError) as exc:
    fail(f"could not load the migration graph: {exc}")

current_revisions = tuple(
    dict.fromkeys(
        token
        for token in re.findall(r"[0-9A-Za-z_]+", current.stdout)
        if token in migrations
    )
)
if not current_revisions:
    fail("current database revision is unavailable")

try:
    delta = _pending_migration_delta(migrations_dir, current_revisions)
except MigrationMarkerError as exc:
    fail(f"unclassified pending migration: {exc}")
except (OSError, ValueError) as exc:
    fail(f"could not classify pending migrations: {exc}")

if delta.unreachable_detail is not None:
    fail(delta.unreachable_detail)
if not delta.pending:
    print("Production migration gate passed: database is at Alembic head.")
    raise SystemExit(0)

pending_classifications = [
    classify_migration(info.path).classification for info in delta.pending
]
if delta.forward_only:
    digest = hashlib.sha256()
    digest.update(b"agentic-pkm.prod-migration-decision.v1\n")
    digest.update(f"target={target_identity}\n".encode())
    digest.update(f"endpoint={database_endpoint}\n".encode())
    digest.update(f"current={','.join(current_revisions)}\n".encode())
    digest.update(f"heads={','.join(delta.head_revisions)}\n".encode())
    for info, classification in zip(delta.pending, pending_classifications):
        digest.update(
            f"migration={info.revision}\t{info.filename}\t{classification}\n".encode()
        )
        digest.update(info.path.read_bytes())
        digest.update(b"\n")
    expected_ack = f"{ACK_PREFIX}{digest.hexdigest()}"
    supplied_ack = os.environ.get("PROD_MIGRATION_FORWARD_ONLY_ACK", "").strip()
    if not supplied_ack:
        pending_names = ", ".join(info.filename for info in delta.forward_only)
        fail(
            "forward-only migration(s) require explicit acknowledgement; "
            f"set PROD_MIGRATION_FORWARD_ONLY_ACK={expected_ack} "
            f"for target {target_identity} ({pending_names})"
        )
    if not hmac.compare_digest(supplied_ack, expected_ack):
        fail(
            "forward-only acknowledgement does not match the current "
            "target/migration decision"
        )

    print("Production migration gate passed: target-bound forward-only acknowledgement accepted.")
else:
    print("Production migration gate passed: pending migrations are reversible.")
PY
}

if [[ "${MIGRATION_PRODUCTION_GATE:-0}" == "1" || "${PKM_ENVIRONMENT:-}" == "prod" ]]; then
  run_production_migration_gate
fi

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
