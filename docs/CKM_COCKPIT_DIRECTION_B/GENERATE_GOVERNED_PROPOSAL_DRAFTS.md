---
name: Generate Governed Proposal Drafts
description: Render deterministic inert draft text from cited current findings without implying priority, readiness, or an Issue contract.
task_id: CKM-DB-05
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-DB-04]
depends_on: [FILTER_CAPABILITY_MAP_HONESTLY.md]
can_parallelize_with: []
---

# Generate Governed Proposal Drafts

## Purpose

Make a cited CKM finding easier for the owner to carry into the normal Issue/PR path while ensuring
the generated artifact never creates, prioritizes, or authenticates work.

## What This Task Does

- Generate at most one inert text draft per current finding that has at least one retained citation
  or source reference.
- Sort drafts by capability public ID, finding kind, dimension, statement, and stable finding ID.
- Bind every draft to the projection-input digest, CKM epoch/state revision/schema version, exact
  sorted watermarks, capability public ID, and the verbatim finding statement plus cited source
  references/lifecycles.
- Include the fixed disclaimer: `Draft only — not an Issue contract, priority, decision, or ready work.`
- Present the draft in selectable text with no button, clipboard API, GitHub URL, issue template
  prefill, closing keyword, label, assignee, priority, or network/write affordance.
- Render uncited findings as an explicit ineligible count rather than manufacturing supporting text.

## Concretely

Each eligible draft has this deterministic field order:

```text
Draft only — not an Issue contract, priority, decision, or ready work.
Projection input digest: <digest>
CKM state: epoch=<epoch>; revision=<revision>; schema=<version>
Watermarks: <key=value, sorted>
Capability public ID: <public_id>
Observed finding (verbatim): <statement>
Dimension/kind: <dimension> / <kind>
Cited source(s): <source_ref [lifecycle], sorted>
Manual review question: Does this cited finding justify a separate governed Issue?
```

No title, `Fixes`, `Closes`, `agent:ready`, priority, or recommended implementation appears.

## Why This Matters

Copyable prose can look like an approved backlog contract even when it was generated from weak or
shared evidence. Explicit identity/provenance binding and a non-decision shape preserve the
promotion boundary: a human still evaluates the finding and, if warranted, creates a new strict
Issue contract through the normal repo process.

## Acceptance Criteria

- [ ] Only current findings with at least one citation/source reference produce drafts; scores, zero dimensions, stale flags, and uncited findings alone never do.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_drafts_require_cited_current_finding`
- [ ] Every draft binds projection-input digest, full CKM state identity, exact sorted watermarks, capability public ID, verbatim finding, kind/dimension, and sorted cited sources/lifecycles.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_drafts_bind_identity_watermarks_and_verbatim_evidence`
- [ ] Draft order and bytes are deterministic for identical explicit render inputs.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_draft_order_and_text_are_deterministic`
- [ ] Every draft carries the fixed non-decision disclaimer and contains no issue-closing keyword, priority/readiness claim, label, assignee, ranking, causal diagnosis, or generated implementation direction.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_drafts_cannot_be_mistaken_for_ready_issue_contracts`
- [ ] The proposal section exposes selectable inert text only and has no clipboard, URL/prefill, fetch, form submission, or write behavior.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_drafts_are_inert_and_network_free`
- [ ] No eligible finding and uncited-finding cases render explicit empty/ineligible counts without a generic draft.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_draft_empty_and_uncited_states_are_honest`
- [ ] Filters never hide, create, reorder, or rewrite proposal drafts.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_filters_do_not_mutate_proposal_drafts`
- [ ] The implementation PR posts eligible, uncited, empty, and deterministic-regeneration receipts to the parent.
  Verify: CKM-DB-05 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Render fixtures with cited findings, uncited findings, no findings, repeated source refs, and source
  text containing Issue-like words; verify verbatim source text stays labeled and is not scanned as
  renderer-authored direction.
- Search generated cockpit markup for clipboard/network/form/GitHub-prefill affordances.

## Out of Scope

- Creating, opening, labeling, assigning, ranking, or prioritizing Issues/PRs
- Clipboard integration, GitHub URLs/prefill, network requests, or local persistence
- Turning a draft into a complete canonical Issue contract
- Drafts derived only from scores, hazard heuristics, or comparison deltas
- Automatic promotion into BuilderOps `PromotionIntent`

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `.codex/skills/_shared/ISSUE_CONTRACT.md`
- `app/builderops/ckm/overview_html.py`

## Related GitHub Issues

Live child [#4085](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4085) under parent
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) is `agent:blocked` on CKM-DB-04
[#4084](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4084). Cheapest acceptable TCD route:
**Terra/high** because the implementation is deterministic presentation work but has a high
persuasion/authority-boundary risk; escalate to Sol/high if any action, PromotionIntent, or GitHub
integration is proposed.
