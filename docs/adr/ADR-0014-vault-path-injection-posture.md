State: Accepted (owner-delegated decision 2026-06-19; post-#2223 revisit recorded 2026-06-20). Establishes the standing security posture for CodeQL `py/path-injection` alerts that originate from the operator-configured vault path flowing into filesystem path expressions in `app/vault/manager.py`. The posture is **accept-and-dismiss as "won't fix"** (not harden the path), because (a) the vault path is operator-chosen-anywhere by design so no containment root exists, and (b) the genuine residual in an exposed/no-auth deployment is an authentication/exposure concern — now reduced for state-changing Companion vault routes by #2223 / PR #2289 and governed by `docs/SECURITY.md` — not a path-containment bug. Alerts are dismissed uniformly in the code-scanning API.
Doc role: Decision record (ADR)
Authority: Authoritative for the triage disposition of `py/path-injection` alerts rooted in the operator-chosen vault path. The governing reference for future dismissals of the same family.
Owner: Architecture / Security posture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place). The #2223 revisit has been recorded in this ADR; revisit again on a multi-user / hosted pivot or a new taint source — see "When to revisit".
Source of truth: This ADR (with the code-scanning alert state as the machine projection).

# ADR-0014: Path-injection posture for the operator-chosen vault path

**Date:** 2026-06-19
**Status:** Accepted (owner-delegated decision)

---

## Context

CodeQL's default Python query suite raises `py/path-injection` (high severity, "uncontrolled data used in path expression") on `app/vault/manager.py`. As of 2026-06-19 there were **4 open** alerts in this family (#92, #93, #97, #98) on lines that all trace back to one root cause: the operator-configured vault path flows into filesystem path expressions and into the app-local known-vault registry.

- `VaultManager.validate_vault` — `vault_path.expanduser()` → `.exists()` / `.is_dir()` / reads `settings/*.md`.
- `VaultManager.initialize_vault` — `vault_path.expanduser()` → `mkdir(parents=True)` and writes the initial `settings/*.md` files.
- `VaultManager._remember_context` — `vault_path.expanduser()` → persisted as the `path:` key and `path` field of a `KnownVaultRef` in the app-local registry.

The taint source CodeQL follows is real: `POST /api/companion/vault/select` (`app/api/routes/companion.py:610`, `VaultSelectRequest.path`) and the vault-initialize route both accept the path from a request body. So "user-provided value" is accurate, **and** the endpoint is reachable: the FastAPI runtime binds `0.0.0.0:8000` (`scripts/start_api.sh:49`, `docs/SECURITY.md`). Before #2223 / PR #2289, API-key auth was disabled by default (`app/auth.py::require_api_key` returned `""` when `settings.api_key is None`; `app/settings/__init__.py:35`), so on a LAN/Tailscale or host-network deployment without an API key, a reachable non-operator client could supply the path. Current state is narrower: state-changing Companion vault selection and initialization routes preserve unauthenticated loopback-local operation, but reject non-loopback requests unless `API_KEY` is configured and the request supplies the matching `X-API-Key` header (`docs/SECURITY.md :: Auth And Rate Limiting`). (The Companion UI *browser* gateway binds `127.0.0.1` by default — but that is the UI surface, not the API that serves `/vault/select`. An earlier draft of this ADR conflated the two; this version corrects it.)

This same query has fired on this same file before. **Five prior alerts in the identical family — #42, #73, #74, #75, #76 — were already dismissed.** The 4 current alerts are the same root cause re-surfaced after the #2185 / PR #2220 changes shifted line numbers. The decision below makes the disposition explicit, uniform, and honestly scoped rather than letting the family re-accumulate as silent open high-severity alerts.

