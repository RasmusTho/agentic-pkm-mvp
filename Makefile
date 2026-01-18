.PHONY: fmt lint test eval docs smoke ci-smoke setup-merge-driver hygiene-logs indexer-run transcribe qa cold-boot

fmt:
	rufflehog --version >/dev/null 2>&1 || true
	python -m ruff check . --fix
	python -m black .

lint:
	python -m ruff check .
	python -m mypy app || true

test:
	export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; python -m pytest -q -c /dev/null

eval:
	python -m app.eval.run

docs:
	@echo "Docs i ./docs – se README.md"

transcribe:
	@if [ -z "$(SOURCE)" ]; then echo "Usage: make transcribe SOURCE=<URL_OR_FILE>"; exit 1; fi
	python -m app.cli transcribe "$(SOURCE)"

qa:
	@if [ -z "$(QUERY)" ]; then echo "Usage: make qa QUERY='Your question'"; exit 1; fi
	QUERY="$(QUERY)" python -c 'import json, os; from app.agents.qa.agent import answer; res = answer(os.environ["QUERY"]); print(json.dumps(res, ensure_ascii=False, indent=2))'


cold-boot:
	@bash scripts/cold_boot.sh

smoke:
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
	python -m pytest -q -c /dev/null -k "not slow"

reset-zero:
	@bash scripts/reset_to_zero.sh

reset-zero-force:
	@RESET_FORCE=1 bash scripts/reset_to_zero.sh

alpha-e2e-smoke:
	@python - <<'PY'
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
	PYTHONPATH="$(PWD)" python -m app.indexer.runner

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "python -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	mkdir -p logs
	chmod -R u+rwX logs || true


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
	@python scripts/alpha_doctor.py

alpha-bootstrap:
	@if [ -z "$(VAULT_ROOT)" ]; then echo "VAULT_ROOT is required (path to your vault)"; exit 1; fi
	@$(MAKE) alpha-doctor
	@$(MAKE) alpha-up
	@$(MAKE) alpha-status

alpha-down:
	docker compose down

alpha-status:
	@python scripts/alpha_status.py

alpha-smoke:
	@if [ -x scripts/reality_smoke.sh ]; then bash scripts/reality_smoke.sh; else echo "scripts/reality_smoke.sh not found"; fi

alpha-e2e:
	@if [ -z "$(VAULT_ROOT)" ]; then echo "VAULT_ROOT is required (path to your vault)"; exit 1; fi
	VAULT_ROOT="$(VAULT_ROOT)" python -m scripts.alpha_e2e --teardown
