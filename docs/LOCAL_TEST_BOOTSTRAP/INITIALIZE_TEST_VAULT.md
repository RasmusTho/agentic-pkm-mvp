# BOOTSTRAP-02: Initialize Test Vault

**Anchor ID:** `BOOTSTRAP-02`
**Governing Issue:** #332
**Sequence:** Step 2 of the Local Test Bootstrap chain (follows BOOTSTRAP-01 reset).
**Status:** Shipped.

## Purpose

Create a clean `vault-test/` with the required directory structure and seeded UAT notes so that subsequent bootstrap steps (#333–#335) have a known-good vault to operate against.

## Entry Point

```
make test-vault-init
```

Delegates to `scripts/init_test_vault.sh`.

## What It Does

1. Creates `vault-test/System/Config/` and `vault-test/Test/`.
2. Copies `docs/settings/panel-action-wiring.yaml` into `vault-test/System/Config/panel-action-wiring.yaml`.
3. Runs `python -m app.cli uat-seed-vault-test --vault-root vault-test --overwrite` to seed UAT notes into `vault-test/Test/AgenticPKM-UAT/`.
4. Verifies the resulting directory structure and emits a machine-readable success/failure summary.
5. Exits 0 on success, non-zero on failure.

## Required Structure After Init

```
vault-test/
  System/
    Config/
      panel-action-wiring.yaml   ← copied from docs/settings/
  Test/
    AgenticPKM-UAT/              ← seeded by uat-seed-vault-test
      *.md                       ← UAT note fixtures from docs/examples/vault_test_seed/
```

## Idempotence

Running `make test-vault-init` twice produces an identical vault structure.
The `--overwrite` flag on `uat-seed-vault-test` restores seed notes to their original state on each run.

## Constraints

- Must work in a clean checkout (no undocumented hidden files required).
- Does not start the runtime; does not depend on Docker.
- Requires `docs/settings/panel-action-wiring.yaml` to be present in the repo.

## Upstream / Downstream

- **Upstream:** BOOTSTRAP-01 (`make reset-zero-force`, #331) — clears `vault-test/` before this step in a full reset flow.
- **Downstream:** BOOTSTRAP-03 (`make start-test-system`, #333) — starts the full system against the initialized vault.

## CI Verification

`tests/quality_wave/test_bootstrap_init.py` — verifies idempotent vault init in a clean temp directory using `uat-seed-vault-test` directly.
