.PHONY: smoke ci-smoke setup-merge-driver hygiene-logs indexer-run

smoke:
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null tests -k "not slow and not e2e and not integration"

ci-smoke:
	python scripts/check_code_fences.py
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null tests -k "not slow and not e2e and not integration"
	DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" alembic upgrade head
	PYTHONPATH="$(PWD)" STORE_BACKEND=pg DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null tests -k "not slow and not e2e and not integration"

indexer-run:
	PYTHONPATH="$(PWD)" python -m app.indexer.runner

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "python -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	[ -d logs ] || mkdir -p logs
	chmod -R u+rwX,go-rwx logs
	printf '' > logs/.gitkeep
	git add -f logs/.gitkeep .gitignore >/dev/null 2>&1 || true
