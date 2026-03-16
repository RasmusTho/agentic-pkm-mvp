#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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

service_health_status() {
  local service="$1"
  local cid
  cid=$(run_docker_compose ps -q "$service" | head -n1 || true)
  if [ -z "$cid" ]; then
    echo "missing"
    return 0
  fi
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid"
}

require_service_ok() {
  local service="$1"
  local status
  status=$(service_health_status "$service")
  case "$status" in
    healthy|running)
      printf "SERVICE %s: %s\n" "$service" "$status"
      ;;
    *)
      printf "SERVICE %s: %s\n" "$service" "$status" >&2
      return 1
      ;;
  esac
}

echo "--- docker compose ps ---"
run_docker_compose ps

require_service_ok "db"
require_service_ok "api"

watcher_cid=$(run_docker_compose ps -q watcher | head -n1 || true)
if [ -n "$watcher_cid" ]; then
  require_service_ok "watcher"
fi

worker_cid=$(run_docker_compose ps -q worker | head -n1 || true)
if [ -n "$worker_cid" ]; then
  require_service_ok "worker"
fi

echo "--- in-container health ---"
health_json=$(run_docker_compose exec -T api python -m app.cli health --json)
printf "%s\n" "$health_json"

echo "--- llm routing ---"
HEALTH_JSON="$health_json" python3 - <<'PY'
from __future__ import annotations

import json
import os

payload = json.loads(os.environ.get("HEALTH_JSON", "{}"))
router = ((payload.get("checks") or {}).get("llm_router") or {})
policies = router.get("route_policies") or {}

for task_kind in ("decide", "plan", "embed", "eval"):
    item = policies.get(task_kind) or {}
    preferred = item.get("preferred") or {}
    effective = item.get("effective") or {}
    policy = item.get("policy") or {}
    fallback = policy.get("fallback") or {}
    strict_identity = bool(policy.get("require_compatible_identity"))
    print(
        f"ROUTE {task_kind}: "
        f"preferred={preferred.get('provider') or '?'}:{preferred.get('model') or '?'} "
        f"effective={effective.get('provider') or '?'}:{effective.get('model') or '?'} "
        f"fallback={fallback.get('mode') or 'never'} "
        f"strict_identity={str(strict_identity).lower()}"
    )

embedding_index = ((payload.get("checks") or {}).get("embedding_index") or {})
if embedding_index:
    print(
        "EMBEDDING INDEX: "
        f"status={embedding_index.get('status') or '?'} "
        f"rebuild_required={str(bool(embedding_index.get('rebuild_required'))).lower()} "
        f"detail={embedding_index.get('detail') or ''}"
    )
PY

health_meta=$(HEALTH_JSON="$health_json" python3 - <<'PY'
from __future__ import annotations

import json
import os

payload = json.loads(os.environ.get("HEALTH_JSON", "{}"))
ok = bool(payload.get("ok"))
required_ok = bool(payload.get("required_ok"))
checks = payload.get("checks") or {}
failed_required: list[str] = []
if isinstance(checks, dict):
    for name, item in checks.items():
        if isinstance(item, dict) and item.get("required") and item.get("ok") is False:
            failed_required.append(name)
print("1" if ok else "0")
print("1" if required_ok else "0")
print(",".join(failed_required))
PY
)
health_ok=$(printf '%s\n' "$health_meta" | sed -n '1p')
health_required_ok=$(printf '%s\n' "$health_meta" | sed -n '2p')
failed_required=$(printf '%s\n' "$health_meta" | sed -n '3p')
health_ok=${health_ok:-0}
health_required_ok=${health_required_ok:-0}
failed_required=${failed_required:-}

echo "--- in-container status ---"
status_text=$(run_docker_compose exec -T api python -m app.cli status)
printf "%s\n" "$status_text"

if [ "$health_required_ok" != "1" ]; then
  echo "ERROR: runtime required health is not green" >&2
  if [ -n "$failed_required" ]; then
    echo "Required failing checks: $failed_required" >&2
  fi
  exit 1
fi

echo "VERIFY RUNTIME: required health ok=true"
exit 0
