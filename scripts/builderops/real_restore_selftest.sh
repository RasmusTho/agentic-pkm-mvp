#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: real_restore_selftest.sh <control-plane-image> <postgres-walg-image>" >&2
  exit 64
fi
control_image=$1
postgres_image=$2
command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 69; }

test_root="$(mktemp -d "${TMPDIR:-/tmp}/builderops-real-restore.XXXXXX")"
run_suffix="${$}-$(date +%s)"
network="builderops-restore-test-${run_suffix}"
primary="builderops-primary-${run_suffix}"
restored="builderops-restored-${run_suffix}"
cleanup() {
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    docker logs "$primary" >&2 2>/dev/null || true
    docker logs "$restored" >&2 2>/dev/null || true
  fi
  docker rm -f "$primary" "$restored" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$test_root"
}
trap cleanup EXIT

mkdir -p "$test_root/primary" "$test_root/restored" "$test_root/recovery-target"
chmod 0777 "$test_root/primary" "$test_root/restored" "$test_root/recovery-target"
password="restore-test-password-${run_suffix}"
recovery_key="$(python3 -c 'import base64; print(base64.b64encode(b"builderops-independent-key-00000").decode())')"

# Docker Desktop does not preserve host chmod semantics consistently for bind
# mounts. Establish the image's postgres ownership from inside the engine so
# WAL-G can create encrypted backup and archive objects on every runner.
docker run --rm --user root \
  -v "$test_root/primary:/var/lib/postgresql/data" \
  -v "$test_root/restored:/restore" \
  -v "$test_root/recovery-target:/recovery-target" \
  "$postgres_image" sh -c \
  'chown -R postgres:postgres /var/lib/postgresql/data /restore /recovery-target'

docker network create "$network" >/dev/null
docker run -d --name "$primary" --network "$network" \
  -e "POSTGRES_PASSWORD=$password" \
  -e POSTGRES_DB=builderops \
  -e WALG_FILE_PREFIX=/recovery-target \
  -e "WALG_LIBSODIUM_KEY=$recovery_key" \
  -e WALG_LIBSODIUM_KEY_TRANSFORM=base64 \
  -v "$test_root/primary:/var/lib/postgresql/data" \
  -v "$test_root/recovery-target:/recovery-target" \
  "$postgres_image" postgres \
  -c wal_level=replica \
  -c archive_mode=on \
  -c "archive_command=wal-g wal-push %p" >/dev/null

stable_ready=0
for _ in $(seq 1 60); do
  if docker exec "$primary" pg_isready -U postgres -d builderops >/dev/null 2>&1; then
    stable_ready=$((stable_ready + 1))
    [[ $stable_ready -ge 3 ]] && break
  else
    stable_ready=0
  fi
  sleep 2
done
docker exec "$primary" pg_isready -U postgres -d builderops >/dev/null

primary_dsn="postgresql://postgres:${password}@${primary}:5432/builderops"
docker run --rm --network "$network" \
  -e "BUILDEROPS_DATABASE_URL=$primary_dsn" \
  "$control_image" python -m app.builderops.control_plane.migrate >/dev/null

commit_record() {
  local dsn=$1 record_id=$2 idempotency=$3
  docker run --rm -i --network "$network" \
    -e "BUILDEROPS_DATABASE_URL=$dsn" \
    "$control_image" python - "$record_id" "$idempotency" <<'PY'
import os
import sys
from app.builderops.control_plane import AuthorityEnvelope, PostgresBuilderOpsStore

record_id, idempotency_key = sys.argv[1:]
dsn = os.environ["BUILDEROPS_DATABASE_URL"]
store = PostgresBuilderOpsStore(dsn)
result = store.commit_record(
    envelope=AuthorityEnvelope(
        repository="RasmusTho/agentic-pkm-mvp",
        scope="issue:3790",
        stack="builderops-control-plane",
        actor="test:real-restore",
        source_refs=("github:issue:3790",),
    ),
    record_id=record_id,
    record_type="BuilderOpsReceipt",
    state="active",
    payload={"summary": record_id},
    idempotency_key=idempotency_key,
)
print(result.recovery_lsn)
PY
}

commit_record "$primary_dsn" backup-base backup-base >/dev/null
docker exec --user postgres "$primary" wal-g backup-push /var/lib/postgresql/data >/dev/null
target_lsn="$(commit_record "$primary_dsn" wal-sentinel-3790 wal-sentinel-3790)"
target_segment="$(docker exec "$primary" psql -U postgres -d builderops -Atc \
  "SELECT pg_walfile_name('${target_lsn}'::pg_lsn)")"
docker exec "$primary" psql -U postgres -d builderops -Atc "SELECT pg_switch_wal()" >/dev/null
for _ in $(seq 1 60); do
  archived="$(docker exec "$primary" psql -U postgres -d builderops -Atc \
    "SELECT COALESCE(last_archived_wal, '') FROM pg_stat_archiver")"
  if [[ "$archived" == "$target_segment" || "$archived" > "$target_segment" ]]; then break; fi
  sleep 1
done
archived="$(docker exec "$primary" psql -U postgres -d builderops -Atc \
  "SELECT COALESCE(last_archived_wal, '') FROM pg_stat_archiver")"