Two postures were weighed, plus the nuance surfaced in review (Codex P1 on PR #2222):

- **Option A — harden.** Normalize/resolve the path once at the boundary (`Path(...).expanduser().resolve()`) and, where a containment root exists, validate the path stays within it.
- **Option B — accept.** Dismiss the alerts uniformly with a documented reason, so the security tab reflects an intentional decision under the actual threat model.
- **Review nuance.** Because the API is exposed on `0.0.0.0` with auth off by default, a blanket "false positive" would triage away a real path-selection/write surface. The honest resolution is to scope the dismissal and track the real control.

## Decision

**Option B — accept and dismiss, uniformly, as `won't fix`.** All `py/path-injection` alerts whose data flow is the operator-chosen vault path entering `app/vault/manager.py` are dismissed in the code-scanning API with reason **"won't fix"** and a comment pointing to this ADR. No path-hardening code change is made; the genuine residual is addressed on a separate axis (#2223), not by path containment.

The reason is **"won't fix"**, not "false positive": the data flow is real and reachable cross-principal in a non-loopback / no-auth deployment, so calling it a non-issue would be dishonest. We are *accepting the risk* under the documented single-user, trusted-LAN posture, with the real mitigation living in the authentication/exposure track — not denying the flow exists.

Three grounds support accepting rather than path-hardening; each is independently sufficient for *that* sub-decision:

1. **There is no containment root to validate against — by design.** The product's vault model is "the operator points the app at *any* directory of their choosing" (the open-vault picker, #2005/#2006; `docs/ENVIRONMENTS.md` vault terminology; three operator vaults whose names and locations are mutable and must never be hardcoded). The vault path *is* the trust root; there is nothing legitimate above it to contain it within. Option A's containment half therefore has nothing to check against — adding an allowlist root would contradict the open-vault design and break the deliberate "start with no vault, pick any location" boot path.

2. **The genuine residual is authentication/exposure, not path containment.** The real risk Codex identified — an unauthenticated LAN/Tailscale client reaching a state-changing route — is an *access-control* gap, already documented as the trusted-LAN posture in `docs/SECURITY.md` ("not an internet-ready security boundary"; "Do not expose ... without an explicit access-control boundary"). #2223 / PR #2289 has now shipped the bounded control for the state-changing Companion vault selection and initialization routes: loopback-local use stays unauthenticated, while non-loopback requests require configured API-key auth. Path containment would not fix the access-control concern (there is no jail to enforce — the endpoint *is* meant to accept any path); auth/binding does. Dismissing the path-injection alert therefore remains correct *as a path-injection finding*. WriteGuard remains the intentional gate on vault *writes* and is not weakened here.

3. **Option A would not even clear the alerts, and would introduce real risk.** `.resolve()` is not a sanitizer CodeQL recognizes for `py/path-injection`; only an allowlist/containment barrier clears the query, which ground (1) rules out. Worse, switching to `.resolve()` would change the stored `active_vault_path` strings and the `path:{expanduser()}` registry ref keys (resolving symlinks and forcing absolute form), which can break existing known-vault references — a behavior regression for zero security gain on the path-containment axis.

## When to revisit

This posture is scoped to the **single-user, documented trusted-LAN** threat model. The #2223 revisit trigger fired when PR #2289 landed: the accepted path-injection disposition still reads correctly because the product still intentionally accepts an operator-chosen-anywhere vault path, while the prior non-loopback/no-auth residual for state-changing Companion vault routes has shrunk under `docs/SECURITY.md :: Auth And Rate Limiting`.

Reopen and re-decide (a new ADR) if any of these change:

- The product moves to **multi-user or hosted** operation, where one user's `/vault/select` could reach another tenant's filesystem. Then the vault path crosses a real privilege boundary and a per-tenant containment root becomes both meaningful and required — Option A (or a tenant-scoped jail) becomes the correct answer.
- A new code path lets a *non-operator, non-request* source (e.g. an ingested document, an external webhook) influence the vault path — that is outside both this ADR and #2223 and must be triaged fresh.

## Consequences

- The 4 open alerts (#92, #93, #97, #98) are dismissed as "won't fix" with a comment pointing here; the open `py/path-injection` count for this file returns to 0. The security tab reflects an intentional, documented, honestly-scoped decision.
- The previous non-loopback/no-auth residual for state-changing Companion vault selection and initialization routes has been reduced by #2223 / PR #2289: non-loopback requests now require configured API-key auth, while loopback-local operation remains unauthenticated by design.
- Future re-surfacings of the *same* family (operator-chosen vault path → fs op in `app/vault/manager.py`) are dismissed under this ADR without re-litigation. A *new* taint source (ground-3 of "When to revisit") is **not** covered and must be triaged fresh.
- No path-containment runtime behavior changes in this decision; the registry ref keys and stored vault-path strings are untouched. #2223's shipped auth/binding control is the behavioral change for the exposure axis.
- This ADR does not weaken WriteGuard or any vault-write authority gate; it concerns only the *path-selection* data flow.

## Validation

```bash
# End state: zero open py/path-injection alerts for the vault path family.
gh api 'repos/RasmusTho/agentic-pkm-mvp/code-scanning/alerts?state=open&per_page=100' \
  --jq '[.[]|select(.rule.id=="py/path-injection")]|length'   # -> 0

# The dismissals carry the documented reason and this ADR reference.
gh api 'repos/RasmusTho/agentic-pkm-mvp/code-scanning/alerts?state=dismissed&per_page=100' \
  --jq '.[]|select(.rule.id=="py/path-injection")|{number,reason:.dismissed_reason,comment:.dismissed_comment}'
```

## References

- #2148 — terminal review-residual delivery (origin of this triage)
- #2185 / PR #2220 — `_remember_context` change that re-attributed the alert line numbers
- **#2223 / PR #2289 — gate state-changing companion routes behind auth/loopback when bound non-loopback** (the shipped exposure-axis control this ADR points to)
- PR #2222 — this ADR; Codex P1 review surfaced the API-exposure correction
- Prior dismissals (same family, same file): alerts #42, #73, #74, #75, #76
- `app/vault/manager.py` (`validate_vault`, `initialize_vault`, `_remember_context`)
- `app/api/routes/companion.py` (`POST /api/companion/vault/select`, `VaultSelectRequest`); `app/auth.py`; `scripts/start_api.sh`
- `docs/SECURITY.md` (trusted-LAN posture, API binding, auth-disabled-by-default, remote-access next steps)
- `docs/ENVIRONMENTS.md` (vault terminology — operator-chosen vaults)
- #2005 / #2006 — no-vault idle boot and open-vault picker (why no containment root exists)
