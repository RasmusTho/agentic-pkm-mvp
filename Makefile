export PYTHONPATH := $(PWD)

.PHONY: smoke
smoke:
	python3 -m pytest -q tests/system/test_settings_schema.py
	python3 -m pytest -q tests/index/test_rules.py
	python3 -m pytest -q tests/e2e/test_index_rules_e2e.py
	python3 -m pytest -q tests/cli/test_settings_cli.py

.PHONY: query
query:
	python3 -m app.cli.query $(term)
