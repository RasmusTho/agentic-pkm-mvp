#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: restore_drill.sh <empty-disposable-pgdata> <target-lsn>" >&2
  exit 64
fi

restore_data=$1
target_lsn=$2
if [[ ! "$target_lsn" =~ ^[0-9A-F]+/[0-9A-F]+$ ]]; then
  echo "target LSN must use canonical hexadecimal PostgreSQL syntax" >&2
  exit 64
fi
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX is required}"
: "${INDEPENDENT_AWS_ACCESS_KEY_ID_FILE:?independent object-store credential is required}"
: "${INDEPENDENT_AWS_SECRET_ACCESS_KEY_FILE:?independent object-store credential is required}"
: "${INDEPENDENT_WALG_LIBSODIUM_KEY_FILE:?independent recovery key is required}"
: "${BUILDEROPS_DATABASE_URL_FILE:?disposable database credential file is required}"
: "${BUILDEROPS_RECOVERY_ID:?BUILDEROPS_RECOVERY_ID is required}"
: "${BUILDEROPS_RESTORE_REPOSITORY:?repository identity is required}"
: "${BUILDEROPS_RESTORE_SENTINEL_RECORD_ID:?post-backup WAL sentinel identity is required}"

if [[ ${PRIMARY_HOST_SECRET_STORE_AVAILABLE:-0} != 0 ]]; then
  echo "restore drill must run with the primary host secret store unavailable" >&2
  exit 78
fi
if [[ -e "$restore_data" && -n "$(find "$restore_data" -mindepth 1 -print -quit)" ]]; then
  echo "restore target must be empty and disposable" >&2
  exit 73
fi
mkdir -p "$restore_data"

for secret_file in \
  "$INDEPENDENT_AWS_ACCESS_KEY_ID_FILE" \
  "$INDEPENDENT_AWS_SECRET_ACCESS_KEY_FILE" \
  "$INDEPENDENT_WALG_LIBSODIUM_KEY_FILE" \
  "$BUILDEROPS_DATABASE_URL_FILE"; do
  if [[ ! -r "$secret_file" ]]; then
    echo "independently held recovery material is unavailable" >&2
    exit 78
  fi
done

export AWS_ACCESS_KEY_ID="$(<"$INDEPENDENT_AWS_ACCESS_KEY_ID_FILE")"
export AWS_SECRET_ACCESS_KEY="$(<"$INDEPENDENT_AWS_SECRET_ACCESS_KEY_FILE")"
export WALG_LIBSODIUM_KEY="$(<"$INDEPENDENT_WALG_LIBSODIUM_KEY_FILE")"
export WALG_LIBSODIUM_KEY_TRANSFORM=base64
export AWS_ACCESS_KEY_ID_FILE="$INDEPENDENT_AWS_ACCESS_KEY_ID_FILE"
export AWS_SECRET_ACCESS_KEY_FILE="$INDEPENDENT_AWS_SECRET_ACCESS_KEY_FILE"
export WALG_LIBSODIUM_KEY_FILE="$INDEPENDENT_WALG_LIBSODIUM_KEY_FILE"

wal-g backup-fetch "$restore_data" LATEST
cat >>"$restore_data/postgresql.auto.conf" <<EOF
restore_command = '/bin/bash /app/scripts/builderops/wal_archive.sh fetch %f %p'
recovery_target_lsn = '$target_lsn'
recovery_target_action = 'promote'
EOF
touch "$restore_data/recovery.signal"

pg_ctl -D "$restore_data" -w start
cleanup() {
  pg_ctl -D "$restore_data" -m fast -w stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Resolve the disposable DSN only inside the verification child. The parent
# environment and receipt contain only the secret-file reference.
python - \
  "$target_lsn" \
  "$BUILDEROPS_RECOVERY_ID" \
  "$BUILDEROPS_RESTORE_REPOSITORY" \
  "$BUILDEROPS_RESTORE_SENTINEL_RECORD_ID" <<'PY'
import json
import os
import sys

import psycopg

from app.builderops.control_plane import PostgresBuilderOpsStore

target_lsn, recovery_id, repository, sentinel_record_id = sys.argv[1:]
database_url = open(os.environ["BUILDEROPS_DATABASE_URL_FILE"], encoding="utf-8").read().strip()
store = PostgresBuilderOpsStore(database_url)
epoch = store.activate_recovered_epoch(recovery_id=recovery_id, restored_lsn=target_lsn)
with psycopg.connect(database_url) as conn:
    replay = conn.execute(
        "SELECT COALESCE(pg_last_wal_replay_lsn(), pg_current_wal_lsn())::text AS replay_lsn, "
        "(COALESCE(pg_last_wal_replay_lsn(), pg_current_wal_lsn()) >= %s::pg_lsn) "
        "AS reached_target",
        (target_lsn,),
    ).fetchone()
    integrity = conn.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM builderops_outbox o "
        "LEFT JOIN builderops_tasks t ON t.repository=o.repository AND t.task_id=o.task_id "
        "WHERE t.task_id IS NULL)"
    ).fetchone()[0]
    sentinel = conn.execute(
        "SELECT 1 FROM builderops_records WHERE repository = %s AND record_id = %s",
        (repository.lower(), sentinel_record_id),
    ).fetchone()
if not replay[1] or not integrity or sentinel is None:
    raise SystemExit("restored database failed WAL or referential integrity verification")
state = store.recovery_state()
readiness = store.readiness()
print(json.dumps({
    "ok": True,
    "authority_epoch": epoch,
    "schema_version": readiness["schema_version"],
    "replay_lsn": replay[0],
    "counts": store.authority_counts(repository),
    "sentinel_record_id": sentinel_record_id,
    "reconciliation_required": state["reconciliation_required"],
    "executor_enabled": state["executor_enabled"],
}, sort_keys=True, default=str))
PY
