.PHONY: fmt lint test eval docs smoke ci-smoke setup-merge-driver hygiene-logs indexer-run transcribe qa cold-boot start verify verify-runtime doctor persist-runtime-repairs install-skills test-vault-init start-test-system test-bootstrap dev-up dev-down prod-up prod-down test-up test-down dispatcher-init dispatcher-sync

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3 >/dev/null 2>&1; then command -v python3; elif command -v python >/dev/null 2>&1; then command -v python; fi)
TEST_VAULT_ROOT ?= $(PWD)/vault-test
TEST_DATABASE_URL ?= postgresql+psycopg://app:app@db:5432/app_test
SMOKE_WORKERS ?= auto
SMOKE_E2E_WORKERS ?= 0
COMPOSE_BASE := docker compose -f docker-compose.yaml
COMPOSE_DEV := $(COMPOSE_BASE) -f docker-compose.dev.yml -p pkm-dev
COMPOSE_TEST := $(COMPOSE_BASE) -f docker-compose.test.yml -p pkm-test
COMPOSE_PROD := $(COMPOSE_BASE) -p pkm-prod

fmt:
	rufflehog --version >/dev/null 2>&1 || true
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m black .

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy app || true

test:
	export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; $(PYTHON) -m pytest -q -c /dev/null

eval:
	$(PYTHON) -m app.eval.run

docs:
	@echo "Docs i ./docs – se README.md"

transcribe:
	@if [ -z "$(SOURCE)" ]; then echo "Usage: make transcribe SOURCE=<URL_OR_FILE>"; exit 1; fi
	$(PYTHON) -m app.cli transcribe "$(SOURCE)"

qa:
	@if [ -z "$(QUERY)" ]; then echo "Usage: make qa QUERY='Your question'"; exit 1; fi
	QUERY="$(QUERY)" $(PYTHON) -c 'import json, os; from app.agents.qa.agent import answer; res = answer(os.environ["QUERY"]); print(json.dumps(res, ensure_ascii=False, indent=2))'


cold-boot:
	@bash scripts/cold_boot.sh


# make start = daily runtime bring-up
# make cold-boot = from-scratch verification
start:
	@START_MODE=runtime scripts/start_full_system.sh

verify:
	@VERIFY_ACTIVE=1 START_MODE=runtime scripts/start_full_system.sh

verify-runtime:
	@bash scripts/verify_runtime_stack.sh

doctor: verify-runtime

persist-runtime-repairs:
	@bash scripts/persist_runtime_repairs.sh

smoke:
	@XDIST_ARGS=""; \
	if $(PYTHON) -m pytest -p xdist.plugin --help 2>/dev/null | rg -q -- "^-n "; then \
		XDIST_ARGS="-n $(SMOKE_WORKERS) --dist=loadfile"; \
	fi; \
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
	$(PYTHON) -m pytest -p xdist.plugin -q -c /dev/null -k "not slow and not e2e" $$XDIST_ARGS
	@if [ "$(SMOKE_E2E_WORKERS)" != "0" ]; then \
		XDIST_E2E_ARGS=""; \
		if $(PYTHON) -m pytest -p xdist.plugin --help 2>/dev/null | rg -q -- "^-n "; then \
			XDIST_E2E_ARGS="-n $(SMOKE_E2E_WORKERS) --dist=loadfile"; \
		fi; \
		PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
		$(PYTHON) -m pytest -p xdist.plugin -q -c /dev/null -k "e2e and not slow" $$XDIST_E2E_ARGS ; \
	fi

test-vault-init:
	@PYTHON="$(PYTHON)" bash scripts/init_test_vault.sh

reset-zero:
	@bash scripts/reset_to_zero.sh

reset-zero-force:
	@RESET_FORCE=1 bash scripts/reset_to_zero.sh

start-test-system:
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" scripts/start_full_system.sh

test-bootstrap: reset-zero-force test-vault-init
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" scripts/start_full_system.sh
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" bash scripts/verify_runtime_stack.sh
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" $(PYTHON) -m app.cli uat-run-vault-test --vault-root "$(TEST_VAULT_ROOT)" --assert

