#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required for verify_runtime_stack.sh. Install Docker Desktop or make docker available on PATH, then retry." >&2
  exit 127
fi

source "scripts/lib/load_env_defaults.sh"
load_env_defaults_file ".env"
load_env_defaults_file "config/runtime.defaults.env"

runtime_env_path="${RUNTIME_ENV_PATH:-${WATCHER_RUNTIME_ENV_FILE:-tmp/runtime.env}}"
runtime_env=""
if [ -f "$runtime_env_path" ]; then
  runtime_env="--env-file $runtime_env_path"
fi

run_docker_compose() {
  if [ -n "$runtime_env" ]; then
    docker compose $runtime_env "$@"
  else
    docker compose "$@"
  fi
}

# Track overall status
overall_status=0
watcher_ready="false"
worker_ready="false"
api_ready="false"
store_ready="false"

# Helper to check service is running
check_service() {
  local service="$1"
  local timeout="${VERIFY_RUNTIME_SERVICE_WAIT_SECONDS:-10}"
  local sleep_seconds="${VERIFY_RUNTIME_SERVICE_WAIT_SLEEP_SECONDS:-1}"
  local deadline=$((SECONDS + timeout))
  local status="missing"

  while [ "$SECONDS" -lt "$deadline" ]; do
    cid=$(run_docker_compose ps -q "$service" 2>/dev/null | head -n1 || true)
    if [ -z "$cid" ]; then
      sleep "$sleep_seconds"
      continue
    fi

    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo "unknown")
    case "$status" in
      healthy|running)
        return 0
        ;;
      starting|created|restarting)
        sleep "$sleep_seconds"
        ;;
      *)
        return 1
        ;;
    esac
  done

  return 1
}

# Check watcher
printf "→ Checking watcher process... "
if check_service "watcher"; then
  printf "✓ Running\n"
  watcher_ready="true"
else
  printf "✗ Not running\n"
  overall_status=1
fi

# Check worker
printf "→ Checking worker process... "
if check_service "worker"; then
  printf "✓ Running\n"
  worker_ready="true"
else
  printf "✗ Not running\n"
  overall_status=1
fi

# Check API
printf "→ Checking API health... "
if check_service "api"; then
  # Verify API is actually responsive
  if run_docker_compose exec -T api curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    printf "✓ OK\n"
    api_ready="true"
  else
    printf "✗ Not responding\n"
    overall_status=1
  fi
else
  printf "✗ Not running\n"
  overall_status=1
fi

# Check store (DB)
printf "→ Checking store access... "
if check_service "db"; then
  printf "✓ Initialized\n"
  store_ready="true"
else
  printf "✗ Not accessible\n"
  overall_status=1
fi

# Emit machine-readable flags
echo ""
echo "WATCHER_READY=$watcher_ready"
echo "WORKER_READY=$worker_ready"
echo "API_READY=$api_ready"
echo "STORE_READY=$store_ready"

# Final status
if [ "$overall_status" = "0" ]; then
  echo ""
  echo "→ All checks passed"
else
  echo ""
  echo "✗ Runtime verification failed"
fi

exit "$overall_status"
