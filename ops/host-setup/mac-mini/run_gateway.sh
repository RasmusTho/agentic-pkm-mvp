#!/usr/bin/env bash
# Launch wrapper for the llm-gateway. Sources config.env, derives upstream URLs,
# and execs uvicorn from the local venv. Referenced by the launchd plist.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

set -a
# shellcheck disable=SC1091
[ -f "$ROOT/config.env" ] && . "$ROOT/config.env"
set +a

export GATEWAY_MINI_URL="http://127.0.0.1:${MINI_OLLAMA_PORT:-11434}"
export GATEWAY_GAMING_URL="http://${GAMING_PC_HOST:?set GAMING_PC_HOST in config.env}:${GAMING_OLLAMA_PORT:-11434}"
export GATEWAY_WARDEN_URL="http://${GAMING_PC_HOST}:${WARDEN_PORT:-9090}"
export GATEWAY_GAMING_MODEL="${GAMING_CHAT_MODEL:-}"

exec "$HERE/.venv/bin/uvicorn" llm_gateway:app \
  --app-dir "$HERE" \
  --host 127.0.0.1 \
  --port "${GATEWAY_PORT:-11500}"
