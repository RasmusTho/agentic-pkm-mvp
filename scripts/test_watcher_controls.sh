#!/usr/bin/env bash
set -euo pipefail

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory pytest -q tests/watcher/test_watcher_controls.py tests/watcher/test_registry_guardrails.py
