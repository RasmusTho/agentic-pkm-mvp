#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PYTHON="${PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${ROOT}/.venv/bin/python" ]; then
    PYTHON="${ROOT}/.venv/bin/python"
  elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON="$(command -v python3.12)"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  else
    PYTHON="$(command -v python)"
  fi
fi

run_channel() {
  local channel="$1" url
  case "${channel}" in
    dev) url="${COMPANION_UI_DEV_SMOKE_URL:-http://127.0.0.1:8111/}" ;;
    test) url="${COMPANION_UI_TEST_SMOKE_URL:-http://127.0.0.1:8112/}" ;;
    prod) url="${COMPANION_UI_PROD_SMOKE_URL:-http://127.0.0.1:8113/}" ;;
    *) echo "unknown channel: ${channel}" >&2; return 2 ;;
  esac
  echo "[companion-ui:${channel}] post-deploy smoke ${url}"
  (
    cd "${ROOT}" || exit 1
    COMPANION_UI_SMOKE_URL="${url}" \
    COMPANION_UI_EXPECTED_CHANNEL="${channel}" \
    "${PYTHON}" -m pytest tests/companion_ui/test_companion_ui_live_smoke.py -q
  )
}

target="${1:-all}"
case "${target}" in
  all)
    run_channel dev
    run_channel test
    run_channel prod
    ;;
  dev|test|prod)
    run_channel "${target}"
    ;;
  *)
    echo "usage: $0 [dev|test|prod|all]" >&2
    exit 2
    ;;
esac
