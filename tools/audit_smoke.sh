#!/usr/bin/env bash
set -uo pipefail
errors=0
fail(){ echo "  ❌ $*"; errors=$((errors+1)); }
ok(){ echo "  ✅ $*"; }

echo "==> 1) Kolla att filer finns"
must_exist=(app/main.py app/api/_shim_helpers.py app/api/routers/__init__.py app/api/routers/agent.py app/api/routers/interesting.py app/api/routers/dashboard.py app/search/__init__.py app/search/service.py requirements-smoke.txt .github/workflows/smoke.yml Makefile)
for f in "${must_exist[@]}"; do [[ -f "$f" ]] && ok "$f" || fail "saknas: $f"; done

echo "==> 2) Mönsterkontroller"
chk(){ grep -Eq "$2" "$1" && ok "$1 =~ $2" || fail "$1 saknar $2"; }
chk app/main.py 'async def lifespan\(app:\s*FastAPI\)'
chk app/main.py 'app\.include_router\(.*agent_router'
chk app/main.py 'app\.include_router\(.*interesting_router'
chk app/main.py 'app\.include_router\(.*dashboard_router'
chk app/api/routers/agent.py '@router\.get\("/agent/health"'
chk app/api/routers/interesting.py '@router\.get\('
chk app/api/routers/dashboard.py '@router\.get\('
chk app/search/__init__.py 'def get_vector_index\('
chk app/search/__init__.py 'STORE_BACKEND'
chk app/search/__init__.py 'DATABASE_URL'
chk app/search/__init__.py 'PgVectorIndex|NullVectorIndex'
chk app/search/service.py 'def ingest_object\('
chk app/search/service.py 'def search_vector\('
chk app/search/service.py 'def search_hybrid\('
chk app/search/service.py '_embed_text'
for req in 'PyYAML' 'SQLAlchemy' 'httpx' 'jsonschema' 'pytest'; do
  grep -Eq "^${req}([<=>].*)?$" requirements-smoke.txt && ok "requirements-smoke.txt innehåller ${req}" || fail "requirements-smoke.txt saknar ${req}"
done
chk .github/workflows/smoke.yml 'pip install -r requirements-smoke\.txt'
chk .github/workflows/smoke.yml 'pytest -q'
grep -Eq '^\s*worker:' Makefile && ok "Makefile worker target" || echo "  ⚠️  Makefile worker target saknas (ok)"

echo "==> 3) Snabb Python-import"
python - <<'PY' || errors=$((errors+1))
import importlib, sys
def must(mod, attrs=None):
    m = importlib.import_module(mod)
    if attrs:
        for a in (attrs if isinstance(attrs,(list,tuple)) else [attrs]):
            assert hasattr(m, a), f"{mod} saknar {a}"
    print("✅", "import", mod, ("["+",".join(attrs)+"]" if attrs else ""))
must("app.main")
must("app.api.routers.agent")
must("app.api.routers.interesting")
must("app.api.routers.dashboard")
must("app.search", ["get_vector_index","NullVectorIndex"])
svc = importlib.import_module("app.search.service")
for a in ("ingest_object","search_vector","search_hybrid"): assert hasattr(svc, a)
print("✅ app.search.service API ok")
PY

echo "==> 4) Sammanfattning"
if [[ $errors -gt 0 ]]; then echo "🚨 Audit hittade $errors fel. Avbryter."; exit 1; fi
echo "✅ Audit ok"
