.PHONY: fmt lint test eval docs smoke ci-smoke setup-merge-driver hygiene-logs indexer-run transcribe qa cold-boot start verify verify-runtime doctor persist-runtime-repairs install-skills test-vault-init bootstrap-test-channel bootstrap-test-channel-config start-test-system test-bootstrap dev-up dev-down dev-start-full prod-up prod-down prod-start-full test-start-full test-up test-down deploy-dev deploy-test deploy-prod rollback-dev rollback-test rollback-prod check-test-channel check-prod-channel live-prod-probe dev-ui dev-ui-doctor test-ui test-ui-doctor prod-ui prod-ui-doctor dispatcher-init dispatcher-sync db-snapshot db-restore db-dump-prod

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3 >/dev/null 2>&1; then command -v python3; elif command -v python >/dev/null 2>&1; then command -v python; fi)
# Test vault root for bootstrap / seeded test startup lanes. Honors an
# explicit TEST_VAULT_ROOT make/env override first, then VAULT_ROOT_TEST, then
# the repo-local scratch vault. Plain VAULT_ROOT is a runtime binding and may
# point at the operator/prod vault, so it must not select the test seed vault
# implicitly. `start-test-system` has a separate idle-by-default derivation
# below so a fresh checkout can boot with no vault selected.
TEST_VAULT_ROOT ?= $(or $(VAULT_ROOT_TEST),vault-test)
# `start-test-system` should only honor an explicitly supplied test vault path.
# If neither TEST_VAULT_ROOT nor VAULT_ROOT_TEST was explicitly set by the
# caller, leave VAULT_ROOT empty so scripts/start_full_system.sh enters the
# no-vault idle posture instead of forcing the repo-local scratch vault.
START_TEST_SYSTEM_VAULT_ROOT := $(if $(filter command line environment,$(origin TEST_VAULT_ROOT)),$(TEST_VAULT_ROOT),$(if $(filter command line environment,$(origin VAULT_ROOT_TEST)),$(VAULT_ROOT_TEST),))
# Host-reachable test DSN. Host-side tools (migrations, `uat-run-vault-test`,
# promote-to-test verify) reach Postgres on the published port 127.0.0.1:15434;
# the in-container `db:5432` address is unreachable from the host (issue #1997
# symptom 4). Containers keep `db:5432` via docker-compose.test.yml.
TEST_DATABASE_URL ?= postgresql+psycopg://app:app@127.0.0.1:15434/app_test
TEST_API_BASE_URL ?= http://127.0.0.1:18002
TEST_LLM_PROVIDER ?= mock
TEST_LLM_MODEL ?= llama3.1:8b
SMOKE_WORKERS ?= auto
SMOKE_E2E_WORKERS ?= 0
APP_CODE_BIND_COMPOSE ?=
COMPOSE_UP_BUILD := $(if $(strip $(APP_CODE_BIND_COMPOSE)),--build,)
COMPOSE_DEV_FILES := docker-compose.yaml$(if $(strip $(APP_CODE_BIND_COMPOSE)),:$(APP_CODE_BIND_COMPOSE)):docker-compose.dev.yml
COMPOSE_TEST_FILES := docker-compose.yaml$(if $(strip $(APP_CODE_BIND_COMPOSE)),:$(APP_CODE_BIND_COMPOSE)):docker-compose.test.yml
COMPOSE_PROD_FILES := docker-compose.yaml$(if $(strip $(APP_CODE_BIND_COMPOSE)),:$(APP_CODE_BIND_COMPOSE)):docker-compose.prod.yml
COMPOSE_BASE := docker compose -f docker-compose.yaml $(if $(strip $(APP_CODE_BIND_COMPOSE)),-f $(APP_CODE_BIND_COMPOSE),)
COMPOSE_DEV := $(COMPOSE_BASE) --env-file config/deploy/dev.env -f docker-compose.dev.yml -p pkm-dev
COMPOSE_TEST := $(COMPOSE_BASE) --env-file config/deploy/test.env -f docker-compose.test.yml -p pkm-test
COMPOSE_PROD := $(COMPOSE_BASE) --env-file config/deploy/prod.env -f docker-compose.prod.yml -p pkm-prod
TEST_COMPOSE_ENV := COMPOSE_FILE=$(COMPOSE_TEST_FILES) COMPOSE_PROJECT_NAME=pkm-test
# Runtime version marker (issue #2602). Computed once and exported so every
# `docker compose build` invocation (dev-up, prod-up, test-up, alpha-up) bakes
# the real git SHA + build time into the image via compose build-args. Override
# via the environment if needed; defaults preserve current behavior when unset.
VCS_REF ?= $(shell git rev-parse HEAD 2>/dev/null)
BUILT_AT ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
export VCS_REF
export BUILT_AT

