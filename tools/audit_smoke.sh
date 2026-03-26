#!/usr/bin/env bash
set -uo pipefail
errors=0
fail(){ echo "  ❌ $*"; errors=$((errors+1)); }
ok(){ echo "  ✅ $*"; }

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="python"
fi

echo "==> 1) Check required files exist"
must_exist=(
  app/main.py
  app/api/app.py
  app/api/routers/agent.py
  app/api/routes/ask.py
  app/api/routes/status.py
  app/api/routes/search.py
  app/search/__init__.py
  .github/workflows/smoke.yml
  requirements-smoke.txt
  Makefile
  docs/ARCHITECTURE.md
  README.md
)
for f in "${must_exist[@]}"; do
  if [[ -f "$f" ]]; then
    ok "$f"
  else
    fail "missing: $f"
  fi
done

echo "==> 2) Import checks"
"$PYTHON_BIN" - << 'PY'
import importlib
import sys

errors = 0

def must(mod, attrs=None):
    global errors
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        print("  ❌ import", mod, "failed:", e)
        errors += 1
        return
    if attrs:
        for name in attrs:
            if not hasattr(m, name):
                print("  ❌", mod, "missing attribute", name)
                errors += 1
                return
    print("  ✅ import", mod, "[" + ",".join(attrs or []) + "]")

must("app.main", ["app"])
must("app.api.app", ["app"])
must("app.api.routers.agent", ["router"])
must("app.api.routes.ask", ["router"])
must("app.api.routes.status", ["router"])
must("app.api.routes.search", ["router"])
must("app.search")

svc = importlib.import_module("app.search.service")
for name in ("ingest_object", "search_vector", "search_hybrid"):
    if not hasattr(svc, name):
        print("  ❌ app.search.service missing", name)
        errors += 1

if errors:
    sys.exit(1)
PY

if [[ $? -ne 0 ]]; then
  errors=$((errors+1))
fi

echo "==> 3) README CI summary"
if grep -q 'CI SUMMARY' README.md; then
  ok "README CI summary present"
else
  fail "README missing CI summary line"
fi

echo "==> 4) Summary"
if [[ $errors -gt 0 ]]; then
  echo "🚨 Audit found $errors problem(s)."
  exit 1
fi
echo "✅ Audit ok"
