export PYTHONPATH := $(PWD)

.PHONY: smoke
smoke:
	pytest -q tests/system/test_settings_schema.py
	pytest -q tests/index/test_rules.py
	pytest -q tests/index/test_ignore_and_defaults.py
	pytest -q tests/e2e/test_index_rules_e2e.py

.PHONY: query
query:
	python3 -m app.cli.query $(term)

.PHONY: index
index:
	python3 -c 'from app.index.main import build_from_canonical_settings as b; print(len(b()))'
