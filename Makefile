.PHONY: smoke ci-smoke setup-merge-driver hygiene-logs indexer-run

smoke:
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null tests -k "not slow and not e2e and not integration"

ci-smoke:
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null -k "not slow"

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
