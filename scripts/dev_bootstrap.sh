#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker info >/dev/null 2>&1 || true
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    colima start
  fi
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not available. Start Docker/Colima and retry."
  exit 1
fi

cd "$ROOT"

docker compose up -d

for attempt in $(seq 1 30); do
  if curl -sf http://127.0.0.1:18000/agent/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -sf http://127.0.0.1:18000/agent/health > /tmp/dev_bootstrap_health.json 2>/dev/null; then
  echo "API did not become healthy on port 18000"
  exit 1
fi

curl -sf http://127.0.0.1:18000/api/status > /tmp/dev_bootstrap_status.json || true

if [ "${RUN_SMOKE:-0}" != "0" ]; then
  cd "$ROOT"
  pytest tests/agents/test_panel_parser.py -q --maxfail=1
fi

echo "API healthy on 18000; db on 15432; worker running"
cat /tmp/dev_bootstrap_status.json || true
