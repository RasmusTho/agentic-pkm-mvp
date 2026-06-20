State: SoT v5.5 baseline (details align with ARCHITECTURE/STATUS).
# Security

Lightweight policy for local and CI runs.

<!-- SECTION:SECURITY:BEGIN -->
## API keys & endpoints
- Store keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) only in local `.env` files or a secrets manager. Never commit them to Git, CI logs, or docs.
- `LLM_PROVIDER=mock` is the CI default, so no external keys are needed for tests.
- Integrated Runtime v1 still exposes non-UI local services on trusted interfaces by default: the FastAPI runtime starts `uvicorn` on `0.0.0.0:8000`, Compose publishes the API host port to container port `8000`, and Ollama sets `OLLAMA_HOST=0.0.0.0:11434`. Companion UI `test-ui` and `prod-ui` launchers bind the browser UI to `127.0.0.1` by default and require `CUI_BIND_LAN=1` for LAN/Tailscale UAT; `dev-ui` is the UAT exception and binds to `0.0.0.0` by default unless forced to loopback with `CUI_BIND_LAN=0`. This is not an internet-ready security boundary.
- For Companion UI non-loopback UAT on non-dev channels, set `CUI_BIND_LAN=1` deliberately. For dev-channel loopback-only work, set `CUI_BIND_LAN=0`. API and Ollama host binding changes are runtime/config changes and should be made deliberately outside the Companion UI launcher default.
- Do not expose the API, Ollama, or Companion UI to untrusted networks without an explicit access-control boundary such as an SSH tunnel, VPN, or reverse-proxy design with auth and TLS.

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
1. Define and implement a post-v1 remote-access capability slice with real auth, TLS, and a reviewed exposure model. Remote/online access is not a config flip on the current trusted-LAN runtime.
2. Wrap external calls with `CircuitBreaker` + `timeout_wrapper` to avoid DoS via hanging requests.
3. If the project later wants an automated localhost-only posture check, add the enforcement first and document the exact command then. No such pre-commit check exists today.

## Auth And Rate Limiting

Current implementation:
- API key auth is implemented via `app/auth.py` and the `X-API-Key` header
- auth is disabled when no API key is configured
- state-changing Companion vault selection and initialization routes preserve unauthenticated
  loopback-local operation, but reject non-loopback requests unless `API_KEY` is configured and the
  request supplies the matching `X-API-Key` header
- the Companion UI same-origin proxy forwards the browser client address for those vault routes; the
  runtime treats a forwarded non-loopback address as non-loopback even though the backend hop is
  loopback
- rate limiting is implemented via `slowapi` where routers apply explicit limit decorators

Current configuration surface:
- `API_KEY`
- `rate_limit_enabled`
- `rate_limit_default`

Operational stance:
- default to auth disabled for loopback-local operation unless explicitly configured
- non-loopback use of state-changing Companion vault selection/initialization requires `API_KEY`
  and should fail with `401` when missing or invalid
- rate limiting should protect public API surfaces without blocking internal trusted automation

Remaining gaps:
- ensure all externally exposed routers apply auth consistently
- ensure routes that require rate limits actually carry explicit limiter wiring
- choose long-term rate-limit storage posture for production (for example Redis-backed vs local-only)
<!-- SECTION:SECURITY:END -->
