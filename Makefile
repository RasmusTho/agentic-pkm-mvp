PYTHON ?= python3
SMOKE_PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))

backfill:
	PYTHONPATH="$(PWD)" DATABASE_URL="$(DATABASE_URL)" $(PYTHON) -m app.jobs.backfill --limit 500 --trace-id job-backfill

.PHONY: smoke
smoke:
	$(SMOKE_PYTHON) -m pytest -q --confcutdir=tests/system tests/system/test_settings_schema.py
