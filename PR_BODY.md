Summary:
- Route classifier/QA/reasoning + metrics/doctor through the LLM fabric and harden call_llm provider handling (mock override, openai/deepseek, Ollama base URL, max_tokens).
- Add LLM routing contract doc plus COMPONENTS/DOCS_INDEX updates and a guardrail test to prevent provider bypass.
- Extend tests for router precedence, health metadata, alpha-status output, and index-doctor identity.

Tests:
- PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"

Operator verification:
- Active routes/providers: `scripts/alpha_status.py` output and `/api/health` → `checks.llm_router.selected_defaults`, `checks.llm_providers`.
- Example override: `LLM_FORCE_PROVIDER=ollama LLM_FORCE_MODEL=llama3.1:8b-instruct make alpha-up`.
- Guardrail: `test_high_level_llm_access_uses_fabric` in `tests/architecture/test_import_rules.py` enforces fabric-only imports for high-level modules.
