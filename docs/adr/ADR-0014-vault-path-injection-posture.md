State: Accepted (owner-delegated decision 2026-06-19). Establishes the standing security posture for CodeQL `py/path-injection` alerts that originate from the operator-configured vault path flowing into filesystem path expressions in `app/vault/manager.py`. The posture is **accept-and-dismiss** (not harden), because the vault path is operator-chosen-anywhere by design and there is no containment root to validate against; alerts are dismissed uniformly as "false positive" in the code-scanning API.
Doc role: Decision record (ADR)
Authority: Authoritative for the triage disposition of `py/path-injection` alerts rooted in the operator-chosen vault path. The governing reference for future dismissals of the same family.
Owner: Architecture / Security posture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place). Revisit on a multi-user / hosted pivot — see "When to revisit".
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

The taint source CodeQL follows is real: `POST /vault/select` (`app/api/routes/companion.py`, `VaultSelectRequest.path`) and `initialize_vault` both accept the path from a request body. So "user-provided value" is *technically* accurate.

This same query has fired on this same file before. **Five prior alerts in the identical family — #42, #73, #74, #75, #76 — were already dismissed as "false positive."** The 4 current alerts are the same root cause re-surfaced after the #2185 / PR #2220 changes shifted line numbers. The decision below makes the disposition explicit and uniform rather than letting the same family re-accumulate as silent open high-severity alerts.

This is a deliberate posture decision, not ad-hoc dismissal. Two postures were weighed:

- **Option A — harden.** Normalize/resolve the path once at the boundary (`Path(...).expanduser().resolve()`) and, where a containment root exists, validate the path stays within it.
- **Option B — accept.** Dismiss the alerts uniformly with a documented reason, so the security tab reflects an intentional decision under the actual threat model.

## Decision

**Option B — accept and dismiss, uniformly.** All `py/path-injection` alerts whose data flow is the operator-chosen vault path entering `app/vault/manager.py` are dismissed in the code-scanning API with reason **"false positive"** and a comment pointing to this ADR. No code change is made.

Three independent grounds support this, and each one alone is sufficient:

1. **There is no containment root to validate against — by design.** The product's vault model is "the operator points the app at *any* directory of their choosing" (the open-vault picker, #2005/#2006; `docs/ENVIRONMENTS.md` vault terminology; three operator vaults whose names and locations are mutable and must never be hardcoded). The vault path *is* the trust root; there is nothing legitimate above it to contain it within. Option A's containment half therefore has nothing to check against — adding an allowlist root would contradict the open-vault design and break the deliberate "start with no vault, pick any location" boot path.

2. **The only principal is the operator.** This is a single-user, local PKM (single-user is an intentional stance, not an oversight). The `POST /vault/select` source is the sole operator's own request; prod binds the gateway to localhost and the runtime posture is trusted-LAN. No privilege boundary is crossed: the operator already has full filesystem authority on their own machine via their shell. The "attacker controls a path to escape a sandbox" scenario the query models does not exist here — the path-chooser and the trust principal are the same person. WriteGuard remains the real, intentional gate on *vault writes*; it is not weakened by this decision.

3. **Option A would not even clear the alerts, and would introduce real risk.** `.resolve()` is not a sanitizer CodeQL recognizes for `py/path-injection`; only an allowlist/containment barrier clears the query, which ground (1) rules out. Worse, switching to `.resolve()` would change the stored `active_vault_path` strings and the `path:{expanduser()}` registry ref keys (resolving symlinks and forcing absolute form), which can break existing known-vault references — a behavior regression for zero security gain under this threat model.

Consistency with the five prior "false positive" dismissals (#42, #73–76) is the tie-breaker on the dismissal *reason*: using the same reason keeps all nine alerts uniform instead of leaving two rationales for one root cause.

## When to revisit

This posture is scoped to the **single-user, local/trusted-LAN** threat model. Reopen and re-decide (a new ADR) if any of these change:

- The product moves to **multi-user or hosted** operation, where one user's `/vault/select` could reach another tenant's filesystem. Then the vault path crosses a real privilege boundary and a per-tenant containment root becomes both meaningful and required — Option A (or a tenant-scoped jail) becomes the correct answer.
- The companion API stops binding localhost / trusted-LAN and becomes reachable by untrusted clients.
- A new code path lets a *non-operator* source (e.g. an ingested document, an external webhook) influence the vault path.

## Consequences

- The 4 open alerts (#92, #93, #97, #98) are dismissed as "false positive"; the open `py/path-injection` count for this file returns to 0. The security tab reflects an intentional, documented decision.
- Future re-surfacings of the *same* family (operator-chosen vault path → fs op in `app/vault/manager.py`) are dismissed under this ADR without re-litigation. A *new* taint source (ground-3 of "When to revisit") is **not** covered and must be triaged fresh.
- No runtime behavior changes; the registry ref keys and stored vault-path strings are untouched.
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
- Prior dismissals (same family, same file): alerts #42, #73, #74, #75, #76 ("false positive")
- `app/vault/manager.py` (`validate_vault`, `initialize_vault`, `_remember_context`)
- `app/api/routes/companion.py` (`POST /vault/select`, `VaultSelectRequest`)
- `docs/ENVIRONMENTS.md` (vault terminology — operator-chosen vaults, host/container mounts)
- #2005 / #2006 — no-vault idle boot and open-vault picker (why no containment root exists)
