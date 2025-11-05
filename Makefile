export PYTHONPATH := $(PWD)

.PHONY: smoke
smoke:
	pytest -q tests/system/test_settings_schema.py
	pytest -q tests/index/test_rules.py
	pytest -q tests/index/test_ignore_and_defaults.py
	pytest -q tests/index/test_ingest_md_malformed.py
	pytest -q tests/promotion/test_event_shapes.py
	pytest -q tests/promotion/test_policy_move_selection.py
	pytest -q tests/promotion/test_queue_logic.py
	pytest -q tests/promotion/test_reconciliation_rules.py
	pytest -q tests/integration/test_promotion_worker_roundtrip.py
	pytest -q tests/integration/test_batch_move_nightly.py
	pytest -q tests/e2e/test_promotion_intent_to_index.py
	pytest -q tests/smoke/test_promotion_smoke.py
	pytest -q tests/smoke/test_merge_smoke.py

.PHONY: promote-queue
promote-queue:
	python3 -m app.promotion.cli queue "$(path)" "$(uuid)"

.PHONY: promote-run
promote-run:
	python3 -m app.promotion.cli run

.PHONY: agent-run
agent-run:
	python3 -m app.agents.promotion.agent run
PYTHON ?= python

.PHONY: worker
worker:
	@python - <<-'__WORKER__'
	import importlib, runpy, sys, os
	mods = os.environ.get('WORKER_MODULES','app.promotion.queue app.outbox.worker app.jobs.outbox_worker app.services.outbox_worker app.workers.outbox').split()
	for m in mods:
	    try:
	        import importlib; importlib.import_module(m)
	        print(f"[worker] starting {m}")
	        runpy.run_module(m, run_name='__main__')
	        break
	    except ModuleNotFoundError:
	        continue
	else:
	    print('[worker] no known worker module found', file=sys.stderr)
	    sys.exit(2)
	__WORKER__
