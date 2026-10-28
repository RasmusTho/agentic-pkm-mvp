#!/usr/bin/env bash
# launchd entrypoint for the Mac model-access executor. It runs the executor as
# the declared `dev/model-access-executor` host-secret consumer so the explicit
# `openai_api` evaluation transport can resolve `openai.api-key` from Keychain.
# A missing item still starts the executor; that transport then reports
# `credential_unavailable`. Set MODEL_ACCESS_EXECUTOR_PYTHON to the interpreter
# the launchd job already uses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${MODEL_ACCESS_EXECUTOR_PYTHON:-$(command -v python3)}"

cd "$APP_ROOT"
exec "$PYTHON" -m app.ops.host_secret_bootstrap \
    --provider keychain \
    --channel dev \
    --consumer model-access-executor \
    --run-on-credential-unavailable \
    -- \
    "$PYTHON" -m app.model_access.codex_executor_service
