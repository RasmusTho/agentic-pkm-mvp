State: SoT v4.10 Reality-MVP (current core).
# Continuous Integration — Reality-MVP

Primary workflow: `ci-smoke` (push/PR) in `.github/workflows/ci-smoke.yaml`. It runs on Ubuntu with memory stores and mock LLMs and asserts:
1) Doc guardrails (mermaid block in DIAGRAMS, README link markers, no TODO/FIXME in docs/README/CHANGELOG, key phrases in ARCHITECTURE/ROADMAP/STATUS).
2) `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c /dev/null -m "not pg and not alpha_llm"` (fast smoke; excludes Postgres and alpha_llm tests).
3) `python -m app.fitness.report` → validates QAS-003/QAS-010 summary lines and requires `GATES.ok=true`.
4) CLI smoke (`python -m app.cli --help`, `python -m app.cli health --json || true`).
Env defaults mirror docs: `STORE_BACKEND=memory`, `LLM_PROVIDER=mock`, rerank off.

Other workflows:
- `ci.yml` (manual) — YAML/JSON lint of `data/**`, presence checks, a small workspace smoke (`/query`) for the legacy API.
- `ci-lite.yml` (manual) — Postgres-backed smoke; installs dev deps, runs `pytest -q -m "not alpha_llm"` and uploads logs.
- Additional specialty workflows exist (`architecture-ci`, `settings-ci`) but are not on the main PR path.

Local commands (match smoke):
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c /dev/null -m "not pg and not alpha_llm"`
- `python -m app.fitness.report` (expects `GATES.ok=true`)
- For Postgres-backed checks: `DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:15432/app pytest -q -m "not alpha_llm"`

Eval tests (opt-in)
- Marked `@pytest.mark.eval` under `tests/eval/`; run manually when LLM/vector deps are available (see `docs/eval.md`).
- Examples:
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"`
  - `pytest -q -m "eval" tests/eval/test_ask_deepeval.py`
  - `pytest -q -m "eval" tests/eval/test_rag_ragas.py`
- Diagnostic only; not required on PR smoke.
