.PHONY: fmt lint test eval docs smoke ci-smoke setup-merge-driver hygiene-logs indexer-run

fmt:
\trufflehog --version >/dev/null 2>&1 || true
\tpython -m ruff check . --fix
\tpython -m black .

lint:
\tpython -m ruff check .
\tpython -m mypy app || true

test:
\texport PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; python -m pytest -q -c /dev/null

eval:
\tpython -m app.eval.run

docs:
\t@echo "Docs i ./docs – se README.md"

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
