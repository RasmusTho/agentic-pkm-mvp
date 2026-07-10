---
name: External BuilderOps Vault Configuration
description: Configure a shared artifact vault with advisory claims while retaining local SQLite and authoritative leases.
task_id: BMI-01
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Scope
parent_capability: BuilderOps Model Inquiry
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# External BuilderOps Vault Configuration

## Purpose

Make the Yggdrasil-owned iCloud BuilderOps vault an explicit artifact root without turning iCloud
into a database or lock service.

## What This Task Does

Add a validated `BUILDEROPS_VAULT_ROOT` configuration path for shared Markdown artifacts, queue
files, receipts, transient worker state, and TTL-based advisory claim signals. Preserve the existing
local `BUILDEROPS_DB_PATH` behavior and local authoritative dispatcher leases. Bootstrap must
initialize the external artifact vault without creating SQLite files or provider credentials.

## Concretely

```bash
scripts/builderops_cli.sh builderops vault init "$BUILDEROPS_VAULT_ROOT" --json
scripts/builderops_cli.sh builderops vault paths --json
```

The paths command reports the shared artifact root, local SQLite path, and shared advisory claims
root. Validation fails if the configured shared vault contains SQLite or if the requested root does
not match `BUILDEROPS_VAULT_ROOT`.

## SQLite Confinement Invariant

Every BuilderOps SQLite open path enforces the same rule: when `BUILDEROPS_VAULT_ROOT` is bound,
both the lexical and resolved database paths must be outside that root. A symlink leaf lexically
inside the vault cannot escape the check by resolving to an outside target. The invariant applies at the shared store
boundary, not only during CLI configuration, so explicit API/MCP paths, completeness inspection,
and direct store construction cannot bypass it. Completeness inspection uses SQLite read-only mode;
it never creates a database when the inspected file is missing or disappears before open.

## Ticket And Advisory Claim Schemas

Queue tickets are Markdown files with YAML mapping frontmatter. `id` is a required, non-empty,
filename-safe string and `status` is a required recognized dispatcher status or display-column
value. Dispatcher Signboard cards may also carry `column`; when present it must match the normalized
status. Duplicate keys, incomplete mappings, unknown statuses, and folder/status disagreement fail
closed. This normalization lets the dispatcher producer and imported title-case vault cards share
one semantic queue contract.

Advisory claims are JSON mappings with non-empty string `ticket_id`, `agent`, `claimed_at`, and
`expires_at`. IDs are filename-safe, timestamps are timezone-aware, and `claimed_at < expires_at`.
Claim filenames are non-authoritative; the validated payload identifies the signal. Clock skew and
maximum TTL are not rejected in BMI-01 because the files provide visibility, not exclusion.

## Failure Model

The shared iCloud tree and imported queue/claim files are untrusted inputs. Init, validation,
claim, release, and SQLite scanning reject a symlinked vault root and pre-existing symlinked `agent-delivery`, status,
`.builderops`, and `claims` directories and reject symlinked ticket, claim, or database-candidate
leaves before reading, writing, unlinking, or recursing through them. These checks prevent a static
vault entry from aliasing an outside path. They do not claim race-free protection against a
malicious same-host process replacing filesystem entries between system calls; local dispatcher
leases and local SQLite remain the authoritative same-host coordination layer.

## Why This Matters

iCloud synchronizes files but does not provide transactional SQLite or distributed lock semantics.
Treating advisory files as authoritative leases creates false safety across developer devices.

## Acceptance Criteria

- [ ] All BuilderOps store entrypoints enforce the SQLite confinement invariant. Verify:
  `tests/builderops/test_builderops_paths.py::test_all_builderops_store_entrypoints_reject_sqlite_inside_shared_vault`.
- [ ] Completeness inspection cannot create a database across a missing-path race. Verify:
  `tests/builderops/test_builderops_paths.py::test_completeness_report_is_read_only_across_missing_path_race`.
- [ ] Bootstrap and validation reject hostile directory and leaf symlinks without outside writes.
  Verify: `tests/builderops/test_builderops_paths.py::test_shared_vault_bootstrap_rejects_symlinked_ancestors_without_outside_writes`
  and `tests/builderops/test_builderops_claims.py::test_queue_rejects_symlinked_ticket_and_claim_leaves_without_external_access`.
- [ ] Dispatcher Signboard tickets round-trip through validation and claim. Verify:
  `tests/builderops/test_builderops_claims.py::test_dispatcher_signboard_ticket_round_trips_vault_validation_and_claim`.
- [ ] Ticket and claim schemas reject incomplete, ambiguous, or temporally invalid inputs. Verify:
  `tests/builderops/test_builderops_claims.py::test_queue_rejects_incomplete_or_ambiguous_ticket_frontmatter`
  and `tests/builderops/test_builderops_claims.py::test_queue_rejects_invalid_claim_time_windows`.
- [ ] Concurrent agents may publish advisory claims without implying an exclusive distributed
  lock, and stale signals remain visible. Verify: `tests/builderops/test_builderops_claims.py`.
- [ ] The BuilderOps store contract documents the shared-artifact/local-state separation.
  Verify: doc writeback at `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Store Location`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_builderops_paths.py tests/builderops/test_builderops_claims.py tests/builderops/test_completeness_report.py tests/dispatcher/test_cli.py tests/tools/test_mcp_tool_provider.py`
- `scripts/builderops_cli.sh builderops vault paths --json`
- Review the documented location contract.

## Out of Scope

- cross-device distributed or authoritative leases;
- race-free protection from a malicious concurrent same-host path-swap attacker;
- maximum advisory TTL or future-clock-skew rejection;
- moving existing local SQLite records into iCloud;
- model orchestration or desktop skills.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_STORE.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3289](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3289)
