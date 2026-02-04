State: SoT v5.5 baseline (details align with ARCHITECTURE/STATUS).
# Security

Lightweight policy for local and CI runs.

<!-- SECTION:SECURITY:BEGIN -->
## API keys & endpoints
- Store keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) only in local `.env` files or a secrets manager. Never commit them to Git, CI logs, or docs.
- `LLM_PROVIDER=mock` is the CI default, so no external keys are needed for tests.
- If `OLLAMA_URL` is exposed on a network interface, secure the port via SSH tunnel or VPN; default assumption is localhost.

## Least privilege
- The Postgres account (`DATABASE_URL`) uses `app:app` for local dev. In production create a dedicated role with only the required `INSERT/SELECT/UPDATE`.
- CLI smoke commands append to the JSONL audit log (`INDEX_OUTBOX_PATH`). Runtime watcher/worker flows use the DB outbox; keep database permissions minimal and scoped to the outbox/index tables.

## Secrets in CI
- GitHub Actions workflow does not require secrets today. If future jobs do, add them through `secrets.*` and never hardcode fallbacks.
- `requirements.txt` lists public packages; no private indexes are used.

## Logs & PII
- See `docs/PRIVACY.md` for masking policy. Default rule: no raw customer/note text in `extra`.
- Health/agent errors should log stack/exception names only; avoid dumping HTTP payloads.

## Next steps
1. Add TLS / Basic Auth around future FastAPI endpoints.
2. Wrap external calls with `CircuitBreaker` + `timeout_wrapper` to avoid DoS via hanging requests.
3. Add a `pre-commit` check ensuring `OLLAMA_URL` remains localhost-bound.
<!-- SECTION:SECURITY:END -->
