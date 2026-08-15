---
name: Establish Verification Execution Authority
description: Make the existing API-backed verifier eligible for one installed-main, host-fenced pilot.
task_id: AVC-01
github_issue: 3603
source_anchor: docs/AUTONOMOUS_PR_CLOSURE/README.md :: Case model and safe action selection
parent_capability: Autonomous PR verification and closure
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish verification execution authority

## Purpose

The existing verifier must have one API-backed durable execution authority before it can safely
claim published PR verification or any later closure request. This task reuses #3603 rather than
introducing a second consumer, queue, or credential path.

## What This Task Does

Complete #3603's migration/pilot boundary: API-only durable task, claim, attempt, receipt, and
recovery state; fenced outbox-backed external effects; host-local scoped credentials; and an
installed-main Demerzel review-to-merge-or-no-merge receipt. The verifier continues to apply
`verification-and-closure` as its policy contract.

## Concretely

For an authenticated current-head request, the host creates or resumes the one `RepoRef`-bound
verification case, commits its fenced attempt before external work, revalidates current live truth,
and either returns a verified current-head result to the separately fenced executor or records a
safe technical/authority outcome. A host/API outage has no SQLite or API-key fallback.

## Why This Matters

Without this authority, an artifact-only CI request can be observed but cannot safely reduce the
operator's closure coordination. A local or duplicate verifier would create split claims,
unreconciled effects, and unverifiable merge authority.

## Acceptance Criteria

- [ ] The existing verification consumer uses BuilderOps API state for durable claims, attempts,
  idempotency, receipts, and recovery rather than dispatcher SQLite.
  - Verify: `tests/dispatcher/test_verification_consumer.py::test_consumer_uses_builderops_api_for_durable_state`
- [ ] A restart and an unknown external effect reconcile the durable attempt before a retry and do
  not duplicate the model or GitHub effect.
  - Verify: `tests/dispatcher/test_verification_recovery.py::test_restart_resumes_from_api_receipts_without_duplicate_attempt`
- [ ] The protected-base/manifest and scoped host-credential fences reject stale or mismatched merge
  authority before any merge.
  - Verify: `tests/dispatcher/test_verification_merge.py::test_merge_revalidates_protected_manifest_and_repo_credential_binding`
- [ ] One installed-main Demerzel cycle records an exact Issue/PR/SHA-bound terminal readback with
  no raw credentials.
  - Verify: runtime receipt: `bcp05_demerzel_cycle.v1`

## How to Verify (Pre-Merge)

- Run the named dispatcher consumer, recovery, and merge tests from #3603.
- Run the retained verification-dispatch/agent-loop regression set and exact-head CI.
- Perform the #3603 installed-main cycle only through its governed host credential and control-plane
  contract; retain the secret-free receipt on #3603.

## Out of Scope

- Post-merge closure dispatch/reconciliation, owned by AVC-02 / #3604.
- A second verifier, direct SQLite/PostgreSQL consumer, direct GitHub credential transport, or
  Product/Runtime changes.

## Related Docs

- [Capability README](README.md)
- `docs/BUILDEROPS_CONTROL_PLANE/DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md`
- `.codex/skills/verification-and-closure/SKILL.md`

## Related GitHub Issues

- Existing implementation contract: [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603)
- Existing validation hub: [#3224](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3224)
