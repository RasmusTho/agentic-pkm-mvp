#!/usr/bin/env bash
set -euo pipefail

GIT_SHA="$(git rev-parse --short HEAD)"

python3 scripts/run_with_host_lease.py \
  --resource pytest-not-pg \
  --execution-id "py312-smoke:${GIT_SHA}:$$" \
  --wait-seconds 900 \
  -- docker run --rm \
  -v "$(pwd):/repo" \
  -w /repo \
  python:3.12 \
  bash -lc "pip install -r requirements.txt -r dev-requirements.txt && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin -q -m 'not pg'"
