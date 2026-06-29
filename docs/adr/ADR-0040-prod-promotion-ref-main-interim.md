State: Accepted (operator decision, 2026-06-29). Records the interim prod promotion ref and the reproducibility invariant that backs it. The gated `stable` model in docs/RELEASE_CHANNELS/README.md §"Promotion contract" is unchanged and remains the target; this ADR does not relax it.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* that prod tracks `main` as the interim promotion ref, that `origin/stable` is dormant and must not be treated as the prod source-of-truth until restored, and that the prod runtime must equal the promotion ref with a clean working tree (reproducible from git alone). Channel identity, isolation invariants, and the target four-phase gated promotion contract remain owned by `docs/RELEASE_CHANNELS/README.md`; this ADR reconciles that doc with prod reality and points at it, it does not redefine it.
Owner: Release channels / deployment governance
Temporal class: Durable decision (supersede via a new ADR when `stable` is restored as a gated ref; do not edit in place)
Source of truth: This ADR plus `docs/RELEASE_CHANNELS/README.md` §"Promotion model".

# ADR-0040: Prod promotion ref — `main` interim baseline; gated `stable` deferred

**Date:** 2026-06-29
**Status:** Accepted

---

## Context

Part of Issue #2527. Read-only inspection of the prod host (2026-06-25) found that the production
deployment did **not** track the protected `stable` branch the promotion machinery assumes:

- Prod ran from a host checkout bind-mounted into the prod container, on branch **`main`**, not a
  `stable` checkout.
- `origin/stable` (`e2892b18`, 2026-06-14) was **not an ancestor** of prod's HEAD — prod was
  hundreds of commits ahead of `stable` and `stable` was not reachable from `main` (squash-merge
  history). As of 2026-06-29 `origin/stable` is still not an ancestor of `origin/main`.
- The prod working tree was **dirty**: tracked files modified and untracked directories present —
  uncommitted state that existed nowhere in git, so prod was not reproducible on another machine
  and was not reviewed.

This made two documented facts false against reality:

- `docs/RELEASE_CHANNELS/README.md` channel table listed prod's code ref as `stable (tag or branch)`;
- Invariant 4 (Code-ref-per-channel) said "the prod process runs from a checkout pinned to the
  `stable` ref."

The startup-ergonomics changes that the prod tree carried (`.env.prod.local` vault binding,
`/healthz`, the vault-mount guard, runbook updates) were already captured to `main` via #2523, so
this ADR is about the **promotion-ref decision and the reproducibility invariant**, not about
re-capturing that code.

## Decision

### 1. Prod's promotion ref is `main` (interim baseline)

Prod tracks **`main`** directly. The prod process runs from a checkout pinned to `main`. There is no
gated `stable` indirection in force today. This is the interim baseline chosen because establishing a
trustworthy prod runtime comes **before** promotion-governance hardening — these are sequential
concerns, not parallel ones (see `docs/RELEASE_CHANNELS/README.md` §"Current direction").

### 2. `origin/stable` is dormant; not the prod source-of-truth until restored

`origin/stable` does not reflect what prod runs and **must not** be treated as the prod
source-of-truth until it is restored as a gated ref. The promotion **skills**
(`prepare-promotion`, `execute-promotion`, `verify-promotion`, `promote-test-to-prod`) and the
four-phase gated **Promotion contract** in `docs/RELEASE_CHANNELS/README.md` describe the **target**
model and remain valid for that future. They do not describe the current `main`-tracking baseline,
and this ADR does not relax any of their invariants.

### 3. Reproducibility invariant: prod runtime equals the promotion ref, with a clean tree

Prod must be reconstructible from git alone. The prod runtime HEAD must equal the promotion ref and
the working tree must be **clean** — no uncommitted, machine-local state acting as durable truth.
This re-states, for the deployment surface, the repository's existing principle that durable truth
must not live in machine-local or ephemeral state.

Enforcement is a **read-only** guard: `app/release_channels/prod_ref_fitness.py`
(`check_prod_head_matches_promotion_ref_and_clean`) flags a prod checkout that is on a branch other
than the promotion ref, on a detached HEAD, dirty, or — when given an already-known comparison ref —
at a commit that diverges from it. The guard never fetches, checks out, resets, or mutates anything.
The operator runs it on the prod host to produce the Issue #2527 AC2 "prod tree clean" receipt:

```
python -m app.release_channels.prod_ref_fitness /Users/rasmus/workspace --promotion-ref main
```

### 4. Cleaning the prod working tree is an operator act

Returning the prod working tree to clean (committing or discarding the residual local changes on the
prod host) is an operator action on the live prod host, gated by operator authorization — it is not
performed by agent automation. This ADR and the guard make that act checkable; they do not perform
it.

## Constraints honored

- Doc/ADR + read-only-guard only. No change to prod runtime behavior, no mutation of the prod host,
  no change to the gated promotion contract or its invariants.
- `stable` is not redefined or deleted — it is named dormant, with restoration as future work.
- The guard is read-only and fail-closed; it reports and exits non-zero, it never edits operator
  state.

## Consequences

- `docs/RELEASE_CHANNELS/README.md` now states the true current promotion ref (`main`) in the
  channel table, Invariant 4, and a new §"Promotion model", with the gated `stable` model explicitly
  marked as the deferred target.
- A fitness check (`tests/ops/test_release_channel_startup_targets.py::test_prod_head_matches_promotion_ref_and_clean`)
  guards the reproducibility invariant and gives the operator a single command for the AC2 receipt.
- Promotion skills and the gated contract remain the target; no promotion workflow is enabled or
  disabled by this ADR.
- Issue #2527 retains one residual: the operator "prod tree clean" receipt (AC2), and the eventual
  switch from `main`-tracking to a restored gated `stable` ref.

## When to revisit

Reopen and supersede with a new ADR when:

- `stable` is restored as a gated promotion ref and prod is switched from `main`-tracking to
  `stable`-tracking (the target model in §"Promotion contract" becomes the in-force model); or
- the deployment moves off the single-user bind-mount checkout to an immutable image, changing what
  "the prod runtime ref" means; or
- the product moves to multi-user / hosted operation, changing the promotion-authority assumptions.

## References

- Issue #2527 — reconcile prod deployment with the promotion source-of-truth.
- #2523 — captured the prod startup-ergonomics changes (`.env.prod.local`, `/healthz`, vault-mount
  guard) to `main` (AC2 code capture).
- `docs/RELEASE_CHANNELS/README.md` §"Promotion model" (current baseline), §"Promotion contract"
  (target gated model), §"Current direction" (baseline-before-hardening sequencing), Invariant 4.
- `app/release_channels/prod_ref_fitness.py` — read-only prod-ref fitness guard (AC3).
- `tests/ops/test_release_channel_startup_targets.py::test_prod_head_matches_promotion_ref_and_clean`
  — the fitness check (AC3 Verify target).
