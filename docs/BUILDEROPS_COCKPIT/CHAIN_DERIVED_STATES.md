---
name: Chain-Derived States
description: Derive the five thread states as positions in the process chain, deficiency types as chain predicates, and within-band ordering
task_id: BOPS-COCKPIT-04
source_anchor: "docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ2 — Branching and bidirectional enumeration"
parent_capability: BuilderOps Cockpit
github_issue: 4452
prerequisites: [BOPS-COCKPIT-01, BOPS-COCKPIT-03]
depends_on: [REGISTRY_READ_TIME_JOIN.md, GITHUB_LIVE_PLANE.md]
can_parallelize_with: [DOCS_PLANE_CAPABILITY_LANES.md, COGNITIVE_LOAD_SIBLING.md]
---

# Chain-Derived States

## Purpose

The delivered banding maps dispatcher status words to bands. The owner's model is stronger: the
five thread states — in progress / delivered / tried by owner / has flaws / forgotten — are
**positions in the process chain**, and deficiency types are **derivable predicates over that
chain** rather than an enumerated list. This task replaces status-word banding with chain-position
banding, fail-closed.

## What This Task Does

- Encodes the chain-position rule over the evidence spine and the live GitHub plane:
  - *in progress* — the thread holds an active position from backlog through merge: an open ready
    slice issue (even unclaimed — the register's first question includes the queue), a claimed
    lease, an open PR, running/pending checks. An unclaimed ready issue stays here until it meets
    the forgotten stall condition below
  - *delivered* — merged with terminal verification, through deploy where applicable
  - *tried by owner* — reserved: renders only when an owner-acceptance receipt exists (INV-DG-7;
    empty-by-contract until then)
  - *has flaws* — some link is missing its next link or its verification (predicates below)
  - *forgotten* — the chain has stalled without closure: no movement in the thread's own authority
    for the threshold window **and** no terminal state (decision Q1: age alone never suffices)
- Derives deficiency predicates computable from the joined planes, each rendered as a named flaw on
  the card (a thread may hold a position *and* carry flaws — same id, both bands, no duplicated
  truth):
  - a pushed branch with no PR (from the branch list BOPS-COCKPIT-03 reads)
  - a PR no CI has touched, or with red CI on its head SHA
  - a merged/delivered thread without a verification receipt
  - an expired dispatcher lease (someone stopped mid-work)
  - an epic whose children are not closed and which nothing has touched in the window
  - a delivered thread never tried (visible via the empty tried tier, not a red mark — delivered
    posture from #4438 stays)
  - a dispatcher task and GitHub state that contradict each other (sync divergence rendered as a
    flaw, not silently reconciled)
- Predicates that need planes v1 does not read are **named as unread** in the flaws band header —
  absence made visible, per the design's honesty idiom, not silently omitted. The named-as-unread
  set at this task's landing: unpushed local worktrees (plane: git working trees), unlanded
  session insight (plane: session records), and issues closed without their owner-doc writeback
  receipt (plane: issue comments — the post-merge owner-doc receipt is a comment this task does
  not fetch).
- Enacts the stale-source consequence on the spine (see
  `README.md :: Cross-Task Invariants / Interaction Safety`): a rung whose evidence depends on a
  stale source renders amber, and counts owned by that source are withdrawn rather than shown
  whole.
- Within-band ordering: risk/urgency orders cards strictly *within* a band (EXT-7 as accepted:
  four ticks maximum, no scalar displayed, never a selection input per ADR-0057 A1, never
  cross-band, and no ordering ever hides a card). Band order itself stays locked.
- `why_now` per card becomes the gate's own phrasing (which predicate fired), never a score.

## Concretely

```
curl -s localhost:18001/api/cockpit/registry | jq '.bands[] | select(.key=="flawed") | .items[0].flaws'
```

Expected: named predicates with their evidence keys (PR number, SHA, lease id), not status words.

## Why This Matters

Status-word banding inherits whatever the dispatcher store believes; chain-position banding is
derived from the authorities themselves and stays correct when the store lags. Deficiency-as-
predicate is what makes the flaws band complete-by-construction instead of complete-by-enumeration
— a new flaw type is a new predicate over existing keys, not a new writer.

## Acceptance Criteria

- [ ] Banding derives from chain position over joined planes, fail-closed: a thread whose position
      cannot be computed lands in the explicit unclassified list, never in a band
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_unresolvable_position_is_unclassified_not_guessed`
    (enforcement AC: drives `build_registry` end to end with contradictory plane fixtures)
- [ ] Each deficiency predicate fires on a fixture reproducing its real-world shape and renders as
      a named flaw with evidence keys
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_each_flaw_predicate_fires_with_evidence`
- [ ] A thread can hold a working position and carry flaws simultaneously — one identity, two
      bands, no copy drift
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_dual_band_single_identity`
- [ ] Forgotten requires stalled-without-closure (age + no authority movement), not age alone
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_forgotten_needs_stall_not_age`
- [ ] Ordering applies only within a band; no ordering removes or hides a card
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_ordering_never_crosses_bands_or_hides`
- [ ] Unreadable-plane predicates are named as unread in the flaws band header
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_unread_flaw_planes_named`
- [ ] A rung depending on a stale source renders amber and the counts that source owns are
      withdrawn, not shown whole
  - Verify: `tests/builderops/test_cockpit_chain_states.py::test_stale_source_ambers_rungs_and_withdraws_counts`

## How to Verify (Pre-Merge)

`pytest tests/builderops/test_cockpit_chain_states.py tests/builderops/test_cockpit_registry.py -m "not pg"`
— existing registry tests must stay green (band order, refusal, spine contracts unchanged).

## Out of Scope

- Reading new planes (git working trees, session logs) — the corresponding predicates stay
  named-as-unread until a plane task exists.
- Any owner-acceptance receipt mechanics (INV-DG-7, owner-gated).
- Epic child-set enumeration from prose tables — the in-flight delivery-graph data-edge work owns
  the structured parent/child ledger (INV-DG-3/4); this task consumes whatever machine edge exists
  and renders prose-only edges as `derived` rungs, honestly weaker.
- Any TCD arithmetic beyond within-band ordering; any interruption-cost formula.

## Restart / Durability Posture

Chain positions, flaw predicates, why-now phrasing, and within-band ordering are recomputed per
render from the joined planes; nothing survives a reload or restart. The user consequence is a
fresh re-derivation on every load — a flaw that was fixed in the authority disappears at the next
render, and no cockpit-local memory can contradict GitHub.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q1, Q2, EXT-7`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md` (RQ1 key classes, F2, F4)
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` (A1: signal to read, never selection)

## Related GitHub Issues

One bounded issue. Reference "Implements BUILDEROPS_COCKPIT/CHAIN_DERIVED_STATES". Blocked until
the GitHub live plane merges; coordinates with the data-edge issues for INV-DG-3/4 (consume, don't
duplicate).
