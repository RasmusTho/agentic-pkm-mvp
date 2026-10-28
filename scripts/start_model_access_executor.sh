#!/usr/bin/env bash
# launchd entrypoint for the Mac model-access executor. It runs the executor as
# the declared `dev/model-access-executor` host-secret consumer so the explicit
# `openai_api` evaluation transport can resolve `openai.api-key` from Keychain.
# A missing item still starts the executor; that transport then reports
# `credential_unavailable`. MODEL_ACCESS_EXECUTOR_PYTHON must name the exact
# interpreter the launchd job uses; there is no PATH fallback.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${MODEL_ACCESS_EXECUTOR_PYTHON:?MODEL_ACCESS_EXECUTOR_PYTHON must name the executor interpreter}"

cd "$APP_ROOT"
exec "$PYTHON" -m app.ops.host_secret_bootstrap \
    --provider keychain \
    --channel dev \
    --consumer model-access-executor \
    --run-on-credential-unavailable \
    -- \
    "$PYTHON" -m app.model_access.codex_executor_service
