#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RESET_FORCE="${RESET_FORCE:-0}"
shopt -s nullglob

patterns=(
  "tmp/index-outbox.jsonl"
  "tmp/index-outbox.*.jsonl"
  "tmp/worker_heartbeat.json"
  "tmp/watcher_heartbeat.json"
  "tmp/WATCHER_STOP"
  "tmp/watcher_state.json"
  "tmp/watcher_state.*.json"
  "tmp/watcher_states"
  "tmp/health_incidents.jsonl"
  "tmp/worker_heartbeat.*"
)

deleted=()
for pattern in "${patterns[@]}"; do
  for target in $pattern; do
    deleted+=("$target")
  done
done

echo "Stopping docker compose (down -v --remove-orphans)"
docker compose down -v --remove-orphans

echo "Identified runtime artifacts to delete:"
if [ "${#deleted[@]}" -eq 0 ]; then
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
  echo "Removed runtime artifacts."
fi

cat <<SUMMARY
SUMMARY:
  docker compose down -v --remove-orphans
  cleaned tmp/index-outbox* + WATCHER_STOP + heartbeat/health state files
  use scripts/reset_to_zero.sh RESET_FORCE=1 to repeat non-interactively
SUMMARY
