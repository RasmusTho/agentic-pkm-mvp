State: Accepted (owner decision, 2026-07-04; RESEARCH-08 decision D3). Records
the decision to adopt INV-EF1, the two-scope public/private operator-invariance rule, together with
a per-item register and a `public_seam_lint.py` enforcement hook. Enactment (the lint script itself,
the register, PR-workflow wiring, and the owner-doc rows in `docs/PRIVACY.md` and
`docs/SECURITY_TRUST_BOUNDARIES.md`) is deferred to follow-up issues; this ADR performs no code
change and no enforcement change.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* of whether, and in what shape, a public/private
confidentiality rule governs the public Yggdrasil tree. The invariant's design content — the
two-scope split, the register discipline, the lint hook's two modes — is owned by
`docs/architecture/ecosystem-federation.md` § Public/private invariant; this ADR ratifies its
adoption, it does not restate the design. `docs/testing/invariant-tests.md` remains the owning
surface for invariant-test semantics; INV-EF1 extends it, this ADR does not fork it.
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede via a new ADR only if reversed, or if a future register
redesign changes the enforcement shape).
Source of truth: This ADR plus `docs/architecture/ecosystem-federation.md` § Public/private
invariant and § Owner decisions (D3), and `docs/testing/invariant-tests.md`.

# ADR-0046: Adopt INV-EF1, the two-scope public/private operator-invariance seam, with register + lint

**Date:** 2026-07-04
**Status:** Accepted (owner decision, 2026-07-04)

---

## Context

