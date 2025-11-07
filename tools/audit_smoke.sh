#!/usr/bin/env bash
set -uo pipefail

errors=0
fail(){ echo "  ❌ $*"; errors=$((errors+1)); }
ok(){ echo "  ✅ $*"; }

echo "==> 1) Kolla att filer finns"
must_exist=(
  "app/main.py"
  "app/api/_shim_helpers.py"
  "app/api/routers/__init__.py"
  "app/api/routers/agent.py"
  "app/api/routers/interesting.py"
  "app/api/routers/dashboard.py"
  "app/search/__init__.py"
  "app/search/service.py"
  "requirements-smoke.txt"
  ".github/workflows/smoke.yml"
  "Makefile"
)
for f in "${must_exist[@]}"; do
  [[ -f "$f" ]] && ok "$f" || fail "saknas: $f"
done

echo "==> 2) Mönsterkontroller (grep)"
chk(){ local file="$1" patt="$2"
  if grep -Eq "$patt" "$file"; then ok "$file =~ $patt"; else fail "$file saknar $patt"; fi
}

# main.py: lifespan + include_router
chk app/main.py 'async def lifespan\(app:\s*FastAPI\)'
chk app/main.py 'app\.include_router\(.*agent_router'
chk app/main.py 'app\.include_router\(.*interesting_router'
chk app/main.py 'app\.include_router\(.*dashboard_router'

# agent/interesting/dashboard routers
chk app/api/routers/agent.py '@router\.get\("/agent/health"'
chk app/api/routers/interesting.py '@router\.get\('
chk app/api/routers/dashboard.py '@router\.get\('

# search __init__: auto-detect DATABASE_URL eller STORE_BACKEND=pg
chk app/search/__init__.py 'def get_vector_index\('
chk app/search/__init__.py 'STORE_BACKEND'
chk app/search/__init__.py 'DATABASE_URL'
chk app/search/__init__.py 'PgVectorIndex|NullVectorIndex'

# search service: publika API:n
chk app/search/service.py 'def ingest_object\('
chk app/search/service.py 'def search_vector\('
chk app/search/service.py 'def search_hybrid\('
chk app/search/service.py '_embed_text'

# requirements-smoke: minimideps (PyYAML, SQLAlchemy, httpx, jsonschema)
for req in 'PyYAML' 'SQLAlchemy' 'httpx' 'jsonschema'; do
  if grep -Eq "^${req}([<=>].*)?$" requirements-smoke.txt; then
    ok "requirements-smoke.txt innehåller ${req}"
  else
    fail "requirements-smoke.txt saknar ${req}"
  fi
done

# workflow: pip install requirements-smoke + pytest -q
chk .github/workflows/smoke.yml 'pip install -r requirements-smoke\.txt'
chk .github/workflows/smoke.yml 'pytest -q'

# Makefile: worker-target (valfritt)
if grep -Eq '^\s*worker:' Makefile; then
  ok "Makefile worker target"
else
  echo "  ⚠️  Makefile worker target hittades ej (ok om ej används)"
fi

echo "==> 3) Snabb Python-import för kritiska symboler"
python - <<'PY' || errors=$((errors+1))
import importlib, sys
def must(mod, attrs=None):
    m = importlib.import_module(mod)
    if attrs:
        for a in (attrs if isinstance(attrs,(list,tuple)) else [attrs]):
            if not hasattr(m, a):
                print(f"❌ {mod} saknar {a}"); sys.exit(2)
    print(f"✅ import {mod}" + (f" [{attrs}]" if attrs else ""))

must("app.main")
must("app.api.routers.agent")
must("app.api.routers.interesting")
must("app.api.routers.dashboard")
must("app.search", ["get_vector_index","NullVectorIndex"])

svc = importlib.import_module("app.search.service")
for a in ("ingest_object","search_vector","search_hybrid"):
    assert hasattr(svc, a), f"search.service saknar {a}"
print("✅ app.search.service API ok")
PY

echo "==> 4) Sammanfattning"
if [[ $errors -gt 0 ]]; then
  echo "🚨 Audit hittade $errors fel. Smoke hoppar över. Åtgärda ovan."
  exit 1
fi

echo "==> 5) Kör smoke DB-fritt"
export STORE_BACKEND=memory
export SKIP_CLASSIFIER_TESTS=1
pytest -q tests/system/test_settings_schema.py tests/guard/test_no_direct_db_imports.py tests/test_agent_smoke.py