fmt:
	rufflehog --version >/dev/null 2>&1 || true
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m black .

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy app || true

test:
	@PYTEST_PLUGIN_ARGS=""; \
	if $(PYTHON) -c "import pytest_asyncio.plugin" >/dev/null 2>&1; then \
		PYTEST_PLUGIN_ARGS="-p pytest_asyncio.plugin"; \
	fi; \
	export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; \
	$(PYTHON) -m pytest $$PYTEST_PLUGIN_ARGS -q -c /dev/null --import-mode=importlib

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
	@PYTEST_PLUGIN_ARGS=""; \
	XDIST_ARGS=""; \
	if $(PYTHON) -c "import xdist.plugin" >/dev/null 2>&1; then \
		PYTEST_PLUGIN_ARGS="-p xdist.plugin"; \
		XDIST_ARGS="-n $(SMOKE_WORKERS) --dist=loadfile"; \
	fi; \
	if $(PYTHON) -c "import pytest_asyncio.plugin" >/dev/null 2>&1; then \
		PYTEST_PLUGIN_ARGS="$$PYTEST_PLUGIN_ARGS -p pytest_asyncio.plugin"; \
	fi; \
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
	$(PYTHON) -m pytest $$PYTEST_PLUGIN_ARGS -q -c /dev/null --import-mode=importlib -k "not slow and not e2e" $$XDIST_ARGS
	@if [ "$(SMOKE_E2E_WORKERS)" != "0" ]; then \
		PYTEST_E2E_PLUGIN_ARGS=""; \
		XDIST_E2E_ARGS=""; \
		if $(PYTHON) -c "import xdist.plugin" >/dev/null 2>&1; then \
			PYTEST_E2E_PLUGIN_ARGS="-p xdist.plugin"; \
			XDIST_E2E_ARGS="-n $(SMOKE_E2E_WORKERS) --dist=loadfile"; \
		fi; \
		if $(PYTHON) -c "import pytest_asyncio.plugin" >/dev/null 2>&1; then \
			PYTEST_E2E_PLUGIN_ARGS="$$PYTEST_E2E_PLUGIN_ARGS -p pytest_asyncio.plugin"; \
		fi; \
		PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
		$(PYTHON) -m pytest $$PYTEST_E2E_PLUGIN_ARGS -q -c /dev/null --import-mode=importlib -k "e2e and not slow" $$XDIST_E2E_ARGS ; \
	fi

test-vault-init:
	@PYTHON="$(PYTHON)" bash scripts/init_test_vault.sh

# The ONE idempotent test-channel bring-up (issue #1997 F3). Single source of
# truth: vault init + canonical channel env + fail-loud preflight, then the
# single-watcher Docker stack. Safe to re-run. Use `bootstrap-test-channel-config`
# for the Docker-free config layer (CI / no-engine hosts).
bootstrap-test-channel:
	@PYTHON="$(PYTHON)" bash scripts/bootstrap_test_channel.sh

bootstrap-test-channel-config:
	@PYTHON="$(PYTHON)" bash scripts/bootstrap_test_channel.sh --config-only

reset-zero:
	@bash scripts/reset_to_zero.sh

reset-zero-force:
	@RESET_FORCE=1 bash scripts/reset_to_zero.sh

