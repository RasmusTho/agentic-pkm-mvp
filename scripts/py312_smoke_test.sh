#!/usr/bin/env bash
set -euo pipefail

docker run --rm \
  -v "$(pwd):/repo" \
  -w /repo \
  python:3.12 \
  bash -lc "pip install -r app/requirements.txt -r dev-requirements.txt && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory pytest -q -m 'not pg'"
