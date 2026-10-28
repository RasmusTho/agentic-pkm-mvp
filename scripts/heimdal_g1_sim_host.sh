#!/bin/bash
# Ephemeral, isolated Heimdal media-ingress instance for the G1 day-like
# simulation (#3408, ADR-0060 §4 G1). Measurement harness only: it runs the
# channel's already-pinned app image unchanged and adds no capture path.
#
# Runs ON the channel host (as root), fed over SSH from the operator machine:
#
#   ssh ygg-test 'sudo bash -s -- up     <run_id> <image> <bind_ip> <port>' < scripts/heimdal_g1_sim_host.sh
#   ssh ygg-test 'sudo bash -s -- status <run_id>'                         < scripts/heimdal_g1_sim_host.sh
#   ssh ygg-test 'sudo bash -s -- down   <run_id>'                         < scripts/heimdal_g1_sim_host.sh
#
# Isolation (where synthetic captures land):
# - a throwaway pgvector container bound to 127.0.0.1 only, never the
#   channel's own database;
# - an empty synthetic vault directory under /srv/ygg-test/g1-sim/<run_id>,
#   never an owner or channel vault;
# - a raw-store key generated here into a 0600 env file, never printed;
# - the api bound to the given (tailnet) address only: no public ingress.
# `down` removes both containers, their volumes and the run directory.
#
# The image must already be present on the host: `up` never pulls (disk
# headroom on the channel VMs is the scarce resource), and refuses to start
# below the disk floor.
set -euo pipefail

SIM_ROOT="${G1_SIM_ROOT:-/srv/ygg-test/g1-sim}"
DISK_FLOOR_FREE_MB="${G1_SIM_DISK_FLOOR_FREE_MB:-4096}"
DISK_CEILING_USE_PCT="${G1_SIM_DISK_CEILING_USE_PCT:-90}"
PG_IMAGE="${G1_SIM_PG_IMAGE:-pgvector/pgvector:pg16}"
PG_PORT="${G1_SIM_PG_PORT:-55408}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

valid_run_id() {
  [[ "$1" =~ ^g1sim-[a-z0-9-]{4,40}$ ]] || die "run_id must match g1sim-[a-z0-9-]{4,40}"
}

disk_json() {
  df -Pm / | awk 'NR==2 {gsub("%","",$5); printf "{\"total_mb\": %d, \"used_mb\": %d, \"free_mb\": %d, \"use_pct\": %d}", $2, $3, $4, $5}'
}

cmd_up() {
  local run_id="$1" image="$2" bind_ip="$3" port="$4"
  valid_run_id "$run_id"
  [[ "$port" =~ ^[0-9]{4,5}$ ]] || die "port must be numeric"
  local run_dir="$SIM_ROOT/$run_id"
  [ ! -e "$run_dir" ] || die "run dir already exists: $run_dir"

  local free_mb use_pct
  free_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
  use_pct="$(df -Pm / | awk 'NR==2 {gsub("%","",$5); print $5}')"
  [ "$free_mb" -ge "$DISK_FLOOR_FREE_MB" ] || die "disk floor: ${free_mb}MB free < ${DISK_FLOOR_FREE_MB}MB"
  [ "$use_pct" -lt "$DISK_CEILING_USE_PCT" ] || die "disk ceiling: ${use_pct}% used >= ${DISK_CEILING_USE_PCT}%"
  docker image inspect "$image" >/dev/null 2>&1 || die "image not present on host (no pull): $image"
  docker image inspect "$PG_IMAGE" >/dev/null 2>&1 || die "image not present on host (no pull): $PG_IMAGE"
  ip -4 addr | grep -q "inet ${bind_ip}/" || die "bind address is not a local interface: $bind_ip"

  install -d -m 0700 "$run_dir" "$run_dir/vault" "$run_dir/tmp"
  local pg_password raw_key
  pg_password="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  raw_key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  local dsn="postgresql+psycopg://app:${pg_password}@127.0.0.1:${PG_PORT}/app_g1sim"
  umask 077
  {
    echo "POSTGRES_USER=app"
    echo "POSTGRES_PASSWORD=${pg_password}"
    echo "POSTGRES_DB=app_g1sim"
  } >"$run_dir/db.env"
  {
    echo "DATABASE_URL=${dsn}"
    echo "DB_DSN=${dsn}"
    echo "HEIMDAL_RAW_STORE_KEY=${raw_key}"
    echo "PKM_ENVIRONMENT=test"
    echo "STORE_BACKEND=pg"
    echo "LLM_PROVIDER=ollama"
    echo "LLM_PROVIDER_ENFORCE=0"
    echo "VAULT_ROOT=/sim/vault"
    echo "WATCHER_ENABLE=0"
    echo "TTS_ENABLED=0"
    echo "INDEX_OUTBOX_PATH=/sim/tmp/index-outbox.jsonl"
  } >"$run_dir/api.env"
  unset pg_password raw_key dsn

  docker run -d --name "${run_id}-db" --label "com.agentic-pkm.g1sim=${run_id}" \
    --env-file "$run_dir/db.env" -p "127.0.0.1:${PG_PORT}:5432" "$PG_IMAGE" >/dev/null
  local _
  for _ in $(seq 1 60); do
    if docker exec "${run_id}-db" pg_isready -U app -d app_g1sim >/dev/null 2>&1; then break; fi
    sleep 1
  done
  docker exec "${run_id}-db" pg_isready -U app -d app_g1sim >/dev/null || die "ephemeral db not ready"

  docker run -d --name "${run_id}-api" --label "com.agentic-pkm.g1sim=${run_id}" \
    --network host --env-file "$run_dir/api.env" \
    -v "$run_dir/vault:/sim/vault" -v "$run_dir/tmp:/sim/tmp" -w /app \
    --entrypoint /bin/bash "$image" \
    -c "bash scripts/run_migrations.sh && exec python -m uvicorn app.api.app:app --host ${bind_ip} --port ${port} --no-access-log" \
    >/dev/null
  local probe="http://${bind_ip}:${port}/api/heimdal/capture/receipts?capture_id=00000000-0000-4000-8000-000000000000"
  for _ in $(seq 1 180); do
    if curl -fsS -o /dev/null "$probe" 2>/dev/null; then
      printf '{"run_id": "%s", "state": "up", "image": "%s", "base_url": "http://%s:%s", "disk": %s}\n' \
        "$run_id" "$image" "$bind_ip" "$port" "$(disk_json)"
      return 0
    fi
    sleep 1
  done
  docker logs --tail 40 "${run_id}-api" >&2 || true
  die "ephemeral api did not become ready"
}

