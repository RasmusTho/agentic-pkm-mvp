---
name: Canonicalize Settings Location
description: One canonical vault settings root <vault>/settings/; legacy locations compat-read for one release with loud deprecation; CI gate blocks new locations
task_id: SETTINGS-03
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F2
parent_capability: Settings Spine
prerequisites: [SETTINGS-01]
depends_on: [WIRE_SETTINGS_INGESTION.md]
can_parallelize_with: [Receipt Every Settings Write]
---

# Canonicalize Settings Location

## Purpose

Close audit finding F2 (SET-2): four vault settings locations exist today — `<vault>/settings/`
(scoped md service), `<vault>/_system/settings/system-settings.yaml` (YAML stack),
`<vault>/@Settings/` (compiled-bundle sources), `<vault>/_system/Settings/health.md` (health) —
and three owner-adjacent docs each present a different one as canonical.

## What This Task Does

- Declares `<vault>/settings/` the single canonical root (visible, human-named — conforms to the
  documented scaffold in `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md:123-138` and the human-first
  naming stance; not hidden under `_system/`, not sigil-named).
- Relocates the compiled-bundle sources (`@Settings/*.md`, `@Settings/agents/*.md`), the
  system-settings YAML content (as markdown), and `health.md` under `<vault>/settings/`, updating
  their loaders (`app/settings/compiler.py:35,316-326`, `app/config/paths.py:193-216`,
  `app/settings/health_settings.py`).
- Legacy paths remain compat-read for one release: a key found only at a legacy path still
  resolves, with a loud deprecation warning naming the target path; a key present in both resolves
  from the canonical path and logs the shadowed legacy value (no merging — see capability
  Cross-Task Invariants).
- Adds the CI gate: no code may introduce a settings path outside the canonical root or the
  enumerated legacy compat list.
- Vault init scaffolds `settings/` only on explicit init, never on open (consumes the #2312 / R5
  ruling if made; otherwise this conservative default applies and is stated in the PR).

## Concretely

```
$ ls "$VAULT/settings/"        # vault.md paths.md workflow.md companion-ui.md local.md
                               # llm_routing.md embeddings.md watchers.md health.md agents/ ...
$ docker compose logs api | grep deprecated
  WARN settings: legacy location vault/@Settings/llm_routing.md still present; canonical is settings/llm_routing.md
$ pytest -q tests/architecture/test_settings_single_location.py
```

## Why This Matters

Four locations means every writer, reader, doc and human guesses differently; F1-class wire cuts
regrow at each location seam. One visible folder is also the dyslexia-friendly answer: the human
finds settings by looking, not by knowing a path convention.

## Acceptance Criteria

- [ ] All four settings stacks read their sources under `<vault>/settings/`; a fresh vault
      initialized today contains no `@Settings/`, `_system/settings/`, or `_system/Settings/`.
  - Verify: `tests/settings/test_canonical_location.py::test_all_stacks_read_canonical_root`
- [ ] Legacy-path compat: key only at legacy path → resolves + deprecation warning; key at both →
      canonical wins + shadowed value logged.
  - Verify: `tests/settings/test_canonical_location.py::test_legacy_compat_and_shadowing`
    (enforcement AC — exercises the production resolution path, not a path helper in isolation)
- [ ] CI gate blocks introduction of any new settings location.
  - Verify: `tests/architecture/test_settings_single_location.py::test_no_new_settings_paths`
- [ ] Migration of an existing vault is a governed write: performed only on explicit operator
      action (documented command), WriteGuard-gated, and receipted (or, if SETTINGS-04 has not yet
      merged, recorded in the PR receipt with SETTINGS-04's backfill scope extended — see
      capability Cross-Task Invariants).
  - Verify: `tests/settings/test_canonical_location.py::test_migration_is_governed_and_receipted`
- [ ] SET-2 registered in the invariant registry with enforcement `static_test` (gate).
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: one_vault_settings_location`
- [ ] The three contradicting docs (`docs/SETTINGS.md:26`, `docs/ENVIRONMENTS.md:30`,
      `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md:123-138`) name the same canonical root in this
      PR (full owner-doc rewrite stays with SETTINGS-08).
  - Verify: doc writeback at `docs/ENVIRONMENTS.md :: Vault terminology` naming `<vault>/settings/`

## How to Verify (Pre-Merge)

- `pytest -q tests/settings/test_canonical_location.py tests/architecture/test_settings_single_location.py`
- `pytest -q -m "not pg"` and `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration -k settings`
  (vault hot path)
- Manual dev-channel migration receipt attached to the PR.

## Out of Scope

- Rewriting `docs/SETTINGS.md` as owner doc (SETTINGS-08).
- Prompt files (SETTINGS-06 places them under the canonical root once it exists).
- `_heimdal/**` stays where it is — contracted Bifrost surface, not a settings location defect.

## Restart / Durability Posture

Markdown files are the durable truth; the migration is a one-time filesystem move with receipt.
Deprecation warnings are re-emitted every boot while legacy files exist — the nagging is the
feature.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F2`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Initial Vault Files`
- Issue #2312 (R5 scaffolding ruling — consume, do not duplicate)

## Related GitHub Issues

One implementation issue. TCD hint: opus / high — cross-cutting migration across four loaders on
the vault hot path; wrong-path bugs are silent-data-class; full suite + UAT + careful review.
