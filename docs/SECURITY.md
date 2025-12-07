State: SoT v4.10 Reality-MVP (current, minimal hardening).
# Security

Lightweight policy for local and CI runs.

<!-- SECTION:SECURITY:BEGIN -->
## API keys & endpoints
- Reality-MVP runs in a trusted, single-user context; no auth middleware or API-key checks are wired today.
- Store any optional provider keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) only in local `.env` files or a secrets manager. Never commit them to Git, CI logs, or docs.
- `LLM_PROVIDER=mock` is the CI default, so no external keys are needed for tests.
- If `OLLAMA_URL` is exposed on a network interface, secure the port via SSH tunnel or VPN; default assumption is localhost.

## Least privilege
- The Postgres account (`DATABASE_URL`) uses `app:app` with minimal privileges for local dev. For any broader deployment, create a dedicated role with only the required `INSERT/SELECT`.
- CLI commands only write to `INDEX_OUTBOX_PATH`; run them under a user with limited rights to minimize blast radius.

## Secrets in CI
- GitHub Actions workflow does not require secrets today. If future jobs do, add them through `secrets.*` and never hardcode fallbacks.
- `requirements.txt` lists public packages; no private indexes are used.

## Logs & PII
- See `docs/PRIVACY.md` for masking policy. Default rule: no raw customer/note text in `extra`.
- Health/agent errors should log stack/exception names only; avoid dumping HTTP payloads.

## Next steps
1. Add TLS / API-key or Basic Auth around public-facing FastAPI endpoints (planned).
2. Wrap external calls with `CircuitBreaker` + `timeout_wrapper` to avoid DoS via hanging requests.
3. Add a `pre-commit` check ensuring `OLLAMA_URL` remains localhost-bound.
<!-- SECTION:SECURITY:END -->