dev-up:
	@$(COMPOSE_DEV) up -d --build

dev-down:
	@$(COMPOSE_DEV) down --remove-orphans

prod-up:
	@$(COMPOSE_PROD) up -d --build

prod-down:
	@$(COMPOSE_PROD) down --remove-orphans

test-up:
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" $(COMPOSE_TEST) up -d --build

test-down:
	@$(COMPOSE_TEST) down --remove-orphans

alpha-e2e-smoke:
	@$(PYTHON) - <<'PY'
	import os, pathlib, subprocess, sys, tempfile, textwrap
	provider = os.environ.get('LLM_PROVIDER')
	if not provider:
		raise SystemExit('LLM_PROVIDER must be set before running alpha-e2e-smoke')
	note = pathlib.Path(tempfile.mktemp(prefix='tmp/alpha-e2e-smoke-', suffix='.md'))
	content = textwrap.dedent('''
	---
	uuid: alpha-e2e-smoke
	created_by: smoke
	---
	# alpha-e2e-smoke
	- [x] verify note
	''')
	note.write_text(content, encoding='utf-8')
	try:
		subprocess.run([sys.executable, '-m', 'app.cli', 'pipe', str(note)], check=True)
	finally:
		note.unlink(missing_ok=True)
	PY

	@tail -n 5 tmp/index-outbox.jsonl
	@docker compose logs --tail=20 worker || true

ci-smoke: smoke

indexer-run:
	PYTHONPATH="$(PWD)" $(PYTHON) -m app.indexer.runner

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "$(PYTHON) -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	mkdir -p logs
	chmod -R u+rwX logs || true

install-skills:
	@bash scripts/install_skills.sh


.PHONY: alpha alpha-up alpha-up-ollama alpha-bootstrap alpha-doctor alpha-down alpha-status alpha-smoke alpha-e2e alpha-rebuild require-vault-root

require-vault-root:
	@: $(if $(strip $(VAULT_ROOT)),,$(error VAULT_ROOT is required. Example: export VAULT_ROOT="/path/to/your/vault"))

alpha: require-vault-root
	@$(MAKE) alpha-up
	@$(MAKE) alpha-status
	@$(MAKE) alpha-e2e
	@$(MAKE) alpha-smoke

alpha-up: require-vault-root
	VAULT_ROOT="$(VAULT_ROOT)" scripts/start_full_system.sh

alpha-rebuild:
	@if [ "${ALPHA_REBUILD_PULL:-0}" = "1" ]; then docker compose build --pull api worker watcher; else docker compose build api worker watcher; fi

alpha-up-ollama:
	@if [ -z "$(VAULT_ROOT)" ]; then echo "VAULT_ROOT is required (path to your vault)"; exit 1; fi
	VAULT_ROOT="$(VAULT_ROOT)" LLM_PROVIDER=ollama scripts/start_full_system.sh

alpha-doctor:
	@$(PYTHON) scripts/alpha_doctor.py

alpha-bootstrap:
	@if [ -z "$(VAULT_ROOT)" ]; then echo "VAULT_ROOT is required (path to your vault)"; exit 1; fi
	@$(MAKE) alpha-doctor
	@$(MAKE) alpha-up
	@$(MAKE) alpha-status

alpha-down:
	docker compose down

alpha-status:
	@$(PYTHON) scripts/alpha_status.py

alpha-smoke:
	@if [ -x scripts/reality_smoke.sh ]; then bash scripts/reality_smoke.sh; else echo "scripts/reality_smoke.sh not found"; fi

alpha-e2e:
	@if [ -z "$(VAULT_ROOT)" ]; then echo "VAULT_ROOT is required (path to your vault)"; exit 1; fi
	VAULT_ROOT="$(VAULT_ROOT)" $(PYTHON) -m scripts.alpha_e2e --teardown

dispatcher-init:
	$(PYTHON) -m app.dispatcher init --json
	@$(PYTHON) -m app.dispatcher pull --repo RasmusTho/agentic-pkm-mvp --json

dispatcher-sync:
	$(PYTHON) -m app.dispatcher pull --repo RasmusTho/agentic-pkm-mvp --json
