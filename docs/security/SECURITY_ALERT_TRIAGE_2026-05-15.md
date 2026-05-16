# Security Alert Triage — 2026-05-15

State: Point-in-time triage snapshot of the CodeQL and Dependabot alert set captured on 2026-05-15. Not a living posture document; use `docs/SECURITY.md` and `docs/SECURITY-ROADMAP-v6.1.md` for current security state.

Triage date: 2026-05-15  
Repo: RasmusTho/agentic-pkm-mvp  
System posture: local-first, single-user. Companion UI/API may later be exposed beyond localhost/Tailscale.

---

## Code Scanning Alerts

| # | Rule | File:Line | State | Priority | Runtime/Dev | Companion blocker | Action |
|---|------|-----------|-------|----------|-------------|-------------------|--------|
| #24 | py/clear-text-logging-sensitive-data | app/cli/settings_explain.py:100 | open | P1 | Runtime CLI | No (operator tool) | Add `_redact_payload()` walk before `json.dumps` to guarantee no taint reaches print, even if new fields are added. DSN already masked via `mask_dsn`; fix breaks CodeQL taint chain and adds defense in depth. |
| #23 | py/weak-sensitive-data-hashing | app/promotion/queue.py:69 | open | P1 | Runtime | No | SHA-1 used for trace_id fallback (idempotency only, not a security boundary). Replace with SHA-256 to eliminate the alert and apply correct practice. |
| #22 | py/incomplete-url-substring-sanitization | tests/ops/test_start_system_outbox_contract.py:188 | open | P3 | Test only | No | **Defer/dismiss.** CodeQL flagged a URL substring check in test helper code. No production code is involved. Dismiss as test-only non-issue. |
| #21 | py/stack-trace-exposure | app/api/routes/health.py:14 | open | P0 | Runtime API | **Yes** | `run_health()` returns raw DSN string in `runtime.db.dsn`. Must be masked before HTTP response. |
| #20 | py/stack-trace-exposure | app/api/routes/debug.py:43 | open | P0 | Runtime API | **Yes** | Raw exception interpolated into HTTPException detail. Exposes filesystem paths. Replace with generic safe message; log detail internally. |

---

## Dependabot Alerts (open)

| # | Package | Severity | Scope | Current | Fixed ≥ | Priority | Action |
|---|---------|----------|-------|---------|---------|----------|--------|
| #27 | langsmith | High | Runtime | 0.7.31 | 0.8.0 | P1 | Bump to ≥0.8.0 |
| #26 | urllib3 | High | Runtime | 2.6.3 | 2.7.0 | P0 | Bump to ≥2.7.0 (decompression bomb + sensitive header forwarding) |
| #25 | urllib3 | High | Runtime | 2.6.3 | 2.7.0 | P0 | Same CVE family as #26; resolved by same bump |
| #24 | langchain-core | High | Runtime | 1.2.28 | 1.3.3 | P1 | Bump to ≥1.3.3 (unsafe deserialization) |
| #23 | Mako | High | Runtime | 1.3.11 | 1.3.12 | P1 | Bump to ≥1.3.12 (path traversal) |

---

## Priority definitions

- **P0** — directly exploitable via an already-exposed HTTP surface; fix in this PR.
- **P1** — high-severity, runtime dependency or code path that reaches the API surface when Companion UI is exposed; fix in this PR.
- **P2** — medium-severity, indirect risk; fix in follow-up.
- **P3** — test-only or zero runtime path; dismiss or defer.

---

## Alert #22 dismissal rationale

CodeQL #22 (`py/incomplete-url-substring-sanitization`) points to `tests/ops/test_start_system_outbox_contract.py:188`. This is a test helper, not production code. No shared utility is involved. The substring check pattern appears in test assertion logic that constructs expected URL strings for contract validation. There is no runtime call path from this location. Recommended action: dismiss as "used in tests" / false positive.

---

## Companion UI exposure impact

Alerts #20 and #21 are P0 because `/health` and `/api/debug/*` are HTTP routes. If Companion UI is exposed beyond localhost, both routes would be reachable by a network adversary. Fixing them before any Tailscale/public exposure is a hard prerequisite.

---

## Remaining follow-ups

- Dismiss CodeQL #22 via `gh api` after PR merges.
- Audit `app/cli/health.py` for other fields that might leak env-var values (e.g. `base_url` fields that could contain bearer tokens in query strings).
- Add rate-limiting or auth middleware to `/api/debug/*` before any non-localhost exposure — the debug panel endpoint exposes vault note content and file paths.
