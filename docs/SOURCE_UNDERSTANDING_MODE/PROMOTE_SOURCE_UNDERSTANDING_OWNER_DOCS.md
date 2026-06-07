---
name: Promote Source Understanding Owner Docs
description: Promote delivered Source Understanding truth into owner docs and close #1646 after child validation receipts are complete.
task_id: SUMODE-CLOSE
state: blocked-final-closure
issue: 1687
source_anchor: GitHub Issue #1646 :: Done condition
parent_capability: SOURCE_UNDERSTANDING_MODE
prerequisites: [SUMODE-P0, SUMODE-HANDOFF, SUMODE-P1, SUMODE-P2]
depends_on: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md, CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md, EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md, EXTEND_INTEGRATION_AND_ACTION_LENSES.md]
can_parallelize_with: []
---

# Promote Source Understanding Owner Docs

## Purpose

Owner docs should claim Source Understanding support only after the child slices have shipped and validation receipts prove the supported truth. This task reconciles docs, issue state, and remaining target-state work before closing #1646.

## What This Task Does

Update the relevant owner docs to distinguish shipped Source Understanding support from remaining target-state work, then close the parent validation hub with receipts.

## Concretely

- Review all #1646 child receipts and merged PRs.
- Update owner docs that now claim supported Source Understanding behavior.
- Keep unsupported lenses, broad research automation, citation-manager behavior, and automatic note promotion in target-state or out-of-scope language.
- Record that #1638 is related cognitive-load work, not the #1646 parent.
- Close #1646 only after the acceptance checklist is complete.

## Why This Matters

Premature owner-doc promotion would make the repo claim source-comprehension support that may not exist or may not preserve authority. The final closure issue keeps repo truth aligned with delivered behavior.

## Acceptance Criteria

- [ ] Owner docs identify the shipped Source Understanding surface, input scope, packet lenses, authority posture, and degraded states. Verify: doc writeback at `docs/HUMAN-FLOWS.md :: Source -> interpret -> stabilize` or the more local owner doc selected by delivered implementation.
- [ ] Owner docs distinguish shipped support from remaining target-state lenses and automation. Verify: `rg -n "Source Understanding|source understanding|Concept|Critique|Integration|Action" docs companion-ui/docs`.
- [ ] Docs state that understanding packets are non-authoritative projections and do not mutate canonical artifacts or hidden memory. Verify: `rg -n "non-authoritative.*Source Understanding|understanding projection|hidden memory" docs companion-ui/docs`.
- [ ] #1646 body is updated with all child receipts and final acceptance status. Verify: GitHub issue #1646 body and closure comment.
- [ ] #1646 closes only after #1647 and every created child issue are delivered or explicitly superseded by a documented parent decision. Verify: GitHub issue state and child issue links.

## How to Verify (Pre-Merge)

Local:

- `git diff --check`
- `python3 scripts/docs_guard.py`
- issue-specific `rg` checks listed in Acceptance Criteria

Post-merge:

- Post a final validation receipt to #1646 with child issue/PR links, validation evidence, owner-doc paths, and remaining target-state follow-ups.
- Close #1646 only when the parent acceptance checklist is complete.

## Out of Scope

- Implementing new Source Understanding runtime behavior.
- Creating new child implementation work unless closure discovers a concrete missing acceptance item.
- Closing #1638 or changing the cognitive-load runtime adoption parent.
- Reclassifying #1647 as a #1638 child.

## Related Docs

- Parent: [README.md](README.md), [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- `docs/HUMAN-FLOWS.md`
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md`
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md`

## Related GitHub Issues

GitHub Issue #1687. It must remain `agent:blocked` until every implementation child has delivered or been superseded by an explicit parent validation decision.
