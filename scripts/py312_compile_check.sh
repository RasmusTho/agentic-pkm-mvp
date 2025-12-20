#!/usr/bin/env bash
set -euo pipefail

docker run --rm \
  -v "$(pwd):/repo" \
  -w /repo \
  python:3.12 \
  bash -lc "PYTHONPYCACHEPREFIX=/tmp/py312_compile_cache python -m compileall -q app tests"