# No require-test-vault-root guard: the runtime must be able to start without a
# vault selected (#2005). start_full_system.sh routes an unset/empty VAULT_ROOT
# to the no-vault idle posture (picker state), and fails loud only on a
# set-but-missing path — so requiring a vault here would defeat idle boot.
start-test-system:
	@$(TEST_COMPOSE_ENV) VAULT_ROOT="$(START_TEST_SYSTEM_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" API_BASE_URL="$(TEST_API_BASE_URL)" HEALTH_ENDPOINT="$(TEST_API_BASE_URL)/healthz" LLM_PROVIDER="$(TEST_LLM_PROVIDER)" LLM_MODEL="$(TEST_LLM_MODEL)" scripts/start_full_system.sh

test-bootstrap: require-test-vault-root
	@$(TEST_COMPOSE_ENV) RESET_FORCE=1 bash scripts/reset_to_zero.sh
	@bash scripts/init_test_vault.sh
	@$(TEST_COMPOSE_ENV) VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" API_BASE_URL="$(TEST_API_BASE_URL)" HEALTH_ENDPOINT="$(TEST_API_BASE_URL)/healthz" LLM_PROVIDER="$(TEST_LLM_PROVIDER)" LLM_MODEL="$(TEST_LLM_MODEL)" VERIFY_RUNTIME_SERVICE_WAIT_SECONDS=30 scripts/start_full_system.sh
	@$(TEST_COMPOSE_ENV) VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" API_BASE_URL="$(TEST_API_BASE_URL)" LLM_PROVIDER="$(TEST_LLM_PROVIDER)" LLM_MODEL="$(TEST_LLM_MODEL)" VERIFY_RUNTIME_SERVICE_WAIT_SECONDS=30 bash scripts/verify_runtime_stack.sh
	@$(TEST_COMPOSE_ENV) VAULT_ROOT="$(TEST_VAULT_ROOT)" DATABASE_URL="$(TEST_DATABASE_URL)" DB_DSN="$(TEST_DATABASE_URL)" LLM_PROVIDER="$(TEST_LLM_PROVIDER)" LLM_MODEL="$(TEST_LLM_MODEL)" $(PYTHON) -m app.cli uat-run-vault-test --vault-root "$(TEST_VAULT_ROOT)" --assert

dev-up:
	@$(COMPOSE_DEV) up -d $(COMPOSE_UP_BUILD)

dev-down:
	@$(COMPOSE_DEV) down --remove-orphans

dev-start-full:
	@COMPOSE_FILE="$(COMPOSE_DEV_FILES)" \
	COMPOSE_PROJECT_NAME="pkm-dev" \
	PKM_ENVIRONMENT="dev" \
	START_MODE=runtime \
	scripts/start_full_system.sh

# Canonical dev/Niflheim Companion UI startup + doctor (Issue #1358).
# dev-ui orchestrates the dev runtime API and Companion UI dev page against the
# Niflheim vault in one command. dev-ui-doctor is the read-only diagnostic.
dev-ui:
	@bash scripts/dev/start_niflheim_ui.sh

dev-ui-doctor:
	@bash scripts/dev/dev_ui_doctor.sh

# Canonical test/Bifröst Companion UI startup + doctor (Issue #1359).
# Same pattern as dev-ui, bound to the test channel (PKM_ENVIRONMENT=test,
# pkm-test, app_test, API 18002, UI 8112) with channel separation preserved.
test-ui:
	@bash scripts/test/start_bifrost_ui.sh

test-ui-doctor:
	@bash scripts/test/test_ui_doctor.sh

# Canonical prod/Midgård Companion UI startup + doctor with guardrails (Issue #1360).
# prod-ui defaults to a safe verification posture (watchers/workers NOT auto-started);
# write/automation-capable startup requires PROD_UI_ENABLE_AUTOMATION=1.
# prod-ui-doctor is the read-only diagnostic (incl. automation-flag safety check).
prod-ui:
	@bash scripts/prod/start_midgard_ui.sh

prod-ui-doctor:
	@bash scripts/prod/prod_ui_doctor.sh

prod-up:
	@$(COMPOSE_PROD) up -d $(COMPOSE_UP_BUILD)

prod-down:
	@$(COMPOSE_PROD) down --remove-orphans