if [[ "$archived" != "$target_segment" && ! "$archived" > "$target_segment" ]]; then
  echo "target WAL segment was not archived" >&2
  exit 1
fi
docker stop "$primary" >/dev/null
docker rm "$primary" >/dev/null

docker run --rm --user postgres \
  -e WALG_FILE_PREFIX=/recovery-target \
  -e "WALG_LIBSODIUM_KEY=$recovery_key" \
  -e WALG_LIBSODIUM_KEY_TRANSFORM=base64 \
  -v "$test_root/restored:/restore" \
  -v "$test_root/recovery-target:/recovery-target:ro" \
  "$postgres_image" wal-g backup-fetch /restore LATEST >/dev/null
docker run --rm --user postgres \
  -e "TARGET_LSN=$target_lsn" \
  -v "$test_root/restored:/restore" \
  "$postgres_image" sh -c \
  'printf "%s\n" \
    "restore_command = '\''wal-g wal-fetch %f %p'\''" \
    "recovery_target_lsn = '\''$TARGET_LSN'\''" \
    "recovery_target_action = '\''promote'\''" \
    >>/restore/postgresql.auto.conf && touch /restore/recovery.signal'

docker run -d --name "$restored" --network "$network" \
  -e "POSTGRES_PASSWORD=$password" \
  -e WALG_FILE_PREFIX=/recovery-target \
  -e "WALG_LIBSODIUM_KEY=$recovery_key" \
  -e WALG_LIBSODIUM_KEY_TRANSFORM=base64 \
  -v "$test_root/restored:/var/lib/postgresql/data" \
  -v "$test_root/recovery-target:/recovery-target:ro" \
  "$postgres_image" postgres >/dev/null
stable_ready=0
for _ in $(seq 1 90); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "$restored" 2>/dev/null || true)" != true ]]; then
    echo "restored PostgreSQL exited before reaching readiness" >&2
    exit 1
  fi
  if docker exec "$restored" pg_isready -U postgres -d builderops >/dev/null 2>&1; then
    stable_ready=$((stable_ready + 1))
    [[ $stable_ready -ge 3 ]] && break
  else
    stable_ready=0
  fi
  sleep 2
done
docker exec "$restored" pg_isready -U postgres -d builderops >/dev/null

restored_dsn="postgresql://postgres:${password}@${restored}:5432/builderops"
docker run --rm -i --network "$network" \
  -e "BUILDEROPS_DATABASE_URL=$restored_dsn" \
  "$control_image" python - "$target_lsn" <<'PY'
import json
import os
import sys
import psycopg
from app.builderops.control_plane import PostgresBuilderOpsStore

target_lsn = sys.argv[1]
dsn = os.environ["BUILDEROPS_DATABASE_URL"]
store = PostgresBuilderOpsStore(dsn)
base = store.get_record("RasmusTho/agentic-pkm-mvp", "backup-base")
sentinel = store.get_record("RasmusTho/agentic-pkm-mvp", "wal-sentinel-3790")
if base["payload"].get("summary") != "backup-base":
    raise SystemExit("base-backup record failed restored-data integrity check")
if sentinel["payload"].get("summary") != "wal-sentinel-3790":
    raise SystemExit("archived-WAL sentinel failed restored-data integrity check")
with psycopg.connect(dsn) as conn:
    replay = conn.execute(
        "SELECT COALESCE(pg_last_wal_replay_lsn(), pg_current_wal_lsn())::text, "
        "COALESCE(pg_last_wal_replay_lsn(), pg_current_wal_lsn()) >= %s::pg_lsn",
        (target_lsn,),
    ).fetchone()
if not replay[1]:
    raise SystemExit("restored database did not reach the archived target LSN")
epoch = store.activate_recovered_epoch(recovery_id="real-restore-selftest", restored_lsn=target_lsn)
state = store.recovery_state()
if not state["reconciliation_required"] or state["executor_enabled"]:
    raise SystemExit("restored authority was not fenced for reconciliation")
print(json.dumps({
    "ok": True,
    "authority_epoch": epoch,
    "schema_version": store.readiness()["schema_version"],
    "replay_lsn": replay[0],
    "base_record": "backup-base",
    "sentinel_record": "wal-sentinel-3790",
    "counts": store.authority_counts("RasmusTho/agentic-pkm-mvp"),
    "reconciliation_required": state["reconciliation_required"],
    "executor_enabled": state["executor_enabled"],
}, sort_keys=True, default=str))
PY

docker run --rm --user postgres \
  -e "SCAN_PASSWORD=$password" \
  -e "SCAN_RECOVERY_KEY=$recovery_key" \
  -v "$test_root/recovery-target:/recovery-target:ro" \
  "$postgres_image" sh -c '
    if grep -R -a -F "$SCAN_PASSWORD" /recovery-target >/dev/null 2>&1; then
      echo "raw database credential leaked into recovery target" >&2
      exit 1
    fi
    if grep -R -a -F "$SCAN_RECOVERY_KEY" /recovery-target >/dev/null 2>&1; then
      echo "raw recovery key leaked into recovery target" >&2
      exit 1
    fi
  '
