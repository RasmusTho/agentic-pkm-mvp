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
scripts/builderops_cli.sh builderops inquiry promote inq_20260709_example --create-issue --json
scripts/builderops_cli.sh builderops inquiry trace inq_20260709_example --include-delivery --json
```

## Why This Matters

Model consensus is not authority. The output must become a bounded Issue with explicit acceptance
criteria and source anchors before any implementation agent can claim it.

## Acceptance Criteria

- [ ] Promotion refuses inquiries with blocking questions, disagreement, missing source anchors, or
  absent readiness receipt. Verify: `tests/builderops/test_model_inquiry_promotion.py::test_issue_promotion_requires_ready_receipt`.
- [ ] Successful promotion creates a canonical Issue contract through GitHub REST and records the
  Issue reference in a BuilderOps receipt. Verify: `tests/builderops/test_model_inquiry_promotion.py::test_promote_creates_issue_and_receipt`.
- [ ] If GitHub creates an Issue before local receipt persistence fails, retry reconciles the same
  Issue using a deterministic promotion marker and creates no duplicate. Verify:
  `tests/builderops/test_model_inquiry_promotion.py::test_retry_reconciles_issue_after_receipt_failure`.
- [ ] Trace output links an inquiry to its Issue, implementation PR, verification receipt, and owner
  documents when those refs exist. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_includes_delivery_refs`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_promotion.py tests/builderops/test_model_inquiry_trace.py`
- GitHub REST integration test with an isolated fixture repository or recorded client.

## Out of Scope

- automatic PR creation, merge, or owner-document mutation;
- GitHub Project v2 or GraphQL hot-path operations.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`
- `.codex/skills/issue-to-code/SKILL.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3293](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3293)