`docs/architecture/ecosystem-federation.md` (RESEARCH-08, #2852) found that no rule today governs
what may live in the public Yggdrasil tree. Adversarial review (skeptic S4, refuted-and-redesigned)
established the empirical ground truth:

- **Zero secrets** anywhere in the public tree — no API-key shapes, no IPs, no personal emails
  (verified sweep).
- **~307 personal-identifier hits across 11 spelling variants** — vault proper names
  (Niflheim/Bifröst/Midgård and casing/diacritic forms), the personal host "Demerzel," "Mac mini,"
  and `/Users/rasmus*` paths (e.g. `scripts/builderops_cli.sh:67`,
  `app/release_channels/prod_ref_fitness.py:217`).
- Some of those tokens are **load-bearing by function**: the prod vault guard is a fail-loud safety
  gate keyed to the vault label (`scripts/lib/companion_ui_startup.sh:159-166`,
  `scripts/prod/prod_ui_doctor.sh:20-22`); tests pin personal strings
  (`tests/capture/test_capture_writer_layout.py:51`,
  `tests/builderops/test_builderops_cli_automation.py:333`); the dispatcher doc names the shared
  coordination host so agent machines can find it across devices
  (`docs/AGENT_ISSUE_DISPATCHER.md:244-310`).
- **No rule exists today.** No doc states the repository is public; the environment/exposure
  trust-boundary row (`docs/SECURITY_TRUST_BOUNDARIES.md:37`) governs network reachability only,
  not source-repo content exposure; `docs/PRIVACY.md` scopes to runtime data flows and predates
  this seam; no enforcement mechanism scans for any of this — no gitleaks/detect-secrets anywhere,
  `scripts/docs_guard.py:8` diffs file *paths* not content, and `architecture-ci.yaml:4-5` is
  `workflow_dispatch`-only and cannot gate a PR as-is.

A blanket "no personal names in the public tree" law is therefore either aspirational (never
enforced) or destructive (breaking fail-loud guards, pinning tests, and cross-device builder
reproducibility). The issue's own constraint rules out an unenforced law, so the rule must be
scoped by lifecycle role and backed by a real check.

Per the artifact's SBS reconciliation (row 10), INV-EF1 is classified **Extend** — a new
fitness/invariant proposal that extends `docs/testing/invariant-tests.md` semantics. It is not a
boundary reshape (contrast ADR-0044/ADR-0045, which route reshape-class SoI/seam-governance
decisions through CES / `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`). Adoption here routes
through the normal filed-issue lane: implementation and owner-doc follow-ups, not a CES boundary
route.

## Decision

### 1. Adopt INV-EF1 (two-scope operator-invariance)

> **(a) Product scope — strict.** Artifacts of the SoI product surface (`app/`,
> `yggdrasil_runtime/`, `schemas/`, product contracts and architecture docs) must be
> **operator-invariant**: substituting another operator's personal environment leaves them
> byte-identical. No tokens from the personal-binding categories — (i) secrets and credentials,
> (ii) personal identity (usernames, personal paths, emails), (iii) personal infrastructure
> identity (machine names, mesh hostnames, IPs), (iv) personal data-space identity (vault proper
> names, personal iCloud paths), (v) personal-environment inventories (device registries,
> home/network topology). Personal bindings resolve at deploy time from the private side
> (env/config); public code speaks in roles (`dev`/`test`/`prod` channel, `VAULT_ROOT`).
> **(b) Builder/ops scope — secret-free + registered.** Enabling-system surfaces (builder docs,
> runbooks, `ops/host-setup`, dispatcher docs, their pinning tests) may carry categories (ii)–(v)
> **only** with a per-item row in an owned register naming the artifact, the token category, why it
> is load-bearing, and its migration disposition (stay / migrate-to-private-sibling /
> parameterize). Category (i) — secrets — is absolute in both scopes. A new personal token without
> a register row is a violation in either scope.

The register follows the `docs/architecture/SBS_TRANSITION_DEBT.md` per-item discipline (owned
rows, dispositions, issue links) rather than a blanket ratchet baseline — with the honest caveat,
named in the artifact, that even that discipline shows rot risk (several debt rows have sat open
across cycles). That is why the check below is mechanical, not manual.

### 2. Adopt the `public_seam_lint.py` enforcement hook

A new script, `scripts/public_seam_lint.py`, because `scripts/docs_guard.py:8`'s path-only diff
model cannot see content:

- **GATE mode (PR diff):** (1) secret-shape scan — hard-fails on any hit; the tree is clean today,
  so this is enforceable and green from day one. (2) personal-identifier scan of changed files
  against a small maintained pattern file (regex with diacritic folding — the repo's own native
  idiom, cf. `midg(å|a)rd` in `scripts/prod/prod_ui_doctor.sh:21`; hashed lexicons are rejected as
  they fail on normalization variance) — a hit in a file without a covering register row fails; a
  hit covered by a row passes.
- **DOCTOR mode (full tree, manual/scheduled):** reconciles the register — rows without hits
  (stale), hits without rows (drift), migration-disposition progress.
- **Wiring:** GATE mode joins an existing `pull_request`-triggered workflow (e.g. the ci-smoke
  workflow) and optionally `.pre-commit-config.yaml` — not `architecture-ci.yaml`, which is
  `workflow_dispatch`-only and cannot gate PRs as-is. Consistent with the repo's settled merge-gate
  posture, the gate binds through the agent delivery chain, not through branch protection
  (`docs/architecture/SBS_OPERATING_MODEL.md:383` — an unprotected `main` does not waive the gate;
  that convention is cited here, not created by this decision).
- **Invariant registry:** INV-EF1 extends `docs/testing/invariant-tests.md` semantics —
  GATE (secret scan; new-token-without-row) + DOCTOR (register reconciliation). No competing
  registry is created.

### 3. This is an Extend, not a Reshape

Per SBS reconciliation row 10, INV-EF1 is a new invariant/fitness-function proposal layered onto
existing `docs/testing/invariant-tests.md` semantics. It does not move a system boundary and is not
routed through CES / `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` the way ADR-0044 (D1, SoI
target-state ratification) and ADR-0045 (D2, ecosystem/SFC interaction-tier rule) are. Enactment
follows the ordinary filed-issue lane.

### 4. Enactment is separate follow-up work (does not happen in this ADR)

This ADR records the decision only. It enacts nothing — no script is written, no register row is
created, no workflow file changes, no owner doc changes. Three follow-up threads, each its own
issue(s):

1. **`public_seam_lint.py` + register + PR-workflow wiring** — implementation lane, docs-adjacent;
   filed on D3 acceptance.
2. **Vault-guard/label parameterization and `/Users/rasmus*` burn-down slices** — implementation
   lane, **not** docs-lane: these touch runtime guards (e.g.
   `scripts/lib/companion_ui_startup.sh:159-166`, `scripts/prod/prod_ui_doctor.sh:20-22`) and must
   go through the normal implementation-issue contract, not this ADR's PR. This burn-down converges
   with the ecosystem's first private-sibling constituent (§ Ecosystem model in the artifact) but is
   sequenced as its own slices.
3. **Owner-doc rows in `docs/PRIVACY.md` and `docs/SECURITY_TRUST_BOUNDARIES.md`** — their own
   filed docs issues, each its own PR. `docs/SECURITY_TRUST_BOUNDARIES.md:37`'s environment/exposure
   row does not yet cover source-repo content exposure; `docs/PRIVACY.md` predates this seam and
   currently scopes to runtime data flows only. Neither is edited by this ADR or folded into its PR.

## Constraints honored

- Decision record only — no code, script, register, workflow, or owner-doc change lands in this
  ADR's PR.
- Extend, not Reshape: no CES / `SBS_OPERATIONALIZATION_PLAN.md` route is invoked; contrast
  ADR-0044 (D1) and ADR-0045 (D2), which are reshape-class and do invoke it.
- Single-user stance preserved: the register and the seam split are about *where* operator-bound
  material may live, not about adding users or changing the one-human apex-authority model.
- Rejects the strict-everywhere alternative (artifact Option 3) on evidence: it would break
  fail-loud vault guards, pinning tests, and cross-device builder reproducibility
  (`docs/AGENT_ISSUE_DISPATCHER.md:244-310`).
- Rejects secrets-only (artifact Option 2) as insufficient: it leaves categories (ii)–(v) drift
  ungoverned, failing the issue's no-aspirational-law constraint.
- Register rot risk is named, not hidden: the artifact draws the parallel to
  `docs/architecture/SBS_TRANSITION_DEBT.md`'s own rot history and answers it with a mechanical
  DOCTOR-mode check rather than a manual-only discipline.

## Consequences

- A decidable, immediately enforceable rule exists in place of silence: secrets-GATE is green from
  day one; personal-identifier drift now requires a conscious, owned register row instead of
  passing unnoticed.
- A real, bounded work queue is created (lint script, register seed, guard parameterization, owner
  doc rows) — none of it performed here.
- The register becomes a standing maintenance cost with a named rot risk; DOCTOR mode is the
  mitigation, not a guarantee.
- Future personal-identifier introductions in enabling-system surfaces must either match an
  existing register row or add a new one — this is a process change for contributors and agents
  touching those surfaces, effective once the lint hook is wired (follow-up 1).
- D4 (MCP topology stance) and D1/D2 (SoI target-state, interaction-tier rule) stand independently;
  this decision does not presuppose or block any of them.
- The operator's incoming **Heimdall** sensor system, a constituent of the acknowledged SoS
  (per ADR-0044), makes the private-side binding split immediately load-bearing rather than
  hypothetical: its sensor/device/endpoint bindings are exactly INV-EF1 category (iii)/(v)
  private-side material.

## When to revisit

Supersede with a new ADR if the two-scope split or the register discipline is reversed, or if a
future redesign changes the enforcement mechanism (e.g. replaces `public_seam_lint.py` or folds it
into a different check). Also revisit if the first private-sibling constituent lands and the
burn-down migrations it enables change the register's steady-state size materially.

## References

- `docs/architecture/ecosystem-federation.md` § Public/private invariant, § Owner decisions (D3),
  § SBS reconciliation (row 10).
- `docs/testing/invariant-tests.md` — the invariant-test registry INV-EF1 extends.
- `docs/SECURITY_TRUST_BOUNDARIES.md:37` — the environment/exposure row that does not yet cover
  source-repo content exposure.
- `docs/PRIVACY.md` — predates this seam; owner-doc row is follow-up 3.
- `scripts/docs_guard.py:8` — existing path-only diff check; the gap `public_seam_lint.py` fills.
- `architecture-ci.yaml:4-5` — `workflow_dispatch`-only; cannot gate PRs, hence wiring into an
  existing `pull_request`-triggered workflow instead.
- `docs/architecture/SBS_TRANSITION_DEBT.md` — the per-item register discipline INV-EF1's register
  follows, including its named rot risk.
- `docs/architecture/SBS_OPERATING_MODEL.md:383` — merge-gate binds through the agent delivery
  chain, not branch protection.
- ADR-0044 (D1, SoI target-state ratification) and ADR-0045 (D2, ecosystem/SFC interaction-tier
  rule) — sibling RESEARCH-08 decision records, both reshape-class by contrast with this Extend.
