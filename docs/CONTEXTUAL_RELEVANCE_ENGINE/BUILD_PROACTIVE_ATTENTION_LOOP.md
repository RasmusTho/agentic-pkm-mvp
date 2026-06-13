---
name: Build the Proactive Attention Loop
description: The new seam — a trigger evaluator that proactively reaches out via the graduated ladder, gated by the context-dependent interruption threshold, plus user-declared patterns.
task_id: CRE-04
source_anchor: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md :: 7. Slicing direction (2)(3)
parent_capability: Contextual Relevance Engine
prerequisites: [CRE-01, CRE-02, CRE-03]
depends_on: [BUILD_VAULT_NATIVE_PULL_MOMENTS.md]
can_parallelize_with: []
---

# Build the Proactive Attention Loop

## Purpose

Add the genuinely new dimension: **proactivity**. A quiet loop watches the context model and decides
*"now is the moment for X,"* then reaches out — but only as far up the intrusiveness ladder as the
current interruption threshold allows. Includes **user-declared patterns**; the emergent/learned loop
is an explicit follow-on, not this task.

## What This Task Does

- Implements the **trigger evaluator**: on a context tick, evaluates candidate moments (from CRE-03)
  for proactive surfacing.
- Implements the **reach-out ladder + scarcity gate** from CRE-02: a moment fires a reach-out only
  when its urgency clears the **current context-dependent interruption threshold**; at the
  **zero-tolerance floor** (sleep / declared DND) nothing pushes; suppressed moments **defer down the
  ladder** (re-attempt at the glance surface) rather than drop.
- Implements **user-declared patterns** ("when *this* context, surface *that*") as soft guidance for
  the evaluator.
- Every durable effect is governed (write guard + receipt) per the #1881 tiers; reach-out itself is
  Act/agent-review; no external side-effects in this slice.

## Concretely

With the human's declared bands (home/meeting/focus/sleep), a slipping-deadline moment surfaces as an
OS push when the human is at home (low load), as an in-app nudge when the app is open in a low-tolerance
context, and not at all during sleep — re-attempting when interruptibility rises. A receipt records
every reach-out and every deliberate suppression.

## Why This Matters

This is the capability's reason for existing — the system *bringing* the right thing rather than
waiting to be asked — and the place the cognitive-load contract is most at risk. If scarcity is wrong,
it becomes a firehose and violates `HUMAN-FLOWS` §0. The zero-tolerance floor and defer-not-drop are
the hard guarantees that keep it a prosthesis.

## Acceptance Criteria

- [ ] A moment fires a proactive reach-out only when its urgency clears the current context-dependent interruption threshold; below it, it defers (re-attempts at the glance surface) and is not dropped.
  - Verify: `tests/relevance/test_attention_loop.py::test_reachout_respects_context_threshold_and_defers`.
- [ ] At the zero-tolerance floor (sleep / declared DND) no reach-out is emitted regardless of urgency.
  - Verify: `tests/relevance/test_attention_loop.py::test_zero_tolerance_floor_never_pushes`.
- [ ] A user-declared pattern measurably changes which moments surface, and every reach-out / deliberate suppression emits a receipt; no external side-effects occur.
  - Verify: `tests/relevance/test_attention_loop.py::test_declared_pattern_changes_surfacing_with_receipts`.

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/relevance/test_attention_loop.py`
- `ruff check app tests`
- Post a validation receipt to the parent feature issue; this slice triggers the owner-doc promotion (HUMAN-FLOWS §5 + runtime map).

## Out of Scope

- The emergent/learned pattern loop (system proposes new patterns) — explicit follow-on.
- External connectors (deferred slice); any external side-effect (sending mail, booking) — that is the #1881 "ask you" tier, not this slice.

## Related Docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` (brief, §3.3, §7)
- `docs/EMERGENT_FEATURES_MODEL.md`
- `docs/HUMAN-FLOWS.md` §0, §5
- GitHub #1881 (governance tiers)

## Related GitHub Issues

Filed as `agent:blocked` (on CRE-01..03). The final child of the core chain — includes the parent
owner-doc promotion handoff (HUMAN-FLOWS §5 + runtime-map row). May split (trigger loop vs. reach-out
channels) if large.
