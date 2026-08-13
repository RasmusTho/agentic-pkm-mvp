State: SoT v5.5 baseline (details align with ARCHITECTURE/STATUS).
# Security

Lightweight policy for local and CI runs.

<!-- SECTION:SECURITY:BEGIN -->
## API keys & endpoints
- Store keys (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) only in local `.env` files or a secrets manager. Never commit them to Git, CI logs, or docs.
- `LLM_PROVIDER=mock` is the CI default, so no external keys are needed for tests.
- Integrated Runtime v1 still exposes non-UI local services on trusted interfaces by default: the FastAPI runtime starts `uvicorn` on `0.0.0.0:8000`, Compose publishes the API host port to container port `8000`, and Ollama sets `OLLAMA_HOST=0.0.0.0:11434`. Companion UI launchers bind the browser UI to `127.0.0.1` by default and require `CUI_BIND_LAN=1` for LAN/Tailscale UAT. This is not an internet-ready security boundary.
- For Companion UI non-loopback UAT, set `CUI_BIND_LAN=1` deliberately. API and Ollama host binding changes are runtime/config changes and should be made deliberately outside the Companion UI launcher default.
- Do not expose the API, Ollama, or Companion UI to untrusted networks without an explicit access-control boundary such as an SSH tunnel, VPN, or reverse-proxy design with auth and TLS.

## Delegated local operator principal (MVR-03, shipped)

