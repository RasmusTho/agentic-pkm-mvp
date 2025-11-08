.PHONY: smoke ci-smoke setup-merge-driver hygiene-logs

smoke:
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory pytest -q tests/smoke

ci-smoke:
	python scripts/check_code_fences.py
	PYTHONPATH="$(PWD)" STORE_BACKEND=memory pytest -q
	DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" alembic upgrade head || true
	PYTHONPATH="$(PWD)" STORE_BACKEND=pg DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q || true

setup-merge-driver:
	git config merge.semanticmd.name "Semantic Markdown merge"
	git config merge.semanticmd.driver "python -m app.cli.merge_driver %O %A %B"

hygiene-logs:
	[ -d logs ] || mkdir -p logs
	chmod -R u+rwX,go-rwx logs
	printf '' > logs/.gitkeep
	git add -f logs/.gitkeep .gitignore >/dev/null 2>&1 || true