prod-start-full:
	COMPOSE_FILE="$(COMPOSE_PROD_FILES)" \
	COMPOSE_PROJECT_NAME="pkm-prod" \
	PKM_ENVIRONMENT="prod" \
	VERIFY_RUNTIME_SERVICE_WAIT_SECONDS=60 \
	bash scripts/prod/start_midgard_stack.sh

test-start-full: require-vault-root
	COMPOSE_FILE="$(COMPOSE_TEST_FILES)" \
	COMPOSE_PROJECT_NAME="pkm-test" \
	PKM_ENVIRONMENT="test" \
	VAULT_ROOT="$(VAULT_ROOT)" \
	VERIFY_RUNTIME_SERVICE_WAIT_SECONDS=60 \
	scripts/start_full_system.sh

test-up:
	@VAULT_ROOT="$(TEST_VAULT_ROOT)" VAULT_HOST_ROOT="$(TEST_VAULT_ROOT)" $(COMPOSE_TEST) -f docker-compose.legacy-vault.yml up -d $(COMPOSE_UP_BUILD)

test-down:
	@$(COMPOSE_TEST) down --remove-orphans

deploy-dev:
	@bash scripts/deploy_channel.sh deploy dev "$(SHA)"

deploy-test:
	@bash scripts/deploy_channel.sh deploy test "$(SHA)"

deploy-prod:
	@bash scripts/deploy_channel.sh deploy prod "$(SHA)"

rollback-dev:
	@bash scripts/deploy_channel.sh rollback dev $(if $(SHA),"$(SHA)",)

rollback-test:
	@bash scripts/deploy_channel.sh rollback test $(if $(SHA),"$(SHA)",)

rollback-prod:
	@bash scripts/deploy_channel.sh rollback prod $(if $(SHA),"$(SHA)",)

## check-test-channel: run pytest channel-isolation suites for the test channel
check-test-channel:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q \
		tests/ops/test_release_channel_isolation.py \
		tests/ops/test_release_channel_startup_targets.py \
		tests/release_channels/test_channel_isolation_preflight.py

## check-prod-channel: run pytest channel-isolation suites for the prod channel
check-prod-channel:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q \
		tests/ops/test_release_channel_isolation.py \
		tests/ops/test_release_channel_startup_targets.py

## live-prod-probe: invoke the prod-down backstop probe once for a manual spot-check
## This hits the real PROBE_BASE_URL (default localhost:8000); it is NOT a pytest suite.
## For the channel-isolation pytest suites, use check-prod-channel / check-test-channel.
live-prod-probe:
	@$(PYTHON) ops/host-setup/mac-mini/prod_probe.py

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
	@echo "indexer-run: app.indexer.runner has been removed (#2480)."
	@echo "Use the DB outbox worker path instead: PYTHONPATH=\"$(PWD)\" $(PYTHON) -m app.workers.outbox_worker"

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "$(PYTHON) -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	mkdir -p logs
	chmod -R u+rwX logs || true

install-skills:
	@bash scripts/install_skills.sh


.PHONY: alpha alpha-up alpha-up-ollama alpha-bootstrap alpha-doctor alpha-down alpha-status alpha-smoke alpha-e2e alpha-rebuild require-vault-root require-test-vault-root

require-vault-root:
	@: $(if $(strip $(VAULT_ROOT)),,$(error VAULT_ROOT is required. Example: export VAULT_ROOT="/path/to/your/vault"))

require-test-vault-root:
	@: $(if $(strip $(TEST_VAULT_ROOT)),,$(error TEST_VAULT_ROOT is empty: set TEST_VAULT_ROOT or VAULT_ROOT_TEST to a test vault, or allow the repo-local vault-test fallback.))

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