An API key is a **credential**, and `appInstallId` is **instance identity**. Neither is a
principal. MVR-03 (#3857) ships the missing producer: a private, versioned delegated
operator-role record that governed operations resolve a principal from.

Shipped mapping — `app/instance/local_operator_principal.py`, `app/auth.py`:

- The record lives at `<instance-state>/agentic-pkm/local-operator-principal.json` under the
  MVR-01 instance-state boundary: mode `0600` inside a mode-`0700` directory, written through
  a lock + atomic-replace + `fsync` path. Native installs use the same layout in private
  app-data. It carries its own schema (`agentic-pkm.local-operator-principal.v1`), a
  monotonic revision, and migration provenance.
- `local_operator_role_id` is CSPRNG-minted and opaque. It is **not derived** from the
  credential, from its fingerprint, from `appInstallId`, or from any path.
- Three **server-derived** subjects map to that one role: `trusted_loopback` (bindable when
  the operator declares a loopback-local listener at bootstrap, and re-proved on **every
  request** from the effective client host before it is ever used — the request-path proof is
  what enforces it, the bootstrap flag only decides whether the subject exists),
  `trusted_companion_proxy` (the immediate peer is the server-configured,
  middleware-validated Companion UI container), and
  `api_key_credential` (the configured #2223 key, matched by non-reversible fingerprint —
  the raw key never reaches durable state, a log, a receipt, or a cache key). A proxy,
  forwarding, or client header can claim none of them; `resolve_auth_subject` and
  `require_loopback_or_api_key` share one decision path so the admitting subject and the
  admission decision cannot diverge.
- Configuring or rotating an API key binds the credential fingerprint to the **same** role id
  and does not disable the already-supported loopback/proxy subjects. Only an explicit
  governed posture change (`revoke_subject`) may drop one, and it is atomic.
- An explicitly added human or agent role receives a **distinct** principal id; roles never
  merge or alias.
- **Fail-closed principal resolution.** A governed operation with no resolved
  principal/delegated role fails closed — there is no anonymous fallback and no
  "derive it from the instance" branch. Multiple ambiguous credentials, any other
  zero-credential non-loopback posture, unsafe ownership or mode, missing durable storage,
  and a partial record each raise `PrincipalPreflightError` carrying an explicit
  provisioning action.
- The instance identity is carried separately in every snapshot and can never derive, equal,
  or substitute for a principal.

Selection carries no authority. The active-context selection bearer
(`docs/contracts/ACTIVE_CONTEXT_SET.md :: ActiveContextSet`) is an expiring capability used
*in addition to* the #2223 gate; it stores no action, write class, or permission, and GOV
authorizes every binding independently per call.

### devUI loopback-published gateway admission (#4841)

The production devUI read transport uses a narrower subset of the delegated local subjects. Its
browser boundary is the explicitly rendered host publish
`COMPANION_UI_BIND_HOST=127.0.0.1` → `127.0.0.1:8113:8113`, not the gateway container's
`HOST=0.0.0.0` listener and not the request peer observed inside Docker. Missing, wildcard,
non-loopback, mixed-resolution, or unresolvable declarations leave ordinary Companion health
available but keep the devUI gateway routes unavailable. Port `18000` remains direct API
health/version diagnostics only; it is not a supported devUI browser origin.
The canonical production Compose file fixes both sides of that producer pair to loopback, and the
production deploy wrapper fails before mutation if the publish or process declaration is absent,
ambient, wildcard, or otherwise drifts from the exact pair.

The gateway admits only a local loopback `Host` with no forwarded identity header, including
`Forwarded`, every `X-Forwarded-*` name, and `Via`. It proxies exactly GET
`/api/devui/overview` without a query and GET `/api/devui/focus` with one nonempty `subject`
query. It rejects unknown devUI paths, wildcards, duplicate/extra query keys, and every write verb.
Each admitted call is a new server-side request built from the configured API origin plus that
exact path/query; inbound `Host`, API key, authorization, forwarding, client-IP, and proxy headers
are never copied upstream.

FastAPI rejects forwarded identity before resolving a subject. It then admits either the existing
direct-loopback + local-Host path or the exact server-derived result
`resolve_auth_subject(request, None) == SUBJECT_TRUSTED_COMPANION_PROXY`. API-key subjects,
arbitrary bridge/LAN/Tailscale peers, and missing or unresolvable Companion proxy configuration
fail closed. #4841 supplies transport only: it adds no FastAPI page/static route and no remote
browser mode; presentation consumer #4836 must reuse this boundary unchanged.

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
- the Companion UI same-origin proxy forwards the browser client address for vault select,
  initialize, and browse routes. The runtime honors `X-Forwarded-For` only when the immediate peer is
  loopback or is listed in the opt-in `COMPANION_TRUSTED_PROXY_HOSTS` allowlist, so a configured
  same-host docker-bridge gateway can preserve loopback-local operation without letting arbitrary
  callers spoof loopback.
- rate limiting is implemented via `slowapi` where routers apply explicit limit decorators

Current configuration surface:
- `API_KEY`
- `COMPANION_TRUSTED_PROXY_HOSTS` (comma-separated trusted proxy IPs/hosts/CIDRs whose
  `X-Forwarded-For` value may be used for Companion vault-route loopback/auth decisions)
- `rate_limit_enabled`
- `rate_limit_default`

Operational stance:
- default to auth disabled for loopback-local operation unless explicitly configured
- non-loopback use of state-changing Companion vault selection/initialization requires `API_KEY`
  and should fail with `401` when missing or invalid
- docker-bridge or reverse-proxy deployments may add only the Companion gateway/proxy hop to
  `COMPANION_TRUSTED_PROXY_HOSTS`; do not add broad untrusted LAN ranges unless that network is an
  intentional trusted proxy boundary
- rate limiting should protect public API surfaces without blocking internal trusted automation

BuilderOps independent control-plane contract (#3790):
- BuilderOps does not inherit Product `API_KEY`, loopback bypass, or Companion proxy trust. Its
  independent service requires a bearer credential on health, status, metrics, record, and lease
  routes even when the caller is on the tailnet or loopback.
- The server-side credential manifest carries scope, revocation/rotation metadata, a non-secret
  SHA-256 verifier, bounded token length, and references only. Token length permits verifier-only
  substring scanning without retaining the bearer. Raw values may be supplied through host secret
  files for compatibility bootstrap but are never returned or stored in BuilderOps PostgreSQL.
- Complete durable request documents, including identifiers, envelope metadata, idempotency keys,
  and payloads, fail closed on registered bearer values, credential-shaped keys,
  credential-bearing database URLs, and known provider-token shapes. Secret references,
  fingerprints, scopes, credential IDs, and rotation generations remain valid durable metadata.
- Normal client, executor, probe, and operator scopes are separate. Authentication failure is
  `401`, insufficient scope is `403`, and a per-principal service limiter returns `429` without
  logging the bearer.
- The host outage probe uses distinct host-secret credentials for `health:read` readiness and
  `status:read` recovery-state inspection; the narrower health credential is never promoted to a
  broader scope merely to simplify the probe.
- Tailnet TLS is the transport boundary, not authentication. Live activation still requires an
  operator-provided separate BuilderOps engine on the configured control-plane host, real immutable
  pins, scoped host secrets, and the later BCP cutover gates. Deployment rejects active
  Funnel/public exposure before mutating Tailscale Serve, then configures HTTPS termination to the
  loopback-only API port and verifies the expected mapping; the repo configuration alone does not
  claim a running production service.
- Durable metadata allowlists are shape-checked: fingerprints must be SHA-256 values, secret
  references must identify a supported host-secret provider, and scope/rotation fields must have
  their bounded canonical forms. Credential IDs and verifier fingerprints are unique, and malformed
  manifest metadata fails closed before status is rendered. Credential-like spelling variants such
  as `APIKey` and credential-shaped values embedded in ordinary text remain denied.
- Candidate control-plane and PostgreSQL/WAL-G images must pass a real encrypted backup plus
  archived-WAL restore gate. The gate uses independent recovery-key material, binds verification to
  the restored PostgreSQL data directory, validates the recovery fence, and scans recovery material
  and restored state for raw credentials. Main CI then emits and GitHub-attests one candidate-pair
  receipt binding the source SHA to both exact `linux/amd64` digests; deployment rejects independent
  digest arguments or an unattested/mismatched receipt. Verification enforces the certificate's
  `refs/heads/main` source ref and exact receipt source SHA. Only the push-only successor job receives
  OIDC/attestation permissions, never the pull-request image job.

Remaining gaps:
- ensure all externally exposed routers apply auth consistently
- ensure routes that require rate limits actually carry explicit limiter wiring
- choose long-term rate-limit storage posture for production (for example Redis-backed vs local-only)
<!-- SECTION:SECURITY:END -->
