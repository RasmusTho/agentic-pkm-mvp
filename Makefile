<<<<<<< HEAD
.PHONY: smoke ci-smoke setup-merge-driver hygiene-logs indexer-run
=======
.PHONY: smoke ci-smoke setup-merge-driver hygiene-logs
>>>>>>> 40e55c3 (fix(ci): Python 3.12, matrix & concurrency; repo hygiene and semantic merge)

smoke:
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
	pytest -q -c /dev/null tests -k "not slow and not e2e and not integration"

ci-smoke:
<<<<<<< HEAD
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 scripts/check_code_fences.py
	PYTHONPATH="$(PWD)" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c /dev/null tests -k "not slow"

indexer-run:
	PYTHONPATH="$(PWD)" python -m app.indexer.runner
=======
	python scripts/check_code_fences.py
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory pytest -q
	DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" alembic upgrade head || true
	PYTHONPATH="$(PWD)" STORE_BACKEND=pg DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q || true
>>>>>>> 40e55c3 (fix(ci): Python 3.12, matrix & concurrency; repo hygiene and semantic merge)

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "python -m app.cli.merge_driver %O %A %B"

hygiene-logs:
<<<<<<< HEAD
	@echo "Ensuring logs/ exists and is writable"
	mkdir -p logs
	touch logs/.gitkeep || true
=======
	[ -d logs ] || mkdir -p logs
	chmod -R u+rwX,go-rwx logs
	printf '' > logs/.gitkeep
	git add -f logs/.gitkeep .gitignore >/dev/null 2>&1 || true
>>>>>>> 40e55c3 (fix(ci): Python 3.12, matrix & concurrency; repo hygiene and semantic merge)
