State: SoT v5.5 baseline (implemented for API surfaces; doc includes explicit delta for what’s not yet wired everywhere).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Auth & Rate Limiting (Current Reality + Plan)

## Current Implementation (v5.5)
- API key auth is implemented in `app/auth.py` (`require_api_key`) using the `X-API-Key` header.
  - Auth is **disabled** when `settings.api_key` is `None`.
- Rate limiting is implemented via `slowapi` in `app/auth.py` (`limiter`) and applied on API routes that decorate with `@limiter.limit(...)`.
- API routers currently wiring these:
  - `app/api/items.py` uses both `Depends(require_api_key)` and `@limiter.limit(rate_limit_default())`.
  - `app/api/ingest.py` and `app/api/search.py` also depend on `require_api_key` (auth gating), but may not apply per-route limits unless explicitly decorated.

### Config knobs (env-backed)
- `api_key` (env: `API_KEY`) enables API key auth when set.
- `rate_limit_enabled` enables/disables SlowAPI enforcement.
- `rate_limit_default` controls the default rule string (e.g. `60/minute`).

## Spec / Desired Behavior

## Goals
- Protect the public API surface (`/items`, future endpoints) without blocking internal automation workflows.
- Provide a lightweight mechanism for trusted clients during MVP, with a path to stronger auth when external users arrive.
- Guard against abuse (burst traffic) while keeping latency low for normal usage.

## Authentication Options
| Option | Pros | Cons | Recommendation |
| --- | --- | --- | --- |
| API key via header (`X-API-Key`) checked against env var | Simple to implement; works in serverless/container setups | Single key, manual rotation | ✅ MVP default |
| HTTP Basic auth | Built into many clients | Requires TLS everywhere; still single credential | Optional fallback |
| OAuth2 / OIDC (Auth0, Azure AD) | Scales to multiple users, granular scopes | Requires IdP setup, token validation complexity | Defer until external stakeholders need SSO |
| mTLS | Strong identity auth | Operationally heavy, cert lifecycle | Defer |

**Auth rules**
- Default: disabled unless `API_KEY` is set.
- When enabled: reject unauthorized requests with `401`.
- Future: support multiple keys + rotation without downtime.

## Rate Limiting Options
| Option | Pros | Cons | Recommendation |
| --- | --- | --- | --- |
| `slowapi` with Redis backend | Compatible with FastAPI, simple decorators | Requires Redis instance | ✅ Preferred for production |
| `fastapi-limiter` | Similar to `slowapi`, includes helpers | Additional dependencies | Alternative |
| Reverse proxy (nginx/traefik) limits | Offloads enforcement, no code changes | Need config + metrics integration | Consider for edge services |
| Application-level counters (in-memory) | Zero dependencies | Not distributed-safe | Useful for local dev only |

**Rate limiting rules**
- Default: disabled unless `rate_limit_enabled=true`.
- When enabled: apply `rate_limit_default` to the public API surface; override per-route when needed.
- Future: move storage to Redis when we run multi-instance.

## Delta (Doc vs Code)
- This doc previously described auth/rate limiting as “proposed”; it is now **partially implemented**.
- Remaining gaps to close for “fully wired”:
  - Ensure every externally exposed API router uses `Depends(require_api_key)` consistently.
  - Ensure every route that must be protected has an explicit `@limiter.limit(...)` decorator (or a global middleware policy).
  - Decide on rate limit storage (in-memory vs Redis) for production deployments.

## Operational Considerations
- Rotate API keys by updating the env and restarting; keep old key for grace period if needed.
- Monitor rate-limit metrics via `slowapi` storage backend (Redis stats).
- When migrating to OAuth/OIDC, reuse dependency pattern; replace API key check with token validation.

## Next Steps
- Implement API-key dependency and apply across routers.
- Introduce slowapi with configurable rules; ensure CI includes new deps.
- Evaluate long-term IdP integration once external users are on-boarded.
