#!/usr/bin/env bash
set -euo pipefail

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export STORE_BACKEND=memory

echo "== POLICY_ENFORCE=1 =="
POLICY_ENFORCE=1 pytest -q tests/policy/test_tool_policy.py

echo "== POLICY_ENFORCE=0 =="
POLICY_ENFORCE=0 pytest -q tests/policy/test_tool_policy.py
