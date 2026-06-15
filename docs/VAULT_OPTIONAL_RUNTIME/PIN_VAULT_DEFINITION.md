---
name: Pin the Vault Definition
description: Pin the overloaded "vault" term across docs (content vault vs vault-settings vs VAULT_ROOT binding vs test vault).
task_id: VAULT_OPTIONAL_RUNTIME-04
source_anchor: docs/VAULT_OPTIONAL_RUNTIME/README.md :: Out of scope
parent_capability: Vault Optional at Runtime
prerequisites: []
depends_on: []
can_parallelize_with: [RESOLVE_NO_VAULT_STATE.md, BOOT_RUNTIME_WITHOUT_VAULT.md, COMPANION_NO_VAULT_ROUTING.md]
---

# Pin the Vault Definition

## Purpose
"Vault" is overloaded, and the owner explicitly flagged that the scope of "no vault at
initiation" **depends on the definition of vault**. This task pins the term so future work
(and the runtime tasks above) share one vocabulary. Deferred by owner ("2 now, 3 later").

## What This Task Does
A docs/decision pass (no runtime code) that names and distinguishes the senses of "vault":
- the **content vault** — the notes folder a human opens (the Obsidian-style sense);
- the **vault-settings** — the `settings/` files inside a vault (#1991 foundation);
- the **`VAULT_ROOT` runtime binding** — the env/config that binds a content vault to a
  running process;
- the **test vault** — the deterministic vault the #1997 harness provisions.
It records which of these "no vault at initiation" applies to (owner: includes the
`VAULT_ROOT` runtime binding), and updates `docs/ENVIRONMENTS.md` (or the most local owner
doc) with the canonical definitions.

## Concretely
A short owner-doc section (e.g. `docs/ENVIRONMENTS.md :: Vault terminology`) listing the four
senses with one-line definitions and which invariants attach to each.

## Why This Matters
Without a pinned definition, "no vault required" is ambiguous and the runtime tasks risk
relaxing the wrong invariant (e.g. accidentally making the *test* vault optional, breaking
deterministic UAT).

## Acceptance Criteria
- [ ] The four senses of "vault" are defined in an owner doc, with the invariants that attach to each. Verify: `docs/ENVIRONMENTS.md :: Vault terminology` anchor exists and is referenced by `docs/VAULT_OPTIONAL_RUNTIME/README.md`.
- [ ] The doc states which sense "no vault at initiation" applies to (per owner: the `VAULT_ROOT` runtime binding). Verify: same doc anchor.

## How to Verify (Pre-Merge)
Docs-only; reviewed in PR. No tests.

## Out of Scope
- Any runtime behaviour change (that is tasks 1–3).

## Related Docs
- Parent: `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/ENVIRONMENTS.md`
- [[project_open_vault_on_missing_vault]] (memory: the decision and its "definition of vault" caveat)

## Related GitHub Issues
One bounded docs issue. Implements VAULT_OPTIONAL_RUNTIME/PIN_VAULT_DEFINITION. Deferred —
`agent:needs-human` (owner decision on the canonical definition); low priority relative to
tasks 1–3.