cmd_status() {
  local run_id="$1"
  valid_run_id "$run_id"
  local db_bytes api_mem api_state api_restarts raw_rows receipt_rows
  db_bytes="$(docker exec "${run_id}-db" psql -U app -d app_g1sim -tAc "select pg_database_size('app_g1sim')" 2>/dev/null || echo null)"
  raw_rows="$(docker exec "${run_id}-db" psql -U app -d app_g1sim -tAc "select count(*) from heimdal_raw_record" 2>/dev/null || echo null)"
  receipt_rows="$(docker exec "${run_id}-db" psql -U app -d app_g1sim -tAc "select count(*) from heimdal_media_receipt" 2>/dev/null || echo null)"
  api_mem="$(docker stats --no-stream --format '{{.MemUsage}}' "${run_id}-api" 2>/dev/null | awk '{print $1}' || true)"
  api_state="$(docker inspect -f '{{.State.Status}}' "${run_id}-api" 2>/dev/null || echo missing)"
  api_restarts="$(docker inspect -f '{{.RestartCount}}' "${run_id}-api" 2>/dev/null || echo null)"
  printf '{"run_id": "%s", "api_state": "%s", "api_restart_count": %s, "api_mem": "%s", "db_bytes": %s, "raw_rows": %s, "receipt_rows": %s, "disk": %s}\n' \
    "$run_id" "$api_state" "$api_restarts" "${api_mem:-unknown}" "${db_bytes:-null}" "${raw_rows:-null}" "${receipt_rows:-null}" "$(disk_json)"
}

cmd_restart_api() {
  local run_id="$1"
  valid_run_id "$run_id"
  docker restart -t 0 "${run_id}-api" >/dev/null
  echo "{\"run_id\": \"${run_id}\", \"restarted\": \"api\"}"
}

cmd_down() {
  local run_id="$1"
  valid_run_id "$run_id"
  docker rm -f -v "${run_id}-api" "${run_id}-db" >/dev/null 2>&1 || true
  if [ -d "$SIM_ROOT/$run_id" ]; then
    rm -rf -- "${SIM_ROOT:?}/${run_id:?}"
  fi
  local left
  left="$(docker ps -a --filter "label=com.agentic-pkm.g1sim=${run_id}" -q | wc -l)"
  printf '{"run_id": "%s", "state": "down", "containers_left": %d, "run_dir_exists": %s, "disk": %s}\n' \
    "$run_id" "$left" "$([ -e "$SIM_ROOT/$run_id" ] && echo true || echo false)" "$(disk_json)"
}

[ "$(id -u)" -eq 0 ] || die "run as root (sudo bash -s -- ...)"
action="${1:-}"
shift || true
case "$action" in
  up) [ "$#" -eq 4 ] || die "usage: up <run_id> <image> <bind_ip> <port>"; cmd_up "$@" ;;
  status) [ "$#" -eq 1 ] || die "usage: status <run_id>"; cmd_status "$@" ;;
  restart-api) [ "$#" -eq 1 ] || die "usage: restart-api <run_id>"; cmd_restart_api "$@" ;;
  down) [ "$#" -eq 1 ] || die "usage: down <run_id>"; cmd_down "$@" ;;
  *) die "usage: {up|status|restart-api|down} ..." ;;
esac
