State: SoT v4.10 Reality-MVP (planned; not implemented yet).
# Auth & Rate Limiting Strategy

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

**Proposed implementation (not yet wired)**
- Add `API_KEY` to `.env`/environment. Default to disabled when empty.
- Create dependency `get_api_key` that validates the header; raise `HTTPException(401)` when invalid.
- Apply to routers via `Depends(get_api_key)` or `APIKeyHeader` from `fastapi.security`.
- Support future multi-key storage by reading from JSON/Redis when needed.

## Rate Limiting Options
| Option | Pros | Cons | Recommendation |
| --- | --- | --- | --- |
| `slowapi` with Redis backend | Compatible with FastAPI, simple decorators | Requires Redis instance | ✅ Preferred for production |
| `fastapi-limiter` | Similar to `slowapi`, includes helpers | Additional dependencies | Alternative |
| Reverse proxy (nginx/traefik) limits | Offloads enforcement, no code changes | Need config + metrics integration | Consider for edge services |
| Application-level counters (in-memory) | Zero dependencies | Not distributed-safe | Useful for local dev only |

**Proposed rollout (not yet wired)**
1. Start with `slowapi` + Redis (or DuckDB-backed cache for dev using `slowapi.Limiter` with memory storage).
2. Apply route-specific limits, e.g. `@limiter.limit("60/minute")` on read endpoints and stricter on POST.
3. Expose headers (`X-RateLimit-Remaining`, etc.) for clients.
4. Include bypass ability for internal cron jobs by matching API key prefixes.

## Implementation Plan (future work)
1. Introduce `settings.api_key` and `settings.rate_limit_enabled` fields.
2. Create `auth.py` module housing API key dependency and optional FastAPI security scheme.
3. Wire dependency into routers or include globally via middleware.
4. Integrate `slowapi` limiter with optional Redis URL from env; fallback to in-memory for dev/testing.
5. Document curl examples and failure responses (`401`, `429`).
6. Expand tests: API key required, missing key, exhausted limit triggers `429`.

## Operational Considerations (future)
- Rotate API keys by updating the env and restarting; keep old key for grace period if needed.
- Monitor rate-limit metrics via `slowapi` storage backend (Redis stats).
- When migrating to OAuth/OIDC, reuse dependency pattern; replace API key check with token validation.

## Next Steps
- Implement API-key dependency and apply across routers (planned).
- Introduce slowapi with configurable rules; ensure CI includes new deps.
- Evaluate long-term IdP integration once external users are on-boarded.