# ── Dev/test DB snapshot & forensic dump ─────────────────────────────────────
# These targets are dev-ergonomics and on-demand forensic tooling.
# They are NOT scheduled disaster recovery — the vault is the durable SoR.
# See docs/OPERATIONS.md § "DB snapshot/restore".
#
# DSN resolution: reads DATABASE_URL (or DB_DSN) from the environment via
# app/db/dsn.py::resolve_dsn(), matching the pattern used by all app code.
# Host-published ports: dev=app_dev:15433, test=app_test:15434, prod=app:15432.
# For dev, export DATABASE_URL=postgresql://app:app@127.0.0.1:15433/app_dev
# For prod forensics, export DATABASE_URL from .env.prod.local before calling
# db-dump-prod (never hardcode the prod DSN here).
#
# SAFETY: db-restore defaults to the newest dev_*/test_* snapshot only
# (never a prod_*.dump) and refuses to run against a prod DSN unless
# ALLOW_PROD_RESTORE=1 is set. db-dump-prod is dump-only; it never restores.
# db-snapshot refuses prod-looking DSNs so prod capture stays on the explicit
# db-dump-prod path and never lands in a dev_-prefixed snapshot.

SNAPSHOT_DIR ?= .db-snapshots

db-snapshot:
	@STAMP=$$(date -u +%Y%m%dT%H%M%SZ); \
	DSN=$$($(PYTHON) -c "from app.db.dsn import resolve_dsn; print(resolve_dsn())"); \
	if [ -z "$$DSN" ]; then echo "ERROR: DATABASE_URL / DB_DSN is not set"; exit 1; fi; \
	if $(PYTHON) -c "import sys; from app.db.dsn import looks_like_prod_dsn; sys.exit(0 if looks_like_prod_dsn() else 1)"; then \
		echo "REFUSING: db-snapshot target DSN looks like prod (db 'app' or port 15432). Use db-dump-prod for prod forensic dumps."; exit 1; fi; \
	mkdir -p "$(SNAPSHOT_DIR)"; \
	DUMP_FILE="$(SNAPSHOT_DIR)/dev_$$STAMP.dump"; \
	echo "Snapshotting dev DB → $$DUMP_FILE"; \
	pg_dump --format=custom --no-password --file="$$DUMP_FILE" "$$DSN" && \
	echo "Snapshot written: $$DUMP_FILE"

db-restore:
	@SNAP="$(SNAPSHOT)"; \
	if [ -z "$$SNAP" ]; then \
		SNAP=$$(ls -1t "$(SNAPSHOT_DIR)"/dev_*.dump "$(SNAPSHOT_DIR)"/test_*.dump 2>/dev/null | head -1); \
	fi; \
	if [ -z "$$SNAP" ]; then echo "ERROR: no dev_/test_ snapshot found in $(SNAPSHOT_DIR)/. Use SNAPSHOT=path/to/file.dump for a named restore."; exit 1; fi; \
	DSN=$$($(PYTHON) -c "from app.db.dsn import resolve_dsn; print(resolve_dsn())"); \
	if [ -z "$$DSN" ]; then echo "ERROR: DATABASE_URL / DB_DSN is not set"; exit 1; fi; \
	if [ "$(ALLOW_PROD_RESTORE)" != "1" ] && $(PYTHON) -c "import sys; from app.db.dsn import looks_like_prod_dsn; sys.exit(0 if looks_like_prod_dsn() else 1)"; then \
		echo "REFUSING: target DSN looks like prod (db 'app' or port 15432). Set ALLOW_PROD_RESTORE=1 to override."; exit 1; fi; \
	echo "Restoring from $$SNAP → $$DSN"; \
	pg_restore --clean --if-exists --no-password --dbname="$$DSN" "$$SNAP" && \
	echo "Restore complete."

db-dump-prod:
	@mkdir -p "$(SNAPSHOT_DIR)"
	@STAMP=$$(date -u +%Y%m%dT%H%M%SZ); \
	DSN=$$($(PYTHON) -c "from app.db.dsn import resolve_dsn; print(resolve_dsn())"); \
	if [ -z "$$DSN" ]; then echo "ERROR: DATABASE_URL / DB_DSN is not set. Source .env.prod.local first."; exit 1; fi; \
	DUMP_FILE="$(SNAPSHOT_DIR)/prod_$$STAMP.dump"; \
	echo "Forensic dump of prod DB → $$DUMP_FILE"; \
	pg_dump --format=custom --no-password --file="$$DUMP_FILE" "$$DSN" && \
	echo "Prod forensic dump written: $$DUMP_FILE"
