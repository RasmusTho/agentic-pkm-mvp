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
# `alembic upgrade head`. The production Compose overlay owns the gate binding
# for the canonical migrate service; a prod API re-run also carries
# PKM_ENVIRONMENT=prod. Dev/test migrations do not enter this gate. Deploys may
# invoke this script in gate-token-only mode before draining writers; that mode
# is a read-only token producer and must never reach Alembic.
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
token_only = os.environ.get("MIGRATION_GATE_TOKEN_ONLY") == "1"

try:
    delta = _pending_migration_delta(migrations_dir, current_revisions)
except MigrationMarkerError as exc:
    fail(f"unclassified pending migration: {exc}")
except (OSError, ValueError) as exc:
    fail(f"could not classify pending migrations: {exc}")

if delta.unreachable_detail is not None:
    fail(delta.unreachable_detail)
if not delta.pending:
    if token_only:
        fail("token-only migration probe found no pending migration")
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
    if token_only:
        print(expected_ack)
        raise SystemExit(0)
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
    if token_only:
        fail("token-only migration probe found no forward-only pending migration")
    print("Production migration gate passed: pending migrations are reversible.")
PY
}

# A non-production token-only invocation is not a migration producer. Preserve
# its existing no-op behavior without waiting for or touching a database. The
# production probe is handled after the readiness check below.
if [[ "${MIGRATION_GATE_TOKEN_ONLY:-0}" == "1" \
  && "${MIGRATION_PRODUCTION_GATE:-0}" != "1" \
  && "${PKM_ENVIRONMENT:-}" != "prod" ]]; then
  exit 0
fi

# Readiness and extension setup use the same effective DSN as the gate:
# DATABASE_URL takes precedence, with DB_DSN as the compatibility fallback.
if [[ -n "${DATABASE_URL:-${DB_DSN:-}}" ]]; then
  database_ready=0
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
      database_ready=1
      break
    fi
    sleep 1
  done
  if [[ "${database_ready}" != "1" ]]; then
    echo "ERROR: migration database readiness check failed after 30 attempts" >&2
    exit 78
  fi
fi

# The deploy channel producer uses the same target-bound gate before it stops
# runtime writers. A production token-only invocation is a read-only
# pre-cutover probe, but it must wait until the database is reachable before
# asking Alembic for its current revision. It exits before extension setup so
# the probe does not mutate the database.
if [[ "${MIGRATION_GATE_TOKEN_ONLY:-0}" == "1" ]]; then
  if [[ "${MIGRATION_PRODUCTION_GATE:-0}" == "1" || "${PKM_ENVIRONMENT:-}" == "prod" ]]; then
    run_production_migration_gate
  fi
  exit 0
fi

if [[ -n "${DATABASE_URL:-${DB_DSN:-}}" ]]; then
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

# Ordinary production startup runs this gate after extension setup and
# immediately before the first upgrade.
if [[ "${MIGRATION_PRODUCTION_GATE:-0}" == "1" || "${PKM_ENVIRONMENT:-}" == "prod" ]]; then
  run_production_migration_gate
fi

alembic -c app/alembic.ini upgrade head
