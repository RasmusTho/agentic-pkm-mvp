---
name: Surface Materialized Memory In Companion
description: Surface materialized memory artifacts and recall provenance in the Companion UI, with authority posture visible.
task_id: DURABLE-MEMORY-05
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Relation to companion UI and human review
parent_capability: Durable Memory and Recall
prerequisites: [DURABLE-MEMORY-03, DURABLE-MEMORY-04]
depends_on: [MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md, ACTIVATE_GUARDED_RECALL.md]
can_parallelize_with: []
---
State: Specified. Not yet delivered. Blocked on DURABLE-MEMORY-03 and DURABLE-MEMORY-04. Lower
priority than the persistence/materialization/recall core.

# SURFACE_MATERIALIZED_MEMORY_IN_COMPANION

## Purpose

Make durable memory legible in the Companion UI: show that a promoted memory materialized as a vault
artifact, where it came from, whether it was inferred, its review state, and — when recalled — why it
surfaced and under what authority.

## What This Task Does

Extends the existing memory-review surface (`companion-ui/.../memory_review_drawer.py` and the
`/api/companion/memory/review-queue` path) and the vault/workspace views so that:

- a materialized memory artifact is identifiable as agent-promoted (provenance, source links,
  decided_by) rather than human-authored;
- recall provenance from DURABLE-MEMORY-04 (why-now, authority limits, receipt reference) is
  viewable where recalled memory influences an answer/orientation/proposal;
- the authority posture is explicit ("Unreviewed memory is not semantic authority"), consistent with
  the existing review-drawer posture callout.

The UI remains a support surface: it displays provenance and posture, it does not classify
candidate-worthiness locally or treat a surfaced item as recalled authority.

## Concretely

```
Companion shows, for a recalled/materialized memory:
  - source: <vault note / candidate id>
  - inferred: true|false
  - review state: promoted (decided_by, decided_at)
  - why now: <recall explanation>
  - authority: may_answer / may_propose / may_write=false
```

## Why This Matters

Durable, materialized memory and guarded recall are only trustworthy if the human can see what the
system remembered, where it came from, and what authority it carries. This task delivers the
visibility half of the agent-memory contract's companion-UI requirements.

## Acceptance Criteria

- [ ] The companion surface marks a materialized memory artifact as agent-promoted with provenance,
  distinct from human-authored notes.
  Verify: `tests/companion_ui/test_materialized_memory_surface.py::test_materialized_memory_shows_provenance_and_agent_label`
- [ ] Recall provenance (why-now, authority limits, receipt reference) is rendered where recalled
  memory is shown.
  Verify: `tests/companion_ui/test_materialized_memory_surface.py::test_recall_provenance_is_rendered`
- [ ] The authority posture is shown and unreviewed memory is not presented as semantic authority.
  Verify: `tests/companion_ui/test_materialized_memory_surface.py::test_unreviewed_memory_posture_visible`

## How to Verify (Pre-Merge)

- Add the named render tests (pure render-function assertions, consistent with the companion-ui test
  style — no live HTTP/DB).
- Assert provenance fields and authority posture appear in the rendered output.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_materialized_memory_surface.py`

## Out of Scope

- The materialization write path (DURABLE-MEMORY-03) and recall seam (DURABLE-MEMORY-04).
- New authority semantics (UI reflects posture; it does not define it).
- Browser/Playwright runtime tests (optional, separate marker).

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py`

## Related GitHub Issues

- Parent feature: Durable Memory and Recall (see PARENT_FEATURE_ISSUE.md).
- Blocked on DURABLE-MEMORY-03 and DURABLE-MEMORY-04.
