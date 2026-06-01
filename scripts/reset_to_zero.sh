#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required for reset_to_zero.sh. Install Docker Desktop or make docker available on PATH, then retry." >&2
  exit 127
fi

RESET_FORCE="${RESET_FORCE:-0}"
shopt -s nullglob

patterns=(
  "vault-test"
  ".watcher_pause"
  "tmp/index-outbox.jsonl"
  "tmp/index-outbox.*.jsonl"
  "tmp/WATCHER_STOP*"
  "tmp/worker_heartbeat.json"
  "tmp/watcher_heartbeat.json"
  "tmp/watcher_state.json"
  "tmp/watcher_state.*.json"
  "tmp/watcher_states"
  "tmp/health_incidents.jsonl"
  "tmp/worker_heartbeat.*"
  "tmp/runtime.env"
  "tmp/startup_status.json"
  "tmp/latest_watcher_tick_log"
  "tmp-test/index-outbox.jsonl"
  "tmp-test/index-outbox.*.jsonl"
  "tmp-test/WATCHER_STOP*"
  "tmp-test/worker_heartbeat.json"
  "tmp-test/watcher_heartbeat.json"
  "tmp-test/watcher_state.json"
  "tmp-test/watcher_state.*.json"
  "tmp-test/watcher_states"
  "tmp-test/health_incidents.jsonl"
  "tmp-test/worker_heartbeat.*"
  "tmp-test/runtime.env"
  "tmp-test/startup_status.json"
  "tmp-test/latest_watcher_tick_log"
)

echo "Stopping docker compose (down -v --remove-orphans)"
if command -v docker &> /dev/null; then
  if docker compose down -v --remove-orphans 2>&1; then
    : # Success
  else
    DOCKER_EXIT_CODE=$?
    echo "⚠ Docker compose teardown failed (exit code: $DOCKER_EXIT_CODE)"
    echo "  This may leave stale containers/volumes. Check docker status before retry."
    exit $DOCKER_EXIT_CODE
  fi
else
  echo "  (docker not available, skipping)"
fi

deleted=()
for pattern in "${patterns[@]}"; do
  for target in $pattern; do
    if [ -e "$target" ] || [ -L "$target" ]; then
      deleted+=("$target")
    fi
  done
done

durable_deleted=()
if [ "${#deleted[@]}" -gt 0 ]; then
  for entry in "${deleted[@]}"; do
    case "$entry" in
      tmp/index-outbox.jsonl|tmp/index-outbox.*.jsonl|tmp/WATCHER_STOP*|tmp/worker_heartbeat.json|tmp/watcher_heartbeat.json|tmp/watcher_state.json|tmp/watcher_state.*.json|tmp/watcher_states|tmp/health_incidents.jsonl|tmp/worker_heartbeat.*|tmp/runtime.env|tmp/startup_status.json|tmp/latest_watcher_tick_log|tmp-test/index-outbox.jsonl|tmp-test/index-outbox.*.jsonl|tmp-test/WATCHER_STOP*|tmp-test/worker_heartbeat.json|tmp-test/watcher_heartbeat.json|tmp-test/watcher_state.json|tmp-test/watcher_state.*.json|tmp-test/watcher_states|tmp-test/health_incidents.jsonl|tmp-test/worker_heartbeat.*|tmp-test/runtime.env|tmp-test/startup_status.json|tmp-test/latest_watcher_tick_log)
        ;;
      *)
        durable_deleted+=("$entry")
        ;;
    esac
  done
fi

echo "Identified runtime artifacts to delete:"
if [ "${#durable_deleted[@]}" -eq 0 ]; then
  echo "  (none found)"
else
  for entry in "${deleted[@]}"; do
    echo "  $entry"
  done
fi

if [ "$RESET_FORCE" != "1" ]; then
  printf "Type YES to delete the files above (or set RESET_FORCE=1): "
  read -r confirm
  if [ "$confirm" != "YES" ]; then
    echo "Aborted by user"
    exit 1
  fi
fi

if [ "${#deleted[@]}" -eq 0 ]; then
  echo "No runtime artifacts existed."
else
  for entry in "${deleted[@]}"; do
    if [ -d "$entry" ]; then
      rm -rf "$entry"
    else
      rm -f "$entry"
    fi
  done
  if [ "${#durable_deleted[@]}" -eq 0 ]; then
    echo "No runtime artifacts existed."
  else
    echo "Removed runtime artifacts."
  fi
fi

cat <<SUMMARY
RESET_COMPLETE=true
SUMMARY

echo "✓ Reset complete: runtime state clean"
echo "  - docker compose containers stopped (volumes removed)"
echo "  - cleaned tmp/tmp-test outbox + WATCHER_STOP + heartbeat/health/startup state files"
echo "  - test vault directory removed (vault-test/)"
echo "  - watcher pause/state files cleared"
