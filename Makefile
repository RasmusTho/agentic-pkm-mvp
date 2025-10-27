.PHONY: smoke
smoke:
	pytest -q tests/system/test_settings_schema.py
	pytest -q tests/index/test_rules.py
	pytest -q tests/e2e/test_index_rules_e2e.py
