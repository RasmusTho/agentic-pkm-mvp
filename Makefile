.PHONY: fmt lint test eval docs smoke ci-smoke setup-merge-driver hygiene-logs indexer-run transcribe qa

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
	@if [ -z "$(QUERY)" ]; then echo "Usage: make qa QUERY='Din fråga'"; exit 1; fi
	python - <<'PY'
from app.agents.qa.agent import answer
import json
res = answer("${QUERY}")
print(json.dumps(res, ensure_ascii=False, indent=2))
PY

smoke:
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory \
	python -m pytest -q -c /dev/null -k "not slow"

ci-smoke: smoke

indexer-run:
	PYTHONPATH="$(PWD)" python -m app.indexer.runner

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "python -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	mkdir -p logs
	chmod -R u+rwX logs || true
