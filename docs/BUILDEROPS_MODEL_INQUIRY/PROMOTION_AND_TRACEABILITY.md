---
name: Promotion And Traceability
description: Promote only issue-ready inquiry results and preserve Issue-to-document delivery lineage.
task_id: BMI-05
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Capability Acceptance Criteria
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-02, BMI-03, BMI-04]
depends_on: [PRE_TICKET_INQUIRY_RECORDS.md, MODEL_TURN_ADAPTERS.md, DESKTOP_SKILL_LAUNCHERS.md]
can_parallelize_with: []
---

# Promotion And Traceability

## Purpose

Convert mature inquiry output into an executable Issue only through an explicit authority crossing.

## What This Task Does

Implement a readiness evaluator, PromotionIntent record, REST-only GitHub Issue creation, and a
trace graph from inquiry through Issue, PR, verification, and owner-document references.

## Concretely

```bash
scripts/builderops_cli.sh builderops inquiry evaluate inq_20260709_example --json
scripts/builderops_cli.sh builderops inquiry promote inq_20260709_example --create-issue --json
scripts/builderops_cli.sh builderops inquiry trace inq_20260709_example --include-delivery --json
```

The accepted model response carries a strict `builderops.model-inquiry-issue-proposal.v1` JSON
string with `title` and `body`. Evaluation validates that exact body against the canonical Issue
section contract, per-criterion `Verify:` markers, source-anchor resolution, consensus lineage, and
empty final blocking questions. A preterminal evaluation is read-only and fails loudly, so it cannot
freeze an in-progress inquiry. After a terminal run, the evaluator persists `issue_ready`,
`needs_input`, or `not_ready` in `readiness.json` plus a hash-bound readiness terminal receipt.
Evaluation is local and requires no GitHub repository or credentials; repository identity becomes
mandatory only at the explicit `promote --create-issue` authority crossing.

Promotion persists an immutable, file-first `PromotionIntent` beside the inquiry before any remote
call. The Issue body contains a deterministic marker derived from the target repository and
immutable readiness/synthesis/title/body material. Retry scans the repository through REST for that
exact marker before creation; a single match is reconciled, multiple matches or a truncated scan
fail closed. The same-host promotion lock prevents concurrent local creates. GitHub has no Issue
idempotency key, so cross-host simultaneous search-before-create remains advisory; duplicate marker
detection makes that limitation visible instead of selecting a winner.

The production client invokes only `gh api` REST endpoints with argv execution and JSON on stdin.
It never calls GraphQL, Project v2, `gh issue`, or a shell. Set `BUILDEROPS_GITHUB_REPOSITORY` to
`owner/name` or pass `--repository owner/name`. The v1 receipt contract binds canonical
`https://github.com/<owner>/<repo>/issues/<number>` URLs; GitHub Enterprise hosts are unsupported
until host identity becomes an explicit configuration and receipt field.

## Why This Matters

Model consensus is not authority. The output must become a bounded Issue with explicit acceptance
criteria and source anchors before any implementation agent can claim it.

## Acceptance Criteria

- [x] Promotion refuses inquiries with blocking questions, disagreement, missing source anchors, or
  absent readiness receipt. Verify: `tests/builderops/test_model_inquiry_promotion.py::test_issue_promotion_requires_ready_receipt`.
- [x] Successful promotion creates a canonical Issue contract through GitHub REST and records the
  Issue reference in a BuilderOps receipt. Verify: `tests/builderops/test_model_inquiry_promotion.py::test_promote_creates_issue_and_receipt`.
- [x] If GitHub creates an Issue before local receipt persistence fails, retry reconciles the same
  Issue using a deterministic promotion marker and creates no duplicate. Verify:
  `tests/builderops/test_model_inquiry_promotion.py::test_retry_reconciles_issue_after_receipt_failure`.
- [x] Trace output links an inquiry to its Issue, implementation PR, verification receipt, and owner
  documents when those refs exist. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_includes_delivery_refs`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_promotion.py tests/builderops/test_model_inquiry_trace.py`
- GitHub REST integration test with an isolated fixture repository or recorded client.

## Out of Scope

- automatic PR creation, merge, or owner-document mutation;
- GitHub Project v2 or GraphQL hot-path operations.

## Durable Layout

BMI-05 adds these immutable files under
`$BUILDEROPS_VAULT_ROOT/model-inquiries/<inquiry_id>/`:

- `promotion-intent.json` — exact repository, title, marked Issue body, readiness/synthesis hashes,
  and source refs, persisted before REST;
- `receipts/readiness-terminal.json` — binds the terminal `issue_ready`, `needs_input`, or
  `not_ready` result to the readiness artifact and its exact input artifact hashes;
- `receipts/promotion-github-issue.json` — binds the PromotionIntent hash and deterministic marker
  to the created/reconciled Issue;
- `receipts/delivery-<ref-hash>.json` — append-only PR, verification-receipt, and owner-doc links.

SQLite remains local and is not the durable promotion authority for model inquiries. The generic
BuilderOps PromotionGateway remains proposal-only; this specialized gateway is the explicit
`--create-issue` crossing governed by the stronger inquiry evidence contract.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`
- `.codex/skills/issue-to-code/SKILL.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3293](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3293)
