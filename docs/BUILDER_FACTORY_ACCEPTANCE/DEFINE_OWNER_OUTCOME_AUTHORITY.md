---
name: "Define owner outcome authority"
description: "The retained P1 on #5404 identifies an invalid use of ADR-0065 dispositions. Define a separate bounded outcome receipt contract before any producer writes trial or acceptance."
task_id: FCA-09
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: FCA-09 — Owner outcome contract repair"
parent_capability: "BUILDER_FACTORY_ACCEPTANCE"
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Task specification accepted for bounded contract repair; not yet filed or delivered. No runtime implementation or deployment is claimed.
Doc role: Target-state task specification in an existing capability directory.
Authority: Existing capability and owner documents govern the repair. This task defines work and verification, not the repaired action/data/runtime authority. Source disposition: #5399 comment 5648534770.

# Define owner outcome authority

## Purpose

The [retained P1 on #5404](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5404#issuecomment-5578318482)
identifies an invalid use of ADR-0065 dispositions. Define a separate bounded outcome receipt
contract before any producer writes trial or acceptance. Publishing this repair specification does
not resolve that review finding or admit a writer.

## What This Task Does

- Extend the existing BuilderOps receipt/object contract with the finite owner-outcome payload and authenticated writer/readback authority; do not reinterpret done/ignore/never_show_again.
- Keep trial observations (tried, unable_to_try plus observation) separate from acceptance decisions (accepted/rejected). Preserve compatibility with any already-admitted source vocabulary explicitly.
- Bind subject/repo, candidate source/image/config, environment, readiness receipt, acceptance-profile/AC version, owner actor, observation/decision times, limitations and superseded receipt.
- Specify idempotency, concurrent differing decisions, corrections/supersession and restart readback. Store no transcripts or unnecessary personal data; use the owning retention policy and identify a real policy gap if it cannot cover the bounded observation.
- Correct the DEVUI and FCA-02/object-model cross references; retain withdrawn facts until implementation and admission.

## Concretely

The owner tried candidate C in environment E and rejected AC-2. The historical decision remains attached to C when C2 becomes available.

## Why This Matters

The complete owner journey depends on this finite seam. Delivering the module or a fixture alone must not be described as live owner-platform acceptance.

## Acceptance Criteria

- [ ] Trial/decision kinds, source/writer, payload, readback and correction semantics are fully named without overloading temporal-intention dispositions. Verify: doc writeback at `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md :: Owner-fact carriers and bounded handoff (FCA-02)`
- [ ] DEVUI references the separate outcome contract and still withdraws outcomes until the admitted writer exists. Verify: doc writeback at `docs/DEVUI.md :: FCA-02 source-backed owner facts and bounded handoff (2026-09-07)`
- [ ] Changed candidate/profile, two conflicting submissions, unavailable writer and post-write projection failure are specified with exact expected outcomes. Verify: doc writeback at `docs/BUILDER_FACTORY_ACCEPTANCE/PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md :: Acceptance Criteria`

## How to Verify (Pre-Merge)

For each AC, review the named writeback anchor and its finite examples against the current source owner; all are pre-merge document targets. Run `python3 scripts/docs_guard.py --language-only`, the current diff-aware docs guard, and `git diff --check`; verify changed index rows and all source links. Validate the final Issue body before readiness. No runtime test or live acceptance pass is implied.

## Out of Scope

No temporal-intention redesign, broad privacy programme, new generic owner-fact database, code or fabricated owner decisions.

## Restart / Durability Posture

No runtime state changes in this task.

## Related Docs

- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/DEVUI.md`
- `docs/BUILDER_FACTORY_ACCEPTANCE/PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md`
- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`

## Related GitHub Issues

Parent validation: #5399. Existing related work: #5404, #5401. FCA-09 is a stable specification ID, not a filed Issue. Write `github_issue` frontmatter only after successful filing and readback. Milestone: M0.

Execution context: fresh_issue_agent; helper budget 1 for the required independent authority/mechanism review when the contract is repaired; configured Codex / high reasoning. This is a non-binding capability hint; the execution skill reclassifies the actual diff. Serial delivery is the default.
